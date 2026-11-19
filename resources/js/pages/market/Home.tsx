import { ChevronLeft, ChevronRight } from 'lucide-react';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { MarketCard } from '@/components/market/MarketCard';
import { Link } from '@/components/ui/Link';
import { MarketLayout } from '@/layouts/MarketLayout';
import { BANNERS, CATEGORIES, COUPONS, discount, PRODUCTS, STORIES, type MarketProduct } from '@/market/demo';
import { sum } from '@/market/format';
import { routes } from '@/routes';

const catalog = (query: string) => (query ? `${routes.marketCatalog}?${query}` : routes.marketCatalog);

/**
 * Главная маркетплейса: подборки-кружки, «Скидки дня» с баннером,
 * купоны, категории, три подборки — «Хиты», «Распродажа», «Новинки» —
 * и лента «Все товары», которая догружается при прокрутке.
 * Места под баннеры из админки — слайдер и (позже) полосы между
 * подборками; «Стать продавцом» — в конце страницы.
 */
export default function MarketHome() {
    const hits = PRODUCTS.filter((p) => p.badge === 'hit');
    const sale = PRODUCTS.filter((p) => p.oldPrice).sort((a, b) => discount(b) - discount(a));
    // Новинок с меткой может быть меньше ряда — добираем самыми свежими из остальных
    const fresh = [...PRODUCTS.filter((p) => p.badge === 'new'), ...PRODUCTS.filter((p) => p.badge !== 'new').sort((a, b) => b.id - a.id)];
    const deals = sale.slice(0, 3);

    return (
        <MarketLayout title="SavdEx Market" tab="home">
            <div className="mk-in">
                <Row className="mk-stories" label="Подборки">
                    {STORIES.map((story) => (
                        <Link key={story.label} href={catalog(story.query)} className="mk-story">
                            <span aria-hidden>{story.emoji}</span>
                            {story.label}
                        </Link>
                    ))}
                </Row>

                <div className="mk-deal">
                    <section className="mk-flash" aria-label="Скидки дня">
                        <h2>
                            Скидки дня <Countdown />
                        </h2>
                        <div className="mk-flash-items">
                            {deals.map((p) => (
                                <Link key={p.id} href={routes.marketProduct(p.slug)} aria-label={p.title}>
                                    <span aria-hidden>{p.emoji}</span>
                                    {sum(p.price)}
                                    <em>−{discount(p)}%</em>
                                </Link>
                            ))}
                        </div>
                    </section>
                    <Banners />
                </div>

                <Coupons />

                <Row className="mk-cats" label="Категории">
                    {CATEGORIES.slice(0, 11).map((c) => (
                        <Link key={c.slug} href={catalog(`category=${c.slug}`)} className="mk-cat">
                            <span aria-hidden>{c.emoji}</span>
                            {c.name}
                        </Link>
                    ))}
                </Row>

                <Shelf title="Хиты продаж" query="only=hit" products={hits.slice(0, 5)} />
                <Shelf title="Распродажа" query="only=sale" products={sale.slice(0, 5)} sale />
                <Shelf title="Новинки" query="only=new" products={fresh.slice(0, 5)} />

                <Feed />

                <aside className="mk-strip">
                    <span>
                        Продавайте на SavdEx Market
                        <small>Привезите товар на склад — хранение, выдача и оплата на нас</small>
                    </span>
                    <Link href={routes.marketSell}>Стать продавцом</Link>
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
                <button type="button" className="mk-row__arrow mk-row__arrow--back" aria-label={`${label}: назад`} onClick={() => scroll(-1)}>
                    <ChevronLeft size={20} aria-hidden />
                </button>
            )}
            <nav ref={track} className={className} aria-label={label}>
                {children}
            </nav>
            {can.forward && (
                <button type="button" className="mk-row__arrow mk-row__arrow--forward" aria-label={`${label}: вперёд`} onClick={() => scroll(1)}>
                    <ChevronRight size={20} aria-hidden />
                </button>
            )}
        </div>
    );
}

function Shelf({ title, query, products, sale = false }: { title: string; query: string; products: MarketProduct[]; sale?: boolean }) {
    return (
        <section>
            <div className={sale ? 'mk-sh mk-sh--sale' : 'mk-sh'}>
                <h2>{title}</h2>
                <Link href={catalog(query)}>Смотреть все →</Link>
            </div>
            <div className="mk-grid mk-shelf">
                {products.map((p) => (
                    <MarketCard key={p.id} product={p} />
                ))}
            </div>
        </section>
    );
}

