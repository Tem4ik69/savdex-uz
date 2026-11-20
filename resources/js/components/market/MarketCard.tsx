import { router } from '@inertiajs/react';
import { Check, Heart, ShoppingCart } from 'lucide-react';
import { useState } from 'react';
import { MarketPhoto } from '@/components/market/MarketPhoto';
import { Link } from '@/components/ui/Link';
import { cn } from '@/lib/cn';
import { localize } from '@/lib/locale';
import { rating, sum } from '@/market/format';
import { addProductToCart, cartLines, toggleFavorite, useCart, useFavorites } from '@/market/store';
import type { MarketProduct } from '@/market/types';
import { routes } from '@/routes';

/**
 * Карточка товара маркетплейса — одна на все ленты: подборки главной,
 * каталог, избранное, страница продавца. Цена в синей плашке, скидка
 * рядом, кнопка «В корзину» на всю ширину.
 *
 * Вся карточка — ссылка на товар (псевдоэлемент заголовка), сердечко
 * и корзина лежат поверх и работают сами. «В корзину» кладёт товар
 * сразу, если у него один вариант; если нужно выбрать цвет или размер —
 * открывает страницу товара. Гостя обе кнопки ведут на вход.
 */
export function MarketCard({ product }: { product: MarketProduct }) {
    const inCart = cartLines(useCart()).some((line) => line.productId === product.id);
    const liked = useFavorites().includes(product.id);
    const [busy, setBusy] = useState(false);
    const off = product.oldPrice ? Math.round((1 - product.price / product.oldPrice) * 100) : 0;
    const out = product.stock === 0;

    async function toCart() {
        setBusy(true);

        const result = await addProductToCart(product.slug);

        setBusy(false);

        if (result === 'choose') router.visit(localize(routes.marketProduct(product.slug)));
    }

    return (
        <article className="mk-card mk-card--hit">
            <div className="mk-card__ph">
                <MarketPhoto image={product.image} id={product.id} category={product.category} />
                {out && <span className="mk-card__out">Нет в наличии</span>}
                <button
                    type="button"
                    className="mk-fav"
                    aria-pressed={liked}
                    aria-label={liked ? 'Убрать из избранного' : 'В избранное'}
                    onClick={() => void toggleFavorite(product.id)}
                >
                    <Heart size={17} aria-hidden />
                </button>
            </div>
            <div className="mk-card__body">
                <div className="mk-card__price">
                    <b>
                        {sum(product.price)} <i>сум</i>
                    </b>
                    {product.oldPrice && <s>{sum(product.oldPrice)}</s>}
                    {off > 0 && <span className="mk-card__disc">−{off}%</span>}
                </div>
                <h3 className="mk-card__title">
                    <Link href={routes.marketProduct(product.slug)}>{product.title}</Link>
                </h3>
                <div className="mk-card__meta">
                    {product.reviews > 0 ? (
                        <>
                            <b aria-hidden>★</b> {rating(product.rating)} · {sum(product.reviews)} отзывов
                        </>
                    ) : (
                        product.sellerName
                    )}
                </div>
                <button
                    type="button"
                    className={cn('mk-card__cart', inCart && 'is-in')}
                    disabled={out || busy}
                    aria-label={inCart ? `В корзине: ${product.title}` : `В корзину: ${product.title}`}
                    onClick={() => void toCart()}
                >
                    {inCart ? <Check size={17} aria-hidden /> : <ShoppingCart size={17} aria-hidden />}
                    <span>{out ? 'Нет в наличии' : inCart ? 'В корзине' : 'В корзину'}</span>
                </button>
            </div>
        </article>
    );
}

/** Заглушка карточки на время загрузки списка. */
export function MarketCardSkeleton() {
    return (
        <div className="mk-skel" aria-hidden>
            <i />
            <i />
            <i />
            <i />
        </div>
    );
}

/** Ряд заглушек — пока список товаров грузится. */
export function MarketGridSkeleton({ count = 5 }: { count?: number }) {
    return (
        <>
            {Array.from({ length: count }, (_, i) => (
                <MarketCardSkeleton key={i} />
            ))}
        </>
    );
}
