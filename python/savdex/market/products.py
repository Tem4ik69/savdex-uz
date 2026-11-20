"""
Товары продавца (ТЗ, раздел 5): черновик, варианты, характеристики, фото,
отправка на продажу и снятие.

Путь товара:

    draft ──submit──▶ pending ──модератор──▶ active
      ▲                  │                     │
      └──── правка ◀── rejected            hide / blocked

- Черновик продавец правит сколько угодно; покупатель его не видит.
- «Отправить на продажу»: если у продавца меньше N товаров, уже
  прошедших модерацию (настройка market_premoderated_products, по
  умолчанию 5), товар ждёт модератора (pending), иначе — сразу в продаже.
- Пока продавец «новый» (одобренных товаров меньше N), правка текста,
  категории, характеристик или фото товара в продаже или на проверке
  возвращает его в черновик: покупатель не должен увидеть непроверенное
  под проверенной карточкой. Названия вариантов (options) и артикулы —
  тоже содержание. У проверенного продавца правка — сразу на витрине, как
  и новые товары. Цена и включение вариантов статус не меняют никогда.
- Отклонённый или снятый модератором товар назад в продажу — только через
  модератора, даже у проверенного продавца: пометка — reject_reason, её
  стирает только одобрение (``approve``). Снятый продавцом (hidden) товар
  без такой пометки проверенный продавец возвращает сразу.
- Снятый модератором (blocked) товар продавец не правит.

Остаток продавец не задаёт: к продаже доступно только то, что лежит на
складе BTS (ТЗ, раздел 6). Пока склада в коде нет, остаток ставит
сотрудник в админке; появится склад — остаток будет приходить с приёмки.

Цена — в сумах из формы, в базе — тийины (common.tiyin).
"""

from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import IO, Any

from django.db import transaction

from savdex import images
from savdex.market.catalog import attributes_for, image_view
from savdex.market.common import (
    MIN_PRICE_SOM,
    TIYIN,
    now,
    one,
    premoderated_count,
    rows,
    som,
    tiyin,
    write,
)
from savdex.tenders.slug import numbered_slug
from savdex.web.shared import public_url

#: Фото у товара — не больше (ТЗ: «до 10 фото»)
MAX_IMAGES = 10

#: Вариантов у товара — не больше: дальше это уже другой товар
MAX_VARIANTS = 100

#: Измерений выбора («Цвет», «Размер», «Объём») — не больше трёх
MAX_OPTION_NAMES = 3

#: Фото товара — квадрат до 1600 px, WebP. На входе — не больше 25 Мп
#: (≈ 6100×4100; обычный снимок телефона, 12 Мп, проходит с запасом):
#: общий предел 48 Мп рассчитан на баннеры, а фото товара грузят чаще и
#: по десять за раз — распаковка каждого держит память воркера
PHOTO = images.Frame(1600, 1600, 82, max_pixels=25_000_000)

#: Уменьшенная копия для карточек каталога на телефоне
THUMB = images.Frame(480, 480, 78)

LOCALES = ("ru", "uz", "en", "zh", "tr")

#: «Да / нет» из формы → value_text '1' / '0' (миграция 2026_11_19_110000)
BOOL_VALUES = {
    "1": "1", "true": "1", "yes": "1", "on": "1", "да": "1", "ha": "1",
    "0": "0", "false": "0", "no": "0", "off": "0", "нет": "0", "yo'q": "0",
}  # fmt: skip

#: Статусы, в которых продавец может править товар (тот же список — в
#: условии записи в save: модератор мог снять товар между чтением и записью)
EDITABLE = ("draft", "pending", "active", "rejected", "hidden")

STATUSES: dict[str, str] = {
    "draft": "Черновик",
    "pending": "На проверке",
    "active": "В продаже",
    "rejected": "Отклонён",
    "blocked": "Снят модератором",
    "hidden": "Снят продавцом",
}


@dataclass
class Errors:
    """Ошибки формы: поле → ключи текстов (common.t)."""

    fields: dict[str, list[str]] = field(default_factory=dict)

    def add(self, name: str, key: str) -> None:
        self.fields.setdefault(name, []).append(key)

    def __bool__(self) -> bool:
        return bool(self.fields)


