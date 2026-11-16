"""
Пределы книги Excel до и во время разбора (Н35).

xlsx — zip: файл в 10 МБ распаковывается в сотни мегабайт XML, а openpyxl
в режиме read_only всё равно держит общие строки (sharedStrings.xml)
целиком. Ширину строк он берёт из заголовка листа или из самой дальней
ячейки: одна ячейка в столбце XFD растягивает строку до 16 384 значений,
а одна ячейка в строке 1 048 576 — до миллиона пустых строк перед ней.
Файл в 15 КБ так занимал 250 МБ памяти.

Поэтому:
- check — до разбора: число частей и их размер после распаковки (zipfile
  не распакует больше объявленного размера, так что объявленному можно
  верить);
- MAX_COLS и MAX_ROWS — при чтении: шире и длиннее не читаем.
"""

from __future__ import annotations

import io
import zipfile

#: Частей в архиве — у настоящей книги их десятки
MAX_PARTS = 1000

#: Всё, кроме картинок, после распаковки
MAX_UNPACKED = 100 * 1024 * 1024

#: Общие строки openpyxl держит в памяти целиком
MAX_SHARED_STRINGS = 30 * 1024 * 1024

#: Столбцов на листе — в шаблонах площадки их меньше сорока
MAX_COLS = 200

#: Строк на листе вместе с пустыми
MAX_ROWS = 10_000


class TooLargeError(ValueError):
    """Книга больше пределов — сообщение для человека."""


def check(content: bytes) -> None:
    """Книга не больше пределов после распаковки; не zip — решит openpyxl."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        return

    with archive:
        parts = archive.infolist()

        if len(parts) > MAX_PARTS:
            raise TooLargeError("В книге слишком много частей — сохраните её заново в Excel.")

        unpacked = sum(p.file_size for p in parts if not p.filename.startswith("xl/media/"))

        if unpacked > MAX_UNPACKED:
            raise TooLargeError(
                "Книга после распаковки больше 100 МБ — разбейте её на несколько файлов."
            )

        shared = sum(p.file_size for p in parts if p.filename.endswith("sharedStrings.xml"))

        if shared > MAX_SHARED_STRINGS:
            raise TooLargeError("В книге слишком много текста — разбейте её на несколько файлов.")


def too_many_rows() -> TooLargeError:
    return TooLargeError(
        f"На листе больше {MAX_ROWS:,} строк".replace(",", " ")
        + " — разбейте книгу на несколько файлов."
    )
