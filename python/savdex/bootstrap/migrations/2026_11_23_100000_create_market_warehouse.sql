-- Маркетплейс SavdEx, склад и пункты выдачи — схема (ТЗ 18.11, разделы 6 и
-- 11.3; решение Тимура 23.11 «Склад маркетплейса — свой интерфейс»: приёмку,
-- остатки, отгрузки, выдачу и возвраты отмечают сотрудники склада и пунктов
-- выдачи в нашей системе, BTS не ждём).
--
-- Что здесь:
--   склады (market_warehouses) и кто на них работает;
--   поставки продавца (market_supplies, market_supply_items): заявка — что и
--     сколько везёт, приёмка — сколько принято и сколько брака;
--   движения остатка (market_stock_movements) — единственный путь изменить
--     остаток склада; только дописываются, как журнал денег;
--   остаток по складам (market_warehouse_stock) — его ведёт сама база из
--     движений, у сайта — только чтение;
--   отгрузки склад ↔ пункт выдачи (market_shipments) и заказы в них;
--   у пунктов выдачи — часы, точка на карте и кто на них работает;
--   у заказа — когда пришёл в пункт, кто выдал, попытки кода выдачи.
--
-- Остаток. market_product_variants.stock — всё, что у нас на руках: на
-- складе, в пути и в пункте выдачи (как и сейчас: остаток списывается только
-- при выдаче покупателю). Движение склада меняет и остаток склада, и stock
-- варианта — в одной транзакции, триггером; поэтому код, который перейдёт на
-- движения, перестаёт менять stock сам (выдача в orders.py, правка остатка в
-- админке). До этого перехода движений никто не пишет — существующий код
-- работает как работал. Отгрузка в пункт и возврат невостребованного остаток
-- не двигают: товар остаётся у нас, меняется только резерв (orders.py).
--
-- Только добавляет; старые таблицы — новые столбцы с пустыми значениями и
-- проверки, которые существующие строки проходят.

-- ── Склады ─────────────────────────────────────────────────────────
-- Пока один — арендованный у BTS в Ташкенте; заводит администратор, миграция
-- не создаёт (адреса ещё нет). code — короткий код, его не меняют.
create table market_warehouses (
    id bigserial primary key,
    code varchar(32) not null,
    name varchar(200) not null,
    address varchar(500) not null,
    city varchar(64) not null default 'Ташкент',
    is_active boolean not null default true,
    sort integer not null default 0,
    created_at timestamp(0) without time zone not null default (now() at time zone 'utc'),
    updated_at timestamp(0) without time zone not null default (now() at time zone 'utc'),
    constraint market_warehouses_code_unique unique (code),
    constraint market_warehouses_code_check check (code ~ '^[a-z0-9]+(-[a-z0-9]+)*$')
);

-- ── Кто где работает ───────────────────────────────────────────────
-- Роль «Склад» и «Пункт выдачи» даёт раздел админки (savdex/access.py);
-- эти таблицы — где именно: сотрудник видит и отмечает только своё место.
create table market_warehouse_staff (
    warehouse_id bigint not null references market_warehouses (id) on delete cascade,
    user_id bigint not null references users (id) on delete cascade,
    created_at timestamp(0) without time zone not null default (now() at time zone 'utc'),
    primary key (warehouse_id, user_id)
);

create index market_warehouse_staff_user_index on market_warehouse_staff (user_id);

create table market_pickup_point_staff (
    pickup_point_id bigint not null references market_pickup_points (id) on delete cascade,
    user_id bigint not null references users (id) on delete cascade,
    created_at timestamp(0) without time zone not null default (now() at time zone 'utc'),
    primary key (pickup_point_id, user_id)
);

create index market_pickup_point_staff_user_index on market_pickup_point_staff (user_id);

-- ── Пункты выдачи: часы и точка на карте ───────────────────────────
-- ТЗ, раздел 6: адрес, часы, точка на карте. hours — как показать
-- покупателю («Пн–Сб 9:00–20:00»). Координаты — обе или ни одной, в
-- пределах Узбекистана.
alter table market_pickup_points
    add column hours varchar(200),
    add column latitude numeric(9, 6),
    add column longitude numeric(9, 6),
    add constraint market_pickup_points_point_check check (
        (latitude is null) = (longitude is null)
        and (latitude is null or (latitude between 37 and 46 and longitude between 55 and 74))
    );

-- Отгрузка помнит пункт заказа — составной ключ ниже
alter table market_orders
    add constraint market_orders_id_pickup_point_unique unique (id, pickup_point_id);

-- Поставка — товар именно этого продавца — составной ключ ниже
alter table market_products
    add constraint market_products_id_seller_unique unique (id, seller_id);

