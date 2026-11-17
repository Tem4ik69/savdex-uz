"""
Разговор с Telegram-ботом: привязка к учётной записи и меню уведомлений
о новых объявлениях и тендерах (рассылка — savdex/telegram_feed.py).

Привязка — только одноразовой ссылкой из кабинета (Н38, решение
директора 15.11): «Настройки → Telegram → Подключить» кладёт токен в кэш
на 15 минут, бот по /start <токен> привязывает чат к вошедшему человеку.
ИНН, ПИНФЛ, почту и код в бота больше не вводят — перебором ИНН можно
было узнавать, какие компании есть на площадке и чьи почты к ним
относятся. Имени и почты человека бот в ответах не пишет.

Без ссылки (/start, любой текст) — подсказка, где её взять, и кнопка в
настройки. Состояние разговора — telegram_bot_chats (шаг и язык).
Категории в боте не выбираются: они общие на компанию и меняются на
сайте («Настройки → Категории»), бот даёт кнопку туда и паузу рассылки
(notification_preferences, событие category_feed).
"""

from __future__ import annotations

import html
import os
from typing import Any

from django.db import connection

from savdex import laravel_cache
from savdex.guards import allowed_writes
from savdex.web import eloquent, locales, messaging, ui
from savdex.web.listing_actions import _now
from savdex.web.messaging import Button
from savdex.web.settings_actions import LINK_PREFIX

#: Событие настроек уведомлений: рассылка по категориям (галочка «Telegram»)
FEED_EVENT = "category_feed"

#: Шаг «не привязан, ждём ссылку из кабинета». В таблице это прежнее
#: значение «inn» (ограничение столбца state), ИНН бот больше не спрашивает
WAITING = "inn"

#: Поля прежней привязки по ИНН и коду: при любом ответе — стираются,
#: чтобы ИНН (у ИП — ПИНФЛ) и хеш кода не лежали в базе без дела
_CLEARED: dict[str, Any] = {
    "tin": None,
    "user_id": None,
    "code_hash": None,
    "code_expires_at": None,
    "mistakes": 0,
    "locked_until": None,
}


# ── База ─────────────────────────────────────────────────────────────


def _rows(query: str, params: list[Any]) -> list[dict[str, Any]]:
    with connection.cursor() as cursor:
        cursor.execute(query, params)
        columns = [c[0] for c in cursor.description or []]

        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _execute(query: str, params: list[Any]) -> None:
    with allowed_writes("telegram_bot_chats"), connection.cursor() as cursor:
        cursor.execute(query, params)


def _chat(chat_id: str, language: str) -> dict[str, Any]:
    """Строка разговора; новая — на языке Telegram, уже привязанный чат — сразу «done»."""
    found = _rows("select * from telegram_bot_chats where chat_id = %s", [chat_id])

    if found:
        return found[0]

    linked = _linked_user(chat_id)
    locale = linked["locale"] if linked else (language if locales.supports(language) else "ru")
    now = _now()
    _execute(
        "insert into telegram_bot_chats (chat_id, state, locale, created_at, updated_at) "
        "values (%s, %s, %s, %s, %s) on conflict (chat_id) do nothing",
        [chat_id, "done" if linked else WAITING, locale, now, now],
    )

    return _rows("select * from telegram_bot_chats where chat_id = %s", [chat_id])[0]


def _update(chat: dict[str, Any], **changes: Any) -> None:
    changes["updated_at"] = _now()
    columns = ", ".join(f"{name} = %s" for name in changes)
    _execute(
        f"update telegram_bot_chats set {columns} where chat_id = %s",
        [*changes.values(), chat["chat_id"]],
    )
    chat.update(changes)


def _linked_user(chat_id: str) -> dict[str, Any] | None:
    rows = _rows(
        "select * from users where telegram_chat_id = %s and deleted_at is null "
        "and status = 'active' order by telegram_linked_at desc nulls last, id desc limit 1",
        [chat_id],
    )

    return rows[0] if rows else None


