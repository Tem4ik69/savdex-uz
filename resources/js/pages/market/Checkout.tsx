import { router, usePage } from '@inertiajs/react';
import { Banknote, CreditCard } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { Link } from '@/components/ui/Link';
import { MarketLayout } from '@/layouts/MarketLayout';
import { PRODUCTS } from '@/market/demo';
import { sum } from '@/market/format';
import { itemOf, placeOrder, pointOf, POINTS } from '@/market/orders';
import { clearCart, useCart } from '@/market/store';
import { routes } from '@/routes';
import type { SharedProps } from '@/types';

/**
 * Врезка OpenStreetMap с отметкой пункта — как у карты офиса
 * (components/OfficeMap): без ключа API и стороннего скрипта.
 */
function mapSrc(lat: number, lng: number): string {
    const dx = 0.012;
    const dy = 0.007;

    return `https://www.openstreetmap.org/export/embed.html?bbox=${lng - dx}%2C${lat - dy}%2C${lng + dx}%2C${lat + dy}&layer=mapnik&marker=${lat}%2C${lng}`;
}

/**
 * Оформление заказа: получатель, пункт выдачи (список и карта), способ
 * оплаты. Купить можно только с входом; гостю экран показывается лишь
 * по кнопке демо-режима — чтобы оформление можно было посмотреть, пока
 * нет сервера. Заказ сохраняется в браузере (market/orders.ts).
 */
export default function MarketCheckout() {
    const { auth } = usePage<SharedProps>().props;
    const cart = useCart();
    const [guestDemo, setGuestDemo] = useState(false);
    const [name, setName] = useState(auth.user?.name ?? '');
    const [phone, setPhone] = useState('');
    const [point, setPoint] = useState(POINTS[0].id);
    // Карта — сторонний сервер (OSM, за рубежом): грузим только по просьбе
    // покупателя, без Referer и в песочнице — выбор пункта сам не уходит
    const [showMap, setShowMap] = useState(false);
    const [payment, setPayment] = useState<'card' | 'cash'>('card');
    const [tried, setTried] = useState(false);

    const lines = PRODUCTS.filter((p) => cart[p.id] && p.stock > 0).map((product) => ({ product, quantity: cart[product.id] }));
    const total = lines.reduce((s, l) => s + l.product.price * l.quantity, 0);
    const chosen = pointOf(point);
    const phoneOk = phone.replace(/\D/g, '').length >= 9;
    const nameOk = name.trim().length > 1;

    function submit(event: FormEvent) {
        event.preventDefault();
        setTried(true);

        if (!phoneOk || !nameOk) return;

        placeOrder(
            lines.map((l) => itemOf(l.product, l.quantity)),
            point,
            payment,
        );
        clearCart();
        router.get(`${routes.marketOrders}?new=1`);
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

    if (!auth.user && !guestDemo) {
        return shell(
            <div className="mk-gate">
                <h2>Войдите, чтобы оформить заказ</h2>
                <p>Покупать на SavdEx Market можно только с входом — так мы сообщим, когда заказ приедет в пункт выдачи. Корзина сохранится.</p>
                <Link href={routes.loginBack(routes.marketCheckout)} className="mk-btn">
                    Войти или зарегистрироваться
                </Link>
                <button type="button" className="mk-demo-btn" onClick={() => setGuestDemo(true)}>
                    Демо: посмотреть оформление без входа
                </button>
            </div>,
        );
    }

    return shell(
        <form className="mk-checkout" onSubmit={submit} noValidate>
            <div>
                <section className="mk-panel">
                    <h2 className="mk-step-title">
                        <i>1</i> Получатель
                    </h2>
                    <div className="mk-form mk-form--2">
                        <label className="mk-field">
                            Имя
                            <input id="mk-name" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
                            {tried && !nameOk && <small className="is-error">Укажите имя — его назовут в пункте выдачи</small>}
                        </label>
                        <label className="mk-field">
                            Телефон
                            <input
                                id="mk-phone"
                                type="tel"
                                inputMode="tel"
                                placeholder="+998 90 123 45 67"
                                value={phone}
                                onChange={(e) => setPhone(e.target.value)}
                                autoComplete="tel"
                            />
                            {tried && !phoneOk ? (
                                <small className="is-error">Укажите телефон — на него придёт код выдачи</small>
                            ) : (
                                <small>На него придёт сообщение с кодом выдачи</small>
                            )}
                        </label>
                    </div>
                </section>

                <section className="mk-panel">
                    <h2 className="mk-step-title">
                        <i>2</i> Пункт выдачи
                    </h2>
                    <div className="mk-pickup">
                        <div className="mk-points" role="radiogroup" aria-label="Пункты выдачи BTS в Ташкенте">
                            {POINTS.map((p) => (
                                <label key={p.id} className="mk-choice">
                                    <input type="radio" name="point" checked={point === p.id} onChange={() => setPoint(p.id)} />
                                    <span>
                                        <b>{p.name}</b>
                                        <small>
                                            {p.district}, {p.address}
                                        </small>
                                        <small>{p.hours}</small>
                                    </span>
                                </label>
                            ))}
                        </div>
                        <div className="mk-map">
                            {showMap ? (
                                <iframe
                                    key={chosen.id}
                                    title={`Карта: ${chosen.name}`}
                                    src={mapSrc(chosen.lat, chosen.lng)}
                                    loading="lazy"
                                    referrerPolicy="no-referrer"
                                    sandbox="allow-scripts allow-same-origin"
                                />
                            ) : (
                                <button type="button" className="mk-btn mk-btn--ghost" onClick={() => setShowMap(true)}>
                                    Показать на карте
                                </button>
                            )}
                            <p>
                                {chosen.name} · {chosen.address}. Доставки до двери пока нет — заказ забирают в пункте.
                            </p>
                        </div>
                    </div>
                </section>

                <section className="mk-panel">
                    <h2 className="mk-step-title">
                        <i>3</i> Способ оплаты
                    </h2>
                    <div className="mk-pay" role="radiogroup" aria-label="Способ оплаты">
                        <label className="mk-choice">
                            <input type="radio" name="payment" checked={payment === 'card'} onChange={() => setPayment('card')} />
                            <span>
                                <b>
                                    <CreditCard size={16} aria-hidden style={{ display: 'inline', verticalAlign: '-3px' }} /> Картой онлайн
                                </b>
                                <small>Uzcard, Humo, Visa, Mastercard — через Uzum</small>
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
                </section>
            </div>

            <aside className="mk-sum" aria-label="Ваш заказ">
                <h2>Ваш заказ</h2>
                {lines.map(({ product, quantity }) => (
                    <div key={product.id} className="mk-mini">
                        <span style={{ background: product.tint }} aria-hidden>
                            {product.emoji}
                        </span>
                        {product.title} × {quantity}
                        <b>{sum(product.price * quantity)}</b>
                    </div>
                ))}
                <dl>
                    <div>
                        <dt>Выдача в {chosen.name}</dt>
                        <dd>0 сум</dd>
                    </div>
                    <div className="is-total">
                        <dt>Итого</dt>
                        <dd>{sum(total)} сум</dd>
                    </div>
                </dl>
                <button type="submit" className="mk-btn mk-btn--block">
                    {payment === 'card' ? 'Оплатить и оформить' : 'Оформить заказ'}
                </button>
                <p className="mk-note">
                    Демо: оплата не списывается, заказ сохраняется только в этом браузере. Отменить заказ можно, пока он не уехал со
                    склада.
                </p>
            </aside>
        </form>,
    );
}
