import { MarketPhoto } from '@/components/market/MarketPhoto';
import { Link } from '@/components/ui/Link';
import { cn } from '@/lib/cn';
import { sum } from '@/market/format';
import { STEPS, stepIndex, statusTone } from '@/market/orders';
import type { OrderItem, OrderStatusView } from '@/market/types';
import { routes } from '@/routes';

/** Метка статуса заказа — текст с сервера, цвет по коду. */
export function StatusPill({ status }: { status: OrderStatusView }) {
    return <span className={cn('mk-pill', statusTone(status.code))}>{status.text}</span>;
}

/** Полоса шагов заказа; у отменённого и возвращённого её нет. */
export function OrderSteps({ status }: { status: OrderStatusView }) {
    const step = stepIndex(status.code);

    if (step < 0) return null;

    return (
        <ol className="mk-steps" aria-label="Путь заказа">
            {STEPS.map((s, i) => (
                <li key={s.label} className={cn(i <= step && 'is-done', i === step && 'is-now')} aria-current={i === step ? 'step' : undefined}>
                    {s.label}
                </li>
            ))}
        </ol>
    );
}

/** Позиция заказа: фото, название с вариантом, количество, сумма. */
export function OrderLine({ item }: { item: OrderItem }) {
    const variant = Object.entries(item.options)
        .map(([name, value]) => `${name}: ${value}`)
        .join(' · ');

    return (
        <div className="mk-mini">
            <span>
                <MarketPhoto image={item.image} id={item.variantId} />
            </span>
            <span className="mk-mini__text">
                <Link href={routes.marketProduct(item.slug)}>{item.title}</Link>
                {variant && <small>{variant}</small>}
            </span>
            × {item.quantity}
            {item.total !== undefined && <b>{sum(item.total)} сум</b>}
        </div>
    );
}
