"""
OneID у продавца (savdex/market/oneid.py, ТЗ 18.11, 11.4 — безопасность).

- state: одноразовый, со сроком, привязан к пользователю; чужой,
  просроченный или повторный ответ не доходит до обмена code;
- адрес возврата — только из настроек, http — лишь для localhost;
  после возврата — постоянный адрес с итогом из закрытого списка;
- из профиля — минимум: ИНН компании, время, хеш ПИНФЛ; ни ПИНФЛ, ни ФИО
  не попадают ни в базу, ни в сессию;
- ИНН компании должен совпасть с OneID; человек с заблокированным
  продавцом не возвращается через другую компанию.

Проход целиком — с поддельным сервером OneID на 127.0.0.1.
Нужен PostgreSQL (SAVDEX_PARITY_PG_URL) для части проверок.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar
from urllib.parse import parse_qs, urlsplit

import pytest

from savdex.market import oneid

from .pg_admin import sql, нужна_база, свежая_база
from .test_market import _json, _post, _компания, _продавец, _человек
from .test_web_forms import SID, отправить
from .web_site import адрес, строка

PIN = "31234567890123"
КЛЮЧ = "k" * 40
ФИО = "ТЕСТОВ ТЕСТ ТЕСТОВИЧ"


class _Store:
    """Сессия без базы — для проверок state."""

    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def put(self, key: str, value: Any) -> None:
        self.data[key] = value

    def forget(self, key: str) -> None:
        self.data.pop(key, None)


def _cfg() -> oneid.Config:
    return oneid.Config(
        url="https://sso.example/oauth",
        client_id="savdex",
        client_secret="s",
        redirect_uri="https://market.savdex.uz/market/api/oneid/callback",
        scope="savdex",
        pin_key=КЛЮЧ.encode(),
    )


# ── Без базы ────────────────────────────────────────────────────────


def test_state_одноразовый_и_свой():
    store = _Store()
    state = oneid.issue_state(store, 7, 70)  # type: ignore[arg-type]
    assert len(state) >= 40

    assert oneid.take_state(store, state, 7) == 70  # type: ignore[arg-type]
    assert oneid.take_state(store, state, 7) is None, "повтор"  # type: ignore[arg-type]

    state = oneid.issue_state(store, 7, 70)  # type: ignore[arg-type]
    assert oneid.take_state(store, state, 8) is None, "чужой пользователь"  # type: ignore[arg-type]
    assert oneid.SESSION_KEY not in store.data, "запись снята и после отказа"

    state = oneid.issue_state(store, 7, 70)  # type: ignore[arg-type]
    assert oneid.take_state(store, state + "x", 7) is None  # type: ignore[arg-type]

    oneid.issue_state(store, 7, 70)  # type: ignore[arg-type]
    assert oneid.take_state(store, "", 7) is None  # type: ignore[arg-type]

    state = oneid.issue_state(store, 7, 70)  # type: ignore[arg-type]
    store.data[oneid.SESSION_KEY]["at"] = int(time.time()) - oneid.STATE_TTL - 1
    assert oneid.take_state(store, state, 7) is None, "просрочен"  # type: ignore[arg-type]

    assert oneid.take_state(_Store(), "любой", 7) is None, "без начала"  # type: ignore[arg-type]


def test_адрес_возврата_только_из_настроек(monkeypatch):
    for name in ("ONEID_CLIENT_ID", "ONEID_CLIENT_SECRET", "ONEID_REDIRECT_URI", "ONEID_PIN_KEY"):
        monkeypatch.delenv(name, raising=False)

    assert oneid.config() is None

    monkeypatch.setenv("ONEID_CLIENT_ID", "savdex")
    monkeypatch.setenv("ONEID_CLIENT_SECRET", "s")
    monkeypatch.setenv("ONEID_PIN_KEY", КЛЮЧ)

    for плохой in (
        "http://savdex.uz/market/api/oneid/callback",
        "https://user:pw@savdex.uz/cb",
        "https://savdex.uz/cb#x",
        "javascript:alert(1)",
        "//savdex.uz/cb",
    ):
        monkeypatch.setenv("ONEID_REDIRECT_URI", плохой)
        assert oneid.config() is None, плохой

    monkeypatch.setenv("ONEID_REDIRECT_URI", "https://savdex.uz/market/api/oneid/callback")
    monkeypatch.setenv("ONEID_PIN_KEY", "короткий")
    assert oneid.config() is None, "ключ хеша короче 32 знаков"

    monkeypatch.setenv("ONEID_PIN_KEY", КЛЮЧ)
    cfg = oneid.config()
    assert cfg is not None

    адрес = urlsplit(oneid.authorize_url(cfg, "STATE"))
    query = parse_qs(адрес.query)
    assert адрес.netloc == "sso.egov.uz"
    assert query["redirect_uri"] == ["https://savdex.uz/market/api/oneid/callback"]
    assert query["state"] == ["STATE"] and query["response_type"] == ["one_code"]


def test_итог_возврата_из_закрытого_списка():
    for итог in ("ok", "mismatch", "//evil.com", "https://evil.com", "ok&next=//evil.com"):
        ответ = oneid.result_redirect("https://savdex.uz", итог)
        адрес = urlsplit(ответ["Location"])
        assert (адрес.scheme, адрес.netloc, адрес.path) == ("https", "savdex.uz", "/market/sell")
        assert parse_qs(адрес.query)["oneid"][0] in oneid.RESULTS


def test_из_профиля_минимум():
    профиль = {
        "valid": "true",
        "pin": PIN,
        "tin": "412345678",
        "full_name": ФИО,
        "pport_no": "AA1234567",
        "birth_date": "1990-01-01",
        "legal_info": [{"is_basic": True, "le_tin": "301234567", "le_name": "OOO Test"}, "мусор"],
    }
    person = oneid.identity(профиль)
    assert person == oneid.Identity(PIN, "412345678", ("301234567",))
    assert ФИО not in repr(person) and "AA1234567" not in repr(person)

    with pytest.raises(oneid.OneIdError):
        oneid.identity({**профиль, "valid": False})

    with pytest.raises(oneid.OneIdError, match="не подтверждён"):
        oneid.identity({k: v for k, v in профиль.items() if k != "valid"})

    with pytest.raises(oneid.OneIdError):
        oneid.identity({**профиль, "pin": "123"})

    with pytest.raises(oneid.OneIdError):
        oneid.identity(["не объект"])


def test_сверка_инн():
    person = oneid.Identity(PIN, "412345678", ("301234567",))
    m = oneid.matched_tin
    assert m(person, "301 234-567", "legal") == "301234567", "юрлицо по ЭЦП"
    assert m(person, "412345678", "individual") == "412345678", "ИП — личный ИНН"
    assert m(person, PIN, "freelancer") == PIN, "ИП — ПИНФЛ"
    assert m(person, "412345678", "legal") is None, "личный ИНН — не ООО"
    assert m(person, PIN, None) is None, "без формы — как юрлицо"
    assert m(person, "301234567", "individual") is None
    assert m(person, "309999999", "legal") is None
    assert m(person, "", "legal") is None and m(person, None, "individual") is None

    хеш = oneid.pin_hash(_cfg(), PIN)
    assert len(хеш) == 64 and PIN not in хеш
    assert хеш != oneid.pin_hash(_cfg(), "31234567890124")


# ── Проход целиком ──────────────────────────────────────────────────


@pytest.fixture(scope="module")
def сайт() -> Iterator[str]:
    свежая_база()

    with адрес() as root:
        yield root


class _OneId(BaseHTTPRequestHandler):
    """Поддельный OneID: code GOOD → токен → профиль; счёт обращений."""

    calls: ClassVar[list[dict[str, str]]] = []
    profile: ClassVar[dict[str, Any]] = {}

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        form = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode()).items()}
        type(self).calls.append(form)
        grant = form.get("grant_type")

        if grant == "one_authorization_code" and form.get("code") == "GOOD":
            body: Any = {"access_token": "AT", "token_type": "Bearer"}
        elif grant == "one_access_token_identify" and form.get("access_token") == "AT":
            body = type(self).profile
        elif grant == "one_log_out":
            body = {"ok": True}
        else:
            self.send_response(400)
            self.end_headers()
            return

        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args: Any) -> None:
        pass


@pytest.fixture(scope="module")
def сервер() -> Iterator[dict[str, str]]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _OneId)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}/sso/oauth/Authorization.do"

    yield {
        "ONEID_URL": url,
        "ONEID_CLIENT_ID": "savdex",
        "ONEID_CLIENT_SECRET": "secret",
        "ONEID_REDIRECT_URI": "http://127.0.0.1/market/api/oneid/callback",
        "ONEID_PIN_KEY": КЛЮЧ,
    }

    server.shutdown()


def _профиль(tin: str) -> dict[str, Any]:
    return {
        "valid": "true",
        "pin": PIN,
        "tin": "412345678",
        "full_name": ФИО,
        "legal_info": [{"is_basic": True, "le_tin": tin, "le_name": "OOO"}],
    }


def _возврат(
    root: str, uid: int, env: dict[str, str], query: str, запись: dict[str, Any] | None
) -> dict[str, Any]:
    данные = {oneid.SESSION_KEY: запись} if запись is not None else {}

    return отправить(
        root,
        f"/market/api/oneid/callback?{query}",
        lambda: None,
        uid=uid,
        данные=данные,
        method="GET",
        headers={"Accept": "text/html"},
        env=env,
    )


def _итог(ответ: dict[str, Any]) -> str:
    assert ответ["ответ"]["status"] == 302, ответ["ответ"]["body"][:500]
    location = ответ["ответ"]["headers"]["location"]
    адрес = urlsplit(location)
    assert адрес.path == "/market/sell" and адрес.netloc.startswith("127.0.0.1")

    return parse_qs(адрес.query)["oneid"][0]


@нужна_база
def test_oneid_проход(сайт, сервер):
    компания = _компания("OneID Test", "oneid-test", tin="305550001")
    владелец = _человек("owner@oneid.uz", компания)
    менеджер = _человек("manager@oneid.uz", компания, role="manager")

    # Выключен — кнопка скрыта, старт отвечает «не подключён»
    assert _post(сайт, "/market/api/oneid/start", владелец, {"offer": True})["status"] == 409

    def старт(uid: int, body: dict[str, Any]) -> dict[str, Any]:
        return отправить(
            сайт,
            "/market/api/oneid/start",
            lambda: None,
            uid=uid,
            body=body,
            headers=_заголовки(),
            env=сервер,
        )

    assert старт(владелец, {})["ответ"]["status"] == 422, "без оферты"
    assert старт(менеджер, {"offer": True})["ответ"]["status"] == 422, "только владелец"

    начал = старт(владелец, {"offer": True})
    assert начал["ответ"]["status"] == 200, начал["ответ"]["body"]
    адрес = urlsplit(_json(начал["ответ"])["redirect"])
    query = parse_qs(адрес.query)
    assert query["redirect_uri"] == [сервер["ONEID_REDIRECT_URI"]]
    запись = _сессия(начал)[oneid.SESSION_KEY]
    assert запись["state"] == query["state"][0] and запись["company"] == компания

    _OneId.profile = _профиль("305550001")
    _OneId.calls.clear()

    # Чужой state — code в OneID не уходит
    плохой = _возврат(сайт, владелец, сервер, "code=GOOD&state=WRONG", запись)
    assert _итог(плохой) == "expired" and _OneId.calls == []
    assert oneid.SESSION_KEY not in _сессия(плохой), "попытка сгорела"

    # Без начала (нет записи в сессии)
    assert _итог(_возврат(сайт, владелец, сервер, "code=GOOD&state=x", None)) == "expired"

    # Отказ в OneID
    отказ = _возврат(сайт, владелец, сервер, f"error=denied&state={запись['state']}", запись)
    assert _итог(отказ) == "denied" and _OneId.calls == []

    # Другой человек в той же сессии не завершит чужой вход
    assert (
        _итог(_возврат(сайт, менеджер, сервер, f"code=GOOD&state={запись['state']}", запись))
        == "expired"
    )

    # ИНН не совпал
    _OneId.profile = _профиль("309999999")
    assert (
        _итог(_возврат(сайт, владелец, сервер, f"code=GOOD&state={запись['state']}", запись))
        == "mismatch"
    )
    assert sql("select 1 from market_sellers where company_id = %s", [компания]) == []

    # Всё сошлось
    _OneId.profile = _профиль("305550001")
    _OneId.calls.clear()
    итог = _возврат(сайт, владелец, сервер, f"code=GOOD&state={запись['state']}", запись)
    assert _итог(итог) == "ok"
    assert [c["grant_type"] for c in _OneId.calls] == [
        "one_authorization_code",
        "one_access_token_identify",
        "one_log_out",
    ]
    assert _OneId.calls[0]["redirect_uri"] == сервер["ONEID_REDIRECT_URI"]

    [(status, via, tin, хеш, когда)] = sql(
        "select status, verified_via, oneid_tin, oneid_pin_hash, oneid_verified_at "
        "from market_sellers where company_id = %s",
        [компания],
    )
    assert (status, via, tin) == ("approved", "oneid", "305550001")
    assert когда is not None and хеш == oneid.pin_hash(_cfg(), PIN) and PIN not in хеш

    # Персональных данных из профиля нет ни в базе продавцов, ни в сессии
    [строка_продавца] = sql(
        "select row_to_json(s)::text from market_sellers s where company_id = %s", [компания]
    )
    assert PIN not in строка_продавца[0] and ФИО not in строка_продавца[0]
    сессия = json.dumps(строка(SID), ensure_ascii=False)
    assert PIN not in сессия and ФИО not in сессия
    assert oneid.SESSION_KEY not in _сессия(итог), "токен и state в сессии не остаются"

    # Тот же человек, продавец заблокирован — через другую компанию не вернётся
    sql(
        "update market_sellers set status = 'blocked', blocked_at = now() where company_id = %s",
        [компания],
    )
    другая = _компания("OneID Second", "oneid-second", tin="305550002")
    второй = _человек("owner2@oneid.uz", другая)
    _OneId.profile = _профиль("305550002")
    начал2 = старт(второй, {"offer": True})
    запись2 = _сессия(начал2)[oneid.SESSION_KEY]
    assert (
        _итог(_возврат(сайт, второй, сервер, f"code=GOOD&state={запись2['state']}", запись2))
        == "blocked"
    )
    assert sql("select 1 from market_sellers where company_id = %s", [другая]) == []

    def пройти(uid: int, tin: str) -> str:
        _OneId.profile = _профиль(tin)
        запись_ = _сессия(старт(uid, {"offer": True}))[oneid.SESSION_KEY]
        return _итог(_возврат(сайт, uid, сервер, f"code=GOOD&state={запись_['state']}", запись_))

    # Личный ИНН у «юрлица» не подтверждает его
    шестая = _компания("OneID Sixth", "oneid-sixth", tin="412345678")
    assert пройти(_человек("owner6@oneid.uz", шестая), "305559999") == "mismatch"

    sql(
        "update market_sellers set status = 'approved', blocked_at = null where company_id = %s",
        [компания],
    )

    # Номер, подтверждённый OneID у заблокированного (другой человек), — нет
    третья = _компания("OneID Third", "oneid-third", tin="305550004")
    sql(
        "insert into market_sellers (company_id, status, verified_via, oneid_tin, "
        "oneid_pin_hash, oneid_verified_at, approved_at, blocked_at) values "
        "(%s, 'blocked', 'oneid', '305550004', %s, now(), now(), now())",
        [третья, "0" * 64],
    )
    четвёртая = _компания("OneID Fourth", "oneid-fourth", tin="305550004")
    assert пройти(_человек("owner4@oneid.uz", четвёртая), "305550004") == "blocked"

    # Тот же ИНН лишь в карточке, заблокированной вручную, — путь не закрыт
    _продавец(_компания("Самозванец", "oneid-squatter", tin="305550008"), status="blocked")
    настоящая = _компания("OneID Real", "oneid-real", tin="305550008")
    assert пройти(_человек("owner8@oneid.uz", настоящая), "305550008") == "ok"

    # ИП по ПИНФЛ: подтверждён, но сам ПИНФЛ в oneid_tin не пишется
    ип = _компания("ИП Тестов", "ip-testov", tin=PIN, legal_form="individual")
    assert пройти(_человек("owner7@oneid.uz", ип), "305559999") == "ok"
    assert sql("select status, oneid_tin from market_sellers where company_id = %s", [ип]) == [
        ("approved", None)
    ]

    # Отклонённую модератором заявку OneID не одобряет — снова на проверку
    пятая = _компания("OneID Fifth", "oneid-fifth", tin="305550005")
    sql(
        "insert into market_sellers (company_id, status, reject_reason) "
        "values (%s, 'rejected', 'Документы не читаются')",
        [пятая],
    )
    assert пройти(_человек("owner5@oneid.uz", пятая), "305550005") == "review"
    assert sql(
        "select status, verified_via, oneid_tin from market_sellers where company_id = %s",
        [пятая],
    ) == [("pending", "oneid", "305550005")]


def _сессия(ответ: dict[str, Any]) -> dict[str, Any]:
    return dict(json.loads(ответ["сессия"]["payload"]))


def _заголовки() -> dict[str, str]:
    from .test_market import JSON
    from .test_web_forms import xsrf

    return {**JSON, "X-XSRF-TOKEN": xsrf()}


@нужна_база
def test_состояние_продавца_показывает_oneid(сайт, сервер):
    компания = _компания("OneID State", "oneid-state", tin="305550003")
    владелец = _человек("owner3@oneid.uz", компания)
    _продавец(компания, status="pending")

    ответ = отправить(
        сайт,
        "/market/api/me/seller",
        lambda: None,
        uid=владелец,
        method="GET",
        headers=_заголовки(),
        env=сервер,
    )["ответ"]
    assert _json(ответ)["oneid"] is True
    assert _json(ответ)["verifiedVia"] is None
