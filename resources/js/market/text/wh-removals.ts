/** Склад, вкладка «Вывоз» (components/market/staff/Removals.tsx). */
const ru = {
    title: 'Вывоз продавцами',
    emptyTitle: 'Заявок на вывоз нет',
    emptyText: 'Продавец оформляет вывоз годного остатка или брака в своём кабинете — заявка появится здесь.',
    active: 'В работе',
    history: 'Завершённые',
    status: {
        requested: 'Новая заявка',
        ready: 'Собрано, ждёт продавца',
        done: 'Выдано продавцу',
        cancelled: 'Отменена продавцом',
    },
    kind: {
        good: 'годное',
        defect: 'брак',
    },
    requestedAt: (at: string) => `Заявка от ${at}`,
    doneAt: (at: string) => `Выдано ${at}`,
    ready: 'Собрано, ждёт продавца',
    done: 'Выдано продавцу',
    confirmDone: (number: string, seller: string) => `Выдать заявку ${number} продавцу «${seller}»? Товар уйдёт с остатка склада.`,
    hint: 'Соберите товар по заявке и нажмите «Собрано» — продавец увидит, что можно приезжать. Когда отдали — «Выдано продавцу»: товар уйдёт с остатка склада.',
};

const uz: typeof ru = {
    title: 'Sotuvchilar olib ketishi',
    emptyTitle: 'Olib ketish uchun arizalar yo‘q',
    emptyText: 'Sotuvchi yaroqli qoldiq yoki nuqsonli mahsulotni olib ketishni o‘z kabinetida rasmiylashtiradi — ariza shu yerda paydo bo‘ladi.',
    active: 'Ishda',
    history: 'Yakunlanganlar',
    status: {
        requested: 'Yangi ariza',
        ready: 'Yig‘ildi, sotuvchini kutmoqda',
        done: 'Sotuvchiga berildi',
        cancelled: 'Sotuvchi bekor qildi',
    },
    kind: {
        good: 'yaroqli',
        defect: 'nuqsonli',
    },
    requestedAt: (at) => `Ariza sanasi: ${at}`,
    doneAt: (at) => `Berildi: ${at}`,
    ready: 'Yig‘ildi, sotuvchini kutmoqda',
    done: 'Sotuvchiga berildi',
    confirmDone: (number, seller) => `${number} arizasi «${seller}» sotuvchisiga berilsinmi? Mahsulot ombor qoldig‘idan chiqadi.`,
    hint: 'Ariza bo‘yicha mahsulotni yig‘ing va «Yig‘ildi» tugmasini bosing — sotuvchi kelish mumkinligini ko‘radi. Topshirgach — «Sotuvchiga berildi»: mahsulot ombor qoldig‘idan chiqadi.',
};

export const removalsText = { ru, uz };
