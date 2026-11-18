import { useEffect, useState } from 'react';
import { MarketCard } from '@/components/market/MarketCard';
import { Link } from '@/components/ui/Link';
import { MarketLayout } from '@/layouts/MarketLayout';
import { BANNERS, CATEGORIES, COUPONS, discount, PRODUCTS, STORIES, type MarketProduct } from '@/market/demo';
import { sum } from '@/market/format';
import { routes } from '@/routes';

const catalog = (query: string) => (query ? `${routes.marketCatalog}?${query}` : routes.marketCatalog);

/**
 * Главная маркетплейса: подборки-кружки, «Скидки дня» с баннером,
 * купоны, категории и три подборки — «Хиты», «Распродажа», «Новинки».
 * Места под баннеры из админки — слайдер и (позже) полосы между
 * подборками; «Стать продавцом» — в конце страницы.
 */
export default function MarketHome() {
    const hits = PRODUCTS.filter((p) => p.badge === 'hit');
    const sale = PRODUCTS.filter((p) => p.oldPrice).sort((a, b) => discount(b) - discount(a));
    const fresh = PRODUCTS.filter((p) => p.badge === 'new');
    const deals = sale.slice(0, 3);

    return (
        <MarketLayout title="SavdEx Market" tab="home">
            <div className="mk-in">
                <nav className="mk-stories" aria-label="Подборки">
                    {STORIES.map((story) => (
                        <Link key={story.label} href={catalog(story.query)} className="mk-story">
                            <span aria-hidden>{story.emoji}</span>
                            {story.label}
                        </Link>
                    ))}
                </nav>

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

                <nav className="mk-cats" aria-label="Категории">
                    {CATEGORIES.slice(0, 11).map((c) => (
                        <Link key={c.slug} href={catalog(`category=${c.slug}`)} className="mk-cat">
                            <span aria-hidden>{c.emoji}</span>
                            {c.name}
                        </Link>
                    ))}
                </nav>

                <Shelf title="Хиты продаж" query="only=hit" products={hits.slice(0, 5)} kind="hit" />
                <Shelf title="Распродажа" query="only=sale" products={sale.slice(0, 5)} kind="sale" />
                <Shelf title="Новинки" query="only=new" products={fresh.slice(0, 4)} kind="fresh" />

                <aside className="mk-strip">
                    <span>
                        Продавайте на SavdEx Market
                        <small>Привезите товар на склад — хранение, выдача и оплата на нас</small>
                    </span>
                    <Link href={routes.cabinet}>Стать продавцом</Link>
                </aside>
            </div>
        </MarketLayout>
    );
}

function Shelf({
    title,
    query,
    products,
    kind,
}: {
    title: string;
    query: string;
    products: MarketProduct[];
    kind: 'hit' | 'sale' | 'fresh';
}) {
    return (
        <section>
            <div className={kind === 'sale' ? 'mk-sh mk-sh--sale' : 'mk-sh'}>
                <h2>{title}</h2>
                <Link href={catalog(query)}>Смотреть все →</Link>
            </div>
            <div className={kind === 'fresh' ? 'mk-grid mk-grid--4 mk-shelf' : 'mk-grid mk-shelf'}>
                {products.map((p) => (
                    <MarketCard key={p.id} product={p} kind={kind} />
                ))}
            </div>
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
