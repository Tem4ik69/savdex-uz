/** Склад, вкладка «Возвраты» (components/market/staff/Returns.tsx). */
const ru = {
    title: 'Возвраты из пунктов',
    emptyTitle: 'Возвратов нет',
    emptyText: 'Здесь появятся партии из пунктов выдачи: заказы, которые не забрали за 7 дней, и отказы при получении.',
    status: {
        sent: 'Едет на склад',
        received: 'Принята',
    },
    from: (name: string) => `Из пункта: ${name}`,
    sentAt: (at: string) => `Отправлена ${at}`,
    ordersCount: (n: number) => `Заказов: ${n}`,
    good: 'Годен',
    defect: 'Брак',
    short: (n: number) => `не хватает ${n}`,
    receive: 'Принять партию',
    confirmReceive: (number: string, good: number, defect: number) => `Принять партию ${number}: годных ${good}, брак ${defect}?`,
    confirmShort: (n: number) => `Не хватает ${n} шт. — всё равно принять? Недостачу разберёт администратор.`,
    totals: (good: number, defect: number) => `Годных ${good} · брак ${defect}`,
    hint: 'Годный товар вернётся в остаток и снова пойдёт в продажу. Брак останется на складе, пока продавец его не вывезет.',
};

const uz: typeof ru = {
    title: 'Punktlardan qaytarishlar',
    emptyTitle: 'Qaytarishlar yo‘q',
    emptyText: 'Bu yerda topshirish punktlaridan partiyalar paydo bo‘ladi: 7 kun ichida olib ketilmagan buyurtmalar va olishda rad etilganlar.',
    status: {
        sent: 'Omborga kelmoqda',
        received: 'Qabul qilindi',
    },
    from: (name) => `Punktdan: ${name}`,
    sentAt: (at) => `Jo‘natildi: ${at}`,
    ordersCount: (n) => `Buyurtmalar: ${n}`,
    good: 'Yaroqli',
    defect: 'Nuqsonli',
    short: (n) => `${n} ta yetishmaydi`,
    receive: 'Partiyani qabul qilish',
    confirmReceive: (number, good, defect) => `${number} partiyasi qabul qilinsinmi: yaroqli ${good}, nuqsonli ${defect}?`,
    confirmShort: (n) => `${n} dona yetishmaydi — baribir qabul qilinsinmi? Kamomadni administrator ko‘rib chiqadi.`,
    totals: (good, defect) => `Yaroqli ${good} · nuqsonli ${defect}`,
    hint: 'Yaroqli mahsulot qoldiqqa qaytadi va yana sotuvga chiqadi. Nuqsonli mahsulot sotuvchi olib ketguncha omborda qoladi.',
};

export const returnsText = { ru, uz };
