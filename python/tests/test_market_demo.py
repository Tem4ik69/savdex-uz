"""
Демо маркетплейса на тестовом (savdex/market/demo.py, manage.py demo):
продавцы и товары из demo.ts — в продаже, с вариантами, характеристиками
и сводкой цены; добавляется и к базе, где демо SavdEx уже есть; повторный
запуск ничего не дублирует; на боевом — отказ.

Нужен PostgreSQL (SAVDEX_PARITY_PG_URL).
"""

from __future__ import annotations

import pytest

from savdex import demo
from savdex.market import demo as market_demo

from .pg_admin import sql, нужна_база
from .test_demo import manage, база  # noqa: F401 — та же свежая база со справочниками

pytestmark = нужна_база


def test_демо_маркетплейса(база):  # noqa: F811
    итог = manage("demo")
    assert итог.returncode == 0, итог.stderr[-3000:]
    assert f"товаров {len(market_demo.PRODUCTS)}" in итог.stdout

    # Продавцы — одобрены, у проверенных — документы приняты
    продавцы = sql(
        "select c.slug, c.verification_level, s.status from market_sellers s "
        "join companies c on c.id = s.company_id where c.source_note = %s",
        [market_demo.MARK],
    )
    assert len(продавцы) == len(market_demo.SELLERS)
    assert all(статус == "approved" for *_, статус in продавцы)
    уровни = {slug: уровень for slug, уровень, _ in продавцы}
    assert уровни["chorsu-tech"] == 2 and уровни["bolajon"] == 1

    # Товары — в продаже, сводка цены и остатка пересчитана по вариантам
    товары = {
        slug: (цена, старая, остаток, вариантов, характеристик)
        for slug, цена, старая, остаток, вариантов, характеристик in sql(
            "select p.slug, p.price, p.old_price, p.stock, "
            "(select count(*) from market_product_variants v where v.product_id = p.id), "
            "(select count(*) from market_product_values x where x.product_id = p.id) "
            "from market_products p where p.status = 'active'"
        )
    }
    assert len(товары) == len(market_demo.PRODUCTS)
    assert товары["smartfon-nova-x5-256"] == (349_000_000, 429_000_000, 14, 6, 5)
    assert товары["kofevarka-kapelnaya-12"][3] == 1  # без выбора — один вариант
    assert товары["kazan-chugunnyj-12l"][1] is None  # без скидки
    assert товары["umnye-chasy-pulse-3"][2] == 0  # нет в наличии

    # Остаток — только приёмкой поставки на демо-склад: склад и варианты сходятся
    assert sql(
        "select (select sum(quantity) from market_warehouse_stock), "
        "(select sum(stock) from market_product_variants), "
        "(select count(*) from market_stock_movements where kind <> 'receipt'), "
        "(select count(*) from market_supplies where status = 'received')"
    ) == [
        (sum(p["stock"] for p in market_demo.PRODUCTS),) * 2
        + (0, len({p["seller"] for p in market_demo.PRODUCTS if p["stock"]}))
    ]

    # Варианты — с названиями выбора, как в форме продавца
    [(выбор,)] = sql(
        "select v.options from market_product_variants v join market_products p "
        "on p.id = v.product_id where p.slug = 'smartfon-nova-x5-256' and v.sort = 0"
    )
    assert выбор == {"Цвет": "Синий", "Память": "128 ГБ"}

    # Пункты выдачи — те же 8, что в демо оформления заказа (resources/js/market/orders.ts)
    assert f"Пункты выдачи: {len(market_demo.PICKUP_POINTS)}" in итог.stdout
    пункты = sql("select code, city, is_active from market_pickup_points where code like 'demo-%%'")
    assert len(пункты) == len(market_demo.PICKUP_POINTS)
    assert all(город == "Ташкент" and работает for _, город, работает in пункты)

    # Повторный запуск ничего не дублирует
    ещё = manage("demo")
    assert ещё.returncode == 0 and "Демо маркетплейса уже есть" in ещё.stdout
    assert "Пункты выдачи" not in ещё.stdout
    [(всего,)] = sql("select count(*) from market_products")
    assert всего == len(market_demo.PRODUCTS)


def test_к_уже_наполненной_базе(база):  # noqa: F811
    # Демо SavdEx уже было (тестовый сейчас), маркетплейса не было. Движения
    # остатка только дописываются — стереть их можно лишь truncate владельца
    sql(
        "truncate market_stock_movements, market_warehouse_stock, market_supply_items, "
        "market_supplies"
    )
    sql("delete from market_products")
    sql(
        "delete from market_sellers where company_id in "
        "(select id from companies where source_note = %s)",
        [market_demo.MARK],
    )
    sql("delete from companies where source_note = %s", [market_demo.MARK])
    [(компаний,)] = sql("select count(*) from companies where source_note = %s", [demo.MARK])
    assert компаний == len(demo.COMPANIES)

    sql("delete from market_pickup_points where code like 'demo-%%'")
    итог = manage("demo")
    assert итог.returncode == 0, итог.stderr[-3000:]
    assert "Демо-данные уже есть" in итог.stdout
    assert f"Пункты выдачи: {len(market_demo.PICKUP_POINTS)}" in итог.stdout
    assert f"товаров {len(market_demo.PRODUCTS)}" in итог.stdout


def test_на_боевом_отказ(база):  # noqa: F811
    итог = manage("demo", APP_ENV="production")

    assert итог.returncode != 0
    assert "Боевой сайт" in итог.stderr


@pytest.mark.parametrize(
    ("имя", "ключ"), [("Тип кожи", "tip_kozhi"), ("SIM", "sim"), ("В комплекте", "v_komplekte")]
)
def test_ключ_характеристики(имя, ключ):
    assert market_demo._attribute_key(имя) == ключ
