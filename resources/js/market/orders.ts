import { createLocal } from '@/market/local';
import type { CartLine } from '@/market/types';

/**
 * Заказы и пункты выдачи — пока демо: заказов на сервере ещё нет
 * (docs/marketplace.md, «Дальше», пункт 3). Корзина уже настоящая,
 * поэтому оформленный заказ собирается из её строк, но хранится в
 * браузере. Появятся заказы на сервере — этот файл уходит.
 *
 * Статусы — из ТЗ: оформлен → оплачен (или оплата при получении) →
 * собирается на складе → в пути в пункт выдачи → можно забрать → выдан;
 * отдельно — отменён. Код выдачи покупатель видит, когда заказ приехал.
 */

export type OrderStatus = 'placed' | 'paid' | 'packing' | 'shipping' | 'ready' | 'done' | 'cancelled';

export interface OrderItem {
    productId: number;
    title: string;
    image: string | null;
    /** Вариант словами: «Цвет: Чёрный» */
    options: string;
    price: number;
    quantity: number;
}

export interface MarketOrder {
    id: string;
    /** ISO-дата оформления */
    created: string;
    items: OrderItem[];
    total: number;
    point: string;
    payment: 'card' | 'cash';
    status: OrderStatus;
    /** Код выдачи: показывается со статуса «можно забрать» */
    code: string;
}

export interface PickupPoint {
    id: string;
    name: string;
    district: string;
    address: string;
    hours: string;
    lat: number;
    lng: number;
}

/** Пункты выдачи BTS в Ташкенте. Адреса демонстрационные — настоящий список придёт от BTS. */
export const POINTS: PickupPoint[] = [
    { id: 'chilanzar', name: 'BTS Чиланзар', district: 'Чиланзарский район', address: 'ул. Бунёдкор, 12', hours: 'Ежедневно 9:00–21:00', lat: 41.2756, lng: 69.2044 },
    { id: 'yunusabad', name: 'BTS Юнусабад', district: 'Юнусабадский район', address: 'ул. Амира Темура, 107', hours: 'Ежедневно 9:00–21:00', lat: 41.3636, lng: 69.2889 },
    { id: 'ulugbek', name: 'BTS Буюк Ипак Йули', district: 'Мирзо-Улугбекский район', address: 'ул. Буюк Ипак Йули, 45', hours: 'Ежедневно 9:00–20:00', lat: 41.3256, lng: 69.3286 },
    { id: 'sergeli', name: 'BTS Сергели', district: 'Сергелийский район', address: 'ул. Янги Сергели, 8', hours: 'Пн–Сб 9:00–20:00', lat: 41.2256, lng: 69.2189 },
    { id: 'yakkasaray', name: 'BTS Яккасарай', district: 'Яккасарайский район', address: 'ул. Шота Руставели, 22', hours: 'Ежедневно 9:00–21:00', lat: 41.2867, lng: 69.2553 },
    { id: 'chorsu', name: 'BTS Чорсу', district: 'Шайхантахурский район', address: 'ул. Навои, 48', hours: 'Ежедневно 8:00–20:00', lat: 41.3264, lng: 69.2353 },
    { id: 'mirabad', name: 'BTS Мирабад', district: 'Мирабадский район', address: 'ул. Нукус, 31', hours: 'Пн–Сб 9:00–20:00', lat: 41.2903, lng: 69.2808 },
    { id: 'olmazor', name: 'BTS Алмазар', district: 'Алмазарский район', address: 'ул. Каракамыш, 3', hours: 'Ежедневно 9:00–20:00', lat: 41.3536, lng: 69.2125 },
];

export const pointOf = (id: string): PickupPoint => POINTS.find((p) => p.id === id) ?? POINTS[0];

/** Шаги пути заказа по порядку — для полосы статуса. */
export const STEPS: { status: OrderStatus; label: string }[] = [
    { status: 'placed', label: 'Оформлен' },
    { status: 'packing', label: 'Собирается' },
    { status: 'shipping', label: 'В пути' },
    { status: 'ready', label: 'Можно забрать' },
    { status: 'done', label: 'Выдан' },
];

