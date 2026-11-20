-- OneID у продавца (savdex/market/oneid.py, ТЗ 18.11, разделы 4 и 10).
--
-- Из профиля OneID храним минимум: oneid_tin (совпавший ИНН компании —
-- столбец уже есть), время подтверждения и HMAC-SHA256 от ПИНФЛ на ключе
-- ONEID_PIN_KEY. Сам ПИНФЛ, ФИО, паспорт, адрес, телефон не храним: хеш
-- нужен только чтобы человек с заблокированным продавцом не вернулся
-- через другую компанию. Права роли savdex_django на таблицу уже выданы.

alter table market_sellers
    add column oneid_pin_hash char(64),
    add column oneid_verified_at timestamp(0) without time zone,
    add constraint market_sellers_oneid_check check (
        verified_via is distinct from 'oneid'
        or (oneid_tin is not null and oneid_pin_hash is not null and oneid_verified_at is not null)
    );

create index market_sellers_oneid_pin_hash_index
    on market_sellers (oneid_pin_hash) where oneid_pin_hash is not null;
