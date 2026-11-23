import { router, usePage } from '@inertiajs/react';
import { Banknote, CreditCard } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { MarketPhoto } from '@/components/market/MarketPhoto';
import { Link } from '@/components/ui/Link';
import { MarketLayout } from '@/layouts/MarketLayout';
import { localize } from '@/lib/locale';
import { api, ApiError, useApi } from '@/market/api';
import { sum } from '@/market/format';
import { lang } from '@/market/lang';
import { payByCard } from '@/market/orders';
import { cartLines, notify, putCart, reloadCart, useCart } from '@/market/store';
import { checkoutText } from '@/market/text/checkout';
import { commonText } from '@/market/text/common';
import type { CartSummary, OrderDetail, PickupPoint } from '@/market/types';
import { routes } from '@/routes';
import type { SharedProps } from '@/types';

/**
 * Оформление заказа: пункт выдачи и способ оплаты (/market/api/checkout).
 *
 * Получатель — владелец аккаунта: отдельно имя и телефон не спрашиваем. Сервер сверяет сумму, которую видел
 * покупатель (expectedTotal): цена изменилась или товар кончился — 409 и
 * свежая корзина, покупатель видит новую сумму и подтверждает ещё раз.
 * Картой — после заказа сразу страница оплаты провайдера; при получении —
 * страница заказа.
 */
