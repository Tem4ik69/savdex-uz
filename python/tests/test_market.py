"""
Маркетплейс, этап 1 (savdex/market): то, что ТЗ 18.11 требует проверить
в разделе «Как проверить».

- деньги — целыми тийинами, наружу — сумами; адрес каталога разбирается
  без ошибок на мусоре;
- права: модератор решает по продавцам и товарам, но не правит дерево
  категорий; финансам и продажам раздела нет;
- витрина показывает только товары «в продаже» у подтверждённых продавцов:
  черновик и товар заблокированного продавца не видны ни в каталоге, ни
  по прямой ссылке;
- каталог: категория с подразделами, характеристики, цена, подборки,
  сортировка, поиск по началу слова; подсказки;
- корзина — только со входом (гостю 401 и адрес входа), цена — с
  сервера, больше остатка не положить;
- «Стать продавцом»: без документа и оферты заявка не принимается,
  модератор подтверждает — кабинет продавца открыт, без этого — закрыт;
- первые N товаров нового продавца ждут модерации, следующие — сразу.

Нужен PostgreSQL (SAVDEX_PARITY_PG_URL).
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Iterator
from typing import Any

import pytest

from savdex import access, images
from savdex.market import products
from savdex.market.catalog import Query
from savdex.market.common import som, tiyin

from .pg_admin import django, sql, нужна_база, свежая_база, сотрудник
from .test_web_forms import xsrf, отправить
from .web_site import адрес, открыть

# ── Без базы ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("сумма", "тийины"),
    [
        ("125000", 12_500_000),
        ("125 000", 12_500_000),
        ("125000,50", 12_500_050),
        (99.5, 9_950),
        ("0", None),
        ("-5", None),
        ("1.001", None),
        ("abc", None),
        (True, None),
        (None, None),
        ("20000000000", None),
        ("NaN", None),
    ],
)
def test_деньги_в_тийинах(сумма, тийины):
    assert tiyin(сумма) == тийины


def test_фото_товара_строже_общего_предела():
    """Фото товара грузят по десять за раз: предел пикселей у рамки — 25 Мп, ниже общего."""
    assert products.PHOTO.max_pixels == 25_000_000 < images.MAX_PIXELS


def test_тийины_в_сумы():
    assert som(12_500_000) == 125_000
    assert som(12_500_050) == 125_000.5
    assert som(None) is None


def test_адрес_каталога():
    query = Query.parse(
        {
            "q": "  Galaxy  ",
            "category": "smartphones",
            "sort": "cheap",
            "only": "sale",
            "min": "100 000",
            "max": "5000000",
            "attr.color": "black, white",
            "attr.memory_min": "128",
            "attr.memory_max": "x",
            "attr.DROP;--": "1",
            "page": "999",
        }
    )

    assert (query.q, query.category, query.sort, query.only) == (
        "Galaxy",
        "smartphones",
        "cheap",
        "sale",
    )
    assert (query.min_price, query.max_price) == (10_000_000, 500_000_000)
    assert query.values == (("color", ("black", "white")),)
    assert query.ranges == (("memory", 128.0, None),)
    assert query.page == 100

    мусор = Query.parse({"sort": "price; drop", "only": "all", "page": "-3", "min": "дёшево"})
    assert (мусор.sort, мусор.only, мусор.page, мусор.min_price) == ("popular", "", 1, None)


def test_права_маркетплейса():
    модератор = access.abilities_for("moderator")
    assert {"market.view", "market.moderate"} <= set(модератор)
    assert "market_catalog.edit" not in модератор and "market_catalog.view" in модератор
    assert "market.delete" not in модератор

    assert {"market_catalog.view", "market_catalog.edit"} <= set(
        access.abilities_for("content_manager")
    )
    assert "market.view" not in access.abilities_for("content_manager")

    for роль in ("finance", "sales", "supplier_manager", "buyer_manager"):
        assert not [a for a in access.abilities_for(роль) if a.startswith("market")], роль

    assert "market.view" in access.abilities_for("support")
    assert "market.moderate" not in access.abilities_for("support")


# ── Данные ──────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def сайт() -> Iterator[str]:
    свежая_база()

    with адрес() as root:
        yield root


def _id(query: str, params: list[Any] | None = None) -> int:
    [(pk,)] = sql(query, params)

    return int(pk)


def _компания(name: str, slug: str, **поля: Any) -> int:
    columns = {
        "slug": slug,
        "name": name,
        "tin": "301234567",
        "status": "active",
        "verification_level": 0,
        **поля,
    }

    return _id(
        f"insert into companies ({', '.join(columns)}, created_at, updated_at) "
        f"values ({', '.join(['%s'] * len(columns))}, now(), now()) returning id",
        list(columns.values()),
    )


def _человек(email: str, company_id: int | None = None, role: str = "owner") -> int:
    return _id(
        "insert into users (name, email, password, status, company_id, company_role, "
        "email_verified_at, created_at, updated_at) values (%s, %s, 'x', 'active', %s, %s, "
        "now(), now(), now()) returning id",
        [f"Человек {email}", email, company_id, role],
    )


def _продавец(company_id: int, status: str = "approved") -> int:
    approved = status in ("approved", "blocked")

    return _id(
        "insert into market_sellers (company_id, status, verified_via, approved_at) "
        "values (%s, %s, %s, %s) returning id",
        [company_id, status, "documents" if approved else None, "2026-11-01" if approved else None],
    )


def _сотрудник(role: str) -> int:
    """Сотрудник админки — один на роль на весь модуль."""
    found = sql("select id from users where email = %s", [f"{role}@savdex.uz"])

    return int(found[0][0]) if found else сотрудник(role)


def _версия(table: str, pk: int) -> str:
    """
    Версия записи для решения модератора, как в форме решения: updated_at;
    у заявки продавца — ещё число и время документов компании.
    """
    if table == "market_products":
        from savdex.market.products import VERSION_SQL

        [(отпечаток,)] = sql(VERSION_SQL, [pk])

        return str(отпечаток)

    [(версия,)] = sql(
        f"select to_char(updated_at, 'YYYY-MM-DD HH24:MI:SS') from {table} where id = %s", [pk]
    )

    if table != "market_sellers":
        return str(версия)

    [(n, last)] = sql(
        "select count(*), coalesce(to_char(max(greatest(d.created_at, coalesce(d.updated_at, "
        "d.created_at))), 'YYYY-MM-DD HH24:MI:SS'), '') from company_documents d "
        "join market_sellers s on s.company_id = d.company_id where s.id = %s "
        "and d.type in ('registration', 'license', 'certificate', 'quality')",
        [pk],
    )

    return f"{версия}|{n}:{last}"


def _категория(slug: str) -> int:
    return _id("select id from market_categories where slug = %s", [slug])


def _товар(
    seller_id: int,
    category: str,
    title: str,
    slug: str,
    *,
    status: str = "active",
    price: int,
    old_price: int | None = None,
    stock: int = 5,
    sold: int = 0,
    days_ago: int = 30,
) -> tuple[int, int]:
    product = _id(
        "insert into market_products (seller_id, category_id, slug, title, description, status, "
        "ikpu, price, old_price, stock, sold_count, published_at, approved_at) "
        "values (%s, %s, %s, %s, %s, %s, '12345678901234567', %s, %s, %s, %s, "
        "(now() at time zone 'utc') - make_interval(days => %s), now()) returning id",
        [
            seller_id,
            _категория(category),
            slug,
            title,
            f"Описание: {title}",
            status,
            price * 100,
            old_price * 100 if old_price else None,
            stock,
            sold,
            days_ago,
        ],
    )
    variant = _id(
        "insert into market_product_variants (product_id, options, price, old_price, stock) "
        "values (%s, %s::jsonb, %s, %s, %s) returning id",
        [
            product,
            json.dumps({"Память": "128 ГБ"} if category == "smartphones" else {}),
            price * 100,
            old_price * 100 if old_price else None,
            0,
        ],
    )

    if stock:
        _на_склад(seller_id, product, variant, stock)

    return product, variant


#: Тестовый склад: остаток товаров приходит на него приёмкой поставки
СКЛАД = "test-sklad"


def _склад() -> int:
    """Тестовый склад и сотрудник, который принимает поставки, — один на базу."""
    sql(
        "insert into market_warehouses (code, name, address) "
        "values (%s, 'Тестовый склад', 'Ташкент') on conflict (code) do nothing",
        [СКЛАД],
    )
    [(склад,)] = sql("select id from market_warehouses where code = %s", [СКЛАД])

    return int(склад)


def _приёмщик() -> int:
    sql(
        "insert into users (name, email, password, status, created_at, updated_at) "
        "values ('Приёмщик', 'receiver@stock.example', 'x', 'active', now(), now()) "
        "on conflict do nothing"
    )
    [(uid,)] = sql("select id from users where email = 'receiver@stock.example'")

    return int(uid)


def _на_склад(seller_id: int, product: int, variant: int, quantity: int) -> None:
    """
    Остаток варианта — как в жизни: принятая поставка на тестовый склад и
    движение «receipt» (stock варианта двигает триггер базы).
    """
    склад, приёмщик = _склад(), _приёмщик()
    поставка = _id(
        "insert into market_supplies (number, seller_id, warehouse_id, status, submitted_at, "
        "received_at, received_by) values (%s, %s, %s, 'received', now(), now(), %s) "
        "returning id",
        [secrets.token_hex(6).upper(), seller_id, склад, приёмщик],
    )
    строка = _id(
        "insert into market_supply_items (supply_id, seller_id, product_id, variant_id, "
        "quantity_declared, quantity_accepted, quantity_defect) "
        "values (%s, %s, %s, %s, %s, %s, 0) returning id",
        [поставка, seller_id, product, variant, quantity, quantity],
    )
    sql(
        "insert into market_stock_movements (warehouse_id, variant_id, product_id, kind, "
        "quantity, supply_item_id, actor_user_id) values (%s, %s, %s, 'receipt', %s, %s, %s)",
        [склад, variant, product, quantity, строка, приёмщик],
    )


@pytest.fixture(scope="module")
def витрина(сайт) -> dict[str, Any]:
    """Два живых товара, черновик и товар заблокированного продавца."""
    электроника = _категория("electronics")
    смартфоны = _категория("smartphones")
    цвет = _id(
        "insert into market_attributes (category_id, key, name, names, kind, options) values "
        "(%s, 'color', 'Цвет', '{\"uz\": \"Rang\"}', 'choice', %s::jsonb) returning id",
        [
            электроника,
            json.dumps(
                [
                    {"value": "black", "name": "Чёрный", "names": {"uz": "Qora"}},
                    {"value": "white", "name": "Белый"},
                ],
                ensure_ascii=False,
            ),
        ],
    )
    память = _id(
        "insert into market_attributes (category_id, key, name, kind, unit) "
        "values (%s, 'memory', 'Память', 'number', 'ГБ') returning id",
        [смартфоны],
    )

    живая = _компания("Chorsu Tech", "chorsu-tech", verification_level=2)
    продавец = _продавец(живая)
    телефон, вариант_телефона = _товар(
        продавец, "smartphones", "Смартфон Galaxy A55", "galaxy-a55", price=4_000_000, sold=120
    )
    sql(
        "insert into market_product_values (product_id, attribute_id, value_text, value_number) "
        "values (%s, %s, 'black', null), (%s, %s, null, 128)",
        [телефон, цвет, телефон, память],
    )
    наушники, вариант_наушников = _товар(
        продавец,
        "headphones",
        "Наушники Air Buds",
        "air-buds",
        price=350_000,
        old_price=450_000,
        days_ago=2,
    )
    _товар(продавец, "laptops", "Ноутбук Черновик", "draft-laptop", status="draft", price=9_000_000)

    закрытая = _компания("Bolajon", "bolajon")
    _товар(_продавец(закрытая, "blocked"), "toys", "Кубики Bolajon", "bolajon-cubes", price=90_000)

    return {
        "телефон": телефон,
        "вариант_телефона": вариант_телефона,
        "наушники": наушники,
        "вариант_наушников": вариант_наушников,
        "продавец": продавец,
        "компания": живая,
    }


def _json(ответ: dict[str, Any]) -> Any:
    return json.loads(ответ["body"])


def _get(сайт: str, path: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
    return открыть(сайт, path, headers={"Accept": "application/json", **(headers or {})})


def _посетитель() -> dict[str, str]:
    """
    Свой гость (документационная сеть IPv6): отсев повторных просмотров —
    только наш. Гость IPv6 — это сеть /64, поэтому случайны первые 64 бита.
    """
    сеть = f"{secrets.randbelow(0xFFFF):x}:{secrets.randbelow(0xFFFF):x}"

    return {"X-Forwarded-For": f"2001:db8:{сеть}::1"}


def _премодерация(n: int) -> None:
    """Сколько первых товаров нового продавца — через модератора (0 — все продавцы проверенные)."""
    sql("delete from settings where key = 'market_premoderated_products'")
    sql(
        'insert into settings ("group", key, label, type, value, sort, created_at, updated_at) '
        "values ('market', 'market_premoderated_products', 'Первые товары', 'number', "
        "%s::json, 1, now(), now())",
        [str(n)],
    )


#: Заголовки запроса страницы маркетплейса: JSON, XHR и токен из куки
JSON = {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}


def _post(сайт: str, path: str, uid: int | None, body: Any = None) -> dict[str, Any]:
    return отправить(
        сайт,
        path,
        lambda: None,
        uid=uid,
        body=body if body is not None else {},
        headers={**JSON, "X-XSRF-TOKEN": xsrf()},
    )["ответ"]


def _get_as(сайт: str, path: str, uid: int) -> dict[str, Any]:
    return отправить(сайт, path, lambda: None, uid=uid, method="GET", headers=JSON)["ответ"]


# ── Витрина ─────────────────────────────────────────────────────────


@нужна_база
def test_дерево_категорий(сайт, витрина):
    русское = _json(_get(сайт, "/market/api/categories"))["categories"]
    узбекское = _json(_get(сайт, "/uz/market/api/categories"))["categories"]

    assert len(русское) == 12
    электроника = next(c for c in русское if c["slug"] == "electronics")
    assert электроника["name"] == "Электроника" and электроника["emoji"] == "📱"
    assert "smartphones" in [c["slug"] for c in электроника["children"]]
    assert next(c for c in узбекское if c["slug"] == "electronics")["name"] == "Elektronika"


@нужна_база
def test_видно_только_то_что_в_продаже(сайт, витрина):
    ответ = _get(сайт, "/market/api/catalog")
    каталог = _json(ответ)

    assert ответ["headers"]["x-robots-tag"] == "noindex, nofollow"
    assert {item["slug"] for item in каталог["items"]} == {"galaxy-a55", "air-buds"}
    assert каталог["total"] == 2

    for slug in ("draft-laptop", "bolajon-cubes", "nobody"):
        assert _get(сайт, f"/market/api/product/{slug}")["status"] == 404, slug

    assert _get(сайт, "/market/api/seller/bolajon")["status"] == 404


@нужна_база
def test_каталог_фильтры_сортировка_поиск(сайт, витрина):
    def slugs(query: str) -> list[str]:
        return [item["slug"] for item in _json(_get(сайт, f"/market/api/catalog?{query}"))["items"]]

    # Раздел показывает товары подразделов
    assert set(slugs("category=electronics")) == {"galaxy-a55", "air-buds"}
    assert slugs("category=smartphones&attr.color=black") == ["galaxy-a55"]
    assert slugs("category=smartphones&attr.color=white") == []
    assert slugs("category=smartphones&attr.memory_min=256") == []
    assert slugs("sort=cheap") == ["air-buds", "galaxy-a55"]
    assert slugs("sort=expensive") == ["galaxy-a55", "air-buds"]
    assert slugs("only=sale") == ["air-buds"]
    assert slugs("only=new") == ["air-buds"]
    assert slugs("only=hit") == ["galaxy-a55"]
    assert slugs("max=1000000") == ["air-buds"]
    assert slugs("q=galax") == ["galaxy-a55"]
    assert slugs("q=смартф") == ["galaxy-a55"]
    assert slugs("category=nope") == []
    # Избранное гостя — пусто, а не ошибка
    assert slugs("only=fav") == []

    смартфоны = _json(_get(сайт, "/market/api/catalog?category=smartphones"))
    фильтры = {f["key"]: f for f in смартфоны["filters"]}
    assert фильтры["color"]["options"] == [{"value": "black", "name": "Чёрный", "count": 1}]
    assert (фильтры["memory"]["min"], фильтры["memory"]["max"]) == (128.0, 128.0)
    assert [p["slug"] for p in смартфоны["category"]["path"]] == ["electronics", "smartphones"]

    карточки = {i["slug"]: i for i in _json(_get(сайт, "/market/api/catalog"))["items"]}
    assert карточки["air-buds"]["badge"] == "sale"
    assert (карточки["air-buds"]["price"], карточки["air-buds"]["oldPrice"]) == (350_000, 450_000)
    assert карточки["galaxy-a55"]["badge"] == "hit"
    assert карточки["galaxy-a55"]["seller"] == "chorsu-tech"


@нужна_база
def test_поиск_с_опечатками(сайт, витрина):
    """Полнотекстовый ничего не нашёл — похожие по написанию (pg_trgm), с пометкой fuzzy."""

    def found(query: str) -> tuple[list[str], bool]:
        ответ = _json(_get(сайт, f"/market/api/catalog?{query}"))
        return [item["slug"] for item in ответ["items"]], ответ["fuzzy"]

    # Обычный поиск — как был, без пометки
    assert found("q=galax") == (["galaxy-a55"], False)
    # Опечатки — находятся, с пометкой «похожие»
    assert found("q=смартфн") == (["galaxy-a55"], True)
    assert found("q=galxy") == (["galaxy-a55"], True)
    # Фильтры действуют и на похожие: в другом разделе — ничего
    assert found("q=смартфн&category=smartphones") == (["galaxy-a55"], True)
    assert found("q=смартфн&only=sale") == ([], False)
    # Случайное слово — ничего, а не всё подряд
    assert found("q=куртка") == ([], False)
    # Невидимые товары не всплывают и через похожие
    assert "draft-laptop" not in found("q=noutbuk")[0]
    # Порог похожести — 0.5 у самой базы (миграция): с порогом pg_trgm по
    # умолчанию 0.6 «samsng» не нашёл бы «Samsung» (0.57). Новое соединение —
    # как у сайта после релиза
    assert sql("show pg_trgm.word_similarity_threshold") == [("0.5",)]
    assert sql("select word_similarity('samsng', 'Samsung Galaxy A15') between 0.5 and 0.6") == [
        (True,)
    ]


@нужна_база
def test_подсказки(сайт, витрина):
    подсказки = _json(_get(сайт, "/market/api/suggest?q=gal"))
    assert подсказки["products"] == [{"slug": "galaxy-a55", "title": "Смартфон Galaxy A55"}]

    категории = _json(_get(сайт, "/market/api/suggest?q=смарт"))["categories"]
    assert {"slug": "smartphones", "name": "Смартфоны"} in категории

    assert _json(_get(сайт, "/market/api/suggest?q=%20%20")) == {"products": [], "categories": []}
    # Опечатка — тоже подсказка
    assert _json(_get(сайт, "/market/api/suggest?q=galxy"))["products"] == [
        {"slug": "galaxy-a55", "title": "Смартфон Galaxy A55"}
    ]


@нужна_база
def test_карточка_товара(сайт, витрина):
    sql("update market_products set views_count = 0 where id = %s", [витрина["телефон"]])
    гость = _посетитель()
    товар = _json(_get(сайт, "/market/api/product/galaxy-a55", гость))["product"]

    assert товар["price"] == 4_000_000 and товар["stock"] == 5
    assert товар["variants"] == [{"name": "Память", "options": ["128 ГБ"]}]
    assert товар["offers"][0]["id"] == витрина["вариант_телефона"]
    assert ["Цвет", "Чёрный"] in товар["specs"] and ["Память", "128 ГБ"] in товар["specs"]
    assert товар["sellerInfo"]["verified"] is True
    assert [p["slug"] for p in товар["categoryPath"]] == ["electronics", "smartphones"]
    assert товар["favorite"] is False
    assert sql("select views_count from market_products where id = %s", [витрина["телефон"]]) == [
        (1,)
    ]

    по_узбекски = _json(_get(сайт, "/uz/market/api/product/galaxy-a55", гость))["product"]
    assert ["Rang", "Qora"] in по_узбекски["specs"]

    # Тот же гость снова (и на другом языке) — сегодня уже засчитан:
    # обновлением страницы товар в «Популярные» не накрутить
    _get(сайт, "/market/api/product/galaxy-a55", гость)
    assert sql("select views_count from market_products where id = %s", [витрина["телефон"]]) == [
        (1,)
    ]
    # Другой посетитель — новый просмотр
    _get(сайт, "/market/api/product/galaxy-a55", _посетитель())
    assert sql("select views_count from market_products where id = %s", [витрина["телефон"]]) == [
        (2,)
    ]


@нужна_база
def test_страница_продавца(сайт, витрина):
    страница = _json(_get(сайт, "/market/api/seller/chorsu-tech?sort=cheap"))

    assert страница["seller"]["name"] == "Chorsu Tech"
    assert [i["slug"] for i in страница["items"]] == ["air-buds", "galaxy-a55"]


# ── Корзина и избранное ─────────────────────────────────────────────


@нужна_база
def test_корзина_гостю_вход(сайт, витрина):
    ответ = _post(сайт, "/market/api/cart/add", None, {"variantId": витрина["вариант_телефона"]})

    assert ответ["status"] == 401
    assert _json(ответ)["login"].endswith("/login")
    assert _get(сайт, "/market/api/cart")["status"] == 401


@нужна_база
def test_корзина_цена_с_сервера_и_остаток(сайт, витрина):
    покупатель = _человек("buyer@example.com")
    телефон = витрина["вариант_телефона"]
    sql("delete from market_cart_items where user_id = %s", [покупатель])

    # Цена из запроса ничего не значит
    положил = _post(
        сайт, "/market/api/cart/add", покупатель, {"variantId": телефон, "quantity": 2, "price": 1}
    )
    assert положил["status"] == 200, положил["body"]
    корзина = _json(положил)["cart"]
    assert корзина["total"] == 8_000_000 and корзина["count"] == 2
    assert корзина["parts"][0]["seller"]["slug"] == "chorsu-tech"

    # 2 + 4 больше остатка 5
    много = _post(сайт, "/market/api/cart/add", покупатель, {"variantId": телефон, "quantity": 4})
    assert много["status"] == 422
    assert "5" in _json(много)["message"]

    стало = _post(сайт, f"/market/api/cart/{телефон}", покупатель, {"quantity": 3})
    assert _json(стало)["cart"]["total"] == 12_000_000

    # Подорожал — в корзине новая цена
    sql("update market_product_variants set price = 410000000 where id = %s", [телефон])
    корзина = _json(_get_as(сайт, "/market/api/cart", покупатель))
    assert корзина["total"] == 12_300_000
    sql("update market_product_variants set price = 400000000 where id = %s", [телефон])

    черновик = sql(
        "select v.id from market_product_variants v join market_products p on p.id = v.product_id "
        "where p.slug = 'draft-laptop'"
    )[0][0]
    assert _post(сайт, "/market/api/cart/add", покупатель, {"variantId": черновик})["status"] == 404

    убрал = _post(сайт, f"/market/api/cart/{телефон}", покупатель, {"quantity": 0})
    assert _json(убрал)["cart"]["lines"] == 0


@нужна_база
def test_избранное(сайт, витрина):
    покупатель = _человек("fav@example.com")
    наушники = витрина["наушники"]

    assert _json(_post(сайт, f"/market/api/favorites/{наушники}", покупатель)) == {"favorite": True}
    assert _json(_get_as(сайт, "/market/api/favorites", покупатель)) == {"ids": [наушники]}
    каталог = _json(_get_as(сайт, "/market/api/catalog?only=fav", покупатель))
    assert [i["slug"] for i in каталог["items"]] == ["air-buds"]
    assert _json(_post(сайт, f"/market/api/favorites/{наушники}", покупатель)) == {
        "favorite": False
    }


# ── «Стать продавцом» и товары продавца ─────────────────────────────


@нужна_база
def test_заявка_продавца(сайт, витрина):
    компания = _компания("Usta Market", "usta-market")
    владелец = _человек("owner@usta.uz", компания)
    менеджер = _человек("manager@usta.uz", компания, role="manager")

    def заявка(uid: int, body: dict[str, Any]) -> dict[str, Any]:
        return _post(сайт, "/market/api/me/seller/apply", uid, body)

    без_документов = заявка(владелец, {"offer": True})
    assert без_документов["status"] == 422
    assert "документ" in _json(без_документов)["message"]

    sql(
        "insert into company_documents (company_id, type, title, file_path, created_at, "
        "updated_at) values (%s, 'registration', 'Свидетельство', 'docs/x.pdf', now(), now())",
        [компания],
    )

    assert заявка(менеджер, {"offer": True})["status"] == 422, "только владелец"
    assert заявка(владелец, {})["status"] == 422, "без оферты"

    подал = заявка(владелец, {"offer": True, "note": "Продаём инструменты"})
    assert подал["status"] == 200, подал["body"]
    assert _json(подал)["seller"]["status"] == "pending"
    assert sql(
        "select status, offer_version, note from market_sellers where company_id = %s", [компания]
    ) == [("pending", "draft-2026-11", "Продаём инструменты")]

    assert "уже" in _json(заявка(владелец, {"offer": True}))["message"]

    # Пока не подтверждён — кабинета продавца нет
    assert _get_as(сайт, "/market/api/me/products", владелец)["status"] == 403


@нужна_база
def test_первые_товары_на_модерации(сайт, витрина):
    компания = _компания("Oltin Vodiy", "oltin-vodiy")
    владелец = _человек("owner@oltin.uz", компания)
    продавец = _продавец(компания)
    sql("delete from settings where key = 'market_premoderated_products'")
    sql(
        'insert into settings ("group", key, label, type, value, sort, created_at, updated_at) '
        "values ('market', 'market_premoderated_products', 'Первые товары', 'number', "
        "'1'::json, 1, now(), now())"
    )

    товар = {
        "title": "Курага сушёная, 1 кг",
        "description": "Из Ферганы",
        "category": "dried-fruits-nuts",
        "variants": [{"price": "85 000", "oldPrice": 99000, "stock": 1000}],
    }

    раздел = _post(сайт, "/market/api/me/products/create", владелец, {**товар, "category": "food"})
    assert раздел["status"] == 422 and "category" in _json(раздел)["errors"], "только конечная"

    создал = _post(сайт, "/market/api/me/products/create", владелец, товар)
    assert создал["status"] == 201, создал["body"]
    первый = _json(создал)["product"]
    assert первый["status"] == "draft"
    # Остаток продавец не задаёт — он со склада
    assert первый["variants"][0]["stock"] == 0
    assert первый["variants"][0]["price"] == 85_000
    assert set(первый["missing"]) == {"ikpu", "images"}

    не_готов = _post(сайт, f"/market/api/me/products/{первый['id']}/submit", владелец)
    assert не_готов["status"] == 422 and set(_json(не_готов)["missing"]) == {"ikpu", "images"}

    правка = _post(
        сайт,
        f"/market/api/me/products/{первый['id']}",
        владелец,
        {
            **товар,
            "ikpu": "1234567890123456 7",
            "variants": [{**товар["variants"][0], "id": первый["variants"][0]["id"]}],
        },
    )
    assert правка["status"] == 200, правка["body"]
    sql(
        "insert into market_product_images (product_id, path) "
        "values (%s, 'market/products/a.webp')",
        [первый["id"]],
    )

    отправил = _post(сайт, f"/market/api/me/products/{первый['id']}/submit", владелец)
    assert _json(отправил)["status"] == "pending", "новый продавец — на модерацию"
    [(slug,)] = sql("select slug from market_products where id = %s", [первый["id"]])
    assert slug.startswith("kuraga-sushionaia-1-kg-")
    assert _get(сайт, f"/market/api/product/{slug}")["status"] == 404, "до проверки не виден"

    # Модератор одобряет — первый (и единственный по настройке) проверенный товар
    модератор = _сотрудник("moderator")
    адрес_товара = f"/py/admin/market/product/{первый['id']}/"
    версия = _версия("market_products", первый["id"])
    _, карточка, решение = django(
        модератор,
        ("get", адрес_товара + "change/", None),
        ("post", адрес_товара + "decide/", {"decision": "approve", "version": версия}),
    )
    assert карточка["status"] == 200 and "Одобрить" in карточка["body"]
    assert f'name="version" value="{версия}"' in карточка["body"]
    assert решение["status"] == 302
    assert sql("select status from market_products where id = %s", [первый["id"]]) == [("active",)]
    assert _get(сайт, f"/market/api/product/{slug}")["status"] == 200
    assert sql(
        "select action, section from admin_actions where subject_id = %s and section = 'market'",
        [первый["id"]],
    ) == [("approved", "market")]
    assert sql("select count(*) from user_notifications where user_id = %s", [владелец]) == [(1,)]

    # Второй товар того же продавца — сразу в продажу
    второй = _json(
        _post(
            сайт,
            "/market/api/me/products/create",
            владелец,
            {**товар, "title": "Изюм, 1 кг", "ikpu": "12345678901234567"},
        )
    )["product"]
    sql(
        "insert into market_product_images (product_id, path) "
        "values (%s, 'market/products/b.webp')",
        [второй["id"]],
    )
    сразу = _post(сайт, f"/market/api/me/products/{второй['id']}/submit", владелец)
    assert _json(сразу)["status"] == "active"

    # Чужой товар — как будто его нет
    чужой = _человек("owner@other.uz", _компания("Other", "other-co"))
    _продавец(sql("select company_id from users where id = %s", [чужой])[0][0])
    assert _post(сайт, f"/market/api/me/products/{первый['id']}/hide", чужой)["status"] == 404

    мои = _json(_get_as(сайт, "/market/api/me/products", владелец))["products"]
    assert {p["status"] for p in мои} == {"active"}
    assert продавец


@нужна_база
def test_админка_продавцов(сайт, витрина):
    компания = _компания("Guli Cosmetics", "guli-cosmetics")
    владелец = _человек("owner@guli.uz", компания)
    заявка = _продавец(компания, "pending")
    модератор = _сотрудник("moderator")
    финансы = _сотрудник("finance")
    адрес_заявки = f"/py/admin/market/seller/{заявка}/"

    _, список, без_причины, отказ = django(
        модератор,
        ("get", "/py/admin/market/seller/?status=pending", None),
        ("post", адрес_заявки + "decide/", {"decision": "reject", "note": "мало"}),
        (
            "post",
            адрес_заявки + "decide/",
            {
                "decision": "reject",
                "note": "Нет свидетельства о регистрации",
                "version": _версия("market_sellers", заявка),
            },
        ),
    )
    assert список["status"] == 200 and "Guli Cosmetics" in список["body"]
    assert sql("select status, reject_reason from market_sellers where id = %s", [заявка]) == [
        ("rejected", "Нет свидетельства о регистрации")
    ]
    assert без_причины["status"] == 302 and отказ["status"] == 302

    # Подал снова — модератор подтверждает
    sql("update market_sellers set status = 'pending' where id = %s", [заявка])
    django(
        модератор,
        (
            "post",
            адрес_заявки + "decide/",
            {"decision": "approve", "version": _версия("market_sellers", заявка)},
        ),
    )
    assert sql("select status, verified_via from market_sellers where id = %s", [заявка]) == [
        ("approved", "documents")
    ]
    assert _get_as(сайт, "/market/api/me/products", владелец)["status"] == 200

    _, чужим = django(финансы, ("get", "/py/admin/market/seller/", None))
    assert чужим["status"] == 403


@нужна_база
def test_остаток_вариантов_в_админке(сайт, витрина):
    """
    Модератор и поддержка видят варианты, остаток и остаток по складам —
    только смотреть: остаток приходит с приёмки и меняется движениями склада
    (test_market_stock.py). Финансам карточка закрыта.
    """
    компания = _компания("Stock Admin", "stock-admin")
    товар, вариант = _товар(_продавец(компания), "textile", "Плед", "pled", price=100_000)
    адрес_товара = f"/py/admin/market/product/{товар}/change/"

    for роль in ("moderator", "support"):
        _, страница = django(_сотрудник(роль), ("get", адрес_товара, None))
        assert страница["status"] == 200
        assert "Плед" in страница["body"] and "Тестовый склад: 5" in страница["body"]
        assert 'name="variants-0-stock"' not in страница["body"], роль

    _, финансам = django(_сотрудник("finance"), ("get", адрес_товара, None))
    assert финансам["status"] == 403
    assert вариант


@нужна_база
def test_остаток_в_карточке_не_пишется(сайт, витрина):
    """
    Правки остатка в карточке товара нет: присланное поле остатка ничего не
    меняет — ни остаток и резерв варианта, ни строку товара; строки журнала
    «остаток вариантов» нет.
    """
    компания = _компания("Stock Write", "stock-write")
    товар, вариант = _товар(
        _продавец(компания), "textile", "Покрывало", "pokryvalo", price=200_000, stock=5
    )
    sql("update market_product_variants set reserved = 2 where id = %s", [вариант])
    адрес_товара = f"/py/admin/market/product/{товар}/change/"
    версия = _версия("market_products", товар)

    _, ответ = django(
        _сотрудник("moderator"),
        (
            "post",
            адрес_товара,
            {
                "variants-TOTAL_FORMS": "1",
                "variants-INITIAL_FORMS": "1",
                "variants-MIN_NUM_FORMS": "0",
                "variants-MAX_NUM_FORMS": "1000",
                "variants-0-id": str(вариант),
                "variants-0-product": str(товар),
                "variants-0-stock": "9",
                "_save": "Сохранить",
            },
        ),
    )
    assert ответ["status"] in (200, 302, 403), ответ["body"][:2000]
    assert sql(
        "select stock, reserved, price from market_product_variants where id = %s", [вариант]
    ) == [(5, 2, 20_000_000)]
    assert _версия("market_products", товар) == версия
    assert sql(
        "select count(*) from admin_actions where subject_id = %s and note = 'остаток вариантов'",
        [товар],
    ) == [(0,)]


@нужна_база
def test_решение_по_той_версии_что_видел_модератор(сайт, витрина):
    """
    Товар или заявка изменились после того, как модератор открыл карточку, —
    решение не принимается: продавец не подменит товар под «Одобрить».
    """
    модератор = _сотрудник("moderator")
    товар, _ = _товар(
        _продавец(_компания("Toctou Shop", "toctou-shop")),
        "textile",
        "Скатерть",
        "skatert",
        status="pending",
        price=150_000,
    )
    sql("update market_products set updated_at = '2026-11-01 10:00:00' where id = %s", [товар])
    адрес_товара = f"/py/admin/market/product/{товар}/"

    увиденная = _версия("market_products", товар)
    assert увиденная.startswith("2026-11-01 10:00:00|")
    _, карточка = django(модератор, ("get", адрес_товара + "change/", None))
    assert f'name="version" value="{увиденная}"' in карточка["body"]

    # Продавец поменял товар в ту же секунду — время то же, отпечаток другой
    sql("update market_products set title = 'Подменённая скатерть' where id = %s", [товар])
    assert _версия("market_products", товар) != увиденная
    assert _версия("market_products", товар).startswith("2026-11-01 10:00:00|")
    _, по_старой, без_версии = django(
        модератор,
        (
            "post",
            адрес_товара + "decide/",
            {"decision": "approve", "version": увиденная},
        ),
        ("post", адрес_товара + "decide/", {"decision": "approve"}),
    )
    assert по_старой["status"] == 302 and без_версии["status"] == 302
    assert sql("select status from market_products where id = %s", [товар]) == [("pending",)]
    assert sql(
        "select count(*) from admin_actions where subject_type = %s and subject_id = %s",
        ["Savdex\\Market\\Product", товар],
    ) == [(0,)]

    django(
        модератор,
        (
            "post",
            адрес_товара + "decide/",
            {"decision": "approve", "version": _версия("market_products", товар)},
        ),
    )
    assert sql("select status from market_products where id = %s", [товар]) == [("active",)]

    # Заявка продавца — так же, по времени её правки
    заявка = _продавец(_компания("Toctou Seller", "toctou-seller"), "pending")
    sql("update market_sellers set updated_at = '2026-11-01 11:00:00' where id = %s", [заявка])
    адрес_заявки = f"/py/admin/market/seller/{заявка}/decide/"

    django(
        модератор,
        ("post", адрес_заявки, {"decision": "approve", "version": "2026-11-01 10:59:59|0:"}),
    )
    assert sql("select status from market_sellers where id = %s", [заявка]) == [("pending",)]

    # Компания заменила документ, пока модератор смотрел, — заявка та же, а
    # версия другая: одобрение по старой не проходит
    увиденная = _версия("market_sellers", заявка)
    assert увиденная == "2026-11-01 11:00:00|0:"
    sql(
        "insert into company_documents (company_id, type, title, file_path, created_at, "
        "updated_at) select company_id, 'registration', 'Свидетельство', 'docs/y.pdf', "
        "'2026-11-01 11:01:00', '2026-11-01 11:01:00' from market_sellers where id = %s",
        [заявка],
    )
    django(модератор, ("post", адрес_заявки, {"decision": "approve", "version": увиденная}))
    assert sql("select status from market_sellers where id = %s", [заявка]) == [("pending",)]

    django(
        модератор,
        (
            "post",
            адрес_заявки,
            {"decision": "approve", "version": _версия("market_sellers", заявка)},
        ),
    )
    assert sql("select status from market_sellers where id = %s", [заявка]) == [("approved",)]

    # Запретить можно и без версии: правка продавца не мешает снять товар
    sql("update market_products set updated_at = '2026-11-01 12:00:00' where id = %s", [товар])
    django(
        модератор,
        (
            "post",
            адрес_товара + "decide/",
            {"decision": "block", "note": "Подделка известного бренда", "version": "старая"},
        ),
    )
    assert sql("select status from market_products where id = %s", [товар]) == [("blocked",)]


@нужна_база
def test_характеристики_в_админке_категорий(сайт, витрина):
    """
    Характеристики категории видны и правятся по правам раздела
    «market_catalog», правка попадает в журнал, а удалить заполненную у
    товаров характеристику нельзя — каскад стёр бы значения.
    """
    категория = _id(
        "insert into market_categories (slug, name, sort) "
        "values ('attr-admin', 'Проверка характеристик', 990) returning id"
    )
    размер = _id(
        "insert into market_attributes (category_id, key, name, kind) "
        "values (%s, 'size', 'Размер', 'text') returning id",
        [категория],
    )
    оттенок = _id(
        "insert into market_attributes (category_id, key, name, kind) "
        "values (%s, 'shade', 'Оттенок', 'text') returning id",
        [категория],
    )
    sql(
        "insert into market_product_values (product_id, attribute_id, value_text) "
        "values (%s, %s, 'XL')",
        [витрина["наушники"], размер],
    )
    адрес_категории = f"/py/admin/market/category/{категория}/change/"

    def форма(**правка: str) -> dict[str, str]:
        поля = {
            "parent": "",
            "slug": "attr-admin",
            "name": "Проверка характеристик",
            "name_uz": "",
            "name_en": "",
            "icon": "",
            "sort": "990",
            "is_active": "on",
            "attributes-TOTAL_FORMS": "2",
            "attributes-INITIAL_FORMS": "2",
            "attributes-MIN_NUM_FORMS": "0",
            "attributes-MAX_NUM_FORMS": "1000",
        }

        for i, (pk, key, name) in enumerate(
            [(размер, "size", "Размер"), (оттенок, "shade", "Оттенок")]
        ):
            поля |= {
                f"attributes-{i}-id": str(pk),
                f"attributes-{i}-category": str(категория),
                f"attributes-{i}-key": key,
                f"attributes-{i}-name": name,
                f"attributes-{i}-kind": "text",
                f"attributes-{i}-unit": "",
                f"attributes-{i}-options": "[]",
                f"attributes-{i}-is_filter": "on",
                f"attributes-{i}-sort": "0",
            }

        return поля | правка

    def журнал_категории() -> dict[str, Any]:
        [(изменения,)] = sql(
            "select changes from admin_actions where subject_type = %s and subject_id = %s "
            "order by id desc limit 1",
            ["Savdex\\Market\\Category", категория],
        )

        return dict(json.loads(изменения) if isinstance(изменения, str) else изменения)

    try:
        контент = _сотрудник("content_manager")
        _, редактору, правка = django(
            контент,
            ("get", адрес_категории, None),
            ("post", адрес_категории, форма(**{"attributes-0-is_required": "on"})),
        )
        assert редактору["status"] == 200
        assert 'name="attributes-TOTAL_FORMS"' in редактору["body"]
        assert 'name="attributes-0-key"' in редактору["body"]
        assert 'name="attributes-0-DELETE"' not in редактору["body"], "удалять — не редактору"
        assert правка["status"] == 302, правка["body"][:3000]
        assert sql("select is_required from market_attributes where id = %s", [размер]) == [(True,)]
        изменения = журнал_категории()
        assert изменения["before"]["attributes"][0] == {
            "key": "size",
            "kind": "text",
            "options": [],
            "is_required": False,
        }
        assert изменения["after"]["attributes"][0]["is_required"] is True

        _, модератору = django(_сотрудник("moderator"), ("get", адрес_категории, None))
        assert модератору["status"] == 200 and "Оттенок" in модератору["body"]
        assert 'name="attributes-0-key"' not in модератору["body"], "модератор только смотрит"

        главный = _сотрудник("superadmin")
        _, заполненную, пустую = django(
            главный,
            (
                "post",
                адрес_категории,
                форма(**{"attributes-0-is_required": "on", "attributes-0-DELETE": "on"}),
            ),
            (
                "post",
                адрес_категории,
                форма(**{"attributes-0-is_required": "on", "attributes-1-DELETE": "on"}),
            ),
        )
        assert заполненную["status"] == 200
        assert "Нельзя удалить характеристику" in заполненную["body"]
        assert пустую["status"] == 302, пустую["body"][:3000]
        assert sql("select id from market_attributes where category_id = %s", [категория]) == [
            (размер,)
        ]
        assert sql(
            "select value_text from market_product_values where attribute_id = %s", [размер]
        ) == [("XL",)]
        удаление = журнал_категории()
        assert [a["key"] for a in удаление["before"]["attributes"]] == ["size", "shade"]
        assert [a["key"] for a in удаление["after"]["attributes"]] == ["size"]
    finally:
        sql("delete from market_product_values where attribute_id = %s", [размер])
        sql("delete from market_attributes where category_id = %s", [категория])
        sql("delete from market_categories where id = %s", [категория])


@нужна_база
def test_роль_сайта_не_удаляет_продавцов_и_товары(сайт):
    """Продавцов, товары и варианты сайт не удаляет — права DELETE у его роли нет."""
    if not sql("select 1 from pg_roles where rolname = 'savdex_django'"):
        pytest.skip("нет роли savdex_django")

    for таблица in ("market_sellers", "market_products", "market_product_variants"):
        assert sql("select has_table_privilege('savdex_django', %s, 'DELETE')", [таблица]) == [
            (False,)
        ], таблица

    # Корзину и фото сайт удаляет штатно
    for таблица in ("market_cart_items", "market_product_images", "market_product_values"):
        assert sql("select has_table_privilege('savdex_django', %s, 'DELETE')", [таблица]) == [
            (True,)
        ], таблица


@нужна_база
def test_фото_товара(сайт, витрина):
    """
    Фото пересобирается в WebP на публичном диске, рядом — уменьшенная
    копия для каталога; фото можно привязать к варианту своего товара, но не
    чужого; не картинка — 422; удаление стирает оба файла.
    """
    from pathlib import Path

    from PIL import Image

    from .pg_admin import КОРЕНЬ
    from .test_web_company_profile_actions import multipart, картинка

    компания = _компания("Samarqand Tekstil", "samarqand-tekstil")
    владелец = _человек("owner@tekstil.uz", компания)
    продавец = _продавец(компания)
    товар, вариант = _товар(
        продавец, "textile", "Сюзане ручной работы", "suzani", status="draft", price=900_000
    )
    диск = Path(КОРЕНЬ) / "storage/app/public"

    def загрузить(имя: str, данные: bytes, variant: int | None = None) -> dict[str, Any]:
        поля: dict[str, Any] = {"file": (имя, данные)}

        if variant is not None:
            поля["variantId"] = str(variant)

        тело, тип = multipart(поля)

        return отправить(
            сайт,
            f"/market/api/me/products/{товар}/images",
            lambda: None,
            uid=владелец,
            body=тело,
            content_type=тип,
            headers={**JSON, "X-XSRF-TOKEN": xsrf()},
        )["ответ"]

    assert загрузить("fake.png", b"not an image")["status"] == 422
    # Вариант чужого товара — нельзя
    assert загрузить("photo.png", картинка(800, 800), витрина["вариант_телефона"])["status"] == 422

    ответ = загрузить("photo.png", картинка(2400, 1200))
    assert ответ["status"] == 201, ответ["body"]
    [фото] = _json(ответ)["product"]["images"]
    [(путь, копия)] = sql(
        "select path, thumb_path from market_product_images where product_id = %s", [товар]
    )
    файлы = [диск / путь, диск / копия]

    try:
        assert путь.startswith("market/products/") and путь.endswith(".webp")
        assert копия.startswith("market/products/thumbs/") and копия.endswith(".webp")
        assert all(f.exists() for f in файлы)
        with Image.open(файлы[1]) as маленькая:
            assert max(маленькая.size) == 480
        assert фото["url"].endswith(путь) and фото["thumb"].endswith(копия)
        assert фото["variantId"] is None

        # Фото — варианту и обратно общим
        стало = _post(
            сайт,
            f"/market/api/me/products/{товар}/images/{фото['id']}/variant",
            владелец,
            {"variantId": вариант},
        )
        assert _json(стало)["product"]["images"][0]["variantId"] == вариант
        чужой = _post(
            сайт,
            f"/market/api/me/products/{товар}/images/{фото['id']}/variant",
            владелец,
            {"variantId": витрина["вариант_телефона"]},
        )
        assert чужой["status"] == 422
        общее = _post(
            сайт,
            f"/market/api/me/products/{товар}/images/{фото['id']}/variant",
            владелец,
            {"variantId": None},
        )
        assert _json(общее)["product"]["images"][0]["variantId"] is None

        убрал = _post(сайт, f"/market/api/me/products/{товар}/images/{фото['id']}/delete", владелец)
        assert убрал["status"] == 200 and _json(убрал)["product"]["images"] == []
        assert not any(f.exists() for f in файлы)
    finally:
        for файл in файлы:
            файл.unlink(missing_ok=True)


@нужна_база
def test_фото_не_больше_предела(сайт, витрина):
    """Одиннадцатое фото — 422, файлы на диске не остаются; не картинка — 422."""
    from pathlib import Path

    from savdex.market.products import MAX_IMAGES

    from .pg_admin import КОРЕНЬ
    from .test_web_company_profile_actions import multipart, картинка

    компания = _компания("Foto Limit", "foto-limit")
    владелец = _человек("owner@foto-limit.uz", компания)
    товар, _ = _товар(
        _продавец(компания), "textile", "Ковёр", "kovyor", status="draft", price=500_000
    )
    for номер in range(MAX_IMAGES):
        sql(
            "insert into market_product_images (product_id, path, thumb_path, sort) "
            "values (%s, %s, %s, %s)",
            [
                товар,
                f"market/products/x{номер}.webp",
                f"market/products/thumbs/x{номер}.webp",
                номер,
            ],
        )
    диск = Path(КОРЕНЬ) / "storage/app/public/market/products"
    было = set(диск.rglob("*.webp")) if диск.exists() else set()

    тело, тип = multipart({"file": ("photo.png", картинка(800, 800))})
    ответ = отправить(
        сайт,
        f"/market/api/me/products/{товар}/images",
        lambda: None,
        uid=владелец,
        body=тело,
        content_type=тип,
        headers={**JSON, "X-XSRF-TOKEN": xsrf()},
    )["ответ"]

    assert ответ["status"] == 422, ответ["body"]
    assert sql("select count(*) from market_product_images where product_id = %s", [товар]) == [
        (MAX_IMAGES,)
    ]
    assert (set(диск.rglob("*.webp")) if диск.exists() else set()) == было


@нужна_база
def test_характеристика_да_нет(сайт, витрина):
    """Тип bool: значение '1' / '0', в карточке — «Да» / «Нет», фильтр attr.<код>=1."""
    наушники = _категория("headphones")
    признак = _id(
        "insert into market_attributes (category_id, key, name, names, kind) values "
        "(%s, 'wireless', 'Беспроводные', '{\"uz\": \"Simsiz\"}', 'bool') returning id",
        [наушники],
    )
    sql(
        "insert into market_product_values (product_id, attribute_id, value_text) "
        "values (%s, %s, '1')",
        [витрина["наушники"], признак],
    )

    try:
        товар = _json(_get(сайт, "/market/api/product/air-buds"))["product"]
        assert ["Беспроводные", "Да"] in товар["specs"]
        assert ["Simsiz", "Ha"] in _json(_get(сайт, "/uz/market/api/product/air-buds"))["product"][
            "specs"
        ]

        def slugs(query: str) -> list[str]:
            ответ = _json(_get(сайт, f"/market/api/catalog?category=headphones&{query}"))
            return [i["slug"] for i in ответ["items"]]

        assert slugs("attr.wireless=1") == ["air-buds"]
        assert slugs("attr.wireless=0") == []
        фильтры = {
            f["key"]: f
            for f in _json(_get(сайт, "/market/api/catalog?category=headphones"))["filters"]
        }
        assert фильтры["wireless"]["options"] == [{"value": "1", "name": "Да", "count": 1}]

        # Продавец: «да» / «нет» словами и неизвестное значение
        компания = _компания("Air Shop", "air-shop")
        владелец = _человек("owner@air.uz", компания)
        _продавец(компания)
        товар_продавца = {
            "title": "Наушники с проводом",
            "category": "headphones",
            "variants": [{"price": 99000}],
        }
        нет = _post(
            сайт,
            "/market/api/me/products/create",
            владелец,
            {**товар_продавца, "values": {"wireless": "нет"}},
        )
        assert нет["status"] == 201, нет["body"]
        assert _json(нет)["product"]["values"] == {"wireless": False}
        мусор = _post(
            сайт,
            "/market/api/me/products/create",
            владелец,
            {**товар_продавца, "values": {"wireless": "может быть"}},
        )
        assert мусор["status"] == 422 and "values.wireless" in _json(мусор)["errors"]
    finally:
        sql("delete from market_product_values where attribute_id = %s", [признак])
        sql("delete from market_attributes where id = %s", [признак])


@нужна_база
def test_убранный_вариант_не_удаляется(сайт, витрина):
    """Вариант, который продавец убрал, выключается и помечается — строки остаются для заказов."""
    компания = _компания("Variant Shop", "variant-shop")
    владелец = _человек("owner@variant.uz", компания)
    _продавец(компания)
    товар = {
        "title": "Футболка хлопковая",
        "category": "men-clothes",
        "variants": [
            {"options": {"Размер": "M"}, "price": 120000},
            {"options": {"Размер": "L"}, "price": 125000},
        ],
    }
    создал = _json(_post(сайт, "/market/api/me/products/create", владелец, товар))["product"]
    средний, большой = создал["variants"]
    покупатель = _человек("buyer-variant@example.com")
    sql(
        "insert into market_cart_items (user_id, variant_id, quantity) values (%s, %s, 1)",
        [покупатель, большой["id"]],
    )

    правка = _post(
        сайт,
        f"/market/api/me/products/{создал['id']}",
        владелец,
        {**товар, "variants": [{**товар["variants"][0], "id": средний["id"]}]},
    )
    assert правка["status"] == 200, правка["body"]
    assert [v["id"] for v in _json(правка)["product"]["variants"]] == [средний["id"]]
    assert sql(
        "select is_active, options ? '_removed' from market_product_variants where id = %s",
        [большой["id"]],
    ) == [(False, True)]
    assert sql("select count(*) from market_cart_items where variant_id = %s", [большой["id"]]) == [
        (0,)
    ]


# ── Модерация и проверки формы товара ───────────────────────────────


@нужна_база
def test_отклонённый_и_снятый_товар_только_через_модератора(сайт, витрина):
    """
    Проверенный продавец (премодерация выключена) отправляет сразу в продажу
    только то, что модератор не убирал: отклонённый и возвращённый после
    снятия товар идёт на проверку, а снятый самим продавцом — сразу назад.
    """
    _премодерация(0)
    компания = _компания("Toshkent Bodom", "toshkent-bodom")
    владелец = _человек("owner@bodom.uz", компания)
    продавец = _продавец(компания)
    товар, _ = _товар(
        продавец,
        "dried-fruits-nuts",
        "Миндаль жареный",
        "almond-roasted",
        status="rejected",
        price=120_000,
    )
    sql(
        "update market_products set reject_reason = 'На фото другой товар, не миндаль' "
        "where id = %s",
        [товар],
    )
    sql(
        "insert into market_product_images (product_id, path) "
        "values (%s, 'market/products/c.webp')",
        [товар],
    )
    модератор = _сотрудник("moderator")
    решение = f"/py/admin/market/product/{товар}/decide/"

    def на_продажу() -> str:
        ответ = _post(сайт, f"/market/api/me/products/{товар}/submit", владелец)
        assert ответ["status"] == 200, ответ["body"]

        return str(_json(ответ)["status"])

    def статус() -> tuple[str, bool]:
        [(status, причина)] = sql(
            "select status, reject_reason is not null from market_products where id = %s", [товар]
        )

        return status, причина

    assert на_продажу() == "pending", "отклонённый — через модератора"
    assert статус() == ("pending", True)

    def решить(decision: str, **поля: str) -> None:
        """Решение по той версии товара, что сейчас в базе (как в карточке)."""
        версия = _версия("market_products", товар)
        django(модератор, ("post", решение, {"decision": decision, "version": версия, **поля}))

    решить("approve")
    assert статус() == ("active", False)

    решить("block", note="Жалоба покупателя на подделку")
    решить("unblock")
    assert статус() == ("draft", True), "причина снятия остаётся продавцу"
    assert на_продажу() == "pending", "возвращённый после снятия — через модератора"

    решить("approve")
    assert _post(сайт, f"/market/api/me/products/{товар}/hide", владелец)["status"] == 200
    assert статус() == ("hidden", False)
    assert на_продажу() == "active", "снятый самим продавцом — сразу назад"


@нужна_база
def test_после_отказа_копия_товара_тоже_через_модератора(сайт, витрина):
    """Проверенному продавцу отказали — новые товары месяц идут через модератора."""
    _премодерация(0)
    компания = _компания("Nusxa Savdo", "nusxa-savdo")
    владелец = _человек("owner@nusxa.uz", компания)
    продавец = _продавец(компания)
    форма = {
        "title": "Миндаль отборный",
        "description": "Как у известного бренда",
        "category": "dried-fruits-nuts",
        "ikpu": "12345678901234567",
        "variants": [{"price": "150000"}],
    }

    def новый_в_продажу() -> str:
        создал = _post(сайт, "/market/api/me/products/create", владелец, форма)
        assert создал["status"] == 201, создал["body"]
        товар = _json(создал)["product"]["id"]
        sql(
            "insert into market_product_images (product_id, path) values (%s, %s)",
            [товар, f"market/products/n{товар}.webp"],
        )
        ответ = _post(сайт, f"/market/api/me/products/{товар}/submit", владелец)
        assert ответ["status"] == 200, ответ["body"]

        return str(_json(ответ)["status"])

    assert новый_в_продажу() == "active", "проверенный продавец — сразу"

    отклонённый, _ = _товар(
        продавец,
        "dried-fruits-nuts",
        "Миндаль-подделка",
        "fake-almond",
        status="rejected",
        price=150_000,
    )
    sql(
        "update market_products set reject_reason = 'Подделка известного бренда', "
        "moderated_at = (now() at time zone 'utc') - interval '2 days' where id = %s",
        [отклонённый],
    )
    assert новый_в_продажу() == "pending", "копия отклонённого — через модератора"

    sql(
        "update market_products set moderated_at = (now() at time zone 'utc') - "
        "interval '40 days' where id = %s",
        [отклонённый],
    )
    assert новый_в_продажу() == "active", "отказ давний — снова сразу"


@нужна_база
def test_правка_вариантов_у_нового_продавца_возвращает_в_черновик(сайт, витрина):
    """Название варианта и артикул — тоже содержание; цена — нет."""
    _премодерация(100)
    компания = _компания("Yangi Savdo", "yangi-savdo")
    владелец = _человек("owner@yangi.uz", компания)
    продавец = _продавец(компания)
    товар, вариант = _товар(
        продавец, "men-clothes", "Рубашка льняная", "linen-shirt", price=200_000
    )
    форма = {
        "title": "Рубашка льняная",
        "description": "Описание: Рубашка льняная",
        "category": "men-clothes",
        "ikpu": "12345678901234567",
    }

    def правка(**поля: Any) -> str:
        sql("update market_products set status = 'active' where id = %s", [товар])
        ответ = _post(
            сайт,
            f"/market/api/me/products/{товар}",
            владелец,
            {**форма, "variants": [{"id": вариант, "price": 200000, **поля}]},
        )
        assert ответ["status"] == 200, ответ["body"]

        return str(_json(ответ)["product"]["status"])

    assert правка() == "active", "ничего не поменялось"
    assert правка(price=210000) == "active", "цена статус не меняет"
    assert правка(price=210000, options={"Цвет": "Красный"}) == "draft", "новое название варианта"
    assert правка(price=210000, options={"Цвет": "Красный"}, sku="LN-RED-42") == "draft", (
        "новый артикул"
    )


@нужна_база
def test_цена_товара_с_варианта_который_можно_купить(сайт, витрина):
    """
    В строке товара (каталог, сортировка по цене) — цена самого дешёвого
    варианта, который есть на складе; нет ни одного — самого дешёвого.
    Дешевле 100 сумов форма не примет.
    """
    компания = _компания("Narx Shop", "narx-shop")
    владелец = _человек("owner@narx.uz", компания)
    _продавец(компания)
    товар = {
        "title": "Кроссовки беговые",
        "category": "men-clothes",
        "variants": [
            {"options": {"Размер": "41"}, "price": 300000},
            {"options": {"Размер": "42"}, "price": 350000},
        ],
    }

    дёшево = _post(
        сайт, "/market/api/me/products/create", владелец, {**товар, "variants": [{"price": "50"}]}
    )
    assert дёшево["status"] == 422 and "variants.0.price" in _json(дёшево)["errors"]

    создал = _post(сайт, "/market/api/me/products/create", владелец, товар)
    assert создал["status"] == 201, создал["body"]
    карточка = _json(создал)["product"]
    малый, большой = карточка["variants"]

    def цена_после_правки() -> tuple[int, int]:
        правка = _post(
            сайт,
            f"/market/api/me/products/{карточка['id']}",
            владелец,
            {
                **товар,
                "variants": [
                    {**товар["variants"][0], "id": малый["id"]},
                    {**товар["variants"][1], "id": большой["id"]},
                ],
            },
        )
        assert правка["status"] == 200, правка["body"]
        [(price, stock)] = sql(
            "select price, stock from market_products where id = %s", [карточка["id"]]
        )

        return price, stock

    assert цена_после_правки() == (30_000_000, 0), "склад пуст — самый дешёвый"
    sql("update market_product_variants set stock = 3 where id = %s", [большой["id"]])
    assert цена_после_правки() == (35_000_000, 3), "есть только 42-й — его цена"
    sql("update market_product_variants set reserved = 3 where id = %s", [большой["id"]])
    assert цена_после_правки() == (30_000_000, 0), "всё отложено под заказы — самый дешёвый"


@нужна_база
def test_ошибки_формы_товара_422_а_не_500(сайт, витрина):
    """То, что раньше доходило до ограничений базы (500), — ошибка формы или сохранение."""
    _премодерация(0)
    компания = _компания("Xato Shop", "xato-shop")
    владелец = _человек("owner@xato.uz", компания)
    продавец = _продавец(компания)
    товар = {
        "title": "Свитер шерстяной",
        "category": "men-clothes",
        "variants": [
            {"options": {"Размер": "M"}, "price": 150000},
            {"options": {"Размер": "L"}, "price": 160000},
        ],
    }

    # Арабские цифры — не цифры ИКПУ и штрихкода: поле пустое, а не 500
    # от market_products_ikpu_check
    арабские = _post(
        сайт,
        "/market/api/me/products/create",
        владелец,
        {**товар, "ikpu": "١٢٣٤٥٦٧٨٩٠١٢٣٤٥٦٧", "barcode": "١٢٣٤٥٦٧٨"},
    )
    assert арабские["status"] == 201, арабские["body"]
    создал = _json(арабские)["product"]
    assert (создал["ikpu"], создал["barcode"]) == (None, None)

    # Убрал L и в том же запросе добавил L заново (без id) — новый вариант,
    # а не 500 от уникальности (product_id, options)
    средний, большой = создал["variants"]
    заново = _post(
        сайт,
        f"/market/api/me/products/{создал['id']}",
        владелец,
        {
            **товар,
            "variants": [{**товар["variants"][0], "id": средний["id"]}, товар["variants"][1]],
        },
    )
    assert заново["status"] == 200, заново["body"]
    новый = _json(заново)["product"]["variants"][1]
    assert новый["id"] != большой["id"] and новый["options"] == {"Размер": "L"}
    assert sql(
        "select options ? '_removed' from market_product_variants where id = %s", [большой["id"]]
    ) == [(True,)]

    # Товар в продаже: выключить все варианты или стереть ИКПУ — ошибка
    # формы, а не 500 от market_products_active_check
    живой, вариант = _товар(
        продавец, "men-clothes", "Свитер в продаже", "sweater-live", price=150_000
    )
    форма = {
        "title": "Свитер в продаже",
        "description": "Описание: Свитер в продаже",
        "category": "men-clothes",
        "ikpu": "12345678901234567",
    }
    выключил = _post(
        сайт,
        f"/market/api/me/products/{живой}",
        владелец,
        {**форма, "variants": [{"id": вариант, "price": 150000, "active": False}]},
    )
    assert выключил["status"] == 422 and "variants" in _json(выключил)["errors"]
    без_икпу = _post(
        сайт,
        f"/market/api/me/products/{живой}",
        владелец,
        {**форма, "ikpu": "", "variants": [{"id": вариант, "price": 150000}]},
    )
    assert без_икпу["status"] == 422 and "ikpu" in _json(без_икпу)["errors"]
    assert sql("select status, price from market_products where id = %s", [живой]) == [
        ("active", 15_000_000)
    ]

    # Товар на проверке: без ИКПУ модератор не смог бы его одобрить — тоже ошибка
    sql("update market_products set status = 'pending' where id = %s", [живой])
    на_проверке = _post(
        сайт,
        f"/market/api/me/products/{живой}",
        владелец,
        {**форма, "ikpu": "", "variants": [{"id": вариант, "price": 150000}]},
    )
    assert на_проверке["status"] == 422 and "ikpu" in _json(на_проверке)["errors"]
    assert sql("select ikpu from market_products where id = %s", [живой]) == [
        ("12345678901234567",)
    ]


@pytest.mark.parametrize(
    ("адрес", "гость"),
    [
        ("203.0.113.7", "203.0.113.7"),
        ("2001:db8:1:2:aaaa::1", "2001:db8:1:2::/64"),
        ("2001:db8:1:2:bbbb::9", "2001:db8:1:2::/64"),
        ("не адрес", "не адрес"),
    ],
)
def test_гость_для_просмотров_ipv6_по_сети(monkeypatch, адрес, гость):
    from savdex.market import api

    monkeypatch.setattr(api, "client_ip", lambda request: адрес)

    assert api._visitor_net(None) == гость  # type: ignore[arg-type]
