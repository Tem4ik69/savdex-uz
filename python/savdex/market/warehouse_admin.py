"""
Склад и пункты выдачи маркетплейса в админке (savdex/market/warehouse.py).

Раздел «Склад маркетплейса» (market_stock, роль «Склад маркетплейса»):

- **Поставки** — отправленные продавцами заявки на свой склад: принять
  (по каждой строке — принято и брак) или отказать с причиной;
- **Отгрузки** — собрать отгрузку в пункт выдачи (в неё сразу попадают
  все собранные заказы пункта с товаром на складе), отправить, отменить,
  убрать заказ; принять невостребованные, вернувшиеся из пункта;
- **Движения остатка** — журнал (только смотреть) и ручные движения:
  списание, вывоз продавцу, инвентаризация — всегда с причиной.

Раздел «Пункт выдачи» (market_pickup, роль «Пункт выдачи маркетплейса»):

- **Заказы в пункте** — выдать по коду покупателя; к оплате — только у
  заказов «при получении»;
- **Отгрузки пункта** — принять отгрузку со склада (заказы — «можно
  забрать», покупателю — уведомление), собрать и отправить
  невостребованные обратно.

Склады заводит администратор (раздел заказов, как и пункты выдачи) и там
же отмечает, кто где работает. Сотрудник видит и отмечает только своё
место; администратор (market_orders.moderate) — все. Каждое действие —
POST с CSRF на адрес действия, строка журнала действий.
"""

from __future__ import annotations

from datetime import UTC
from typing import Any, ClassVar

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db import connection, transaction
from django.db.models import OuterRef, QuerySet, Subquery
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join

from savdex import audit
from savdex.accounts.models import User
from savdex.adminsite import SavdexModelAdmin, _admin_of, register
from savdex.crm.admin import _badge, when
from savdex.market import orders, warehouse
from savdex.market.admin import SLUG, _company_name, _money
from savdex.market.common import one, rows
from savdex.market.models import (
    PickupPoint,
    PointOrder,
    PointShipment,
    Seller,
    Shipment,
    StockMovement,
    Supply,
    Warehouse,
)

_TEMPLATE = "admin/market/warehouse_change_form.html"

#: Право на действия склада и пункта
STOCK_ABILITY = "market_stock.moderate"
PICKUP_ABILITY = "market_pickup.moderate"

_SUPPLY_TONES = {
    "draft": "gray",
    "submitted": "warning",
    "received": "success",
    "rejected": "danger",
    "cancelled": "gray",
}

_SHIPMENT_TONES = {
    "assembling": "warning",
    "in_transit": "info",
    "delivered": "success",
    "cancelled": "gray",
}


def places(request: HttpRequest) -> warehouse.Places:
    """Где сотрудник работает; администратор заказов — везде."""
    admin_ = _admin_of(request)

    return warehouse.places_of(admin_.id, everything=admin_.can("market_orders.moderate"))


def _staff_name(user_id: int | None) -> str:
    if user_id is None:
        return "—"

    found = one("select name from users where id = %s", [user_id])

    return f"{found['name'] if found else '—'} (№{user_id})"


def _at(value: Any) -> str:  # noqa: ANN401
    if value is None:
        return "—"

    return when(value if value.tzinfo is not None else timezone.make_aware(value, UTC))


def _record(
    request: HttpRequest,
    section: str,
    action: str,
    model: str,
    pk: int,
    label: str,
    note: str | None = None,
    changes: dict[str, Any] | None = None,
) -> None:
    audit.record(
        connection,
        action=action,
        section=section,
        actor=_admin_of(request),
        subject_type=f"Savdex\\Market\\{model}",
        subject_id=pk,
        subject_label=label,
        changes=changes,
        note=note,
        ip=audit.client_ip(request),
    )


class _Actions(SavdexModelAdmin):
    """
    Карточка с формами действий (как касса): каждая форма — POST на
    <id>/act/ с кодом действия ``do``. Код, которого нет среди форм этой
    записи сейчас, — «уже недоступно»; отказ — WarehouseError с текстом.
    """

    change_form_template = _TEMPLATE
    act_ability: ClassVar[str] = STOCK_ABILITY

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:  # noqa: ANN401
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:  # noqa: ANN401
        return False

    def action_forms(self, request: HttpRequest, obj: Any) -> list[dict[str, Any]]:  # noqa: ANN401
        return []

    def act(self, request: HttpRequest, obj: Any, code: str) -> str | None:  # noqa: ANN401
        """Итог для «готово»; None — действие само сказало, что вышло."""
        raise NotImplementedError

    def render_change_form(
        self,
        request: HttpRequest,
        context: dict[str, Any],
        add: bool = False,
        change: bool = False,
        form_url: str = "",
        obj: Any = None,  # noqa: ANN401
    ) -> HttpResponse:
        if obj is not None and _admin_of(request).can(self.act_ability):
            context["stock_forms"] = self.action_forms(request, obj)
            opts = self.model._meta
            context["act_url"] = reverse(
                f"savdex_admin:{opts.app_label}_{opts.model_name}_act", args=[obj.pk]
            )

        return super().render_change_form(request, context, add, change, form_url, obj)

    def get_urls(self) -> list[Any]:
        opts = self.model._meta

        return [
            path(
                "<path:object_id>/act/",
                self.admin_site.admin_view(self.act_view),
                name=f"{opts.app_label}_{opts.model_name}_act",
            ),
            *super().get_urls(),
        ]

    def act_view(self, request: HttpRequest, object_id: str) -> HttpResponse:
        if request.method != "POST" or not _admin_of(request).can(self.act_ability):
            raise PermissionDenied

        obj = self.get_object(request, object_id)

        if obj is None:
            raise PermissionDenied

        opts = self.model._meta
        page = reverse(f"savdex_admin:{opts.app_label}_{opts.model_name}_change", args=[obj.pk])
        code = request.POST.get("do", "")

        if code not in {form["code"] for form in self.action_forms(request, obj)}:
            self.message_user(request, "Это действие уже недоступно.", messages.WARNING)

            return HttpResponseRedirect(page)

        try:
            with transaction.atomic():
                done = self.act(request, obj, code)
        except warehouse.WarehouseError as refused:
            self.message_user(request, str(refused), messages.ERROR)

            return HttpResponseRedirect(page)

        if done is not None:
            self.message_user(request, done, messages.SUCCESS)

        return HttpResponseRedirect(page)


