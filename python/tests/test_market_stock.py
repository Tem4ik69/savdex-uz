"""
Склад и пункты выдачи маркетплейса — код (savdex/market/warehouse.py,
warehouse_admin.py; схема — test_market_warehouse.py):

- поставка: продавец заводит и отправляет только свои товары; склад
  принимает (принято и брак по строке) или отказывает с причиной; принятое
  — в остаток движением «receipt», брак — нет; чужой склад поставку не видит;
- заказ дальше «в сборку» — только отгрузкой: склад отправляет, пункт
  принимает — «можно забрать», время прихода, код выдачи, уведомление;
- код: в базе — только отпечаток; покупатель видит код в своём заказе;
  неверный — счётчик, после пяти подряд ввод закрыт; выдача — резерв снят,
  движение «issue», кто выдал; остаток склада и варианта сходятся;
- не забрали за N дней — закрыт сам (картой — к возврату, при получении —
  отменён), резерв снят; товар едет обратно на склад отгрузкой;
- списание, вывоз и инвентаризация — движением с причиной, не в минус и
  не ниже резерва; правки остатка в карточке товара нет;
- роль «Пункт выдачи» видит только свой пункт; склад и пункт не заходят в
  разделы друг друга.

Нужен PostgreSQL (SAVDEX_PARITY_PG_URL); проверки без базы — в начале.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import datetime
from itertools import count
from typing import Any

import pytest

from savdex import access
from savdex.market import orders, warehouse

from .pg_admin import django, sql, журнал, нужна_база, свежая_база, сотрудник
from .test_market import (
    СКЛАД,
    _get_as,
    _json,
    _post,
    _компания,
    _продавец,
    _склад,
    _товар,
    _человек,
)
from .test_market_orders import (
    _id,
    _manage,
    _python,
    _в_корзину,
    _до_выдачи,
    _оформить,
    _покупатель,
    _статус,
)
from .web_site import адрес

# ── Без базы ────────────────────────────────────────────────────────


def test_шаги_заказа_после_сборки_только_складом():
    # Кнопкой в карточке заказа — только «в сборку»
    assert orders.STAFF_STEPS == {
        orders.PAID: orders.ASSEMBLING,
        orders.CASH_ON_PICKUP: orders.ASSEMBLING,
    }
    # Из пункта: выдан или закрыт как невостребованный
    assert orders.TRANSITIONS[orders.READY] == {
        orders.ISSUED,
        orders.CANCELLED,
        orders.REFUND_PENDING,
    }
    # Покупатель сам заказ из пункта не отменяет
    assert orders.READY not in orders.CANCELLABLE


def test_код_выдачи():
    момент = "2026-11-23 10:00:00"
    код = warehouse.pickup_code(7, момент)

    assert re.fullmatch(r"[0-9]{6}", код)
    # Тот же код из времени прихода, прочитанного из базы
    assert warehouse.pickup_code(7, datetime(2026, 11, 23, 10, 0, 0)) == код
    # Отпечаток зависит от заказа: чужой код к чужому заказу не подойдёт
    assert warehouse._code_hash(7, код) != warehouse._code_hash(8, код)
    assert код not in warehouse._code_hash(7, код)
    # Покупатель видит код только пока заказ ждёт в пункте
    заказ = {"id": 7, "status": orders.READY, "ready_at": момент}
    assert warehouse.code_of(заказ) == код
    assert warehouse.code_of({**заказ, "status": orders.ISSUED}) is None
    assert warehouse.code_of({**заказ, "ready_at": None}) is None


def test_ручные_движения_до_базы():
    for kind, amount, why in (
        ("receipt", 1, "приёмка руками"),
        ("issue", 1, "выдача руками"),
        ("writeoff", 1, ""),
        ("writeoff", -1, "разбили при выгрузке"),
        ("adjust", 0, "инвентаризация"),
    ):
        with pytest.raises(warehouse.WarehouseError):
            warehouse.manual_move(1, 1, kind, amount, why, actor_user_id=1)


def test_нет_товара_под_заказ_понятный_отказ(monkeypatch):
    """Остатка на складе не хватило при выдаче — сотруднику пункта текст, а не 500."""
    from types import SimpleNamespace

    from savdex.adminsite import site
    from savdex.market import warehouse_admin
    from savdex.market.models import PointOrder

    раздел = site._registry[PointOrder]

    def нехватка(*a: Any, **k: Any) -> str:
        raise orders.WriteOffError("нет остатка")

    monkeypatch.setattr(warehouse_admin, "_admin_of", lambda request: SimpleNamespace(id=1))
    monkeypatch.setattr(warehouse_admin.warehouse, "issue", нехватка)
    запрос: Any = SimpleNamespace(POST={"code": "123456"})

    with pytest.raises(warehouse.WarehouseError, match="нет товара"):
        раздел.act(запрос, SimpleNamespace(pk=1, number="ABCDEFGH23"), "issue")


def test_роль_пункта_выдачи():
    assert set(access.abilities_for("pickup_point")) == {
        f"market_pickup.{a}" for a in ("view", "create", "edit", "moderate")
    }
    склад = set(access.abilities_for("warehouse"))
    assert not {a for a in склад if a.startswith("market_pickup.")}


# ── Данные ──────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def сайт() -> Iterator[str]:
    sql(
        "do $$ begin if not exists (select from pg_roles where rolname = 'savdex_django') "
        "then create role savdex_django; end if; end $$"
    )
    свежая_база()

    with адрес() as root:
        yield root


_номер = count(1)

ЦЕНА = 50_000


def _staff(role: str, email: str) -> int:
    return _id_sql(
        "insert into users (name, email, password, is_admin, admin_role, status, "
        "created_at, updated_at) values (%s, %s, 'x', true, %s, 'active', now(), now()) "
        "returning id",
        [f"Сотрудник {email}", email, role],
    )


def _id_sql(query: str, params: list[Any]) -> int:
    [(pk,)] = sql(query, params)

    return int(pk)


@pytest.fixture(scope="module")
def место(сайт) -> dict[str, Any]:
    """Склад и пункт со своими сотрудниками, чужой склад и чужой пункт."""
    склад = _склад()
    чужой_склад = _id_sql(
        "insert into market_warehouses (code, name, address) "
        "values ('other-sklad', 'Другой склад', 'Самарканд') returning id",
        [],
    )
    пункт = _id_sql(
        "insert into market_pickup_points (code, name, address, hours) "
        "values ('chilonzor', 'ПВЗ Чиланзар', 'Ташкент, Чиланзар', 'Пн–Сб 9:00–20:00') "
        "returning id",
        [],
    )
    чужой_пункт = _id_sql(
        "insert into market_pickup_points (code, name, address) "
        "values ('yunusobod', 'ПВЗ Юнусобод', 'Ташкент, Юнусобод') returning id",
        [],
    )
    кладовщик = сотрудник("warehouse")
    чужой_кладовщик = _staff("warehouse", "warehouse-other@savdex.uz")
    выдающий = сотрудник("pickup_point")
    чужой_выдающий = _staff("pickup_point", "pickup-other@savdex.uz")
    sql(
        "insert into market_warehouse_staff (warehouse_id, user_id) values (%s, %s), (%s, %s)",
        [склад, кладовщик, чужой_склад, чужой_кладовщик],
    )
    sql(
        "insert into market_pickup_point_staff (pickup_point_id, user_id) "
        "values (%s, %s), (%s, %s)",
        [пункт, выдающий, чужой_пункт, чужой_выдающий],
    )

    return {
        "склад": склад,
        "чужой_склад": чужой_склад,
        "пункт": пункт,
        "чужой_пункт": чужой_пункт,
        "кладовщик": кладовщик,
        "чужой_кладовщик": чужой_кладовщик,
        "выдающий": выдающий,
        "чужой_выдающий": чужой_выдающий,
        "админ": сотрудник("admin"),
    }


def _продавец_и_товар(stock: int = 0) -> dict[str, Any]:
    n = next(_номер)
    компания = _компания(f"Склад Тест {n}", f"stock-test-{n}")
    продавец = _продавец(компания)
    товар, вариант = _товар(продавец, "toys", f"Робот {n}", f"robot-{n}", price=ЦЕНА, stock=stock)

    return {
        "продавец": продавец,
        "товар": товар,
        "вариант": вариант,
        "владелец": _человек(f"owner{n}@stock.example", компания),
    }


def _остатки(вариант: int) -> tuple[int, int, int]:
    """(остаток варианта, резерв, на складах)."""
    [(stock, reserved, на_складах)] = sql(
        "select v.stock, v.reserved, coalesce((select sum(s.quantity) from "
        "market_warehouse_stock s where s.variant_id = v.id), 0) "
        "from market_product_variants v where v.id = %s",
        [вариант],
    )

    return int(stock), int(reserved), int(на_складах)


def _склады_сходятся() -> None:
    """Для каждого варианта: сумма по складам = stock варианта (проверка Нозима)."""
    assert sql(
        "select count(*) from market_product_variants v where v.stock <> coalesce(("
        "select sum(s.quantity) from market_warehouse_stock s where s.variant_id = v.id), 0)"
    ) == [(0,)]


def _действие(uid: int, адрес_записи: str, **поля: Any) -> dict[str, Any]:
    """POST действия в карточке (…/act/) и карточка после него."""
    _, ответ, страница = django(
        uid,
        ("post", адрес_записи + "act/", {k: str(v) for k, v in поля.items()}),
        ("get", адрес_записи + "change/", None),
    )

    return {"status": ответ["status"], "body": страница["body"], "page": страница["status"]}


# ── Поставки ────────────────────────────────────────────────────────


@нужна_база
def test_поставка_приёмка_и_отказ(сайт, место):
    мой = _продавец_и_товар()
    чужой = _продавец_и_товар()
    создать = "/market/api/me/supplies/create"

    # Чужой товар и неизвестный склад — 422, ничего не заведено
    for тело, поле in (
        ({"warehouse": СКЛАД, "items": [{"variantId": чужой["вариант"], "quantity": 5}]}, "items"),
        (
            {"warehouse": "net-sklada", "items": [{"variantId": мой["вариант"], "quantity": 5}]},
            "warehouse",
        ),
        ({"warehouse": СКЛАД, "items": [{"variantId": мой["вариант"], "quantity": 0}]}, "items"),
        ({"warehouse": СКЛАД, "items": []}, "items"),
    ):
        ответ = _post(сайт, создать, мой["владелец"], тело)
        assert ответ["status"] == 422, ответ["body"]
        assert поле in _json(ответ)["errors"]

    assert sql("select count(*) from market_supplies where seller_id = %s", [мой["продавец"]]) == [
        (0,)
    ]

    ответ = _post(
        сайт,
        создать,
        мой["владелец"],
        {
            "warehouse": СКЛАД,
            "note": "Привезём утром",
            "items": [{"variantId": мой["вариант"], "quantity": 10}],
            "submit": True,
        },
    )
    assert ответ["status"] == 201, ответ["body"]
    поставка = _json(ответ)["supply"]
    assert поставка["status"]["code"] == "submitted" and поставка["canCancel"]
    number = поставка["number"]
    [(pk,)] = sql("select id from market_supplies where number = %s", [number])

    # Чужому продавцу её не видно
    assert _get_as(сайт, f"/market/api/me/supplies/{number}", чужой["владелец"])["status"] == 404
    assert _json(_get_as(сайт, "/market/api/me/supplies", чужой["владелец"]))["supplies"] == []

    карточка = f"/py/admin/market/supply/{pk}/"
    # Чужой склад поставку не видит и принять не может
    _, чужая = django(место["чужой_кладовщик"], ("get", карточка + "change/", None))
    assert "Принять поставку" not in чужая["body"]
    _, мимо = django(место["чужой_кладовщик"], ("post", карточка + "act/", {"do": "receive"}))
    assert мимо["status"] == 403

    _, своя = django(место["кладовщик"], ("get", карточка + "change/", None))
    assert своя["status"] == 200 and "Принять поставку" in своя["body"]
    [(строка,)] = sql("select id from market_supply_items where supply_id = %s", [pk])

    # Меньше нуля — отказ, ничего не записано
    минус = _действие(
        место["кладовщик"],
        карточка,
        do="receive",
        **{f"accepted_{строка}": -1, f"defect_{строка}": 0},
    )
    assert "не меньше нуля" in минус["body"]
    assert _остатки(мой["вариант"]) == (0, 0, 0)

    # Пришло больше заявленного — принимаем факт (решение 23.11, №2)
    принято = _действие(
        место["кладовщик"],
        карточка,
        do="receive",
        **{f"accepted_{строка}": 11, f"defect_{строка}": 2},
    )
    assert "принята: 11 шт." in принято["body"]
    assert _остатки(мой["вариант"]) == (11, 0, 11)
    assert sql(
        "select kind, quantity, actor_user_id from market_stock_movements "
        "where supply_item_id = %s",
        [строка],
    ) == [("receipt", 11, место["кладовщик"])]
    assert журнал("received")["subject_label"] == number
    # Второй раз — «уже недоступно», остаток тот же
    повтор = _действие(
        место["кладовщик"],
        карточка,
        do="receive",
        **{f"accepted_{строка}": 8, f"defect_{строка}": 0},
    )
    assert "уже недоступно" in повтор["body"] and _остатки(мой["вариант"]) == (11, 0, 11)

    # Принятую продавец уже не отменит
    assert _post(сайт, f"/market/api/me/supplies/{number}/cancel", мой["владелец"])["status"] == 409
    итог = _json(_get_as(сайт, f"/market/api/me/supplies/{number}", мой["владелец"]))["supply"]
    assert итог["items"][0] | {"title": None, "options": None} == {
        "variantId": мой["вариант"],
        "title": None,
        "options": None,
        "declared": 10,
        "accepted": 11,
        "defect": 2,
    }

    # Черновик: отменить можно; отправленную — отказ складом с причиной
    черновик = _json(
        _post(
            сайт,
            создать,
            мой["владелец"],
            {"warehouse": СКЛАД, "items": [{"variantId": мой["вариант"], "quantity": 3}]},
        )
    )["supply"]["number"]
    assert (
        _post(сайт, f"/market/api/me/supplies/{черновик}/cancel", мой["владелец"])["status"] == 200
    )
    assert (
        _post(сайт, f"/market/api/me/supplies/{черновик}/submit", мой["владелец"])["status"] == 409
    )

    второй = _json(
        _post(
            сайт,
            создать,
            мой["владелец"],
            {"warehouse": СКЛАД, "items": [{"variantId": мой["вариант"], "quantity": 3}]},
        )
    )["supply"]["number"]
    # До приёмки поставку можно изменить: количество и новые строки; убрать строку — нет
    _, другой_вариант = _товар(
        мой["продавец"], "toys", "Робот-2", f"robot-2-{второй.lower()}", price=ЦЕНА, stock=0
    )
    правка = f"/market/api/me/supplies/{второй}"
    убрать = _post(
        сайт, правка, мой["владелец"], {"items": [{"variantId": другой_вариант, "quantity": 2}]}
    )
    assert убрать["status"] == 422 and "items" in _json(убрать)["errors"]
    изменена = _post(
        сайт,
        правка,
        мой["владелец"],
        {
            "note": "Две коробки",
            "items": [
                {"variantId": мой["вариант"], "quantity": 4},
                {"variantId": другой_вариант, "quantity": 2},
            ],
        },
    )
    assert изменена["status"] == 200, изменена["body"]
    assert [(i["variantId"], i["declared"]) for i in _json(изменена)["supply"]["items"]] == [
        (мой["вариант"], 4),
        (другой_вариант, 2),
    ]
    assert _post(сайт, f"/market/api/me/supplies/{второй}/submit", мой["владелец"])["status"] == 200
    [(второй_pk,)] = sql("select id from market_supplies where number = %s", [второй])
    коротко = _действие(
        место["кладовщик"], f"/py/admin/market/supply/{второй_pk}/", do="reject", reason="брак"
    )
    assert "не короче" in коротко["body"]
    _действие(
        место["кладовщик"],
        f"/py/admin/market/supply/{второй_pk}/",
        do="reject",
        reason="Нет маркировки на коробках",
    )
    отказ = _json(_get_as(сайт, f"/market/api/me/supplies/{второй}", мой["владелец"]))["supply"]
    assert отказ["status"]["code"] == "rejected"
    assert отказ["rejectReason"] == "Нет маркировки на коробках"
    assert _остатки(мой["вариант"]) == (11, 0, 11)
    _склады_сходятся()


# ── Отгрузка и выдача по коду ───────────────────────────────────────


def _заказ(сайт: str, вариант: int, штук: int = 1, method: str = "cash") -> tuple[int, str, int]:
    покупатель = _покупатель()
    _в_корзину(покупатель, вариант, штук)
    ответ = _оформить(сайт, покупатель, ЦЕНА * штук, method=method)
    assert ответ["status"] == 201, ответ["body"]
    number = _json(ответ)["order"]["number"]

    return покупатель, number, _id(number)


@нужна_база
def test_отгрузка_и_выдача_по_коду(сайт, место):
    данные = _продавец_и_товар(stock=10)
    покупатель, number, pk = _заказ(сайт, данные["вариант"], 2)
    assert _остатки(данные["вариант"]) == (10, 2, 10)

    # Отгрузить можно только собранный заказ
    _, добавить, _ = django(
        место["кладовщик"],
        (
            "post",
            "/py/admin/market/shipment/add/",
            {"warehouse": str(место["склад"]), "pickup_point": str(место["пункт"])},
        ),
        ("get", "/py/admin/market/shipment/", None),
    )
    assert добавить["status"] == 200 and "Отправлять нечего" in добавить["body"]

    _, в_сборку = django(
        место["кладовщик"],
        (
            "post",
            f"/py/admin/market/order/{pk}/decide/",
            {"decision": "to:cash_on_pickup:assembling"},
        ),
    )
    assert в_сборку["status"] == 302 and _статус(number) == "assembling"

    _, создана = django(
        место["кладовщик"],
        (
            "post",
            "/py/admin/market/shipment/add/",
            {"warehouse": str(место["склад"]), "pickup_point": str(место["пункт"])},
        ),
    )
    assert создана["status"] == 302, создана["body"][:2000]
    [(отгрузка, отгрузка_номер)] = sql(
        "select s.id, s.number from market_shipments s join market_shipment_orders so "
        "on so.shipment_id = s.id where so.order_id = %s",
        [pk],
    )
    склад_отгрузки = f"/py/admin/market/shipment/{отгрузка}/"
    пункт_отгрузки = f"/py/admin/market/pointshipment/{отгрузка}/"
    assert журнал("created")["subject_label"] == отгрузка_номер

    # Принять в пункте до отправки нельзя; отправляет склад, не пункт
    assert "уже недоступно" in _действие(место["выдающий"], пункт_отгрузки, do="deliver")["body"]
    assert "уже недоступно" in _действие(место["выдающий"], пункт_отгрузки, do="ship")["body"]
    assert "уехала: заказов 1" in _действие(место["кладовщик"], склад_отгрузки, do="ship")["body"]
    assert _статус(number) == "in_transit"
    # Склад сам у себя приёмку в пункте не отмечает; чужой пункт отгрузку не видит
    assert "уже недоступно" in _действие(место["кладовщик"], склад_отгрузки, do="deliver")["body"]
    _, чужой = django(место["чужой_выдающий"], ("post", пункт_отгрузки + "act/", {"do": "deliver"}))
    assert чужой["status"] == 403 and _статус(number) == "in_transit"

    принята = _действие(место["выдающий"], пункт_отгрузки, do="deliver")
    assert "принята: заказов 1" in принята["body"]
    assert _статус(number) == "ready"
    # Остаток не тронут: товар наш, просто в пункте
    assert _остатки(данные["вариант"]) == (10, 2, 10)

    # Покупателю — уведомление без кода; код — в его заказе
    [(заголовок, текст)] = sql(
        "select title, body from user_notifications where user_id = %s and type = 'market'",
        [покупатель],
    )
    assert number in заголовок and "ПВЗ Чиланзар" in текст and "Пн–Сб 9:00–20:00" in текст
    заказ = _json(_get_as(сайт, f"/market/api/orders/{number}", покупатель))["order"]
    код = заказ["pickupCode"]
    assert re.fullmatch(r"[0-9]{6}", код) and код not in текст
    assert заказ["pickupPoint"]["hours"] == "Пн–Сб 9:00–20:00" and заказ["readyAt"]
    # В базе — только отпечаток кода
    [(отпечаток,)] = sql("select pickup_code_hash from market_orders where id = %s", [pk])
    assert отпечаток and код not in отпечаток
    # Чужому заказ не виден, код — тоже
    assert _get_as(сайт, f"/market/api/orders/{number}", _покупатель())["status"] == 404

    карточка = f"/py/admin/market/pointorder/{pk}/"
    _, страница = django(место["выдающий"], ("get", карточка + "change/", None))
    assert "Выдать заказ" in страница["body"] and "100 000 сум" in страница["body"]
    # Имени покупателя пункт не видит
    [(имя,)] = sql("select name from users where id = %s", [покупатель])
    assert имя not in страница["body"]
    assert код not in страница["body"]
    # Чужой пункт заказ не видит
    _, мимо = django(место["чужой_выдающий"], ("post", карточка + "act/", {"do": "issue"}))
    assert мимо["status"] == 403

    неверный = "000000" if код != "000000" else "111111"

    for попытка in range(1, warehouse.CODE_ATTEMPTS):
        ответ = _действие(место["выдающий"], карточка, do="issue", code=неверный)
        assert "Код неверный" in ответ["body"]
        assert sql(
            "select status, pickup_code_attempts from market_orders where id = %s", [pk]
        ) == [("ready", попытка)]

    закрыт = _действие(место["выдающий"], карточка, do="issue", code=неверный)
    assert "на паузе" in закрыт["body"]
    # Пока закрыто — и верный код не проходит; каждая неудача — в журнале
    assert "на паузе" in _действие(место["выдающий"], карточка, do="issue", code=код)["body"]
    assert _статус(number) == "ready"
    assert sql(
        "select count(*) from admin_actions where action = 'pickup_code_failed' "
        "and subject_label = %s",
        [number],
    ) == [(warehouse.CODE_ATTEMPTS + 1,)]
    assert код not in str(sql("select note, changes from admin_actions"))

    # Раньше конца паузы открывает администратор — с причиной; склад и пункт — нет
    заказ_в_админке = f"/py/admin/market/order/{pk}/"
    _, у_склада = django(место["кладовщик"], ("get", заказ_в_админке + "change/", None))
    assert "Открыть ввод кода" not in у_склада["body"]
    _, без_причины, открыт = django(
        место["админ"],
        ("post", заказ_в_админке + "decide/", {"decision": "unlock:ready", "note": "ок"}),
        (
            "post",
            заказ_в_админке + "decide/",
            {
                "decision": "unlock:ready",
                "note": "Позвонили покупателю, код подтвердил",
            },
        ),
    )
    assert без_причины["status"] == открыт["status"] == 302
    assert sql(
        "select pickup_code_attempts, pickup_code_locked_until from market_orders where id = %s",
        [pk],
    ) == [(0, None)]
    assert журнал("unblocked")["subject_label"] == number

    выдан = _действие(место["выдающий"], карточка, do="issue", code=f" {код[:3]} {код[3:]} ")
    assert f"Заказ {number} выдан" in выдан["body"]
    assert sql(
        "select status, issued_by, pickup_code_attempts, pickup_code_locked_until "
        "from market_orders where id = %s",
        [pk],
    ) == [("issued", место["выдающий"], 0, None)]
    # Резерв снят, остаток — движением «issue» со склада отгрузки
    assert _остатки(данные["вариант"]) == (8, 0, 8)
    assert sql(
        "select warehouse_id, kind, quantity, actor_user_id from market_stock_movements "
        "where order_id = %s",
        [pk],
    ) == [(место["склад"], "issue", -2, место["выдающий"])]
    assert sql("select sold_count from market_products where id = %s", [данные["товар"]]) == [(2,)]
    assert sql(
        "select sum(amount) from market_ledger where order_id = %s and account = 'cash_collected'",
        [pk],
    ) == [(ЦЕНА * 2 * 100,)]
    assert журнал("status_changed")["section"] == "market_pickup"
    # Повтор — «уже недоступно», второй раз не списывает
    assert "уже недоступно" in _действие(место["выдающий"], карточка, do="issue", code=код)["body"]
    assert _остатки(данные["вариант"]) == (8, 0, 8)
    _склады_сходятся()


@нужна_база
def test_отменённый_в_сборке_не_уезжает(сайт, место):
    данные = _продавец_и_товар(stock=5)
    покупатель, number, pk = _заказ(сайт, данные["вариант"])
    _, второй_number, второй = _заказ(сайт, данные["вариант"])

    for заказ in (pk, второй):
        assert (
            _python(
                "from savdex.market import orders\n"
                f"print(orders.advance({заказ}, 'cash_on_pickup', "
                f"actor_user_id={место['кладовщик']}))"
            )
            == "True"
        )

    shipment = _python(
        "from savdex.market import warehouse\n"
        f"print(warehouse.shipment_create({место['склад']}, {место['пункт']}, 'to_point', "
        f"actor_user_id={место['кладовщик']})[0])"
    )
    # Покупатель отменил, пока собирали
    assert _post(сайт, f"/market/api/orders/{number}/cancel", покупатель)["status"] == 200
    уехала = _действие(место["кладовщик"], f"/py/admin/market/shipment/{shipment}/", do="ship")
    assert "уехала: заказов 1" in уехала["body"]
    assert _статус(number) == "cancelled" and _статус(второй_number) == "in_transit"
    assert sql(
        "select order_id from market_shipment_orders where shipment_id = %s", [int(shipment)]
    ) == [(второй,)]


# ── Невостребованные ────────────────────────────────────────────────


@нужна_база
def test_невостребованные_закрываются_и_едут_на_склад(сайт, место):
    данные = _продавец_и_товар(stock=5)
    _, наличными, при_получении = _заказ(сайт, данные["вариант"])
    _, картой_номер, картой = _заказ(сайт, данные["вариант"], method="card")
    assert (
        _python(
            f"from savdex.market import orders\nprint(orders.mark_paid({картой}, {ЦЕНА * 100}))"
        )
        == "True"
    )
    свежий_покупатель, свежий_номер, свежий = _заказ(сайт, данные["вариант"])

    for заказ in (при_получении, картой, свежий):
        _до_выдачи(заказ, место["кладовщик"], выдать=False)

    assert _остатки(данные["вариант"]) == (5, 3, 5)
    sql(
        "update market_orders set ready_at = ready_at - interval '8 days' where id = any(%s)",
        [[при_получении, картой]],
    )

    итог = _manage("market_unclaimed_orders")
    assert итог.returncode == 0, итог.stderr[-3000:]
    assert "заказов: 2." in итог.stdout
    assert _статус(наличными) == "cancelled" and _статус(картой_номер) == "refund_pending"
    assert _статус(свежий_номер) == "ready"
    # Резерв снят, остаток — на месте (товар в пункте, он наш)
    assert _остатки(данные["вариант"]) == (5, 1, 5)
    # Начисление продавцу — назад: по каждому счёту ноль, кроме долга покупателю картой
    assert sql(
        "select order_id, account, sum(amount) from market_ledger where order_id = any(%s) "
        "group by order_id, account having sum(amount) <> 0 order by order_id, account",
        [[при_получении, картой]],
    ) == [
        (картой, "gateway_clearing", ЦЕНА * 100),
        (картой, "refund_payable", -ЦЕНА * 100),
    ]
    [(причина,)] = sql("select cancel_reason from market_orders where id = %s", [при_получении])
    assert причина == "не забран за 7 дн."
    assert "заказов: 0." in _manage("market_unclaimed_orders").stdout

    # Обратно на склад: собирает и отправляет пункт, принимает склад
    _, создана = django(
        место["выдающий"],
        (
            "post",
            "/py/admin/market/pointshipment/add/",
            {"warehouse": str(место["склад"]), "pickup_point": str(место["пункт"])},
        ),
    )
    assert создана["status"] == 302, создана["body"][:2000]
    [(обратно,)] = sql(
        "select id from market_shipments where direction = 'to_warehouse' and pickup_point_id = %s",
        [место["пункт"]],
    )
    assert sorted(
        r[0]
        for r in sql(
            "select order_id from market_shipment_orders where shipment_id = %s", [обратно]
        )
    ) == sorted([при_получении, картой])
    assert (
        "уехала"
        in _действие(место["выдающий"], f"/py/admin/market/pointshipment/{обратно}/", do="ship")[
            "body"
        ]
    )
    assert (
        "принята"
        in _действие(место["кладовщик"], f"/py/admin/market/shipment/{обратно}/", do="deliver")[
            "body"
        ]
    )
    assert sql(
        "select count(*) from market_order_events where order_id = %s and note like %s",
        [при_получении, "%вернулся на склад%"],
    ) == [(1,)]
    assert _остатки(данные["вариант"]) == (5, 1, 5)
    # Свежий заказ по-прежнему выдаётся
    код = _json(_get_as(сайт, f"/market/api/orders/{свежий_номер}", свежий_покупатель))["order"][
        "pickupCode"
    ]
    assert (
        "выдан"
        in _действие(
            место["выдающий"], f"/py/admin/market/pointorder/{свежий}/", do="issue", code=код
        )["body"]
    )
    assert _остатки(данные["вариант"]) == (4, 0, 4)
    _склады_сходятся()


# ── Ручные движения и карточка товара ───────────────────────────────


@нужна_база
def test_списание_и_инвентаризация(сайт, место):
    данные = _продавец_и_товар(stock=4)
    _заказ(сайт, данные["вариант"])
    вариант = данные["вариант"]
    добавить = "/py/admin/market/stockmovement/add/"

    def движение(
        uid: int, kind: str, amount: int, why: str, store: int | None = None
    ) -> dict[str, Any]:
        _, ответ = django(
            uid,
            (
                "post",
                добавить,
                {
                    "warehouse": str(store or место["склад"]),
                    "variant_number": str(вариант),
                    "manual_kind": kind,
                    "amount": str(amount),
                    "why": why,
                },
            ),
        )

        return dict(ответ)

    # Одна штука — под заказом: списать можно не больше трёх
    много = движение(место["кладовщик"], "return_to_seller", 4, "продавец забрал всё")
    assert много["status"] == 200 and "Столько не списать" in много["body"]
    без_причины = движение(место["кладовщик"], "return_to_seller", 1, " ")
    assert без_причины["status"] == 200
    # Чужой склад сотруднику не выбрать
    чужой = движение(место["чужой_кладовщик"], "return_to_seller", 1, "продавец забрал")
    assert чужой["status"] == 200 and _остатки(вариант) == (4, 1, 4)

    # Списание — только администратор (решение 23.11, №7): у склада его нет
    сам = движение(место["кладовщик"], "writeoff", 1, "разбили при выгрузке")
    assert сам["status"] == 200 and _остатки(вариант) == (4, 1, 4)
    assert движение(место["админ"], "writeoff", 1, "разбили при выгрузке")["status"] == 302
    assert (
        движение(место["кладовщик"], "return_to_seller", 1, "продавец забрал образец")["status"]
        == 302
    )
    assert движение(место["кладовщик"], "adjust", 3, "нашли при пересчёте")["status"] == 302
    assert движение(место["кладовщик"], "adjust", -2, "недостача при пересчёте")["status"] == 302
    assert _остатки(вариант) == (3, 1, 3)
    assert sql(
        "select kind, quantity, reason from market_stock_movements where variant_id = %s "
        "and kind <> 'receipt' order by id",
        [вариант],
    ) == [
        ("writeoff", -1, "разбили при выгрузке"),
        ("return_to_seller", -1, "продавец забрал образец"),
        ("adjust", 3, "нашли при пересчёте"),
        ("adjust", -2, "недостача при пересчёте"),
    ]
    assert журнал("created")["section"] == "market_stock"
    _склады_сходятся()

    # В карточке товара остаток — только смотреть: POST его не меняет
    _, карточка = django(
        _сотрудник_market(), ("get", f"/py/admin/market/product/{данные['товар']}/change/", None)
    )
    assert карточка["status"] == 200 and 'name="variants-0-stock"' not in карточка["body"]


def _сотрудник_market() -> int:
    from .test_market import _сотрудник

    return _сотрудник("moderator")


# ── Разделы ролей ───────────────────────────────────────────────────


@нужна_база
def test_склад_и_пункт_в_своих_разделах(сайт, место):
    for uid, закрыто in (
        (
            место["выдающий"],
            (
                "/py/admin/market/order/",
                "/py/admin/market/supply/",
                "/py/admin/market/shipment/",
                "/py/admin/market/stockmovement/",
            ),
        ),
        (место["кладовщик"], ("/py/admin/market/pointorder/", "/py/admin/market/pointshipment/")),
    ):
        ответы = django(uid, *(("get", путь, None) for путь in закрыто))[1:]
        assert [о["status"] for о in ответы] == [403] * len(закрыто)

    ответы = django(
        место["выдающий"],
        ("get", "/py/admin/market/pointorder/", None),
        ("get", "/py/admin/market/pointshipment/", None),
    )[1:]
    assert [о["status"] for о in ответы] == [200, 200]


@нужна_база
def test_отказ_при_получении(сайт, место):
    данные = _продавец_и_товар(stock=3)
    _, number, pk = _заказ(сайт, данные["вариант"])
    _до_выдачи(pk, место["кладовщик"], выдать=False)
    карточка = f"/py/admin/market/pointorder/{pk}/"

    отказ = _действие(место["выдающий"], карточка, do="refuse")
    assert "отказ при получении" in отказ["body"]
    assert _статус(number) == "cancelled"
    assert sql("select cancel_reason from market_orders where id = %s", [pk]) == [
        ("отказ при получении",)
    ]
    # Резерв снят, остаток — на месте: товар поедет на склад с невостребованными
    assert _остатки(данные["вариант"]) == (3, 0, 3)
    assert журнал("cancelled")["section"] == "market_pickup"
    assert "уже недоступно" in _действие(место["выдающий"], карточка, do="refuse")["body"]
