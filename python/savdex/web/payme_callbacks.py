"""
Payme — Merchant API (JSON-RPC 2.0) для счетов сайта (тарифы и пакеты
кредитов): POST /payments/payme/callback. Настройки и ссылка на оплату —
savdex/payments/payme.py.

Методы: CheckPerformTransaction, CreateTransaction, PerformTransaction,
CancelTransaction, CheckTransaction, GetStatement. Ответ — всегда HTTP 200,
ошибка — ``{"error": {"code", "message": {ru, uz, en}, "data"}, "id"}``.

- Выключенный Payme — 404, как будто маршрута нет.
- Авторизация — ``Authorization: Basic base64("Paycom:<KEY>")``, ключ —
  PAYMENTS_PAYME_KEY, сравнение — ``hmac.compare_digest``; не тот или адрес
  не из PAYMENTS_PAYME_CALLBACK_IPS — -32504.
- Номер счёта — ``account.<поле>`` (PAYMENTS_PAYME_ACCOUNT_FIELD, по
  умолчанию invoice); сумма — в тийинах и только из счёта.
- Ошибки счёта: -31050 не найден, -31051 не ждёт оплаты (отменён),
  -31052 уже оплачен, -31053 по счёту идёт другая транзакция Payme;
  -31001 — сумма не та; -31003 — транзакция не найдена; -31008 —
  операцию выполнить нельзя; -31007 — отменить проведённую нельзя.
- Транзакция — строка payment_transactions (provider = payme): created —
  1, performed — 2, cancelled без проведения — -1, cancelled после
  проведения (возврат) — -2. Время Payme и причина отмены — в payload.
- Срок жизни созданной транзакции — 12 часов: CreateTransaction и
  PerformTransaction после него гасят её с причиной 4 и отвечают -31008.
  Брошенная попытка (созданная, старше PAYMENTS_PAYME_PENDING_MINUTES,
  по умолчанию 30) новой не мешает: её гасим.
- Повтор любого метода с тем же id отвечает тем же (время — из базы):
  второго зачисления и второй отмены нет. Зачисление — только
  settlement.mark_paid, как у Uzum.
- Возврат: сначала счёт возвращают в админке (статус «Возвращён»), затем
  отменяют транзакцию в кабинете Payme Business — Payme зовёт
  CancelTransaction. Отмену проведённой по не возвращённому счёту не
  принимаем (-31007).

ChangePassword не поддерживается (-32601): ключ живёт только в окружении.
"""

from __future__ import annotations

import base64
import calendar
import hmac
import json
import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from django.db import transaction
from django.http import HttpRequest, HttpResponse

from savdex import audit
from savdex.payments import payme
from savdex.web import eloquent, orders, settlement
from savdex.web.cabinet import _rows
from savdex.web.payment_callbacks import (
    CANCELLED,
    CREATED,
    PERFORMED,
    _callback,
    _payment,
    _save_tx,
)
from savdex.web.shared import Context

log = logging.getLogger("savdex.payments")

PROVIDER = "payme"

#: Причины отмены Payme: 3 — ошибка выполнения (счёт уже не ждёт оплаты), 4 — истёк срок
REASON_ORDER_GONE = 3
REASON_TIMEOUT = 4

#: Целые из JSON — в пределах bigint
BIGINT_MAX = 2**63 - 1

