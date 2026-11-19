-- Маркетплейс, этап 1 — две добавки к каталогу (2026_11_19_100000), по
-- сверке схемы 19.11 (docs/marketplace-schema.md):
--
-- 1. Фото товара: thumb_path — уменьшенная копия для карточек каталога на
--    телефоне; variant_id — фото одного варианта (цвета). Пустой variant_id —
--    общее фото товара. Вариант — только этого же товара: составной внешний
--    ключ (variant_id, product_id). Убрали вариант — фото остаётся общим.
-- 2. Характеристика «да / нет» — тип bool. Значение — в value_text: '1' или
--    '0' (market_product_values: одно из value_text, value_number).
--
-- Только добавляет: столбцы пустые по умолчанию, прежний код их не видит.

alter table market_product_variants
    add constraint market_product_variants_id_product_unique unique (id, product_id);

alter table market_product_images
    add column thumb_path varchar(190),
    add column variant_id bigint,
    add constraint market_product_images_variant_fkey
        foreign key (variant_id, product_id)
        references market_product_variants (id, product_id)
        on delete set null (variant_id);

create index market_product_images_variant_index
    on market_product_images (variant_id) where variant_id is not null;

alter table market_attributes
    drop constraint market_attributes_kind_check,
    add constraint market_attributes_kind_check
        check (kind in ('text', 'number', 'choice', 'bool'));
