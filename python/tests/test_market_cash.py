"""
Касса маркетплейса, этап 3 (savdex/market/cash.py, cash_admin.py): правила
docs/marketplace-security.md, разделы 3 и 4.

- выплата в два шага: создал один кассир, подтверждает другой — тот же не
  может; выше доступного — отказ; заблокированному продавцу — нельзя;
- отметка «выплачено» пишет в журнал денег одну сходящуюся группу —
  ровно один раз; номер платёжки — один на выплату; доступное
  перепроверяется; выплату не переписать и мимо кода (триггер);
- подтверждённую отменяет только подтвердивший, с отметкой «платёжка не
  отправлялась»;
- реквизиты сменены меньше суток назад — подтверждение только с отметкой
  «реквизиты сверены» и заметкой; сменились после подтверждения — не
  выплатить; смена — только с паролем, с уведомлением владельцу; невидимые
  символы — отказ; в списке админки счёт скрыт;
- наличные заказа идут «к выплате» только после сверки с отчётом BTS;
- у своей компании не купить;
- модератор, поддержка, склад кассы не видят (403); склад ведёт заказ по
  шагам до выдачи, но не отменяет и сумм не видит; выдача «при
  получении» закрывает долг покупателя наличными;
- продавец видит только свой баланс; реквизиты — только владелец компании;
- заказ, ждущий возврата, в доступное не входит; ручной возврат — только
  взятый на себя или запрошенный, с номером возврата у провайдера.

Нужен PostgreSQL (SAVDEX_PARITY_PG_URL); проверки без базы — в начале.
"""

from __future__ import annotations

from collections.abc import Iterator
from itertools import count
from typing import Any

import bcrypt
import pytest

from savdex import access
from savdex.market import cash

from .pg_admin import django, sql, журнал, нужна_база, свежая_база
from .test_market import _get_as, _json, _post, _компания, _продавец, _сотрудник, _товар, _человек
from .test_market_orders import _id, _python, _в_корзину, _оформить, _покупатель, _статус
from .web_site import адрес

# ── Без базы ────────────────────────────────────────────────────────


def test_роли_кассы_и_склада():
    касса = set(access.abilities_for("cashier"))
    склад = set(access.abilities_for("warehouse"))

    assert касса == {f"market_cash.{a}" for a in ("view", "create", "edit", "moderate")}
    # Касса не правит заказы, остатки и товары и не двигает заказ
    for право in (
        "market.edit",
        "market_stock.edit",
        "market_stock.moderate",
        "market_orders.moderate",
    ):
        assert право not in касса

    # Склад: шаги заказа (market_stock.moderate), заказы — только смотреть, денег нет
    assert "market_stock.moderate" in склад and "market_orders.view" in склад
    assert "market_orders.moderate" not in склад
    assert not [a for a in склад if a.startswith(("market_cash", "market."))]
    assert access.details_hidden("warehouse", "market_orders")

    # Модератор и поддержка — без кассы; администратор тоже: выплаты — роль кассы
    for роль in ("moderator", "support", "admin", "finance", "content_manager", "warehouse"):
        assert not [a for a in access.abilities_for(роль) if a.startswith("market_cash")], роль


def test_баланс_не_уходит_в_минус():
    баланс = cash.Balance(accrued=100, released=60, in_work=30, paid=40)

    assert баланс.on_hold == 40
    assert баланс.free == -10 and баланс.available == 0
    assert cash.Balance(accrued=100, released=100, in_work=0, paid=25).available == 75


def test_реквизиты_проверяются_до_базы():
    """Неверные реквизиты и невидимые символы отклоняются до базы."""
    _, ошибки = cash.validate_requisites(
        {
            "bankAccount": "2020 8000 1234",
            "bankMfo": "0044",
            "bankName": "",
            "recipientName": "x",
            "recipientTin": "12345678901",
        }
    )
    assert set(ошибки) == {"bankAccount", "bankMfo", "bankName", "recipientName", "recipientTin"}
    assert all(key.startswith("cash.") for key in ошибки.values())

    # RLO и символ нулевой ширины в названии — подмена того, что видит касса
    for плохое in ("ООО \u202eтсеТ", "Капитал\u200bбанк", "Банк\x07"):
        _, ошибки = cash.validate_requisites({**РЕКВИЗИТЫ, "bankName": плохое})
        assert set(ошибки) == {"bankName"}, плохое

    значения, ошибки = cash.validate_requisites(РЕКВИЗИТЫ)
    assert ошибки == {} and значения["bank_account"] == "20208000123456789012"
    assert cash.masked("20208000123456789012") == "•••• 9012"


def _касса_без_базы() -> access.Admin:
    return access.Admin(
        id=1, name="Кассир", email="c@savdex.uz", is_admin=True, role="cashier", status="active"
    )


def test_сверка_наличных_до_базы():
    """Отчёт BTS короче 10 знаков и пачка больше 100 — отказ раньше базы."""
    with pytest.raises(cash.CashRefused, match="отчёта BTS"):
        cash.reconcile_cash(_касса_без_базы(), [1], "отчёт 1")

    with pytest.raises(cash.CashRefused, match="Не больше 100"):
        cash.reconcile_cash(_касса_без_базы(), range(1, 102), "отчёт BTS №77 от 20.11")


