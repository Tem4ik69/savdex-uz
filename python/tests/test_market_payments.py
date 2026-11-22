"""
Оплата заказов маркетплейса, этап 2 (savdex/market/payments): Uzum, Payme,
Click — правила docs/marketplace-security.md, раздел 3.

По каждому провайдеру:

- чужая подпись или пароль — отказ;
- сумма не та — отказ;
- оплата проводит заказ и пишет начисление в журнал денег один раз;
- повтор колбэка ничего не начисляет второй раз;
- оплата истёкшего или отменённого заказа — отказ (провайдер вернёт деньги);
- второй живой счёт на тот же заказ невозможен;
- чужой заказ — 404 при открытии счёта;
- возврат: refund_pending → refunded — ровно один раз.

Payme — JSON-RPC запросом к нашему адресу с заголовком Basic; Click — формой
с посчитанной подписью. Нужен PostgreSQL (SAVDEX_PARITY_PG_URL).
"""

from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest

from savdex.market.payments import base, click, payme

from .pg_admin import PYTHON, КОРЕНЬ, ОКРУЖЕНИЕ, django, sql, журнал, нужна_база, свежая_база
from .test_market import _json, _post, _компания, _продавец, _сотрудник, _товар
from .test_market_orders import (
    _id,
    _manage,
    _python,
    _в_корзину,
    _оформить,
    _покупатель,
    _статус,
)
from .test_web_forms import xsrf, отправить
from .web_site import адрес, открыть

#: Ключи провайдеров для проверок — выдуманные, только этого файла
ОПЛАТА = {
    "MARKET_UZUM_SERVICE_ID": "777001",
    "MARKET_UZUM_CALLBACK_LOGIN": "uzum-market",
    "MARKET_UZUM_CALLBACK_PASSWORD": "uzum-market-pass",
    "MARKET_UZUM_PAY_URL": (
        "https://pay.uzum.example/service?serviceId={service_id}&order={order}&amount={amount}"
    ),
    "MARKET_PAYME_MERCHANT_ID": "65a1b2c3d4e5f6a7b8c9d0e1",
    "MARKET_PAYME_KEY": "payme-test-key",
    "MARKET_CLICK_SERVICE_ID": "35001",
    "MARKET_CLICK_MERCHANT_ID": "21001",
    "MARKET_CLICK_SECRET_KEY": "click-test-secret",
}

#: Цена кубиков — 90 000 сумов
ЦЕНА = 9_000_000

# ── Без базы ────────────────────────────────────────────────────────


def test_сумма_click_в_тийины_точно():
    assert base.tiyin_exact("90000.00") == 9_000_000
    assert base.tiyin_exact("90000") == 9_000_000
    assert base.tiyin_exact("1000.5") == 100_050
    assert base.som_text(100_050) == "1000.50" and base.som_text(9_000_000) == "90000.00"

    for плохая in ("1000.001", "0", "-5", "abc", "", None, True, "NaN", "Infinity"):
        assert base.tiyin_exact(плохая) is None, плохая


def test_подпись_click(monkeypatch):
    monkeypatch.setenv("MARKET_CLICK_SECRET_KEY", "k")
    config = click.Config.from_env()
    поля = {
        "click_trans_id": "1",
        "service_id": "2",
        "merchant_trans_id": "ABCDEFGH23",
        "amount": "1000.00",
        "action": "0",
        "sign_time": "2026-11-21 10:00:00",
    }
    assert (
        click.sign(config, **поля)
        == hashlib.md5(b"12kABCDEFGH231000.0002026-11-21 10:00:00").hexdigest()
    )
    # В Complete между номером заказа и суммой — merchant_prepare_id
    assert click.sign(config, **{**поля, "action": "1"}, merchant_prepare_id="77") == (
        hashlib.md5(b"12kABCDEFGH23771000.0012026-11-21 10:00:00").hexdigest()
    )


def test_провайдер_без_ключей_выключен(monkeypatch):
    from savdex.market.payments import uzum

    for name in ОПЛАТА:
        monkeypatch.delenv(name, raising=False)

    assert not any(base.enabled(name) for name in base.PROVIDERS)

    for name, value in ОПЛАТА.items():
        monkeypatch.setenv(name, value)

    monkeypatch.setenv("APP_ENV", "local")
    assert all(base.enabled(name) for name in base.PROVIDERS)

    # На боевом — только со списком адресов провайдера (docs/marketplace-security.md,
    # раздел 3): у Uzum, Payme и Click одинаково
    monkeypatch.setenv("APP_ENV", "production")

    for name in base.PROVIDERS:
        monkeypatch.delenv(f"MARKET_{name.upper()}_CALLBACK_IPS", raising=False)

    assert not any(base.enabled(name) for name in base.PROVIDERS)

    for name in base.PROVIDERS:
        monkeypatch.setenv(f"MARKET_{name.upper()}_CALLBACK_IPS", "10.0.0.1, 10.0.0.2")

    assert uzum.PROVIDER.enabled() and all(base.enabled(name) for name in base.PROVIDERS)
    assert base.callback_ips("uzum") == ["10.0.0.1", "10.0.0.2"]


def test_кривые_значения_не_роняют(monkeypatch):
    from savdex.market.payments import uzum

    # «²» и арабские цифры isdigit считает цифрами — сумма из них не число
    for плохая in ("²", "٣٤", "1" * 30, -1, 2**70, True, 1.5, None):
        assert uzum._amount(плохая) is None, плохая
    assert uzum._amount("9000000") == 9_000_000

    # Переполнение Decimal и длинные строки — не сумма, а не 500
    for плохая in ("1e999999999", "9" * 40, "1e-999999999", "sNaN"):
        assert base.tiyin_exact(плохая) is None, плохая

    # reason — smallint, from/to — bigint: всё вне — не число для нас
    assert payme._int(2**70) is None and payme._int(-1) is None and payme._int(5) == 5

    # Эхо — только строки до 64 знаков и целые в пределах bigint
    assert base.echo("x" * 64) == "x" * 64
    assert base.echo("x" * 65) is None and base.echo(2**70) is None
    assert base.echo({"a": 1}) is None and base.echo(True) is None


def test_сроки_pending_с_потолком(monkeypatch):
    from datetime import timedelta

    from savdex.market.payments import uzum

    monkeypatch.setenv("MARKET_PAYME_PENDING_MINUTES", "99999999999999999999")
    monkeypatch.setenv("MARKET_CLICK_PENDING_MINUTES", "-5")
    monkeypatch.setenv("MARKET_UZUM_CONFIRM_TIMEOUT", str(10**30))
    assert base.pending_minutes("payme") == 720
    assert base.pending_minutes("click") == 1
    assert base.pending_minutes("uzum") == 1440
    assert uzum.Config.from_env().confirm_timeout == 1440
    assert base.max_pending_minutes() == 1440
    # Никакого OverflowError у expire и у проверки брошенной попытки
    assert timedelta(minutes=base.max_pending_minutes())
    monkeypatch.setenv("MARKET_CLICK_PENDING_MINUTES", "не число")
    assert base.pending_minutes("click") == 30


