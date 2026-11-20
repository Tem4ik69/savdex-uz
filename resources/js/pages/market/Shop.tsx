import { BadgeCheck } from 'lucide-react';
import { MarketCard } from '@/components/market/MarketCard';
import { Link } from '@/components/ui/Link';
import { MarketLayout } from '@/layouts/MarketLayout';
import { PRODUCTS, SELLERS } from '@/market/demo';
import { plural, rating, sum } from '@/market/format';
import { routes } from '@/routes';

/** Страница продавца — витрина компании: кто продаёт и все его товары. */
export default function MarketShop({ slug }: { slug: string }) {
    const seller = SELLERS.find((s) => s.slug === slug);
    const products = PRODUCTS.filter((p) => p.seller === slug);

    if (!seller) {
        return (
            <MarketLayout title="Продавец не найден · SavdEx Market" tab="catalog">
                <div className="mk-in" style={{ paddingTop: 24 }}>
                    <div className="mk-empty">
                        <span aria-hidden>🏬</span>
                        <h2>Такого продавца нет</h2>
                        <p>Возможно, магазин закрылся или ссылка устарела.</p>
                        <Link href={routes.marketCatalog} className="mk-btn">
                            Перейти в каталог
                        </Link>
                    </div>
                </div>
            </MarketLayout>
        );
    }

    const sold = products.reduce((s, p) => s + p.sold, 0);

    return (
        <MarketLayout title={`${seller.name} · SavdEx Market`} tab="catalog">
            <div className="mk-in">
                <nav className="mk-bc" aria-label="Путь">
                    <Link href={routes.market}>Главная</Link>› Продавцы › {seller.name}
                </nav>

                <header className="mk-shop">
                    <span className="mk-shop__logo" aria-hidden>
                        {seller.name.slice(0, 2).toUpperCase()}
                    </span>
                    <div>
                        <h1>{seller.name}</h1>
                        <p>
                            {seller.verified && <BadgeCheck size={16} aria-hidden />}
                            {seller.verified ? 'Проверенный продавец · компания на SavdEx' : 'Продавец на SavdEx'}
                        </p>
                    </div>
                    <dl>
                        <div>
                            <dt>Рейтинг</dt>
                            <dd>★ {rating(seller.rating)}</dd>
                        </div>
                        <div>
                            <dt>Товаров</dt>
                            <dd>{products.length}</dd>
                        </div>
                        <div>
                            <dt>Продано</dt>
                            <dd>{sum(sold)}+</dd>
                        </div>
                    </dl>
                </header>

                <div className="mk-sh">
                    <h2>
                        {products.length} {plural(products.length, ['товар', 'товара', 'товаров'])} продавца
                    </h2>
                </div>
                {products.length > 0 ? (
                    <div className="mk-grid">
                        {products.map((p) => (
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