def test_ссылки_маркетплейса_на_пользователя_в_одном_списке():
    """
    Каждый внешний ключ маркетплейса на users с on delete restrict (держит
    строку users) — в MARKET_USER_REFERENCES: удаление навсегда его видит.
    """
    import re

    from savdex.accounts.admin import MARKET_USER_REFERENCES

    from .pg_admin import PYTHON

    найдено: set[str] = set()

    for путь in (PYTHON / "savdex/bootstrap/migrations").glob("*market*.sql"):
        текст = путь.read_text(encoding="utf-8")
        найдено |= set(
            re.findall(
                r"(\w+) bigint(?: not null)?\s+references users \(id\) on delete restrict", текст
            )
        )

    assert найдено == {column for _, column in MARKET_USER_REFERENCES}


# ── Данные ──────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def сайт() -> Iterator[str]:
    sql(
        "do $$ begin if not exists (select from pg_roles where rolname = 'savdex_django') "
        "then create role savdex_django; end if; end $$"
    )
    свежая_база()
    sql(
        "insert into market_pickup_points (code, name, address) "
        "values ('chilonzor', 'ПВЗ Чиланзар', 'Ташкент, Чиланзар, 9-й квартал')"
    )

    with адрес() as root:
        yield root


_номер = count(1)

#: Цена товара продавца — 90 000 сумов; комиссия 10 % — продавцу 81 000
ЦЕНА = 90_000

#: Пароль владельцев компаний-продавцов (хеш — как у Laravel, $2y$)
ПАРОЛЬ = "Kassa-2026-test"
_ХЕШ = bcrypt.hashpw(ПАРОЛЬ.encode(), bcrypt.gensalt(4)).decode().replace("$2b$", "$2y$", 1)

РЕКВИЗИТЫ = {
    "bankAccount": "2020 8000 1234 5678 9012",
    "bankMfo": "00440",
    "bankName": "Капиталбанк",
    "recipientName": "ООО «Тест»",
    "recipientTin": "301234567",
}


def _продавец_с_товаром() -> dict[str, Any]:
    n = next(_номер)
    компания = _компания(f"Касса Тест {n}", f"cash-test-{n}")
    продавец = _продавец(компания)
    _, вариант = _товар(продавец, "toys", f"Мяч {n}", f"ball-{n}", price=ЦЕНА, stock=50)
    владелец = _человек(f"owner{n}@cash.example", компания)
    sql("update users set password = %s where id = %s", [_ХЕШ, владелец])
    сотрудник = _человек(f"staff{n}@cash.example", компания, role="manager")

    return {
        "компания": компания,
        "продавец": продавец,
        "вариант": вариант,
        "владелец": владелец,
        "сотрудник": сотрудник,
    }


def _заказ(сайт: str, вариант: int, method: str = "cash") -> tuple[int, str, int]:
    покупатель = _покупатель()
    _в_корзину(покупатель, вариант)
    ответ = _оформить(сайт, покупатель, ЦЕНА, method=method)
    assert ответ["status"] == 201, ответ["body"]
    number = _json(ответ)["order"]["number"]

    return покупатель, number, _id(number)


def _выдать(pk: int, дней_назад: int = 0, *, сверить: bool = True) -> None:
    """
    Заказ с оплатой при получении — до выдачи (orders.advance), выдан
    дней_назад; наличные — сверены с отчётом BTS (иначе не «к выплате»).
    """
    админ = _сотрудник("admin")
    код = (
        "from savdex.market import orders\n"
        "for b in ('cash_on_pickup', 'assembling', 'in_transit', 'ready'):\n"
        f"    assert orders.advance({pk}, b, actor_user_id={админ})\n"
        "print('ok')"
    )
    assert _python(код) == "ok"
    # Сверка — как у кассы (cash.reconcile_cash): когда, кто и номер отчёта
    # вместе (их держит проверка market_orders_cash_reconciled_check)
    sql(
        "update market_orders set issued_at = issued_at - make_interval(days => %s), "
        "cash_reconciled_at = case when %s then now() at time zone 'utc' end, "
        "cash_reconciled_by = case when %s then %s::bigint end, "
        "cash_reconciled_ref = case when %s then 'BTS-test' end where id = %s",
        [дней_назад, сверить, сверить, админ, сверить, pk],
    )


def _реквизиты(сайт: str, владелец: int, часов_назад: int = 48, **поля: Any) -> None:
    ответ = _post(
        сайт, "/market/api/me/requisites", владелец, {**РЕКВИЗИТЫ, "password": ПАРОЛЬ, **поля}
    )
    assert ответ["status"] == 200, ответ["body"]

    if часов_назад:
        sql(
            "update market_seller_requisites set changed_at = changed_at "
            "- make_interval(hours => %s) where changed_by = %s",
            [часов_назад, владелец],
        )


def _кассир(номер: int = 1) -> int:
    if номер == 1:
        return _сотрудник("cashier")

    email = f"cashier{номер}@savdex.uz"
    found = sql("select id from users where email = %s", [email])

    if found:
        return int(found[0][0])

    [(uid,)] = sql(
        "insert into users (name, email, password, is_admin, admin_role, status, created_at, "
        "updated_at) values (%s, %s, 'x', true, 'cashier', 'active', now(), now()) returning id",
        [f"Кассир {номер}", email],
    )

    return int(uid)


def _выплата(uid: int, pk: int, do: str, **поля: str) -> dict[str, Any]:
    адрес_выплаты = f"/py/admin/market/payout/{pk}/"
    _, ответ, страница = django(
        uid,
        ("post", адрес_выплаты + "act/", {"do": do, **поля}),
        ("get", адрес_выплаты + "change/", None),
    )

    return {"status": ответ["status"], "body": страница["body"]}


def _создать(uid: int, продавец: int, сумма: Any) -> dict[str, Any]:
    _, ответ, страница = django(
        uid,
        ("post", f"/py/admin/market/sellerbalance/{продавец}/payout/", {"amount": str(сумма)}),
        ("get", f"/py/admin/market/sellerbalance/{продавец}/change/", None),
    )

    return {"status": ответ["status"], "location": ответ["location"], "body": страница["body"]}


