-- Маркетплейс SavdEx, оплата — этап 2: оплаты заказов картой через Uzum,
-- Payme и Click (docs/marketplace.md, «Оплата — этап 2»;
-- docs/marketplace-security.md, раздел 3). Код — savdex/market/payments/.
--
-- Одна строка — одна попытка оплаты заказа у одного провайдера. Деньги —
-- целыми тийинами (bigint), сумма берётся только из заказа. Движение денег
-- пишет журнал market_ledger (orders.mark_paid, orders.mark_refunded);
-- здесь — состояние транзакции провайдера.
--
-- status: created — счёт открыт на сайте (ссылка на оплату выдана),
-- транзакции провайдера ещё нет; pending — провайдер завёл транзакцию
-- (Uzum create, Payme CreateTransaction, Click Prepare), деньги ещё не
-- проведены; paid — проведена, заказ оплачен; cancelled — отменена до
-- проведения; refunded — деньги вернули покупателю.
--
-- provider_transaction_id — номер транзакции у провайдера (Uzum transId,
-- Payme id, Click click_trans_id): повтор колбэка с тем же номером находит
-- ту же строку — второго зачисления нет. provider_ref — второй номер
-- провайдера, если он нужен (Click click_paydoc_id — для возврата).
-- provider_time — время транзакции у провайдера в миллисекундах (Payme
-- time — по нему отвечаем на GetStatement). reason — код причины отмены
-- (Payme reason), note — короткая пометка для администратора.
-- refund_requested_at — возврат уже запрошен (ровно один раз).
-- rejected_at — отклонена на шаге проведения (заказ уже не ждал оплаты):
-- провайдер мог списать деньги, сверка просит проверить, что он их вернул.
-- rejection_checked_at, checked_by, check_note — сотрудник проверил у
-- провайдера отказ или зависший возврат (payments/base.py, acknowledge):
-- сверка такую оплату больше не считает расхождением.
-- created_at — когда провайдер завёл транзакцию (у открытого счёта —
-- когда счёт открыт): от него считаются сроки провайдера.
create table market_payments (
    id bigserial primary key,
    order_id bigint not null references market_orders (id) on delete restrict,
    provider varchar(8) not null,
    provider_transaction_id varchar(64),
    provider_ref varchar(64),
    provider_time bigint,
    amount bigint not null,
    status varchar(12) not null default 'created',
    reason smallint,
    note varchar(500),
    created_at timestamp(0) without time zone not null default (now() at time zone 'utc'),
    updated_at timestamp(0) without time zone not null default (now() at time zone 'utc'),
    performed_at timestamp(0) without time zone,
    cancelled_at timestamp(0) without time zone,
    refund_requested_at timestamp(0) without time zone,
    refunded_at timestamp(0) without time zone,
    rejected_at timestamp(0) without time zone,
    rejection_checked_at timestamp(0) without time zone,
    checked_by bigint references users (id) on delete restrict,
    check_note varchar(500),
    constraint market_payments_provider_check check (provider in ('uzum', 'payme', 'click')),
    constraint market_payments_status_check
        check (status in ('created', 'pending', 'paid', 'cancelled', 'refunded')),
    constraint market_payments_amount_check check (amount > 0),
    -- Транзакция провайдера есть у всех, кроме только что открытого счёта
    constraint market_payments_transaction_check
        check (status = 'created' or status = 'cancelled' or provider_transaction_id is not null),
    constraint market_payments_transaction_unique unique (provider, provider_transaction_id)
);

-- Один живой счёт на заказ: открытый, ждущий или оплаченный — не больше
-- одного. Вторая оплата того же заказа — отказ, а не второе зачисление
create unique index market_payments_live_unique on market_payments (order_id)
    where status in ('created', 'pending', 'paid');

create index market_payments_order_index on market_payments (order_id);
create index market_payments_provider_time_index on market_payments (provider, provider_time);
create index market_payments_updated_index on market_payments (updated_at);
create index market_payments_rejected_index on market_payments (rejected_at)
    where rejected_at is not null;

-- ── Права роли Django ──────────────────────────────────────────────
-- Читать, заводить и менять статус; удалять — нет: история оплат нужна
-- сверке и разбору споров.
do $$ begin
    if exists (select from pg_roles where rolname = 'savdex_django') then
        grant select, insert, update on market_payments to savdex_django;
        revoke delete, truncate on market_payments from savdex_django;
        grant usage on sequence market_payments_id_seq to savdex_django;
    end if;
end $$;
