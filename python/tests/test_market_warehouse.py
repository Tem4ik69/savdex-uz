"""
Склад маркетплейса — схема (миграция 2026_11_23_100000, ТЗ 18.11, разделы 6
и 11.3): что держит сама база, ещё до кода склада.

- остаток склада меняется только движением; движение двигает и остаток
  склада, и остаток варианта; в минус и ниже резерва — нельзя;
- приёмка — ровно принятое по строке принятой поставки, один раз;
- движения только дописываются; остаток склада сайт не пишет;
- поставка — товар своего продавца, вариант своего товара;
- отгрузка — в пункт заказа, в одну сторону один раз.

Нужен PostgreSQL (SAVDEX_PARITY_PG_URL).
"""

from __future__ import annotations

from typing import Any

import psycopg
import pytest

from .pg_admin import АДРЕС, sql, нужна_база, свежая_база
from .test_market import _id, _компания, _продавец, _товар

pytestmark = нужна_база


@pytest.fixture(scope="module")
def склад() -> dict[str, Any]:
    sql(
        "do $$ begin if not exists (select from pg_roles where rolname = 'savdex_django') "
        "then create role savdex_django; end if; end $$"
    )
    свежая_база()
    продавец = _продавец(_компания("Chorsu Tech", "chorsu-tech"))
    чужой = _продавец(_компания("Bolajon Toys", "bolajon-toys"))
    товар, вариант = _товар(
        продавец, "smartphones", "Смартфон Galaxy A55", "galaxy-a55", price=4_000_000, stock=0
    )
    чужой_товар, чужой_вариант = _товар(
        чужой, "toys", "Кубики деревянные", "cubes", price=90_000, stock=0
    )
    [(сотрудник,)] = sql(
        "insert into users (name, email, password, status, created_at, updated_at) "
        "values ('Склад', 'stock@savdex.uz', 'x', 'active', now(), now()) returning id"
    )
    return {
        "продавец": продавец,
        "чужой": чужой,
        "товар": товар,
        "вариант": вариант,
        "чужой_товар": чужой_товар,
        "чужой_вариант": чужой_вариант,
        "сотрудник": сотрудник,
        "склад": _id(
            "insert into market_warehouses (code, name, address) "
            "values ('bts-tashkent', 'Склад BTS', 'Ташкент') returning id"
        ),
        "пункт": _id(
            "insert into market_pickup_points (code, name, address) "
            "values ('chilonzor', 'ПВЗ Чиланзар', 'Ташкент, Чиланзар') returning id"
        ),
        "другой_пункт": _id(
            "insert into market_pickup_points (code, name, address) "
            "values ('yunusobod', 'ПВЗ Юнусобод', 'Ташкент, Юнусобод') returning id"
        ),
    }


def _сайт(query: str, params: list[Any] | None = None) -> list[tuple[Any, ...]]:
    """Запрос от имени роли сайта (savdex_django), как его сделает код."""
    with psycopg.connect(АДРЕС, autocommit=True) as соединение:
        соединение.execute("set role savdex_django")
        курсор = соединение.execute(query, params or [])

        return курсор.fetchall() if курсор.description else []


def _отказ(query: str, params: list[Any], причина: str, *, сайт: bool = False) -> None:
    with pytest.raises(psycopg.Error, match=причина):
        (_сайт if сайт else sql)(query, params)


def _остатки(с: dict[str, Any]) -> tuple[int, int]:
    """(остаток на складе, остаток варианта)."""
    [(на_складе,)] = sql(
        "select coalesce(sum(quantity), 0) from market_warehouse_stock where variant_id = %s",
        [с["вариант"]],
    )
    [(у_варианта,)] = sql("select stock from market_product_variants where id = %s", [с["вариант"]])
    return int(на_складе), int(у_варианта)


_номер = iter(range(1, 10_000))


def _поставка(с: dict[str, Any], заявлено: int, *, принято: int, брак: int) -> int:
    """Принятая поставка из одной строки; вернёт id строки."""
    n = next(_номер)
    поставка = _id(
        "insert into market_supplies (number, seller_id, warehouse_id, status, submitted_at, "
        "received_at, received_by) values (%s, %s, %s, 'received', now(), now(), %s) returning id",
        [f"SUP{n:08d}", с["продавец"], с["склад"], с["сотрудник"]],
    )
    return _id(
        "insert into market_supply_items (supply_id, seller_id, product_id, variant_id, "
        "quantity_declared, quantity_accepted, quantity_defect) "
        "values (%s, %s, %s, %s, %s, %s, %s) returning id",
        [поставка, с["продавец"], с["товар"], с["вариант"], заявлено, принято, брак],
    )


