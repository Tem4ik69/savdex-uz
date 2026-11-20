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
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import pytest

from savdex.market.payments import base, click, payme

from .pg_admin import sql, нужна_база, свежая_база
from .test_market import _json, _post, _компания, _продавец, _товар
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

    # Uzum на боевом — только со списком адресов (docs/marketplace-security.md, раздел 3)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("MARKET_UZUM_CALLBACK_IPS", raising=False)
    assert not uzum.PROVIDER.enabled()
    monkeypatch.setenv("MARKET_UZUM_CALLBACK_IPS", "10.0.0.1, 10.0.0.2")
    assert uzum.PROVIDER.enabled()
    assert base.callback_ips("uzum") == ["10.0.0.1", "10.0.0.2"]


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


def _payme(
    сайт: str, method: str, params: dict[str, Any], key: str = "payme-test-key", who: str = "Paycom"
) -> dict[str, Any]:
    ответ = открыть(
        сайт,
        "/market/api/payments/payme",
        headers={"Authorization": "Basic " + base64.b64encode(f"{who}:{key}".encode()).decode()},
        env=ОПЛАТА,
        method="POST",
        body=json.dumps({"id": 7, "method": method, "params": params}),
        content_type="application/json",
    )
    assert ответ["status"] == 200, ответ["body"]

    return dict(json.loads(ответ["body"]))


def _uzum(
    сайт: str,
    operation: str,
    body: dict[str, Any],
    auth: tuple[str, str] = ("uzum-market", "uzum-market-pass"),
) -> tuple[int, dict[str, Any]]:
    ответ = открыть(
        сайт,
        f"/market/api/payments/uzum/{operation}",
        headers={"Authorization": "Basic " + base64.b64encode(":".join(auth).encode()).decode()},
        env=ОПЛАТА,
        method="POST",
        body=json.dumps({"serviceId": "777001", "timestamp": 1, **body}),
        content_type="application/json",
    )

    return ответ["status"], dict(json.loads(ответ["body"]))


def _click(
    сайт: str, step: str, поля: dict[str, str], secret: str = "click-test-secret"
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
        env=ОПЛАТА,
        method="POST",
        body=urlencode(form),
        content_type="application/x-www-form-urlencoded",
    )
    assert ответ["status"] == 200, ответ["body"]

    return dict(json.loads(ответ["body"]))


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
    assert _manage("market_expire_orders").returncode == 0
    assert _статус(истёк) == "cancelled" and _статус(ждёт) == "created"

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
    # Другая транзакция того же заказа — отказ
    assert _click(сайт, "prepare", {**поля, "click_trans_id": "9002"})["error"] == -8
    assert _оплаты(pk) == [("click", "pending")]

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
    # У Payme API возврата нет — пометка администратору, заказ ждёт отмены из кабинета
    assert _python(код) == "manual"
    assert _python(код) == "requested"
    assert _статус(number) == "refund_pending"
    [(пометок,)] = sql(
        "select count(*) from market_order_events where order_id = %s "
        "and from_status = 'refund_pending' and to_status = 'refund_pending'",
        [pk],
    )
    assert пометок == 1

    _payme(сайт, "CancelTransaction", {"id": "pm-r", "reason": 5})
    assert _статус(number) == "refunded"
    assert _python(код) == "not_pending"
    [(возвратов,)] = sql(
        "select count(*) from market_ledger where order_id = %s and account = 'refund_payable' "
        "and amount > 0",
        [pk],
    )
    assert возвратов == 1


@нужна_база
def test_сверка_оплат(сайт, магазин):
    день = datetime.now(UTC).date().isoformat()
    чисто = _manage("market_reconcile_payments", "--day", день)
    assert чисто.returncode == 0, чисто.stdout + чисто.stderr
    assert "расхождений 0." in чисто.stdout

    # Оплата «проведена», а начисления в журнале нет — расхождение
    _, number, pk = _заказ(сайт, магазин)
    sql(
        "insert into market_payments (order_id, provider, provider_transaction_id, amount, "
        "status, performed_at) values (%s, 'click', 'fake-1', %s, 'paid', "
        "now() at time zone 'utc')",
        [pk, ЦЕНА],
    )
    грязно = _manage("market_reconcile_payments", "--day", день)
    assert грязно.returncode == 1
    assert number in грязно.stdout
    # В журнал приложения — только счётчики, без номера заказа
    assert number not in грязно.stderr
