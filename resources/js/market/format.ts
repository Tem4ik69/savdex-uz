import { numberLocale } from '@/lib/i18n';
import { marketLocale } from '@/market/lang';

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

/** Узбекские месяцы: у ICU браузеров их часто нет, и «uz-Latn» печатает «M11 23». */
const UZ_MONTHS = ['yanvar', 'fevral', 'mart', 'aprel', 'may', 'iyun', 'iyul', 'avgust', 'sentabr', 'oktabr', 'noyabr', 'dekabr'];

/**
 * Дата на языке страницы по времени Ташкента: «18 ноября» / «18-noyabr»,
 * со временем — «18 ноября, 14:05» / «18-noyabr, 14:05».
 */
export function dateText(value: Date, withTime: boolean): string {
    const zone = { timeZone: 'Asia/Tashkent' } as const;

    if (marketLocale() !== 'uz') {
        return value.toLocaleString('ru-RU', { ...zone, day: 'numeric', month: 'long', ...(withTime ? { hour: '2-digit', minute: '2-digit' } : {}) });
    }

    const parts = Object.fromEntries(
        new Intl.DateTimeFormat('en-GB', { ...zone, day: 'numeric', month: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
            .formatToParts(value)
            .map((part) => [part.type, part.value]),
    );
    const date = `${parts.day}-${UZ_MONTHS[Number(parts.month) - 1]}`;

    return withTime ? `${date}, ${parts.hour}:${parts.minute}` : date;
}