def _выплаты(продавец: int) -> list[tuple[Any, ...]]:
    return sql(
        "select id, amount, status from market_payouts where seller_id = %s order by id",
        [продавец],
    )


def _готовая(сайт: str, сумма: int = 10_000) -> dict[str, Any]:
    """Продавец с выданным сверенным заказом, старыми реквизитами и подтверждённой выплатой."""
    данные = _продавец_с_товаром()
    _, _, pk = _заказ(сайт, данные["вариант"])
    _выдать(pk, дней_назад=8)
    _реквизиты(сайт, данные["владелец"])
    _создать(_кассир(1), данные["продавец"], сумма)
    [(выплата, _, _)] = _выплаты(данные["продавец"])
    assert _выплата(_кассир(2), выплата, "approve")["status"] == 302

    return {**данные, "заказ": pk, "выплата": выплата}


# ── Права ───────────────────────────────────────────────────────────


@нужна_база
def test_касса_закрыта_модератору_поддержке_складу(сайт):
    данные = _продавец_с_товаром()
    адреса = [
        "/py/admin/market/payout/",
        "/py/admin/market/sellerbalance/",
        "/py/admin/market/sellerrequisites/",
        "/py/admin/market/refundorder/",
        "/py/admin/market/cashorder/",
        f"/py/admin/market/sellerbalance/{данные['продавец']}/change/",
    ]

    for роль in ("moderator", "support", "warehouse", "admin"):
        ответы = django(_сотрудник(роль), *(("get", адрес, None) for адрес in адреса))[1:]
        assert [о["status"] for о in ответы] == [403] * len(адреса), роль

    # POST создания выплаты не той ролью — 403, выплаты нет
    _, создание = django(
        _сотрудник("support"),
        ("post", f"/py/admin/market/sellerbalance/{данные['продавец']}/payout/", {"amount": "1"}),
    )
    assert создание["status"] == 403
    assert _выплаты(данные["продавец"]) == []

    ответы = django(_кассир(), *(("get", адрес, None) for адрес in адреса))[1:]
    assert [о["status"] for о in ответы] == [200] * len(адреса)


@нужна_база
def test_склад_ведёт_заказ_до_выдачи(сайт):
    данные = _продавец_с_товаром()
    _, number, pk = _заказ(сайт, данные["вариант"])
    склад = _сотрудник("warehouse")
    карточка = f"/py/admin/market/order/{pk}/"

    _, страница = django(склад, ("get", карточка + "change/", None))
    assert страница["status"] == 200
    assert "В сборку" in страница["body"]
    # Отменить склад не может, сумм не видит
    assert "Отменить заказ" not in страница["body"]
    assert "90 000 сум" not in страница["body"]

    _, отмена = django(склад, ("post", карточка + "decide/", {"decision": "cancel:cash_on_pickup"}))
    assert отмена["status"] == 302 and _статус(number) == "cash_on_pickup"

    for before, after in (
        ("cash_on_pickup", "assembling"),
        ("assembling", "in_transit"),
        ("in_transit", "ready"),
        ("ready", "issued"),
    ):
        _, шаг = django(склад, ("post", карточка + "decide/", {"decision": f"to:{before}:{after}"}))
        assert шаг["status"] == 302 and _статус(number) == after
        assert журнал("status_changed")["section"] == "market_stock"

    # Выдан при получении: долг покупателя закрыт наличными — один раз
    assert sql(
        "select account, sum(amount) from market_ledger where order_id = %s "
        "and account in ('buyer_receivable', 'cash_collected') group by account order by account",
        [pk],
    ) == [("buyer_receivable", 0), ("cash_collected", ЦЕНА * 100)]
    assert sql(
        "select count(*) from market_ledger where order_id = %s and account = 'cash_collected'",
        [pk],
    ) == [(1,)]

    # Выплаты складу закрыты
    _, выплаты = django(склад, ("get", "/py/admin/market/payout/", None))
    assert выплаты["status"] == 403


@нужна_база
def test_у_своей_компании_не_купить(сайт):
    данные = _продавец_с_товаром()
    _в_корзину(данные["сотрудник"], данные["вариант"])

    ответ = _оформить(сайт, данные["сотрудник"], ЦЕНА)
    assert ответ["status"] == 422, ответ["body"]
    assert "своей компании" in _json(ответ)["message"]
    assert sql(
        "select count(*) from market_orders where buyer_user_id = %s", [данные["сотрудник"]]
    ) == [(0,)]


# ── Выплаты ─────────────────────────────────────────────────────────


