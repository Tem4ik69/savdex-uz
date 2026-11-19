"""
Маркетплейс — страницы оформления на демо-данных (ТЗ 18.11, раздел 11.1).

Бэкенда каталога, корзины и заказов ещё нет: сервер отдаёт только
страницу и разобранный адрес, а товары, цены и продавцы лежат во
фронтенде (resources/js/market/demo.ts) в том виде, в каком страницы
будут получать их с сервера. Корзина и избранное — в браузере.

Пока это демо, страницы закрыты от поисковиков, а на боевом
(APP_ENV=production) не открываются вовсе.
"""

from __future__ import annotations

import os

from django.http import HttpRequest, HttpResponse

from savdex.web import fallback, inertia
from savdex.web.request import context
from savdex.web.seo import Seo
from savdex.web.shared import Context

#: Параметры каталога, которые понимает страница; остальное отбрасывается
_CATALOG_KEYS = ("q", "category", "sort", "only", "max")

#: Вкладки кабинета продавца
_SELLER_TABS = ("overview", "products", "supplies", "stock", "orders", "payouts")


def _seo(ctx: Context, title: str) -> Seo:
    seo = Seo(ctx.root, ctx.path.rstrip("/") or "/", ctx.locale).title(title)
    seo.noindex = True

    return seo


def _page(
    request: HttpRequest, component: str, title: str, props: dict[str, object]
) -> HttpResponse:
    # На боевом демо с выдуманными товарами не показывается: адреса
    # отвечают «страница не найдена», пока маркетплейс не запущен
    if os.environ.get("APP_ENV", "local") == "production":
        return fallback.page_not_found(request)

    ctx = context(request)

    if isinstance(ctx, HttpResponse):
        return ctx

    return inertia.render(ctx, component, props, _seo(ctx, title))


def home(request: HttpRequest) -> HttpResponse:
    return _page(request, "market/Home", "SavdEx Market", {})


def catalog(request: HttpRequest) -> HttpResponse:
    query = {
        key: request.GET.get(key, "").strip()[:80] for key in _CATALOG_KEYS if request.GET.get(key)
    }

    return _page(request, "market/Catalog", "Каталог · SavdEx Market", {"query": query})


def product(request: HttpRequest, slug: str) -> HttpResponse:
    return _page(request, "market/Product", "SavdEx Market", {"slug": slug})


def cart(request: HttpRequest) -> HttpResponse:
    return _page(request, "market/Cart", "Корзина · SavdEx Market", {})


def checkout(request: HttpRequest) -> HttpResponse:
    return _page(request, "market/Checkout", "Оформление заказа · SavdEx Market", {})


def orders(request: HttpRequest) -> HttpResponse:
    return _page(request, "market/Orders", "Мои заказы · SavdEx Market", {})


def shop(request: HttpRequest, slug: str) -> HttpResponse:
    return _page(request, "market/Shop", "SavdEx Market", {"slug": slug})


def sell(request: HttpRequest) -> HttpResponse:
    return _page(request, "market/Sell", "Стать продавцом · SavdEx Market", {})


def seller(request: HttpRequest) -> HttpResponse:
    tab = request.GET.get("tab", "")

    return _page(
        request,
        "market/Seller",
        "Кабинет продавца · SavdEx Market",
        {"tab": tab if tab in _SELLER_TABS else "overview"},
    )