export const STATUS_LABEL: Record<OrderStatus, string> = {
    placed: 'Оформлен, оплата при получении',
    paid: 'Оплачен',
    packing: 'Собирается на складе',
    shipping: 'В пути в пункт выдачи',
    ready: 'Можно забрать',
    done: 'Выдан',
    cancelled: 'Отменён',
};

/** Номер шага на полосе: «оплачен» стоит на первом шаге вместе с «оформлен». */
export function stepIndex(status: OrderStatus): number {
    return status === 'paid' ? 0 : STEPS.findIndex((s) => s.status === status);
}

/** Отменить сам покупатель может, пока заказ не уехал со склада. */
export const canCancel = (status: OrderStatus): boolean => status === 'placed' || status === 'paid' || status === 'packing';

const NEXT: Partial<Record<OrderStatus, OrderStatus>> = {
    placed: 'packing',
    paid: 'packing',
    packing: 'shipping',
    shipping: 'ready',
    ready: 'done',
};

export const nextStatus = (status: OrderStatus): OrderStatus | undefined => NEXT[status];

/** Строка корзины → позиция заказа: копия названия и цены на момент покупки. */
export function itemOf(line: CartLine): OrderItem {
    return {
        productId: line.productId,
        title: line.title,
        image: line.image,
        options: Object.entries(line.options)
            .map(([name, value]) => `${name}: ${value}`)
            .join(' · '),
        price: line.price,
        quantity: Math.min(line.quantity, line.available),
    };
}

const sample = (id: string, created: string, status: OrderStatus, lines: [number, string, number, number][], point: string, payment: 'card' | 'cash', code: string): MarketOrder => {
    const items = lines.map(([productId, title, price, quantity]) => ({ productId, title, image: null, options: '', price, quantity }));

    return { id, created, status, items, total: items.reduce((s, i) => s + i.price * i.quantity, 0), point, payment, code };
};

/** Три заказа для примера — чтобы экран не был пустым до первой покупки. */
export const SAMPLE_ORDERS: MarketOrder[] = [
    sample('SM-104 218', '2026-11-17T10:24:00', 'ready', [[4, 'Казан чугунный 12 л с крышкой', 415_000, 1], [10, 'Постельное бельё, хлопок, 2-спальное', 329_000, 1]], 'chilanzar', 'card', '4721'),
    sample('SM-104 190', '2026-11-16T18:02:00', 'shipping', [[2, 'Беспроводные наушники Orbit Buds 2', 289_000, 1]], 'yunusabad', 'cash', '9053'),
    sample('SM-103 877', '2026-11-09T12:40:00', 'done', [[7, 'Конструктор детский, 520 деталей', 159_000, 2], [8, 'Крем для лица увлажняющий, 50 мл', 78_000, 1]], 'chorsu', 'card', '1186'),
];

/** Заказы, оформленные в этом браузере; примеры — отдельно, их не стирают. */
export const orders = createLocal<MarketOrder[]>('savdex.market.orders', []);

export function placeOrder(items: OrderItem[], point: string, payment: 'card' | 'cash'): MarketOrder {
    const stamp = Date.now();
    const number = String(stamp).slice(-6);
    const order: MarketOrder = {
        id: `SM-${number.slice(0, 3)} ${number.slice(3)}`,
        created: new Date(stamp).toISOString(),
        items,
        total: items.reduce((s, i) => s + i.price * i.quantity, 0),
        point,
        payment,
        status: payment === 'card' ? 'paid' : 'placed',
        code: String(1000 + (stamp % 9000)),
    };

    orders.set([order, ...orders.get()]);

    return order;
}

export function setOrderStatus(id: string, status: OrderStatus): void {
    orders.set(orders.get().map((o) => (o.id === id ? { ...o, status } : o)));
}
