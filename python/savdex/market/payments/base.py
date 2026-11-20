"""
Общий слой оплаты маркетплейса: настройки, протокол провайдера, строки
``market_payments``, проведение и возврат (docs/marketplace-security.md,
раздел 3; docs/marketplace.md, «Оплата — этап 2»).

Правила, которые держит этот модуль (а провайдеры только переводят их на
язык своего API):

- **Сумма — только из заказа.** Присланная провайдером сумма сверяется с
  ``market_orders.total``; не совпала — отказ на шаге провайдера.
- **Один живой счёт на заказ** — ``created``, ``pending`` или ``paid``; это
  держит и база (уникальный индекс ``market_payments_live_unique``).
  Открытый, но не начатый счёт другого провайдера при смене способа оплаты
  гасится; начатый (``pending``) или оплаченный — отказ.
- **Повтор транзакции** с тем же номером провайдера находит ту же строку
  (уникальность ``(provider, provider_transaction_id)``) — второго зачисления
  нет.
- **Порядок замков** везде один: сначала заказ (``for update``), затем строка
  оплаты — две оплаты одного заказа не сцепятся взаимной блокировкой.
- **Проведение** — ``orders.mark_paid`` (сумма, статус, срок — ещё раз под
  замком заказа); отказ — транзакция гасится, провайдер получает ошибку и
  возвращает деньги покупателю.
- **Возврат** — один раз: ``refund_requested_at`` ставится условным
  обновлением до вызова API провайдера, ``paid → refunded`` и
  ``orders.mark_refunded`` — одной транзакцией.

Ключи — только из окружения (``MARKET_UZUM_*``, ``MARKET_PAYME_*``,
``MARKET_CLICK_*``); провайдер без ключей выключен.
"""

from __future__ import annotations

import calendar
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from functools import wraps
from typing import Any, Protocol

from django.db import transaction
from django.http import HttpRequest, HttpResponse, HttpResponseNotAllowed
from django.views.decorators.csrf import csrf_exempt

from savdex.market import orders
from savdex.market.common import now, one, rows, write
from savdex.web.shared import settings_values

log = logging.getLogger("savdex.market.payments")

#: Провайдеры — тот же список держит ограничение market_payments_provider_check
PROVIDERS = ("uzum", "payme", "click")

# ── Статусы оплаты ──────────────────────────────────────────────────

#: Счёт открыт на сайте, транзакции провайдера ещё нет
CREATED = "created"
#: Провайдер завёл транзакцию, деньги ещё не проведены
PENDING = "pending"
#: Проведена: заказ оплачен, начисление в журнале денег
PAID = "paid"
#: Отменена до проведения
CANCELLED = "cancelled"
#: Деньги вернули покупателю
REFUNDED = "refunded"

#: Живые — не больше одной на заказ (market_payments_live_unique)
LIVE = (CREATED, PENDING, PAID)

# ── Причины отказа (провайдер переводит их в свои коды) ──────────────

NOT_FOUND = "not_found"
NOT_PAYABLE = "not_payable"
ALREADY_PAID = "already_paid"
WRONG_AMOUNT = "wrong_amount"
BUSY = "busy"

#: Что пишем администратору, когда вернуть через API нельзя
MANUAL_REFUND: dict[str, str] = {
    "uzum": (
        "Вернуть деньги: в кабинете Uzum отменить транзакцию — Uzum вызовет reverse, "
        "и заказ станет «деньги возвращены» сам"
    ),
    "payme": (
        "Вернуть деньги: в кабинете Payme Business отменить транзакцию — Payme вызовет "
        "CancelTransaction, и заказ станет «деньги возвращены» сам"
    ),
    "click": (
        "Вернуть деньги: API возврата Click не настроен (MARKET_CLICK_MERCHANT_USER_ID) — "
        "отменить платёж в кабинете Click и отметить возврат вручную"
    ),
}

#: НДС в чеке (Payme detail) — настройка в админке, по умолчанию 12
VAT_KEY = "market_vat_percent"
VAT_DEFAULT = 12

