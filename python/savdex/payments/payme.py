"""
Payme для счетов сайта (тарифы и пакеты кредитов): настройки из окружения,
ссылка на checkout и чек для CheckPerformTransaction. Колбэки Merchant API —
savdex/web/payme_callbacks.py.

Ссылка на оплату — без обращения к Payme: ``{checkout}/base64("m=…;
ac.invoice=SVD-000123;a=<тийины>;c=<возврат>;l=ru")``. Транзакцию заводит
сам Payme вызовом CreateTransaction, когда покупатель нажмёт «Оплатить».

Ключи — только в окружении (секреты GitHub или .env машины):

- ``PAYMENTS_PAYME_ENABLED`` — включить; без ключей не включится;
- ``PAYMENTS_PAYME_MERCHANT_ID``, ``PAYMENTS_PAYME_KEY`` — касса и ключ
  (колбэк приходит с ``Authorization: Basic base64("Paycom:<KEY>")``);
- ``PAYMENTS_PAYME_CHECKOUT_URL`` — по умолчанию https://checkout.paycom.uz
  (песочница — https://checkout.test.paycom.uz);
- ``PAYMENTS_PAYME_ACCOUNT_FIELD`` — поле account (по умолчанию invoice);
- ``PAYMENTS_PAYME_CALLBACK_IPS`` — адреса Payme через запятую; на боевом
  (APP_ENV=production) без них Payme выключен;
- ``PAYMENTS_PAYME_IKPU``, ``PAYMENTS_PAYME_PACKAGE_CODE``,
  ``PAYMENTS_PAYME_VAT_PERCENT`` — чек; не заданы — берутся у Uzum
  (``PAYMENTS_UZUM_SPIC``, ``…_PACKAGE_CODE``, ``…_VAT_PERCENT``): услуга
  та же. Без ИКПУ чек не передаётся.

**Сверить с договором и документацией Payme** до боевого включения: состав
``detail``, адрес checkout и параметры ссылки.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Any

#: Срок жизни созданной транзакции у Payme — 12 часов, в миллисекундах
TIMEOUT_MS = 43_200_000


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def production() -> bool:
    return os.environ.get("APP_ENV", "local") == "production"


def callback_ips(provider: str) -> list[str]:
    """Белый список адресов провайдера: PAYMENTS_<ПРОВАЙДЕР>_CALLBACK_IPS через запятую."""
    raw = _env(f"PAYMENTS_{provider.upper()}_CALLBACK_IPS")

    return [ip.strip() for ip in raw.split(",") if ip.strip()]


@dataclass(frozen=True)
class PaymeConfig:
    merchant_id: str
    key: str
    checkout_url: str
    account_field: str
    ikpu: str
    package_code: str
    vat_percent: int

    @classmethod
    def from_env(cls) -> PaymeConfig:
        try:
            vat = int(_env("PAYMENTS_PAYME_VAT_PERCENT") or _env("PAYMENTS_UZUM_VAT_PERCENT") or 12)
        except ValueError:
            vat = 12

        return cls(
            merchant_id=_env("PAYMENTS_PAYME_MERCHANT_ID"),
            key=_env("PAYMENTS_PAYME_KEY"),
            checkout_url=_env("PAYMENTS_PAYME_CHECKOUT_URL") or "https://checkout.paycom.uz",
            account_field=_env("PAYMENTS_PAYME_ACCOUNT_FIELD") or "invoice",
            ikpu=_env("PAYMENTS_PAYME_IKPU") or _env("PAYMENTS_UZUM_SPIC"),
            package_code=_env("PAYMENTS_PAYME_PACKAGE_CODE") or _env("PAYMENTS_UZUM_PACKAGE_CODE"),
            vat_percent=vat if 0 <= vat <= 100 else 12,
        )


def enabled() -> bool:
    """Включён флагом, ключи заданы; на боевом — ещё и со списком адресов Payme."""
    from savdex.payments.checkout import env_flag

    config = PaymeConfig.from_env()

    return (
        env_flag("PAYMENTS_PAYME_ENABLED")
        and bool(config.merchant_id and config.key)
        and (not production() or bool(callback_ips("payme")))
    )


def checkout_url(payment: dict[str, Any], locale: str, back_url: str) -> str:
    """Ссылка на checkout Payme для счёта; сумма — в тийинах."""
    config = PaymeConfig.from_env()
    params = ";".join(
        [
            f"m={config.merchant_id}",
            f"ac.{config.account_field}={payment['number']}",
            f"a={int(payment['amount']) * 100}",
            # «;» и «=» в адресе возврата сломали бы разбор параметров —
            # такой адрес не передаём (Payme вернёт на свою страницу)
            *([f"c={back_url}"] if back_url and not set(";=") & set(back_url) else []),
            f"l={locale if locale in ('ru', 'uz', 'en') else 'ru'}",
        ]
    )
    encoded = base64.b64encode(params.encode()).decode()

    return f"{config.checkout_url.rstrip('/')}/{encoded}"


def detail(payment: dict[str, Any]) -> dict[str, Any] | None:
    """Чек: одна позиция на всю сумму; без ИКПУ — None (чек не передаём)."""
    config = PaymeConfig.from_env()

    if config.ikpu == "":
        return None

    item: dict[str, Any] = {
        "title": (payment["description"] or "Услуги площадки SAVDEX")[:128],
        "price": int(payment["amount"]) * 100,
        "count": 1,
        "code": config.ikpu,
        "vat_percent": config.vat_percent,
    }

    if config.package_code != "":
        item["package_code"] = config.package_code

    return {"receipt_type": 0, "items": [item]}
