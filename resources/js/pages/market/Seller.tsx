import { usePage } from '@inertiajs/react';
import { Plus, Trash2, X } from 'lucide-react';
import { useState, type ChangeEvent, type FormEvent } from 'react';
import { MarketPhoto } from '@/components/market/MarketPhoto';
import { StatusPill } from '@/components/market/OrderView';
import { Link } from '@/components/ui/Link';
import { cn } from '@/lib/cn';
import { MarketLayout } from '@/layouts/MarketLayout';
import { api, ApiError, useApi } from '@/market/api';
import { dateText, sum } from '@/market/format';
import { when } from '@/market/orders';
import { lang } from '@/market/lang';
import { notify, useCategories } from '@/market/store';
import { sellerText } from '@/market/text/seller';
import type { MarketCategory, MyProduct, MyProductDetail, MyVariant, ProductStatus, SellerBalance, SellerOrder, Supply, Warehouse } from '@/market/types';
import { routes } from '@/routes';
import type { SharedProps } from '@/types';

const TABS = ['products', 'stock', 'supplies', 'orders', 'payouts'] as const;

// Подпись статуса — из text/seller.ts (status), здесь только цвет
const STATUS: Record<ProductStatus, string> = {
    draft: 'mk-pill--off',
    pending: 'mk-pill--warn',
    active: 'mk-pill--ok',
    rejected: 'mk-pill--warn',
    hidden: 'mk-pill--off',
    blocked: 'mk-pill--warn',
};

/** «ГГГГ-ММ-ДД» без времени: полдень по Ташкенту, чтобы день не сдвинулся. */
const day = (iso: string) => dateText(new Date(`${iso}T12:00:00+05:00`), false);

/**
 * Кабинет продавца. «Мои товары» и «Остатки» — с сервера
 * (/market/api/me/products): добавить, изменить, загрузить фото,
 * отправить на продажу, снять. Заказы и начисления — тоже с сервера
 * (me/orders, me/balance). Поставки сервер ещё не ведёт (склад BTS —
 * следующий этап) — там образец с пометкой. Открыт только подтверждённому продавцу: остальным сервер
 * отвечает «нельзя», и страница ведёт к заявке.
 */
export default function MarketSeller({ tab }: { tab: string }) {
    const L = lang(sellerText);
    const { auth } = usePage<SharedProps>().props;
    const list = useApi<{ products: MyProduct[]; needsReview: boolean }>(auth.user ? 'me/products' : null);

    if (!auth.user || list.status === 403 || list.status === 401) {
        return (
            <MarketLayout title={L.pageTitle}>
                <div className="mk-in" style={{ paddingTop: 24 }}>
                    <div className="mk-gate">
                        <h2>{L.gate.title}</h2>
                        <p>{L.gate.text}</p>
                        <Link href={auth.user ? routes.marketSell : routes.loginBack(routes.marketSeller())} className="mk-btn">
                            {auth.user ? L.gate.becomeSeller : L.gate.login}
                        </Link>
                    </div>
                </div>
            </MarketLayout>
        );
    }

    return (
        <MarketLayout title={L.pageTitle}>
            <div className="mk-in">
                <nav className="mk-bc" aria-label={L.breadcrumbs}>
                    <Link href={routes.market}>{L.home}</Link>› {L.cabinet}
                </nav>
                <div className="mk-title">
                    <h1>{auth.company?.name ?? L.cabinet}</h1>
                    <span className="mk-pill mk-pill--ok">{L.verified}</span>
                </div>
                <nav className="mk-tabs" aria-label={L.tabsLabel}>
                    {TABS.map((key) => (
                        <Link key={key} href={routes.marketSeller(key)} aria-current={tab === key ? 'page' : undefined} preserveScroll>
                            {L.tabs[key]}
                        </Link>
                    ))}
                </nav>

                {(tab === 'products' || tab === 'stock' || tab === 'supplies') && list.loading && <div className="mk-skel-block" style={{ height: 240 }} aria-busy />}
                {(tab === 'products' || tab === 'stock' || tab === 'supplies') && list.error && (
                    <div className="mk-failed">
                        <h2>{L.products.failed}</h2>
                        <p>{list.error}</p>
                        <button type="button" className="mk-btn" onClick={list.reload}>
                            {L.retry}
                        </button>
                    </div>
                )}
                {tab === 'products' && list.data && <Products products={list.data.products} needsReview={list.data.needsReview} reload={list.reload} />}
                {tab === 'stock' && list.data && <Stock products={list.data.products} />}
                {tab === 'supplies' && list.data && <Supplies products={list.data.products} />}
                {tab === 'orders' && <Orders />}
                {tab === 'payouts' && <Payouts />}
            </div>
        </MarketLayout>
    );
}

