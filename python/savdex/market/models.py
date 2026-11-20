"""
Модели маркетплейса для раздела админки (savdex/market/admin.py).

Таблицы создаёт миграция SQL 2026_11_19_100000_create_market_catalog.sql:
managed = False, схему Django не трогает. Витрина, корзина и кабинет
продавца ходят в базу запросами (catalog.py, cart.py, products.py) — так
видно каждое условие «товар виден покупателю».
"""

from __future__ import annotations

from typing import Any

from django.db import models

from savdex.catalog import UTCDateTimeField
from savdex.market.common import som


class Category(models.Model):
    parent = models.ForeignKey(
        "self",
        on_delete=models.DO_NOTHING,
        null=True,
        blank=True,
        related_name="children",
        db_column="parent_id",
        verbose_name="раздел",
    )
    slug = models.CharField("адрес (slug)", max_length=80, unique=True)
    name = models.CharField("название по-русски", max_length=120)
    names: Any = models.JSONField("названия на других языках", default=dict, blank=True)
    icon = models.CharField("значок", max_length=16, null=True, blank=True)
    sort = models.IntegerField("порядок", default=0)
    is_active = models.BooleanField("включена", default=True)
    created_at = UTCDateTimeField(auto_now_add=True)
    updated_at = UTCDateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = "market_categories"
        ordering = ("sort", "name")
        verbose_name = "категория маркетплейса"
        verbose_name_plural = "категории маркетплейса"

    def __str__(self) -> str:
        return self.name if self.pk else "новая категория"

    def depth(self) -> int:
        """Уровень в дереве: раздел — 1, подраздел — 2, …"""
        level, node, seen = 1, self.parent, {self.pk}

        while node is not None and node.pk not in seen:
            seen.add(node.pk)
            level += 1
            node = node.parent

        return level


class Attribute(models.Model):
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name="attributes",
        db_column="category_id",
        verbose_name="категория",
    )
    key = models.CharField("код", max_length=40)
    name = models.CharField("название по-русски", max_length=120)
    names: Any = models.JSONField("названия на других языках", default=dict, blank=True)
    kind = models.CharField(
        "тип",
        max_length=16,
        default="text",
        choices=[
            ("text", "Строка"),
            ("number", "Число"),
            ("choice", "Выбор из списка"),
            ("bool", "Да / нет"),
        ],
    )
    options: Any = models.JSONField("варианты выбора", default=list, blank=True)
    unit = models.CharField("единица", max_length=16, null=True, blank=True)
    is_filter = models.BooleanField("в фильтрах каталога", default=True)
    is_required = models.BooleanField("обязательна", default=False)
    sort = models.IntegerField("порядок", default=0)
    created_at = UTCDateTimeField(auto_now_add=True)
    updated_at = UTCDateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = "market_attributes"
        ordering = ("sort", "id")
        unique_together = (("category", "key"),)
        verbose_name = "характеристика"
        verbose_name_plural = "характеристики"

    def __str__(self) -> str:
        return self.name


class Seller(models.Model):
    company_id = models.BigIntegerField("компания")
    user_id = models.BigIntegerField("подал заявку", null=True)
    status = models.CharField("статус", max_length=16, default="pending")
    verified_via = models.CharField("подтверждён", max_length=16, null=True)
    oneid_tin = models.CharField("ИНН из OneID", max_length=14, null=True)
    offer_version = models.CharField("редакция оферты", max_length=32, null=True)
    offer_accepted_at = UTCDateTimeField("оферта принята", null=True)
    note = models.CharField("комментарий к заявке", max_length=1000, null=True)
    reject_reason = models.CharField("причина", max_length=1000, null=True)
    reviewed_by = models.BigIntegerField("решение принял", null=True)
    reviewed_at = UTCDateTimeField("решение", null=True)
    approved_at = UTCDateTimeField("продавец с", null=True)
    blocked_at = UTCDateTimeField("заблокирован", null=True)
    created_at = UTCDateTimeField("заявка", auto_now_add=True)
    updated_at = UTCDateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = "market_sellers"
        ordering = ("-created_at",)
        verbose_name = "продавец"
        verbose_name_plural = "продавцы"

    def __str__(self) -> str:
        return f"Продавец №{self.pk}"


