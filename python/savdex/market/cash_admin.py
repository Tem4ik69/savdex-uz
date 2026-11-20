"""
Касса маркетплейса в админке (раздел market_cash, роль «Касса
маркетплейса»; savdex/market/cash.py).

- **Балансы продавцов** — только смотреть: начислено, держится, доступно,
  в работе, выплачено; реквизиты и последние выплаты. Отсюда кассир
  создаёт выплату (шаг 1).
- **Выплаты продавцам** — подтвердить (шаг 2, другой кассир; на свежие
  реквизиты — с отметкой «реквизиты сверены» и заметкой, как сверили),
  отметить выплаченной (номер платёжки — проводка в журнале денег),
  отменить (подтверждённую — только подтвердивший, с отметкой «платёжка
  не отправлялась»).
- **Наличные к сверке** — выданные заказы «при получении»: касса сверяет
  их с отчётом BTS (по одному или пачкой), и только тогда деньги идут
  продавцу «к выплате».
- **Реквизиты продавцов** — только смотреть, с историей смен; в списке
  счёт скрыт: меняет реквизиты только владелец компании из кабинета.
- **Возвраты покупателям** — заказы в «ждёт возврата»: касса берёт
  возврат на себя, возвращает деньги в кабинете провайдера и отмечает
  возврат с его номером.

Каждое действие — POST с CSRF на свой адрес, право проверяется и здесь,
и в cash.py; итог — строка журнала действий (cash.py).
"""

from __future__ import annotations

from typing import Any

from django.contrib import admin, messages
from django.contrib.admin import helpers
from django.core.exceptions import PermissionDenied
from django.db.models import F, QuerySet
from django.db.models.expressions import RawSQL
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html, format_html_join

from savdex import audit
from savdex.adminsite import SavdexModelAdmin, _admin_of, register
from savdex.crm.admin import _badge, when
from savdex.market import cash, orders
from savdex.market.admin import _company_name
from savdex.market.common import one, rows, tiyin
from savdex.market.models import (
    CashOrder,
    Payout,
    RefundOrder,
    RequisitesLog,
    SellerBalance,
    SellerRequisites,
)

_TEMPLATE = "admin/market/cash_change_form.html"

_PAYOUT_TONES = {
    cash.DRAFT: "warning",
    cash.APPROVED: "info",
    cash.PAID: "success",
    cash.CANCELLED: "gray",
}


def _staff_name(user_id: int | None) -> str:
    if user_id is None:
        return "—"

    found = one("select name from users where id = %s", [user_id])

    return f"{found['name'] if found else '—'} (№{user_id})"


class _ReadOnly(SavdexModelAdmin):
    """Раздел кассы: записи только смотреть, действия — своими POST-адресами."""

    change_form_template = _TEMPLATE

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:  # noqa: ANN401
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:  # noqa: ANN401
        return False

    def cash_forms(self, request: HttpRequest, obj: Any) -> list[dict[str, Any]]:  # noqa: ANN401
        return []

    def render_change_form(
        self,
        request: HttpRequest,
        context: dict[str, Any],
        add: bool = False,
        change: bool = False,
        form_url: str = "",
        obj: Any = None,  # noqa: ANN401
    ) -> HttpResponse:
        """Формы действий — по записи, которую карточка уже прочитала."""
        if obj is not None:
            context["cash_forms"] = self.cash_forms(request, obj)

        return super().render_change_form(request, context, add, change, form_url, obj)

    def _post(self, request: HttpRequest, object_id: str, ability: str) -> Any:  # noqa: ANN401
        """Общая проверка действия: только POST, право, запись есть."""
        if request.method != "POST" or not _admin_of(request).can(ability):
            raise PermissionDenied

        obj = self.get_object(request, object_id)

        if obj is None:
            raise PermissionDenied

        return obj

    def _back(
        self,
        request: HttpRequest,
        obj: Any,  # noqa: ANN401
        done: str | None,
        error: str | None,
    ) -> HttpResponse:
        if error:
            self.message_user(request, error, messages.ERROR)
        elif done:
            self.message_user(request, done, messages.SUCCESS)

        opts = self.model._meta

        return HttpResponseRedirect(
            reverse(f"savdex_admin:{opts.app_label}_{opts.model_name}_change", args=[obj.pk])
        )


