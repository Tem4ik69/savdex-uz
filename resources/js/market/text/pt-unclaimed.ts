import { plural } from '@/market/format';

/** Пункт выдачи, «Невостребованные»: не забрали за 7 дней и отказы — на склад. */
const ru = {
    title: 'Невостребованные',
    intro: 'Заказы, которые не забрали за 7 дней, и отказы при получении. Отметьте коробки и соберите возвратную партию — склад заберёт её вместе со следующей доставкой.',
    emptyTitle: 'Возвращать нечего',
    emptyText: 'Здесь появятся заказы, которые не забрали в срок, и отказы при получении.',
    readyAt: (at: string) => `В пункте с ${at}`,
    inBatch: (number: string) => `В возвратной партии ${number}`,
    selectAll: 'Отметить все',
    selectNone: 'Снять отметки',
    create: (n: number) => (n > 0 ? `Собрать возвратную партию (${n})` : 'Собрать возвратную партию'),
    createHint: 'Отметьте заказы, которые кладёте в возвратную партию.',
    confirm: (n: number) => `Собрать возвратную партию из ${n} ${plural(n, ['заказа', 'заказов', 'заказов'])}? Убрать заказ из неё потом будет нельзя.`,
};

const uz: typeof ru = {
    title: 'Olib ketilmaganlar',
    intro: '7 kun ichida olib ketilmagan buyurtmalar va olishdan voz kechilganlar. Qutilarni belgilang va qaytarish partiyasini yig‘ing — ombor uni keyingi yetkazib berish bilan olib ketadi.',
    emptyTitle: 'Qaytariladigan narsa yo‘q',
    emptyText: 'Bu yerda muddatida olib ketilmagan va olishdan voz kechilgan buyurtmalar paydo bo‘ladi.',
    readyAt: (at) => `Punktda ${at} dan beri`,
    inBatch: (number) => `${number} qaytarish partiyasida`,
    selectAll: 'Hammasini belgilash',
    selectNone: 'Belgilarni olib tashlash',
    create: (n) => (n > 0 ? `Qaytarish partiyasini yig‘ish (${n})` : 'Qaytarish partiyasini yig‘ish'),
    createHint: 'Qaytarish partiyasiga solayotgan buyurtmalarni belgilang.',
    confirm: (n) => `${n} ta buyurtmadan qaytarish partiyasi yig‘ilsinmi? Keyin buyurtmani undan olib bo‘lmaydi.`,
};

export const ptUnclaimedText = { ru, uz };
