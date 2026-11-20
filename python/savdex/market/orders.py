"""
Заказ маркетплейса, этап 1 (ТЗ, разделы 7 и 8; docs/marketplace-security.md,
разделы 1, 3 и 5).

Оформление: корзина → пункт выдачи (пока только Ташкент) и способ оплаты
(картой на сайте или при получении) → один заказ покупателя с частями по
продавцам: деньги каждого продавца — в своей части.

- **Цена и остаток — только из базы**, в той же транзакции, что создаёт
  заказ. Браузер присылает сумму, которую видел (``expectedTotal``): не
  совпала — 409 и свежая корзина, а не заказ по новой цене. В позицию
  копируются цена, название, выбор, ИКПУ и процент комиссии на момент
  покупки.
- **Резерв** — одним условным обновлением на вариант, по возрастанию
  номера варианта (без взаимных блокировок); не обновилась хоть одна
  строка — откат всего заказа, «товар закончился».
- **Статусы** меняет только ``transition``: ``update … where status =
  ожидаемый``; ноль строк — статус уже сменил кто-то другой. Резерв
  снимается ровно один раз (``reserve_released_at``).
- **Журнал денег** (``market_ledger``) — двойная запись: каждое движение
  — группа строк с суммой ноль (``post``), только дописывается. Оплата
  при получении — начисление сразу при оформлении; картой — ничего, пока
  не пришли деньги (``mark_paid``, этап 2).

Отмена покупателем — только до отгрузки со склада (до ``in_transit``);
оплаченный картой заказ уходит в «ожидает возврата» (``refund_pending``),
сам возврат — этап 2 (``mark_refunded``). Неоплаченный картой заказ старше
N минут (настройка ``market_order_expire_minutes``, по умолчанию 30)
отменяется сам — ``expire`` (manage.py market_expire_orders и расписание).
"""

from __future__ import annotations

import json
import logging
import secrets
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from django.db import transaction

from savdex.market.catalog import VISIBLE
from savdex.market.common import now, one, rows, som, t, tiyin, write
from savdex.web.shared import public_url, settings_values

log = logging.getLogger("savdex.market.orders")

# ── Статусы ─────────────────────────────────────────────────────────

CREATED = "created"
PAID = "paid"
CASH_ON_PICKUP = "cash_on_pickup"
ASSEMBLING = "assembling"
IN_TRANSIT = "in_transit"
READY = "ready"
ISSUED = "issued"
CANCELLED = "cancelled"
REFUND_PENDING = "refund_pending"
REFUNDED = "refunded"

#: Статусы по-русски — для админки
STATUSES: dict[str, str] = {
    CREATED: "Оформлен, ждёт оплаты",
    PAID: "Оплачен картой",
    CASH_ON_PICKUP: "Оплата при получении",
    ASSEMBLING: "Собирается",
    IN_TRANSIT: "В пути в пункт выдачи",
    READY: "Можно забрать",
    ISSUED: "Выдан",
    CANCELLED: "Отменён",
    REFUND_PENDING: "Ждёт возврата денег",
    REFUNDED: "Деньги возвращены",
}

#: Из какого статуса → в какие. Перехода нет в таблице — TransitionError:
#: это ошибка в коде, а не ввод покупателя
TRANSITIONS: dict[str, frozenset[str]] = {
    CREATED: frozenset({PAID, CASH_ON_PICKUP, CANCELLED}),
    PAID: frozenset({ASSEMBLING, REFUND_PENDING}),
    CASH_ON_PICKUP: frozenset({ASSEMBLING, CANCELLED}),
    ASSEMBLING: frozenset({IN_TRANSIT, CANCELLED, REFUND_PENDING}),
    IN_TRANSIT: frozenset({READY}),
    # Невостребованный заказ и возврат из пункта — этап склада и ПВЗ
    READY: frozenset({ISSUED}),
    ISSUED: frozenset(),
    CANCELLED: frozenset(),
    REFUND_PENDING: frozenset({REFUNDED}),
    REFUNDED: frozenset(),
}

