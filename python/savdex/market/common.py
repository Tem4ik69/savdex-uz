"""
Общее для маркетплейса: деньги, время, запросы, настройки, тексты.

Деньги в базе — целыми тийинами (bigint), наружу — сумами. Сумма из
формы продавца переводится в тийины один раз, на входе (``tiyin``), и
обратно — один раз, на выходе (``som``): дробей и округлений посередине нет.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from django.db import connection

from savdex.guards import allowed_writes
from savdex.web import ui
from savdex.web.shared import settings_values

#: Тийинов в суме
TIYIN = 100

#: Самая большая цена одной штуки — 10 млрд сумов: больше — опечатка
MAX_PRICE_SOM = 10_000_000_000

#: Самая маленькая цена товара — 100 сумов: дешевле — опечатка или
#: приманка «за 1 сум» в сортировке «Сначала дешёвые». Проверяет форма
#: товара (products.clean_variants), а не tiyin: фильтр каталога «цена от»
#: может быть и меньше
MIN_PRICE_SOM = 100

#: Таблицы маркетплейса — все пишет только Django (savdex/guards.py)
TABLES = (
    "market_categories",
    "market_attributes",
    "market_sellers",
    "market_products",
    "market_product_images",
    "market_product_variants",
    "market_product_values",
    "market_favorites",
    "market_cart_items",
)

#: Настройка «сколько первых товаров нового продавца — через модерацию»
PREMODERATED_KEY = "market_premoderated_products"
PREMODERATED_DEFAULT = 5


def now() -> str:
    """Время в UTC строкой, как пишет остальная площадка."""
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


#: Типы json и jsonb в PostgreSQL: Django отдаёт их строкой (её разбирает
#: JSONField), запросам маркетплейса нужны словари и списки
_JSON_TYPES = frozenset({114, 3802})


def rows(query: str, params: list[Any] | tuple[Any, ...] | None = None) -> list[dict[str, Any]]:
    """Строки запроса словарями: имя столбца → значение; json — разобранным."""
    with connection.cursor() as cursor:
        cursor.execute(query, list(params or []))
        description = cursor.description or []
        columns = [c[0] for c in description]
        decode = [getattr(c, "type_code", None) in _JSON_TYPES for c in description]

        return [
            {
                name: json.loads(value) if parse and isinstance(value, str) else value
                for name, value, parse in zip(columns, row, decode, strict=True)
            }
            for row in cursor.fetchall()
        ]


def one(query: str, params: list[Any] | tuple[Any, ...] | None = None) -> dict[str, Any] | None:
    found = rows(query, params)

    return found[0] if found else None


def write(query: str, params: list[Any] | tuple[Any, ...] | None = None) -> Any:  # noqa: ANN401
    """
    Запись в таблицы маркетплейса. Возвращает первое значение RETURNING,
    если оно есть, иначе число затронутых строк.
    """
    with allowed_writes(*TABLES), connection.cursor() as cursor:
        cursor.execute(query, list(params or []))

        if cursor.description:
            row = cursor.fetchone()

            return row[0] if row else None

        return cursor.rowcount


def tiyin(value: Any) -> int | None:  # noqa: ANN401
    """
    Сумма из формы (сумы: 125000, «125 000», «125000.50») → тийины.
    Не число, ноль, минус, больше предела, больше двух знаков после
    точки — None: такую цену форма не примет.
    """
    if value is None or isinstance(value, bool):
        return None

    text = str(value).replace(" ", "").replace(" ", "").replace(",", ".")

    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None

    if not amount.is_finite() or amount <= 0 or amount > MAX_PRICE_SOM:
        return None

    cents = amount * TIYIN

    if cents != cents.to_integral_value():
        return None

    return int(cents)


def som(value: int | None) -> int | float | None:
    """Тийины → сумы для страниц: целые — целым числом, иначе с тийинами."""
    if value is None:
        return None

    whole, rest = divmod(int(value), TIYIN)

    return whole if rest == 0 else int(value) / TIYIN


def premoderated_count() -> int:
    """
    Сколько первых товаров нового продавца идут через модерацию (ТЗ,
    раздел 5): настройка в админке, по умолчанию 5. Не число или
    меньше нуля — по умолчанию: проверку так случайно не выключить.
    """
    value = settings_values().get(PREMODERATED_KEY)

    try:
        number = int(str(value))
    except (TypeError, ValueError):
        return PREMODERATED_DEFAULT

    return number if number >= 0 else PREMODERATED_DEFAULT


def t(key: str, locale: str, **replace: object) -> str:
    """Текст из словаря интерфейса, раздел market."""
    return ui.t(f"market.{key}", locale, **replace)


def localized(name: str, names: Any, locale: str) -> str:  # noqa: ANN401
    """Название на языке страницы: перевода нет — по-русски."""
    if locale != "ru" and isinstance(names, dict):
        value = names.get(locale)

        if isinstance(value, str) and value.strip():
            return value

    return name
