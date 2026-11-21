import { BadgeCheck } from 'lucide-react';
import { MarketCard, MarketGridSkeleton } from '@/components/market/MarketCard';
import { Link } from '@/components/ui/Link';
import { MarketLayout } from '@/layouts/MarketLayout';
import { useApi } from '@/market/api';
import { plural, rating, sum } from '@/market/format';
import type { MarketShop } from '@/market/types';
import { routes } from '@/routes';

/** Страница продавца — витрина компании: кто продаёт и все его товары (/market/api/seller/<адрес>). */
export default function MarketShopPage({ slug }: { slug: string }) {
    const { data, loading, error, status, reload } = useApi<MarketShop>(`seller/${slug}`);

    if (!data) {
        const missing = status === 404;

        return (
            <MarketLayout title={missing ? 'Продавец не найден · SavdEx Market' : 'SavdEx Market'} tab="catalog">
                <div className="mk-in" style={{ paddingTop: 24 }} aria-busy={loading}>
                    {loading ? (
                        <div className="mk-grid">
                            <MarketGridSkeleton />
                        </div>
                    ) : (
                        <div className="mk-empty">
                            <span aria-hidden>🏬</span>
                            <h2>{missing ? 'Такого продавца нет' : 'Страница продавца не загрузилась'}</h2>
                            <p>{missing ? 'Возможно, магазин закрылся или ссылка устарела.' : error}</p>
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
                    )}
                </div>
            </MarketLayout>
        );
    }

    const { seller, items, total } = data;

    return (
        <MarketLayout title={`${seller.name} · SavdEx Market`} tab="catalog">
            <div className="mk-in">
                <nav className="mk-bc" aria-label="Путь">
                    <Link href={routes.market}>Главная</Link>› Продавцы › {seller.name}
                </nav>

                <header className="mk-shop">
                    {seller.logo ? (
                        <img className="mk-shop__logo" src={seller.logo} alt="" />
                    ) : (
                        <span className="mk-shop__logo" aria-hidden>
                            {seller.name.slice(0, 2).toUpperCase()}
                        </span>
                    )}
                    <div>
                        <h1>{seller.name}</h1>
                        <p>
                            {seller.verified && <BadgeCheck size={16} aria-hidden />}
                            {seller.verified ? 'Проверенный продавец · компания на SavdEx' : 'Продавец на SavdEx'}
                        </p>
                        {seller.description && <p className="mk-shop__about">{seller.description}</p>}
                    </div>
                    <dl>
                        {seller.rating > 0 && (
                            <div>
                                <dt>Рейтинг</dt>
                                <dd>★ {rating(seller.rating)}</dd>
                            </div>
                        )}
                        <div>
                            <dt>Товаров</dt>
                            <dd>{sum(total)}</dd>
                        </div>
                        {seller.since && (
                            <div>
                                <dt>На SavdEx с</dt>
                                <dd>{seller.since}</dd>
                            </div>
                        )}
                    </dl>
                </header>

                <div className="mk-sh">
                    <h2>
                        {sum(total)} {plural(total, ['товар', 'товара', 'товаров'])} продавца
                    </h2>
                    <Link href={seller.company}>Карточка компании на SavdEx →</Link>
                </div>
                {items.length > 0 ? (
                    <div className="mk-grid">
                        {items.map((p) => (
                            <MarketCard key={p.id} product={p} />
                        ))}
                    </div>
                ) : (
                    <div className="mk-empty">
                        <span aria-hidden>📦</span>
                        <h2>Продавец пока ничего не выставил</h2>
                        <p>Товары появятся здесь, как только склад примет первую поставку.</p>
                    </div>
                )}
            </div>
        </MarketLayout>
    );
}