# ── Разбор формы ────────────────────────────────────────────────────


def _int(value: Any, low: int, high: int) -> int | None:  # noqa: ANN401
    if value is None or value == "" or isinstance(value, bool):
        return None

    try:
        number = int(str(value).strip())
    except ValueError:
        return None

    return number if low <= number <= high else None


def _text(value: Any, limit: int) -> str | None:  # noqa: ANN401
    if value is None:
        return None

    text = re.sub(r"[ \t]+", " ", str(value)).strip()

    return text[:limit] if text else None


def clean(data: dict[str, Any], errors: Errors) -> dict[str, Any]:
    """
    Поля товара из формы продавца. Для черновика обязательны только
    название и категория; остальное проверяется при отправке на продажу
    (``missing``).
    """
    out: dict[str, Any] = {}
    title = _text(data.get("title"), 1000)

    if title is None:
        errors.add("title", "product.title_required")
    elif len(title) < 3 or len(title) > 200:
        errors.add("title", "product.title_length")
    else:
        out["title"] = title

    description = str(data.get("description") or "").strip()

    if len(description) > 5000:
        errors.add("description", "product.description_length")
    else:
        out["description"] = description or None

    locale = str(data.get("locale") or "ru")
    out["locale"] = locale if locale in LOCALES else "ru"

    category = (
        one(
            "select c.id from market_categories c where c.slug = %s and c.is_active "
            "and not exists (select 1 from market_categories k where k.parent_id = c.id "
            "and k.is_active)",
            [str(data.get("category") or "")],
        )
        if data.get("category")
        else None
    )

    if category is None:
        errors.add("category", "product.category_required")
    else:
        out["category_id"] = category["id"]

    # Только ASCII-цифры: \D пропустил бы «٣» и другие цифры Юникода, а
    # база (market_products_ikpu_check) примет только 0–9 — была бы 500
    ikpu = re.sub(r"[^0-9]", "", str(data.get("ikpu") or ""))

    if ikpu and len(ikpu) != 17:
        errors.add("ikpu", "product.ikpu_format")
    else:
        out["ikpu"] = ikpu or None

    barcode = re.sub(r"[^0-9]", "", str(data.get("barcode") or ""))

    if barcode and not 8 <= len(barcode) <= 14:
        errors.add("barcode", "product.barcode_format")
    else:
        out["barcode"] = barcode or None

    for name, high in (
        ("weight_g", 1_000_000),
        ("length_mm", 10_000),
        ("width_mm", 10_000),
        ("height_mm", 10_000),
    ):
        raw = data.get(name)
        value = _int(raw, 1, high)

        if raw not in (None, "") and value is None:
            errors.add(name, "product.size_format")
        else:
            out[name] = value

    return out


def clean_variants(data: Any, errors: Errors) -> list[dict[str, Any]]:  # noqa: ANN401
    """
    Варианты: [{"id": 5?, "options": {"Цвет": "Чёрный"}, "sku": "…",
    "price": 125000, "oldPrice": 150000, "active": true}]. У товара без
    выбора — один вариант с options {}. Остатка здесь нет — он со склада.
    """
    if not isinstance(data, list) or not data:
        errors.add("variants", "product.variants_required")

        return []

    if len(data) > MAX_VARIANTS:
        errors.add("variants", "product.variants_limit")

        return []

    result = []
    seen: set[str] = set()
    names: set[str] = set()

    for index, item in enumerate(data):
        prefix = f"variants.{index}"

        if not isinstance(item, dict):
            errors.add(prefix, "product.variant_invalid")
            continue

        options_raw = item.get("options") or {}
        options: dict[str, str] = {}

        if not isinstance(options_raw, dict):
            errors.add(f"{prefix}.options", "product.variant_invalid")
            continue

        for name, value in options_raw.items():
            key = _text(name, 40)
            text = _text(value, 60)

            # «_…» — служебные пометки вариантов (_save_variants), не выбор покупателя
            if key is None or text is None or key.startswith("_"):
                errors.add(f"{prefix}.options", "product.variant_invalid")
                break

            options[key] = text
            names.add(key)

        signature = repr(sorted(options.items()))

        if signature in seen:
            errors.add(f"{prefix}.options", "product.variant_duplicate")

        seen.add(signature)
        price = tiyin(item.get("price"))
        old = tiyin(item.get("oldPrice")) if item.get("oldPrice") not in (None, "", 0) else None

        if price is None:
            errors.add(f"{prefix}.price", "product.price_format")
        elif price < MIN_PRICE_SOM * TIYIN:
            errors.add(f"{prefix}.price", "product.price_min")
        elif item.get("oldPrice") not in (None, "", 0) and (old is None or old <= price):
            errors.add(f"{prefix}.oldPrice", "product.old_price_format")

        sku = _text(item.get("sku"), 64)
        variant_id = _int(item.get("id"), 1, 2**62)
        result.append(
            {
                "id": variant_id,
                "options": options,
                "sku": sku,
                "price": price,
                "old_price": old,
                "is_active": item.get("active", True) is not False,
                "sort": index,
            }
        )

    if len(names) > MAX_OPTION_NAMES:
        errors.add("variants", "product.options_limit")

    return result