@нужна_база
def test_выплата_в_два_шага(сайт):
    данные = _продавец_с_товаром()
    продавец = данные["продавец"]
    _, _, pk = _заказ(сайт, данные["вариант"])
    _выдать(pk, дней_назад=8)
    первый, второй = _кассир(1), _кассир(2)

    # Без реквизитов выплатить некуда
    assert "нет реквизитов" in _создать(первый, продавец, 1000)["body"]
    _реквизиты(сайт, данные["владелец"])

    # Больше доступного — отказ
    много = _создать(первый, продавец, 81_001)
    assert "Больше доступного" in много["body"]
    assert _выплаты(продавец) == []

    создана = _создать(первый, продавец, 50_000)
    [(выплата, сумма, статус)] = _выплаты(продавец)
    assert (сумма, статус) == (5_000_000, "draft")
    assert создана["location"].endswith(f"/payout/{выплата}/change/")

    # Пока первая в работе, вторая на всю сумму не пройдёт
    assert "Больше доступного" in _создать(первый, продавец, 81_000)["body"]

    # Тот же кассир не подтверждает
    сам = _выплата(первый, выплата, "approve")
    assert "Подтверждает другой кассир" in сам["body"]
    assert _выплаты(продавец)[0][2] == "draft"

    # До подтверждения отметить выплаченной нельзя
    рано = _выплата(первый, выплата, "paid", bank_reference="ПП-1")
    assert "не подтверждена" in рано["body"]

    assert _выплата(второй, выплата, "approve")["status"] == 302
    assert sql(
        "select status, approved_by, created_by, fresh_requisites from market_payouts "
        "where id = %s",
        [выплата],
    ) == [("approved", второй, первый, False)]

    без_номера = _выплата(первый, выплата, "paid", bank_reference="")
    assert "платёжного поручения" in без_номера["body"]
    assert _выплата(первый, выплата, "paid", bank_reference="ПП-123")["status"] == 302
    повтор = _выплата(первый, выплата, "paid", bank_reference="ПП-124")
    assert "уже отмечена" in повтор["body"]

    [(группа, банк)] = sql(
        "select ledger_group, bank_reference from market_payouts where id = %s and status = 'paid'",
        [выплата],
    )
    assert банк == "ПП-123"
    assert sql(
        "select account, amount, seller_id from market_ledger where entry_group = %s "
        "order by account",
        [группа],
    ) == [("payout_clearing", -5_000_000, продавец), ("seller_payable", 5_000_000, продавец)]
    assert sql(
        "select count(*) from market_ledger where account = 'payout_clearing' and seller_id = %s",
        [продавец],
    ) == [(1,)]

    # Журнал действий: кто, что, сумма, продавец
    for действие in ("payout_created", "payout_approved", "payout_paid"):
        запись = журнал(действие)
        assert запись["section"] == "market_cash", действие
        assert запись["changes"]["after"]["amount"] == 5_000_000
        assert запись["changes"]["after"]["seller_id"] == продавец

    # Баланс продавца: выплачено 50 000, доступно 31 000
    баланс = _json(_get_as(сайт, "/market/api/me/balance", данные["владелец"]))["balance"]
    assert (баланс["paid"], баланс["available"], баланс["accrued"]) == (50_000, 31_000, 81_000)
    assert баланс["payouts"][0]["status"]["code"] == "paid"
    assert баланс["payouts"][0]["bankReference"] == "ПП-123"

    # Та же платёжка у второй выплаты — отказ
    _создать(первый, продавец, 1_000)
    вторая = _выплаты(продавец)[-1][0]
    assert _выплата(второй, вторая, "approve")["status"] == 302
    двойная = _выплата(первый, вторая, "paid", bank_reference="ПП-123")
    assert "уже отмечена в другой выплате" in двойная["body"]
    assert _выплаты(продавец)[-1][2] == "approved"


@нужна_база
def test_выплату_не_переписать_мимо_кода(сайт):
    """Триггер: сумма, продавец, автор не меняются; из «выплачено» не выйти; два шага — в базе."""
    готовая = _готовая(сайт)
    выплата = готовая["выплата"]

    with pytest.raises(Exception, match="не меняются"):
        sql("update market_payouts set amount = amount + 1 where id = %s", [выплата])

    # Назад в draft — нельзя; подтверждение после ухода из draft не меняется
    with pytest.raises(Exception, match="запрещён"):
        sql("update market_payouts set status = 'draft' where id = %s", [выплата])

    with pytest.raises(Exception, match="подтверждение не меняется"):
        sql("update market_payouts set approved_by = created_by where id = %s", [выплата])

    with pytest.raises(Exception, match="подтверждение не меняется"):
        sql("update market_payouts set fresh_requisites = true where id = %s", [выплата])

    assert _выплата(_кассир(1), выплата, "paid", bank_reference="ПП-777")["status"] == 302

    with pytest.raises(Exception, match="уже закрыта"):
        sql("update market_payouts set status = 'cancelled' where id = %s", [выплата])

    # Выплаченная не меняется вовсе — ни заметка, ни время
    with pytest.raises(Exception, match="уже закрыта"):
        sql("update market_payouts set note = 'правка' where id = %s", [выплата])

    with pytest.raises(Exception, match="market_payouts_two_people_check"):
        sql(
            "insert into market_payouts (seller_id, amount, status, created_by, approved_by) "
            "values (%s, 100, 'draft', %s, %s)",
            [готовая["продавец"], _кассир(1), _кассир(1)],
        )


@нужна_база
def test_отмена_подтверждённой(сайт):
    готовая = _готовая(сайт)
    выплата = готовая["выплата"]

    # Создатель не отменяет подтверждённую — только подтвердивший
    чужая = _выплата(_кассир(1), выплата, "cancel", reason="передумали", not_sent="1")
    assert "только тот, кто её подтвердил" in чужая["body"]
    # Без отметки «платёжка не отправлялась» — отказ
    без_отметки = _выплата(_кассир(2), выплата, "cancel", reason="передумали")
    assert "не отправлялась" in без_отметки["body"]
    assert _выплаты(готовая["продавец"])[0][2] == "approved"

    assert (
        _выплата(_кассир(2), выплата, "cancel", reason="продавец попросил", not_sent="1")["status"]
        == 302
    )
    assert sql("select status, cancel_not_sent from market_payouts where id = %s", [выплата]) == [
        ("cancelled", True)
    ]