/** Сколько карточек приходит за один раз: два ряда на компьютере */
const FEED_STEP = 10;

/**
 * Лента «Все товары» в конце главной: догружается сама, когда до её
 * низа докручивают, — и так до последнего товара. Пока сервера нет,
 * следующая порция берётся из демо-каталога с короткой паузой, чтобы
 * было видно состояние загрузки; с сервером здесь будет запрос
 * следующей страницы. Без наблюдателя (старый браузер) — кнопка
 * «Показать ещё».
 */
function Feed() {
    const all = [...PRODUCTS].sort((a, b) => b.sold - a.sold);
    const [shown, setShown] = useState(FEED_STEP);
    const [loading, setLoading] = useState(false);
    const sentinel = useRef<HTMLDivElement>(null);
    const done = shown >= all.length;

    const more = () => {
        setLoading(true);
        window.setTimeout(() => {
            setShown((count) => Math.min(count + FEED_STEP, all.length));
            setLoading(false);
        }, 500);
    };

    useEffect(() => {
        const target = sentinel.current;

        if (!target || done || loading || typeof IntersectionObserver === 'undefined') return;

        // Запас в 300 px: порция успевает приехать до того, как докрутят до края
        const observer = new IntersectionObserver((entries) => entries[0]?.isIntersecting && more(), { rootMargin: '300px' });

        observer.observe(target);

        return () => observer.disconnect();
    }, [done, loading, shown]);

    return (
        <section aria-busy={loading}>
            <div className="mk-sh">
                <h2>Все товары</h2>
                <Link href={routes.marketCatalog}>В каталог →</Link>
            </div>
            <div className="mk-grid">
                {all.slice(0, shown).map((p) => (
                    <MarketCard key={p.id} product={p} />
                ))}
                {loading &&
                    Array.from({ length: Math.min(5, all.length - shown) }, (_, i) => (
                        <div key={i} className="mk-skel" aria-hidden>
                            <i />
                            <i />
                            <i />
                            <i />
                        </div>
                    ))}
            </div>
            {done ? (
                <p className="mk-feed-end">Вы посмотрели все товары</p>
            ) : (
                <div ref={sentinel} className="mk-feed-more">
                    {!loading && (
                        <button type="button" className="mk-btn mk-btn--ghost" onClick={more}>
                            Показать ещё
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
        <span className="mk-timer" aria-label="До конца акции">
            <i>{parts[0]}</i>:<i>{parts[1]}</i>:<i>{parts[2]}</i>
        </span>
    );
}

/** Слайдер баннеров: листается сам раз в шесть секунд, точки — вручную. */
function Banners() {
    const [index, setIndex] = useState(0);
    const [paused, setPaused] = useState(false);

    useEffect(() => {
        if (paused || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

        const timer = window.setInterval(() => setIndex((i) => (i + 1) % BANNERS.length), 6000);

        return () => window.clearInterval(timer);
    }, [paused]);

    const banner = BANNERS[index];

    return (
        <section
            className="mk-banner"
            aria-roledescription="карусель"
            aria-label="Акции"
            onMouseEnter={() => setPaused(true)}
            onMouseLeave={() => setPaused(false)}
            onFocus={() => setPaused(true)}
            onBlur={() => setPaused(false)}
        >
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
            <div className="mk-dots">
                {BANNERS.map((b, i) => (
                    <button
                        key={b.title}
                        type="button"
                        aria-current={i === index}
                        aria-label={`Баннер ${i + 1} из ${BANNERS.length}`}
                        onClick={() => setIndex(i)}
                    />
                ))}
            </div>
        </section>
    );
}

/** Купоны: «Взять» отмечает купон взятым — применять их пока некуда. */
function Coupons() {
    const [taken, setTaken] = useState<string[]>([]);

    return (
        <div className="mk-coupons">
            {COUPONS.map((c) => {
                const done = taken.includes(c.value);

                return (
                    <div key={c.value} className="mk-coupon">
                        <span>
                            <b>{c.value}</b>
                            <small>{c.text}</small>
                        </span>
                        <button type="button" disabled={done} onClick={() => setTaken([...taken, c.value])}>
                            {done ? 'Взят' : c.cta}
                        </button>
                    </div>
                );
            })}
        </div>
    );
}