# ── Балансы продавцов ──────────────────────────────────────────────


@register(SellerBalance, section="market_cash")
class SellerBalanceAdmin(_ReadOnly):
    laravel_model = "Savdex\\Market\\Seller"
    title_list = "Балансы продавцов"
    title_change = "Баланс продавца"

    list_display = ("id", "company", "accrued", "on_hold", "available", "paid_total")
    list_per_page = 50
    fields = ("company", "money", "requisites", "payouts")
    readonly_fields = fields

    def get_queryset(self, request: HttpRequest) -> QuerySet[SellerBalance]:
        """Баланс каждой строки — подзапросами в том же запросе, а не запросом на строку."""
        found: QuerySet[SellerBalance] = super().get_queryset(request)
        parts = cash.balance_parts('"market_sellers"."id"')

        return found.filter(status__in=("approved", "blocked")).annotate(
            company_title=_company_name(),
            **{f"cash_{name}": RawSQL(sql, params) for name, sql, params in parts},
        )

    def get_urls(self) -> list[Any]:
        return [
            path(
                "<path:object_id>/payout/",
                self.admin_site.admin_view(self.payout_view),
                name="market_sellerbalance_payout",
            ),
            *super().get_urls(),
        ]

    @staticmethod
    def _balance(obj: SellerBalance) -> cash.Balance:
        return cash.Balance(
            accrued=int(getattr(obj, "cash_accrued", 0) or 0),
            released=int(getattr(obj, "cash_released", 0) or 0),
            in_work=int(getattr(obj, "cash_in_work", 0) or 0),
            paid=int(getattr(obj, "cash_paid", 0) or 0),
        )

    @admin.display(description="компания", ordering="company_title")
    def company(self, obj: SellerBalance) -> str:
        return format_html(
            "{} <small>№{}{}</small>",
            getattr(obj, "company_title", "—"),
            obj.pk,
            "" if obj.status == "approved" else " · заблокирован",
        )

    @admin.display(description="начислено")
    def accrued(self, obj: SellerBalance) -> str:
        return cash.money(self._balance(obj).accrued)

    @admin.display(description="держится")
    def on_hold(self, obj: SellerBalance) -> str:
        return cash.money(self._balance(obj).on_hold)

    @admin.display(description="доступно")
    def available(self, obj: SellerBalance) -> str:
        return cash.money(self._balance(obj).available)

    @admin.display(description="выплачено")
    def paid_total(self, obj: SellerBalance) -> str:
        return cash.money(self._balance(obj).paid)

    @admin.display(description="деньги")
    def money(self, obj: SellerBalance) -> str:
        found = self._balance(obj)

        return format_html(
            "начислено {} · держится {} (выдача + {} дн., наличные — после сверки с BTS)<br>"
            "к выплате {} · в работе {} · выплачено {}<br><b>доступно {}</b>",
            cash.money(found.accrued),
            cash.money(found.on_hold),
            cash.hold_days(),
            cash.money(found.released),
            cash.money(found.in_work),
            cash.money(found.paid),
            cash.money(found.available),
        )

    @admin.display(description="реквизиты")
    def requisites(self, obj: SellerBalance) -> str:
        found = cash.requisites_of(obj.pk)

        if found is None:
            return "нет — продавец заполняет их в кабинете"

        return format_html(
            "{} · счёт {} · МФО {}<br><small>получатель {}, ИНН/ПИНФЛ {}; сменены {}</small>",
            found["bank_name"],
            found["bank_account"],
            found["bank_mfo"],
            found["recipient_name"],
            found["recipient_tin"],
            found["changed_at"],
        )

    @admin.display(description="последние выплаты")
    def payouts(self, obj: SellerBalance) -> str:
        found = rows(
            "select id, amount, status, created_at from market_payouts where seller_id = %s "
            "order by id desc limit 10",
            [obj.pk],
        )

        return (
            format_html_join(
                "<br>",
                '<a href="{}">№{}</a> · {} · {} · {}',
                (
                    (
                        reverse("savdex_admin:market_payout_change", args=[p["id"]]),
                        p["id"],
                        cash.money(p["amount"]),
                        cash.STATUSES.get(p["status"], p["status"]),
                        p["created_at"],
                    )
                    for p in found
                ),
            )
            or "нет"
        )

    def cash_forms(self, request: HttpRequest, obj: Any) -> list[dict[str, Any]]:  # noqa: ANN401
        if not _admin_of(request).can(f"{cash.SECTION}.create") or obj.status != "approved":
            return []

        return [
            {
                "title": "Создать выплату (шаг 1 из 2)",
                "help": "Подтверждает выплату другой кассир. Сумма — не больше доступного.",
                "url": reverse("savdex_admin:market_sellerbalance_payout", args=[obj.pk]),
                "code": "create",
                "button": "Создать выплату",
                "fields": [
                    {"name": "amount", "label": "Сумма, сум", "type": "text"},
                    {"name": "note", "label": "Комментарий", "type": "textarea"},
                ],
            }
        ]

    def payout_view(self, request: HttpRequest, object_id: str) -> HttpResponse:
        obj = self._post(request, object_id, f"{cash.SECTION}.create")
        amount = tiyin(request.POST.get("amount"))

        if amount is None:
            return self._back(request, obj, None, "Сумма выплаты — число больше нуля, в сумах.")

        try:
            payout_id = cash.create_payout(
                _admin_of(request),
                obj.pk,
                amount,
                note=(request.POST.get("note") or "").strip() or None,
                ip=audit.client_ip(request),
            )
        except cash.CashRefused as refused:
            return self._back(request, obj, None, str(refused))

        self.message_user(
            request,
            f"Выплата №{payout_id} создана — её подтверждает другой кассир.",
            messages.SUCCESS,
        )

        return HttpResponseRedirect(reverse("savdex_admin:market_payout_change", args=[payout_id]))


