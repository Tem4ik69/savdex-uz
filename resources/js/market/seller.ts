import { PRODUCTS } from '@/market/demo';
import { createLocal } from '@/market/local';

/**
 * Кабинет продавца — демо.
 *
 * Заявка, товары и поставки живут в браузере. Путь продавца по ТЗ:
 * заявка с документами → проверка модератором → кабинет; товар
 * продаётся только после приёмки на складе BTS; первые пять товаров
 * нового продавца ждут модерации.
 */

export interface SellerProduct {
    id: number;
    title: string;
    emoji: string;
    category: string;
    price: number;
    oldPrice: number | null;
    /** На складе, в резерве под заказы */
    stock: number;
    reserved: number;
    status: 'live' | 'moderation' | 'draft';
    sku: string;
}

export interface Supply {
    id: string;
    date: string;
    productId: number;
    quantity: number;
    /** Сколько принял склад; null — ещё не привезли */
    accepted: number | null;
    status: 'planned' | 'accepted' | 'partial';
}

export interface SellerState {
    application: 'none' | 'pending' | 'approved';
    company: string;
    products: SellerProduct[];
    supplies: Supply[];
}

/** Стартовая витрина — товары одного продавца из демо-каталога. */
const STARTER: SellerProduct[] = PRODUCTS.filter((p) => p.seller === 'samarqand-tekstil').map((p, i) => ({
    id: p.id,
    title: p.title,
    emoji: p.emoji,
    category: p.category,
    price: p.price,
    oldPrice: p.oldPrice,
    stock: p.stock,
    reserved: i + 2,
    status: 'live',
    sku: `ST-${1000 + p.id}`,
}));

export const seller = createLocal<SellerState>('savdex.market.seller', {
    application: 'none',
    company: '',
    products: STARTER,
    supplies: [
        { id: 'П-0031', date: '2026-11-12', productId: STARTER[0]?.id ?? 0, quantity: 60, accepted: 58, status: 'partial' },
        { id: 'П-0034', date: '2026-11-21', productId: STARTER[1]?.id ?? 0, quantity: 40, accepted: null, status: 'planned' },
    ],
});

/** Заказы продавца: без телефона покупателя — выдаёт пункт (ТЗ, раздел 10). */
export const SELLER_ORDERS: { id: string; date: string; title: string; quantity: number; sum: number; status: string; buyer: string }[] = [
    { id: 'SM-104 218', date: '2026-11-17', title: 'Постельное бельё, хлопок, 2-спальное', quantity: 1, sum: 329_000, status: 'Можно забрать', buyer: 'Дильноза' },
    { id: 'SM-104 102', date: '2026-11-15', title: 'Рюкзак городской 25 л, влагозащита', quantity: 2, sum: 398_000, status: 'Выдан', buyer: 'Жасур' },
    { id: 'SM-104 077', date: '2026-11-14', title: 'Постельное бельё, хлопок, 2-спальное', quantity: 1, sum: 329_000, status: 'Выдан', buyer: 'Мадина' },
    { id: 'SM-103 990', date: '2026-11-11', title: 'Рюкзак городской 25 л, влагозащита', quantity: 1, sum: 199_000, status: 'Отменён', buyer: 'Азиз' },
];

/** Комиссия площадки в демо. Настоящий процент ещё не определён (ТЗ, открытый вопрос 1). */
export const COMMISSION = 10;
