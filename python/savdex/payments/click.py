"""
Click для счетов сайта (тарифы и пакеты кредитов): настройки из окружения,
подпись запросов и ссылка на страницу оплаты. Колбэки SHOP API (Prepare и
Complete) — savdex/web/click_callbacks.py.

Ссылка на оплату — без обращения к Click: ``{pay_url}?service_id=…&
merchant_id=…&amount=1500.00&transaction_param=SVD-000123&return_url=…``.
Транзакцию заводит сам Click вызовом Prepare.

Ключи — только в окружении (секреты GitHub или .env машины):

- ``PAYMENTS_CLICK_ENABLED`` — включить; без ключей не включится;
- ``PAYMENTS_CLICK_SERVICE_ID``, ``PAYMENTS_CLICK_MERCHANT_ID``,
  ``PAYMENTS_CLICK_SECRET_KEY`` — сервис, поставщик и ключ подписи;
- ``PAYMENTS_CLICK_PAY_URL`` — по умолчанию https://my.click.uz/services/pay;
- ``PAYMENTS_CLICK_CALLBACK_IPS`` — адреса Click через запятую; на боевом
  (APP_ENV=production) без них Click выключен.

Возврат денег — вручную в кабинете Click (как у Uzum): колбэка о возврате
в SHOP API нет.

**Сверить с договором и документацией Click** до боевого включения: правила
подписи, ответ на повторный Complete, адрес страницы оплаты и её параметры.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote, urlencode

from savdex.payments.payme import callback_ips, production


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


@dataclass(frozen=True)
class ClickConfig:
    service_id: str
    merchant_id: str
    secret_key: str
    pay_url: str

    @classmethod
    def from_env(cls) -> ClickConfig:
        return cls(
            service_id=_env("PAYMENTS_CLICK_SERVICE_ID"),
            merchant_id=_env("PAYMENTS_CLICK_MERCHANT_ID"),
            secret_key=_env("PAYMENTS_CLICK_SECRET_KEY"),
            pay_url=_env("PAYMENTS_CLICK_PAY_URL") or "https://my.click.uz/services/pay",
        )


def enabled() -> bool:
    """Включён флагом, ключи заданы; на боевом — ещё и со списком адресов Click."""
    from savdex.payments.checkout import env_flag

    config = ClickConfig.from_env()

    return (
        env_flag("PAYMENTS_CLICK_ENABLED")
        and bool(config.service_id and config.merchant_id and config.secret_key)
        and (not production() or bool(callback_ips("click")))
    )


def som_text(amount_som: int) -> str:
    """Сумма счёта (целые сумы) → «1500.00»."""
    return f"{int(amount_som)}.00"


def tiyin(value: str) -> int | None:
    """
    Сумма от Click в сумах («1500», «1500.5», «1500.00») → тийины, точно:
    больше двух знаков после точки, не число, ноль и минус — None.
    """
    text = value.strip()

    if text == "" or len(text) > 32:
        return None

    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None

    if not amount.is_finite() or amount <= 0:
        return None

    cents = amount * 100

    if cents != cents.to_integral_value() or cents > 2**63 - 1:
        return None

    return int(cents)


def sign(
    config: ClickConfig,
    *,
    click_trans_id: str,
    service_id: str,
    merchant_trans_id: str,
    amount: str,
    action: str,
    sign_time: str,
    merchant_prepare_id: str | None = None,
) -> str:
    """
    Подпись запроса Click: md5(click_trans_id + service_id + SECRET_KEY +
    merchant_trans_id + [merchant_prepare_id] + amount + action + sign_time).
    """
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


def pay_url(payment: dict[str, Any], back_url: str) -> str:
    """Ссылка на страницу оплаты Click для счёта."""
    config = ClickConfig.from_env()
    query = urlencode(
        {
            "service_id": config.service_id,
            "merchant_id": config.merchant_id,
            "amount": som_text(int(payment["amount"])),
            "transaction_param": payment["number"],
            "return_url": back_url,
        },
        quote_via=quote,
    )

    return f"{config.pay_url}?{query}"
