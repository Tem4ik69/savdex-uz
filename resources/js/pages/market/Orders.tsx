import { useEffect, useState } from 'react';
import { Link } from '@/components/ui/Link';
import { cn } from '@/lib/cn';
import { MarketLayout } from '@/layouts/MarketLayout';
import { sum } from '@/market/format';
import { useLocal } from '@/market/local';
import {
    canCancel,
    nextStatus,
    orders,
    pointOf,
    SAMPLE_ORDERS,
    setOrderStatus,
    STATUS_LABEL,
    stepIndex,
    STEPS,
    type MarketOrder,
} from '@/market/orders';
import { routes } from '@/routes';

const date = (iso: string) => new Date(iso).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' });

/**
 * «Мои заказы»: статус полосой шагов, код выдачи, когда заказ приехал,
 * отмена до отгрузки. Свои заказы (оформленные в этом браузере) идут
 * первыми, под ними — три примера. У своих есть кнопка демо «следующий
 * статус»: без сервера заказ сам по пути не поедет.
 */
export default function MarketOrders() {
    const own = useLocal(orders);
    const [fresh, setFresh] = useState(false);

    useEffect(() => {
        setFresh(new URLSearchParams(window.location.search).has('new'));
    }, []);

    return (
        <MarketLayout title="Мои заказы · SavdEx Market" tab="orders">
            <div className="mk-in">
                <nav className="mk-bc" aria-label="Путь">
                    <Link href={routes.market}>Главная</Link>› Мои заказы
                </nav>
                <div className="mk-title">
                    <h1>Мои заказы</h1>
                </div>

                <div className="mk-orders">
                    {own.map((order, i) => (
                        <Order key={order.id} order={order} own fresh={fresh && i === 0} />
                    ))}
                    {SAMPLE_ORDERS.map((order) => (
                        <Order key={order.id} order={order} />
                    ))}
                </div>
            </div>
        </MarketLayout>
    );
}

function Order({ order, own = false, fresh = false }: { order: MarketOrder; own?: boolean; fresh?: boolean }) {
    const point = pointOf(order.point);
    const step = stepIndex(order.status);
    const cancelled = order.status === 'cancelled';
    const next = nextStatus(order.status);

    return (
        <article className={cn('mk-order', fresh && 'is-new')}>
            <div className="mk-order__head">
                <h2>
                    Заказ {order.id}
                    <small>
                        {fresh ? 'только что' : date(order.created)}
                        {!own && ' · пример'}
                    </small>
                </h2>
                <span className={cn('mk-pill', order.status === 'ready' && 'mk-pill--ok', order.status === 'done' && 'mk-pill--off', cancelled && 'mk-pill--off')}>
                    {STATUS_LABEL[order.status]}
                </span>
            </div>

            {!cancelled && (
                <ol className="mk-steps" aria-label="Путь заказа">
                    {STEPS.map((s, i) => (
                        <li key={s.status} className={cn(i <= step && 'is-done', i === step && 'is-now')} aria-current={i === step ? 'step' : undefined}>
                            {s.label}
                        </li>
                    ))}
                </ol>
            )}

            {order.status === 'ready' && (
                <div className="mk-code">
                    <span>Код выдачи — назовите его сотруднику пункта и заберите заказ.</span>
                    <b>{order.code}</b>
                </div>
            )}

            <div className="mk-order__body">
                <div className="mk-order__items">
                    {order.items.map((item) => (
                        <div key={item.productId} className="mk-mini">
                            <span style={{ background: item.tint }} aria-hidden>
                                {item.emoji}
                            </span>
                            {item.title} × {item.quantity}
                            <b>{sum(item.price * item.quantity)} сум</b>
                        </div>
                    ))}
                </div>
                <dl className="mk-order__side">
                    <div>
                        <dt>Пункт выдачи</dt>
                        <dd>
                            {point.name}, {point.address}
                        </dd>
                        <dd style={{ fontWeight: 500 }}>{point.hours}</dd>
                    </div>
                    <div>
                        <dt>Оплата</dt>
                        <dd>{order.payment === 'card' ? 'Картой онлайн — оплачен' : 'Наличными при получении'}</dd>
                    </div>
                </dl>
            </div>

            <div className="mk-order__foot">
                <b>Итого: {sum(order.total)} сум</b>
                <div>
                    {own && next && (
                        <button type="button" className="mk-demo-btn" onClick={() => setOrderStatus(order.id, next)}>
                            Демо: следующий статус
                        </button>
                    )}
                    {own && canCancel(order.status) && (
                        <button type="button" className="mk-link-danger" onClick={() => setOrderStatus(order.id, 'cancelled')}>
                            Отменить заказ
                        </button>
                    )}
                    {cancelled && order.payment === 'card' && <span className="mk-note">Деньги вернутся на карту через Uzum</span>}
                </div>
            </div>
        </article>
    );
}
