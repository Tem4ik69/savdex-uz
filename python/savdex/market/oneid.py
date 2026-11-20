"""
OneID (id.egov.uz) — подтверждение продавца (ТЗ 18.11, разделы 4 и 10).

Ход: кабинет шлёт POST /market/api/oneid/start (оферта принята) → сервер
кладёт в сессию одноразовый state и отвечает адресом OneID → человек
входит в OneID → OneID возвращает его на ONEID_REDIRECT_URI
(/market/api/oneid/callback?code=…&state=…) → сервер сверяет state,
меняет code на токен, берёт профиль, сверяет ИНН компании и подтверждает
продавца.

## Что проверяется

- **state.** 32 случайных байта (secrets), в сессии вместе с номером
  пользователя, компании и временем. Запись из сессии снимается *до*
  проверок — второй раз тот же ответ не пройдёт. Срок — 10 минут;
  сравнение — hmac.compare_digest; пользователь в момент возврата —
  тот же, что начинал. Нет записи, чужой, просрочен, не совпал — отказ,
  code в OneID не отправляется вовсе.
- **Адрес возврата** — один, из настроек (ONEID_REDIRECT_URI, только
  https; http — лишь для 127.0.0.1/localhost на проверках). Из запроса
  он не берётся никогда: ни на шаге авторизации, ни при обмене code.
  После возврата человек уходит на постоянный адрес /market/sell?oneid=<итог>
  — итог из закрытого списка, никаких next/back из запроса.
- **ИНН.** Юрлицо — ИНН организации из legal_info (вход по ЭЦП); ИП —
  как физлицо: личный ИНН или ПИНФЛ. Не совпал с ИНН компании на
  SavdEx — продавец не подтверждается.

## Что храним из профиля — минимум (раздел 10)

В market_sellers: oneid_tin — совпавший ИНН компании (он и так есть в
карточке), verified_via = 'oneid', oneid_verified_at, oneid_pin_hash —
HMAC-SHA256 от ПИНФЛ на ключе ONEID_PIN_KEY. Сам ПИНФЛ, ФИО, паспорт,
дата рождения, адрес, телефон и почта из ответа OneID не записываются
никуда: ни в базу, ни в сессию, ни в журналы. Хеш нужен, чтобы человек,
чей продавец заблокирован, не вернулся через другую компанию.

Токены OneID живут только на время запроса; после профиля сессия OneID
закрывается (one_log_out), ошибка закрытия ничего не ломает.

## Настройки (секреты GitHub → окружение машины, в код — никогда)

ONEID_CLIENT_ID, ONEID_CLIENT_SECRET, ONEID_REDIRECT_URI, ONEID_PIN_KEY
(не короче 32 знаков); ONEID_URL — адрес OAuth OneID (по умолчанию
sso.egov.uz), ONEID_SCOPE — по умолчанию client_id. Пока хоть одной нет —
OneID выключен: кнопка не показывается, адреса отвечают «не подключён».

Имена полей профиля — по общедоступному описанию OneID; сверить с
документацией из договора (ТЗ, 11.5), когда дадут доступ. Там же
уточнить, отдаёт ли legal_info только организации, где человек —
руководитель (право подписи): если нет — фильтровать по полю роли.

ONEID_REDIRECT_URI — на том же адресе, где кнопка, или на домене общей
куки: state лежит в сессии. Смена ONEID_PIN_KEY обнуляет сверку
«заблокированный не вернётся» — ключ не менять без пересчёта.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import logging
import os
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx
from django.db import transaction
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect

from savdex.market import sellers
from savdex.market.common import now, one, write
from savdex.web import session
from savdex.web.tin import normalize

log = logging.getLogger(__name__)

DEFAULT_URL = "https://sso.egov.uz/sso/oauth/Authorization.do"

#: Ключ записи в сессии
SESSION_KEY = "market_oneid"

#: Сколько живёт state, секунд
STATE_TTL = 600

#: Связь с OneID: соединение — 5 с, ответ — 15 с
TIMEOUT = httpx.Timeout(15.0, connect=5.0)

#: Итоги возврата — только они попадают в адрес /market/sell?oneid=…
RESULTS = ("ok", "review", "off", "denied", "expired", "mismatch", "blocked", "error")


#: Предупреждение о негодных настройках — один раз на процесс
_warned = False


class OneIdError(Exception):
    """Отказ OneID или обрыв связи. Текст — без данных ответа."""


@dataclass(frozen=True)
class Config:
    url: str
    client_id: str
    client_secret: str
    redirect_uri: str
    scope: str
    pin_key: bytes


@dataclass(frozen=True)
class Identity:
    """Из профиля — только то, что нужно для сверки; дальше не уходит."""

    pin: str
    personal_tin: str | None
    legal_tins: tuple[str, ...]


def _redirect_ok(uri: str) -> bool:
    parts = urlsplit(uri)

    if not parts.hostname or parts.username or parts.password or parts.fragment:
        return False

    if parts.scheme == "https":
        return True

    return parts.scheme == "http" and parts.hostname in ("127.0.0.1", "localhost")


def config() -> Config | None:
    """Настройки OneID — или None: чего-то нет или адрес возврата негодный."""
    client_id = os.environ.get("ONEID_CLIENT_ID", "").strip()
    secret = os.environ.get("ONEID_CLIENT_SECRET", "").strip()
    redirect_uri = os.environ.get("ONEID_REDIRECT_URI", "").strip()
    pin_key = os.environ.get("ONEID_PIN_KEY", "").strip()
    url = os.environ.get("ONEID_URL", "").strip() or DEFAULT_URL

    if not (client_id and secret and redirect_uri and len(pin_key) >= 32):
        return None

    if not _redirect_ok(redirect_uri) or not _redirect_ok(url):
        global _warned

        if not _warned:
            _warned = True
            log.warning("OneID выключен: ONEID_REDIRECT_URI или ONEID_URL — не https")

        return None

    return Config(
        url=url,
        client_id=client_id,
        client_secret=secret,
        redirect_uri=redirect_uri,
        scope=os.environ.get("ONEID_SCOPE", "").strip() or client_id,
        pin_key=pin_key.encode(),
    )


def enabled() -> bool:
    return config() is not None


# ── state ───────────────────────────────────────────────────────────


def issue_state(store: session.Store, user_id: int, company_id: int) -> str:
    """Новый state взамен прежнего: в сессии — одна попытка за раз."""
    state = secrets.token_urlsafe(32)
    store.put(
        SESSION_KEY,
        {"state": state, "user": user_id, "company": company_id, "at": int(time.time())},
    )

    return state


def take_state(store: session.Store, given: str, user_id: int) -> int | None:
    """
    Сверка state: номер компании — или None. Запись снимается сразу,
    удачна проверка или нет: ответ OneID одноразовый.
    """
    entry = store.get(SESSION_KEY)
    store.forget(SESSION_KEY)

    if not isinstance(entry, dict) or not isinstance(given, str) or not given:
        return None

    expected = entry.get("state")
    at = entry.get("at")

    if not isinstance(expected, str) or not isinstance(at, int):
        return None

    if not 0 <= time.time() - at <= STATE_TTL:
        return None

    if entry.get("user") != user_id:
        return None

    if not hmac.compare_digest(expected.encode(), given.encode()):
        return None

    company = entry.get("company")

    return company if isinstance(company, int) else None


def authorize_url(cfg: Config, state: str) -> str:
    query = urlencode(
        {
            "response_type": "one_code",
            "client_id": cfg.client_id,
            "redirect_uri": cfg.redirect_uri,
            "scope": cfg.scope,
            "state": state,
        }
    )

    return f"{cfg.url}?{query}"


# ── Профиль ─────────────────────────────────────────────────────────


def _digits(value: Any, length: int) -> str | None:  # noqa: ANN401
    text = str(value or "").strip()

    return text if re.fullmatch(rf"\d{{{length}}}", text) else None


def identity(profile: Any) -> Identity:  # noqa: ANN401
    """Ответ OneID → Identity. Всё остальное из ответа отбрасывается."""
    # Только явное «valid: true»: нет поля — не подтверждён
    if not isinstance(profile, dict) or profile.get("valid") not in (True, "true", "True"):
        raise OneIdError("OneID: профиль не подтверждён")

    pin = _digits(profile.get("pin"), 14)

    if pin is None:
        raise OneIdError("OneID: в профиле нет ПИНФЛ")

    legal: list[str] = []

    for item in profile.get("legal_info") or []:
        if isinstance(item, dict):
            number = _digits(item.get("le_tin") or item.get("tin"), 9)

            if number is not None and number not in legal:
                legal.append(number)

    return Identity(pin=pin, personal_tin=_digits(profile.get("tin"), 9), legal_tins=tuple(legal))


def matched_tin(person: Identity, company_tin: Any, legal_form: Any) -> str | None:  # noqa: ANN401
    """
    Номер компании, если он совпал с OneID. Юрлицо (legal_form = legal или
    пусто) — только ИНН организации из legal_info (вход по ЭЦП); физлицо,
    ИП, фрилансер — личный ИНН или ПИНФЛ. Личный номер у «юрлица» его не
    подтверждает: иначе физлицо выдало бы себя за ООО.
    """
    tin = normalize(company_tin)

    if not isinstance(tin, str) or not tin:
        return None

    if (legal_form or "legal") == "legal":
        candidates = set(person.legal_tins)
    else:
        candidates = {person.pin}

        if person.personal_tin is not None:
            candidates.add(person.personal_tin)

    return tin if tin in candidates else None


def pin_hash(cfg: Config, pin: str) -> str:
    return hmac.new(cfg.pin_key, pin.encode(), hashlib.sha256).hexdigest()


# ── Обмен с OneID ───────────────────────────────────────────────────


def _call(cfg: Config, data: dict[str, str]) -> dict[str, Any]:
    payload = {"client_id": cfg.client_id, "client_secret": cfg.client_secret, **data}

    try:
        response = httpx.post(cfg.url, data=payload, timeout=TIMEOUT)
    except httpx.HTTPError as error:
        # Только тип ошибки: в тексте httpx бывает адрес с параметрами
        raise OneIdError(f"OneID: нет связи ({type(error).__name__})") from None

    if response.status_code != 200:
        raise OneIdError(f"OneID: ответ {response.status_code}")

    try:
        body = response.json()
    except ValueError:
        raise OneIdError("OneID: ответ не JSON") from None

    if not isinstance(body, dict):
        raise OneIdError("OneID: ответ не объект")

    return body


def fetch_identity(cfg: Config, code: str) -> Identity:
    """code → токен → профиль → Identity; сессия OneID закрывается."""
    token = _call(
        cfg,
        {"grant_type": "one_authorization_code", "code": code, "redirect_uri": cfg.redirect_uri},
    ).get("access_token")

    if not isinstance(token, str) or not token:
        raise OneIdError("OneID: нет access_token")

    try:
        profile = _call(
            cfg,
            {"grant_type": "one_access_token_identify", "access_token": token, "scope": cfg.scope},
        )

        return identity(profile)
    finally:
        with contextlib.suppress(OneIdError):
            _call(cfg, {"grant_type": "one_log_out", "access_token": token, "scope": cfg.scope})


# ── Продавец ────────────────────────────────────────────────────────


def confirm_seller(cfg: Config, person: Identity, user: dict[str, Any], company_id: int) -> str:
    """Подтвердить продавца по OneID: итог из RESULTS."""
    with transaction.atomic():
        company = one(
            "select id, tin, legal_form, status, deleted_at from companies "
            "where id = %s for update",
            [company_id],
        )

        if (
            company is None
            or company["deleted_at"] is not None
            or company["status"] != "active"
            or user.get("company_id") != company_id
            or user.get("company_role") != "owner"
        ):
            return "denied"

        matched = matched_tin(person, company["tin"], company["legal_form"])

        if matched is None:
            return "mismatch"

        digest = pin_hash(cfg, person.pin)
        # Совпал ПИНФЛ (ИП) — сам номер не пишем: хватает хеша
        tin = None if matched == person.pin else matched

        # Заблокированный продавец не возвращается через другую компанию: тот
        # же человек (хеш ПИНФЛ) или номер, подтверждённый OneID. ИНН из
        # карточки без OneID не в счёт: карточку с чужим ИНН мог завести и
        # заблокировать не владелец — настоящему юрлицу путь не закрываем
        banned = one(
            "select 1 as x from market_sellers where status = 'blocked' and company_id <> %s "
            "and (oneid_pin_hash = %s or oneid_tin = %s) limit 1",
            [company_id, digest, matched],
        )
        seller = one("select * from market_sellers where company_id = %s for update", [company_id])

        if banned is not None or (seller is not None and seller["status"] == "blocked"):
            return "blocked"

        moment = now()

        # Отказ модератора по существу OneID не снимает: заявка — снова на
        # проверку, уже с отметкой OneID
        if seller is not None and seller["status"] == "rejected":
            write(
                "update market_sellers set status = 'pending', verified_via = 'oneid', "
                "oneid_tin = %s, oneid_pin_hash = %s, oneid_verified_at = %s, user_id = %s, "
                "offer_version = %s, offer_accepted_at = %s, reject_reason = null, "
                "reviewed_by = null, reviewed_at = null, updated_at = %s "
                "where id = %s and status = 'rejected'",
                [
                    tin,
                    digest,
                    moment,
                    user["id"],
                    sellers.OFFER_VERSION,
                    moment,
                    moment,
                    seller["id"],
                ],
            )
            log.info("OneID: компания %s — заявка снова на проверке", company_id)

            return "review"

        if seller is None:
            written = write(
                "insert into market_sellers (company_id, user_id, status, verified_via, oneid_tin, "
                "oneid_pin_hash, oneid_verified_at, offer_version, offer_accepted_at, approved_at, "
                "created_at, updated_at) values (%s, %s, 'approved', 'oneid', %s, %s, %s, %s, %s, "
                "%s, %s, %s) on conflict (company_id) do nothing",
                [
                    company_id,
                    user["id"],
                    tin,
                    digest,
                    moment,
                    sellers.OFFER_VERSION,
                    moment,
                    moment,
                    moment,
                    moment,
                ],
            )
        else:
            written = write(
                "update market_sellers set status = 'approved', verified_via = 'oneid', "
                "oneid_tin = %s, oneid_pin_hash = %s, oneid_verified_at = %s, user_id = %s, "
                "offer_version = %s, offer_accepted_at = %s, "
                "approved_at = coalesce(approved_at, %s), reject_reason = null, "
                "updated_at = %s where id = %s and status in ('pending', 'approved')",
                [
                    tin,
                    digest,
                    moment,
                    user["id"],
                    sellers.OFFER_VERSION,
                    moment,
                    moment,
                    moment,
                    seller["id"],
                ],
            )

        if not written:
            return "error"

    # Только номера: ни ИНН, ни ПИНФЛ, ни имени — в журнал приложения
    log.info("OneID: компания %s подтверждена как продавец", company_id)

    return "ok"


# ── Возврат из OneID ────────────────────────────────────────────────


def result_redirect(root: str, result: str) -> HttpResponse:
    """Постоянный адрес кабинета продавца с итогом из закрытого списка."""
    code = result if result in RESULTS else "error"

    return HttpResponseRedirect(f"{root}/market/sell?{urlencode({'oneid': code})}")


def callback(request: HttpRequest) -> HttpResponse:
    """GET ?code&state (или ?error) — от OneID."""
    from django.http import HttpResponseNotAllowed

    from savdex.web.request import context

    if request.method not in ("GET", "HEAD"):
        return HttpResponseNotAllowed(["GET", "HEAD"])

    ctx = context(request, redirect=False)

    if isinstance(ctx, HttpResponse):
        return ctx

    cfg = config()

    if cfg is None:
        return result_redirect(ctx.root, "off")

    started = session.start(request)
    user = ctx.user

    if started is None or user is None:
        return result_redirect(ctx.root, "expired")

    company_id = take_state(started[0], request.GET.get("state", ""), int(user["id"]))

    if company_id is None:
        return result_redirect(ctx.root, "expired")

    code = request.GET.get("code", "")

    # Отказ в OneID или пустой code — дальше не идём
    if request.GET.get("error") or not re.fullmatch(r"[A-Za-z0-9._~-]{1,512}", code):
        return result_redirect(ctx.root, "denied")

    try:
        person = fetch_identity(cfg, code)
    except OneIdError as error:
        log.warning("%s", error)

        return result_redirect(ctx.root, "error")

    return result_redirect(ctx.root, confirm_seller(cfg, person, user, company_id))
