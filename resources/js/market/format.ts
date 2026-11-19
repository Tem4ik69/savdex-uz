import { numberLocale } from '@/lib/i18n';

/** Цена в сумах: «1 290 000» с неразрывными пробелами, без валюты. */
export function sum(value: number): string {
    return value.toLocaleString(numberLocale()).replace(/\s/g, ' ');
}

/** Оценка: «4,8» по-русски. */
export function rating(value: number): string {
    return value.toLocaleString(numberLocale(), { minimumFractionDigits: 1, maximumFractionDigits: 1 });
}

/** Форма слова при числе: plural(3, ['товар', 'товара', 'товаров']) → «товара». */
export function plural(count: number, forms: [string, string, string]): string {
    const n = Math.abs(count) % 100;
    const n1 = n % 10;

    if (n > 10 && n < 20) return forms[2];
    if (n1 > 1 && n1 < 5) return forms[1];
    if (n1 === 1) return forms[0];

    return forms[2];
}
