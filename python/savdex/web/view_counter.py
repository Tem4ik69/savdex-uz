"""
Засчитать ли просмотр тендера, резюме, IT-задачи, визитки (Н22).

Раньше каждый запрос страницы писал +1 в базу: обновление страницы,
скрипт без куки или робот накручивали счётчик и нагружали базу без
предела. Теперь просмотр засчитывается:

- не роботу (User-Agent с bot/crawl/spider и т. п., CRAWLERS);
- раз в полчаса на посетителя и страницу — вошедший узнаётся по номеру,
  гость по адресу IP (без куки у каждого запроса своя сессия, отсев по
  сессии его не ловит);
- не больше HOURLY_CAP засчитанных просмотров в час с одного посетителя —
  перебор адресов страниц не превращается в поток записей.

Метки — в общем файловом кэше (CACHE_STORE=file, как throttle и
отсев объявлений). Без файлового кэша (тесты с array) отсева нет.
"""

from __future__ import annotations

import hashlib
import re

from savdex import laravel_cache
from savdex.audit import client_ip
from savdex.web.request import CRAWLERS
from savdex.web.shared import Context
from savdex.web.throttle import hit, too_many

#: Повтор того же посетителя на той же странице не засчитывается
DEDUP_SECONDS = 30 * 60

#: Засчитанных просмотров в час с одного посетителя — сверх не пишем
HOURLY_CAP = 120

_ROBOT = re.compile(
    r"bot|crawl|spider|slurp|curl|wget|python|httpclient|okhttp|headless|scrapy|"
    + "|".join(re.escape(name) for name in CRAWLERS),
    re.IGNORECASE,
)


def _robot(ctx: Context) -> bool:
    agent = ctx.request.META.get("HTTP_USER_AGENT") or ""

    return agent.strip() == "" or _ROBOT.search(agent) is not None


def _who(ctx: Context) -> str:
    """Посетитель для отсева: номер вошедшего или адрес гостя — в sha1."""
    if ctx.visitor.user_id is not None:
        raw = f"u:{ctx.visitor.user_id}"
    else:
        raw = f"ip:{client_ip(ctx.request) or ''}"

    return hashlib.sha1(raw.encode()).hexdigest()


def should_count(ctx: Context, kind: str, object_id: int) -> bool:
    """Засчитать просмотр страницы kind/object_id этим посетителем."""
    if not laravel_cache.is_file_store():
        return True

    if _robot(ctx):
        return False

    who = _who(ctx)
    cap = f"views:cap:{who}"

    if too_many(cap, HOURLY_CAP):
        return False

    if not laravel_cache.add(f"views:{kind}:{who}:{object_id}", True, DEDUP_SECONDS):
        return False

    hit(cap, 3600)

    return True