class Product(models.Model):
    seller = models.ForeignKey(
        Seller, on_delete=models.DO_NOTHING, db_column="seller_id", verbose_name="продавец"
    )
    category = models.ForeignKey(
        Category, on_delete=models.DO_NOTHING, db_column="category_id", verbose_name="категория"
    )
    slug = models.CharField("адрес", max_length=80, null=True)
    title = models.CharField("название", max_length=200)
    description = models.TextField("описание", null=True)
    locale = models.CharField("язык", max_length=8, default="ru")
    status = models.CharField("статус", max_length=16, default="draft")
    reject_reason = models.CharField("причина", max_length=1000, null=True)
    ikpu = models.CharField("ИКПУ", max_length=17, null=True)
    barcode = models.CharField("штрихкод", max_length=32, null=True)
    weight_g = models.IntegerField("вес, г", null=True)
    length_mm = models.IntegerField("длина, мм", null=True)
    width_mm = models.IntegerField("ширина, мм", null=True)
    height_mm = models.IntegerField("высота, мм", null=True)
    price = models.BigIntegerField("цена, тийин", null=True)
    old_price = models.BigIntegerField("старая цена, тийин", null=True)
    stock = models.IntegerField("остаток", default=0)
    rating = models.DecimalField("рейтинг", max_digits=3, decimal_places=2, default=0)
    reviews_count = models.IntegerField("отзывов", default=0)
    sold_count = models.IntegerField("продано", default=0)
    views_count = models.IntegerField("просмотров", default=0)
    submitted_at = UTCDateTimeField("отправлен", null=True)
    published_at = UTCDateTimeField("в продаже с", null=True)
    approved_at = UTCDateTimeField("одобрен модератором", null=True)
    moderated_by = models.BigIntegerField("решение принял", null=True)
    moderated_at = UTCDateTimeField("решение", null=True)
    created_at = UTCDateTimeField("создан", auto_now_add=True)
    updated_at = UTCDateTimeField("изменён", auto_now=True)

    class Meta:
        managed = False
        db_table = "market_products"
        ordering = ("-updated_at",)
        verbose_name = "товар"
        verbose_name_plural = "товары"

    def __str__(self) -> str:
        return self.title

    def price_label(self) -> str:
        value = som(self.price)

        return f"{value:,}".replace(",", " ") + " сум" if value is not None else "—"


class Variant(models.Model):
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="variants",
        db_column="product_id",
        verbose_name="товар",
    )
    options: Any = models.JSONField("выбор", default=dict)
    sku = models.CharField("артикул", max_length=64, null=True)
    price = models.BigIntegerField("цена, тийин")
    old_price = models.BigIntegerField("старая цена, тийин", null=True)
    stock = models.IntegerField("остаток", default=0)
    reserved = models.IntegerField("в резерве", default=0)
    is_active = models.BooleanField("включён", default=True)
    sort = models.IntegerField("порядок", default=0)
    created_at = UTCDateTimeField(auto_now_add=True)
    updated_at = UTCDateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = "market_product_variants"
        ordering = ("sort", "id")
        verbose_name = "вариант"
        verbose_name_plural = "варианты и остатки"

    def __str__(self) -> str:
        options = self.options if isinstance(self.options, dict) else {}

        return ", ".join(f"{k}: {v}" for k, v in options.items() if not k.startswith("_")) or (
            "без выбора"
        )


class PickupPoint(models.Model):
    """Пункт выдачи (миграция 2026_11_21_100000): пока Ташкент, заводит администратор."""

    code = models.CharField(
        "код",
        max_length=32,
        unique=True,
        help_text="Латиница, цифры и дефис: chilonzor-1. Попадает в заказы — не меняйте.",
    )
    name = models.CharField("название", max_length=200)
    address = models.CharField("адрес", max_length=500)
    city = models.CharField("город", max_length=64, default="Ташкент")
    is_active = models.BooleanField("принимает заказы", default=True)
    sort = models.IntegerField("порядок", default=0)
    created_at = UTCDateTimeField(auto_now_add=True)
    updated_at = UTCDateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = "market_pickup_points"
        ordering = ("sort", "name")
        verbose_name = "пункт выдачи"
        verbose_name_plural = "пункты выдачи"

    def __str__(self) -> str:
        return self.name if self.pk else "новый пункт выдачи"


class Order(models.Model):
    """
    Заказ (savdex/market/orders.py). В админке — только смотреть: статусы
    меняют оформление, отмена и расписание, дальше — оплата и склад.
    """

    number = models.CharField("номер", max_length=16, unique=True)
    buyer_user_id = models.BigIntegerField("покупатель")
    status = models.CharField("статус", max_length=20)
    payment_method = models.CharField("оплата", max_length=8)
    pickup_point = models.ForeignKey(
        PickupPoint,
        on_delete=models.DO_NOTHING,
        db_column="pickup_point_id",
        verbose_name="пункт выдачи",
    )
    pickup_point_name = models.CharField("пункт выдачи", max_length=200)
    pickup_point_address = models.CharField("адрес пункта", max_length=500)
    items_total = models.BigIntegerField("товары, тийин")
    delivery_total = models.BigIntegerField("доставка, тийин", default=0)
    total = models.BigIntegerField("итого, тийин")
    commission_total = models.BigIntegerField("комиссия, тийин", default=0)
    paid_at = UTCDateTimeField("оплачен", null=True)
    cancelled_at = UTCDateTimeField("отменён", null=True)
    cancel_reason = models.CharField("причина отмены", max_length=500, null=True)
    issued_at = UTCDateTimeField("выдан", null=True)
    reserve_released_at = UTCDateTimeField("резерв снят", null=True)
    #: Касса сверила наличные заказа с отчётом BTS (миграция 2026_11_21_120000)
    cash_reconciled_at = UTCDateTimeField("наличные сверены", null=True)
    cash_reconciled_by = models.BigIntegerField("сверил", null=True)
    stock_written_off_at = UTCDateTimeField("остаток списан", null=True)
    created_at = UTCDateTimeField("оформлен", auto_now_add=True)
    updated_at = UTCDateTimeField("изменён", auto_now=True)

    class Meta:
        managed = False
        db_table = "market_orders"
        ordering = ("-created_at", "-id")
        verbose_name = "заказ"
        verbose_name_plural = "заказы"

    def __str__(self) -> str:
        return f"Заказ {self.number}"


