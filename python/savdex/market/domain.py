"""
Маркетплейс на своём адресе (ТЗ 18.11, раздел 3): market.savdex.uz, на
тестовом — market.staging.savdex.uz. Адрес приходит в переменной
MARKET_DOMAIN (её пишут deploy.sh и prod-app.sh — deploy/README.md,
«Маркетплейс — свой адрес»). Нет переменной — всё как раньше: маркетплейс
только по адресам /market/… основного сайта.

На адресе маркетплейса (MarketHostMiddleware):

- страницы — с корня: «/» — главная маркетплейса, «/catalog» — каталог,
  «/product/<адрес>» — товар, «/uz/cart» — корзина по-узбекски. Внутри это
  те же виды /market/… (savdex/web/market.py): путь подменяется только для
  поиска маршрута, а адрес страницы, ссылки на языки и «вернуться после
  входа» остаются корневыми;
- старый вид адреса /market/… — переход на корневой (302);
- вход, регистрация, сброс пароля, язык, файлы и служебное — как есть: сессия
  общая, войти можно на любом из двух адресов;
- JSON /market/api/… — как есть, на обоих адресах (страницы шлют запросы
  относительным адресом);
- прочие страницы основного сайта — переход на основной адрес (302), чтобы
  каталог объявлений или карточки компаний не жили вторым экземпляром.

На основном адресе страницы /market/… переходят на адрес маркетплейса.

Общий вход: кука сессии — на общий домен обоих адресов (savdex.uz и
market.savdex.uz → .savdex.uz) — laravel_session.session_domain(). Имя
такой куки — с окружением (savdex-staging-session), чтобы кука боевого
(.savdex.uz) не смешивалась с кукой тестового на его адресах.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from urllib.parse import urlsplit

from django.http import HttpRequest, HttpResponse, HttpResponseNotFound, HttpResponseRedirect
from django.urls import Resolver404, resolve

from savdex.web import locales

#: Префикс страниц маркетплейса на основном адресе
PREFIX = "/market"

#: Что на адресе маркетплейса работает как есть — первый сегмент пути (без
#: языка): вход и регистрация (сессия общая), язык, файлы, картинки
#: соцсетей, служебное и статика админки (сама админка — нет, _ADMIN ниже)
_PASS = frozenset(
    {
        "login",
        "logout",
        "register",
        "forgot-password",
        "reset-password",
        "password",
        "verify-email",
        "email",
        "captcha",
        "locale",
        "onboarding",
        "files",
        "og",
        "robots.txt",
        "up",
        "py",
        "build",
        "static",
        "storage",
        "images",
        "favicon.ico",
    }
)

#: Админка и вход в неё (пропуск из bridge) — только на основном адресе:
#: на адресе маркетплейса их нет, переход на основной адрес. Иначе куки и
#: формы админки жили бы ещё на одном адресе, рядом со страницами
#: маркетплейса. Статика (/py/static) и проверка (/py/up) — как есть
_ADMIN = ("/py/admin", "/py/login", "/py/logout")


def _is_admin(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix + "/") for prefix in _ADMIN)


def market_host() -> str | None:
    """Адрес маркетплейса из MARKET_DOMAIN: только имя хоста, в нижнем регистре."""
    value = (os.environ.get("MARKET_DOMAIN") or "").strip().lower()

    if not value:
        return None

    host = urlsplit(value if "//" in value else f"//{value}").hostname

    return host or None


def site_host() -> str:
    """Основной адрес — хост из APP_URL."""
    return (urlsplit(os.environ.get("APP_URL", "")).hostname or "").lower()


def _scheme() -> str:
    return urlsplit(os.environ.get("APP_URL", "")).scheme or "https"


def market_url(path: str = "/") -> str | None:
    """Полный адрес на маркетплейсе: https://market.savdex.uz/catalog."""
    host = market_host()

    return f"{_scheme()}://{host}{path}" if host else None


