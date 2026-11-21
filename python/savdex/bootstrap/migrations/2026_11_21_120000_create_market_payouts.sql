-- Маркетплейс SavdEx, касса — этап 3: реквизиты продавцов, их история и
-- выплаты продавцам в два шага (docs/marketplace.md, «Касса — этап 3»;
-- docs/marketplace-security.md, разделы 3 и 4). Код — savdex/market/cash.py.
--
-- Выплата пока ручная (ТЗ: выплаты по оферте — позже): продавец видит
-- начисления в кабинете, касса переводит деньги платёжкой из банка и
-- отмечает выплату в админке. Деньги — целыми тийинами (bigint).

-- ── Реквизиты продавца ─────────────────────────────────────────────
-- Одна строка на продавца — текущие реквизиты; меняет только владелец
-- компании из кабинета. Каждая смена — строка истории
-- (market_seller_requisites_log), changed_at — когда сменили: выплату на
-- реквизиты, сменённые меньше суток назад, касса подтверждает отдельно.
-- bank_account — расчётный счёт (20 цифр), bank_mfo — МФО банка (5 цифр),
-- recipient_tin — ИНН (9 цифр) или ПИНФЛ (14 цифр) получателя.
create table market_seller_requisites (
    id bigserial primary key,
    seller_id bigint not null references market_sellers (id) on delete restrict,
    bank_account varchar(20) not null,
    bank_mfo varchar(5) not null,
    bank_name varchar(200) not null,
    recipient_name varchar(200) not null,
    recipient_tin varchar(14) not null,
    changed_at timestamp(0) without time zone not null default (now() at time zone 'utc'),
    changed_by bigint references users (id) on delete restrict,
    created_at timestamp(0) without time zone not null default (now() at time zone 'utc'),
    updated_at timestamp(0) without time zone not null default (now() at time zone 'utc'),
    constraint market_seller_requisites_seller_unique unique (seller_id),
    constraint market_seller_requisites_account_check check (bank_account ~ '^[0-9]{20}$'),
    constraint market_seller_requisites_mfo_check check (bank_mfo ~ '^[0-9]{5}$'),
    constraint market_seller_requisites_tin_check
        check (recipient_tin ~ '^([0-9]{9}|[0-9]{14})$')
);

-- История реквизитов — только дописывается (как журнал денег, построчным
-- триггером на update и delete): по ней разбирают, куда ушла выплата, и
-- видят подмену счёта.
create table market_seller_requisites_log (
    id bigserial primary key,
    seller_id bigint not null references market_sellers (id) on delete restrict,
    bank_account varchar(20) not null,
    bank_mfo varchar(5) not null,
    bank_name varchar(200) not null,
    recipient_name varchar(200) not null,
    recipient_tin varchar(14) not null,
    changed_by bigint references users (id) on delete restrict,
    ip varchar(45),
    created_at timestamp(0) without time zone not null default (now() at time zone 'utc')
);

create index market_seller_requisites_log_seller_index
    on market_seller_requisites_log (seller_id, id desc);

create trigger market_seller_requisites_log_append_only
    before update or delete on market_seller_requisites_log
    for each row execute function market_append_only();

-- ── Выплаты продавцам ──────────────────────────────────────────────
-- status: draft — создана кассиром; approved — подтвердил другой кассир
-- (approved_by <> created_by — держит и база); paid — деньги ушли
-- платёжкой (bank_reference — номер платёжного поручения), в журнале денег
-- — группа ledger_group; cancelled — отменена до выплаты.
-- requisites_log_id — реквизиты, на которые подтвердили выплату (строка
-- истории): сменились после подтверждения — выплату не отмечают, а
-- отменяют и создают заново. fresh_requisites — подтверждена на реквизиты,
-- сменённые меньше суток назад (повторное подтверждение), fresh_check_note
-- — как их сверили. cancel_not_sent — отменяя подтверждённую, сотрудник
-- отметил, что платёжка в банк не отправлялась.
create table market_payouts (
    id bigserial primary key,
    seller_id bigint not null references market_sellers (id) on delete restrict,
    amount bigint not null,
    status varchar(12) not null default 'draft',
    note varchar(500),
    created_by bigint not null references users (id) on delete restrict,
    approved_by bigint references users (id) on delete restrict,
    paid_by bigint references users (id) on delete restrict,
    cancelled_by bigint references users (id) on delete restrict,
    requisites_log_id bigint references market_seller_requisites_log (id) on delete restrict,
    fresh_requisites boolean not null default false,
    fresh_check_note varchar(500),
    bank_reference varchar(64),
    ledger_group uuid,
    cancel_reason varchar(500),
    cancel_not_sent boolean not null default false,
    created_at timestamp(0) without time zone not null default (now() at time zone 'utc'),
    updated_at timestamp(0) without time zone not null default (now() at time zone 'utc'),
    approved_at timestamp(0) without time zone,
    paid_at timestamp(0) without time zone,
    cancelled_at timestamp(0) without time zone,
    constraint market_payouts_amount_check check (amount > 0),
    constraint market_payouts_status_check
        check (status in ('draft', 'approved', 'paid', 'cancelled')),
    -- Два шага — два разных сотрудника
    constraint market_payouts_two_people_check
        check (approved_by is null or approved_by <> created_by),
    constraint market_payouts_approved_check check (
        status not in ('approved', 'paid')
        or (approved_by is not null and approved_at is not null and requisites_log_id is not null)
    ),
    constraint market_payouts_paid_check check (
        status <> 'paid'
        or (paid_by is not null and paid_at is not null and bank_reference is not null
            and ledger_group is not null)
    ),
    constraint market_payouts_ledger_group_unique unique (ledger_group)
);