ERROR_AUTH = -32504
ERROR_PARSE = -32700
ERROR_REQUEST = -32600
ERROR_METHOD = -32601
ERROR_AMOUNT = -31001
ERROR_TRANSACTION_NOT_FOUND = -31003
ERROR_CANNOT_CANCEL = -31007
ERROR_CANNOT_PERFORM = -31008
ERROR_NOT_FOUND = -31050
ERROR_NOT_PAYABLE = -31051
ERROR_PAID = -31052
ERROR_BUSY = -31053
ERROR_OTHER_INVOICE = -31099

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
        "Счёт оплачен, отменить транзакцию нельзя",
        "Hisob to‘langan, tranzaksiyani bekor qilib bo‘lmaydi",
        "The invoice is paid, the transaction cannot be cancelled",
    ),
    ERROR_CANNOT_PERFORM: (
        "Невозможно выполнить операцию",
        "Amalni bajarib bo‘lmaydi",
        "Unable to perform operation",
    ),
    ERROR_NOT_FOUND: ("Счёт не найден", "Hisob topilmadi", "Invoice not found"),
    ERROR_NOT_PAYABLE: (
        "Счёт не ждёт оплаты",
        "Hisob to‘lovni kutmayapti",
        "The invoice is not awaiting payment",
    ),
    ERROR_PAID: ("Счёт уже оплачен", "Hisob allaqachon to‘langan", "Invoice already paid"),
    ERROR_BUSY: (
        "По счёту уже идёт другая оплата",
        "Hisob bo‘yicha boshqa to‘lov amalga oshirilmoqda",
        "Another payment for the invoice is in progress",
    ),
    ERROR_OTHER_INVOICE: (
        "Транзакция заведена на другой счёт",
        "Tranzaksiya boshqa hisobga ochilgan",
        "The transaction belongs to another invoice",
    ),
}


# ── Общее ───────────────────────────────────────────────────────────


def _echo(value: object) -> object:
    """id запроса для эха: строка до 64 знаков или целое в пределах bigint."""
    if isinstance(value, bool):
        return None

    if isinstance(value, str):
        return value if len(value) <= 64 else None

    if isinstance(value, int):
        return value if -BIGINT_MAX <= value <= BIGINT_MAX else None

    return None


def _response(body: dict[str, Any]) -> HttpResponse:
    return HttpResponse(
        json.dumps(body, ensure_ascii=False), status=200, content_type="application/json"
    )


def _result(request_id: object, result: dict[str, Any]) -> HttpResponse:
    return _response({"jsonrpc": "2.0", "id": _echo(request_id), "result": result})


def _error(request_id: object, code: int, data: str | None = None) -> HttpResponse:
    ru, uz, en = MESSAGES.get(code, MESSAGES[ERROR_CANNOT_PERFORM])

    return _response(
        {
            "jsonrpc": "2.0",
            "id": _echo(request_id),
            "error": {"code": code, "message": {"ru": ru, "uz": uz, "en": en}, "data": data},
        }
    )


def _int(value: object) -> int | None:
    """Целое из JSON в пределах 0…2⁶³-1; прочее — None."""
    if isinstance(value, bool):
        return None

    if isinstance(value, float) and value.is_integer():
        value = int(value)

    if isinstance(value, int) and 0 <= value <= BIGINT_MAX:
        return value

    return None


def _ms(moment: datetime | None) -> int:
    """Время из базы (UTC, без пояса) — в миллисекундах; нет — 0 (так ждёт Payme)."""
    if moment is None:
        return 0

    return calendar.timegm(moment.timetuple()) * 1000


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _timed_out(tx: dict[str, Any]) -> bool:
    created: datetime = tx["created_at"]

    return _utcnow() - created > timedelta(milliseconds=payme.TIMEOUT_MS)


def _pending_minutes() -> int:
    """Срок, после которого созданная транзакция считается брошенной: 1…720 минут."""
    try:
        value = int(os.environ.get("PAYMENTS_PAYME_PENDING_MINUTES") or 30)
    except ValueError:
        value = 30

    return min(max(1, value), 720)


def _payload(tx: dict[str, Any]) -> dict[str, Any]:
    raw = tx.get("payload")

    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        data = None

    return data if isinstance(data, dict) else {}


def _tx(trans_id: str, *, lock: bool = False) -> dict[str, Any] | None:
    if trans_id == "":
        return None

    found = _rows(
        "select * from payment_transactions where provider = 'payme' "
        "and provider_transaction_id = %s limit 1" + (" for update" if lock else ""),
        [trans_id],
    )

    return found[0] if found else None


def _state(tx: dict[str, Any]) -> int:
    if tx["state"] == CREATED:
        return 1

    if tx["state"] == PERFORMED:
        return 2

    return -2 if tx["performed_at"] is not None else -1


