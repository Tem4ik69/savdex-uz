import { router, usePage } from '@inertiajs/react';
import { SlidersHorizontal } from 'lucide-react';
import { useState, type KeyboardEvent } from 'react';
import { MarketCard, MarketGridSkeleton } from '@/components/market/MarketCard';
import { Link } from '@/components/ui/Link';
import { cn } from '@/lib/cn';
import { MarketLayout } from '@/layouts/MarketLayout';
import { useApi } from '@/market/api';
import { plural, sum } from '@/market/format';
import { useCategories } from '@/market/store';
import type { MarketFilter, MarketListing } from '@/market/types';
import { routes } from '@/routes';
import type { SharedProps } from '@/types';

const SORTS: [string, string][] = [
    ['popular', 'Популярные'],
    ['cheap', 'Дешевле'],
    ['expensive', 'Дороже'],
    ['new', 'Новые'],
    ['rating', 'С высоким рейтингом'],
];

const SHELVES: Record<string, string> = { sale: 'Скидки', new: 'Новинки', hit: 'Хиты продаж', fav: 'Избранное' };

/**
 * Каталог. Всё, что выбрано, лежит в адресе (категория, поиск, цена,
 * характеристики, сортировка, страница) — им можно поделиться, и кнопка
 * «назад» возвращает прежний отбор. Страница передаёт адрес серверу как
 * есть (/market/api/catalog) и показывает ответ: товары, фильтры этой
 * категории, границы цены. Избранное — тот же каталог с only=fav.
 */