-- ── Заказ: пункт выдачи ────────────────────────────────────────────
-- ready_at — когда заказ пришёл в пункт (от него — срок «не забрал за N
-- дней»); issued_by — кто выдал. Код выдачи: его хеш уже есть
-- (pickup_code_hash); pickup_code_attempts — неверные попытки подряд,
-- pickup_code_locked_until — до какого времени ввод закрыт (перебор кодов,
-- docs/marketplace-security.md). Сколько попыток и на сколько закрывать —
-- решает код.
alter table market_orders
    add column ready_at timestamp(0) without time zone,
    add column issued_by bigint references users (id) on delete restrict,
    add column pickup_code_attempts integer not null default 0,
    add column pickup_code_locked_until timestamp(0) without time zone,
    add constraint market_orders_pickup_code_attempts_check check (pickup_code_attempts >= 0);

create index market_orders_ready_index on market_orders (ready_at) where status = 'ready';

-- ── Поставки продавца ──────────────────────────────────────────────
-- Продавец заводит заявку в кабинете (draft) и отправляет (submitted);
-- склад принимает (received) — по каждой строке сколько принято и сколько
-- брака; или отказывает (rejected, с причиной). Продавец может отменить до
-- приёмки (cancelled). number — случайный код, как у заказа: по нему
-- поставку ищут на складе. Принятое попадает в остаток движением «receipt».
create table market_supplies (
    id bigserial primary key,
    number varchar(16) not null,
    seller_id bigint not null references market_sellers (id) on delete restrict,
    warehouse_id bigint not null references market_warehouses (id) on delete restrict,
    status varchar(16) not null default 'draft',
    note varchar(1000),
    expected_at date,
    created_by bigint references users (id) on delete set null,
    submitted_at timestamp(0) without time zone,
    received_at timestamp(0) without time zone,
    received_by bigint references users (id) on delete restrict,
    cancelled_at timestamp(0) without time zone,
    rejected_at timestamp(0) without time zone,
    reject_reason varchar(1000),
    created_at timestamp(0) without time zone not null default (now() at time zone 'utc'),
    updated_at timestamp(0) without time zone not null default (now() at time zone 'utc'),
    constraint market_supplies_number_unique unique (number),
    constraint market_supplies_number_check check (number ~ '^[0-9A-Z]{8,16}$'),
    constraint market_supplies_id_seller_unique unique (id, seller_id),
    constraint market_supplies_status_check
        check (status in ('draft', 'submitted', 'received', 'rejected', 'cancelled')),
    -- У каждого шага — его время (и кто принял, почему отказали)
    constraint market_supplies_status_times_check check (
        (status = 'draft' or submitted_at is not null or status = 'cancelled')
        and ((status = 'received') = (received_at is not null))
        and ((received_at is null) = (received_by is null))
        and ((status = 'cancelled') = (cancelled_at is not null))
        and ((status = 'rejected') = (rejected_at is not null))
        and ((rejected_at is null) = (reject_reason is null))
    )
);

create index market_supplies_seller_index on market_supplies (seller_id, created_at desc);
create index market_supplies_warehouse_index on market_supplies (warehouse_id, status, created_at);

-- Строка поставки: заявлено (declared) — продавцом; принято (accepted) и
-- брак (defect) — складом при приёмке, вместе. Брак в остаток не идёт —
-- возвращается продавцу. Товар — только этого продавца и вариант — только
-- этого товара (составные ключи).
create table market_supply_items (
    id bigserial primary key,
    supply_id bigint not null,
    seller_id bigint not null,
    product_id bigint not null,
    variant_id bigint not null,
    quantity_declared integer not null,
    quantity_accepted integer,
    quantity_defect integer,
    created_at timestamp(0) without time zone not null default (now() at time zone 'utc'),
    updated_at timestamp(0) without time zone not null default (now() at time zone 'utc'),
    constraint market_supply_items_supply_fkey foreign key (supply_id, seller_id)
        references market_supplies (id, seller_id) on delete cascade,
    constraint market_supply_items_product_fkey foreign key (product_id, seller_id)
        references market_products (id, seller_id) on delete restrict,
    constraint market_supply_items_variant_fkey foreign key (variant_id, product_id)
        references market_product_variants (id, product_id) on delete restrict,
    constraint market_supply_items_unique unique (supply_id, variant_id),
    constraint market_supply_items_id_variant_unique unique (id, variant_id),
    constraint market_supply_items_declared_check check (quantity_declared between 1 and 100000),
    constraint market_supply_items_received_check check (
        (quantity_accepted is null) = (quantity_defect is null)
        and (quantity_accepted is null or (quantity_accepted >= 0 and quantity_defect >= 0))
    )
);

create index market_supply_items_variant_index on market_supply_items (variant_id);