# ── Склады ──────────────────────────────────────────────────────────


def _staff_choices(role: str) -> list[tuple[int, str]]:
    return [
        (user.pk, f"{user.name} — {user.email}")
        for user in User.objects.filter(is_admin=True, admin_role=role, status="active")
        .order_by("name")
        .only("id", "name", "email")
    ]


class WarehouseForm(forms.ModelForm):  # type: ignore[type-arg]
    staff = forms.TypedMultipleChoiceField(
        label="кто работает на складе",
        coerce=int,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Сотрудники с ролью «Склад маркетплейса»: видят и отмечают только этот склад.",
    )

    class Meta:
        model = Warehouse
        fields = ("code", "name", "address", "city", "is_active", "sort")

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        staff: Any = self.fields["staff"]
        staff.choices = _staff_choices("warehouse")

        if self.instance.pk:
            self.initial["staff"] = warehouse.staff_of(
                "market_warehouse_staff", "warehouse_id", self.instance.pk
            )

    def clean_code(self) -> str:
        code = str(self.cleaned_data.get("code") or "").strip().lower()

        if not SLUG.fullmatch(code) or len(code) > 32:
            raise forms.ValidationError("Только латиница, цифры и дефис: bts-tashkent.")

        return code


@register(Warehouse, section="market_orders")
class WarehouseAdmin(SavdexModelAdmin):
    """Склады: заводит администратор; код после создания не меняется — он в поставках."""

    laravel_model = "Savdex\\Market\\Warehouse"
    title_list = "Склады маркетплейса"
    title_add = "Новый склад"
    title_change = "Склад"

    form = WarehouseForm
    list_display = ("name", "code", "address", "is_active", "staff_count")
    list_filter = ("is_active",)
    search_fields = ("name", "code", "address")
    ordering = ("sort", "name")

    def get_fields(self, request: HttpRequest, obj: Any = None) -> Any:  # noqa: ANN401
        shown = ["code", "name", "address", "city", "is_active", "sort", "staff"]

        return [*shown, "stock"] if obj is not None else shown

    def get_readonly_fields(self, request: HttpRequest, obj: Any = None) -> Any:  # noqa: ANN401
        return ("code", "stock") if obj is not None else ()

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:  # noqa: ANN401
        """Склад с движениями не удаляется (база держит) — выключите его."""
        return False

    def save_related(
        self,
        request: HttpRequest,
        form: Any,  # noqa: ANN401
        formsets: list[Any],
        change: bool,
    ) -> None:
        super().save_related(request, form, formsets, change)

        if "staff" in form.cleaned_data:
            warehouse.set_staff(
                "market_warehouse_staff",
                "warehouse_id",
                form.instance.pk,
                form.cleaned_data["staff"],
            )

    @admin.display(description="сотрудников")
    def staff_count(self, obj: Warehouse) -> int:
        return len(warehouse.staff_of("market_warehouse_staff", "warehouse_id", obj.pk))

    @admin.display(description="остаток на складе")
    def stock(self, obj: Warehouse) -> str:
        found = rows(
            "select p.title, v.options, s.quantity, v.id from market_warehouse_stock s "
            "join market_product_variants v on v.id = s.variant_id "
            "join market_products p on p.id = s.product_id "
            "where s.warehouse_id = %s and s.quantity > 0 order by p.title, v.sort, v.id "
            "limit 500",
            [obj.pk],
        )

        if not found:
            return "пусто"

        return format_html_join(
            "<br>",
            "{} <small>{} · вариант №{}</small> — {} шт.",
            (
                (
                    r["title"],
                    _options(r["options"]),
                    r["id"],
                    r["quantity"],
                )
                for r in found
            ),
        )


def _options(value: Any) -> str:  # noqa: ANN401
    options = value if isinstance(value, dict) else {}

    return ", ".join(f"{k}: {v}" for k, v in options.items() if not str(k).startswith("_")) or (
        "без выбора"
    )


# ── Пункты выдачи: часы, точка, сотрудники ──────────────────────────


