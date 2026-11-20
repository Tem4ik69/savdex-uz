"""
Маркетплейс на своём адресе (savdex/market/domain.py): MARKET_DOMAIN.

- домен и имя куки сессии: общий домен сайта и маркетплейса, имя с
  окружением; без MARKET_DOMAIN — как было;
- на адресе маркетплейса страницы — с корня, старый вид /market/… —
  переход на корневой, вход и JSON — как есть, чужие страницы — на
  основной адрес;
- на основном адресе страницы /market/… — переход на адрес маркетплейса;
- один вход: сессия, начатая на основном адресе, видна на маркетплейсе.

Адрес сайта в проверках — http://127.0.0.1:<порт>, адрес маркетплейса —
market.127.0.0.1. Нужен PostgreSQL (SAVDEX_PARITY_PG_URL) — кроме первых
проверок.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from savdex import laravel_session
from savdex.market import domain

from .pg_admin import нужна_база, свежая_база
from .web_site import адрес, завести, кука, открыть, страница

# ── Без базы: домен и имя куки ──────────────────────────────────────


@pytest.fixture
def окружение(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name in ("SESSION_DOMAIN", "SESSION_COOKIE", "MARKET_DOMAIN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("APP_NAME", "SAVDEX")

    return monkeypatch


@pytest.mark.parametrize(
    ("app_url", "market", "домен"),
    [
        ("https://savdex.uz", "market.savdex.uz", ".savdex.uz"),
        ("https://staging.savdex.uz", "market.staging.savdex.uz", ".staging.savdex.uz"),
        ("https://savdex.uz", "https://Market.Savdex.uz/", ".savdex.uz"),
        # Маркетплейс не под основным адресом — общей куки не бывает
        ("https://savdex.uz", "savdex-market.uz", None),
        ("https://savdex.uz", "", None),
        ("https://preview.savdex.uz", "market.staging.savdex.uz", None),
    ],
)
def test_домен_куки_по_адресу_маркетплейса(окружение, app_url, market, домен):
    окружение.setenv("APP_URL", app_url)
    окружение.setenv("MARKET_DOMAIN", market)

    assert laravel_session.session_domain() == домен


def test_имя_куки_с_окружением_только_у_общей(окружение):
    окружение.setenv("APP_URL", "https://staging.savdex.uz")
    окружение.setenv("APP_ENV", "staging")

    assert laravel_session.cookie_name() == "savdex-session", "без маркетплейса — как было"

    окружение.setenv("MARKET_DOMAIN", "market.staging.savdex.uz")
    assert laravel_session.cookie_name() == "savdex-staging-session"

    окружение.setenv("APP_ENV", "production")
    окружение.setenv("APP_URL", "https://savdex.uz")
    окружение.setenv("MARKET_DOMAIN", "market.savdex.uz")
    assert laravel_session.cookie_name() == "savdex-production-session"

    # Заданное явно — главнее
    окружение.setenv("SESSION_COOKIE", "sid")
    assert laravel_session.cookie_name() == "sid"
    окружение.delenv("SESSION_COOKIE")
    окружение.setenv("SESSION_DOMAIN", ".example.uz")
    assert laravel_session.session_domain() == ".example.uz"


def test_адрес_маркетплейса_из_переменной(окружение):
    окружение.setenv("APP_URL", "https://savdex.uz")
    assert domain.market_host() is None and domain.market_url() is None

    окружение.setenv("MARKET_DOMAIN", " HTTPS://Market.Savdex.uz:443/ ")
    assert domain.market_host() == "market.savdex.uz"
    assert domain.market_url("/catalog") == "https://market.savdex.uz/catalog"


# ── Сайт ────────────────────────────────────────────────────────────

РЫНОК = "market.127.0.0.1"


@pytest.fixture(scope="module")
def сайт() -> Iterator[str]:
    свежая_база()

    with адрес() as root:
        yield root


def _env(сайт: str) -> dict[str, str]:
    host = сайт.removeprefix("http://").rsplit(":", 1)[0]

    return {"MARKET_DOMAIN": РЫНОК, "DJANGO_ALLOWED_HOSTS": f"{host},{РЫНОК}"}


def _на_рынке(сайт: str, path: str, **запрос: Any) -> dict[str, Any]:
    return открыть(сайт, path, headers={"Host": РЫНОК}, env=_env(сайт), **запрос)


@нужна_база
@pytest.mark.parametrize(
    ("path", "component"),
    [
        ("/", "market/Home"),
        ("/uz", "market/Home"),
        ("/catalog", "market/Catalog"),
        ("/en/catalog", "market/Catalog"),
        ("/product/smartfon-nova-x5-256", "market/Product"),
        ("/cart", "market/Cart"),
        ("/tr/sell", "market/Sell"),
        ("/shop/technomir", "market/Shop"),
    ],
)
def test_страницы_с_корня(сайт, path, component):
    ответ = _на_рынке(сайт, path)

    assert ответ["status"] == 200, ответ["body"][:500]
    page = страница(ответ["body"])
    assert page["component"] == component
    # Адрес страницы — корневой, а не внутренний /market/…
    assert "/market" not in page["url"]
    assert page["props"]["marketLinks"]["base"] == ""
    assert page["props"]["marketLinks"]["market"] == f"http://{РЫНОК}"


@нужна_база
def test_каталог_с_корня_берёт_параметры(сайт):
    page = страница(_на_рынке(сайт, "/catalog?q=%20казан%20&sort=cheap&utm=x")["body"])

    assert page["props"]["query"] == {"q": "казан", "sort": "cheap"}


@нужна_база
@pytest.mark.parametrize(
    ("path", "куда"),
    [
        ("/market", "/"),
        ("/market/catalog?q=a", "/catalog?q=a"),
        ("/uz/market", "/uz"),
        ("/uz/market/cart", "/uz/cart"),
    ],
)
def test_старый_вид_адреса_на_корневой(сайт, path, куда):
    ответ = _на_рынке(сайт, path)

    assert ответ["status"] == 302
    assert ответ["headers"]["location"] == куда


@нужна_база
def test_чужие_страницы_на_основной_адрес(сайт):
    ответ = _на_рынке(сайт, "/companies?page=2")

    assert ответ["status"] == 302
    assert ответ["headers"]["location"] == f"{сайт}/companies?page=2"


@нужна_база
def test_вход_и_json_работают_как_есть(сайт):
    assert _на_рынке(сайт, "/login")["status"] == 200
    категории = _на_рынке(сайт, "/market/api/categories")

    assert категории["status"] == 200
    assert '"categories"' in категории["body"]


@нужна_база
def test_основной_адрес_ведёт_на_маркетплейс(сайт):
    ответ = открыть(сайт, "/uz/market/catalog?q=a", env=_env(сайт))

    assert ответ["status"] == 302
    assert ответ["headers"]["location"] == f"http://{РЫНОК}/uz/catalog?q=a"

    # JSON на основном адресе — как есть
    assert открыть(сайт, "/market/api/categories", env=_env(сайт))["status"] == 200


@нужна_база
def test_ссылки_inertia_между_адресами(сайт):
    # Ссылка Inertia — фоновый запрос: на чужой домен браузер его не пустит,
    # поэтому вместо 302 — 409 и X-Inertia-Location (Inertia сам откроет адрес)
    inertia = {"X-Inertia": "true", "X-Requested-With": "XMLHttpRequest"}

    туда = открыть(сайт, "/uz/market/catalog?q=a", headers=inertia, env=_env(сайт))
    assert туда["status"] == 409
    assert туда["headers"]["x-inertia-location"] == f"http://{РЫНОК}/uz/catalog?q=a"

    рынок = {"Host": РЫНОК, **inertia}
    обратно = открыть(сайт, "/companies?page=2", headers=рынок, env=_env(сайт))
    assert обратно["status"] == 409
    assert обратно["headers"]["x-inertia-location"] == f"{сайт}/companies?page=2"

    # Внутри одного адреса — обычный 302: его Inertia проходит сам
    свой = открыть(сайт, "/market/catalog", headers=рынок, env=_env(сайт))
    assert свой["status"] == 302 and свой["headers"]["location"] == "/catalog"


@нужна_база
def test_без_переменной_всё_как_было(сайт):
    page = страница(открыть(сайт, "/market/catalog")["body"])

    assert page["component"] == "market/Catalog"
    assert page["props"]["marketLinks"] == {"base": "/market", "site": сайт, "market": None}


@нужна_база
def test_один_вход_на_двух_адресах(сайт):
    """Сессия с основного адреса видна на маркетплейсе; кука — на общий домен."""
    from .web_site import пользователь

    uid = пользователь("both-hosts@example.com")
    имя = "savdex-local-session"
    sid = "M" * 40
    завести(sid, {"_token": "t" * 40, laravel_session.LOGIN_KEY: uid}, user_id=uid)

    ответ = открыть(
        сайт, "/", cookies={имя: кука(имя, sid)}, headers={"Host": РЫНОК}, env=_env(сайт)
    )

    assert ответ["status"] == 200
    assert страница(ответ["body"])["props"]["auth"]["user"]["id"] == uid
    assert ответ["cookies"][имя]["domain"] == ".127.0.0.1"
    # Токен формы — кука своего адреса: у тестового и боевого он не смешается
    assert "domain" not in ответ["cookies"]["XSRF-TOKEN"]
