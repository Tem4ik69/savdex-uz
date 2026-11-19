"""
Корзина и избранное покупателя (ТЗ, раздел 7).

Корзина — на сервере, у входа: одна и та же на savdex.uz, поддомене и
телефоне. В строке корзины — только вариант и количество. Цена, название
и остаток каждый раз берутся из варианта и товара: что бы ни прислал
браузер, к оплате пойдёт серверная цена (на оформлении заказа она
скопируется в заказ).

Положить можно не больше, чем есть к продаже (остаток минус резерв).
Если остаток потом уменьшился, строка остаётся, но помечается: сколько
можно купить сейчас (``available``) — страница покажет «осталось N».
"""

from __future__ import annotations

from typing import Any

from savdex.market.catalog import FROM, VISIBLE
from savdex.market.common import now, one, rows, som, write
from savdex.web.shared import public_url

#: Одного варианта — не больше 99 штук (держит и база)
MAX_QUANTITY = 99

#: Строк в корзине — не больше 100
MAX_LINES = 100


def _variant(variant_id: int) -> dict[str, Any] | None:
    """Вариант товара, который можно купить: товар в продаже, вариант включён."""
    return one(
        f"select v.id, v.product_id, v.stock - v.reserved as available {FROM} "
        "join market_product_variants v on v.product_id = p.id "
        f"where {VISIBLE} and v.id = %s and v.is_active",
        [variant_id],
    )


def add(user_id: int, variant_id: int, quantity: int) -> tuple[bool, str, dict[str, Any]]:
    """Положить в корзину (или добавить к лежащему): (удалось, ключ текста, подробности)."""
    if not 1 <= quantity <= MAX_QUANTITY:
        return False, "cart.quantity", {"max": MAX_QUANTITY}

    variant = _variant(variant_id)

    if variant is None:
        return False, "not_found", {}

    available = int(variant["available"])
    current = one(
        "select quantity from market_cart_items where user_id = %s and variant_id = %s",
        [user_id, variant_id],
    )
    total = quantity + (int(current["quantity"]) if current else 0)

    if available <= 0:
        return False, "cart.out_of_stock", {}

    if total > min(available, MAX_QUANTITY):
        return False, "cart.not_enough", {"left": min(available, MAX_QUANTITY)}

    if current is None:
        lines = one("select count(*) as n from market_cart_items where user_id = %s", [user_id])

        if lines is not None and int(lines["n"]) >= MAX_LINES:
            return False, "cart.too_many", {"max": MAX_LINES}

    moment = now()
    write(
        "insert into market_cart_items (user_id, variant_id, quantity, created_at, updated_at) "
        "values (%s, %s, %s, %s, %s) on conflict (user_id, variant_id) do update set "
        "quantity = least(%s, market_cart_items.quantity + excluded.quantity), updated_at = %s",
        [user_id, variant_id, quantity, moment, moment, MAX_QUANTITY, moment],
    )

    return True, "cart.added", {}


def set_quantity(user_id: int, variant_id: int, quantity: int) -> tuple[bool, str, dict[str, Any]]:
    """Сколько штук: 0 — убрать из корзины."""
    if quantity == 0:
        remove(user_id, variant_id)

        return True, "cart.removed", {}

    if not 1 <= quantity <= MAX_QUANTITY:
        return False, "cart.quantity", {"max": MAX_QUANTITY}

    current = one(
        "select 1 as x from market_cart_items where user_id = %s and variant_id = %s",
        [user_id, variant_id],
    )

    if current is None:
        return False, "not_found", {}

    variant = _variant(variant_id)
    available = int(variant["available"]) if variant is not None else 0

    # Меньше — всегда можно (даже если товар кончился); больше — в пределах остатка
    if variant is None or quantity > available:
        return False, "cart.not_enough", {"left": max(0, min(available, MAX_QUANTITY))}

    write(
        "update market_cart_items set quantity = %s, updated_at = %s "
        "where user_id = %s and variant_id = %s",
        [quantity, now(), user_id, variant_id],
    )

    return True, "cart.updated", {}


def remove(user_id: int, variant_id: int) -> None:
    write(
        "delete from market_cart_items where user_id = %s and variant_id = %s",
        [user_id, variant_id],
    )


def summary(user_id: int) -> dict[str, Any]:
    """
    Корзина для страницы: части по продавцам (в заказе у каждого продавца
    будет своя часть и свои деньги), строки с серверной ценой и итог по
    тому, что можно купить сейчас.
    """
    found = rows(
        "select ci.variant_id, ci.quantity, v.options, v.price, v.old_price, "
        "v.stock - v.reserved as left_now, v.is_active, p.id as product_id, p.slug, p.title, "
        f"c.slug as seller_slug, c.name as seller_name, ({VISIBLE}) as on_sale, "
        "(select i.path from market_product_images i where i.product_id = p.id "
        " order by i.sort, i.id limit 1) as cover "
        "from market_cart_items ci "
        "join market_product_variants v on v.id = ci.variant_id "
        "join market_products p on p.id = v.product_id "
        "join market_sellers s on s.id = p.seller_id "
        "join companies c on c.id = s.company_id "
        "where ci.user_id = %s order by ci.created_at, ci.id",
        [user_id],
    )
    parts: dict[str, dict[str, Any]] = {}
    total = 0
    count = 0

    for r in found:
        buyable = bool(r["on_sale"]) and bool(r["is_active"]) and int(r["left_now"]) > 0
        available = max(0, int(r["left_now"])) if buyable else 0
        quantity = int(r["quantity"])
        line_total = int(r["price"]) * min(quantity, available)
        part = parts.setdefault(
            r["seller_slug"],
            {
                "seller": {"slug": r["seller_slug"], "name": r["seller_name"]},
                "items": [],
                "total": 0,
            },
        )
        part["items"].append(
            {
                "variantId": r["variant_id"],
                "productId": r["product_id"],
                "slug": r["slug"],
                "title": r["title"],
                "image": public_url(r["cover"]) if r["cover"] else None,
                "options": r["options"] or {},
                "price": som(r["price"]),
                "oldPrice": som(r["old_price"]),
                "quantity": quantity,
                "available": available,
                "buyable": buyable,
                "total": som(line_total),
            }
        )
        part["total"] += line_total
        total += line_total
        count += min(quantity, available)

    return {
        "parts": [{**p, "total": som(p["total"])} for p in parts.values()],
        "count": count,
        "lines": len(found),
        "total": som(total),
    }


# ── Избранное ───────────────────────────────────────────────────────


def toggle_favorite(user_id: int, product_id: int) -> bool | None:
    """
    В избранное и обратно: итог — в избранном ли теперь. Добавить можно
    только товар в продаже (None — нет такого); убрать — любой.
    """
    removed = write(
        "delete from market_favorites where user_id = %s and product_id = %s",
        [user_id, product_id],
    )

    if removed:
        return False

    visible = one(f"select p.id {FROM} where {VISIBLE} and p.id = %s", [product_id])

    if visible is None:
        return None

    write(
        "insert into market_favorites (user_id, product_id, created_at) values (%s, %s, %s) "
        "on conflict do nothing",
        [user_id, product_id, now()],
    )

    return True


def favorite_ids(user_id: int) -> list[int]:
    return [
        r["product_id"]
        for r in rows(
            "select product_id from market_favorites where user_id = %s order by created_at desc",
            [user_id],
        )
    ]
