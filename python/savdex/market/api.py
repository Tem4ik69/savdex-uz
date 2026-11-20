"""
Адреса /market/api/… — JSON для страниц маркетплейса (ветка maksud).

Витрина — GET без входа: категории, каталог, подсказки, товар, продавец.
Корзина, избранное, «Стать продавцом» и «Мои товары» — только со входом:
гость получает 401 и адрес входа (``login``), а адрес страницы, с которой
он пришёл, запоминается — после входа он вернётся к товару (ТЗ, раздел 4).

Запись — POST с токеном CSRF, как у всех форм сайта (заголовок
X-XSRF-TOKEN из куки — так его шлют Inertia и axios), с ограничением
частоты. Ошибка проверки — 422 {message, errors: {поле: [текст]}}, как у
остальных JSON-ответов сайта.

Языковой префикс работает как у страниц: /uz/market/api/… — названия
категорий и тексты по-узбекски.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any

from django.http import HttpRequest, HttpResponse, JsonResponse

from savdex.market import banners as market_banners
from savdex.market import cart, catalog, products, sellers
from savdex.market.common import t
from savdex.web import throttle
from savdex.web.actions import form
from savdex.web.cabinet import _authenticate, company_of
from savdex.web.forms import action, input_of
from savdex.web.request import context
from savdex.web.shared import Context

#: Ответы API в поиск не попадают
_HEADERS = {"X-Robots-Tag": "noindex, nofollow", "Cache-Control": "private, no-store"}


def _json(data: Any, status: int = 200) -> JsonResponse:  # noqa: ANN401
    response = JsonResponse(
        data, status=status, safe=False, json_dumps_params={"ensure_ascii": False}
    )

    for name, value in _HEADERS.items():
        response[name] = value

    return response


def _message(ctx: Context, key: str, status: int, **replace: object) -> JsonResponse:
    return _json({"message": t(key, ctx.locale, **replace)}, status)


def _errors(ctx: Context, errors: products.Errors) -> JsonResponse:
    texts = {name: [t(key, ctx.locale) for key in keys] for name, keys in errors.fields.items()}
    first = next((m for messages in texts.values() for m in messages), "")

    return _json({"message": first, "errors": texts}, 422)


def _reader(request: HttpRequest) -> Context | HttpResponse:
    """Контекст чтения: без перехода на запомненный язык — это не страница."""
    return context(request, redirect=False)


def _guest(ctx: Context) -> JsonResponse:
    """401 со входом: страница, с которой пришёл, запоминается (url.intended)."""
    _authenticate(ctx)

    return _json({"message": t("login", ctx.locale), "login": ctx.url("/login")}, 401)


def _get(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    """Только GET (и HEAD)."""

    @wraps(view)
    def wrapped(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if request.method not in ("GET", "HEAD"):
            return _json({"message": "Method not allowed"}, 405)

        return view(request, *args, **kwargs)

    return wrapped


def _limited(ctx: Context, name: str, per_minute: int) -> JsonResponse | None:
    """
    Ограничение частоты витрины: счётчик на посетителя (номер или IP) и
    адрес — поиск и каталог дорогие, без предела их можно заваливать.
    """
    from savdex import laravel_cache

    if not laravel_cache.is_file_store():
        return None

    key = f"market-{name}|{throttle.signature(ctx)}"

    if throttle.too_many(key, per_minute):
        return _json({"message": "Too many requests"}, 429)

    throttle.hit(key)

    return None


def _id(value: Any) -> int | None:  # noqa: ANN401
    try:
        number = int(str(value))
    except (TypeError, ValueError):
        return None

    return number if 0 < number < 2**62 else None


# ── Витрина ─────────────────────────────────────────────────────────


@_get
def categories(request: HttpRequest) -> HttpResponse:
    ctx = _reader(request)

    if isinstance(ctx, HttpResponse):
        return ctx

    return _json({"categories": catalog.category_tree(ctx.locale)})


@_get
def listing(request: HttpRequest) -> HttpResponse:
    ctx = _reader(request)

    if isinstance(ctx, HttpResponse):
        return ctx

    if (refused := _limited(ctx, "listing", 120)) is not None:
        return refused

    user = ctx.user
    query = catalog.Query.parse(request.GET)

    return _json(catalog.search(query, ctx.locale, user["id"] if user else None))


@_get
def suggest(request: HttpRequest) -> HttpResponse:
    ctx = _reader(request)

    if isinstance(ctx, HttpResponse):
        return ctx

    if (refused := _limited(ctx, "suggest", 60)) is not None:
        return refused

    return _json(catalog.suggest(str(request.GET.get("q", ""))[:100], ctx.locale))


@_get
def product(request: HttpRequest, slug: str) -> HttpResponse:
    ctx = _reader(request)

    if isinstance(ctx, HttpResponse):
        return ctx

    if (refused := _limited(ctx, "product", 120)) is not None:
        return refused

    user = ctx.user
    found = catalog.product(slug, ctx.locale, user["id"] if user else None)

    if found is None:
        return _message(ctx, "not_found", 404)

    catalog.seen(found["id"])

    return _json({"product": found})


@_get
def seller_page(request: HttpRequest, slug: str) -> HttpResponse:
    ctx = _reader(request)

    if isinstance(ctx, HttpResponse):
        return ctx

    if (refused := _limited(ctx, "seller_page", 120)) is not None:
        return refused

    user = ctx.user
    found = catalog.seller(
        slug, catalog.Query.parse(request.GET), ctx.locale, user["id"] if user else None
    )

    if found is None:
        return _message(ctx, "seller.not_found", 404)

    return _json(found)


@_get
def banners(request: HttpRequest) -> HttpResponse:
    """?place=slider|strip|catalog — живые баннеры места (savdex/market/banners.py)."""
    ctx = _reader(request)

    if isinstance(ctx, HttpResponse):
        return ctx

    place = str(request.GET.get("place", "slider"))

    if place not in market_banners.PLACES:
        return _json({"banners": []})

    return _json({"banners": market_banners.live(ctx, place)})


# ── Корзина и избранное ─────────────────────────────────────────────


@_get
def cart_view(request: HttpRequest) -> HttpResponse:
    ctx = _reader(request)

    if isinstance(ctx, HttpResponse):
        return ctx

    user = ctx.user

    if user is None:
        return _guest(ctx)

    return _json(cart.summary(user["id"]))


def _quantity(value: Any, default: int) -> int | None:  # noqa: ANN401
    if value is None or value == "":
        return default

    try:
        return int(str(value))
    except ValueError:
        return None


@form()
def cart_add(request: HttpRequest) -> HttpResponse:
    """POST {variantId, quantity = 1}: положить в корзину."""
    ctx = action(request, auth=False, throttle=60, throttle_prefix="market-cart")
    user = ctx.user

    if user is None:
        return _guest(ctx)

    data = input_of(request)
    variant_id = _id(data.get("variantId"))
    quantity = _quantity(data.get("quantity"), 1)

    if variant_id is None or quantity is None:
        return _message(ctx, "not_found", 404)

    ok, key, extra = cart.add(user["id"], variant_id, quantity)

    if not ok:
        return _message(ctx, key, 404 if key == "not_found" else 422, **extra)

    return _json({"message": t(key, ctx.locale), "cart": cart.summary(user["id"])})


@form()
def cart_set(request: HttpRequest, variant_id: str) -> HttpResponse:
    """POST {quantity}: сколько штук; 0 — убрать."""
    ctx = action(request, auth=False, throttle=120, throttle_prefix="market-cart")
    user = ctx.user

    if user is None:
        return _guest(ctx)

    quantity = _quantity(input_of(request).get("quantity"), 0)

    if quantity is None or quantity < 0:
        return _message(ctx, "cart.quantity", 422, max=cart.MAX_QUANTITY)

    ok, key, extra = cart.set_quantity(user["id"], int(variant_id), quantity)

    if not ok:
        return _message(ctx, key, 404 if key == "not_found" else 422, **extra)

    return _json({"message": t(key, ctx.locale), "cart": cart.summary(user["id"])})


@form()
def favorite(request: HttpRequest, product_id: str) -> HttpResponse:
    """POST: в избранное и обратно."""
    ctx = action(request, auth=False, throttle=60, throttle_prefix="market-favorite")
    user = ctx.user

    if user is None:
        return _guest(ctx)

    state = cart.toggle_favorite(user["id"], int(product_id))

    if state is None:
        return _message(ctx, "not_found", 404)

    return _json({"favorite": state})


@_get
def favorites(request: HttpRequest) -> HttpResponse:
    ctx = _reader(request)

    if isinstance(ctx, HttpResponse):
        return ctx

    user = ctx.user

    if user is None:
        return _guest(ctx)

    return _json({"ids": cart.favorite_ids(user["id"])})


# ── «Стать продавцом» ───────────────────────────────────────────────


@_get
def seller_state(request: HttpRequest) -> HttpResponse:
    """Кабинет: статус заявки продавца и чего не хватает для неё."""
    ctx = _reader(request)

    if isinstance(ctx, HttpResponse):
        return ctx

    user = ctx.user

    if user is None:
        return _guest(ctx)

    return _json(sellers.state(user, company_of(ctx)))


@form()
def seller_apply(request: HttpRequest) -> HttpResponse:
    """POST {offer: true, note?}: заявка «Стать продавцом»."""
    ctx = action(
        request, auth=False, throttle=5, throttle_minutes=60, throttle_prefix="market-seller"
    )
    user = ctx.user

    if user is None:
        return _guest(ctx)

    data = input_of(request)

    if data.get("offer") not in (True, 1, "1", "true", "on", "yes"):
        return _json(
            {
                "message": t("seller.need_offer", ctx.locale),
                "errors": {"offer": [t("seller.need_offer", ctx.locale)]},
            },
            422,
        )

    note = str(data.get("note") or "").strip()[:1000] or None
    company = company_of(ctx)
    ok, key = sellers.apply(user, company, note)

    if not ok:
        return _message(ctx, key, 422)

    return _json({"message": t(key, ctx.locale), "seller": sellers.state(user, company)})


# ── «Мои товары» (кабинет продавца) ─────────────────────────────────


def _seller_ctx(ctx: Context) -> tuple[dict[str, Any] | None, HttpResponse | None]:
    """Подтверждённый продавец — или готовый отказ (гостю 401, не продавцу 403)."""
    user = ctx.user

    if user is None:
        return None, _guest(ctx)

    seller = sellers.approved_of_user(user)

    if seller is None:
        return None, _message(ctx, "seller.required", 403)

    return seller, None


@_get
def my_products(request: HttpRequest) -> HttpResponse:
    ctx = _reader(request)

    if isinstance(ctx, HttpResponse):
        return ctx

    seller, refused = _seller_ctx(ctx)

    if refused is not None:
        return refused

    assert seller is not None

    return _json({"products": products.mine(seller), "needsReview": products.needs_review(seller)})


@form()
def my_product_create(request: HttpRequest) -> HttpResponse:
    ctx = action(request, auth=False, throttle=60, throttle_prefix="market-product")
    seller, refused = _seller_ctx(ctx)

    if refused is not None:
        return refused

    assert seller is not None
    product_id, errors = products.save(seller, input_of(request))

    if errors:
        return _errors(ctx, errors)

    assert product_id is not None

    return _json(
        {"message": t("product.saved", ctx.locale), "product": products.detail(seller, product_id)},
        201,
    )


def my_product(request: HttpRequest, product_id: str) -> HttpResponse:
    """GET — товар для формы правки, POST — сохранить правку."""
    if request.method == "POST":
        return _my_product_update(request, product_id)

    return _my_product_detail(request, product_id)


@_get
def _my_product_detail(request: HttpRequest, product_id: str) -> HttpResponse:
    ctx = _reader(request)

    if isinstance(ctx, HttpResponse):
        return ctx

    seller, refused = _seller_ctx(ctx)

    if refused is not None:
        return refused

    assert seller is not None
    found = products.detail(seller, int(product_id))

    if found is None:
        return _message(ctx, "not_found", 404)

    return _json({"product": found})


@form()
def _my_product_update(request: HttpRequest, product_id: str) -> HttpResponse:
    ctx = action(request, auth=False, throttle=60, throttle_prefix="market-product")
    seller, refused = _seller_ctx(ctx)

    if refused is not None:
        return refused

    assert seller is not None
    saved, errors = products.save(seller, input_of(request), int(product_id))

    if errors:
        if "product" in errors.fields:
            key = errors.fields["product"][0]

            return _message(ctx, key, 404 if key == "not_found" else 422)

        return _errors(ctx, errors)

    assert saved is not None

    return _json(
        {"message": t("product.saved", ctx.locale), "product": products.detail(seller, saved)}
    )


@form()
def my_product_submit(request: HttpRequest, product_id: str) -> HttpResponse:
    """POST: «Отправить на продажу» — на модерацию или сразу в продажу."""
    ctx = action(request, auth=False, throttle=30, throttle_prefix="market-product")
    seller, refused = _seller_ctx(ctx)

    if refused is not None:
        return refused

    assert seller is not None
    status, gaps = products.submit(seller, int(product_id))

    if status is None:
        if gaps == ["not_found"]:
            return _message(ctx, "not_found", 404)

        if gaps == ["product.not_draft"]:
            return _message(ctx, "product.not_draft", 422)

        fields = ", ".join(t(f"product.field.{gap}", ctx.locale) for gap in gaps)

        return _json(
            {"message": t("product.missing", ctx.locale, fields=fields), "missing": gaps}, 422
        )

    return _json(
        {
            "message": t(f"product.{'sent' if status == 'pending' else 'published'}", ctx.locale),
            "status": status,
        }
    )


@form()
def my_product_hide(request: HttpRequest, product_id: str) -> HttpResponse:
    ctx = action(request, auth=False, throttle=30, throttle_prefix="market-product")
    seller, refused = _seller_ctx(ctx)

    if refused is not None:
        return refused

    assert seller is not None

    if not products.hide(seller, int(product_id)):
        return _message(ctx, "not_found", 404)

    return _json({"message": t("product.hidden", ctx.locale), "status": "hidden"})


@form()
def my_product_image(request: HttpRequest, product_id: str) -> HttpResponse:
    """
    POST multipart: file — фото (до 10 на товар), variantId — необязательно:
    фото одного варианта (цвета) этого товара; без него — общее.
    """
    ctx = action(request, auth=False, throttle=60, throttle_prefix="market-image")
    seller, refused = _seller_ctx(ctx)

    if refused is not None:
        return refused

    assert seller is not None
    upload = request.FILES.get("file")

    if upload is None:
        return _message(ctx, "product.image_invalid", 422)

    raw = request.POST.get("variantId") or None
    variant_id = _id(raw) if raw is not None else None

    if raw is not None and variant_id is None:
        return _message(ctx, "product.variant_invalid", 422)

    path, key = products.add_image(seller, int(product_id), upload, variant_id)

    if path is None:
        return _message(ctx, key, 404 if key == "not_found" else 422)

    return _json({"product": products.detail(seller, int(product_id))}, 201)


@form()
def my_product_image_delete(request: HttpRequest, product_id: str, image_id: str) -> HttpResponse:
    ctx = action(request, auth=False, throttle=60, throttle_prefix="market-image")
    seller, refused = _seller_ctx(ctx)

    if refused is not None:
        return refused

    assert seller is not None

    if not products.remove_image(seller, int(product_id), int(image_id)):
        return _message(ctx, "not_found", 404)

    return _json({"product": products.detail(seller, int(product_id))})


@form()
def my_product_image_variant(request: HttpRequest, product_id: str, image_id: str) -> HttpResponse:
    """POST {variantId: номер | null}: фото — одного варианта или общее."""
    ctx = action(request, auth=False, throttle=60, throttle_prefix="market-image")
    seller, refused = _seller_ctx(ctx)

    if refused is not None:
        return refused

    assert seller is not None
    raw = input_of(request).get("variantId")
    variant_id = _id(raw) if raw not in (None, "") else None

    if raw not in (None, "") and variant_id is None:
        return _message(ctx, "product.variant_invalid", 422)

    key = products.set_image_variant(seller, int(product_id), int(image_id), variant_id)

    if key:
        return _message(ctx, key, 404 if key == "not_found" else 422)

    return _json({"product": products.detail(seller, int(product_id))})