# ── Выплаты ─────────────────────────────────────────────────────────


class PayoutStatus(admin.SimpleListFilter):
    title = "статус"
    parameter_name = "status"

    def lookups(self, request: HttpRequest, model_admin: Any) -> list[tuple[str, str]]:  # noqa: ANN401
        return list(cash.STATUSES.items())

    def queryset(self, request: HttpRequest, queryset: QuerySet[Any]) -> QuerySet[Any]:
        return queryset.filter(status=self.value()) if self.value() else queryset


@register(Payout, section="market_cash")
class PayoutAdmin(_ReadOnly):
    laravel_model = "Savdex\\Market\\Payout"
    title_list = "Выплаты продавцам"
    title_change = "Выплата продавцу"

    list_display = ("id", "seller_name", "amount_text", "state", "created")
    list_filter = (PayoutStatus,)
    search_fields = ("bank_reference",)
    ordering = ("-id",)
    list_per_page = 50
    fields = ("seller_name", "amount_text", "state", "people", "requisites", "bank", "note")
    readonly_fields = fields

    def get_queryset(self, request: HttpRequest) -> QuerySet[Payout]:
        from django.db.models import OuterRef, Subquery

        from savdex.data.models import CompanyRecord

        found: QuerySet[Payout] = super().get_queryset(request)

        return found.select_related("seller").annotate(
            company_title=Subquery(
                CompanyRecord.objects.filter(pk=OuterRef("seller__company_id")).values("name")[:1]
            )
        )

    def get_urls(self) -> list[Any]:
        return [
            path(
                "<path:object_id>/act/",
                self.admin_site.admin_view(self.act_view),
                name="market_payout_act",
            ),
            *super().get_urls(),
        ]

    @admin.display(description="продавец")
    def seller_name(self, obj: Payout) -> str:
        return format_html(
            '<a href="{}">{}</a> <small>№{}</small>',
            reverse("savdex_admin:market_sellerbalance_change", args=[obj.seller_id]),
            getattr(obj, "company_title", None) or "—",
            obj.seller_id,
        )

    @admin.display(description="сумма", ordering="amount")
    def amount_text(self, obj: Payout) -> str:
        return cash.money(obj.amount)

    @admin.display(description="статус", ordering="status")
    def state(self, obj: Payout) -> str:
        return format_html(
            "{}<br><small>{}</small>",
            _badge(
                cash.STATUSES.get(obj.status, obj.status), _PAYOUT_TONES.get(obj.status, "gray")
            ),
            obj.cancel_reason or "",
        )

    @admin.display(description="создана", ordering="created_at")
    def created(self, obj: Payout) -> str:
        return when(obj.created_at)

    @admin.display(description="кто")
    def people(self, obj: Payout) -> str:
        return format_html(
            "создал {} {}<br>подтвердил {} {}{}<br>отметил выплату {} {}<br>отменил {} {}{}",
            _staff_name(obj.created_by),
            when(obj.created_at),
            _staff_name(obj.approved_by),
            when(obj.approved_at),
            f" — на свежие реквизиты, сверены: {obj.fresh_check_note}"
            if obj.fresh_requisites
            else "",
            _staff_name(obj.paid_by),
            when(obj.paid_at),
            _staff_name(obj.cancelled_by),
            when(obj.cancelled_at),
            " — платёжка не отправлялась" if obj.cancel_not_sent else "",
        )

    @admin.display(description="реквизиты")
    def requisites(self, obj: Payout) -> str:
        """Подтверждённые реквизиты (строка истории), а до подтверждения — текущие."""
        if obj.requisites_log_id is not None:
            found = one(
                "select bank_name, bank_account, bank_mfo, recipient_name, recipient_tin, "
                "created_at as changed_at from market_seller_requisites_log where id = %s",
                [obj.requisites_log_id],
            )
        else:
            found = cash.requisites_of(obj.seller_id)

        if found is None:
            return "нет"

        return format_html(
            "{} · счёт {} · МФО {}<br><small>получатель {}, ИНН/ПИНФЛ {}; сменены {}</small>",
            found["bank_name"],
            found["bank_account"],
            found["bank_mfo"],
            found["recipient_name"],
            found["recipient_tin"],
            found["changed_at"],
        )

    @admin.display(description="платёжка")
    def bank(self, obj: Payout) -> str:
        if not obj.bank_reference:
            return "—"

        return format_html(
            "{}<br><small>журнал денег: {}</small>", obj.bank_reference, obj.ledger_group
        )

    def cash_forms(self, request: HttpRequest, obj: Payout) -> list[dict[str, Any]]:
        admin_ = _admin_of(request)
        url = reverse("savdex_admin:market_payout_act", args=[obj.pk])
        found: list[dict[str, Any]] = []

        if obj.status == cash.DRAFT and admin_.can(f"{cash.SECTION}.moderate"):
            found.append(
                {
                    "title": "Подтвердить выплату (шаг 2 из 2)",
                    "help": "Подтверждает другой кассир — не тот, кто создал. Реквизиты, "
                    "сменённые меньше суток назад, сверьте с продавцом по известному телефону "
                    "и напишите, как сверили.",
                    "url": url,
                    "code": "approve",
                    "button": "Подтвердить",
                    "fields": [
                        {
                            "name": "fresh_ok",
                            "label": "Реквизиты сверены с продавцом",
                            "type": "checkbox",
                        },
                        {"name": "fresh_note", "label": "Как сверили", "type": "textarea"},
                    ],
                }
            )

        if obj.status == cash.APPROVED and admin_.can(f"{cash.SECTION}.moderate"):
            found.append(
                {
                    "title": "Деньги переведены",
                    "help": "После платёжки из банка: номер платёжного поручения. Проводка в "
                    "журнале денег — один раз.",
                    "url": url,
                    "code": "paid",
                    "button": "Отметить выплаченной",
                    "fields": [
                        {"name": "bank_reference", "label": "Платёжное поручение", "type": "text"}
                    ],
                }
            )

        can_cancel = admin_.can(f"{cash.SECTION}.edit") and (
            obj.status == cash.DRAFT
            or (
                obj.status == cash.APPROVED
                and (obj.approved_by == admin_.id or admin_.is_superadmin)
            )
        )

        if can_cancel:
            fields: list[dict[str, str]] = [
                {"name": "reason", "label": "Причина", "type": "textarea"}
            ]

            if obj.status == cash.APPROVED:
                fields.insert(
                    0,
                    {
                        "name": "not_sent",
                        "label": "Платёжка в банк не отправлялась",
                        "type": "checkbox",
                    },
                )

            found.append(
                {
                    "title": "Отменить выплату",
                    "help": "Подтверждённую отменяет только тот, кто её подтвердил, — и только "
                    "если платёжка в банк не уходила."
                    if obj.status == cash.APPROVED
                    else "",
                    "url": url,
                    "code": "cancel",
                    "button": "Отменить",
                    "fields": fields,
                }
            )

        return found

    def act_view(self, request: HttpRequest, object_id: str) -> HttpResponse:
        do = request.POST.get("do", "")
        ability = {"approve": "moderate", "paid": "moderate", "cancel": "edit"}.get(do)

        if ability is None:
            raise PermissionDenied

        obj = self._post(request, object_id, f"{cash.SECTION}.{ability}")
        admin_ = _admin_of(request)
        ip = audit.client_ip(request)

        try:
            if do == "approve":
                cash.approve_payout(
                    admin_,
                    obj.pk,
                    fresh_ok=request.POST.get("fresh_ok") == "1",
                    fresh_note=request.POST.get("fresh_note"),
                    ip=ip,
                )
                done = f"Выплата №{obj.pk} подтверждена."
            elif do == "paid":
                cash.mark_paid(admin_, obj.pk, request.POST.get("bank_reference") or "", ip=ip)
                done = f"Выплата №{obj.pk} отмечена выплаченной."
            else:
                cash.cancel_payout(
                    admin_,
                    obj.pk,
                    request.POST.get("reason") or "",
                    not_sent=request.POST.get("not_sent") == "1",
                    ip=ip,
                )
                done = f"Выплата №{obj.pk} отменена."
        except cash.CashRefused as refused:
            return self._back(request, obj, None, str(refused))

        return self._back(request, obj, done, None)


