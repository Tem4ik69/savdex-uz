"""
Витрина маркетплейса: категории, список товаров, подсказки поиска,
карточка товара, страница продавца. Только чтение.

Покупателю видны только товары «в продаже» (status = 'active') у
подтверждённых продавцов, чья компания не заблокирована и не удалена.
Всё остальное — 404, как будто товара нет: черновик, отклонённый или
снятый товар не должен открываться по прямой ссылке.

Ответы — в том виде, в каком их ждут страницы Максуда
(resources/js/market/demo.ts, ветка maksud): цены — в сумах, у карточки
badge 'hit' | 'new' | 'sale' | null, у товара specs — пары
[название, значение].
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from savdex.market.common import localized, one, rows, som, t, tiyin, write
from savdex.web.shared import public_url

#: Карточек на странице каталога
PER_PAGE = 24

#: Дальше сотой страницы каталог не листается: такие запросы — роботы,
#: а большой OFFSET дорог базе
MAX_PAGE = 100

#: Сортировки каталога — ключи те же, что у страницы Максуда
SORTS: dict[str, str] = {
    "popular": "p.sold_count desc, p.views_count desc, p.id desc",
    "cheap": "p.price asc, p.id desc",
    "expensive": "p.price desc, p.id desc",
    "new": "p.published_at desc, p.id desc",
    "rating": "p.rating desc, p.reviews_count desc, p.id desc",
}

#: Подборки (only=…): «Скидки», «Новинки», «Хиты»; «Избранное» — у входа
SHELVES = ("sale", "new", "hit", "fav")

#: «Новинка» — в продаже не дольше двух недель
NEW_DAYS = 14

#: «Хит» — продано не меньше 50 штук
HIT_SOLD = 50

#: Товар у покупателя виден, только если и он, и продавец, и компания живы
VISIBLE = (
    "p.status = 'active' and s.status = 'approved' and c.deleted_at is null and c.status = 'active'"
)

FROM = (
    "from market_products p "
    "join market_sellers s on s.id = p.seller_id "
    "join companies c on c.id = s.company_id "
    "join market_categories mc on mc.id = p.category_id "
)

#: Слово запроса для поиска: буквы и цифры любого алфавита
_WORD = re.compile(r"\w+", re.UNICODE)

# Похожие по написанию — только когда полнотекстовый поиск ничего не
# нашёл: «смартфн» → «Смартфон», «samsng» → «Samsung». pg_trgm, индекс
# market_products_title_trgm_index; порог 0.5 — настройка базы
# (миграция 2026_11_19_120000_add_typo_search_to_market.sql)
# «%%» — знак «%» оператора: запросы идут с параметрами psycopg
_FUZZY = "%s <%% p.title"
_FUZZY_RANK = "word_similarity(%s, p.title) desc"


# ── Категории ───────────────────────────────────────────────────────


def category_tree(locale: str) -> list[dict[str, Any]]:
    """
    Дерево включённых категорий: разделы, в каждом — подразделы (и их
    подразделы). Выключенный раздел прячет и всё, что под ним.
    """
    found = rows(
        "select id, parent_id, slug, name, names, icon from market_categories "
        "where is_active order by sort, name"
    )
    nodes = {
        r["id"]: {
            "slug": r["slug"],
            "name": localized(r["name"], r["names"], locale),
            "emoji": r["icon"] or "",
            "children": [],
            "_parent": r["parent_id"],
        }
        for r in found
    }
    tree = []

    for node in nodes.values():
        parent = node.pop("_parent")

        if parent is None:
            tree.append(node)
        elif parent in nodes:
            nodes[parent]["children"].append(node)

    return tree


def category_by_slug(slug: str) -> dict[str, Any] | None:
    return one("select * from market_categories where slug = %s and is_active", [slug])


def subtree_ids(category_id: int) -> list[int]:
    """Категория и все включённые под ней — товар подраздела виден и в разделе."""
    found = rows(
        "with recursive tree as ("
        "  select id from market_categories where id = %s and is_active"
        "  union all"
        "  select c.id from market_categories c join tree on c.parent_id = tree.id"
        "  where c.is_active"
        ") select id from tree",
        [category_id],
    )

    return [r["id"] for r in found]


def category_path(category_id: int, locale: str) -> list[dict[str, str]]:
    """Хлебные крошки: от раздела до самой категории."""
    found = rows(
        "with recursive up as ("
        "  select id, parent_id, slug, name, names, 0 as depth from market_categories"
        "  where id = %s"
        "  union all"
        "  select c.id, c.parent_id, c.slug, c.name, c.names, up.depth + 1"
        "  from market_categories c join up on c.id = up.parent_id"
        ") select slug, name, names from up order by depth desc",
        [category_id],
    )

    return [{"slug": r["slug"], "name": localized(r["name"], r["names"], locale)} for r in found]


def attributes_for(category_id: int) -> list[dict[str, Any]]:
    """Характеристики категории вместе с унаследованными от разделов выше."""
    return rows(
        "with recursive up as ("
        "  select id, parent_id, 0 as depth from market_categories where id = %s"
        "  union all"
        "  select c.id, c.parent_id, up.depth + 1 from market_categories c"
        "  join up on c.id = up.parent_id"
        ") select a.* from market_attributes a join up on up.id = a.category_id "
        "order by up.depth desc, a.sort, a.id",
        [category_id],
    )


# ── Карточка в списке ───────────────────────────────────────────────


def _badge(row: Mapping[str, Any]) -> str | None:
    """Метка карточки: скидка важнее новинки, новинка — хита."""
    if row["old_price"] is not None:
        return "sale"

    published = row.get("published_at")

    if published is not None:
        moment = published if published.tzinfo else published.replace(tzinfo=UTC)

        if datetime.now(UTC) - moment <= timedelta(days=NEW_DAYS):
            return "new"

    if int(row["sold_count"] or 0) >= HIT_SOLD:
        return "hit"

    return None


#: Что нужно для карточки в списке
CARD_COLUMNS = (
    "p.id, p.slug, p.title, p.price, p.old_price, p.stock, p.rating, p.reviews_count, "
    "p.sold_count, p.published_at, mc.slug as category_slug, c.slug as seller_slug, "
    "c.name as seller_name, "
    # Обложка — первое общее фото (фото вариантов — после), уменьшенная копия
    "(select coalesce(i.thumb_path, i.path) from market_product_images i "
    " where i.product_id = p.id order by i.variant_id is not null, i.sort, i.id "
    " limit 1) as cover"
)


def card(row: Mapping[str, Any]) -> dict[str, Any]:
    """Карточка товара в списке — формат MarketProduct без описания и вариантов."""
    return {
        "id": row["id"],
        "slug": row["slug"],
        "title": row["title"],
        "image": public_url(row["cover"]) if row.get("cover") else None,
        "price": som(row["price"]),
        "oldPrice": som(row["old_price"]),
        "rating": float(row["rating"] or 0),
        "reviews": int(row["reviews_count"] or 0),
        "sold": int(row["sold_count"] or 0),
        "stock": int(row["stock"] or 0),
        "category": row["category_slug"],
        "seller": row["seller_slug"],
        "sellerName": row["seller_name"],
        "badge": _badge(row),
    }


def _cover(images: list[dict[str, Any]]) -> str | None:
    """Обложка карточки: первое общее фото, иначе первое любое; уменьшенная копия."""
    ordered = sorted(images, key=lambda i: i["variant_id"] is not None)

    return (ordered[0]["thumb_path"] or ordered[0]["path"]) if ordered else None


def image_view(row: Mapping[str, Any]) -> dict[str, Any]:
    """
    Фото для страниц: большое, уменьшенное для карточек (нет — то же
    большое) и чьё — номер варианта (цвета) или None, если общее.
    """
    return {
        "id": row["id"],
        "url": public_url(row["path"]),
        "thumb": public_url(row["thumb_path"] or row["path"]),
        "variantId": row["variant_id"],
    }


# ── Список с поиском и фильтрами ────────────────────────────────────


@dataclass(frozen=True)
class Query:
    """Разобранный адрес каталога. Непонятное отбрасывается, а не ломает запрос."""

    q: str = ""
    category: str = ""
    seller: str = ""
    sort: str = "popular"
    only: str = ""
    min_price: int | None = None
    max_price: int | None = None
    #: Характеристики: ключ → выбранные значения (текст и выбор)
    values: tuple[tuple[str, tuple[str, ...]], ...] = ()
    #: Числовые характеристики: ключ → (от, до)
    ranges: tuple[tuple[str, float | None, float | None], ...] = ()
    page: int = 1

    @classmethod
    def parse(cls, params: Mapping[str, Any]) -> Query:
        """
        ?q=…&category=…&seller=…&sort=…&only=…&min=…&max=…&page=…
        и характеристики: attr.color=red,blue и attr.memory_min=64 / _max=256.
        Цены — в сумах, как на странице.
        """

        def text(key: str, limit: int = 80) -> str:
            value = params.get(key)

            return str(value).strip()[:limit] if value is not None else ""

        def number(key: str) -> float | None:
            value = text(key, 20).replace(" ", "").replace(",", ".")

            try:
                parsed = float(value) if value else None
            except ValueError:
                return None

            return parsed if parsed is not None and parsed == parsed else None

        try:
            page = max(1, min(MAX_PAGE, int(text("page", 4) or 1)))
        except ValueError:
            page = 1

        values: dict[str, tuple[str, ...]] = {}
        bounds: dict[str, list[float | None]] = {}

        for key in list(params)[:40]:
            if not isinstance(key, str) or not key.startswith("attr."):
                continue

            name = key[5:]

            for suffix, index in (("_min", 0), ("_max", 1)):
                if name.endswith(suffix) and re.fullmatch(r"[a-z][a-z0-9_]{0,39}", name[:-4]):
                    bounds.setdefault(name[:-4], [None, None])[index] = number(key)
                    break
            else:
                if re.fullmatch(r"[a-z][a-z0-9_]{0,39}", name):
                    picked = [v.strip()[:200] for v in text(key, 1000).split(",") if v.strip()]
                    values[name] = tuple(picked[:20])

        sort = text("sort", 16)
        only = text("only", 8)

        return cls(
            q=text("q", 100),
            category=text("category"),
            seller=text("seller"),
            sort=sort if sort in SORTS else "popular",
            only=only if only in SHELVES else "",
            min_price=tiyin(text("min", 20) or None),
            max_price=tiyin(text("max", 20) or None),
            values=tuple(sorted((k, v) for k, v in values.items() if v)),
            ranges=tuple(sorted((k, lo, hi) for k, (lo, hi) in bounds.items())),
            page=page,
        )


def _tsquery(text: str) -> str | None:
    """Слова запроса — «слово:*» через «&»: «айфон 15» найдёт «iPhone 15 Pro»… по началу слова."""
    words = [w.lower() for w in _WORD.findall(text)][:8]

    return " & ".join(f"{w}:*" for w in words) if words else None


def _needle(text: str) -> str | None:
    """Запрос для поиска с опечатками: слова в нижнем регистре, не длиннее 60 знаков."""
    words = " ".join(w.lower() for w in _WORD.findall(text))[:60].strip()

    return words or None


def search(query: Query, locale: str, user_id: int | None = None) -> dict[str, Any]:
    """
    Каталог: товары с поиском, фильтрами, сортировкой и страницами.
    Плюс то, что нужно странице для фильтров: характеристики категории
    и разброс цен.
    """
    where = [VISIBLE]
    params: list[Any] = []
    category = category_by_slug(query.category) if query.category else None

    if query.category and category is None:
        return _empty(query)

    if category is not None:
        ids = subtree_ids(category["id"])
        where.append("p.category_id = any(%s)")
        params.append(ids)

    if query.seller:
        where.append("c.slug = %s")
        params.append(query.seller)

    tsquery = _tsquery(query.q) if query.q else None

    if query.q and tsquery is None:
        return _empty(query)

    match_at = param_at = -1

    if tsquery is not None:
        match_at, param_at = len(where), len(params)
        where.append("p.search @@ to_tsquery('simple', %s)")
        params.append(tsquery)

    if query.only == "sale":
        where.append("p.old_price is not null")
    elif query.only == "new":
        where.append(f"p.published_at >= (now() at time zone 'utc') - interval '{NEW_DAYS} days'")
    elif query.only == "hit":
        where.append(f"p.sold_count >= {HIT_SOLD}")
    elif query.only == "fav":
        if user_id is None:
            return _empty(query)

        where.append(
            "exists (select 1 from market_favorites f where f.product_id = p.id and f.user_id = %s)"
        )
        params.append(user_id)

    price_where = list(where)
    price_params = list(params)

    if query.min_price is not None:
        where.append("p.price >= %s")
        params.append(query.min_price)

    if query.max_price is not None:
        where.append("p.price <= %s")
        params.append(query.max_price)

    attributes = attributes_for(category["id"]) if category is not None else []
    by_key = {a["key"]: a for a in attributes}

    for key, picked in query.values:
        attribute = by_key.get(key)

        if attribute is None:
            continue

        where.append(
            "exists (select 1 from market_product_values v where v.product_id = p.id "
            "and v.attribute_id = %s and v.value_text = any(%s))"
        )
        params += [attribute["id"], list(picked)]

    for key, low, high in query.ranges:
        attribute = by_key.get(key)

        if attribute is None or attribute["kind"] != "number" or (low is None and high is None):
            continue

        where.append(
            "exists (select 1 from market_product_values v where v.product_id = p.id "
            "and v.attribute_id = %s and v.value_number between %s and %s)"
        )
        params += [
            attribute["id"],
            low if low is not None else -1e15,
            high if high is not None else 1e15,
        ]

    condition = " and ".join(where)
    total = int(rows(f"select count(*) as n {FROM} where {condition}", params)[0]["n"])

    # Ничего не нашлось — то же самое, но по похожему написанию названия
    # (те же фильтры); странице — fuzzy: «показаны похожие»
    needle = _needle(query.q) if tsquery is not None and total == 0 else None
    fuzzy = False

    if needle is not None:
        where[match_at] = price_where[match_at] = _FUZZY
        params[param_at] = price_params[param_at] = needle
        condition = " and ".join(where)
        total = int(rows(f"select count(*) as n {FROM} where {condition}", params)[0]["n"])
        fuzzy = total > 0

    order = SORTS[query.sort]
    order_params: list[Any] = []

    # Поиск без явной сортировки — сначала самые подходящие
    if fuzzy and query.sort == "popular":
        order = f"{_FUZZY_RANK}, {order}"
        order_params = [needle]
    elif tsquery is not None and query.sort == "popular":
        order = f"ts_rank(p.search, to_tsquery('simple', %s)) desc, {order}"
        order_params = [tsquery]

    found = rows(
        f"select {CARD_COLUMNS} {FROM} where {condition} order by {order} limit %s offset %s",
        [*params, *order_params, PER_PAGE, (query.page - 1) * PER_PAGE],
    )
    span = rows(
        f"select min(p.price) as low, max(p.price) as high {FROM} "
        f"where {' and '.join(price_where)}",
        price_params,
    )[0]

    return {
        "items": [card(r) for r in found],
        "total": total,
        "page": query.page,
        "pages": min(MAX_PAGE, -(-total // PER_PAGE)),
        "sort": query.sort,
        "fuzzy": fuzzy,
        "price": {"min": som(span["low"]), "max": som(span["high"])},
        "filters": _filters(category, attributes, locale) if category is not None else [],
        "category": (
            {
                "slug": category["slug"],
                "name": localized(category["name"], category["names"], locale),
                "path": category_path(category["id"], locale),
            }
            if category is not None
            else None
        ),
    }


def _empty(query: Query) -> dict[str, Any]:
    return {
        "items": [],
        "total": 0,
        "page": query.page,
        "pages": 0,
        "sort": query.sort,
        "fuzzy": False,
        "price": {"min": None, "max": None},
        "filters": [],
        "category": None,
    }


def _filters(
    category: Mapping[str, Any], attributes: list[dict[str, Any]], locale: str
) -> list[dict[str, Any]]:
    """
    Фильтры категории: у выбора — варианты, у строки — встречающиеся
    значения (до 30 самых частых), у числа — от и до. Сколько товаров у
    значения — по всей категории.
    """
    ids = subtree_ids(category["id"])
    result = []

    for attribute in attributes:
        if not attribute["is_filter"]:
            continue

        item: dict[str, Any] = {
            "key": attribute["key"],
            "name": localized(attribute["name"], attribute["names"], locale),
            "kind": attribute["kind"],
            "unit": attribute["unit"],
        }

        if attribute["kind"] == "number":
            span = rows(
                f"select min(v.value_number) as low, max(v.value_number) as high {FROM} "
                "join market_product_values v on v.product_id = p.id "
                f"where {VISIBLE} and v.attribute_id = %s and p.category_id = any(%s)",
                [attribute["id"], ids],
            )[0]
            item["min"] = float(span["low"]) if span["low"] is not None else None
            item["max"] = float(span["high"]) if span["high"] is not None else None
        else:
            counted = rows(
                f"select v.value_text as value, count(*) as n {FROM} "
                "join market_product_values v on v.product_id = p.id "
                f"where {VISIBLE} and v.attribute_id = %s and p.category_id = any(%s) "
                "group by v.value_text order by count(*) desc, v.value_text limit 30",
                [attribute["id"], ids],
            )
            names = (
                {"1": t("yes", locale), "0": t("no", locale)}
                if attribute["kind"] == "bool"
                else {
                    str(o.get("value")): localized(str(o.get("name", "")), o.get("names"), locale)
                    for o in attribute["options"] or []
                    if isinstance(o, dict)
                }
            )
            item["options"] = [
                {"value": r["value"], "name": names.get(r["value"], r["value"]), "count": r["n"]}
                for r in counted
            ]

        result.append(item)

    return result


# ── Подсказки поиска ────────────────────────────────────────────────


def suggest(text: str, locale: str) -> dict[str, Any]:
    """Подсказки под строкой поиска: до 8 товаров и до 4 категорий."""
    tsquery = _tsquery(text)

    if tsquery is None:
        return {"products": [], "categories": []}

    products = rows(
        f"select p.slug, p.title {FROM} where {VISIBLE} "
        "and p.search @@ to_tsquery('simple', %s) "
        "order by ts_rank(p.search, to_tsquery('simple', %s)) desc, p.sold_count desc, p.id desc "
        "limit 8",
        [tsquery, tsquery],
    )
    needle = " ".join(_WORD.findall(text.lower()))[:60]

    # Ничего по началу слова — похожие по написанию («galxy» → «Galaxy»)
    if not products:
        products = rows(
            f"select p.slug, p.title {FROM} where {VISIBLE} and {_FUZZY} "
            f"order by {_FUZZY_RANK}, p.sold_count desc, p.id desc limit 8",
            [needle, needle],
        )
    categories = rows(
        "select slug, name, names from market_categories where is_active and ("
        "  lower(name) like %s or lower(names::text) like %s"
        ") order by parent_id nulls first, sort limit 4",
        [f"%{needle}%", f"%{needle}%"],
    )

    return {
        "products": [{"slug": r["slug"], "title": r["title"]} for r in products],
        "categories": [
            {"slug": r["slug"], "name": localized(r["name"], r["names"], locale)}
            for r in categories
        ],
    }


# ── Карточка товара ─────────────────────────────────────────────────


def seller_card(company: Mapping[str, Any]) -> dict[str, Any]:
    """Продавец на карточке товара — формат MarketSeller."""
    return {
        "slug": company["slug"],
        "name": company["name"],
        # Проверенная компания SavdEx (документы приняты модератором)
        "verified": int(company["verification_level"] or 0) >= 2,
        "rating": float(company["rating"] or 0),
        "logo": public_url(company["logo_path"]) if company.get("logo_path") else None,
    }


def _value_text(value: Mapping[str, Any], attribute: Mapping[str, Any], locale: str) -> str:
    if value["value_number"] is not None:
        number = value["value_number"].normalize()
        text = f"{number:f}"

        return f"{text} {attribute['unit']}" if attribute["unit"] else text

    if attribute["kind"] == "bool":
        return t("yes" if value["value_text"] == "1" else "no", locale)

    if attribute["kind"] == "choice":
        for option in attribute["options"] or []:
            if isinstance(option, dict) and str(option.get("value")) == value["value_text"]:
                return localized(str(option.get("name", "")), option.get("names"), locale)

    return str(value["value_text"])


def variants_of(product_id: int) -> list[dict[str, Any]]:
    """Включённые варианты: цена и остаток каждого (остаток — за вычетом резерва)."""
    found = rows(
        "select id, options, sku, price, old_price, stock, reserved from market_product_variants "
        "where product_id = %s and is_active order by sort, id",
        [product_id],
    )

    return [
        {
            "id": v["id"],
            "options": v["options"] or {},
            "sku": v["sku"],
            "price": som(v["price"]),
            "oldPrice": som(v["old_price"]),
            "stock": max(0, int(v["stock"]) - int(v["reserved"])),
        }
        for v in found
    ]


def product(slug: str, locale: str, user_id: int | None = None) -> dict[str, Any] | None:
    """
    Карточка товара. Варианты — двумя видами: variants (что выбирать:
    «Цвет» — [«Чёрный», «Белый»], как в демо) и offers (каждое сочетание
    со своей ценой и остатком — их кладут в корзину).
    """
    row = one(
        f"select p.*, mc.slug as category_slug, c.slug as seller_slug, c.name as seller_name, "
        f"c.verification_level, c.rating as company_rating, c.logo_path {FROM} "
        f"where {VISIBLE} and p.slug = %s",
        [slug],
    )

    if row is None:
        return None

    images = rows(
        "select id, path, thumb_path, variant_id from market_product_images "
        "where product_id = %s order by sort, id",
        [row["id"]],
    )
    offers = variants_of(row["id"])
    choices: dict[str, list[str]] = {}

    for offer in offers:
        for name, value in offer["options"].items():
            picked = choices.setdefault(str(name), [])

            if str(value) not in picked:
                picked.append(str(value))

    attributes = {a["id"]: a for a in attributes_for(row["category_id"])}
    values = rows(
        "select attribute_id, value_text, value_number from market_product_values "
        "where product_id = %s",
        [row["id"]],
    )
    by_id = {v["attribute_id"]: v for v in values}
    specs = [
        [localized(a["name"], a["names"], locale), _value_text(by_id[a_id], a, locale)]
        for a_id, a in attributes.items()
        if a_id in by_id
    ]

    favorite = (
        user_id is not None
        and one(
            "select 1 as x from market_favorites where user_id = %s and product_id = %s",
            [user_id, row["id"]],
        )
        is not None
    )

    return {
        **card({**row, "cover": _cover(images)}),
        "images": [image_view(i) for i in images],
        "description": row["description"] or "",
        "locale": row["locale"],
        "variants": [{"name": name, "options": opts} for name, opts in choices.items()],
        "offers": offers,
        "specs": specs,
        "categoryPath": category_path(row["category_id"], locale),
        "sellerInfo": seller_card(
            {
                "slug": row["seller_slug"],
                "name": row["seller_name"],
                "verification_level": row["verification_level"],
                "rating": row["company_rating"],
                "logo_path": row["logo_path"],
            }
        ),
        "favorite": favorite,
    }


def seen(product_id: int) -> None:
    """Просмотр карточки — для сортировки «Популярные»."""
    write("update market_products set views_count = views_count + 1 where id = %s", [product_id])


# ── Страница продавца ───────────────────────────────────────────────


def seller(
    slug: str, query: Query, locale: str, user_id: int | None = None
) -> dict[str, Any] | None:
    """Витрина продавца: о компании и её товары с теми же фильтрами, что в каталоге."""
    company = one(
        "select c.* from market_sellers s join companies c on c.id = s.company_id "
        "where c.slug = %s and s.status = 'approved' and c.deleted_at is null "
        "and c.status = 'active'",
        [slug],
    )

    if company is None:
        return None

    listing = search(replace(query, seller=slug), locale, user_id)

    return {
        "seller": {
            **seller_card(company),
            "description": company["description"] or "",
            "since": company["created_at"].year if company["created_at"] else None,
            "company": f"/company/{company['slug']}",
        },
        **listing,
    }
