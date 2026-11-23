import { usePage } from '@inertiajs/react';
import { useState } from 'react';
import { OrderLine, OrderSteps, StatusPill } from '@/components/market/OrderView';
import { Link } from '@/components/ui/Link';
import { MarketLayout } from '@/layouts/MarketLayout';
import { api, ApiError, useApi } from '@/market/api';
import { sum } from '@/market/format';
import { payByCard, when } from '@/market/orders';
import { notify } from '@/market/store';
import type { OrderDetail } from '@/market/types';
import { routes } from '@/routes';
import type { SharedProps } from '@/types';

/**
 * Один заказ (/market/api/orders/<номер>): статус по шагам, части по
 * продавцам, пункт выдачи, оплата и отмена. Сюда же возвращает
 * покупателя страница оплаты провайдера — статус «оплачен» сервер ставит
 * по уведомлению провайдера, поэтому неоплаченный заказ здесь можно
 * обновить.
 */
export default function MarketOrder({ number }: { number: string }) {
    const { auth } = usePage<SharedProps>().props;
    const loaded = useApi<{ order: OrderDetail }>(auth.user ? `orders/${number}` : null);
    const [fresh, setFresh] = useState<OrderDetail | null>(null);
    const [busy, setBusy] = useState(false);
    const [asking, setAsking] = useState(false);
    const [reason, setReason] = useState('');
    const order = fresh ?? loaded.data?.order ?? null;

    async function cancel() {
        setBusy(true);

        try {
            const data = await api<{ message: string; order: OrderDetail }>(`orders/${number}/cancel`, { body: { reason: reason.trim() } });

            setFresh(data.order);
            setAsking(false);
            notify(data.message);
        } catch (failure) {
            notify(failure instanceof ApiError ? failure.message : 'Не получилось отменить заказ.', true);
        } finally {
            setBusy(false);
        }
    }

    async function pay() {
        setBusy(true);
        await payByCard(number);
        setBusy(false);
    }

    const shell = (children: React.ReactNode) => (
        <MarketLayout title={`Заказ ${number} · SavdEx Market`} tab="orders">
            <div className="mk-in">
                <nav className="mk-bc" aria-label="Путь">
                    <Link href={routes.market}>Главная</Link>›<Link href={routes.marketOrders}>Мои заказы</Link>› {number}
                </nav>
                {children}
            </div>
        </MarketLayout>
    );

    if (!auth.user) {
        return shell(
            <div className="mk-gate" style={{ marginTop: 16 }}>
                <h2>Войдите, чтобы увидеть заказ</h2>
                <Link href={routes.loginBack(routes.marketOrder(number))} className="mk-btn">
                    Войти
                </Link>
            </div>,
        );
    }

    if (!order) {
        if (loaded.loading) return shell(<div className="mk-skel-block" style={{ height: 320, marginTop: 16 }} aria-busy />);

        return shell(
            <div className="mk-empty" style={{ marginTop: 16 }}>
                <span aria-hidden>📦</span>
                <h2>{loaded.status === 404 ? 'Такого заказа нет' : 'Заказ не загрузился'}</h2>
                <p>{loaded.status === 404 ? 'Проверьте номер — или найдите заказ в списке.' : loaded.error}</p>
                {loaded.status === 404 ? (
                    <Link href={routes.marketOrders} className="mk-btn">
                        Мои заказы
                    </Link>
                ) : (
                    <button type="button" className="mk-btn" onClick={loaded.reload}>
                        Повторить
                    </button>
                )}
            </div>,
        );
    }

    const unpaidCard = order.status.code === 'created' && order.paymentMethod === 'card';

    return shell(
        <article className="mk-order" style={{ marginTop: 12 }}>
            <div className="mk-order__head">
                <h1 className="mk-order__title">
                    Заказ {order.number}
                    <small>{when(order.createdAt)}</small>
                </h1>
                <StatusPill status={order.status} />
            </div>

            <OrderSteps status={order.status} />

            {unpaidCard && (
                <div className="mk-code mk-code--pay">
                    <span>Заказ ждёт оплаты картой. Если вы уже оплатили — статус обновится через минуту.</span>
                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                        <button type="button" className="mk-btn" disabled={busy} onClick={() => void pay()}>
                            Оплатить {sum(order.total)} сум
                        </button>
                        <button
                            type="button"
                            className="mk-btn mk-btn--ghost"
                            onClick={() => {
                                setFresh(null);
                                loaded.reload();
                            }}
                        >
                            Обновить статус
                        </button>
                    </div>
                </div>
            )}

            {order.status.code === 'ready' && (
                <div className="mk-code">
                    <span>Заказ ждёт вас в пункте выдачи: {order.pickupPoint.name}. Номер заказа:</span>
                    <b>{order.number}</b>
                </div>
            )}

            <div className="mk-order__body">
                <div className="mk-order__items">
                    {order.parts.map((part) => (
                        <div key={part.seller.slug}>
                            <div className="mk-part">
                                <Link href={routes.marketShop(part.seller.slug)}>{part.seller.name}</Link>
                                <span>{sum(part.total)} сум</span>
                            </div>
                            {part.items.map((item) => (
                                <OrderLine key={item.variantId} item={item} />
                            ))}
                        </div>
                    ))}
                </div>
                <dl className="mk-order__side">
                    <div>
                        <dt>Пункт выдачи</dt>
                        <dd>{order.pickupPoint.name}</dd>
                        <dd style={{ fontWeight: 500 }}>{order.pickupPoint.address}</dd>
                    </div>
                    <div>
                        <dt>Оплата</dt>
                        <dd>
                            {order.paymentMethod === 'card'
                                ? order.paidAt
                                    ? `Картой — оплачен ${when(order.paidAt)}`
                                    : 'Картой онлайн'
                                : 'Наличными при получении'}
                        </dd>
                    </div>
                    {order.cancelledAt && (
                        <div>
                            <dt>Отменён</dt>
                            <dd>{when(order.cancelledAt)}</dd>
                        </div>
                    )}
                    {order.issuedAt && (
                        <div>
                            <dt>Выдан</dt>
                            <dd>{when(order.issuedAt)}</dd>
                        </div>
                    )}
                </dl>
            </div>

            <div className="mk-order__foot">
                <b>Итого: {sum(order.total)} сум</b>
                {order.canCancel && !asking && (
                    <button type="button" className="mk-link-danger" onClick={() => setAsking(true)}>
                        Отменить заказ
                    </button>
                )}
            </div>

            {asking && (
                <div className="mk-cancel">
                    <label className="mk-field">
                        Почему отменяете? (необязательно)
                        <input id="mk-cancel-reason" value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} />
                    </label>
                    <p className="mk-note">
                        {order.paidAt ? 'Деньги вернутся на карту, с которой платили.' : 'Товары вернутся в продажу.'}
                    </p>
                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                        <button type="button" className="mk-btn" style={{ background: 'var(--danger)' }} disabled={busy} onClick={() => void cancel()}>
                            Да, отменить
                        </button>
                        <button type="button" className="mk-btn mk-btn--ghost" onClick={() => setAsking(false)}>
                            Не отменять
                        </button>
                    </div>
                </div>
            )}
        </article>,
    );
}
