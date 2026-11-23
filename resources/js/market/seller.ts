/**
 * Образец для раздела кабинета продавца, которого на сервере ещё нет, —
 * поставки на склад (склад BTS — следующий этап). Остальное в кабинете
 * уже с сервера (/market/api/me/…).
 */

// Номер и название товара — на языке страницы, из text/seller.ts (supplies.number, supplies.items)
export const SAMPLE_SUPPLIES: { id: string; date: string; item: 'bedding' | 'backpack'; quantity: number; accepted: number | null; status: 'planned' | 'accepted' | 'partial' }[] = [
    { id: '0034', date: '2026-11-21', item: 'bedding', quantity: 40, accepted: null, status: 'planned' },
    { id: '0031', date: '2026-11-12', item: 'backpack', quantity: 60, accepted: 58, status: 'partial' },
    { id: '0027', date: '2026-11-03', item: 'bedding', quantity: 55, accepted: 55, status: 'accepted' },
];
