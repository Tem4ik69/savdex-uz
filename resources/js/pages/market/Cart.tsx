import { usePage } from '@inertiajs/react';
import { Link } from '@/components/ui/Link';
import { MarketLayout } from '@/layouts/MarketLayout';
import { PRODUCTS, sellerOf } from '@/market/demo';
import { sum } from '@/market/format';
import { cartCount, setCartQuantity, useCart } from '@/market/store';
import { routes } from '@/routes';
import type { SharedProps } from '@/types';

/**
 * Корзина. Гость может собирать её свободно; оформить — только с
 * входом: кнопка ведёт на вход, а после него — сразу на оформление.
 */
export default function MarketCart() {
    const { auth } = usePage<SharedProps>().props;
    const cart = useCart();
    const lines = PRODUCTS.filter((p) => cart[p.id]).map((product) => ({ product, quantity: cart[product.id] }));
    const total = lines.reduce((s, l) => s + l.product.price * l.quantity, 0);
    const full = lines.reduce((s, l) => s + (l.product.oldPrice ?? l.product.price) * l.quantity, 0);
    const count = cartCount(cart);

    return (
        <MarketLayout title="Корзина · SavdEx Market" tab="cart">
            <div className="mk-in">
                <nav className="mk-bc" aria-label="Путь">
                    <Link href={routes.market}>Главная</Link>› Корзина
                </nav>
                <div className="mk-title">
                    <h1>Корзина</h1>
                    {count > 0 && <span>{count} шт.</span>}
                </div>

                {lines.length === 0 ? (
                    <div className="mk-empty">
                        <span aria-hidden>🛒</span>
                        <h2>В корзине пока пусто</h2>
                        <p>Добавьте товары из каталога — они сохранятся здесь, даже если закрыть страницу.</p>
                        <Link href={routes.marketCatalog} className="mk-btn">
                            Перейти в каталог
                        </Link>
                    </div>
                ) : (
                    <div className="mk-cart">
                        <div className="mk-lines">
                            {lines.map(({ product, quantity }) => (
                                <div key={product.id} className="mk-line">
                                    <div className="mk-line__ph" style={{ background: product.tint }} aria-hidden>
                                        {product.emoji}
                                    </div>
                                    <div>
                                        <h3>
                                            <Link href={routes.marketProduct(product.slug)}>{product.title}</Link>
                                        </h3>
                                        <small>Продавец: {sellerOf(product).name}</small>
                                        <div className="mk-line__ctl">
                                            <div className="mk-qty">
                                                <button
                                                    type="button"
                                                    aria-label="Меньше"
                                                    disabled={quantity <= 1}
                                                    onClick={() => setCartQuantity(product.id, quantity - 1)}
                                                >
                                                    −
                                                </button>
                                                <output aria-label="Количество">{quantity}</output>
                                                <button
                                                    type="button"
                                                    aria-label="Больше"
                                                    disabled={quantity >= product.stock}
                                                    onClick={() => setCartQuantity(product.id, quantity + 1)}
                                                >
                                                    +
                                                </button>
                                            </div>
                                            <button type="button" className="mk-line__del" onClick={() => setCartQuantity(product.id, 0)}>
                                                Удалить
                                            </button>
                                        </div>
                                    </div>
                                    <div className="mk-line__sum">
                                        {sum(product.price * quantity)} сум
                                        {product.oldPrice && <s>{sum(product.oldPrice * quantity)} сум</s>}
                                    </div>
                                </div>
                            ))}
                        </div>

                        <aside className="mk-sum" aria-label="Итог">
                            <h2>Ваш заказ</h2>
                            <dl>
                                <div>
                                    <dt>Товары, {count} шт.</dt>
                                    <dd>{sum(full)} сум</dd>
                                </div>
                                {full > total && (
                                    <div className="is-save">
                                        <dt>Скидка</dt>
                                        <dd>−{sum(full - total)} сум</dd>
                                    </div>
                                )}
                                <div>
                                    <dt>Выдача в пункте BTS</dt>
                                    <dd>0 сум</dd>
                                </div>
                                <div className="is-total">
                                    <dt>Итого</dt>
                                    <dd>{sum(total)} сум</dd>
                                </div>
                            </dl>
                            <Link href={auth.user ? routes.marketCheckout : routes.loginBack(routes.marketCheckout)} className="mk-btn mk-btn--block">
                                {auth.user ? 'Перейти к оформлению' : 'Войти и оформить'}
                            </Link>
                            {!auth.user && <p className="mk-note">Покупать можно только с входом. После входа сразу откроется оформление.</p>}
                        </aside>
                    </div>
                )}
            </div>
        </MarketLayout>
    );
}