#: Покупатель отменяет сам — только до отгрузки со склада (ТЗ, раздел 7)
CANCELLABLE = frozenset({CREATED, PAID, CASH_ON_PICKUP, ASSEMBLING})

#: Продавцу не показываем неоплаченный картой заказ: собирать его рано
_SELLER_HIDDEN = (CREATED,)

#: Способы оплаты: картой на сайте (Uzum, этап 2) или при получении
METHODS = ("card", "cash")

#: Кто меняет статус (market_order_events.actor)
ACTORS = ("buyer", "seller", "staff", "system")

# ── Счета журнала денег ─────────────────────────────────────────────

#: Плюс — дебет, минус — кредит; каждая группа записей в сумме ноль.
#: Тот же список держит ограничение market_ledger_account_check
ACCOUNTS: dict[str, str] = {
    # Покупатель должен заплатить при получении (наличные или карта в ПВЗ)
    "buyer_receivable": "Покупатель должен (оплата при получении)",
    # Деньги картой — у Uzum, ещё не на нашем счёте (этап 2)
    "gateway_clearing": "Деньги у платёжной системы",
    # Наличные, принятые пунктом выдачи (этап кассы)
    "cash_collected": "Принято при получении",
    # Должны продавцу: сумма его части без комиссии (с seller_id)
    "seller_payable": "Должны продавцу",
    # Комиссия площадки
    "commission_revenue": "Комиссия площадки",
    # Должны вернуть покупателю (отмена оплаченного заказа)
    "refund_payable": "К возврату покупателю",
}

# ── Настройки ───────────────────────────────────────────────────────

#: Процент комиссии площадки — настройка в админке; копируется в позицию
COMMISSION_KEY = "market_commission_percent"
COMMISSION_DEFAULT = Decimal(10)

#: Через сколько минут неоплаченный картой заказ отменяется и резерв снимается
EXPIRE_KEY = "market_order_expire_minutes"
EXPIRE_DEFAULT = 30

#: Номер заказа: 10 знаков без похожих (0/O, 1/I) — около 10¹⁵ вариантов
_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
_NUMBER_LENGTH = 10


class TransitionError(ValueError):
    """Смена статуса, которой нет в TRANSITIONS: ошибка в коде."""


class OrderRefused(Exception):  # noqa: N818 — отказ покупателю, а не сбой
    """
    Отказ с текстом для покупателя: ключ словаря (market.<key>), код ответа,
    поле формы (для 422) и нужна ли в ответе свежая корзина (409).
    """

    def __init__(
        self, key: str, status: int, *, field: str | None = None, fresh_cart: bool = False
    ) -> None:
        super().__init__(key)
        self.key = key
        self.status = status
        self.field = field
        self.fresh_cart = fresh_cart


def commission_percent() -> Decimal:
    """
    Процент комиссии из настроек (ТЗ, раздел 8), по умолчанию 10. Не число,
    меньше нуля или больше ста — по умолчанию: опечатка в настройке не
    раздаст товары даром и не заберёт у продавца всё.
    """
    value = settings_values().get(COMMISSION_KEY)

    if value is None or isinstance(value, bool):
        return COMMISSION_DEFAULT

    try:
        number = Decimal(str(value).strip().replace(",", "."))
    except InvalidOperation:
        return COMMISSION_DEFAULT

    if not number.is_finite() or number < 0 or number > 100:
        return COMMISSION_DEFAULT

    return number.quantize(Decimal("0.01"))


def expire_minutes() -> int:
    """Сколько минут ждём оплаты картой; не число или меньше 5 — по умолчанию."""
    value = settings_values().get(EXPIRE_KEY)

    try:
        number = int(str(value))
    except (TypeError, ValueError):
        return EXPIRE_DEFAULT

    return number if number >= 5 else EXPIRE_DEFAULT


