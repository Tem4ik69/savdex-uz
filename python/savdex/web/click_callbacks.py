"""
Click — SHOP API для счетов сайта (тарифы и пакеты кредитов):
POST /payments/click/callback/prepare (action=0) и
POST /payments/click/callback/complete (action=1), форма
application/x-www-form-urlencoded, ответ — JSON. Настройки, подпись и
ссылка на оплату — savdex/payments/click.py.

- Выключенный Click — 404, как будто маршрута нет.
- Подпись: ``md5(click_trans_id + service_id + SECRET_KEY +
  merchant_trans_id + [merchant_prepare_id — только в Complete] + amount +
  action + sign_time)`` — строки ровно как пришли; сравнение —
  ``hmac.compare_digest``. Не та — -1. Адрес не из
  PAYMENTS_CLICK_CALLBACK_IPS — -8.
- merchant_trans_id — номер счёта; merchant_prepare_id и
  merchant_confirm_id — номер строки payment_transactions (provider = click).
- Сумма — в сумах («1500.00») → тийины точно, сверяется со счётом; не та — -2.
- Коды: 0 — успех, -1 — подпись, -2 — сумма, -3 — действие не то,
  -4 — уже оплачен, -5 — счёт не найден, -6 — транзакция не найдена,
  -8 — ошибка в запросе, -9 — отменена (счёт не ждёт оплаты, оплата не
  прошла).
- Повтор Prepare с тем же click_trans_id — тот же merchant_prepare_id;
  повтор Complete по проведённой — тот же успех без второго зачисления.
  Complete с error < 0 (у Click оплата не прошла) — гасим.
- Ошибка в ответ на Complete — Click отменяет платёж и возвращает деньги.
  Зачисление — только settlement.mark_paid, как у Uzum.
"""

from __future__ import annotations

import hmac
import json
import logging
from typing import Any

from django.db import transaction
from django.http import HttpRequest, HttpResponse

from savdex import audit
from savdex.payments import click, payme
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

PROVIDER = "click"

OK = 0
ERROR_SIGN = -1
ERROR_AMOUNT = -2
ERROR_ACTION = -3
ERROR_ALREADY_PAID = -4
ERROR_NOT_FOUND = -5
ERROR_TRANSACTION_NOT_FOUND = -6
ERROR_REQUEST = -8
ERROR_CANCELLED = -9

NOTES = {
    OK: "Success",
    ERROR_SIGN: "SIGN CHECK FAILED!",
    ERROR_AMOUNT: "Incorrect parameter amount",
    ERROR_ACTION: "Action not found",
    ERROR_ALREADY_PAID: "Already paid",
    ERROR_NOT_FOUND: "Invoice does not exist",
    ERROR_TRANSACTION_NOT_FOUND: "Transaction does not exist",
    ERROR_REQUEST: "Error in request from click",
    ERROR_CANCELLED: "Transaction cancelled",
}

#: Поля, без которых запрос Click не разобрать
REQUIRED = (
    "click_trans_id",
    "service_id",
    "merchant_trans_id",
    "amount",
    "action",
    "sign_time",
    "sign_string",
)


def _echo(value: str | None) -> str | None:
    return value if value is not None and len(value) <= 64 else None


def _answer(form: dict[str, str], error: int, **extra: object) -> HttpResponse:
    body = {
        "click_trans_id": _echo(form.get("click_trans_id")),
        "merchant_trans_id": _echo(form.get("merchant_trans_id")),
        **extra,
        "error": error,
        "error_note": NOTES.get(error, NOTES[ERROR_REQUEST]),
    }

    return HttpResponse(
        json.dumps(body, ensure_ascii=False), status=200, content_type="application/json"
    )


def _form(request: HttpRequest) -> dict[str, str]:
    return {key: str(request.POST.get(key, "")).strip() for key in request.POST}


