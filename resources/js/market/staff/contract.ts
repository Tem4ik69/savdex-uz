/**
 * Контракт экранов склада и пункта выдачи — предложение Максуда Шерзоду
 * (ТЗ «2026-11-23 Команда — склад маркетплейса SavdEx»: «адреса для них
 * дам по контракту»). Описание адресов — docs/marketplace.md, раздел
 * «Экраны склада и пункта — контракт».
 *
 * Все адреса — /market/api/warehouse/… и /market/api/point/…: только
 * сотруднику своего склада или пункта (иначе 403 с текстом), запись — POST
 * с токеном, ошибки — 422 {message, errors} или 409 {message}. Даты —
 * ISO в UTC, суммы — целые сумы.
 *
 * Пока сервер отвечает на адрес 404, экраны показывают образцы того же
 * вида (staff/samples.ts) с пометкой «Образец» — переключатся сами, когда
 * адрес появится.
 */

/** Статус с сервера: код для логики и текст на языке страницы. */
export interface StaffStatus<C extends string = string> {
    code: C;
    text: string;
}

/** Строка товара на складе: вариант, подпись и где лежит. */
export interface StockLine {
    variantId: number;
    title: string;
    /** «Синий, XL»; у товара без вариантов — пусто */
    options: string;
    sku: string | null;
    /** Ячейка склада, если заведена */
    cell?: string | null;
    quantity: number;
}

// ── Склад ────────────────────────────────────────────────────────────

/** GET warehouse/me — свой склад и сотрудник. */
export interface WarehouseMe {
    warehouse: { code: string; name: string; address: string };
    staff: { name: string };
    /** Сколько ждёт работы — цифры на вкладках */
    counts: Partial<Record<WarehouseTab, number>>;
}

export type WarehouseTab = 'supplies' | 'receiving' | 'stock' | 'picking' | 'shipments' | 'returns' | 'removals' | 'writeoffs';

/** GET warehouse/supplies?status=submitted|received|rejected — поставки продавцов на этот склад. */
export interface WarehouseSupply {
    number: string;
    status: StaffStatus<'submitted' | 'received' | 'rejected'>;
    seller: { name: string };
    expectedAt: string | null;
    note: string | null;
    items: { itemId: number; variantId: number; title: string; options: string; declared: number; accepted: number | null; defect: number | null }[];
    submittedAt: string | null;
    receivedAt: string | null;
}
// POST warehouse/supplies/<номер>/receive {items: [{itemId, accepted, defect}]} → {message, supply}
// POST warehouse/supplies/<номер>/reject {reason} → {message, supply}

/** GET warehouse/stock?q= — остатки склада. */
export interface WarehouseStockRow extends StockLine {
    seller: { name: string };
    /** quantity — на полке всего; reserved — под заказы; defect — брак, ждёт вывоза */
    reserved: number;
    defect: number;
}

/** GET warehouse/picking — заказы к сборке (оплачены или «при получении»). */
export interface PickingOrder {
    number: string;
    status: StaffStatus<'paid' | 'assembling' | 'assembled'>;
    pickupPoint: { code: string; name: string };
    items: StockLine[];
    createdAt: string;
}
// POST warehouse/picking/<номер>/start → «собирается»; POST …/done {places} → «собран»

/** GET warehouse/shipments — партии склад → пункт. */
export interface Shipment {
    number: string;
    status: StaffStatus<'draft' | 'sent' | 'delivered'>;
    pickupPoint: { code: string; name: string; address: string };
    orders: { number: string; places: number }[];
    sentAt: string | null;
    deliveredAt: string | null;
}
// GET warehouse/shipments/ready → {points: [{code, name, orders}]} — сколько собранных ждёт по пунктам
// POST warehouse/shipments/create {pickupPoint} → партия из всех собранных заказов пункта
// POST warehouse/shipments/<номер>/send → «уехала»

/** GET warehouse/returns — возвратные партии из пунктов (невостребованные и отказы). */
export interface ReturnBatch {
    number: string;
    status: StaffStatus<'sent' | 'received'>;
    pickupPoint: { name: string };
    orders: { number: string; reason: string; items: StockLine[] }[];
    sentAt: string | null;
}
// POST warehouse/returns/<номер>/receive {items: [{order, variantId, good, defect}]}

