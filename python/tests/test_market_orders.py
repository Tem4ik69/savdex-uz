"""
Заказ маркетплейса, этап 1 (savdex/market/orders.py): правила
docs/marketplace-security.md, разделы 1, 3 и 5.

- цена из запроса ничего не значит: сумма, которую видел покупатель
  (expectedTotal), не совпала с серверной — 409 и свежая корзина; в
  позицию копируются цена, название, ИКПУ и процент комиссии;
- последняя штука — одному: второе оформление получает «товар закончился»;
- резерв снимается ровно один раз — при отмене и при истечении
  неоплаченного картой заказа;
- чужой заказ — 404, как несуществующий;
- продавец видит только свою часть, о покупателе — имя, без телефона и почты;
- журнал денег: каждая группа сходится в ноль, записи не меняются и не
  удаляются (у роли приложения нет update и delete);
- после отгрузки со склада покупатель заказ не отменит; оплаченный картой —
  в «ожидает возврата».

Нужен PostgreSQL (SAVDEX_PARITY_PG_URL).
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest

from savdex.market import orders

from .pg_admin import PYTHON, ОКРУЖЕНИЕ, sql, нужна_база, свежая_база
from .test_market import _get, _get_as, _json, _post, _компания, _продавец, _товар, _человек
from .web_site import адрес

# ── Без базы ────────────────────────────────────────────────────────


def test_проводка_не_сходится_до_базы():
    """post() отказывает раньше, чем дойдёт до базы: сумма не ноль, ноль, дробь, чужой счёт."""
    with pytest.raises(ValueError, match="ноль"):
        orders.post(
            None, [orders.Entry("buyer_receivable", 100), orders.Entry("seller_payable", -99)]
        )

    for плохая in (
        [orders.Entry("buyer_receivable", 0)],
        [orders.Entry("нет-такого", 100), orders.Entry("seller_payable", -100)],
        [orders.Entry("buyer_receivable", 1.5), orders.Entry("seller_payable", -1.5)],  # type: ignore[arg-type]
        [],
    ):
        with pytest.raises(ValueError):
            orders.post(None, плохая)


def test_комиссия_и_переходы():
    assert orders.commission_of(400_000_000, Decimal(10)) == 40_000_000
    # Половина тийина — вверх, больше суммы — никогда
    assert orders.commission_of(5, Decimal("10")) == 1
    assert orders.commission_of(100, Decimal(100)) == 100

    # Отмена покупателем — только до отгрузки со склада
    assert orders.IN_TRANSIT not in orders.CANCELLABLE
    assert orders.READY not in orders.CANCELLABLE
    assert orders.CANCELLED not in orders.TRANSITIONS[orders.IN_TRANSIT]
    # Возвращённый снова оплаченным не становится
    assert orders.TRANSITIONS[orders.REFUNDED] == frozenset()

    with pytest.raises(orders.TransitionError):
        orders.transition(1, orders.ISSUED, orders.CANCELLED, actor="buyer")


# ── Данные ──────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def сайт() -> Iterator[str]:
    свежая_база()

    with адрес() as root:
        yield root


@pytest.fixture(scope="module")
def магазин(сайт) -> dict[str, Any]:
    """Два продавца, у каждого товар; у второго — ещё товар в одном экземпляре; пункт выдачи."""
    первая = _компания("Chorsu Tech", "chorsu-tech")
    продавец = _продавец(первая)
    телефон, вариант_телефона = _товар(
        продавец, "smartphones", "Смартфон Galaxy A55", "galaxy-a55", price=4_000_000, stock=20
    )
    вторая = _компания("Bolajon Toys", "bolajon-toys")
    второй = _продавец(вторая)
    _, кубики = _товар(второй, "toys", "Кубики деревянные", "cubes", price=90_000, stock=20)
    _, последняя = _товар(второй, "toys", "Пазл редкий", "rare-puzzle", price=150_000, stock=1)
    sql(
        "insert into market_pickup_points (code, name, address) values "
        "('chilonzor', 'ПВЗ Чиланзар', 'Ташкент, Чиланзар, 9-й квартал'), "
        "('closed', 'Закрытый пункт', 'Ташкент') "
    )
    sql("update market_pickup_points set is_active = false where code = 'closed'")

    return {
        "телефон": телефон,
        "вариант_телефона": вариант_телефона,
        "кубики": кубики,
        "последняя": последняя,
        "компания": первая,
        "вторая": вторая,
        "продавец": продавец,
    }


_номер_покупателя = iter(range(1, 1000))


def _покупатель(name: str = "Азиз Каримов") -> int:
    """Покупатель с телефоном и почтой — их не должно быть в ответах продавцу."""
    n = next(_номер_покупателя)
    [(uid,)] = sql(
        "insert into users (name, email, password, status, phone, email_verified_at, "
        "created_at, updated_at) values (%s, %s, 'x', 'active', %s, now(), now(), now()) "
        "returning id",
        [name, f"buyer{n}@mail.example", f"+9989012{n:05d}"],
    )

    return int(uid)


def _в_корзину(uid: int, variant: int, quantity: int = 1) -> None:
    sql(
        "insert into market_cart_items (user_id, variant_id, quantity) values (%s, %s, %s)",
        [uid, variant, quantity],
    )


def _оформить(
    сайт: str, uid: int, total: Any, method: str = "cash", point: str = "chilonzor", **лишнее: Any
) -> dict[str, Any]:
    return _post(
        сайт,
        "/market/api/checkout",
        uid,
        {"pickupPoint": point, "paymentMethod": method, "expectedTotal": total, **лишнее},
    )


def _резерв(variant: int) -> int:
    [(reserved,)] = sql("select reserved from market_product_variants where id = %s", [variant])

    return int(reserved)


def _статус(number: str) -> str:
    [(status,)] = sql("select status from market_orders where number = %s", [number])

    return str(status)


def _id(number: str) -> int:
    [(pk,)] = sql("select id from market_orders where number = %s", [number])

    return int(pk)


def _manage(*args: str) -> subprocess.CompletedProcess[str]:
    """manage.py под ролью приложения (как на сервере): права миграции проверяются тоже."""
    return subprocess.run(
        [sys.executable, "manage.py", *args],
        cwd=PYTHON,
        env={**ОКРУЖЕНИЕ, "PYTHONPATH": str(PYTHON)},
        capture_output=True,
        text=True,
    )


def _python(code: str) -> str:
    """Код этапа 2 (оплата) — вызовом функции заказа, как его позовёт колбэк Uzum."""
    итог = _manage("shell", "-c", code)
    assert итог.returncode == 0, итог.stderr[-3000:]

    # Последняя строка: shell может напечатать и своё (что импортировал сам)
    return итог.stdout.strip().splitlines()[-1]


# ── Оформление ──────────────────────────────────────────────────────


@нужна_база
def test_проверка_формы(сайт, магазин):
    покупатель = _покупатель()
    _в_корзину(покупатель, магазин["вариант_телефона"])

    нет_способа = _оформить(сайт, покупатель, 4_000_000, method="crypto")
    assert нет_способа["status"] == 422 and "paymentMethod" in _json(нет_способа)["errors"]
    закрытый = _оформить(сайт, покупатель, 4_000_000, point="closed")
    assert закрытый["status"] == 422 and "pickupPoint" in _json(закрытый)["errors"]
    без_суммы = _оформить(сайт, покупатель, None)
    assert без_суммы["status"] == 422 and "expectedTotal" in _json(без_суммы)["errors"]
    assert _оформить(сайт, None, 4_000_000)["status"] == 401

    пустая = _покупатель()
    assert _оформить(сайт, пустая, 4_000_000)["status"] == 422
    assert sql(
        "select count(*) from market_orders where buyer_user_id in (%s, %s)", [покупатель, пустая]
    ) == [(0,)]


@нужна_база
def test_цена_из_запроса_не_действует(сайт, магазин):
    покупатель = _покупатель()
    телефон = магазин["вариант_телефона"]
    _в_корзину(покупатель, телефон, 2)
    до = _резерв(телефон)

    # Подменённая цена и сумма — 409 со свежей корзиной, заказа нет, резерва нет
    подмена = _оформить(сайт, покупатель, 1, price=1, total=1)
    assert подмена["status"] == 409, подмена["body"]
    assert _json(подмена)["cart"]["total"] == 8_000_000
    assert sql("select count(*) from market_orders where buyer_user_id = %s", [покупатель]) == [
        (0,)
    ]
    assert _резерв(телефон) == до

    # Продавец поднял цену, пока покупатель смотрел корзину — тоже 409
    sql("update market_product_variants set price = 410000000 where id = %s", [телефон])
    подорожал = _оформить(сайт, покупатель, 8_000_000)
    assert подорожал["status"] == 409 and _json(подорожал)["cart"]["total"] == 8_200_000
    sql("update market_product_variants set price = 400000000 where id = %s", [телефон])

    ответ = _оформить(сайт, покупатель, 8_000_000)
    assert ответ["status"] == 201, ответ["body"]
    заказ = _json(ответ)["order"]
    assert заказ["total"] == 8_000_000 and заказ["status"]["code"] == "cash_on_pickup"
    assert re.fullmatch(r"[0-9A-Z]{10}", заказ["number"])
    assert заказ["number"] != str(_id(заказ["number"]))
    assert [p["seller"]["slug"] for p in заказ["parts"]] == ["chorsu-tech"]

    # Копия на момент покупки; корзина пуста; резерв +2
    позиция = sql(
        "select title, ikpu, price, quantity, line_total, commission_percent, commission "
        "from market_order_items where order_id = %s",
        [_id(заказ["number"])],
    )
    assert позиция == [
        (
            "Смартфон Galaxy A55",
            "12345678901234567",
            400_000_000,
            2,
            800_000_000,
            Decimal("10.00"),
            80_000_000,
        )
    ]
    assert sql("select count(*) from market_cart_items where user_id = %s", [покупатель]) == [(0,)]
    assert _резерв(телефон) == до + 2

    # Цена товара потом поменялась — заказ живёт на копии
    sql("update market_product_variants set price = 500000000 where id = %s", [телефон])
    свой = _json(_get_as(сайт, f"/market/api/orders/{заказ['number']}", покупатель))["order"]
    assert свой["total"] == 8_000_000 and свой["parts"][0]["items"][0]["price"] == 4_000_000
    sql("update market_product_variants set price = 400000000 where id = %s", [телефон])


@нужна_база
def test_последняя_штука_одному(сайт, магазин):
    последняя = магазин["последняя"]
    первый, второй = _покупатель(), _покупатель()
    _в_корзину(первый, последняя)
    _в_корзину(второй, последняя)

    assert _оформить(сайт, первый, 150_000)["status"] == 201
    опоздал = _оформить(сайт, второй, 150_000)

    assert опоздал["status"] == 409
    assert _json(опоздал)["message"] == "Товар закончился"
    assert _json(опоздал)["cart"]["total"] == 0
    assert sql(
        "select stock, reserved from market_product_variants where id = %s", [последняя]
    ) == [(1, 1)]
    assert sql("select count(*) from market_orders where buyer_user_id = %s", [второй]) == [(0,)]
    # Строка второго осталась в корзине — «закончился» видно на странице
    assert sql("select count(*) from market_cart_items where user_id = %s", [второй]) == [(1,)]


# ── Отмена и истечение ──────────────────────────────────────────────


@нужна_база
def test_отмена_снимает_резерв_один_раз(сайт, магазин):
    покупатель = _покупатель()
    кубики = магазин["кубики"]
    _в_корзину(покупатель, кубики, 3)
    до = _резерв(кубики)
    number = _json(_оформить(сайт, покупатель, 270_000))["order"]["number"]
    assert _резерв(кубики) == до + 3

    отмена = _post(сайт, f"/market/api/orders/{number}/cancel", покупатель, {"reason": "передумал"})
    assert отмена["status"] == 200, отмена["body"]
    assert _json(отмена)["order"]["status"]["code"] == "cancelled"
    assert _резерв(кубики) == до

    # Второй щелчок — отказ, резерв не уходит в минус и не снимается дважды
    ещё = _post(сайт, f"/market/api/orders/{number}/cancel", покупатель)
    assert ещё["status"] == 409
    assert _резерв(кубики) == до
    assert sql(
        "select from_status, to_status, actor from market_order_events where order_id = %s "
        "order by id",
        [_id(number)],
    ) == [
        (None, "created", "buyer"),
        ("created", "cash_on_pickup", "buyer"),
        ("cash_on_pickup", "cancelled", "buyer"),
    ]
    # Начисление при получении и обратное — по каждому счёту в ноль
    assert sql(
        "select account, sum(amount) from market_ledger where order_id = %s "
        "group by account order by account",
        [_id(number)],
    ) == [("buyer_receivable", 0), ("commission_revenue", 0), ("seller_payable", 0)]


@нужна_база
def test_истечение_неоплаченной_карты(сайт, магазин):
    покупатель = _покупатель()
    кубики = магазин["кубики"]
    до = _резерв(кубики)
    _в_корзину(покупатель, кубики, 2)
    старый = _json(_оформить(сайт, покупатель, 180_000, method="card"))["order"]
    assert старый["status"]["code"] == "created"
    _в_корзину(покупатель, кубики, 1)
    свежий = _json(_оформить(сайт, покупатель, 90_000, method="card"))["order"]
    assert _резерв(кубики) == до + 3
    # Картой — в журнал денег ничего, пока деньги не пришли
    assert sql(
        "select count(*) from market_ledger where order_id in (%s, %s)",
        [_id(старый["number"]), _id(свежий["number"])],
    ) == [(0,)]

    sql(
        "update market_orders set created_at = created_at - interval '2 hours' where number = %s",
        [старый["number"]],
    )
    итог = _manage("market_expire_orders")
    assert итог.returncode == 0, итог.stderr[-3000:]
    assert "Отменено неоплаченных заказов: 1." in итог.stdout
    assert _статус(старый["number"]) == "cancelled" and _статус(свежий["number"]) == "created"
    assert _резерв(кубики) == до + 1

    # Повтор ничего не снимает второй раз
    assert "заказов: 0." in _manage("market_expire_orders").stdout
    assert _резерв(кубики) == до + 1

    # И отмена истёкшего покупателем — отказ, резерв тот же
    assert _post(сайт, f"/market/api/orders/{старый['number']}/cancel", покупатель)["status"] == 409
    assert _резерв(кубики) == до + 1


@нужна_база
def test_отмена_после_отгрузки_нельзя(сайт, магазин):
    покупатель = _покупатель()
    кубики = магазин["кубики"]
    _в_корзину(покупатель, кубики)
    number = _json(_оформить(сайт, покупатель, 90_000))["order"]["number"]
    резерв = _резерв(кубики)
    # Склад отгрузил (этап склада): статус заказа и частей
    sql("update market_orders set status = 'in_transit' where number = %s", [number])
    sql("update market_order_parts set status = 'in_transit' where order_id = %s", [_id(number)])

    отказ = _post(сайт, f"/market/api/orders/{number}/cancel", покупатель)
    assert отказ["status"] == 409
    assert "отменить его нельзя" in _json(отказ)["message"]
    assert _статус(number) == "in_transit" and _резерв(кубики) == резерв
    assert (
        _json(_get_as(сайт, f"/market/api/orders/{number}", покупатель))["order"]["canCancel"]
        is False
    )


@нужна_база
def test_оплаченный_картой_ждёт_возврата(сайт, магазин):
    покупатель = _покупатель()
    кубики = магазин["кубики"]
    до = _резерв(кубики)
    _в_корзину(покупатель, кубики)
    number = _json(_оформить(сайт, покупатель, 90_000, method="card"))["order"]["number"]
    pk = _id(number)

    # Сумма не та — оплата не принимается
    assert _python(f"from savdex.market import orders; print(orders.mark_paid({pk}, 1))") == "False"
    assert _python(f"from savdex.market import orders; print(orders.mark_paid({pk}, 9000000))") == (
        "True"
    )
    # Повтор колбэка — второй раз не начисляет
    assert _python(f"from savdex.market import orders; print(orders.mark_paid({pk}, 9000000))") == (
        "False"
    )
    assert _статус(number) == "paid"

    отмена = _post(сайт, f"/market/api/orders/{number}/cancel", покупатель)
    assert отмена["status"] == 200, отмена["body"]
    assert _статус(number) == "refund_pending" and _резерв(кубики) == до
    assert sql(
        "select account, sum(amount) from market_ledger where order_id = %s "
        "group by account order by account",
        [pk],
    ) == [
        ("commission_revenue", 0),
        ("gateway_clearing", 9_000_000),
        ("refund_payable", -9_000_000),
        ("seller_payable", 0),
    ]

    assert _python(f"from savdex.market import orders; print(orders.mark_refunded({pk}))") == "True"
    assert _статус(number) == "refunded"
    assert sql(
        "select count(*) from (select account from market_ledger where order_id = %s "
        "group by account having sum(amount) <> 0) t",
        [pk],
    ) == [(0,)]


# ── Чужое и продавец ────────────────────────────────────────────────


@нужна_база
def test_чужой_заказ_404(сайт, магазин):
    хозяин, чужой = _покупатель(), _покупатель()
    _в_корзину(хозяин, магазин["кубики"])
    number = _json(_оформить(сайт, хозяин, 90_000))["order"]["number"]

    assert _get_as(сайт, f"/market/api/orders/{number}", хозяин)["status"] == 200
    assert _get_as(сайт, f"/market/api/orders/{number.lower()}", хозяин)["status"] == 200

    чужому = _get_as(сайт, f"/market/api/orders/{number}", чужой)
    нет_такого = _get_as(сайт, "/market/api/orders/ZZZZZZZZZZ", чужой)
    assert чужому["status"] == нет_такого["status"] == 404
    assert _json(чужому) == _json(нет_такого)
    assert _post(сайт, f"/market/api/orders/{number}/cancel", чужой)["status"] == 404
    assert _статус(number) == "cash_on_pickup"
    assert _json(_get_as(сайт, "/market/api/orders", чужой)) == {"orders": []}
    assert [o["number"] for o in _json(_get_as(сайт, "/market/api/orders", хозяин))["orders"]] == [
        number
    ]
    assert _get(сайт, f"/market/api/orders/{number}")["status"] == 401


@нужна_база
def test_продавец_видит_только_свою_часть(сайт, магазин):
    покупатель = _покупатель("Дилноза Юсупова")
    [(телефон, почта)] = sql("select phone, email from users where id = %s", [покупатель])
    _в_корзину(покупатель, магазин["вариант_телефона"])
    _в_корзину(покупатель, магазин["кубики"], 2)
    заказ = _json(_оформить(сайт, покупатель, 4_180_000))["order"]
    assert len(заказ["parts"]) == 2

    первый = _человек("owner@chorsu.uz", магазин["компания"])
    второй = _человек("owner@bolajon.uz", магазин["вторая"])
    ответ = _get_as(сайт, "/market/api/me/orders", первый)
    assert ответ["status"] == 200, ответ["body"]
    свои = [o for o in _json(ответ)["orders"] if o["number"] == заказ["number"]]

    assert len(свои) == 1
    assert свои[0]["buyer"] == {"name": "Дилноза Юсупова"}
    assert [i["title"] for i in свои[0]["items"]] == ["Смартфон Galaxy A55"]
    assert свои[0]["total"] == 4_000_000 and свои[0]["payout"] == 3_600_000
    assert телефон not in ответ["body"] and почта not in ответ["body"]
    assert "phone" not in ответ["body"] and "email" not in ответ["body"]

    у_второго = [
        o
        for o in _json(_get_as(сайт, "/market/api/me/orders", второй))["orders"]
        if o["number"] == заказ["number"]
    ]
    assert [i["title"] for i in у_второго[0]["items"]] == ["Кубики деревянные"]

    # Не продавец — 403, гость — 401
    assert _get_as(сайт, "/market/api/me/orders", покупатель)["status"] == 403
    assert _get(сайт, "/market/api/me/orders")["status"] == 401


# ── Журнал денег ────────────────────────────────────────────────────


@нужна_база
def test_журнал_денег_сходится_и_не_меняется(сайт, магазин):
    import psycopg

    покупатель = _покупатель()
    _в_корзину(покупатель, магазин["кубики"])
    number = _json(_оформить(сайт, покупатель, 90_000))["order"]["number"]

    assert sql("select count(distinct entry_group) from market_ledger")[0][0] > 0
    assert (
        sql("select entry_group from market_ledger group by entry_group having sum(amount) <> 0")
        == []
    )
    [(строка,)] = sql(
        "select id from market_ledger where order_id = %s and account = 'buyer_receivable'",
        [_id(number)],
    )

    # Даже владельцу базы: не правится, не удаляется, несходящаяся группа не пишется
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        sql("update market_ledger set amount = amount + 1 where id = %s", [строка])
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        sql("delete from market_ledger where id = %s", [строка])
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        sql("delete from market_order_events where order_id = %s", [_id(number)])
    with pytest.raises(psycopg.errors.CheckViolation):
        sql(
            "insert into market_ledger (entry_group, account, amount) "
            "values (gen_random_uuid(), 'seller_payable', 100)"
        )


@нужна_база
def test_у_роли_приложения_журнал_только_дописывается(сайт):
    if not sql("select 1 from pg_roles where rolname = 'savdex_django'"):
        pytest.skip("нет роли savdex_django — права миграции проверить не на ком")

    for table in ("market_ledger", "market_order_events"):
        assert sql(
            "select has_table_privilege('savdex_django', %s, 'insert'), "
            "has_table_privilege('savdex_django', %s, 'update'), "
            "has_table_privilege('savdex_django', %s, 'delete')",
            [table, table, table],
        ) == [(True, False, False)], table

    assert sql(
        "select has_table_privilege('savdex_django', 'market_orders', 'update'), "
        "has_table_privilege('savdex_django', 'market_orders', 'delete')"
    ) == [(True, False)]
