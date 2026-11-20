"""
Касса маркетплейса в админке (раздел market_cash, роль «Касса
маркетплейса»; savdex/market/cash.py).

- **Балансы продавцов** — только смотреть: начислено, держится, доступно,
  в работе, выплачено; реквизиты и последние выплаты. Отсюда кассир
  создаёт выплату (шаг 1).
- **Выплаты продавцам** — подтвердить (шаг 2, другой кассир; на свежие
  реквизиты — с отметкой «реквизиты сверены»), отметить выплаченной
  (номер платёжки — проводка в журнале денег), отменить.
- **Реквизиты продавцов** — только смотреть, с историей смен: меняет их
  только владелец компании из кабинета.
- **Возвраты покупателям** — заказы в «ждёт возврата»: касса вернула
  деньги в кабинете провайдера и отмечает возврат здесь.

Каждое действие — POST с CSRF на свой адрес, право проверяется и здесь,
и в cash.py; итог — строка журнала действий (cash.py).
"""

from __future__ import annotations

from typing import Any

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.urls import path, reverse
from django.utils.html import format_html, format_html_join

from savdex import audit
from savdex.adminsite import SavdexModelAdmin, _admin_of, register
from savdex.crm.admin import _badge, when
from savdex.market import cash, orders
from savdex.market.admin import _company_name
from savdex.market.common import one, rows, tiyin
from savdex.market.models import Payout, RefundOrder, RequisitesLog, SellerBalance, SellerRequisites

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

    def change_view(
        self,
        request: HttpRequest,
        object_id: str,
        form_url: str = "",
        extra_context: Any = None,  # noqa: ANN401
    ) -> HttpResponse:
        obj = self.get_object(request, object_id)
        extra = dict(extra_context or {})

        if obj is not None:
            extra["cash_forms"] = self.cash_forms(request, obj)

        return super().change_view(request, object_id, form_url, extra)

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
        found: QuerySet[SellerBalance] = super().get_queryset(request)

        return found.filter(status__in=("approved", "blocked")).annotate(
            company_title=_company_name()
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

    def _balance(self, obj: SellerBalance) -> cash.Balance:
        cached = getattr(obj, "_cash_balance", None)

        if cached is None:
            cached = cash.balance(obj.pk)
            obj._cash_balance = cached  # type: ignore[attr-defined]

        return cached

    @admin.display(description="компания", ordering="company_title")
    def company(self, obj: SellerBalance) -> str:
        return format_html("{} <small>№{}</small>", getattr(obj, "company_title", "—"), obj.pk)

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
            "начислено {} · держится {} (выдача + {} дн.)<br>к выплате {} · в работе {} · "
            "выплачено {}<br><b>доступно {}</b>",
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
        if not _admin_of(request).can(f"{cash.SECTION}.create"):
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
            "создал {} {}<br>подтвердил {} {}{}<br>отметил выплату {} {}<br>отменил {} {}",
            _staff_name(obj.created_by),
            when(obj.created_at),
            _staff_name(obj.approved_by),
            when(obj.approved_at),
            " — на свежие реквизиты, сверены" if obj.fresh_requisites else "",
            _staff_name(obj.paid_by),
            when(obj.paid_at),
            _staff_name(obj.cancelled_by),
            when(obj.cancelled_at),
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
                    "сменённые меньше суток назад, сверьте с продавцом по известному телефону.",
                    "url": url,
                    "code": "approve",
                    "button": "Подтвердить",
                    "fields": [
                        {
                            "name": "fresh_ok",
                            "label": "Реквизиты сверены с продавцом",
                            "type": "checkbox",
                        }
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

        if obj.status in cash.IN_WORK and admin_.can(f"{cash.SECTION}.edit"):
            found.append(
                {
                    "title": "Отменить выплату",
                    "help": "",
                    "url": url,
                    "code": "cancel",
                    "button": "Отменить",
                    "fields": [{"name": "reason", "label": "Причина", "type": "textarea"}],
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
                    admin_, obj.pk, fresh_ok=request.POST.get("fresh_ok") == "1", ip=ip
                )
                done = f"Выплата №{obj.pk} подтверждена."
            elif do == "paid":
                cash.mark_paid(admin_, obj.pk, request.POST.get("bank_reference") or "", ip=ip)
                done = f"Выплата №{obj.pk} отмечена выплаченной."
            else:
                cash.cancel_payout(admin_, obj.pk, request.POST.get("reason") or "", ip=ip)
                done = f"Выплата №{obj.pk} отменена."
        except cash.CashRefused as refused:
            return self._back(request, obj, None, str(refused))

        return self._back(request, obj, done, None)


# ── Реквизиты ───────────────────────────────────────────────────────


@register(SellerRequisites, section="market_cash")
class SellerRequisitesAdmin(_ReadOnly):
    laravel_model = "Savdex\\Market\\SellerRequisites"
    title_list = "Реквизиты продавцов"
    title_change = "Реквизиты продавца"

    list_display = ("seller_id", "bank_name", "bank_account", "recipient_name", "changed")
    search_fields = ("bank_account", "recipient_tin", "recipient_name")
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

    @admin.display(description="сумма", ordering="total")
    def total_text(self, obj: RefundOrder) -> str:
        return cash.money(obj.total)

    @admin.display(description="оплата")
    def payment(self, obj: RefundOrder) -> str:
        found = one(
            "select provider, provider_transaction_id, refund_requested_at, note "
            "from market_payments where order_id = %s and status = 'paid' order by id desc limit 1",
            [obj.pk],
        )

        if found is None:
            return "проведённой оплаты картой нет"

        return format_html(
            "{} · транзакция {}<br><small>возврат запрошен: {}; {}</small>",
            found["provider"],
            found["provider_transaction_id"] or "—",
            found["refund_requested_at"] or "нет",
            found["note"] or "",
        )

    @admin.display(description="отменён", ordering="cancelled_at")
    def cancelled(self, obj: RefundOrder) -> str:
        return format_html(
            "{}<br><small>{}</small>", when(obj.cancelled_at), obj.cancel_reason or ""
        )

    def cash_forms(self, request: HttpRequest, obj: RefundOrder) -> list[dict[str, Any]]:
        if not _admin_of(request).can(f"{cash.SECTION}.moderate"):
            return []

        return [
            {
                "title": "Деньги вернули в кабинете провайдера",
                "help": "Только после возврата в кабинете Uzum, Payme или Click: заказ станет "
                "«деньги возвращены», в журнале денег — проводка возврата.",
                "url": reverse("savdex_admin:market_refundorder_refund", args=[obj.pk]),
                "code": "refund",
                "button": "Отметить возврат",
                "fields": [{"name": "note", "label": "Где и когда вернули", "type": "textarea"}],
            }
        ]

    def refund_view(self, request: HttpRequest, object_id: str) -> HttpResponse:
        obj = self._post(request, object_id, f"{cash.SECTION}.moderate")

        try:
            done = cash.mark_refunded(
                _admin_of(request),
                obj.pk,
                request.POST.get("note") or "",
                ip=audit.client_ip(request),
            )
        except cash.CashRefused as refused:
            return self._back(request, obj, None, str(refused))

        if not done:
            return self._back(request, obj, None, "Заказ уже не ждёт возврата — обновите страницу.")

        self.message_user(request, f"Заказ {obj.number}: деньги возвращены.", messages.SUCCESS)

        return HttpResponseRedirect(reverse("savdex_admin:market_refundorder_changelist"))
