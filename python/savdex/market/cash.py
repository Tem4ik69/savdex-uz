"""
Касса маркетплейса, этап 3 (docs/marketplace.md, «Касса — этап 3»;
docs/marketplace-security.md, разделы 3 и 4): баланс продавца, реквизиты,
выплаты в два шага, сверка наличных и ручная отметка возврата.

Выплата пока ручная (ТЗ: выплаты по оферте — позже): продавец видит
начисления в кабинете, касса переводит деньги платёжкой из банка и
отмечает это здесь.

- **Баланс** — из журнала денег: ``seller_payable`` по заказам продавца
  (начисление — минус, обратная группа отмены — плюс). К выплате — только
  выданные заказы старше N дней (настройка ``market_payout_hold_days``, по
  умолчанию 7, не меньше 1): срок на возврат; заказ «при получении» — ещё и
  только после отметки кассы «сверено с отчётом BTS»
  (``cash_reconciled_at``). Заказы в «ждёт возврата» и «деньги возвращены»
  — не в счёт. Доступно = к выплате − выплаты в работе (создана,
  подтверждена) − выплаченное. Допущение: деньги картой идут «к выплате»
  до того, как пришли на наш счёт (до ночной сверки с выпиской).
- **Два шага**: один кассир создаёт, другой подтверждает (не тот же — и
  база: market_payouts_two_people_check); продавец должен быть
  подтверждён (не заблокирован). Выплату на реквизиты, сменённые меньше
  суток назад, подтверждают только отметкой «реквизиты сверены» с
  заметкой, как сверили. Реквизиты сменились после подтверждения —
  выплату не отметить: отменить и создать заново.
- **Выплачено** — одна группа журнала: ``seller_payable`` плюс (долг
  продавцу закрыт), ``payout_clearing`` минус (деньги ушли с нашего
  счёта); ровно один раз — условным переходом approved → paid; номер
  платёжки уникален. Доступное перепроверяется и здесь.
- **Отмена подтверждённой** — только тот, кто подтверждал (или
  суперадмин), с отметкой «платёжка в банк не отправлялась» и причиной:
  иначе выплату можно было бы провести второй раз.
- Порядок замков везде один: строка продавца (``for update``), затем
  строка выплаты. Каждое действие — ``audit.record`` (кто, что, сумма,
  продавец) в той же транзакции.
"""

from __future__ import annotations

import html
import logging
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from django.db import IntegrityError, connection, transaction

from savdex import audit
from savdex.access import Admin
from savdex.guards import allowed_writes
from savdex.market import orders
from savdex.market.common import now, one, rows, som, t, write
from savdex.web.shared import settings_values

log = logging.getLogger("savdex.market.cash")

#: Раздел админки кассы (savdex/access.py)
SECTION = "market_cash"

# ── Статусы выплаты ─────────────────────────────────────────────────

DRAFT = "draft"
APPROVED = "approved"
PAID = "paid"
CANCELLED = "cancelled"

#: Те же слова, что в кабинете продавца (словарь market.cash.status)
STATUSES: dict[str, str] = {
    DRAFT: "Создана, ждёт подтверждения",
    APPROVED: "Подтверждена, ждёт перевода",
    PAID: "Выплачено",
    CANCELLED: "Отменена",
}

#: Выплаты в работе: их сумма уже не «доступна»
IN_WORK = (DRAFT, APPROVED)

#: Заказы, начисления по которым продавцу не причитаются
_NOT_OWED = (orders.CANCELLED, orders.REFUND_PENDING, orders.REFUNDED)

# ── Настройки ───────────────────────────────────────────────────────

#: Сколько дней после выдачи деньги держатся (срок на возврат)
HOLD_KEY = "market_payout_hold_days"
HOLD_DEFAULT = 7

#: Реквизиты моложе стольких часов — выплата только с отдельной отметкой
FRESH_HOURS = 24

#: Короче — не объяснение (как сверили реквизиты, почему отменили)
MIN_NOTE = 10

_SUBJECT = "Savdex\\Market\\Payout"


class CashRefused(Exception):  # noqa: N818 — отказ кассиру, а не сбой
    """Отказ кассиру с понятным текстом (админка показывает его как есть)."""


def hold_days() -> int:
    """Срок удержания в днях; не число или меньше одного дня — по умолчанию."""
    try:
        number = int(str(settings_values().get(HOLD_KEY)))
    except (TypeError, ValueError):
        return HOLD_DEFAULT

    return number if number >= 1 else HOLD_DEFAULT


def _ago(delta: timedelta, moment: datetime | None = None) -> str:
    return ((moment or datetime.now(UTC)) - delta).strftime("%Y-%m-%d %H:%M:%S")


def money(value: int | None) -> str:
    """Тийины → «1 250 000 сум» для админки."""
    amount = som(value)

    return f"{amount:,}".replace(",", " ") + " сум" if amount is not None else "—"


def _text(value: Any, limit: int = 500) -> str:  # noqa: ANN401
    return " ".join(str(value or "").split())[:limit]


