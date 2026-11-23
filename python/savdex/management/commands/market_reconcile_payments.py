"""
Сверка оплат маркетплейса за сутки (savdex/market/payments/reconcile.py).

  manage.py market_reconcile_payments [--day ГГГГ-ММ-ДД]

Без --day — вчерашние сутки (UTC). То же каждую ночь делает расписание
(savdex/schedule.py). Номера заказов с расхождением — только в вывод
команды; в журнал приложения — счётчики. Расхождение — код выхода 1.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from savdex.market.payments import reconcile


class Command(BaseCommand):
    help = (
        "Маркетплейс: сверить оплаты Uzum, Payme и Click, наличные BTS и выплаты "
        "с журналом денег за сутки"
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--day",
            default=None,
            help="Сутки (UTC) в виде ГГГГ-ММ-ДД; по умолчанию — вчера",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        raw = options["day"]

        try:
            day = date.fromisoformat(raw) if raw else datetime.now(UTC).date() - timedelta(days=1)
        except ValueError:
            self.stderr.write("--day — дата в виде ГГГГ-ММ-ДД.")

            raise SystemExit(2) from None

        reports = reconcile.run(day)
        total = 0

        for report in reports:
            # У кассы и склада оплат провайдеров нет — только расхождения
            payments = (
                ""
                if report.provider in (reconcile.CASH, reconcile.STOCK)
                else f"оплат {report.payments}, "
            )
            self.stdout.write(
                f"{report.label}: {payments}расхождений {len(report.problems)}"
                + (", выписка сверена" if report.statement else "")
            )

            for problem in report.problems:
                self.stdout.write(f"  - {problem}")

            total += len(report.problems)

        self.stdout.write(f"Сверка за {day.isoformat()}: расхождений {total}.")

        if total:
            raise SystemExit(1)
