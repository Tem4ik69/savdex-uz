import { Head, router, usePage } from '@inertiajs/react';
import { ChevronRight, Heart, Home, LayoutGrid, MapPin, Package, Search, ShoppingCart, User, X } from 'lucide-react';
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { FlashToast } from '@/components/FlashToast';
import { SiteFooter } from '@/components/SiteFooter';
import { Link } from '@/components/ui/Link';
import { cn } from '@/lib/cn';
import { localize } from '@/lib/locale';
import { api } from '@/market/api';
import { lang } from '@/market/lang';
import { cartCount, startSession, useCart, useCategories, useFavorites, useNotice } from '@/market/store';
import { layoutText } from '@/market/text/layout';
import type { MarketCategory } from '@/market/types';
import { routes } from '@/routes';
import type { SharedProps } from '@/types';

/**
 * Раскладка маркетплейса: своя шапка с каталогом, поиском и корзиной, на
 * телефоне — нижняя панель вместо значков в шапке.
 *
 * Данные — с сервера (/market/api/…): категории, подсказки поиска,
 * корзина и избранное вошедшего покупателя (market/store.ts).
 *
 * Тексты интерфейса — по-русски и по-узбекски, в market/text/layout.ts.
 * Названия категорий и сообщения сервера приходят на языке страницы.
 */
export function MarketLayout({
    title,
    tab,
    search = '',
    children,
}: {
    title: string;
    /** Какой пункт нижней панели подсветить */
    tab?: 'home' | 'catalog' | 'cart' | 'orders';
    /** Текст в строке поиска — каталог возвращает сюда свой запрос */
    search?: string;
    children: ReactNode;
}) {
    const L = lang(layoutText);
    const { auth, marketLinks } = usePage<SharedProps>().props;
    // На своём адресе маркетплейса «/» — его главная: на основной сайт —
    // полным адресом и обычной ссылкой (другой домен, не переход Inertia)
    const site = marketLinks?.base === '' && marketLinks.site ? marketLinks.site : null;
    const userId = auth.user?.id ?? null;
    const inCart = cartCount(useCart());
    const liked = useFavorites().length;
    const notice = useNotice();
    const account = auth.user ? routes.cabinet : routes.loginBack();

    useEffect(() => startSession(userId), [userId]);

    return (
        <div className="mk">
            <Head title={title} />
            <a href="#main" className="skip-link">
                {L.skip}
            </a>

            <div className="mk-util">
                <div className="mk-in">
                    <span>
                        <MapPin size={13} aria-hidden /> {L.pickupNote}
                    </span>
                    <nav aria-label={L.utilityMenu}>
                        <Link href={routes.marketSell}>{L.becomeSeller}</Link>
                        {site ? <a href={`${site}${localize('/')}`}>savdex.uz</a> : <Link href={routes.home}>savdex.uz</Link>}
                        <Link href={routes.help}>{L.help}</Link>
                    </nav>
                </div>
            </div>

            <header className="mk-hd">
                <div className="mk-in">
                    <Link href={routes.market} className="mk-logo notranslate" translate="no" aria-label={L.logoLabel}>
                        <span>
                            Savd<b>Ex</b>
                        </span>
                        <i>Market</i>
                    </Link>
                    <CatalogMenu />
                    <SearchBox key={search} initial={search} />
                    <nav className="mk-nav" aria-label={L.buyerMenu}>
                        <Link href={`${routes.marketCatalog}?only=fav`}>
                            <Heart size={20} aria-hidden />
                            {L.favorites}
                            {liked > 0 && <span className="mk-count">{liked}</span>}
                        </Link>
                        <Link href={routes.marketOrders}>
                            <Package size={20} aria-hidden />
                            {L.orders}
                        </Link>
                        <Link href={routes.marketCart}>
                            <ShoppingCart size={20} aria-hidden />
                            {L.cart}
                            {inCart > 0 && <span className="mk-count">{inCart}</span>}
                        </Link>
                        <Link href={account}>
                            <User size={20} aria-hidden />
                            {auth.user ? L.cabinet : L.login}
                        </Link>
                    </nav>
                </div>
            </header>

            <main id="main" className="mk-main">
                {children}
            </main>

            <FlashToast />
            {notice && (
                <div key={notice.id} className={cn('mk-toast', notice.error && 'mk-toast--error')} role="status">
                    {notice.text}
                </div>
            )}
            <SiteFooter />

            <nav className="mk-tab" aria-label={L.sections}>
                <Link href={routes.market} aria-current={tab === 'home' ? 'page' : undefined}>
                    <Home size={20} aria-hidden />
                    {L.home}
                </Link>
                <Link href={routes.marketCatalog} aria-current={tab === 'catalog' ? 'page' : undefined}>
                    <LayoutGrid size={20} aria-hidden />
                    {L.catalog}
                </Link>
                <Link href={routes.marketCart} aria-current={tab === 'cart' ? 'page' : undefined}>
                    <ShoppingCart size={20} aria-hidden />
                    {L.cart}
                    {inCart > 0 && <span className="mk-count">{inCart}</span>}
                </Link>
                <Link href={routes.marketOrders} aria-current={tab === 'orders' ? 'page' : undefined}>
                    <Package size={20} aria-hidden />
                    {L.orders}
                </Link>
                <Link href={account}>
                    <User size={20} aria-hidden />
                    {auth.user ? L.cabinet : L.login}
                </Link>
            </nav>
        </div>
    );
}

