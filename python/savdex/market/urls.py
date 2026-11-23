"""
Адреса JSON маркетплейса — /market/api/… (savdex/market/api.py).

Отдельным списком, чтобы не мешать адресам страниц (/market, /market/catalog
… — savdex/web/market.py, ветка maksud); подключаются в savdex/urls.py
перед последним «всё остальное — 404».
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any

from django.http import HttpRequest, HttpResponse
from django.urls import URLPattern, re_path

from savdex.market import api, oneid
from savdex.market.payments import click, payme, uzum

_P = r"^(?:(?:uz|en|zh|tr)/)?market/api/"
_ID = r"[0-9]{1,18}"
#: Номер заказа — случайный код (savdex/market/orders.py)
_NUMBER = r"[0-9A-Za-z]{8,16}"

urlpatterns = [
    re_path(_P + r"categories$", api.categories, name="market.api.categories"),
    re_path(_P + r"catalog$", api.listing, name="market.api.catalog"),
    re_path(_P + r"suggest$", api.suggest, name="market.api.suggest"),
    re_path(_P + r"banners$", api.banners, name="market.api.banners"),
    re_path(_P + r"product/(?P<slug>[a-z0-9-]{1,80})$", api.product, name="market.api.product"),
    re_path(_P + r"seller/(?P<slug>[a-z0-9-]{1,190})$", api.seller_page, name="market.api.seller"),
    re_path(_P + r"cart$", api.cart_view, name="market.api.cart"),
    re_path(_P + r"cart/add$", api.cart_add, name="market.api.cart.add"),
    re_path(_P + rf"cart/(?P<variant_id>{_ID})$", api.cart_set, name="market.api.cart.set"),
    re_path(_P + r"favorites$", api.favorites, name="market.api.favorites"),
    re_path(
        _P + rf"favorites/(?P<product_id>{_ID})$", api.favorite, name="market.api.favorites.toggle"
    ),
    re_path(_P + r"pickup-points$", api.pickup_points, name="market.api.pickup_points"),
    re_path(_P + r"checkout$", api.checkout, name="market.api.checkout"),
    re_path(_P + r"orders$", api.my_orders, name="market.api.orders"),
    re_path(_P + rf"orders/(?P<number>{_NUMBER})$", api.order, name="market.api.order"),
    re_path(
        _P + rf"orders/(?P<number>{_NUMBER})/cancel$",
        api.order_cancel,
        name="market.api.order.cancel",
    ),
    re_path(_P + rf"orders/(?P<number>{_NUMBER})/pay$", api.order_pay, name="market.api.order.pay"),
    re_path(_P + r"me/orders$", api.my_seller_orders, name="market.api.me.orders"),
    re_path(_P + r"me/balance$", api.my_balance, name="market.api.me.balance"),
    re_path(_P + r"me/warehouses$", api.my_warehouses, name="market.api.me.warehouses"),
    re_path(_P + r"me/supplies$", api.my_supplies, name="market.api.me.supplies"),
    re_path(
        _P + r"me/supplies/create$", api.my_supply_create, name="market.api.me.supplies.create"
    ),
    re_path(
        _P + rf"me/supplies/(?P<number>{_NUMBER})$", api.my_supply, name="market.api.me.supply"
    ),
    re_path(
        _P + rf"me/supplies/(?P<number>{_NUMBER})/submit$",
        api.my_supply_submit,
        name="market.api.me.supply.submit",
    ),
    re_path(
        _P + rf"me/supplies/(?P<number>{_NUMBER})/cancel$",
        api.my_supply_cancel,
        name="market.api.me.supply.cancel",
    ),
    re_path(_P + r"me/requisites$", api.my_requisites, name="market.api.me.requisites"),
    re_path(_P + r"me/seller$", api.seller_state, name="market.api.me.seller"),
    re_path(_P + r"me/seller/apply$", api.seller_apply, name="market.api.me.seller.apply"),
    re_path(_P + r"oneid/start$", api.oneid_start, name="market.api.oneid.start"),
    # Без языкового префикса: адрес возврата у OneID — один, из настроек
    re_path(r"^market/api/oneid/callback$", oneid.callback, name="market.api.oneid.callback"),
    re_path(_P + r"me/products$", api.my_products, name="market.api.me.products"),
    re_path(
        _P + r"me/products/create$", api.my_product_create, name="market.api.me.products.create"
    ),
    re_path(
        _P + rf"me/products/(?P<product_id>{_ID})$", api.my_product, name="market.api.me.product"
    ),
    re_path(
        _P + rf"me/products/(?P<product_id>{_ID})/submit$",
        api.my_product_submit,
        name="market.api.me.product.submit",
    ),
    re_path(
        _P + rf"me/products/(?P<product_id>{_ID})/hide$",
        api.my_product_hide,
        name="market.api.me.product.hide",
    ),
    re_path(
        _P + rf"me/products/(?P<product_id>{_ID})/images$",
        api.my_product_image,
        name="market.api.me.product.images",
    ),
    re_path(
        _P + rf"me/products/(?P<product_id>{_ID})/images/(?P<image_id>{_ID})/variant$",
        api.my_product_image_variant,
        name="market.api.me.product.images.variant",
    ),
    re_path(
        _P + rf"me/products/(?P<product_id>{_ID})/images/(?P<image_id>{_ID})/delete$",
        api.my_product_image_delete,
        name="market.api.me.product.images.delete",
    ),
]


def _open_only(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    """Пока маркетплейс не запущен (savdex.web.shared.market_open) — 404, как у страниц."""

    @wraps(view)
    def wrapped(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        from savdex.web import fallback
        from savdex.web.shared import market_open

        if not market_open():
            return fallback.page_not_found(request)

        return view(request, *args, **kwargs)

    return wrapped


def _gated(route: URLPattern) -> URLPattern:
    return re_path(route.pattern.regex.pattern, _open_only(route.callback), name=route.name)


# Каждый адрес из списка выше — за проверкой «маркетплейс открыт».
# Исключение одно — колбэки оплаты ниже: их список дописан после этой
# строки (``+=``) намеренно, и _open_only их не оборачивает. Новый адрес
# страниц — в список выше, не ниже
urlpatterns = [_gated(route) for route in urlpatterns]

# Колбэки провайдеров оплаты (savdex/market/payments): сервер — серверу,
# без языкового префикса — адрес один, его заводят в кабинете провайдера.
# Вне проверки «маркетплейс открыт»: по уже заведённым транзакциям
# (confirm, perform, complete, reverse, cancel, status) провайдер должен
# достучаться всегда, иначе деньги повиснут. Новые транзакции (check,
# create, prepare, CheckPerform, CreateTransaction) колбэк сам пускает
# только при открытом маркетплейсе (payments/base.py, market_closed)
urlpatterns += [
    re_path(
        r"^market/api/payments/uzum/(?P<operation>check|create|confirm|reverse|status)$",
        uzum.merchant,
        name="market.api.payments.uzum",
    ),
    re_path(r"^market/api/payments/payme$", payme.endpoint, name="market.api.payments.payme"),
    re_path(
        r"^market/api/payments/click/prepare$",
        click.prepare,
        name="market.api.payments.click.prepare",
    ),
    re_path(
        r"^market/api/payments/click/complete$",
        click.complete,
        name="market.api.payments.click.complete",
    ),
]
