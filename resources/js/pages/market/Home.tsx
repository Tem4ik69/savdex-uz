import { ChevronLeft, ChevronRight } from 'lucide-react';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { MarketCard, MarketGridSkeleton } from '@/components/market/MarketCard';
import { MarketPhoto } from '@/components/market/MarketPhoto';
import { Link } from '@/components/ui/Link';
import { MarketLayout } from '@/layouts/MarketLayout';
import { api, useApi } from '@/market/api';
import { BANNERS, COUPONS, STORIES, type ServerBanner } from '@/market/content';
import { sum } from '@/market/format';
import { lang } from '@/market/lang';
import { useCategories } from '@/market/store';
import type { MarketListing, MarketProduct } from '@/market/types';
import { homeText } from '@/market/text/home';
import { routes } from '@/routes';

const catalog = (query: string) => (query ? `${routes.marketCatalog}?${query}` : routes.marketCatalog);
const discount = (p: MarketProduct) => (p.oldPrice ? Math.round((1 - p.price / p.oldPrice) * 100) : 0);

/**
 * Главная маркетплейса: подборки-кружки, «Скидки дня» с баннером,
 * купоны, категории, три подборки — «Хиты», «Распродажа», «Новинки» —
 * и лента «Все товары», которая догружается при прокрутке.
 *
 * Товары, категории и баннеры — с сервера (/market/api/…). Подборки —
 * тот же каталог с отбором only=hit | sale | new. Кружки и купоны пока
 * статичные (market/content.ts): на сервере их нет.
 */
export default function MarketHome() {
    const L = lang(homeText);
    const categories = useCategories();
    const sale = useApi<MarketListing>('catalog?only=sale');
    const deals = [...(sale.data?.items ?? [])].sort((a, b) => discount(b) - discount(a)).slice(0, 3);

    return (
        <MarketLayout title="SavdEx Market" tab="home">
            <div className="mk-in">
                <Row className="mk-stories" label={L.stories}>
                    {lang(STORIES).map((story) => (
                        <Link key={story.label} href={catalog(story.query)} className="mk-story">
                            <span aria-hidden>{story.emoji}</span>
                            {story.label}
                        </Link>
                    ))}
                </Row>

                <div className="mk-deal">
                    <section className="mk-flash" aria-label={L.deals} aria-busy={sale.loading}>
                        <h2>
                            {L.deals} <Countdown />
                        </h2>
                        <div className="mk-flash-items">
                            {deals.map((p) => (
                                <Link key={p.id} href={routes.marketProduct(p.slug)} aria-label={p.title}>
                                    <MarketPhoto image={p.image} id={p.id} category={p.category} className="mk-flash-photo" />
                                    {sum(p.price)}
                                    <em>−{discount(p)}%</em>
                                </Link>
                            ))}
                            {!sale.loading && deals.length === 0 && <p className="mk-flash-empty">{L.dealsEmpty}</p>}
                        </div>
                    </section>
                    <Banners />
                </div>

                <Coupons />

                {categories !== null && categories.length > 0 && (
                    <Row className="mk-cats" label={L.categories}>
                        {categories.slice(0, 11).map((c) => (
                            <Link key={c.slug} href={catalog(`category=${c.slug}`)} className="mk-cat">
                                <span aria-hidden>{c.emoji}</span>
                                {c.name}
                            </Link>
                        ))}
                    </Row>
                )}

                <Shelf title={L.hits} query="only=hit" />
                <Strip />
                <Shelf title={L.sale} query="only=sale" sale preloaded={sale} />
                <Shelf title={L.novelties} query="only=new" />

                <Feed />

                <aside className="mk-strip">
                    <span>
                        {L.sellTitle}
                        <small>{L.sellText}</small>
                    </span>
                    <Link href={routes.marketSell}>{L.sellCta}</Link>
                </aside>
            </div>
        </MarketLayout>
    );
}

/**
 * Ряд, который прокручивается вбок, — со стрелками по краям.
 *
 * Стрелка видна, только когда в её сторону есть что листать: на широком
 * экране, где ряд помещается целиком, стрелок нет вовсе. Нажатие
 * прокручивает примерно на три четверти видимой ширины. На телефоне
 * стрелки скрыты стилями — там ряд листают пальцем.
 */
