import { usePage } from '@inertiajs/react';
import { StatusPill } from '@/components/market/OrderView';
import { Link } from '@/components/ui/Link';
import { MarketLayout } from '@/layouts/MarketLayout';
import { useApi } from '@/market/api';
import { plural, sum } from '@/market/format';
import { when } from '@/market/orders';
import type { OrderSummary } from '@/market/types';
import { routes } from '@/routes';
import type { SharedProps } from '@/types';

/** «Мои заказы»: список с сервера (/market/api/orders), новые сверху; заказ целиком — на своей странице. */
export default function MarketOrders() {
    const { auth } = usePage<SharedProps>().props;
    const { data, loading, error, reload } = useApi<{ orders: OrderSummary[] }>(auth.user ? 'orders' : null);

    return (
        <MarketLayout title="Мои заказы · SavdEx Market" tab="orders">
            <div className="mk-in">
                <nav className="mk-bc" aria-label="Путь">
                    <Link href={routes.market}>Главная</Link>› Мои заказы
                </nav>
                <div className="mk-title">
                    <h1>Мои заказы</h1>
                </div>

                {!auth.user && (
                    <div className="mk-gate">
                        <h2>Войдите, чтобы увидеть заказы</h2>
                        <p>Заказы хранятся в вашем аккаунте.</p>
                        <Link href={routes.loginBack(routes.marketOrders)} className="mk-btn">
                            Войти
                        </Link>
                    </div>
                )}

                {loading && <div className="mk-skel-block" style={{ height: 220 }} aria-busy />}

                {error && (
                    <div className="mk-failed">
                        <h2>Заказы не загрузились</h2>
                        <p>{error}</p>
                        <button type="button" className="mk-btn" onClick={reload}>
                            Повторить
                        </button>
                    </div>
                )}

                {data && data.orders.length === 0 && (
                    <div className="mk-empty">
                        <span aria-hidden>📦</span>
                        <h2>Заказов пока нет</h2>
                        <p>Оформленные заказы появятся здесь — с их статусом и пунктом выдачи.</p>
                        <Link href={routes.marketCatalog} className="mk-btn">
                            Перейти в каталог
                        </Link>
                    </div>
                )}

                {data && data.orders.length > 0 && (
                    <div className="mk-orders">
                        {data.orders.map((order) => (
                            <Link key={order.number} href={routes.marketOrder(order.number)} className="mk-order mk-order--row">
                                <div className="mk-order__head">
                                    <h2>
                                        Заказ {order.number}
                                        <small>{when(order.createdAt)}</small>
                                    </h2>
                                    <StatusPill status={order.status} />
                                </div>
                                <div className="mk-order__foot">
                                    <span className="mk-note">
                                        {order.count} {plural(order.count, ['товар', 'товара', 'товаров'])} · {order.pickupPoint.name} ·{' '}
                                        {order.paymentMethod === 'card' ? 'картой' : 'при получении'}
                                    </span>
                                    <b>{sum(order.total)} сум</b>
                                </div>
                            </Link>
                        ))}
                    </div>
                )}
            </div>
        </MarketLayout>
    );
}
