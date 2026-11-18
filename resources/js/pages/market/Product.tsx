import { BadgeCheck, Check, CreditCard, Heart, MapPin, RotateCcw, ShoppingCart } from 'lucide-react';
import { useState } from 'react';
import { MarketCard } from '@/components/market/MarketCard';
import { Link } from '@/components/ui/Link';
import { MarketLayout } from '@/layouts/MarketLayout';
import { categoryOf, discount, PRODUCTS, sellerOf } from '@/market/demo';
import { rating, sum } from '@/market/format';
import { addToCart, toggleFavorite, useCart, useFavorites } from '@/market/store';
import { routes } from '@/routes';

/**
 * Карточка товара: фото, варианты, цена и скидка, «В корзину» и «В
 * избранное», продавец, как получить, характеристики, место под отзывы
 * (сами отзывы — второй этап по ТЗ).
 */
export default function MarketProductPage({ slug }: { slug: string }) {
    const product = PRODUCTS.find((p) => p.slug === slug);
    const cart = useCart();
    const favorites = useFavorites();
    const [quantity, setQuantity] = useState(1);
    const [chosen, setChosen] = useState<Record<string, string>>({});
    const [shot, setShot] = useState(0);

    if (!product) {
        return (
            <MarketLayout title="Товар не найден · SavdEx Market" tab="catalog">
                <div className="mk-in" style={{ paddingTop: 24 }}>
                    <div className="mk-empty">
                        <span aria-hidden>📦</span>
                        <h2>Такого товара нет</h2>
                        <p>Возможно, продавец снял его с продажи или ссылка устарела.</p>
                        <Link href={routes.marketCatalog} className="mk-btn">
                            Перейти в каталог
                        </Link>
                    </div>
                </div>
            </MarketLayout>
        );
    }

    const seller = sellerOf(product);
    const category = categoryOf(product.category);
    const off = discount(product);
    const out = product.stock === 0;
    const inCart = cart[product.id] ?? 0;
    const liked = Boolean(favorites[product.id]);
    const similar = PRODUCTS.filter((p) => p.id !== product.id && p.category === product.category)
        .concat(PRODUCTS.filter((p) => p.id !== product.id && p.category !== product.category))
        .slice(0, 5);
    // Фотографий пока нет: три «кадра» — один значок на разных подложках
    const shots = [product.tint, '#f1f5f9', '#fff7ed'];

    return (
        <MarketLayout title={`${product.title} · SavdEx Market`} tab="catalog">
            <div className="mk-in">
                <nav className="mk-bc" aria-label="Путь">
                    <Link href={routes.market}>Главная</Link>›
                    {category && (
                        <>
                            <Link href={`${routes.marketCatalog}?category=${category.slug}`}>{category.name}</Link>›
                        </>
                    )}
                    {product.title}
                </nav>

                <div className="mk-product">
                    <div className="mk-gallery">
                        <div className="mk-thumbs">
                            {shots.map((tint, i) => (
                                <button
                                    key={tint}
                                    type="button"
                                    style={{ background: tint }}
                                    aria-current={i === shot}
                                    aria-label={`Фото ${i + 1}`}
                                    onClick={() => setShot(i)}
                                >
                                    <span aria-hidden>{product.emoji}</span>
                                </button>
                            ))}
                        </div>
                        <div className="mk-photo" style={{ background: shots[shot] }}>
                            <span aria-hidden>{product.emoji}</span>
                        </div>
                    </div>

                    <div className="mk-info">
                        <h1>{product.title}</h1>
                        <div className="mk-info__meta">
                            <span>
                                <b aria-hidden>★</b> {rating(product.rating)} · {sum(product.reviews)} отзывов
                            </span>
                            <span>Продано {sum(product.sold)}+</span>
                        </div>

                        <div className="mk-price">
                            <b>{sum(product.price)} сум</b>
                            {product.oldPrice && <s>{sum(product.oldPrice)} сум</s>}
                            {off > 0 && <em>−{off}%</em>}
                        </div>

                        {product.variants.map((variant) => (
                            <div key={variant.name} className="mk-opts">
                                <h3>
                                    {variant.name}: {chosen[variant.name] ?? variant.options[0]}
                                </h3>
                                <div role="group" aria-label={variant.name}>
                                    {variant.options.map((option) => (
                                        <button
                                            key={option}
                                            type="button"
                                            aria-pressed={(chosen[variant.name] ?? variant.options[0]) === option}
                                            onClick={() => setChosen({ ...chosen, [variant.name]: option })}
                                        >
                                            {option}
                                        </button>
                                    ))}
                                </div>
                            </div>
                        ))}

                        <div className={out ? 'mk-stock mk-stock--out' : 'mk-stock'}>
                            {out ? 'Нет в наличии — добавьте в избранное, чтобы не потерять' : `В наличии: ${product.stock} шт.`}
                        </div>

                        <div className="mk-buy">
                            <div className="mk-qty">
                                <button type="button" aria-label="Меньше" disabled={out || quantity <= 1} onClick={() => setQuantity(quantity - 1)}>
                                    −
                                </button>
                                <output aria-label="Количество">{quantity}</output>
                                <button
                                    type="button"
                                    aria-label="Больше"
                                    disabled={out || quantity >= product.stock}
                                    onClick={() => setQuantity(quantity + 1)}
                                >
                                    +
                                </button>
                            </div>
                            <button type="button" className="mk-btn" disabled={out} onClick={() => addToCart(product.id, quantity)}>
                                <ShoppingCart size={18} aria-hidden /> В корзину
                            </button>
                            <button
                                type="button"
                                className="mk-fav"
                                aria-pressed={liked}
                                aria-label={liked ? 'Убрать из избранного' : 'В избранное'}
                                onClick={() => toggleFavorite(product.id)}
                            >
                                <Heart size={20} aria-hidden />
                            </button>
                        </div>
                        {inCart > 0 && (
                            <Link href={routes.marketCart} className="mk-btn mk-btn--ghost">
                                <Check size={18} aria-hidden /> В корзине {inCart} шт. — перейти
                            </Link>
                        )}

                        <div className="mk-facts">
                            <div>
                                <MapPin size={16} aria-hidden /> Получение в пункте выдачи BTS в Ташкенте — выберете при оформлении
                            </div>
                            <div>
                                <CreditCard size={16} aria-hidden /> Оплата картой онлайн или наличными при получении
                            </div>
                            <div>
                                <RotateCcw size={16} aria-hidden /> Отменить заказ можно, пока он не уехал со склада
                            </div>
                        </div>

                        <div className="mk-seller">
                            <span className="mk-seller__logo" aria-hidden>
                                {seller.name.slice(0, 2).toUpperCase()}
                            </span>
                            <span>
                                <b>{seller.name}</b>
                                <small>
                                    {seller.verified && <BadgeCheck size={14} aria-hidden />}
                                    {seller.verified ? 'Проверенный продавец' : 'Продавец'} · ★ {rating(seller.rating)}
                                </small>
                            </span>
                            <Link href={routes.marketCatalog}>Все товары</Link>
                        </div>
                    </div>
                </div>

                <section className="mk-panel">
                    <h2>О товаре</h2>
                    <p>{product.description}</p>
                </section>

                <section className="mk-panel">
                    <h2>Характеристики</h2>
                    <dl className="mk-specs">
                        {product.specs.map(([name, value]) => (
                            <div key={name}>
                                <dt>{name}</dt>
                                <dd>{value}</dd>
                            </div>
                        ))}
                    </dl>
                </section>

                <section className="mk-panel">
                    <h2>Отзывы</h2>
                    <div className="mk-reviews-empty">
                        <span aria-hidden>💬</span>
                        <p>Отзывы покупателей появятся здесь после запуска заказов.</p>
                    </div>
                </section>

                <div className="mk-sh">
                    <h2>Похожие товары</h2>
                    <Link href={category ? `${routes.marketCatalog}?category=${category.slug}` : routes.marketCatalog}>Смотреть все →</Link>
                </div>
                <div className="mk-grid">
                    {similar.map((p) => (
                        <MarketCard key={p.id} product={p} />
                    ))}
                </div>
            </div>
        </MarketLayout>
    );
}
