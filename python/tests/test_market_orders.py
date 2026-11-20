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
  в «ожидает возврата»;
- незавершённых заказов у покупателя не больше пяти; не собранный за 48
  часов заказ с оплатой при получении отменяется сам;
- продавец не видит неоплаченный картой заказ — ни ждущий, ни отменённый;
- куплено меньше, чем лежало в корзине, — остаток строки остаётся;
- сводка остатка товара пересчитывается при оформлении и снятии резерва;
- пользователя с заказами админка навсегда не удаляет — понятный отказ;
- в лимите — и отменённые самим покупателем за сутки;
- сотрудник (market_orders.moderate) ведёт заказ до выдачи и отменяет
  заказ до отгрузки (оплаченный картой — к возврату); поддержке — 403;
- выдача списывает остаток и резерв ровно один раз, продажи растут.

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
from savdex.market.common import MAX_PRICE_SOM, tiyin

from .pg_admin import PYTHON, ОКРУЖЕНИЕ, django, sql, журнал, нужна_база, свежая_база
from .test_market import (
    _get,
    _get_as,
    _json,
    _post,
    _компания,
    _продавец,
    _сотрудник,
    _товар,
    _человек,
)
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


def test_сумма_заказа_не_режется_пределом_цены():
    """expectedTotal большой корзины больше цены одной штуки — сравнивается честно."""
    большая = MAX_PRICE_SOM * 3
    assert tiyin(большая) is None
    assert orders.total_tiyin(большая) == большая * 100
    assert orders.total_tiyin(orders.MAX_TOTAL_SOM) == orders.MAX_TOTAL_SOM * 100
    assert orders.total_tiyin("125 000,50") == 12_500_050
    assert orders.total_tiyin(0) == 0

    for плохая in (
        orders.MAX_TOTAL_SOM + 1,
        -1,
        "1.001",
        "Infinity",
        "NaN",
        "1e999999",
        "abc",
        True,
        None,
    ):
        assert orders.total_tiyin(плохая) is None, плохая


def test_доставка_в_журнале_сходится():
    """С доставкой группа начисления и обратная ей — в ноль; доставка — свой счёт."""
    заказ = {"id": 7, "total": 1_150_000, "delivery_total": 150_000}
    части = [
        {"id": 1, "seller_id": 3, "subtotal": 600_000, "commission": 60_000},
        {"id": 2, "seller_id": 4, "subtotal": 400_000, "commission": 0},
    ]
    начисление = orders.accrual_entries(заказ, части, "buyer_receivable", "заказ")
    обратно = orders.reversal_entries(начисление, "buyer_receivable", "refund_payable", "отмена")

    for группа in (начисление, обратно):
        assert sum(entry.amount for entry in группа) == 0
        assert {entry.account for entry in группа} <= set(orders.ACCOUNTS)

    assert [e.amount for e in начисление if e.account == "delivery_revenue"] == [-150_000]
    assert [e.amount for e in обратно if e.account == "delivery_revenue"] == [150_000]
    # Без доставки строки доставки нет (сумму 0 журнал не принимает)
    без = orders.accrual_entries(
        {"id": 7, "total": 1_000_000, "delivery_total": 0}, части, "gateway_clearing", "заказ"
    )
    assert "delivery_revenue" not in {entry.account for entry in без}
    assert sum(entry.amount for entry in без) == 0


def test_счета_журнала_совпадают_с_миграцией():
    """
    Ограничение market_ledger_account_check — тот же список, что ACCOUNTS:
    действует последнее по порядку миграций (касса, этап 3, его заменяет).
    """
    найдено = [
        совпадение
        for путь in sorted((PYTHON / "savdex/bootstrap/migrations").glob("*.sql"))
        for совпадение in re.finditer(
            r"market_ledger_account_check check \(account in \((.*?)\)\)",
            путь.read_text(encoding="utf-8"),
            re.S,
        )
    ]
    assert найдено
    assert set(re.findall(r"'(\w+)'", найдено[-1].group(1))) == set(orders.ACCOUNTS)


