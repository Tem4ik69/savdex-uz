"""
«Стать продавцом» (ТЗ, раздел 4): заявка компании и решения модератора.

Продавец — компания SavdEx, та же карточка. Пока OneID не подключён,
проверка ручная: заявку подаёт владелец компании, у компании должен быть
ИНН и хотя бы один документ о регистрации или лицензия, загруженные в
кабинете («Документы», раздел админки «Документы на проверку»).
Модератор смотрит документы и подтверждает или отклоняет заявку. Своих
копий документов маркетплейс не хранит: персональные данные — в одном
месте.

Состояния: pending → approved | rejected; approved ↔ blocked. Отклонённую
заявку можно подать снова, заблокированную — нет: разблокирует модератор.
Подключим OneID — verified_via станет 'oneid', а заявка без OneID
перестанет приниматься (ТЗ: «новые продавцы только через него»).
"""

from __future__ import annotations

from typing import Any

from savdex.market.common import now, one, rows, write

#: Редакция оферты продавца. Текста ещё нет (ТЗ, открытый вопрос 1 —
#: Тимур): галочка записывается с этой меткой, чтобы потом было видно,
#: какую редакцию принял продавец
OFFER_VERSION = "draft-2026-11"

#: Документы, которые подтверждают компанию (как у раздела «Документы»)
VERIFICATION_TYPES = ("registration", "license", "certificate", "quality")

#: Причина отказа — не отписка
MIN_REASON = 10

STATUSES: dict[str, str] = {
    "pending": "На проверке",
    "approved": "Продавец",
    "rejected": "Отклонена",
    "blocked": "Заблокирован",
}


def of_company(company_id: int) -> dict[str, Any] | None:
    return one("select * from market_sellers where company_id = %s", [company_id])


def approved_of_user(user: dict[str, Any] | None) -> dict[str, Any] | None:
    """Подтверждённый продавец, от имени которого действует человек: его компания."""
    if user is None or user.get("company_id") is None:
        return None

    return one(
        "select s.* from market_sellers s join companies c on c.id = s.company_id "
        "where s.company_id = %s and s.status = 'approved' and c.deleted_at is null "
        "and c.status = 'active'",
        [user["company_id"]],
    )


def checks(user: dict[str, Any], company: dict[str, Any] | None) -> dict[str, bool]:
    """Что нужно для заявки — по пунктам, чтобы кабинет показал, чего не хватает."""
    documents = (
        company is not None
        and one(
            "select 1 as x from company_documents where company_id = %s "
            "and type = any(%s) and moderation_status <> 'rejected' limit 1",
            [company["id"], list(VERIFICATION_TYPES)],
        )
        is not None
    )

    return {
        "company": company is not None and company["status"] == "active",
        "owner": user.get("company_role") == "owner",
        "tin": company is not None and bool(str(company.get("tin") or "").strip()),
        "documents": documents,
    }


def _oneid_enabled() -> bool:
    from savdex.market import oneid  # oneid импортирует sellers

    return oneid.enabled()


def state(user: dict[str, Any], company: dict[str, Any] | None) -> dict[str, Any]:
    """Для кабинета: статус заявки, причина отказа и что ещё нужно сделать."""
    seller = of_company(company["id"]) if company is not None else None
    need = checks(user, company)
    status = seller["status"] if seller is not None else None

    return {
        "status": status,
        "rejectReason": seller["reject_reason"] if status == "rejected" and seller else None,
        "checks": need,
        "canApply": all(need.values()) and status in (None, "rejected"),
        "offerVersion": OFFER_VERSION,
        # Кнопка «Подтвердить через OneID» — только когда он подключён
        "oneid": _oneid_enabled(),
        "verifiedVia": seller["verified_via"] if seller is not None else None,
    }