# ── Касса — этап 3 (миграция 2026_11_21_120000, savdex/market/cash.py) ──


class SellerRequisites(models.Model):
    """Реквизиты продавца для выплат: меняет только владелец компании из кабинета."""

    seller = models.OneToOneField(
        Seller, on_delete=models.DO_NOTHING, db_column="seller_id", verbose_name="продавец"
    )
    bank_account = models.CharField("расчётный счёт", max_length=20)
    bank_mfo = models.CharField("МФО", max_length=5)
    bank_name = models.CharField("банк", max_length=200)
    recipient_name = models.CharField("получатель", max_length=200)
    recipient_tin = models.CharField("ИНН / ПИНФЛ", max_length=14)
    changed_at = UTCDateTimeField("сменены")
    changed_by = models.BigIntegerField("сменил", null=True)
    created_at = UTCDateTimeField(auto_now_add=True)
    updated_at = UTCDateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = "market_seller_requisites"
        ordering = ("-changed_at",)
        verbose_name = "реквизиты продавца"
        verbose_name_plural = "реквизиты продавцов"

    def __str__(self) -> str:
        return f"Реквизиты продавца №{self.seller_id}"


class RequisitesLog(models.Model):
    """История реквизитов — только дописывается."""

    seller = models.ForeignKey(
        Seller, on_delete=models.DO_NOTHING, db_column="seller_id", verbose_name="продавец"
    )
    bank_account = models.CharField("расчётный счёт", max_length=20)
    bank_mfo = models.CharField("МФО", max_length=5)
    bank_name = models.CharField("банк", max_length=200)
    recipient_name = models.CharField("получатель", max_length=200)
    recipient_tin = models.CharField("ИНН / ПИНФЛ", max_length=14)
    changed_by = models.BigIntegerField("сменил", null=True)
    ip = models.CharField("IP", max_length=45, null=True)
    created_at = UTCDateTimeField("когда", auto_now_add=True)

    class Meta:
        managed = False
        db_table = "market_seller_requisites_log"
        ordering = ("-id",)
        verbose_name = "смена реквизитов"
        verbose_name_plural = "история реквизитов"


class Payout(models.Model):
    """Выплата продавцу: создаёт один кассир, подтверждает другой."""

    seller = models.ForeignKey(
        Seller, on_delete=models.DO_NOTHING, db_column="seller_id", verbose_name="продавец"
    )
    amount = models.BigIntegerField("сумма, тийин")
    status = models.CharField("статус", max_length=12, default="draft")
    note = models.CharField("комментарий", max_length=500, null=True)
    created_by = models.BigIntegerField("создал")
    approved_by = models.BigIntegerField("подтвердил", null=True)
    paid_by = models.BigIntegerField("отметил выплату", null=True)
    cancelled_by = models.BigIntegerField("отменил", null=True)
    requisites_log_id = models.BigIntegerField("реквизиты (история)", null=True)
    fresh_requisites = models.BooleanField("на свежие реквизиты", default=False)
    fresh_check_note = models.CharField("как сверили реквизиты", max_length=500, null=True)
    bank_reference = models.CharField("платёжное поручение", max_length=64, null=True)
    ledger_group = models.UUIDField("группа журнала денег", null=True)
    cancel_reason = models.CharField("причина отмены", max_length=500, null=True)
    cancel_not_sent = models.BooleanField("платёжка не отправлялась", default=False)
    created_at = UTCDateTimeField("создана", auto_now_add=True)
    updated_at = UTCDateTimeField(auto_now=True)
    approved_at = UTCDateTimeField("подтверждена", null=True)
    paid_at = UTCDateTimeField("выплачена", null=True)
    cancelled_at = UTCDateTimeField("отменена", null=True)

    class Meta:
        managed = False
        db_table = "market_payouts"
        ordering = ("-id",)
        verbose_name = "выплата продавцу"
        verbose_name_plural = "выплаты продавцам"

    def __str__(self) -> str:
        return f"Выплата №{self.pk}" if self.pk else "новая выплата"


class SellerBalance(Seller):
    """Балансы продавцов в кассе — только смотреть (savdex/market/cash.py, balance)."""

    class Meta:
        proxy = True
        verbose_name = "баланс продавца"
        verbose_name_plural = "балансы продавцов"


class RefundOrder(Order):
    """Заказы, ждущие возврата денег, — ручная отметка возврата кассой."""

    class Meta:
        proxy = True
        verbose_name = "возврат покупателю"
        verbose_name_plural = "возвраты покупателям"


class CashOrder(Order):
    """Выданные заказы «при получении», ждущие сверки наличных с отчётом BTS."""

    class Meta:
        proxy = True
        verbose_name = "наличные к сверке"
        verbose_name_plural = "наличные к сверке"
