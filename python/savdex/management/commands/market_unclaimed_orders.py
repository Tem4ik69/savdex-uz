"""
Заказы маркетплейса, которые не забрали из пункта выдачи за N дней, —
закрыть: картой — «ждёт возврата денег», при получении — «отменён»; резерв
снять (savdex/market/warehouse.py, expire_unclaimed). Товар едет на склад
отгрузкой «невостребованные».

  manage.py market_unclaimed_orders [--days 7]

Без --days — настройка «market_unclaimed_days» (по умолчанию 7).
То же каждый час делает расписание (savdex/schedule.py).
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from savdex.market import warehouse


class Command(BaseCommand):
    help = "Маркетплейс: закрыть заказы, не забранные из пункта выдачи за N дней"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--days",
            type=int,
            default=None,
            help="Сколько дней заказ ждёт в пункте (по умолчанию — из настроек)",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        days = options["days"]

        if days is not None and days < 0:
            self.stderr.write("--days — не меньше нуля.")

            raise SystemExit(1)

        done = warehouse.expire_unclaimed(days)
        self.stdout.write(f"Закрыто невостребованных заказов: {done}.")