def test_лимиты_без_файлового_кэша_предупреждают_один_раз(monkeypatch, caplog):
    import logging

    from django.test import RequestFactory

    monkeypatch.setenv("CACHE_STORE", "array")
    monkeypatch.setattr(base, "_store_warned", False)

    # Не боевой (тестовый, проверки) — тишина: там кэш в памяти — обычное дело
    monkeypatch.setenv("APP_ENV", "local")

    with caplog.at_level(logging.WARNING, logger="savdex.market.payments"):
        assert base._throttled(RequestFactory().post("/")) is False

    assert not any("throttle_disabled" in r.getMessage() for r in caplog.records)

    monkeypatch.setenv("APP_ENV", "production")

    with caplog.at_level(logging.WARNING, logger="savdex.market.payments"):
        for _ in range(3):
            assert base._throttled(RequestFactory().post("/")) is False

    assert sum("throttle_disabled" in r.getMessage() for r in caplog.records) == 1


def test_адрес_возврата_без_точки_с_запятой(monkeypatch):
    for name, value in ОПЛАТА.items():
        monkeypatch.setenv(name, value)

    monkeypatch.setenv("MARKET_PAYMENT_RETURN_URL", "https://x.example/o/{number};c=evil")
    assert base.return_url("ABCDEFGH23", "https://site/o") == "https://site/o"
    monkeypatch.setenv("MARKET_PAYMENT_RETURN_URL", "https://x.example/o/{number}")
    assert base.return_url("ABCDEFGH23", "https://site/o") == "https://x.example/o/ABCDEFGH23"

    # Адрес с «=» в ссылку Payme не попадает вовсе
    url = payme.PROVIDER.create_invoice(
        {"number": "ABCDEFGH23"}, {"amount": ЦЕНА}, locale="ru", back="https://x.example/?a=b"
    )
    params = base64.b64decode(url.rsplit("/", 1)[1]).decode()
    assert params == "m=65a1b2c3d4e5f6a7b8c9d0e1;ac.order=ABCDEFGH23;a=9000000;l=ru"


def test_сигнал_сверки_только_цифры(monkeypatch):
    from datetime import date

    from savdex.market.payments import reconcile

    отчёты = [
        reconcile.Report("payme", payments=3, problems=["ABCDEFGH23", "оплата 5 …"]),
        reconcile.Report("*", problems=[]),
    ]
    итог = reconcile.summary(отчёты, date(2026, 11, 20))
    assert итог == "сверка оплат за 2026-11-20: расхождений 2 (payme 2, общее 0)"
    assert "ABCDEFGH23" not in итог

    # Адрес не задан — сигнала нет, сверка не падает
    monkeypatch.delenv(reconcile.PING_KEY, raising=False)
    assert reconcile.signal(отчёты, date(2026, 11, 20)) is None


def test_адрес_тестового_клиента():
    """Колбэки проверок ниже ходят с 127.0.0.1 — на этом держатся белые списки в них."""
    from django.test import RequestFactory

    from savdex import audit

    assert audit.client_ip(RequestFactory().post("/")) == "127.0.0.1"


def test_ссылка_payme(monkeypatch):
    for name, value in ОПЛАТА.items():
        monkeypatch.setenv(name, value)

    url = payme.PROVIDER.create_invoice(
        {"number": "ABCDEFGH23"}, {"amount": ЦЕНА}, locale="uz", back="https://x.example/o"
    )
    prefix = "https://checkout.paycom.uz/"
    assert url.startswith(prefix)
    assert base64.b64decode(url[len(prefix) :]).decode() == (
        "m=65a1b2c3d4e5f6a7b8c9d0e1;ac.order=ABCDEFGH23;a=9000000;c=https://x.example/o;l=uz"
    )


# ── Данные ──────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def сайт() -> Iterator[str]:
    свежая_база()

    with адрес() as root:
        yield root


@pytest.fixture(scope="module")
def магазин(сайт) -> dict[str, Any]:
    продавец = _продавец(_компания("Bolajon Toys", "bolajon-toys"))
    _, кубики = _товар(продавец, "toys", "Кубики деревянные", "cubes", price=90_000, stock=500)
    sql(
        "insert into market_pickup_points (code, name, address) "
        "values ('chilonzor', 'ПВЗ Чиланзар', 'Ташкент, Чиланзар, 9-й квартал')"
    )

    return {"кубики": кубики}


def _заказ(сайт: str, магазин: dict[str, Any], method: str = "card") -> tuple[int, str, int]:
    """Заказ одной коробки кубиков: (покупатель, номер, id)."""
    uid = _покупатель()
    _в_корзину(uid, магазин["кубики"])
    ответ = _оформить(сайт, uid, 90_000, method=method)
    assert ответ["status"] == 201, ответ["body"]
    number = _json(ответ)["order"]["number"]

    return uid, number, _id(number)


def _платить(
    сайт: str, number: str, uid: int | None, provider: str, env: dict[str, str] | None = None
) -> dict[str, Any]:
    return отправить(
        сайт,
        f"/market/api/orders/{number}/pay",
        lambda: None,
        uid=uid,
        body={"provider": provider},
        headers={"Accept": "application/json", "X-XSRF-TOKEN": xsrf()},
        env=ОПЛАТА if env is None else env,
    )["ответ"]


#: Как на боевом: маркетплейс закрыт (market_open ложно), у провайдеров —
#: белые списки с адресом тестового клиента
ЗАКРЫТ = {
    "APP_ENV": "production",
    "DJANGO_ALLOWED_HOSTS": "*",
    "MARKET_UZUM_CALLBACK_IPS": "127.0.0.1",
    "MARKET_PAYME_CALLBACK_IPS": "127.0.0.1",
    "MARKET_CLICK_CALLBACK_IPS": "127.0.0.1",
}