def clean_values(
    data: Any,  # noqa: ANN401
    category_id: int | None,
    errors: Errors,
) -> list[tuple[int, str | None, Decimal | None]]:
    """Характеристики: {"color": "red", "memory": 128} — по ключам характеристик категории."""
    if category_id is None or data in (None, ""):
        return []

    if not isinstance(data, dict):
        errors.add("values", "product.value_invalid")

        return []

    attributes = {a["key"]: a for a in attributes_for(category_id)}
    result: list[tuple[int, str | None, Decimal | None]] = []

    for key, raw in data.items():
        attribute = attributes.get(str(key))

        if attribute is None or raw in (None, ""):
            continue

        name = f"values.{key}"

        if attribute["kind"] == "number":
            try:
                number = Decimal(str(raw).replace(",", ".").replace(" ", ""))
            except InvalidOperation:
                errors.add(name, "product.value_number")
                continue

            if not number.is_finite() or abs(number) >= Decimal("1e11"):
                errors.add(name, "product.value_number")
                continue

            result.append((attribute["id"], None, number.quantize(Decimal("0.001"))))
        elif attribute["kind"] == "bool":
            flag = BOOL_VALUES.get(str(raw).strip().lower())

            if flag is None:
                errors.add(name, "product.value_bool")
                continue

            result.append((attribute["id"], flag, None))
        elif attribute["kind"] == "choice":
            allowed = {
                str(o.get("value")) for o in attribute["options"] or [] if isinstance(o, dict)
            }

            if str(raw) not in allowed:
                errors.add(name, "product.value_choice")
                continue

            result.append((attribute["id"], str(raw), None))
        else:
            text = _text(raw, 200)

            if text is not None:
                result.append((attribute["id"], text, None))

    return result


# ── Запись ──────────────────────────────────────────────────────────


def owned(seller_id: int, product_id: int) -> dict[str, Any] | None:
    """Товар своего продавца; чужой — None (404, а не 403: не подтверждаем, что он есть)."""
    return one(
        "select * from market_products where id = %s and seller_id = %s", [product_id, seller_id]
    )


def refresh(product_id: int) -> None:
    """
    Сводка по вариантам в строке товара: самая низкая цена включённого
    варианта, который можно купить (остаток за вычетом резерва больше
    нуля), её старая цена и сумма остатков. Купить нечего — цена самого
    дешёвого включённого. Иначе каталог показывал бы цену варианта,
    которого нет на складе, а в карточке товар оказывался бы дороже.
    """
    write(
        "update market_products p set "
        "price = v.price, old_price = v.old_price, stock = coalesce(v.stock, 0) "
        "from (select "
        "  (select price from market_product_variants where product_id = %s and is_active "
        "   order by stock - reserved > 0 desc, price, id limit 1) as price, "
        "  (select old_price from market_product_variants where product_id = %s and is_active "
        "   order by stock - reserved > 0 desc, price, id limit 1) as old_price, "
        "  (select sum(stock - reserved) from market_product_variants "
        "   where product_id = %s and is_active) as stock"
        ") v where p.id = %s",
        [product_id, product_id, product_id, product_id],
    )


