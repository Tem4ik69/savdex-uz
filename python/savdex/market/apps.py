from __future__ import annotations

from django.apps import AppConfig


class MarketConfig(AppConfig):
    """Маркетплейс: каталог товаров, продавцы, корзина."""

    name = "savdex.market"
    label = "market"
    verbose_name = "Маркетплейс"
