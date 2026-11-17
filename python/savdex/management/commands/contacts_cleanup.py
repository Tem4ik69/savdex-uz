"""
Разовая чистка контактов в старых текстах (Н21) — savdex/data/contacts_cleanup.py.

  manage.py contacts_cleanup            посчитать, что изменится
  manage.py contacts_cleanup --apply    записать

На боевом — только после релиза с Н21 и свежей копии базы.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from savdex.data import contacts_cleanup

_NAMES = {
    "listings": "объявлений (текст и переводы)",
    "attributes": "значений полей раздела",
    "companies": "компаний (название, описание)",
    "replies": "ответов на отзывы",
    "websites": "контактов «Сайт» не с адресом сайта — скрыть",
}


class Command(BaseCommand):
    help = "Н21: контакты в старых текстах — «[•••]», «Сайт» с телефоном — скрыть"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--apply", action="store_true", help="Записать (иначе только счёт)")

    def handle(self, *args: Any, **options: Any) -> None:
        apply = bool(options["apply"])
        counts = contacts_cleanup.run(apply=apply)
        prefix = "Изменено" if apply else "Изменится"

        for key, count in counts.items():
            self.stdout.write(f"{prefix}: {_NAMES[key]} — {count}")