# ── Наличные к сверке с отчётом BTS ────────────────────────────────


class Reconciled(admin.SimpleListFilter):
    title = "сверка с BTS"
    parameter_name = "reconciled"

    def lookups(self, request: HttpRequest, model_admin: Any) -> list[tuple[str, str]]:  # noqa: ANN401
        return [("no", "ждут сверки"), ("yes", "сверены")]

    def queryset(self, request: HttpRequest, queryset: QuerySet[Any]) -> QuerySet[Any]:
        if self.value() == "no":
            return queryset.filter(cash_reconciled_at__isnull=True)

        if self.value() == "yes":
            return queryset.filter(cash_reconciled_at__isnull=False)

        return queryset


@register(CashOrder, section="market_cash")
class CashOrderAdmin(_ReadOnly):
    laravel_model = "Savdex\\Market\\Order"
    title_list = "Наличные: сверка с отчётом BTS"
    title_change = "Наличные заказа"

    list_display = ("number", "total_text", "point", "issued", "reconciled")
    list_filter = (Reconciled,)
    search_fields = ("number",)
    list_per_page = 100
    fields = ("number", "total_text", "point", "issued", "reconciled")
    readonly_fields = fields

    def get_queryset(self, request: HttpRequest) -> QuerySet[CashOrder]:
        found: QuerySet[CashOrder] = super().get_queryset(request)

        return found.filter(payment_method="cash", status=orders.ISSUED)

    def get_ordering(self, request: HttpRequest) -> Any:  # noqa: ANN401
        # Сначала ждущие сверки, старые выше
        return (F("cash_reconciled_at").asc(nulls_first=True), "issued_at", "id")

    def get_actions(self, request: HttpRequest) -> dict[str, Any]:
        """Сверка пачкой — отмеченные строки списка (POST с CSRF, как у Django)."""
        if not _admin_of(request).can(f"{cash.SECTION}.moderate"):
            return {}

        return {
            "reconcile": (
                type(self).reconcile_action,
                "reconcile",
                "Сверено с отчётом BTS…",
            )
        }

    def reconcile_action(
        self, request: HttpRequest, queryset: QuerySet[CashOrder]
    ) -> HttpResponse | None:
        """
        Пачкой — через страницу подтверждения: сколько заказов ждут сверки и
        на какую сумму, номер или дата отчёта BTS — один на всю пачку.
        """
        ids = [int(pk) for pk in queryset.values_list("pk", flat=True)[: cash.RECONCILE_BATCH + 1]]

        if len(ids) > cash.RECONCILE_BATCH:
            self.message_user(
                request,
                f"Не больше {cash.RECONCILE_BATCH} заказов за одну сверку.",
                messages.ERROR,
            )

            return None

        count, total = cash.cash_pending(ids)

        if request.POST.get("confirm") == "yes":
            try:
                done = cash.reconcile_cash(
                    _admin_of(request),
                    ids,
                    request.POST.get("report") or "",
                    ip=audit.client_ip(request),
                )
            except cash.CashRefused as refused:
                self.message_user(request, str(refused), messages.ERROR)

                return None

            self.message_user(request, f"Сверено с отчётом BTS: {done}.", messages.SUCCESS)

            return None

        return TemplateResponse(
            request,
            "admin/market/cash_reconcile_confirm.html",
            {
                **self.admin_site.each_context(request),
                "title": "Сверка наличных с отчётом BTS",
                "opts": self.model._meta,
                "ids": ids,
                "count": count,
                "total": cash.money(total),
                "report_min": cash.REPORT_MIN,
                "action_checkbox_name": helpers.ACTION_CHECKBOX_NAME,
            },
        )

    def get_urls(self) -> list[Any]:
        return [
            path(
                "<path:object_id>/reconcile/",
                self.admin_site.admin_view(self.reconcile_view),
                name="market_cashorder_reconcile",
            ),
            *super().get_urls(),
        ]

    @admin.display(description="сумма", ordering="total")
    def total_text(self, obj: CashOrder) -> str:
        return cash.money(obj.total)

    @admin.display(description="пункт выдачи")
    def point(self, obj: CashOrder) -> str:
        return obj.pickup_point_name

    @admin.display(description="выдан", ordering="issued_at")
    def issued(self, obj: CashOrder) -> str:
        return when(obj.issued_at)

    @admin.display(description="сверка", ordering="cash_reconciled_at")
    def reconciled(self, obj: CashOrder) -> str:
        if obj.cash_reconciled_at is None:
            return "ждёт"

        return format_html(
            "{} <small>({}; {})</small>",
            when(obj.cash_reconciled_at),
            obj.cash_reconciled_ref or "",
            _staff_name(obj.cash_reconciled_by),
        )

    def cash_forms(self, request: HttpRequest, obj: CashOrder) -> list[dict[str, Any]]:
        if not _admin_of(request).can(f"{cash.SECTION}.moderate"):
            return []

        url = reverse("savdex_admin:market_cashorder_reconcile", args=[obj.pk])

        if obj.cash_reconciled_at is not None:
            return [
                {
                    "title": "Снять сверку",
                    "help": "Ошиблись заказом или отчётом. Нельзя, если деньги заказа уже в "
                    "выплате — сначала отмените её.",
                    "url": url,
                    "code": "unreconcile",
                    "button": "Снять сверку",
                    "fields": [{"name": "reason", "label": "Причина", "type": "textarea"}],
                }
            ]

        return [
            {
                "title": "Сверено с отчётом BTS",
                "help": "Сумма заказа есть в отчёте пункта выдачи: деньги пойдут продавцу "
                f"«к выплате». Номер или дата отчёта — не короче {cash.REPORT_MIN} знаков.",
                "url": url,
                "code": "reconcile",
                "button": "Сверено",
                "fields": [{"name": "report", "label": "Отчёт BTS (номер, дата)", "type": "text"}],
            }
        ]

    def reconcile_view(self, request: HttpRequest, object_id: str) -> HttpResponse:
        obj = self._post(request, object_id, f"{cash.SECTION}.moderate")
        admin_ = _admin_of(request)
        ip = audit.client_ip(request)

        try:
            if request.POST.get("do") == "unreconcile":
                cash.unreconcile_cash(admin_, obj.pk, request.POST.get("reason") or "", ip=ip)

                return self._back(request, obj, f"Заказ {obj.number}: сверка снята.", None)

            done = cash.reconcile_cash(admin_, [obj.pk], request.POST.get("report") or "", ip=ip)
        except cash.CashRefused as refused:
            return self._back(request, obj, None, str(refused))

        return self._back(
            request,
            obj,
            f"Заказ {obj.number}: сверено." if done else None,
            None if done else "Заказ уже сверен.",
        )