def _active_user(user_id: object) -> dict[str, Any] | None:
    rows = _rows(
        "select * from users where id = %s and deleted_at is null and status = 'active'",
        [user_id],
    )

    return rows[0] if rows else None


# ── Ответы ───────────────────────────────────────────────────────────


def _t(chat: dict[str, Any], key: str, **replace: object) -> str:
    return ui.t(f"messages.bot.{key}", chat["locale"], **replace)


def _app_url(chat: dict[str, Any], path: str) -> str:
    root = (os.environ.get("APP_URL") or "http://localhost").rstrip("/")

    return root + locales.prefix(chat["locale"]) + path


def _say(chat: dict[str, Any], text: str, buttons: list[list[Button]] | None = None) -> None:
    messaging.telegram_send(chat["chat_id"], text, buttons)


def _e(value: object) -> str:
    return html.escape(str(value), quote=False)


# ── Категории и пауза ────────────────────────────────────────────────


def categories_of(company_id: object, locale: str) -> list[str]:
    from savdex.web.directory import _named

    ids = [
        r["category_id"]
        for r in _rows(
            "select category_id from company_category where company_id = %s order by id",
            [company_id],
        )
    ]

    if not ids:
        return []

    names = _named("categories", locale)

    return [names.get(i, str(i)) for i in ids]


def feed_on(user_id: object) -> bool:
    """Галочка рассылки по категориям: по умолчанию включена."""
    rows = _rows(
        "select telegram from notification_preferences where user_id = %s and event = %s",
        [user_id, FEED_EVENT],
    )

    return not rows or rows[0]["telegram"] is None or bool(rows[0]["telegram"])


def _set_feed(user_id: int, on: bool) -> None:
    from savdex.web.actions import _save_preference

    _save_preference(user_id, FEED_EVENT, False, on)


def _menu_buttons(chat: dict[str, Any], on: bool) -> list[list[Button]]:
    toggle = (
        Button(_t(chat, "btn_pause"), data="pause")
        if on
        else (Button(_t(chat, "btn_resume"), data="resume"))
    )

    return [
        [Button(_t(chat, "btn_categories"), _app_url(chat, "/cabinet/settings#categories"))],
        [toggle],
    ]


def _categories_text(chat: dict[str, Any], user: dict[str, Any]) -> str:
    names = categories_of(user["company_id"], chat["locale"])

    if not names:
        return _t(chat, "no_categories")

    return "\n".join(f"• {_e(name)}" for name in names)


def _menu(chat: dict[str, Any], user: dict[str, Any]) -> None:
    on = feed_on(user["id"])
    state = _t(chat, "state_on" if on else "state_off")
    _say(
        chat,
        _t(chat, "menu", state=state, categories=_categories_text(chat, user)),
        _menu_buttons(chat, on),
    )


# ── Привязка ─────────────────────────────────────────────────────────


def _link(ctx: Any, chat: dict[str, Any], user: dict[str, Any], username: str) -> None:  # noqa: ANN401
    """Чат — этому человеку: у прежнего владельца чата он снимается."""
    others = _rows(
        "select * from users where telegram_chat_id = %s and id <> %s",
        [chat["chat_id"], user["id"]],
    )

    for other in others:
        eloquent.save(
            ctx,
            "users",
            other,
            {"telegram_chat_id": None, "telegram_username": None, "telegram_linked_at": None},
            section="users",
            model="User",
        )

    eloquent.save(
        ctx,
        "users",
        user,
        {
            "telegram_chat_id": chat["chat_id"],
            # У PHP «0» тоже пусто — как в прежней привязке
            "telegram_username": None if username in ("", "0") else username,
            "telegram_linked_at": eloquent.now(),
        },
        section="users",
        model="User",
    )
    locale = user["locale"] if locales.supports(user["locale"]) else chat["locale"]
    _update(chat, state="done", locale=locale, link_user_id=None, **_CLEARED)
    on = feed_on(user["id"])
    # Без имени: чат могут читать и другие (Н38)
    _say(chat, _t(chat, "linked", categories=_categories_text(chat, user)), _menu_buttons(chat, on))