def _save_variants(product_id: int, variants: list[dict[str, Any]]) -> None:
    """
    Варианты товара как в форме: с id — правка своего, без id — новый,
    не пришедший — выключается и помечается убранным (не удаляется).
    """
    existing = {
        r["id"]: r
        for r in rows(
            "select id from market_product_variants where product_id = %s "
            "and not options ? '_removed'",
            [product_id],
        )
    }
    kept = {v["id"] for v in variants if v["id"] in existing}
    moment = now()

    # Сначала убранные — пометить: иначе новый вариант с тем же
    # сочетанием, что у убранного в этом же запросе, упёрся бы в
    # уникальность (product_id, options) — 500 вместо сохранения
    for variant_id in set(existing) - kept:
        # Вариант не удаляется никогда: на него будут ссылаться позиции
        # заказов (и остаток на складе). Убранный продавцом — выключен и
        # помечен; его фото становятся общими, из корзин он уходит
        write(
            "update market_product_variants set is_active = false, options = "
            "jsonb_build_object('_removed', id), updated_at = %s where id = %s",
            [moment, variant_id],
        )
        write(
            "update market_product_images set variant_id = null where variant_id = %s", [variant_id]
        )
        write("delete from market_cart_items where variant_id = %s", [variant_id])

    # Затем оставшиеся — во временные options, чтобы обмен сочетаниями
    # между вариантами не упёрся в уникальность
    for variant_id in kept:
        write(
            "update market_product_variants set options = jsonb_build_object('_', id) "
            "where id = %s",
            [variant_id],
        )

    for variant in variants:
        options = json.dumps(variant["options"], ensure_ascii=False)

        if variant["id"] in kept:
            write(
                "update market_product_variants set options = %s::jsonb, sku = %s, price = %s, "
                "old_price = %s, is_active = %s, sort = %s, updated_at = %s where id = %s",
                [
                    options,
                    variant["sku"],
                    variant["price"],
                    variant["old_price"],
                    variant["is_active"],
                    variant["sort"],
                    moment,
                    variant["id"],
                ],
            )
        else:
            write(
                "insert into market_product_variants (product_id, options, sku, price, "
                "old_price, is_active, sort, created_at, updated_at) "
                "values (%s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s)",
                [
                    product_id,
                    options,
                    variant["sku"],
                    variant["price"],
                    variant["old_price"],
                    variant["is_active"],
                    variant["sort"],
                    moment,
                    moment,
                ],
            )


def _save_values(product_id: int, values: list[tuple[int, str | None, Decimal | None]]) -> None:
    write("delete from market_product_values where product_id = %s", [product_id])

    for attribute_id, text, number in values:
        write(
            "insert into market_product_values (product_id, attribute_id, value_text, "
            "value_number) values (%s, %s, %s, %s)",
            [product_id, attribute_id, text, number],
        )


