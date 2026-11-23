import type { WarehouseStockRow } from '@/market/staff/contract';

/**
 * Образец остатков склада (GET warehouse/stock) — общий для вкладок
 * «Остатки» и «Списания»: показывается, пока сервер отвечает на адрес 404.
 */
const ROWS: WarehouseStockRow[] = [
    { variantId: 101, title: 'Плед флисовый', options: 'Бежевый, 200×220', sku: 'ST-PLD-200-BG', cell: 'A-03-2', quantity: 24, reserved: 3, defect: 1, seller: { name: 'Samarqand Tekstil' } },
    { variantId: 102, title: 'Плед флисовый', options: 'Серый, 150×200', sku: 'ST-PLD-150-GR', cell: 'A-03-3', quantity: 18, reserved: 0, defect: 0, seller: { name: 'Samarqand Tekstil' } },
    { variantId: 103, title: 'Сюзане ручной вышивки', options: '', sku: null, cell: 'A-05-1', quantity: 3, reserved: 1, defect: 0, seller: { name: 'Samarqand Tekstil' } },
    { variantId: 201, title: 'Рюкзак городской 25 л', options: 'Чёрный', sku: 'UB-BP25-BK', cell: 'B-01-1', quantity: 12, reserved: 2, defect: 0, seller: { name: 'Urban Bag' } },
    { variantId: 301, title: 'Казан чугунный 12 л', options: '', sku: 'QU-KZ-12', cell: 'C-02-1', quantity: 7, reserved: 1, defect: 2, seller: { name: 'Qozon Ustaxonasi' } },
    { variantId: 401, title: 'Наушники беспроводные TWS', options: 'Белые', sku: 'TX-TWS-W', cell: 'D-04-2', quantity: 40, reserved: 6, defect: 0, seller: { name: 'Texnomir' } },
    { variantId: 402, title: 'Наушники беспроводные TWS', options: 'Чёрные', sku: 'TX-TWS-B', cell: 'D-04-3', quantity: 35, reserved: 4, defect: 1, seller: { name: 'Texnomir' } },
    { variantId: 501, title: 'Чайник электрический 1,7 л', options: 'Стальной', sku: 'TX-KT17-S', cell: null, quantity: 9, reserved: 9, defect: 0, seller: { name: 'Texnomir' } },
];

export const sampleStock = (): { stock: WarehouseStockRow[] } => ({ stock: ROWS });

/** Поиск по образцу — как искал бы сервер: товар, вариант, артикул, продавец, ячейка. */
export function filterStock(rows: WarehouseStockRow[], query: string): WarehouseStockRow[] {
    const words = query.toLowerCase().split(/\s+/).filter(Boolean);

    if (words.length === 0) return rows;

    return rows.filter((row) => {
        const text = [row.title, row.options, row.sku ?? '', row.seller.name, row.cell ?? ''].join(' ').toLowerCase();

        return words.every((word) => text.includes(word));
    });
}

/** Свободно — можно продать или списать: на полке минус резерв под заказы. */
export const freeOf = (row: WarehouseStockRow): number => Math.max(0, row.quantity - row.reserved);