function Row({ className, label, children }: { className: string; label: string; children: ReactNode }) {
    const L = lang(homeText);
    const track = useRef<HTMLElement>(null);
    const [can, setCan] = useState({ back: false, forward: false });

    useEffect(() => {
        const el = track.current;

        if (!el) return;

        const update = () => {
            const back = el.scrollLeft > 4;
            const forward = el.scrollLeft + el.clientWidth < el.scrollWidth - 4;

            setCan((prev) => (prev.back === back && prev.forward === forward ? prev : { back, forward }));
        };

        update();
        el.addEventListener('scroll', update, { passive: true });
        window.addEventListener('resize', update);

        return () => {
            el.removeEventListener('scroll', update);
            window.removeEventListener('resize', update);
        };
    }, []);

    const scroll = (direction: 1 | -1) => {
        const el = track.current;

        if (!el) return;

        const smooth = !window.matchMedia('(prefers-reduced-motion: reduce)').matches;

        el.scrollBy({ left: direction * el.clientWidth * 0.75, behavior: smooth ? 'smooth' : 'auto' });
    };

    return (
        <div className={`mk-row mk-row--${className.replace('mk-', '')}`}>
            {can.back && (
                <button type="button" className="mk-row__arrow mk-row__arrow--back" aria-label={L.back(label)} onClick={() => scroll(-1)}>
                    <ChevronLeft size={20} aria-hidden />
                </button>
            )}
            <nav ref={track} className={className} aria-label={label}>
                {children}
            </nav>
            {can.forward && (
                <button type="button" className="mk-row__arrow mk-row__arrow--forward" aria-label={L.forward(label)} onClick={() => scroll(1)}>
                    <ChevronRight size={20} aria-hidden />
                </button>
            )}
        </div>
    );
}

/**
 * Подборка главной: первый ряд каталога с отбором. Пустая подборка не
 * показывается вовсе — заголовок над пустотой хуже, чем его отсутствие;
 * не загрузилась — тоже: главная остаётся целой без неё.
 */
function Shelf({
    title,
    query,
    sale = false,
    preloaded,
}: {
    title: string;
    query: string;
    sale?: boolean;
    /** Уже запрошенный список — чтобы не спрашивать сервер дважды */
    preloaded?: { data: MarketListing | null; loading: boolean; error: string | null };
}) {
    const L = lang(homeText);
    const own = useApi<MarketListing>(preloaded ? null : `catalog?${query}`);
    const { data, loading } = preloaded ?? own;
    const products = data?.items.slice(0, 5) ?? [];

    if (!loading && products.length === 0) return null;

    return (
        <section aria-busy={loading}>
            <div className={sale ? 'mk-sh mk-sh--sale' : 'mk-sh'}>
                <h2>{title}</h2>
                <Link href={catalog(query)}>{L.seeAll}</Link>
            </div>
            <div className="mk-grid mk-shelf">
                {loading ? <MarketGridSkeleton /> : products.map((p) => <MarketCard key={p.id} product={p} />)}
            </div>
        </section>
    );
}

/** Полоса-баннер между подборками — место strip из админки; пусто — ничего. */
function Strip() {
    const { data } = useApi<{ banners: ServerBanner[] }>('banners?place=strip');
    const banner = data?.banners[0];

    if (!banner) return null;

    const picture = (
        <picture>
            {banner.imageMobile && <source media="(max-width: 640px)" srcSet={banner.imageMobile} />}
            <img src={banner.image} alt={banner.alt} loading="lazy" />
        </picture>
    );

    return banner.url ? (
        <a href={banner.url} className="mk-strip-banner">
            {picture}
        </a>
    ) : (
        <div className="mk-strip-banner">{picture}</div>
    );
}

/**
 * Лента «Все товары» в конце главной: следующая страница каталога
 * запрашивается сама, когда до низа ленты докручивают, — и так до
 * последней. Пока страница идёт — карточки-заглушки; не пришла —
 * сообщение и «Повторить». Без наблюдателя (старый браузер) — кнопка
 * «Показать ещё».
 */
