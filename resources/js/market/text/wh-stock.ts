/** Склад, вкладка «Остатки». */
const ru = {
    title: 'Остатки',
    searchPlaceholder: 'Товар, артикул, продавец или ячейка',
    colSku: 'Артикул',
    colShelf: 'На полке',
    colReserved: 'В резерве',
    colFree: 'Свободно',
    colDefect: 'Брак',
    totals: (n: number) => `Итого, позиций: ${n}`,
    notFoundTitle: 'Ничего не нашлось',
    notFoundText: 'Попробуйте другое слово или часть артикула.',
    emptyTitle: 'На складе пока ничего нет',
    emptyText: 'Остаток появится после первой приёмки.',
    hint: 'Остаток меняют только движения: приёмка, выдача, вывоз, списание. «Свободно» — то, что можно продать: на полке минус резерв под заказы. Брак лежит отдельно и ждёт вывоза продавцом.',
};

const uz: typeof ru = {
    title: 'Qoldiqlar',
    searchPlaceholder: 'Mahsulot, artikul, sotuvchi yoki yacheyka',
    colSku: 'Artikul',
    colShelf: 'Javonda',
    colReserved: 'Rezervda',
    colFree: 'Erkin',
    colDefect: 'Nuqson',
    totals: (n) => `Jami, pozitsiyalar: ${n}`,
    notFoundTitle: 'Hech narsa topilmadi',
    notFoundText: 'Boshqa so‘z yoki artikulning bir qismi bilan urinib ko‘ring.',
    emptyTitle: 'Omborda hozircha hech narsa yo‘q',
    emptyText: 'Qoldiq birinchi qabuldan keyin paydo bo‘ladi.',
    hint: 'Qoldiqni faqat harakatlar o‘zgartiradi: qabul qilish, topshirish, olib ketish, hisobdan chiqarish. «Erkin» — sotish mumkin bo‘lgani: javondagidan buyurtmalar uchun rezerv ayirilgan. Nuqsonli mahsulot alohida turadi va sotuvchi olib ketishini kutadi.',
};

export const whStockText = { ru, uz };
