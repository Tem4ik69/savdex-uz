-- Маркетплейс: целостность заказов и денег — в самой базе (ТЗ 18.11, 11.3:
-- «ограничения в самой базе»; просмотр миграций заказов, оплат и кассы
-- Жавохира — Нозим, 21.11). Код (savdex/market/orders.py, cash.py,
-- payments/base.py) всё это уже соблюдает; проверки — чтобы ошибка в будущем
-- коде не испортила заказы и деньги молча.
--
-- 1. Позиция заказа — вариант именно этого товара: составной ключ
--    (variant_id, product_id), как у фото варианта (2026_11_19_110000).
-- 2. Позиция заказа — часть именно этого заказа: составной ключ
--    (part_id, order_id).
-- 3. Журнал денег: долг продавцу (seller_payable) и выплата (payout_clearing)
--    — всегда с продавцом, иначе деньги не попадут ни в чей баланс.
-- 4. Сверка наличных с отчётом BTS — только у заказа «при получении», и
--    когда, кто и номер отчёта — вместе (снятие сверки чистит все три).
-- 5. Оплата: «оплачена» — со временем проведения, «возвращена» — со временем
--    проведения и возврата, «отменена» — со временем отмены.
--
-- Только добавляет. Проверки — not valid и отдельный validate: проверка
-- старых строк идёт под лёгким замком, запись в таблицы не ждёт.

alter table market_order_parts
    add constraint market_order_parts_id_order_unique unique (id, order_id);

alter table market_order_items
    add constraint market_order_items_variant_product_fkey
        foreign key (variant_id, product_id)
        references market_product_variants (id, product_id) on delete restrict not valid,
    add constraint market_order_items_part_order_fkey
        foreign key (part_id, order_id)
        references market_order_parts (id, order_id) on delete restrict not valid;

alter table market_ledger
    add constraint market_ledger_seller_check
        check (account not in ('seller_payable', 'payout_clearing') or seller_id is not null)
        not valid;

alter table market_orders
    add constraint market_orders_cash_reconciled_check check (
        (cash_reconciled_at is null) = (cash_reconciled_by is null)
        and (cash_reconciled_at is null) = (cash_reconciled_ref is null)
        and (cash_reconciled_at is null or payment_method = 'cash')
    ) not valid;

alter table market_payments
    add constraint market_payments_status_times_check check (
        (status <> 'paid' or performed_at is not null)
        and (status <> 'refunded' or (performed_at is not null and refunded_at is not null))
        and (status <> 'cancelled' or cancelled_at is not null)
    ) not valid;

alter table market_order_items validate constraint market_order_items_variant_product_fkey;
alter table market_order_items validate constraint market_order_items_part_order_fkey;
alter table market_ledger validate constraint market_ledger_seller_check;
alter table market_orders validate constraint market_orders_cash_reconciled_check;
alter table market_payments validate constraint market_payments_status_times_check;
