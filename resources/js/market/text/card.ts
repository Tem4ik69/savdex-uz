import { plural, sum } from '@/market/format';

/** Тексты карточки товара (MarketCard) — она стоит во всех лентах маркетплейса. */
const ru = {
    outOfStock: 'Нет в наличии',
    favAdd: 'В избранное',
    favRemove: 'Убрать из избранного',
    currency: 'сум',
    reviews: (n: number) => `${sum(n)} ${plural(n, ['отзыв', 'отзыва', 'отзывов'])}`,
    inCart: 'В корзине',
    toCart: 'В корзину',
    inCartLabel: (title: string) => `В корзине: ${title}`,
    toCartLabel: (title: string) => `В корзину: ${title}`,
};

const uz: typeof ru = {
    outOfStock: 'Mavjud emas',
    favAdd: 'Sevimlilarga',
    favRemove: 'Sevimlilardan olib tashlash',
    currency: 'so‘m',
    reviews: (n) => `${sum(n)} ta sharh`,
    inCart: 'Savatda',
    toCart: 'Savatga',
    inCartLabel: (title) => `Savatda: ${title}`,
    toCartLabel: (title) => `Savatga: ${title}`,
};

export const cardText = { ru, uz };