# ── Реквизиты ───────────────────────────────────────────────────────


@register(SellerRequisites, section="market_cash")
class SellerRequisitesAdmin(_ReadOnly):
    laravel_model = "Savdex\\Market\\SellerRequisites"
    title_list = "Реквизиты продавцов"
    title_change = "Реквизиты продавца"

    #: Счёт в списке — скрыт (последние 4 цифры); поиска по счёту нет
    list_display = ("seller_id", "bank_name", "account_masked", "recipient_name", "changed")
    search_fields = ("recipient_name",)
    list_per_page = 50
    fields = (
        "seller_id",
        "bank_account",
        "bank_mfo",
        "bank_name",
        "recipient_name",
        "recipient_tin",
        "changed",
        "history",
    )
    readonly_fields = fields

    @admin.display(description="счёт")
    def account_masked(self, obj: SellerRequisites) -> str:
        return cash.masked(obj.bank_account)

    @admin.display(description="сменены", ordering="changed_at")
    def changed(self, obj: SellerRequisites) -> str:
        return format_html(
            "{} <small>({})</small>", when(obj.changed_at), _staff_name(obj.changed_by)
        )

    @admin.display(description="история смен")
    def history(self, obj: SellerRequisites) -> str:
        found = RequisitesLog.objects.filter(seller_id=obj.seller_id).order_by("-id")[:50]

        return format_html_join(
            "<br>",
            "{} · {} · счёт {} · МФО {} · {} ({}) <small>— {}, IP {}</small>",
            (
                (
                    when(row.created_at),
                    row.bank_name,
                    row.bank_account,
                    row.bank_mfo,
                    row.recipient_name,
                    row.recipient_tin,
                    _staff_name(row.changed_by),
                    row.ip or "—",
                )
                for row in found
            ),
        )


