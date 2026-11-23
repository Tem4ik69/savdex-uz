import type { Writeoff } from '@/market/staff/contract';

type WriteoffCode = Writeoff['status']['code'];

/** Склад, вкладка «Списания»: заявки на списание, подтверждает администратор. */
const ru = {
    title: 'Списания',
    add: 'Заявка на списание',
    formTitle: 'Заявка на списание',
    variant: 'Товар',
    choose: 'Выберите товар',
    chooseRequired: 'Выберите товар',
    free: (n: number) => `свободно ${n} шт.`,
    noFree: 'нет свободного остатка',
    quantityRequired: 'Укажите, сколько списать',
    quantityMax: (n: number) => `Не больше ${n} шт. — столько свободно`,
    reasonPlaceholder: 'Например: разбит при хранении, испорчен водой',
    submit: 'Отправить администратору',
    statuses: {
        requested: 'Ждёт администратора',
        approved: 'Подтверждено',
        rejected: 'Отклонено',
    } as Record<WriteoffCode, string>,
    colNumber: 'Заявка',
    colAuthor: 'Кто',
    emptyTitle: 'Заявок на списание нет',
    emptyText: 'Испорченный или потерянный товар — заявкой: администратор проверит и подтвердит.',
    hint: 'Списание подтверждает администратор маркетплейса — до подтверждения остаток не меняется.',
};

const uz: typeof ru = {
    title: 'Hisobdan chiqarish',
    add: 'Hisobdan chiqarishga ariza',
    formTitle: 'Hisobdan chiqarishga ariza',
    variant: 'Mahsulot',
    choose: 'Mahsulotni tanlang',
    chooseRequired: 'Mahsulotni tanlang',
    free: (n) => `erkin: ${n} dona`,
    noFree: 'erkin qoldiq yo‘q',
    quantityRequired: 'Qanchasini hisobdan chiqarishni ko‘rsating',
    quantityMax: (n) => `${n} donadan oshmasin — shuncha erkin`,
    reasonPlaceholder: 'Masalan: saqlashda singan, suvdan buzilgan',
    submit: 'Administratorga yuborish',
    statuses: {
        requested: 'Administratorni kutmoqda',
        approved: 'Tasdiqlangan',
        rejected: 'Rad etilgan',
    },
    colNumber: 'Ariza',
    colAuthor: 'Kim',
    emptyTitle: 'Hisobdan chiqarishga arizalar yo‘q',
    emptyText: 'Buzilgan yoki yo‘qolgan mahsulot — ariza orqali: administrator tekshirib, tasdiqlaydi.',
    hint: 'Hisobdan chiqarishni marketpleys administratori tasdiqlaydi — tasdiqlanmaguncha qoldiq o‘zgarmaydi.',
};

export const whWriteoffsText = { ru, uz };