@нужна_база
def test_выплата_перепроверяет_доступное(сайт):
    """Пока выплата ждала перевода, срок удержания снова не прошёл — не выплатить."""
    готовая = _готовая(сайт)
    sql(
        "update market_orders set issued_at = now() at time zone 'utc' where id = %s",
        [готовая["заказ"]],
    )

    отказ = _выплата(_кассир(1), готовая["выплата"], "paid", bank_reference="ПП-55")
    assert "больше доступного" in отказ["body"]
    assert _выплаты(готовая["продавец"])[0][2] == "approved"


@нужна_база
def test_заблокированному_продавцу_не_выплачивать(сайт):
    данные = _продавец_с_товаром()
    _, _, pk = _заказ(сайт, данные["вариант"])
    _выдать(pk, дней_назад=8)
    _реквизиты(сайт, данные["владелец"])
    _создать(_кассир(1), данные["продавец"], 1_000)
    [(выплата, _, _)] = _выплаты(данные["продавец"])
    sql("update market_sellers set status = 'blocked' where id = %s", [данные["продавец"]])

    assert "заблокирован" in _выплата(_кассир(2), выплата, "approve")["body"]
    assert "заблокирован" in _создать(_кассир(1), данные["продавец"], 1_000)["body"]
    assert _выплаты(данные["продавец"]) == [(выплата, 100_000, "draft")]


@нужна_база
def test_свежие_реквизиты(сайт):
    данные = _продавец_с_товаром()
    продавец = данные["продавец"]
    _, _, pk = _заказ(сайт, данные["вариант"])
    _выдать(pk, дней_назад=8)
    первый, второй = _кассир(1), _кассир(2)
    # Реквизиты только что сменены
    _реквизиты(сайт, данные["владелец"], часов_назад=0)
    assert sql(
        "select count(*) from market_seller_requisites_log where seller_id = %s", [продавец]
    ) == [(1,)]

    _создать(первый, продавец, 10_000)
    [(выплата, _, _)] = _выплаты(продавец)

    отказ = _выплата(второй, выплата, "approve")
    assert "сменены меньше 24 часов назад" in отказ["body"]
    # Отметка без заметки, как сверили, — тоже отказ
    assert "как сверили" in _выплата(второй, выплата, "approve", fresh_ok="1")["body"]
    assert _выплаты(продавец)[0][2] == "draft"

    заметка = "позвонил владельцу по номеру из договора"
    assert _выплата(второй, выплата, "approve", fresh_ok="1", fresh_note=заметка)["status"] == 302
    assert sql(
        "select status, fresh_requisites, fresh_check_note from market_payouts where id = %s",
        [выплата],
    ) == [("approved", True, заметка)]

    # Реквизиты сменились после подтверждения — выплату не отметить
    _реквизиты(сайт, данные["владелец"], часов_назад=0, bankAccount="20208000999988887777")
    поздно = _выплата(первый, выплата, "paid", bank_reference="ПП-9")
    assert "сменились после подтверждения" in поздно["body"]
    assert _выплаты(продавец)[0][2] == "approved"

    # История реквизитов только дописывается
    with pytest.raises(Exception, match="только дописываются"):
        sql("delete from market_seller_requisites_log where seller_id = %s", [продавец])


# ── Наличные: сверка с отчётом BTS ──────────────────────────────────


@нужна_база
def test_наличные_к_выплате_после_сверки(сайт):
    данные = _продавец_с_товаром()
    _, number, pk = _заказ(сайт, данные["вариант"])
    _выдать(pk, дней_назад=8, сверить=False)
    кассир = _кассир(1)

    баланс = _json(_get_as(сайт, "/market/api/me/balance", данные["владелец"]))["balance"]
    assert (баланс["accrued"], баланс["available"], баланс["onHold"]) == (81_000, 0, 81_000)

    список = "/py/admin/market/cashorder/"
    _, страница = django(кассир, ("get", список + "?reconciled=no", None))
    assert number in страница["body"]

    # Поддержка не сверяет
    _, чужой = django(
        _сотрудник("support"), ("post", f"{список}{pk}/reconcile/", {"report": "отчёт BTS 1234"})
    )
    assert чужой["status"] == 403

    # Пачкой: сначала страница подтверждения — сколько и на какую сумму
    выбор = {"action": "reconcile", "_selected_action": [str(pk)]}
    _, подтверждение = django(кассир, ("post", список, выбор))
    assert подтверждение["status"] == 200
    assert "Ждут сверки: <b>1</b>" in подтверждение["body"]
    assert "90 000 сум" in подтверждение["body"]
    assert sql("select cash_reconciled_at from market_orders where id = %s", [pk]) == [(None,)]

    # Отчёт короче 10 знаков — отказ
    django(кассир, ("post", список, {**выбор, "confirm": "yes", "report": "отчёт 1"}))
    assert sql("select cash_reconciled_at from market_orders where id = %s", [pk]) == [(None,)]

    # Пачка изменилась, пока кассир смотрел (показано 2 заказа) — снова
    # страница подтверждения с пересчитанными цифрами, ничего не записано
    отчёт = {**выбор, "confirm": "yes", "report": "BTS-2026-11-20 №77"}
    _, снова = django(кассир, ("post", список, {**отчёт, "count": "2", "total": "18000000"}))
    assert снова["status"] == 200 and "Пачка изменилась" in снова["body"]
    assert 'name="count" value="1"' in снова["body"]
    assert 'name="total" value="9000000"' in снова["body"]
    assert sql("select cash_reconciled_at from market_orders where id = %s", [pk]) == [(None,)]

    _, итог = django(кассир, ("post", список, {**отчёт, "count": "1", "total": "9000000"}))
    assert итог["status"] == 302
    assert sql(
        "select cash_reconciled_at is not null, cash_reconciled_by, cash_reconciled_ref "
        "from market_orders where id = %s",
        [pk],
    ) == [(True, кассир, "BTS-2026-11-20 №77")]
    запись = журнал("cash_reconciled")
    assert запись["subject_label"] == number
    assert запись["changes"]["after"]["amount"] == ЦЕНА * 100

    баланс = _json(_get_as(сайт, "/market/api/me/balance", данные["владелец"]))["balance"]
    assert баланс["available"] == 81_000

    # Сверивший не подтверждает выплату из этих денег — только другой кассир
    _реквизиты(сайт, данные["владелец"])
    _создать(_кассир(2), данные["продавец"], 10_000)
    [(выплата, _, _)] = _выплаты(данные["продавец"])
    assert "Вы сверяли наличные" in _выплата(кассир, выплата, "approve")["body"]
    assert _выплаты(данные["продавец"])[0][2] == "draft"

    # Снять сверку, пока деньги в выплате, — нельзя; без выплаты — можно, с причиной
    карточка = f"{список}{pk}/"
    снять = {"do": "unreconcile", "reason": "ошиблись отчётом"}
    _, _, нельзя = django(
        кассир,
        ("post", карточка + "reconcile/", снять),
        ("get", карточка + "change/", None),
    )
    assert "уже в выплате" in нельзя["body"]
    assert _выплата(_кассир(2), выплата, "cancel", reason="снимаем сверку")["status"] == 302
    _, снята = django(кассир, ("post", карточка + "reconcile/", снять))
    assert снята["status"] == 302
    assert sql("select cash_reconciled_at from market_orders where id = %s", [pk]) == [(None,)]
    assert журнал("cash_unreconciled")["subject_label"] == number


