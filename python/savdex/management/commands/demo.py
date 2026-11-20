"""
Демо-наполнение тестового сервера (savdex/demo.py).

  manage.py demo    придуманные компании, владельцы, объявления и отзывы,
                    продавцы и товары маркетплейса (savdex/market/demo.py);
                    уже заведены — ничего. Маркетплейс добавляется и к
                    базе, где демо SavdEx уже есть. На боевом
                    (APP_ENV=production) отказывается.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from savdex import demo
from savdex.market import demo as market_demo


class Command(BaseCommand):
    help = "Демо-данные тестового сервера: придуманные компании, объявления и товары"

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            made = demo.seed()
            market = market_demo.seed()
        except demo.DemoRefusedError as error:
            raise CommandError(str(error)) from error

        if made["companies"]:
            self.stdout.write(
                f"Демо-данные: компаний {made['companies']}, владельцев {made['users']}, "
                f"объявлений {made['listings']}, отзывов {made['reviews']}"
            )
        else:
            self.stdout.write("Демо-данные уже есть — ничего нового")

        if market["products"]:
            self.stdout.write(
                f"Маркетплейс: продавцов {market['sellers']}, товаров {market['products']}, "
                f"вариантов {market['variants']}"
            )
        else:
            self.stdout.write("Демо маркетплейса уже есть — ничего нового")
