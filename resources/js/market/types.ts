/**
 * Данные маркетплейса — в том виде, в каком их отдаёт сервер
 * (/market/api/…, docs/marketplace.md). Цены — в сумах.
 */

/** Карточка товара в списке. */
export interface MarketProduct {
    id: number;
    slug: string;
    title: string;
    /** Уменьшенная копия первого общего фото; null — фото ещё нет */
    image: string | null;
    price: number;
    oldPrice: number | null;
    rating: number;
    reviews: number;
    sold: number;
    /** Остаток по всем вариантам; 0 — купить нельзя */
    stock: number;
    /** Адрес самой точной категории товара */
    category: string;
    seller: string;
    sellerName: string;
    badge: 'hit' | 'new' | 'sale' | null;
}

export interface MarketCategory {
    slug: string;
    name: string;
    emoji: string;
    children: MarketCategory[];
}

export interface MarketSeller {
    slug: string;
    name: string;
    /** Компания проверена площадкой (документы приняты модератором) */
    verified: boolean;
    rating: number;
    logo: string | null;
}

/** Вариант товара, который кладут в корзину: своё сочетание, цена и остаток. */
export interface MarketOffer {
    id: number;
    options: Record<string, string>;
    sku: string | null;
    price: number;
    oldPrice: number | null;
    stock: number;
}

export interface MarketImage {
    id: number;
    url: string;
    thumb: string;
    /** Фото одного варианта (цвета); null — общее */
    variantId: number | null;
}

/** Страница товара: карточка плюс всё для выбора и покупки. */
export interface MarketProductPage extends MarketProduct {
    images: MarketImage[];
    description: string;
    /** Что выбирать: «Цвет» — [«Чёрный», «Белый»] */
    variants: { name: string; options: string[] }[];
    offers: MarketOffer[];
    specs: [string, string][];
    categoryPath: { slug: string; name: string }[];
    sellerInfo: MarketSeller;
    favorite: boolean;
}

/** Фильтр категории: у выбора и строки — значения со счётчиком, у числа — от и до. */
export interface MarketFilter {
    key: string;
    name: string;
    kind: 'choice' | 'text' | 'bool' | 'number';
    unit: string | null;
    options?: { value: string; name: string; count: number }[];
    min?: number | null;
    max?: number | null;
}

export interface MarketListing {
    items: MarketProduct[];
    total: number;
    page: number;
    pages: number;
    sort: string;
    /** Точных совпадений не было — показаны похожие по написанию */
    fuzzy: boolean;
    price: { min: number | null; max: number | null };
    filters: MarketFilter[];
    category: { slug: string; name: string; path: { slug: string; name: string }[] } | null;
}

export interface MarketShop extends MarketListing {
    seller: MarketSeller & { description: string; since: number | null; company: string };
}

export interface CartLine {
    variantId: number;
    productId: number;
    slug: string;
    title: string;
    image: string | null;
    options: Record<string, string>;
    price: number;
    oldPrice: number | null;
    quantity: number;
    /** Сколько можно купить сейчас; 0 — товара нет или он снят */
    available: number;
    buyable: boolean;
    total: number;
}

/** Корзина: части по продавцам — в заказе у каждого будет своя. */
export interface CartSummary {
    parts: { seller: { slug: string; name: string }; items: CartLine[]; total: number }[];
    count: number;
    lines: number;
    total: number;
}

export interface SellerApplication {
    status: 'pending' | 'approved' | 'rejected' | 'blocked' | null;
    rejectReason: string | null;
    /** Что нужно для заявки: компания, владелец, ИНН, документы */
    checks: { company: boolean; owner: boolean; tin: boolean; documents: boolean };
    canApply: boolean;
    offerVersion: string;
}

export type ProductStatus = 'draft' | 'pending' | 'active' | 'rejected' | 'hidden' | 'blocked';

/** Товар в списке «Мои товары». */
export interface MyProduct {
    id: number;
    slug: string;
    title: string;
    status: ProductStatus;
    rejectReason: string | null;
    price: number | null;
    oldPrice: number | null;
    stock: number;
    sold: number;
    views: number;
    image: string | null;
}

