"""
Маркетплейс: страницы (savdex/web/market.py).

Сервер отдаёт страницу и то, что нужно до загрузки данных; сами данные
страница берёт запросами к /market/api/… (проверки — test_market.py).
Здесь проверяется, что адреса открываются на всех языках, что каталог
передаёт странице строку отбора, а кабинет продавца знает свои вкладки,
и что до запуска страницы закрыты от поисковиков и не открываются на
боевом.

Нужен PostgreSQL (SAVDEX_PARITY_PG_URL); общая часть — в web_site.py.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from .pg_admin import нужна_база, свежая_база
from .web_site import адрес, открыть, страница

pytestmark = нужна_база


@pytest.fixture(scope="module")
def сайт() -> Iterator[str]:
    свежая_база()

    with адрес() as root:
        yield root


@pytest.mark.parametrize(
    ("path", "component"),
    [
        ("/market", "market/Home"),
        ("/uz/market", "market/Home"),
        ("/market/catalog", "market/Catalog"),
        ("/en/market/catalog", "market/Catalog"),
        ("/market/product/kazan-chugunnyj-12l", "market/Product"),
        ("/market/cart", "market/Cart"),
        ("/market/checkout", "market/Checkout"),
        ("/market/orders", "market/Orders"),
        ("/market/shop/technomir", "market/Shop"),
        ("/tr/market/sell", "market/Sell"),
        ("/market/seller", "market/Seller"),
    ],
)
def test_страницы_открываются(сайт, path, component):
    д = открыть(сайт, path)

    assert д["status"] == 200
    assert страница(д["body"])["component"] == component
    # До запуска страницы в поиск не попадают
    assert "noindex" in д["body"]


def test_каталог_передаёт_странице_строку_отбора(сайт):
    д = открыть(сайт, "/market/catalog?category=home&sort=cheap&attr.color=red,blue&page=2")

    assert страница(д["body"])["props"]["search"] == (
        "category=home&sort=cheap&attr.color=red,blue&page=2"
    )


def test_каталог_не_пускает_бесконечную_строку_отбора(сайт):
    д = открыть(сайт, "/market/catalog?q=" + "a" * 5000)

    assert len(страница(д["body"])["props"]["search"]) == 2000


def test_товар_получает_свой_адрес(сайт):
    д = открыть(сайт, "/market/product/smartfon-nova-x5-256")

    assert страница(д["body"])["props"]["slug"] == "smartfon-nova-x5-256"


def test_кривой_адрес_товара_не_открывается(сайт):
    assert открыть(сайт, "/market/product/Товар!")["status"] == 404


@pytest.mark.parametrize(
    ("адрес_вкладки", "вкладка"),
    [("", "products"), ("?tab=stock", "stock"), ("?tab=чужая", "products")],
)
def test_кабинет_продавца_знает_только_свои_вкладки(сайт, адрес_вкладки, вкладка):
    д = открыть(сайт, "/market/seller" + адрес_вкладки)

    assert страница(д["body"])["props"]["tab"] == вкладка


def test_на_боевом_демо_не_открывается(сайт):
    д = открыть(сайт, "/market", env={"APP_ENV": "production", "DJANGO_ALLOWED_HOSTS": "*"})

    assert д["status"] == 404


@pytest.mark.parametrize(
    "path",
    [
        "/market/api/catalog",
        "/market/api/categories",
        "/market/api/me/seller",
        "/uz/market/api/cart",
    ],
)
def test_на_боевом_json_маркетплейса_закрыт(сайт, path):
    боевой = {"APP_ENV": "production", "DJANGO_ALLOWED_HOSTS": "*"}
    д = открыть(сайт, path, headers={"Accept": "application/json"}, env=боевой)

    assert д["status"] == 404


@pytest.mark.parametrize(
    ("окружение", "открыт"),
    [
        ("local", True),
        ("testing", True),
        ("staging", True),
        (" Staging ", True),
        ("production", False),
        ("prod", False),
        ("Production", False),
        ("", False),
    ],
)
def test_маркетплейс_открыт_только_явно(monkeypatch, окружение, открыт):
    from savdex import demo
    from savdex.web.shared import market_open

    monkeypatch.setenv("APP_ENV", окружение)

    assert market_open() is открыт
    assert (demo.refused() is None) is открыт


def test_пункт_в_шапке_есть_везде_кроме_боевого(сайт):
    assert страница(открыть(сайт, "/about")["body"])["props"]["market"] is True

    боевой = открыть(сайт, "/about", env={"APP_ENV": "production", "DJANGO_ALLOWED_HOSTS": "*"})

    assert страница(боевой["body"])["props"]["market"] is False
