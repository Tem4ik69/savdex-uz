import { usePage } from '@inertiajs/react';
import { StatusPill } from '@/components/market/OrderView';
import { Link } from '@/components/ui/Link';
import { MarketLayout } from '@/layouts/MarketLayout';
import { useApi } from '@/market/api';
import { sum } from '@/market/format';
import { lang } from '@/market/lang';
import { when } from '@/market/orders';
import { ordersPageText } from '@/market/text/orders-page';
import type { OrderSummary } from '@/market/types';
import { routes } from '@/routes';
import type { SharedProps } from '@/types';

/** «Мои заказы»: список с сервера (/market/api/orders), новые сверху; заказ целиком — на своей странице. */
export default function MarketOrders() {
    const L = lang(ordersPageText);
    const { auth } = usePage<SharedProps>().props;
    const { data, loading, error, reload } = useApi<{ orders: OrderSummary[] }>(auth.user ? 'orders' : null);

    return (
        <MarketLayout title={L.title} tab="orders">
            <div className="mk-in">
                <nav className="mk-bc" aria-label={L.crumbs}>
                    <Link href={routes.market}>{L.home}</Link>› {L.heading}
                </nav>
                <div className="mk-title">
                    <h1>{L.heading}</h1>
                </div>

                {!auth.user && (
                    <div className="mk-gate">
                        <h2>{L.gateTitle}</h2>
                        <p>{L.gateText}</p>
                        <Link href={routes.loginBack(routes.marketOrders)} className="mk-btn">
                            {L.login}
                        </Link>
                    </div>
                )}

                {loading && <div className="mk-skel-block" style={{ height: 220 }} aria-busy />}

                {error && (
                    <div className="mk-failed">
                        <h2>{L.failed}</h2>
                        <p>{error}</p>
                        <button type="button" className="mk-btn" onClick={reload}>
                            {L.retry}
                        </button>
                    </div>
                )}

                {data && data.orders.length === 0 && (
                    <div className="mk-empty">
                        <span aria-hidden>📦</span>
                        <h2>{L.emptyTitle}</h2>
                        <p>{L.emptyText}</p>
                        <Link href={routes.marketCatalog} className="mk-btn">
                            {L.toCatalog}
                        </Link>
                    </div>
                )}

                {data && data.orders.length > 0 && (
                    <div className="mk-orders">
                        {data.orders.map((order) => (
                            <Link key={order.number} href={routes.marketOrder(order.number)} className="mk-order mk-order--row">
                                <div className="mk-order__head">
                                    <h2>
                                        {L.order(order.number)}
                                        <small>{when(order.createdAt)}</small>
                                    </h2>
                                    <StatusPill status={order.status} />
                                </div>
                                <div className="mk-order__foot">
                                    <span className="mk-note">
                                        {L.items(order.count)} · {order.pickupPoint.name} ·{' '}
                                        {order.paymentMethod === 'card' ? L.byCard : L.onDelivery}
                                    </span>
                                    <b>{sum(order.total)} {L.currency}</b>
                                </div>
                            </Link>
                        ))}
                    </div>
                )}
            </div>
        </MarketLayout>
    );
}