class PickupPointForm(forms.ModelForm):  # type: ignore[type-arg]
    staff = forms.TypedMultipleChoiceField(
        label="кто работает в пункте",
        coerce=int,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Сотрудники с ролью «Пункт выдачи маркетплейса»: только этот пункт.",
    )

    class Meta:
        model = PickupPoint
        fields = (
            "code",
            "name",
            "address",
            "city",
            "hours",
            "latitude",
            "longitude",
            "is_active",
            "sort",
        )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        staff: Any = self.fields["staff"]
        staff.choices = _staff_choices("pickup_point")

        if self.instance.pk:
            self.initial["staff"] = warehouse.staff_of(
                "market_pickup_point_staff", "pickup_point_id", self.instance.pk
            )

    def clean_code(self) -> str:
        code = str(self.cleaned_data.get("code") or "").strip().lower()

        if not SLUG.fullmatch(code) or len(code) > 32:
            raise forms.ValidationError("Только латиница, цифры и дефис: chilonzor-1.")

        return code

    def clean(self) -> dict[str, Any]:
        data = super().clean() or {}
        latitude, longitude = data.get("latitude"), data.get("longitude")

        if (latitude is None) != (longitude is None):
            raise forms.ValidationError("Точка на карте — широта и долгота вместе или ничего.")

        if (
            latitude is not None
            and longitude is not None
            and not (37 <= latitude <= 46 and 55 <= longitude <= 74)
        ):
            raise forms.ValidationError(
                "Точка — в пределах Узбекистана (широта 37–46, долгота 55–74)."
            )

        return data


@register(PickupPoint, section="market_orders")
class PickupPointAdmin(SavdexModelAdmin):
    """
    Пункты выдачи: заводит администратор; код после создания не меняется —
    он в заказах. Часы и точка на карте — покупателю; кто работает в пункте —
    сотрудники роли «Пункт выдачи маркетплейса».
    """

    laravel_model = "Savdex\\Market\\PickupPoint"
    title_list = "Пункты выдачи"
    title_add = "Новый пункт выдачи"
    title_change = "Пункт выдачи"

    form = PickupPointForm
    list_display = ("name", "code", "address", "city", "hours", "is_active", "sort")
    list_filter = ("is_active",)
    search_fields = ("name", "code", "address")
    ordering = ("sort", "name")

    def get_readonly_fields(self, request: HttpRequest, obj: Any = None) -> Any:  # noqa: ANN401
        return ("code",) if obj is not None else ()

    def get_fields(self, request: HttpRequest, obj: Any = None) -> Any:  # noqa: ANN401
        return [*PickupPointForm.Meta.fields, "staff"]

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:  # noqa: ANN401
        """Пункт с заказами не удаляется (база держит), выключите его."""
        return False

    def save_related(
        self,
        request: HttpRequest,
        form: Any,  # noqa: ANN401
        formsets: list[Any],
        change: bool,
    ) -> None:
        super().save_related(request, form, formsets, change)

        if "staff" in form.cleaned_data:
            warehouse.set_staff(
                "market_pickup_point_staff",
                "pickup_point_id",
                form.instance.pk,
                form.cleaned_data["staff"],
            )


# ── Поставки ────────────────────────────────────────────────────────


class SupplyStatus(admin.SimpleListFilter):
    title = "статус"
    parameter_name = "status"

    def lookups(self, request: HttpRequest, model_admin: Any) -> list[tuple[str, str]]:  # noqa: ANN401
        return [(k, v) for k, v in warehouse.SUPPLY_STATUSES.items() if k != "draft"]

    def queryset(self, request: HttpRequest, queryset: QuerySet[Any]) -> QuerySet[Any]:
        return queryset.filter(status=self.value()) if self.value() else queryset