def apply(
    user: dict[str, Any], company: dict[str, Any] | None, note: str | None
) -> tuple[bool, str]:
    """
    Подать заявку: (удалось ли, ключ текста). Отклонённая подаётся снова
    той же строкой — история решений остаётся в журнале админки.
    """
    need = checks(user, company)

    for key in ("company", "owner", "tin", "documents"):
        if not need[key]:
            return False, f"seller.need_{key}"

    assert company is not None
    seller = of_company(company["id"])
    moment = now()

    if seller is not None and seller["status"] == "blocked":
        return False, "seller.blocked"

    if seller is not None and seller["status"] in ("pending", "approved"):
        return False, f"seller.already_{seller['status']}"

    if seller is None:
        write(
            "insert into market_sellers (company_id, user_id, status, offer_version, "
            "offer_accepted_at, note, created_at, updated_at) "
            "values (%s, %s, 'pending', %s, %s, %s, %s, %s) "
            "on conflict (company_id) do nothing",
            [company["id"], user["id"], OFFER_VERSION, moment, note, moment, moment],
        )
    else:
        write(
            "update market_sellers set status = 'pending', user_id = %s, offer_version = %s, "
            "offer_accepted_at = %s, note = %s, reject_reason = null, reviewed_by = null, "
            "reviewed_at = null, updated_at = %s where id = %s and status = 'rejected'",
            [user["id"], OFFER_VERSION, moment, note, moment, seller["id"]],
        )

    return True, "seller.sent"


# ── Решения модератора ──────────────────────────────────────────────


def approve(seller_id: int, admin_id: int) -> bool:
    """Подтвердить: компания — продавец, кабинет продавца открыт."""
    moment = now()

    return bool(
        write(
            "update market_sellers set status = 'approved', verified_via = coalesce("
            "verified_via, 'documents'), approved_at = coalesce(approved_at, %s), "
            "reject_reason = null, reviewed_by = %s, reviewed_at = %s, blocked_at = null, "
            "updated_at = %s where id = %s and status in ('pending', 'rejected')",
            [moment, admin_id, moment, moment, seller_id],
        )
    )


def reject(seller_id: int, admin_id: int, reason: str) -> bool:
    """Отклонить с причиной: без причины компания пришлёт то же самое."""
    reason = reason.strip()

    if len(reason) < MIN_REASON:
        raise ValueError(f"Причина — не короче {MIN_REASON} знаков")

    moment = now()

    return bool(
        write(
            "update market_sellers set status = 'rejected', reject_reason = %s, "
            "reviewed_by = %s, reviewed_at = %s, updated_at = %s "
            "where id = %s and status = 'pending'",
            [reason[:1000], admin_id, moment, moment, seller_id],
        )
    )


def block(seller_id: int, admin_id: int, reason: str) -> bool:
    """
    Остановить продажи: товары пропадают с витрины сразу (витрина
    показывает только подтверждённых продавцов), сами товары не трогаются.
    """
    reason = reason.strip()

    if len(reason) < MIN_REASON:
        raise ValueError(f"Причина — не короче {MIN_REASON} знаков")

    moment = now()

    return bool(
        write(
            "update market_sellers set status = 'blocked', reject_reason = %s, blocked_at = %s, "
            "reviewed_by = %s, reviewed_at = %s, updated_at = %s "
            "where id = %s and status = 'approved'",
            [reason[:1000], moment, admin_id, moment, moment, seller_id],
        )
    )


def unblock(seller_id: int, admin_id: int) -> bool:
    moment = now()

    return bool(
        write(
            "update market_sellers set status = 'approved', reject_reason = null, "
            "blocked_at = null, reviewed_by = %s, reviewed_at = %s, updated_at = %s "
            "where id = %s and status = 'blocked'",
            [admin_id, moment, moment, seller_id],
        )
    )


def documents_of(company_id: int) -> list[dict[str, Any]]:
    """Документы компании для карточки заявки в админке (без файлов — только статус)."""
    return rows(
        "select id, type, title, moderation_status, created_at from company_documents "
        "where company_id = %s and type = any(%s) order by created_at desc, id desc",
        [company_id, list(VERIFICATION_TYPES)],
    )