function Feed() {
    const L = lang(homeText);
    const [items, setItems] = useState<MarketProduct[]>([]);
    const [page, setPage] = useState(0);
    const [pages, setPages] = useState<number | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const sentinel = useRef<HTMLDivElement>(null);
    const busy = useRef(false);
    const done = pages !== null && page >= pages;

    const more = () => {
        if (busy.current) return;

        busy.current = true;
        setLoading(true);
        setError(null);
        api<MarketListing>(`catalog?sort=popular&page=${page + 1}`)
            .then((data) => {
                // Товар мог сдвинуться между страницами — повторов в ленте не показываем
                setItems((prev) => [...prev, ...data.items.filter((p) => !prev.some((x) => x.id === p.id))]);
                setPage(data.page);
                setPages(data.pages);
            })
            .catch((failure: unknown) => setError(failure instanceof Error ? failure.message : L.loadFailed))
            .finally(() => {
                busy.current = false;
                setLoading(false);
            });
    };

    // Первая страница — сразу
    useEffect(() => {
        more();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    useEffect(() => {
        const target = sentinel.current;

        if (!target || done || loading || error || page === 0 || typeof IntersectionObserver === 'undefined') return;

        // Запас в 300 px: страница успевает приехать до того, как докрутят до края
        const observer = new IntersectionObserver((entries) => entries[0]?.isIntersecting && more(), { rootMargin: '300px' });

        observer.observe(target);

        return () => observer.disconnect();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [done, loading, error, page]);

    if (done && items.length === 0) return null;

    return (
        <section aria-busy={loading}>
            <div className="mk-sh">
                <h2>{L.allProducts}</h2>
                <Link href={routes.marketCatalog}>{L.toCatalog}</Link>
            </div>
            <div className="mk-grid">
                {items.map((p) => (
                    <MarketCard key={p.id} product={p} />
                ))}
                {loading && <MarketGridSkeleton />}
            </div>
            {error && (
                <div className="mk-failed" style={{ marginTop: 16 }}>
                    <p>{error}</p>
                    <button type="button" className="mk-btn" onClick={more}>
                        {L.retry}
                    </button>
                </div>
            )}
            {done ? (
                <p className="mk-feed-end">{L.feedEnd}</p>
            ) : (
                <div ref={sentinel} className="mk-feed-more">
                    {!loading && !error && page > 0 && (
                        <button type="button" className="mk-btn mk-btn--ghost" onClick={more}>
                            {L.showMore}
                        </button>
                    )}
                </div>
            )}
        </section>
    );
}

/**
 * Сколько осталось до полуночи. До гидрации — прочерки: время сервера
 * и браузера разное, и разметка иначе не сошлась бы.
 */
function Countdown() {
    const L = lang(homeText);
    const [left, setLeft] = useState<number | null>(null);

    useEffect(() => {
        const tick = () => {
            const now = new Date();
            const midnight = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);

            setLeft(Math.floor((midnight.getTime() - now.getTime()) / 1000));
        };

        tick();
        const timer = window.setInterval(tick, 1000);

        return () => window.clearInterval(timer);
    }, []);

    const part = (value: number) => String(value).padStart(2, '0');
    const parts = left === null ? ['––', '––', '––'] : [part(Math.floor(left / 3600)), part(Math.floor(left / 60) % 60), part(left % 60)];

    return (
        <span className="mk-timer" aria-label={L.timer}>
            <i>{parts[0]}</i>:<i>{parts[1]}</i>:<i>{parts[2]}</i>
        </span>
    );
}

/**
 * Слайдер баннеров: листается сам раз в шесть секунд, точки — вручную.
 * Баннеры — из админки (место slider); пока там пусто — запасные из
 * вёрстки, чтобы первый экран не оставался без баннера.
 */
function Banners() {
    const L = lang(homeText);
    const fallback = lang(BANNERS);
    const { data } = useApi<{ banners: ServerBanner[] }>('banners?place=slider');
    const server = data?.banners ?? [];
    const count = server.length || fallback.length;
    const [index, setIndex] = useState(0);
    const [paused, setPaused] = useState(false);

    useEffect(() => {
        if (paused || count < 2 || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

        const timer = window.setInterval(() => setIndex((i) => (i + 1) % count), 6000);

        return () => window.clearInterval(timer);
    }, [paused, count]);

    const at = index % count;
    const dots = count > 1 && (
        <div className="mk-dots">
            {Array.from({ length: count }, (_, i) => (
                <button key={i} type="button" aria-current={i === at} aria-label={L.bannerDot(i + 1, count)} onClick={() => setIndex(i)} />
            ))}
        </div>
    );
    const hold = {
        onMouseEnter: () => setPaused(true),
        onMouseLeave: () => setPaused(false),
        onFocus: () => setPaused(true),
        onBlur: () => setPaused(false),
    };

    if (server.length > 0) {
        const banner = server[at];
        const picture = (
            <picture>
                {banner.imageMobile && <source media="(max-width: 640px)" srcSet={banner.imageMobile} />}
                <img src={banner.image} alt={banner.alt} />
            </picture>
        );

        return (
            <section className="mk-banner mk-banner--image" aria-roledescription={L.carousel} aria-label={L.promos} {...hold}>
                {banner.url ? <a href={banner.url}>{picture}</a> : picture}
                {dots}
            </section>
        );
    }

    const banner = fallback[at];

    return (
        <section className="mk-banner" aria-roledescription={L.carousel} aria-label={L.promos} {...hold}>
            <div>
                <small>{banner.eyebrow}</small>
                <h2>{banner.title}</h2>
                <p>{banner.text}</p>
                <Link href={catalog(banner.query)} className="mk-banner-cta">
                    {banner.cta}
                </Link>
            </div>
            <div className="mk-banner-art" aria-hidden>
                {banner.emoji}
            </div>
            {dots}
        </section>
    );
}

/** Купоны: «Взять» отмечает купон взятым — применять их пока некуда. */
function Coupons() {
    const L = lang(homeText);
    const [taken, setTaken] = useState<string[]>([]);

    return (
        <div className="mk-coupons">
            {lang(COUPONS).map((c) => {
                const done = taken.includes(c.value);

                return (
                    <div key={c.value} className="mk-coupon">
                        <span>
                            <b>{c.value}</b>
                            <small>{c.text}</small>
                        </span>
                        <button type="button" disabled={done} onClick={() => setTaken([...taken, c.value])}>
                            {done ? L.couponTaken : c.cta}
                        </button>
                    </div>
                );
            })}
        </div>
    );
}