def _fields(tx: dict[str, Any]) -> dict[str, Any]:
    """Поля транзакции для CheckTransaction и GetStatement."""
    return {
        "create_time": _ms(tx["created_at"]),
        "perform_time": _ms(tx["performed_at"]),
        "cancel_time": _ms(tx["cancelled_at"]),
        "transaction": str(tx["id"]),
        "state": _state(tx),
        "reason": _payload(tx).get("reason"),
    }


def _cancel(ctx: Context, tx: dict[str, Any], reason: int | None) -> None:
    """Погасить транзакцию: время отмены и причина (в payload)."""
    payload = {**_payload(tx), "reason": reason}
    _save_tx(
        ctx,
        tx,
        {"state": CANCELLED, "cancelled_at": eloquent.now(), "payload": json.dumps(payload)},
    )


def _paid_by(payment: dict[str, Any] | None, tx: dict[str, Any]) -> bool:
    """Счёт оплачен именно этой транзакцией Payme (её след пишет mark_paid)."""
    return (
        payment is not None
        and payment["status"] == "paid"
        and payment.get("provider") == PROVIDER
        and payment.get("external_id") == tx["provider_transaction_id"]
    )


# ── Методы ──────────────────────────────────────────────────────────


class _Rpc:
    def __init__(
        self, ctx: Context, request_id: object, params: dict[str, Any], config: payme.PaymeConfig
    ) -> None:
        self.ctx = ctx
        self.id = request_id
        self.params = params
        self.config = config

    def number(self) -> str:
        account = self.params.get("account")
        value = account.get(self.config.account_field) if isinstance(account, dict) else None

        if isinstance(value, bool) or not isinstance(value, str | int):
            return ""

        return str(value).strip()[:20]

    def transaction_id(self) -> str:
        value = self.params.get("id")

        return value.strip()[:64] if isinstance(value, str) else ""

    def invoice_error(self, code: int) -> HttpResponse:
        return _error(self.id, code, None if code == ERROR_AMOUNT else self.config.account_field)

    def payable(self, *, lock: bool = False) -> tuple[dict[str, Any] | None, int]:
        """Счёт по номеру ждёт оплаты на эту сумму; иначе — код отказа."""
        number = self.number()

        if number == "":
            return None, ERROR_NOT_FOUND

        found = _rows(
            "select * from payments where number = %s limit 1" + (" for update" if lock else ""),
            [number],
        )

        if not found:
            return None, ERROR_NOT_FOUND

        payment = found[0]

        if payment["status"] == "paid":
            return None, ERROR_PAID

        if payment["status"] != "pending":
            return None, ERROR_NOT_PAYABLE

        if _int(self.params.get("amount")) != int(payment["amount"]) * 100:
            return None, ERROR_AMOUNT

        return payment, 0

    def busy(self, payment: dict[str, Any], trans_id: str) -> bool:
        """
        По счёту живая транзакция Payme с другим id. Брошенную (старше
        PAYMENTS_PAYME_PENDING_MINUTES) гасим — новой оплате она не мешает.
        """
        stale = _utcnow() - timedelta(minutes=_pending_minutes())

        for other in _rows(
            "select * from payment_transactions where payment_id = %s and provider = 'payme' "
            "and state = 'created' and provider_transaction_id <> %s for update",
            [payment["id"], trans_id],
        ):
            if other["created_at"] < stale:
                _cancel(self.ctx, other, REASON_TIMEOUT)
            else:
                return True

        return False

    def check_perform(self) -> HttpResponse:
        payment, code = self.payable()

        if payment is None:
            return self.invoice_error(code)

        if self.busy(payment, ""):
            return self.invoice_error(ERROR_BUSY)

        result: dict[str, Any] = {"allow": True}

        if (receipt := payme.detail(payment)) is not None:
            result["detail"] = receipt

        return _result(self.id, result)

    def create(self) -> HttpResponse:
        trans_id = self.transaction_id()
        payme_time = _int(self.params.get("time"))

        if trans_id == "" or payme_time is None:
            return _error(self.id, ERROR_REQUEST)

        existing = _tx(trans_id, lock=True)

        if existing is not None:
            payment = _payment(existing["payment_id"])

            if payment is None or payment["number"] != self.number():
                return self.invoice_error(ERROR_OTHER_INVOICE)

            if _int(self.params.get("amount")) != existing["amount_minor"]:
                return _error(self.id, ERROR_AMOUNT)

            if existing["state"] != CREATED:
                return _error(self.id, ERROR_CANNOT_PERFORM)

            if _timed_out(existing):
                _cancel(self.ctx, existing, REASON_TIMEOUT)

                return _error(self.id, ERROR_CANNOT_PERFORM)

            # Счёт за это время оплатили иначе или отменили — гасим
            if payment["status"] != "pending":
                _cancel(self.ctx, existing, REASON_ORDER_GONE)

                return _error(self.id, ERROR_CANNOT_PERFORM)

            return self.created(existing)

        payment, code = self.payable(lock=True)

        if payment is None:
            return self.invoice_error(code)

        if self.busy(payment, trans_id):
            return self.invoice_error(ERROR_BUSY)

        now = eloquent.now()
        tx = orders._insert(
            "payment_transactions",
            {
                "payment_id": payment["id"],
                "provider": PROVIDER,
                "provider_transaction_id": trans_id,
                "state": CREATED,
                "amount_minor": int(payment["amount"]) * 100,
                "currency": "UZS",
                "payload": json.dumps({"time": payme_time, "reason": None}),
                "updated_at": now,
                "created_at": now,
            },
        )

        return self.created({**tx, "created_at": now})

    def created(self, tx: dict[str, Any]) -> HttpResponse:
        return _result(
            self.id,
            {"create_time": _ms(tx["created_at"]), "transaction": str(tx["id"]), "state": 1},
        )

    def perform(self) -> HttpResponse:
        tx = _tx(self.transaction_id(), lock=True)

        if tx is None:
            return _error(self.id, ERROR_TRANSACTION_NOT_FOUND)

        if tx["state"] == PERFORMED:
            return self.performed(tx, tx["performed_at"])

        if tx["state"] != CREATED:
            return _error(self.id, ERROR_CANNOT_PERFORM)

        if _timed_out(tx):
            _cancel(self.ctx, tx, REASON_TIMEOUT)

            return _error(self.id, ERROR_CANNOT_PERFORM)

        payment = _payment(tx["payment_id"], lock=True)

        # Счёт уже оплачен этой самой транзакцией, а «проведена» не записалась
        if _paid_by(payment, tx):
            assert payment is not None
            done = payment["paid_at"] or eloquent.now()
            _save_tx(self.ctx, tx, {"state": PERFORMED, "performed_at": done})

            return self.performed(tx, done)

        if (
            payment is None
            or payment["status"] != "pending"
            or int(payment["amount"]) * 100 != tx["amount_minor"]
        ):
            _cancel(self.ctx, tx, REASON_ORDER_GONE)

            return _error(self.id, ERROR_CANNOT_PERFORM)

        granted, _ = settlement.mark_paid(
            self.ctx, payment, {"provider": PROVIDER, "external_id": tx["provider_transaction_id"]}
        )

        # Зачисление не прошло (компанию удалили, счёт успели оплатить) —
        # не проводим: Payme отменит транзакцию и вернёт деньги
        if not granted:
            _cancel(self.ctx, tx, REASON_ORDER_GONE)

            return _error(self.id, ERROR_CANNOT_PERFORM)

        now = eloquent.now()
        _save_tx(self.ctx, tx, {"state": PERFORMED, "performed_at": now})

        return self.performed(tx, now)

    def performed(self, tx: dict[str, Any], when: datetime | None) -> HttpResponse:
        return _result(
            self.id, {"transaction": str(tx["id"]), "perform_time": _ms(when), "state": 2}
        )

    def cancel(self) -> HttpResponse:
        tx = _tx(self.transaction_id(), lock=True)

        if tx is None:
            return _error(self.id, ERROR_TRANSACTION_NOT_FOUND)

        raw = self.params.get("reason")
        reason = _int(raw)

        if raw is not None and (reason is None or reason > 32767):
            return _error(self.id, ERROR_REQUEST)

        if tx["state"] == CREATED:
            _cancel(self.ctx, tx, reason)
        elif tx["state"] == PERFORMED:
            payment = _payment(tx["payment_id"], lock=True)

            # Возврат — только по счёту, который уже вернули в админке:
            # иначе тариф остался бы, а деньги ушли назад
            if payment is None or payment["status"] != "refunded":
                log.warning("payment.payme.cancel_paid", extra={"payment_id": tx["payment_id"]})

                return _error(self.id, ERROR_CANNOT_CANCEL)

            _cancel(self.ctx, tx, reason)

        fresh = _tx(tx["provider_transaction_id"])
        assert fresh is not None
        found = _fields(fresh)

        return _result(
            self.id,
            {
                "transaction": found["transaction"],
                "cancel_time": found["cancel_time"],
                "state": found["state"],
            },
        )

    def check_transaction(self) -> HttpResponse:
        tx = _tx(self.transaction_id())

        if tx is None:
            return _error(self.id, ERROR_TRANSACTION_NOT_FOUND)

        return _result(self.id, _fields(tx))

    def statement(self) -> HttpResponse:
        start, end = _int(self.params.get("from")), _int(self.params.get("to"))

        if start is None or end is None or start > end:
            return _error(self.id, ERROR_REQUEST)

        found = []

        for tx in _rows(
            "select t.*, p.number from payment_transactions t "
            "join payments p on p.id = t.payment_id "
            "where t.provider = 'payme' "
            # Время Payme и наше расходятся на секунды: сутки запаса с
            # каждой стороны, точный отбор — по времени Payme ниже
            "and t.created_at between (to_timestamp(%s / 1000.0) at time zone 'UTC') "
            "- interval '1 day' and (to_timestamp(%s / 1000.0) at time zone 'UTC') "
            "+ interval '1 day' order by t.created_at, t.id",
            [start, end],
        ):
            payme_time = _int(_payload(tx).get("time"))

            if payme_time is not None and start <= payme_time <= end:
                found.append(
                    {
                        "id": tx["provider_transaction_id"],
                        "time": payme_time,
                        "amount": tx["amount_minor"],
                        "account": {self.config.account_field: tx["number"]},
                        **_fields(tx),
                        "receivers": None,
                    }
                )

        return _result(self.id, {"transactions": found})


