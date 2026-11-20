"""
Неоплаченные картой заказы маркетплейса и не начатые сборкой заказы с
оплатой при получении — отменить и снять резерв (savdex/market/orders.py,
expire).

  manage.py market_expire_orders [--minutes 30] [--hours 48]

Без --minutes — настройка «market_order_expire_minutes» (по умолчанию 30),
без --hours — «market_cash_order_expire_hours» (по умолчанию 48).
То же каждый час делает расписание (savdex/schedule.py).
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from savdex.market import orders


class Command(BaseCommand):
    help = (
        "Маркетплейс: отменить неоплаченные картой заказы старше N минут и не "
        "собранные заказы с оплатой при получении старше N часов, снять резерв"
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--minutes",
            type=int,
            default=None,
            help="Сколько минут ждать оплаты (по умолчанию — из настроек)",
        )
        parser.add_argument(
            "--hours",
            type=int,
            default=None,
            help="Сколько часов ждать сборки заказа с оплатой при получении "
            "(по умолчанию — из настроек)",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        minutes = options["minutes"]
        hours = options["hours"]

        if minutes is not None and minutes < 0:
            self.stderr.write("--minutes — не меньше нуля.")

            raise SystemExit(1)

        if hours is not None and hours < 0:
            self.stderr.write("--hours — не меньше нуля.")

            raise SystemExit(1)

        done = orders.expire(minutes, hours=hours)
        self.stdout.write(f"Отменено незавершённых заказов: {done}.")
