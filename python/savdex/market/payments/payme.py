"""
Payme — Merchant API (JSON-RPC 2.0) для заказов маркетплейса:
POST /market/api/payments/payme.

Методы: CheckPerformTransaction, CreateTransaction, PerformTransaction,
CancelTransaction, CheckTransaction, GetStatement. Ответ — всегда HTTP 200,
ошибка — ``{"error": {"code", "message": {ru, uz, en}, "data"}, "id"}``.

- Авторизация — заголовок ``Authorization: Basic base64("Paycom:<KEY>")``,
  KEY — MARKET_PAYME_KEY; сравнение — ``hmac.compare_digest``. Не то —
  -32504.
- Суммы — в тийинах; номер заказа — ``account.<поле>``
  (MARKET_PAYME_ACCOUNT_FIELD, по умолчанию ``order``).
- Ошибки заказа: -31050 не найден, -31051 не ждёт оплаты (отменён, истёк,
  не картой), -31052 уже оплачен, -31053 по заказу уже идёт другая
  транзакция; -31001 — сумма не та; -31003 — транзакция не найдена;
  -31008 — операцию выполнить нельзя; -31007 — отменить проведённую нельзя
  (заказ не ждёт возврата).
- Состояния транзакции: 1 — создана, 2 — проведена, -1 — отменена до
  проведения, -2 — отменена после проведения (возврат).
- Срок жизни созданной транзакции — 12 часов: CreateTransaction и
  PerformTransaction после него отменяют её с причиной 4 и отвечают -31008.
- Повтор любого метода с тем же id отвечает тем же (время — из базы):
  второго зачисления и второй отмены нет.
- Возврат: API для продавца нет — отмена проведённой транзакции в кабинете
  Payme Business, Payme зовёт CancelTransaction; принимаем, только если
  заказ ждёт возврата (refund_pending).
- В ответе CheckPerformTransaction — ``detail`` (чек): позиции заказа с
  ИКПУ (code), названием, ценой за штуку, количеством и НДС.

ChangePassword не поддерживается (-32601): ключ живёт только в окружении.

**Сверить с договором и документацией Payme Merchant API** до боевого
включения: коды -31050…-31099 и их тексты, состав ``detail`` (обязательность
package_code, НДС, ИНН продавца для маркетплейса — ``commission_info``),
адрес checkout (MARKET_PAYME_CHECKOUT_URL, у песочницы —
https://checkout.test.paycom.uz) и формат параметров ссылки.
"""

from __future__ import annotations

import base64
import hmac
import json
import logging
import time
from dataclasses import dataclass
from datetime import date
from typing import Any

from django.http import HttpRequest, HttpResponse

from savdex.market import orders
from savdex.market.common import one, rows
from savdex.market.payments import base

log = logging.getLogger("savdex.market.payments.payme")

#: Срок жизни созданной транзакции — 12 часов, в миллисекундах
TIMEOUT_MS = 43_200_000

#: Причина отмены «истёк срок» (Payme reason 4)
REASON_TIMEOUT = 4

#: Причина отмены «ошибка выполнения» (Payme reason 3): заказ уже не ждёт оплаты
REASON_ORDER_GONE = 3

#: reason хранится в smallint
REASON_MAX = 32767

ERROR_AUTH = -32504
ERROR_PARSE = -32700
ERROR_REQUEST = -32600
ERROR_METHOD = -32601
ERROR_AMOUNT = -31001
ERROR_TRANSACTION_NOT_FOUND = -31003
ERROR_CANNOT_CANCEL = -31007
ERROR_CANNOT_PERFORM = -31008
ERROR_ORDER_NOT_FOUND = -31050
ERROR_ORDER_NOT_PAYABLE = -31051
ERROR_ORDER_PAID = -31052
ERROR_ORDER_BUSY = -31053
#: Чек не собрать: у позиции нет ИКПУ (или у доставки — MARKET_DELIVERY_IKPU)
ERROR_NO_RECEIPT = -31054
#: Транзакция с этим id заведена на другой заказ
ERROR_OTHER_ORDER = -31099