_COLUMNS = (
    "id, order_id, provider, provider_transaction_id, provider_ref, provider_time, amount, "
    "status, reason, note, created_at, updated_at, performed_at, cancelled_at, "
    "refund_requested_at, refunded_at"
)
_ORDER_COLUMNS = (
    "id, number, buyer_user_id, status, payment_method, total, paid_at, reserve_released_at"
)


# ── Настройки ───────────────────────────────────────────────────────


def env(name: str) -> str:
    """Переменная окружения без пробелов по краям; нет — пустая строка."""
    return (os.environ.get(name) or "").strip()


def env_int(name: str, default: int) -> int:
    try:
        return int(env(name) or default)
    except ValueError:
        return default


def production() -> bool:
    return os.environ.get("APP_ENV", "local") == "production"


def callback_ips(provider: str) -> list[str]:
    """Белый список адресов провайдера (MARKET_<ПРОВАЙДЕР>_CALLBACK_IPS через запятую)."""
    raw = env(f"MARKET_{provider.upper()}_CALLBACK_IPS")

    return [ip.strip() for ip in raw.split(",") if ip.strip()]


def vat_percent() -> int:
    """НДС для чека: настройка market_vat_percent; не число или вне 0…100 — 12."""
    try:
        value = int(str(settings_values().get(VAT_KEY, VAT_DEFAULT)).strip())
    except (TypeError, ValueError):
        return VAT_DEFAULT

    return value if 0 <= value <= 100 else VAT_DEFAULT


def return_url(number: str, fallback: str) -> str:
    """
    Куда провайдер вернёт покупателя после оплаты: MARKET_PAYMENT_RETURN_URL
    с {number} или страница заказа (fallback).
    """
    template = env("MARKET_PAYMENT_RETURN_URL")

    return template.replace("{number}", number) if template else fallback


def ms(moment: datetime | None) -> int:
    """Время из базы (UTC, без пояса) — в миллисекундах; нет — 0 (так ждёт Payme)."""
    if moment is None:
        return 0

    return calendar.timegm(moment.timetuple()) * 1000


def som_text(amount: int) -> str:
    """Тийины → «1000.00» (Click: сумма с двумя знаками)."""
    whole, rest = divmod(int(amount), 100)

    return f"{whole}.{rest:02d}"


def tiyin_exact(value: object) -> int | None:
    """
    Сумма в сумах от провайдера («1000», «1000.5», «1000.50») → тийины,
    точно: больше двух знаков после точки, не число, ноль и минус — None.
    """
    if value is None or isinstance(value, bool):
        return None

    try:
        amount = Decimal(str(value).strip())
    except InvalidOperation:
        return None

    if not amount.is_finite() or amount <= 0:
        return None

    cents = amount * 100

    if cents != cents.to_integral_value():
        return None

    return int(cents)


# ── Протокол провайдера ─────────────────────────────────────────────


@dataclass(frozen=True)
class StatementLine:
    """Строка выписки провайдера для сверки: номер транзакции и сумма в тийинах."""

    transaction_id: str
    amount: int


class Provider(Protocol):
    """
    Провайдер оплаты. Колбэки — свои у каждого (uzum.py, payme.py,
    click.py); здесь — то, что зовёт общий код.
    """

    name: str

    def enabled(self) -> bool:
        """Ключи заданы — можно платить и принимать колбэки."""
        ...

    def create_invoice(
        self, order: dict[str, Any], payment: dict[str, Any], *, locale: str, back: str
    ) -> str:
        """Адрес страницы оплаты провайдера для счёта ``payment`` заказа ``order``."""
        ...

    def refund(self, payment: dict[str, Any]) -> bool | None:
        """
        Вернуть деньги через API провайдера: True — вернул, False — отказал
        (можно повторить), None — API возврата нет (возврат — из кабинета
        провайдера, MANUAL_REFUND). Сбой связи — исключение: вернул или нет,
        неизвестно, и повторять сам код не должен.
        """
        ...

    def statement(self, day: date) -> list[StatementLine] | None:
        """Проведённые за сутки (UTC) транзакции по данным провайдера; нет API — None."""
        ...