# ── Кабинет продавца ────────────────────────────────────────────────


@нужна_база
def test_продавец_видит_только_свой_баланс(сайт):
    первый, второй = _продавец_с_товаром(), _продавец_с_товаром()
    _, _, pk = _заказ(сайт, первый["вариант"])
    _выдать(pk, дней_назад=8)
    # У второго заказ выдан вчера — держится
    _, _, другой = _заказ(сайт, второй["вариант"])
    _выдать(другой, дней_назад=1)

    свой = _json(_get_as(сайт, "/market/api/me/balance", первый["владелец"]))["balance"]
    assert (свой["accrued"], свой["available"], свой["onHold"]) == (81_000, 81_000, 0)
    чужой = _json(_get_as(сайт, "/market/api/me/balance", второй["владелец"]))["balance"]
    assert (чужой["accrued"], чужой["available"], чужой["onHold"]) == (81_000, 0, 81_000)
    assert чужой["holdDays"] == 7

    # Сотрудник компании баланс видит, реквизиты — нет (только владелец)
    assert _get_as(сайт, "/market/api/me/balance", первый["сотрудник"])["status"] == 200
    assert _get_as(сайт, "/market/api/me/requisites", первый["сотрудник"])["status"] == 403
    assert (
        _post(
            сайт,
            "/market/api/me/requisites",
            первый["сотрудник"],
            {**РЕКВИЗИТЫ, "password": ПАРОЛЬ},
        )["status"]
        == 403
    )

    # Не продавец — 403, гость — 401
    assert _get_as(сайт, "/market/api/me/balance", _покупатель())["status"] == 403
    assert _post(сайт, "/market/api/me/requisites", None, РЕКВИЗИТЫ)["status"] == 401
    assert _json(_get_as(сайт, "/market/api/me/requisites", второй["владелец"])) == {
        "requisites": None
    }


@нужна_база
def test_смена_реквизитов_с_паролем_и_уведомлением(сайт):
    данные = _продавец_с_товаром()
    владелец, продавец = данные["владелец"], данные["продавец"]
    адрес_api = "/market/api/me/requisites"

    плохие = _post(сайт, адрес_api, владелец, {"bankMfo": "1", "password": ПАРОЛЬ})
    assert плохие["status"] == 422 and "bankAccount" in _json(плохие)["errors"]
    невидимые = _post(
        сайт, адрес_api, владелец, {**РЕКВИЗИТЫ, "bankName": "Банк\u202e", "password": ПАРОЛЬ}
    )
    assert невидимые["status"] == 422 and "bankName" in _json(невидимые)["errors"]

    # Без пароля и с чужим паролем — отказ, ничего не записано
    for пароль in ("", "не-тот"):
        ответ = _post(сайт, адрес_api, владелец, {**РЕКВИЗИТЫ, "password": пароль})
        assert ответ["status"] == 422 and "password" in _json(ответ)["errors"]

    assert sql(
        "select count(*) from market_seller_requisites_log where seller_id = %s", [продавец]
    ) == [(0,)]

    _реквизиты(сайт, владелец, часов_назад=0)
    _реквизиты(сайт, владелец, часов_назад=0)
    реквизиты = _json(_get_as(сайт, адрес_api, владелец))
    assert реквизиты["requisites"]["bankAccount"] == "20208000123456789012"
    # Повтор тех же реквизитов — не смена: одна строка истории, одно уведомление
    assert sql(
        "select count(*) from market_seller_requisites_log where seller_id = %s", [продавец]
    ) == [(1,)]
    уведомления = sql(
        "select title, body from user_notifications where user_id = %s and type = 'billing'",
        [владелец],
    )
    assert len(уведомления) == 1
    заголовок, текст = уведомления[0]
    assert "Реквизиты" in заголовок and "поддержку" in текст
    # Самих реквизитов в уведомлении нет
    assert "9012" not in текст and "Капиталбанк" not in текст

    # В списке админки счёт скрыт
    _, список = django(_кассир(1), ("get", "/py/admin/market/sellerrequisites/", None))
    assert "•••• 9012" in список["body"] and "20208000123456789012" not in список["body"]


