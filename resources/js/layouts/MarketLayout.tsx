import { Head, router, usePage } from '@inertiajs/react';
import { Heart, Home, LayoutGrid, MapPin, Menu, Package, Search, ShoppingCart, User } from 'lucide-react';
import { useState, type FormEvent, type ReactNode } from 'react';
import { FlashToast } from '@/components/FlashToast';
import { SiteFooter } from '@/components/SiteFooter';
import { Link } from '@/components/ui/Link';
import { PRODUCTS } from '@/market/demo';
import { sum } from '@/market/format';
import { cartCount, useCart, useFavorites } from '@/market/store';
import { routes } from '@/routes';
import type { SharedProps } from '@/types';

/**
 * Раскладка маркетплейса: своя шапка с поиском и корзиной, на телефоне —
 * нижняя панель вместо значков в шапке.
 *
 * Тексты пока по-русски прямо в разметке: это демо оформления (ТЗ
 * 18.11), формулировки ещё меняются. Устоятся — переедут в словари
 * на пять языков, как у остальной площадки.
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
    const { auth } = usePage<SharedProps>().props;
    const inCart = cartCount(useCart());
    const liked = Object.keys(useFavorites()).length;
    const account = auth.user ? routes.cabinet : routes.loginBack();

    return (
        <div className="mk">
            <Head title={title} />
            <a href="#main" className="skip-link">
                Перейти к содержимому
            </a>

            <div className="mk-util">
                <div className="mk-in">
                    <span>
                        <MapPin size={13} aria-hidden /> Ташкент · выдача в пунктах BTS
                        <b className="mk-demo">· Демо: товары и цены для примера</b>
                    </span>
                    <nav aria-label="Служебное меню">
                        <Link href={routes.marketSell}>Стать продавцом</Link>
                        <Link href={routes.home}>savdex.uz</Link>
                        <Link href={routes.help}>Помощь</Link>
                    </nav>
                </div>
            </div>

            <header className="mk-hd">
                <div className="mk-in">
                    <Link href={routes.market} className="mk-logo notranslate" translate="no" aria-label="SavdEx Market — на главную">
                        <span>
                            Savd<b>Ex</b>
                        </span>
                        <i>Market</i>
                    </Link>
                    <Link href={routes.marketCatalog} className="mk-catbtn">
                        <Menu size={20} aria-hidden /> Каталог
                    </Link>
                    <SearchBox initial={search} />
                    <nav className="mk-nav" aria-label="Покупателю">
                        <Link href={`${routes.marketCatalog}?only=fav`}>
                            <Heart size={20} aria-hidden />
                            Избранное
                            {liked > 0 && <span className="mk-count">{liked}</span>}
                        </Link>
                        <Link href={routes.marketOrders}>
                            <Package size={20} aria-hidden />
                            Заказы
                        </Link>
                        <Link href={routes.marketCart}>
                            <ShoppingCart size={20} aria-hidden />
                            Корзина
                            {inCart > 0 && <span className="mk-count">{inCart}</span>}
                        </Link>
                        <Link href={account}>
                            <User size={20} aria-hidden />
                            {auth.user ? 'Кабинет' : 'Войти'}
                        </Link>
                    </nav>
                </div>
            </header>

            <main id="main" className="mk-main">
                {children}
            </main>

            <FlashToast />
            <SiteFooter />

            <nav className="mk-tab" aria-label="Разделы маркетплейса">
                <Link href={routes.market} aria-current={tab === 'home' ? 'page' : undefined}>
                    <Home size={20} aria-hidden />
                    Главная
                </Link>
                <Link href={routes.marketCatalog} aria-current={tab === 'catalog' ? 'page' : undefined}>
                    <LayoutGrid size={20} aria-hidden />
                    Каталог
                </Link>
                <Link href={routes.marketCart} aria-current={tab === 'cart' ? 'page' : undefined}>
                    <ShoppingCart size={20} aria-hidden />
                    Корзина
                    {inCart > 0 && <span className="mk-count">{inCart}</span>}
                </Link>
                <Link href={routes.marketOrders} aria-current={tab === 'orders' ? 'page' : undefined}>
                    <Package size={20} aria-hidden />
                    Заказы
                </Link>
                <Link href={account}>
                    <User size={20} aria-hidden />
                    {auth.user ? 'Кабинет' : 'Войти'}
                </Link>
            </nav>
        </div>
    );
}

/** Поиск с подсказками: с двух букв — до пяти товаров, Enter — в каталог. */
function SearchBox({ initial }: { initial: string }) {
    const [text, setText] = useState(initial);
    const [open, setOpen] = useState(false);
    const needle = text.trim().toLowerCase();
    const found = needle.length >= 2 ? PRODUCTS.filter((p) => p.title.toLowerCase().includes(needle)).slice(0, 5) : [];

    function submit(event: FormEvent) {
        event.preventDefault();
        setOpen(false);
        router.get(routes.marketCatalog, needle ? { q: text.trim() } : {});
    }

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
                    placeholder="Искать товары и продавцов"
                    aria-label="Поиск по маркетплейсу"
                    autoComplete="off"
                />
                <button type="submit">Найти</button>
            </form>
            {open && needle.length >= 2 && (
                <div className="mk-sug">
                    {found.length === 0 ? (
                        <p>Ничего не нашли по «{text.trim()}». Попробуйте короче или другое слово.</p>
                    ) : (
                        found.map((p) => (
                            <Link key={p.id} href={routes.marketProduct(p.slug)}>
                                <span aria-hidden>{p.emoji}</span>
                                {p.title}
                                <em>{sum(p.price)} сум</em>
                            </Link>
                        ))
                    )}
                </div>
            )}
        </div>
    );
}
