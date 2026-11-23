import type { PointTab } from '@/market/staff/contract';

/** Экран пункта выдачи: подписи вкладок. Тексты разделов — в text/pt-*.ts рядом с ними. */
const ru = {
    tabs: {
        issue: 'Выдать',
        batches: 'Партии',
        unclaimed: 'Невостребованные',
        cash: 'Наличные',
    } as Record<PointTab, string>,
};

const uz: typeof ru = {
    tabs: {
        issue: 'Berish',
        batches: 'Partiyalar',
        unclaimed: 'Olib ketilmaganlar',
        cash: 'Naqd pul',
    },
};

export const pointText = { ru, uz };