export interface MyVariant {
    id?: number;
    options: Record<string, string>;
    sku: string | null;
    price: number | null;
    oldPrice: number | null;
    stock?: number;
    active?: boolean;
}

/** Товар для формы правки. */
export interface MyProductDetail {
    id: number;
    slug: string;
    status: ProductStatus;
    rejectReason: string | null;
    title: string;
    description: string;
    locale: string;
    category: string | null;
    ikpu: string | null;
    barcode: string | null;
    weight_g: number | null;
    length_mm: number | null;
    width_mm: number | null;
    height_mm: number | null;
    values: Record<string, string | number | boolean>;
    variants: MyVariant[];
    images: MarketImage[];
}

export interface PickupPoint {
    code: string;
    name: string;
    address: string;
    city: string;
}

/** Статус с сервера: код для логики и текст на языке страницы. */
export interface OrderStatusView {
    code: 'created' | 'paid' | 'cash_on_pickup' | 'assembling' | 'in_transit' | 'ready' | 'issued' | 'cancelled' | 'refund_pending' | 'refunded';
    text: string;
}

/** Заказ в списке «Мои заказы». */
export interface OrderSummary {
    number: string;
    status: OrderStatusView;
    paymentMethod: 'card' | 'cash';
    total: number;
    count: number;
    pickupPoint: { name: string; address: string };
    createdAt: string | null;
}

export interface OrderItem {
    variantId: number;
    title: string;
    slug: string;
    image: string | null;
    options: Record<string, string>;
    quantity: number;
    price?: number;
    total?: number;
}

/** Заказ целиком: части по продавцам, суммы, можно ли отменить. */
export interface OrderDetail {
    number: string;
    status: OrderStatusView;
    paymentMethod: 'card' | 'cash';
    /** hours — часы работы пункта, если склад их завёл */
    pickupPoint: { name: string; address: string; hours?: string | null };
    /** Код выдачи — только покупателю и только пока заказ «можно забрать»; иначе null */
    pickupCode?: string | null;
    readyAt?: string | null;
    itemsTotal: number;
    delivery: number;
    total: number;
    parts: { seller: { slug: string; name: string }; status: OrderStatusView; total: number; items: OrderItem[] }[];
    canCancel: boolean;
    createdAt: string | null;
    paidAt: string | null;
    cancelledAt: string | null;
    issuedAt: string | null;
}

/** Часть заказа у продавца: о покупателе — только имя (ТЗ, раздел 10). */
export interface SellerOrder {
    number: string;
    status: OrderStatusView;
    buyer: { name: string };
    pickupPoint: { name: string };
    total: number;
    commission: number;
    payout: number;
    items: OrderItem[];
    createdAt: string | null;
}

export interface SellerBalance {
    accrued: number;
    onHold: number;
    available: number;
    inWork: number;
    paid: number;
    holdDays: number;
    payouts: { id: number; amount: number; status: { code: string; text: string }; bankReference: string | null; createdAt: string | null; paidAt: string | null }[];
}

/** Склад, куда продавец везёт поставку (/market/api/me/warehouses). */
export interface Warehouse {
    code: string;
    name: string;
    address: string;
    city: string;
}

/** Поставка продавца на склад (/market/api/me/supplies). */
export interface Supply {
    number: string;
    status: { code: 'draft' | 'submitted' | 'received' | 'rejected' | 'cancelled'; text: string };
    warehouse: { code: string; name: string; address: string };
    note: string | null;
    /** Дата «ГГГГ-ММ-ДД» или null */
    expectedAt: string | null;
    rejectReason: string | null;
    items: { variantId: number; title: string; options: Record<string, string>; declared: number; accepted: number | null; defect: number | null }[];
    canSubmit: boolean;
    canCancel: boolean;
    createdAt: string | null;
    submittedAt: string | null;
    receivedAt: string | null;
}