def _движение(с: dict[str, Any], kind: str, quantity: int, **поля: Any) -> None:
    columns = {
        "warehouse_id": с["склад"],
        "variant_id": с["вариант"],
        "product_id": с["товар"],
        "kind": kind,
        "quantity": quantity,
        "actor_user_id": с["сотрудник"],
        **поля,
    }
    _сайт(
        f"insert into market_stock_movements ({', '.join(columns)}) "
        f"values ({', '.join(['%s'] * len(columns))})",
        list(columns.values()),
    )


def _заказ(с: dict[str, Any], пункт: int) -> int:
    """Заказ на один вариант с пунктом выдачи — напрямую, без оформления."""
    n = next(_номер)
    [(покупатель,)] = sql(
        "insert into users (name, email, password, status, created_at, updated_at) "
        "values ('Азиз', %s, 'x', 'active', now(), now()) returning id",
        [f"buyer{n}@mail.example"],
    )
    заказ = _id(
        "insert into market_orders (number, buyer_user_id, status, payment_method, "
        "pickup_point_id, pickup_point_name, pickup_point_address, items_total, total) "
        "values (%s, %s, 'assembling', 'cash', %s, 'ПВЗ', 'Ташкент', 400000000, 400000000) "
        "returning id",
        [f"ORD{n:08d}", покупатель, пункт],
    )
    часть = _id(
        "insert into market_order_parts (order_id, seller_id, status, subtotal) "
        "values (%s, %s, 'assembling', 400000000) returning id",
        [заказ, с["продавец"]],
    )
    sql(
        "insert into market_order_items (order_id, part_id, product_id, variant_id, title, "
        "price, quantity, line_total, commission_percent, commission) "
        "values (%s, %s, %s, %s, 'Смартфон', 400000000, 1, 400000000, 10, 40000000)",
        [заказ, часть, с["товар"], с["вариант"]],
    )
    return заказ


def test_приёмка_двигает_оба_остатка(склад):
    строка = _поставка(склад, 10, принято=8, брак=2)

    _движение(склад, "receipt", 8, supply_item_id=строка)

    # Брак в остаток не идёт; остаток склада и варианта — вместе
    assert _остатки(склад) == (8, 8)

    # Вторая приёмка той же строки — нельзя
    _отказ(
        "insert into market_stock_movements (warehouse_id, variant_id, product_id, kind, "
        "quantity, supply_item_id) values (%s, %s, %s, 'receipt', 8, %s)",
        [склад["склад"], склад["вариант"], склад["товар"], строка],
        "market_stock_movements_receipt_unique",
    )
    assert _остатки(склад) == (8, 8)


def test_приёмка_только_принятого(склад):
    строка = _поставка(склад, 5, принято=5, брак=0)
    вставка = (
        "insert into market_stock_movements (warehouse_id, variant_id, product_id, kind, "
        "quantity, supply_item_id) values (%s, %s, %s, 'receipt', %s, %s)"
    )
    общие = [склад["склад"], склад["вариант"], склад["товар"]]

    # Больше, чем принято
    _отказ(вставка, [*общие, 6, строка], "приёмка не совпадает", сайт=True)
    # Поставка ещё не принята
    sql(
        "update market_supplies set status = 'submitted', received_at = null, "
        "received_by = null where id = (select supply_id from market_supply_items where id = %s)",
        [строка],
    )
    _отказ(вставка, [*общие, 5, строка], "приёмка не совпадает", сайт=True)
    # Вариант — не из строки поставки
    _отказ(
        вставка,
        [склад["склад"], склад["чужой_вариант"], склад["чужой_товар"], 5, строка],
        "market_stock_movements_supply_item_fkey",
    )


def test_в_минус_и_ниже_резерва_нельзя(склад):
    _движение(склад, "adjust", 2, reason="инвентаризация")
    до = _остатки(склад)

    _отказ(
        "insert into market_stock_movements (warehouse_id, variant_id, product_id, kind, "
        "quantity, reason) values (%s, %s, %s, 'writeoff', %s, 'брак')",
        [склад["склад"], склад["вариант"], склад["товар"], -(до[0] + 1)],
        "market_warehouse_stock_quantity_check",
        сайт=True,
    )

    # Резерв под заказы: списать то, что отложено, — нельзя
    sql("update market_product_variants set reserved = %s where id = %s", [до[1], склад["вариант"]])
    try:
        _отказ(
            "insert into market_stock_movements (warehouse_id, variant_id, product_id, kind, "
            "quantity, reason) values (%s, %s, %s, 'writeoff', -1, 'брак')",
            [склад["склад"], склад["вариант"], склад["товар"]],
            "market_product_variants_reserved_check",
            сайт=True,
        )
    finally:
        sql("update market_product_variants set reserved = 0 where id = %s", [склад["вариант"]])

    assert _остатки(склад) == до

    # Правильное списание проходит
    _движение(склад, "writeoff", -1, reason="разбит при приёмке")
    assert _остатки(склад) == (до[0] - 1, до[1] - 1)


