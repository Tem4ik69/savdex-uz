"""
Демо-товары маркетплейса для тестового сервера (manage.py demo).

Те же продавцы и товары, что в демо Максуда (resources/js/market/demo.ts):
страницы маркетплейса, переведённые с demo.ts на настоящие адреса
/market/api/…, показывают на тестовом то же, что показывали на
демо-данных. ТЗ 18.11, раздел 11.3: «Демо-данные на тестовом: категории,
товары, ПВЗ» (категории заводит миграция каталога; пункты выдачи — здесь,
те же 8, что в демо оформления заказа, resources/js/market/orders.ts).

Правила — как у savdex/demo.py:
- на боевом (APP_ENV=production) не работает;
- продавцы — придуманные компании, помечены (companies.source_note):
  повторный запуск ничего не дублирует;
- заводится и в базе, где демо-компании SavdEx уже есть: маркетплейс
  добавляется к ним, ничего не стирая.

Фото у демо-товаров нет — как и в demo.ts (там значок вместо фото).
ИКПУ — придуманные (17 цифр, начинаются с 99): без ИКПУ товар не может
быть «в продаже» (ограничение market_products_active_check).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from itertools import product as combinations
from typing import Any

from django.db import transaction

from savdex import demo
from savdex.market import products
from savdex.tenders.slug import slugify
from savdex.web.search_text import index

#: Метка компаний-продавцов демо (companies.source_note)
MARK = "Демо-данные маркетплейса тестового сервера (manage.py demo)"

#: Продавцы — как SELLERS в demo.ts: адрес, название, проверен, рейтинг
SELLERS: list[tuple[str, str, bool, float]] = [
    ("chorsu-tech", "Chorsu Tech", True, 4.8),
    ("technomir", "TechnoMir", True, 4.7),
    ("oltin-vodiy", "Oltin Vodiy", True, 4.6),
    ("namangan-metall", "Namangan Metall", True, 4.9),
    ("samarqand-tekstil", "Samarqand Tekstil", True, 4.8),
    ("bolajon", "Bolajon", False, 4.7),
    ("guli-cosmetics", "Guli Cosmetics", True, 4.6),
    ("usta-market", "Usta Market", True, 4.7),
]

_WARRANTY = ("Гарантия", "12 месяцев")

#: Товары — как PRODUCTS в demo.ts. Цены в сумах. Категория — подраздел
#: (товар лежит в категории без подразделов), в demo.ts — только раздел.
#: badge new — опубликован недавно (метка «Новинка» считается по дате).
PRODUCTS: list[dict[str, Any]] = [
    {
        "slug": "smartfon-nova-x5-256",
        "title": "Смартфон Nova X5, 8/256 ГБ",
        "category": "smartphones",
        "seller": "chorsu-tech",
        "price": 3_490_000,
        "old": 4_290_000,
        "rating": 4.8,
        "reviews": 312,
        "sold": 1200,
        "stock": 14,
        "new": False,
        "variants": {"Цвет": ["Синий", "Чёрный", "Зелёный"], "Память": ["128 ГБ", "256 ГБ"]},
        "specs": [
            ("Экран", "6,7″ AMOLED, 120 Гц"),
            ("Камера", "50 Мп"),
            ("Батарея", "5000 мА·ч"),
            ("SIM", "Две SIM"),
            _WARRANTY,
        ],
        "description": (
            "Яркий экран, быстрая зарядка и камера с ночным режимом. Официальная гарантия продавца."
        ),
    },
    {
        "slug": "naushniki-orbit-buds-2",
        "title": "Беспроводные наушники Orbit Buds 2",
        "category": "headphones",
        "seller": "technomir",
        "price": 289_000,
        "old": 420_000,
        "rating": 4.7,
        "reviews": 1840,
        "sold": 5400,
        "stock": 60,
        "new": False,
        "variants": {"Цвет": ["Чёрный", "Белый"]},
        "specs": [
            ("Тип", "Вкладыши с шумоподавлением"),
            ("Работа", "до 28 часов с кейсом"),
            ("Связь", "Bluetooth 5.3"),
            _WARRANTY,
        ],
        "description": (
            "Активное шумоподавление и быстрая зарядка: 10 минут в кейсе дают два часа музыки."
        ),
    },
    {
        "slug": "krossovki-begovye-setka",
        "title": "Кроссовки мужские беговые, сетка",
        "category": "men-shoes",
        "seller": "oltin-vodiy",
        "price": 349_000,
        "old": 499_000,
        "rating": 4.6,
        "reviews": 96,
        "sold": 310,
        "stock": 22,
        "new": True,
        "variants": {"Размер": ["40", "41", "42", "43", "44"]},
        "specs": [
            ("Верх", "Дышащая сетка"),
            ("Подошва", "Вспененная, 3 см"),
            ("Сезон", "Весна — осень"),
        ],
        "description": "Лёгкая пара для бега и города. Маломерят на полразмера — берите с запасом.",
    },
    {
        "slug": "kazan-chugunnyj-12l",
        "title": "Казан чугунный 12 л с крышкой",
        "category": "tableware",
        "seller": "namangan-metall",
        "price": 415_000,
        "old": None,
        "rating": 4.9,
        "reviews": 540,
        "sold": 2100,
        "stock": 35,
        "new": False,
        "variants": {"Объём": ["8 л", "12 л", "16 л"]},
        "specs": [
            ("Материал", "Чугун, наманганское литьё"),
            ("Крышка", "Алюминиевая"),
            ("Вес", "9,4 кг"),
            ("Плита", "Газ, очаг"),
        ],
        "description": (
            "Классический казан для плова на 10–12 порций. Перед первым приготовлением прокалите "
            "с маслом."
        ),
    },
    {
        "slug": "kofevarka-kapelnaya-12",
        "title": "Кофеварка капельная 1,2 л",
        "category": "kitchen-appliances",
        "seller": "technomir",
        "price": 890_000,
        "old": 1_150_000,
        "rating": 4.5,
        "reviews": 71,
        "sold": 180,
        "stock": 9,
        "new": False,
        "variants": {},
        "specs": [
            ("Объём", "1,2 л — до 10 чашек"),
            ("Мощность", "900 Вт"),
            ("Подогрев", "до 40 минут"),
            _WARRANTY,
        ],
        "description": (
            "Варит до десяти чашек за раз и держит кофе горячим. Съёмный фильтр моется под краном."
        ),
    },
    {
        "slug": "ryukzak-gorodskoj-25l",
        "title": "Рюкзак городской 25 л, влагозащита",
        "category": "bags-backpacks",
        "seller": "samarqand-tekstil",
        "price": 199_000,
        "old": 280_000,
        "rating": 4.7,
        "reviews": 228,
        "sold": 760,
        "stock": 48,
        "new": True,
        "variants": {"Цвет": ["Красный", "Серый", "Чёрный"]},
        "specs": [
            ("Объём", "25 л"),
            ("Отделение", "Для ноутбука до 15,6″"),
            ("Ткань", "Полиэстер с пропиткой"),
        ],
        "description": (
            "Отделение для ноутбука, карман на спинке для документов и порт для зарядки."
        ),
    },
    {
        "slug": "konstruktor-520-detalej",
        "title": "Конструктор детский, 520 деталей",
        "category": "toys",
        "seller": "bolajon",
        "price": 159_000,
        "old": 230_000,
        "rating": 4.8,
        "reviews": 403,
        "sold": 1900,
        "stock": 70,
        "new": False,
        "variants": {},
        "specs": [("Деталей", "520"), ("Возраст", "от 6 лет"), ("Материал", "Пластик без запаха")],
        "description": (
            "Три модели из одного набора. Детали совместимы с популярными конструкторами."
        ),
    },
    {
        "slug": "krem-dlya-lica-50ml",
        "title": "Крем для лица увлажняющий, 50 мл",
        "category": "face-care",
        "seller": "guli-cosmetics",
        "price": 78_000,
        "old": None,
        "rating": 4.6,
        "reviews": 1250,
        "sold": 8300,
        "stock": 200,
        "new": True,
        "variants": {"Объём": ["50 мл", "100 мл"]},
        "specs": [
            ("Тип кожи", "Нормальная и сухая"),
            ("Состав", "Гиалуроновая кислота, алоэ"),
            ("Срок", "24 месяца"),
        ],
        "description": "Лёгкая текстура, быстро впитывается. Подходит под макияж.",
    },
    {
        "slug": "drel-shurupovert-18v",
        "title": "Дрель-шуруповёрт 18 В, 2 аккумулятора",
        "category": "hand-tools",
        "seller": "usta-market",
        "price": 720_000,
        "old": 960_000,
        "rating": 4.7,
        "reviews": 158,
        "sold": 420,
        "stock": 17,
        "new": False,
        "variants": {},
        "specs": [
            ("Напряжение", "18 В"),
            ("Аккумуляторы", "2 × 2,0 А·ч"),
            ("Патрон", "до 13 мм"),
            ("В комплекте", "Кейс, 12 бит"),
            _WARRANTY,
        ],
        "description": "Два аккумулятора в комплекте: один работает, второй заряжается.",
    },
    {
        "slug": "postelnoe-bele-hlopok-2sp",
        "title": "Постельное бельё, хлопок, 2-спальное",
        "category": "textile",
        "seller": "samarqand-tekstil",
        "price": 329_000,
        "old": 450_000,
        "rating": 4.9,
        "reviews": 677,
        "sold": 3000,
        "stock": 55,
        "new": False,
        "variants": {"Цвет": ["Голубой", "Бежевый", "Белый"]},
        "specs": [
            ("Ткань", "Хлопок 100 %, сатин"),
            ("Комплект", "Пододеяльник, простыня, 2 наволочки"),
            ("Размер", "2-спальный"),
        ],
        "description": (
            "Плотный сатин из узбекского хлопка: не скатывается и не линяет после стирки."
        ),
    },
    {
        "slug": "umnye-chasy-pulse-3",
        "title": "Умные часы Pulse 3, AMOLED",
        "category": "smartwatches",
        "seller": "chorsu-tech",
        "price": 540_000,
        "old": 790_000,
        "rating": 4.4,
        "reviews": 89,
        "sold": 240,
        "stock": 0,
        "new": False,
        "variants": {"Цвет": ["Чёрный", "Серебро"]},
        "specs": [
            ("Экран", "1,43″ AMOLED"),
            ("Работа", "до 10 дней"),
            ("Защита", "5 ATM"),
            _WARRANTY,
        ],
        "description": "Пульс, сон, 100 видов тренировок и звонки с запястья.",
    },
    {
        "slug": "chajnik-elektricheskij-17",
        "title": "Чайник электрический 1,7 л, стекло",
        "category": "kitchen-appliances",
        "seller": "technomir",
        "price": 185_000,
        "old": 240_000,
        "rating": 4.6,
        "reviews": 344,
        "sold": 1100,
        "stock": 40,
        "new": True,
        "variants": {},
        "specs": [
            ("Объём", "1,7 л"),
            ("Мощность", "2200 Вт"),
            ("Корпус", "Термостойкое стекло"),
            _WARRANTY,
        ],
        "description": "Закипает за три минуты и отключается сам. Подсветка воды при нагреве.",
    },
]


def _attribute_key(name: str) -> str:
    """«Тип кожи» → tip_kozhi: ключ характеристики (латиница, цифры, «_»)."""
    key = slugify(name).replace("-", "_")[:40] or "spec"

    return key if key[0].isalpha() else f"s_{key}"[:40]


def _attribute(category_id: int, name: str) -> int:
    """Характеристика подраздела по названию: есть — её номер, нет — заводится (строка)."""
    key = _attribute_key(name)
    found = demo._rows(
        "select id from market_attributes where category_id = %s and key = %s", [category_id, key]
    )

    if found:
        return int(found[0][0])

    return demo._insert(
        "market_attributes",
        {"category_id": category_id, "key": key, "name": name, "kind": "text", "is_filter": False},
    )


def _split(total: int, parts: int) -> list[int]:
    """Остаток товара — поровну между вариантами, лишнее — первым."""
    base, extra = divmod(total, parts)

    return [base + (1 if n < extra else 0) for n in range(parts)]


#: Пункты выдачи BTS — как POINTS в resources/js/market/orders.ts: код (с «demo-»,
#: чтобы не спутать с настоящими кодами BTS), название, район и адрес. Часы —
#: одинаковые демо-часы (настоящие и точки на карте ждут ответов BTS, ТЗ,
#: вопросы 4–5).
PICKUP_POINTS: list[tuple[str, str, str]] = [
    ("demo-chilanzar", "BTS Чиланзар", "Чиланзарский район, ул. Бунёдкор, 12"),
    ("demo-yunusabad", "BTS Юнусабад", "Юнусабадский район, ул. Амира Темура, 107"),
    ("demo-ulugbek", "BTS Буюк Ипак Йули", "Мирзо-Улугбекский район, ул. Буюк Ипак Йули, 45"),
    ("demo-sergeli", "BTS Сергели", "Сергелийский район, ул. Янги Сергели, 8"),
    ("demo-yakkasaray", "BTS Яккасарай", "Яккасарайский район, ул. Шота Руставели, 22"),
    ("demo-chorsu", "BTS Чорсу", "Шайхантахурский район, ул. Навои, 48"),
    ("demo-mirabad", "BTS Мирабад", "Мирабадский район, ул. Нукус, 31"),
    ("demo-olmazor", "BTS Алмазар", "Алмазарский район, ул. Каракамыш, 3"),
]


def _pickup_points() -> int:
    """Демо-пункты выдачи: какие уже есть (по коду) — не трогаются. Итог — сколько заведено."""
    made = 0

    for sort, (code, name, address) in enumerate(PICKUP_POINTS):
        made += len(
            demo._rows(
                "insert into market_pickup_points (code, name, address, city, sort, hours) "
                "values (%s, %s, %s, 'Ташкент', %s, 'Пн–Сб 9:00–20:00') "
                "on conflict (code) do nothing returning id",
                [code, name, address, sort],
            )
        )

    return made


def seed(*, now: datetime | None = None) -> dict[str, int]:
    """Завести демо маркетплейса; уже заведено — ничего. Итог — сколько чего заведено."""
    if (why := demo.refused()) is not None:
        raise demo.DemoRefusedError(why)

    # Пункты выдачи — отдельно от продавцов: доезжают и туда, где демо-товары уже есть
    made = {
        "sellers": 0,
        "products": 0,
        "variants": 0,
        "supplies": 0,
        "pickup_points": _pickup_points(),
    }

    if demo._rows("select 1 from companies where source_note = %s limit 1", [MARK]):
        return made

    now = now or datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    categories = demo._ids("market_categories", {p["category"] for p in PRODUCTS})
    missing = sorted({p["category"] for p in PRODUCTS} - set(categories))

    if missing:
        raise demo.DemoRefusedError(
            f"Нет категорий маркетплейса: {', '.join(missing)} — их заводит миграция каталога."
        )

    country = demo._rows("select id from countries where code = 'uz'")
    city = demo._rows("select id from cities where slug = 'tashkent'")

    if not country or not city:
        raise demo.DemoRefusedError(
            "Нет справочников (страна uz, Ташкент) — сначала manage.py seed."
        )

    sellers: dict[str, int] = {}
    #: Остаток вариантов по продавцам — его заведёт приёмка поставки (_receive)
    arrivals: dict[int, list[tuple[int, int, int]]] = {}

    with transaction.atomic():
        for n, (slug, name, verified, rating) in enumerate(SELLERS, start=1):
            joined = now - timedelta(days=60 + n * 17)
            taken = demo._rows("select 1 from companies where slug = %s limit 1", [slug])
            company_id = demo._insert(
                "companies",
                {
                    # Адрес — как у продавца в demo.ts: страница /market/shop/<адрес>
                    "slug": demo._company_slug(name) if taken else slug,
                    "name": name,
                    "legal_name": f"ООО «{name}»",
                    "legal_form": "legal",
                    "tin": str(400_000_000 + n * 7919),
                    "country_id": int(country[0][0]),
                    "city_id": int(city[0][0]),
                    "type": "supplier",
                    "primary_role": "supplier",
                    "description": f"{name} — продавец маркетплейса SavdEx (демо).",
                    "phone": f"+998 71 300 {n:02d} {n * 7 % 100:02d}",
                    "email": f"shop@{slug}.{demo.EMAIL_DOMAIN}",
                    # Проверенный продавец — документы приняты (как verified в demo.ts)
                    "verification_level": 2 if verified else 1,
                    "rating": rating,
                    "status": "active",
                    "search_text": index(name),
                    "source_note": MARK,
                    "created_at": joined,
                    "updated_at": joined,
                },
            )
            sellers[slug] = demo._insert(
                "market_sellers",
                {
                    "company_id": company_id,
                    "status": "approved",
                    "verified_via": "documents",
                    "offer_version": "draft-2026-11",
                    "offer_accepted_at": joined,
                    "note": "Демо-продавец тестового сервера",
                    "reviewed_at": joined,
                    "approved_at": joined,
                    "created_at": joined,
                    "updated_at": joined,
                },
            )
            made["sellers"] += 1

        for n, data in enumerate(PRODUCTS, start=1):
            category_id = categories[data["category"]]
            published = now - timedelta(days=3 if data["new"] else 30 + n * 5)
            product_id = demo._insert(
                "market_products",
                {
                    "seller_id": sellers[data["seller"]],
                    "category_id": category_id,
                    "slug": data["slug"],
                    "title": data["title"],
                    "description": data["description"],
                    "locale": "ru",
                    "status": "active",
                    "ikpu": f"99{n:015d}",
                    # Сводка — сразу (в продаже — только с ценой); refresh ниже сверит
                    "price": data["price"] * 100,
                    "old_price": data["old"] * 100 if data["old"] else None,
                    "stock": data["stock"],
                    "rating": data["rating"],
                    "reviews_count": data["reviews"],
                    "sold_count": data["sold"],
                    "views_count": data["sold"] * 4,
                    "submitted_at": published,
                    "published_at": published,
                    "approved_at": published,
                    "moderated_at": published,
                    "created_at": published,
                    "updated_at": published,
                },
            )

            # Каждое сочетание выбора — свой вариант (у товара без выбора — один, {})
            axes = data["variants"]
            picks = [dict(zip(axes, combo, strict=True)) for combo in combinations(*axes.values())]
            for sort, (options, stock) in enumerate(
                zip(picks, _split(data["stock"], len(picks)), strict=True)
            ):
                variant_id = demo._insert(
                    "market_product_variants",
                    {
                        "product_id": product_id,
                        "options": json.dumps(options, ensure_ascii=False),
                        "sku": f"{data['slug'][:50]}-{sort + 1}",
                        "price": data["price"] * 100,
                        "old_price": data["old"] * 100 if data["old"] else None,
                        # Остаток — только приёмкой поставки (_receive ниже)
                        "stock": 0,
                        "sort": sort,
                    },
                )
                made["variants"] += 1

                if stock:
                    arrivals.setdefault(sellers[data["seller"]], []).append(
                        (product_id, variant_id, stock)
                    )

            for name, value in data["specs"]:
                demo._rows(
                    "insert into market_product_values (product_id, attribute_id, value_text) "
                    "values (%s, %s, %s) on conflict do nothing returning product_id",
                    [product_id, _attribute(category_id, name), value],
                )

            products.refresh(product_id)
            made["products"] += 1

        made["supplies"] = _receive(arrivals, now)

    return made


#: Демо-склад — код с «demo-», как у демо-пунктов выдачи
WAREHOUSE = ("demo-bts", "Склад BTS (демо)", "Сергелийский район, ул. Янги Сергели, 1")


def _receive(arrivals: dict[int, list[tuple[int, int, int]]], now: datetime) -> int:
    """
    Остаток демо-товаров — так же, как у настоящих продавцов: принятая
    поставка на демо-склад и движение «receipt» по каждой строке
    (savdex/market/warehouse.py). Правки остатка в обход склада нет.
    Итог — сколько поставок заведено.
    """
    from savdex.market import warehouse

    code, name, address = WAREHOUSE
    found = demo._rows(
        "insert into market_warehouses (code, name, address, city) "
        "values (%s, %s, %s, 'Ташкент') on conflict (code) do nothing returning id",
        [code, name, address],
    ) or demo._rows("select id from market_warehouses where code = %s", [code])
    store = int(found[0][0])
    # Кто «принял» поставку — первый сотрудник админки, иначе первый пользователь
    staff = demo._rows("select id from users order by is_admin desc, id limit 1") or [
        (
            demo._insert(
                "users",
                {
                    "name": "Склад (демо)",
                    "email": f"stock@{demo.EMAIL_DOMAIN}",
                    "password": "!",
                    "status": "active",
                    "created_at": now,
                    "updated_at": now,
                },
            ),
        )
    ]
    receiver = int(staff[0][0])
    arrived = now - timedelta(days=7)

    for seller_id, lines in sorted(arrivals.items()):
        supply = demo._insert(
            "market_supplies",
            {
                "number": f"DEMO{seller_id:08d}",
                "seller_id": seller_id,
                "warehouse_id": store,
                "status": "received",
                "note": "Демо-поставка тестового сервера",
                "submitted_at": arrived,
                "received_at": arrived,
                "received_by": receiver,
                "created_at": arrived,
                "updated_at": arrived,
            },
        )

        for product_id, variant_id, quantity in lines:
            item = demo._insert(
                "market_supply_items",
                {
                    "supply_id": supply,
                    "seller_id": seller_id,
                    "product_id": product_id,
                    "variant_id": variant_id,
                    "quantity_declared": quantity,
                    "quantity_accepted": quantity,
                    "quantity_defect": 0,
                    "created_at": arrived,
                    "updated_at": arrived,
                },
            )
            warehouse.move(
                store,
                variant_id,
                "receipt",
                quantity,
                actor_user_id=receiver,
                supply_item_id=item,
            )

    return len(arrivals)