def _claim(token: str) -> dict[str, Any] | None:
    """Токен кнопки кабинета одноразовый — сразу из кэша прочь."""
    key = LINK_PREFIX + token
    user_id = laravel_cache.get(key)

    if user_id is None:
        return None

    laravel_cache.forget(key)

    return _active_user(user_id)


def _settings_button(chat: dict[str, Any]) -> list[list[Button]]:
    return [[Button(_t(chat, "btn_settings"), _app_url(chat, "/cabinet/settings#telegram"))]]


def _how_to_link(chat: dict[str, Any]) -> None:
    """Не привязан: ссылка — только из кабинета."""
    _update(chat, state=WAITING, link_user_id=None, **_CLEARED)
    _say(chat, _t(chat, "start"), _settings_button(chat))


def _start(ctx: Any, chat: dict[str, Any], token: str, username: str) -> None:  # noqa: ANN401
    """/start: с токеном из кабинета — привязать, без — меню или подсказка."""
    if token == "":
        user = _linked_user(chat["chat_id"])

        if user is not None:
            _update(chat, state="done", **_CLEARED)
            _menu(chat, user)
        else:
            _how_to_link(chat)

        return

    user = _claim(token)

    if user is None:
        _say(
            chat,
            ui.t("messages.auth.telegram_link_expired", chat["locale"]),
            _settings_button(chat),
        )

        return

    _link(ctx, chat, user, username)


def _string(value: object) -> str:
    if value is None or isinstance(value, dict | list):
        return ""

    if isinstance(value, bool):
        return "1" if value else ""

    return str(value)


def handle(ctx: Any, update: dict[str, Any]) -> None:  # noqa: ANN401
    """Одно обновление Telegram: сообщение или нажатие кнопки."""
    callback = update.get("callback_query")

    if isinstance(callback, dict):
        _callback(callback)

        return

    message = update.get("message")

    if not isinstance(message, dict):
        return

    chat_info = message.get("chat")
    raw_sender = message.get("from")
    sender: dict[str, Any] = raw_sender if isinstance(raw_sender, dict) else {}
    chat_id = _string(chat_info.get("id")) if isinstance(chat_info, dict) else ""
    text = _string(message.get("text")).strip()

    if chat_id == "" or text == "" or not messaging.telegram_configured():
        return

    username = _string(sender.get("username"))
    chat = _chat(chat_id, _string(sender.get("language_code"))[:2])

    if text.startswith("/start"):
        _start(ctx, chat, text[len("/start") :].strip(), username)

        return

    user = _linked_user(chat_id)

    if user is None:
        _how_to_link(chat)
    else:
        _menu(chat, user)


def _callback(callback: dict[str, Any]) -> None:
    """Кнопки «Поставить на паузу» и «Включить уведомления»."""
    callback_id = _string(callback.get("id"))
    message = callback.get("message")
    chat_info = message.get("chat") if isinstance(message, dict) else None
    chat_id = _string(chat_info.get("id")) if isinstance(chat_info, dict) else ""
    data = _string(callback.get("data"))
    messaging.telegram_answer(callback_id)

    if chat_id == "" or data not in ("pause", "resume") or not messaging.telegram_configured():
        return

    raw_sender = callback.get("from")
    sender: dict[str, Any] = raw_sender if isinstance(raw_sender, dict) else {}
    chat = _chat(chat_id, _string(sender.get("language_code"))[:2])
    user = _linked_user(chat_id)

    if user is None:
        _how_to_link(chat)

        return

    on = data == "resume"
    _set_feed(int(user["id"]), on)
    _say(chat, _t(chat, "resumed" if on else "paused"), _menu_buttons(chat, on))
