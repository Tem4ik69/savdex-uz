import { usePage } from '@inertiajs/react';
import { useState } from 'react';
import { OrderLine, OrderSteps, StatusPill } from '@/components/market/OrderView';
import { Link } from '@/components/ui/Link';
import { MarketLayout } from '@/layouts/MarketLayout';
import { api, ApiError, useApi } from '@/market/api';
import { sum } from '@/market/format';
import { lang } from '@/market/lang';
import { payByCard, when } from '@/market/orders';
import { notify } from '@/market/store';
import { commonText } from '@/market/text/common';
import { orderText } from '@/market/text/order';
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
    const L = lang(orderText);
    const C = lang(commonText);
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
            notify(failure instanceof ApiError ? failure.message : L.cancelFailed, true);
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
        <MarketLayout title={L.pageTitle(number)} tab="orders">
            <div className="mk-in">
                <nav className="mk-bc" aria-label={L.breadcrumbs}>
                    <Link href={routes.market}>{L.home}</Link>›<Link href={routes.marketOrders}>{L.myOrders}</Link>› {number}
                </nav>
                {children}
            </div>
        </MarketLayout>
    );

    if (!auth.user) {
        return shell(
            <div className="mk-gate" style={{ marginTop: 16 }}>
                <h2>{L.gateTitle}</h2>
                <Link href={routes.loginBack(routes.marketOrder(number))} className="mk-btn">
                    {L.login}
                </Link>
            </div>,
        );
    }

    if (!order) {
        if (loaded.loading) return shell(<div className="mk-skel-block" style={{ height: 320, marginTop: 16 }} aria-busy />);

        return shell(
            <div className="mk-empty" style={{ marginTop: 16 }}>
                <span aria-hidden>📦</span>
                <h2>{loaded.status === 404 ? L.notFound : L.loadFailed}</h2>
                <p>{loaded.status === 404 ? L.notFoundText : loaded.error}</p>
                {loaded.status === 404 ? (
                    <Link href={routes.marketOrders} className="mk-btn">
                        {L.myOrders}
                    </Link>
                ) : (
                    <button type="button" className="mk-btn" onClick={loaded.reload}>
                        {L.retry}
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
                    {L.title(order.number)}
                    <small>{when(order.createdAt)}</small>
                </h1>
                <StatusPill status={order.status} />
            </div>

            <OrderSteps status={order.status} />

            {unpaidCard && (
                <div className="mk-code mk-code--pay">
                    <span>{L.awaitingCard}</span>
                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                        <button type="button" className="mk-btn" disabled={busy} onClick={() => void pay()}>
                            {L.pay} {sum(order.total)} {C.currency}
                        </button>
                        <button
                            type="button"
                            className="mk-btn mk-btn--ghost"
                            onClick={() => {
                                setFresh(null);
                                loaded.reload();
                            }}
                        >
                            {L.refresh}
                        </button>
                    </div>
                </div>
            )}

            {order.status.code === 'ready' && (
                <div className="mk-code">
                    {/* Код выдачи сервер отдаёт только покупателю и только пока заказ
                        ждёт в пункте; нет кода — заказ находят по номеру */}
                    <span>{order.pickupCode ? L.readyCode(order.pickupPoint.name) : L.readyAt(order.pickupPoint.name)}</span>
                    <b aria-label={order.pickupCode ? L.codeLabel : undefined}>{order.pickupCode ?? order.number}</b>
                </div>
            )}

            <div className="mk-order__body">
                <div className="mk-order__items">
                    {order.parts.map((part) => (
                        <div key={part.seller.slug}>
                            <div className="mk-part">
                                <Link href={routes.marketShop(part.seller.slug)}>{part.seller.name}</Link>
                                <span>{sum(part.total)} {C.currency}</span>
                            </div>
                            {part.items.map((item) => (
                                <OrderLine key={item.variantId} item={item} />
                            ))}
                        </div>
                    ))}
                </div>
                <dl className="mk-order__side">
                    <div>
                        <dt>{L.pickupPoint}</dt>
                        <dd>{order.pickupPoint.name}</dd>
                        <dd style={{ fontWeight: 500 }}>{order.pickupPoint.address}</dd>
                        {order.pickupPoint.hours && <dd style={{ fontWeight: 500 }}>{L.hours(order.pickupPoint.hours)}</dd>}
                    </div>
                    <div>
                        <dt>{L.payment}</dt>
                        <dd>
                            {order.paymentMethod === 'card'
                                ? order.paidAt
                                    ? L.paidByCard(when(order.paidAt))
                                    : L.cardOnline
                                : L.cashOnReceipt}
                        </dd>
                    </div>
                    {order.cancelledAt && (
                        <div>
                            <dt>{L.cancelled}</dt>
                            <dd>{when(order.cancelledAt)}</dd>
                        </div>
                    )}
                    {order.issuedAt && (
                        <div>
                            <dt>{L.issued}</dt>
                            <dd>{when(order.issuedAt)}</dd>
                        </div>
                    )}
                </dl>
            </div>

            <div className="mk-order__foot">
                <b>
                    {L.total} {sum(order.total)} {C.currency}
                </b>
                {order.canCancel && !asking && (
                    <button type="button" className="mk-link-danger" onClick={() => setAsking(true)}>
                        {L.cancelOrder}
                    </button>
                )}
            </div>

            {asking && (
                <div className="mk-cancel">
                    <label className="mk-field">
                        {L.reasonLabel}
                        <input id="mk-cancel-reason" value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} />
                    </label>
                    <p className="mk-note">
                        {order.paidAt ? L.refundNote : L.restockNote}
                    </p>
                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                        <button type="button" className="mk-btn" style={{ background: 'var(--danger)' }} disabled={busy} onClick={() => void cancel()}>
                            {L.confirmCancel}
                        </button>
                        <button type="button" className="mk-btn mk-btn--ghost" onClick={() => setAsking(false)}>
                            {L.keepOrder}
                        </button>
                    </div>
                </div>
            )}
        </article>,
    );
}
