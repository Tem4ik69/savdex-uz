"""
Баннеры маркетплейса (ТЗ, раздел 3) — из существующего раздела админки
«Баннеры», новыми местами размещения (savdex/site/models.py, PLACEMENTS):

- market_slider — слайдер сверху главной: все живые баннеры по порядку;
- market_strip — полосы между подборками: страница ставит их по очереди;
- market_catalog — каталог товаров: один, как у каталога объявлений.

Живой — включён и в своём сроке показа. Картинка — на языке страницы,
если её загрузили, иначе общая; для телефона — своя, если есть.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from savdex.site.models import DISMISS_DAYS, Banner
from savdex.web.shared import Context

#: Места маркетплейса: короткое имя в адресе → место в админке и сколько отдавать
PLACES: dict[str, tuple[str, int]] = {
    "slider": ("market_slider", 10),
    "strip": ("market_strip", 10),
    "catalog": ("market_catalog", 1),
}


def live(ctx: Context, place: str) -> list[dict[str, Any]]:
    placement, limit = PLACES[place]
    now = datetime.now(UTC)
    found = (
        Banner.objects.filter(is_active=True, placement=placement)
        .exclude(starts_at__gt=now)
        .exclude(ends_at__lte=now)
        .prefetch_related("images")
        .order_by("sort", "-id")[:limit]
    )
    result = []

    for banner in found:
        own = next((i for i in banner.images.all() if i.locale == ctx.locale), None)
        image = own.image_path if own is not None else banner.image_path
        mobile = own.image_mobile_path if own is not None else banner.image_mobile_path
        result.append(
            {
                "key": f"banner-{banner.id}",
                "url": banner.url,
                "alt": banner.alt,
                "image": ctx.url("storage/" + image),
                "imageMobile": ctx.url("storage/" + mobile) if mobile else None,
                "focal": f"{banner.focal_x}% {banner.focal_y}%",
                "dismissible": banner.is_dismissible,
                "dismissDays": DISMISS_DAYS,
            }
        )

    return result