def save(
    seller: dict[str, Any], data: dict[str, Any], product_id: int | None = None
) -> tuple[int | None, Errors]:
    """
    Создать или изменить товар. Итог — (номер товара, ошибки). У нового
    продавца правка содержания возвращает товар в черновик (``reviewed``).
    """
    errors = Errors()
    row = owned(seller["id"], product_id) if product_id is not None else None

    if product_id is not None and row is None:
        errors.add("product", "not_found")

        return None, errors

    if row is not None and row["status"] not in EDITABLE:
        errors.add("product", "product.locked")

        return None, errors

    fields = clean(data, errors)
    variants = clean_variants(data.get("variants"), errors)
    values = clean_values(data.get("values"), fields.get("category_id"), errors)

    if errors:
        return None, errors

    if row is not None:
        foreign = [
            v["id"] for v in variants if v["id"] is not None and not _variant_of(row["id"], v["id"])
        ]

        if foreign:
            errors.add("variants", "product.variant_invalid")

            return None, errors

        # Товару в продаже или на проверке нужны цена и ИКПУ: в продаже без них
        # запись упёрлась бы в market_products_active_check — 500, а товар на
        # проверке модератор не смог бы одобрить
        if row["status"] in ("active", "pending") and not any(v["is_active"] for v in variants):
            errors.add("variants", "product.active_variant_required")

        if row["status"] in ("active", "pending") and not fields["ikpu"]:
            errors.add("ikpu", "product.ikpu_required")

        if errors:
            return None, errors

    moment = now()
    draft = (
        row is not None and _content_changed(row, fields, values, variants) and needs_review(seller)
    )

    with transaction.atomic():
        if row is None:
            product_id = write(
                "insert into market_products (seller_id, category_id, title, description, "
                "locale, ikpu, barcode, weight_g, length_mm, width_mm, height_mm, status, "
                "created_at, updated_at) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                "'draft', %s, %s) returning id",
                [
                    seller["id"],
                    fields["category_id"],
                    fields["title"],
                    fields["description"],
                    fields["locale"],
                    fields["ikpu"],
                    fields["barcode"],
                    fields["weight_g"],
                    fields["length_mm"],
                    fields["width_mm"],
                    fields["height_mm"],
                    moment,
                    moment,
                ],
            )
        else:
            # Статус проверен выше, но модератор мог снять товар за это
            # время: тогда правка не проходит
            changed = write(
                "update market_products set category_id = %s, title = %s, description = %s, "
                "locale = %s, ikpu = %s, barcode = %s, weight_g = %s, length_mm = %s, "
                "width_mm = %s, height_mm = %s, updated_at = %s "
                "where id = %s and status in ('draft', 'pending', 'active', 'rejected', 'hidden')",
                [
                    fields["category_id"],
                    fields["title"],
                    fields["description"],
                    fields["locale"],
                    fields["ikpu"],
                    fields["barcode"],
                    fields["weight_g"],
                    fields["length_mm"],
                    fields["width_mm"],
                    fields["height_mm"],
                    moment,
                    product_id,
                ],
            )

            if not changed:
                errors.add("product", "product.locked")

                return None, errors

        assert product_id is not None

        if draft:
            _to_draft(product_id)

        _save_variants(product_id, variants)
        _save_values(product_id, values)
        refresh(product_id)

    return product_id, errors


#: Сколько дней после отказа или снятия товары продавца снова проверяет модератор
RECENT_REFUSAL_DAYS = 30


def needs_review(seller: dict[str, Any]) -> bool:
    """
    Товары и правки продавца проверяет модератор: продавец ещё «новый» —
    или недавно получил отказ или снятие (у товара осталась причина). Иначе
    отклонённый товар выходил бы в продажу копией — новым товаром с тем же
    содержимым, который проверенному продавцу публиковать можно сразу.
    """
    if moderated_count(seller["id"]) < premoderated_count():
        return True

    return (
        one(
            "select 1 as x from market_products where seller_id = %s "
            "and reject_reason is not null and moderated_at > "
            "(now() at time zone 'utc') - make_interval(days => %s) limit 1",
            [seller["id"], RECENT_REFUSAL_DAYS],
        )
        is not None
    )


def _to_draft(product_id: int) -> None:
    """Товар в продаже или на проверке — обратно в черновик (правка у нового продавца)."""
    write(
        "update market_products set status = 'draft', updated_at = %s "
        "where id = %s and status in ('active', 'pending')",
        [now(), product_id],
    )


def _variant_text(options: dict[str, Any], sku: str | None) -> tuple[str, str | None]:
    """Что покупатель читает у варианта: сочетание выбора и артикул — без цены."""
    return repr(sorted((str(k), str(v)) for k, v in options.items())), sku


def _content_changed(
    row: dict[str, Any],
    fields: dict[str, Any],
    values: list[tuple[int, str | None, Decimal | None]],
    variants: list[dict[str, Any]],
) -> bool:
    """
    Поменялось ли то, что проверяет модератор: текст, категория,
    характеристики, названия вариантов и артикулы. Цена, включение и
    порядок вариантов — нет; убрать вариант — тоже нет: непроверенного
    текста от этого не прибавляется.
    """
    for name in ("title", "description", "category_id"):
        if row[name] != fields[name]:
            return True

    shown = {
        _variant_text(r["options"] or {}, r["sku"])
        for r in rows(
            "select options, sku from market_product_variants where product_id = %s "
            "and not options ? '_removed'",
            [row["id"]],
        )
    }

    if any(_variant_text(v["options"], v["sku"]) not in shown for v in variants):
        return True

    before = {
        (r["attribute_id"], r["value_text"], r["value_number"])
        for r in rows(
            "select attribute_id, value_text, value_number from market_product_values "
            "where product_id = %s",
            [row["id"]],
        )
    }

    return before != set(values)


