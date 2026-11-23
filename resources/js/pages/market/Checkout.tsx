import { router, usePage } from '@inertiajs/react';
import { Banknote, CreditCard } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { MarketPhoto } from '@/components/market/MarketPhoto';
import { Link } from '@/components/ui/Link';
import { MarketLayout } from '@/layouts/MarketLayout';
import { localize } from '@/lib/locale';
import { api, ApiError, useApi } from '@/market/api';
import { sum } from '@/market/format';
import { payByCard } from '@/market/orders';
import { cartLines, notify, putCart, reloadCart, useCart } from '@/market/store';
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
            setErrors({ pickupPoint: ['Выберите пункт выдачи'] });

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
        <MarketLayout title="Оформление заказа · SavdEx Market" tab="cart">
            <div className="mk-in">
                <nav className="mk-bc" aria-label="Путь">
                    <Link href={routes.market}>Главная</Link>›<Link href={routes.marketCart}>Корзина</Link>› Оформление
                </nav>
                <div className="mk-title">
                    <h1>Оформление заказа</h1>
                </div>
                {children}
            </div>
        </MarketLayout>
    );

    if (!auth.user) {
        return shell(
            <div className="mk-gate">
                <h2>Войдите, чтобы оформить заказ</h2>
                <p>Покупать на SavdEx Market можно только с входом — так мы сообщим, когда заказ приедет в пункт выдачи.</p>
                <Link href={routes.loginBack(routes.marketCheckout)} className="mk-btn">
                    Войти или зарегистрироваться
                </Link>
            </div>,
        );
    }

    if (cart === null) return shell(<div className="mk-skel-block" style={{ height: 320 }} aria-busy />);

    if (lines.length === 0) {
        return shell(
            <div className="mk-empty">
                <span aria-hidden>🛒</span>
                <h2>Оформлять пока нечего</h2>
                <p>В корзине нет товаров, которые есть в наличии.</p>
                <Link href={routes.marketCatalog} className="mk-btn">
                    Перейти в каталог
                </Link>
            </div>,
        );
    }

    return shell(
        <form className="mk-checkout" onSubmit={(event) => void submit(event)} noValidate>
            <div>
                <section className="mk-panel">
                    <h2 className="mk-step-title">
                        <i>1</i> Пункт выдачи
                    </h2>
                    {points.loading && <div className="mk-skel-block" style={{ height: 180 }} aria-busy />}
                    {points.error && (
                        <div className="mk-failed">
                            <p>Пункты выдачи не загрузились. {points.error}</p>
                            <button type="button" className="mk-btn" onClick={points.reload}>
                                Повторить
                            </button>
                        </div>
                    )}
                    {points.data && list.length === 0 && <p className="mk-note">Пунктов выдачи пока нет — оформить заказ не получится. Загляните позже.</p>}
                    {list.length > 0 && (
                        <div className="mk-points mk-points--wide" role="radiogroup" aria-label="Пункты выдачи BTS">
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
                    <p className="mk-note">Доставки до двери пока нет — заказ забирают в пункте. Часы работы и карта пунктов появятся позже.</p>
                </section>

                <section className="mk-panel">
                    <h2 className="mk-step-title">
                        <i>2</i> Способ оплаты
                    </h2>
                    <div className="mk-pay" role="radiogroup" aria-label="Способ оплаты">
                        <label className="mk-choice">
                            <input type="radio" name="payment" checked={payment === 'card'} onChange={() => setPayment('card')} />
                            <span>
                                <b>
                                    <CreditCard size={16} aria-hidden style={{ display: 'inline', verticalAlign: '-3px' }} /> Картой онлайн
                                </b>
                                <small>Uzcard, Humo, Visa, Mastercard — на странице платёжной системы</small>
                            </span>
                        </label>
                        <label className="mk-choice">
                            <input type="radio" name="payment" checked={payment === 'cash'} onChange={() => setPayment('cash')} />
                            <span>
                                <b>
                                    <Banknote size={16} aria-hidden style={{ display: 'inline', verticalAlign: '-3px' }} /> При получении
                                </b>
                                <small>Наличными в пункте выдачи</small>
                            </span>
                        </label>
                    </div>
                    {errors.paymentMethod?.[0] && <p className="mk-line__warn">{errors.paymentMethod[0]}</p>}
                </section>
            </div>

            <aside className="mk-sum" aria-label="Ваш заказ">
                <h2>Ваш заказ</h2>
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
                        <dt>{chosen ? `Выдача: ${chosen.name}` : 'Выдача в пункте BTS'}</dt>
                        <dd>0 сум</dd>
                    </div>
                    <div className="is-total">
                        <dt>Итого</dt>
                        <dd>{sum(total)} сум</dd>
                    </div>
                </dl>
                <button type="submit" className="mk-btn mk-btn--block" disabled={sending || list.length === 0}>
                    {payment === 'card' ? 'Оформить и оплатить' : 'Оформить заказ'}
                </button>
                <p className="mk-note">
                    Получатель — владелец аккаунта: имя и телефон берём из него. Статус заказа — в «Моих заказах».
                    {left > 0 && ' Товары без наличия останутся в корзине.'}
                </p>
            </aside>
        </form>,
    );
}
