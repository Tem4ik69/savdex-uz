import { plural } from '@/market/format';

/** Склад, вкладка «Сборка» (components/market/staff/Picking.tsx). */
const ru = {
    title: 'Сборка заказов',
    filterLabel: 'Пункт выдачи',
    all: 'Все',
    emptyTitle: 'Собирать нечего',
    emptyText: 'Здесь появятся оплаченные заказы и заказы с оплатой при получении.',
    status: {
        paid: 'Ждёт сборки',
        assembling: 'Собирается',
        assembled: 'Собран',
    },
    created: (at: string) => `Заказ от ${at}`,
    point: (name: string) => `В пункт: ${name}`,
    lines: (n: number) => `${n} ${plural(n, ['позиция', 'позиции', 'позиций'])}`,
    noCell: 'без ячейки',
    tickHint: 'Касайтесь строки, когда положили товар в заказ.',
    ticked: (n: number, total: number) => `Отмечено ${n} из ${total}`,
    start: 'Начать сборку',
    done: 'Собрано',
    doneDisabled: 'Сначала отметьте все строки',
    placesTitle: 'Сколько мест получилось?',
    placesHint: 'Коробки и пакеты: на каждое место — наклейка с номером заказа.',
    placesLabel: 'Мест',
    placesConfirm: 'Подтвердить',
    less: 'Меньше',
    more: 'Больше',
    readyNote: 'Собран — ждёт отгрузки в пункт',
    wholeHint: 'Заказ выдаётся только целиком: если товара не хватает или он с браком — не нажимайте «Собрано», сообщите администратору.',
};

const uz: typeof ru = {
    title: 'Buyurtmalarni yig‘ish',
    filterLabel: 'Topshirish punkti',
    all: 'Hammasi',
    emptyTitle: 'Yig‘ish uchun hech narsa yo‘q',
    emptyText: 'Bu yerda to‘langan buyurtmalar va olishda to‘lanadigan buyurtmalar paydo bo‘ladi.',
    status: {
        paid: 'Yig‘ishni kutmoqda',
        assembling: 'Yig‘ilmoqda',
        assembled: 'Yig‘ildi',
    },
    created: (at) => `Buyurtma sanasi: ${at}`,
    point: (name) => `Punktga: ${name}`,
    lines: (n) => `${n} ta pozitsiya`,
    noCell: 'yacheykasiz',
    tickHint: 'Mahsulotni buyurtmaga solganingizda qatorga bosing.',
    ticked: (n, total) => `${total} tadan ${n} tasi belgilandi`,
    start: 'Yig‘ishni boshlash',
    done: 'Yig‘ildi',
    doneDisabled: 'Avval barcha qatorlarni belgilang',
    placesTitle: 'Nechta joy bo‘ldi?',
    placesHint: 'Qutilar va paketlar: har bir joyga buyurtma raqami yozilgan yorliq.',
    placesLabel: 'Joylar',
    placesConfirm: 'Tasdiqlash',
    less: 'Kamroq',
    more: 'Ko‘proq',
    readyNote: 'Yig‘ildi — punktga jo‘natishni kutmoqda',
    wholeHint: 'Buyurtma faqat to‘liq topshiriladi: mahsulot yetishmasa yoki nuqsonli bo‘lsa — «Yig‘ildi» tugmasini bosmang, administratorga xabar bering.',
};

export const pickingText = { ru, uz };