def _variant_of(product_id: int, variant_id: int) -> bool:
    return (
        one(
            "select 1 as x from market_product_variants where id = %s and product_id = %s",
            [variant_id, product_id],
        )
        is not None
    )


def missing(product: dict[str, Any]) -> list[str]:
    """Чего не хватает товару для продажи: ключи текстов полей."""
    gaps = []

    if not product["ikpu"]:
        gaps.append("ikpu")

    if product["price"] is None:
        gaps.append("variants")

    if (
        one("select 1 as x from market_product_images where product_id = %s", [product["id"]])
        is None
    ):
        gaps.append("images")

    required = [a for a in attributes_for(product["category_id"]) if a["is_required"]]

    if required:
        filled = {
            r["attribute_id"]
            for r in rows(
                "select attribute_id from market_product_values where product_id = %s",
                [product["id"]],
            )
        }

        if any(a["id"] not in filled for a in required):
            gaps.append("values")

    return gaps


def moderated_count(seller_id: int) -> int:
    """Сколько товаров продавца модератор уже одобрил."""
    found = one(
        "select count(*) as n from market_products where seller_id = %s "
        "and approved_at is not null",
        [seller_id],
    )

    return int(found["n"]) if found else 0


def submit(seller: dict[str, Any], product_id: int) -> tuple[str | None, list[str]]:
    """
    «Отправить на продажу»: (новый статус, чего не хватает). Новичок —
    на модерацию, проверенный продавец — сразу в продажу.

    Отклонённый или снятый модератором товар (пометка reject_reason — до
    одобрения) — на модерацию всегда: иначе проверенный продавец вернул бы
    на витрину ровно то, что модератор убрал. Снятый самим продавцом после
    продажи (hidden без пометки) и ни разу не отклонённый черновик у
    проверенного продавца — сразу в продажу.
    """
    row = owned(seller["id"], product_id)

    if row is None:
        return None, ["not_found"]

    if row["status"] not in ("draft", "rejected", "hidden"):
        return None, ["product.not_draft"]

    gaps = missing(row)

    if gaps:
        return None, gaps

    moment = now()
    slug = row["slug"] or numbered_slug(row["title"], row["id"])[:80].strip("-")

    refused = row["status"] == "rejected" or row["reject_reason"] is not None

    # В условии записи — те же статусы, что проверены выше: модератор мог
    # снять товар за это время, и тогда отправка не проходит. Причина
    # отказа не стирается: она — пометка «только через модератора»
    if refused or needs_review(seller):
        changed = write(
            "update market_products set status = 'pending', slug = %s, submitted_at = %s, "
            "updated_at = %s where id = %s and status in ('draft', 'rejected', 'hidden')",
            [slug, moment, moment, product_id],
        )

        return ("pending", []) if changed else (None, ["product.locked"])

    changed = write(
        "update market_products set status = 'active', slug = %s, submitted_at = %s, "
        "published_at = coalesce(published_at, %s), updated_at = %s "
        "where id = %s and status in ('draft', 'hidden') and reject_reason is null",
        [slug, moment, moment, moment, product_id],
    )

    return ("active", []) if changed else (None, ["product.locked"])


def hide(seller: dict[str, Any], product_id: int) -> bool:
    """Продавец снимает товар с продажи (вернуть — снова «Отправить на продажу»)."""
    return bool(
        write(
            "update market_products set status = 'hidden', updated_at = %s "
            "where id = %s and seller_id = %s and status in ('active', 'pending')",
            [now(), product_id, seller["id"]],
        )
    )


# ── Фото ────────────────────────────────────────────────────────────


