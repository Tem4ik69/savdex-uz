"""
Неоплаченные картой заказы маркетплейса — отменить и снять резерв
(savdex/market/orders.py, expire).

  manage.py market_expire_orders [--minutes 30]

Без --minutes — настройка «market_order_expire_minutes» (по умолчанию 30).
То же каждый час делает расписание (savdex/schedule.py).
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from savdex.market import orders


class Command(BaseCommand):
    help = "Маркетплейс: отменить неоплаченные картой заказы старше N минут и снять резерв"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--minutes",
            type=int,
            default=None,
            help="Сколько минут ждать оплаты (по умолчанию — из настроек)",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        minutes = options["minutes"]

        if minutes is not None and minutes < 0:
            self.stderr.write("--minutes — не меньше нуля.")

            raise SystemExit(1)

        done = orders.expire(minutes)
        self.stdout.write(f"Отменено неоплаченных заказов: {done}.")