MESSAGES: dict[int, tuple[str, str, str]] = {
    ERROR_AUTH: ("Недостаточно привилегий", "Ruxsat yo‘q", "Insufficient privileges"),
    ERROR_PARSE: ("Ошибка разбора JSON", "JSON xatosi", "Parse error"),
    ERROR_REQUEST: ("Неверный запрос", "Noto‘g‘ri so‘rov", "Invalid request"),
    ERROR_METHOD: ("Метод не найден", "Metod topilmadi", "Method not found"),
    ERROR_AMOUNT: ("Неверная сумма", "Noto‘g‘ri summa", "Wrong amount"),
    ERROR_TRANSACTION_NOT_FOUND: (
        "Транзакция не найдена",
        "Tranzaksiya topilmadi",
        "Transaction not found",
    ),
    ERROR_CANNOT_CANCEL: (
        "Заказ выполнен, отменить транзакцию нельзя",
        "Buyurtma bajarilgan, tranzaksiyani bekor qilib bo‘lmaydi",
        "Order completed, transaction cannot be cancelled",
    ),
    ERROR_CANNOT_PERFORM: (
        "Невозможно выполнить операцию",
        "Amalni bajarib bo‘lmaydi",
        "Unable to perform operation",
    ),
    ERROR_ORDER_NOT_FOUND: ("Заказ не найден", "Buyurtma topilmadi", "Order not found"),
    ERROR_ORDER_NOT_PAYABLE: (
        "Заказ не ждёт оплаты",
        "Buyurtma to‘lovni kutmayapti",
        "Order is not awaiting payment",
    ),
    ERROR_ORDER_PAID: ("Заказ уже оплачен", "Buyurtma allaqachon to‘langan", "Order already paid"),
    ERROR_ORDER_BUSY: (
        "По заказу уже идёт другая оплата",
        "Buyurtma bo‘yicha boshqa to‘lov amalga oshirilmoqda",
        "Another payment for the order is in progress",
    ),
    ERROR_NO_RECEIPT: (
        "Нет ИКПУ у позиции заказа — чек не собрать",
        "Buyurtma pozitsiyasida MXIK yo‘q — chekni tuzib bo‘lmaydi",
        "An order item has no IKPU code, the receipt cannot be built",
    ),
    ERROR_OTHER_ORDER: (
        "Транзакция заведена на другой заказ",
        "Tranzaksiya boshqa buyurtmaga ochilgan",
        "The transaction belongs to another order",
    ),
}

REFUSALS = {
    base.NOT_FOUND: ERROR_ORDER_NOT_FOUND,
    base.NOT_PAYABLE: ERROR_ORDER_NOT_PAYABLE,
    base.ALREADY_PAID: ERROR_ORDER_PAID,
    base.BUSY: ERROR_ORDER_BUSY,
    base.WRONG_AMOUNT: ERROR_AMOUNT,
}

#: Статус оплаты → состояние транзакции Payme
STATES = {base.PENDING: 1, base.PAID: 2, base.CANCELLED: -1, base.REFUNDED: -2}


@dataclass(frozen=True)
class Config:
    merchant_id: str
    key: str
    checkout_url: str
    account_field: str

    @classmethod
    def from_env(cls) -> Config:
        return cls(
            merchant_id=base.env("MARKET_PAYME_MERCHANT_ID"),
            key=base.env("MARKET_PAYME_KEY"),
            checkout_url=base.env("MARKET_PAYME_CHECKOUT_URL") or "https://checkout.paycom.uz",
            account_field=base.env("MARKET_PAYME_ACCOUNT_FIELD") or "order",
        )


class PaymeProvider:
    name = "payme"

    def enabled(self) -> bool:
        config = Config.from_env()

        # На боевом — только со списком адресов Payme, как у Uzum
        return bool(config.merchant_id and config.key) and base.allowed_here(self.name)

    def create_invoice(
        self, order: dict[str, Any], payment: dict[str, Any], *, locale: str, back: str
    ) -> str:
        """Ссылка на checkout Payme: base64 от «m=…;ac.order=…;a=…;c=…;l=…»."""
        config = Config.from_env()
        params = ";".join(
            [
                f"m={config.merchant_id}",
                f"ac.{config.account_field}={order['number']}",
                f"a={int(payment['amount'])}",
                # «;» и «=» в адресе возврата сломали бы разбор параметров —
                # такой адрес не передаём (Payme вернёт на свою страницу)
                *([f"c={back}"] if back and ";" not in back and "=" not in back else []),
                f"l={locale if locale in ('ru', 'uz', 'en') else 'ru'}",
            ]
        )
        encoded = base64.b64encode(params.encode()).decode()

        return f"{config.checkout_url.rstrip('/')}/{encoded}"

    def refund(self, payment: dict[str, Any]) -> bool | None:
        # У Merchant API нет возврата по запросу продавца: отмена — в кабинете
        # Payme Business, Payme сам зовёт CancelTransaction
        return None

    def statement(self, day: date) -> list[base.StatementLine] | None:
        # Реестр для Payme — наш же ответ на GetStatement: сверка — оплаты
        # против журнала денег (reconcile.py)
        return None