/** GET warehouse/removals — заявки продавцов на вывоз. */
export interface Removal {
    number: string;
    status: StaffStatus<'requested' | 'ready' | 'done' | 'cancelled'>;
    seller: { name: string };
    /** kind: годный остаток или брак */
    items: (StockLine & { kind: 'good' | 'defect' })[];
    requestedAt: string;
    doneAt: string | null;
}
// POST warehouse/removals/<номер>/ready → «собран, ждёт продавца»; POST …/done → «вывезен» (движение return_to_seller)

/** GET warehouse/writeoffs — заявки на списание; подтверждает администратор (решение 23.11, №7). */
export interface Writeoff {
    number: string;
    status: StaffStatus<'requested' | 'approved' | 'rejected'>;
    line: StockLine;
    reason: string;
    author: { name: string };
    createdAt: string;
}
// POST warehouse/writeoffs/create {variantId, quantity, reason} → заявка

// ── Пункт выдачи ─────────────────────────────────────────────────────

/** GET point/me — свой пункт и сотрудник. */
export interface PointMe {
    point: { code: string; name: string; address: string; hours: string | null };
    staff: { name: string };
    counts: Partial<Record<PointTab, number>>;
}

export type PointTab = 'batches' | 'issue' | 'unclaimed' | 'cash';

/** GET point/batches — партии со склада в этот пункт. */
export interface PointBatch {
    number: string;
    status: StaffStatus<'sent' | 'delivered'>;
    orders: { number: string; places: number; problem: string | null }[];
    sentAt: string | null;
    deliveredAt: string | null;
}
// POST point/batches/<номер>/accept {problems: [{order, note}]} → все заказы «можно забрать», кроме проблемных

/**
 * GET point/orders/<номер> — заказ по номеру с наклейки, перед вводом кода.
 * Имени и телефона покупателя нет (решение 23.11); сумма — только «при получении».
 */
export interface PointOrder {
    number: string;
    status: StaffStatus;
    places: number;
    /** К оплате наличными; null — оплачен картой */
    toPay: number | null;
    until: string | null;
    /** Пауза после 5 неверных кодов */
    lockedUntil: string | null;
    attemptsLeft: number;
}
// POST point/orders/<номер>/issue {code} → {result: 'issued'|'wrong'|'locked', attemptsLeft, lockedUntil, message}
// POST point/orders/<номер>/refuse {reason} — отказ при получении: целиком (решение 23.11, №4)

/** GET point/unclaimed — не забрали в срок (7 дней) и отказы — собрать в возвратную партию. */
export interface UnclaimedOrder {
    number: string;
    places: number;
    reason: StaffStatus<'expired' | 'refused'>;
    readyAt: string | null;
    returnBatch: string | null;
}
// POST point/returns/create {orders: [номер]} → возвратная партия на склад

/** GET point/cash?date=ГГГГ-ММ-ДД — наличные за день по пункту. */
export interface PointCash {
    date: string;
    orders: { number: string; amount: number; issuedAt: string; staff: string }[];
    total: number;
}

// ── Продавец: «Вывоз» ────────────────────────────────────────────────

/**
 * GET me/removals — свои заявки на вывоз со склада (годный остаток или
 * брак — брак ждёт вывоза продавцом, решение 23.11, №3).
 */
export interface SellerRemoval {
    number: string;
    status: StaffStatus<'requested' | 'ready' | 'done' | 'cancelled'>;
    warehouse: { name: string; address: string };
    items: (StockLine & { kind: 'good' | 'defect' })[];
    requestedAt: string;
    doneAt: string | null;
    canCancel: boolean;
}
/** GET me/removals/available — что можно вывезти: по вариантам годное и брак на складах. */
export interface RemovalAvailable {
    warehouse: { code: string; name: string; address: string };
    items: (StockLine & { good: number; defect: number })[];
}
// POST me/removals/create {warehouse, items: [{variantId, kind, quantity}]} → {message, removal}
// POST me/removals/<номер>/cancel — пока склад не собрал
