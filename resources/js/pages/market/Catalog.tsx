import { SlidersHorizontal } from 'lucide-react';
import { useState } from 'react';
import { MarketCard } from '@/components/market/MarketCard';
import { Link } from '@/components/ui/Link';
import { cn } from '@/lib/cn';
import { MarketLayout } from '@/layouts/MarketLayout';
import { CATEGORIES, categoryOf, discount, PRODUCTS, SELLERS, type MarketProduct } from '@/market/demo';
import { plural } from '@/market/format';
import { useFavorites } from '@/market/store';
import { routes } from '@/routes';

interface Query {
    q?: string;
    category?: string;
    sort?: string;
    /** Подборка: sale, new, hit или fav (избранное) */
    only?: string;
    /** Потолок цены из подборки «До 100 000» */
    max?: string;
}

const SORTS: [string, string, (a: MarketProduct, b: MarketProduct) => number][] = [
    ['popular', 'Популярные', (a, b) => b.sold - a.sold],
    ['cheap', 'Дешевле', (a, b) => a.price - b.price],
    ['expensive', 'Дороже', (a, b) => b.price - a.price],
    ['new', 'Новые', (a, b) => b.id - a.id],
    ['rating', 'С высоким рейтингом', (a, b) => b.rating - a.rating],
];

const SHELVES: Record<string, string> = { sale: 'Скидки', new: 'Новинки', hit: 'Хиты продаж', fav: 'Избранное' };

const number = (text: string): number | null => {
    const value = Number(text.replace(/\D/g, ''));

    return text.trim() && Number.isFinite(value) ? value : null;
};

/**
 * Каталог: категории, цена, продавец, «только со скидкой», сортировка.
 * Категория, подборка и поиск приходят адресом (ими можно поделиться),
 * остальные фильтры — на странице. Избранное — тот же каталог с only=fav.
 */