interface Suggestions {
    products: { slug: string; title: string }[];
    categories: { slug: string; name: string }[];
}

/**
 * Поиск с подсказками: с двух букв сервер отдаёт до восьми товаров и
 * до четырёх категорий (опечатки он тоже понимает). Запрос уходит через
 * четверть секунды после последней буквы — не на каждое нажатие.
 * Enter — в каталог.
 */
function SearchBox({ initial }: { initial: string }) {
    const L = lang(layoutText);
    const [text, setText] = useState(initial);
    const [open, setOpen] = useState(false);
    const [found, setFound] = useState<{ for: string; data: Suggestions } | null>(null);
    const needle = text.trim();

    useEffect(() => {
        if (needle.length < 2) return;

        const controller = new AbortController();
        const timer = window.setTimeout(() => {
            api<Suggestions>(`suggest?q=${encodeURIComponent(needle)}`, { signal: controller.signal })
                .then((data) => setFound({ for: needle, data }))
                .catch(() => undefined);
        }, 250);

        return () => {
            window.clearTimeout(timer);
            controller.abort();
        };
    }, [needle]);

    function submit(event: FormEvent) {
        event.preventDefault();
        setOpen(false);
        router.get(routes.marketCatalog, needle ? { q: needle } : {});
    }

    const data = found && found.for === needle ? found.data : null;
    const empty = data !== null && data.products.length === 0 && data.categories.length === 0;

    return (
        <div
            className="mk-search"
            onBlur={(event) => {
                if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
            }}
        >
            <form role="search" onSubmit={submit}>
                <Search size={20} aria-hidden />
                <input
                    type="search"
                    name="q"
                    value={text}
                    onChange={(event) => {
                        setText(event.target.value);
                        setOpen(true);
                    }}
                    onFocus={() => setOpen(true)}
                    placeholder={L.searchPlaceholder}
                    aria-label={L.searchLabel}
                    autoComplete="off"
                />
                <button type="submit">{L.find}</button>
            </form>
            {open && needle.length >= 2 && data !== null && (
                <div className="mk-sug">
                    {empty && <p>{L.nothingFound(needle)}</p>}
                    {data.categories.map((c) => (
                        <Link key={c.slug} href={`${routes.marketCatalog}?category=${c.slug}`}>
                            <span aria-hidden>
                                <LayoutGrid size={18} />
                            </span>
                            {c.name}
                            <em>{L.category}</em>
                        </Link>
                    ))}
                    {data.products.map((p) => (
                        <Link key={p.slug} href={routes.marketProduct(p.slug)}>
                            <span aria-hidden>
                                <Search size={18} />
                            </span>
                            {p.title}
                        </Link>
                    ))}
                </div>
            )}
        </div>
    );
}