PROVIDER = PaymeProvider()


# ── Ответы ──────────────────────────────────────────────────────────


def _response(body: dict[str, Any]) -> HttpResponse:
    return HttpResponse(
        json.dumps(body, ensure_ascii=False), status=200, content_type="application/json"
    )


def _result(request_id: object, result: dict[str, Any]) -> HttpResponse:
    return _response({"jsonrpc": "2.0", "id": base.echo(request_id), "result": result})


def _error(request_id: object, code: int, data: str | None = None) -> HttpResponse:
    ru, uz, en = MESSAGES.get(code, MESSAGES[ERROR_CANNOT_PERFORM])

    return _response(
        {
            "jsonrpc": "2.0",
            "id": base.echo(request_id),
            "error": {"code": code, "message": {"ru": ru, "uz": uz, "en": en}, "data": data},
        }
    )


def _now_ms() -> int:
    return int(time.time() * 1000)


def _int(value: object) -> int | None:
    """Целое из JSON в пределах 0…2⁶³-1 (bigint); прочее — None."""
    if isinstance(value, bool):
        return None

    if isinstance(value, float) and value.is_integer():
        value = int(value)

    if isinstance(value, int) and 0 <= value <= base.BIGINT_MAX:
        return value

    return None


def _timed_out(payment: dict[str, Any]) -> bool:
    return _now_ms() - base.ms(payment["created_at"]) > TIMEOUT_MS


def _transaction(payment: dict[str, Any]) -> dict[str, Any]:
    """Поля транзакции для CheckTransaction и GetStatement."""
    cancelled = payment["refunded_at"] if payment["status"] == base.REFUNDED else None

    return {
        "create_time": base.ms(payment["created_at"]),
        "perform_time": base.ms(payment["performed_at"]),
        "cancel_time": base.ms(cancelled or payment["cancelled_at"]),
        "transaction": str(payment["id"]),
        "state": STATES.get(payment["status"], -1),
        "reason": payment["reason"],
    }


def detail(order: dict[str, Any]) -> dict[str, Any] | None:
    """
    Чек для CheckPerformTransaction: позиции заказа — ИКПУ (code), название,
    цена за штуку и количество (тийины), НДС из настройки market_vat_percent;
    доставка (delivery_total > 0) — своей позицией с ИКПУ из
    MARKET_DELIVERY_IKPU. Чек с пустым кодом не отправляем: у позиции нет
    ИКПУ — None (провайдер получает отказ ERROR_NO_RECEIPT до транзакции).
    """
    vat = base.vat_percent()
    items = []

    for item in rows(
        "select title, ikpu, price, quantity from market_order_items where order_id = %s "
        "order by id",
        [order["id"]],
    ):
        line: dict[str, Any] = {
            "title": str(item["title"])[:128],
            "price": int(item["price"]),
            "count": int(item["quantity"]),
            "code": item["ikpu"],
            "vat_percent": vat,
        }
        # TODO(маркетплейс, оплата): код упаковки (package_code) к ИКПУ — у
        # товара его пока нет; Payme требует его для фискализации. Завести
        # поле у товара (справочник tasnif.soliq.uz) и копировать в позицию
        # заказа; до тех пор ключ не передаём
        items.append(line)

    total = one("select delivery_total from market_orders where id = %s", [order["id"]])
    delivery = int(total["delivery_total"] or 0) if total else 0

    if delivery > 0:
        items.append(
            {
                "title": "Доставка",
                "price": delivery,
                "count": 1,
                "code": base.env("MARKET_DELIVERY_IKPU") or None,
                "vat_percent": vat,
            }
        )

    if not items or any(not str(item["code"] or "").strip() for item in items):
        log.warning("market.payment.payme.no_ikpu order=%s", order["id"])

        return None

    return {"receipt_type": 0, "items": items}


# ── Методы ──────────────────────────────────────────────────────────


