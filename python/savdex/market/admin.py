"""
Раздел админки «Маркетплейс» (ТЗ, раздел 9): продавцы, товары, категории.

- **Продавцы** (право market.*): очередь заявок «Стать продавцом».
  Модератор видит компанию, её ИНН и статус документов проверки (сами
  документы — в разделе «Документы на проверку»), подтверждает или
  отклоняет с причиной, может приостановить продажи и вернуть их.
- **Товары** (market.*): очередь модерации первых товаров новых
  продавцов; одобрить, отклонить с причиной, снять любой товар (ТЗ:
  «модератор может снять любой товар»). Пока склада BTS в коде нет,
  остаток вариантов ставят здесь (право market.edit); появится склад —
  остаток будет приходить с приёмки, а это поле станет только для чтения.
- **Категории** (market_catalog.*): дерево до трёх уровней,
  характеристики для фильтров. Удалить можно только пустую категорию.

Каждое решение — строка журнала действий и уведомление компании.
Денег в разделе нет: модератор их не видит (ТЗ, раздел 9).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any, ClassVar

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.db.models import Count, OuterRef, QuerySet, Subquery
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.urls import path, reverse
from django.utils.html import format_html, format_html_join

from savdex import audit
from savdex.adminsite import SavdexModelAdmin, _admin_of, register
from savdex.crm.admin import _badge, when
from savdex.market import products, sellers
from savdex.market.common import t
from savdex.market.models import Attribute, Category, Product, Seller, Variant
from savdex.moderation.services import context_of, notify_company
from savdex.web.shared import public_url

#: Причина отказа — не отписка: её дословно увидит компания
MIN_NOTE = 10

#: Глубина дерева категорий: раздел → подраздел → вид
MAX_DEPTH = 3

SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
KEY = re.compile(r"[a-z][a-z0-9_]{0,39}")

_TONES = {
    "pending": "warning",
    "approved": "success",
    "active": "success",
    "rejected": "danger",
    "blocked": "danger",
    "draft": "gray",
    "hidden": "gray",
}


def _journal(
    request: HttpRequest, action: str, section: str, model: str, pk: int, label: str, note: str
) -> None:
    audit.record(
        connection,
        action=action,
        section=section,
        actor=_admin_of(request),
        subject_type=f"Savdex\\Market\\{model}",
        subject_id=pk,
        subject_label=label,
        note=note or None,
        ip=audit.client_ip(request),
    )


def _company(company_id: int) -> dict[str, Any] | None:
    with connection.cursor() as cursor:
        cursor.execute(
            "select id, name, slug, tin, verification_level, status from companies where id = %s",
            [company_id],
        )
        row = cursor.fetchone()

    if row is None:
        return None

    return dict(
        zip(("id", "name", "slug", "tin", "verification_level", "status"), row, strict=True)
    )


def _notify(
    request: HttpRequest, company_id: int, key: str, tone: str, body: str | None, **replace: Any
) -> None:
    notify_company(
        context_of(request),
        company_id,
        "moderation",
        lambda locale: t(f"notify.{key}", locale, **replace),
        tone,
        "/cabinet",
        body,
    )


class DecisionsMixin:
    """Кнопки решений под карточкой — общая панель модерации."""

    change_form_template: Any = "admin/market/change_form.html"
    #: Право на решения
    decide_ability: ClassVar[str] = "market.moderate"
    decide_url_name: ClassVar[str] = ""

    def decisions(self, obj: Any) -> list[tuple[str, str, bool]]:  # noqa: ANN401
        raise NotImplementedError

    def decide(self, request: HttpRequest, obj: Any, decision: str, note: str) -> str:  # noqa: ANN401
        raise NotImplementedError

    def get_urls(self) -> list[Any]:
        return [
            path(
                "<path:object_id>/decide/",
                self.admin_site.admin_view(self.decide_view),  # type: ignore[attr-defined]
                name=self.decide_url_name,
            ),
            *super().get_urls(),  # type: ignore[misc]
        ]

    def decide_view(self, request: HttpRequest, object_id: str) -> HttpResponse:
        if request.method != "POST" or not _admin_of(request).can(self.decide_ability):
            raise PermissionDenied

        obj = self.get_object(request, object_id)  # type: ignore[attr-defined]

        if obj is None:
            raise PermissionDenied

        page = reverse(
            f"savdex_admin:{self.decide_url_name.removesuffix('_decide')}_change", args=[obj.pk]
        )
        decision = request.POST.get("decision", "")
        allowed = {code: needs for code, _, needs in self.decisions(obj)}
        note = (request.POST.get("note") or "").strip()

        if decision not in allowed:
            self.message_user(request, "Это решение уже недоступно.", messages.WARNING)  # type: ignore[attr-defined]

            return HttpResponseRedirect(page)

        if allowed[decision] and len(note) < MIN_NOTE:
            self.message_user(  # type: ignore[attr-defined]
                request,
                f"Напишите причину — не короче {MIN_NOTE} знаков: её увидит компания.",
                messages.ERROR,
            )

            return HttpResponseRedirect(page)

        self.message_user(request, self.decide(request, obj, decision, note), messages.SUCCESS)  # type: ignore[attr-defined]

        return HttpResponseRedirect(page)

    def change_view(
        self,
        request: HttpRequest,
        object_id: str,
        form_url: str = "",
        extra_context: Any = None,  # noqa: ANN401
    ) -> HttpResponse:
        obj = self.get_object(request, object_id)  # type: ignore[attr-defined]
        extra = dict(extra_context or {})

        if obj is not None and _admin_of(request).can(self.decide_ability):
            extra["decisions"] = self.decisions(obj)
            extra["min_note"] = MIN_NOTE
            extra["decide_url"] = reverse(f"savdex_admin:{self.decide_url_name}", args=[obj.pk])

        return super().change_view(request, object_id, form_url, extra)  # type: ignore[misc, no-any-return]


# ── Продавцы ────────────────────────────────────────────────────────


class SellerStatus(admin.SimpleListFilter):
    title = "статус"
    parameter_name = "status"

    def lookups(self, request: HttpRequest, model_admin: Any) -> list[tuple[str, str]]:  # noqa: ANN401
        return list(sellers.STATUSES.items())

    def queryset(self, request: HttpRequest, queryset: QuerySet[Any]) -> QuerySet[Any]:
        return queryset.filter(status=self.value()) if self.value() else queryset


def _company_name() -> Subquery:
    from savdex.data.models import CompanyRecord

    return Subquery(CompanyRecord.objects.filter(pk=OuterRef("company_id")).values("name")[:1])


@register(Seller, section="market")
class SellerAdmin(DecisionsMixin, SavdexModelAdmin):
    laravel_model = "Savdex\\Market\\Seller"
    title_list = "Продавцы маркетплейса"
    title_change = "Заявка продавца"
    decide_url_name = "market_seller_decide"

    list_display = ("company", "state", "documents", "applied")
    list_filter = (SellerStatus,)
    search_fields = ("company_title",)
    ordering = ("-created_at", "-id")
    list_per_page = 50

    fields = (
        "company",
        "tin",
        "state",
        "documents",
        "note",
        "offer",
        "applied",
        "decided",
    )
    readonly_fields = fields

    def get_queryset(self, request: HttpRequest) -> QuerySet[Seller]:
        queryset: QuerySet[Seller] = super().get_queryset(request)

        return queryset.annotate(company_title=_company_name())

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:  # noqa: ANN401
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:  # noqa: ANN401
        return False

    @admin.display(description="компания", ordering="company_title")
    def company(self, obj: Seller) -> str:
        company = _company(obj.company_id)

        if company is None:
            return "—"

        return format_html(
            "{}<br><small>уровень проверки: {}{}</small>",
            company["name"],
            company["verification_level"],
            "" if company["status"] == "active" else " · компания заблокирована",
        )

    @admin.display(description="ИНН")
    def tin(self, obj: Seller) -> str:
        company = _company(obj.company_id)

        return str(company["tin"] or "—") if company else "—"

    @admin.display(description="статус", ordering="status")
    def state(self, obj: Seller) -> str:
        return format_html(
            "{}<br><small>{}</small>",
            _badge(sellers.STATUSES.get(obj.status, obj.status), _TONES.get(obj.status, "gray")),
            obj.reject_reason or "",
        )

    @admin.display(description="документы проверки")
    def documents(self, obj: Seller) -> str:
        found = sellers.documents_of(obj.company_id)

        if not found:
            return _badge("нет", "danger")

        labels = {"approved": "принят", "rejected": "отклонён", "pending": "ждёт проверки"}

        return format_html_join(
            "<br>",
            "{} — {}",
            (
                (d["title"], labels.get(d["moderation_status"], d["moderation_status"]))
                for d in found
            ),
        )

    @admin.display(description="оферта")
    def offer(self, obj: Seller) -> str:
        if obj.offer_accepted_at is None:
            return "—"

        return f"редакция {obj.offer_version}, {when(obj.offer_accepted_at)}"

    @admin.display(description="заявка", ordering="created_at")
    def applied(self, obj: Seller) -> str:
        return when(obj.created_at)

    @admin.display(description="решение")
    def decided(self, obj: Seller) -> str:
        return when(obj.reviewed_at) or "—"

    def decisions(self, obj: Seller) -> list[tuple[str, str, bool]]:
        return {
            "pending": [("approve", "Подтвердить продавца", False), ("reject", "Отклонить", True)],
            "rejected": [("approve", "Подтвердить продавца", False)],
            "approved": [("block", "Приостановить продажи", True)],
            "blocked": [("unblock", "Вернуть продажи", False)],
        }.get(obj.status, [])

    def decide(self, request: HttpRequest, obj: Seller, decision: str, note: str) -> str:
        staff = _admin_of(request).id
        label = (_company(obj.company_id) or {}).get("name") or str(obj)
        actions: dict[str, tuple[Callable[[], bool], str, str, str | None]] = {
            "approve": (
                lambda: sellers.approve(obj.pk, staff),
                "approved",
                "seller_approved",
                "success",
            ),
            "reject": (
                lambda: sellers.reject(obj.pk, staff, note),
                "rejected",
                "seller_rejected",
                "danger",
            ),
            "block": (
                lambda: sellers.block(obj.pk, staff, note),
                "blocked",
                "seller_blocked",
                "danger",
            ),
            "unblock": (
                lambda: sellers.unblock(obj.pk, staff),
                "unblocked",
                "seller_approved",
                "success",
            ),
        }
        run, action, key, tone = actions[decision]

        if not run():
            return "Статус уже изменился — обновите страницу."

        _journal(request, action, "market", "Seller", obj.pk, label, note)
        _notify(request, obj.company_id, key, tone or "info", note or None)

        return {
            "approve": "Компания стала продавцом.",
            "reject": "Заявка отклонена.",
            "block": "Продажи приостановлены.",
            "unblock": "Продажи возвращены.",
        }[decision]


# ── Товары ──────────────────────────────────────────────────────────


class ProductStatus(admin.SimpleListFilter):
    title = "статус"
    parameter_name = "status"

    def lookups(self, request: HttpRequest, model_admin: Any) -> list[tuple[str, str]]:  # noqa: ANN401
        return list(products.STATUSES.items())

    def queryset(self, request: HttpRequest, queryset: QuerySet[Any]) -> QuerySet[Any]:
        return queryset.filter(status=self.value()) if self.value() else queryset


class VariantInline(admin.TabularInline):  # type: ignore[type-arg]
    """
    Варианты: цена — только смотреть (её задаёт продавец), остаток — до
    появления склада BTS ставит сотрудник.
    """

    model = Variant
    extra = 0
    can_delete = False
    fields = ("title", "sku", "price_label", "stock", "reserved", "is_active")
    readonly_fields = ("title", "sku", "price_label", "reserved", "is_active")

    def get_queryset(self, request: HttpRequest) -> QuerySet[Variant]:
        return super().get_queryset(request).exclude(options__has_key="_removed")

    def has_add_permission(self, request: HttpRequest, obj: Any = None) -> bool:  # noqa: ANN401
        return False

    # Вариант не регистрируется в админке отдельно (своего раздела нет),
    # и проверка Django «market.change_variant» не находила раздела —
    # таблица вариантов не показывалась никому. Права — раздела «market»
    def has_view_permission(self, request: HttpRequest, obj: Any = None) -> bool:  # noqa: ANN401
        return _admin_of(request).can("market.view")

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:  # noqa: ANN401
        return _admin_of(request).can("market.edit")

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:  # noqa: ANN401
        return False

    @admin.display(description="вариант")
    def title(self, obj: Variant) -> str:
        return str(obj)

    @admin.display(description="цена")
    def price_label(self, obj: Variant) -> str:
        from savdex.market.common import som

        price = som(obj.price)
        old = som(obj.old_price)
        text = f"{price:,}".replace(",", " ") + " сум"

        return f"{text} (было {old:,})".replace(",", " ") if old else text


@register(Product, section="market")
class ProductAdmin(DecisionsMixin, SavdexModelAdmin):
    laravel_model = "Savdex\\Market\\Product"
    title_list = "Товары маркетплейса"
    title_change = "Товар"
    decide_url_name = "market_product_decide"

    list_display = ("name", "seller_name", "category", "state", "price_text", "stock", "changed")
    list_filter = (ProductStatus, "category")
    list_select_related = ("category",)
    search_fields = ("title", "ikpu", "barcode")
    ordering = ("-updated_at", "-id")
    list_per_page = 50
    inlines = (VariantInline,)

    fields = (
        "name",
        "seller_name",
        "category",
        "state",
        "photos",
        "description",
        "specs",
        "ikpu",
        "barcode",
        "sizes",
        "price_text",
        "stock",
        "dates",
    )
    readonly_fields = fields

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:  # noqa: ANN401
        return False

    def save_related(
        self,
        request: HttpRequest,
        form: Any,  # noqa: ANN401
        formsets: list[Any],
        change: bool,
    ) -> None:
        """Остатки вариантов сохранены — сводка товара заново, строка журнала."""
        before = {v.pk: v.stock for v in Variant.objects.filter(product=form.instance)}
        super().save_related(request, form, formsets, change)
        products.refresh(form.instance.pk)
        after = {v.pk: v.stock for v in Variant.objects.filter(product=form.instance)}
        changed = {str(k): v for k, v in after.items() if before.get(k) != v}

        if changed:
            audit.record(
                connection,
                action="updated",
                section="market",
                actor=_admin_of(request),
                subject_type=self.laravel_model,
                subject_id=form.instance.pk,
                subject_label=form.instance.title,
                changes={
                    "before": {k: before.get(int(k)) for k in changed},
                    "after": changed,
                },
                note="остаток вариантов",
                ip=audit.client_ip(request),
            )

    @admin.display(description="товар", ordering="title")
    def name(self, obj: Product) -> str:
        if obj.slug and obj.status == "active":
            return format_html("{}<br><small>/market/product/{}</small>", obj.title, obj.slug)

        return obj.title

    @admin.display(description="продавец")
    def seller_name(self, obj: Product) -> str:
        company = _company(obj.seller.company_id)

        return company["name"] if company else "—"

    @admin.display(description="статус", ordering="status")
    def state(self, obj: Product) -> str:
        return format_html(
            "{}<br><small>{}</small>",
            _badge(products.STATUSES.get(obj.status, obj.status), _TONES.get(obj.status, "gray")),
            obj.reject_reason or "",
        )

    @admin.display(description="цена", ordering="price")
    def price_text(self, obj: Product) -> str:
        return obj.price_label()

    @admin.display(description="изменён", ordering="updated_at")
    def changed(self, obj: Product) -> str:
        return when(obj.updated_at)

    @admin.display(description="фото")
    def photos(self, obj: Product) -> str:
        with connection.cursor() as cursor:
            cursor.execute(
                "select i.path, coalesce(i.thumb_path, i.path), v.options "
                "from market_product_images i "
                "left join market_product_variants v on v.id = i.variant_id "
                "where i.product_id = %s order by i.sort, i.id",
                [obj.pk],
            )
            found = cursor.fetchall()

        if not found:
            return "нет"

        def whose(options: Any) -> str:  # noqa: ANN401
            if options is None:
                return "общее"

            values = json.loads(options) if isinstance(options, str) else options

            return ", ".join(str(v) for k, v in values.items() if not str(k).startswith("_"))

        return format_html_join(
            " ",
            '<a href="{0}" target="_blank" rel="noopener" title="{2}">'
            '<img src="{1}" alt="{2}" height="96"></a>',
            (
                (public_url(path), public_url(thumb), whose(options))
                for path, thumb, options in found
            ),
        )

    @admin.display(description="характеристики")
    def specs(self, obj: Product) -> str:
        from savdex.market.catalog import _value_text, attributes_for

        attributes = {a["id"]: a for a in attributes_for(obj.category_id)}

        with connection.cursor() as cursor:
            cursor.execute(
                "select attribute_id, value_text, value_number from market_product_values "
                "where product_id = %s",
                [obj.pk],
            )
            values = [
                dict(zip(("attribute_id", "value_text", "value_number"), r, strict=True))
                for r in cursor.fetchall()
            ]

        pairs = [
            (
                attributes[v["attribute_id"]]["name"],
                _value_text(v, attributes[v["attribute_id"]], "ru"),
            )
            for v in values
            if v["attribute_id"] in attributes
        ]

        return format_html_join("<br>", "{}: {}", pairs) if pairs else "—"

    @admin.display(description="вес и габариты")
    def sizes(self, obj: Product) -> str:
        weight = f"{obj.weight_g} г" if obj.weight_g else "вес не указан"
        dims = (
            f"{obj.length_mm}×{obj.width_mm}×{obj.height_mm} мм"
            if obj.length_mm and obj.width_mm and obj.height_mm
            else "габариты не указаны"
        )

        return f"{weight}, {dims}"

    @admin.display(description="даты")
    def dates(self, obj: Product) -> str:
        return format_html(
            "создан {}<br>отправлен {}<br>в продаже с {}<br>решение {}",
            when(obj.created_at) or "—",
            when(obj.submitted_at) or "—",
            when(obj.published_at) or "—",
            when(obj.moderated_at) or "—",
        )

    def decisions(self, obj: Product) -> list[tuple[str, str, bool]]:
        found: list[tuple[str, str, bool]] = []

        if obj.status == "pending":
            found += [("approve", "Одобрить — в продажу", False), ("reject", "Отклонить", True)]

        if obj.status == "blocked":
            found.append(("unblock", "Вернуть продавцу в черновик", False))
        else:
            found.append(("block", "Снять с продажи", True))

        return found

    def decide(self, request: HttpRequest, obj: Product, decision: str, note: str) -> str:
        staff = _admin_of(request).id
        actions: dict[str, tuple[Callable[[], bool], str, str | None, str]] = {
            "approve": (
                lambda: products.approve(obj.pk, staff),
                "approved",
                "product_approved",
                "success",
            ),
            "reject": (
                lambda: products.reject(obj.pk, staff, note),
                "rejected",
                "product_rejected",
                "danger",
            ),
            "block": (
                lambda: products.block(obj.pk, staff, note),
                "blocked",
                "product_blocked",
                "danger",
            ),
            "unblock": (lambda: products.unblock(obj.pk, staff), "unblocked", None, "info"),
        }
        run, action, key, tone = actions[decision]

        if not run():
            return "Статус уже изменился — обновите страницу."

        _journal(request, action, "market", "Product", obj.pk, obj.title, note)

        if key is not None:
            _notify(request, obj.seller.company_id, key, tone, note or None, title=obj.title)

        return {
            "approve": "Товар в продаже.",
            "reject": "Товар отклонён.",
            "block": "Товар снят с продажи.",
            "unblock": "Товар возвращён продавцу в черновик.",
        }[decision]


# ── Категории ───────────────────────────────────────────────────────


class CategoryForm(forms.ModelForm):  # type: ignore[type-arg]
    name_uz = forms.CharField(label="название по-узбекски", max_length=120, required=False)
    name_en = forms.CharField(label="название по-английски", max_length=120, required=False)

    class Meta:
        model = Category
        fields = ("parent", "slug", "name", "icon", "sort", "is_active")
        help_texts: ClassVar[dict[str, str]] = {
            "slug": "Латиницей через дефис: smartphones. Идёт в адрес каталога",
            "icon": "Значок-эмодзи у раздела: 📱",
            "sort": "Меньше — раньше в списке",
            "is_active": "Выключенная категория пропадает с витрины вместе с подразделами",
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        names = self.instance.names if isinstance(self.instance.names, dict) else {}
        self.fields["name_uz"].initial = names.get("uz", "")
        self.fields["name_en"].initial = names.get("en", "")

    def clean_slug(self) -> str:
        slug = str(self.cleaned_data.get("slug") or "").strip().lower()

        if not SLUG.fullmatch(slug):
            raise forms.ValidationError("Только латиница, цифры и дефис: smartphones, tea-coffee.")

        return slug

    def clean(self) -> dict[str, Any]:
        data = super().clean() or {}
        parent = data.get("parent")

        if parent is not None:
            node, depth = parent, 1

            while node is not None:
                if self.instance.pk is not None and node.pk == self.instance.pk:
                    raise forms.ValidationError("Категорию нельзя вложить саму в себя.")

                depth += 1
                node = node.parent

            if depth > MAX_DEPTH:
                raise forms.ValidationError(f"Дерево — не глубже {MAX_DEPTH} уровней.")

        return data

    def save(self, commit: bool = True) -> Category:
        names = dict(self.instance.names) if isinstance(self.instance.names, dict) else {}

        for locale in ("uz", "en"):
            value = str(self.cleaned_data.get(f"name_{locale}") or "").strip()

            if value:
                names[locale] = value
            else:
                names.pop(locale, None)

        self.instance.names = names

        return super().save(commit)  # type: ignore[no-any-return]


class AttributeForm(forms.ModelForm):  # type: ignore[type-arg]
    class Meta:
        model = Attribute
        fields = ("key", "name", "kind", "unit", "options", "is_filter", "is_required", "sort")
        help_texts: ClassVar[dict[str, str]] = {
            "key": "Латиницей: color, memory",
            "options": 'Для «выбора»: [{"value": "black", "name": "Чёрный"}]',
        }

    def clean_key(self) -> str:
        key = str(self.cleaned_data.get("key") or "").strip().lower()

        if not KEY.fullmatch(key):
            raise forms.ValidationError("Латиница, цифры и подчёркивание, с буквы: memory_gb.")

        return key

    def clean_options(self) -> Any:  # noqa: ANN401
        options = self.cleaned_data.get("options") or []

        if not isinstance(options, list) or not all(
            isinstance(o, dict)
            and str(o.get("value") or "").strip()
            and str(o.get("name") or "").strip()
            for o in options
        ):
            raise forms.ValidationError('Список вида [{"value": "black", "name": "Чёрный"}].')

        return options

    def clean(self) -> dict[str, Any]:
        data = super().clean() or {}

        if data.get("kind") == "choice" and not data.get("options"):
            raise forms.ValidationError("У «выбора из списка» нужны варианты.")

        # У «да / нет» варианты свои — «Да» и «Нет», список не нужен
        if data.get("kind") == "bool":
            data["options"] = []

        return data


class AttributeInline(admin.TabularInline):  # type: ignore[type-arg]
    model = Attribute
    form = AttributeForm
    extra = 0
    fields = ("key", "name", "kind", "unit", "options", "is_filter", "is_required", "sort")


@register(Category, section="market_catalog")
class CategoryAdmin(SavdexModelAdmin):
    laravel_model = "Savdex\\Market\\Category"
    title_list = "Категории маркетплейса"
    title_add = "Новая категория маркетплейса"
    title_change = "Категория маркетплейса"

    form = CategoryForm
    inlines = (AttributeInline,)
    list_display = ("title", "slug", "products_count", "sort", "is_active")
    list_filter = ("is_active", ("parent", admin.RelatedOnlyFieldListFilter))
    search_fields = ("name", "slug")
    ordering = ("parent__sort", "sort", "name")
    list_per_page = 100
    fieldsets = (
        (
            "Категория",
            {
                "fields": (
                    "parent",
                    "slug",
                    "name",
                    "name_uz",
                    "name_en",
                    "icon",
                    "sort",
                    "is_active",
                )
            },
        ),
    )

    def get_queryset(self, request: HttpRequest) -> QuerySet[Category]:
        queryset: QuerySet[Category] = super().get_queryset(request)

        return queryset.select_related("parent").annotate(
            _products=Subquery(
                Product.objects.filter(category=OuterRef("pk"))
                .values("category")
                .annotate(n=Count("id"))
                .values("n")[:1]
            )
        )

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:  # noqa: ANN401
        """Удалить — только пустую: без подразделов и товаров."""
        if obj is not None and (
            Category.objects.filter(parent=obj).exists()
            or Product.objects.filter(category=obj).exists()
        ):
            return False

        return super().has_delete_permission(request, obj)

    @admin.display(description="категория", ordering="name")
    def title(self, obj: Category) -> str:
        parent = obj.parent

        if parent is None:
            return format_html("{} {}", obj.icon or "", obj.name)

        return format_html("{} <small>· {}</small>", obj.name, parent.name)

    @admin.display(description="товаров")
    def products_count(self, obj: Category) -> int:
        return int(getattr(obj, "_products", 0) or 0)