@register(Supply, section="market_stock")
class SupplyAdmin(_Actions):
    """Поставки на свои склады: черновики продавца складу не видны."""

    laravel_model = "Savdex\\Market\\Supply"
    title_list = "Поставки продавцов"
    title_change = "Поставка"

    list_display = ("number", "seller_name", "warehouse", "state", "lines", "expected", "sent")
    list_filter = (SupplyStatus,)
    search_fields = ("number",)
    ordering = ("-created_at", "-id")
    list_per_page = 50
    list_select_related = ("warehouse",)

    fields = ("number", "seller_name", "warehouse", "state", "note", "expected", "items", "steps")
    readonly_fields = fields

    def get_queryset(self, request: HttpRequest) -> QuerySet[Supply]:
        found: QuerySet[Supply] = super().get_queryset(request).exclude(status="draft")
        place = places(request)

        if not place.everything:
            found = found.filter(warehouse_id__in=place.warehouses)

        return found.annotate(
            company_title=Subquery(
                Seller.objects.filter(pk=OuterRef("seller_id"))
                .annotate(t=_company_name())
                .values("t")[:1]
            )
        )

    def _items(self, obj: Supply) -> list[dict[str, Any]]:
        return rows(
            "select i.id, i.variant_id, i.quantity_declared, i.quantity_accepted, "
            "i.quantity_defect, p.title, v.options from market_supply_items i "
            "join market_products p on p.id = i.product_id "
            "join market_product_variants v on v.id = i.variant_id "
            "where i.supply_id = %s order by i.id",
            [obj.pk],
        )

    def action_forms(self, request: HttpRequest, obj: Supply) -> list[dict[str, Any]]:
        if obj.status != "submitted":
            return []

        return [
            {
                "code": "receive",
                "title": "Приёмка",
                "help": "По каждой строке — сколько пришло годного и сколько брака, по "
                "факту (больше или меньше заявленного — тоже). Годное — в остаток, брак "
                "ждёт вывоза продавцом.",
                "button": "Принять поставку",
                "lines": [
                    {
                        "id": item["id"],
                        "label": f"{item['title']} ({_options(item['options'])})",
                        "declared": item["quantity_declared"],
                    }
                    for item in self._items(obj)
                ],
                "fields": [],
            },
            {
                "code": "reject",
                "title": "Отказ",
                "help": "Причину увидит продавец — не короче "
                f"{warehouse.MIN_REJECT_REASON} знаков.",
                "button": "Отказать в приёмке",
                "fields": [{"name": "reason", "label": "Причина", "type": "textarea"}],
            },
        ]

    def act(self, request: HttpRequest, obj: Supply, code: str) -> str:
        admin_ = _admin_of(request)

        if code == "reject":
            reason = (request.POST.get("reason") or "").strip()
            warehouse.supply_reject(obj.pk, reason, actor_user_id=admin_.id)
            _record(request, "market_stock", "rejected", "Supply", obj.pk, obj.number, reason[:500])

            return f"Поставка {obj.number}: отказ."

        counts: dict[int, tuple[int, int]] = {}

        for item in self._items(obj):
            try:
                accepted = int(request.POST.get(f"accepted_{item['id']}", ""))
                defect = int(request.POST.get(f"defect_{item['id']}", "") or 0)
            except ValueError as error:
                raise warehouse.WarehouseError(
                    "Принято и брак — целыми числами по каждой строке."
                ) from error

            counts[int(item["id"])] = (accepted, defect)

        total = warehouse.supply_receive(obj.pk, counts, actor_user_id=admin_.id)
        _record(
            request,
            "market_stock",
            "received",
            "Supply",
            obj.pk,
            obj.number,
            changes={
                "after": {str(k): {"accepted": a, "defect": d} for k, (a, d) in counts.items()}
            },
        )

        return f"Поставка {obj.number} принята: {total} шт. в остатке."

    @admin.display(description="продавец")
    def seller_name(self, obj: Supply) -> str:
        return format_html(
            "{} <small>№{}</small>", getattr(obj, "company_title", "—"), obj.seller_id
        )

    @admin.display(description="статус", ordering="status")
    def state(self, obj: Supply) -> str:
        return format_html(
            "{}<br><small>{}</small>",
            _badge(
                warehouse.SUPPLY_STATUSES.get(obj.status, obj.status),
                _SUPPLY_TONES.get(obj.status, "gray"),
            ),
            obj.reject_reason or "",
        )

    @admin.display(description="строк")
    def lines(self, obj: Supply) -> int:
        found = one("select count(*) as n from market_supply_items where supply_id = %s", [obj.pk])

        return int(found["n"]) if found else 0

    @admin.display(description="ожидается", ordering="expected_at")
    def expected(self, obj: Supply) -> str:
        return obj.expected_at.strftime("%d.%m.%Y") if obj.expected_at else "—"

    @admin.display(description="отправлена", ordering="submitted_at")
    def sent(self, obj: Supply) -> str:
        return _at(obj.submitted_at)

    @admin.display(description="состав")
    def items(self, obj: Supply) -> str:
        return format_html_join(
            "<br>",
            "{} <small>({}, вариант №{})</small> — заявлено {}{}",
            (
                (
                    item["title"],
                    _options(item["options"]),
                    item["variant_id"],
                    item["quantity_declared"],
                    ""
                    if item["quantity_accepted"] is None
                    else f", принято {item['quantity_accepted']}, брак {item['quantity_defect']}",
                )
                for item in self._items(obj)
            ),
        )

    @admin.display(description="шаги")
    def steps(self, obj: Supply) -> str:
        return format_html(
            "заведена {} · отправлена {} · принята {} ({}) · отказ {} · отменена {}",
            _at(obj.created_at),
            _at(obj.submitted_at),
            _at(obj.received_at),
            _staff_name(obj.received_by),
            _at(obj.rejected_at),
            _at(obj.cancelled_at),
        )


# ── Отгрузки ────────────────────────────────────────────────────────


class ShipmentStatus(admin.SimpleListFilter):
    title = "статус"
    parameter_name = "status"

    def lookups(self, request: HttpRequest, model_admin: Any) -> list[tuple[str, str]]:  # noqa: ANN401
        return list(warehouse.SHIPMENT_STATUSES.items())

    def queryset(self, request: HttpRequest, queryset: QuerySet[Any]) -> QuerySet[Any]:
        return queryset.filter(status=self.value()) if self.value() else queryset


