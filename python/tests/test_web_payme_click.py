"""
Payme и Click для счетов сайта (тарифы и пакеты кредитов).

Payme Merchant API (/payments/payme/callback): выключенный — 404, ключ,
проверка счёта и суммы, создание, проведение с выдачей тарифа ровно один
раз, вторая транзакция по тому же счёту, отмена до и после проведения
(возврат — только по возвращённому счёту), истёкшая транзакция, выписка.
Click SHOP API (/payments/click/callback/{prepare,complete}): выключенный —
404, подпись, сумма, Prepare → Complete с выдачей тарифа ровно один раз,
«оплата не прошла». Касса кабинета: «Оплатить» уводит на страницу
выбранного провайдера. Ссылки, подпись и выбор провайдера — без базы.

Нужен PostgreSQL (SAVDEX_PARITY_PG_URL) — кроме проверок без базы в конце.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest

from .factories import компания
from .pg_admin import sql, нужна_база, свежая_база
from .test_web_catalog import справочники
from .test_web_forms import inertia, отправить, учётка
from .test_web_payment_callbacks import _id, сброс, снимок, счёт
from .web_site import адрес

pytestmark = нужна_база

БЕЗ_ПЕРЕВОДА = {"MACHINE_TRANSLATION_ENABLED": "false"}
PAYME = {
    "PAYMENTS_PAYME_ENABLED": "true",
    "PAYMENTS_PAYME_MERCHANT_ID": "merchant-1",
    "PAYMENTS_PAYME_KEY": "payme-key",
    **БЕЗ_ПЕРЕВОДА,
}
CLICK = {
    "PAYMENTS_CLICK_ENABLED": "true",
    "PAYMENTS_CLICK_SERVICE_ID": "111",
    "PAYMENTS_CLICK_MERCHANT_ID": "222",
    "PAYMENTS_CLICK_SECRET_KEY": "click-secret",
    **БЕЗ_ПЕРЕВОДА,
}
ВХОД_PAYME = "Basic " + base64.b64encode(b"Paycom:payme-key").decode()
#: Счёт SVD-000001 — 1500 сумов, то есть 150000 тийинов
СУММА = 150000
СЧЁТ = {"invoice": "SVD-000001"}
#: Время Payme в миллисекундах — сейчас, как в жизни: выписка ищет рядом с нашим
ВРЕМЯ = int(time.time() * 1000)


@pytest.fixture(scope="module")
def сайт() -> Iterator[str]:
    """Тарифы, пакет кредитов, компания и её владелец — как у колбэков Uzum."""
    свежая_база()
    справочники("plans")
    sql(
        "insert into credit_packs (code, name, credits, price_usd, price_uzs, sort, is_active, "
        "created_at, updated_at) values ('m', 'Средний', 50, 30, 350000, 1, true, now(), now())"
    )
    компания(slug="mine")
    учётка("owner@savdex.uz", company_id=_id("companies", "slug = 'mine'"))

    with адрес() as root:
        yield root


def ничего() -> None:
    """Подготовка второго и следующих шагов: база — от предыдущего."""


def payme(
    сайт: str,
    method: str,
    params: dict[str, Any],
    подготовка: Any = ничего,
    *,
    вход: str | None = ВХОД_PAYME,
    env: dict[str, str] | None = None,
) -> tuple[dict[str, Any], Any]:
    headers = {"Accept": "application/json"}

    if вход is not None:
        headers["Authorization"] = вход

    итог = отправить(
        сайт,
        "/payments/payme/callback",
        подготовка,
        снимок,
        body={"jsonrpc": "2.0", "id": 7, "method": method, "params": params},
        headers=headers,
        env=PAYME if env is None else env,
    )

    return итог["ответ"], итог["база"]


def тело(ответ: dict[str, Any]) -> dict[str, Any]:
    return dict(json.loads(ответ["body"]))


def код(ответ: dict[str, Any]) -> int:
    return int(тело(ответ)["error"]["code"])


def счета(база: Any) -> list[tuple[Any, ...]]:
    """(номер, статус, оплачен, провайдер, external_id)."""
    return [tuple(row[:5]) for row in база["payments"]]


def транзакции(база: Any) -> list[tuple[Any, ...]]:
    """(провайдер, id провайдера, состояние, тийины, проведена, отменена)."""
    return [(r[1], r[2], r[3], r[4], r[7], r[8]) for r in база["transactions"]]


# ── Payme ───────────────────────────────────────────────────────────


def test_payme_выключен_404(сайт):
    ответ, _ = payme(
        сайт, "CheckPerformTransaction", {"amount": СУММА, "account": СЧЁТ}, сброс(), env={}
    )

    assert ответ["status"] == 404


@pytest.mark.parametrize(
    "вход",
    [None, "Basic " + base64.b64encode(b"Paycom:wrong").decode(), "Bearer payme-key"],
)
def test_payme_чужой_ключ(сайт, вход):
    ответ, база = payme(
        сайт, "CheckPerformTransaction", {"amount": СУММА, "account": СЧЁТ}, сброс(), вход=вход
    )

    assert ответ["status"] == 200
    assert код(ответ) == -32504
    assert тело(ответ)["id"] == 7
    assert база["transactions"] == []


@pytest.mark.parametrize(
    ("params", "подготовка", "ждём"),
    [
        ({"amount": СУММА + 100, "account": СЧЁТ}, {}, -31001),
        ({"amount": СУММА, "account": {"invoice": "SVD-999999"}}, {}, -31050),
        ({"amount": СУММА, "account": {}}, {}, -31050),
        ({"amount": СУММА, "account": СЧЁТ}, {"счета": счёт("paid")}, -31052),
        ({"amount": СУММА, "account": СЧЁТ}, {"счета": счёт("failed")}, -31051),
    ],
)
def test_payme_проверка_счёта_отказ(сайт, params, подготовка, ждём):
    ответ, база = payme(сайт, "CheckPerformTransaction", params, сброс(**подготовка))

    assert код(ответ) == ждём
    assert база["transactions"] == []


def test_payme_проверка_счёта_с_чеком(сайт):
    ответ, _ = payme(
        сайт,
        "CheckPerformTransaction",
        {"amount": СУММА, "account": СЧЁТ},
        сброс(),
        env={
            **PAYME,
            "PAYMENTS_PAYME_IKPU": "10305008002000000",
            "PAYMENTS_PAYME_VAT_PERCENT": "0",
        },
    )

    result = тело(ответ)["result"]

    assert result["allow"] is True
    assert result["detail"]["items"] == [
        {
            "title": "Счёт «SVD-000001» / тест",
            "price": СУММА,
            "count": 1,
            "code": "10305008002000000",
            "vat_percent": 0,
        }
    ]


def test_payme_оплата_выдаёт_тариф_один_раз(сайт):
    создать = {"id": "PM-1", "time": ВРЕМЯ, "amount": СУММА, "account": СЧЁТ}
    ответ, база = payme(сайт, "CreateTransaction", создать, сброс())
    result = тело(ответ)["result"]

    assert result["state"] == 1 and result["create_time"] > 0
    assert транзакции(база) == [("payme", "PM-1", "created", СУММА, False, False)]
    assert счета(база)[0][1] == "pending"

    # Повтор Create — та же транзакция, второй строки нет
    повтор, база = payme(сайт, "CreateTransaction", создать)

    assert тело(повтор)["result"] == result
    assert len(база["transactions"]) == 1

    провести, база = payme(сайт, "PerformTransaction", {"id": "PM-1"})
    done = тело(провести)["result"]

    assert done["state"] == 2 and done["perform_time"] > 0
    assert счета(база) == [("SVD-000001", "paid", True, "payme", "PM-1")]
    assert транзакции(база) == [("payme", "PM-1", "performed", СУММА, True, False)]
    assert len(база["subscriptions"]) == 1

    # Повтор Perform — тот же ответ, тариф не выдаётся второй раз
    снова, база = payme(сайт, "PerformTransaction", {"id": "PM-1"})

    assert тело(снова)["result"] == done
    assert len(база["subscriptions"]) == 1

    статус, _ = payme(сайт, "CheckTransaction", {"id": "PM-1"})

    assert тело(статус)["result"]["state"] == 2
    assert тело(статус)["result"]["perform_time"] == done["perform_time"]

    # Отменить проведённую по не возвращённому счёту нельзя
    отмена, база = payme(сайт, "CancelTransaction", {"id": "PM-1", "reason": 5})

    assert код(отмена) == -31007
    assert транзакции(база)[0][2] == "performed"

    # Счёт вернули в админке — теперь отмена принимается как возврат (-2)
    sql("update payments set status = 'refunded'")
    отмена, база = payme(сайт, "CancelTransaction", {"id": "PM-1", "reason": 5})
    cancelled = тело(отмена)["result"]

    assert cancelled["state"] == -2 and cancelled["cancel_time"] > 0
    assert транзакции(база) == [("payme", "PM-1", "cancelled", СУММА, True, True)]

    выписка, _ = payme(сайт, "GetStatement", {"from": ВРЕМЯ - 1000, "to": ВРЕМЯ + 1000})
    строки = тело(выписка)["result"]["transactions"]

    assert [(с["id"], с["time"], с["amount"], с["state"], с["reason"]) for с in строки] == [
        ("PM-1", ВРЕМЯ, СУММА, -2, 5)
    ]
    assert строки[0]["account"] == СЧЁТ

    пусто, _ = payme(сайт, "GetStatement", {"from": 1, "to": 2})

    assert тело(пусто)["result"]["transactions"] == []


def test_payme_вторая_транзакция_и_отмена(сайт):
    первая = {"id": "PM-1", "time": ВРЕМЯ, "amount": СУММА, "account": СЧЁТ}
    payme(сайт, "CreateTransaction", первая, сброс())

    # Пока первая жива — вторая по тому же счёту не заводится
    вторая, база = payme(сайт, "CreateTransaction", {**первая, "id": "PM-2"})

    assert код(вторая) == -31053
    assert len(база["transactions"]) == 1

    отмена, база = payme(сайт, "CancelTransaction", {"id": "PM-1", "reason": 3})

    assert тело(отмена)["result"]["state"] == -1
    assert транзакции(база) == [("payme", "PM-1", "cancelled", СУММА, False, True)]

    # Проводить отменённую нельзя, счёт ждёт оплаты дальше
    провести, база = payme(сайт, "PerformTransaction", {"id": "PM-1"})

    assert код(провести) == -31008
    assert счета(база)[0][1] == "pending" and база["subscriptions"] == []

    # После отмены — новая транзакция заводится
    снова, база = payme(сайт, "CreateTransaction", {**первая, "id": "PM-2"})

    assert тело(снова)["result"]["state"] == 1
    assert [t[1] for t in транзакции(база)] == ["PM-1", "PM-2"]


def test_payme_брошенная_попытка_не_мешает(сайт):
    первая = {"id": "PM-1", "time": ВРЕМЯ, "amount": СУММА, "account": СЧЁТ}
    payme(сайт, "CreateTransaction", первая, сброс())
    sql("update payment_transactions set created_at = now() - interval '1 hour'")

    ответ, база = payme(сайт, "CreateTransaction", {**первая, "id": "PM-2"})

    assert тело(ответ)["result"]["state"] == 1
    assert [t[1:3] for t in транзакции(база)] == [("PM-1", "cancelled"), ("PM-2", "created")]


def test_payme_истёкшая_транзакция(сайт):
    payme(
        сайт,
        "CreateTransaction",
        {"id": "PM-1", "time": ВРЕМЯ, "amount": СУММА, "account": СЧЁТ},
        сброс(),
    )
    sql("update payment_transactions set created_at = now() - interval '13 hours'")

    ответ, база = payme(сайт, "PerformTransaction", {"id": "PM-1"})

    assert код(ответ) == -31008
    assert транзакции(база)[0][2] == "cancelled"
    assert счета(база)[0][1] == "pending" and база["subscriptions"] == []

    статус, _ = payme(сайт, "CheckTransaction", {"id": "PM-1"})

    assert тело(статус)["result"]["state"] == -1
    assert тело(статус)["result"]["reason"] == 4


def test_payme_счёт_отменили_до_проведения(сайт):
    payme(
        сайт,
        "CreateTransaction",
        {"id": "PM-1", "time": ВРЕМЯ, "amount": СУММА, "account": СЧЁТ},
        сброс(),
    )
    sql("update payments set status = 'failed'")

    ответ, база = payme(сайт, "PerformTransaction", {"id": "PM-1"})

    assert код(ответ) == -31008
    assert транзакции(база)[0][2] == "cancelled"
    assert база["subscriptions"] == []


def test_payme_неизвестное(сайт):
    метод, _ = payme(сайт, "ChangePassword", {"password": "x"}, сброс())
    нет, _ = payme(сайт, "PerformTransaction", {"id": "NOPE"})

    assert код(метод) == -32601
    assert код(нет) == -31003


# ── Click ───────────────────────────────────────────────────────────


def подпись(form: dict[str, str], prepare_id: str = "") -> str:
    text = (
        form["click_trans_id"]
        + form["service_id"]
        + "click-secret"
        + form["merchant_trans_id"]
        + prepare_id
        + form["amount"]
        + form["action"]
        + form["sign_time"]
    )

    return hashlib.md5(text.encode(), usedforsecurity=False).hexdigest()


def форма(action: str, prepare_id: str = "", **extra: str) -> dict[str, str]:
    form = {
        "click_trans_id": "CL-1",
        "service_id": "111",
        "click_paydoc_id": "555",
        "merchant_trans_id": "SVD-000001",
        "amount": "1500.00",
        "action": action,
        "error": "0",
        "error_note": "Success",
        "sign_time": "2026-11-23 10:00:00",
        **extra,
    }

    if prepare_id:
        form["merchant_prepare_id"] = prepare_id

    form["sign_string"] = extra.get("sign_string") or подпись(form, prepare_id)

    return form


def click(
    сайт: str,
    шаг: str,
    form: dict[str, str],
    подготовка: Any = ничего,
    env: dict[str, str] | None = None,
) -> tuple[dict[str, Any], Any]:
    итог = отправить(
        сайт,
        f"/payments/click/callback/{шаг}",
        подготовка,
        снимок,
        body=urlencode(form),
        content_type="application/x-www-form-urlencoded",
        headers={"Accept": "application/json"},
        env=CLICK if env is None else env,
    )

    return итог["ответ"], итог["база"]


def test_click_выключен_404(сайт):
    ответ, _ = click(сайт, "prepare", форма("0"), сброс(), env={})

    assert ответ["status"] == 404


@pytest.mark.parametrize(
    ("form", "ждём"),
    [
        (форма("0", sign_string="0" * 32), -1),
        (форма("0", amount="1600.00"), -2),
        (форма("0", merchant_trans_id="SVD-999999"), -5),
        (форма("1"), -3),
    ],
)
def test_click_prepare_отказ(сайт, form, ждём):
    ответ, база = click(сайт, "prepare", form, сброс())

    assert тело(ответ)["error"] == ждём
    assert база["transactions"] == []


def test_click_оплата_выдаёт_тариф_один_раз(сайт):
    ответ, база = click(сайт, "prepare", форма("0"), сброс())
    prepare_id = тело(ответ)["merchant_prepare_id"]

    assert тело(ответ)["error"] == 0
    assert транзакции(база) == [("click", "CL-1", "created", СУММА, False, False)]

    # Повтор Prepare — тот же номер, второй строки нет
    повтор, база = click(сайт, "prepare", форма("0"))

    assert тело(повтор)["merchant_prepare_id"] == prepare_id
    assert len(база["transactions"]) == 1

    # Complete с чужим prepare_id — транзакция не найдена
    чужой, _ = click(сайт, "complete", форма("1", str(prepare_id + 1)))

    assert тело(чужой)["error"] == -6

    готово, база = click(сайт, "complete", форма("1", str(prepare_id)))

    assert тело(готово)["error"] == 0
    assert тело(готово)["merchant_confirm_id"] == prepare_id
    assert счета(база) == [("SVD-000001", "paid", True, "click", "CL-1")]
    assert транзакции(база) == [("click", "CL-1", "performed", СУММА, True, False)]
    assert len(база["subscriptions"]) == 1

    снова, база = click(сайт, "complete", форма("1", str(prepare_id)))

    assert тело(снова)["error"] == 0
    assert len(база["subscriptions"]) == 1

    # Новый Prepare по оплаченному счёту — «уже оплачен»
    другой, _ = click(сайт, "prepare", форма("0", click_trans_id="CL-2"))

    assert тело(другой)["error"] == -4


def test_click_оплата_не_прошла(сайт):
    ответ, _ = click(сайт, "prepare", форма("0"), сброс())
    prepare_id = str(тело(ответ)["merchant_prepare_id"])

    готово, база = click(
        сайт, "complete", форма("1", prepare_id, error="-5017", error_note="Not enough money")
    )

    assert тело(готово)["error"] == -9
    assert транзакции(база)[0][2] == "cancelled"
    assert счета(база)[0][1] == "pending" and база["subscriptions"] == []


# ── Касса кабинета ──────────────────────────────────────────────────


@pytest.mark.parametrize("провайдер", ["payme", "click"])
def test_оплатить_выбранным_провайдером(сайт, провайдер):
    сброс()()
    номер = _id("payments", "number = 'SVD-000001'")
    uid = учётка(
        "owner@savdex.uz",
        company_id=_id("companies", "slug = 'mine'"),
        email_verified_at="2026-01-01 00:00:00",
    )
    итог = отправить(
        сайт,
        f"/cabinet/billing/invoice/{номер}/pay",
        ничего,
        снимок,
        uid=uid,
        body={"provider": провайдер},
        headers=inertia(),
        env={**PAYME, **CLICK},
    )
    адрес_ = итог["ответ"]["headers"].get("x-inertia-location", "")

    assert итог["ответ"]["status"] == 409, итог["ответ"]["body"][:500]

    if провайдер == "payme":
        assert адрес_.startswith("https://checkout.paycom.uz/")
        params = base64.b64decode(адрес_.rsplit("/", 1)[1]).decode()

        assert "m=merchant-1;ac.invoice=SVD-000001;a=150000;" in params
    else:
        parts = urlsplit(адрес_)
        query = parse_qs(parts.query)

        assert f"{parts.scheme}://{parts.netloc}{parts.path}" == "https://my.click.uz/services/pay"
        assert query["service_id"] == ["111"] and query["merchant_id"] == ["222"]
        assert query["amount"] == ["1500.00"]
        assert query["transaction_param"] == ["SVD-000001"]

    # Ни строки транзакции, ни смены счёта: их заводит сам провайдер колбэком
    assert итог["база"]["transactions"] == []
    assert счета(итог["база"])[0][1] == "pending"
