import { plural } from '@/market/format';

/** Пункт выдачи, «Партии»: приём партий со склада. */
const ru = {
    title: 'Принять партию',
    emptyTitle: 'Партий в пути нет',
    emptyText: 'Когда склад отправит партию в ваш пункт, она появится здесь.',
    batch: (number: string) => `Партия ${number}`,
    sentAt: (at: string) => `Отправлена ${at}`,
    deliveredAt: (at: string) => `Принята ${at}`,
    summary: (orders: number, places: number) =>
        `${orders} ${plural(orders, ['заказ', 'заказа', 'заказов'])}, ${places} ${plural(places, ['место', 'места', 'мест'])}`,
    open: 'Принимать',
    close: 'Свернуть',
    checkHint: 'Сверьте коробки с наклейками. Всё на месте и цело — просто примите партию; если нет — отметьте заказ «Проблема» и опишите, что не так.',
    problem: 'Проблема',
    problemOff: 'Всё в порядке',
    problemLabel: 'Что не так',
    problemPlaceholder: 'Нет коробки, повреждена упаковка, не то число мест…',
    problemRequired: 'Опишите проблему',
    accept: 'Принять партию',
    acceptWith: (n: number) => `Принять, проблем: ${n}`,
    acceptHint: 'Заказы без проблем сразу станут «можно забрать» — покупатели получат код. Проблемные заказы разберёт администратор.',
    history: (n: number) => `Принятые партии: ${n}`,
    problemShort: (note: string) => `Проблема: ${note}`,
    noProblems: 'без проблем',
    statusDelivered: 'Принята',
};

const uz: typeof ru = {
    title: 'Partiyani qabul qilish',
    emptyTitle: 'Yo‘ldagi partiyalar yo‘q',
    emptyText: 'Ombor punktingizga partiya jo‘natganda, u shu yerda paydo bo‘ladi.',
    batch: (number) => `Partiya ${number}`,
    sentAt: (at) => `Jo‘natilgan: ${at}`,
    deliveredAt: (at) => `Qabul qilingan: ${at}`,
    summary: (orders, places) => `${orders} ta buyurtma, ${places} joy`,
    open: 'Qabul qilish',
    close: 'Yopish',
    checkHint: 'Qutilarni yorliqlar bilan solishtiring. Hammasi joyida va butun bo‘lsa — partiyani qabul qiling; bo‘lmasa — buyurtmani «Muammo» deb belgilang va nima noto‘g‘riligini yozing.',
    problem: 'Muammo',
    problemOff: 'Hammasi joyida',
    problemLabel: 'Nima noto‘g‘ri',
    problemPlaceholder: 'Quti yo‘q, qadoq shikastlangan, joylar soni boshqa…',
    problemRequired: 'Muammoni yozing',
    accept: 'Partiyani qabul qilish',
    acceptWith: (n) => `Qabul qilish, muammolar: ${n}`,
    acceptHint: 'Muammosiz buyurtmalar darhol «olib ketish mumkin» bo‘ladi — xaridorlar kod oladi. Muammoli buyurtmalarni administrator ko‘rib chiqadi.',
    history: (n) => `Qabul qilingan partiyalar: ${n}`,
    problemShort: (note) => `Muammo: ${note}`,
    noProblems: 'muammosiz',
    statusDelivered: 'Qabul qilingan',
};

export const ptBatchesText = { ru, uz };