class ShipmentForm(forms.ModelForm):  # type: ignore[type-arg]
    """Новая отгрузка: склад и пункт — только свои; заказы подберёт сама."""

    class Meta:
        model = Shipment
        fields = ("warehouse", "pickup_point")

    def __init__(self, *args: Any, place: warehouse.Places, direction: str, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.place = place
        self.direction = direction
        stores = Warehouse.objects.filter(is_active=True)
        points = PickupPoint.objects.all()

        if not place.everything:
            if direction == "to_point":
                stores = stores.filter(pk__in=place.warehouses)
            else:
                points = points.filter(pk__in=place.points)

        self.fields["warehouse"].queryset = stores  # type: ignore[attr-defined]
        self.fields["pickup_point"].queryset = points  # type: ignore[attr-defined]

    def clean(self) -> dict[str, Any]:
        data = super().clean() or {}
        store, point = data.get("warehouse"), data.get("pickup_point")

        if (
            store is not None
            and point is not None
            and not warehouse._candidates(store.pk, point.pk, self.direction)
        ):
            raise forms.ValidationError(
                "Отправлять нечего: нет собранных заказов этого пункта с товаром на складе."
                if self.direction == "to_point"
                else "Отправлять нечего: невостребованных заказов этого склада в пункте нет."
            )

        return data


class _ShipmentBase(_Actions):
    """
    Общее отгрузок. «Отправитель» собирает, отправляет, отменяет и убирает
    заказы; «получатель» принимает. В пункт отправитель — склад, получатель
    — пункт; обратно (невостребованные) — наоборот.
    """

    #: Какое направление эта сторона заводит (отправитель)
    sends: ClassVar[str]
    section_name: ClassVar[str]

    list_display = ("number", "route", "state", "orders_count", "created")
    list_filter = (ShipmentStatus, "direction")
    search_fields = ("number",)
    ordering = ("-created_at", "-id")
    list_per_page = 50
    list_select_related = ("warehouse", "pickup_point")

    fields = ("number", "route", "state", "contents", "steps")
    readonly_fields = fields

    def mine(self, place: warehouse.Places, obj: Shipment) -> bool:
        raise NotImplementedError

    def has_add_permission(self, request: HttpRequest) -> bool:
        return _admin_of(request).can(self.act_ability)

    def get_form(
        self,
        request: HttpRequest,
        obj: Any = None,  # noqa: ANN401
        change: bool = False,
        **kwargs: Any,
    ) -> Any:  # noqa: ANN401
        if obj is not None:
            return super().get_form(request, obj, change, **kwargs)

        place, direction = places(request), self.sends

        class Bound(ShipmentForm):
            def __init__(self, *args: Any, **inner: Any) -> None:
                super().__init__(*args, place=place, direction=direction, **inner)

        return Bound

    def get_fields(self, request: HttpRequest, obj: Any = None) -> Any:  # noqa: ANN401
        return self.fields if obj is not None else ("warehouse", "pickup_point")

    def get_readonly_fields(self, request: HttpRequest, obj: Any = None) -> Any:  # noqa: ANN401
        return self.readonly_fields if obj is not None else ()

    def save_model(self, request: HttpRequest, obj: Shipment, form: Any, change: bool) -> None:  # noqa: ANN401
        """Отгрузку заводит warehouse.shipment_create — сразу с заказами."""
        shipment_id, number, count = warehouse.shipment_create(
            form.cleaned_data["warehouse"].pk,
            form.cleaned_data["pickup_point"].pk,
            self.sends,
            actor_user_id=_admin_of(request).id,
        )
        obj.pk, obj.number = shipment_id, number
        _record(
            request,
            self.section_name,
            "created",
            "Shipment",
            shipment_id,
            number,
            f"{warehouse.DIRECTIONS[self.sends]}, заказов: {count}",
        )

    def save_related(
        self,
        request: HttpRequest,
        form: Any,  # noqa: ANN401
        formsets: list[Any],
        change: bool,
    ) -> None:
        """Строка журнала — в save_model: запись завела не Django."""
        return None

    def action_forms(self, request: HttpRequest, obj: Shipment) -> list[dict[str, Any]]:
        if not self.mine(places(request), obj):
            return []

        found: list[dict[str, Any]] = []

        if obj.direction == self.sends and obj.status == "assembling":
            found.append(
                {
                    "code": "ship",
                    "title": "Отправить",
                    "help": "Отгрузка уехала: заказы — «в пути». Отменённые за это время "
                    "заказы уберутся сами.",
                    "button": "Отгрузка уехала",
                    "fields": [],
                }
            )
            found += [
                {
                    "code": f"remove:{order['id']}",
                    "title": f"Заказ {order['number']}",
                    "help": "Убрать из отгрузки — поедет следующей.",
                    "button": "Убрать заказ",
                    "fields": [],
                }
                for order in warehouse.shipment_orders(obj.pk)
            ]
            found.append(
                {
                    "code": "cancel",
                    "title": "Отменить отгрузку",
                    "help": "Заказы освободятся для следующей отгрузки.",
                    "button": "Отменить отгрузку",
                    "fields": [],
                }
            )

        if obj.direction != self.sends and obj.status == "in_transit":
            found.append(
                {
                    "code": "deliver",
                    "title": "Приёмка отгрузки",
                    "help": "Отгрузка на месте: заказы — «можно забрать», покупателям — "
                    "уведомление с адресом и часами."
                    if obj.direction == "to_point"
                    else "Невостребованные вернулись на склад.",
                    "button": "Отгрузку приняли",
                    "fields": [],
                }
            )

        return found

    def act(self, request: HttpRequest, obj: Shipment, code: str) -> str:
        actor = _admin_of(request).id

        if code == "ship":
            count = warehouse.shipment_ship(obj.pk, actor_user_id=actor)
            done, action = f"Отгрузка {obj.number} уехала: заказов {count}.", "shipped"
        elif code == "deliver":
            count = warehouse.shipment_deliver(obj.pk, actor_user_id=actor)
            done, action = f"Отгрузка {obj.number} принята: заказов {count}.", "delivered"
        elif code == "cancel":
            warehouse.shipment_cancel(obj.pk, actor_user_id=actor)
            done, action = f"Отгрузка {obj.number} отменена.", "cancelled"
        else:
            order_id = int(code.removeprefix("remove:"))
            warehouse.shipment_remove(obj.pk, order_id)
            done, action = f"Заказ убран из отгрузки {obj.number}.", "updated"

        _record(request, self.section_name, action, "Shipment", obj.pk, obj.number, code)

        return done

    @admin.display(description="маршрут", ordering="direction")
    def route(self, obj: Shipment) -> str:
        store, point = obj.warehouse.name, obj.pickup_point.name

        return f"{store} → {point}" if obj.direction == "to_point" else f"{point} → {store}"

    @admin.display(description="статус", ordering="status")
    def state(self, obj: Shipment) -> str:
        return _badge(
            warehouse.SHIPMENT_STATUSES.get(obj.status, obj.status),
            _SHIPMENT_TONES.get(obj.status, "gray"),
        )

    @admin.display(description="заказов")
    def orders_count(self, obj: Shipment) -> int:
        found = one(
            "select count(*) as n from market_shipment_orders where shipment_id = %s", [obj.pk]
        )

        return int(found["n"]) if found else 0

    @admin.display(description="заведена", ordering="created_at")
    def created(self, obj: Shipment) -> str:
        return _at(obj.created_at)

    @admin.display(description="заказы")
    def contents(self, obj: Shipment) -> str:
        found = warehouse.shipment_orders(obj.pk)

        if not found:
            return "—"

        return format_html_join(
            "<br>",
            "{} — {}",
            (
                (order["number"], orders.STATUSES.get(order["status"], order["status"]))
                for order in found
            ),
        )

    @admin.display(description="шаги")
    def steps(self, obj: Shipment) -> str:
        return format_html(
            "собрал {} · уехала {} ({}) · принята {} ({}) · отменена {}",
            _staff_name(obj.created_by),
            _at(obj.shipped_at),
            _staff_name(obj.shipped_by),
            _at(obj.delivered_at),
            _staff_name(obj.delivered_by),
            _at(obj.cancelled_at),
        )


@register(Shipment, section="market_stock")
class ShipmentAdmin(_ShipmentBase):
    """Склад: собирает и отправляет в пункты, принимает невостребованные."""

    laravel_model = "Savdex\\Market\\Shipment"
    title_list = "Отгрузки склада"
    title_add = "Новая отгрузка в пункт выдачи"
    title_change = "Отгрузка"
    act_ability = STOCK_ABILITY
    sends = "to_point"
    section_name = "market_stock"

    def mine(self, place: warehouse.Places, obj: Shipment) -> bool:
        return place.warehouse(obj.warehouse_id)

    def get_queryset(self, request: HttpRequest) -> QuerySet[Shipment]:
        found: QuerySet[Shipment] = super().get_queryset(request)
        place = places(request)

        return found if place.everything else found.filter(warehouse_id__in=place.warehouses)


@register(PointShipment, section="market_pickup")
class PointShipmentAdmin(_ShipmentBase):
    """Пункт: принимает отгрузки со склада, отправляет невостребованные обратно."""

    laravel_model = "Savdex\\Market\\Shipment"
    title_list = "Отгрузки пункта выдачи"
    title_add = "Невостребованные — на склад"
    title_change = "Отгрузка"
    act_ability = PICKUP_ABILITY
    sends = "to_warehouse"
    section_name = "market_pickup"

    def mine(self, place: warehouse.Places, obj: Shipment) -> bool:
        return place.point(obj.pickup_point_id)

    def get_queryset(self, request: HttpRequest) -> QuerySet[PointShipment]:
        found: QuerySet[PointShipment] = super().get_queryset(request)
        place = places(request)

        return found if place.everything else found.filter(pickup_point_id__in=place.points)


# ── Движения остатка ────────────────────────────────────────────────


class MovementForm(forms.ModelForm):  # type: ignore[type-arg]
    """Ручное движение: списание, вывоз продавцу, инвентаризация — с причиной."""

    variant_number = forms.IntegerField(
        label="вариант №", min_value=1, help_text="Номер варианта — в карточке склада и товара."
    )
    manual_kind = forms.ChoiceField(
        label="движение",
        choices=[(kind, warehouse.KINDS[kind][0]) for kind in warehouse.MANUAL_KINDS],
    )
    amount = forms.IntegerField(
        label="штук",
        help_text="Списание и вывоз — сколько штук ушло (положительным числом); "
        "инвентаризация — на сколько поправить: «-2» — недостача, «3» — излишек.",
    )
    why = forms.CharField(label="причина", max_length=500, widget=forms.Textarea(attrs={"rows": 2}))

    class Meta:
        model = StockMovement
        fields = ("warehouse",)

    def __init__(self, *args: Any, place: warehouse.Places, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.place = place
        stores = Warehouse.objects.all()

        # Списание — только администратор (подтверждает второй человек)
        if not place.everything:
            kind: Any = self.fields["manual_kind"]
            kind.choices = [c for c in kind.choices if c[0] != "writeoff"]
            kind.help_text = "Списание — через администратора маркетплейса."

        if not place.everything:
            stores = stores.filter(pk__in=place.warehouses)

        self.fields["warehouse"].queryset = stores  # type: ignore[attr-defined]

    def clean(self) -> dict[str, Any]:
        """Заранее — то же, что проверит база: не в минус на складе и не ниже резерва."""
        data = super().clean() or {}
        store, variant = data.get("warehouse"), data.get("variant_number")
        kind, amount = data.get("manual_kind"), data.get("amount")

        if store is None or variant is None or kind is None or amount is None:
            return data

        if len(str(data.get("why") or "").strip()) < warehouse.MIN_REASON:
            raise forms.ValidationError("Напишите причину движения.")

        if amount == 0 or (kind != "adjust" and amount < 0):
            raise forms.ValidationError("Штук — не ноль; списание и вывоз — положительным числом.")

        delta = amount if kind == "adjust" else -amount
        found = one(
            "select v.stock, v.reserved, coalesce((select s.quantity from market_warehouse_stock s "
            " where s.warehouse_id = %s and s.variant_id = v.id), 0) as here "
            "from market_product_variants v where v.id = %s",
            [store.pk, variant],
        )

        if found is None:
            raise forms.ValidationError("Такого варианта товара нет.")

        if delta < 0 and (
            int(found["here"]) + delta < 0 or int(found["stock"]) + delta < int(found["reserved"])
        ):
            raise forms.ValidationError(
                f"Столько не списать: на этом складе {found['here']} шт., "
                f"отложено под заказы {found['reserved']} шт."
            )

        return data


@register(StockMovement, section="market_stock")
class StockMovementAdmin(SavdexModelAdmin):
    """Движения остатка своих складов: журнал и ручные движения с причиной."""

    laravel_model = "Savdex\\Market\\StockMovement"
    title_list = "Движения остатка"
    title_add = "Списание, вывоз продавцу или инвентаризация"
    title_change = "Движение остатка"

    list_display = ("created", "warehouse", "item", "kind_text", "quantity", "basis", "actor")
    list_filter = ("kind", "warehouse")
    search_fields = ("product__title",)
    ordering = ("-id",)
    list_per_page = 100
    list_select_related = ("warehouse", "product", "variant")

    fields = ("created", "warehouse", "item", "kind_text", "quantity", "basis", "actor")
    readonly_fields = fields

    def get_queryset(self, request: HttpRequest) -> QuerySet[StockMovement]:
        found: QuerySet[StockMovement] = super().get_queryset(request)
        place = places(request)

        return found if place.everything else found.filter(warehouse_id__in=place.warehouses)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return _admin_of(request).can(STOCK_ABILITY)

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:  # noqa: ANN401
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:  # noqa: ANN401
        return False

    def get_form(
        self,
        request: HttpRequest,
        obj: Any = None,  # noqa: ANN401
        change: bool = False,
        **kwargs: Any,
    ) -> Any:  # noqa: ANN401
        if obj is not None:
            return super().get_form(request, obj, change, **kwargs)

        place = places(request)

        class Bound(MovementForm):
            def __init__(self, *args: Any, **inner: Any) -> None:
                super().__init__(*args, place=place, **inner)

        return Bound

    def get_fields(self, request: HttpRequest, obj: Any = None) -> Any:  # noqa: ANN401
        if obj is not None:
            return self.fields

        return ("warehouse", "variant_number", "manual_kind", "amount", "why")

    def get_readonly_fields(self, request: HttpRequest, obj: Any = None) -> Any:  # noqa: ANN401
        return self.readonly_fields if obj is not None else ()

    def save_model(self, request: HttpRequest, obj: StockMovement, form: Any, change: bool) -> None:  # noqa: ANN401
        data = form.cleaned_data
        obj.pk = warehouse.manual_move(
            data["warehouse"].pk,
            int(data["variant_number"]),
            data["manual_kind"],
            int(data["amount"]),
            data["why"],
            actor_user_id=_admin_of(request).id,
            confirmed=form.place.everything,
        )
        _record(
            request,
            "market_stock",
            "created",
            "StockMovement",
            obj.pk,
            f"{warehouse.KINDS[data['manual_kind']][0]}: вариант №{data['variant_number']}",
            str(data["why"]).strip()[:500],
            {"after": {"quantity": int(data["amount"]), "warehouse": data["warehouse"].code}},
        )

    def save_related(
        self,
        request: HttpRequest,
        form: Any,  # noqa: ANN401
        formsets: list[Any],
        change: bool,
    ) -> None:
        """Строка журнала — в save_model: движение записала не Django."""
        return None

    @admin.display(description="когда", ordering="id")
    def created(self, obj: StockMovement) -> str:
        return _at(obj.created_at)

    @admin.display(description="товар")
    def item(self, obj: StockMovement) -> str:
        return format_html(
            "{} <small>({}, вариант №{})</small>",
            obj.product.title,
            _options(obj.variant.options),
            obj.variant_id,
        )

    @admin.display(description="движение", ordering="kind")
    def kind_text(self, obj: StockMovement) -> str:
        return warehouse.KINDS.get(obj.kind, (obj.kind, 0))[0]

    @admin.display(description="основание")
    def basis(self, obj: StockMovement) -> str:
        if obj.order_id:
            found = one("select number from market_orders where id = %s", [obj.order_id])

            return f"заказ {found['number']}" if found else f"заказ №{obj.order_id}"

        if obj.supply_item_id:
            found = one(
                "select s.number from market_supply_items i join market_supplies s "
                "on s.id = i.supply_id where i.id = %s",
                [obj.supply_item_id],
            )

            return f"поставка {found['number']}" if found else "поставка"

        return obj.reason or "—"

    @admin.display(description="кто")
    def actor(self, obj: StockMovement) -> str:
        return _staff_name(obj.actor_user_id)


# ── Пункт выдачи: заказы ────────────────────────────────────────────


class PointOrderStatus(admin.SimpleListFilter):
    title = "статус"
    parameter_name = "status"

    def lookups(self, request: HttpRequest, model_admin: Any) -> list[tuple[str, str]]:  # noqa: ANN401
        return [
            (code, orders.STATUSES[code])
            for code in (orders.IN_TRANSIT, orders.READY, orders.ISSUED, orders.CANCELLED)
        ]

    def queryset(self, request: HttpRequest, queryset: QuerySet[Any]) -> QuerySet[Any]:
        return queryset.filter(status=self.value()) if self.value() else queryset


@register(PointOrder, section="market_pickup")
class PointOrderAdmin(_Actions):
    """
    Заказы своего пункта, которые до него доехали или едут: выдать по коду.
    Сумм нет — кроме «к оплате» у заказов при получении: её пункт берёт с
    покупателя.
    """

    laravel_model = "Savdex\\Market\\Order"
    title_list = "Заказы в пункте выдачи"
    title_change = "Заказ в пункте"
    act_ability = PICKUP_ABILITY

    #: Имени и телефона покупателя пункт не видит (ТЗ «Склад маркетплейса»):
    #: заказ — по номеру с наклейки и коду покупателя
    list_display = ("number", "state", "to_pay", "ready")
    list_filter = (PointOrderStatus, "pickup_point")
    search_fields = ("number",)
    ordering = ("-ready_at", "-id")
    list_per_page = 50

    fields = ("number", "state", "point", "to_pay", "contents", "ready", "issued")
    readonly_fields = fields

    def get_queryset(self, request: HttpRequest) -> QuerySet[PointOrder]:
        found: QuerySet[PointOrder] = (
            super()
            .get_queryset(request)
            .filter(
                status__in=(
                    orders.IN_TRANSIT,
                    orders.READY,
                    orders.ISSUED,
                    orders.CANCELLED,
                    orders.REFUND_PENDING,
                    orders.REFUNDED,
                )
            )
            .exclude(
                status__in=(orders.CANCELLED, orders.REFUND_PENDING, orders.REFUNDED), ready_at=None
            )
        )
        place = places(request)

        if not place.everything:
            found = found.filter(pickup_point_id__in=place.points)

        return found

    def action_forms(self, request: HttpRequest, obj: PointOrder) -> list[dict[str, Any]]:
        if obj.status != orders.READY:
            return []

        pay = (
            f" Возьмите с покупателя {_money(obj.total)}."
            if obj.payment_method == "cash"
            else " Заказ оплачен картой."
        )

        return [
            {
                "code": "issue",
                "title": "Выдача по коду",
                "help": "Покупатель называет 6 цифр из своего заказа. После "
                f"{warehouse.CODE_ATTEMPTS} неверных подряд — пауза "
                f"{warehouse.CODE_LOCK_MINUTES} минут." + pay,
                "button": "Выдать заказ",
                "fields": [{"name": "code", "label": "Код выдачи", "type": "code"}],
            },
            {
                "code": "refuse",
                "title": "Отказ при получении",
                "help": "Покупатель отказался от заказа (только целиком). Оплаченный "
                "картой — к возврату денег; заказ поедет на склад с невостребованными.",
                "button": "Покупатель отказался",
                "fields": [],
            },
        ]

    def act(self, request: HttpRequest, obj: PointOrder, code: str) -> str | None:
        if code == "refuse":
            after = warehouse.refuse(obj.pk, actor_user_id=_admin_of(request).id)

            if after is None:
                raise warehouse.WarehouseError("Заказ уже не ждёт выдачи — обновите страницу.")

            _record(
                request,
                "market_pickup",
                "cancelled",
                "Order",
                obj.pk,
                obj.number,
                "отказ при получении",
                {"before": {"status": orders.READY}, "after": {"status": after}},
            )

            return f"Заказ {obj.number}: отказ при получении — {orders.STATUSES[after]}."

        try:
            result = warehouse.issue(
                obj.pk, request.POST.get("code") or "", actor_user_id=_admin_of(request).id
            )
        except orders.WriteOffError as error:
            raise warehouse.WarehouseError(
                "Заказ не выдан: на складе нет товара под этот заказ — напишите складу."
            ) from error

        if result == "issued":
            _record(
                request,
                "market_pickup",
                "status_changed",
                "Order",
                obj.pk,
                obj.number,
                changes={"before": {"status": orders.READY}, "after": {"status": orders.ISSUED}},
            )

            return f"Заказ {obj.number} выдан."

        # Неверная попытка должна остаться записанной: сообщение — не
        # исключением (оно откатило бы транзакцию act_view). Каждая
        # неудачная попытка — строка журнала действий (без самого кода)
        if result in ("wrong", "locked", "staff_limit"):
            _record(
                request, "market_pickup", "pickup_code_failed", "Order", obj.pk, obj.number, result
            )

        if result == "wrong":
            self.message_user(request, "Код неверный — проверьте с покупателем.", messages.ERROR)
        elif result == "locked":
            self.message_user(
                request,
                "Слишком много неверных кодов: ввод по заказу на паузе "
                f"{warehouse.CODE_LOCK_MINUTES} минут. Открыть раньше может администратор.",
                messages.ERROR,
            )
        elif result == "staff_limit":
            self.message_user(
                request,
                "Слишком много неверных кодов за час — подождите и проверьте номер заказа.",
                messages.ERROR,
            )
        else:
            self.message_user(
                request, "Заказ уже не ждёт выдачи — обновите страницу.", messages.WARNING
            )

        return None

    @admin.display(description="статус", ordering="status")
    def state(self, obj: PointOrder) -> str:
        return orders.STATUSES.get(obj.status, obj.status)

    @admin.display(description="пункт")
    def point(self, obj: PointOrder) -> str:
        return obj.pickup_point_name

    @admin.display(description="к оплате")
    def to_pay(self, obj: PointOrder) -> str:
        return _money(obj.total) if obj.payment_method == "cash" else "оплачен картой"

    @admin.display(description="пришёл", ordering="ready_at")
    def ready(self, obj: PointOrder) -> str:
        return _at(obj.ready_at)

    @admin.display(description="выдан")
    def issued(self, obj: PointOrder) -> str:
        return f"{_at(obj.issued_at)} · {_staff_name(obj.issued_by)}" if obj.issued_at else "—"

    @admin.display(description="состав")
    def contents(self, obj: PointOrder) -> str:
        return format_html_join(
            "<br>",
            "{} — {} шт.",
            (
                (r["title"], r["quantity"])
                for r in rows(
                    "select title, quantity from market_order_items where order_id = %s "
                    "order by id",
                    [obj.pk],
                )
            ),
        )
