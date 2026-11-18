import { Check, Heart, ShoppingCart } from 'lucide-react';
import { Link } from '@/components/ui/Link';
import { cn } from '@/lib/cn';
import { discount, type MarketProduct } from '@/market/demo';
import { rating, sum } from '@/market/format';
import { addToCart, toggleFavorite, useCart, useFavorites } from '@/market/store';
import { routes } from '@/routes';

const TAGS = { hit: 'Хит', new: 'Новинка', sale: 'Скидка' } as const;

/**
 * Карточка товара маркетплейса — три вида по подборкам главной:
 * hit — цена в синей плашке и кнопка «В корзину» (она же в каталоге);
 * sale — красная цена и «Продано»; fresh — крупная, цена на жёлтой бирке.
 *
 * Вся карточка — ссылка на товар (псевдоэлемент заголовка), сердечко
 * и корзина лежат поверх и работают сами.
 */
export function MarketCard({ product, kind = 'hit' }: { product: MarketProduct; kind?: 'hit' | 'sale' | 'fresh' }) {
    const inCart = (useCart()[product.id] ?? 0) > 0;
    const liked = Boolean(useFavorites()[product.id]);
    const off = discount(product);
    const out = product.stock === 0;

    return (
        <article className={cn('mk-card', kind === 'fresh' ? 'mk-card--new' : `mk-card--${kind}`)}>
            <div className="mk-card__ph" style={{ background: product.tint }}>
                <span aria-hidden>{product.emoji}</span>
                {kind === 'sale' && product.badge && <span className="mk-card__tag">{TAGS[product.badge]}</span>}
                {out && <span className="mk-card__out">Нет в наличии</span>}
                <button
                    type="button"
                    className="mk-fav"
                    aria-pressed={liked}
                    aria-label={liked ? 'Убрать из избранного' : 'В избранное'}
                    onClick={() => toggleFavorite(product.id)}
                >
                    <Heart size={17} aria-hidden />
                </button>
            </div>
            <div className="mk-card__body">
                <div className="mk-card__price">
                    <b className={off ? 'is-sale' : undefined}>
                        {sum(product.price)} <i>сум</i>
                    </b>
                    {product.oldPrice && <s>{sum(product.oldPrice)}</s>}
                    {off > 0 && <span className="mk-card__disc">−{off}%</span>}
                </div>
                <h3 className="mk-card__title">
                    <Link href={routes.marketProduct(product.slug)}>{product.title}</Link>
                </h3>
                <div className="mk-card__meta">
                    <b aria-hidden>★</b> {rating(product.rating)} · {sum(product.reviews)} отзывов
                </div>
                {kind === 'sale' && <div className="mk-card__meta">Продано {sum(product.sold)}+</div>}
                <button
                    type="button"
                    className={cn('mk-card__cart', inCart && 'is-in')}
                    disabled={out}
                    aria-label={inCart ? `В корзине: ${product.title}` : `В корзину: ${product.title}`}
                    onClick={() => addToCart(product.id)}
                >
                    {inCart ? <Check size={17} aria-hidden /> : <ShoppingCart size={17} aria-hidden />}
                    <span>{out ? 'Нет в наличии' : inCart ? 'В корзине' : 'В корзину'}</span>
                </button>
            </div>
        </article>
    );
}