def get(name: str) -> Provider:
    """Провайдер по имени; неизвестный — KeyError."""
    if name == "uzum":
        from savdex.market.payments import uzum

        return uzum.PROVIDER

    if name == "payme":
        from savdex.market.payments import payme

        return payme.PROVIDER

    if name == "click":
        from savdex.market.payments import click

        return click.PROVIDER

    raise KeyError(name)


def enabled(name: str) -> bool:
    return name in PROVIDERS and get(name).enabled()


# ── Строки оплат и заказа ───────────────────────────────────────────


def payment(pk: int, *, lock: bool = False) -> dict[str, Any] | None:
    return one(
        f"select {_COLUMNS} from market_payments where id = %s" + (" for update" if lock else ""),
        [pk],
    )


def by_transaction(provider: str, transaction_id: str) -> dict[str, Any] | None:
    if not transaction_id:
        return None

    return one(
        f"select {_COLUMNS} from market_payments "
        "where provider = %s and provider_transaction_id = %s",
        [provider, transaction_id],
    )


def live(order_id: int, *, lock: bool = False) -> dict[str, Any] | None:
    return one(
        f"select {_COLUMNS} from market_payments where order_id = %s and status = any(%s)"
        + (" for update" if lock else ""),
        [order_id, list(LIVE)],
    )


def order_by_id(order_id: int, *, lock: bool = False) -> dict[str, Any] | None:
    return one(
        f"select {_ORDER_COLUMNS} from market_orders where id = %s"
        + (" for update" if lock else ""),
        [order_id],
    )


def order_by_number(number: str, *, lock: bool = False) -> dict[str, Any] | None:
    if not number:
        return None

    return one(
        f"select {_ORDER_COLUMNS} from market_orders where number = %s"
        + (" for update" if lock else ""),
        [orders.normalize_number(str(number))[:16]],
    )


def locked(provider: str, transaction_id: str) -> dict[str, Any] | None:
    """
    Строка оплаты по номеру транзакции провайдера — под замком, в порядке
    «заказ, затем оплата». Только внутри transaction.atomic.
    """
    found = by_transaction(provider, transaction_id)

    if found is None:
        return None

    order_by_id(int(found["order_id"]), lock=True)

    return payment(int(found["id"]), lock=True)


def _set(pk: int, before: tuple[str, ...], after: str, **fields: object) -> bool:
    """Смена статуса оплаты условным обновлением: ноль строк — уже сменили."""
    moment = now()
    names = ["status = %s", "updated_at = %s", *(f"{name} = %s" for name in fields)]

    return bool(
        write(
            f"update market_payments set {', '.join(names)} where id = %s and status = any(%s)",
            [after, moment, *fields.values(), pk, list(before)],
        )
    )


def _refusal(order: dict[str, Any] | None, amount: int | None) -> str | None:
    """Почему по заказу нельзя платить эту сумму; можно — None."""
    if order is None:
        return NOT_FOUND

    if order["paid_at"] is not None:
        return ALREADY_PAID

    if (
        order["payment_method"] != "card"
        or order["status"] != orders.CREATED
        or order["reserve_released_at"] is not None
    ):
        return NOT_PAYABLE

    if amount is None or int(amount) != int(order["total"]):
        return WRONG_AMOUNT

    return None


def check(number: str, amount: int | None) -> tuple[dict[str, Any] | None, str | None]:
    """
    Предварительная проверка провайдера (Uzum check, Payme
    CheckPerformTransaction): заказ есть, ждёт оплаты картой, сумма та, и
    другой транзакции по нему нет. Без записи.
    """
    order = order_by_number(number)
    problem = _refusal(order, amount)

    if problem is not None:
        return order, problem

    assert order is not None
    current = live(int(order["id"]))

    if current is not None and current["status"] == PAID:
        return order, ALREADY_PAID

    if current is not None and current["status"] == PENDING:
        return order, BUSY

    return order, None