def commission_of(line_total: int, percent: Decimal) -> int:
    """Комиссия с суммы позиции — целыми тийинами, половина — вверх."""
    value = (Decimal(line_total) * percent / 100).quantize(Decimal(1), rounding=ROUND_HALF_UP)

    return min(int(value), line_total)


# ── Журнал денег ────────────────────────────────────────────────────


@dataclass(frozen=True)
class Entry:
    """Строка журнала денег: счёт, сумма в тийинах со знаком и к чему она."""

    account: str
    amount: int
    order_id: int | None = None
    part_id: int | None = None
    seller_id: int | None = None
    memo: str | None = None


def post(group: str | None, entries: Sequence[Entry]) -> str:
    """
    Записать движение денег: группа строк с суммой ноль. Возвращает номер
    группы (uuid). Сумма не ноль, пустая строка, неизвестный счёт —
    ValueError до записи; базу держит и триггер market_ledger_balanced
    (проверка в конце транзакции).
    """
    if not entries:
        raise ValueError("market_ledger: пустая группа")

    for entry in entries:
        if entry.account not in ACCOUNTS:
            raise ValueError(f"market_ledger: неизвестный счёт {entry.account}")

        if not isinstance(entry.amount, int) or isinstance(entry.amount, bool) or not entry.amount:
            raise ValueError(f"market_ledger: сумма {entry.amount!r} — нужны целые тийины, не 0")

    if sum(entry.amount for entry in entries) != 0:
        raise ValueError("market_ledger: группа не сходится в ноль")

    number = str(uuid.UUID(group)) if group else str(uuid.uuid4())
    moment = now()

    with transaction.atomic():
        for entry in entries:
            write(
                "insert into market_ledger (entry_group, account, order_id, part_id, seller_id, "
                "amount, memo, created_at) values (%s::uuid, %s, %s, %s, %s, %s, %s, %s)",
                [
                    number,
                    entry.account,
                    entry.order_id,
                    entry.part_id,
                    entry.seller_id,
                    entry.amount,
                    entry.memo,
                    moment,
                ],
            )

    return number


def _accrual(order_id: int, source: str, memo: str) -> list[Entry]:
    """
    Начисление по заказу: source (кто должен деньги) — плюс сумма заказа;
    каждому продавцу — минус его часть без комиссии, площадке — минус
    комиссия.
    """
    order = one("select total from market_orders where id = %s", [order_id])
    assert order is not None
    entries = [Entry(source, int(order["total"]), order_id=order_id, memo=memo)]

    for part in rows(
        "select id, seller_id, subtotal, commission from market_order_parts "
        "where order_id = %s order by id",
        [order_id],
    ):
        payable = int(part["subtotal"]) - int(part["commission"])
        refs = {"order_id": order_id, "part_id": part["id"], "seller_id": part["seller_id"]}

        if payable:
            entries.append(Entry("seller_payable", -payable, memo=memo, **refs))

        if part["commission"]:
            entries.append(Entry("commission_revenue", -int(part["commission"]), memo=memo, **refs))

    return entries


def _reversal(order_id: int, source: str, target: str, memo: str) -> list[Entry]:
    """Обратное начислению: продавцам и комиссии — назад, сумма заказа — на target."""
    return [
        Entry(
            target if entry.account == source else entry.account,
            -entry.amount,
            order_id=entry.order_id,
            part_id=entry.part_id,
            seller_id=entry.seller_id,
            memo=memo,
        )
        for entry in _accrual(order_id, source, memo)
    ]


# ── Переходы статуса и резерв ───────────────────────────────────────


def _event(
    order_id: int,
    before: str | None,
    after: str,
    actor: str,
    actor_user_id: int | None,
    note: str | None,
) -> None:
    write(
        "insert into market_order_events (order_id, from_status, to_status, actor, "
        "actor_user_id, note, created_at) values (%s, %s, %s, %s, %s, %s, %s)",
        [order_id, before, after, actor, actor_user_id, (note or "")[:500] or None, now()],
    )


