import { BadgeCheck } from 'lucide-react';
import { MarketCard, MarketGridSkeleton } from '@/components/market/MarketCard';
import { Link } from '@/components/ui/Link';
import { MarketLayout } from '@/layouts/MarketLayout';
import { useApi } from '@/market/api';
import { rating, sum } from '@/market/format';
import { lang } from '@/market/lang';
import { shopText } from '@/market/text/shop';
import type { MarketShop } from '@/market/types';
import { routes } from '@/routes';

/** Страница продавца — витрина компании: кто продаёт и все его товары (/market/api/seller/<адрес>). */
export default function MarketShopPage({ slug }: { slug: string }) {
    const L = lang(shopText);
    const { data, loading, error, status, reload } = useApi<MarketShop>(`seller/${slug}`);

    if (!data) {
        const missing = status === 404;

        return (
            <MarketLayout title={missing ? L.notFoundTitle : 'SavdEx Market'} tab="catalog">
                <div className="mk-in" style={{ paddingTop: 24 }} aria-busy={loading}>
                    {loading ? (
                        <div className="mk-grid">
                            <MarketGridSkeleton />
                        </div>
                    ) : (
                        <div className="mk-empty">
                            <span aria-hidden>🏬</span>
                            <h2>{missing ? L.missingTitle : L.failedTitle}</h2>
                            <p>{missing ? L.missingText : error}</p>
                            {missing ? (
                                <Link href={routes.marketCatalog} className="mk-btn">
                                    {L.toCatalog}
                                </Link>
                            ) : (
                                <button type="button" className="mk-btn" onClick={reload}>
                                    {L.retry}
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
                <nav className="mk-bc" aria-label={L.crumbs}>
                    <Link href={routes.market}>{L.home}</Link>› {L.sellers} › {seller.name}
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
                            {seller.verified ? L.verified : L.seller}
                        </p>
                        {seller.description && <p className="mk-shop__about">{seller.description}</p>}
                    </div>
                    <dl>
                        {seller.rating > 0 && (
                            <div>
                                <dt>{L.rating}</dt>
                                <dd>★ {rating(seller.rating)}</dd>
                            </div>
                        )}
                        <div>
                            <dt>{L.goods}</dt>
                            <dd>{sum(total)}</dd>
                        </div>
                        {seller.since && (
                            <div>
                                <dt>{L.since}</dt>
                                <dd>{seller.since}</dd>
                            </div>
                        )}
                    </dl>
                </header>

                <div className="mk-sh">
                    <h2>{L.items(sum(total), total)}</h2>
                    <Link href={seller.company}>{L.companyCard}</Link>
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
                        <h2>{L.emptyTitle}</h2>
                        <p>{L.emptyText}</p>
                    </div>
                )}
            </div>
        </MarketLayout>
    );
}