class _Rpc:
    def __init__(self, request_id: object, params: dict[str, Any], config: Config) -> None:
        self.id = request_id
        self.params = params
        self.config = config

    def number(self) -> str:
        account = self.params.get("account")
        value = account.get(self.config.account_field) if isinstance(account, dict) else None

        if isinstance(value, bool) or not isinstance(value, str | int):
            return ""

        return str(value).strip()

    def transaction_id(self) -> str:
        value = self.params.get("id")

        return value.strip()[:64] if isinstance(value, str) else ""

    def refused(self, problem: str | None) -> HttpResponse:
        code = REFUSALS.get(problem or base.NOT_PAYABLE, ERROR_ORDER_NOT_PAYABLE)

        return _error(self.id, code, None if code == ERROR_AMOUNT else self.config.account_field)

    def check_perform(self) -> HttpResponse:
        order, problem = base.check(self.number(), _int(self.params.get("amount")))

        if problem is not None:
            return self.refused(problem)

        assert order is not None
        receipt = detail(order)

        if receipt is None:
            return _error(self.id, ERROR_NO_RECEIPT, self.config.account_field)

        return _result(self.id, {"allow": True, "detail": receipt})

    def create(self) -> HttpResponse:
        trans_id = self.transaction_id()
        payme_time = _int(self.params.get("time"))

        if trans_id == "" or payme_time is None:
            return _error(self.id, ERROR_REQUEST)

        existing = base.locked("payme", trans_id)
        amount = _int(self.params.get("amount"))

        if existing is not None:
            # Повтор с известным id: тот же заказ и та же сумма, заказ всё
            # ещё ждёт оплаты — иначе понятный отказ, а не «та же транзакция»
            order = base.order_by_id(int(existing["order_id"]))

            if order is None or order["number"] != orders.normalize_number(self.number()):
                return _error(self.id, ERROR_OTHER_ORDER, self.config.account_field)

            if amount != int(existing["amount"]):
                return _error(self.id, ERROR_AMOUNT)

            if existing["status"] != base.PENDING:
                return _error(self.id, ERROR_CANNOT_PERFORM)

            if _timed_out(existing):
                base.cancel_pending(existing, reason=REASON_TIMEOUT, note="Payme: истёк срок 12 ч")

                return _error(self.id, ERROR_CANNOT_PERFORM)

            # Заказ за это время истёк или отменён: нашу строку гасим (Payme
            # затем вызовет CancelTransaction и увидит -1) и отвечаем -31008,
            # как при истёкшей транзакции
            if base.refusal(order, amount) is not None:
                base.cancel_pending(
                    existing, reason=REASON_ORDER_GONE, note="Payme: заказ уже не ждёт оплаты"
                )

                return _error(self.id, ERROR_CANNOT_PERFORM)

            return self.created(existing)

        found = base.order_by_number(self.number())

        if found is not None and base.refusal(found, amount) is None and detail(found) is None:
            return _error(self.id, ERROR_NO_RECEIPT, self.config.account_field)

        payment, problem = base.open_transaction(
            "payme",
            trans_id,
            self.number(),
            amount,
            provider_time=payme_time,
        )

        if payment is None:
            return self.refused(problem)

        return self.created(payment)

    def created(self, payment: dict[str, Any]) -> HttpResponse:
        return _result(
            self.id,
            {
                "create_time": base.ms(payment["created_at"]),
                "transaction": str(payment["id"]),
                "state": 1,
            },
        )

    def perform(self) -> HttpResponse:
        payment = base.locked("payme", self.transaction_id())

        if payment is None:
            return _error(self.id, ERROR_TRANSACTION_NOT_FOUND)

        if payment["status"] == base.PENDING:
            if _timed_out(payment):
                # Payme пришёл проводить после срока — отказ с отметкой
                # rejected_at (деньги могли списать, сверка попросит проверить)
                base.reject(payment, reason=REASON_TIMEOUT, note="Payme: истёк срок 12 ч")

                return _error(self.id, ERROR_CANNOT_PERFORM)

            if base.complete(payment) is not None:
                return _error(self.id, ERROR_CANNOT_PERFORM)

            payment = base.payment(int(payment["id"]))
            assert payment is not None

        if payment["status"] != base.PAID:
            # Проводить погашенную (отменена нами или Payme) — тоже отказ с отметкой
            base.reject(payment, note="Payme: Perform по отменённой транзакции")

            return _error(self.id, ERROR_CANNOT_PERFORM)

        return _result(
            self.id,
            {
                "transaction": str(payment["id"]),
                "perform_time": base.ms(payment["performed_at"]),
                "state": 2,
            },
        )

    def cancel(self) -> HttpResponse:
        payment = base.locked("payme", self.transaction_id())

        if payment is None:
            return _error(self.id, ERROR_TRANSACTION_NOT_FOUND)

        raw = self.params.get("reason")
        reason = _int(raw)

        # reason пишется в smallint: вне его — неверный запрос, а не 500
        if raw is not None and (reason is None or not 0 <= reason <= REASON_MAX):
            return _error(self.id, ERROR_REQUEST)

        if payment["status"] == base.PENDING:
            base.cancel_pending(payment, reason=reason, note="Payme: отмена транзакции")
        elif payment["status"] == base.PAID and not base.refund_payment(
            payment, reason=reason, note="Payme: отмена проведённой транзакции (возврат)"
        ):
            return _error(self.id, ERROR_CANNOT_CANCEL)

        fresh = base.payment(int(payment["id"]))
        assert fresh is not None
        found = _transaction(fresh)

        return _result(
            self.id,
            {
                "transaction": found["transaction"],
                "cancel_time": found["cancel_time"],
                "state": found["state"],
            },
        )

    def check_transaction(self) -> HttpResponse:
        payment = base.by_transaction("payme", self.transaction_id())

        if payment is None:
            return _error(self.id, ERROR_TRANSACTION_NOT_FOUND)

        return _result(self.id, _transaction(payment))

    def statement(self) -> HttpResponse:
        start, end = _int(self.params.get("from")), _int(self.params.get("to"))

        # Границы — миллисекунды в bigint; _int уже отсёк всё вне 0…2⁶³-1
        if start is None or end is None or start > end:
            return _error(self.id, ERROR_REQUEST)

        found = rows(
            "select p.id, p.provider_transaction_id, p.provider_time, p.amount, p.status, "
            "p.reason, p.created_at, p.performed_at, p.cancelled_at, p.refunded_at, o.number "
            "from market_payments p join market_orders o on o.id = p.order_id "
            "where p.provider = 'payme' and p.provider_transaction_id is not null "
            "and p.provider_time between %s and %s order by p.provider_time, p.id",
            [start, end],
        )

        return _result(
            self.id,
            {
                "transactions": [
                    {
                        "id": payment["provider_transaction_id"],
                        "time": int(payment["provider_time"]),
                        "amount": int(payment["amount"]),
                        "account": {self.config.account_field: payment["number"]},
                        **_transaction(payment),
                        "receivers": None,
                    }
                    for payment in found
                ]
            },
        )


