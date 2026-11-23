import { plural } from '@/market/format';

/** Пункт выдачи, «Наличные»: что получено за день при выдаче. */
const ru = {
    title: 'Наличные за день',
    date: 'День',
    prev: 'Предыдущий день',
    next: 'Следующий день',
    today: 'Сегодня',
    total: 'Получено наличными',
    count: (n: number) => `${n} ${plural(n, ['заказ', 'заказа', 'заказов'])}`,
    emptyTitle: 'Наличных за этот день нет',
    emptyText: 'Здесь будут заказы, оплаченные наличными при получении.',
    note: 'Наличные сдавайте по правилам BTS. Сверка с SavdEx — каждую ночь: расхождение увидит администратор.',
};

const uz: typeof ru = {
    title: 'Kunlik naqd pul',
    date: 'Kun',
    prev: 'Oldingi kun',
    next: 'Keyingi kun',
    today: 'Bugun',
    total: 'Naqd olingan',
    count: (n) => `${n} ta buyurtma`,
    emptyTitle: 'Bu kunda naqd pul yo‘q',
    emptyText: 'Bu yerda olishda naqd to‘langan buyurtmalar bo‘ladi.',
    note: 'Naqd pulni BTS qoidalari bo‘yicha topshiring. SavdEx bilan solishtirish — har kecha: farqni administrator ko‘radi.',
};

export const ptCashText = { ru, uz };