def transition(
    order_id: int,
    before: str,
    after: str,
    *,
    actor: str,
    actor_user_id: int | None = None,
    note: str | None = None,
) -> bool:
    """
    Единственная смена статуса заказа (и его частей в том же статусе):
    ``update … where id = %s and status = before``. False — статус уже
    сменил кто-то другой (двойной щелчок, колбэк, расписание); ничего не
    записано. Строка истории — в той же транзакции.
    """
    if after not in TRANSITIONS.get(before, frozenset()) or actor not in ACTORS:
        log.error(
            "market.order.transition_refused id=%s %s→%s by %s", order_id, before, after, actor
        )

        raise TransitionError(f"заказ {order_id}: {before} → {after} ({actor}) запрещено")

    moment = now()
    sets = ["status = %s", "updated_at = %s"]
    params: list[Any] = [after, moment]

    if after == PAID:
        sets.append("paid_at = %s")
        params.append(moment)

    if after in (CANCELLED, REFUND_PENDING):
        sets += ["cancelled_at = %s", "cancel_reason = %s"]
        params += [moment, (note or "")[:500] or None]

    if after == ISSUED:
        sets.append("issued_at = %s")
        params.append(moment)

    with transaction.atomic():
        changed = write(
            f"update market_orders set {', '.join(sets)} where id = %s and status = %s",
            [*params, order_id, before],
        )

        if not changed:
            return False

        write(
            "update market_order_parts set status = %s, updated_at = %s "
            "where order_id = %s and status = %s",
            [after, moment, order_id, before],
        )
        _event(order_id, before, after, actor, actor_user_id, note)

    return True


def release_reserve(order_id: int) -> bool:
    """
    Снять резерв остатка заказа — ровно один раз: отметка
    ``reserve_released_at`` ставится условно, второй вызов ничего не делает.
    """
    with transaction.atomic():
        changed = write(
            "update market_orders set reserve_released_at = %s "
            "where id = %s and reserve_released_at is null",
            [now(), order_id],
        )

        if not changed:
            return False

        for item in rows(
            "select variant_id, quantity from market_order_items where order_id = %s "
            "order by variant_id",
            [order_id],
        ):
            released = write(
                "update market_product_variants set reserved = reserved - %s "
                "where id = %s and reserved >= %s",
                [item["quantity"], item["variant_id"], item["quantity"]],
            )

            if not released:
                # Резерв меньше заказанного — расхождение, но не повод держать заказ
                log.error(
                    "market.order.reserve_mismatch order=%s variant=%s",
                    order_id,
                    item["variant_id"],
                )

    return True


# ── Оформление ──────────────────────────────────────────────────────


def _new_number() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(_NUMBER_LENGTH))


def normalize_number(value: str) -> str:
    return value.strip().upper()


def _cart_lines(user_id: int) -> list[dict[str, Any]]:
    """
    Строки корзины с ценой и остатком из базы, под блокировкой строк
    корзины: второе оформление той же корзины ждёт первое и видит её уже
    пустой.
    """
    return rows(
        "select ci.variant_id, ci.quantity, v.product_id, v.price, v.options, v.is_active, "
        "v.stock - v.reserved as left_now, p.title, p.ikpu, p.seller_id, "
        f"({VISIBLE}) as on_sale "
        "from market_cart_items ci "
        "join market_product_variants v on v.id = ci.variant_id "
        "join market_products p on p.id = v.product_id "
        "join market_sellers s on s.id = p.seller_id "
        "join companies c on c.id = s.company_id "
        "where ci.user_id = %s order by ci.variant_id for update of ci",
        [user_id],
    )


