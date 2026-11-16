"""
Книга Excel не съедает память машины админки (Н35, savdex/data/xlsx_limits.py).

Заголовок листа с размером A1:XFD1048576, ячейка в столбце XFD или в
строке 1 048 576, части архива, раздутые после распаковки, — всё это
раньше разбиралось целиком: файл в 15 КБ занимал сотни мегабайт.
"""

from __future__ import annotations

import io
import re
import tracemalloc
import zipfile

import pytest
from openpyxl import Workbook

from savdex.data import xlsx_limits


def _книга(строк: int, *, размер: str | None = None, ячейки: tuple[str, ...] = ()) -> bytes:
    """Книга: столбец A на строк строк, по желанию — размер в заголовке и лишние ячейки."""
    wb = Workbook()
    ws = wb.active
    ws.append(["Название", "Заказчик", "Срок"])

    for r in range(строк):
        ws.append([f"Тендер {r}", "ООО Ромашка", "2026-12-31"])

    for адрес in ячейки:
        ws[адрес] = "x"

    buffer = io.BytesIO()
    wb.save(buffer)

    if размер is None:
        return buffer.getvalue()

    # Заголовок листа с чужим размером — как у файла, собранного не Excel
    source = zipfile.ZipFile(io.BytesIO(buffer.getvalue()))
    out = io.BytesIO()

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for part in source.infolist():
            data = source.read(part.filename)

            if part.filename == "xl/worksheets/sheet1.xml":
                новое = f'<dimension ref="{размер}"/>'.encode()
                data = re.sub(rb'<dimension ref="[^"]+" ?/>', новое, data)

            target.writestr(part.filename, data)

    return out.getvalue()


def _пик_памяти(действие) -> int:
    tracemalloc.start()

    try:
        действие()

        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def test_размер_из_заголовка_не_раздувает_строки():
    """2 000 строк при «размере» A1:XFD1048576 — не 16 384 значения в каждой."""
    from savdex.tenders.importer import read_table

    content = _книга(2000, размер="A1:XFD1048576")
    таблица: list = []
    пик = _пик_памяти(lambda: таблица.extend(read_table("t.xlsx", content)))

    assert len(таблица) == 2000
    assert set(таблица[0]) == {"Название", "Заказчик", "Срок"}
    # Раньше — около 250 МБ
    assert пик < 40 * 1024 * 1024


def test_ячейка_в_последней_строке_листа_отказ():
    """Одна ячейка в строке 1 048 576 — не миллион пустых строк, а понятный отказ."""
    from savdex.tenders.importer import read_table, unreadable

    content = _книга(3, ячейки=("A1048576",))

    with pytest.raises(xlsx_limits.TooLargeError) as error:
        read_table("t.xlsx", content)

    assert "разбейте" in unreadable(error.value)


def test_ячейка_в_столбце_xfd_не_растягивает_строку():
    from savdex.tenders.importer import read_table

    таблица = read_table("t.xlsx", _книга(3, ячейки=("XFD2",)))

    assert len(таблица) == 3
    assert set(таблица[0]) == {"Название", "Заказчик", "Срок"}


def test_раздутая_после_распаковки_книга_отклоняется_до_разбора(monkeypatch):
    monkeypatch.setattr(xlsx_limits, "MAX_UNPACKED", 1024 * 1024)
    out = io.BytesIO()

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        target.writestr("xl/worksheets/sheet1.xml", b"\0" * (2 * 1024 * 1024))

    # Сжатый файл маленький, распакованный — больше предела
    assert len(out.getvalue()) < 100 * 1024

    with pytest.raises(xlsx_limits.TooLargeError):
        xlsx_limits.check(out.getvalue())


def test_книга_объявлений_с_ячейкой_в_последней_строке():
    """Загрузка объявлений: тот же отказ, с понятной причиной, а не «не удалось прочитать»."""
    from savdex.data.workbook import UnreadableWorkbookError, import_workbook

    with pytest.raises(UnreadableWorkbookError) as error:
        import_workbook(_книга(3, ячейки=("A1048576",)), author_id=1)

    assert "разбейте" in str(error.value)
