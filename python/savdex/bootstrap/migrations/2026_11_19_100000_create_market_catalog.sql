-- Маркетплейс SavdEx, этап 1 (ТЗ 18.11, разделы 5 и 11.2): каталог товаров,
-- продавцы, избранное и корзина. Заказы, оплата, склад BTS, ПВЗ и касса —
-- следующими миграциями (docs/marketplace.md).
--
-- Товар — не объявление: у него цена, остаток и кнопка «В корзину».
-- Поэтому всё в своих таблицах market_*, объявления не тронуты.
--
-- Деньги — целыми тийинами (1 сум = 100 тийин), bigint: без дробей и
-- округлений. Остаток и резерв не уходят в минус, резерв не больше остатка —
-- это держит сама база, а не только код.

-- ── Категории ──────────────────────────────────────────────────────
-- Своё дерево для товаров (не категории объявлений). name — по-русски,
-- names — остальные языки: {"uz": "...", "en": "..."}. Глубина — до трёх
-- уровней, её проверяет админка (savdex/market/admin.py).
create table market_categories (
    id bigserial primary key,
    parent_id bigint references market_categories (id) on delete restrict,
    slug varchar(80) not null,
    name varchar(120) not null,
    names jsonb not null default '{}'::jsonb,
    icon varchar(16),
    sort integer not null default 0,
    is_active boolean not null default true,
    created_at timestamp(0) without time zone not null default (now() at time zone 'utc'),
    updated_at timestamp(0) without time zone not null default (now() at time zone 'utc'),
    constraint market_categories_slug_unique unique (slug),
    constraint market_categories_slug_check check (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
    constraint market_categories_parent_check check (parent_id is null or parent_id <> id)
);

create index market_categories_parent_index on market_categories (parent_id, sort);

-- ── Характеристики категории (для фильтров) ────────────────────────
-- kind: text — строка, number — число (unit — единица: «ГБ», «кг»),
-- choice — один из options: [{"value": "red", "name": "Красный",
-- "names": {"uz": "..."}}]. Характеристика родителя действует и в
-- подкатегориях.
create table market_attributes (
    id bigserial primary key,
    category_id bigint not null references market_categories (id) on delete cascade,
    key varchar(40) not null,
    name varchar(120) not null,
    names jsonb not null default '{}'::jsonb,
    kind varchar(16) not null default 'text',
    options jsonb not null default '[]'::jsonb,
    unit varchar(16),
    is_filter boolean not null default true,
    is_required boolean not null default false,
    sort integer not null default 0,
    created_at timestamp(0) without time zone not null default (now() at time zone 'utc'),
    updated_at timestamp(0) without time zone not null default (now() at time zone 'utc'),
    constraint market_attributes_key_unique unique (category_id, key),
    constraint market_attributes_key_check check (key ~ '^[a-z][a-z0-9_]{0,39}$'),
    constraint market_attributes_kind_check check (kind in ('text', 'number', 'choice'))
);

-- ── Продавцы ───────────────────────────────────────────────────────
-- Продавец — компания SavdEx (та же карточка), одна запись на компанию.
-- Пока OneID нет — заявка и ручная проверка модератором по документам
-- компании (company_documents, раздел «Документы на проверку»): своих
-- копий документов маркетплейс не хранит. verified_via — чем подтверждён:
-- documents сейчас, oneid — когда дадут API (oneid_tin — ИНН из OneID).
create table market_sellers (
    id bigserial primary key,
    company_id bigint not null references companies (id) on delete restrict,
    user_id bigint references users (id) on delete set null,
    status varchar(16) not null default 'pending',
    verified_via varchar(16),
    oneid_tin varchar(14),
    offer_version varchar(32),
    offer_accepted_at timestamp(0) without time zone,
    note varchar(1000),
    reject_reason varchar(1000),
    reviewed_by bigint references users (id) on delete set null,
    reviewed_at timestamp(0) without time zone,
    approved_at timestamp(0) without time zone,
    blocked_at timestamp(0) without time zone,
    created_at timestamp(0) without time zone not null default (now() at time zone 'utc'),
    updated_at timestamp(0) without time zone not null default (now() at time zone 'utc'),
    constraint market_sellers_company_unique unique (company_id),
    constraint market_sellers_status_check
        check (status in ('pending', 'approved', 'rejected', 'blocked')),
    constraint market_sellers_verified_via_check
        check (verified_via is null or verified_via in ('documents', 'oneid')),
    constraint market_sellers_approved_check
        check (status <> 'approved' or (approved_at is not null and verified_via is not null))
);

create index market_sellers_status_index on market_sellers (status, created_at);

-- ── Товары ─────────────────────────────────────────────────────────
-- status: draft — черновик продавца, pending — на модерации, active — в
-- продаже, rejected — отклонён (reject_reason), blocked — снят модератором,
-- hidden — снят с продажи самим продавцом. approved_at — когда модератор
-- одобрил товар: по ним считаются «первые N товаров нового продавца».
--
-- price, old_price, stock — сводка по включённым вариантам (самая низкая
-- цена, её старая цена, сумма остатков): для сортировки и фильтров без
-- подсчёта на каждом запросе. Пересчитывает savdex/market/products.py
-- после каждой правки вариантов.
--
-- locale — язык, на котором написал продавец (ТЗ, раздел 3: карточки —
-- на языке продавца). search — поиск по названию и описанию в самом
-- PostgreSQL, словарь simple: без внешних сервисов, данные в Узбекистане.
create table market_products (
    id bigserial primary key,
    seller_id bigint not null references market_sellers (id) on delete restrict,
    category_id bigint not null references market_categories (id) on delete restrict,
    slug varchar(80),
    title varchar(200) not null,
    description text,
    locale varchar(8) not null default 'ru',
    status varchar(16) not null default 'draft',
    reject_reason varchar(1000),
    ikpu varchar(17),
    barcode varchar(32),
    weight_g integer,
    length_mm integer,
    width_mm integer,
    height_mm integer,
    price bigint,
    old_price bigint,
    stock integer not null default 0,
    rating numeric(3, 2) not null default 0,
    reviews_count integer not null default 0,
    sold_count integer not null default 0,
    views_count integer not null default 0,
    submitted_at timestamp(0) without time zone,
    published_at timestamp(0) without time zone,
    approved_at timestamp(0) without time zone,
    moderated_by bigint references users (id) on delete set null,
    moderated_at timestamp(0) without time zone,
    created_at timestamp(0) without time zone not null default (now() at time zone 'utc'),
    updated_at timestamp(0) without time zone not null default (now() at time zone 'utc'),
    search tsvector generated always as (
        setweight(to_tsvector('simple'::regconfig, coalesce(title, '')), 'A')
        || setweight(to_tsvector('simple'::regconfig, coalesce(description, '')), 'B')
    ) stored,
    constraint market_products_slug_unique unique (slug),
    constraint market_products_slug_check check (slug is null or slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
    constraint market_products_status_check
        check (status in ('draft', 'pending', 'active', 'rejected', 'blocked', 'hidden')),
    constraint market_products_locale_check check (locale in ('ru', 'uz', 'en', 'zh', 'tr')),
    constraint market_products_ikpu_check check (ikpu is null or ikpu ~ '^[0-9]{17}$'),
    constraint market_products_barcode_check check (barcode is null or barcode ~ '^[0-9]{8,14}$'),
    constraint market_products_size_check check (
        coalesce(weight_g, 1) > 0 and coalesce(length_mm, 1) > 0
        and coalesce(width_mm, 1) > 0 and coalesce(height_mm, 1) > 0
    ),
    constraint market_products_price_check check (price is null or price > 0),
    constraint market_products_old_price_check
        check (old_price is null or (price is not null and old_price > price)),
    constraint market_products_stock_check check (stock >= 0),
    constraint market_products_rating_check check (rating >= 0 and rating <= 5),
    -- В продаже — только с ценой, адресом и ИКПУ (нужен для чека)
    constraint market_products_active_check check (
        status <> 'active' or (price is not null and slug is not null and ikpu is not null)
    )
);

create index market_products_seller_index on market_products (seller_id, status);
create index market_products_category_index on market_products (category_id, status);
create index market_products_active_new_index on market_products (published_at desc)
    where status = 'active';
create index market_products_active_price_index on market_products (price)
    where status = 'active';
create index market_products_active_sold_index on market_products (sold_count desc)
    where status = 'active';
create index market_products_search_index on market_products using gin (search);

-- ── Фото товара ────────────────────────────────────────────────────
-- До 10 на товар (держит savdex/market/products.py), первое по sort —
-- обложка. Файлы — WebP на публичном диске (savdex/images.py).
create table market_product_images (
    id bigserial primary key,
    product_id bigint not null references market_products (id) on delete cascade,
    path varchar(190) not null,
    sort integer not null default 0,
    created_at timestamp(0) without time zone not null default (now() at time zone 'utc')
);

create index market_product_images_product_index on market_product_images (product_id, sort);

-- ── Варианты ───────────────────────────────────────────────────────
-- У каждого товара — хотя бы один вариант: цена и остаток живут здесь.
-- options — выбор покупателя: {"color": "Чёрный", "memory": "128 ГБ"};
-- у товара без выбора — {}. reserved — отложено под оформленные заказы
-- (заполнится с заказами), продать можно stock - reserved.
create table market_product_variants (
    id bigserial primary key,
    product_id bigint not null references market_products (id) on delete cascade,
    options jsonb not null default '{}'::jsonb,
    sku varchar(64),
    price bigint not null,
    old_price bigint,
    stock integer not null default 0,
    reserved integer not null default 0,
    is_active boolean not null default true,
    sort integer not null default 0,
    created_at timestamp(0) without time zone not null default (now() at time zone 'utc'),
    updated_at timestamp(0) without time zone not null default (now() at time zone 'utc'),
    constraint market_product_variants_price_check check (price > 0),
    constraint market_product_variants_old_price_check
        check (old_price is null or old_price > price),
    constraint market_product_variants_stock_check check (stock >= 0),
    constraint market_product_variants_reserved_check check (reserved >= 0 and reserved <= stock),
    constraint market_product_variants_options_unique unique (product_id, options)
);

create index market_product_variants_product_index on market_product_variants (product_id, sort);

-- ── Значения характеристик товара ──────────────────────────────────
-- Одна строка — одна характеристика: число — в value_number (фильтр «от и
-- до»), строка и выбор — в value_text.
create table market_product_values (
    product_id bigint not null references market_products (id) on delete cascade,
    attribute_id bigint not null references market_attributes (id) on delete cascade,
    value_text varchar(200),
    value_number numeric(14, 3),
    primary key (product_id, attribute_id),
    constraint market_product_values_one_check
        check ((value_text is null) <> (value_number is null))
);

create index market_product_values_text_index on market_product_values (attribute_id, value_text);
create index market_product_values_number_index on market_product_values (attribute_id, value_number);

-- ── Избранное покупателя ───────────────────────────────────────────
create table market_favorites (
    user_id bigint not null references users (id) on delete cascade,
    product_id bigint not null references market_products (id) on delete cascade,
    created_at timestamp(0) without time zone not null default (now() at time zone 'utc'),
    primary key (user_id, product_id)
);

create index market_favorites_product_index on market_favorites (product_id);

-- ── Корзина ────────────────────────────────────────────────────────
-- На сервере, у входа: одна и та же на savdex.uz, поддомене и телефоне.
-- Цена и остаток в корзине не хранятся — их всегда берут из варианта.
create table market_cart_items (
    id bigserial primary key,
    user_id bigint not null references users (id) on delete cascade,
    variant_id bigint not null references market_product_variants (id) on delete cascade,
    quantity integer not null,
    created_at timestamp(0) without time zone not null default (now() at time zone 'utc'),
    updated_at timestamp(0) without time zone not null default (now() at time zone 'utc'),
    constraint market_cart_items_unique unique (user_id, variant_id),
    constraint market_cart_items_quantity_check check (quantity between 1 and 99)
);

-- ── Стартовое дерево категорий ─────────────────────────────────────
-- Двенадцать разделов и их подразделы — как в демо Максуда
-- (resources/js/market/demo.ts, ветка maksud). Дальше дерево правят в
-- админке. Повторный запуск ничего не дублирует.
insert into market_categories (slug, name, names, icon, sort) values
    ('electronics', 'Электроника', '{"uz": "Elektronika", "en": "Electronics"}', '📱', 10),
    ('appliances', 'Бытовая техника', '{"uz": "Maishiy texnika", "en": "Appliances"}', '🔌', 20),
    ('clothes', 'Одежда', '{"uz": "Kiyim", "en": "Clothes"}', '👕', 30),
    ('shoes', 'Обувь', '{"uz": "Poyabzal", "en": "Shoes"}', '👟', 40),
    ('home', 'Дом и интерьер', '{"uz": "Uy va interyer", "en": "Home and interior"}', '🛋️', 50),
    ('beauty', 'Красота', '{"uz": "Go''zallik", "en": "Beauty"}', '💄', 60),
    ('kids', 'Детям', '{"uz": "Bolalar uchun", "en": "Kids"}', '🧸', 70),
    ('food', 'Продукты', '{"uz": "Oziq-ovqat", "en": "Food"}', '🥗', 80),
    ('tools', 'Ремонт и стройка', '{"uz": "Ta''mir va qurilish", "en": "Repair and construction"}', '🛠️', 90),
    ('auto', 'Авто', '{"uz": "Avto", "en": "Auto"}', '🚗', 100),
    ('sport', 'Спорт и отдых', '{"uz": "Sport va dam olish", "en": "Sport and leisure"}', '⚽', 110),
    ('office', 'Канцтовары', '{"uz": "Kanselyariya", "en": "Stationery"}', '📚', 120)
on conflict (slug) do nothing;

insert into market_categories (parent_id, slug, name, names, sort)
select parent.id, child.slug, child.name, child.names::jsonb, child.sort
from (values
    ('electronics', 'smartphones', 'Смартфоны', '{"uz": "Smartfonlar", "en": "Smartphones"}', 10),
    ('electronics', 'headphones', 'Наушники', '{"uz": "Quloqchinlar", "en": "Headphones"}', 20),
    ('electronics', 'smartwatches', 'Умные часы', '{"uz": "Aqlli soatlar", "en": "Smartwatches"}', 30),
    ('electronics', 'laptops', 'Ноутбуки', '{"uz": "Noutbuklar", "en": "Laptops"}', 40),
    ('electronics', 'gadget-accessories', 'Аксессуары', '{"uz": "Aksessuarlar", "en": "Accessories"}', 50),
    ('appliances', 'kitchen-appliances', 'Для кухни', '{"uz": "Oshxona uchun", "en": "For the kitchen"}', 10),
    ('appliances', 'home-appliances', 'Для дома', '{"uz": "Uy uchun", "en": "For the home"}', 20),
    ('appliances', 'climate', 'Климат', '{"uz": "Iqlim texnikasi", "en": "Climate"}', 30),
    ('appliances', 'personal-care', 'Красота и уход', '{"uz": "Go''zallik va parvarish", "en": "Personal care"}', 40),
    ('clothes', 'women-clothes', 'Женская', '{"uz": "Ayollar uchun", "en": "Women"}', 10),
    ('clothes', 'men-clothes', 'Мужская', '{"uz": "Erkaklar uchun", "en": "Men"}', 20),
    ('clothes', 'kids-clothes', 'Детская', '{"uz": "Bolalar uchun", "en": "Kids"}', 30),
    ('clothes', 'outerwear', 'Верхняя одежда', '{"uz": "Ustki kiyim", "en": "Outerwear"}', 40),
    ('shoes', 'women-shoes', 'Женская', '{"uz": "Ayollar uchun", "en": "Women"}', 10),
    ('shoes', 'men-shoes', 'Мужская', '{"uz": "Erkaklar uchun", "en": "Men"}', 20),
    ('shoes', 'kids-shoes', 'Детская', '{"uz": "Bolalar uchun", "en": "Kids"}', 30),
    ('shoes', 'sport-shoes', 'Спортивная', '{"uz": "Sport poyabzali", "en": "Sport"}', 40),
    ('home', 'textile', 'Текстиль', '{"uz": "Tekstil", "en": "Textile"}', 10),
    ('home', 'tableware', 'Посуда', '{"uz": "Idish-tovoq", "en": "Tableware"}', 20),
    ('home', 'furniture', 'Мебель', '{"uz": "Mebel", "en": "Furniture"}', 30),
    ('home', 'lighting', 'Освещение', '{"uz": "Yoritish", "en": "Lighting"}', 40),
    ('home', 'storage', 'Хранение', '{"uz": "Saqlash", "en": "Storage"}', 50),
    ('beauty', 'face-care', 'Уход за лицом', '{"uz": "Yuz parvarishi", "en": "Face care"}', 10),
    ('beauty', 'hair', 'Волосы', '{"uz": "Soch", "en": "Hair"}', 20),
    ('beauty', 'makeup', 'Макияж', '{"uz": "Pardoz", "en": "Makeup"}', 30),
    ('beauty', 'perfume', 'Парфюмерия', '{"uz": "Atir-upa", "en": "Perfume"}', 40),
    ('kids', 'toys', 'Игрушки', '{"uz": "O''yinchoqlar", "en": "Toys"}', 10),
    ('kids', 'baby', 'Для малышей', '{"uz": "Chaqaloqlar uchun", "en": "Baby"}', 20),
    ('kids', 'school', 'Школа', '{"uz": "Maktab", "en": "School"}', 30),
    ('kids', 'baby-food', 'Детское питание', '{"uz": "Bolalar ovqati", "en": "Baby food"}', 40),
    ('food', 'tea-coffee', 'Чай и кофе', '{"uz": "Choy va qahva", "en": "Tea and coffee"}', 10),
    ('food', 'sweets', 'Сладости', '{"uz": "Shirinliklar", "en": "Sweets"}', 20),
    ('food', 'dried-fruits-nuts', 'Сухофрукты и орехи', '{"uz": "Quruq mevalar va yong''oqlar", "en": "Dried fruits and nuts"}', 30),
    ('food', 'grocery', 'Бакалея', '{"uz": "Baqqollik", "en": "Grocery"}', 40),
    ('tools', 'hand-tools', 'Инструменты', '{"uz": "Asboblar", "en": "Tools"}', 10),
    ('tools', 'plumbing', 'Сантехника', '{"uz": "Santexnika", "en": "Plumbing"}', 20),
    ('tools', 'electrical', 'Электрика', '{"uz": "Elektr jihozlari", "en": "Electrical"}', 30),
    ('tools', 'finishing', 'Отделка', '{"uz": "Pardozlash ishlari", "en": "Finishing"}', 40),
    ('auto', 'car-accessories', 'Аксессуары', '{"uz": "Aksessuarlar", "en": "Accessories"}', 10),
    ('auto', 'oils-chemicals', 'Масла и химия', '{"uz": "Moylar va kimyo", "en": "Oils and chemicals"}', 20),
    ('auto', 'tyres-wheels', 'Шины и диски', '{"uz": "Shinalar va disklar", "en": "Tyres and wheels"}', 30),
    ('sport', 'fitness', 'Фитнес', '{"uz": "Fitnes", "en": "Fitness"}', 10),
    ('sport', 'tourism', 'Туризм', '{"uz": "Turizm", "en": "Tourism"}', 20),
    ('sport', 'bicycles', 'Велосипеды', '{"uz": "Velosipedlar", "en": "Bicycles"}', 30),
    ('sport', 'bags-backpacks', 'Сумки и рюкзаки', '{"uz": "Sumkalar va ryukzaklar", "en": "Bags and backpacks"}', 40),
    ('office', 'paper', 'Бумага', '{"uz": "Qog''oz", "en": "Paper"}', 10),
    ('office', 'writing', 'Письменные', '{"uz": "Yozuv buyumlari", "en": "Writing"}', 20),
    ('office', 'office-supplies', 'Для офиса', '{"uz": "Ofis uchun", "en": "Office supplies"}', 30),
    ('office', 'books', 'Книги', '{"uz": "Kitoblar", "en": "Books"}', 40)
) as child (parent, slug, name, names, sort)
join market_categories parent on parent.slug = child.parent
on conflict (slug) do nothing;

-- ── Права роли Django ──────────────────────────────────────────────
do $$ begin
    if exists (select from pg_roles where rolname = 'savdex_django') then
        grant select, insert, update, delete on
            market_categories, market_attributes, market_sellers, market_products,
            market_product_images, market_product_variants, market_product_values,
            market_favorites, market_cart_items
        to savdex_django;
        grant usage on sequence
            market_categories_id_seq, market_attributes_id_seq, market_sellers_id_seq,
            market_products_id_seq, market_product_images_id_seq,
            market_product_variants_id_seq, market_cart_items_id_seq
        to savdex_django;
    end if;
end $$;