@pytest.mark.parametrize(
    ("kind", "quantity", "поля", "причина"),
    [
        # Основание есть (проверки строки — раньше ключей), знак не тот
        ("receipt", -1, {"supply_item_id": 999_999}, "market_stock_movements_sign_check"),
        ("issue", 1, {"order_id": 999_999}, "market_stock_movements_sign_check"),
        ("adjust", 0, {"reason": "ноль"}, "market_stock_movements_sign_check"),
        ("writeoff", -1, {}, "market_stock_movements_ref_check"),
        ("adjust", 1, {}, "market_stock_movements_ref_check"),
        ("issue", -1, {"reason": "без заказа"}, "market_stock_movements_ref_check"),
        ("receipt", 1, {}, "market_stock_movements_ref_check"),
        ("moved", 1, {"reason": "?"}, "market_stock_movements_kind_check"),
    ],
)
def test_вид_движения_знак_и_основание(склад, kind, quantity, поля, причина):
    columns = {
        "warehouse_id": склад["склад"],
        "variant_id": склад["вариант"],
        "product_id": склад["товар"],
        "kind": kind,
        "quantity": quantity,
        **поля,
    }
    _отказ(
        f"insert into market_stock_movements ({', '.join(columns)}) "
        f"values ({', '.join(['%s'] * len(columns))})",
        list(columns.values()),
        причина,
    )


def test_выдача_только_по_позиции_заказа(склад):
    _движение(склад, "adjust", 3, reason="инвентаризация")
    заказ = _заказ(склад, склад["пункт"])
    до = _остатки(склад)

    # Вариант, которого нет в заказе
    _отказ(
        "insert into market_stock_movements (warehouse_id, variant_id, product_id, kind, "
        "quantity, order_id) values (%s, %s, %s, 'issue', -1, %s)",
        [склад["склад"], склад["чужой_вариант"], склад["чужой_товар"], заказ],
        "market_stock_movements_order_item_fkey",
    )

    _движение(склад, "issue", -1, order_id=заказ)
    assert _остатки(склад) == (до[0] - 1, до[1] - 1)


def test_движения_только_дописываются_остаток_пишет_база(склад):
    _движение(склад, "adjust", 1, reason="нашли")
    [(движение,)] = sql("select max(id) from market_stock_movements")

    for запрос in (
        "update market_stock_movements set quantity = 100 where id = %s",
        "delete from market_stock_movements where id = %s",
    ):
        # Даже владельцу базы
        _отказ(запрос, [движение], "только дописываются")
        _отказ(запрос, [движение], "permission denied", сайт=True)

    # Остаток склада сайт напрямую не пишет — только движением
    _отказ(
        "update market_warehouse_stock set quantity = 1000 where variant_id = %s",
        [склад["вариант"]],
        "permission denied",
        сайт=True,
    )
    assert sql(
        "select has_table_privilege('savdex_django', 'market_warehouse_stock', 'select'), "
        "has_table_privilege('savdex_django', 'market_warehouse_stock', 'insert'), "
        "has_table_privilege('savdex_django', 'market_stock_movements', 'truncate'), "
        "has_function_privilege('savdex_django', 'market_stock_apply()', 'execute')"
    ) == [(True, False, False, False)]


