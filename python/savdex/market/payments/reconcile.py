"""
Ночная сверка оплат маркетплейса (docs/marketplace-security.md, раздел 3):
manage.py market_reconcile_payments [--day ГГГГ-ММ-ДД] и расписание.

За сутки (UTC) по каждому провайдеру — заказы, у оплат этого провайдера
которых что-то случилось в этот день (заведена, проведена, отменена,
возвращена):

- деньги у провайдеров по журналу (сумма ``gateway_clearing`` заказа)
  равны сумме проведённых оплат заказа (``paid``; журнал провайдера не
  различает, поэтому сумма — по всем провайдерам заказа): оплата пришла —
  начисление есть, вернули — счёт закрыт;
- проведённая оплата этого провайдера — только у оплаченного заказа (не
  created, не cancelled, не refunded); возвращённая — только у refunded;
- возврат запрошен через API (``refund_requested_at``), а оплата всё ещё
  paid при заказе не в refund_pending — провайдер вернул, а мы не отметили;
- оплаты, отклонённые на шаге проведения (``rejected_at``): провайдер мог
  уже списать деньги — «проверить возврат у провайдера»;
- выписка провайдера (``statement``), где она есть, — те же транзакции и
  суммы, что проведены у нас за сутки.

Плюс общее: заказы картой, оплаченные в этот день без проведённой оплаты;
группы журнала денег за день, не сходящиеся в ноль; заказы, которые ждут
возврата дольше N часов (настройка market_refund_alert_hours, по
умолчанию 24) — не по дню, а на момент сверки.

Расхождение — строка ERROR в журнале приложения: только счётчики, без
номеров заказов, сумм и данных покупателей. Сигнал наружу — Healthchecks
(``signal``, MARKET_HC_PING_PAYMENTS): удача или сбой с итогом в цифрах.
Разбирают по ``manage.py market_reconcile_payments --day …``: команда
печатает номера заказов и оплат только в свой вывод.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta

import httpx

from savdex.market import orders
from savdex.market.common import rows
from savdex.market.payments import base
from savdex.web.shared import settings_values

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

#: Сколько часов заказ может ждать возврата, прежде чем это проблема
REFUND_HOURS_KEY = "market_refund_alert_hours"
REFUND_HOURS_DEFAULT = 24

#: Адрес сигнала Healthchecks (секрет, как HC_PING_* у копий)
PING_KEY = "MARKET_HC_PING_PAYMENTS"


@dataclass
class Report:
    """Итог сверки одного провайдера (или «всё», provider = "*")."""

    provider: str
    payments: int = 0
    statement: bool = False
    #: Номера заказов и оплат с расхождением — только для вывода команды
    problems: list[str] = field(default_factory=list)


def refund_alert_hours() -> int:
    """Часов ожидания возврата до тревоги: настройка; не число или меньше 1 — 24."""
    try:
        value = int(str(settings_values().get(REFUND_HOURS_KEY, REFUND_HOURS_DEFAULT)))
    except (TypeError, ValueError):
        return REFUND_HOURS_DEFAULT

    return value if value >= 1 else REFUND_HOURS_DEFAULT


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
        # Начисление в журнале — по заказу, без провайдера: сравниваем с
        # проведёнными оплатами заказа у всех провайдеров
        "(select coalesce(sum(p.amount), 0) from market_payments p where p.order_id = o.id "
        " and p.status = 'paid') as paid, "
        "(select count(*) from market_payments p where p.order_id = o.id "
        " and p.provider = %s and p.status = 'paid') as paid_here, "
        "(select count(*) from market_payments p where p.order_id = o.id "
        " and p.provider = %s and p.status = 'refunded') as refunded_here, "
        "(select count(*) from market_payments p where p.order_id = o.id "
        " and p.provider = %s and p.status = 'paid' and p.refund_requested_at is not null) "
        " as refund_asked, "
        "(select coalesce(sum(l.amount), 0) from market_ledger l where l.order_id = o.id "
        " and l.account = 'gateway_clearing') as clearing "
        "from touched t join market_orders o on o.id = t.order_id order by o.id",
        [provider, start, end, start, end, start, end, start, end, *[provider] * 4],
    )

    for order in touched:
        report.payments += int(order["payments"])
        paid, clearing = int(order["paid"]), int(order["clearing"])
        status = order["status"]
        wrong = (
            paid != clearing
            or (int(order["paid_here"]) > 0 and status not in _PAID_ORDER)
            or (int(order["refunded_here"]) > 0 and paid == 0 and status != orders.REFUNDED)
            # Возврат через API запрошен, а оплата не отмечена, и заказ уже
            # не ждёт возврата (refund_order → unrecorded)
            or (int(order["refund_asked"]) > 0 and status != orders.REFUND_PENDING)
        )

        if wrong:
            report.problems.append(str(order["number"]))

    for rejected in rows(
        "select id from market_payments where provider = %s and rejected_at >= %s "
        "and rejected_at < %s order by id",
        [provider, start, end],
    ):
        report.problems.append(
            f"оплата {rejected['id']} отклонена на проведении — проверить возврат у провайдера"
        )

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


def check_common(day: date, moment: datetime | None = None) -> Report:
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

    hours = refund_alert_hours()
    cutoff = ((moment or datetime.now(UTC)) - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")

    for order in rows(
        "select number from market_orders where status = %s and cancelled_at < %s order by id",
        [orders.REFUND_PENDING, cutoff],
    ):
        report.problems.append(f"{order['number']} ждёт возврата дольше {hours} ч")

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


def summary(reports: list[Report], day: date) -> str:
    """Итог одной строкой — только цифры (уходит в Healthchecks, за пределы страны)."""
    parts = [f"{'общее' if r.provider == '*' else r.provider} {len(r.problems)}" for r in reports]
    total = sum(len(r.problems) for r in reports)

    return f"сверка оплат за {day.isoformat()}: расхождений {total} ({', '.join(parts)})"


def signal(reports: list[Report], day: date) -> bool | None:
    """
    Сигнал Healthchecks (MARKET_HC_PING_PAYMENTS, как HC_PING_* у копий):
    без расхождений — «готово», с расхождениями — «сбой» (адрес + /fail),
    в теле — итог в цифрах. Сигнал не пришёл вовремя — Healthchecks сам
    тревожит: сверка не запустилась. None — адрес не задан; False — не
    дошёл (в журнал WARNING, сверка от этого не падает).
    """
    url = base.env(PING_KEY)

    if not url:
        return None

    failed = any(report.problems for report in reports)

    try:
        with httpx.Client(timeout=httpx.Timeout(10.0, connect=5.0), trust_env=False) as client:
            response = client.post(
                url.rstrip("/") + ("/fail" if failed else ""),
                content=summary(reports, day).encode(),
            )
    except httpx.HTTPError:
        log.warning("market.payments.reconcile_signal_failed")

        return False

    return response.status_code < 400