/**
 * Кнопка «Каталог»: значок-плитка (не «бургер» — тот читается как меню
 * сайта) и окно с деревом категорий с сервера. Слева — разделы, справа —
 * подразделы того, на который навели или перешли с клавиатуры: колонками
 * с группами под каждым, если в дереве есть третий уровень, иначе —
 * списком в несколько колонок. Закрывается по Escape, нажатию мимо и
 * после перехода.
 */
function CatalogMenu() {
    const L = lang(layoutText);
    const categories = useCategories();
    const [open, setOpen] = useState(false);
    const [active, setActive] = useState<string | null>(null);
    const box = useRef<HTMLDivElement>(null);
    const current: MarketCategory | undefined = categories?.find((c) => c.slug === active) ?? categories?.[0];
    const href = (slug: string) => `${routes.marketCatalog}?category=${slug}`;
    const close = () => setOpen(false);

    useEffect(() => {
        if (!open) return;

        const onKey = (event: KeyboardEvent) => event.key === 'Escape' && setOpen(false);
        const onDown = (event: PointerEvent) => {
            if (!box.current?.contains(event.target as Node)) setOpen(false);
        };

        document.addEventListener('keydown', onKey);
        document.addEventListener('pointerdown', onDown);

        return () => {
            document.removeEventListener('keydown', onKey);
            document.removeEventListener('pointerdown', onDown);
        };
    }, [open]);

    const deep = current?.children.some((child) => child.children.length > 0) ?? false;

    return (
        <div className="mk-catmenu" ref={box}>
            <button type="button" className="mk-catbtn" aria-expanded={open} aria-controls="mk-catalog-panel" onClick={() => setOpen(!open)}>
                {open ? <X size={20} aria-hidden /> : <LayoutGrid size={20} aria-hidden />} {L.catalog}
            </button>
            {open && (
                <div className="mk-catpanel" id="mk-catalog-panel">
                    {categories === null && <p className="mk-catpanel__note">{L.loadingCategories}</p>}
                    {categories !== null && categories.length === 0 && (
                        <p className="mk-catpanel__note">
                            {L.categoriesFailed}{' '}
                            <Link href={routes.marketCatalog} onClick={close}>
                                {L.openCatalog}
                            </Link>
                        </p>
                    )}
                    {current && categories && (
                        <>
                            <ul className="mk-catpanel__list">
                                {categories.map((c) => (
                                    <li key={c.slug}>
                                        <Link
                                            href={href(c.slug)}
                                            aria-current={c.slug === current.slug}
                                            onMouseEnter={() => setActive(c.slug)}
                                            onFocus={() => setActive(c.slug)}
                                            onClick={close}
                                        >
                                            <span aria-hidden>{c.emoji}</span>
                                            {c.name}
                                            <ChevronRight size={16} aria-hidden />
                                        </Link>
                                    </li>
                                ))}
                            </ul>
                            <div className="mk-catpanel__sub">
                                <h3>
                                    <span aria-hidden>{current.emoji}</span> {current.name}
                                </h3>
                                {deep ? (
                                    <div className="mk-catpanel__cols">
                                        {current.children.map((group) => (
                                            <div key={group.slug}>
                                                <h4>
                                                    <Link href={href(group.slug)} onClick={close}>
                                                        {group.name}
                                                    </Link>
                                                </h4>
                                                <ul>
                                                    {group.children.map((item) => (
                                                        <li key={item.slug}>
                                                            <Link href={href(item.slug)} onClick={close}>
                                                                {item.name}
                                                            </Link>
                                                        </li>
                                                    ))}
                                                </ul>
                                            </div>
                                        ))}
                                    </div>
                                ) : (
                                    <ul className="mk-catpanel__cols mk-catpanel__cols--flat">
                                        {current.children.map((item) => (
                                            <li key={item.slug}>
                                                <Link href={href(item.slug)} onClick={close}>
                                                    {item.name}
                                                </Link>
                                            </li>
                                        ))}
                                    </ul>
                                )}
                                <Link href={href(current.slug)} className="mk-catpanel__all" onClick={close}>
                                    {L.allInSection}
                                </Link>
                            </div>
                        </>
                    )}
                </div>
            )}
        </div>
    );
}