function Products({ products, needsReview, reload }: { products: MyProduct[]; needsReview: boolean; reload: () => void }) {
    const L = lang(sellerText);
    // null — список; 'new' — новый товар; номер — правка
    const [editing, setEditing] = useState<number | 'new' | null>(null);

    if (editing !== null) {
        return (
            <ProductForm
                key={editing}
                id={editing === 'new' ? null : editing}
                needsReview={needsReview}
                onClose={() => {
                    setEditing(null);
                    reload();
                }}
            />
        );
    }

    return (
        <>
            <div className="mk-bar">
                <h2>{L.products.title}</h2>
                <button type="button" className="mk-btn" onClick={() => setEditing('new')}>
                    <Plus size={18} aria-hidden /> {L.products.add}
                </button>
            </div>

            {products.length === 0 ? (
                <div className="mk-empty">
                    <span aria-hidden>📦</span>
                    <h2>{L.products.emptyTitle}</h2>
                    <p>{L.products.emptyText}</p>
                    <button type="button" className="mk-btn" onClick={() => setEditing('new')}>
                        {L.products.add}
                    </button>
                </div>
            ) : (
                <div className="mk-table-wrap">
                    <table className="mk-table">
                        <thead>
                            <tr>
                                <th>{L.products.colProduct}</th>
                                <th className="is-num">{L.products.colPrice}</th>
                                <th className="is-num">{L.products.colStock}</th>
                                <th className="is-num">{L.products.colSold}</th>
                                <th>{L.products.colStatus}</th>
                                <th />
                            </tr>
                        </thead>
                        <tbody>
                            {products.map((p) => (
                                <tr key={p.id}>
                                    <td>
                                        <div className="mk-table__item">
                                            <span>
                                                <MarketPhoto image={p.image} id={p.id} />
                                            </span>
                                            {p.title}
                                        </div>
                                        {p.rejectReason && (p.status === 'rejected' || p.status === 'blocked') && <div className="mk-line__warn">{L.products.reason(p.rejectReason)}</div>}
                                    </td>
                                    <td className="is-num">{p.price ? L.money(sum(p.price)) : '—'}</td>
                                    <td className={cn('is-num', p.stock === 0 && 'mk-low')}>{p.stock}</td>
                                    <td className="is-num">{sum(p.sold)}</td>
                                    <td>
                                        <span className={cn('mk-pill', STATUS[p.status])}>{L.status[p.status]}</span>
                                    </td>
                                    <td>
                                        <button type="button" onClick={() => setEditing(p.id)}>
                                            {L.products.edit}
                                        </button>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
            <p className="mk-hint">
                {needsReview ? L.products.hintReview : L.products.hintFree}
                {L.products.hintStock}
            </p>
        </>
    );
}

/** Листья дерева категорий: товар кладут в самую точную, без подразделов. */
function leaves(tree: MarketCategory[]): { root: string; items: { slug: string; name: string }[] }[] {
    const collect = (node: MarketCategory, prefix: string): { slug: string; name: string }[] =>
        node.children.length === 0 ? [{ slug: node.slug, name: prefix + node.name }] : node.children.flatMap((child) => collect(child, prefix ? `${prefix}${node.name} › ` : ''));

    return tree.map((root) => ({
        root: root.name,
        items: root.children.length === 0 ? [{ slug: root.slug, name: root.name }] : root.children.flatMap((child) => collect(child, '')),
    }));
}

interface Row {
    id?: number;
    options: Record<string, string>;
    /** Значение единственной характеристики выбора — «Чёрный» */
    value: string;
    sku: string;
    price: string;
    oldPrice: string;
}

const digits = (text: string): number | null => {
    const clean = text.replace(/\D/g, '');

    return clean ? Number(clean) : null;
};

const toRow = (variant: MyVariant, dimension: string): Row => ({
    id: variant.id,
    options: variant.options,
    value: String(variant.options[dimension] ?? ''),
    sku: variant.sku ?? '',
    price: variant.price ? String(variant.price) : '',
    oldPrice: variant.oldPrice ? String(variant.oldPrice) : '',
});

/**
 * Форма товара. Новый товар сохраняется черновиком — после этого можно
 * загрузить фото и отправить на продажу. Варианты: либо один (без
 * выбора), либо несколько по одной характеристике («Цвет»: чёрный,
 * белый). Если у товара уже несколько характеристик выбора (цвет и
 * память), их состав здесь не меняется — правятся только цена и артикул.
 */
function ProductForm({ id, needsReview, onClose }: { id: number | null; needsReview: boolean; onClose: () => void }) {
    const L = lang(sellerText);
    const loaded = useApi<{ product: MyProductDetail }>(id === null ? null : `me/products/${id}`);
    const [saved, setSaved] = useState<MyProductDetail | null>(null);
    const product = saved ?? loaded.data?.product ?? null;

    if (id !== null && !product) {
        return loaded.error ? (
            <div className="mk-failed">
                <h2>{L.form.failed}</h2>
                <p>{loaded.error}</p>
                <button type="button" className="mk-btn" onClick={onClose}>
                    {L.form.backToList}
                </button>
            </div>
        ) : (
            <div className="mk-skel-block" style={{ height: 420 }} aria-busy />
        );
    }

    // key: после первого сохранения форма пересобирается уже с номером товара и его вариантов
    return <ProductFields key={product ? `${product.id}-${product.variants.map((v) => v.id).join(',')}` : 'new'} product={product} needsReview={needsReview} onSaved={setSaved} onClose={onClose} />;
}

function ProductFields({
    product,
    needsReview,
    onSaved,
    onClose,
}: {
    product: MyProductDetail | null;
    needsReview: boolean;
    onSaved: (product: MyProductDetail) => void;
    onClose: () => void;
}) {
    const L = lang(sellerText);
    const categories = useCategories();
    const keys = [...new Set((product?.variants ?? []).flatMap((v) => Object.keys(v.options)))];
    // Несколько характеристик выбора — состав вариантов здесь не трогаем
    const locked = keys.length > 1;
    const [dimension, setDimension] = useState(keys[0] ?? '');
    const [rows, setRows] = useState<Row[]>(() =>
        product && product.variants.length > 0 ? product.variants.map((v) => toRow(v, keys[0] ?? '')) : [{ options: {}, value: '', sku: '', price: '', oldPrice: '' }],
    );
    const [errors, setErrors] = useState<Record<string, string[]>>({});
    const [busy, setBusy] = useState(false);
    const status = product?.status ?? 'draft';
    const several = rows.length > 1 || dimension.trim() !== '';

    const patch = (index: number, change: Partial<Row>) => setRows(rows.map((row, i) => (i === index ? { ...row, ...change } : row)));

    function body(form: FormData): Record<string, unknown> {
        const text = (name: string) => String(form.get(name) ?? '').trim();
        const number = (name: string) => digits(text(name));

        return {
            title: text('title'),
            description: text('description'),
            category: text('category'),
            locale: product?.locale ?? 'ru',
            ikpu: text('ikpu') || null,
            barcode: text('barcode') || null,
            weight_g: number('weight_g'),
            length_mm: number('length_mm'),
            width_mm: number('width_mm'),
            height_mm: number('height_mm'),
            values: product?.values ?? {},
            variants: rows.map((row) => ({
                ...(row.id ? { id: row.id } : {}),
                options: locked ? row.options : several && dimension.trim() ? { [dimension.trim()]: row.value.trim() } : {},
                sku: row.sku.trim() || null,
                price: digits(row.price),
                oldPrice: digits(row.oldPrice),
                active: true,
            })),
        };
    }

    async function send(path: string, payload?: Record<string, unknown> | FormData): Promise<Record<string, unknown> | null> {
        setBusy(true);
        setErrors({});

        try {
            const data = await api<Record<string, unknown>>(path, payload ? { body: payload } : { post: true });

            if (typeof data.message === 'string') notify(data.message);

            return data;
        } catch (failure) {
            if (failure instanceof ApiError) {
                setErrors(failure.errors);
                notify(failure.message, true);
            }

            return null;
        } finally {
            setBusy(false);
        }
    }

    async function save(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();

        const data = await send(product ? `me/products/${product.id}` : 'me/products/create', body(new FormData(event.currentTarget)));

        if (data?.product) onSaved(data.product as MyProductDetail);
    }

    async function publish() {
        if (!product) return;

        const data = await send(`me/products/${product.id}/submit`);

        if (data) onClose();
    }

    async function hide() {
        if (!product) return;

        const data = await send(`me/products/${product.id}/hide`);

        if (data) onClose();
    }

    async function upload(event: ChangeEvent<HTMLInputElement>) {
        const file = event.target.files?.[0];

        event.target.value = '';

        if (!file || !product) return;

        const form = new FormData();

        form.append('file', file);

        const data = await send(`me/products/${product.id}/images`, form);

        if (data?.product) onSaved(data.product as MyProductDetail);
    }

    async function removeImage(imageId: number) {
        if (!product) return;

        const data = await send(`me/products/${product.id}/images/${imageId}/delete`);

        if (data?.product) onSaved(data.product as MyProductDetail);
    }

    const fail = (name: string) => errors[name]?.[0] && <small className="is-error">{errors[name][0]}</small>;
    const groups = leaves(categories ?? []);

    return (
        <section className="mk-panel" style={{ marginTop: 0 }} aria-busy={busy}>
            <div className="mk-bar">
                <h2>
                    {product ? L.form.product : L.form.newProduct} {product && <span className={cn('mk-pill', STATUS[status])}>{L.status[status]}</span>}
                </h2>
                <button type="button" className="mk-btn mk-btn--ghost" onClick={onClose}>
                    <X size={16} aria-hidden /> {L.form.toList}
                </button>
            </div>
            {/* Причина приходит и у товара на проверке — показываем только отклонённому и снятому */}
            {product?.rejectReason && (status === 'rejected' || status === 'blocked') && (
                <p className="mk-sample">
                    {status === 'blocked' ? L.form.moderatorHid : L.form.moderatorRejected}: {product.rejectReason}
                </p>
            )}

            <form className="mk-form mk-form--2" onSubmit={(event) => void save(event)} noValidate>
                <label className="mk-field mk-field--wide">
                    {L.form.title}
                    <input id="mk-p-title" name="title" defaultValue={product?.title} maxLength={200} placeholder={L.form.titlePlaceholder} />
                    {fail('title')}
                </label>
                <label className="mk-field mk-field--wide">
                    {L.form.description}
                    <textarea id="mk-p-description" name="description" rows={4} defaultValue={product?.description} placeholder={L.form.descriptionPlaceholder} />
                    {fail('description')}
                </label>
                <label className="mk-field">
                    {L.form.category}
                    <select id="mk-p-category" name="category" defaultValue={product?.category ?? ''}>
                        <option value="">{L.form.chooseCategory}</option>
                        {groups.map((group) => (
                            <optgroup key={group.root} label={group.root}>
                                {group.items.map((item) => (
                                    <option key={item.slug} value={item.slug}>
                                        {item.name}
                                    </option>
                                ))}
                            </optgroup>
                        ))}
                    </select>
                    {fail('category')}
                </label>
                <label className="mk-field">
                    {L.form.ikpu}
                    <input id="mk-p-ikpu" name="ikpu" inputMode="numeric" defaultValue={product?.ikpu ?? ''} placeholder={L.form.ikpuPlaceholder} />
                    {fail('ikpu') || <small>{L.form.ikpuHint}</small>}
                </label>
                <label className="mk-field">
                    {L.form.barcode}
                    <input id="mk-p-barcode" name="barcode" inputMode="numeric" defaultValue={product?.barcode ?? ''} />
                    {fail('barcode')}
                </label>
                <label className="mk-field">
                    {L.form.weight}
                    <input id="mk-p-weight" name="weight_g" inputMode="numeric" defaultValue={product?.weight_g ?? ''} />
                    {fail('weight_g')}
                </label>
                <div className="mk-field mk-field--wide">
                    {L.form.dimensions}
                    <div className="mk-range">
                        <input name="length_mm" inputMode="numeric" aria-label={L.form.lengthLabel} placeholder={L.form.length} defaultValue={product?.length_mm ?? ''} />
                        <input name="width_mm" inputMode="numeric" aria-label={L.form.widthLabel} placeholder={L.form.width} defaultValue={product?.width_mm ?? ''} />
                        <input name="height_mm" inputMode="numeric" aria-label={L.form.heightLabel} placeholder={L.form.height} defaultValue={product?.height_mm ?? ''} />
                    </div>
                    <small>{L.form.dimensionsHint}</small>
                </div>

                <div className="mk-field mk-field--wide">
                    {L.form.priceAndVariants}
                    {!locked && (
                        <label className="mk-field" style={{ maxWidth: 320 }}>
                            <small>{L.form.dimensionHint}</small>
                            <input id="mk-p-dimension" value={dimension} onChange={(e) => setDimension(e.target.value)} placeholder={L.form.dimensionPlaceholder} maxLength={40} />
                        </label>
                    )}
                    <div className="mk-variants">
                        {rows.map((row, i) => (
                            <div key={row.id ?? `new-${i}`} className="mk-variant">
                                <label className="mk-field">
                                    <small>{locked ? L.form.variant : dimension.trim() || L.form.variant}</small>
                                    {locked ? (
                                        <input value={Object.values(row.options).join(' · ')} readOnly />
                                    ) : (
                                        <input value={row.value} onChange={(e) => patch(i, { value: e.target.value })} placeholder={several ? L.form.variantExample : L.form.singleVariant} disabled={!several} />
                                    )}
                                </label>
                                <label className="mk-field">
                                    <small>{L.form.price}</small>
                                    <input inputMode="numeric" value={row.price} onChange={(e) => patch(i, { price: e.target.value })} />
                                </label>
                                <label className="mk-field">
                                    <small>{L.form.oldPrice}</small>
                                    <input inputMode="numeric" value={row.oldPrice} onChange={(e) => patch(i, { oldPrice: e.target.value })} />
                                </label>
                                <label className="mk-field">
                                    <small>{L.form.sku}</small>
                                    <input value={row.sku} onChange={(e) => patch(i, { sku: e.target.value })} />
                                </label>
                                {!locked && rows.length > 1 ? (
                                    <button type="button" aria-label={L.form.removeVariant} onClick={() => setRows(rows.filter((_, x) => x !== i))}>
                                        <Trash2 size={16} aria-hidden />
                                    </button>
                                ) : (
                                    <span />
                                )}
                            </div>
                        ))}
                    </div>
                    {fail('variants')}
                    {!locked && (
                        <button
                            type="button"
                            className="mk-reset"
                            onClick={() => setRows([...rows, { options: {}, value: '', sku: '', price: '', oldPrice: '' }])}
                            disabled={!dimension.trim()}
                        >
                            {L.form.addVariant}
                        </button>
                    )}
                    <small>
                        {locked ? L.form.lockedHint : L.form.variantsHint}
                    </small>
                </div>

                <div className="mk-field mk-field--wide">
                    {L.form.photos}
                    {product ? (
                        <div className="mk-thumbs-edit">
                            {product.images.map((image) => (
                                <figure key={image.id}>
                                    <img src={image.thumb} alt="" />
                                    <button type="button" aria-label={L.form.removePhoto} onClick={() => void removeImage(image.id)}>
                                        <X size={13} aria-hidden />
                                    </button>
                                </figure>
                            ))}
                            {product.images.length < 10 && (
                                <label>
                                    <input type="file" accept="image/*" className="sr-only" onChange={(event) => void upload(event)} disabled={busy} />
                                    {L.form.addPhoto}
                                </label>
                            )}
                        </div>
                    ) : (
                        <small>{L.form.photosLater}</small>
                    )}
                </div>

                <div className="mk-field--wide" style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                    <button type="submit" className="mk-btn" disabled={busy}>
                        {product ? L.form.save : L.form.saveDraft}
                    </button>
                    {product && (status === 'draft' || status === 'rejected' || status === 'hidden') && (
                        <button type="button" className="mk-btn mk-btn--ghost" disabled={busy} onClick={() => void publish()}>
                            {L.form.publish}
                        </button>
                    )}
                    {product && (status === 'active' || status === 'pending') && (
                        <button type="button" className="mk-btn mk-btn--ghost" disabled={busy} onClick={() => void hide()}>
                            {L.form.hide}
                        </button>
                    )}
                </div>
            </form>
            <p className="mk-hint">
                {needsReview ? L.form.hintReview : L.form.hintFree} {L.form.hintSpecs}
            </p>
        </section>
    );
}

function Stock({ products }: { products: MyProduct[] }) {
    const L = lang(sellerText);

    return (
        <>
            <div className="mk-bar">
                <h2>{L.stock.title}</h2>
            </div>
            {products.length === 0 ? (
                <div className="mk-empty">
                    <span aria-hidden>🏬</span>
                    <h2>{L.stock.emptyTitle}</h2>
                    <p>{L.stock.emptyText}</p>
                </div>
            ) : (
                <div className="mk-table-wrap">
                    <table className="mk-table">
                        <thead>
                            <tr>
                                <th>{L.stock.colProduct}</th>
                                <th className="is-num">{L.stock.colStock}</th>
                                <th />
                            </tr>
                        </thead>
                        <tbody>
                            {products.map((p) => (
                                <tr key={p.id}>
                                    <td>
                                        <div className="mk-table__item">
                                            <span>
                                                <MarketPhoto image={p.image} id={p.id} />
                                            </span>
                                            {p.title}
                                        </div>
                                    </td>
                                    <td className={cn('is-num', p.stock < 10 && 'mk-low')}>{p.stock}</td>
                                    <td>{p.stock === 0 ? L.stock.none : p.stock < 10 ? L.stock.low : ''}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
            <p className="mk-hint">{L.stock.hint}</p>
        </>
    );
}

const SUPPLY_TONE: Record<Supply['status']['code'], string> = {
    draft: '',
    submitted: 'mk-pill--warn',
    received: 'mk-pill--ok',
    rejected: 'mk-pill--off',
    cancelled: 'mk-pill--off',
};

/** Подпись варианта: «Синий, XL»; у товара без вариантов — пусто. */
const optionsText = (options: Record<string, string>): string => Object.values(options).filter(Boolean).join(', ');

/**
 * Поставки на склад (/market/api/me/supplies, склад — PR #33): список
 * своих поставок с приёмкой и браком, новая поставка (черновик или сразу на
 * склад), «Отправить» черновик и «Отменить» до приёмки. Остаток ставит
 * склад при приёмке — продавец его не правит.
 */
function Supplies({ products }: { products: MyProduct[] }) {
    const L = lang(sellerText);
    const { data, loading, error, reload } = useApi<{ supplies: Supply[] }>('me/supplies');
    const [creating, setCreating] = useState(false);
    const [busy, setBusy] = useState<string | null>(null);

    async function act(supply: Supply, action: 'submit' | 'cancel') {
        if (action === 'cancel' && !window.confirm(L.supplies.confirmCancel(supply.number))) return;

        setBusy(supply.number);

        try {
            const result = await api<{ message?: string }>(`me/supplies/${supply.number}/${action}`, { post: true });

            if (result.message) notify(result.message);
            reload();
        } catch (failure) {
            if (failure instanceof ApiError) notify(failure.message, true);
            reload();
        } finally {
            setBusy(null);
        }
    }

    return (
        <>
            <div className="mk-bar">
                <h2>{L.supplies.title}</h2>
                {!creating && products.length > 0 && (
                    <button type="button" className="mk-btn" onClick={() => setCreating(true)}>
                        <Plus size={16} aria-hidden /> {L.supplies.add}
                    </button>
                )}
            </div>
            {creating && (
                <SupplyForm
                    products={products}
                    onClose={() => setCreating(false)}
                    onCreated={() => {
                        setCreating(false);
                        reload();
                    }}
                />
            )}
            <Loading loading={loading} error={error} reload={reload} />
            {data && data.supplies.length === 0 && !creating && (
                <div className="mk-empty">
                    <span aria-hidden>🚚</span>
                    <h2>{L.supplies.emptyTitle}</h2>
                    <p>{products.length > 0 ? L.supplies.emptyText : L.supplies.noProducts}</p>
                    {products.length > 0 && (
                        <button type="button" className="mk-btn" onClick={() => setCreating(true)}>
                            {L.supplies.add}
                        </button>
                    )}
                </div>
            )}
            {data && data.supplies.length > 0 && (
                <div className="mk-table-wrap">
                    <table className="mk-table">
                        <thead>
                            <tr>
                                <th>{L.supplies.colSupply}</th>
                                <th>{L.supplies.colWarehouse}</th>
                                <th>{L.supplies.colExpected}</th>
                                <th>{L.supplies.colItems}</th>
                                <th>{L.supplies.colStatus}</th>
                                <th />
                            </tr>
                        </thead>
                        <tbody>
                            {data.supplies.map((supply) => (
                                <tr key={supply.number}>
                                    <td>
                                        <b>{supply.number}</b>
                                        {supply.createdAt && <div className="mk-muted">{when(supply.createdAt)}</div>}
                                    </td>
                                    <td>
                                        {supply.warehouse.name}
                                        <small className="mk-muted">{supply.warehouse.address}</small>
                                    </td>
                                    <td>{supply.expectedAt ? day(supply.expectedAt) : L.supplies.noDate}</td>
                                    <td>
                                        <ul className="mk-supply-items">
                                            {supply.items.map((item) => {
                                                const options = optionsText(item.options);

                                                return (
                                                    <li key={item.variantId}>
                                                        {L.supplies.line(options ? `${item.title} (${options})` : item.title, item.declared)}
                                                        {item.accepted !== null && (
                                                            <small className={cn(item.defect ? 'mk-low' : undefined)}> · {L.supplies.accepted(item.accepted, item.defect ?? 0)}</small>
                                                        )}
                                                    </li>
                                                );
                                            })}
                                        </ul>
                                        {supply.status.code === 'rejected' && supply.rejectReason && <small className="is-error">{L.supplies.rejected(supply.rejectReason)}</small>}
                                        {supply.note && <small className="mk-muted">{supply.note}</small>}
                                    </td>
                                    <td>
                                        <span className={cn('mk-pill', SUPPLY_TONE[supply.status.code])}>{supply.status.text}</span>
                                    </td>
                                    <td>
                                        <div className="mk-row-actions">
                                            {supply.canSubmit && (
                                                <button type="button" className="mk-btn" disabled={busy !== null} onClick={() => void act(supply, 'submit')}>
                                                    {L.supplies.submit}
                                                </button>
                                            )}
                                            {supply.canCancel && (
                                                <button type="button" className="mk-btn mk-btn--ghost" disabled={busy !== null} onClick={() => void act(supply, 'cancel')}>
                                                    {L.supplies.cancel}
                                                </button>
                                            )}
                                        </div>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
            <p className="mk-hint">{L.supplies.hint}</p>
        </>
    );
}

interface SupplyLine {
    variantId: number;
    title: string;
    quantity: number;
}

/**
 * Новая поставка: склад, дата, комментарий и строки «товар — вариант —
 * сколько». Варианты товара берутся из его карточки (me/products/<id>);
 * у товара с одним вариантом выбирать нечего.
 */
function SupplyForm({ products, onClose, onCreated }: { products: MyProduct[]; onClose: () => void; onCreated: () => void }) {
    const L = lang(sellerText);
    const places = useApi<{ warehouses: Warehouse[] }>('me/warehouses');
    const [productId, setProductId] = useState<number | null>(null);
    const detail = useApi<{ product: MyProductDetail }>(productId === null ? null : `me/products/${productId}`);
    const [variantId, setVariantId] = useState<number | null>(null);
    const [warehouseCode, setWarehouseCode] = useState('');
    const [quantity, setQuantity] = useState('');
    const [lines, setLines] = useState<SupplyLine[]>([]);
    const [errors, setErrors] = useState<Record<string, string[]>>({});
    const [busy, setBusy] = useState(false);
    const today = new Date().toISOString().slice(0, 10);
    const variants = (detail.data?.product.variants ?? []).filter((v) => v.id !== undefined && v.active !== false && !lines.some((line) => line.variantId === v.id));
    const chosen = variants.length === 1 ? variants[0].id ?? null : variantId;
    const count = Number(quantity);

    function addLine() {
        const product = detail.data?.product;
        const variant = variants.find((v) => v.id === chosen);

        if (!product || !variant?.id || !Number.isInteger(count) || count < 1) return;

        const options = optionsText(variant.options);

        setLines([...lines, { variantId: variant.id, title: options ? `${product.title} (${options})` : product.title, quantity: count }]);
        setProductId(null);
        setVariantId(null);
        setQuantity('');
    }

    async function save(event: FormEvent<HTMLFormElement>, submit: boolean) {
        event.preventDefault();

        if (lines.length === 0) {
            setErrors({ items: [L.supplies.noLines] });

            return;
        }

        const form = new FormData(event.currentTarget);

        setBusy(true);
        setErrors({});

        try {
            const data = await api<{ message: string }>('me/supplies/create', {
                body: {
                    warehouse: String(form.get('warehouse') ?? ''),
                    expectedAt: String(form.get('expectedAt') ?? '') || null,
                    note: String(form.get('note') ?? '').trim() || null,
                    items: lines.map((line) => ({ variantId: line.variantId, quantity: line.quantity })),
                    submit,
                },
            });

            notify(data.message);
            onCreated();
        } catch (failure) {
            if (failure instanceof ApiError) {
                setErrors(failure.errors);
                notify(failure.message, true);
            }
        } finally {
            setBusy(false);
        }
    }

    const warehouses = places.data?.warehouses ?? [];
    const place = warehouses.find((w) => w.code === warehouseCode) ?? warehouses[0];

    return (
        <section className="mk-panel">
            <div className="mk-bar">
                <h2>{L.supplies.formTitle}</h2>
                <button type="button" className="mk-btn mk-btn--ghost" onClick={onClose} aria-label={L.supplies.close}>
                    <X size={16} aria-hidden />
                </button>
            </div>
            <Loading loading={places.loading} error={places.error} reload={places.reload} />
            {places.data && warehouses.length === 0 && <p className="mk-hint">{L.supplies.warehouseNone}</p>}
            {places.data && warehouses.length > 0 && (
                <form
                    className="mk-form mk-form--2"
                    noValidate
                    onSubmit={(event) => {
                        const submitter = (event.nativeEvent as SubmitEvent).submitter as HTMLButtonElement | null;

                        void save(event, submitter?.value === 'send');
                    }}
                >
                    <label className="mk-field">
                        {L.supplies.warehouse}
                        <select name="warehouse" value={place.code} onChange={(event) => setWarehouseCode(event.target.value)}>
                            {warehouses.map((w) => (
                                <option key={w.code} value={w.code}>
                                    {w.name}
                                </option>
                            ))}
                        </select>
                        {errors.warehouse?.[0] ? (
                            <small className="is-error">{errors.warehouse[0]}</small>
                        ) : (
                            <small className="mk-where">{L.supplies.bringTo(`${place.address}${place.city && !place.address.includes(place.city) ? `, ${place.city}` : ''}`)}</small>
                        )}
                    </label>
                    <label className="mk-field">
                        {L.supplies.expected}
                        <input type="date" name="expectedAt" min={today} />
                        {errors.expectedAt?.[0] ? <small className="is-error">{errors.expectedAt[0]}</small> : <small>{L.supplies.expectedHint}</small>}
                    </label>
                    <label className="mk-field mk-field--wide">
                        {L.supplies.note}
                        <input name="note" maxLength={1000} placeholder={L.supplies.notePlaceholder} />
                    </label>

                    <fieldset className="mk-field mk-field--wide mk-supply-lines">
                        <legend>{L.supplies.items}</legend>
                        {lines.length > 0 && (
                            <ul>
                                {lines.map((line) => (
                                    <li key={line.variantId}>
                                        <span>{L.supplies.line(line.title, line.quantity)}</span>
                                        <button
                                            type="button"
                                            className="mk-icon-btn"
                                            aria-label={L.supplies.removeLine(line.title)}
                                            onClick={() => setLines(lines.filter((l) => l.variantId !== line.variantId))}
                                        >
                                            <Trash2 size={16} aria-hidden />
                                        </button>
                                    </li>
                                ))}
                            </ul>
                        )}
                        <div className="mk-supply-pick">
                            <label>
                                {L.supplies.product}
                                <select
                                    value={productId ?? ''}
                                    onChange={(event) => {
                                        setProductId(event.target.value ? Number(event.target.value) : null);
                                        setVariantId(null);
                                    }}
                                >
                                    <option value="">{L.supplies.choose}</option>
                                    {products.map((p) => (
                                        <option key={p.id} value={p.id}>
                                            {p.title}
                                        </option>
                                    ))}
                                </select>
                            </label>
                            {productId !== null && detail.loading && <small>{L.supplies.loadingVariants}</small>}
                            {productId !== null && detail.data && variants.length > 1 && (
                                <label>
                                    {L.supplies.variant}
                                    <select value={variantId ?? ''} onChange={(event) => setVariantId(event.target.value ? Number(event.target.value) : null)}>
                                        <option value="">—</option>
                                        {variants.map((v) => (
                                            <option key={v.id} value={v.id}>
                                                {optionsText(v.options) || L.supplies.oneVariant}
                                            </option>
                                        ))}
                                    </select>
                                </label>
                            )}
                            <label>
                                {L.supplies.quantity}
                                <input type="number" inputMode="numeric" min={1} max={100000} value={quantity} onChange={(event) => setQuantity(event.target.value)} />
                            </label>
                            <button type="button" className="mk-btn mk-btn--ghost" disabled={chosen === null || !Number.isInteger(count) || count < 1} onClick={addLine}>
                                <Plus size={16} aria-hidden /> {L.supplies.addLine}
                            </button>
                        </div>
                        {errors.items?.[0] && <small className="is-error">{errors.items[0]}</small>}
                    </fieldset>

                    <div className="mk-field--wide" style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                        <button type="submit" value="send" className="mk-btn" disabled={busy}>
                            {L.supplies.sendNow}
                        </button>
                        <button type="submit" value="draft" className="mk-btn mk-btn--ghost" disabled={busy}>
                            {L.supplies.saveDraft}
                        </button>
                    </div>
                </form>
            )}
        </section>
    );
}

/** Заказы с товарами продавца (/market/api/me/orders): только его части, о покупателе — имя. */
function Orders() {
    const L = lang(sellerText);
    const { data, loading, error, reload } = useApi<{ orders: SellerOrder[] }>('me/orders');

    return (
        <>
            <div className="mk-bar">
                <h2>{L.orders.title}</h2>
            </div>
            <Loading loading={loading} error={error} reload={reload} />
            {data && data.orders.length === 0 && (
                <div className="mk-empty">
                    <span aria-hidden>🧾</span>
                    <h2>{L.orders.emptyTitle}</h2>
                    <p>{L.orders.emptyText}</p>
                </div>
            )}
            {data && data.orders.length > 0 && (
                <div className="mk-table-wrap">
                    <table className="mk-table">
                        <thead>
                            <tr>
                                <th>{L.orders.colOrder}</th>
                                <th>{L.orders.colDate}</th>
                                <th>{L.orders.colItems}</th>
                                <th>{L.orders.colBuyer}</th>
                                <th>{L.orders.colPickup}</th>
                                <th className="is-num">{L.orders.colTotal}</th>
                                <th className="is-num">{L.orders.colPayout}</th>
                                <th>{L.orders.colStatus}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {data.orders.map((o) => (
                                <tr key={o.number}>
                                    <td>{o.number}</td>
                                    <td>{when(o.createdAt)}</td>
                                    <td>{o.items.map((item) => `${item.title} × ${item.quantity}`).join(', ')}</td>
                                    <td>{o.buyer.name}</td>
                                    <td>{o.pickupPoint.name}</td>
                                    <td className="is-num">{L.money(sum(o.total))}</td>
                                    <td className="is-num">{L.money(sum(o.payout))}</td>
                                    <td>
                                        <StatusPill status={o.status} />
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
            <p className="mk-hint">{L.orders.hint}</p>
        </>
    );
}

/** Касса продавца (/market/api/me/balance): начислено, держится, доступно, выплаты. */
function Payouts() {
    const L = lang(sellerText);
    const { data, loading, error, reload } = useApi<{ balance: SellerBalance }>('me/balance');
    const balance = data?.balance;

    return (
        <>
            <div className="mk-bar">
                <h2>{L.payouts.title}</h2>
            </div>
            <Loading loading={loading} error={error} reload={reload} />
            {balance && (
                <>
                    <div className="mk-kpis">
                        <div className="mk-kpi">
                            <small>{L.payouts.accrued}</small>
                            <b>{L.money(sum(balance.accrued))}</b>
                        </div>
                        <div className="mk-kpi">
                            <small>{L.payouts.onHold}</small>
                            <b>{L.money(sum(balance.onHold))}</b>
                            <span>{L.payouts.onHoldNote(balance.holdDays)}</span>
                        </div>
                        <div className="mk-kpi">
                            <small>{L.payouts.available}</small>
                            <b>{L.money(sum(balance.available))}</b>
                        </div>
                        <div className="mk-kpi">
                            <small>{L.payouts.paid}</small>
                            <b>{L.money(sum(balance.paid))}</b>
                            {balance.inWork > 0 && <span>{L.payouts.inWork(sum(balance.inWork))}</span>}
                        </div>
                    </div>
                    <h3 className="mk-subhead">{L.payouts.payouts}</h3>
                    {balance.payouts.length === 0 ? (
                        <p className="mk-hint">{L.payouts.none}</p>
                    ) : (
                        <div className="mk-table-wrap">
                            <table className="mk-table">
                                <thead>
                                    <tr>
                                        <th>{L.payouts.colCreated}</th>
                                        <th className="is-num">{L.payouts.colAmount}</th>
                                        <th>{L.payouts.colStatus}</th>
                                        <th>{L.payouts.colPaid}</th>
                                        <th>{L.payouts.colReference}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {balance.payouts.map((p) => (
                                        <tr key={p.id}>
                                            <td>{when(p.createdAt)}</td>
                                            <td className="is-num">{L.money(sum(p.amount))}</td>
                                            <td>
                                                <span className="mk-pill">{p.status.text}</span>
                                            </td>
                                            <td>{when(p.paidAt) || '—'}</td>
                                            <td>{p.bankReference ?? '—'}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </>
            )}
            <p className="mk-hint">{L.payouts.hint}</p>
            <Requisites />
        </>
    );
}

interface RequisitesData {
    bankAccount: string;
    bankMfo: string;
    bankName: string;
    recipientName: string;
    recipientTin: string;
    changedAt: string | null;
}

// Подпись и подсказка поля — из text/seller.ts (requisites.fields)
const REQUISITE_FIELDS: [keyof Omit<RequisitesData, 'changedAt'>, 'numeric' | 'text'][] = [
    ['recipientName', 'text'],
    ['recipientTin', 'numeric'],
    ['bankName', 'text'],
    ['bankMfo', 'numeric'],
    ['bankAccount', 'numeric'],
];

/**
 * Реквизиты для выплат (/market/api/me/requisites) — видит и меняет только
 * владелец компании; сохранение — с паролем от входа, чтобы чужая открытая
 * сессия не подменила счёт. Выплата на новые реквизиты — через сутки или
 * после сверки кассой.
 */
function Requisites() {
    const L = lang(sellerText);
    const loaded = useApi<{ requisites: RequisitesData | null }>('me/requisites');
    const [saved, setSaved] = useState<RequisitesData | null>(null);
    const [errors, setErrors] = useState<Record<string, string[]>>({});
    const [busy, setBusy] = useState(false);
    const [editing, setEditing] = useState(false);
    const current = saved ?? loaded.data?.requisites ?? null;

    if (loaded.status === 403) {
        return (
            <section className="mk-panel">
                <h2>{L.requisites.title}</h2>
                <p className="mk-hint">{loaded.error}</p>
            </section>
        );
    }

    async function save(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();

        const form = new FormData(event.currentTarget);
        const body = Object.fromEntries([...REQUISITE_FIELDS.map(([key]) => key), 'password'].map((key) => [key, String(form.get(key) ?? '').trim()]));

        setBusy(true);
        setErrors({});

        try {
            const data = await api<{ message: string; requisites: RequisitesData }>('me/requisites', { body });

            notify(data.message);
            setSaved(data.requisites ?? { ...(body as unknown as RequisitesData), changedAt: new Date().toISOString() });
            setEditing(false);
        } catch (failure) {
            if (failure instanceof ApiError) {
                setErrors(failure.errors);
                notify(failure.message, true);
            }
        } finally {
            setBusy(false);
        }
    }

    return (
        <section className="mk-panel">
            <div className="mk-bar">
                <h2>{L.requisites.title}</h2>
                {current && !editing && (
                    <button type="button" className="mk-btn mk-btn--ghost" onClick={() => setEditing(true)}>
                        {L.requisites.edit}
                    </button>
                )}
            </div>
            {loaded.loading && <div className="mk-skel-block" style={{ height: 120 }} aria-busy />}
            {loaded.error && loaded.status !== 403 && (
                <div className="mk-failed">
                    <p>{loaded.error}</p>
                    <button type="button" className="mk-btn" onClick={loaded.reload}>
                        {L.retry}
                    </button>
                </div>
            )}
            {!loaded.loading && !loaded.error && current && !editing && (
                <dl className="mk-specs">
                    {REQUISITE_FIELDS.map(([key]) => (
                        <div key={key}>
                            <dt>{L.requisites.fields[key][0]}</dt>
                            <dd>{current[key]}</dd>
                        </div>
                    ))}
                    {current.changedAt && (
                        <div>
                            <dt>{L.requisites.changed}</dt>
                            <dd>{when(current.changedAt)}</dd>
                        </div>
                    )}
                </dl>
            )}
            {!loaded.loading && !loaded.error && (!current || editing) && (
                <form className="mk-form mk-form--2" onSubmit={(event) => void save(event)} noValidate>
                    {!current && <p className="mk-hint mk-field--wide">{L.requisites.none}</p>}
                    {REQUISITE_FIELDS.map(([key, mode]) => (
                        <label key={key} className={key === 'recipientName' || key === 'bankAccount' ? 'mk-field mk-field--wide' : 'mk-field'}>
                            {L.requisites.fields[key][0]}
                            <input id={`mk-r-${key}`} name={key} inputMode={mode} defaultValue={current?.[key] ?? ''} placeholder={L.requisites.fields[key][1]} autoComplete="off" />
                            {errors[key]?.[0] && <small className="is-error">{errors[key][0]}</small>}
                        </label>
                    ))}
                    <label className="mk-field mk-field--wide">
                        {L.requisites.password}
                        <input id="mk-r-password" name="password" type="password" autoComplete="current-password" />
                        {errors.password?.[0] ? <small className="is-error">{errors.password[0]}</small> : <small>{L.requisites.passwordHint}</small>}
                    </label>
                    <div className="mk-field--wide" style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                        <button type="submit" className="mk-btn" disabled={busy}>
                            {L.requisites.save}
                        </button>
                        {editing && (
                            <button type="button" className="mk-btn mk-btn--ghost" onClick={() => setEditing(false)}>
                                {L.requisites.cancel}
                            </button>
                        )}
                    </div>
                    <p className="mk-hint mk-field--wide">{L.requisites.hint}</p>
                </form>
            )}
        </section>
    );
}

function Loading({ loading, error, reload }: { loading: boolean; error: string | null; reload: () => void }) {
    const L = lang(sellerText);

    if (loading) return <div className="mk-skel-block" style={{ height: 200 }} aria-busy />;

    if (!error) return null;

    return (
        <div className="mk-failed">
            <p>{error}</p>
            <button type="button" className="mk-btn" onClick={reload}>
                {L.retry}
            </button>
        </div>
    );
}