def open_transaction(
    provider: str,
    transaction_id: str,
    number: str,
    amount: int | None,
    *,
    provider_time: int | None = None,
    provider_ref: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """
    Провайдер завёл транзакцию (Uzum create, Payme CreateTransaction, Click
    Prepare): привязать её к живому счёту заказа или завести счёт.
    Возвращает (оплата, None) или (None, причина отказа). Только внутри
    transaction.atomic: заказ — под замком до конца транзакции.
    """
    order = order_by_number(number, lock=True)
    problem = _refusal(order, amount)

    if problem is not None:
        return None, problem

    assert order is not None
    order_id = int(order["id"])
    current = live(order_id, lock=True)

    if current is not None:
        if current["status"] == PAID:
            return None, ALREADY_PAID

        if current["status"] == PENDING:
            # Тот же номер транзакции пришёл вторым запросом одновременно с первым
            if current["provider"] == provider and current["provider_transaction_id"] == (
                transaction_id
            ):
                return current, None

            return None, BUSY

        if current["provider"] == provider:
            # created_at — с этой минуты: от неё считают сроки провайдера
            # (Payme — 12 часов, Uzum — confirm) и отсрочка истечения заказа
            _set(
                int(current["id"]),
                (CREATED,),
                PENDING,
                created_at=now(),
                provider_transaction_id=transaction_id,
                provider_time=provider_time,
                provider_ref=provider_ref,
                amount=int(order["total"]),
            )

            return payment(int(current["id"])), None

        # Счёт другого провайдера ещё не начат — покупатель сменил способ оплаты
        _set(
            int(current["id"]),
            (CREATED,),
            CANCELLED,
            cancelled_at=now(),
            note=f"сменили способ оплаты на {provider}",
        )

    moment = now()
    pk = write(
        "insert into market_payments (order_id, provider, provider_transaction_id, provider_ref, "
        "provider_time, amount, status, created_at, updated_at) "
        "values (%s, %s, %s, %s, %s, %s, %s, %s, %s) returning id",
        [
            order_id,
            provider,
            transaction_id,
            provider_ref,
            provider_time,
            int(order["total"]),
            PENDING,
            moment,
            moment,
        ],
    )
    log.info("market.payment.opened provider=%s order=%s payment=%s", provider, order_id, pk)

    return payment(int(pk)), None


def complete(found: dict[str, Any]) -> str | None:
    """
    Провайдер провёл деньги (Uzum confirm, Payme PerformTransaction, Click
    Complete) по ждущей оплате ``found`` (взята через ``locked``):
    ``orders.mark_paid`` и paid. Заказ уже не ждёт оплаты (отменён, истёк,
    сумма не та) — транзакция гасится, возвращается причина отказа:
    провайдер получает ошибку и возвращает деньги покупателю.
    """
    order_id = int(found["order_id"])
    note = f"оплата {found['provider']}, транзакция {found['provider_transaction_id']}"

    if orders.mark_paid(order_id, int(found["amount"]), note=note):
        _set(int(found["id"]), (PENDING,), PAID, performed_at=now())
        log.info("market.payment.paid provider=%s order=%s", found["provider"], order_id)

        return None

    order = order_by_id(order_id)
    _set(
        int(found["id"]),
        (PENDING,),
        CANCELLED,
        cancelled_at=now(),
        reason=3,
        note="заказ уже не ждёт оплаты — деньги не приняты",
    )
    log.warning(
        "market.payment.rejected provider=%s order=%s status=%s",
        found["provider"],
        order_id,
        order["status"] if order else None,
    )

    return ALREADY_PAID if order is not None and order["paid_at"] is not None else NOT_PAYABLE


def cancel_pending(found: dict[str, Any], *, reason: int | None = None, note: str) -> bool:
    """Отмена транзакции до проведения (провайдер отменил, истёк срок)."""
    return _set(
        int(found["id"]),
        (PENDING,),
        CANCELLED,
        cancelled_at=now(),
        reason=reason,
        note=note[:500],
    )


def refundable(found: dict[str, Any]) -> bool:
    """Проведённую оплату можно вернуть: заказ ждёт возврата (refund_pending)."""
    if found["status"] != PAID:
        return False

    order = order_by_id(int(found["order_id"]))

    return order is not None and order["status"] == orders.REFUND_PENDING


def refund_payment(found: dict[str, Any], *, reason: int | None = None, note: str) -> bool:
    """
    Деньги покупателю вернули: оплата paid → refunded и
    ``orders.mark_refunded`` — одной транзакцией и ровно один раз. Заказ не
    ждёт возврата или оплату уже вернули — False, ничего не записано.
    """
    with transaction.atomic():
        order = order_by_id(int(found["order_id"]), lock=True)

        if order is None or order["status"] != orders.REFUND_PENDING:
            return False

        if not _set(int(found["id"]), (PAID,), REFUNDED, refunded_at=now(), reason=reason):
            return False

        if not orders.mark_refunded(int(found["order_id"]), note=note):
            # Под замком заказа статус не мог смениться — значит, ошибка в коде
            raise RuntimeError(f"market_payments {found['id']}: заказ не перешёл в refunded")

    log.info("market.payment.refunded provider=%s order=%s", found["provider"], order["id"])

    return True


# ── Счёт со страницы заказа ─────────────────────────────────────────


def open_invoice(
    user_id: int, number: str, provider: str, *, locale: str, back: str
) -> tuple[dict[str, Any], str]:
    """
    POST /market/api/orders/<номер>/pay: открыть счёт у провайдера или
    вернуть уже открытый. Только свой заказ (чужой — 404), только картой и
    только ждущий оплаты. Возвращает (оплата, адрес страницы провайдера);
    отказ — orders.OrderRefused.
    """
    if provider not in PROVIDERS or not get(provider).enabled():
        raise orders.OrderRefused("payment.provider", 422, field="provider")

    with transaction.atomic():
        order = one(
            f"select {_ORDER_COLUMNS} from market_orders where number = %s "
            "and buyer_user_id = %s for update",
            [orders.normalize_number(number), user_id],
        )

        if order is None:
            raise orders.OrderRefused("order.not_found", 404)

        problem = _refusal(order, int(order["total"]))

        if problem == ALREADY_PAID:
            raise orders.OrderRefused("payment.already_paid", 409)

        if problem is not None:
            raise orders.OrderRefused("payment.not_payable", 409)

        order_id = int(order["id"])
        current = live(order_id, lock=True)

        if current is not None and current["status"] == PAID:
            raise orders.OrderRefused("payment.already_paid", 409)

        if current is not None and current["status"] == PENDING:
            raise orders.OrderRefused("payment.in_progress", 409)

        if current is not None and current["provider"] != provider:
            _set(
                int(current["id"]),
                (CREATED,),
                CANCELLED,
                cancelled_at=now(),
                note=f"сменили способ оплаты на {provider}",
            )
            current = None

        if current is None:
            moment = now()
            pk = write(
                "insert into market_payments (order_id, provider, amount, status, created_at, "
                "updated_at) values (%s, %s, %s, %s, %s, %s) returning id",
                [order_id, provider, int(order["total"]), CREATED, moment, moment],
            )
            current = payment(int(pk))

        assert current is not None
        url = get(provider).create_invoice(order, current, locale=locale, back=back)

    return current, url


# ── Возврат ─────────────────────────────────────────────────────────


def refund_order(order_id: int) -> str:
    """
    Вернуть деньги по заказу в «ожидает возврата» (refund_pending) — ровно
    один раз. Итог:

    - ``refunded`` — провайдер вернул через API, заказ — «деньги возвращены»;
    - ``manual`` — API возврата нет: пометка администратору в истории заказа
      (MANUAL_REFUND), заказ остаётся refund_pending, пока провайдер не
      пришлёт отмену (Uzum reverse, Payme CancelTransaction) или возврат не
      отметят вручную;
    - ``requested`` — возврат уже запрошен раньше (второй вызов ничего не делает);
    - ``refused`` — провайдер отказал, можно повторить;
    - ``error`` — сбой связи: вернул ли провайдер деньги, неизвестно —
      повторно сам не запрашиваем, разбирают руками (журнал — ERROR);
    - ``not_pending`` — заказ не ждёт возврата; ``no_payment`` — оплаты картой нет.

    Сеть — вне транзакции и без замков: замок держит только отметка
    ``refund_requested_at``, поставленная условным обновлением.
    """
    order = order_by_id(order_id)

    if order is None or order["status"] != orders.REFUND_PENDING:
        return "not_pending"

    found = one(
        f"select {_COLUMNS} from market_payments where order_id = %s and status = %s "
        "order by id desc limit 1",
        [order_id, PAID],
    )

    if found is None:
        log.error("market.payment.refund_without_payment order=%s", order_id)

        return "no_payment"

    claimed = write(
        "update market_payments set refund_requested_at = %s, updated_at = %s "
        "where id = %s and status = %s and refund_requested_at is null",
        [now(), now(), found["id"], PAID],
    )

    if not claimed:
        return "requested"

    provider = get(str(found["provider"]))

    try:
        result = provider.refund(found) if provider.enabled() else None
    except Exception:
        log.exception(
            "market.payment.refund_failed provider=%s order=%s", found["provider"], order_id
        )

        return "error"

    if result is None:
        note = MANUAL_REFUND[str(found["provider"])]

        with transaction.atomic():
            write(
                "update market_payments set note = %s, updated_at = %s where id = %s",
                [note[:500], now(), found["id"]],
            )
            orders.note(order_id, note)

        log.warning(
            "market.payment.refund_manual provider=%s order=%s", found["provider"], order_id
        )

        return "manual"

    if result is False:
        write(
            "update market_payments set refund_requested_at = null, updated_at = %s "
            "where id = %s and status = %s",
            [now(), found["id"], PAID],
        )
        log.error("market.payment.refund_refused provider=%s order=%s", found["provider"], order_id)

        return "refused"

    fresh = payment(int(found["id"]))

    if fresh is not None and refund_payment(
        fresh, reason=5, note=f"возврат через {found['provider']}"
    ):
        return "refunded"

    # Пока шёл запрос, провайдер уже прислал отмену — возврат записан ею
    return "requested"


def refund_all(limit: int = 200) -> dict[str, int]:
    """Расписание: все заказы в refund_pending, по которым возврат ещё не запрашивали."""
    done: dict[str, int] = {}

    for found in rows(
        "select distinct o.id from market_orders o join market_payments p on p.order_id = o.id "
        "where o.status = %s and p.status = %s and p.refund_requested_at is null "
        "order by o.id limit %s",
        [orders.REFUND_PENDING, PAID, limit],
    ):
        result = refund_order(int(found["id"]))
        done[result] = done.get(result, 0) + 1

    return done


# ── Колбэки ─────────────────────────────────────────────────────────

View = Callable[..., HttpResponse]


def callback(provider: str, deny: Callable[[HttpRequest], HttpResponse]) -> Callable[[View], View]:
    """
    Обёртка колбэка провайдера (сервер — серверу):

    - без CSRF: у провайдера нет ни сессии, ни токена — запрос держит
      подпись или пароль, которые проверяет сам колбэк (как у колбэков
      тарифов, savdex/web/payment_callbacks.py; проверка CSRF Django на
      сайте и так стоит только на /py/ — savdex/csrf.py);
    - только там, где маркетплейс открыт (market_open), и только у
      включённого провайдера — иначе 404, как будто адреса нет;
    - только POST;
    - белый список адресов провайдера (MARKET_<ПРОВАЙДЕР>_CALLBACK_IPS),
      если задан; чужой адрес — deny (ответ в формате провайдера);
    - вся обработка — одной транзакцией: два одинаковых колбэка разом —
      второй ждёт замка и видит готовое, а не 500.
    """

    def decorate(view: View) -> View:
        @csrf_exempt
        @wraps(view)
        def wrapped(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
            from savdex import audit
            from savdex.web.shared import market_open

            if not market_open() or not enabled(provider):
                return HttpResponse(status=404)

            if request.method != "POST":
                return HttpResponseNotAllowed(["POST"])

            ips = callback_ips(provider)

            if ips and audit.client_ip(request) not in ips:
                log.warning("market.payment.foreign_ip provider=%s", provider)

                return deny(request)

            with transaction.atomic():
                return view(request, *args, **kwargs)

        return wrapped

    return decorate
