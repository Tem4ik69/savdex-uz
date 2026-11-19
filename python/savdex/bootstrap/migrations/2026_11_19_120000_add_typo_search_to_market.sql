-- Маркетплейс: поиск с опечатками («смартфн» → «Смартфон», «samsng» →
-- «Samsung») — расширение pg_trgm, в самом PostgreSQL: без внешних
-- сервисов, данные остаются в Узбекистане (ТЗ, раздел 10 и 11.3).
--
-- Основной поиск не меняется — полнотекстовый, по началу слова
-- (market_products.search). Похожие по написанию — только когда он ничего
-- не нашёл (savdex/market/catalog.py, _FUZZY).
--
-- Порог похожести 0.5 (word_similarity, от 0 до 1) — для оператора «<%»,
-- которым пользуется индекс. Проверено 19.11: опечатки — 0.57…0.83
-- («samsng» → «Samsung Galaxy» 0.57, «смартфн» → «Смартфон» 0.75),
-- случайные совпадения — до 0.29. По умолчанию у pg_trgm 0.6 — опечатки
-- вроде «samsng» не находились бы. Настройка базы действует на новые
-- соединения; pg_trgm в SavdEx пользуется только маркетплейс.
--
-- create extension — от владельца базы: миграции применяет он (savdex,
-- суперпользователь — проверено на боевой базе 19.11).

create extension if not exists pg_trgm;

do $$ begin
    execute format(
        'alter database %I set pg_trgm.word_similarity_threshold = 0.5',
        current_database()
    );
end $$;

create index market_products_title_trgm_index
    on market_products using gin (title gin_trgm_ops)
    where status = 'active';