def _verified(
    request: HttpRequest, form: dict[str, str], config: click.ClickConfig, *, complete: bool
) -> int | None:
    """Код ошибки адреса, разбора и подписи; всё верно — None."""
    ips = payme.callback_ips(PROVIDER)

    if ips and audit.client_ip(request) not in ips:
        log.warning("payment.click.bad_ip", extra={"ip": audit.client_ip(request)})

        return ERROR_REQUEST

    needed = (*REQUIRED, "merchant_prepare_id") if complete else REQUIRED

    if any(not form.get(key) for key in needed):
        return ERROR_REQUEST

    expected = click.sign(
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
        log.warning("payment.click.bad_sign", extra={"ip": audit.client_ip(request)})

        return ERROR_SIGN

    if not hmac.compare_digest(form["service_id"].encode(), config.service_id.encode()):
        return ERROR_REQUEST

    if form["action"] != ("1" if complete else "0"):
        return ERROR_ACTION

    return None


def _tx(trans_id: str, *, lock: bool = False) -> dict[str, Any] | None:
    found = _rows(
        "select * from payment_transactions where provider = 'click' "
        "and provider_transaction_id = %s limit 1" + (" for update" if lock else ""),
        [trans_id],
    )

    return found[0] if found else None


def _cancel(ctx: Context, tx: dict[str, Any]) -> None:
    _save_tx(ctx, tx, {"state": CANCELLED, "cancelled_at": eloquent.now()})


def _prepare(ctx: Context, request: HttpRequest) -> HttpResponse:
    """Prepare (action=0): проверить счёт и сумму, завести транзакцию."""
    from savdex.web.views import not_found

    if not click.enabled():
        return not_found(ctx)

    config = click.ClickConfig.from_env()
    form = _form(request)

    if (problem := _verified(request, form, config, complete=False)) is not None:
        return _answer(form, problem)

    amount = click.tiyin(form["amount"])

    if amount is None:
        return _answer(form, ERROR_AMOUNT)

    with transaction.atomic():
        trans_id = form["click_trans_id"][:64]
        existing = _tx(trans_id, lock=True)

        if existing is not None:
            if existing["state"] == PERFORMED:
                return _answer(form, ERROR_ALREADY_PAID)

            if existing["state"] != CREATED:
                return _answer(form, ERROR_CANCELLED)

            payment = _payment(int(existing["payment_id"]))

            if payment is None or payment["number"] != form["merchant_trans_id"]:
                return _answer(form, ERROR_TRANSACTION_NOT_FOUND)

            if existing["amount_minor"] != amount:
                return _answer(form, ERROR_AMOUNT)

            if payment["status"] != "pending":
                _cancel(ctx, existing)

                return _answer(
                    form, ERROR_ALREADY_PAID if payment["status"] == "paid" else ERROR_CANCELLED
                )

            return _answer(form, OK, merchant_prepare_id=int(existing["id"]))

        found = _rows(
            "select * from payments where number = %s limit 1 for update",
            [form["merchant_trans_id"][:20]],
        )

        if not found:
            return _answer(form, ERROR_NOT_FOUND)

        payment = found[0]

        if payment["status"] == "paid":
            return _answer(form, ERROR_ALREADY_PAID)

        if payment["status"] != "pending":
            return _answer(form, ERROR_CANCELLED)

        if amount != int(payment["amount"]) * 100:
            return _answer(form, ERROR_AMOUNT)

        now = eloquent.now()
        tx = orders._insert(
            "payment_transactions",
            {
                "payment_id": payment["id"],
                "provider": PROVIDER,
                "provider_transaction_id": trans_id,
                "state": CREATED,
                "amount_minor": amount,
                "currency": "UZS",
                "payload": json.dumps(
                    {"click_paydoc_id": form.get("click_paydoc_id", "")[:64] or None}
                ),
                "updated_at": now,
                "created_at": now,
            },
        )

        return _answer(form, OK, merchant_prepare_id=int(tx["id"]))


def _complete(ctx: Context, request: HttpRequest) -> HttpResponse:
    """Complete (action=1): провести оплату — ровно один раз."""
    from savdex.web.views import not_found

    if not click.enabled():
        return not_found(ctx)

    config = click.ClickConfig.from_env()
    form = _form(request)

    if (problem := _verified(request, form, config, complete=True)) is not None:
        return _answer(form, problem)

    with transaction.atomic():
        tx = _tx(form["click_trans_id"][:64], lock=True)

        if tx is None or str(tx["id"]) != form["merchant_prepare_id"]:
            return _answer(form, ERROR_TRANSACTION_NOT_FOUND)

        payment = _payment(int(tx["payment_id"]), lock=True)

        if payment is None or payment["number"] != form["merchant_trans_id"]:
            return _answer(form, ERROR_TRANSACTION_NOT_FOUND)

        if click.tiyin(form["amount"]) != tx["amount_minor"]:
            return _answer(form, ERROR_AMOUNT)

        if tx["state"] == PERFORMED:
            # Повтор Complete по проведённой — тот же успех, второго зачисления нет
            return _answer(form, OK, merchant_confirm_id=int(tx["id"]))

        try:
            click_error = int(form.get("error") or 0)
        except ValueError:
            click_error = 0

        if tx["state"] != CREATED:
            return _answer(form, ERROR_CANCELLED)

        if click_error < 0:
            # У Click оплата не прошла — денег нет, транзакцию гасим
            _cancel(ctx, tx)

            return _answer(form, ERROR_CANCELLED)

        # Счёт уже оплачен этой самой транзакцией, а «проведена» не записалась
        if (
            payment["status"] == "paid"
            and payment.get("provider") == PROVIDER
            and payment.get("external_id") == tx["provider_transaction_id"]
        ):
            _save_tx(
                ctx,
                tx,
                {"state": PERFORMED, "performed_at": payment["paid_at"] or eloquent.now()},
            )

            return _answer(form, OK, merchant_confirm_id=int(tx["id"]))

        if payment["status"] != "pending" or int(payment["amount"]) * 100 != tx["amount_minor"]:
            _cancel(ctx, tx)

            return _answer(
                form, ERROR_ALREADY_PAID if payment["status"] == "paid" else ERROR_CANCELLED
            )

        granted, _ = settlement.mark_paid(
            ctx, payment, {"provider": PROVIDER, "external_id": tx["provider_transaction_id"]}
        )

        # Зачисление не прошло — отказ: Click отменит платёж и вернёт деньги
        if not granted:
            _cancel(ctx, tx)
            fresh = _payment(int(tx["payment_id"]))

            return _answer(
                form,
                ERROR_ALREADY_PAID
                if fresh is not None and fresh["status"] == "paid"
                else ERROR_CANCELLED,
            )

        _save_tx(ctx, tx, {"state": PERFORMED, "performed_at": eloquent.now()})

        return _answer(form, OK, merchant_confirm_id=int(tx["id"]))


prepare = _callback(_prepare)
complete = _callback(_complete)
