/**
 * Примеры для разделов кабинета продавца, которых на сервере ещё нет:
 * поставки, заказы и начисления (docs/marketplace.md, «Дальше»:
 * склад BTS, заказы, касса). Заявка и «Мои товары» уже настоящие —
 * /market/api/me/…; здесь — только образцы для вида этих экранов.
 */

export const SAMPLE_SUPPLIES: { id: string; date: string; title: string; quantity: number; accepted: number | null; status: 'planned' | 'accepted' | 'partial' }[] = [
    { id: 'П-0034', date: '2026-11-21', title: 'Постельное бельё, хлопок, 2-спальное', quantity: 40, accepted: null, status: 'planned' },
    { id: 'П-0031', date: '2026-11-12', title: 'Рюкзак городской 25 л, влагозащита', quantity: 60, accepted: 58, status: 'partial' },
    { id: 'П-0027', date: '2026-11-03', title: 'Постельное бельё, хлопок, 2-спальное', quantity: 55, accepted: 55, status: 'accepted' },
];

/** Заказы продавца: без телефона покупателя — выдаёт пункт (ТЗ, раздел 10). */
export const SAMPLE_ORDERS: { id: string; date: string; title: string; quantity: number; sum: number; status: string; buyer: string }[] = [
    { id: 'SM-104 218', date: '2026-11-17', title: 'Постельное бельё, хлопок, 2-спальное', quantity: 1, sum: 329_000, status: 'Можно забрать', buyer: 'Дильноза' },
    { id: 'SM-104 102', date: '2026-11-15', title: 'Рюкзак городской 25 л, влагозащита', quantity: 2, sum: 398_000, status: 'Выдан', buyer: 'Жасур' },
    { id: 'SM-104 077', date: '2026-11-14', title: 'Постельное бельё, хлопок, 2-спальное', quantity: 1, sum: 329_000, status: 'Выдан', buyer: 'Мадина' },
    { id: 'SM-103 990', date: '2026-11-11', title: 'Рюкзак городской 25 л, влагозащита', quantity: 1, sum: 199_000, status: 'Отменён', buyer: 'Азиз' },
];

/** Комиссия площадки в примере. Настоящий процент ещё не определён (ТЗ, открытый вопрос 1). */
export const COMMISSION = 10;