def _payme_raw(
    сайт: str,
    method: str,
    params: dict[str, Any],
    key: str = "payme-test-key",
    who: str = "Paycom",
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    return открыть(
        сайт,
        "/market/api/payments/payme",
        headers={"Authorization": "Basic " + base64.b64encode(f"{who}:{key}".encode()).decode()},
        env={**ОПЛАТА, **(env or {})},
        method="POST",
        body=json.dumps({"id": 7, "method": method, "params": params}),
        content_type="application/json",
    )


def _payme(
    сайт: str,
    method: str,
    params: dict[str, Any],
    key: str = "payme-test-key",
    who: str = "Paycom",
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    ответ = _payme_raw(сайт, method, params, key, who, env)
    assert ответ["status"] == 200, ответ["body"]

    return dict(json.loads(ответ["body"]))


def _uzum(
    сайт: str,
    operation: str,
    body: dict[str, Any],
    auth: tuple[str, str] = ("uzum-market", "uzum-market-pass"),
    env: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    ответ = открыть(
        сайт,
        f"/market/api/payments/uzum/{operation}",
        headers={"Authorization": "Basic " + base64.b64encode(":".join(auth).encode()).decode()},
        env={**ОПЛАТА, **(env or {})},
        method="POST",
        body=json.dumps({"serviceId": "777001", "timestamp": 1, **body}),
        content_type="application/json",
    )

    if ответ["status"] == 404:
        return 404, {}

    return ответ["status"], dict(json.loads(ответ["body"]))


def _click(
    сайт: str,
    step: str,
    поля: dict[str, str],
    secret: str = "click-test-secret",
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Запрос Click формой: подпись — md5 по правилам SHOP API, считаем здесь же."""
    action = "0" if step == "prepare" else "1"
    form = {
        "service_id": "35001",
        "click_paydoc_id": "555" + поля["click_trans_id"],
        "action": action,
        "error": "0",
        "error_note": "Success",
        "sign_time": "2026-11-21 10:00:00",
        **поля,
    }
    подпись = (
        form["click_trans_id"]
        + form["service_id"]
        + secret
        + form["merchant_trans_id"]
        + (form.get("merchant_prepare_id", "") if step == "complete" else "")
        + form["amount"]
        + form["action"]
        + form["sign_time"]
    )
    form["sign_string"] = hashlib.md5(подпись.encode()).hexdigest()
    ответ = открыть(
        сайт,
        f"/market/api/payments/click/{step}",
        env={**ОПЛАТА, **(env or {})},
        method="POST",
        body=urlencode(form),
        content_type="application/x-www-form-urlencoded",
    )

    if ответ["status"] == 404:
        return {"status": 404}

    assert ответ["status"] == 200, ответ["body"]

    return dict(json.loads(ответ["body"]))


def _python_env(code: str, env: dict[str, str] | None = None) -> str:
    """Код в процессе с ключами провайдеров (ОПЛАТА), как на сервере."""
    итог = subprocess.run(
        [sys.executable, "manage.py", "shell", "-c", code],
        cwd=PYTHON,
        env={**ОКРУЖЕНИЕ, **ОПЛАТА, **(env or {}), "PYTHONPATH": str(PYTHON)},
        capture_output=True,
        text=True,
    )
    assert итог.returncode == 0, итог.stderr[-3000:]

    return итог.stdout.strip().splitlines()[-1]


def _журнал(pk: int) -> dict[str, int]:
    return {
        account: int(total)
        for account, total in sql(
            "select account, sum(amount) from market_ledger where order_id = %s group by account",
            [pk],
        )
    }


def _групп(pk: int) -> int:
    [(count,)] = sql(
        "select count(distinct entry_group) from market_ledger where order_id = %s", [pk]
    )

    return int(count)


def _оплаты(pk: int) -> list[tuple[str, str]]:
    return [
        (str(provider), str(status))
        for provider, status in sql(
            "select provider, status from market_payments where order_id = %s order by id", [pk]
        )
    ]


def _отменить(сайт: str, uid: int, number: str) -> None:
    ответ = _post(сайт, f"/market/api/orders/{number}/cancel", uid)
    assert ответ["status"] == 200, ответ["body"]


def _ms() -> int:
    return int(time.time() * 1000)


# ── Счёт со страницы заказа ─────────────────────────────────────────


@нужна_база
def test_счёт_только_свой_и_один_живой(сайт, магазин):
    import psycopg

    uid, number, pk = _заказ(сайт, магазин)
    чужой = _покупатель()

    assert _платить(сайт, number, None, "payme")["status"] == 401
    assert _платить(сайт, number, чужой, "payme")["status"] == 404
    assert _платить(сайт, "ZZZZZZZZZZ", uid, "payme")["status"] == 404
    assert _платить(сайт, number, uid, "crypto")["status"] == 422
    # Провайдер без ключей выключен
    assert _платить(сайт, number, uid, "uzum", env={})["status"] == 422
    assert _оплаты(pk) == []

    первый = _платить(сайт, number, uid, "payme")
    assert первый["status"] == 200, первый["body"]
    адрес_оплаты = _json(первый)["redirect"]
    prefix = "https://checkout.paycom.uz/"
    assert адрес_оплаты.startswith(prefix)
    параметры = base64.b64decode(адрес_оплаты[len(prefix) :]).decode()
    assert f"ac.order={number};a={ЦЕНА};" in параметры

    # Повтор — тот же счёт, второго нет
    assert _json(_платить(сайт, number, uid, "payme"))["redirect"] == адрес_оплаты
    assert _оплаты(pk) == [("payme", "created")]

    # Сменил способ — прежний не начатый счёт гасится, живой по-прежнему один
    clicks = _json(_платить(сайт, number, uid, "click"))["redirect"]
    assert clicks.startswith("https://my.click.uz/services/pay?")
    assert f"transaction_param={number}" in clicks and "amount=90000.00" in clicks
    assert _оплаты(pk) == [("payme", "cancelled"), ("click", "created")]

    # Второй живой счёт на заказ не пропустит и сама база
    with pytest.raises(psycopg.errors.UniqueViolation):
        sql(
            "insert into market_payments (order_id, provider, amount, status) "
            "values (%s, 'uzum', %s, 'created')",
            [pk, ЦЕНА],
        )

    # При получении — платить картой нечего
    наличные_uid, наличные, _ = _заказ(сайт, магазин, method="cash")
    assert _платить(сайт, наличные, наличные_uid, "payme")["status"] == 409


# ── Payme ───────────────────────────────────────────────────────────


@нужна_база
def test_payme_оплата_повтор_и_возврат(сайт, магазин):
    uid, number, pk = _заказ(сайт, магазин)
    счёт = {"order": number}

    # Чужой ключ, чужое имя, неизвестный метод
    for key, who in (("wrong", "Paycom"), ("payme-test-key", "Other")):
        ответ = _payme(сайт, "CheckPerformTransaction", {"amount": ЦЕНА, "account": счёт}, key, who)
        assert ответ["error"]["code"] == -32504
    assert _payme(сайт, "ChangePassword", {"password": "x"})["error"]["code"] == -32601

    # Сумма не та, заказа нет
    assert (
        _payme(сайт, "CheckPerformTransaction", {"amount": 1, "account": счёт})["error"]["code"]
        == -31001
    )
    assert (
        _payme(
            сайт, "CheckPerformTransaction", {"amount": ЦЕНА, "account": {"order": "ZZZZZZZZZZ"}}
        )["error"]["code"]
        == -31050
    )

    можно = _payme(сайт, "CheckPerformTransaction", {"amount": ЦЕНА, "account": счёт})["result"]
    assert можно["allow"] is True
    assert можно["detail"]["items"] == [
        {
            "title": "Кубики деревянные",
            "price": ЦЕНА,
            "count": 1,
            "code": "12345678901234567",
            "vat_percent": 12,
        }
    ]

    создать = {"id": "pm-1", "time": _ms(), "amount": ЦЕНА, "account": счёт}
    создана = _payme(сайт, "CreateTransaction", создать)["result"]
    assert создана["state"] == 1
    # Повтор с тем же id — тот же ответ, строка одна
    assert _payme(сайт, "CreateTransaction", создать)["result"] == создана
    # Тот же id, но другой заказ или другая сумма — понятный отказ, не 500
    _, другой, _ = _заказ(сайт, магазин)
    assert (
        _payme(сайт, "CreateTransaction", {**создать, "account": {"order": другой}})["error"][
            "code"
        ]
        == -31099
    )
    assert (
        _payme(сайт, "CreateTransaction", {**создать, "amount": ЦЕНА + 100})["error"]["code"]
        == -31001
    )
    # Другая транзакция того же заказа — отказ, второго живого счёта нет
    assert _payme(сайт, "CreateTransaction", {**создать, "id": "pm-2"})["error"]["code"] == -31053
    assert (
        _payme(сайт, "CheckPerformTransaction", {"amount": ЦЕНА, "account": счёт})["error"]["code"]
        == -31053
    )
    assert _оплаты(pk) == [("payme", "pending")]
    assert _журнал(pk) == {}

    проведена = _payme(сайт, "PerformTransaction", {"id": "pm-1"})["result"]
    assert проведена["state"] == 2 and проведена["transaction"] == создана["transaction"]
    assert _статус(number) == "paid"
    assert _журнал(pk)["gateway_clearing"] == ЦЕНА
    групп = _групп(pk)

    # Повтор проведения — тот же ответ, второго начисления нет
    assert _payme(сайт, "PerformTransaction", {"id": "pm-1"})["result"] == проведена
    assert _групп(pk) == групп and _журнал(pk)["gateway_clearing"] == ЦЕНА
    assert _payme(сайт, "PerformTransaction", {"id": "pm-404"})["error"]["code"] == -31003

    проверка = _payme(сайт, "CheckTransaction", {"id": "pm-1"})["result"]
    assert проверка["state"] == 2 and проверка["perform_time"] == проведена["perform_time"]
    выписка = _payme(сайт, "GetStatement", {"from": 0, "to": _ms() + 60_000})["result"]
    assert "pm-1" in [t["id"] for t in выписка["transactions"]]
    assert "pm-2" not in [t["id"] for t in выписка["transactions"]]

    # Заказ не ждёт возврата — отменить проведённую нельзя
    assert _payme(сайт, "CancelTransaction", {"id": "pm-1", "reason": 5})["error"]["code"] == -31007
    assert _статус(number) == "paid"

    # Покупатель отменил — возврат отменой транзакции в кабинете Payme
    _отменить(сайт, uid, number)
    assert _статус(number) == "refund_pending"
    отменена = _payme(сайт, "CancelTransaction", {"id": "pm-1", "reason": 5})["result"]
    assert отменена["state"] == -2
    assert _статус(number) == "refunded" and _оплаты(pk) == [("payme", "refunded")]
    assert _payme(сайт, "CancelTransaction", {"id": "pm-1", "reason": 5})["result"] == отменена
    assert all(total == 0 for total in _журнал(pk).values()), _журнал(pk)


@нужна_база
def test_payme_истёкший_отменённый_и_12_часов(сайт, магазин):
    # Истёкший по сроку заказ — отказ уже на проверке
    _, истёк, истёк_pk = _заказ(сайт, магазин)
    sql(
        "update market_orders set created_at = created_at - interval '2 hours' where id = %s",
        [истёк_pk],
    )
    # Заказ, по которому Payme уже завёл транзакцию, ждёт оплаты дольше
    _, ждёт, ждёт_pk = _заказ(сайт, магазин)
    _payme(
        сайт,
        "CreateTransaction",
        {"id": "pm-wait", "time": _ms(), "amount": ЦЕНА, "account": {"order": ждёт}},
    )
    sql(
        "update market_orders set created_at = created_at - interval '2 hours' where id = %s",
        [ждёт_pk],
    )
    # А брошенная давно попытка заказ не держит: отсрочка — не дольше срока
    _, брошен, брошен_pk = _заказ(сайт, магазин)
    _payme(
        сайт,
        "CreateTransaction",
        {"id": "pm-old", "time": _ms(), "amount": ЦЕНА, "account": {"order": брошен}},
    )
    sql(
        "update market_orders set created_at = created_at - interval '3 hours' where id = %s",
        [брошен_pk],
    )
    sql(
        "update market_payments set created_at = created_at - interval '2 hours' "
        "where provider_transaction_id = 'pm-old'"
    )
    assert _manage("market_expire_orders").returncode == 0
    assert _статус(истёк) == "cancelled" and _статус(ждёт) == "created"
    assert _статус(брошен) == "cancelled"
    # Payme всё же пришёл провести брошенную — отказ, денег не принимаем
    assert _payme(сайт, "PerformTransaction", {"id": "pm-old"})["error"]["code"] == -31008
    assert _журнал(брошен_pk) == {}

    for method, params in (
        ("CheckPerformTransaction", {"amount": ЦЕНА, "account": {"order": истёк}}),
        (
            "CreateTransaction",
            {"id": "pm-late", "time": _ms(), "amount": ЦЕНА, "account": {"order": истёк}},
        ),
    ):
        assert _payme(сайт, method, params)["error"]["code"] == -31051
    assert _оплаты(истёк_pk) == []

    # Транзакция заведена, а покупатель отменил заказ — проведение отклоняется
    uid, отменён, отменён_pk = _заказ(сайт, магазин)
    _payme(
        сайт,
        "CreateTransaction",
        {"id": "pm-3", "time": _ms(), "amount": ЦЕНА, "account": {"order": отменён}},
    )
    _отменить(сайт, uid, отменён)
    assert _payme(сайт, "PerformTransaction", {"id": "pm-3"})["error"]["code"] == -31008
    assert _статус(отменён) == "cancelled" and _журнал(отменён_pk) == {}
    assert _payme(сайт, "CheckTransaction", {"id": "pm-3"})["result"]["state"] == -1

    # 12 часов прошло — транзакция отменяется с причиной 4
    _, долгий, долгий_pk = _заказ(сайт, магазин)
    _payme(
        сайт,
        "CreateTransaction",
        {"id": "pm-4", "time": _ms(), "amount": ЦЕНА, "account": {"order": долгий}},
    )
    sql(
        "update market_payments set created_at = created_at - interval '13 hours' "
        "where provider_transaction_id = 'pm-4'"
    )
    assert _payme(сайт, "PerformTransaction", {"id": "pm-4"})["error"]["code"] == -31008
    итог = _payme(сайт, "CheckTransaction", {"id": "pm-4"})["result"]
    assert итог["state"] == -1 and итог["reason"] == 4
    assert _статус(долгий) == "created" and _журнал(долгий_pk) == {}


# ── Click ───────────────────────────────────────────────────────────


@нужна_база
def test_click_подпись_сумма_и_повтор(сайт, магазин):
    _, number, pk = _заказ(сайт, магазин)
    поля = {"click_trans_id": "9001", "merchant_trans_id": number, "amount": "90000.00"}

    assert _click(сайт, "prepare", поля, secret="чужой")["error"] == -1
    assert _click(сайт, "prepare", {**поля, "amount": "1.00"})["error"] == -2
    assert _click(сайт, "prepare", {**поля, "amount": "90000.001"})["error"] == -2
    assert _click(сайт, "prepare", {**поля, "merchant_trans_id": "ZZZZZZZZZZ"})["error"] == -5
    assert _оплаты(pk) == []

    готов = _click(сайт, "prepare", поля)
    assert готов["error"] == 0 and готов["merchant_prepare_id"]
    # Повтор Prepare — тот же номер, строка одна
    assert _click(сайт, "prepare", поля)["merchant_prepare_id"] == готов["merchant_prepare_id"]
    # Другая транзакция того же заказа — отказ (у Click — «отменена»)
    assert _click(сайт, "prepare", {**поля, "click_trans_id": "9002"})["error"] == -9
    assert _оплаты(pk) == [("click", "pending")]
    # Повтор с известным id, но на другой заказ или с другой суммой — отказ
    _, чужой, _ = _заказ(сайт, магазин)
    assert _click(сайт, "prepare", {**поля, "merchant_trans_id": чужой})["error"] == -6
    assert _click(сайт, "prepare", {**поля, "amount": "90001.00"})["error"] == -2

    итог = {**поля, "merchant_prepare_id": str(готов["merchant_prepare_id"])}
    assert _click(сайт, "complete", {**итог, "merchant_prepare_id": "999999"})["error"] == -6
    assert _click(сайт, "complete", итог, secret="чужой")["error"] == -1
    assert _статус(number) == "created"

    проведена = _click(сайт, "complete", итог)
    assert проведена["error"] == 0
    assert проведена["merchant_confirm_id"] == готов["merchant_prepare_id"]
    assert _статус(number) == "paid" and _журнал(pk)["gateway_clearing"] == ЦЕНА
    групп = _групп(pk)

    # Повтор Complete — тот же успех, второго начисления нет
    assert _click(сайт, "complete", итог) == проведена
    assert _групп(pk) == групп and _журнал(pk)["gateway_clearing"] == ЦЕНА
    # Оплаченный заказ новым Prepare не оплатить
    assert _click(сайт, "prepare", {**поля, "click_trans_id": "9003"})["error"] == -4


@нужна_база
def test_click_неудачная_оплата_и_отменённый_заказ(сайт, магазин):
    _, number, pk = _заказ(сайт, магазин)
    поля = {"click_trans_id": "9101", "merchant_trans_id": number, "amount": "90000"}
    готов = _click(сайт, "prepare", поля)
    assert готов["error"] == 0

    # У Click оплата не прошла (error < 0) — гасим, заказ ждёт дальше
    сбой = _click(
        сайт,
        "complete",
        {**поля, "merchant_prepare_id": str(готов["merchant_prepare_id"]), "error": "-5017"},
    )
    assert сбой["error"] == -9
    assert _оплаты(pk) == [("click", "cancelled")] and _статус(number) == "created"

    # Покупатель отменил заказ между Prepare и Complete — Complete отклоняется
    uid, отменён, отменён_pk = _заказ(сайт, магазин)
    поля = {"click_trans_id": "9102", "merchant_trans_id": отменён, "amount": "90000.00"}
    готов = _click(сайт, "prepare", поля)
    _отменить(сайт, uid, отменён)
    ответ = _click(
        сайт, "complete", {**поля, "merchant_prepare_id": str(готов["merchant_prepare_id"])}
    )
    assert ответ["error"] == -9
    assert _статус(отменён) == "cancelled" and _журнал(отменён_pk) == {}
    # И новый Prepare по отменённому — отказ
    assert _click(сайт, "prepare", {**поля, "click_trans_id": "9103"})["error"] == -9


# ── Uzum ────────────────────────────────────────────────────────────


@нужна_база
def test_uzum_оплата_повтор_и_возврат(сайт, магазин):
    uid, number, pk = _заказ(сайт, магазин)
    params = {"order": number}

    статус, ответ = _uzum(сайт, "check", {"params": params}, auth=("uzum-market", "wrong"))
    assert статус == 401 and ответ["errorCode"] == 10001
    статус, ответ = _uzum(сайт, "check", {"params": params, "serviceId": "1"})
    assert ответ["errorCode"] == 10006
    assert _uzum(сайт, "check", {"params": params, "amount": ЦЕНА})[1]["status"] == "OK"

    создать = {"transId": "uz-1", "params": params, "amount": ЦЕНА}
    assert _uzum(сайт, "create", {**создать, "amount": 100})[1]["errorCode"] == 10011
    статус, создана = _uzum(сайт, "create", создать)
    assert статус == 200 and создана["status"] == "CREATED", создана
    # Повтор create — отказ, строка одна; другая транзакция заказа — отказ
    assert _uzum(сайт, "create", создать)[1]["errorCode"] == 10010
    assert _uzum(сайт, "create", {**создать, "transId": "uz-2"})[1]["errorCode"] == 10010
    assert _оплаты(pk) == [("uzum", "pending")]

    статус, проведена = _uzum(сайт, "confirm", {"transId": "uz-1"})
    assert статус == 200 and проведена["status"] == "CONFIRMED", проведена
    assert _статус(number) == "paid" and _журнал(pk)["gateway_clearing"] == ЦЕНА
    групп = _групп(pk)
    assert _uzum(сайт, "confirm", {"transId": "uz-1"})[1]["errorCode"] == 10016
    assert _групп(pk) == групп

    # Заказ не ждёт возврата — отменить проведённую нельзя
    assert _uzum(сайт, "reverse", {"transId": "uz-1"})[1]["errorCode"] == 10017

    _отменить(сайт, uid, number)
    статус, отменена = _uzum(сайт, "reverse", {"transId": "uz-1"})
    assert статус == 200 and отменена["status"] == "REVERSED", отменена
    assert _статус(number) == "refunded"
    assert _uzum(сайт, "reverse", {"transId": "uz-1"})[1]["errorCode"] == 10018
    assert _uzum(сайт, "status", {"transId": "uz-1"})[1]["status"] == "REVERSED"
    # confirm по возвращённой — отказ, но без отметки «отклонена»: деньги
    # покупателю ушли нашим же путём, проверять у провайдера нечего
    assert _uzum(сайт, "confirm", {"transId": "uz-1"})[1]["errorCode"] == 10018
    assert sql(
        "select rejected_at from market_payments where provider_transaction_id = 'uz-1'"
    ) == [(None,)]
    assert all(total == 0 for total in _журнал(pk).values()), _журнал(pk)


@нужна_база
def test_uzum_отменённый_заказ(сайт, магазин):
    uid, number, pk = _заказ(сайт, магазин)
    _uzum(сайт, "create", {"transId": "uz-10", "params": {"order": number}, "amount": ЦЕНА})
    _отменить(сайт, uid, number)

    assert _uzum(сайт, "confirm", {"transId": "uz-10"})[1]["errorCode"] == 10009
    assert _статус(number) == "cancelled" and _журнал(pk) == {}
    assert _оплаты(pk) == [("uzum", "cancelled")]
    assert (
        _uzum(сайт, "create", {"transId": "uz-11", "params": {"order": number}, "amount": ЦЕНА})[1][
            "errorCode"
        ]
        == 10009
    )


@нужна_база
def test_колбэки_выключенного_провайдера_и_чужой_адрес(сайт, магазин):
    _, number, _ = _заказ(сайт, магазин)
    тело = json.dumps({"id": 1, "method": "CheckTransaction", "params": {"id": "x"}})

    # Без ключей адреса нет
    нет = открыть(
        сайт,
        "/market/api/payments/payme",
        env={},
        method="POST",
        body=тело,
        content_type="application/json",
    )
    assert нет["status"] == 404

    # Белый список задан, а запрос не с того адреса — отказ
    чужой = открыть(
        сайт,
        "/market/api/payments/payme",
        headers={"Authorization": "Basic " + base64.b64encode(b"Paycom:payme-test-key").decode()},
        env={**ОПЛАТА, "MARKET_PAYME_CALLBACK_IPS": "10.9.9.9"},
        method="POST",
        body=тело,
        content_type="application/json",
    )
    assert json.loads(чужой["body"])["error"]["code"] == -32504
    assert _статус(number) == "created"


@нужна_база
def test_по_заведённым_транзакциям_колбэки_работают_и_при_закрытом(сайт, магазин):
    """Маркетплейс закрыт (как на боевом): новые транзакции — 404, заведённые доводятся."""
    _, payme_заказ, _ = _заказ(сайт, магазин)
    _payme(
        сайт,
        "CreateTransaction",
        {"id": "pm-s5", "time": _ms(), "amount": ЦЕНА, "account": {"order": payme_заказ}},
    )
    _, click_заказ, _ = _заказ(сайт, магазин)
    click_поля = {"click_trans_id": "9501", "merchant_trans_id": click_заказ, "amount": "90000.00"}
    готов = _click(сайт, "prepare", click_поля)
    _, uzum_заказ, _ = _заказ(сайт, магазин)
    _uzum(сайт, "create", {"transId": "uz-s5", "params": {"order": uzum_заказ}, "amount": ЦЕНА})
    _, новый, новый_pk = _заказ(сайт, магазин)

    # Новые — как будто адреса нет
    for method, params in (
        ("CheckPerformTransaction", {"amount": ЦЕНА, "account": {"order": новый}}),
        (
            "CreateTransaction",
            {"id": "pm-s5-new", "time": _ms(), "amount": ЦЕНА, "account": {"order": новый}},
        ),
    ):
        assert _payme_raw(сайт, method, params, env=ЗАКРЫТ)["status"] == 404
    assert _uzum(сайт, "check", {"params": {"order": новый}}, env=ЗАКРЫТ)[0] == 404
    создать = {"transId": "uz-s5-new", "params": {"order": новый}, "amount": ЦЕНА}
    assert _uzum(сайт, "create", создать, env=ЗАКРЫТ)[0] == 404
    новые_click = {"click_trans_id": "9502", "merchant_trans_id": новый, "amount": "90000.00"}
    assert _click(сайт, "prepare", новые_click, env=ЗАКРЫТ) == {"status": 404}
    assert _оплаты(новый_pk) == []

    # Заведённые — проводятся
    assert _payme(сайт, "PerformTransaction", {"id": "pm-s5"}, env=ЗАКРЫТ)["result"]["state"] == 2
    assert _payme(сайт, "CheckTransaction", {"id": "pm-s5"}, env=ЗАКРЫТ)["result"]["state"] == 2
    итог = {**click_поля, "merchant_prepare_id": str(готов["merchant_prepare_id"])}
    assert _click(сайт, "complete", итог, env=ЗАКРЫТ)["error"] == 0
    статус, проведена = _uzum(сайт, "confirm", {"transId": "uz-s5"}, env=ЗАКРЫТ)
    assert статус == 200 and проведена["status"] == "CONFIRMED", проведена
    assert _uzum(сайт, "status", {"transId": "uz-s5"}, env=ЗАКРЫТ)[1]["status"] == "CONFIRMED"
    assert {_статус(payme_заказ), _статус(click_заказ), _статус(uzum_заказ)} == {"paid"}


def _сбросить_счётчики() -> None:
    """Счётчики частоты колбэков адреса 127.0.0.1 в файловом кэше — с нуля."""
    ip = hashlib.sha1(b"127.0.0.1").hexdigest()

    for key in (f"market-pay:{ip}", f"market-pay-auth:{ip}"):
        for name in (key, f"{key}:timer"):
            digest = hashlib.sha1(name.encode()).hexdigest()
            (
                Path(КОРЕНЬ) / "storage/framework/cache/data" / digest[:2] / digest[2:4] / digest
            ).unlink(missing_ok=True)


@нужна_база
def test_лимит_колбэков_и_неудачных_подписей(сайт, магазин):
    счётчик = {"CACHE_STORE": "file", "MARKET_CALLBACK_AUTH_FAILS": "2"}
    _сбросить_счётчики()

    try:
        # Две неудачные подписи — и с адреса больше не пускают даже с верным ключом
        for _ in range(2):
            ответ = _payme(сайт, "CheckTransaction", {"id": "x"}, key="wrong", env=счётчик)
            assert ответ["error"]["code"] == -32504
        верный = _payme(сайт, "CheckTransaction", {"id": "x"}, env=счётчик)
        assert верный["error"]["code"] == -32504

        # Общий предел запросов с адреса в минуту
        _сбросить_счётчики()
        предел = {"CACHE_STORE": "file", "MARKET_CALLBACK_RATE": "2"}
        for _ in range(2):
            ответ = _payme(сайт, "CheckTransaction", {"id": "x"}, env=предел)
            assert ответ["error"]["code"] == -31003
        assert _payme(сайт, "CheckTransaction", {"id": "x"}, env=предел)["error"]["code"] == -32504

        # Адрес из списка провайдера — сам провайдер: ни блокировки за
        # неудачные подписи, ни общего предела
        _сбросить_счётчики()
        свой = {**счётчик, "MARKET_CALLBACK_RATE": "2", "MARKET_PAYME_CALLBACK_IPS": "127.0.0.1"}
        for _ in range(3):
            ответ = _payme(сайт, "CheckTransaction", {"id": "x"}, key="wrong", env=свой)
            assert ответ["error"]["code"] == -32504
        for _ in range(3):
            ответ = _payme(сайт, "CheckTransaction", {"id": "x"}, env=свой)
            assert ответ["error"]["code"] == -31003
    finally:
        _сбросить_счётчики()


@нужна_база
def test_кривые_значения_при_верной_подписи_не_500(сайт, магазин):
    _, number, _ = _заказ(сайт, магазин)

    # Uzum: «²» — не сумма; длинное эхо не возвращается
    статус, ответ = _uzum(
        сайт,
        "create",
        {"transId": "uz-bad", "params": {"order": number}, "amount": "²", "timestamp": "y" * 100},
    )
    assert статус == 400 and ответ["errorCode"] == 10005 and ответ["timestamp"] is None
    статус, ответ = _uzum(сайт, "check", {"params": {"order": number}, "amount": 2**70})
    assert ответ["errorCode"] == 10011

    # Payme: reason вне smallint, from/to вне bigint — неверный запрос
    _payme(
        сайт,
        "CreateTransaction",
        {"id": "pm-bad", "time": _ms(), "amount": ЦЕНА, "account": {"order": number}},
    )
    отмена = _payme(сайт, "CancelTransaction", {"id": "pm-bad", "reason": 10**10})
    assert отмена["error"]["code"] == -32600
    assert _payme(сайт, "GetStatement", {"from": 0, "to": 2**70})["error"]["code"] == -32600
    поздно = {"id": "pm-bad2", "time": 2**70, "amount": ЦЕНА, "account": {"order": number}}
    assert _payme(сайт, "CreateTransaction", поздно)["error"]["code"] == -32600

    # Click: сумма с переполнением Decimal — «сумма не та»
    _, другой, _ = _заказ(сайт, магазин)
    поля = {"click_trans_id": "9601", "merchant_trans_id": другой, "amount": "1e999999999"}
    assert _click(сайт, "prepare", поля)["error"] == -2
    длинный = _click(сайт, "prepare", {**поля, "merchant_trans_id": "Z" * 100})
    assert длинный["merchant_trans_id"] is None


@нужна_база
def test_click_повтор_prepare_после_отмены_заказа(сайт, магазин):
    uid, number, pk = _заказ(сайт, магазин)
    поля = {"click_trans_id": "9701", "merchant_trans_id": number, "amount": "90000.00"}
    assert _click(сайт, "prepare", поля)["error"] == 0
    _отменить(сайт, uid, number)

    # Повтор Prepare с известным id — заказ уже отменён, отказ
    assert _click(сайт, "prepare", поля)["error"] == -9
    assert _статус(number) == "cancelled" and _журнал(pk) == {}


@нужна_база
def test_брошенная_попытка_не_держит_заказ(сайт, магазин):
    uid, number, pk = _заказ(сайт, магазин)
    первая = {"click_trans_id": "9801", "merchant_trans_id": number, "amount": "90000.00"}
    готов = _click(сайт, "prepare", первая)
    assert готов["error"] == 0

    # Свежая — держит: вторая попытка отказ, счёт со страницы — «оплата идёт»
    assert _click(сайт, "prepare", {**первая, "click_trans_id": "9802"})["error"] == -9
    assert _платить(сайт, number, uid, "uzum")["status"] == 409

    # Старше срока Click (30 мин) — брошена: новая попытка её гасит
    sql(
        "update market_payments set created_at = created_at - interval '2 hours' "
        "where provider_transaction_id = '9801'"
    )
    assert _click(сайт, "prepare", {**первая, "click_trans_id": "9802"})["error"] == 0
    assert _оплаты(pk) == [("click", "cancelled"), ("click", "pending")]
    # Complete по погашенной — отказ, Click вернёт деньги; но деньги он мог
    # уже списать — отметка rejected_at, и сверка это видит
    итог = {**первая, "merchant_prepare_id": str(готов["merchant_prepare_id"])}
    assert _click(сайт, "complete", итог)["error"] == -9
    [(брошенная, отклонена)] = sql(
        "select id, rejected_at is not null from market_payments "
        "where provider_transaction_id = '9801'"
    )
    assert отклонена
    сегодня = _manage("market_reconcile_payments", "--day", str(datetime.now(UTC).date()))
    assert f"оплата {брошенная} отклонена на проведении" in сегодня.stdout, сегодня.stdout

    # И со страницы заказа брошенная попытка счёт не блокирует
    sql(
        "update market_payments set created_at = created_at - interval '2 hours' "
        "where provider_transaction_id = '9802'"
    )
    assert _платить(сайт, number, uid, "payme")["status"] == 200
    assert _оплаты(pk)[-1] == ("payme", "created")


@нужна_база
def test_payme_чек_без_икпу_и_доставка(сайт, магазин):
    _, number, pk = _заказ(сайт, магазин)
    sql("update market_order_items set ikpu = null where order_id = %s", [pk])
    счёт = {"order": number}

    # Чек с пустым кодом не отправляем — отказ до транзакции
    проверка = _payme(сайт, "CheckPerformTransaction", {"amount": ЦЕНА, "account": счёт})
    assert проверка["error"]["code"] == -31054
    создать = {"id": "pm-noikpu", "time": _ms(), "amount": ЦЕНА, "account": счёт}
    assert _payme(сайт, "CreateTransaction", создать)["error"]["code"] == -31054
    assert _оплаты(pk) == []

    # Доставка — своей позицией с ИКПУ из окружения
    _, доставка, доставка_pk = _заказ(сайт, магазин)
    sql(
        "update market_orders set delivery_total = 1500000, total = total + 1500000 where id = %s",
        [доставка_pk],
    )
    ответ = _payme(
        сайт,
        "CheckPerformTransaction",
        {"amount": ЦЕНА + 1_500_000, "account": {"order": доставка}},
        env={"MARKET_DELIVERY_IKPU": "10112006002000000"},
    )
    позиции = ответ["result"]["detail"]["items"]
    assert позиции[-1] == {
        "title": "Доставка",
        "price": 1_500_000,
        "count": 1,
        "code": "10112006002000000",
        "vat_percent": 12,
    }
    # Без ИКПУ доставки — отказ
    без = _payme(
        сайт,
        "CheckPerformTransaction",
        {"amount": ЦЕНА + 1_500_000, "account": {"order": доставка}},
    )
    assert без["error"]["code"] == -31054


# ── Возврат и сверка ────────────────────────────────────────────────


@нужна_база
def test_возврат_ровно_один_раз(сайт, магазин):
    uid, number, pk = _заказ(сайт, магазин)
    счёт = {"order": number}
    _payme(
        сайт, "CreateTransaction", {"id": "pm-r", "time": _ms(), "amount": ЦЕНА, "account": счёт}
    )
    _payme(сайт, "PerformTransaction", {"id": "pm-r"})
    _отменить(сайт, uid, number)
    assert _статус(number) == "refund_pending"

    код = f"from savdex.market.payments import base; print(base.refund_order({pk}))"
    # Провайдер выключен (нет ключей) — отметку «запрошен» не ставим навсегда
    assert _python(код) == "disabled"
    assert sql(
        "select refund_requested_at from market_payments where order_id = %s and status = 'paid'",
        [pk],
    ) == [(None,)]

    # У Payme API возврата нет — пометка администратору, заказ ждёт отмены из кабинета
    assert _python_env(код) == "manual"
    assert _python_env(код) == "requested"
    assert _статус(number) == "refund_pending"
    [(пометок,)] = sql(
        "select count(*) from market_order_events where order_id = %s "
        "and from_status = 'refund_pending' and to_status = 'refund_pending'",
        [pk],
    )
    assert пометок == 1

    _payme(сайт, "CancelTransaction", {"id": "pm-r", "reason": 5})
    assert _статус(number) == "refunded"
    assert _python_env(код) == "not_pending"
    [(возвратов,)] = sql(
        "select count(*) from market_ledger where order_id = %s and account = 'refund_payable' "
        "and amount > 0",
        [pk],
    )
    assert возвратов == 1


#: День сверки, на который проверки переносят свои оплаты: прочие проверки
#: файла в него не попадают — сверка видит только своё
ДЕНЬ = "2020-01-01"


def _в_тот_день(pk: int) -> None:
    sql(
        "update market_payments set created_at = %s, updated_at = %s, performed_at = "
        "case when performed_at is null then null else %s::timestamp end where order_id = %s",
        [f"{ДЕНЬ} 10:00:00", f"{ДЕНЬ} 10:00:00", f"{ДЕНЬ} 10:00:00", pk],
    )
    sql(
        "update market_orders set paid_at = %s where id = %s and paid_at is not null",
        [f"{ДЕНЬ} 10:00:00", pk],
    )


@нужна_база
def test_сверка_оплат(сайт, магазин):
    # Чистый день: одна честная оплата Click
    _, number, pk = _заказ(сайт, магазин)
    поля = {"click_trans_id": "9901", "merchant_trans_id": number, "amount": "90000.00"}
    готов = _click(сайт, "prepare", поля)
    _click(сайт, "complete", {**поля, "merchant_prepare_id": str(готов["merchant_prepare_id"])})
    _в_тот_день(pk)

    чисто = _manage("market_reconcile_payments", "--day", ДЕНЬ)
    assert чисто.returncode == 0, чисто.stdout + чисто.stderr
    assert "click: оплат 1, расхождений 0" in чисто.stdout
    assert "расхождений 0." in чисто.stdout

    # Оплата «проведена», а начисления в журнале нет — расхождение
    _, фальшивый, фальшивый_pk = _заказ(сайт, магазин)
    sql(
        "insert into market_payments (order_id, provider, provider_transaction_id, amount, "
        "status, performed_at) values (%s, 'click', 'fake-1', %s, 'paid', "
        "now() at time zone 'utc')",
        [фальшивый_pk, ЦЕНА],
    )
    _в_тот_день(фальшивый_pk)

    # Отклонённая на проведении (Click Complete по отменённому заказу) —
    # «проверить возврат у провайдера»
    uid, отменён, отменён_pk = _заказ(сайт, магазин)
    поля = {"click_trans_id": "9902", "merchant_trans_id": отменён, "amount": "90000.00"}
    готов = _click(сайт, "prepare", поля)
    _отменить(сайт, uid, отменён)
    _click(сайт, "complete", {**поля, "merchant_prepare_id": str(готов["merchant_prepare_id"])})
    sql(
        "update market_payments set rejected_at = %s, updated_at = %s where order_id = %s",
        [f"{ДЕНЬ} 11:00:00", f"{ДЕНЬ} 11:00:00", отменён_pk],
    )
    [(отклонена,)] = sql(
        "select id from market_payments where order_id = %s and rejected_at is not null",
        [отменён_pk],
    )

    # Заказ ждёт возврата дольше суток
    покупатель, ждёт, ждёт_pk = _заказ(сайт, магазин)
    _payme(
        сайт,
        "CreateTransaction",
        {"id": "pm-wait-refund", "time": _ms(), "amount": ЦЕНА, "account": {"order": ждёт}},
    )
    _payme(сайт, "PerformTransaction", {"id": "pm-wait-refund"})
    _отменить(сайт, покупатель, ждёт)
    sql(
        "update market_orders set cancelled_at = cancelled_at - interval '48 hours' where id = %s",
        [ждёт_pk],
    )

    try:
        грязно = _manage("market_reconcile_payments", "--day", ДЕНЬ)
        assert грязно.returncode == 1, грязно.stdout
        assert фальшивый in грязно.stdout
        assert f"оплата {отклонена} отклонена на проведении" in грязно.stdout
        assert f"{ждёт} ждёт возврата дольше 24 ч" in грязно.stdout
        assert number not in грязно.stdout
        # В журнал приложения — только счётчики, без номеров заказов
        for номер in (фальшивый, ждёт):
            assert номер not in грязно.stderr

        # Сотрудник проверил у провайдера отказ и зависший возврат — сверка
        # их больше не считает; повторная отметка — False
        [(возврат,)] = sql(
            "select id from market_payments where order_id = %s and status = 'paid'", [ждёт_pk]
        )
        кассир = _сотрудник("superadmin")
        заметка = "деньги вернулись, сверено в кабинете"

        # Не сотрудник кассы и короткая заметка — отказ команды
        for лишний in (
            ["--admin", str(покупатель), "--note", заметка],
            ["--admin", str(кассир), "--note", "ок"],
        ):
            отказ = _manage("market_ack_payment", str(отклонена), *лишний)
            assert отказ.returncode == 2, отказ.stdout + отказ.stderr

        for pk_ in (отклонена, возврат):
            итог = _manage(
                "market_ack_payment", str(pk_), "--admin", str(кассир), "--note", заметка
            )
            assert итог.returncode == 0, итог.stdout + итог.stderr
            повтор = _manage(
                "market_ack_payment", str(pk_), "--admin", str(кассир), "--note", заметка
            )
            assert повтор.returncode == 1
        assert sql(
            "select checked_by, check_note from market_payments where id = %s", [отклонена]
        ) == [(кассир, заметка)]

        # Журнал действий админки и история заказа — от имени сотрудника
        запись = журнал("payment_checked")
        assert запись["section"] == "market_cash" and запись["subject_type"] == "market_payment"
        assert sql(
            "select actor, actor_user_id from market_order_events where order_id = %s "
            "and note like %s",
            [ждёт_pk, f"оплата {возврат}: проверено%"],
        ) == [("staff", кассир)]
        проверено = _manage("market_reconcile_payments", "--day", ДЕНЬ)
        assert f"оплата {отклонена} отклонена" not in проверено.stdout
        assert f"{ждёт} ждёт возврата" not in проверено.stdout
        # Фальшивая оплата без начисления — по-прежнему расхождение
        assert проверено.returncode == 1 and фальшивый in проверено.stdout
    finally:
        # Прочие проверки после этой сверку не запускают, но порядок мог
        # бы смениться: долгий возврат возвращаем в «сейчас»
        sql(
            "update market_orders set cancelled_at = now() at time zone 'utc' where id = %s",
            [ждёт_pk],
        )


@нужна_база
def test_проверенный_отказ_другой_оплаты_не_глушит_зависший_возврат(сайт, магазин):
    """У заказа проверенный отказ Click и зависший возврат Payme — возврат всё равно виден."""
    покупатель, number, pk = _заказ(сайт, магазин)
    click_поля = {"click_trans_id": "9961", "merchant_trans_id": number, "amount": "90000.00"}
    готов = _click(сайт, "prepare", click_поля)
    # Попытка Click брошена — Payme её гасит и проводит оплату
    sql(
        "update market_payments set created_at = created_at - interval '2 hours' "
        "where provider_transaction_id = '9961'"
    )
    счёт = {"order": number}
    _payme(
        сайт, "CreateTransaction", {"id": "pm-mix", "time": _ms(), "amount": ЦЕНА, "account": счёт}
    )
    _payme(сайт, "PerformTransaction", {"id": "pm-mix"})
    # Click всё же пришёл провести брошенную — отказ с отметкой
    итог = {**click_поля, "merchant_prepare_id": str(готов["merchant_prepare_id"])}
    assert _click(сайт, "complete", итог)["error"] == -9
    [(отказ,)] = sql(
        "select id from market_payments where provider_transaction_id = '9961' "
        "and rejected_at is not null"
    )
    кассир = _сотрудник("superadmin")
    отмечено = _manage(
        "market_ack_payment", str(отказ), "--admin", str(кассир), "--note", "Click вернул деньги"
    )
    assert отмечено.returncode == 0, отмечено.stdout + отмечено.stderr

    _отменить(сайт, покупатель, number)
    assert _статус(number) == "refund_pending"
    sql(
        "update market_orders set cancelled_at = cancelled_at - interval '48 hours' where id = %s",
        [pk],
    )

    try:
        сверка = _manage("market_reconcile_payments", "--day", ДЕНЬ)
        assert f"{number} ждёт возврата дольше 24 ч" in сверка.stdout, сверка.stdout
        assert сверка.returncode == 1
    finally:
        sql(
            "update market_orders set cancelled_at = now() at time zone 'utc' where id = %s",
            [pk],
        )


@нужна_база
def test_сотрудника_с_отметкой_проверки_не_удалить_навсегда(сайт, магазин):
    """market_payments.checked_by держит сотрудника: удаление — понятный отказ, не 500."""
    [(проверяющий,)] = sql(
        "insert into users (name, email, password, is_admin, admin_role, status, deleted_at, "
        "created_at, updated_at) values ('Бывший кассир', 'old-cashier@savdex.uz', 'x', true, "
        "'finance', 'active', now(), now(), now()) returning id"
    )
    _, _, pk = _заказ(сайт, магазин)
    sql(
        "insert into market_payments (order_id, provider, amount, status, checked_by, "
        "rejection_checked_at, cancelled_at) "
        "values (%s, 'click', %s, 'cancelled', %s, now(), now())",
        [pk, ЦЕНА, проверяющий],
    )

    список = "/py/admin/accounts/user/"
    _, _, страница = django(
        _сотрудник("superadmin"),
        (
            "post",
            список,
            {"action": "force_delete", "_selected_action": [str(проверяющий)], "post": "yes"},
        ),
        ("get", список + "?state=disabled", None),
    )

    assert страница["status"] == 200
    assert "удалить нельзя" in страница["body"]
    assert sql("select count(*) from users where id = %s", [проверяющий]) == [(1,)]