# ── Баланс ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Balance:
    """Баланс продавца в тийинах."""

    #: Начислено по живым заказам (без отменённых и возвращённых)
    accrued: int
    #: Из них к выплате: выданы, срок удержания прошёл, наличные сверены
    released: int
    #: Выплаты в работе (создана, подтверждена)
    in_work: int
    #: Выплачено
    paid: int

    @property
    def on_hold(self) -> int:
        """Начислено, но ещё держится: не выдан, срок не прошёл, наличные не сверены."""
        return self.accrued - self.released

    @property
    def free(self) -> int:
        """К выплате минус выплаты в работе и выплаченное (может уйти в минус)."""
        return self.released - self.in_work - self.paid

    @property
    def available(self) -> int:
        return max(0, self.free)


def balance_parts(seller: str) -> list[tuple[str, str, list[Any]]]:
    """
    Четыре подзапроса баланса — (имя, SQL, параметры) для продавца
    ``seller`` (выражение SQL: «%s» или столбец внешнего запроса): одни и
    те же условия для карточки (balance) и для списка «Балансы продавцов»
    (одним запросом, cash_admin.py).
    """
    owed = (
        "(select coalesce(sum(-l.amount) filter (where {cond}), 0) "
        "from market_ledger l join market_orders o on o.id = l.order_id "
        "where l.account = 'seller_payable' and l.seller_id = {seller})"
    )
    payouts = (
        "(select coalesce(sum(p.amount) filter (where {cond}), 0) "
        "from market_payouts p where p.seller_id = {seller})"
    )
    released = (
        "o.status = %s and o.issued_at < %s "
        "and (o.payment_method <> 'cash' or o.cash_reconciled_at is not null)"
    )

    return [
        ("accrued", owed.format(cond="o.status <> all(%s)", seller=seller), [list(_NOT_OWED)]),
        (
            "released",
            owed.format(cond=released, seller=seller),
            [orders.ISSUED, _ago(timedelta(days=hold_days()))],
        ),
        ("in_work", payouts.format(cond="p.status = any(%s)", seller=seller), [list(IN_WORK)]),
        ("paid", payouts.format(cond="p.status = %s", seller=seller), [PAID]),
    ]


def balance(seller_id: int) -> Balance:
    """Баланс продавца: журнал денег по его заказам и его выплаты."""
    parts = balance_parts("%s")
    found = one(
        "select " + ", ".join(f"{sql} as {name}" for name, sql, _ in parts),
        [value for _, _, params in parts for value in [*params, seller_id]],
    )
    assert found is not None

    return Balance(
        accrued=int(found["accrued"]),
        released=int(found["released"]),
        in_work=int(found["in_work"]),
        paid=int(found["paid"]),
    )


# ── Реквизиты ───────────────────────────────────────────────────────

_REQUISITES = "bank_account, bank_mfo, bank_name, recipient_name, recipient_tin"

#: Поле API → (столбец, проверка)
_FIELDS: dict[str, tuple[str, re.Pattern[str]]] = {
    "bankAccount": ("bank_account", re.compile(r"[0-9]{20}")),
    "bankMfo": ("bank_mfo", re.compile(r"[0-9]{5}")),
    "bankName": ("bank_name", re.compile(r".{2,200}")),
    "recipientName": ("recipient_name", re.compile(r".{2,200}")),
    "recipientTin": ("recipient_tin", re.compile(r"[0-9]{9}|[0-9]{14}")),
}


def _invisible(text: str) -> bool:
    """
    Управляющие и невидимые символы (категории Cc и Cf: RLO, нулевой
    ширины…) — ими подменяют, как название выглядит в админке.
    """
    return any(unicodedata.category(char) in ("Cc", "Cf") for char in text)


def requisites_of(seller_id: int) -> dict[str, Any] | None:
    """Текущие реквизиты продавца (с changed_at) или None."""
    return one(
        f"select id, seller_id, {_REQUISITES}, changed_at, changed_by "
        "from market_seller_requisites where seller_id = %s",
        [seller_id],
    )


def _clean(field: str, value: Any) -> str:  # noqa: ANN401
    raw = str(value or "")

    # Счёт, МФО и ИНН пишут с пробелами и дефисами — оставляем цифры
    if field in ("bankAccount", "bankMfo", "recipientTin"):
        return re.sub(r"[\s-]", "", raw)

    # Невидимые символы не чистим, а отклоняем: так их видно в ответе
    return raw if _invisible(raw.replace("\n", "").replace("\t", "")) else " ".join(raw.split())


