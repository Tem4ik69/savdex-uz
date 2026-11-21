import { BadgeCheck, Check, CreditCard, Heart, MapPin, RotateCcw, ShoppingCart } from 'lucide-react';
import { useState } from 'react';
import { MarketCard } from '@/components/market/MarketCard';
import { MarketPhoto } from '@/components/market/MarketPhoto';
import { Link } from '@/components/ui/Link';
import { MarketLayout } from '@/layouts/MarketLayout';
import { useApi } from '@/market/api';
import { rating, sum } from '@/market/format';
import { addToCart, cartLines, toggleFavorite, useCart, useFavorites } from '@/market/store';
import type { MarketListing, MarketOffer, MarketProductPage } from '@/market/types';
import { routes } from '@/routes';

/**
 * Карточка товара: фото, варианты, цена и скидка, «В корзину» и «В
 * избранное», продавец, как получить, характеристики, место под отзывы
 * (сами отзывы — второй этап по ТЗ).
 *
 * Данные — /market/api/product/<адрес>. Покупают не товар, а его
 * вариант (offer): у каждого сочетания «цвет + размер» своя цена и
 * остаток, и в корзину уходит номер варианта.
 */
export default function MarketProductView({ slug }: { slug: string }) {
    const { data, loading, error, status, reload } = useApi<{ product: MarketProductPage }>(`product/${slug}`);

    if (loading) {
        return (
            <MarketLayout title="SavdEx Market" tab="catalog">
                <div className="mk-in" aria-busy>
                    <div className="mk-product mk-product--loading" style={{ marginTop: 24 }}>
                        <div className="mk-skel-block" style={{ aspectRatio: '1' }} />
                        <div style={{ display: 'grid', gap: 14, alignContent: 'start' }}>
                            <div className="mk-skel-block" style={{ height: 34, width: '80%' }} />
                            <div className="mk-skel-block" style={{ height: 18, width: '40%' }} />
                            <div className="mk-skel-block" style={{ height: 44, width: '55%' }} />
                            <div className="mk-skel-block" style={{ height: 44 }} />
                            <div className="mk-skel-block" style={{ height: 96 }} />
                        </div>
                    </div>
                </div>
            </MarketLayout>
        );
    }

    if (!data) {
        const missing = status === 404;

        return (
            <MarketLayout title={missing ? 'Товар не найден · SavdEx Market' : 'SavdEx Market'} tab="catalog">
                <div className="mk-in" style={{ paddingTop: 24 }}>
                    <div className="mk-empty">
                        <span aria-hidden>📦</span>
                        <h2>{missing ? 'Такого товара нет' : 'Товар не загрузился'}</h2>
                        <p>{missing ? 'Возможно, продавец снял его с продажи или ссылка устарела.' : error}</p>
                        {missing ? (
                            <Link href={routes.marketCatalog} className="mk-btn">
                                Перейти в каталог
                            </Link>
                        ) : (
                            <button type="button" className="mk-btn" onClick={reload}>
                                Повторить
                            </button>
                        )}
                    </div>
                </div>
            </MarketLayout>
        );
    }

    // key: другой товар — выбор варианта и количество начинаются заново
    return <Loaded key={data.product.id} product={data.product} />;
}

/** Вариант под выбранные значения: «Цвет: Чёрный, Память: 256 ГБ». */
function offerFor(product: MarketProductPage, chosen: Record<string, string>): MarketOffer | undefined {
    return product.offers.find((offer) => product.variants.every((v) => String(offer.options[v.name] ?? '') === chosen[v.name]));
}