def checkout(user_id: int, data: Mapping[str, Any]) -> str:
    """
    Оформить заказ из корзины: {pickupPoint: код пункта, paymentMethod:
    card | cash, expectedTotal: сумма в сумах, которую видел покупатель}.
    Возвращает номер заказа; отказ — OrderRefused.

    В заказ идёт то же, что корзина считает «можно купить сейчас»: товар в
    продаже, вариант включён, не больше остатка за вычетом резерва.
    Остальные строки остаются в корзине.
    """
    method = str(data.get("paymentMethod") or "")

    if method not in METHODS:
        raise OrderRefused("order.method", 422, field="paymentMethod")

    code = str(data.get("pickupPoint") or "").strip().lower()[:32]
    point = (
        one(
            "select id, name, address from market_pickup_points where code = %s and is_active",
            [code],
        )
        if code
        else None
    )

    if point is None:
        raise OrderRefused("order.pickup_point", 422, field="pickupPoint")

    expected = tiyin(data.get("expectedTotal"))

    if expected is None:
        raise OrderRefused("order.expected_total", 422, field="expectedTotal")

    percent = commission_percent()

    with transaction.atomic():
        lines = _cart_lines(user_id)

        if not lines:
            raise OrderRefused("order.cart_empty", 422)

        buyable: list[dict[str, Any]] = []

        for line in lines:
            on_sale = bool(line["on_sale"]) and bool(line["is_active"])
            take = min(int(line["quantity"]), max(0, int(line["left_now"]))) if on_sale else 0

            if take > 0:
                buyable.append({**line, "take": take})

        if not buyable:
            raise OrderRefused("cart.out_of_stock", 409, fresh_cart=True)

        total = sum(int(line["price"]) * int(line["take"]) for line in buyable)

        if total != expected:
            raise OrderRefused("order.total_changed", 409, fresh_cart=True)

        # Резерв — по возрастанию номера варианта, одним условным обновлением
        for line in sorted(buyable, key=lambda item: int(item["variant_id"])):
            reserved = write(
                "update market_product_variants set reserved = reserved + %s "
                "where id = %s and is_active and stock - reserved >= %s returning id",
                [line["take"], line["variant_id"], line["take"]],
            )

            if reserved is None:
                raise OrderRefused("cart.out_of_stock", 409, fresh_cart=True)

        parts: dict[int, list[dict[str, Any]]] = {}

        for line in buyable:
            line_total = int(line["price"]) * int(line["take"])
            line["line_total"] = line_total
            line["commission"] = commission_of(line_total, percent)
            parts.setdefault(int(line["seller_id"]), []).append(line)

        commission_total = sum(int(line["commission"]) for line in buyable)
        order_id, number = _insert_order(user_id, method, point, total, commission_total)

        for seller_id, items in parts.items():
            part_id = write(
                "insert into market_order_parts (order_id, seller_id, status, subtotal, "
                "commission, created_at, updated_at) values (%s, %s, %s, %s, %s, %s, %s) "
                "returning id",
                [
                    order_id,
                    seller_id,
                    CREATED,
                    sum(int(item["line_total"]) for item in items),
                    sum(int(item["commission"]) for item in items),
                    now(),
                    now(),
                ],
            )

            for item in items:
                write(
                    "insert into market_order_items (order_id, part_id, product_id, variant_id, "
                    "title, options, ikpu, price, quantity, line_total, commission_percent, "
                    "commission, created_at) "
                    "values (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s)",
                    [
                        order_id,
                        part_id,
                        item["product_id"],
                        item["variant_id"],
                        item["title"],
                        _json_text(item["options"]),
                        item["ikpu"],
                        item["price"],
                        item["take"],
                        item["line_total"],
                        percent,
                        item["commission"],
                        now(),
                    ],
                )

        _event(order_id, None, CREATED, "buyer", user_id, None)

        if method == "cash":
            transition(order_id, CREATED, CASH_ON_PICKUP, actor="buyer", actor_user_id=user_id)
            post(None, _accrual(order_id, "buyer_receivable", f"заказ {number}: при получении"))

        write(
            "delete from market_cart_items where user_id = %s and variant_id = any(%s)",
            [user_id, [int(line["variant_id"]) for line in buyable]],
        )

    log.info("market.order.created id=%s method=%s parts=%s", order_id, method, len(parts))

    return number


