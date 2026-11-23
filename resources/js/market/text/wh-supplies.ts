import type { WarehouseSupply } from '@/market/staff/contract';

type SupplyCode = WarehouseSupply['status']['code'];

/** Склад, вкладка «Поставки»: поставки продавцов на этот склад. */
const ru = {
    title: 'Поставки',
    filterLabel: 'Какие поставки показать',
    filters: {
        submitted: 'Ждём',
        received: 'Приняты',
        rejected: 'Отказ',
    } as Record<SupplyCode, string>,
    /** Статусы образца — на сервере их пишет он сам */
    statuses: {
        submitted: 'Ждём на склад',
        received: 'Принята',
        rejected: 'Отказ в приёмке',
    } as Record<SupplyCode, string>,
    colSupply: 'Поставка',
    colExpected: 'Привезут',
    colItems: 'Товары',
    noDate: 'дата не указана',
    submittedAt: (date: string) => `отправлена ${date}`,
    receivedAt: (date: string) => `принята ${date}`,
    declared: (n: number) => `заявлено ${n}`,
    accepted: (accepted: number, defect: number) => (defect ? `принято ${accepted}, брак ${defect}` : `принято ${accepted}`),
    short: (n: number) => `не хватает ${n}`,
    extra: (n: number) => `лишних ${n}`,
    receive: 'Принять',
    empty: {
        submitted: 'Сейчас никто не везёт товар на склад',
        received: 'Принятых поставок пока нет',
        rejected: 'Отказов не было',
    } as Record<SupplyCode, string>,
    emptyTitle: 'Пусто',
    hint: 'Поставку принимаем по факту: пришло больше или меньше заявленного — принимаем сколько есть, продавец увидит расхождение. Брак лежит на складе, пока продавец его не вывезет.',
};

const uz: typeof ru = {
    title: 'Yetkazib berishlar',
    filterLabel: 'Qaysi yetkazib berishlarni ko‘rsatish',
    filters: {
        submitted: 'Kutilmoqda',
        received: 'Qabul qilingan',
        rejected: 'Rad etilgan',
    },
    statuses: {
        submitted: 'Omborga kutilmoqda',
        received: 'Qabul qilindi',
        rejected: 'Qabul rad etildi',
    },
    colSupply: 'Yetkazib berish',
    colExpected: 'Olib kelinadi',
    colItems: 'Mahsulotlar',
    noDate: 'sana ko‘rsatilmagan',
    submittedAt: (date) => `${date} yuborilgan`,
    receivedAt: (date) => `${date} qabul qilingan`,
    declared: (n) => `arizada ${n}`,
    accepted: (accepted, defect) => (defect ? `qabul qilindi ${accepted}, nuqson ${defect}` : `qabul qilindi ${accepted}`),
    short: (n) => `${n} ta yetishmaydi`,
    extra: (n) => `${n} ta ortiqcha`,
    receive: 'Qabul qilish',
    empty: {
        submitted: 'Hozir omborga hech kim mahsulot olib kelmayapti',
        received: 'Qabul qilingan yetkazib berishlar hozircha yo‘q',
        rejected: 'Rad etishlar bo‘lmagan',
    },
    emptyTitle: 'Bo‘sh',
    hint: 'Yetkazib berish fakt bo‘yicha qabul qilinadi: arizadagidan ko‘p yoki kam kelsa — borini qabul qilamiz, sotuvchi farqni ko‘radi. Nuqsonli mahsulot sotuvchi olib ketguncha omborda turadi.',
};

export const whSuppliesText = { ru, uz };
