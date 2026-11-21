/**
 * Наполнение главной, которого на сервере пока нет: подборки-кружки и
 * купоны. Баннеры приходят из админки (/market/api/banners); эти —
 * запасные, на случай когда там пусто.
 */

/** Подборки-кружки: каждая ведёт в каталог со своим отбором. */
export const STORIES: { label: string; emoji: string; query: string }[] = [
    { label: 'Скидки', emoji: '🔥', query: 'only=sale' },
    { label: 'Новинки', emoji: '✨', query: 'only=new' },
    { label: 'Хиты', emoji: '🏆', query: 'only=hit' },
    { label: 'До 100 000', emoji: '💸', query: 'max=100000' },
    { label: 'Сделано в UZ', emoji: '🇺🇿', query: 'category=home' },
    { label: 'К зиме', emoji: '❄️', query: 'category=clothes' },
    { label: 'Для дома', emoji: '🏠', query: 'category=home' },
    { label: 'Детям', emoji: '🧸', query: 'category=kids' },
    { label: 'Гаджеты', emoji: '🎧', query: 'category=electronics' },
    { label: 'Красота', emoji: '💄', query: 'category=beauty' },
    { label: 'Ремонт', emoji: '🛠️', query: 'category=tools' },
    { label: 'Спорт', emoji: '⚽', query: 'category=sport' },
];

export const BANNERS: { eyebrow: string; title: string; text: string; cta: string; query: string; emoji: string }[] = [
    { eyebrow: 'Скидки ноября', title: 'Техника для дома до −40%', text: 'Заберите в любом пункте выдачи BTS в Ташкенте', cta: 'Смотреть скидки', query: 'only=sale', emoji: '🧺' },
    { eyebrow: 'Выдача в пунктах BTS', title: 'Закажите онлайн — заберите рядом с домом', text: 'Оплата картой или наличными при получении', cta: 'Выбрать товары', query: '', emoji: '📦' },
    { eyebrow: 'Сделано в Узбекистане', title: 'Текстиль и посуда от местных продавцов', text: 'Хлопок из Самарканда, чугун из Намангана', cta: 'В каталог', query: 'category=home', emoji: '🍲' },
];

export const COUPONS: { value: string; text: string; cta: string }[] = [
    { value: '−50 000 сум', text: 'при заказе от 500 000 сум', cta: 'Взять' },
    { value: '−10%', text: 'на первый заказ', cta: 'Взять' },
    { value: '0 сум', text: 'выдача в пункте BTS', cta: 'Подробнее' },
];

/** Баннер из админки (места slider, strip, catalog). */
export interface ServerBanner {
    url: string | null;
    alt: string;
    image: string;
    imageMobile: string | null;
}
