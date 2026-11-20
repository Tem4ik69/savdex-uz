"""
Uzum — Merchant API для заказов маркетплейса:
POST /market/api/payments/uzum/{check|create|confirm|reverse|status}.

Образец — колбэки тарифов сайта (savdex/web/payment_callbacks.py, класс
_Merchant): те же операции, коды ошибок и форма ответа. Код тарифов не
меняется; у маркетплейса — **свой serviceId** (MARKET_UZUM_SERVICE_ID) и
свои логин и пароль: оплаты заказов не смешиваются с оплатами тарифов.

- Basic-авторизация (MARKET_UZUM_CALLBACK_LOGIN / _PASSWORD) —
  ``hmac.compare_digest``; serviceId обязателен и сверяется.
- Номер заказа — в ``params.<поле>`` (MARKET_UZUM_ACCOUNT_FIELD, по
  умолчанию ``order``); сумма — тийины, сверяется с заказом.
- create с уже известным transId — отказ 10010 (как у тарифов): вторая
  строка и второе зачисление невозможны.
- confirm и reverse — под замком (заказ, затем оплата). confirm позже
  MARKET_UZUM_CONFIRM_TIMEOUT минут (по умолчанию 30) после create — гасим,
  Uzum вернёт деньги.
- reverse проведённой транзакции — только если заказ ждёт возврата
  (refund_pending): так делается возврат — отменой транзакции в кабинете
  Uzum. Иначе — 10017, как у тарифов.
- Белый список адресов Uzum (MARKET_UZUM_CALLBACK_IPS) на боевом
  обязателен: без него провайдер выключен (docs/marketplace-security.md,
  раздел 3).

Страница оплаты — шаблон адреса MARKET_UZUM_PAY_URL с подстановками
{service_id}, {order}, {amount} (тийины), {amount_som}, {return_url}.

**Сверить с договором и документацией Uzum Merchant API** до боевого
включения: имена полей запроса (serviceId, transId, params, amount,
timestamp), коды ошибок, HTTP-статусы ответов с ошибкой, разрешена ли
отмена (reverse) уже подтверждённой транзакции и как выглядит ссылка на
оплату услуги в приложении Uzum.
"""

from __future__ import annotations

import base64
import hmac
import json
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import quote

from django.http import HttpRequest, HttpResponse

from savdex.market.payments import base

log = logging.getLogger("savdex.market.payments.uzum")

#: Коды ошибок Merchant API Uzum — те же, что у тарифов
ERROR_AUTH = 10001
ERROR_BAD_OPERATION = 10003
ERROR_PARAMS_MISSING = 10005
ERROR_BAD_SERVICE_ID = 10006
ERROR_INVOICE_NOT_FOUND = 10007
ERROR_ALREADY_PAID = 10008
ERROR_INVOICE_CANCELLED = 10009
ERROR_TRANSACTION_EXISTS = 10010
ERROR_BAD_AMOUNT = 10011
ERROR_TRANSACTION_NOT_FOUND = 10014
ERROR_TRANSACTION_CANCELLED = 10015
ERROR_ALREADY_CONFIRMED = 10016
ERROR_CANNOT_REVERSE = 10017
ERROR_ALREADY_REVERSED = 10018

#: Причина отказа общего слоя → код Uzum
REFUSALS = {
    base.NOT_FOUND: ERROR_INVOICE_NOT_FOUND,
    base.ALREADY_PAID: ERROR_ALREADY_PAID,
    base.NOT_PAYABLE: ERROR_INVOICE_CANCELLED,
    base.WRONG_AMOUNT: ERROR_BAD_AMOUNT,
    base.BUSY: ERROR_TRANSACTION_EXISTS,
}

#: Статус оплаты → состояние транзакции в ответе status
STATE_LABELS = {
    base.PENDING: "CREATED",
    base.PAID: "CONFIRMED",
    base.CANCELLED: "REVERSED",
    base.REFUNDED: "REVERSED",
}