def _json_text(value: Any) -> str:  # noqa: ANN401
    return json.dumps(value if isinstance(value, dict) else {}, ensure_ascii=False)


def _insert_order(
    user_id: int, method: str, point: dict[str, Any], total: int, commission_total: int
) -> tuple[int, str]:
    """Строка заказа со случайным номером; совпал с чужим — другой номер."""
    moment = now()

    for _ in range(5):
        number = _new_number()
        order_id = write(
            "insert into market_orders (number, buyer_user_id, status, payment_method, "
            "pickup_point_id, pickup_point_name, pickup_point_address, items_total, "
            "delivery_total, total, commission_total, created_at, updated_at) "
            "values (%s, %s, %s, %s, %s, %s, %s, %s, 0, %s, %s, %s, %s) "
            "on conflict (number) do nothing returning id",
            [
                number,
                user_id,
                CREATED,
                method,
                point["id"],
                point["name"],
                point["address"],
                total,
                total,
                commission_total,
                moment,
                moment,
            ],
        )

        if order_id is not None:
            return int(order_id), number

    raise RuntimeError("market_orders: не удалось выбрать свободный номер")


# ── Отмена и истечение ──────────────────────────────────────────────


def cancel(user_id: int, number: str, reason: str | None = None) -> str:
    """
    Отмена покупателем — только своего заказа и только до отгрузки со
    склада. Оплаченный картой — в «ожидает возврата», остальные — в
    «отменён»; резерв снимается, начисление продавцам — назад. Возвращает
    новый статус; отказ — OrderRefused (чужой или нет — 404).
    """
    with transaction.atomic():
        order = one(
            "select id, number, status, payment_method, paid_at from market_orders "
            "where number = %s and buyer_user_id = %s for update",
            [normalize_number(number), user_id],
        )

        if order is None:
            raise OrderRefused("order.not_found", 404)

        status = str(order["status"])

        if status not in CANCELLABLE:
            raise OrderRefused("order.cannot_cancel", 409)

        paid = order["paid_at"] is not None
        target = REFUND_PENDING if paid else CANCELLED
        note = (reason or "").strip()[:500] or "отменён покупателем"

        if not transition(
            int(order["id"]), status, target, actor="buyer", actor_user_id=user_id, note=note
        ):
            raise OrderRefused("order.changed", 409)

        release_reserve(int(order["id"]))
        memo = f"заказ {order['number']}: отмена"

        if paid:
            post(None, _reversal(int(order["id"]), "gateway_clearing", "refund_payable", memo))
        elif order["payment_method"] == "cash":
            post(None, _reversal(int(order["id"]), "buyer_receivable", "buyer_receivable", memo))

    log.info("market.order.cancelled id=%s to=%s", order["id"], target)

    return target


def expire(minutes: int | None = None, moment: datetime | None = None) -> int:
    """
    Неоплаченные картой заказы старше N минут — отменить и снять резерв.
    Каждый — своей транзакцией и условным переходом: оплата, пришедшая
    одновременно, побеждает или проигрывает целиком. Возвращает, сколько
    отменено.
    """
    wait = minutes if minutes is not None else expire_minutes()
    cutoff = ((moment or datetime.now(UTC)) - timedelta(minutes=wait)).strftime("%Y-%m-%d %H:%M:%S")
    done = 0

    for order in rows(
        "select id from market_orders where status = %s and payment_method = 'card' "
        "and created_at < %s order by id limit 1000",
        [CREATED, cutoff],
    ):
        with transaction.atomic():
            if transition(
                int(order["id"]),
                CREATED,
                CANCELLED,
                actor="system",
                note=f"не оплачен за {wait} мин.",
            ):
                release_reserve(int(order["id"]))
                done += 1

    if done:
        log.info("market.order.expired count=%s", done)

    return done