export default function MarketCatalog({ search }: { search: string }) {
    const { auth } = usePage<SharedProps>().props;
    const categories = useCategories();
    const params = new URLSearchParams(search);
    const only = params.get('only') ?? '';
    const needsLogin = only === 'fav' && !auth.user;
    const { data, loading, error, reload } = useApi<MarketListing>(needsLogin ? null : `catalog?${search}`);
    const [filtersOpen, setFiltersOpen] = useState(false);

    /** Поменять отбор: новые значения — в адрес, страница — с первой. */
    function update(patch: Record<string, string | null>, keepPage = false) {
        const next = new URLSearchParams(search);

        if (!keepPage) next.delete('page');

        for (const [key, value] of Object.entries(patch)) {
            if (value === null || value === '') next.delete(key);
            else next.set(key, value);
        }

        const query = next.toString();

        router.get(query ? `${routes.marketCatalog}?${query}` : routes.marketCatalog, {}, { preserveState: true, preserveScroll: keepPage ? false : true, replace: true });
    }

    const q = (params.get('q') ?? '').trim();
    const category = data?.category ?? null;
    const title = q ? `Поиск: «${q}»` : (category?.name ?? SHELVES[only] ?? 'Каталог');
    const sort = params.get('sort') ?? 'popular';
    // Раздел верхнего уровня, внутри которого мы сейчас, — чтобы раскрыть его подразделы
    const rootSlug = category?.path[0]?.slug ?? params.get('category');
    const changed = ['min', 'max'].some((key) => params.has(key)) || [...params.keys()].some((key) => key.startsWith('attr.')) || only === 'sale';
    const reset = () => {
        const next = new URLSearchParams();

        for (const key of ['q', 'category', 'sort']) {
            const value = params.get(key);

            if (value) next.set(key, value);
        }

        if (only && only !== 'sale') next.set('only', only);

        const query = next.toString();

        router.get(query ? `${routes.marketCatalog}?${query}` : routes.marketCatalog, {}, { preserveState: true, preserveScroll: true, replace: true });
    };

    return (
        <MarketLayout title={`${title} · SavdEx Market`} tab="catalog" search={q}>
            <div className="mk-in">
                <nav className="mk-bc" aria-label="Путь">
                    <Link href={routes.market}>Главная</Link>›<Link href={routes.marketCatalog}>Каталог</Link>
                    {category?.path.map((step, i) =>
                        i < category.path.length - 1 ? (
                            <span key={step.slug}>
                                › <Link href={`${routes.marketCatalog}?category=${step.slug}`}>{step.name}</Link>
                            </span>
                        ) : (
                            <span key={step.slug}>› {step.name}</span>
                        ),
                    )}
                    {!category && title !== 'Каталог' && <>› {title}</>}
                </nav>
                <div className="mk-title">
                    <h1>{title}</h1>
                    {data && (
                        <span>
                            {sum(data.total)} {plural(data.total, ['товар', 'товара', 'товаров'])}
                        </span>
                    )}
                </div>

                {needsLogin ? (
                    <div className="mk-gate">
                        <h2>Войдите, чтобы увидеть избранное</h2>
                        <p>Товары, отмеченные сердечком, хранятся в вашем аккаунте и видны с любого устройства.</p>
                        <Link href={routes.loginBack(`${routes.marketCatalog}?only=fav`)} className="mk-btn">
                            Войти или зарегистрироваться
                        </Link>
                    </div>
                ) : (
                    <div className="mk-catalog">
                        <aside className={cn('mk-filters', filtersOpen && 'is-open')} aria-label="Фильтры">
                            <div>
                                <h3>Категории</h3>
                                <ul>
                                    <li>
                                        <Link href={routes.marketCatalog} aria-current={!params.get('category') && !only}>
                                            Все товары
                                        </Link>
                                    </li>
                                    {(categories ?? []).map((c) => (
                                        <li key={c.slug}>
                                            <Link href={`${routes.marketCatalog}?category=${c.slug}`} aria-current={params.get('category') === c.slug}>
                                                <span aria-hidden>{c.emoji}</span>
                                                {c.name}
                                            </Link>
                                            {c.slug === rootSlug && c.children.length > 0 && (
                                                <ul className="mk-filters__sub">
                                                    {c.children.map((child) => (
                                                        <li key={child.slug}>
                                                            <Link
                                                                href={`${routes.marketCatalog}?category=${child.slug}`}
                                                                aria-current={params.get('category') === child.slug}
                                                            >
                                                                {child.name}
                                                            </Link>
                                                        </li>
                                                    ))}
                                                </ul>
                                            )}
                                        </li>
                                    ))}
                                </ul>
                            </div>
                            <PriceRange
                                key={`${params.get('min')}-${params.get('max')}`}
                                from={params.get('min') ?? ''}
                                to={params.get('max') ?? ''}
                                bounds={data?.price ?? null}
                                onChange={(min, max) => update({ min, max })}
                            />
                            <label className="mk-check">
                                <input type="checkbox" checked={only === 'sale'} onChange={(e) => update({ only: e.target.checked ? 'sale' : null })} />
                                Только со скидкой
                            </label>
                            {(data?.filters ?? []).map((filter) => (
                                <Filter key={filter.key} filter={filter} params={params} update={update} />
                            ))}
                            {changed && (
                                <button type="button" className="mk-reset" onClick={reset}>
                                    Сбросить фильтры
                                </button>
                            )}
                        </aside>

                        <div aria-busy={loading}>
                            <div className="mk-sort" role="group" aria-label="Сортировка">
                                <button type="button" className="mk-filters-toggle" aria-expanded={filtersOpen} onClick={() => setFiltersOpen(!filtersOpen)}>
                                    <SlidersHorizontal size={14} aria-hidden style={{ display: 'inline', verticalAlign: '-2px' }} /> Фильтры
                                </button>
                                {SORTS.map(([key, label]) => (
                                    <button key={key} type="button" aria-pressed={sort === key} onClick={() => update({ sort: key === 'popular' ? null : key })}>
                                        {label}
                                    </button>
                                ))}
                            </div>

                            {data?.fuzzy && <p className="mk-fuzzy">Точных совпадений нет — показаны товары с похожим названием.</p>}

                            {loading && (
                                <div className="mk-grid">
                                    <MarketGridSkeleton count={8} />
                                </div>
                            )}

                            {error && (
                                <div className="mk-failed">
                                    <h2>Каталог не загрузился</h2>
                                    <p>{error}</p>
                                    <button type="button" className="mk-btn" onClick={reload}>
                                        Повторить
                                    </button>
                                </div>
                            )}

                            {data && data.items.length > 0 && (
                                <>
                                    <div className="mk-grid">
                                        {data.items.map((p) => (
                                            <MarketCard key={p.id} product={p} />
                                        ))}
                                    </div>
                                    {data.pages > 1 && (
                                        <nav className="mk-pages" aria-label="Страницы каталога">
                                            <button
                                                type="button"
                                                className="mk-btn mk-btn--ghost"
                                                disabled={data.page <= 1}
                                                onClick={() => update({ page: data.page > 2 ? String(data.page - 1) : null }, true)}
                                            >
                                                ← Назад
                                            </button>
                                            <span className="mk-pages__now">
                                                Страница {data.page} из {data.pages}
                                            </span>
                                            <button
                                                type="button"
                                                className="mk-btn mk-btn--ghost"
                                                disabled={data.page >= data.pages}
                                                onClick={() => update({ page: String(data.page + 1) }, true)}
                                            >
                                                Дальше →
                                            </button>
                                        </nav>
                                    )}
                                </>
                            )}

                            {data && data.items.length === 0 && (
                                <div className="mk-empty">
                                    <span aria-hidden>{only === 'fav' && !changed ? '🤍' : '🔎'}</span>
                                    {only === 'fav' && !changed ? (
                                        <>
                                            <h2>В избранном пока пусто</h2>
                                            <p>Нажмите на сердечко на карточке товара — он появится здесь.</p>
                                            <Link href={routes.marketCatalog} className="mk-btn">
                                                Перейти в каталог
                                            </Link>
                                        </>
                                    ) : (
                                        <>
                                            <h2>Ничего не нашлось</h2>
                                            <p>
                                                {changed
                                                    ? 'Под такие фильтры товаров нет. Сбросьте их или расширьте цену.'
                                                    : q
                                                      ? 'Попробуйте другое слово или посмотрите в категориях.'
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
                                        </>
                                    )}
                                </div>
                            )}
                        </div>
                    </div>
                )}
            </div>
        </MarketLayout>
    );
}

/** Цена от и до: уходит в адрес по Enter или когда поле покинули, а не на каждую цифру. */
function PriceRange({
    from,
    to,
    bounds,
    onChange,
}: {
    from: string;
    to: string;
    bounds: { min: number | null; max: number | null } | null;
    onChange: (min: string | null, max: string | null) => void;
}) {
    const [min, setMin] = useState(from);
    const [max, setMax] = useState(to);
    const digits = (text: string) => text.replace(/\D/g, '');
    const commit = () => {
        if (digits(min) !== from || digits(max) !== to) onChange(digits(min) || null, digits(max) || null);
    };
    const onKey = (event: KeyboardEvent) => event.key === 'Enter' && commit();

    return (
        <div>
            <h3>Цена, сум</h3>
            <div className="mk-range">
                <input
                    inputMode="numeric"
                    placeholder={bounds?.min != null ? `от ${sum(bounds.min)}` : 'от'}
                    aria-label="Цена от"
                    value={min}
                    onChange={(e) => setMin(e.target.value)}
                    onBlur={commit}
                    onKeyDown={onKey}
                />
                <input
                    inputMode="numeric"
                    placeholder={bounds?.max != null ? `до ${sum(bounds.max)}` : 'до'}
                    aria-label="Цена до"
                    value={max}
                    onChange={(e) => setMax(e.target.value)}
                    onBlur={commit}
                    onKeyDown={onKey}
                />
            </div>
        </div>
    );
}

/**
 * Фильтр по характеристике категории. Выбор, строка и «да / нет» —
 * галочки со счётчиком товаров; число — от и до. В адресе:
 * attr.<код>=a,b и attr.<код>_min / _max.
 */
function Filter({
    filter,
    params,
    update,
}: {
    filter: MarketFilter;
    params: URLSearchParams;
    update: (patch: Record<string, string | null>) => void;
}) {
    const key = `attr.${filter.key}`;

    if (filter.kind === 'number') {
        if (filter.min == null || filter.max == null || filter.min === filter.max) return null;

        return (
            <NumberRange
                key={`${params.get(`${key}_min`)}-${params.get(`${key}_max`)}`}
                title={filter.unit ? `${filter.name}, ${filter.unit}` : filter.name}
                from={params.get(`${key}_min`) ?? ''}
                to={params.get(`${key}_max`) ?? ''}
                low={filter.min}
                high={filter.max}
                onChange={(min, max) => update({ [`${key}_min`]: min, [`${key}_max`]: max })}
            />
        );
    }

    const options = filter.options ?? [];

    if (options.length === 0) return null;

    const picked = (params.get(key) ?? '').split(',').filter(Boolean);

    return (
        <div>
            <h3>{filter.name}</h3>
            {options.map((option) => (
                <label key={option.value} className="mk-check">
                    <input
                        type="checkbox"
                        checked={picked.includes(option.value)}
                        onChange={(e) =>
                            update({ [key]: (e.target.checked ? [...picked, option.value] : picked.filter((v) => v !== option.value)).join(',') || null })
                        }
                    />
                    {option.name}
                    <span className="mk-count-chip">{option.count}</span>
                </label>
            ))}
        </div>
    );
}

function NumberRange({
    title,
    from,
    to,
    low,
    high,
    onChange,
}: {
    title: string;
    from: string;
    to: string;
    low: number;
    high: number;
    onChange: (min: string | null, max: string | null) => void;
}) {
    const [min, setMin] = useState(from);
    const [max, setMax] = useState(to);
    const clean = (text: string) => text.replace(',', '.').replace(/[^\d.]/g, '');
    const commit = () => {
        if (clean(min) !== from || clean(max) !== to) onChange(clean(min) || null, clean(max) || null);
    };
    const onKey = (event: KeyboardEvent) => event.key === 'Enter' && commit();

    return (
        <div>
            <h3>{title}</h3>
            <div className="mk-range">
                <input inputMode="decimal" placeholder={`от ${low}`} aria-label={`${title}: от`} value={min} onChange={(e) => setMin(e.target.value)} onBlur={commit} onKeyDown={onKey} />
                <input inputMode="decimal" placeholder={`до ${high}`} aria-label={`${title}: до`} value={max} onChange={(e) => setMax(e.target.value)} onBlur={commit} onKeyDown={onKey} />
            </div>
        </div>
    );
}