-- Одна платёжка — одна выплата: тот же номер второй раз не отметить
create unique index market_payouts_bank_reference_unique on market_payouts (bank_reference)
    where bank_reference is not null;
create index market_payouts_seller_index on market_payouts (seller_id, status);
create index market_payouts_status_index on market_payouts (status, created_at desc);

-- Выплата не переписывается задним числом, даже владельцем базы:
-- - продавец, сумма и автор — только при создании;
-- - переходы — только вперёд: draft → approved | cancelled,
--   approved → paid | cancelled; назад (approved → draft) — нет;
-- - после ухода из draft подтверждение (кто, когда, реквизиты, отметка
--   «сверены») не меняется;
-- - выплаченная и отменённая не меняются вовсе.
create or replace function market_payouts_guard() returns trigger
language plpgsql as $$
begin
    if new.seller_id <> old.seller_id or new.amount <> old.amount
        or new.created_by <> old.created_by
    then
        raise exception 'market_payouts %: продавец, сумма и автор не меняются', old.id
            using errcode = 'insufficient_privilege';
    end if;

    if old.status in ('paid', 'cancelled') then
        raise exception 'market_payouts %: выплата уже закрыта (%)', old.id, old.status
            using errcode = 'insufficient_privilege';
    end if;

    if new.status <> old.status and not (
        (old.status = 'draft' and new.status in ('approved', 'cancelled'))
        or (old.status = 'approved' and new.status in ('paid', 'cancelled'))
    ) then
        raise exception 'market_payouts %: переход % → % запрещён', old.id, old.status, new.status
            using errcode = 'insufficient_privilege';
    end if;

    if old.status <> 'draft' and (
        new.approved_by is distinct from old.approved_by
        or new.approved_at is distinct from old.approved_at
        or new.requisites_log_id is distinct from old.requisites_log_id
        or new.fresh_requisites is distinct from old.fresh_requisites
        or new.fresh_check_note is distinct from old.fresh_check_note
    ) then
        raise exception 'market_payouts %: подтверждение не меняется', old.id
            using errcode = 'insufficient_privilege';
    end if;

    return new;
end $$;

create trigger market_payouts_guard
    before update on market_payouts
    for each row execute function market_payouts_guard();

-- ── Наличные: сверка с отчётом BTS ─────────────────────────────────
-- Заказ «при получении» попадает продавцу «к выплате» только после
-- отметки кассы «сверено с отчётом BTS» (cash_reconciled_ref — номер или
-- дата отчёта): пока деньги не пришли от пункта выдачи, выплачивать их
-- рано. Сверку можно снять, пока деньги заказа не ушли в выплату.
alter table market_orders add column cash_reconciled_at timestamp(0) without time zone;
alter table market_orders add column cash_reconciled_by bigint
    references users (id) on delete restrict;
alter table market_orders add column cash_reconciled_ref varchar(100);

-- ── Возврат вручную ────────────────────────────────────────────────
-- refund_mode — как идёт возврат: api — расписание запрашивает его у
-- провайдера (ставится до сетевого вызова), manual — API нет, вернуть в
-- кабинете, error — сбой связи, итог неизвестен, claimed — касса взяла
-- возврат на себя (refund_claimed_by). Отметить возврат вручную можно
-- только в claimed, manual и error — не пока идёт запрос api.
-- refund_reference — номер возврата у провайдера, один на возврат.
alter table market_payments add column refund_mode varchar(8);
alter table market_payments add column refund_claimed_by bigint
    references users (id) on delete restrict;
alter table market_payments add column refund_reference varchar(64);
alter table market_payments add constraint market_payments_refund_mode_check
    check (refund_mode is null or refund_mode in ('api', 'manual', 'error', 'claimed'));
create unique index market_payments_refund_reference_unique on market_payments (refund_reference)
    where refund_reference is not null;

-- ── Реквизиты: неверные пароли ──────────────────────────────────────
-- Смена реквизитов — с паролем от входа; пять неверных подряд — смена
-- закрыта на сутки (requisites_locked_until), владельцам — письмо.
alter table market_sellers add column requisites_failed smallint not null default 0;
alter table market_sellers add column requisites_locked_until timestamp(0) without time zone;

-- ── Журнал денег: счёт выплат ──────────────────────────────────────
-- payout_clearing — деньги, ушедшие продавцам платёжкой с нашего счёта:
-- выплата — seller_payable плюс (долг продавцу закрыт), payout_clearing
-- минус. Список счетов — savdex/market/orders.py, ACCOUNTS.
-- Замок на запись в журнал денег всё равно берётся (drop и add
-- constraint); not valid и отдельный validate только делят проверку
-- старых строк на свой шаг. Журнал пока маленький — это мгновения.
alter table market_ledger drop constraint market_ledger_account_check;
alter table market_ledger add constraint market_ledger_account_check check (account in (
        'buyer_receivable', 'gateway_clearing', 'cash_collected', 'seller_payable',
        'commission_revenue', 'refund_payable', 'delivery_revenue', 'payout_clearing'
    )) not valid;
alter table market_ledger validate constraint market_ledger_account_check;

-- ── Права роли Django ──────────────────────────────────────────────
-- Реквизиты и выплаты — читать, заводить, менять; удалять — нет. История
-- реквизитов — только читать и дописывать.
do $$ begin
    if exists (select from pg_roles where rolname = 'savdex_django') then
        grant select, insert, update on market_seller_requisites, market_payouts to savdex_django;
        revoke delete, truncate on market_seller_requisites, market_payouts from savdex_django;
        grant select, insert on market_seller_requisites_log to savdex_django;
        revoke update, delete, truncate on market_seller_requisites_log from savdex_django;
        grant usage on sequence
            market_seller_requisites_id_seq, market_seller_requisites_log_id_seq,
            market_payouts_id_seq
        to savdex_django;
    end if;
end $$;