def _variant_for_image(product_id: int, variant_id: int | None) -> bool:
    """Фото можно привязать только к живому варианту этого же товара (держит и база)."""
    if variant_id is None:
        return True

    return (
        one(
            "select 1 as x from market_product_variants where id = %s and product_id = %s "
            "and not options ? '_removed'",
            [variant_id, product_id],
        )
        is not None
    )


def add_image(
    seller: dict[str, Any], product_id: int, upload: IO[bytes], variant_id: int | None = None
) -> tuple[str | None, str]:
    """
    Добавить фото: (путь, ключ ошибки). Файл пересобирается в WebP без
    EXIF, рядом — уменьшенная копия для карточек каталога (thumb_path).
    variant_id — фото одного варианта (цвета); без него — общее фото.
    """
    row = owned(seller["id"], product_id)

    if row is None:
        return None, "not_found"

    if row["status"] not in EDITABLE:
        return None, "product.locked"

    if not _variant_for_image(product_id, variant_id):
        return None, "product.variant_invalid"

    count = one(
        "select count(*) as n from market_product_images where product_id = %s", [product_id]
    )

    if count is not None and int(count["n"]) >= MAX_IMAGES:
        return None, "product.images_limit"

    try:
        binary = images.prepare(upload, PHOTO)
        thumb = images.process(io.BytesIO(binary), THUMB)
    except images.NotAnImageError:
        return None, "product.image_invalid"

    path = images.write(binary, "market/products")
    thumb_path = images.write(thumb, "market/products/thumbs")

    if needs_review(seller):
        _to_draft(product_id)

    write(
        "insert into market_product_images (product_id, variant_id, path, thumb_path, sort) "
        "values (%s, %s, %s, %s, (select coalesce(max(sort), -1) + 1 "
        "from market_product_images where product_id = %s))",
        [product_id, variant_id, path, thumb_path, product_id],
    )

    return path, ""


def set_image_variant(
    seller: dict[str, Any], product_id: int, image_id: int, variant_id: int | None
) -> str:
    """Чьё фото: варианта или общее. Итог — ключ ошибки или пусто."""
    row = owned(seller["id"], product_id)

    if row is None:
        return "not_found"

    if row["status"] not in EDITABLE:
        return "product.locked"

    if not _variant_for_image(product_id, variant_id):
        return "product.variant_invalid"

    changed = write(
        "update market_product_images set variant_id = %s where id = %s and product_id = %s",
        [variant_id, image_id, product_id],
    )

    return "" if changed else "not_found"


def remove_image(seller: dict[str, Any], product_id: int, image_id: int) -> bool:
    row = owned(seller["id"], product_id)

    if row is None or row["status"] not in EDITABLE:
        return False

    found = one(
        "select path, thumb_path from market_product_images where id = %s and product_id = %s",
        [image_id, product_id],
    )

    if found is None:
        return False

    write("delete from market_product_images where id = %s", [image_id])
    images.delete(found["path"], found["thumb_path"])

    if needs_review(seller):
        _to_draft(product_id)

    return True


# ── Список «Мои товары» ─────────────────────────────────────────────


def mine(seller: dict[str, Any]) -> list[dict[str, Any]]:
    """Товары продавца для кабинета: все статусы, новые сверху."""
    found = rows(
        "select p.id, p.slug, p.title, p.status, p.reject_reason, p.price, p.old_price, "
        "p.stock, p.sold_count, p.views_count, p.updated_at, "
        "(select coalesce(i.thumb_path, i.path) from market_product_images i "
        " where i.product_id = p.id order by i.variant_id is not null, i.sort, i.id "
        " limit 1) as cover "
        "from market_products p where p.seller_id = %s order by p.updated_at desc, p.id desc",
        [seller["id"]],
    )

    return [
        {
            "id": r["id"],
            "slug": r["slug"],
            "title": r["title"],
            "status": r["status"],
            "rejectReason": r["reject_reason"],
            "price": som(r["price"]),
            "oldPrice": som(r["old_price"]),
            "stock": r["stock"],
            "sold": r["sold_count"],
            "views": r["views_count"],
            "image": public_url(r["cover"]) if r["cover"] else None,
        }
        for r in found
    ]