export default function MarketCatalog({ query }: { query: Query }) {
    const favorites = useFavorites();
    const [sort, setSort] = useState(SORTS.some(([key]) => key === query.sort) ? String(query.sort) : 'popular');
    const [from, setFrom] = useState('');
    const [to, setTo] = useState(query.max ?? '');
    const [saleOnly, setSaleOnly] = useState(false);
    const [sellers, setSellers] = useState<string[]>([]);
    const [filtersOpen, setFiltersOpen] = useState(false);

    const category = query.category ? categoryOf(query.category) : undefined;
    const needle = (query.q ?? '').trim().toLowerCase();
    const min = number(from);
    const max = number(to);

    const found = PRODUCTS.filter(
        (p) =>
            (!query.category || p.category === query.category) &&
            (!needle || p.title.toLowerCase().includes(needle)) &&
            (query.only !== 'sale' || p.oldPrice !== null) &&
            (query.only !== 'new' || p.badge === 'new') &&
            (query.only !== 'hit' || p.badge === 'hit') &&
            (query.only !== 'fav' || Boolean(favorites[p.id])) &&
            (min === null || p.price >= min) &&
            (max === null || p.price <= max) &&
            (!saleOnly || discount(p) > 0) &&
            (sellers.length === 0 || sellers.includes(p.seller)),
    ).sort(SORTS.find(([key]) => key === sort)?.[2]);

    const title = needle
        ? `Поиск: «${query.q?.trim()}»`
        : (category?.name ?? (query.only ? SHELVES[query.only] : undefined) ?? 'Каталог');
    const changed = from !== '' || to !== '' || saleOnly || sellers.length > 0;

    const reset = () => {
        setFrom('');
        setTo('');
        setSaleOnly(false);
        setSellers([]);
    };

    return (
        <MarketLayout title={`${title} · SavdEx Market`} tab="catalog" search={query.q ?? ''}>
            <div className="mk-in">
                <nav className="mk-bc" aria-label="Путь">
                    <Link href={routes.market}>Главная</Link>›<Link href={routes.marketCatalog}>Каталог</Link>
                    {title !== 'Каталог' && <>› {title}</>}
                </nav>
                <div className="mk-title">
                    <h1>{title}</h1>
                    <span>
                        {found.length} {plural(found.length, ['товар', 'товара', 'товаров'])}
                    </span>
                </div>

                <div className="mk-catalog">
                    <aside className={cn('mk-filters', filtersOpen && 'is-open')} aria-label="Фильтры">
                        <div>
                            <h3>Категории</h3>
                            <ul>
                                <li>
                                    <Link href={routes.marketCatalog} aria-current={!query.category && !query.only}>
                                        Все товары
                                    </Link>
                                </li>
                                {CATEGORIES.map((c) => (
                                    <li key={c.slug}>
                                        <Link
                                            href={`${routes.marketCatalog}?category=${c.slug}`}
                                            aria-current={query.category === c.slug}
                                        >
                                            <span aria-hidden>{c.emoji}</span>
                                            {c.name}
                                        </Link>
                                    </li>
                                ))}
                            </ul>
                        </div>
                        <div>
                            <h3>Цена, сум</h3>
                            <div className="mk-range">
                                <input
                                    inputMode="numeric"
                                    placeholder="от"
                                    aria-label="Цена от"
                                    value={from}
                                    onChange={(e) => setFrom(e.target.value)}
                                />
                                <input
                                    inputMode="numeric"
                                    placeholder="до"
                                    aria-label="Цена до"
                                    value={to}
                                    onChange={(e) => setTo(e.target.value)}
                                />
                            </div>
                        </div>
                        <label className="mk-check">
                            <input type="checkbox" checked={saleOnly} onChange={(e) => setSaleOnly(e.target.checked)} />
                            Только со скидкой
                        </label>
                        <div>
                            <h3>Продавец</h3>
                            {SELLERS.map((s) => (
                                <label key={s.slug} className="mk-check">
                                    <input
                                        type="checkbox"
                                        checked={sellers.includes(s.slug)}
                                        onChange={(e) =>
                                            setSellers(e.target.checked ? [...sellers, s.slug] : sellers.filter((x) => x !== s.slug))
                                        }
                                    />
                                    {s.name}
                                </label>
                            ))}
                        </div>
                        {changed && (
                            <button type="button" className="mk-reset" onClick={reset}>
                                Сбросить фильтры
                            </button>
                        )}
                    </aside>

                    <div>
                        <div className="mk-sort" role="group" aria-label="Сортировка">
                            <button
                                type="button"
                                className="mk-filters-toggle"
                                aria-expanded={filtersOpen}
                                onClick={() => setFiltersOpen(!filtersOpen)}
                            >
                                <SlidersHorizontal size={14} aria-hidden style={{ display: 'inline', verticalAlign: '-2px' }} /> Фильтры
                            </button>
                            {SORTS.map(([key, label]) => (
                                <button key={key} type="button" aria-pressed={sort === key} onClick={() => setSort(key)}>
                                    {label}
                                </button>
                            ))}
                        </div>

                        {found.length > 0 ? (
                            <div className="mk-grid">
                                {found.map((p) => (
                                    <MarketCard key={p.id} product={p} />
                                ))}
                            </div>
                        ) : query.only === 'fav' && !changed ? (
                            <div className="mk-empty">
                                <span aria-hidden>🤍</span>
                                <h2>В избранном пока пусто</h2>
                                <p>Нажмите на сердечко на карточке товара — он появится здесь.</p>
                                <Link href={routes.marketCatalog} className="mk-btn">
                                    Перейти в каталог
                                </Link>
                            </div>
                        ) : (
                            <div className="mk-empty">
                                <span aria-hidden>🔎</span>
                                <h2>Ничего не нашлось</h2>
                                <p>
                                    {changed
                                        ? 'Под такие фильтры товаров нет. Сбросьте их или расширьте цену.'
                                        : 'В этом разделе пока нет товаров. Загляните в другие категории.'}
                                </p>
                                {changed ? (
                                    <button type="button" className="mk-btn" onClick={reset}>
                                        Сбросить фильтры
                                    </button>
                                ) : (
                                    <Link href={routes.marketCatalog} className="mk-btn">
                                        Все товары
                                    </Link>
                                )}
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </MarketLayout>
    );
}
