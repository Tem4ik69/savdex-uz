"""
Click — SHOP API для заказов маркетплейса:
POST /market/api/payments/click/prepare (action=0) и
POST /market/api/payments/click/complete (action=1), форма
application/x-www-form-urlencoded, ответ — JSON.

- Подпись: ``sign_string = md5(click_trans_id + service_id + SECRET_KEY +
  merchant_trans_id + [merchant_prepare_id — только в Complete] + amount +
  action + sign_time)`` — строки ровно как пришли; сравнение —
  ``hmac.compare_digest``. Не та — -1.
- merchant_trans_id — номер заказа; merchant_prepare_id и
  merchant_confirm_id — номер строки market_payments.
- Сумма — в сумах с двумя знаками («1000.00») → тийины точно
  (``base.tiyin_exact``), сверяется с заказом; не та — -2.
- Коды: 0 — успех, -1 — подпись, -2 — сумма, -3 — действие не то,
  -4 — уже оплачен, -5 — заказ не найден, -6 — транзакция не найдена,
  -8 — ошибка в запросе, -9 — отменена (заказ не ждёт оплаты, оплата не
  прошла).
- Повтор Prepare с тем же click_trans_id — тот же merchant_prepare_id;
  повтор Complete по уже проведённой — тот же успех без второго
  зачисления. Complete с error < 0 (у Click оплата не прошла) — гасим.
- Ошибка в ответ на Complete — Click отменяет платёж и возвращает деньги
  покупателю.

Возврат: Merchant API Click — ``DELETE {api}/payment/reversal/{service_id}/
{payment_id}`` с заголовком ``Auth: merchant_user_id:sha1(timestamp +
SECRET_KEY):timestamp``, если задан MARKET_CLICK_MERCHANT_USER_ID; иначе —
вручную в кабинете Click (base.MANUAL_REFUND).

**Сверить с договором и документацией Click** до боевого включения:
правила подписи (порядок полей, формат amount в подписи), ответ на
повторный Complete (0 или -4), что передавать как payment_id при возврате
(click_paydoc_id или click_trans_id), сроки, в которые возможен reversal,
адрес страницы оплаты (MARKET_CLICK_PAY_URL) и её параметры.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import quote, urlencode

import httpx
from django.http import HttpRequest, HttpResponse

from savdex.market.payments import base

log = logging.getLogger("savdex.market.payments.click")

OK = 0
ERROR_SIGN = -1
ERROR_AMOUNT = -2
ERROR_ACTION = -3
ERROR_ALREADY_PAID = -4
ERROR_ORDER_NOT_FOUND = -5
ERROR_TRANSACTION_NOT_FOUND = -6
ERROR_REQUEST = -8
ERROR_CANCELLED = -9

NOTES = {
    OK: "Success",
    ERROR_SIGN: "SIGN CHECK FAILED!",
    ERROR_AMOUNT: "Incorrect parameter amount",
    ERROR_ACTION: "Action not found",
    ERROR_ALREADY_PAID: "Already paid",
    ERROR_ORDER_NOT_FOUND: "Order does not exist",
    ERROR_TRANSACTION_NOT_FOUND: "Transaction does not exist",
    ERROR_REQUEST: "Error in request from click",
    ERROR_CANCELLED: "Transaction cancelled",
}

REFUSALS = {
    base.NOT_FOUND: ERROR_ORDER_NOT_FOUND,
    base.ALREADY_PAID: ERROR_ALREADY_PAID,
    base.NOT_PAYABLE: ERROR_CANCELLED,
    base.WRONG_AMOUNT: ERROR_AMOUNT,
    # По заказу идёт другая оплата — для Click это «отменена»
    base.BUSY: ERROR_CANCELLED,
}

#: Связь с API возврата: соединение 5 с, ответ 15 с
TIMEOUT = httpx.Timeout(15.0, connect=5.0)


@dataclass(frozen=True)
class Config:
    service_id: str
    merchant_id: str
    secret_key: str
    merchant_user_id: str
    pay_url: str
    api_url: str

    @classmethod
    def from_env(cls) -> Config:
        return cls(
            service_id=base.env("MARKET_CLICK_SERVICE_ID"),
            merchant_id=base.env("MARKET_CLICK_MERCHANT_ID"),
            secret_key=base.env("MARKET_CLICK_SECRET_KEY"),
            merchant_user_id=base.env("MARKET_CLICK_MERCHANT_USER_ID"),
            pay_url=base.env("MARKET_CLICK_PAY_URL") or "https://my.click.uz/services/pay",
            api_url=base.env("MARKET_CLICK_API_URL") or "https://api.click.uz/v2/merchant",
        )


def sign(
    config: Config,
    *,
    click_trans_id: str,
    service_id: str,
    merchant_trans_id: str,
    amount: str,
    action: str,
    sign_time: str,
    merchant_prepare_id: str | None = None,
) -> str:
    """Подпись запроса Click (md5, шестнадцатеричная строкой)."""
    text = "".join(
        [
            click_trans_id,
            service_id,
            config.secret_key,
            merchant_trans_id,
            merchant_prepare_id or "",
            amount,
            action,
            sign_time,
        ]
    )

    return hashlib.md5(text.encode(), usedforsecurity=False).hexdigest()


class ClickProvider:
    name = "click"

    def enabled(self) -> bool:
        config = Config.from_env()

        # На боевом — только со списком адресов Click, как у Uzum
        return bool(
            config.service_id and config.merchant_id and config.secret_key
        ) and base.allowed_here(self.name)

    def create_invoice(
        self, order: dict[str, Any], payment: dict[str, Any], *, locale: str, back: str
    ) -> str:
        config = Config.from_env()
        query = urlencode(
            {
                "service_id": config.service_id,
                "merchant_id": config.merchant_id,
                "amount": base.som_text(int(payment["amount"])),
                "transaction_param": order["number"],
                "return_url": back,
            },
            quote_via=quote,
        )

        return f"{config.pay_url}?{query}"

    def refund(self, payment: dict[str, Any]) -> bool | None:
        """Reversal через Merchant API Click — если задан MARKET_CLICK_MERCHANT_USER_ID."""
        config = Config.from_env()
        reference = payment["provider_ref"] or ""

        if not config.merchant_user_id or not reference:
            return None

        stamp = str(int(time.time()))
        digest = hashlib.sha1((stamp + config.secret_key).encode(), usedforsecurity=False)
        url = (
            f"{config.api_url.rstrip('/')}/payment/reversal/"
            f"{quote(config.service_id, safe='')}/{quote(str(reference), safe='')}"
        )

        # Сбой связи — исключение: вернул ли Click деньги, неизвестно (refund_order)
        with httpx.Client(timeout=TIMEOUT, trust_env=False) as client:
            response = client.delete(
                url,
                headers={
                    "Accept": "application/json",
                    "Auth": f"{config.merchant_user_id}:{digest.hexdigest()}:{stamp}",
                },
            )

        try:
            answer = response.json()
        except ValueError:
            answer = {}

        code = answer.get("error_code") if isinstance(answer, dict) else None

        if response.status_code == httpx.codes.OK and code == 0:
            return True

        log.error(
            "market.payment.click.reversal_refused http=%s code=%s", response.status_code, code
        )

        return False

    def statement(self, day: date) -> list[base.StatementLine] | None:
        # Выписки за сутки в SHOP API нет: сверка — оплаты против журнала денег
        return None


PROVIDER = ClickProvider()


# ── Колбэки ─────────────────────────────────────────────────────────


def _answer(form: dict[str, str], error: int, **extra: object) -> HttpResponse:
    body = {
        "click_trans_id": base.echo(form.get("click_trans_id")),
        "merchant_trans_id": base.echo(form.get("merchant_trans_id")),
        **extra,
        "error": error,
        "error_note": NOTES.get(error, NOTES[ERROR_REQUEST]),
    }

    return HttpResponse(
        json.dumps(body, ensure_ascii=False), status=200, content_type="application/json"
    )


def _form(request: HttpRequest) -> dict[str, str]:
    return {key: str(request.POST.get(key, "")).strip() for key in request.POST}


#: Поля, без которых запрос Click не разобрать
_REQUIRED = (
    "click_trans_id",
    "service_id",
    "merchant_trans_id",
    "amount",
    "action",
    "sign_time",
    "sign_string",
)


def _verified(
    request: HttpRequest, form: dict[str, str], config: Config, *, complete: bool
) -> int | None:
    """Код ошибки разбора и подписи; всё верно — None."""
    needed = (*_REQUIRED, "merchant_prepare_id") if complete else _REQUIRED

    if any(not form.get(key) for key in needed):
        return ERROR_REQUEST

    expected = sign(
        config,
        click_trans_id=form["click_trans_id"],
        service_id=form["service_id"],
        merchant_trans_id=form["merchant_trans_id"],
        amount=form["amount"],
        action=form["action"],
        sign_time=form["sign_time"],
        merchant_prepare_id=form["merchant_prepare_id"] if complete else None,
    )

    if not hmac.compare_digest(expected.encode(), form["sign_string"].lower().encode()):
        base.auth_failed(request, "click")

        return ERROR_SIGN

    if not hmac.compare_digest(form["service_id"].encode(), config.service_id.encode()):
        return ERROR_REQUEST

    if form["action"] != ("1" if complete else "0"):
        return ERROR_ACTION

    return None


def _deny(request: HttpRequest) -> HttpResponse:
    return _answer(_form(request), ERROR_REQUEST)


@base.callback("click", _deny)
def prepare(request: HttpRequest) -> HttpResponse:
    """Prepare (action=0): проверить заказ и сумму, завести транзакцию."""
    config = Config.from_env()
    form = _form(request)

    # Новая транзакция — только где маркетплейс открыт; Complete по
    # заведённой Click доводит всегда
    if (closed := base.market_closed()) is not None:
        return closed

    if (problem := _verified(request, form, config, complete=False)) is not None:
        return _answer(form, problem)

    amount = base.tiyin_exact(form["amount"])

    if amount is None:
        return _answer(form, ERROR_AMOUNT)

    trans_id = form["click_trans_id"][:64]
    existing = base.locked("click", trans_id)

    if existing is not None:
        if existing["status"] == base.PAID:
            return _answer(form, ERROR_ALREADY_PAID)

        if existing["status"] != base.PENDING:
            return _answer(form, ERROR_CANCELLED)

        # Повтор с известным id: тот же заказ, та же сумма, и заказ всё ещё
        # ждёт оплаты (не истёк и не отменён)
        order = base.order_by_id(int(existing["order_id"]))

        if order is None or order["number"] != form["merchant_trans_id"].upper():
            return _answer(form, ERROR_TRANSACTION_NOT_FOUND)

        if int(existing["amount"]) != amount:
            return _answer(form, ERROR_AMOUNT)

        if (refused := base.refusal(order, amount)) is not None:
            return _answer(form, REFUSALS.get(refused, ERROR_CANCELLED))

        return _answer(form, OK, merchant_prepare_id=int(existing["id"]))

    payment, refusal = base.open_transaction(
        "click",
        trans_id,
        form["merchant_trans_id"],
        amount,
        provider_ref=form.get("click_paydoc_id", "")[:64] or None,
    )

    if payment is None:
        return _answer(form, REFUSALS.get(refusal or base.NOT_PAYABLE, ERROR_CANCELLED))

    return _answer(form, OK, merchant_prepare_id=int(payment["id"]))


@base.callback("click", _deny)
def complete(request: HttpRequest) -> HttpResponse:
    """Complete (action=1): провести оплату — ровно один раз."""
    config = Config.from_env()
    form = _form(request)

    if (problem := _verified(request, form, config, complete=True)) is not None:
        return _answer(form, problem)

    payment = base.locked("click", form["click_trans_id"][:64])

    if payment is None or str(payment["id"]) != form["merchant_prepare_id"]:
        return _answer(form, ERROR_TRANSACTION_NOT_FOUND)

    order = base.order_by_id(int(payment["order_id"]))

    if order is None or order["number"] != form["merchant_trans_id"].upper():
        return _answer(form, ERROR_TRANSACTION_NOT_FOUND)

    if base.tiyin_exact(form["amount"]) != int(payment["amount"]):
        return _answer(form, ERROR_AMOUNT)

    if payment["status"] == base.PAID:
        # Повтор Complete по проведённой — тот же успех, второго зачисления нет
        return _answer(form, OK, merchant_confirm_id=int(payment["id"]))

    try:
        click_error = int(form.get("error") or 0)
    except ValueError:
        click_error = 0

    if payment["status"] != base.PENDING:
        # Complete по уже погашенной (брошенная попытка, отказ): Click мог
        # списать деньги — отметка rejected_at, сверка попросит проверить.
        # Если Click сам говорит «не прошла» (error < 0) — денег нет, отметки нет
        if click_error >= 0:
            base.reject(payment, note="Click: Complete по отменённой транзакции")

        return _answer(form, ERROR_CANCELLED)

    if click_error < 0:
        base.cancel_pending(payment, note=f"Click: оплата не прошла (error {click_error})")

        return _answer(form, ERROR_CANCELLED)

    refusal = base.complete(payment)

    if refusal is not None:
        return _answer(
            form, ERROR_ALREADY_PAID if refusal == base.ALREADY_PAID else ERROR_CANCELLED
        )

    return _answer(form, OK, merchant_confirm_id=int(payment["id"]))
