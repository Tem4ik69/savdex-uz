import type { WarehouseTab } from '@/market/staff/contract';

/** Экран склада: подписи вкладок. Тексты разделов — в text/wh-*.ts рядом с ними. */
const ru = {
    tabs: {
        supplies: 'Поставки',
        receiving: 'Приёмка',
        stock: 'Остатки',
        picking: 'Сборка',
        shipments: 'Отгрузки',
        returns: 'Возвраты',
        removals: 'Вывоз',
        writeoffs: 'Списания',
    } as Record<WarehouseTab, string>,
};

const uz: typeof ru = {
    tabs: {
        supplies: 'Yetkazib berishlar',
        receiving: 'Qabul qilish',
        stock: 'Qoldiqlar',
        picking: 'Yig‘ish',
        shipments: 'Jo‘natmalar',
        returns: 'Qaytarishlar',
        removals: 'Olib ketish',
        writeoffs: 'Hisobdan chiqarish',
    },
};

export const warehouseText = { ru, uz };