def _authorized(request: HttpRequest, config: payme.PaymeConfig) -> bool:
    ips = payme.callback_ips(PROVIDER)

    if ips and audit.client_ip(request) not in ips:
        return False

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


def _endpoint(ctx: Context, request: HttpRequest) -> HttpResponse:
    """POST /payments/payme/callback — JSON-RPC Payme Merchant API."""
    from savdex.web.views import not_found

    if not payme.enabled():
        return not_found(ctx)

    config = payme.PaymeConfig.from_env()

    try:
        body = json.loads(request.body or b"")
    except ValueError:
        body = None

    request_id = body.get("id") if isinstance(body, dict) else None

    if not _authorized(request, config):
        log.warning("payment.payme.auth_failed", extra={"ip": audit.client_ip(request)})

        return _error(request_id, ERROR_AUTH)

    if body is None:
        return _error(None, ERROR_PARSE)

    method = body.get("method") if isinstance(body, dict) else None
    params = body.get("params") if isinstance(body, dict) else None

    if not isinstance(method, str) or not isinstance(params, dict):
        return _error(request_id, ERROR_REQUEST)

    rpc = _Rpc(ctx, request_id, params, config)
    methods = {
        "CheckPerformTransaction": rpc.check_perform,
        "CreateTransaction": rpc.create,
        "PerformTransaction": rpc.perform,
        "CancelTransaction": rpc.cancel,
        "CheckTransaction": rpc.check_transaction,
        "GetStatement": rpc.statement,
    }
    run = methods.get(method)

    if run is None:
        return _error(request_id, ERROR_METHOD)

    # Одной транзакцией и под замками: зачисление и «проведена» не
    # расходятся при сбое, а два одинаковых запроса разом не дают двух итогов
    with transaction.atomic():
        return run()


endpoint = _callback(_endpoint)
