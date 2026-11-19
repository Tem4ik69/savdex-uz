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
from collections.abc import Iterator
from typing import Any

import pytest

from savdex import access
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
            stock,
        ],
    )

    return product, variant


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


def _get(сайт: str, path: str) -> dict[str, Any]:
    return открыть(сайт, path, headers={"Accept": "application/json"})


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
def test_подсказки(сайт, витрина):
    подсказки = _json(_get(сайт, "/market/api/suggest?q=gal"))
    assert подсказки["products"] == [{"slug": "galaxy-a55", "title": "Смартфон Galaxy A55"}]

    категории = _json(_get(сайт, "/market/api/suggest?q=смарт"))["categories"]
    assert {"slug": "smartphones", "name": "Смартфоны"} in категории

    assert _json(_get(сайт, "/market/api/suggest?q=%20%20")) == {"products": [], "categories": []}


@нужна_база
def test_карточка_товара(сайт, витрина):
    sql("update market_products set views_count = 0 where id = %s", [витрина["телефон"]])
    товар = _json(_get(сайт, "/market/api/product/galaxy-a55"))["product"]

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

    по_узбекски = _json(_get(сайт, "/uz/market/api/product/galaxy-a55"))["product"]
    assert ["Rang", "Qora"] in по_узбекски["specs"]


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
    _, карточка, решение = django(
        модератор,
        ("get", адрес_товара + "change/", None),
        ("post", адрес_товара + "decide/", {"decision": "approve"}),
    )
    assert карточка["status"] == 200 and "Одобрить" in карточка["body"]
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
            {"decision": "reject", "note": "Нет свидетельства о регистрации"},
        ),
    )
    assert список["status"] == 200 and "Guli Cosmetics" in список["body"]
    assert sql("select status, reject_reason from market_sellers where id = %s", [заявка]) == [
        ("rejected", "Нет свидетельства о регистрации")
    ]
    assert без_причины["status"] == 302 and отказ["status"] == 302

    # Подал снова — модератор подтверждает
    sql("update market_sellers set status = 'pending' where id = %s", [заявка])
    django(модератор, ("post", адрес_заявки + "decide/", {"decision": "approve"}))
    assert sql("select status, verified_via from market_sellers where id = %s", [заявка]) == [
        ("approved", "documents")
    ]
    assert _get_as(сайт, "/market/api/me/products", владелец)["status"] == 200

    _, чужим = django(финансы, ("get", "/py/admin/market/seller/", None))
    assert чужим["status"] == 403


@нужна_база
def test_фото_товара(сайт, витрина):
    """Фото пересобирается в WebP на публичном диске; не картинка — 422; удаление стирает файл."""
    from pathlib import Path

    from .pg_admin import КОРЕНЬ
    from .test_web_company_profile_actions import multipart, картинка

    компания = _компания("Samarqand Tekstil", "samarqand-tekstil")
    владелец = _человек("owner@tekstil.uz", компания)
    продавец = _продавец(компания)
    товар, _ = _товар(
        продавец, "textile", "Сюзане ручной работы", "suzani", status="draft", price=900_000
    )

    def загрузить(имя: str, данные: bytes) -> dict[str, Any]:
        тело, тип = multipart({"file": (имя, данные)})

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

    ответ = загрузить("photo.png", картинка(2400, 1200))
    assert ответ["status"] == 201, ответ["body"]
    [фото] = _json(ответ)["product"]["images"]
    [(путь,)] = sql("select path from market_product_images where product_id = %s", [товар])
    файл = Path(КОРЕНЬ) / "storage/app/public" / путь

    try:
        assert путь.startswith("market/products/") and путь.endswith(".webp")
        assert файл.exists()
        assert фото["url"].endswith(путь)

        убрал = _post(сайт, f"/market/api/me/products/{товар}/images/{фото['id']}/delete", владелец)
        assert убрал["status"] == 200 and _json(убрал)["product"]["images"] == []
        assert not файл.exists()
    finally:
        файл.unlink(missing_ok=True)