def detail(seller: dict[str, Any], product_id: int) -> dict[str, Any] | None:
    """Товар для формы правки продавца: все поля, варианты, характеристики, фото."""
    row = owned(seller["id"], product_id)

    if row is None:
        return None

    category = one("select slug from market_categories where id = %s", [row["category_id"]])
    attributes = {a["id"]: a for a in attributes_for(row["category_id"])}
    values = {}

    for v in rows(
        "select attribute_id, value_text, value_number from market_product_values "
        "where product_id = %s",
        [product_id],
    ):
        attribute = attributes.get(v["attribute_id"])

        if attribute is not None:
            if v["value_number"] is not None:
                values[attribute["key"]] = float(v["value_number"])
            elif attribute["kind"] == "bool":
                values[attribute["key"]] = v["value_text"] == "1"
            else:
                values[attribute["key"]] = v["value_text"]

    return {
        "id": row["id"],
        "slug": row["slug"],
        "status": row["status"],
        "rejectReason": row["reject_reason"],
        "title": row["title"],
        "description": row["description"] or "",
        "locale": row["locale"],
        "category": category["slug"] if category else None,
        "ikpu": row["ikpu"],
        "barcode": row["barcode"],
        "weight_g": row["weight_g"],
        "length_mm": row["length_mm"],
        "width_mm": row["width_mm"],
        "height_mm": row["height_mm"],
        "values": values,
        "variants": [
            {
                "id": v["id"],
                "options": v["options"],
                "sku": v["sku"],
                "price": som(v["price"]),
                "oldPrice": som(v["old_price"]),
                "stock": v["stock"],
                "active": v["is_active"],
            }
            for v in rows(
                "select * from market_product_variants where product_id = %s "
                "and not options ? '_removed' order by sort, id",
                [product_id],
            )
        ],
        "images": [
            image_view(i)
            for i in rows(
                "select id, path, thumb_path, variant_id from market_product_images "
                "where product_id = %s order by sort, id",
                [product_id],
            )
        ],
        "missing": missing(row),
    }


# ── Решения модератора ──────────────────────────────────────────────


def approve(product_id: int, admin_id: int) -> bool:
    """Модератор пропустил товар: в продаже, засчитан продавцу в «проверенные»."""
    moment = now()

    return bool(
        write(
            "update market_products set status = 'active', published_at = coalesce("
            "published_at, %s), approved_at = coalesce(approved_at, %s), moderated_by = %s, "
            "moderated_at = %s, reject_reason = null, updated_at = %s "
            "where id = %s and status = 'pending'",
            [moment, moment, admin_id, moment, moment, product_id],
        )
    )


def reject(product_id: int, admin_id: int, reason: str) -> bool:
    """Отклонить с причиной: продавец исправит и отправит снова."""
    reason = reason.strip()

    if len(reason) < 10:
        raise ValueError("Причина — не короче 10 знаков")

    moment = now()

    return bool(
        write(
            "update market_products set status = 'rejected', reject_reason = %s, "
            "moderated_by = %s, moderated_at = %s, updated_at = %s "
            "where id = %s and status = 'pending'",
            [reason[:1000], admin_id, moment, moment, product_id],
        )
    )


def block(product_id: int, admin_id: int, reason: str) -> bool:
    """Модератор снимает любой товар (ТЗ, раздел 5). Продавец его больше не правит."""
    reason = reason.strip()

    if len(reason) < 10:
        raise ValueError("Причина — не короче 10 знаков")

    moment = now()

    return bool(
        write(
            "update market_products set status = 'blocked', reject_reason = %s, "
            "moderated_by = %s, moderated_at = %s, updated_at = %s "
            "where id = %s and status <> 'blocked'",
            [reason[:1000], admin_id, moment, moment, product_id],
        )
    )


def unblock(product_id: int, admin_id: int) -> bool:
    """
    Вернуть снятый модератором товар — в черновик: продавец проверит и
    отправит. Причина снятия остаётся: продавец видит, что исправить, а
    отправка идёт через модератора (submit), пока тот не одобрит.
    """
    moment = now()

    return bool(
        write(
            "update market_products set status = 'draft', "
            "moderated_by = %s, moderated_at = %s, updated_at = %s "
            "where id = %s and status = 'blocked'",
            [admin_id, moment, moment, product_id],
        )
    )