-- ── Остаток по складам ─────────────────────────────────────────────
-- Пишет только триггер движений (market_stock_apply ниже); у сайта — чтение.
-- Не уходит в минус.
create table market_warehouse_stock (
    warehouse_id bigint not null references market_warehouses (id) on delete restrict,
    variant_id bigint not null,
    product_id bigint not null,
    quantity integer not null default 0,
    updated_at timestamp(0) without time zone not null default (now() at time zone 'utc'),
    primary key (warehouse_id, variant_id),
    constraint market_warehouse_stock_variant_fkey foreign key (variant_id, product_id)
        references market_product_variants (id, product_id) on delete restrict,
    constraint market_warehouse_stock_quantity_check check (quantity >= 0)
);

create index market_warehouse_stock_variant_index on market_warehouse_stock (variant_id);

-- ── Отгрузки склад ↔ пункт выдачи ──────────────────────────────────
-- direction: to_point — заказы едут в пункт; to_warehouse — невостребованные
-- возвращаются на склад. status: assembling — собирается, in_transit — в
-- пути, delivered — принята на месте, cancelled — не поехала.
create table market_shipments (
    id bigserial primary key,
    number varchar(16) not null,
    warehouse_id bigint not null references market_warehouses (id) on delete restrict,
    pickup_point_id bigint not null references market_pickup_points (id) on delete restrict,
    direction varchar(16) not null,
    status varchar(16) not null default 'assembling',
    created_by bigint references users (id) on delete set null,
    shipped_at timestamp(0) without time zone,
    shipped_by bigint references users (id) on delete restrict,
    delivered_at timestamp(0) without time zone,
    delivered_by bigint references users (id) on delete restrict,
    cancelled_at timestamp(0) without time zone,
    created_at timestamp(0) without time zone not null default (now() at time zone 'utc'),
    updated_at timestamp(0) without time zone not null default (now() at time zone 'utc'),
    constraint market_shipments_number_unique unique (number),
    constraint market_shipments_number_check check (number ~ '^[0-9A-Z]{8,16}$'),
    constraint market_shipments_route_unique unique (id, direction, pickup_point_id),
    constraint market_shipments_direction_check check (direction in ('to_point', 'to_warehouse')),
    constraint market_shipments_status_check
        check (status in ('assembling', 'in_transit', 'delivered', 'cancelled')),
    -- Отменить — только пока не уехала
    constraint market_shipments_status_times_check check (
        ((status in ('in_transit', 'delivered')) = (shipped_at is not null))
        and ((shipped_at is null) = (shipped_by is null))
        and ((status = 'delivered') = (delivered_at is not null))
        and ((delivered_at is null) = (delivered_by is null))
        and ((status = 'cancelled') = (cancelled_at is not null))
    )
);

create index market_shipments_point_index on market_shipments (pickup_point_id, status, created_at);
create index market_shipments_warehouse_index on market_shipments (warehouse_id, status, created_at);

-- Заказ в отгрузке. Пункт отгрузки = пункт заказа (составные ключи); в одну
-- сторону заказ едет не больше одного раза — в пункт и, если не забрали,
-- обратно. Из собираемой отгрузки заказ можно убрать (delete).
create table market_shipment_orders (
    shipment_id bigint not null,
    order_id bigint not null,
    direction varchar(16) not null,
    pickup_point_id bigint not null,
    created_at timestamp(0) without time zone not null default (now() at time zone 'utc'),
    primary key (shipment_id, order_id),
    constraint market_shipment_orders_shipment_fkey foreign key (shipment_id, direction, pickup_point_id)
        references market_shipments (id, direction, pickup_point_id) on delete cascade,
    constraint market_shipment_orders_order_fkey foreign key (order_id, pickup_point_id)
        references market_orders (id, pickup_point_id) on delete restrict,
    constraint market_shipment_orders_once_unique unique (order_id, direction)
);