function Loaded({ product }: { product: MarketProductPage }) {
    const cart = useCart();
    const favorites = useFavorites();
    // Сердечко переключают и на других карточках страницы — источник один, общий список;
    // флаг из ответа товара нужен, только пока этот список ещё не пришёл
    const [toggled, setToggled] = useState(false);
    const liked = toggled ? favorites.includes(product.id) : favorites.includes(product.id) || product.favorite;
    const [quantity, setQuantity] = useState(1);
    const [busy, setBusy] = useState(false);
    // По умолчанию — первый вариант, который есть в наличии
    const first = product.offers.find((offer) => offer.stock > 0) ?? product.offers[0];
    const [chosen, setChosen] = useState<Record<string, string>>(() =>
        Object.fromEntries(product.variants.map((v) => [v.name, String(first?.options[v.name] ?? v.options[0])])),
    );
    const [shot, setShot] = useState(0);
    const offer = offerFor(product, chosen);
    const similar = useApi<MarketListing>(`catalog?category=${product.category}`);

    const price = offer?.price ?? product.price;
    const oldPrice = offer ? offer.oldPrice : product.oldPrice;
    const stock = offer?.stock ?? 0;
    const off = oldPrice ? Math.round((1 - price / oldPrice) * 100) : 0;
    const out = stock === 0;
    const inCart = offer ? (cartLines(cart).find((line) => line.variantId === offer.id)?.quantity ?? 0) : 0;
    // Фото выбранного варианта (цвета) — первыми, за ними общие
    const images = [...product.images.filter((i) => offer && i.variantId === offer.id), ...product.images.filter((i) => i.variantId === null)];
    const photo = images[Math.min(shot, images.length - 1)];
    const root = product.categoryPath[0];
    const leaf = product.categoryPath[product.categoryPath.length - 1];
    const others = (similar.data?.items ?? []).filter((p) => p.id !== product.id).slice(0, 5);

    async function toCart() {
        if (!offer) return;

        setBusy(true);
        await addToCart(offer.id, quantity);
        setBusy(false);
    }

    return (
        <MarketLayout title={`${product.title} · SavdEx Market`} tab="catalog">
            <div className="mk-in">
                <nav className="mk-bc" aria-label="Путь">
                    <Link href={routes.market}>Главная</Link>
                    {product.categoryPath.map((step) => (
                        <span key={step.slug}>
                            › <Link href={`${routes.marketCatalog}?category=${step.slug}`}>{step.name}</Link>
                        </span>
                    ))}
                    <span>› {product.title}</span>
                </nav>

                <div className="mk-product">
                    <div className={images.length > 1 ? 'mk-gallery' : 'mk-gallery mk-gallery--single'}>
                        {images.length > 1 && (
                            <div className="mk-thumbs">
                                {images.map((image, i) => (
                                    <button key={image.id} type="button" aria-current={image.id === photo?.id} aria-label={`Фото ${i + 1}`} onClick={() => setShot(i)}>
                                        <img src={image.thumb} alt="" loading="lazy" />
                                    </button>
                                ))}
                            </div>
                        )}
                        <div className="mk-photo">
                            <MarketPhoto image={photo?.url ?? null} id={product.id} category={product.category} alt={product.title} />
                        </div>
                    </div>

                    <div className="mk-info">
                        <h1>{product.title}</h1>
                        <div className="mk-info__meta">
                            {product.reviews > 0 && (
                                <span>
                                    <b aria-hidden>★</b> {rating(product.rating)} · {sum(product.reviews)} отзывов
                                </span>
                            )}
                            {product.sold > 0 && <span>Продано {sum(product.sold)}+</span>}
                        </div>

                        <div className="mk-price">
                            <b>{sum(price)} сум</b>
                            {oldPrice && <s>{sum(oldPrice)} сум</s>}
                            {off > 0 && <em>−{off}%</em>}
                        </div>

                        {product.variants.map((variant) => (
                            <div key={variant.name} className="mk-opts">
                                <h3>
                                    {variant.name}: {chosen[variant.name]}
                                </h3>
                                <div role="group" aria-label={variant.name}>
                                    {variant.options.map((option) => (
                                        <button
                                            key={option}
                                            type="button"
                                            aria-pressed={chosen[variant.name] === option}
                                            onClick={() => {
                                                setChosen({ ...chosen, [variant.name]: option });
                                                setQuantity(1);
                                                setShot(0);
                                            }}
                                        >
                                            {option}
                                        </button>
                                    ))}
                                </div>
                            </div>
                        ))}

                        <div className={out ? 'mk-stock mk-stock--out' : 'mk-stock'}>
                            {!offer
                                ? 'Такого сочетания нет — выберите другое'
                                : out
                                  ? 'Нет в наличии — добавьте в избранное, чтобы не потерять'
                                  : `В наличии: ${stock} шт.`}
                        </div>

                        <div className="mk-buy">
                            <div className="mk-qty">
                                <button type="button" aria-label="Меньше" disabled={out || quantity <= 1} onClick={() => setQuantity(quantity - 1)}>
                                    −
                                </button>
                                <output aria-label="Количество">{quantity}</output>
                                <button type="button" aria-label="Больше" disabled={out || quantity >= stock} onClick={() => setQuantity(quantity + 1)}>
                                    +
                                </button>
                            </div>
                            <button type="button" className="mk-btn" disabled={out || busy} onClick={() => void toCart()}>
                                <ShoppingCart size={18} aria-hidden /> В корзину
                            </button>
                            <button
                                type="button"
                                className="mk-fav"
                                aria-pressed={liked}
                                aria-label={liked ? 'Убрать из избранного' : 'В избранное'}
                                onClick={() => {
                                    // Список мог не успеть прийти: сначала сверяем его с флагом товара
                                    setToggled(true);
                                    void toggleFavorite(product.id);
                                }}
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
                            {product.sellerInfo.logo ? (
                                <img className="mk-seller__logo" src={product.sellerInfo.logo} alt="" />
                            ) : (
                                <span className="mk-seller__logo" aria-hidden>
                                    {product.sellerInfo.name.slice(0, 2).toUpperCase()}
                                </span>
                            )}
                            <span>
                                <b>{product.sellerInfo.name}</b>
                                <small>
                                    {product.sellerInfo.verified && <BadgeCheck size={14} aria-hidden />}
                                    {product.sellerInfo.verified ? 'Проверенный продавец' : 'Продавец'}
                                    {product.sellerInfo.rating > 0 && ` · ★ ${rating(product.sellerInfo.rating)}`}
                                </small>
                            </span>
                            <Link href={routes.marketShop(product.sellerInfo.slug)}>Магазин продавца</Link>
                        </div>
                    </div>
                </div>

                {product.description && (
                    <section className="mk-panel">
                        <h2>О товаре</h2>
                        <p style={{ whiteSpace: 'pre-line' }}>{product.description}</p>
                    </section>
                )}

                {product.specs.length > 0 && (
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
                )}

                <section className="mk-panel">
                    <h2>Отзывы</h2>
                    <div className="mk-reviews-empty">
                        <span aria-hidden>💬</span>
                        <p>Отзывы покупателей появятся здесь после запуска заказов.</p>
                    </div>
                </section>

                {others.length > 0 && (
                    <>
                        <div className="mk-sh">
                            <h2>Похожие товары</h2>
                            <Link href={`${routes.marketCatalog}?category=${(leaf ?? root)?.slug ?? ''}`}>Смотреть все →</Link>
                        </div>
                        <div className="mk-grid">
                            {others.map((p) => (
                                <MarketCard key={p.id} product={p} />
                            ))}
                        </div>
                    </>
                )}
            </div>
        </MarketLayout>
    );
}
