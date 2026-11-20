"""
Ночная сверка оплат маркетплейса (docs/marketplace-security.md, раздел 3):
manage.py market_reconcile_payments [--day ГГГГ-ММ-ДД] и расписание.

За сутки (UTC) по каждому провайдеру — заказы, у оплат которых что-то
случилось в этот день (заведена, проведена, отменена, возвращена):

- деньги у провайдера по журналу (сумма ``gateway_clearing`` заказа) равны
  сумме его проведённых оплат (``market_payments.paid``): оплата пришла —
  начисление есть, вернули — счёт закрыт;
- проведённая оплата — только у оплаченного заказа (не created, не
  cancelled, не refunded); возвращённая — только у refunded;
- выписка провайдера (``statement``), где она есть, — те же транзакции и
  суммы, что проведены у нас за сутки.

Плюс общее: заказы картой, оплаченные в этот день без проведённой оплаты, и
группы журнала денег за день, не сходящиеся в ноль.

Расхождение — строка ERROR в журнале приложения: только счётчики, без
номеров заказов, сумм и данных покупателей (журналы могут уходить за
пределы страны — CLAUDE.md, правила). Разбирают по
``manage.py market_reconcile_payments --day …``: команда печатает номера
заказов только в свой вывод.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from savdex.market import orders
from savdex.market.common import rows
from savdex.market.payments import base

log = logging.getLogger("savdex.market.payments.reconcile")

#: Статусы заказа, при которых проведённая картой оплата на месте
_PAID_ORDER = frozenset(
    {
        orders.PAID,
        orders.ASSEMBLING,
        orders.IN_TRANSIT,
        orders.READY,
        orders.ISSUED,
        orders.REFUND_PENDING,
    }
)


@dataclass
class Report:
    """Итог сверки одного провайдера (или «всё», provider = "*")."""

    provider: str
    payments: int = 0
    statement: bool = False
    #: Номера заказов с расхождением — только для вывода команды, не для журнала
    problems: list[str] = field(default_factory=list)


def _bounds(day: date) -> tuple[str, str]:
    start = datetime.combine(day, time(0, 0))

    return start.strftime("%Y-%m-%d %H:%M:%S"), (start + timedelta(days=1)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def check_provider(provider: str, day: date) -> Report:
    start, end = _bounds(day)
    report = Report(provider)
    touched = rows(
        "with touched as (select distinct order_id from market_payments where provider = %s "
        "and ((created_at >= %s and created_at < %s) or (performed_at >= %s and performed_at < %s) "
        "or (cancelled_at >= %s and cancelled_at < %s) "
        "or (refunded_at >= %s and refunded_at < %s))) "
        "select o.id, o.number, o.status, "
        "(select count(*) from market_payments p where p.order_id = o.id "
        " and p.provider = %s) as payments, "
        "(select coalesce(sum(p.amount), 0) from market_payments p where p.order_id = o.id "
        " and p.status = 'paid') as paid, "
        "(select count(*) from market_payments p where p.order_id = o.id "
        " and p.status = 'refunded') as refunded, "
        "(select coalesce(sum(l.amount), 0) from market_ledger l where l.order_id = o.id "
        " and l.account = 'gateway_clearing') as clearing "
        "from touched t join market_orders o on o.id = t.order_id order by o.id",
        [provider, start, end, start, end, start, end, start, end, provider],
    )

    for order in touched:
        report.payments += int(order["payments"])
        paid, clearing = int(order["paid"]), int(order["clearing"])
        wrong = (
            paid != clearing
            or (paid > 0 and order["status"] not in _PAID_ORDER)
            or (int(order["refunded"]) > 0 and paid == 0 and order["status"] != orders.REFUNDED)
        )

        if wrong:
            report.problems.append(str(order["number"]))

    statement = base.get(provider).statement(day) if base.enabled(provider) else None

    if statement is not None:
        report.statement = True
        ours = {
            (str(r["provider_transaction_id"]), int(r["amount"]))
            for r in rows(
                "select provider_transaction_id, amount from market_payments where provider = %s "
                "and status in ('paid', 'refunded') and performed_at >= %s and performed_at < %s",
                [provider, start, end],
            )
        }
        theirs = {(line.transaction_id, line.amount) for line in statement}

        for transaction_id, _ in sorted(ours ^ theirs):
            report.problems.append(f"транзакция {transaction_id}")

    return report


def check_common(day: date) -> Report:
    start, end = _bounds(day)
    report = Report("*")

    for order in rows(
        "select o.number from market_orders o where o.payment_method = 'card' "
        "and o.paid_at >= %s and o.paid_at < %s and not exists (select 1 from market_payments p "
        "where p.order_id = o.id and p.status in ('paid', 'refunded')) order by o.id",
        [start, end],
    ):
        report.problems.append(str(order["number"]))

    for group in rows(
        "select entry_group from market_ledger where created_at >= %s and created_at < %s "
        "group by entry_group having sum(amount) <> 0",
        [start, end],
    ):
        report.problems.append(f"группа журнала {group['entry_group']}")

    return report


def run(day: date) -> list[Report]:
    """
    Сверка за сутки: каждый провайдер, у которого есть ключи или оплаты, и
    общая часть. Расхождение — ERROR в журнале со счётчиками.
    """
    start, end = _bounds(day)
    active = {
        str(r["provider"])
        for r in rows(
            "select distinct provider from market_payments where updated_at >= %s "
            "and updated_at < %s",
            [start, end],
        )
    }
    reports = [
        check_provider(name, day) for name in base.PROVIDERS if name in active or base.enabled(name)
    ]
    reports.append(check_common(day))

    for report in reports:
        if report.problems:
            log.error(
                "market.payments.reconcile_mismatch provider=%s day=%s mismatches=%s payments=%s",
                report.provider,
                day.isoformat(),
                len(report.problems),
                report.payments,
            )
        else:
            log.info(
                "market.payments.reconcile_ok provider=%s day=%s payments=%s",
                report.provider,
                day.isoformat(),
                report.payments,
            )

    return reports
