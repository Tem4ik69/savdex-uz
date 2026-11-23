/**
 * Образец для раздела кабинета продавца, которого на сервере ещё нет, —
 * поставки на склад (склад BTS — следующий этап). Остальное в кабинете
 * уже с сервера (/market/api/me/…).
 */

export const SAMPLE_SUPPLIES: { id: string; date: string; title: string; quantity: number; accepted: number | null; status: 'planned' | 'accepted' | 'partial' }[] = [
    { id: 'П-0034', date: '2026-11-21', title: 'Постельное бельё, хлопок, 2-спальное', quantity: 40, accepted: null, status: 'planned' },
    { id: 'П-0031', date: '2026-11-12', title: 'Рюкзак городской 25 л, влагозащита', quantity: 60, accepted: 58, status: 'partial' },
    { id: 'П-0027', date: '2026-11-03', title: 'Постельное бельё, хлопок, 2-спальное', quantity: 55, accepted: 55, status: 'accepted' },
];
