import type { PointMe, WarehouseMe } from '@/market/staff/contract';

/**
 * Образцы для экранов склада и пункта выдачи — того же вида, что ответы
 * сервера по контракту (staff/contract.ts). Показываются, пока адреса
 * /market/api/warehouse/… и /market/api/point/… отвечают 404. Образцы
 * разделов — рядом с экранами (components/market/staff/*).
 */
export const sampleWarehouseMe = (): WarehouseMe => ({
    warehouse: { code: 'bts-tashkent', name: 'Склад BTS, Ташкент', address: 'Сергелийский район, ул. Янги Сергели, 15' },
    staff: { name: 'Сотрудник склада' },
    counts: { receiving: 2, picking: 3, shipments: 1, returns: 1, removals: 1 },
});

export const samplePointMe = (): PointMe => ({
    point: { code: 'demo-chilanzar', name: 'BTS Чиланзар', address: 'Чиланзарский район, ул. Бунёдкор, 12', hours: 'Пн–Сб 9:00–20:00' },
    staff: { name: 'Сотрудник пункта' },
    counts: { batches: 1, unclaimed: 2 },
});

/** Момент «сейчас минус часы» — образцы не стареют. */
export const hoursAgo = (hours: number): string => new Date(Date.now() - hours * 3600_000).toISOString();