def _host(request: HttpRequest) -> str:
    return request.get_host().rsplit(":", 1)[0].lower()


def on_market(request: HttpRequest) -> bool:
    """Запрос пришёл на адрес маркетплейса."""
    host = market_host()

    return host is not None and _host(request) == host


def _query(request: HttpRequest) -> str:
    query = request.META.get("QUERY_STRING", "")

    return f"?{query}" if query else ""


def _is_market_page(path: str) -> bool:
    """Страница маркетплейса (не JSON): /market или /market/…, кроме /market/api/…"""
    return path == PREFIX or (
        path.startswith(PREFIX + "/") and not path.startswith(PREFIX + "/api")
    )


def _resolves_to_market(path: str) -> bool:
    try:
        match = resolve(path)
    except Resolver404:
        return False

    return (match.url_name or "").startswith("market")


def _away(request: HttpRequest, url: str) -> HttpResponse:
    """
    Переход на другой адрес (основной ↔ маркетплейс). Ссылку Inertia
    (запрос с X-Inertia) браузер не пустит фоновым запросом на чужой домен —
    клик молча ничего не делает. Inertia ждёт для этого 409 с
    X-Inertia-Location и сам открывает адрес обычным переходом.
    """
    if request.headers.get("X-Inertia"):
        response = HttpResponse("", status=409)
        response["X-Inertia-Location"] = url

        return response

    return HttpResponseRedirect(url)


class MarketHostMiddleware:
    """Адрес маркетплейса: страницы с корня, остальное — на основной адрес."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        host = market_host()

        if host is None:
            return self.get_response(request)

        reading = request.method in ("GET", "HEAD")
        locale, path = locales.split(request.path)
        lang = f"/{locale}" if locale else ""

        if _host(request) == host:
            first = path.lstrip("/").split("/", 1)[0]

            if _is_admin(path):
                site = os.environ.get("APP_URL", "").rstrip("/")

                if reading and site:
                    return HttpResponseRedirect(f"{site}{request.path}{_query(request)}")

                # Отправка формы (вход по пропуску, сохранение) сюда не
                # приходит со страниц основного адреса — не обслуживается
                return HttpResponseNotFound()

            # Старый вид адреса — на корневой
            if reading and _is_market_page(path):
                rest = path[len(PREFIX) :] or ("" if lang else "/")
                # Один ведущий «/»: «//чужой.адрес» браузер понял бы как
                # другой сайт
                if rest:
                    rest = "/" + rest.lstrip("/")

                return HttpResponseRedirect(f"{lang}{rest}{_query(request)}")

            if path.startswith(PREFIX + "/") or first in _PASS:
                return self.get_response(request)

            inner = f"{lang}{PREFIX}{'' if path == '/' else path}"

            if _resolves_to_market(inner):
                # Только для поиска маршрута: request.path — прежний, корневой
                request.path_info = inner

                return self.get_response(request)

            if reading:
                site = os.environ.get("APP_URL", "").rstrip("/")

                if site:
                    return _away(request, f"{site}{request.path}{_query(request)}")

            return self.get_response(request)

        # Основной адрес: страницы маркетплейса — на его адрес
        if reading and _host(request) == site_host() and _is_market_page(path):
            from savdex.web.shared import market_open

            if market_open():
                rest = path[len(PREFIX) :] or ("" if lang else "/")

                return _away(request, f"{_scheme()}://{host}{lang}{rest}{_query(request)}")

        return self.get_response(request)


def links(request: HttpRequest) -> dict[str, str | None]:
    """
    Для страниц (общий проп marketLinks): base — с чего начинаются адреса
    страниц маркетплейса здесь («» на его адресе, «/market» на основном),
    site — основной сайт, market — адрес маркетплейса или None.
    """
    return {
        "base": "" if on_market(request) else PREFIX,
        "site": os.environ.get("APP_URL", "").rstrip("/") or None,
        "market": market_url("") if market_host() else None,
    }
