"""
Маркетплейс: страницы оформления на демо-данных (savdex/web/market.py).

Сервер отдаёт страницу и разобранный адрес; товары пока лежат во
фронтенде. Проверяется, что адреса открываются на всех языках, что
каталог пропускает только свои параметры и что демо закрыто от
поисковиков.

Нужен PostgreSQL (SAVDEX_PARITY_PG_URL); общая часть — в web_site.py.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from .pg_admin import нужна_база, свежая_база
from .web_site import адрес, открыть, страница

pytestmark = нужна_база


@pytest.fixture(scope="module")
def сайт() -> Iterator[str]:
    свежая_база()

    with адрес() as root:
        yield root


@pytest.mark.parametrize(
    ("path", "component"),
    [
        ("/market", "market/Home"),
        ("/uz/market", "market/Home"),
        ("/market/catalog", "market/Catalog"),
        ("/en/market/catalog", "market/Catalog"),
        ("/market/product/kazan-chugunnyj-12l", "market/Product"),
        ("/market/cart", "market/Cart"),
        ("/market/checkout", "market/Checkout"),
        ("/market/orders", "market/Orders"),
        ("/market/shop/technomir", "market/Shop"),
        ("/tr/market/sell", "market/Sell"),
        ("/market/seller", "market/Seller"),
    ],
)
def test_страницы_открываются(сайт, path, component):
    д = открыть(сайт, path)

    assert д["status"] == 200
    assert страница(д["body"])["component"] == component
    # Демо-товары в поиск не попадают
    assert "noindex" in д["body"]


def test_каталог_берёт_только_свои_параметры(сайт):
    д = открыть(сайт, "/market/catalog?category=home&sort=cheap&q=%20казан%20&utm_source=x&only=")

    assert страница(д["body"])["props"]["query"] == {
        "q": "казан",
        "category": "home",
        "sort": "cheap",
    }


def test_товар_получает_свой_адрес(сайт):
    д = открыть(сайт, "/market/product/smartfon-nova-x5-256")

    assert страница(д["body"])["props"]["slug"] == "smartfon-nova-x5-256"


def test_кривой_адрес_товара_не_открывается(сайт):
    assert открыть(сайт, "/market/product/Товар!")["status"] == 404


@pytest.mark.parametrize(
    ("адрес_вкладки", "вкладка"),
    [("", "overview"), ("?tab=stock", "stock"), ("?tab=чужая", "overview")],
)
def test_кабинет_продавца_знает_только_свои_вкладки(сайт, адрес_вкладки, вкладка):
    д = открыть(сайт, "/market/seller" + адрес_вкладки)

    assert страница(д["body"])["props"]["tab"] == вкладка


def test_на_боевом_демо_не_открывается(сайт):
    д = открыть(сайт, "/market", env={"APP_ENV": "production", "DJANGO_ALLOWED_HOSTS": "*"})

    assert д["status"] == 404
