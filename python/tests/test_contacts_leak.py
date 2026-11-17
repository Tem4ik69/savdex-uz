"""
Н21: контакты не видны бесплатно мимо раскрытия — маска в свободном
тексте и разовая чистка старых текстов (manage.py contacts_cleanup).

Нужен PostgreSQL (SAVDEX_PARITY_PG_URL) для чистки.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from savdex.web.chat_actions import mask_contacts

from .factories import компания, объявление, отзыв
from .pg_admin import PYTHON, ОКРУЖЕНИЕ, sql, нужна_база, свежая_база


@pytest.mark.parametrize(
    ("текст", "итог"),
    [
        # Разделители, которые раньше пропускались
        ("Пишите ivan(at)mail.uz", "Пишите [•••]"),
        ("Пишите ivan [at] mail.uz", "Пишите [•••]"),
        ("сайт savdex.uz/catalog", "сайт [•••]"),
        ("wa.me/998901234567", "[•••]"),
        ("telegram ivan_petrov", "[•••]"),
        ("тг: ivan.petrov", "[•••]"),
        ("звоните 90.123.45.67", "звоните [•••]"),
        ("звоните 998/90/123/45/67", "звоните [•••]"),
        ("звоните 998_90_123_45_67", "звоните [•••]"),
        # Обычный текст не трогается
        ("цена 1 200 000, 1.250.000 сум, 12.03.2024", "цена 1 200 000, 1.250.000 сум, 12.03.2024"),
        ("Цемент М400, т.д., 50 кг", "Цемент М400, т.д., 50 кг"),
        ("Тг каналы есть", "Тг каналы есть"),
    ],
)
def test_маска(текст, итог):
    assert mask_contacts(текст) == итог


def _чистка(*args: str) -> str:
    вывод = subprocess.run(
        [sys.executable, "manage.py", "contacts_cleanup", *args],
        cwd=PYTHON,
        env={**ОКРУЖЕНИЕ, "PYTHONPATH": str(PYTHON)},
        capture_output=True,
        text=True,
    )
    assert вывод.returncode == 0, вывод.stderr[-3000:]

    return вывод.stdout


@нужна_база
def test_разовая_чистка_старых_текстов():
    свежая_база()
    чистая = компания(name="ООО «Чистая»", description="Цемент оптом")
    грязная = компания(name="ООО «Стройбаза» 901234567", description="Пишите sale(at)baza.uz")
    объявление(company_id=чистая, title="Цемент М400 Ташкент", description="Со склада")
    грязное = объявление(
        company_id=грязная,
        title="Цемент звоните 90 123 45 67",
        description="Со склада, тг: baza_uz",
        unit="901234567",
        title_i18n={"en": "Cement call 90 123 45 67"},
    )
    отзыв(company_id=грязная, reply="Спасибо! Наш номер 90 123 45 67")
    for вид, значение in (("website", "baza.uz"), ("website", "+998 90 123 45 67")):
        sql(
            "insert into company_contacts (company_id, type, value, is_public, sort_order, "
            "created_at, updated_at) values (%s, %s, %s, true, 0, now(), now())",
            [грязная, вид, значение],
        )
    до = sql("select id, updated_at from listings order by id")

    # Без --apply — только числа, база не меняется
    счёт = _чистка()
    assert "Изменится: объявлений (текст и переводы) — 1" in счёт
    assert "Изменится: компаний (название, описание) — 1" in счёт
    assert "Изменится: ответов на отзывы — 1" in счёт
    assert "Изменится: контактов «Сайт» не с адресом сайта — скрыть — 1" in счёт
    assert sql("select count(*) from listings where title like '%%[•••]%%'") == [(0,)]

    вывод = _чистка("--apply")
    assert "Изменено: объявлений (текст и переводы) — 1" in вывод

    [(title, description, unit, i18n, search)] = sql(
        "select title, description, unit, title_i18n::text, search_text from listings "
        "where id = %s",
        [грязное],
    )
    assert (title, description, unit) == ("Цемент звоните [•••]", "Со склада, [•••]", "[•••]")
    assert "90 123" not in i18n and "90 123" not in search
    assert sql("select name, description from companies where id = %s", [грязная]) == [
        ("ООО «Стройбаза» [•••]", "Пишите [•••]")
    ]
    assert sql("select reply from reviews") == [("Спасибо! Наш номер [•••]",)]
    assert sql("select value, is_public from company_contacts order by id") == [
        ("baza.uz", True),
        ("+998 90 123 45 67", False),
    ]
    # Чистое не тронуто; updated_at — ни у кого: это не правка владельца
    assert sql("select title from listings where company_id = %s", [чистая]) == [
        ("Цемент М400 Ташкент",)
    ]
    assert sql("select id, updated_at from listings order by id") == до
    # Второй проход — нечего менять
    assert "Изменится: объявлений (текст и переводы) — 0" in _чистка()