@нужна_база
def test_пять_неверных_паролей_закрывают_смену(сайт):
    данные = _продавец_с_товаром()
    владелец, продавец = данные["владелец"], данные["продавец"]
    sql("update users set locale = 'en' where id = %s", [владелец])
    адрес_api = "/market/api/me/requisites"

    for _ in range(5):
        ответ = _post(сайт, адрес_api, владелец, {**РЕКВИЗИТЫ, "password": "не-тот"})
        assert ответ["status"] == 422 and "password" in _json(ответ)["errors"]

    # Закрыто на сутки — даже с верным паролем; владельцу — уведомление на его языке
    закрыто = _post(сайт, адрес_api, владелец, {**РЕКВИЗИТЫ, "password": ПАРОЛЬ})
    assert закрыто["status"] == 429
    assert sql(
        "select count(*) from market_seller_requisites_log where seller_id = %s", [продавец]
    ) == [(0,)]
    [(заголовок,)] = sql(
        "select title from user_notifications where user_id = %s and type = 'billing'",
        [владелец],
    )
    assert заголовок == "Changing payout details locked for 24 hours"

    # Прошли сутки — снова можно; верный пароль сбрасывает счётчик
    sql(
        "update market_sellers set requisites_locked_until = now() at time zone 'utc' "
        "- interval '1 minute' where id = %s",
        [продавец],
    )
    _реквизиты(сайт, владелец, часов_назад=0)
    assert sql("select requisites_failed from market_sellers where id = %s", [продавец]) == [(0,)]


@нужна_база
def test_без_пароля_реквизиты_не_сменить(сайт):
    """Владелец без пароля (вошёл иначе) — понятный текст «задайте пароль»."""
    данные = _продавец_с_товаром()
    sql("update users set password = '' where id = %s", [данные["владелец"]])

    ответ = _post(
        сайт, "/market/api/me/requisites", данные["владелец"], {**РЕКВИЗИТЫ, "password": "x"}
    )
    assert ответ["status"] == 422
    assert "задайте его в настройках" in _json(ответ)["errors"]["password"][0]


# ── Возвраты ────────────────────────────────────────────────────────


def _ждёт_возврата(сайт: str, данные: dict[str, Any], провайдер: str = "click") -> tuple[str, int]:
    """Заказ оплачен картой (оплата — строкой) и отменён покупателем: ждёт возврата."""
    покупатель, number, pk = _заказ(сайт, данные["вариант"], method="card")
    assert (
        _python(f"from savdex.market import orders; print(orders.mark_paid({pk}, {ЦЕНА * 100}))")
        == "True"
    )
    sql(
        "insert into market_payments (order_id, provider, provider_transaction_id, amount, "
        "status, performed_at) values (%s, %s, %s, %s, 'paid', now() at time zone 'utc')",
        [pk, провайдер, f"cash-test-{pk}", ЦЕНА * 100],
    )
    assert _post(сайт, f"/market/api/orders/{number}/cancel", покупатель)["status"] == 200
    assert _статус(number) == "refund_pending"

    return number, pk


def _возврат(uid: int, pk: int, данные: dict[str, str]) -> dict[str, Any]:
    адрес_возврата = f"/py/admin/market/refundorder/{pk}/"
    _, ответ, страница = django(
        uid,
        ("post", адрес_возврата + "refund/", данные),
        ("get", адрес_возврата + "change/", None),
    )

    return {"status": ответ["status"], "body": страница["body"]}