def test_поддержка_не_сортирует_по_сумме(monkeypatch):
    """Роль без подробностей: порядок по деньгам выкинут, столбца суммы для сортировки нет."""
    from savdex.adminsite import site
    from savdex.market.models import Order

    раздел = site._registry[Order]
    запрос: Any = object()
    monkeypatch.setattr(раздел, "ordering", ("-total", "-created_at"))
    monkeypatch.setattr(раздел, "sees_details", lambda request: False)

    assert раздел.get_ordering(запрос) == ("-created_at",)
    assert "total_text" not in раздел.get_sortable_by(запрос)
    monkeypatch.setattr(раздел, "ordering", ("total",))
    assert раздел.get_ordering(запрос) == ("-created_at", "-id")

    monkeypatch.setattr(раздел, "sees_details", lambda request: True)
    assert раздел.get_ordering(запрос) == ("total",)
    assert "total_text" in раздел.get_sortable_by(запрос)

    # Обычный порядок раздела — не по сумме
    assert all("total" not in field for field in type(раздел).ordering)


# ── Данные ──────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def _роль_django() -> None:
    """
    Роль savdex_django, как на сервере (так же, как в tests/test_schema.py):
    миграции выдают ей права, их проверяет
    test_у_роли_приложения_журнал_только_дописывается. В чистой базе CI её нет.

    Роль не удаляется после модуля и остаётся в кластере до конца потока
    тестов — как и у фикстуры в tests/test_schema.py: на ней держатся
    права и права по умолчанию, которые выдают миграции и свежая_база().
    """
    sql(
        "do $$ begin if not exists (select from pg_roles where rolname = 'savdex_django') "
        "then create role savdex_django; end if; end $$"
    )


