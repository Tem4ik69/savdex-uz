import { lang } from '@/market/lang';
import type { WarehouseSupply } from '@/market/staff/contract';
import { hoursAgo } from '@/market/staff/samples';
import { whSuppliesText } from '@/market/text/wh-supplies';

/**
 * Образец поставок склада (GET warehouse/supplies) — общий для вкладок
 * «Поставки» и «Приёмка». Принятая в образце поставка запоминается здесь,
 * до перезагрузки страницы: на вкладке «Поставки» она уже среди принятых.
 */
let kept: WarehouseSupply[] | null = null;

function build(): WarehouseSupply[] {
    const S = lang(whSuppliesText).statuses;
    const status = <C extends WarehouseSupply['status']['code']>(code: C) => ({ code, text: S[code] });

    return [
        {
            number: 'SP-1051',
            status: status('submitted'),
            seller: { name: 'Texnomir' },
            expectedAt: hoursAgo(-3),
            note: 'Две коробки, на каждой — номер поставки',
            items: [
                { itemId: 5101, variantId: 401, title: 'Наушники беспроводные TWS', options: 'Белые', declared: 50, accepted: null, defect: null },
                { itemId: 5102, variantId: 402, title: 'Наушники беспроводные TWS', options: 'Чёрные', declared: 50, accepted: null, defect: null },
                { itemId: 5103, variantId: 501, title: 'Чайник электрический 1,7 л', options: 'Стальной', declared: 12, accepted: null, defect: null },
            ],
            submittedAt: hoursAgo(26),
            receivedAt: null,
        },
        {
            number: 'SP-1048',
            status: status('submitted'),
            seller: { name: 'Samarqand Tekstil' },
            expectedAt: hoursAgo(2),
            note: null,
            items: [
                { itemId: 4801, variantId: 101, title: 'Плед флисовый', options: 'Бежевый, 200×220', declared: 30, accepted: null, defect: null },
                { itemId: 4802, variantId: 102, title: 'Плед флисовый', options: 'Серый, 150×200', declared: 20, accepted: null, defect: null },
                { itemId: 4803, variantId: 103, title: 'Сюзане ручной вышивки', options: '', declared: 4, accepted: null, defect: null },
            ],
            submittedAt: hoursAgo(50),
            receivedAt: null,
        },
        {
            number: 'SP-1039',
            status: status('received'),
            seller: { name: 'Qozon Ustaxonasi' },
            expectedAt: hoursAgo(74),
            note: null,
            items: [{ itemId: 3901, variantId: 301, title: 'Казан чугунный 12 л', options: '', declared: 10, accepted: 7, defect: 2 }],
            submittedAt: hoursAgo(120),
            receivedAt: hoursAgo(73),
        },
        {
            number: 'SP-1032',
            status: status('received'),
            seller: { name: 'Urban Bag' },
            expectedAt: hoursAgo(170),
            note: null,
            items: [{ itemId: 3201, variantId: 201, title: 'Рюкзак городской 25 л', options: 'Чёрный', declared: 10, accepted: 12, defect: 0 }],
            submittedAt: hoursAgo(200),
            receivedAt: hoursAgo(168),
        },
        {
            number: 'SP-1027',
            status: status('rejected'),
            seller: { name: 'Buxoro Hunarmand' },
            expectedAt: hoursAgo(240),
            note: 'Без маркировки',
            items: [{ itemId: 2701, variantId: 601, title: 'Пиала расписная, набор 6 шт.', options: 'Синяя', declared: 15, accepted: null, defect: null }],
            submittedAt: hoursAgo(260),
            receivedAt: null,
        },
    ];
}

export const sampleSupplies = (): { supplies: WarehouseSupply[] } => {
    kept ??= build();

    return { supplies: kept };
};

/** Запомнить поставки образца после действия (приняли, отказали). */
export function keepSampleSupplies(supplies: WarehouseSupply[]): void {
    kept = supplies;
}

/** Расхождение строки с заявкой: > 0 — лишние, < 0 — не хватает; null — ещё не принята. */
export function lineDiff(item: { declared: number; accepted: number | null; defect: number | null }): number | null {
    if (item.accepted === null) return null;

    return item.accepted + (item.defect ?? 0) - item.declared;
}
