import { api, ApiError } from '@/market/api';
import { notify } from '@/market/store';
import type { OrderStatusView } from '@/market/types';

/**
 * Заказы — помощники страниц: шаги заказа для полосы статуса и оплата
 * картой. Сами заказы — на сервере (/market/api/checkout, orders, …).
 */

/** Путь заказа по шагам. Оплата (картой или при получении) — первый шаг. */
export const STEPS: { label: string; codes: OrderStatusView['code'][] }[] = [
    { label: 'Оформлен', codes: ['created', 'paid', 'cash_on_pickup'] },
    { label: 'Собирается', codes: ['assembling'] },
    { label: 'В пути', codes: ['in_transit'] },
    { label: 'Можно забрать', codes: ['ready'] },
    { label: 'Выдан', codes: ['issued'] },
];

/** Номер шага на полосе; -1 — заказ отменён или деньги возвращаются. */
export const stepIndex = (code: OrderStatusView['code']): number => STEPS.findIndex((step) => step.codes.includes(code));

/** Как выглядит метка статуса. */
export function statusTone(code: OrderStatusView['code']): string {
    if (code === 'ready') return 'mk-pill--ok';
    if (code === 'created') return 'mk-pill--warn';
    if (code === 'issued' || code === 'cancelled' || code === 'refunded' || code === 'refund_pending') return 'mk-pill--off';

    return '';
}

/** Провайдеры карты по порядку: берётся первый, который включён на сервере. */
const PROVIDERS = ['uzum', 'payme', 'click'] as const;

/**
 * Открыть оплату заказа картой и уйти на страницу провайдера. Сервер сам
 * знает, какие провайдеры включены, но списка не отдаёт: пробуем по
 * порядку, «провайдер не включён» (422 с полем provider) — следующий.
 * false — ни один не открылся, покупатель остаётся на странице заказа.
 */
export async function payByCard(number: string): Promise<boolean> {
    for (const provider of PROVIDERS) {
        try {
            const { redirect } = await api<{ redirect: string }>(`orders/${number}/pay`, { body: { provider } });

            window.location.assign(redirect);

            return true;
        } catch (error) {
            if (error instanceof ApiError && error.status === 422 && error.errors.provider) continue;

            notify(error instanceof ApiError ? error.message : 'Не получилось открыть оплату. Попробуйте ещё раз.', true);

            return false;
        }
    }

    notify('Оплата картой сейчас недоступна. Можно отменить заказ и оформить с оплатой при получении.', true);

    return false;
}

/** «18 ноября, 14:05» по времени Ташкента — даты с сервера в UTC. */
export function when(iso: string | null): string {
    if (!iso) return '';

    return new Date(iso).toLocaleString('ru-RU', { day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Tashkent' });
}
