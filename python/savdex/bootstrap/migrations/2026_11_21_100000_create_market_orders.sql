-- Маркетплейс SavdEx, заказ — этап 1 (ТЗ 18.11, разделы 7 и 8): пункты
-- выдачи, заказ с частями по продавцам, позиции с копией цены, история
-- статусов и журнал денег. Оплата Uzum, склад BTS, код выдачи и касса —
-- следующими миграциями (docs/marketplace.md, docs/marketplace-security.md).
--
-- Деньги — целыми тийинами (bigint). Всё, на что ссылаются деньги и
-- история, удаляется только вручную и по порядку: внешние ключи —
-- on delete restrict.

-- ── Пункты выдачи ──────────────────────────────────────────────────
-- Пока только Ташкент; список пунктов BTS не решён — пункты заводит
-- администратор, миграция их не создаёт. code — короткий код пункта
-- (в заказе и в ответах API), его не меняют.
create table market_pickup_points (
    id bigserial primary key,
    code varchar(32) not null,
    name varchar(200) not null,
    address varchar(500) not null,
    city varchar(64) not null default 'Ташкент',
    is_active boolean not null default true,
    sort integer not null default 0,
    created_at timestamp(0) without time zone not null default (now() at time zone 'utc'),
    updated_at timestamp(0) without time zone not null default (now() at time zone 'utc'),
    constraint market_pickup_points_code_unique unique (code),
    constraint market_pickup_points_code_check check (code ~ '^[a-z0-9]+(-[a-z0-9]+)*$')
);

-- ── Заказ ──────────────────────────────────────────────────────────
-- Один заказ покупателя на всю корзину; деньги каждого продавца — в своей
-- части (market_order_parts). number — случайный код (не id и не время):
-- по нему заказ видят покупатель и продавец, чужой номер ничего не
-- подсказывает. Пункт выдачи — ссылкой и копией названия и адреса на
-- момент заказа.
--
-- status: created — оформлен (ждёт оплаты картой), paid — оплачен картой,
-- cash_on_pickup — оплата при получении, assembling — собирается,
-- in_transit — едет в пункт, ready — можно забрать, issued — выдан,
-- cancelled — отменён, refund_pending — ждёт возврата денег, refunded —
-- деньги вернули. Переходы — только savdex/market/orders.py, условным
-- обновлением «where status = ожидаемый».
--
-- reserve_released_at — когда резерв остатка снят (отмена, истечение):
-- снимается ровно один раз. pickup_code_hash — хеш кода выдачи
-- (следующий этап, вместе с ПВЗ).
create table market_orders (
    id bigserial primary key,
    number varchar(16) not null,
    buyer_user_id bigint not null references users (id) on delete restrict,
    status varchar(20) not null default 'created',
    payment_method varchar(8) not null,
    pickup_point_id bigint not null references market_pickup_points (id) on delete restrict,
    pickup_point_name varchar(200) not null,
    pickup_point_address varchar(500) not null,
    items_total bigint not null,
    delivery_total bigint not null default 0,
    total bigint not null,
    commission_total bigint not null default 0,
    pickup_code_hash varchar(255),
    paid_at timestamp(0) without time zone,
    cancelled_at timestamp(0) without time zone,
    cancel_reason varchar(500),
    issued_at timestamp(0) without time zone,
    reserve_released_at timestamp(0) without time zone,
    created_at timestamp(0) without time zone not null default (now() at time zone 'utc'),
    updated_at timestamp(0) without time zone not null default (now() at time zone 'utc'),
    constraint market_orders_number_unique unique (number),
    constraint market_orders_number_check check (number ~ '^[0-9A-Z]{8,16}$'),
    constraint market_orders_status_check check (status in (
        'created', 'paid', 'cash_on_pickup', 'assembling', 'in_transit', 'ready', 'issued',
        'cancelled', 'refund_pending', 'refunded'
    )),
    constraint market_orders_payment_method_check check (payment_method in ('card', 'cash')),
    constraint market_orders_items_total_check check (items_total > 0),
    constraint market_orders_delivery_total_check check (delivery_total >= 0),
    constraint market_orders_total_check check (total = items_total + delivery_total),
    constraint market_orders_commission_check
        check (commission_total >= 0 and commission_total <= items_total)
);

create index market_orders_buyer_index on market_orders (buyer_user_id, created_at desc);
create index market_orders_status_index on market_orders (status, created_at);

-- ── Части заказа — по продавцу ─────────────────────────────────────
-- subtotal — сумма позиций продавца, commission — комиссия площадки с
-- неё; продавцу причитается subtotal - commission.
create table market_order_parts (
    id bigserial primary key,
    order_id bigint not null references market_orders (id) on delete restrict,
    seller_id bigint not null references market_sellers (id) on delete restrict,
    status varchar(20) not null default 'created',
    subtotal bigint not null,
    commission bigint not null default 0,
    created_at timestamp(0) without time zone not null default (now() at time zone 'utc'),
    updated_at timestamp(0) without time zone not null default (now() at time zone 'utc'),
    constraint market_order_parts_unique unique (order_id, seller_id),
    constraint market_order_parts_status_check check (status in (
        'created', 'paid', 'cash_on_pickup', 'assembling', 'in_transit', 'ready', 'issued',
        'cancelled', 'refund_pending', 'refunded'
    )),
    constraint market_order_parts_subtotal_check check (subtotal > 0),
    constraint market_order_parts_commission_check check (commission >= 0 and commission <= subtotal)
);

