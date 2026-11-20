-- Значения характеристик у товаров (market_product_values) больше не стираются
-- каскадом при удалении характеристики: админка не даёт удалить заполненную
-- (AttributeFormSet), а если значение появится между проверкой и удалением —
-- база откажет, и значения у товаров останутся.

alter table market_product_values
    drop constraint market_product_values_attribute_id_fkey,
    add constraint market_product_values_attribute_id_fkey
        foreign key (attribute_id) references market_attributes (id) on delete restrict;
