"""
Отметить у оплаты маркетплейса «проверено у провайдера»
(savdex/market/payments/base.py, acknowledge): отказ на проведении
(rejected_at) или зависший возврат разобраны — сверка больше не считает
их расхождением.

  manage.py market_ack_payment <номер оплаты> --admin <id сотрудника> --note "<текст>"

Сотрудник — с правом market_cash.moderate (касса, этап 3) или суперадмин;
заметка — не короче 10 знаков: что проверили и где. Запись — в журнале
действий админки (payment_checked, раздел market_cash) и в истории заказа.
Кнопку в админке добавит касса; до неё — эта команда.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from savdex.market.payments import base


class Command(BaseCommand):
    help = "Маркетплейс: отметить отказ или зависший возврат оплаты как проверенный"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("payment_id", type=int, help="Номер оплаты (market_payments.id)")
        parser.add_argument("--admin", type=int, required=True, help="id сотрудника")
        parser.add_argument("--note", required=True, help="Что проверено (не короче 10 знаков)")

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            done = base.acknowledge(options["payment_id"], options["admin"], options["note"])
        except ValueError:
            self.stderr.write(
                f"Заметка — не короче {base.ACK_NOTE_MIN} знаков: что и где проверено."
            )

            raise SystemExit(2) from None
        except PermissionError:
            self.stderr.write(
                f"Отмечать может только сотрудник с правом {base.ACK_ABILITY} или суперадмин."
            )

            raise SystemExit(2) from None

        if not done:
            self.stderr.write(
                "Нечего отмечать: оплаты нет, она уже проверена или у неё нет ни отказа, "
                "ни ждущего возврата."
            )

            raise SystemExit(1)

        self.stdout.write(f"Оплата {options['payment_id']}: отмечено «проверено».")
