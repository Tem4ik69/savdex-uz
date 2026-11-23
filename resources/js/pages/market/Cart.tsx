import { usePage } from '@inertiajs/react';
import { useState } from 'react';
import { MarketPhoto } from '@/components/market/MarketPhoto';
import { Link } from '@/components/ui/Link';
import { cn } from '@/lib/cn';
import { MarketLayout } from '@/layouts/MarketLayout';
import { sum } from '@/market/format';
import { lang } from '@/market/lang';
import { setCartQuantity, useCart } from '@/market/store';
import { cartText } from '@/market/text/cart';
import { commonText } from '@/market/text/common';
import type { CartLine } from '@/market/types';
import { routes } from '@/routes';
import type { SharedProps } from '@/types';

/** Подпись варианта: «Цвет: Чёрный · Память: 256 ГБ». */
export const optionsText = (options: Record<string, string>): string =>
    Object.entries(options)
        .map(([name, value]) => `${name}: ${value}`)
        .join(' · ');

/**
 * Корзина — на сервере и только у вошедшего (/market/api/cart): цена и
 * остаток всегда серверные, больше остатка не положить. Строки разбиты
 * по продавцам — в заказе у каждого будет своя часть. Товар, которого
 * уже нет в наличии, остаётся в списке с пометкой, но в итог не входит.
 */
export default function MarketCart() {
    const L = lang(cartText);
    const C = lang(commonText);
    const { auth } = usePage<SharedProps>().props;
    const cart = useCart();

    const shell = (children: React.ReactNode, count?: number) => (
        <MarketLayout title={L.pageTitle} tab="cart">
            <div className="mk-in">
                <nav className="mk-bc" aria-label={L.breadcrumbs}>
                    <Link href={routes.market}>{L.home}</Link>› {L.title}
                </nav>
                <div className="mk-title">
                    <h1>{L.title}</h1>
                    {count ? <span>{L.pieces(count)}</span> : null}
                </div>
                {children}
            </div>
        </MarketLayout>
    );

    if (!auth.user) {
        return shell(
            <div className="mk-gate">
                <h2>{L.gateTitle}</h2>
                <p>{L.gateText}</p>
                <Link href={routes.loginBack(routes.marketCart)} className="mk-btn">
                    {L.loginOrRegister}
                </Link>
            </div>,
        );
    }

    if (cart === null) {
        return shell(
            <div className="mk-lines" aria-busy>
                {[0, 1].map((i) => (
                    <div key={i} className="mk-line">
                        <div className="mk-skel-block" style={{ aspectRatio: '1' }} />
                        <div style={{ display: 'grid', gap: 8 }}>
                            <div className="mk-skel-block" style={{ height: 18, width: '70%' }} />
                            <div className="mk-skel-block" style={{ height: 14, width: '40%' }} />
                        </div>
                    </div>
                ))}
            </div>,
        );
    }

    if (cart.lines === 0) {
        return shell(
            <div className="mk-empty">
                <span aria-hidden>🛒</span>
                <h2>{L.emptyTitle}</h2>
                <p>{L.emptyText}</p>
                <Link href={routes.marketCatalog} className="mk-btn">
                    {L.toCatalog}
                </Link>
            </div>,
        );
    }

    const lines = cart.parts.flatMap((part) => part.items);
    const full = lines.reduce((s, l) => s + (l.oldPrice ?? l.price) * Math.min(l.quantity, l.available), 0);
    const unavailable = lines.filter((l) => !l.buyable).length;

    return shell(
        <div className="mk-cart">
            <div className="mk-lines">
                {cart.parts.map((part) => (
                    <div key={part.seller.slug}>
                        <div className="mk-part">
                            <Link href={routes.marketShop(part.seller.slug)}>{part.seller.name}</Link>
                            <span>{sum(part.total)} {C.currency}</span>
                        </div>
                        {part.items.map((line) => (
                            <Line key={line.variantId} line={line} />
                        ))}
                    </div>
                ))}
            </div>

            <aside className="mk-sum" aria-label={L.summary}>
                <h2>{L.yourOrder}</h2>
                <dl>
                    <div>
                        <dt>{L.goods(cart.count)}</dt>
                        <dd>{sum(full)} {C.currency}</dd>
                    </div>
                    {full > cart.total && (
                        <div className="is-save">
                            <dt>{L.discount}</dt>
                            <dd>−{sum(full - cart.total)} {C.currency}</dd>
                        </div>
                    )}
                    <div>
                        <dt>{L.pickupBts}</dt>
                        <dd>0 {C.currency}</dd>
                    </div>
                    <div className="is-total">
                        <dt>{L.total}</dt>
                        <dd>{sum(cart.total)} {C.currency}</dd>
                    </div>
                </dl>
                {cart.count > 0 ? (
                    <Link href={routes.marketCheckout} className="mk-btn mk-btn--block">
                        {L.toCheckout}
                    </Link>
                ) : (
                    <button type="button" className="mk-btn mk-btn--block" disabled>
                        {L.toCheckout}
                    </button>
                )}
                {unavailable > 0 && <p className="mk-note">{L.unavailableNote}</p>}
            </aside>
        </div>,
        cart.count,
    );
}

function Line({ line }: { line: CartLine }) {
    const L = lang(cartText);
    const C = lang(commonText);
    const [busy, setBusy] = useState(false);
    const variant = optionsText(line.options);

    async function change(quantity: number) {
        setBusy(true);
        await setCartQuantity(line.variantId, quantity);
        setBusy(false);
    }

    return (
        <div className={cn('mk-line', !line.buyable && 'mk-line--off')} aria-busy={busy}>
            <div className="mk-line__ph">
                <MarketPhoto image={line.image} id={line.productId} />
            </div>
            <div>
                <h3>
                    <Link href={routes.marketProduct(line.slug)}>{line.title}</Link>
                </h3>
                {variant && <small>{variant}</small>}
                {!line.buyable && <div className="mk-line__warn">{L.outOfStock}</div>}
                {line.buyable && line.quantity > line.available && <div className="mk-line__warn">{L.onlyLeft(line.available)}</div>}
                <div className="mk-line__ctl">
                    <div className="mk-qty">
                        <button type="button" aria-label={L.less} disabled={busy || line.quantity <= 1} onClick={() => void change(line.quantity - 1)}>
                            −
                        </button>
                        <output aria-label={L.quantity}>{line.quantity}</output>
                        <button type="button" aria-label={L.more} disabled={busy || !line.buyable || line.quantity >= line.available} onClick={() => void change(line.quantity + 1)}>
                            +
                        </button>
                    </div>
                    <button type="button" className="mk-line__del" disabled={busy} onClick={() => void change(0)}>
                        {L.remove}
                    </button>
                </div>
            </div>
            <div className="mk-line__sum">
                {sum(line.total)} {C.currency}
                {line.oldPrice && line.buyable && <s>{sum(line.oldPrice * Math.min(line.quantity, line.available))} {C.currency}</s>}
            </div>
        </div>
    );
}