# ── Деньги — для этапа 2 (Uzum) ─────────────────────────────────────


def mark_paid(order_id: int, amount: int, *, note: str | None = None) -> bool:
    """
    Оплата картой пришла (колбэк Uzum, этап 2): created → paid и начисление
    продавцам и комиссии. Сумма сверяется с заказом — не совпала, заказ не
    картой, уже оплачен или отменён по сроку — False, ничего не записано
    (опоздавшую оплату этап 2 возвращает).
    """
    with transaction.atomic():
        order = one(
            "select id, number, status, payment_method, total, reserve_released_at "
            "from market_orders where id = %s for update",
            [order_id],
        )

        if (
            order is None
            or order["payment_method"] != "card"
            or order["status"] != CREATED
            or order["reserve_released_at"] is not None
            or int(amount) != int(order["total"])
        ):
            return False

        if not transition(order_id, CREATED, PAID, actor="system", note=note):
            return False

        post(None, _accrual(order_id, "gateway_clearing", f"заказ {order['number']}: оплата"))

    return True


def mark_refunded(order_id: int, *, note: str | None = None) -> bool:
    """
    Деньги вернули покупателю (ответ Uzum на возврат, этап 2):
    refund_pending → refunded, долг покупателю закрыт деньгами платёжной
    системы. False — статус уже другой.
    """
    with transaction.atomic():
        order = one(
            "select id, number, total from market_orders where id = %s for update", [order_id]
        )

        if order is None or not transition(
            order_id, REFUND_PENDING, REFUNDED, actor="system", note=note
        ):
            return False

        memo = f"заказ {order['number']}: возврат"
        post(
            None,
            [
                Entry("refund_payable", int(order["total"]), order_id=order_id, memo=memo),
                Entry("gateway_clearing", -int(order["total"]), order_id=order_id, memo=memo),
            ],
        )

    return True


# ── Чтение ──────────────────────────────────────────────────────────


def _when(value: Any) -> str | None:  # noqa: ANN401
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")

    return str(value)


def _status(code: str, locale: str) -> dict[str, str]:
    return {"code": code, "text": t(f"order.status.{code}", locale)}


def pickup_points() -> list[dict[str, Any]]:
    """Пункты выдачи для оформления: только включённые."""
    return [
        {"code": r["code"], "name": r["name"], "address": r["address"], "city": r["city"]}
        for r in rows(
            "select code, name, address, city from market_pickup_points where is_active "
            "order by sort, name"
        )
    ]


def mine(user_id: int, locale: str) -> list[dict[str, Any]]:
    """Заказы покупателя — только свои, новые сверху."""
    return [
        {
            "number": r["number"],
            "status": _status(r["status"], locale),
            "paymentMethod": r["payment_method"],
            "total": som(r["total"]),
            "count": int(r["count"] or 0),
            "pickupPoint": {"name": r["pickup_point_name"], "address": r["pickup_point_address"]},
            "createdAt": _when(r["created_at"]),
        }
        for r in rows(
            "select o.number, o.status, o.payment_method, o.total, o.pickup_point_name, "
            "o.pickup_point_address, o.created_at, "
            "(select sum(i.quantity) from market_order_items i where i.order_id = o.id) as count "
            "from market_orders o where o.buyer_user_id = %s "
            "order by o.created_at desc, o.id desc limit 200",
            [user_id],
        )
    ]


