"""
Маркетплейс — страницы (ТЗ 18.11, раздел 11.1).

Сервер отдаёт страницу и то, что нужно знать до загрузки данных: адрес
товара или продавца, строку отбора каталога, вкладку кабинета. Сами
данные страница берёт запросами к /market/api/… (savdex/market/api.py,
docs/marketplace.md): каталог, товар, корзина, избранное, заявка
продавца, «Мои товары». Заказов, склада и кассы на сервере ещё нет —
оформление, «Мои заказы» и часть кабинета продавца пока показывают
образцы.

Пока маркетплейс не запущен, страницы закрыты от поисковиков, а на
боевом (APP_ENV=production) не открываются вовсе.
"""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse

from savdex.web import fallback, inertia
from savdex.web.request import context
from savdex.web.seo import Seo
from savdex.web.shared import Context, market_open

#: Строка отбора каталога длиннее не бывает: адрес с фильтрами короче
_SEARCH_LIMIT = 2000

#: Вкладки кабинета продавца; первая — та, что открывается по умолчанию
_SELLER_TABS = ("products", "stock", "supplies", "orders", "payouts")


def _seo(ctx: Context, title: str) -> Seo:
    seo = Seo(ctx.root, ctx.path.rstrip("/") or "/", ctx.locale).title(title)
    seo.noindex = True

    return seo


def _page(
    request: HttpRequest, component: str, title: str, props: dict[str, object]
) -> HttpResponse:
    # На боевом маркетплейс не показывается, пока не запущен: адреса
    # отвечают «страница не найдена»
    if not market_open():
        return fallback.page_not_found(request)

    ctx = context(request)

    if isinstance(ctx, HttpResponse):
        return ctx

    return inertia.render(ctx, component, props, _seo(ctx, title))


def home(request: HttpRequest) -> HttpResponse:
    return _page(request, "market/Home", "SavdEx Market", {})


def catalog(request: HttpRequest) -> HttpResponse:
    # Отбор (категория, поиск, цена, характеристики, сортировка, страница)
    # страница передаёт серверу как есть — /market/api/catalog сам
    # отбрасывает непонятное, разбирать адрес дважды незачем
    search = request.META.get("QUERY_STRING", "")[:_SEARCH_LIMIT]

    return _page(request, "market/Catalog", "Каталог · SavdEx Market", {"search": search})


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
        {"tab": tab if tab in _SELLER_TABS else _SELLER_TABS[0]},
    )
