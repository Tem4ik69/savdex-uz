"""
Payme и Click для счетов сайта — без базы: выбор провайдера кассы,
ссылка на checkout Payme, ссылка и подпись Click, разбор суммы Click.
Колбэки на настоящей базе — tests/test_web_payme_click.py.
"""

from __future__ import annotations

import base64
import hashlib

import pytest

from savdex.payments import checkout, click, payme

PAYME = {
    "PAYMENTS_PAYME_ENABLED": "true",
    "PAYMENTS_PAYME_MERCHANT_ID": "merchant-1",
    "PAYMENTS_PAYME_KEY": "payme-key",
}
CLICK = {
    "PAYMENTS_CLICK_ENABLED": "true",
    "PAYMENTS_CLICK_SERVICE_ID": "111",
    "PAYMENTS_CLICK_MERCHANT_ID": "222",
    "PAYMENTS_CLICK_SECRET_KEY": "click-secret",
}
UZUM = {"PAYMENTS_UZUM_ENABLED": "true", "PAYMENTS_UZUM_CHECKOUT_ENABLED": "true"}
СЧЁТ = {"number": "SVD-000123", "amount": 1500, "description": "Тариф «Бизнес»"}


@pytest.fixture
def окружение(monkeypatch):
    for name in [*PAYME, *CLICK, *UZUM, "PAYMENTS_DEFAULT", "APP_ENV"]:
        monkeypatch.delenv(name, raising=False)

    for name in ["PAYMENTS_PAYME_CALLBACK_IPS", "PAYMENTS_CLICK_CALLBACK_IPS"]:
        monkeypatch.delenv(name, raising=False)

    def задать(**values: str) -> None:
        for name, value in values.items():
            monkeypatch.setenv(name, value)

    return задать


def test_ничего_не_включено(окружение):
    assert checkout.available() == []
    assert checkout.checkout_enabled() is False
    assert checkout.choose("payme") is None


def test_выбор_провайдера(окружение):
    окружение(**PAYME, **CLICK, **UZUM)

    assert checkout.available() == ["uzum", "payme", "click"]
    assert checkout.choose("click") == "click"
    # Неизвестный или выключенный — первый доступный
    assert checkout.choose("paypal") == "uzum"
    assert checkout.choose(None) == "uzum"

    окружение(PAYMENTS_DEFAULT="payme")

    assert checkout.available() == ["payme", "uzum", "click"]
    assert checkout.choose(None) == "payme"


def test_без_ключей_не_включается(окружение):
    окружение(PAYMENTS_PAYME_ENABLED="true", PAYMENTS_CLICK_ENABLED="true")

    assert checkout.available() == []


def test_на_боевом_только_со_списком_адресов(окружение):
    окружение(**PAYME, **CLICK, APP_ENV="production")

    assert checkout.available() == []

    окружение(PAYMENTS_PAYME_CALLBACK_IPS="185.234.113.1", PAYMENTS_CLICK_CALLBACK_IPS="1.2.3.4")

    assert checkout.available() == ["payme", "click"]


def test_ссылка_payme(окружение):
    окружение(**PAYME)
    адрес = payme.checkout_url(СЧЁТ, "uz", "https://savdex.uz/uz/cabinet/billing")

    assert адрес.startswith("https://checkout.paycom.uz/")
    assert base64.b64decode(адрес.rsplit("/", 1)[1]).decode() == (
        "m=merchant-1;ac.invoice=SVD-000123;a=150000;c=https://savdex.uz/uz/cabinet/billing;l=uz"
    )

    # Адрес возврата с «=» сломал бы разбор — не передаётся; чужой язык — ru
    адрес = payme.checkout_url(СЧЁТ, "zh", "https://savdex.uz/?a=1")

    assert base64.b64decode(адрес.rsplit("/", 1)[1]).decode() == (
        "m=merchant-1;ac.invoice=SVD-000123;a=150000;l=ru"
    )


def test_чек_payme_без_икпу(окружение):
    окружение(**PAYME)

    assert payme.detail(СЧЁТ) is None


def test_ссылка_и_подпись_click(окружение):
    окружение(**CLICK)

    assert click.pay_url(СЧЁТ, "https://savdex.uz/cabinet/billing") == (
        "https://my.click.uz/services/pay?service_id=111&merchant_id=222&amount=1500.00"
        "&transaction_param=SVD-000123&return_url=https%3A%2F%2Fsavdex.uz%2Fcabinet%2Fbilling"
    )

    config = click.ClickConfig.from_env()
    ждём = hashlib.md5(
        b"CL-1111click-secretSVD-0001235551500.0012026-11-23 10:00:00", usedforsecurity=False
    ).hexdigest()

    assert (
        click.sign(
            config,
            click_trans_id="CL-1",
            service_id="111",
            merchant_trans_id="SVD-000123",
            merchant_prepare_id="555",
            amount="1500.00",
            action="1",
            sign_time="2026-11-23 10:00:00",
        )
        == ждём
    )


@pytest.mark.parametrize(
    ("value", "ждём"),
    [
        ("1500", 150000),
        ("1500.00", 150000),
        ("1500.5", 150050),
        (" 1500.50 ", 150050),
        ("1500.001", None),
        ("0", None),
        ("-1", None),
        ("abc", None),
        ("", None),
        ("NaN", None),
        ("1" * 40, None),
    ],
)
def test_сумма_click(value, ждём):
    assert click.tiyin(value) == ждём
