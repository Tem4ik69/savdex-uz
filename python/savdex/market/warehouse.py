"""
Склад и пункты выдачи маркетплейса (ТЗ 18.11, разделы 6 и 11.3; решение
Тимура 23.11: свой интерфейс, BTS не ждём). Схема —
2026_11_23_100000_create_market_warehouse.sql (docs/marketplace.md, «Склад —
схема»).

- **Поставки.** Продавец в кабинете заводит заявку (что и сколько везёт, на
  какой склад), отправляет её или отменяет до приёмки. Склад принимает —
  по каждой строке сколько принято и сколько брака — или отказывает с
  причиной. Принятое попадает в остаток движением ``receipt``; брак — нет.
- **Движения.** Остаток склада меняется только движением
  (market_stock_movements): триггер базы в той же транзакции двигает и
  остаток склада, и ``stock`` варианта. Списание, вывоз продавцу и
  инвентаризация — тоже движения, с причиной; правки остатка руками нет.
- **Отгрузки** склад ↔ пункт выдачи: собирается → в пути → принята.
  В пункт едут собранные заказы этого пункта; принятая в пункте отгрузка
  ставит заказам «можно забрать», время прихода (``ready_at``) и код
  выдачи, покупателю — уведомление. Обратно, на склад, едут невостребованные.
- **Выдача по коду.** Код — 6 цифр, выводится из ключа приложения, номера
  заказа и времени прихода (HMAC): в базе — только его отпечаток
  (``pickup_code_hash``), покупатель видит код в своём заказе. Неверный код
  — счётчик попыток; после ``CODE_ATTEMPTS`` подряд — пауза
  ``CODE_LOCK_MINUTES`` минут (решение Тимура 23.11, ТЗ «Склад
  маркетплейса», №5); администратор может открыть ввод раньше
  (``unlock_code``);
  у сотрудника пункта — свой счётчик неверных кодов по всем заказам
  (``STAFF_WRONG_PER_HOUR`` в час, docs/marketplace-security.md, раздел 1).
  Выдача: резерв снят, движение ``issue``,
  кто выдал (``issued_by``).
- **Невостребованные.** Заказ, который не забрали за N дней после прихода
  (настройка ``market_unclaimed_days``, по умолчанию 7), закрывается сам:
  оплаченный картой — «ждёт возврата денег» (возврат делает расписание
  market_refunds), при получении — «отменён»; резерв снят, начисление
  продавцам — назад. Товар остаётся в остатке (он наш, просто лежит в
  пункте) и едет на склад отгрузкой ``to_warehouse``.

Кто где работает — market_warehouse_staff и market_pickup_point_staff:
сотрудник склада и пункта видит и отмечает только своё место;
администратор (market_orders.moderate) — все.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import DatabaseError, transaction

from savdex.market import orders, products
from savdex.market.common import now, one, rows, t, write
from savdex.web.shared import settings_values

log = logging.getLogger("savdex.market.warehouse")

# ── Статусы и виды ──────────────────────────────────────────────────

SUPPLY_STATUSES: dict[str, str] = {
    "draft": "Черновик",
    "submitted": "Отправлена на склад",
    "received": "Принята",
    "rejected": "Отказ склада",
    "cancelled": "Отменена продавцом",
}

SHIPMENT_STATUSES: dict[str, str] = {
    "assembling": "Собирается",
    "in_transit": "В пути",
    "delivered": "Принята",
    "cancelled": "Отменена",
}

DIRECTIONS: dict[str, str] = {
    "to_point": "Склад → пункт выдачи",
    "to_warehouse": "Пункт выдачи → склад (невостребованные)",
}

#: Движения: вид → (по-русски, знак: +1 только приход, -1 только расход, 0 — любой)
KINDS: dict[str, tuple[str, int]] = {
    "receipt": ("Приёмка поставки", 1),
    "customer_return": ("Возврат покупателя", 1),
    "issue": ("Выдача покупателю", -1),
    "writeoff": ("Списание", -1),
    "return_to_seller": ("Вывоз продавцу", -1),
    "adjust": ("Инвентаризация", 0),
}

#: Что сотрудник склада записывает руками — всегда с причиной
MANUAL_KINDS = ("writeoff", "return_to_seller", "adjust")

# ── Пределы ─────────────────────────────────────────────────────────

#: Строк в поставке и штук в строке (как у ограничения базы)
MAX_SUPPLY_LINES = 100
MAX_SUPPLY_QUANTITY = 100_000

#: Ожидаемая дата поставки — не дальше, чем через столько дней
MAX_EXPECTED_DAYS = 90

#: Причина отказа и движения — не отписка
MIN_REASON = 3
MIN_REJECT_REASON = 10

#: Неверных кодов выдачи подряд — и пауза на CODE_LOCK_MINUTES (раньше
#: может открыть администратор — unlock_code)
CODE_ATTEMPTS = 5
CODE_LOCK_MINUTES = 30
CODE_DIGITS = 6

#: Неверных кодов у одного сотрудника пункта за час — по всем заказам
STAFF_WRONG_PER_HOUR = 20

#: Через сколько дней после прихода в пункт заказ считается невостребованным
UNCLAIMED_KEY = "market_unclaimed_days"
UNCLAIMED_DEFAULT = 7


class WarehouseError(Exception):
    """Отказ сотруднику склада или пункта — текст по-русски для админки."""


def unclaimed_days() -> int:
    """Сколько дней заказ ждёт покупателя в пункте; не число или меньше 1 — по умолчанию."""
    value = settings_values().get(UNCLAIMED_KEY)

    try:
        number = int(str(value))
    except (TypeError, ValueError):
        return UNCLAIMED_DEFAULT

    return number if number >= 1 else UNCLAIMED_DEFAULT


# ── Кто где работает ────────────────────────────────────────────────


@dataclass(frozen=True)
class Places:
    """Где сотрудник работает: всё (администратор) или свои склады и пункты."""

    everything: bool
    warehouses: frozenset[int]
    points: frozenset[int]

    def warehouse(self, warehouse_id: int) -> bool:
        return self.everything or warehouse_id in self.warehouses

    def point(self, point_id: int) -> bool:
        return self.everything or point_id in self.points


def places_of(user_id: int, *, everything: bool = False) -> Places:
    """Склады и пункты сотрудника (market_warehouse_staff, market_pickup_point_staff)."""
    if everything:
        return Places(True, frozenset(), frozenset())

    return Places(
        False,
        frozenset(
            int(r["warehouse_id"])
            for r in rows(
                "select warehouse_id from market_warehouse_staff where user_id = %s", [user_id]
            )
        ),
        frozenset(
            int(r["pickup_point_id"])
            for r in rows(
                "select pickup_point_id from market_pickup_point_staff where user_id = %s",
                [user_id],
            )
        ),
    )


def set_staff(table: str, column: str, place_id: int, user_ids: Sequence[int]) -> None:
    """Кто работает на месте: лишних — убрать, новых — добавить (склад или пункт)."""
    if table not in ("market_warehouse_staff", "market_pickup_point_staff"):
        raise ValueError(table)

    wanted = sorted({int(uid) for uid in user_ids})

    with transaction.atomic():
        write(
            f"delete from {table} where {column} = %s and not (user_id = any(%s))",
            [place_id, wanted],
        )

        for uid in wanted:
            write(
                f"insert into {table} ({column}, user_id) values (%s, %s) on conflict do nothing",
                [place_id, uid],
            )


def staff_of(table: str, column: str, place_id: int) -> list[int]:
    if table not in ("market_warehouse_staff", "market_pickup_point_staff"):
        raise ValueError(table)

    return [
        int(r["user_id"])
        for r in rows(
            f"select user_id from {table} where {column} = %s order by user_id", [place_id]
        )
    ]


# ── Номера ──────────────────────────────────────────────────────────


def _new_number() -> str:
    return orders._new_number()


def _insert_numbered(query: str, params: list[Any]) -> tuple[int, str]:
    """Строка со случайным номером (первый параметр — номер); совпал — другой."""
    for _ in range(5):
        number = _new_number()
        found = write(query + " on conflict (number) do nothing returning id", [number, *params])

        if found is not None:
            return int(found), number

    raise RuntimeError("не удалось выбрать свободный номер")


# ── Движения остатка ────────────────────────────────────────────────


def _db_refused(error: DatabaseError) -> bool:
    """Отказ проверки базы (не в минус, ниже резерва, приёмка не совпала)."""
    code = getattr(getattr(error, "__cause__", None), "sqlstate", None)

    return code in ("23514", "23503", "23505")


def move(
    warehouse_id: int,
    variant_id: int,
    kind: str,
    quantity: int,
    *,
    actor_user_id: int | None,
    reason: str | None = None,
    order_id: int | None = None,
    supply_item_id: int | None = None,
) -> int:
    """
    Записать движение остатка. quantity — со знаком: плюс — пришло, минус —
    ушло. Остаток склада и варианта двигает триггер базы; сводка товара —
    здесь, заново. Строка товара блокируется раньше варианта (порядок
    блокировок — как у заказа). Не в минус, не ниже резерва — иначе
    WarehouseError, ничего не записано.
    """
    if kind not in KINDS:
        raise ValueError(f"неизвестное движение {kind}")

    sign = KINDS[kind][1]

    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity == 0:
        raise ValueError("количество — целое, не ноль")

    if sign and (quantity > 0) != (sign > 0):
        raise ValueError(f"{kind}: знак количества")

    variant = one("select product_id from market_product_variants where id = %s", [variant_id])

    if variant is None:
        raise WarehouseError("Такого варианта товара нет.")

    product_id = int(variant["product_id"])

    try:
        with transaction.atomic():
            orders._lock_products([product_id])
            movement = write(
                "insert into market_stock_movements (warehouse_id, variant_id, product_id, kind, "
                "quantity, supply_item_id, order_id, reason, actor_user_id, created_at) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning id",
                [
                    warehouse_id,
                    variant_id,
                    product_id,
                    kind,
                    quantity,
                    supply_item_id,
                    order_id,
                    (reason or "").strip()[:500] or None,
                    actor_user_id,
                    now(),
                ],
            )
            products.refresh(product_id)
    except DatabaseError as error:
        if not _db_refused(error):
            raise

        log.warning(
            "market.stock.move_refused warehouse=%s variant=%s kind=%s qty=%s",
            warehouse_id,
            variant_id,
            kind,
            quantity,
        )

        raise WarehouseError(
            "Движение не записано: на складе меньше, чем списывается, или товар отложен под заказы."
        ) from error

    return int(movement)


def manual_move(
    warehouse_id: int,
    variant_id: int,
    kind: str,
    quantity: int,
    reason: str,
    *,
    actor_user_id: int,
    confirmed: bool = False,
) -> int:
    """
    Списание, вывоз продавцу (quantity — сколько штук, положительное) и
    инвентаризация (± — на сколько поправить). Причина — обязательна.
    Списание — только с подтверждением администратора (``confirmed``;
    решение Тимура 23.11, №7): пока заявки на списание в схеме нет,
    списывает сам администратор.
    """
    if kind not in MANUAL_KINDS:
        raise WarehouseError("Руками — только списание, вывоз продавцу и инвентаризация.")

    if kind == "writeoff" and not confirmed:
        raise WarehouseError(
            "Списание подтверждает администратор маркетплейса: передайте ему, что и почему."
        )

    text = (reason or "").strip()

    if len(text) < MIN_REASON:
        raise WarehouseError("Напишите причину движения.")

    if not quantity:
        raise WarehouseError("Количество — не ноль.")

    if kind in ("writeoff", "return_to_seller"):
        if quantity < 0:
            raise WarehouseError("Сколько штук списать — положительным числом.")

        quantity = -quantity

    if abs(quantity) > MAX_SUPPLY_QUANTITY:
        raise WarehouseError(f"Не больше {MAX_SUPPLY_QUANTITY} шт. за раз.")

    return move(warehouse_id, variant_id, kind, quantity, actor_user_id=actor_user_id, reason=text)


def warehouse_stock(variant_id: int) -> list[dict[str, Any]]:
    """Остаток варианта по складам (для карточки товара)."""
    return rows(
        "select w.code, w.name, s.quantity from market_warehouse_stock s "
        "join market_warehouses w on w.id = s.warehouse_id "
        "where s.variant_id = %s order by w.sort, w.name",
        [variant_id],
    )


# ── Поставки: продавец ──────────────────────────────────────────────


def warehouses() -> list[dict[str, Any]]:
    """Склады, куда продавец может везти поставку: только включённые."""
    return [
        {"code": r["code"], "name": r["name"], "address": r["address"], "city": r["city"]}
        for r in rows(
            "select code, name, address, city from market_warehouses where is_active "
            "order by sort, name"
        )
    ]


def _count(value: Any) -> int | None:  # noqa: ANN401
    if isinstance(value, bool):
        return None

    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None

    return number


def _expected(value: Any) -> tuple[date | None, bool]:  # noqa: ANN401
    """Ожидаемая дата: (дата или None, верна ли). Пусто — без даты."""
    if value in (None, ""):
        return None, True

    try:
        day = date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None, False

    today = datetime.now(UTC).date()

    return day, today <= day <= today + timedelta(days=MAX_EXPECTED_DAYS)


def _lines(raw: Any) -> dict[int, int]:  # noqa: ANN401
    """Строки поставки из запроса: вариант → сколько. Ошибка — OrderRefused 422."""
    if not isinstance(raw, list) or not raw or len(raw) > MAX_SUPPLY_LINES:
        raise orders.OrderRefused(
            "supply.items", 422, field="items", replace={"max": MAX_SUPPLY_LINES}
        )

    lines: dict[int, int] = {}

    for item in raw:
        if not isinstance(item, Mapping):
            raise orders.OrderRefused(
                "supply.items", 422, field="items", replace={"max": MAX_SUPPLY_LINES}
            )

        variant = _count(item.get("variantId"))
        quantity = _count(item.get("quantity"))

        if variant is None or variant <= 0 or variant in lines:
            raise orders.OrderRefused("supply.variant", 422, field="items")

        if quantity is None or not 1 <= quantity <= MAX_SUPPLY_QUANTITY:
            raise orders.OrderRefused(
                "supply.quantity", 422, field="items", replace={"max": MAX_SUPPLY_QUANTITY}
            )

        lines[variant] = quantity

    return lines


def _own_variants(seller: Mapping[str, Any], lines: Mapping[int, int]) -> dict[int, int]:
    """Варианты — свои и не убранные: вариант → товар. Чужой — OrderRefused 422."""
    found = {
        int(r["id"]): int(r["product_id"])
        for r in rows(
            "select v.id, v.product_id from market_product_variants v "
            "join market_products p on p.id = v.product_id "
            "where v.id = any(%s) and p.seller_id = %s and not (v.options ? '_removed')",
            [sorted(lines), seller["id"]],
        )
    }

    if set(found) != set(lines):
        raise orders.OrderRefused("supply.variant", 422, field="items")

    return found


def supply_create(seller: Mapping[str, Any], user_id: int, data: Mapping[str, Any]) -> str:
    """
    Заявка на поставку (черновик): {warehouse: код склада, expectedAt?:
    ГГГГ-ММ-ДД, note?, items: [{variantId, quantity}]}. Только свои товары,
    вариант — не убранный; одна строка на вариант. Возвращает номер;
    отказ — OrderRefused (422 с полем).
    """
    code = str(data.get("warehouse") or "").strip().lower()[:32]
    place = (
        one("select id from market_warehouses where code = %s and is_active", [code])
        if code
        else None
    )

    if place is None:
        raise orders.OrderRefused("supply.warehouse", 422, field="warehouse")

    expected, valid = _expected(data.get("expectedAt"))

    if not valid:
        raise orders.OrderRefused("supply.expected", 422, field="expectedAt")

    lines = _lines(data.get("items"))
    found = _own_variants(seller, lines)

    note = str(data.get("note") or "").strip()[:1000] or None

    with transaction.atomic():
        supply_id, number = _insert_numbered(
            "insert into market_supplies (number, seller_id, warehouse_id, status, note, "
            "expected_at, created_by, created_at, updated_at) "
            "values (%s, %s, %s, 'draft', %s, %s, %s, %s, %s)",
            [seller["id"], place["id"], note, expected, user_id, now(), now()],
        )

        for variant_id, quantity in sorted(lines.items()):
            write(
                "insert into market_supply_items (supply_id, seller_id, product_id, variant_id, "
                "quantity_declared, created_at, updated_at) "
                "values (%s, %s, %s, %s, %s, %s, %s)",
                [supply_id, seller["id"], found[variant_id], variant_id, quantity, now(), now()],
            )

    log.info("market.supply.created id=%s lines=%s", supply_id, len(lines))

    return number


def supply_update(seller: Mapping[str, Any], number: str, data: Mapping[str, Any]) -> None:
    """
    Изменить поставку до приёмки (черновик или отправленную): ожидаемая
    дата, комментарий и строки {items: [{variantId, quantity}]}. Количество
    — меняется, новые варианты — добавляются; убрать строку нельзя (у роли
    сайта нет удаления строк поставки) — 422, отмените и заведите заново.
    """
    with transaction.atomic():
        found = _seller_supply(seller, number)

        if found["status"] not in ("draft", "submitted"):
            raise orders.OrderRefused("supply.changed", 409)

        expected, valid = _expected(data.get("expectedAt"))

        if not valid:
            raise orders.OrderRefused("supply.expected", 422, field="expectedAt")

        lines = _lines(data.get("items"))
        products_of = _own_variants(seller, lines)
        current = {
            int(r["variant_id"]): int(r["id"])
            for r in rows(
                "select id, variant_id from market_supply_items where supply_id = %s",
                [found["id"]],
            )
        }

        if set(current) - set(lines):
            raise orders.OrderRefused("supply.cannot_remove", 422, field="items")

        for variant_id, quantity in sorted(lines.items()):
            if variant_id in current:
                write(
                    "update market_supply_items set quantity_declared = %s, updated_at = %s "
                    "where id = %s",
                    [quantity, now(), current[variant_id]],
                )
            else:
                write(
                    "insert into market_supply_items (supply_id, seller_id, product_id, "
                    "variant_id, quantity_declared, created_at, updated_at) "
                    "values (%s, %s, %s, %s, %s, %s, %s)",
                    [
                        found["id"],
                        seller["id"],
                        products_of[variant_id],
                        variant_id,
                        quantity,
                        now(),
                        now(),
                    ],
                )

        write(
            "update market_supplies set expected_at = %s, note = %s, updated_at = %s where id = %s",
            [expected, str(data.get("note") or "").strip()[:1000] or None, now(), found["id"]],
        )


def _seller_supply(seller: Mapping[str, Any], number: str) -> dict[str, Any]:
    found = one(
        "select id, status from market_supplies where number = %s and seller_id = %s for update",
        [orders.normalize_number(number), seller["id"]],
    )

    if found is None:
        raise orders.OrderRefused("supply.not_found", 404)

    return found


def supply_submit(seller: Mapping[str, Any], number: str) -> None:
    """Черновик → отправлена на склад. Иначе — 409."""
    with transaction.atomic():
        found = _seller_supply(seller, number)

        if found["status"] != "draft" or not write(
            "update market_supplies set status = 'submitted', submitted_at = %s, updated_at = %s "
            "where id = %s and status = 'draft'",
            [now(), now(), found["id"]],
        ):
            raise orders.OrderRefused("supply.changed", 409)


def supply_cancel(seller: Mapping[str, Any], number: str) -> None:
    """Отменить заявку — до приёмки (черновик или отправленную)."""
    with transaction.atomic():
        found = _seller_supply(seller, number)

        if found["status"] not in ("draft", "submitted") or not write(
            "update market_supplies set status = 'cancelled', cancelled_at = %s, updated_at = %s "
            "where id = %s and status in ('draft', 'submitted')",
            [now(), now(), found["id"]],
        ):
            raise orders.OrderRefused("supply.changed", 409)


def _when(value: Any) -> str | None:  # noqa: ANN401
    return orders._when(value)


def _supply_items(supply_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    found: dict[int, list[dict[str, Any]]] = {}

    for r in rows(
        "select i.supply_id, i.variant_id, i.quantity_declared, i.quantity_accepted, "
        "i.quantity_defect, p.title, v.options from market_supply_items i "
        "join market_products p on p.id = i.product_id "
        "join market_product_variants v on v.id = i.variant_id "
        "where i.supply_id = any(%s) order by i.id",
        [supply_ids],
    ):
        found.setdefault(int(r["supply_id"]), []).append(
            {
                "variantId": r["variant_id"],
                "title": r["title"],
                "options": {
                    k: v for k, v in (r["options"] or {}).items() if not str(k).startswith("_")
                },
                "declared": int(r["quantity_declared"]),
                "accepted": r["quantity_accepted"],
                "defect": r["quantity_defect"],
            }
        )

    return found


def supplies_of(seller: Mapping[str, Any], locale: str) -> list[dict[str, Any]]:
    """Поставки продавца — только свои, новые сверху."""
    found = rows(
        "select s.id, s.number, s.status, s.note, s.expected_at, s.created_at, s.submitted_at, "
        "s.received_at, s.cancelled_at, s.rejected_at, s.reject_reason, "
        "w.code, w.name, w.address from market_supplies s "
        "join market_warehouses w on w.id = s.warehouse_id "
        "where s.seller_id = %s order by s.created_at desc, s.id desc limit 200",
        [seller["id"]],
    )
    items = _supply_items([int(r["id"]) for r in found]) if found else {}

    return [
        {
            "number": r["number"],
            "status": {"code": r["status"], "text": t(f"supply.status.{r['status']}", locale)},
            "warehouse": {"code": r["code"], "name": r["name"], "address": r["address"]},
            "note": r["note"],
            "expectedAt": r["expected_at"].isoformat() if r["expected_at"] else None,
            "rejectReason": r["reject_reason"],
            "items": items.get(int(r["id"]), []),
            "canSubmit": r["status"] == "draft",
            "canCancel": r["status"] in ("draft", "submitted"),
            "createdAt": _when(r["created_at"]),
            "submittedAt": _when(r["submitted_at"]),
            "receivedAt": _when(r["received_at"]),
            "cancelledAt": _when(r["cancelled_at"]),
            "rejectedAt": _when(r["rejected_at"]),
        }
        for r in found
    ]


def supply_detail(seller: Mapping[str, Any], number: str, locale: str) -> dict[str, Any] | None:
    clean = orders.normalize_number(number)

    return next(
        (supply for supply in supplies_of(seller, locale) if supply["number"] == clean), None
    )


# ── Поставки: склад ─────────────────────────────────────────────────


def supply_receive(
    supply_id: int, counts: Mapping[int, tuple[int, int]], *, actor_user_id: int
) -> int:
    """
    Приёмка отправленной поставки: по каждой строке (id строки → (принято,
    брак)). Принято и брак — не меньше нуля; принимаем факт, даже если
    пришло больше или меньше заявленного (решение Тимура 23.11, №2) —
    расхождение продавец видит в поставке.
    Строки, принятое — движением receipt на склад поставки. Возвращает,
    сколько штук принято. Отказ — WarehouseError, ничего не записано.
    """
    with transaction.atomic():
        supply = one(
            "select id, number, status, warehouse_id from market_supplies where id = %s for update",
            [supply_id],
        )

        if supply is None or supply["status"] != "submitted":
            raise WarehouseError("Поставка уже не ждёт приёмки — обновите страницу.")

        items = rows(
            "select id, variant_id, quantity_declared from market_supply_items "
            "where supply_id = %s order by id",
            [supply_id],
        )

        if set(counts) != {int(item["id"]) for item in items}:
            raise WarehouseError("Укажите принятое и брак по каждой строке поставки.")

        for item in items:
            accepted, defect = counts[int(item["id"])]

            if accepted < 0 or defect < 0:
                raise WarehouseError("Принято и брак — не меньше нуля.")

            if accepted > MAX_SUPPLY_QUANTITY or defect > MAX_SUPPLY_QUANTITY:
                raise WarehouseError(f"Не больше {MAX_SUPPLY_QUANTITY} шт. в строке.")

        for item in items:
            accepted, defect = counts[int(item["id"])]
            write(
                "update market_supply_items set quantity_accepted = %s, quantity_defect = %s, "
                "updated_at = %s where id = %s",
                [accepted, defect, now(), item["id"]],
            )

        write(
            "update market_supplies set status = 'received', received_at = %s, received_by = %s, "
            "updated_at = %s where id = %s and status = 'submitted'",
            [now(), actor_user_id, now(), supply_id],
        )
        total = 0

        for item in items:
            accepted = counts[int(item["id"])][0]

            if accepted:
                move(
                    int(supply["warehouse_id"]),
                    int(item["variant_id"]),
                    "receipt",
                    accepted,
                    actor_user_id=actor_user_id,
                    supply_item_id=int(item["id"]),
                )
                total += accepted

    log.info("market.supply.received id=%s accepted=%s", supply_id, total)

    return total


def supply_reject(supply_id: int, reason: str, *, actor_user_id: int) -> None:
    """Отказ склада по отправленной поставке — с причиной (её увидит продавец)."""
    text = (reason or "").strip()

    if len(text) < MIN_REJECT_REASON:
        raise WarehouseError(f"Напишите причину — не короче {MIN_REJECT_REASON} знаков.")

    if not write(
        "update market_supplies set status = 'rejected', rejected_at = %s, reject_reason = %s, "
        "updated_at = %s where id = %s and status = 'submitted'",
        [now(), text[:1000], now(), supply_id],
    ):
        raise WarehouseError("Поставка уже не ждёт приёмки — обновите страницу.")

    log.info("market.supply.rejected id=%s by=%s", supply_id, actor_user_id)


# ── Отгрузки склад ↔ пункт ──────────────────────────────────────────

#: Невостребованный заказ: был в пункте, не выдан, закрыт
_RETURNABLE = (orders.CANCELLED, orders.REFUND_PENDING, orders.REFUNDED)


def _candidates(warehouse_id: int, point_id: int, direction: str) -> list[int]:
    """Заказы, которые сейчас можно положить в отгрузку."""
    if direction == "to_point":
        # Собранные заказы пункта, ещё не ехавшие туда; каждый товар есть
        # на этом складе в нужном количестве
        return [
            int(r["id"])
            for r in rows(
                "select o.id from market_orders o where o.pickup_point_id = %s "
                "and o.status = %s and not exists (select from market_shipment_orders so "
                " where so.order_id = o.id and so.direction = 'to_point') "
                "and not exists (select from market_order_items i where i.order_id = o.id "
                " and coalesce((select s.quantity from market_warehouse_stock s "
                "  where s.warehouse_id = %s and s.variant_id = i.variant_id), 0) < i.quantity) "
                "order by o.id",
                [point_id, orders.ASSEMBLING, warehouse_id],
            )
        ]

    return [
        int(r["id"])
        for r in rows(
            "select o.id from market_orders o where o.pickup_point_id = %s "
            "and o.status = any(%s) and o.ready_at is not null and o.issued_at is null "
            "and exists (select from market_shipment_orders so join market_shipments sh "
            " on sh.id = so.shipment_id where so.order_id = o.id and so.direction = 'to_point' "
            " and sh.status = 'delivered' and sh.warehouse_id = %s) "
            "and not exists (select from market_shipment_orders so "
            " where so.order_id = o.id and so.direction = 'to_warehouse') "
            "order by o.id",
            [point_id, list(_RETURNABLE), warehouse_id],
        )
    ]


def shipment_create(
    warehouse_id: int, point_id: int, direction: str, *, actor_user_id: int
) -> tuple[int, str, int]:
    """
    Новая отгрузка со всеми заказами, которые сейчас можно отправить
    (_candidates). Нечего отправлять — WarehouseError. Возвращает (id,
    номер, сколько заказов).
    """
    if direction not in DIRECTIONS:
        raise WarehouseError("Неизвестное направление отгрузки.")

    with transaction.atomic():
        # Две отгрузки в одно время не делят заказы: блокировка пункта
        if one("select id from market_pickup_points where id = %s for update", [point_id]) is None:
            raise WarehouseError("Такого пункта выдачи нет.")

        if one("select id from market_warehouses where id = %s", [warehouse_id]) is None:
            raise WarehouseError("Такого склада нет.")

        found = _candidates(warehouse_id, point_id, direction)

        if not found:
            raise WarehouseError(
                "Отправлять нечего: нет собранных заказов этого пункта с товаром на складе."
                if direction == "to_point"
                else "Отправлять нечего: невостребованных заказов в пункте нет."
            )

        shipment_id, number = _insert_numbered(
            "insert into market_shipments (number, warehouse_id, pickup_point_id, direction, "
            "status, created_by, created_at, updated_at) "
            "values (%s, %s, %s, %s, 'assembling', %s, %s, %s)",
            [warehouse_id, point_id, direction, actor_user_id, now(), now()],
        )

        for order_id in found:
            write(
                "insert into market_shipment_orders (shipment_id, order_id, direction, "
                "pickup_point_id, created_at) values (%s, %s, %s, %s, %s)",
                [shipment_id, order_id, direction, point_id, now()],
            )

    log.info("market.shipment.created id=%s orders=%s %s", shipment_id, len(found), direction)

    return shipment_id, number, len(found)


def _shipment(shipment_id: int) -> dict[str, Any]:
    found = one(
        "select id, number, warehouse_id, pickup_point_id, direction, status "
        "from market_shipments where id = %s for update",
        [shipment_id],
    )

    if found is None:
        raise WarehouseError("Такой отгрузки нет.")

    return found


def shipment_orders(shipment_id: int) -> list[dict[str, Any]]:
    return rows(
        "select o.id, o.number, o.status, o.payment_method, o.pickup_point_name "
        "from market_shipment_orders so join market_orders o on o.id = so.order_id "
        "where so.shipment_id = %s order by o.id",
        [shipment_id],
    )


def shipment_remove(shipment_id: int, order_id: int) -> None:
    """Убрать заказ из собираемой отгрузки (он поедет следующей)."""
    with transaction.atomic():
        if _shipment(shipment_id)["status"] != "assembling":
            raise WarehouseError("Отгрузка уже уехала — состав не меняется.")

        if not write(
            "delete from market_shipment_orders where shipment_id = %s and order_id = %s",
            [shipment_id, order_id],
        ):
            raise WarehouseError("Этого заказа в отгрузке уже нет.")


def shipment_cancel(shipment_id: int, *, actor_user_id: int) -> None:
    """Отменить собираемую отгрузку: заказы свободны для следующей."""
    with transaction.atomic():
        if not write(
            "update market_shipments set status = 'cancelled', cancelled_at = %s, updated_at = %s "
            "where id = %s and status = 'assembling'",
            [now(), now(), shipment_id],
        ):
            raise WarehouseError("Отгрузка уже уехала или отменена — обновите страницу.")

        write("delete from market_shipment_orders where shipment_id = %s", [shipment_id])

    log.info("market.shipment.cancelled id=%s by=%s", shipment_id, actor_user_id)


def shipment_ship(shipment_id: int, *, actor_user_id: int) -> int:
    """
    Отгрузка уехала. В пункт: каждый заказ «собирается» → «в пути»; заказ,
    который тем временем отменили, из отгрузки убирается. Пусто — отказ.
    Возвращает, сколько заказов уехало.
    """
    with transaction.atomic():
        shipment = _shipment(shipment_id)

        if shipment["status"] != "assembling":
            raise WarehouseError("Отгрузка уже уехала или отменена — обновите страницу.")

        moved = 0

        for order in shipment_orders(shipment_id):
            if shipment["direction"] == "to_point":
                ok = order["status"] == orders.ASSEMBLING and orders.transition(
                    int(order["id"]),
                    orders.ASSEMBLING,
                    orders.IN_TRANSIT,
                    actor="staff",
                    actor_user_id=actor_user_id,
                    note=f"отгрузка {shipment['number']}",
                )
            else:
                ok = order["status"] in _RETURNABLE

                if ok:
                    orders.note(
                        int(order["id"]),
                        f"отгрузка {shipment['number']}: едет на склад",
                        actor="staff",
                        actor_user_id=actor_user_id,
                    )

            if ok:
                moved += 1
            else:
                write(
                    "delete from market_shipment_orders where shipment_id = %s and order_id = %s",
                    [shipment_id, order["id"]],
                )

        if not moved:
            raise WarehouseError("В отгрузке не осталось заказов, которые можно отправить.")

        write(
            "update market_shipments set status = 'in_transit', shipped_at = %s, shipped_by = %s, "
            "updated_at = %s where id = %s and status = 'assembling'",
            [now(), actor_user_id, now(), shipment_id],
        )

    log.info("market.shipment.shipped id=%s orders=%s", shipment_id, moved)

    return moved


def shipment_deliver(shipment_id: int, *, actor_user_id: int) -> int:
    """
    Отгрузку приняли на месте. В пункт: заказы «в пути» → «можно забрать»,
    время прихода, код выдачи, уведомление покупателю. На склад — пометка
    в истории заказа. Возвращает, сколько заказов принято.
    """
    ready: list[int] = []

    with transaction.atomic():
        shipment = _shipment(shipment_id)

        if shipment["status"] != "in_transit" or not write(
            "update market_shipments set status = 'delivered', delivered_at = %s, "
            "delivered_by = %s, updated_at = %s where id = %s and status = 'in_transit'",
            [now(), actor_user_id, now(), shipment_id],
        ):
            raise WarehouseError("Отгрузка не в пути — обновите страницу.")

        for order in shipment_orders(shipment_id):
            order_id = int(order["id"])

            if shipment["direction"] == "to_warehouse":
                orders.note(
                    order_id,
                    f"отгрузка {shipment['number']}: товар вернулся на склад",
                    actor="staff",
                    actor_user_id=actor_user_id,
                )
                ready.append(order_id)

                continue

            if orders.transition(
                order_id,
                orders.IN_TRANSIT,
                orders.READY,
                actor="staff",
                actor_user_id=actor_user_id,
                note=f"отгрузка {shipment['number']}",
            ):
                moment = now()
                write(
                    "update market_orders set ready_at = %s, pickup_code_hash = %s, "
                    "pickup_code_attempts = 0, pickup_code_locked_until = null where id = %s",
                    [moment, _code_hash(order_id, pickup_code(order_id, moment)), order_id],
                )
                ready.append(order_id)

    if shipment["direction"] == "to_point":
        for order_id in ready:
            _notify_ready(order_id)

    log.info("market.shipment.delivered id=%s orders=%s", shipment_id, len(ready))

    return len(ready)


# ── Код выдачи ──────────────────────────────────────────────────────


def _key() -> bytes:
    return f"market-pickup|{settings.SECRET_KEY}".encode()


def pickup_code(order_id: int, ready_at: Any) -> str:  # noqa: ANN401
    """Код выдачи: 6 цифр из ключа приложения, номера заказа и времени прихода."""
    digest = hmac.new(
        _key(), f"code|{order_id}|{_stamp(ready_at)}".encode(), hashlib.sha256
    ).digest()

    return str(int.from_bytes(digest[:8], "big") % 10**CODE_DIGITS).zfill(CODE_DIGITS)


def _code_hash(order_id: int, code: str) -> str:
    """Отпечаток кода в базе: без ключа приложения перебором не восстановить."""
    return hmac.new(_key(), f"hash|{order_id}|{code}".encode(), hashlib.sha256).hexdigest()


def code_of(order: Mapping[str, Any]) -> str | None:
    """Код выдачи заказа для покупателя — только пока «можно забрать»."""
    if order.get("status") != orders.READY or order.get("ready_at") is None:
        return None

    return pickup_code(int(order["id"]), order["ready_at"])


def pickup_until(order: Mapping[str, Any]) -> datetime | None:
    """
    До какого момента заказ ждёт покупателя в пункте (время прихода плюс
    market_unclaimed_days) — только пока «можно забрать»; позже его
    закрывает expire_unclaimed.
    """
    ready = order.get("ready_at")

    if order.get("status") != orders.READY or not isinstance(ready, datetime):
        return None

    return ready + timedelta(days=unclaimed_days())


def _until_text(ready: datetime) -> str:
    """Срок «заберите до» для уведомления: «30.11» по времени Ташкента — понятно на любом языке."""
    moment = ready if ready.tzinfo else ready.replace(tzinfo=UTC)
    until = moment + timedelta(days=unclaimed_days())

    return until.astimezone(ZoneInfo("Asia/Tashkent")).strftime("%d.%m")


def _stamp(value: Any) -> str:  # noqa: ANN401
    """Время прихода тем же видом, каким его пишет now(): «ГГГГ-ММ-ДД ЧЧ:ММ:СС»."""
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(UTC)

        return str(value.strftime("%Y-%m-%d %H:%M:%S"))

    return str(value)


_DIGITS = re.compile(r"\D")


def issue(order_id: int, code: str, *, actor_user_id: int) -> str:
    """
    Выдать заказ по коду. Возвращает: ``issued`` — выдан; ``wrong`` — код
    неверный (попытка засчитана); ``locked`` — ввод по заказу закрыт после
    неверных попыток; ``staff_limit`` — у сотрудника слишком много неверных
    кодов за час; ``changed`` — заказ уже не ждёт выдачи. Неверная попытка
    записывается и тогда, когда выдачи нет. Остатка не хватило —
    orders.WriteOffError (всё откатано).
    """
    entered = _DIGITS.sub("", code or "")[: CODE_DIGITS + 2]
    staff_key = f"market-pickup-code|{actor_user_id}"

    if _staff_throttled(staff_key):
        return "staff_limit"

    with transaction.atomic():
        order = one(
            "select id, status, ready_at, pickup_code_hash, pickup_code_attempts, "
            "pickup_code_locked_until > %s as locked from market_orders where id = %s for update",
            [now(), order_id],
        )

        if order is None or order["status"] != orders.READY or not order["pickup_code_hash"]:
            return "changed"

        if order["locked"]:
            return "locked"

        if not hmac.compare_digest(_code_hash(order_id, entered), str(order["pickup_code_hash"])):
            _staff_missed(staff_key)
            attempts = int(order["pickup_code_attempts"]) + 1

            if attempts >= CODE_ATTEMPTS:
                until = (datetime.now(UTC) + timedelta(minutes=CODE_LOCK_MINUTES)).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                # Счётчик — с нуля: после паузы снова CODE_ATTEMPTS попыток
                write(
                    "update market_orders set pickup_code_attempts = 0, "
                    "pickup_code_locked_until = %s where id = %s",
                    [until, order_id],
                )
                log.warning("market.pickup.locked order=%s by=%s", order_id, actor_user_id)

                return "locked"

            write(
                "update market_orders set pickup_code_attempts = %s where id = %s",
                [attempts, order_id],
            )

            return "wrong"

        warehouse_id = _issue_warehouse(order_id)

        if not orders.issue(order_id, warehouse_id, actor_user_id=actor_user_id):
            return "changed"

    log.info("market.pickup.issued order=%s by=%s", order_id, actor_user_id)

    return "issued"


def code_locked(order: Any) -> bool:  # noqa: ANN401
    """Ввод кода по заказу закрыт (модель Order или строка с pickup_code_locked_until)."""
    until = (
        order.get("pickup_code_locked_until")
        if isinstance(order, Mapping)
        else getattr(order, "pickup_code_locked_until", None)
    )

    if until is None:
        return False

    return _stamp(until) > now()


def unlock_code(order_id: int, *, actor_user_id: int) -> bool:
    """
    Открыть ввод кода после звонка покупателю (администратор): счётчик —
    ноль, блокировки нет. False — заказ не ждёт выдачи или не закрыт.
    """
    done = bool(
        write(
            "update market_orders set pickup_code_attempts = 0, "
            "pickup_code_locked_until = null where id = %s and status = %s "
            "and pickup_code_locked_until is not null",
            [order_id, orders.READY],
        )
    )

    if done:
        log.info("market.pickup.unlocked order=%s by=%s", order_id, actor_user_id)

    return done


def _staff_throttled(key: str) -> bool:
    """У сотрудника пункта предел неверных кодов за час исчерпан (кэш площадки)."""
    from savdex import laravel_cache
    from savdex.web import throttle

    return laravel_cache.is_file_store() and throttle.too_many(key, STAFF_WRONG_PER_HOUR)


def _staff_missed(key: str) -> None:
    from savdex import laravel_cache
    from savdex.web import throttle

    if laravel_cache.is_file_store():
        throttle.hit(key, 3600)


def refuse(order_id: int, *, actor_user_id: int) -> str | None:
    """
    Покупатель отказался от заказа в пункте (целиком — частичной выдачи нет,
    ТЗ «Склад маркетплейса», раздел 7): картой — к возврату денег, при
    получении — отменён; резерв снят, начисление — назад. Товар едет на
    склад отгрузкой «невостребованные». Новый статус или None — заказ уже
    не ждёт выдачи.
    """
    with transaction.atomic():
        order = one(
            f"select {orders._CLOSE_FIELDS} from market_orders "
            "where id = %s and status = %s for update",
            [order_id, orders.READY],
        )

        if order is None:
            return None

        target = orders.REFUND_PENDING if order["paid_at"] is not None else orders.CANCELLED

        if not orders._close(
            order, target, actor="staff", actor_user_id=actor_user_id, note="отказ при получении"
        ):
            return None

    log.info("market.pickup.refused order=%s by=%s", order_id, actor_user_id)

    return target


def _issue_warehouse(order_id: int) -> int:
    """Склад, с которого заказ приехал в пункт (принятая отгрузка to_point)."""
    found = one(
        "select sh.warehouse_id from market_shipment_orders so "
        "join market_shipments sh on sh.id = so.shipment_id "
        "where so.order_id = %s and so.direction = 'to_point' and sh.status = 'delivered'",
        [order_id],
    )

    if found is None:
        raise orders.WriteOffError(f"заказ {order_id}: не пришёл в пункт отгрузкой")

    return int(found["warehouse_id"])


# ── Уведомление «можно забрать» ─────────────────────────────────────


def _notify_ready(order_id: int) -> None:
    """
    Покупателю — в ленту кабинета на его языке: заказ в пункте, адрес и
    часы. Самого кода в уведомлении нет (он не хранится нигде открытым):
    покупатель видит его в своём заказе. Сбой уведомления — в журнал,
    выдача не падает.
    """
    from savdex.market import domain
    from savdex.moderation.services import notify_user

    found = one(
        "select o.number, o.buyer_user_id, o.pickup_point_name, o.pickup_point_address, "
        "o.ready_at, p.hours, u.locale from market_orders o join users u on u.id = o.buyer_user_id "
        "join market_pickup_points p on p.id = o.pickup_point_id where o.id = %s",
        [order_id],
    )

    if found is None:
        return

    locale = str(found["locale"] or "ru")
    days = unclaimed_days()
    url = domain.market_url(f"/orders/{found['number']}") or f"/market/orders/{found['number']}"

    # Своя точка сохранения: сбой записи уведомления не ломает транзакцию
    # приёмки отгрузки, внутри которой его могут позвать
    try:
        with transaction.atomic():
            notify_user(
                int(found["buyer_user_id"]),
                "market",
                t("notify.order_ready_title", locale, number=found["number"]),
                "success",
                url[:255],
                t(
                    "notify.order_ready_body",
                    locale,
                    point=found["pickup_point_name"],
                    address=found["pickup_point_address"],
                    hours=found["hours"] or "—",
                    days=days,
                    until=_until_text(found["ready_at"])
                    if isinstance(found["ready_at"], datetime)
                    else "—",
                ),
            )
    except Exception:
        log.exception("market.pickup.notify_failed order=%s", order_id)


# ── Невостребованные ────────────────────────────────────────────────


def expire_unclaimed(days: int | None = None, moment: datetime | None = None) -> int:
    """
    Заказы «можно забрать», пришедшие в пункт больше N дней назад, —
    закрыть: картой — «ждёт возврата денег», при получении — «отменён»;
    резерв снять, начисление продавцам — назад (тот же путь, что отмена,
    orders._close). Каждый — своей транзакцией, под блокировкой и условным
    переходом: выдача в ту же секунду побеждает или проигрывает целиком.
    Возвращает, сколько закрыто.
    """
    wait = days if days is not None else unclaimed_days()
    cutoff = orders._cutoff(moment, timedelta(days=wait))
    note = f"не забран за {wait} дн."
    done = 0

    for found in rows(
        "select id from market_orders where status = %s and ready_at < %s order by id limit 1000",
        [orders.READY, cutoff],
    ):
        with transaction.atomic():
            order = one(
                f"select {orders._CLOSE_FIELDS} from market_orders "
                "where id = %s and status = %s for update",
                [found["id"], orders.READY],
            )

            if order is None:
                continue

            target = orders.REFUND_PENDING if order["paid_at"] is not None else orders.CANCELLED

            if orders._close(order, target, actor="system", note=note):
                done += 1

    if done:
        log.info("market.order.unclaimed count=%s", done)

    return done