def _items(where: str, params: list[Any], money: bool = True) -> dict[int, list[dict[str, Any]]]:
    """Позиции по частям заказа: part_id → строки."""
    found: dict[int, list[dict[str, Any]]] = {}

    for r in rows(
        "select i.part_id, i.variant_id, i.title, i.options, i.price, i.quantity, i.line_total, "
        "p.slug, (select coalesce(m.thumb_path, m.path) from market_product_images m "
        " where m.product_id = i.product_id and (m.variant_id is null or m.variant_id = "
        " i.variant_id) order by m.variant_id is null, m.sort, m.id limit 1) as cover "
        "from market_order_items i join market_products p on p.id = i.product_id "
        f"where {where} order by i.id",
        params,
    ):
        item: dict[str, Any] = {
            "variantId": r["variant_id"],
            "title": r["title"],
            "slug": r["slug"],
            "image": public_url(r["cover"]) if r["cover"] else None,
            "options": {k: v for k, v in (r["options"] or {}).items() if not k.startswith("_")},
            "quantity": int(r["quantity"]),
        }

        if money:
            item["price"] = som(r["price"])
            item["total"] = som(r["line_total"])

        found.setdefault(int(r["part_id"]), []).append(item)

    return found


def detail(user_id: int, number: str, locale: str) -> dict[str, Any] | None:
    """Заказ покупателя по номеру — только свой: чужой и несуществующий — None."""
    order = one(
        "select id, number, status, payment_method, items_total, delivery_total, total, "
        "pickup_point_name, pickup_point_address, created_at, paid_at, cancelled_at, issued_at "
        "from market_orders where number = %s and buyer_user_id = %s",
        [normalize_number(number), user_id],
    )

    if order is None:
        return None

    items = _items("i.order_id = %s", [order["id"]])
    parts = [
        {
            "seller": {"slug": p["slug"], "name": p["name"]},
            "status": _status(p["status"], locale),
            "total": som(p["subtotal"]),
            "items": items.get(int(p["id"]), []),
        }
        for p in rows(
            "select mp.id, mp.status, mp.subtotal, c.slug, c.name from market_order_parts mp "
            "join market_sellers s on s.id = mp.seller_id join companies c on c.id = s.company_id "
            "where mp.order_id = %s order by mp.id",
            [order["id"]],
        )
    ]

    return {
        "number": order["number"],
        "status": _status(order["status"], locale),
        "paymentMethod": order["payment_method"],
        "pickupPoint": {
            "name": order["pickup_point_name"],
            "address": order["pickup_point_address"],
        },
        "itemsTotal": som(order["items_total"]),
        "delivery": som(order["delivery_total"]),
        "total": som(order["total"]),
        "parts": parts,
        "canCancel": order["status"] in CANCELLABLE,
        "createdAt": _when(order["created_at"]),
        "paidAt": _when(order["paid_at"]),
        "cancelledAt": _when(order["cancelled_at"]),
        "issuedAt": _when(order["issued_at"]),
    }


def seller_orders(seller_id: int, locale: str) -> list[dict[str, Any]]:
    """
    Заказы продавца — только его части. О покупателе — имя и номер заказа;
    телефона, почты и адреса нет (ТЗ, раздел 10): заказ выдаёт пункт
    выдачи. Отдельный набор полей, а не «весь заказ».
    """
    found = rows(
        "select mp.id, mp.status, mp.subtotal, mp.commission, mp.created_at, o.number, "
        "o.pickup_point_name, u.name as buyer_name "
        "from market_order_parts mp "
        "join market_orders o on o.id = mp.order_id "
        "join users u on u.id = o.buyer_user_id "
        "where mp.seller_id = %s and mp.status <> all(%s) "
        "order by mp.created_at desc, mp.id desc limit 200",
        [seller_id, list(_SELLER_HIDDEN)],
    )

    if not found:
        return []

    items = _items("i.part_id = any(%s)", [[int(r["id"]) for r in found]])

    return [
        {
            "number": r["number"],
            "status": _status(r["status"], locale),
            "buyer": {"name": r["buyer_name"]},
            "pickupPoint": {"name": r["pickup_point_name"]},
            "total": som(r["subtotal"]),
            "commission": som(r["commission"]),
            "payout": som(int(r["subtotal"]) - int(r["commission"])),
            "items": items.get(int(r["id"]), []),
            "createdAt": _when(r["created_at"]),
        }
        for r in found
    ]