@pytest.fixture(scope="module")
def сайт(_роль_django) -> Iterator[str]:
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
    # Свои «цена» и «итог» в запросе — лишние поля, их сервер не читает
    подмена = _post(
        сайт,
        "/market/api/checkout",
        покупатель,
        {
            "pickupPoint": "chilonzor",
            "paymentMethod": "cash",
            "expectedTotal": 1,
            "price": 1,
            "total": 1,
        },
    )
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
    assert "Отменено незавершённых заказов: 1." in итог.stdout
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
    # truncate построчные триггеры не ловят — свой триггер на оператор
    for table in ("market_ledger", "market_order_events"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            sql(f"truncate {table}")
    assert sql("select count(*) from market_ledger where order_id = %s", [_id(number)]) != [(0,)]
    with pytest.raises(psycopg.errors.CheckViolation):
        sql(
            "insert into market_ledger (entry_group, account, amount) "
            "values (gen_random_uuid(), 'seller_payable', 100)"
        )


@нужна_база
def test_у_роли_приложения_журнал_только_дописывается(сайт):
    # Роль заводит фикстура _роль_django до миграций — проверка идёт и в CI
    assert sql("select 1 from pg_roles where rolname = 'savdex_django'") == [(1,)]

    for table in ("market_ledger", "market_order_events"):
        assert sql(
            "select has_table_privilege('savdex_django', %s, 'insert'), "
            "has_table_privilege('savdex_django', %s, 'update'), "
            "has_table_privilege('savdex_django', %s, 'delete'), "
            "has_table_privilege('savdex_django', %s, 'truncate')",
            [table, table, table, table],
        ) == [(True, False, False, False)], table

    assert sql(
        "select has_table_privilege('savdex_django', 'market_orders', 'update'), "
        "has_table_privilege('savdex_django', 'market_orders', 'delete')"
    ) == [(True, False)]


# ── Резерв не копится, сводка, корзина, продавец ────────────────────


def _сводка(product: int) -> int:
    [(stock,)] = sql("select stock from market_products where id = %s", [product])

    return int(stock)


@нужна_база
def test_незавершённых_не_больше_пяти_и_истечение_при_получении(сайт, магазин):
    товар, вариант = _товар(
        магазин["продавец"], "toys", "Мяч футбольный", "football", price=50_000, stock=50
    )
    покупатель = _покупатель()
    номера = []

    for _ in range(orders.MAX_OPEN_ORDERS):
        _в_корзину(покупатель, вариант)
        ответ = _оформить(сайт, покупатель, 50_000)
        assert ответ["status"] == 201, ответ["body"]
        номера.append(_json(ответ)["order"]["number"])

    assert _резерв(вариант) == 5 and _сводка(товар) == 45

    # Шестой — 409 с понятным текстом; заказа и резерва нет, корзина цела
    _в_корзину(покупатель, вариант)
    шестой = _оформить(сайт, покупатель, 50_000)
    assert шестой["status"] == 409, шестой["body"]
    assert "5 незавершённых заказов" in _json(шестой)["message"]
    assert sql("select count(*) from market_orders where buyer_user_id = %s", [покупатель]) == [
        (5,)
    ]
    assert _резерв(вариант) == 5
    assert sql("select count(*) from market_cart_items where user_id = %s", [покупатель]) == [(1,)]

    # Не собранный за 48 часов заказ при получении отменяется сам — тем же
    # путём, что отмена: резерв снят один раз, начисление — назад
    старый = номера[0]
    sql(
        "update market_orders set created_at = created_at - interval '49 hours' where number = %s",
        [старый],
    )
    итог = _manage("market_expire_orders", "--minutes", "100000", "--hours", "48")
    assert итог.returncode == 0, итог.stderr[-3000:]
    assert "Отменено незавершённых заказов: 1." in итог.stdout
    assert _статус(старый) == "cancelled"
    assert all(_статус(number) == "cash_on_pickup" for number in номера[1:])
    assert _резерв(вариант) == 4 and _сводка(товар) == 46
    assert sql(
        "select to_status, actor from market_order_events where order_id = %s "
        "order by id desc limit 1",
        [_id(старый)],
    ) == [("cancelled", "system")]
    assert sql(
        "select count(*) from (select account from market_ledger where order_id = %s "
        "group by account having sum(amount) <> 0) t",
        [_id(старый)],
    ) == [(0,)]
    assert "заказов: 0." in _manage("market_expire_orders", "--minutes", "100000").stdout
    assert _резерв(вариант) == 4

    # Место освободилось — шестой оформляется
    assert _оформить(сайт, покупатель, 50_000)["status"] == 201


@нужна_база
def test_частичная_покупка_оставляет_остаток_в_корзине(сайт, магазин):
    товар, вариант = _товар(
        магазин["продавец"], "toys", "Юла светящаяся", "spinning-top", price=20_000, stock=2
    )
    покупатель = _покупатель()
    _в_корзину(покупатель, вариант, 5)

    # Корзина считает «можно купить сейчас» две штуки — их и покупаем
    ответ = _оформить(сайт, покупатель, 40_000)
    assert ответ["status"] == 201, ответ["body"]
    number = _json(ответ)["order"]["number"]
    assert sql("select quantity from market_order_items where order_id = %s", [_id(number)]) == [
        (2,)
    ]
    assert sql(
        "select quantity from market_cart_items where user_id = %s and variant_id = %s",
        [покупатель, вариант],
    ) == [(3,)]
    # Сводка товара — за вычетом резерва, в той же транзакции
    assert _резерв(вариант) == 2 and _сводка(товар) == 0

    отмена = _post(сайт, f"/market/api/orders/{number}/cancel", покупатель)
    assert отмена["status"] == 200, отмена["body"]
    assert _резерв(вариант) == 0 and _сводка(товар) == 2


@нужна_база
def test_продавец_не_видит_неоплаченную_карту(сайт, магазин):
    продавец = _человек("seller-card@chorsu.uz", магазин["компания"])
    покупатель = _покупатель()
    _в_корзину(покупатель, магазин["вариант_телефона"])
    ждёт = _json(_оформить(сайт, покупатель, 4_000_000, method="card"))["order"]["number"]
    _в_корзину(покупатель, магазин["вариант_телефона"])
    отменён = _json(_оформить(сайт, покупатель, 4_000_000, method="card"))["order"]["number"]
    assert _post(сайт, f"/market/api/orders/{отменён}/cancel", покупатель)["status"] == 200
    _в_корзину(покупатель, магазин["вариант_телефона"])
    оплачен = _json(_оформить(сайт, покупатель, 4_000_000, method="card"))["order"]["number"]
    pk = _id(оплачен)
    assert _python(
        f"from savdex.market import orders; print(orders.mark_paid({pk}, 400000000))"
    ) == ("True")

    видит = {o["number"] for o in _json(_get_as(сайт, "/market/api/me/orders", продавец))["orders"]}
    assert оплачен in видит
    assert ждёт not in видит and отменён not in видит


@нужна_база
def test_пользователя_с_заказами_не_удалить_навсегда(сайт, магазин):
    покупатель = _покупатель("Удаляемый Покупатель")
    _в_корзину(покупатель, магазин["кубики"])
    assert _оформить(сайт, покупатель, 90_000)["status"] == 201
    sql("update users set deleted_at = now() where id = %s", [покупатель])

    список = "/py/admin/accounts/user/"
    _, _, страница = django(
        _сотрудник("superadmin"),
        (
            "post",
            список,
            {"action": "force_delete", "_selected_action": [str(покупатель)], "post": "yes"},
        ),
        ("get", список + "?state=disabled", None),
    )

    assert страница["status"] == 200
    assert "У пользователя есть заказы маркетплейса — удалить нельзя" in страница["body"]
    assert sql("select count(*) from users where id = %s", [покупатель]) == [(1,)]
    assert sql("select count(*) from market_orders where buyer_user_id = %s", [покупатель]) == [
        (1,)
    ]


@нужна_база
def test_админка_заказов_имя_покупателя(сайт, магазин):
    покупатель = _покупатель("Шахноза Рашидова")
    _в_корзину(покупатель, магазин["кубики"])
    number = _json(_оформить(сайт, покупатель, 90_000))["order"]["number"]

    for role in ("admin", "support"):
        _, страница = django(_сотрудник(role), ("get", "/py/admin/market/order/", None))
        assert страница["status"] == 200, role
        assert number in страница["body"] and "Шахноза Рашидова" in страница["body"], role


# ── Лимит с отменами, шаги заказа в админке ────────────────────────


@нужна_база
def test_отменённые_покупателем_за_сутки_в_лимите(сайт, магазин):
    _, вариант = _товар(
        магазин["продавец"], "toys", "Скакалка", "jump-rope", price=10_000, stock=50
    )
    покупатель = _покупатель()

    for _ in range(orders.MAX_OPEN_ORDERS):
        _в_корзину(покупатель, вариант)
        number = _json(_оформить(сайт, покупатель, 10_000))["order"]["number"]
        assert _post(сайт, f"/market/api/orders/{number}/cancel", покупатель)["status"] == 200

    # Открытых нет, но пять отмен за сутки — цикл «оформить — отменить» упирается в лимит
    assert _резерв(вариант) == 0
    _в_корзину(покупатель, вариант)
    шестой = _оформить(сайт, покупатель, 10_000)
    assert шестой["status"] == 409, шестой["body"]
    assert "5 незавершённых заказов" in _json(шестой)["message"]

    # Сутки прошли — отмены больше не считаются
    sql(
        "update market_orders set cancelled_at = cancelled_at - interval '25 hours' "
        "where buyer_user_id = %s",
        [покупатель],
    )
    assert _оформить(сайт, покупатель, 10_000)["status"] == 201


def _шаг(uid: int, pk: int, decision: str, note: str = "") -> dict[str, Any]:
    """POST решения в карточке заказа и следующая за ним страница карточки."""
    адрес_заказа = f"/py/admin/market/order/{pk}/"
    _, ответ, страница = django(
        uid,
        ("post", адрес_заказа + "decide/", {"decision": decision, "note": note}),
        ("get", адрес_заказа + "change/", None),
    )
    assert ответ["status"] in (302, 403), ответ

    return {"status": ответ["status"], "body": страница["body"]}


@нужна_база
def test_сотрудник_ведёт_заказ_до_выдачи(сайт, магазин):
    покупатель = _покупатель()
    _в_корзину(покупатель, магазин["кубики"])
    number = _json(_оформить(сайт, покупатель, 90_000))["order"]["number"]
    pk = _id(number)
    администратор, поддержка = _сотрудник("admin"), _сотрудник("support")

    # Поддержка смотрит, но статус не двигает: кнопок нет, POST — 403
    _, карточка = django(поддержка, ("get", f"/py/admin/market/order/{pk}/change/", None))
    assert карточка["status"] == 200 and "В сборку" not in карточка["body"]
    assert _шаг(поддержка, pk, "to:cash_on_pickup:assembling")["status"] == 403
    assert _статус(number) == "cash_on_pickup"
    # GET решения — тоже 403: только POST
    _, без_post = django(администратор, ("get", f"/py/admin/market/order/{pk}/decide/", None))
    assert без_post["status"] == 403

    _, карточка = django(администратор, ("get", f"/py/admin/market/order/{pk}/change/", None))
    assert "В сборку" in карточка["body"] and "Отменить заказ" in карточка["body"]

    цепочка = [
        ("cash_on_pickup", "assembling"),
        ("assembling", "in_transit"),
        ("in_transit", "ready"),
        ("ready", "issued"),
    ]

    for before, after in цепочка:
        шаг = _шаг(администратор, pk, f"to:{before}:{after}", "склад BTS")
        assert шаг["status"] == 302
        assert _статус(number) == after
        запись = журнал("status_changed")
        assert запись["section"] == "market_orders" and запись["subject_label"] == number
        assert запись["changes"] == {"before": {"status": before}, "after": {"status": after}}

    assert sql("select status from market_order_parts where order_id = %s", [pk]) == [("issued",)]
    assert sql(
        "select from_status, to_status from market_order_events "
        "where order_id = %s and actor = 'staff' order by id",
        [pk],
    ) == [tuple(step) for step in цепочка]

    # Повтор того же шага — понятное сообщение, не 500, статус тот же
    повтор = _шаг(администратор, pk, "to:ready:issued")
    assert повтор["status"] == 302
    assert "Это решение уже недоступно" in повтор["body"]
    assert _статус(number) == "issued"
    # Выданный не отменить
    assert "Это решение уже недоступно" in _шаг(администратор, pk, "cancel:issued")["body"]


@нужна_база
def test_сборка_не_истекает_и_отмена_сотрудником(сайт, магазин):
    _, вариант = _товар(
        магазин["продавец"], "toys", "Конструктор", "constructor", price=30_000, stock=10
    )
    администратор = _сотрудник("admin")
    покупатель = _покупатель()
    _в_корзину(покупатель, вариант)
    собирается = _json(_оформить(сайт, покупатель, 30_000))["order"]["number"]
    _в_корзину(покупатель, вариант)
    отменяемый = _json(_оформить(сайт, покупатель, 30_000))["order"]["number"]
    assert _резерв(вариант) == 2

    assert _шаг(администратор, _id(собирается), "to:cash_on_pickup:assembling")["status"] == 302
    assert _статус(собирается) == "assembling"

    # 48-часовое истечение заказ в сборке не трогает
    sql(
        "update market_orders set created_at = created_at - interval '49 hours' where number = %s",
        [собирается],
    )
    итог = _manage("market_expire_orders", "--minutes", "100000", "--hours", "48")
    assert итог.returncode == 0, итог.stderr[-3000:]
    assert _статус(собирается) == "assembling" and _резерв(вариант) == 2

    # Отмена сотрудником — общий путь: резерв снят один раз, начисление назад
    шаг = _шаг(администратор, _id(отменяемый), "cancel:cash_on_pickup", "покупатель не придёт")
    assert шаг["status"] == 302
    assert _статус(отменяемый) == "cancelled" and _резерв(вариант) == 1
    assert журнал("cancelled")["subject_label"] == отменяемый
    assert sql(
        "select count(*) from (select account from market_ledger where order_id = %s "
        "group by account having sum(amount) <> 0) t",
        [_id(отменяемый)],
    ) == [(0,)]
    assert (
        "Это решение уже недоступно"
        in (_шаг(администратор, _id(отменяемый), "cancel:cash_on_pickup")["body"])
    )
    assert _резерв(вариант) == 1


def test_неудачный_шаг_заказа_предупреждение(monkeypatch):
    """Шаг не прошёл (статус уже сменили, остатка не хватило) — DecisionRefused, не «готово»."""
    import contextlib
    from types import SimpleNamespace

    from savdex.adminsite import site
    from savdex.market import admin as market_admin
    from savdex.market.models import Order

    раздел = site._registry[Order]
    заказ: Any = SimpleNamespace(pk=1, number="ABCDEFGH23")
    monkeypatch.setattr(market_admin.transaction, "atomic", contextlib.nullcontext)
    monkeypatch.setattr(market_admin, "_admin_of", lambda request: SimpleNamespace(id=1))
    monkeypatch.setattr(market_admin.orders, "advance", lambda *a, **k: False)
    monkeypatch.setattr(market_admin.orders, "staff_cancel", lambda *a, **k: None)

    for решение in ("to:assembling:in_transit", "cancel:paid"):
        with pytest.raises(market_admin.DecisionRefused, match="уже изменился"):
            раздел.decide(object(), заказ, решение, "", None)

    def нехватка(*a: Any, **k: Any) -> bool:
        raise orders.WriteOffError("нет остатка")

    monkeypatch.setattr(market_admin.orders, "advance", нехватка)

    with pytest.raises(market_admin.DecisionRefused, match="не выдан"):
        раздел.decide(object(), заказ, "to:ready:issued", "", None)


@нужна_база
def test_выдача_списывает_остаток_один_раз(сайт, магазин):
    товар, вариант = _товар(
        магазин["продавец"], "toys", "Машинка на пульте", "rc-car", price=70_000, stock=10
    )
    администратор = _сотрудник("admin")
    покупатель = _покупатель()
    _в_корзину(покупатель, вариант, 3)
    number = _json(_оформить(сайт, покупатель, 210_000))["order"]["number"]
    pk = _id(number)
    assert sql("select stock, reserved from market_product_variants where id = %s", [вариант]) == [
        (10, 3)
    ]
    assert _сводка(товар) == 7

    for before, after in (
        ("cash_on_pickup", "assembling"),
        ("assembling", "in_transit"),
        ("in_transit", "ready"),
    ):
        assert _шаг(администратор, pk, f"to:{before}:{after}")["status"] == 302

    # До выдачи остаток не тронут — только резерв
    assert sql("select stock, reserved from market_product_variants where id = %s", [вариант]) == [
        (10, 3)
    ]

    assert _шаг(администратор, pk, "to:ready:issued")["status"] == 302
    assert _статус(number) == "issued"
    assert sql("select stock, reserved from market_product_variants where id = %s", [вариант]) == [
        (7, 0)
    ]
    assert sql("select sold_count from market_products where id = %s", [товар]) == [(3,)]
    assert _сводка(товар) == 7
    assert sql(
        "select stock_written_off_at is not null, reserve_released_at is null "
        "from market_orders where id = %s",
        [pk],
    ) == [(True, True)]

    # Повтор шага — предупреждение, второй раз не списывает
    повтор = _шаг(администратор, pk, "to:ready:issued")
    assert 'class="warning"' in повтор["body"]
    assert "Это решение уже недоступно" in повтор["body"]
    # Резерв у выданного не снимается: его уже нет
    assert _python(f"from savdex.market import orders; print(orders.release_reserve({pk}))") == (
        "False"
    )
    assert sql("select stock, reserved from market_product_variants where id = %s", [вариант]) == [
        (7, 0)
    ]
    assert sql("select sold_count from market_products where id = %s", [товар]) == [(3,)]


@нужна_база
def test_сотрудник_отменяет_оплаченный_картой(сайт, магазин):
    _, вариант = _товар(
        магазин["продавец"], "toys", "Набор красок", "paints", price=40_000, stock=10
    )
    администратор = _сотрудник("admin")
    покупатель = _покупатель()
    номера = []

    for _ in range(2):
        _в_корзину(покупатель, вариант)
        number = _json(_оформить(сайт, покупатель, 40_000, method="card"))["order"]["number"]
        pk = _id(number)
        assert _python(
            f"from savdex.market import orders; print(orders.mark_paid({pk}, 4000000))"
        ) == ("True")
        номера.append(number)

    assert _резерв(вариант) == 2
    оплачен, собирается = номера
    assert _шаг(администратор, _id(собирается), "to:paid:assembling")["status"] == 302

    _, карточка = django(
        администратор, ("get", f"/py/admin/market/order/{_id(оплачен)}/change/", None)
    )
    assert "Отменить заказ (деньги — к возврату)" in карточка["body"]

    for number, before in ((оплачен, "paid"), (собирается, "assembling")):
        шаг = _шаг(администратор, _id(number), f"cancel:{before}", "нет в наличии у продавца")
        assert шаг["status"] == 302
        assert _статус(number) == "refund_pending"
        assert журнал("cancelled")["changes"]["after"] == {"status": "refund_pending"}
        # Обратная проводка — как у отмены покупателем: долг покупателю
        assert sql(
            "select account, sum(amount) from market_ledger where order_id = %s "
            "group by account order by account",
            [_id(number)],
        ) == [
            ("commission_revenue", 0),
            ("gateway_clearing", 4_000_000),
            ("refund_payable", -4_000_000),
            ("seller_payable", 0),
        ]

    assert _резерв(вариант) == 0