@dataclass(frozen=True)
class Config:
    service_id: str
    login: str
    password: str
    pay_url: str
    account_field: str
    confirm_timeout: int

    @classmethod
    def from_env(cls) -> Config:
        return cls(
            service_id=base.env("MARKET_UZUM_SERVICE_ID"),
            login=base.env("MARKET_UZUM_CALLBACK_LOGIN"),
            password=base.env("MARKET_UZUM_CALLBACK_PASSWORD"),
            pay_url=base.env("MARKET_UZUM_PAY_URL"),
            account_field=base.env("MARKET_UZUM_ACCOUNT_FIELD") or "order",
            # MARKET_UZUM_CONFIRM_TIMEOUT — с потолком (base.pending_minutes)
            confirm_timeout=base.pending_minutes("uzum"),
        )


class UzumProvider:
    name = "uzum"

    def enabled(self) -> bool:
        config = Config.from_env()

        if not (config.service_id and config.login and config.password and config.pay_url):
            return False

        # На боевом — только со списком адресов Uzum (раздел 3 правил)
        return base.allowed_here(self.name)

    def create_invoice(
        self, order: dict[str, Any], payment: dict[str, Any], *, locale: str, back: str
    ) -> str:
        config = Config.from_env()
        values = {
            "{service_id}": quote(config.service_id, safe=""),
            "{order}": quote(str(order["number"]), safe=""),
            "{amount}": str(int(payment["amount"])),
            "{amount_som}": base.som_text(int(payment["amount"])),
            "{return_url}": quote(back, safe=""),
            "{lang}": locale,
        }
        url = config.pay_url

        for key, value in values.items():
            url = url.replace(key, value)

        return url

    def refund(self, payment: dict[str, Any]) -> bool | None:
        # Merchant API не даёт продавцу вернуть деньги запросом: возврат —
        # отменой транзакции в кабинете Uzum, Uzum зовёт reverse
        return None

    def statement(self, day: date) -> list[base.StatementLine] | None:
        # Реестра транзакций через API нет: сверка — оплаты против журнала денег
        return None


PROVIDER = UzumProvider()


# ── Колбэк ──────────────────────────────────────────────────────────


def _json(data: dict[str, Any], status: int = 200) -> HttpResponse:
    return HttpResponse(
        json.dumps(data, ensure_ascii=False), status=status, content_type="application/json"
    )


def _amount(value: object) -> int | None:
    """
    Сумма в тийинах: целое число или строка из цифр ASCII (не «²» и не
    арабские цифры — их isdigit тоже считает цифрами) в пределах bigint;
    иначе None.
    """
    if isinstance(value, bool):
        return None

    if isinstance(value, str):
        text = value.strip()

        if not (text.isascii() and text.isdigit() and len(text) <= 19):
            return None

        value = int(text)

    if isinstance(value, int) and 0 <= value <= base.BIGINT_MAX:
        return value

    return None


