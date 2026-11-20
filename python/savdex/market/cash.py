"""
Касса маркетплейса, этап 3 (docs/marketplace.md, «Касса — этап 3»;
docs/marketplace-security.md, разделы 3 и 4): баланс продавца, реквизиты,
выплаты в два шага и ручная отметка возврата.

Выплата пока ручная (ТЗ: выплаты по оферте — позже): продавец видит
начисления в кабинете, касса переводит деньги платёжкой из банка и
отмечает это здесь.

- **Баланс** — из журнала денег: ``seller_payable`` по заказам продавца
  (начисление — минус, обратная группа отмены — плюс). К выплате — только
  выданные заказы старше N дней (настройка ``market_payout_hold_days``, по
  умолчанию 7): срок на возврат. Заказы в «ждёт возврата» и «деньги
  возвращены» — не в счёт. Доступно = к выплате − выплаты в работе
  (готовится, подтверждена) − выплаченное.
- **Два шага**: один кассир создаёт, другой подтверждает (не тот же — и
  база: market_payouts_two_people_check). Выплату на реквизиты, сменённые
  меньше суток назад, подтверждают только отдельной отметкой «реквизиты
  сверены» (повторное подтверждение). Реквизиты сменились после
  подтверждения — выплату не отметить: отменить и создать заново.
- **Выплачено** — одна группа журнала: ``seller_payable`` плюс (долг
  продавцу закрыт), ``payout_clearing`` минус (деньги ушли с нашего
  счёта); ровно один раз — условным переходом approved → paid.
- Порядок замков везде один: строка продавца (``for update``), затем
  строка выплаты. Каждое действие — ``audit.record`` (кто, что, сумма,
  продавец).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from django.db import connection, transaction

from savdex import audit
from savdex.access import Admin
from savdex.market import orders
from savdex.market.common import now, one, rows, som, t, write
from savdex.web.shared import settings_values

log = logging.getLogger("savdex.market.cash")

#: Раздел админки кассы (savdex/access.py)
SECTION = "market_cash"

# ── Статусы выплаты ─────────────────────────────────────────────────

DRAFT = "draft"
APPROVED = "approved"
PAID = "paid"
CANCELLED = "cancelled"

STATUSES: dict[str, str] = {
    DRAFT: "Создана, ждёт подтверждения",
    APPROVED: "Подтверждена, ждёт перевода",
    PAID: "Выплачено",
    CANCELLED: "Отменена",
}

#: Выплаты в работе: их сумма уже не «доступна»
IN_WORK = (DRAFT, APPROVED)

#: Заказы, начисления по которым продавцу не причитаются
_NOT_OWED = (orders.CANCELLED, orders.REFUND_PENDING, orders.REFUNDED)

# ── Настройки ───────────────────────────────────────────────────────

#: Сколько дней после выдачи деньги держатся (срок на возврат)
HOLD_KEY = "market_payout_hold_days"
HOLD_DEFAULT = 7

#: Реквизиты моложе стольких часов — выплата только с отдельной отметкой
FRESH_HOURS = 24

_SUBJECT = "Savdex\\Market\\Payout"


class CashRefused(Exception):  # noqa: N818 — отказ кассиру, а не сбой
    """Отказ кассиру с понятным текстом (админка показывает его как есть)."""


def hold_days() -> int:
    """Срок удержания в днях; не число или меньше нуля — по умолчанию."""
    try:
        number = int(str(settings_values().get(HOLD_KEY)))
    except (TypeError, ValueError):
        return HOLD_DEFAULT

    return number if number >= 0 else HOLD_DEFAULT


def _ago(delta: timedelta, moment: datetime | None = None) -> str:
    return ((moment or datetime.now(UTC)) - delta).strftime("%Y-%m-%d %H:%M:%S")


def money(value: int | None) -> str:
    """Тийины → «1 250 000 сум» для админки."""
    amount = som(value)

    return f"{amount:,}".replace(",", " ") + " сум" if amount is not None else "—"


# ── Баланс ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Balance:
    """Баланс продавца в тийинах."""

    #: Начислено по живым заказам (без отменённых и возвращённых)
    accrued: int
    #: Из них к выплате: выданы и срок удержания прошёл
    released: int
    #: Выплаты в работе (готовится, подтверждена)
    in_work: int
    #: Выплачено
    paid: int

    @property
    def on_hold(self) -> int:
        """Начислено, но ещё держится: не выдан или срок не прошёл."""
        return self.accrued - self.released

    @property
    def free(self) -> int:
        """К выплате минус выплаты в работе и выплаченное (может уйти в минус)."""
        return self.released - self.in_work - self.paid

    @property
    def available(self) -> int:
        return max(0, self.free)


def balance(seller_id: int, *, moment: datetime | None = None) -> Balance:
    """Баланс продавца: журнал денег по его заказам и его выплаты."""
    owed = one(
        "select coalesce(sum(-l.amount) filter (where o.status <> all(%s)), 0) as accrued, "
        "coalesce(sum(-l.amount) filter (where o.status = %s and o.issued_at < %s), 0) "
        "as released "
        "from market_ledger l join market_orders o on o.id = l.order_id "
        "where l.account = 'seller_payable' and l.seller_id = %s",
        [list(_NOT_OWED), orders.ISSUED, _ago(timedelta(days=hold_days()), moment), seller_id],
    )
    payouts = one(
        "select coalesce(sum(amount) filter (where status = any(%s)), 0) as in_work, "
        "coalesce(sum(amount) filter (where status = %s), 0) as paid "
        "from market_payouts where seller_id = %s",
        [list(IN_WORK), PAID, seller_id],
    )
    assert owed is not None and payouts is not None

    return Balance(
        accrued=int(owed["accrued"]),
        released=int(owed["released"]),
        in_work=int(payouts["in_work"]),
        paid=int(payouts["paid"]),
    )


# ── Реквизиты ───────────────────────────────────────────────────────

_REQUISITES = "bank_account, bank_mfo, bank_name, recipient_name, recipient_tin"

#: Поле API → (столбец, проверка)
_FIELDS: dict[str, tuple[str, re.Pattern[str]]] = {
    "bankAccount": ("bank_account", re.compile(r"[0-9]{20}")),
    "bankMfo": ("bank_mfo", re.compile(r"[0-9]{5}")),
    "bankName": ("bank_name", re.compile(r"[^\x00-\x1f\x7f]{2,200}")),
    "recipientName": ("recipient_name", re.compile(r"[^\x00-\x1f\x7f]{2,200}")),
    "recipientTin": ("recipient_tin", re.compile(r"[0-9]{9}|[0-9]{14}")),
}


def requisites_of(seller_id: int) -> dict[str, Any] | None:
    """Текущие реквизиты продавца (с changed_at) или None."""
    return one(
        f"select id, seller_id, {_REQUISITES}, changed_at, changed_by "
        "from market_seller_requisites where seller_id = %s",
        [seller_id],
    )


def _clean(field: str, value: Any) -> str:  # noqa: ANN401
    text = " ".join(str(value or "").split())

    # Счёт, МФО и ИНН пишут с пробелами и дефисами — оставляем цифры
    return (
        re.sub(r"[\s-]", "", text) if field in ("bankAccount", "bankMfo", "recipientTin") else text
    )


def save_requisites(
    seller_id: int, user_id: int, data: Mapping[str, Any], *, ip: str | None = None
) -> tuple[bool, dict[str, str]]:
    """
    Владелец компании сохраняет реквизиты (кабинет). Возвращает (изменились
    ли, ошибки: поле → ключ словаря market.cash.*). Каждая смена — строка
    истории; changed_at — время смены (от него — сутки до выплаты без
    отдельной отметки кассы).
    """
    values: dict[str, str] = {}
    errors: dict[str, str] = {}

    for field, (column, pattern) in _FIELDS.items():
        value = _clean(field, data.get(field))

        if not pattern.fullmatch(value):
            errors[field] = f"cash.{column}"
        else:
            values[column] = value

    if errors:
        return False, errors

    with transaction.atomic():
        # Замок продавца — тот же порядок, что у выплат: смена реквизитов
        # и подтверждение выплаты не проходят одновременно
        one("select id from market_sellers where id = %s for update", [seller_id])
        current = requisites_of(seller_id)

        if current is not None and all(str(current[c]) == v for c, v in values.items()):
            return False, {}

        moment = now()
        columns = list(values)

        if current is None:
            write(
                f"insert into market_seller_requisites (seller_id, {', '.join(columns)}, "
                "changed_at, changed_by, created_at, updated_at) "
                f"values (%s, {', '.join(['%s'] * len(columns))}, %s, %s, %s, %s)",
                [seller_id, *values.values(), moment, user_id, moment, moment],
            )
        else:
            write(
                "update market_seller_requisites set "
                + ", ".join(f"{c} = %s" for c in columns)
                + ", changed_at = %s, changed_by = %s, updated_at = %s where seller_id = %s",
                [*values.values(), moment, user_id, moment, seller_id],
            )

        write(
            f"insert into market_seller_requisites_log (seller_id, {', '.join(columns)}, "
            "changed_by, ip, created_at) "
            f"values (%s, {', '.join(['%s'] * len(columns))}, %s, %s, %s)",
            [seller_id, *values.values(), user_id, (ip or "")[:45] or None, moment],
        )

    log.info("market.cash.requisites_changed seller=%s", seller_id)

    return True, {}


def _last_log_id(seller_id: int) -> int | None:
    found = one(
        "select id from market_seller_requisites_log where seller_id = %s order by id desc limit 1",
        [seller_id],
    )

    return int(found["id"]) if found else None


# ── Выплаты ─────────────────────────────────────────────────────────


def _need(admin: Admin, ability: str) -> None:
    if not admin.can(ability):
        raise CashRefused("Нет права на это действие в кассе.")


def _lock(payout_id: int) -> dict[str, Any]:
    """Строка продавца, затем строка выплаты — под замком (порядок везде один)."""
    found = one("select seller_id from market_payouts where id = %s", [payout_id])

    if found is None:
        raise CashRefused("Выплата не найдена.")

    one("select id from market_sellers where id = %s for update", [found["seller_id"]])
    payout = one("select * from market_payouts where id = %s for update", [payout_id])
    assert payout is not None

    return payout


def _record(
    admin: Admin,
    action: str,
    payout: Mapping[str, Any],
    *,
    after: Mapping[str, Any],
    before: Mapping[str, Any] | None = None,
    note: str | None = None,
    ip: str | None = None,
) -> None:
    audit.record(
        connection,
        action=action,
        section=SECTION,
        actor=admin,
        subject_type=_SUBJECT,
        subject_id=int(payout["id"]),
        subject_label=f"Выплата №{payout['id']}",
        changes={
            "before": dict(before or {}),
            "after": {"seller_id": payout["seller_id"], "amount": payout["amount"], **after},
        },
        note=note,
        ip=ip,
    )


def create_payout(
    admin: Admin, seller_id: int, amount: int, *, note: str | None = None, ip: str | None = None
) -> int:
    """Шаг 1: кассир создаёт выплату — не больше доступного. Возвращает номер."""
    _need(admin, f"{SECTION}.create")

    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        raise CashRefused("Сумма выплаты — больше нуля.")

    with transaction.atomic():
        seller = one("select id from market_sellers where id = %s for update", [seller_id])

        if seller is None:
            raise CashRefused("Продавец не найден.")

        if requisites_of(seller_id) is None:
            raise CashRefused("У продавца нет реквизитов — выплатить некуда.")

        free = balance(seller_id).available

        if amount > free:
            raise CashRefused(f"Больше доступного: доступно {money(free)}.")

        moment = now()
        payout_id = int(
            write(
                "insert into market_payouts (seller_id, amount, status, note, created_by, "
                "created_at, updated_at) values (%s, %s, %s, %s, %s, %s, %s) returning id",
                [seller_id, amount, DRAFT, (note or "")[:500] or None, admin.id, moment, moment],
            )
        )
        _record(
            admin,
            "payout_created",
            {"id": payout_id, "seller_id": seller_id, "amount": amount},
            after={"status": DRAFT},
            note=note,
            ip=ip,
        )

    log.info("market.cash.payout_created id=%s seller=%s", payout_id, seller_id)

    return payout_id


def approve_payout(
    admin: Admin, payout_id: int, *, fresh_ok: bool = False, ip: str | None = None
) -> None:
    """
    Шаг 2: другой кассир подтверждает. Реквизиты сменены меньше суток назад
    — только с fresh_ok (отметка «реквизиты сверены с продавцом»). Сумма —
    ещё раз против доступного: с создания могла смениться настройка срока.
    """
    _need(admin, f"{SECTION}.moderate")

    with transaction.atomic():
        payout = _lock(payout_id)

        if payout["status"] != DRAFT:
            raise CashRefused("Выплата уже не ждёт подтверждения.")

        if int(payout["created_by"]) == admin.id:
            raise CashRefused("Подтверждает другой кассир — не тот, кто создал выплату.")

        seller_id = int(payout["seller_id"])
        fresh = one(
            "select changed_at >= %s as fresh from market_seller_requisites where seller_id = %s",
            [_ago(timedelta(hours=FRESH_HOURS)), seller_id],
        )
        log_id = _last_log_id(seller_id)

        if fresh is None or log_id is None:
            raise CashRefused("У продавца нет реквизитов — выплатить некуда.")

        if fresh["fresh"] and not fresh_ok:
            raise CashRefused(
                f"Реквизиты продавца сменены меньше {FRESH_HOURS} часов назад. Сверьте их с "
                "продавцом по известному телефону и подтвердите с отметкой «реквизиты сверены»."
            )

        # Эта выплата уже в «в работе» — свободное не должно уйти в минус
        if balance(seller_id).free < 0:
            raise CashRefused("Сумма больше доступного — отмените выплату и создайте новую.")

        changed = write(
            "update market_payouts set status = %s, approved_by = %s, approved_at = %s, "
            "requisites_log_id = %s, fresh_requisites = %s, updated_at = %s "
            "where id = %s and status = %s",
            [APPROVED, admin.id, now(), log_id, bool(fresh["fresh"]), now(), payout_id, DRAFT],
        )

        if not changed:
            raise CashRefused("Выплата уже не ждёт подтверждения.")

        _record(
            admin,
            "payout_approved",
            payout,
            before={"status": DRAFT},
            after={"status": APPROVED, "fresh_requisites": bool(fresh["fresh"])},
            note="реквизиты сменены меньше суток назад, сверены" if fresh["fresh"] else None,
            ip=ip,
        )

    log.info("market.cash.payout_approved id=%s", payout_id)


_BANK_REF = re.compile(r"[0-9A-Za-zА-Яа-яЁё/._ -]{1,64}")


def mark_paid(admin: Admin, payout_id: int, bank_reference: str, *, ip: str | None = None) -> str:
    """
    Деньги ушли платёжкой: approved → paid и группа журнала денег —
    ровно один раз. Возвращает номер группы журнала.
    """
    _need(admin, f"{SECTION}.moderate")
    reference = " ".join(str(bank_reference or "").split())

    if not _BANK_REF.fullmatch(reference):
        raise CashRefused("Укажите номер платёжного поручения (до 64 знаков).")

    with transaction.atomic():
        payout = _lock(payout_id)

        if payout["status"] != APPROVED:
            raise CashRefused("Выплата не подтверждена или уже отмечена.")

        seller_id = int(payout["seller_id"])

        if _last_log_id(seller_id) != payout["requisites_log_id"]:
            raise CashRefused(
                "Реквизиты продавца сменились после подтверждения — отмените выплату и "
                "создайте заново."
            )

        amount = int(payout["amount"])
        memo = f"выплата №{payout_id}: {reference}"[:200]
        group = orders.post(
            None,
            [
                orders.Entry("seller_payable", amount, seller_id=seller_id, memo=memo),
                orders.Entry("payout_clearing", -amount, seller_id=seller_id, memo=memo),
            ],
        )
        changed = write(
            "update market_payouts set status = %s, paid_by = %s, paid_at = %s, "
            "bank_reference = %s, ledger_group = %s::uuid, updated_at = %s "
            "where id = %s and status = %s",
            [PAID, admin.id, now(), reference, group, now(), payout_id, APPROVED],
        )

        if not changed:
            # Под замком статус не мог смениться — ошибка в коде; откат проводки
            raise RuntimeError(f"market_payouts {payout_id}: не перешла в paid")

        _record(
            admin,
            "payout_paid",
            payout,
            before={"status": APPROVED},
            after={"status": PAID, "bank_reference": reference},
            ip=ip,
        )

    log.info("market.cash.payout_paid id=%s seller=%s", payout_id, seller_id)

    return group


def cancel_payout(admin: Admin, payout_id: int, reason: str, *, ip: str | None = None) -> None:
    """Отменить выплату до перевода (готовится или подтверждена)."""
    _need(admin, f"{SECTION}.edit")
    text = " ".join(str(reason or "").split())[:500]

    if len(text) < 5:
        raise CashRefused("Напишите причину отмены — не короче 5 знаков.")

    with transaction.atomic():
        payout = _lock(payout_id)

        if payout["status"] not in IN_WORK:
            raise CashRefused("Выплату уже нельзя отменить.")

        write(
            "update market_payouts set status = %s, cancelled_by = %s, cancelled_at = %s, "
            "cancel_reason = %s, updated_at = %s where id = %s and status = %s",
            [CANCELLED, admin.id, now(), text, now(), payout_id, payout["status"]],
        )
        _record(
            admin,
            "payout_cancelled",
            payout,
            before={"status": payout["status"]},
            after={"status": CANCELLED},
            note=text,
            ip=ip,
        )


# ── Ручной возврат ──────────────────────────────────────────────────


def mark_refunded(admin: Admin, order_id: int, note: str, *, ip: str | None = None) -> bool:
    """
    Касса вернула деньги в кабинете провайдера (Click без API возврата,
    Uzum или Payme, если отмена не пришла колбэком) и отмечает это:
    payments.base.refund_payment — оплата paid → refunded и заказ
    refund_pending → refunded ровно один раз. False — заказ не ждёт
    возврата или оплату уже вернули.
    """
    from savdex.market.payments import base

    _need(admin, f"{SECTION}.moderate")
    text = " ".join(str(note or "").split())[:400]

    if len(text) < 5:
        raise CashRefused("Напишите, где и когда вернули деньги — не короче 5 знаков.")

    found = one(
        "select id from market_payments where order_id = %s and status = %s "
        "order by id desc limit 1",
        [order_id, base.PAID],
    )
    payment = base.payment(int(found["id"])) if found else None

    if payment is None:
        raise CashRefused("У заказа нет проведённой оплаты картой.")

    done = base.refund_payment(payment, note=f"возврат отмечен кассой: {text}")

    if done:
        order = one("select id, number, total from market_orders where id = %s", [order_id])
        assert order is not None
        audit.record(
            connection,
            action="refund_marked",
            section=SECTION,
            actor=admin,
            subject_type="Savdex\\Market\\Order",
            subject_id=order_id,
            subject_label=str(order["number"]),
            changes={
                "before": {"status": orders.REFUND_PENDING},
                "after": {
                    "status": orders.REFUNDED,
                    "amount": order["total"],
                    "provider": payment["provider"],
                },
            },
            note=text,
            ip=ip,
        )

    return done


# ── Кабинет продавца ────────────────────────────────────────────────


def _when(value: Any) -> str | None:  # noqa: ANN401
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")

    return str(value) if value is not None else None


def seller_balance(seller_id: int, locale: str) -> dict[str, Any]:
    """Баланс для кабинета: сумами; последние выплаты — только свои."""
    found = balance(seller_id)
    payouts = rows(
        "select id, amount, status, bank_reference, created_at, paid_at from market_payouts "
        "where seller_id = %s order by id desc limit 20",
        [seller_id],
    )

    return {
        "accrued": som(found.accrued),
        "onHold": som(found.on_hold),
        "available": som(found.available),
        "inWork": som(found.in_work),
        "paid": som(found.paid),
        "holdDays": hold_days(),
        "payouts": [
            {
                "id": p["id"],
                "amount": som(p["amount"]),
                "status": {"code": p["status"], "text": t(f"cash.status.{p['status']}", locale)},
                "bankReference": p["bank_reference"] if p["status"] == PAID else None,
                "createdAt": _when(p["created_at"]),
                "paidAt": _when(p["paid_at"]),
            }
            for p in payouts
        ],
    }


def requisites_view(seller_id: int) -> dict[str, Any] | None:
    """Реквизиты для кабинета владельца."""
    found = requisites_of(seller_id)

    if found is None:
        return None

    return {
        **{field: found[column] for field, (column, _) in _FIELDS.items()},
        "changedAt": _when(found["changed_at"]),
    }
