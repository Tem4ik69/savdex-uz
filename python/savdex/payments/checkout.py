"""
Онлайн-касса: регистрация платежа в Uzum и ссылка на платёжную
страницу (этап 7, шаг 53), выбор провайдера — Uzum, Payme или Click
(available, choose; ссылки Payme и Click — savdex/payments/payme.py и
click.py). Копия PaymentGatewayManager::default и
UzumGateway::createCheckout — без записи в базу: номер заказа Uzum
счёту дописывает вызывающий.

Флаги включения читаются как (bool) env() у Laravel, а не как в
UzumConfig: «yes» и «off» у PHP — оба true, и касса включается или нет
у обеих сторон одинаково.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from savdex.payments.uzum import СВЯЗЬ, UzumConfig, UzumError, call

log = logging.getLogger("savdex.payments")

#: UzumGateway::CURRENCY_UZS, ::SESSION_TIMEOUT_SECS
CURRENCY_UZS = 860
SESSION_TIMEOUT_SECS = 1800

#: UzumGateway::PAY_URL_KEYS
PAY_URL_KEYS = ("paymentRedirectUrl", "redirectUrl", "paymentUrl", "payUrl", "formUrl", "url")

#: Провайдеры онлайн-оплаты счетов сайта — в этом порядке на странице
GATEWAYS = ("uzum", "payme", "click")


class GatewayError(Exception):
    """PaymentGatewayException: касса отказала, счёт остаётся для оплаты переводом."""


def env_flag(name: str) -> bool:
    """(bool) env($name, false): true/false словами, иначе строка по правилам PHP."""
    raw = os.environ.get(name)

    if raw is None:
        return False

    word = raw.strip().lower()

    if word in ("true", "(true)"):
        return True

    if word in ("false", "(false)", "null", "(null)", "empty", "(empty)"):
        return False

    return raw not in ("", "0")


def default_provider() -> str:
    """config('payments.default'): env('PAYMENTS_DEFAULT', 'uzum')."""
    return os.environ.get("PAYMENTS_DEFAULT", "uzum")


def enabled(provider: str) -> bool:
    """
    PaymentGatewayManager::enabled — только Uzum: по нему решает вебхук
    кассы Uzum (payments/<провайдер>/callback). У Payme и Click свои
    колбэки и своя проверка (payme.enabled, click.enabled).
    """
    return provider == "uzum" and env_flag("PAYMENTS_UZUM_ENABLED")


def ready(provider: str) -> bool:
    """Провайдером можно оплатить счёт: включён, ключи заданы, касса открыта."""
    from savdex.payments import click, payme

    if provider == "uzum":
        return env_flag("PAYMENTS_UZUM_CHECKOUT_ENABLED") and enabled("uzum")

    if provider == "payme":
        return payme.enabled()

    if provider == "click":
        return click.enabled()

    return False


def available() -> list[str]:
    """Провайдеры для оплаты счёта; провайдер по умолчанию (PAYMENTS_DEFAULT) — первым."""
    found = [provider for provider in GATEWAYS if ready(provider)]
    default = default_provider()

    return sorted(found, key=lambda provider: provider != default)


def choose(requested: object) -> str | None:
    """Выбранный покупателем провайдер, если им можно платить; иначе — первый доступный."""
    found = available()

    if isinstance(requested, str) and requested in found:
        return requested

    return found[0] if found else None


def checkout_enabled() -> bool:
    """BillingController::checkoutEnabled: открыта касса хотя бы одного провайдера."""
    return bool(available())


def gateway() -> UzumConfig:
    """Настройки Uzum; выключенный — отказ."""
    if not enabled("uzum"):
        raise GatewayError("Провайдер uzum выключен — включите его в конфигурации и задайте ключи")

    return UzumConfig.from_env()


def language(locale: str) -> str:
    """UzumGateway::contentLanguage: форма знает три языка."""
    return {"uz": "uz-UZ", "en": "en-EN"}.get(locale, "ru-RU")


def _require(config: UzumConfig) -> None:
    for key in ("base_url", "terminal_id", "secret_key"):
        if getattr(config, key).strip() == "":
            raise GatewayError(
                f"Uzum не настроен: не задан ключ «{key}» "
                f"(переменная окружения PAYMENTS_UZUM_{key.upper()})"
            )


def _fiscal_cart(config: UzumConfig, payment: dict[str, Any]) -> dict[str, Any]:
    """UzumGateway::fiscalCart: одна позиция на всю сумму; без ИКПУ — ничего."""
    if config.spic == "":
        return {}

    amount = int(payment["amount"]) * 100
    receipt: dict[str, Any] = {"spic": config.spic, "vatPercent": config.vat_percent}

    if config.package_code != "":
        receipt["packageCode"] = config.package_code

    if config.tin != "":
        receipt["TIN"] = config.tin

    product = payment.get("plan_id") or payment.get("credit_pack_id") or payment["id"]
    item = {
        "productId": f"{payment['purpose']}-{product}",
        "title": (payment["description"] or "Услуги площадки SAVDEX")[:255],
        "quantity": 1,
        "unitPrice": amount,
        "total": amount,
        "receiptParams": receipt,
    }

    return {
        "merchantParams": {
            "cart": {
                "cartId": payment["number"],
                "receiptType": "PURCHASE",
                "total": amount,
                "items": [item],
            }
        }
    }


def payment_page_url(result: dict[Any, Any]) -> str | None:
    """UzumGateway::paymentPageUrl: известные поля, затем любой https-адрес."""
    for key in PAY_URL_KEYS:
        value = result.get(key)

        if isinstance(value, str) and value.startswith("http"):
            return value

    for value in result.values():
        if isinstance(value, str) and value.startswith("https://"):
            return value

        if isinstance(value, dict) and (nested := payment_page_url(value)) is not None:
            return nested

        if isinstance(value, list):
            found = payment_page_url(dict(enumerate(value)))

            if found is not None:
                return found

    return None


def create_checkout(
    config: UzumConfig,
    payment: dict[str, Any],
    locale: str,
    client: httpx.Client | None = None,
    back_url: str | None = None,
) -> dict[str, str]:
    """
    UzumGateway::createCheckout: регистрация платежа, ссылка на форму и
    номер заказа Uzum. Сбой сети и отказ Uzum — GatewayError.
    """
    _require(config)
    # Явный адрес из окружения; иначе — страница тарифов того домена
    # и языка, откуда ушёл покупатель (back_url): вход живёт только на
    # одном домене, и возврат на APP_URL другого выбрасывал ко входу
    return_url = (
        os.environ.get("PAYMENTS_UZUM_RETURN_URL")
        or back_url
        or os.environ.get("APP_URL", "").rstrip("/") + "/cabinet/billing"
    )
    body: dict[str, Any] = {
        "amount": int(payment["amount"]) * 100,
        "clientId": str(payment["company_id"]),
        "currency": CURRENCY_UZS,
        "paymentDetails": (payment["description"] or "")[:1024],
        "orderNumber": payment["number"][:36],
        "sessionTimeoutSecs": SESSION_TIMEOUT_SECS,
        "viewType": "REDIRECT",
        "successUrl": return_url,
        "failureUrl": return_url,
        "paymentParams": {"operationType": "PAYMENT", "payType": "ONE_STEP"},
        **_fiscal_cart(config, payment),
    }

    # Статический адрес для белого списка Uzum — только свой прокси, не
    # общий из окружения: Laravel прокси окружения тоже не берёт
    own = client is None
    client = client or httpx.Client(timeout=СВЯЗЬ, proxy=config.proxy or None, trust_env=False)

    try:
        result = call(config, "/api/v1/payment/register", body, client, language(locale))
    except UzumError as error:
        raise GatewayError(str(error)) from error
    finally:
        if own:
            client.close()

    order_id = result.get("orderId")
    url = payment_page_url(result)

    if not isinstance(order_id, str) or order_id == "" or url is None:
        log.warning("payment.uzum.register_unexpected", extra={"result": result})

        raise GatewayError("Uzum зарегистрировал платёж, но не вернул orderId или ссылку оплаты")

    log.info("payment.uzum.registered", extra={"order": order_id, "payment": payment["number"]})

    return {"redirect_url": url, "order_id": order_id}
