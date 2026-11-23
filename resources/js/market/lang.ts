import { translationsLocale } from '@/lib/i18n';

/**
 * Тексты маркетплейса — на русском и узбекском (решение 23.11: «языки
 * маркетплейса — пока русский и узбекский»). На остальных языках
 * площадки страницы маркетплейса — по-русски.
 *
 * Тексты лежат рядом со страницей, в файле `resources/js/market/text/…`:
 *
 *     const ru = { title: 'Корзина', items: (n: number) => `${n} ${plural(n, ['товар', 'товара', 'товаров'])}` };
 *     const uz: typeof ru = { title: 'Savat', items: (n) => `${n} ta mahsulot` };
 *     export const cartText = { ru, uz };
 *
 * и берутся на отрисовке: `const L = lang(cartText)`, затем `L.title`,
 * `L.items(3)`. Узбекский объявлен типом русского — TypeScript не даст
 * забыть перевод или ошибиться в имени. Формы слова при числе и
 * подстановки — функциями: у русского три формы, узбекскому хватает одной.
 *
 * Узбекский — латиницей, как в словарях сайта: o‘ и g‘ — со знаком ‘,
 * tutuq belgisi — ’ (ma’lumot).
 */
export interface LangPack<T> {
    ru: T;
    uz: T;
}

/** Язык текстов маркетплейса для текущей страницы. */
export function marketLocale(): 'ru' | 'uz' {
    return translationsLocale() === 'uz' ? 'uz' : 'ru';
}

/** Тексты набора на языке страницы — звать на отрисовке, не при загрузке файла. */
export function lang<T>(pack: LangPack<T>): T {
    return pack[marketLocale()];
}