def _authorized(request: HttpRequest, config: Config) -> bool:
    header = request.headers.get("Authorization", "")
    user, secret = "", ""

    if header[:6].lower() == "basic ":
        try:
            decoded = base64.b64decode(header[6:].strip()).decode()
        except (ValueError, UnicodeDecodeError):
            decoded = ""

        if ":" in decoded:
            user, secret = decoded.split(":", 1)

    user_ok = hmac.compare_digest(b"Paycom", user.encode())
    key_ok = hmac.compare_digest(config.key.encode(), secret.encode())

    return bool(config.key) and user_ok and key_ok


def _request_id(request: HttpRequest) -> object:
    """id запроса JSON-RPC — для эха в ответе: строка до 64 знаков или целое."""
    try:
        body = json.loads(request.body or b"{}")
    except ValueError:
        return None

    return base.echo(body.get("id")) if isinstance(body, dict) else None


def _deny(request: HttpRequest) -> HttpResponse:
    return _error(_request_id(request), ERROR_AUTH)


@base.callback("payme", _deny)
def endpoint(request: HttpRequest) -> HttpResponse:
    """POST /market/api/payments/payme — JSON-RPC Payme Merchant API."""
    config = Config.from_env()
    request_id = _request_id(request)

    if not _authorized(request, config):
        base.auth_failed(request, "payme")

        return _error(request_id, ERROR_AUTH)

    try:
        body = json.loads(request.body or b"")
    except ValueError:
        return _error(None, ERROR_PARSE)

    method = body.get("method") if isinstance(body, dict) else None
    params = body.get("params") if isinstance(body, dict) else None

    if not isinstance(method, str) or not isinstance(params, dict):
        return _error(request_id, ERROR_REQUEST)

    # Новые транзакции — только где маркетплейс открыт; заведённые Payme
    # доводит всегда (Perform, Cancel, Check, GetStatement)
    if (
        method in ("CheckPerformTransaction", "CreateTransaction")
        and (closed := base.market_closed()) is not None
    ):
        return closed

    rpc = _Rpc(request_id, params, config)
    methods = {
        "CheckPerformTransaction": rpc.check_perform,
        "CreateTransaction": rpc.create,
        "PerformTransaction": rpc.perform,
        "CancelTransaction": rpc.cancel,
        "CheckTransaction": rpc.check_transaction,
        "GetStatement": rpc.statement,
    }
    run = methods.get(method)

    return run() if run is not None else _error(request_id, ERROR_METHOD)