@нужна_база
def test_режимы_ручного_возврата(сайт):
    данные = _продавец_с_товаром()
    первый, второй = _кассир(1), _кассир(2)
    отметить = {"do": "refund", "refund_reference": "PAYME-R-1", "note": "вернули в кабинете"}

    # Запрос через API в полёте (api, минуту назад) — отметить вручную нельзя
    number, pk = _ждёт_возврата(сайт, данные, "payme")
    sql(
        "update market_payments set refund_requested_at = now() at time zone 'utc' "
        "- interval '1 minute', refund_mode = 'api' where order_id = %s",
        [pk],
    )
    assert "дождитесь его итога" in _возврат(первый, pk, отметить)["body"]
    assert _статус(number) == "refund_pending"

    # api без итога 20 минут — зависший, как error: касса отмечает
    sql(
        "update market_payments set refund_requested_at = now() at time zone 'utc' "
        "- interval '20 minutes' where order_id = %s",
        [pk],
    )
    assert _возврат(второй, pk, отметить)["status"] == 302
    assert _статус(number) == "refunded"
    assert sql("select refund_reference from market_payments where order_id = %s", [pk]) == [
        ("PAYME-R-1",)
    ]

    # Взятый возврат: отмечает только взявший; тот же номер возврата — отказ
    другой_номер, другой = _ждёт_возврата(сайт, данные)
    assert _возврат(первый, другой, {"do": "claim"})["status"] == 302
    assert sql(
        "select refund_mode, refund_claimed_by, note from market_payments where order_id = %s",
        [другой],
    ) == [("claimed", первый, "возврат вручную взял Сотрудник cashier")]
    assert "Возврат взял другой кассир" in _возврат(второй, другой, отметить)["body"]
    assert "уже отмечен по другой оплате" in _возврат(первый, другой, отметить)["body"]
    assert _статус(другой_номер) == "refund_pending"

    # Снять взятие — только суперадмин (и не взявший), с причиной; возврат
    # снова ждёт расписания
    сам = _возврат(первый, другой, {"do": "unclaim", "reason": "вернёт API"})
    assert "только суперадмин" in сам["body"]
    assert sql("select refund_mode from market_payments where order_id = %s", [другой]) == [
        ("claimed",)
    ]
    суперадмин = _сотрудник("superadmin")
    _, форма = django(суперадмин, ("get", f"/py/admin/market/refundorder/{другой}/change/", None))
    assert "расписание вернёт их ещё раз" in форма["body"]
    assert _возврат(суперадмин, другой, {"do": "unclaim", "reason": "вернёт API"})["status"] == 302
    assert sql(
        "select refund_mode, refund_requested_at, refund_claimed_by from market_payments "
        "where order_id = %s",
        [другой],
    ) == [(None, None, None)]
    assert журнал("refund_unclaimed")["subject_label"] == другой_номер

    # «Проверено» с короткой заметкой — понятный отказ, не 500
    коротко = _возврат(первый, другой, {"do": "check", "note": "провер"})
    assert коротко["status"] == 302 and "не короче 10 знаков" in коротко["body"]

    # Свежий api суперадмин переводит в «сбой» с причиной — касса отмечает
    третий_номер, третий = _ждёт_возврата(сайт, данные)
    sql(
        "update market_payments set refund_requested_at = now() at time zone 'utc', "
        "refund_mode = 'api' where order_id = %s",
        [третий],
    )
    причина = {"do": "api_error", "reason": "процесс упал посреди запроса"}
    assert "только суперадмин" in _возврат(первый, третий, причина)["body"]
    assert _возврат(суперадмин, третий, причина)["status"] == 302
    assert sql("select refund_mode from market_payments where order_id = %s", [третий]) == [
        ("error",)
    ]
    assert журнал("refund_api_failed")["subject_label"] == третий_номер
    assert _возврат(первый, третий, {**отметить, "refund_reference": "CLK-R-3"})["status"] == 302
    assert _статус(третий_номер) == "refunded"


@нужна_база
def test_ждущий_возврата_не_в_доступном_и_ручной_возврат(сайт):
    данные = _продавец_с_товаром()
    _, _, выданный = _заказ(сайт, данные["вариант"])
    _выдать(выданный, дней_назад=8)

    # Оплачен картой и отменён покупателем — «ждёт возврата»
    number, pk = _ждёт_возврата(сайт, данные)

    баланс = _json(_get_as(сайт, "/market/api/me/balance", данные["владелец"]))["balance"]
    assert (баланс["accrued"], баланс["available"]) == (81_000, 81_000)

    кассир = _кассир(1)
    адрес_возврата = f"/py/admin/market/refundorder/{pk}/"
    отметить = {"do": "refund", "refund_reference": "CLK-REF-1", "note": "вернули в кабинете Click"}

    # Возврат ещё не запрошен — отметить нельзя: сначала взять на себя
    _, _, рано = django(
        кассир,
        ("post", адрес_возврата + "refund/", отметить),
        ("get", адрес_возврата + "change/", None),
    )
    assert "Беру возврат на себя" in рано["body"] and _статус(number) == "refund_pending"

    _, взял = django(кассир, ("post", адрес_возврата + "refund/", {"do": "claim"}))
    assert взял["status"] == 302
    assert sql(
        "select refund_requested_at is not null, refund_mode from market_payments "
        "where order_id = %s",
        [pk],
    ) == [(True, "claimed")]
    assert журнал("refund_claimed")["subject_label"] == number

    # «Проверено у провайдера» — один раз, с журналом; заказ всё ещё ждёт возврата
    проверка = {"do": "check", "note": "в кабинете Click возврат в обработке"}
    _, проверено = django(кассир, ("post", адрес_возврата + "refund/", проверка))
    assert проверено["status"] == 302
    assert sql(
        "select rejection_checked_at is not null, checked_by from market_payments "
        "where order_id = %s",
        [pk],
    ) == [(True, кассир)]
    assert журнал("payment_checked")["section"] == "market_cash"
    _, _, повтор = django(
        кассир,
        ("post", адрес_возврата + "refund/", проверка),
        ("get", адрес_возврата + "change/", None),
    )
    assert "Уже отмечено" in повтор["body"] and _статус(number) == "refund_pending"

    # Без номера возврата у провайдера — отказ
    _, _, без_номера = django(
        кассир,
        ("post", адрес_возврата + "refund/", {**отметить, "refund_reference": ""}),
        ("get", адрес_возврата + "change/", None),
    )
    assert "номер возврата" in без_номера["body"] and _статус(number) == "refund_pending"

    _, поддержка = django(_сотрудник("support"), ("post", адрес_возврата + "refund/", отметить))
    assert поддержка["status"] == 403 and _статус(number) == "refund_pending"

    _, готово = django(кассир, ("post", адрес_возврата + "refund/", отметить))
    assert готово["status"] == 302
    assert _статус(number) == "refunded"
    assert sql("select status from market_payments where order_id = %s", [pk]) == [("refunded",)]
    запись = журнал("refund_marked")
    assert запись["section"] == "market_cash"
    assert запись["changes"]["after"]["refund_reference"] == "CLK-REF-1"

    # Второй раз — заказа уже нет в очереди возвратов
    _, ещё = django(кассир, ("post", адрес_возврата + "refund/", отметить))
    assert ещё["status"] == 403
    assert sql(
        "select count(*) from market_ledger where order_id = %s and account = 'refund_payable' "
        "and amount > 0",
        [pk],
    ) == [(1,)]