export default function MarketCheckout() {
    const L = lang(checkoutText);
    const C = lang(commonText);
    const { auth } = usePage<SharedProps>().props;
    const cart = useCart();
    const points = useApi<{ pickupPoints: PickupPoint[] }>(auth.user ? 'pickup-points' : null);
    const [point, setPoint] = useState<string | null>(null);
    const [payment, setPayment] = useState<'card' | 'cash'>('card');
    const [errors, setErrors] = useState<Record<string, string[]>>({});
    const [sending, setSending] = useState(false);

    const list = points.data?.pickupPoints ?? [];
    const chosen = list.find((p) => p.code === point) ?? null;
    const lines = cartLines(cart).filter((line) => line.buyable && line.available > 0);
    const total = cart?.total ?? 0;
    const left = cartLines(cart).length - lines.length;

    async function submit(event: FormEvent) {
        event.preventDefault();

        if (!chosen) {
            setErrors({ pickupPoint: [L.choosePoint] });

            return;
        }

        setSending(true);
        setErrors({});

        try {
            const { order } = await api<{ message: string; order: OrderDetail }>('checkout', {
                body: { pickupPoint: chosen.code, paymentMethod: payment, expectedTotal: total },
            });

            await reloadCart();

            if (payment === 'card' && (await payByCard(order.number))) return;

            router.visit(localize(routes.marketOrder(order.number)));
        } catch (failure) {
            if (failure instanceof ApiError) {
                setErrors(failure.errors);
                notify(failure.message, true);

                // Цена или остаток изменились: сервер прислал свежую корзину
                if (failure.status === 409 && failure.data.cart) putCart(failure.data.cart as CartSummary);
            }
        } finally {
            setSending(false);
        }
    }

    const shell = (children: React.ReactNode) => (
        <MarketLayout title={L.pageTitle} tab="cart">
            <div className="mk-in">
                <nav className="mk-bc" aria-label={L.breadcrumbs}>
                    <Link href={routes.market}>{L.home}</Link>›<Link href={routes.marketCart}>{L.cart}</Link>› {L.crumb}
                </nav>
                <div className="mk-title">
                    <h1>{L.title}</h1>
                </div>
                {children}
            </div>
        </MarketLayout>
    );

    if (!auth.user) {
        return shell(
            <div className="mk-gate">
                <h2>{L.gateTitle}</h2>
                <p>{L.gateText}</p>
                <Link href={routes.loginBack(routes.marketCheckout)} className="mk-btn">
                    {L.loginOrRegister}
                </Link>
            </div>,
        );
    }

    if (cart === null) return shell(<div className="mk-skel-block" style={{ height: 320 }} aria-busy />);

    if (lines.length === 0) {
        return shell(
            <div className="mk-empty">
                <span aria-hidden>🛒</span>
                <h2>{L.emptyTitle}</h2>
                <p>{L.emptyText}</p>
                <Link href={routes.marketCatalog} className="mk-btn">
                    {L.toCatalog}
                </Link>
            </div>,
        );
    }

    return shell(
        <form className="mk-checkout" onSubmit={(event) => void submit(event)} noValidate>
            <div>
                <section className="mk-panel">
                    <h2 className="mk-step-title">
                        <i>1</i> {L.pointTitle}
                    </h2>
                    {points.loading && <div className="mk-skel-block" style={{ height: 180 }} aria-busy />}
                    {points.error && (
                        <div className="mk-failed">
                            <p>
                                {L.pointsFailed} {points.error}
                            </p>
                            <button type="button" className="mk-btn" onClick={points.reload}>
                                {L.retry}
                            </button>
                        </div>
                    )}
                    {points.data && list.length === 0 && <p className="mk-note">{L.noPoints}</p>}
                    {list.length > 0 && (
                        <div className="mk-points mk-points--wide" role="radiogroup" aria-label={L.pointsLabel}>
                            {list.map((p) => (
                                <label key={p.code} className="mk-choice">
                                    <input type="radio" name="point" checked={point === p.code} onChange={() => setPoint(p.code)} />
                                    <span>
                                        <b>{p.name}</b>
                                        <small>
                                            {p.city}, {p.address}
                                        </small>
                                    </span>
                                </label>
                            ))}
                        </div>
                    )}
                    {errors.pickupPoint?.[0] && <p className="mk-line__warn">{errors.pickupPoint[0]}</p>}
                    <p className="mk-note">{L.noDelivery}</p>
                </section>

                <section className="mk-panel">
                    <h2 className="mk-step-title">
                        <i>2</i> {L.paymentTitle}
                    </h2>
                    <div className="mk-pay" role="radiogroup" aria-label={L.paymentTitle}>
                        <label className="mk-choice">
                            <input type="radio" name="payment" checked={payment === 'card'} onChange={() => setPayment('card')} />
                            <span>
                                <b>
                                    <CreditCard size={16} aria-hidden style={{ display: 'inline', verticalAlign: '-3px' }} /> {L.cardOnline}
                                </b>
                                <small>{L.cardHint}</small>
                            </span>
                        </label>
                        <label className="mk-choice">
                            <input type="radio" name="payment" checked={payment === 'cash'} onChange={() => setPayment('cash')} />
                            <span>
                                <b>
                                    <Banknote size={16} aria-hidden style={{ display: 'inline', verticalAlign: '-3px' }} /> {L.onReceipt}
                                </b>
                                <small>{L.cashHint}</small>
                            </span>
                        </label>
                    </div>
                    {errors.paymentMethod?.[0] && <p className="mk-line__warn">{errors.paymentMethod[0]}</p>}
                </section>
            </div>

            <aside className="mk-sum" aria-label={L.yourOrder}>
                <h2>{L.yourOrder}</h2>
                {lines.map((line) => (
                    <div key={line.variantId} className="mk-mini">
                        <span>
                            <MarketPhoto image={line.image} id={line.productId} />
                        </span>
                        {line.title} × {Math.min(line.quantity, line.available)}
                        <b>{sum(line.total)}</b>
                    </div>
                ))}
                <dl>
                    <div>
                        <dt>{chosen ? L.pickupAt(chosen.name) : L.pickupBts}</dt>
                        <dd>0 {C.currency}</dd>
                    </div>
                    <div className="is-total">
                        <dt>{L.total}</dt>
                        <dd>{sum(total)} {C.currency}</dd>
                    </div>
                </dl>
                <button type="submit" className="mk-btn mk-btn--block" disabled={sending || list.length === 0}>
                    {payment === 'card' ? L.orderAndPay : L.placeOrder}
                </button>
                <p className="mk-note">
                    {L.recipientNote}
                    {left > 0 && L.leftNote}
                </p>
            </aside>
        </form>,
    );
}
