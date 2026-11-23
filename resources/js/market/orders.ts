import { api, ApiError } from '@/market/api';
import { lang, marketLocale } from '@/market/lang';
import { notify } from '@/market/store';
import { commonText } from '@/market/text/common';
import { orderText } from '@/market/text/order';
import type { OrderStatusView } from '@/market/types';

/**
 * Заказы — помощники страниц: шаги заказа для полосы статуса и оплата
 * картой. Сами заказы — на сервере (/market/api/checkout, orders, …).
 */

/** Путь заказа по шагам. Оплата (картой или при получении) — первый шаг. */
const PATH: { key: keyof typeof orderText.ru.steps; codes: OrderStatusView['code'][] }[] = [
    { key: 'created', codes: ['created', 'paid', 'cash_on_pickup'] },
    { key: 'assembling', codes: ['assembling'] },
    { key: 'inTransit', codes: ['in_transit'] },
    { key: 'ready', codes: ['ready'] },
    { key: 'issued', codes: ['issued'] },
];

/** Шаги с подписями на языке страницы — звать на отрисовке. */
export function steps(): { label: string; codes: OrderStatusView['code'][] }[] {
    const L = lang(orderText);

    return PATH.map((step) => ({ label: L.steps[step.key], codes: step.codes }));
}

/** Номер шага на полосе; -1 — заказ отменён или деньги возвращаются. */
export const stepIndex = (code: OrderStatusView['code']): number => PATH.findIndex((step) => step.codes.includes(code));

/** Как выглядит метка статуса. */
export function statusTone(code: OrderStatusView['code']): string {
    if (code === 'ready') return 'mk-pill--ok';
    if (code === 'created') return 'mk-pill--warn';
    if (code === 'issued' || code === 'cancelled' || code === 'refunded' || code === 'refund_pending') return 'mk-pill--off';

    return '';
}

/**
 * Провайдер карты. Решение 23.11 (база команды, «Оплата — пока только
 * Uzum»): Payme и Click в оформлении не показываем, хотя код на сервере есть.
 */
const PROVIDERS = ['uzum'] as const;

/**
 * Открыть оплату заказа картой и уйти на страницу Uzum. Провайдер не
 * включён на сервере (422 с полем provider) — сообщение, покупатель
 * остаётся на странице заказа (false).
 */
export async function payByCard(number: string): Promise<boolean> {
    for (const provider of PROVIDERS) {
        try {
            const { redirect } = await api<{ redirect: string }>(`orders/${number}/pay`, { body: { provider } });

            window.location.assign(redirect);

            return true;
        } catch (error) {
            if (error instanceof ApiError && error.status === 422 && error.errors.provider) continue;

            notify(error instanceof ApiError ? error.message : lang(commonText).payFailed, true);

            return false;
        }
    }

    notify(lang(commonText).cardUnavailable, true);

    return false;
}

/** «18 ноября, 14:05» по времени Ташкента — даты с сервера в UTC; по-узбекски — «18-noyabr, 14:05». */
export function when(iso: string | null): string {
    if (!iso) return '';

    return new Date(iso).toLocaleString(marketLocale() === 'uz' ? 'uz-Latn-UZ' : 'ru-RU', { day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Tashkent' });
}