-- ── Движения остатка ───────────────────────────────────────────────
-- Каждое изменение остатка склада — строка: quantity со знаком (плюс —
-- пришло, минус — ушло). Только дописываются (как журнал денег): ошибку
-- исправляет новое движение «adjust».
--
-- kind и знак:
--   receipt          + приёмка по поставке (supply_item_id);
--   customer_return  + покупатель вернул выданный товар (order_id);
--   issue            − выдан покупателю (order_id);
--   writeoff         − списание: брак, порча, потеря (reason);
--   return_to_seller − вывезен продавцу (reason);
--   adjust           ± инвентаризация, исправление ошибки (reason).
create table market_stock_movements (
    id bigserial primary key,
    warehouse_id bigint not null references market_warehouses (id) on delete restrict,
    variant_id bigint not null,
    product_id bigint not null,
    kind varchar(20) not null,
    quantity integer not null,
    supply_item_id bigint,
    order_id bigint,
    reason varchar(500),
    actor_user_id bigint references users (id) on delete restrict,
    created_at timestamp(0) without time zone not null default (now() at time zone 'utc'),
    constraint market_stock_movements_variant_fkey foreign key (variant_id, product_id)
        references market_product_variants (id, product_id) on delete restrict,
    -- Приёмка — того варианта, что в строке поставки; выдача и возврат —
    -- варианта, что в заказе
    constraint market_stock_movements_supply_item_fkey foreign key (supply_item_id, variant_id)
        references market_supply_items (id, variant_id) on delete restrict,
    constraint market_stock_movements_order_item_fkey foreign key (order_id, variant_id)
        references market_order_items (order_id, variant_id) on delete restrict,
    constraint market_stock_movements_kind_check check (kind in (
        'receipt', 'customer_return', 'issue', 'writeoff', 'return_to_seller', 'adjust'
    )),
    constraint market_stock_movements_sign_check check (
        quantity <> 0
        and (kind not in ('receipt', 'customer_return') or quantity > 0)
        and (kind not in ('issue', 'writeoff', 'return_to_seller') or quantity < 0)
    ),
    constraint market_stock_movements_ref_check check (
        (kind <> 'receipt' or supply_item_id is not null)
        and (kind not in ('issue', 'customer_return') or order_id is not null)
        and (kind not in ('writeoff', 'return_to_seller', 'adjust') or reason is not null)
    )
);

create index market_stock_movements_variant_index on market_stock_movements (variant_id, id);
create index market_stock_movements_warehouse_index on market_stock_movements (warehouse_id, created_at);
create index market_stock_movements_order_index on market_stock_movements (order_id)
    where order_id is not null;
-- Одна строка поставки — одна приёмка
create unique index market_stock_movements_receipt_unique on market_stock_movements (supply_item_id)
    where kind = 'receipt';

create trigger market_stock_movements_append_only
    before update or delete on market_stock_movements
    for each row execute function market_append_only();

-- Движение → остаток склада и остаток варианта, в той же транзакции. От
-- имени владельца (security definer): сайт пишет движение, а остаток склада
-- менять напрямую не может. Минус на складе или остаток варианта меньше
-- резерва — ошибка проверки, движение не записывается. Поэтому при выдаче
-- код сначала снимает резерв, потом пишет движение «issue».
--
-- Приёмка — ровно столько, сколько склад отметил принятым в строке
-- поставки, на склад этой поставки и только у принятой поставки.
create or replace function market_stock_apply() returns trigger
language plpgsql security definer set search_path = public, pg_temp as $$
begin
    if new.kind = 'receipt' and not exists (
        select from market_supply_items i
        join market_supplies s on s.id = i.supply_id
        where i.id = new.supply_item_id
            and s.status = 'received'
            and s.warehouse_id = new.warehouse_id
            and i.quantity_accepted = new.quantity
    ) then
        raise exception 'market_stock_movements: приёмка не совпадает с поставкой (строка %)',
            new.supply_item_id
            using errcode = 'check_violation';
    end if;

    -- Строка остатка — сначала пустая, потом прибавка: проверку «не в минус»
    -- проходит итог, а не само движение
    insert into market_warehouse_stock (warehouse_id, variant_id, product_id, quantity)
    values (new.warehouse_id, new.variant_id, new.product_id, 0)
    on conflict (warehouse_id, variant_id) do nothing;

    update market_warehouse_stock
        set quantity = quantity + new.quantity, updated_at = (now() at time zone 'utc')
        where warehouse_id = new.warehouse_id and variant_id = new.variant_id;

    update market_product_variants
        set stock = stock + new.quantity, updated_at = (now() at time zone 'utc')
        where id = new.variant_id;

    return null;
end $$;

revoke all on function market_stock_apply() from public;

create trigger market_stock_movements_apply
    after insert on market_stock_movements
    for each row execute function market_stock_apply();

-- ── Права роли Django ──────────────────────────────────────────────
-- Склады, поставки, отгрузки — читать, заводить, менять статус; убрать
-- заказ из отгрузки и сотрудника с места — delete. Движения — читать и
-- дописывать; остаток склада — только читать (пишет триггер).
do $$ begin
    if exists (select from pg_roles where rolname = 'savdex_django') then
        grant select, insert, update on
            market_warehouses, market_supplies, market_supply_items, market_shipments
        to savdex_django;
        grant select, insert, delete on
            market_shipment_orders, market_warehouse_staff, market_pickup_point_staff
        to savdex_django;
        grant select, insert on market_stock_movements to savdex_django;
        revoke update, delete, truncate on market_stock_movements from savdex_django;
        grant select on market_warehouse_stock to savdex_django;
        revoke insert, update, delete, truncate on market_warehouse_stock from savdex_django;
        grant usage on sequence
            market_warehouses_id_seq, market_supplies_id_seq, market_supply_items_id_seq,
            market_shipments_id_seq, market_stock_movements_id_seq
        to savdex_django;
    end if;
end $$;