def validate_requisites(data: Mapping[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    """Значения по столбцам и ошибки: поле API → ключ словаря market.cash.*."""
    values: dict[str, str] = {}
    errors: dict[str, str] = {}

    for field, (column, pattern) in _FIELDS.items():
        value = _clean(field, data.get(field))

        if _invisible(value) or not pattern.fullmatch(value):
            errors[field] = f"cash.{column}"
        else:
            values[column] = value

    return values, errors


def save_requisites(
    seller_id: int, user_id: int, data: Mapping[str, Any], *, ip: str | None = None
) -> tuple[bool, dict[str, str]]:
    """
    Владелец компании сохраняет реквизиты (кабинет; пароль проверяет
    api.py). Возвращает (изменились ли, ошибки: поле → ключ словаря
    market.cash.*). Каждая смена — строка истории; changed_at — время смены
    (от него — сутки до выплаты без отдельной отметки кассы).
    """
    values, errors = validate_requisites(data)

    if errors:
        return False, errors

    with transaction.atomic():
        # Замок продавца — тот же порядок, что у выплат: смена реквизитов
        # и подтверждение выплаты не проходят одновременно
        one("select id from market_sellers where id = %s for update", [seller_id])
        current = requisites_of(seller_id)

        if current is not None and all(str(current[c]) == v for c, v in values.items()):
            return False, {}

        moment = now()
        columns = list(values)

        if current is None:
            write(
                f"insert into market_seller_requisites (seller_id, {', '.join(columns)}, "
                "changed_at, changed_by, created_at, updated_at) "
                f"values (%s, {', '.join(['%s'] * len(columns))}, %s, %s, %s, %s)",
                [seller_id, *values.values(), moment, user_id, moment, moment],
            )
        else:
            write(
                "update market_seller_requisites set "
                + ", ".join(f"{c} = %s" for c in columns)
                + ", changed_at = %s, changed_by = %s, updated_at = %s where seller_id = %s",
                [*values.values(), moment, user_id, moment, seller_id],
            )

        write(
            f"insert into market_seller_requisites_log (seller_id, {', '.join(columns)}, "
            "changed_by, ip, created_at) "
            f"values (%s, {', '.join(['%s'] * len(columns))}, %s, %s, %s)",
            [seller_id, *values.values(), user_id, (ip or "")[:45] or None, moment],
        )

    log.info("market.cash.requisites_changed seller=%s", seller_id)

    return True, {}


def _notify_owners(seller_id: int, key: str) -> None:
    """
    Владельцам компании продавца — в ленту кабинета и письмом, каждому на
    его языке (users.locale). Текст — словарь market.cash.<key>_title и
    <key>_body; самих реквизитов в нём нет. Сбой уведомления или письма —
    в журнал приложения, запрос не падает.

    TODO(касса): слать и на прежнюю почту владельца — истории смены почты
    у users пока нет.
    """
    from savdex.moderation.services import notify_user
    from savdex.web import mail

    for owner in rows(
        "select u.id, u.email, u.locale from users u "
        "join market_sellers s on s.company_id = u.company_id "
        "where s.id = %s and u.company_role = 'owner' and u.deleted_at is null",
        [seller_id],
    ):
        locale = str(owner["locale"] or "ru")
        title = t(f"cash.{key}_title", locale)
        body = t(f"cash.{key}_body", locale)

        try:
            notify_user(int(owner["id"]), "billing", title, "warning", "/cabinet", body)
        except Exception:
            log.exception("market.cash.notify_failed seller=%s key=%s", seller_id, key)

        try:
            if owner["email"] and not mail.send(
                str(owner["email"]), title, f"<p>{html.escape(body)}</p>", body
            ):
                log.error("market.cash.mail_failed seller=%s key=%s", seller_id, key)
        except Exception:
            log.exception("market.cash.mail_failed seller=%s key=%s", seller_id, key)


def notify_requisites_changed(seller_id: int) -> None:
    """Реквизиты сменились: «изменены, если это не вы — напишите в поддержку»."""
    _notify_owners(seller_id, "changed")


#: Неверных паролей подряд при смене реквизитов — и смена закрыта на сутки
PASSWORD_FAILS = 5
PASSWORD_LOCK_HOURS = 24


def requisites_locked(seller_id: int) -> bool:
    """Смена реквизитов закрыта после неверных паролей (ещё не прошли сутки)."""
    found = one(
        "select requisites_locked_until > %s as locked from market_sellers where id = %s",
        [now(), seller_id],
    )

    return bool(found and found["locked"])


def password_failed(seller_id: int) -> bool:
    """
    Неверный пароль при смене реквизитов: счётчик подряд; на PASSWORD_FAILS-й
    — смена закрыта на сутки и письмо владельцам. True — только что закрыли.
    """
    found = write(
        "update market_sellers set requisites_failed = requisites_failed + 1 "
        "where id = %s returning requisites_failed",
        [seller_id],
    )

    if found is None or int(found) < PASSWORD_FAILS:
        return False

    write(
        "update market_sellers set requisites_failed = 0, requisites_locked_until = %s "
        "where id = %s",
        [_ago(timedelta(hours=-PASSWORD_LOCK_HOURS)), seller_id],
    )
    log.warning("market.cash.requisites_locked seller=%s", seller_id)
    _notify_owners(seller_id, "locked")

    return True


def password_ok(seller_id: int) -> None:
    """Верный пароль — счётчик неверных с нуля."""
    write(
        "update market_sellers set requisites_failed = 0 where id = %s and requisites_failed <> 0",
        [seller_id],
    )


def _last_log_id(seller_id: int) -> int | None:
    found = one(
        "select id from market_seller_requisites_log where seller_id = %s order by id desc limit 1",
        [seller_id],
    )

    return int(found["id"]) if found else None


# ── Выплаты ─────────────────────────────────────────────────────────


def _need(admin: Admin, ability: str) -> None:
    if not admin.can(ability):
        raise CashRefused("Нет права на это действие в кассе.")


def _seller(seller_id: int) -> dict[str, Any]:
    """Строка продавца под замком; не подтверждён (заблокирован) — отказ."""
    seller = one("select id, status from market_sellers where id = %s for update", [seller_id])

    if seller is None:
        raise CashRefused("Продавец не найден.")

    if seller["status"] != "approved":
        raise CashRefused("Продавец не подтверждён или заблокирован — выплаты остановлены.")

    return seller


def _lock(payout_id: int, *, seller_must_be_active: bool = True) -> dict[str, Any]:
    """Строка продавца, затем строка выплаты — под замком (порядок везде один)."""
    found = one("select seller_id from market_payouts where id = %s", [payout_id])

    if found is None:
        raise CashRefused("Выплата не найдена.")

    if seller_must_be_active:
        _seller(int(found["seller_id"]))
    else:
        one("select id from market_sellers where id = %s for update", [found["seller_id"]])

    payout = one("select * from market_payouts where id = %s for update", [payout_id])
    assert payout is not None

    return payout


def _record(
    admin: Admin,
    action: str,
    payout: Mapping[str, Any],
    *,
    after: Mapping[str, Any],
    before: Mapping[str, Any] | None = None,
    note: str | None = None,
    ip: str | None = None,
) -> None:
    audit.record(
        connection,
        action=action,
        section=SECTION,
        actor=admin,
        subject_type=_SUBJECT,
        subject_id=int(payout["id"]),
        subject_label=f"Выплата №{payout['id']}",
        changes={
            "before": dict(before or {}),
            "after": {"seller_id": payout["seller_id"], "amount": payout["amount"], **after},
        },
        note=note,
        ip=ip,
    )


def create_payout(
    admin: Admin, seller_id: int, amount: int, *, note: str | None = None, ip: str | None = None
) -> int:
    """Шаг 1: кассир создаёт выплату — не больше доступного. Возвращает номер."""
    _need(admin, f"{SECTION}.create")

    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        raise CashRefused("Сумма выплаты — больше нуля.")

    with transaction.atomic():
        _seller(seller_id)

        if requisites_of(seller_id) is None:
            raise CashRefused("У продавца нет реквизитов — выплатить некуда.")

        free = balance(seller_id).available

        if amount > free:
            raise CashRefused(f"Больше доступного: доступно {money(free)}.")

        moment = now()
        text = _text(note) or None
        payout_id = int(
            write(
                "insert into market_payouts (seller_id, amount, status, note, created_by, "
                "created_at, updated_at) values (%s, %s, %s, %s, %s, %s, %s) returning id",
                [seller_id, amount, DRAFT, text, admin.id, moment, moment],
            )
        )
        _record(
            admin,
            "payout_created",
            {"id": payout_id, "seller_id": seller_id, "amount": amount},
            after={"status": DRAFT},
            note=text,
            ip=ip,
        )

    log.info("market.cash.payout_created id=%s seller=%s", payout_id, seller_id)

    return payout_id


def approve_payout(
    admin: Admin,
    payout_id: int,
    *,
    fresh_ok: bool = False,
    fresh_note: str | None = None,
    ip: str | None = None,
) -> None:
    """
    Шаг 2: другой кассир подтверждает. Реквизиты сменены меньше суток назад
    — только с fresh_ok (отметка «реквизиты сверены») и заметкой, как
    сверили (fresh_note, в журнал действий). Сумма — ещё раз против
    доступного: с создания могла смениться настройка срока.
    """
    _need(admin, f"{SECTION}.moderate")

    with transaction.atomic():
        payout = _lock(payout_id)

        if payout["status"] != DRAFT:
            raise CashRefused("Выплата уже не ждёт подтверждения.")

        if int(payout["created_by"]) == admin.id:
            raise CashRefused("Подтверждает другой кассир — не тот, кто создал выплату.")

        seller_id = int(payout["seller_id"])

        # Кто сверял наличные продавца, тот не подтверждает выплату из них.
        # Выплата с заказами не связана — берём заказы, сверенные после
        # последней выплаченной: их деньги могут быть в этой
        if one(
            "select 1 as x from market_orders o join market_order_parts p on p.order_id = o.id "
            "where p.seller_id = %s and o.cash_reconciled_by = %s and o.cash_reconciled_at > "
            "coalesce((select max(paid_at) from market_payouts where seller_id = %s "
            "and status = %s), '-infinity'::timestamp) limit 1",
            [seller_id, admin.id, seller_id, PAID],
        ):
            raise CashRefused(
                "Вы сверяли наличные этого продавца — выплату из них подтверждает другой кассир."
            )

        fresh = one(
            "select changed_at >= %s as fresh from market_seller_requisites where seller_id = %s",
            [_ago(timedelta(hours=FRESH_HOURS)), seller_id],
        )
        log_id = _last_log_id(seller_id)

        if fresh is None or log_id is None:
            raise CashRefused("У продавца нет реквизитов — выплатить некуда.")

        is_fresh = bool(fresh["fresh"])
        check_note = _text(fresh_note)

        if is_fresh and (not fresh_ok or len(check_note) < MIN_NOTE):
            raise CashRefused(
                f"Реквизиты продавца сменены меньше {FRESH_HOURS} часов назад. Сверьте их с "
                "продавцом по известному телефону, отметьте «реквизиты сверены» и напишите, "
                f"как сверили (не короче {MIN_NOTE} знаков)."
            )

        # Эта выплата уже в «в работе» — свободное не должно уйти в минус
        if balance(seller_id).free < 0:
            raise CashRefused("Сумма больше доступного — отмените выплату и создайте новую.")

        changed = write(
            "update market_payouts set status = %s, approved_by = %s, approved_at = %s, "
            "requisites_log_id = %s, fresh_requisites = %s, fresh_check_note = %s, "
            "updated_at = %s where id = %s and status = %s",
            [
                APPROVED,
                admin.id,
                now(),
                log_id,
                is_fresh,
                check_note if is_fresh else None,
                now(),
                payout_id,
                DRAFT,
            ],
        )

        if not changed:
            raise CashRefused("Выплата уже не ждёт подтверждения.")

        _record(
            admin,
            "payout_approved",
            payout,
            before={"status": DRAFT},
            after={"status": APPROVED, "fresh_requisites": is_fresh},
            note=f"реквизиты сменены меньше суток назад, сверены: {check_note}"
            if is_fresh
            else None,
            ip=ip,
        )

    log.info("market.cash.payout_approved id=%s", payout_id)


_BANK_REF = re.compile(r"[0-9A-Za-zА-Яа-яЁё/._ -]{1,64}")


def mark_paid(admin: Admin, payout_id: int, bank_reference: str, *, ip: str | None = None) -> str:
    """
    Деньги ушли платёжкой: approved → paid и группа журнала денег —
    ровно один раз. Номер платёжки — один на выплату. Возвращает номер
    группы журнала.
    """
    _need(admin, f"{SECTION}.moderate")
    reference = _text(bank_reference, 200)

    if not _BANK_REF.fullmatch(reference):
        raise CashRefused("Укажите номер платёжного поручения (до 64 знаков).")

    with transaction.atomic():
        # Выплата, подтверждённая до блокировки продавца, ещё может уйти:
        # платёжка могла быть уже в банке
        payout = _lock(payout_id, seller_must_be_active=False)

        if payout["status"] != APPROVED:
            raise CashRefused("Выплата не подтверждена или уже отмечена.")

        seller_id = int(payout["seller_id"])

        if _last_log_id(seller_id) != payout["requisites_log_id"]:
            raise CashRefused(
                "Реквизиты продавца сменились после подтверждения — отмените выплату и "
                "создайте заново."
            )

        # Пока выплата ждала перевода, заказ могли вернуть — доступное не в минус
        if balance(seller_id).free < 0:
            raise CashRefused("Сумма больше доступного — отмените выплату и создайте новую.")

        if one("select id from market_payouts where bank_reference = %s", [reference]):
            raise CashRefused("Платёжка с таким номером уже отмечена в другой выплате.")

        amount = int(payout["amount"])
        memo = f"выплата №{payout_id}: {reference}"[:200]
        group = orders.post(
            None,
            [
                orders.Entry("seller_payable", amount, seller_id=seller_id, memo=memo),
                orders.Entry("payout_clearing", -amount, seller_id=seller_id, memo=memo),
            ],
        )

        try:
            with transaction.atomic():
                changed = write(
                    "update market_payouts set status = %s, paid_by = %s, paid_at = %s, "
                    "bank_reference = %s, ledger_group = %s::uuid, updated_at = %s "
                    "where id = %s and status = %s",
                    [PAID, admin.id, now(), reference, group, now(), payout_id, APPROVED],
                )
        except IntegrityError as error:
            # Тот же номер платёжки успела отметить другая выплата — откат всего
            raise CashRefused("Платёжка с таким номером уже отмечена в другой выплате.") from error

        if not changed:
            # Под замком статус не мог смениться — ошибка в коде; откат проводки
            raise RuntimeError(f"market_payouts {payout_id}: не перешла в paid")

        _record(
            admin,
            "payout_paid",
            payout,
            before={"status": APPROVED},
            after={"status": PAID, "bank_reference": reference},
            ip=ip,
        )

    log.info("market.cash.payout_paid id=%s seller=%s", payout_id, seller_id)

    return group


def cancel_payout(
    admin: Admin,
    payout_id: int,
    reason: str,
    *,
    not_sent: bool = False,
    ip: str | None = None,
) -> None:
    """
    Отменить выплату до перевода. Созданную — любой кассир с правом
    market_cash.edit. Подтверждённую — только тот, кто подтверждал (или
    суперадмин), с отметкой «платёжка в банк не отправлялась» (not_sent):
    отменённую выплату можно создать заново, и если платёжка уже ушла —
    продавец получил бы деньги дважды.
    """
    _need(admin, f"{SECTION}.edit")
    text = _text(reason)

    if len(text) < 5:
        raise CashRefused("Напишите причину отмены — не короче 5 знаков.")

    with transaction.atomic():
        payout = _lock(payout_id, seller_must_be_active=False)

        if payout["status"] not in IN_WORK:
            raise CashRefused("Выплату уже нельзя отменить.")

        if payout["status"] == APPROVED:
            if int(payout["approved_by"]) != admin.id and not admin.is_superadmin:
                raise CashRefused("Подтверждённую выплату отменяет только тот, кто её подтвердил.")

            if not not_sent:
                raise CashRefused(
                    "Отметьте, что платёжка в банк не отправлялась: иначе продавец получит "
                    "деньги дважды. Ушла — отметьте выплату выплаченной."
                )

        write(
            "update market_payouts set status = %s, cancelled_by = %s, cancelled_at = %s, "
            "cancel_reason = %s, cancel_not_sent = %s, updated_at = %s "
            "where id = %s and status = %s",
            [
                CANCELLED,
                admin.id,
                now(),
                text,
                payout["status"] == APPROVED,
                now(),
                payout_id,
                payout["status"],
            ],
        )
        _record(
            admin,
            "payout_cancelled",
            payout,
            before={"status": payout["status"]},
            after={"status": CANCELLED, "not_sent": payout["status"] == APPROVED},
            note=text,
            ip=ip,
        )


# ── Сверка наличных с отчётом BTS ───────────────────────────────────

#: Больше заказов за одну сверку пачкой не берём: ошибка в пачке дороже
RECONCILE_BATCH = 100

#: Номер или дата отчёта BTS — не короче (как сверили, видно в журнале)
REPORT_MIN = 10


def cash_pending(order_ids: Iterable[int]) -> tuple[int, int]:
    """Сколько из этих заказов ждут сверки наличных и на какую сумму (тийины)."""
    found = one(
        "select count(*) as n, coalesce(sum(total), 0) as total from market_orders "
        "where id = any(%s) and payment_method = 'cash' and status = %s "
        "and cash_reconciled_at is null",
        [sorted({int(pk) for pk in order_ids}), orders.ISSUED],
    )

    return (int(found["n"]), int(found["total"])) if found else (0, 0)


def reconcile_cash(
    admin: Admin, order_ids: Iterable[int], report: str, *, ip: str | None = None
) -> int:
    """
    Касса сверила наличные выданных заказов «при получении» с отчётом BTS
    (report — номер или дата отчёта, один на всю пачку, не короче
    REPORT_MIN знаков): ставит ``cash_reconciled_at`` — с этого момента
    деньги заказа идут продавцу «к выплате». Не больше RECONCILE_BATCH
    заказов за раз. Каждый заказ — условно (ещё не сверен) и строкой
    журнала действий. Возвращает, сколько отмечено.
    """
    _need(admin, f"{SECTION}.moderate")
    text = _text(report, 100)
    ids = sorted({int(pk) for pk in order_ids})

    if len(text) < REPORT_MIN:
        raise CashRefused(f"Укажите номер или дату отчёта BTS — не короче {REPORT_MIN} знаков.")

    if len(ids) > RECONCILE_BATCH:
        raise CashRefused(f"Не больше {RECONCILE_BATCH} заказов за одну сверку.")

    done = 0

    with transaction.atomic():
        for order_id in ids:
            # Номер и сумма — тем же условным обновлением (returning)
            with allowed_writes("market_orders"):
                found = one(
                    "update market_orders set cash_reconciled_at = %s, cash_reconciled_by = %s, "
                    "cash_reconciled_ref = %s where id = %s and payment_method = 'cash' "
                    "and status = %s and cash_reconciled_at is null returning number, total",
                    [now(), admin.id, text, order_id, orders.ISSUED],
                )

            if found is None:
                continue

            done += 1
            audit.record(
                connection,
                action="cash_reconciled",
                section=SECTION,
                actor=admin,
                subject_type="Savdex\\Market\\Order",
                subject_id=order_id,
                subject_label=str(found["number"]),
                changes={"after": {"amount": found["total"], "report": text}},
                note=text,
                ip=ip,
            )

    return done


def unreconcile_cash(admin: Admin, order_id: int, reason: str, *, ip: str | None = None) -> None:
    """
    Снять сверку наличных (ошиблись заказом или отчётом) — пока деньги
    заказа не ушли в выплату: снятие не должно увести доступное продавцу в
    минус (выплаты в работе и выплаченное уже на них рассчитаны). С
    причиной, строкой журнала.
    """
    _need(admin, f"{SECTION}.moderate")
    text = _text(reason)

    if len(text) < 5:
        raise CashRefused("Напишите причину — не короче 5 знаков.")

    with transaction.atomic():
        order = one(
            "select o.id, o.number, o.total, p.seller_id from market_orders o "
            "join market_order_parts p on p.order_id = o.id "
            "where o.id = %s and o.cash_reconciled_at is not null order by p.id",
            [order_id],
        )

        if order is None:
            raise CashRefused("Заказ не сверен.")

        sellers = [
            int(r["seller_id"])
            for r in rows(
                "select seller_id from market_order_parts where order_id = %s order by seller_id",
                [order_id],
            )
        ]

        # Порядок замков — как у выплат: продавцы, затем заказ
        for seller_id in sellers:
            one("select id from market_sellers where id = %s for update", [seller_id])

        write(
            "update market_orders set cash_reconciled_at = null, cash_reconciled_by = null, "
            "cash_reconciled_ref = null where id = %s",
            [order_id],
        )

        if any(balance(seller_id).free < 0 for seller_id in sellers):
            raise CashRefused(
                "Деньги заказа уже в выплате — сначала отмените выплату, потом снимайте сверку."
            )

        audit.record(
            connection,
            action="cash_unreconciled",
            section=SECTION,
            actor=admin,
            subject_type="Savdex\\Market\\Order",
            subject_id=order_id,
            subject_label=str(order["number"]),
            changes={"before": {"amount": order["total"]}},
            note=text,
            ip=ip,
        )


# ── Ручной возврат ──────────────────────────────────────────────────

_REFUND_REF = re.compile(r"[0-9A-Za-z/._:-]{3,64}")

#: Режимы возврата (market_payments.refund_mode), в которых касса отмечает
#: возврат вручную; api — запрос к провайдеру в полёте, его не трогаем
MANUAL_MODES = ("claimed", "manual", "error")


def _refund_payment(order_id: int) -> dict[str, Any] | None:
    """Проведённая оплата заказа — под замком (после замка заказа)."""
    from savdex.market.payments import base

    found = one(
        "select id, provider, status, refund_requested_at, refund_mode, refund_claimed_by, "
        "refund_reference, note from market_payments where order_id = %s and status = %s "
        "order by id desc limit 1",
        [order_id, base.PAID],
    )

    if found is None:
        return None

    return one(
        "select id, order_id, provider, status, refund_requested_at, refund_mode, "
        "refund_claimed_by, refund_reference, note from market_payments where id = %s for update",
        [found["id"]],
    )


def _order_number(order_id: int, *, lock: bool) -> dict[str, Any]:
    order = one(
        "select id, number, total, status from market_orders where id = %s"
        + (" for update" if lock else ""),
        [order_id],
    )

    if order is None or order["status"] != orders.REFUND_PENDING:
        raise CashRefused("Заказ не ждёт возврата.")

    return order


def _append_note(note: Any, text: str) -> str:  # noqa: ANN401
    """Пометка оплаты дописывается, а не затирается: видно всю историю."""
    return "; ".join(part for part in (str(note or "").strip(), text) if part)[-500:]


def claim_refund(admin: Admin, order_id: int, *, ip: str | None = None) -> bool:
    """
    «Беру возврат на себя»: касса возвращает вручную, пока расписание
    возврат не запросило (refund_requested_at — условным обновлением,
    refund_mode = claimed, refund_claimed_by). После этого API провайдера
    возврат уже не запросит — двух возвратов не будет. False — уже
    запрошен (расписанием или другим кассиром).
    """
    _need(admin, f"{SECTION}.moderate")

    with transaction.atomic():
        order = _order_number(order_id, lock=True)
        payment = _refund_payment(order_id)

        if payment is None or payment["refund_requested_at"] is not None:
            return False

        write(
            "update market_payments set refund_requested_at = %s, refund_mode = 'claimed', "
            "refund_claimed_by = %s, note = %s, updated_at = %s where id = %s",
            [
                now(),
                admin.id,
                _append_note(payment["note"], f"возврат вручную взял {admin.name}"),
                now(),
                payment["id"],
            ],
        )
        audit.record(
            connection,
            action="refund_claimed",
            section=SECTION,
            actor=admin,
            subject_type="Savdex\\Market\\Order",
            subject_id=order_id,
            subject_label=str(order["number"]),
            ip=ip,
        )

    return True


def _may_settle(admin: Admin, payment: Mapping[str, Any]) -> None:
    """Взятый возврат отмечает или отпускает только взявший — или суперадмин."""
    if (
        payment["refund_mode"] == "claimed"
        and payment["refund_claimed_by"] != admin.id
        and not admin.is_superadmin
    ):
        raise CashRefused("Возврат взял другой кассир — отмечает он (или суперадмин).")


def unclaim_refund(admin: Admin, order_id: int, reason: str, *, ip: str | None = None) -> None:
    """
    Снять взятие (передумали возвращать вручную): возврат снова ждёт
    расписания — то запросит его через API провайдера. С причиной.
    """
    _need(admin, f"{SECTION}.moderate")
    text = _text(reason)

    if len(text) < 5:
        raise CashRefused("Напишите причину — не короче 5 знаков.")

    with transaction.atomic():
        order = _order_number(order_id, lock=True)
        payment = _refund_payment(order_id)

        if payment is None or payment["refund_mode"] != "claimed":
            raise CashRefused("Возврат не взят вручную.")

        _may_settle(admin, payment)
        write(
            "update market_payments set refund_requested_at = null, refund_mode = null, "
            "refund_claimed_by = null, note = %s, updated_at = %s where id = %s",
            [
                _append_note(payment["note"], f"взятие снял {admin.name}: {text}"),
                now(),
                payment["id"],
            ],
        )
        audit.record(
            connection,
            action="refund_unclaimed",
            section=SECTION,
            actor=admin,
            subject_type="Savdex\\Market\\Order",
            subject_id=order_id,
            subject_label=str(order["number"]),
            note=text,
            ip=ip,
        )


def mark_refunded(
    admin: Admin, order_id: int, refund_reference: str, note: str, *, ip: str | None = None
) -> bool:
    """
    Касса вернула деньги в кабинете провайдера и отмечает это: только в
    режимах claimed (взявший или суперадмин), manual и error — не пока
    расписание запрашивает возврат через API (api). Номер возврата у
    провайдера обязателен и один на возврат (уникальный индекс).
    payments.base.refund_payment (оплата paid → refunded, заказ
    refund_pending → refunded, проводка — один раз) и строка журнала
    действий — одной транзакцией. False — заказ уже не ждёт возврата.
    """
    from savdex.market.payments import base

    _need(admin, f"{SECTION}.moderate")
    reference = _text(refund_reference, 100)
    text = _text(note, 400)

    if not _REFUND_REF.fullmatch(reference):
        raise CashRefused("Укажите номер возврата у провайдера (латиница, цифры, до 64 знаков).")

    if len(text) < 5:
        raise CashRefused("Напишите, где и когда вернули деньги — не короче 5 знаков.")

    with transaction.atomic():
        order = _order_number(order_id, lock=True)
        payment = _refund_payment(order_id)

        if payment is None:
            raise CashRefused("У заказа нет проведённой оплаты картой.")

        if payment["refund_mode"] not in MANUAL_MODES:
            raise CashRefused(
                "Возврат вручную не начат: сначала «Беру возврат на себя». Если идёт запрос "
                "через API провайдера — дождитесь его итога."
            )

        _may_settle(admin, payment)

        if one(
            "select id from market_payments where refund_reference = %s and id <> %s",
            [reference, payment["id"]],
        ):
            raise CashRefused("Возврат с таким номером уже отмечен по другой оплате.")

        try:
            with transaction.atomic():
                write(
                    "update market_payments set refund_reference = %s, updated_at = %s "
                    "where id = %s",
                    [reference, now(), payment["id"]],
                )
        except IntegrityError as error:
            raise CashRefused("Возврат с таким номером уже отмечен по другой оплате.") from error

        full = base.payment(int(payment["id"]))
        assert full is not None

        if not base.refund_payment(full, note=f"возврат отмечен кассой: {reference}; {text}"[:500]):
            # Откат и номера возврата: заказ уже не ждёт возврата
            transaction.set_rollback(True)

            return False

        audit.record(
            connection,
            action="refund_marked",
            section=SECTION,
            actor=admin,
            subject_type="Savdex\\Market\\Order",
            subject_id=order_id,
            subject_label=str(order["number"]),
            changes={
                "before": {"status": orders.REFUND_PENDING, "refund_mode": payment["refund_mode"]},
                "after": {
                    "status": orders.REFUNDED,
                    "amount": order["total"],
                    "provider": payment["provider"],
                    "refund_reference": reference,
                },
            },
            note=text,
            ip=ip,
        )

    return True


def acknowledge_refund(admin: Admin, order_id: int, note: str) -> bool:
    """
    «Проверено у провайдера»: зависший возврат разобран —
    payments.base.acknowledge (право, заметка, строка журнала
    payment_checked и пометка в истории заказа — там). False — уже
    отмечено или оплаты нет.
    """
    from savdex.market.payments import base

    _need(admin, f"{SECTION}.moderate")
    found = one(
        "select id from market_payments where order_id = %s and status = %s "
        "order by id desc limit 1",
        [order_id, base.PAID],
    )

    if found is None:
        return False

    try:
        return base.acknowledge(int(found["id"]), admin.id, note)
    except ValueError as error:
        raise CashRefused(
            f"Напишите, что проверили у провайдера — не короче {base.ACK_NOTE_MIN} знаков."
        ) from error
    except PermissionError as error:
        raise CashRefused("Нет права на это действие в кассе.") from error


# ── Кабинет продавца ────────────────────────────────────────────────


def _when(value: Any) -> str | None:  # noqa: ANN401
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")

    return str(value) if value is not None else None


def seller_balance(seller_id: int, locale: str) -> dict[str, Any]:
    """Баланс для кабинета: сумами; последние выплаты — только свои."""
    found = balance(seller_id)
    payouts = rows(
        "select id, amount, status, bank_reference, created_at, paid_at from market_payouts "
        "where seller_id = %s order by id desc limit 20",
        [seller_id],
    )

    return {
        "accrued": som(found.accrued),
        "onHold": som(found.on_hold),
        "available": som(found.available),
        "inWork": som(found.in_work),
        "paid": som(found.paid),
        "holdDays": hold_days(),
        "payouts": [
            {
                "id": p["id"],
                "amount": som(p["amount"]),
                "status": {"code": p["status"], "text": t(f"cash.status.{p['status']}", locale)},
                "bankReference": p["bank_reference"] if p["status"] == PAID else None,
                "createdAt": _when(p["created_at"]),
                "paidAt": _when(p["paid_at"]),
            }
            for p in payouts
        ],
    }


def requisites_view(seller_id: int) -> dict[str, Any] | None:
    """Реквизиты для кабинета владельца."""
    found = requisites_of(seller_id)

    if found is None:
        return None

    return {
        **{field: found[column] for field, (column, _) in _FIELDS.items()},
        "changedAt": _when(found["changed_at"]),
    }


def masked(account: str | None) -> str:
    """Счёт в списках админки: только последние 4 цифры."""
    return f"•••• {str(account)[-4:]}" if account else "—"
