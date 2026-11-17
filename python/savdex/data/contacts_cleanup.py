"""
Разовая чистка контактов в старых текстах (Н21, решение директора 15.11).

С Н21 телефон, почта, ссылка и ник в свободном тексте прячутся при записи
(chat_actions.mask_contacts). Эта чистка доводит до того же вида то, что
записано раньше:

- объявления: название, описание, условия доставки и оплаты, единица
  измерения и их переводы (title_i18n, description_i18n);
- значения полей раздела со свободным вводом (строка, текст, число);
- компании: название и описание;
- ответы компаний на отзывы;
- контакт «Сайт», который не адрес сайта (там прятали телефон), —
  становится скрытым (is_public = false): владелец увидит его в «Моих
  контактах» и поправит, данные не теряются.

updated_at не трогаем: это не правка владельца (порядок «Моих
объявлений», lastmod карты сайта). Отчёт — только числа, без строк
данных: журналы публичные.

manage.py contacts_cleanup — посчитать; --apply — записать. На боевом —
только после релиза и свежей копии базы.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from django.db import connection, transaction

from savdex.guards import allowed_writes
from savdex.web.chat_actions import mask_contacts
from savdex.web.company_contact_actions import website_ok
from savdex.web.company_profile_actions import _search_text as company_search_text
from savdex.web.listing_actions import _search_text as listing_search_text

#: Строк за раз: таблица не держится под замком долго
BATCH = 500

_LISTING_TEXT = ("title", "description", "delivery_terms", "payment_terms", "unit")
_LISTING_I18N = ("title_i18n", "description_i18n")

#: listing_attributes.value — varchar(255)
_ATTRIBUTE_LENGTH = 255


def _batches(sql: str, params: list[Any] | None = None) -> Iterator[list[dict[str, Any]]]:
    """Строки по номеру пачками: «… and id > %s order by id limit %s»."""
    last = 0

    while True:
        with connection.cursor() as cursor:
            cursor.execute(sql, [*(params or []), last, BATCH])
            columns = [c.name for c in cursor.description or []]
            rows = [dict(zip(columns, r, strict=True)) for r in cursor.fetchall()]

        if not rows:
            return

        yield rows
        last = int(rows[-1]["id"])


def _masked_json(value: Any) -> Any:  # noqa: ANN401
    """Перевод {язык: текст}: каждый текст — через маску."""
    if isinstance(value, str):
        value = json.loads(value)

    if not isinstance(value, dict):
        return value

    return {k: mask_contacts(v) if isinstance(v, str) else v for k, v in value.items()}


def _update(table: str, row_id: int, changes: dict[str, Any]) -> None:
    sets = ", ".join(f"{column} = %s" for column in changes)
    values = [
        json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else v for v in changes.values()
    ]

    with allowed_writes(table), connection.cursor() as cursor:
        cursor.execute(f"update {table} set {sets} where id = %s", [*values, row_id])


def _listings(apply: bool) -> int:
    changed = 0
    columns = ", ".join(("id", *_LISTING_TEXT, *_LISTING_I18N))

    for rows in _batches(f"select {columns} from listings where id > %s order by id limit %s"):
        with transaction.atomic():
            for row in rows:
                changes: dict[str, Any] = {}

                for column in _LISTING_TEXT:
                    if isinstance(row[column], str) and mask_contacts(row[column]) != row[column]:
                        changes[column] = mask_contacts(row[column])

                for column in _LISTING_I18N:
                    masked = _masked_json(row[column])

                    if row[column] is not None and masked != _masked_json_raw(row[column]):
                        changes[column] = masked

                if not changes:
                    continue

                changed += 1

                if apply:
                    after = {**row, **changes}
                    after["title_i18n"] = _masked_json_raw(after["title_i18n"])
                    changes["search_text"] = listing_search_text(after)
                    _update("listings", row["id"], changes)

    return changed


def _masked_json_raw(value: Any) -> Any:  # noqa: ANN401
    """Перевод как есть, разобранный из строки JSON."""
    return json.loads(value) if isinstance(value, str) else value


def _attributes(apply: bool) -> int:
    changed = 0
    sql = (
        "select a.id, a.value from listing_attributes a "
        "join listings l on l.id = a.listing_id "
        "join category_fields f on f.category_id = l.category_id and f.key = a.key "
        "where (f.type not in ('select', 'boolean', 'image') "
        "or (f.type = 'select' and coalesce(f.options::text, 'null') in ('null', '[]'))) "
        "and a.id > %s order by a.id limit %s"
    )

    for rows in _batches(sql):
        with transaction.atomic():
            for row in rows:
                masked = mask_contacts(row["value"])[:_ATTRIBUTE_LENGTH]

                if masked == row["value"]:
                    continue

                changed += 1

                if apply:
                    _update("listing_attributes", row["id"], {"value": masked})

    return changed


def _companies(apply: bool) -> int:
    changed = 0
    sql = (
        "select id, name, legal_name, description from companies where id > %s order by id limit %s"
    )

    for rows in _batches(sql):
        with transaction.atomic():
            for row in rows:
                changes = {
                    column: mask_contacts(row[column])
                    for column in ("name", "description")
                    if isinstance(row[column], str) and mask_contacts(row[column]) != row[column]
                }

                if not changes:
                    continue

                changed += 1

                if apply:
                    changes.update(company_search_text({**row, **changes}))
                    _update("companies", row["id"], changes)

    return changed


def _replies(apply: bool) -> int:
    changed = 0
    sql = "select id, reply from reviews where reply is not null and id > %s order by id limit %s"

    for rows in _batches(sql):
        with transaction.atomic():
            for row in rows:
                masked = mask_contacts(row["reply"])

                if masked == row["reply"]:
                    continue

                changed += 1

                if apply:
                    _update("reviews", row["id"], {"reply": masked})

    return changed


def _websites(apply: bool) -> int:
    changed = 0
    sql = (
        "select id, value from company_contacts where type = 'website' and is_public "
        "and id > %s order by id limit %s"
    )

    for rows in _batches(sql):
        with transaction.atomic():
            for row in rows:
                if website_ok(row["value"]):
                    continue

                changed += 1

                if apply:
                    _update("company_contacts", row["id"], {"is_public": False})

    return changed


def run(apply: bool = False) -> dict[str, int]:
    """Сколько строк в каждой части изменится (apply — и записать)."""
    return {
        "listings": _listings(apply),
        "attributes": _attributes(apply),
        "companies": _companies(apply),
        "replies": _replies(apply),
        "websites": _websites(apply),
    }