def test_поставка_своего_товара_и_варианта(склад):
    поставка = _id(
        "insert into market_supplies (number, seller_id, warehouse_id) "
        "values ('SUPOWN0001', %s, %s) returning id",
        [склад["продавец"], склад["склад"]],
    )
    вставка = (
        "insert into market_supply_items (supply_id, seller_id, product_id, variant_id, "
        "quantity_declared) values (%s, %s, %s, %s, 1)"
    )
    # Товар чужого продавца
    _отказ(
        вставка,
        [поставка, склад["продавец"], склад["чужой_товар"], склад["чужой_вариант"]],
        "market_supply_items_product_fkey",
    )
    # Строка — от имени другого продавца, чем поставка
    _отказ(
        вставка,
        [поставка, склад["чужой"], склад["чужой_товар"], склад["чужой_вариант"]],
        "market_supply_items_supply_fkey",
    )
    # Вариант — не этого товара
    _отказ(
        вставка,
        [поставка, склад["продавец"], склад["товар"], склад["чужой_вариант"]],
        "market_supply_items_variant_fkey",
    )
    # Принято без брака (и наоборот) — вместе или никак
    _отказ(
        "insert into market_supply_items (supply_id, seller_id, product_id, variant_id, "
        "quantity_declared, quantity_accepted) values (%s, %s, %s, %s, 1, 1)",
        [поставка, склад["продавец"], склад["товар"], склад["вариант"]],
        "market_supply_items_received_check",
    )
    _сайт(вставка, [поставка, склад["продавец"], склад["товар"], склад["вариант"]])


@pytest.mark.parametrize(
    ("поля", "причина"),
    [
        ({"status": "submitted"}, "market_supplies_status_times_check"),
        ({"status": "received", "submitted_at": "now"}, "market_supplies_status_times_check"),
        ({"status": "rejected", "submitted_at": "now", "rejected_at": "now"}, "status_times"),
        ({"status": "cancelled"}, "market_supplies_status_times_check"),
        ({"number": "sup-1"}, "market_supplies_number_check"),
    ],
)
def test_поставка_шаги_со_временем(склад, поля, причина):
    columns = {
        "number": f"SUPT{next(_номер):06d}",
        "seller_id": склад["продавец"],
        "warehouse_id": склад["склад"],
        **поля,
    }
    values = ["now()" if v == "now" else "%s" for v in columns.values()]
    _отказ(
        f"insert into market_supplies ({', '.join(columns)}) values ({', '.join(values)})",
        [v for v in columns.values() if v != "now"],
        причина,
    )


def test_отгрузка_в_пункт_заказа_один_раз(склад):
    заказ = _заказ(склад, склад["пункт"])

    def отгрузка(пункт: int, direction: str = "to_point") -> int:
        return _id(
            "insert into market_shipments (number, warehouse_id, pickup_point_id, direction) "
            "values (%s, %s, %s, %s) returning id",
            [f"SHP{next(_номер):08d}", склад["склад"], пункт, direction],
        )

    вставка = (
        "insert into market_shipment_orders (shipment_id, order_id, direction, pickup_point_id) "
        "values (%s, %s, %s, %s)"
    )
    # В чужой пункт: отгрузка в другой, заказ — в свой
    в_другой = отгрузка(склад["другой_пункт"])
    _отказ(
        вставка,
        [в_другой, заказ, "to_point", склад["пункт"]],
        "market_shipment_orders_shipment_fkey",
    )
    _отказ(
        вставка,
        [в_другой, заказ, "to_point", склад["другой_пункт"]],
        "market_shipment_orders_order_fkey",
    )

    туда = отгрузка(склад["пункт"])
    _сайт(вставка, [туда, заказ, "to_point", склад["пункт"]])
    # Второй раз в пункт — нельзя; обратно на склад — можно
    _отказ(
        вставка,
        [отгрузка(склад["пункт"]), заказ, "to_point", склад["пункт"]],
        "market_shipment_orders_once_unique",
    )
    обратно = отгрузка(склад["пункт"], "to_warehouse")
    _сайт(вставка, [обратно, заказ, "to_warehouse", склад["пункт"]])

    # Уехала — со временем и кем; отменить уехавшую нельзя
    _отказ(
        "update market_shipments set status = 'in_transit' where id = %s",
        [туда],
        "market_shipments_status_times_check",
    )
    sql(
        "update market_shipments set status = 'in_transit', shipped_at = now(), shipped_by = %s "
        "where id = %s",
        [склад["сотрудник"], туда],
    )
    _отказ(
        "update market_shipments set status = 'cancelled', cancelled_at = now() where id = %s",
        [туда],
        "market_shipments_status_times_check",
    )


def test_пункт_выдачи_точка_на_карте(склад):
    запрос = "update market_pickup_points set latitude = %s, longitude = %s where id = %s"
    # Одна координата без другой; точка не в Узбекистане
    _отказ(запрос, [41.3, None, склад["пункт"]], "market_pickup_points_point_check")
    _отказ(запрос, [55.75, 37.62, склад["пункт"]], "market_pickup_points_point_check")
    sql(запрос, [41.285, 69.204, склад["пункт"]])
    sql(
        "update market_pickup_points set hours = 'Пн–Сб 9:00–20:00' where id = %s",
        [склад["пункт"]],
    )