# ── Возвраты покупателям ────────────────────────────────────────────

_REFUND_MODES = {
    None: "не запрошен",
    "api": "запрос к провайдеру идёт (API)",
    "manual": "API нет — вернуть в кабинете провайдера",
    "error": "сбой связи — итог неизвестен, проверить у провайдера",
    "claimed": "касса возвращает вручную",
}


@register(RefundOrder, section="market_cash")
class RefundOrderAdmin(_ReadOnly):
    laravel_model = "Savdex\\Market\\Order"
    title_list = "Возвраты покупателям"
    title_change = "Возврат покупателю"

    list_display = ("number", "total_text", "payment", "cancelled")
    search_fields = ("number",)
    ordering = ("cancelled_at", "id")
    list_per_page = 50
    fields = ("number", "total_text", "payment", "cancelled")
    readonly_fields = fields

    def get_queryset(self, request: HttpRequest) -> QuerySet[RefundOrder]:
        found: QuerySet[RefundOrder] = super().get_queryset(request)

        return found.filter(status=orders.REFUND_PENDING)

    def get_urls(self) -> list[Any]:
        return [
            path(
                "<path:object_id>/refund/",
                self.admin_site.admin_view(self.refund_view),
                name="market_refundorder_refund",
            ),
            *super().get_urls(),
        ]

    @staticmethod
    def _payment(obj: RefundOrder) -> dict[str, Any] | None:
        return one(
            "select provider, provider_transaction_id, refund_requested_at, refund_mode, "
            "refund_claimed_by, note, rejection_checked_at "
            "from market_payments where order_id = %s and status = 'paid' order by id desc limit 1",
            [obj.pk],
        )

    @admin.display(description="сумма", ordering="total")
    def total_text(self, obj: RefundOrder) -> str:
        return cash.money(obj.total)

    @admin.display(description="оплата")
    def payment(self, obj: RefundOrder) -> str:
        found = self._payment(obj)

        if found is None:
            return "проведённой оплаты картой нет"

        return format_html(
            "{} · транзакция {}<br><small>возврат: {}{}; запрошен: {}; {}</small>",
            found["provider"],
            found["provider_transaction_id"] or "—",
            _REFUND_MODES.get(found["refund_mode"], found["refund_mode"]),
            f" ({_staff_name(found['refund_claimed_by'])})" if found["refund_claimed_by"] else "",
            found["refund_requested_at"] or "нет",
            found["note"] or "",
        )

    @admin.display(description="отменён", ordering="cancelled_at")
    def cancelled(self, obj: RefundOrder) -> str:
        return format_html(
            "{}<br><small>{}</small>", when(obj.cancelled_at), obj.cancel_reason or ""
        )

    def cash_forms(self, request: HttpRequest, obj: RefundOrder) -> list[dict[str, Any]]:
        from savdex.market.payments import base

        found = self._payment(obj)
        admin_ = _admin_of(request)

        if not admin_.can(f"{cash.SECTION}.moderate") or found is None:
            return []

        url = reverse("savdex_admin:market_refundorder_refund", args=[obj.pk])
        mode = found["refund_mode"]
        mine = found["refund_claimed_by"] == admin_.id or admin_.is_superadmin
        forms: list[dict[str, Any]] = []

        if found["refund_requested_at"] is None:
            forms.append(
                {
                    "title": "Возвращаю вручную",
                    "help": "Возврат ещё не запрашивали. Возьмите его на себя до того, как "
                    "вернуть деньги в кабинете провайдера, — тогда расписание не вернёт их "
                    "второй раз через API.",
                    "url": url,
                    "code": "claim",
                    "button": "Беру возврат на себя",
                    "fields": [],
                }
            )

        if mode in cash.MANUAL_MODES and (mode != "claimed" or mine):
            forms.append(
                {
                    "title": "Деньги вернули в кабинете провайдера",
                    "help": "Только после возврата в кабинете Uzum, Payme или Click: заказ "
                    "станет «деньги возвращены», в журнале денег — проводка возврата.",
                    "url": url,
                    "code": "refund",
                    "button": "Отметить возврат",
                    "fields": [
                        {
                            "name": "refund_reference",
                            "label": "Номер возврата у провайдера",
                            "type": "text",
                        },
                        {"name": "note", "label": "Где и когда вернули", "type": "textarea"},
                    ],
                }
            )

        if mode == "claimed" and mine:
            forms.append(
                {
                    "title": "Отпустить возврат",
                    "help": "Вручную возвращать не будете — возврат снова запросит расписание "
                    "через API провайдера.",
                    "url": url,
                    "code": "unclaim",
                    "button": "Отпустить",
                    "fields": [{"name": "reason", "label": "Причина", "type": "textarea"}],
                }
            )

        if found["rejection_checked_at"] is None:
            forms.append(
                {
                    "title": "Проверено у провайдера",
                    "help": "Возврат завис (сбой связи, ждём отмену от провайдера): проверили "
                    "в кабинете провайдера — сверка больше не покажет его расхождением. Заказ "
                    f"остаётся «ждёт возврата». Заметка — не короче {base.ACK_NOTE_MIN} знаков.",
                    "url": url,
                    "code": "check",
                    "button": "Проверено",
                    "fields": [{"name": "note", "label": "Что проверили", "type": "textarea"}],
                }
            )

        return forms

    def refund_view(self, request: HttpRequest, object_id: str) -> HttpResponse:
        obj = self._post(request, object_id, f"{cash.SECTION}.moderate")
        admin_ = _admin_of(request)
        ip = audit.client_ip(request)
        do = request.POST.get("do")

        try:
            if do == "check":
                if not cash.acknowledge_refund(admin_, obj.pk, request.POST.get("note") or ""):
                    return self._back(request, obj, None, "Уже отмечено — обновите страницу.")

                return self._back(request, obj, "Отмечено: проверено у провайдера.", None)

            if do == "claim":
                if not cash.claim_refund(admin_, obj.pk, ip=ip):
                    return self._back(
                        request, obj, None, "Возврат уже запрошен — обновите страницу."
                    )

                return self._back(
                    request, obj, "Возврат за вами: верните деньги в кабинете провайдера.", None
                )

            if do == "unclaim":
                cash.unclaim_refund(admin_, obj.pk, request.POST.get("reason") or "", ip=ip)

                return self._back(request, obj, "Возврат отпущен — его запросит расписание.", None)

            done = cash.mark_refunded(
                admin_,
                obj.pk,
                request.POST.get("refund_reference") or "",
                request.POST.get("note") or "",
                ip=ip,
            )
        except cash.CashRefused as refused:
            return self._back(request, obj, None, str(refused))

        if not done:
            return self._back(request, obj, None, "Заказ уже не ждёт возврата — обновите страницу.")

        self.message_user(request, f"Заказ {obj.number}: деньги возвращены.", messages.SUCCESS)

        return HttpResponseRedirect(reverse("savdex_admin:market_refundorder_changelist"))
