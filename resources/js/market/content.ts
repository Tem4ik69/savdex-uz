/**
 * Наполнение главной, которого на сервере пока нет: подборки-кружки и
 * купоны. Баннеры приходят из админки (/market/api/banners); эти —
 * запасные, на случай когда там пусто.
 */

import type { LangPack } from '@/market/lang';

interface Story {
    label: string;
    emoji: string;
    query: string;
}

interface Banner {
    eyebrow: string;
    title: string;
    text: string;
    cta: string;
    query: string;
    emoji: string;
}

interface Coupon {
    value: string;
    text: string;
    cta: string;
}

/**
 * Подборки-кружки: каждая ведёт в каталог со своим отбором. Наборы — на
 * двух языках, брать через lang(STORIES) на отрисовке.
 */
export const STORIES: LangPack<Story[]> = {
    ru: [
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
    ],
    uz: [
        { label: 'Chegirmalar', emoji: '🔥', query: 'only=sale' },
        { label: 'Yangiliklar', emoji: '✨', query: 'only=new' },
        { label: 'Xitlar', emoji: '🏆', query: 'only=hit' },
        { label: '100 000 gacha', emoji: '💸', query: 'max=100000' },
        { label: 'UZda ishlab chiqarilgan', emoji: '🇺🇿', query: 'category=home' },
        { label: 'Qishga', emoji: '❄️', query: 'category=clothes' },
        { label: 'Uy uchun', emoji: '🏠', query: 'category=home' },
        { label: 'Bolalarga', emoji: '🧸', query: 'category=kids' },
        { label: 'Gadjetlar', emoji: '🎧', query: 'category=electronics' },
        { label: 'Go‘zallik', emoji: '💄', query: 'category=beauty' },
        { label: 'Ta’mirlash', emoji: '🛠️', query: 'category=tools' },
        { label: 'Sport', emoji: '⚽', query: 'category=sport' },
    ],
};

export const BANNERS: LangPack<Banner[]> = {
    ru: [
        { eyebrow: 'Скидки ноября', title: 'Техника для дома до −40%', text: 'Заберите в любом пункте выдачи BTS в Ташкенте', cta: 'Смотреть скидки', query: 'only=sale', emoji: '🧺' },
        { eyebrow: 'Выдача в пунктах BTS', title: 'Закажите онлайн — заберите рядом с домом', text: 'Оплата картой или наличными при получении', cta: 'Выбрать товары', query: '', emoji: '📦' },
        { eyebrow: 'Сделано в Узбекистане', title: 'Текстиль и посуда от местных продавцов', text: 'Хлопок из Самарканда, чугун из Намангана', cta: 'В каталог', query: 'category=home', emoji: '🍲' },
    ],
    uz: [
        { eyebrow: 'Noyabr chegirmalari', title: 'Uy uchun texnika −40% gacha', text: 'Toshkentdagi istalgan BTS topshirish punktidan olib keting', cta: 'Chegirmalarni ko‘rish', query: 'only=sale', emoji: '🧺' },
        { eyebrow: 'BTS punktlarida topshirish', title: 'Onlayn buyurtma bering — uyingiz yonidan oling', text: 'To‘lov karta orqali yoki olishda naqd pulda', cta: 'Mahsulot tanlash', query: '', emoji: '📦' },
        { eyebrow: 'O‘zbekistonda ishlab chiqarilgan', title: 'Mahalliy sotuvchilardan to‘qimachilik va idishlar', text: 'Samarqand paxtasi, Namangan cho‘yani', cta: 'Katalogga', query: 'category=home', emoji: '🍲' },
    ],
};

export const COUPONS: LangPack<Coupon[]> = {
    ru: [
        { value: '−50 000 сум', text: 'при заказе от 500 000 сум', cta: 'Взять' },
        { value: '−10%', text: 'на первый заказ', cta: 'Взять' },
        { value: '0 сум', text: 'выдача в пункте BTS', cta: 'Подробнее' },
    ],
    uz: [
        { value: '−50 000 so‘m', text: '500 000 so‘mdan boshlab buyurtmaga', cta: 'Olish' },
        { value: '−10%', text: 'birinchi buyurtmaga', cta: 'Olish' },
        { value: '0 so‘m', text: 'BTS punktida topshirish', cta: 'Batafsil' },
    ],
};

/** Баннер из админки (места slider, strip, catalog). */
export interface ServerBanner {
    url: string | null;
    alt: string;
    image: string;
    imageMobile: string | null;
}