create index market_order_parts_seller_index on market_order_parts (seller_id, created_at desc);

-- ── Позиции ────────────────────────────────────────────────────────
-- Копия на момент покупки: название, выбор (options), ИКПУ, цена и
-- процент комиссии. Дальше заказ живёт на копии — правка товара его не
-- меняет.
create table market_order_items (
    id bigserial primary key,
    order_id bigint not null references market_orders (id) on delete restrict,
    part_id bigint not null references market_order_parts (id) on delete restrict,
    product_id bigint not null references market_products (id) on delete restrict,
    variant_id bigint not null references market_product_variants (id) on delete restrict,
    title varchar(200) not null,
    options jsonb not null default '{}'::jsonb,
    ikpu varchar(17),
    price bigint not null,
    quantity integer not null,
    line_total bigint not null,
    commission_percent numeric(5, 2) not null,
    commission bigint not null,
    created_at timestamp(0) without time zone not null default (now() at time zone 'utc'),
    constraint market_order_items_unique unique (order_id, variant_id),
    constraint market_order_items_price_check check (price > 0),
    constraint market_order_items_quantity_check check (quantity between 1 and 99),
    constraint market_order_items_line_total_check check (line_total = price * quantity),
    constraint market_order_items_percent_check
        check (commission_percent >= 0 and commission_percent <= 100),
    constraint market_order_items_commission_check
        check (commission >= 0 and commission <= line_total)
);

create index market_order_items_part_index on market_order_items (part_id);
create index market_order_items_variant_index on market_order_items (variant_id);

-- ── История статусов ───────────────────────────────────────────────
-- Только дописывается. part_id — переход одной части (у продавца), без
-- него — всего заказа. actor: buyer, seller, staff, system (расписание).
create table market_order_events (
    id bigserial primary key,
    order_id bigint not null references market_orders (id) on delete restrict,
    part_id bigint references market_order_parts (id) on delete restrict,
    from_status varchar(20),
    to_status varchar(20) not null,
    actor varchar(16) not null,
    actor_user_id bigint references users (id) on delete restrict,
    note varchar(500),
    created_at timestamp(0) without time zone not null default (now() at time zone 'utc'),
    constraint market_order_events_actor_check
        check (actor in ('buyer', 'seller', 'staff', 'system'))
);

create index market_order_events_order_index on market_order_events (order_id, id);

-- ── Журнал денег ───────────────────────────────────────────────────
-- Двойная запись: каждое движение — группа строк (entry_group) с суммой
-- ноль; amount — тийины со знаком (плюс — дебет, минус — кредит). Счета
-- (account) — savdex/market/orders.py, ACCOUNTS. Только дописывается:
-- у роли приложения нет update и delete, и триггер запрещает их всем.
-- Ошибочную запись исправляет новая группа с обратными знаками.
create table market_ledger (
    id bigserial primary key,
    entry_group uuid not null,
    account varchar(32) not null,
    order_id bigint references market_orders (id) on delete restrict,
    part_id bigint references market_order_parts (id) on delete restrict,
    seller_id bigint references market_sellers (id) on delete restrict,
    amount bigint not null,
    memo varchar(200),
    created_at timestamp(0) without time zone not null default (now() at time zone 'utc'),
    constraint market_ledger_amount_check check (amount <> 0),
    constraint market_ledger_account_check check (account in (
        'buyer_receivable', 'gateway_clearing', 'cash_collected', 'seller_payable',
        'commission_revenue', 'refund_payable'
    ))
);

create index market_ledger_group_index on market_ledger (entry_group);
create index market_ledger_order_index on market_ledger (order_id);
create index market_ledger_seller_index on market_ledger (seller_id, account);

-- Группа сходится в ноль — проверка в конце транзакции (deferred): строки
-- группы вставляются по одной
create or replace function market_ledger_balanced() returns trigger
language plpgsql as $$
begin
    if (select coalesce(sum(amount), 0) from market_ledger where entry_group = new.entry_group) <> 0
    then
        raise exception 'market_ledger: группа % не сходится в ноль', new.entry_group
            using errcode = 'check_violation';
    end if;

    return null;
end $$;

create constraint trigger market_ledger_balanced
    after insert on market_ledger
    deferrable initially deferred
    for each row execute function market_ledger_balanced();

-- Журнал денег и история статусов — только дописываются, даже владельцу
create or replace function market_append_only() returns trigger
language plpgsql as $$
begin
    raise exception '%: записи только дописываются', tg_table_name
        using errcode = 'insufficient_privilege';
end $$;

create trigger market_ledger_append_only
    before update or delete on market_ledger
    for each row execute function market_append_only();

create trigger market_order_events_append_only
    before update or delete on market_order_events
    for each row execute function market_append_only();

-- ── Права роли Django ──────────────────────────────────────────────
-- Заказы, части, позиции и пункты — читать, заводить, менять статус;
-- история и журнал денег — только читать и дописывать.
do $$ begin
    if exists (select from pg_roles where rolname = 'savdex_django') then
        grant select, insert, update on
            market_orders, market_order_parts, market_order_items, market_pickup_points
        to savdex_django;
        grant select, insert on market_order_events, market_ledger to savdex_django;
        revoke update, delete, truncate on market_order_events, market_ledger from savdex_django;
        grant usage on sequence
            market_pickup_points_id_seq, market_orders_id_seq, market_order_parts_id_seq,
            market_order_items_id_seq, market_order_events_id_seq, market_ledger_id_seq
        to savdex_django;
    end if;
end $$;
