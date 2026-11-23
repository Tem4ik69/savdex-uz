/** Общие сообщения маркетплейса: ошибки запросов, оплата, валюта. */
const ru = {
    /** Валюта после суммы: «1 290 000 сум» */
    currency: 'сум',
    requestFailed: 'Не получилось выполнить запрос. Проверьте связь и попробуйте ещё раз.',
    payFailed: 'Не получилось открыть оплату. Попробуйте ещё раз.',
    cardUnavailable: 'Оплата картой сейчас недоступна. Можно отменить заказ и оформить с оплатой при получении.',
};

const uz: typeof ru = {
    currency: 'so‘m',
    requestFailed: 'So‘rovni bajarib bo‘lmadi. Internet aloqasini tekshirib, qayta urinib ko‘ring.',
    payFailed: 'To‘lov sahifasini ochib bo‘lmadi. Qayta urinib ko‘ring.',
    cardUnavailable: 'Karta orqali to‘lov hozircha ishlamayapti. Buyurtmani bekor qilib, qabul qilishda to‘lov bilan qayta rasmiylashtirish mumkin.',
};

export const commonText = { ru, uz };