class _Merchant:
    def __init__(self, request: HttpRequest, config: Config) -> None:
        self.request = request
        self.config = config

        try:
            parsed = json.loads(request.body or b"{}")
        except ValueError:
            parsed = {}

        self.data: dict[str, Any] = parsed if isinstance(parsed, dict) else {}

    def text(self, key: str) -> str:
        value = self.data.get(key)

        if isinstance(value, bool) or not isinstance(value, str | int):
            return ""

        return str(value).strip()

    def number(self) -> str:
        params = self.data.get("params")
        value = params.get(self.config.account_field) if isinstance(params, dict) else None

        if isinstance(value, bool) or not isinstance(value, str | int):
            return ""

        return str(value).strip()

    def error(
        self, code: int, extra: dict[str, Any] | None = None, status: int = 400
    ) -> HttpResponse:
        return _json(
            {
                "serviceId": base.echo(self.data.get("serviceId")),
                "timestamp": base.echo(self.data.get("timestamp")),
                "transId": base.echo(self.data.get("transId")),
                "status": "FAILED",
                "errorCode": code,
                **(extra or {}),
            },
            status,
        )

    def authorized(self) -> bool:
        header = self.request.headers.get("Authorization", "")
        user, secret = "", ""

        if header[:6].lower() == "basic ":
            try:
                decoded = base64.b64decode(header[6:].strip()).decode()
            except (ValueError, UnicodeDecodeError):
                decoded = ""

            if ":" in decoded:
                user, secret = decoded.split(":", 1)

        # Оба сравнения — всегда, чтобы время ответа не подсказывало, что совпало
        login_ok = hmac.compare_digest(self.config.login.encode(), user.encode())
        password_ok = hmac.compare_digest(self.config.password.encode(), secret.encode())

        return bool(self.config.login and self.config.password) and login_ok and password_ok

    def order_data(self, payment: dict[str, Any]) -> dict[str, Any]:
        order = base.order_by_id(int(payment["order_id"]))

        return {"order": order["number"] if order else None, "amount": int(payment["amount"])}

    # ── Операции ────────────────────────────────────────────────────

    def check(self) -> HttpResponse:
        number = self.number()

        if number == "":
            return self.error(ERROR_PARAMS_MISSING)

        amount = _amount(self.data.get("amount"))

        if amount is None and "amount" not in self.data:
            found = base.order_by_number(number)
            amount = int(found["total"]) if found else None

        order, problem = base.check(number, amount)

        if problem is not None:
            return self.error(REFUSALS[problem])

        assert order is not None

        return _json(
            {
                "serviceId": base.echo(self.data.get("serviceId")),
                "timestamp": base.echo(self.data.get("timestamp")),
                "status": "OK",
                "data": {"order": order["number"], "amount": int(order["total"])},
            }
        )

    def create(self) -> HttpResponse:
        trans_id = self.text("transId")[:64]
        amount = _amount(self.data.get("amount"))

        if trans_id == "" or amount is None or self.number() == "":
            return self.error(ERROR_PARAMS_MISSING)

        existing = base.by_transaction("uzum", trans_id)

        if existing is not None:
            return self.error(
                ERROR_TRANSACTION_EXISTS, {"transTime": base.ms(existing["created_at"])}
            )

        payment, problem = base.open_transaction("uzum", trans_id, self.number(), amount)

        if payment is None:
            return self.error(REFUSALS[problem or base.NOT_PAYABLE])

        return _json(
            {
                "serviceId": base.echo(self.data.get("serviceId")),
                "transId": trans_id,
                "status": "CREATED",
                "transTime": base.ms(payment["created_at"]),
                "data": self.order_data(payment),
                "amount": int(payment["amount"]),
            }
        )

    def confirm(self) -> HttpResponse:
        payment = base.locked("uzum", self.text("transId")[:64])

        if payment is None:
            return self.error(ERROR_TRANSACTION_NOT_FOUND)

        # Uzum пришёл проводить то, что мы уже погасили (брошенная попытка,
        # reverse, срок): отказ — и отметка rejected_at, сверка попросит
        # проверить, что деньги вернулись
        if payment["status"] == base.CANCELLED:
            base.reject(payment, note="Uzum: confirm по отменённой транзакции")

            return self.error(ERROR_TRANSACTION_CANCELLED)

        if payment["status"] == base.REFUNDED:
            base.reject(payment, note="Uzum: confirm по возвращённой транзакции")

            return self.error(
                ERROR_ALREADY_REVERSED, {"reverseTime": base.ms(payment["refunded_at"])}
            )

        if payment["status"] == base.PAID:
            return self.error(
                ERROR_ALREADY_CONFIRMED, {"confirmTime": base.ms(payment["performed_at"])}
            )

        deadline = payment["created_at"] + timedelta(minutes=self.config.confirm_timeout)

        if deadline < datetime.now(UTC).replace(tzinfo=None):
            base.reject(payment, note="Uzum: подтверждение позже срока")

            return self.error(ERROR_TRANSACTION_CANCELLED)

        problem = base.complete(payment)

        if problem is not None:
            return self.error(REFUSALS.get(problem, ERROR_INVOICE_CANCELLED))

        fresh = base.payment(int(payment["id"]))
        assert fresh is not None

        return _json(
            {
                "serviceId": base.echo(self.data.get("serviceId")),
                "transId": fresh["provider_transaction_id"],
                "status": "CONFIRMED",
                "confirmTime": base.ms(fresh["performed_at"]),
                "data": self.order_data(fresh),
                "amount": int(fresh["amount"]),
            }
        )

    def reverse(self) -> HttpResponse:
        payment = base.locked("uzum", self.text("transId")[:64])

        if payment is None:
            return self.error(ERROR_TRANSACTION_NOT_FOUND)

        if payment["status"] in (base.CANCELLED, base.REFUNDED):
            moment = payment["cancelled_at"] or payment["refunded_at"]

            return self.error(ERROR_ALREADY_REVERSED, {"reverseTime": base.ms(moment)})

        if payment["status"] == base.PAID:
            # Возврат проведённой — только заказу, который ждёт возврата
            if not base.refund_payment(payment, note="Uzum: отмена транзакции (reverse)"):
                return self.error(ERROR_CANNOT_REVERSE)
        else:
            base.cancel_pending(payment, note="Uzum: отмена транзакции (reverse)")

        fresh = base.payment(int(payment["id"]))
        assert fresh is not None

        return _json(
            {
                "serviceId": base.echo(self.data.get("serviceId")),
                "transId": fresh["provider_transaction_id"],
                "status": "REVERSED",
                "reverseTime": base.ms(fresh["refunded_at"] or fresh["cancelled_at"]),
                "data": self.order_data(fresh),
                "amount": int(fresh["amount"]),
            }
        )

    def status(self) -> HttpResponse:
        payment = base.by_transaction("uzum", self.text("transId")[:64])

        if payment is None:
            return self.error(ERROR_TRANSACTION_NOT_FOUND)

        return _json(
            {
                "serviceId": base.echo(self.data.get("serviceId")),
                "transId": payment["provider_transaction_id"],
                "status": STATE_LABELS.get(payment["status"], payment["status"]),
                "transTime": base.ms(payment["created_at"]),
                "confirmTime": base.ms(payment["performed_at"]) or None,
                "reverseTime": base.ms(payment["cancelled_at"] or payment["refunded_at"]) or None,
                "data": self.order_data(payment),
                "amount": int(payment["amount"]),
            }
        )


def _deny(request: HttpRequest) -> HttpResponse:
    return _json({"status": "FAILED", "errorCode": ERROR_AUTH}, 401)


@base.callback("uzum", _deny)
def merchant(request: HttpRequest, operation: str) -> HttpResponse:
    """POST /market/api/payments/uzum/<operation>."""
    config = Config.from_env()
    handler = _Merchant(request, config)

    if not handler.authorized():
        base.auth_failed(request, "uzum")

        return handler.error(ERROR_AUTH, status=401)

    if not hmac.compare_digest(handler.text("serviceId").encode(), config.service_id.encode()):
        return handler.error(ERROR_BAD_SERVICE_ID)

    # Новые транзакции — только где маркетплейс открыт; заведённые
    # (confirm, reverse, status) провайдер доводит всегда
    if operation in ("check", "create") and (closed := base.market_closed()) is not None:
        return closed

    operations = {
        "check": handler.check,
        "create": handler.create,
        "confirm": handler.confirm,
        "reverse": handler.reverse,
        "status": handler.status,
    }
    run = operations.get(operation)

    return run() if run is not None else handler.error(ERROR_BAD_OPERATION)
