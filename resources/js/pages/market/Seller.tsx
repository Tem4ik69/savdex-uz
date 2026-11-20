import { usePage } from '@inertiajs/react';
import { Plus, Trash2, X } from 'lucide-react';
import { useState, type ChangeEvent, type FormEvent, type ReactNode } from 'react';
import { MarketPhoto } from '@/components/market/MarketPhoto';
import { Link } from '@/components/ui/Link';
import { cn } from '@/lib/cn';
import { MarketLayout } from '@/layouts/MarketLayout';
import { api, ApiError, useApi } from '@/market/api';
import { sum } from '@/market/format';
import { COMMISSION, SAMPLE_ORDERS, SAMPLE_SUPPLIES } from '@/market/seller';
import { notify, useCategories } from '@/market/store';
import type { MarketCategory, MyProduct, MyProductDetail, MyVariant, ProductStatus } from '@/market/types';
import { routes } from '@/routes';
import type { SharedProps } from '@/types';

const TABS: [string, string][] = [
    ['products', 'Мои товары'],
    ['stock', 'Остатки'],
    ['supplies', 'Поставки'],
    ['orders', 'Заказы'],
    ['payouts', 'Начисления'],
];

const STATUS: Record<ProductStatus, [string, string]> = {
    draft: ['Черновик', 'mk-pill--off'],
    pending: ['На проверке', 'mk-pill--warn'],
    active: ['В продаже', 'mk-pill--ok'],
    rejected: ['Отклонён', 'mk-pill--warn'],
    hidden: ['Снят с продажи', 'mk-pill--off'],
    blocked: ['Снят модератором', 'mk-pill--warn'],
};

const day = (iso: string) => new Date(`${iso}T12:00:00`).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' });

/**
 * Кабинет продавца. «Мои товары» и «Остатки» — с сервера
 * (/market/api/me/products): добавить, изменить, загрузить фото,
 * отправить на продажу, снять. Поставки, заказы и начисления сервер
 * ещё не ведёт (склад, заказы и касса — следующие этапы) — там образцы
 * с пометкой. Открыт только подтверждённому продавцу: остальным сервер
 * отвечает «нельзя», и страница ведёт к заявке.
 */
export default function MarketSeller({ tab }: { tab: string }) {
    const { auth } = usePage<SharedProps>().props;
    const list = useApi<{ products: MyProduct[]; needsReview: boolean }>(auth.user ? 'me/products' : null);

    if (!auth.user || list.status === 403 || list.status === 401) {
        return (
            <MarketLayout title="Кабинет продавца · SavdEx Market">
                <div className="mk-in" style={{ paddingTop: 24 }}>
                    <div className="mk-gate">
                        <h2>Кабинет продавца пока закрыт</h2>
                        <p>Он открывается после заявки и проверки документов компании.</p>
                        <Link href={auth.user ? routes.marketSell : routes.loginBack(routes.marketSeller())} className="mk-btn">
                            {auth.user ? 'Стать продавцом' : 'Войти'}
                        </Link>
                    </div>
                </div>
            </MarketLayout>
        );
    }

    return (
        <MarketLayout title="Кабинет продавца · SavdEx Market">
            <div className="mk-in">
                <nav className="mk-bc" aria-label="Путь">
                    <Link href={routes.market}>Главная</Link>› Кабинет продавца
                </nav>
                <div className="mk-title">
                    <h1>{auth.company?.name ?? 'Кабинет продавца'}</h1>
                    <span className="mk-pill mk-pill--ok">Продавец подтверждён</span>
                </div>
                <nav className="mk-tabs" aria-label="Разделы кабинета">
                    {TABS.map(([key, label]) => (
                        <Link key={key} href={routes.marketSeller(key)} aria-current={tab === key ? 'page' : undefined} preserveScroll>
                            {label}
                        </Link>
                    ))}
                </nav>

                {(tab === 'products' || tab === 'stock') && list.loading && <div className="mk-skel-block" style={{ height: 240 }} aria-busy />}
                {(tab === 'products' || tab === 'stock') && list.error && (
                    <div className="mk-failed">
                        <h2>Товары не загрузились</h2>
                        <p>{list.error}</p>
                        <button type="button" className="mk-btn" onClick={list.reload}>
                            Повторить
                        </button>
                    </div>
                )}
                {tab === 'products' && list.data && <Products products={list.data.products} needsReview={list.data.needsReview} reload={list.reload} />}
                {tab === 'stock' && list.data && <Stock products={list.data.products} />}
                {tab === 'supplies' && <Supplies />}
                {tab === 'orders' && <Orders />}
                {tab === 'payouts' && <Payouts />}
            </div>
        </MarketLayout>
    );
}

function Products({ products, needsReview, reload }: { products: MyProduct[]; needsReview: boolean; reload: () => void }) {
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
                <h2>Мои товары</h2>
                <button type="button" className="mk-btn" onClick={() => setEditing('new')}>
                    <Plus size={18} aria-hidden /> Добавить товар
                </button>
            </div>

            {products.length === 0 ? (
                <div className="mk-empty">
                    <span aria-hidden>📦</span>
                    <h2>Товаров пока нет</h2>
                    <p>Добавьте первый товар: название, фото, цену и категорию. В каталоге он появится после проверки и приёмки на складе.</p>
                    <button type="button" className="mk-btn" onClick={() => setEditing('new')}>
                        Добавить товар
                    </button>
                </div>
            ) : (
                <div className="mk-table-wrap">
                    <table className="mk-table">
                        <thead>
                            <tr>
                                <th>Товар</th>
                                <th className="is-num">Цена</th>
                                <th className="is-num">На складе</th>
                                <th className="is-num">Продано</th>
                                <th>Статус</th>
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
                                        {p.rejectReason && <div className="mk-line__warn">Причина: {p.rejectReason}</div>}
                                    </td>
                                    <td className="is-num">{p.price ? `${sum(p.price)} сум` : '—'}</td>
                                    <td className={cn('is-num', p.stock === 0 && 'mk-low')}>{p.stock}</td>
                                    <td className="is-num">{sum(p.sold)}</td>
                                    <td>
                                        <span className={cn('mk-pill', STATUS[p.status][1])}>{STATUS[p.status][0]}</span>
                                    </td>
                                    <td>
                                        <button type="button" onClick={() => setEditing(p.id)}>
                                            Изменить
                                        </button>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
            <p className="mk-hint">
                {needsReview
                    ? 'Пока вы новый продавец, товары и правки их описания проверяет модератор. '
                    : 'Ваши товары выходят в продажу без проверки. '}
                Купить можно только то, что принято на складе: остаток ставит склад, а не продавец.
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
    const loaded = useApi<{ product: MyProductDetail }>(id === null ? null : `me/products/${id}`);
    const [saved, setSaved] = useState<MyProductDetail | null>(null);
    const product = saved ?? loaded.data?.product ?? null;

    if (id !== null && !product) {
        return loaded.error ? (
            <div className="mk-failed">
                <h2>Товар не загрузился</h2>
                <p>{loaded.error}</p>
                <button type="button" className="mk-btn" onClick={onClose}>
                    К списку товаров
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
                    {product ? 'Товар' : 'Новый товар'} {product && <span className={cn('mk-pill', STATUS[status][1])}>{STATUS[status][0]}</span>}
                </h2>
                <button type="button" className="mk-btn mk-btn--ghost" onClick={onClose}>
                    <X size={16} aria-hidden /> К списку
                </button>
            </div>
            {product?.rejectReason && <p className="mk-sample">Модератор отклонил товар: {product.rejectReason}</p>}

            <form className="mk-form mk-form--2" onSubmit={(event) => void save(event)} noValidate>
                <label className="mk-field mk-field--wide">
                    Название
                    <input id="mk-p-title" name="title" defaultValue={product?.title} maxLength={200} placeholder="Например: Плед шерстяной 150×200" />
                    {fail('title')}
                </label>
                <label className="mk-field mk-field--wide">
                    Описание
                    <textarea id="mk-p-description" name="description" rows={4} defaultValue={product?.description} placeholder="Материал, размеры, что в комплекте, как ухаживать" />
                    {fail('description')}
                </label>
                <label className="mk-field">
                    Категория
                    <select id="mk-p-category" name="category" defaultValue={product?.category ?? ''}>
                        <option value="">Выберите категорию</option>
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
                    ИКПУ
                    <input id="mk-p-ikpu" name="ikpu" inputMode="numeric" defaultValue={product?.ikpu ?? ''} placeholder="17 цифр" />
                    {fail('ikpu') || <small>Код товара для чека — без него товар не выйдет в продажу</small>}
                </label>
                <label className="mk-field">
                    Штрихкод
                    <input id="mk-p-barcode" name="barcode" inputMode="numeric" defaultValue={product?.barcode ?? ''} />
                    {fail('barcode')}
                </label>
                <label className="mk-field">
                    Вес, г
                    <input id="mk-p-weight" name="weight_g" inputMode="numeric" defaultValue={product?.weight_g ?? ''} />
                    {fail('weight_g')}
                </label>
                <div className="mk-field mk-field--wide">
                    Габариты упаковки, мм
                    <div className="mk-range">
                        <input name="length_mm" inputMode="numeric" aria-label="Длина, мм" placeholder="длина" defaultValue={product?.length_mm ?? ''} />
                        <input name="width_mm" inputMode="numeric" aria-label="Ширина, мм" placeholder="ширина" defaultValue={product?.width_mm ?? ''} />
                        <input name="height_mm" inputMode="numeric" aria-label="Высота, мм" placeholder="высота" defaultValue={product?.height_mm ?? ''} />
                    </div>
                    <small>Вес и габариты нужны складу</small>
                </div>

                <div className="mk-field mk-field--wide">
                    Цена и варианты
                    {!locked && (
                        <label className="mk-field" style={{ maxWidth: 320 }}>
                            <small>Чем отличаются варианты — если товар один, оставьте пустым</small>
                            <input id="mk-p-dimension" value={dimension} onChange={(e) => setDimension(e.target.value)} placeholder="Цвет, размер, объём…" maxLength={40} />
                        </label>
                    )}
                    <div className="mk-variants">
                        {rows.map((row, i) => (
                            <div key={row.id ?? `new-${i}`} className="mk-variant">
                                <label className="mk-field">
                                    <small>{locked ? 'Вариант' : dimension.trim() || 'Вариант'}</small>
                                    {locked ? (
                                        <input value={Object.values(row.options).join(' · ')} readOnly />
                                    ) : (
                                        <input value={row.value} onChange={(e) => patch(i, { value: e.target.value })} placeholder={several ? 'Чёрный' : 'один вариант'} disabled={!several} />
                                    )}
                                </label>
                                <label className="mk-field">
                                    <small>Цена, сум</small>
                                    <input inputMode="numeric" value={row.price} onChange={(e) => patch(i, { price: e.target.value })} />
                                </label>
                                <label className="mk-field">
                                    <small>Старая цена</small>
                                    <input inputMode="numeric" value={row.oldPrice} onChange={(e) => patch(i, { oldPrice: e.target.value })} />
                                </label>
                                <label className="mk-field">
                                    <small>Артикул</small>
                                    <input value={row.sku} onChange={(e) => patch(i, { sku: e.target.value })} />
                                </label>
                                {!locked && rows.length > 1 ? (
                                    <button type="button" aria-label="Убрать вариант" onClick={() => setRows(rows.filter((_, x) => x !== i))}>
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
                            + Добавить вариант
                        </button>
                    )}
                    <small>
                        {locked
                            ? 'У товара несколько характеристик выбора — здесь правятся только цена и артикул.'
                            : 'Старая цена, если она больше новой, даёт скидку на карточке. Остаток ставит склад.'}
                    </small>
                </div>

                <div className="mk-field mk-field--wide">
                    Фото — до 10
                    {product ? (
                        <div className="mk-thumbs-edit">
                            {product.images.map((image) => (
                                <figure key={image.id}>
                                    <img src={image.thumb} alt="" />
                                    <button type="button" aria-label="Удалить фото" onClick={() => void removeImage(image.id)}>
                                        <X size={13} aria-hidden />
                                    </button>
                                </figure>
                            ))}
                            {product.images.length < 10 && (
                                <label>
                                    <input type="file" accept="image/*" className="sr-only" onChange={(event) => void upload(event)} disabled={busy} />
                                    Добавить фото
                                </label>
                            )}
                        </div>
                    ) : (
                        <small>Фото можно загрузить после первого сохранения.</small>
                    )}
                </div>

                <div className="mk-field--wide" style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                    <button type="submit" className="mk-btn" disabled={busy}>
                        {product ? 'Сохранить' : 'Сохранить черновик'}
                    </button>
                    {product && (status === 'draft' || status === 'rejected' || status === 'hidden') && (
                        <button type="button" className="mk-btn mk-btn--ghost" disabled={busy} onClick={() => void publish()}>
                            Отправить на продажу
                        </button>
                    )}
                    {product && (status === 'active' || status === 'pending') && (
                        <button type="button" className="mk-btn mk-btn--ghost" disabled={busy} onClick={() => void hide()}>
                            Снять с продажи
                        </button>
                    )}
                </div>
            </form>
            <p className="mk-hint">
                {needsReview
                    ? 'Пока вы новый продавец, правка названия, описания, категории или фото возвращает товар в черновик — на повторную проверку. Цена и варианты статус не меняют.'
                    : 'Изменения сохраняются сразу.'}{' '}
                Характеристики для фильтров (материал, память и т. п.) появятся в этой форме следующим шагом.
            </p>
        </section>
    );
}

function Stock({ products }: { products: MyProduct[] }) {
    return (
        <>
            <div className="mk-bar">
                <h2>Остатки на складе</h2>
            </div>
            {products.length === 0 ? (
                <div className="mk-empty">
                    <span aria-hidden>🏬</span>
                    <h2>На складе пока ничего нет</h2>
                    <p>Остатки появятся, когда вы добавите товары и склад примет поставку.</p>
                </div>
            ) : (
                <div className="mk-table-wrap">
                    <table className="mk-table">
                        <thead>
                            <tr>
                                <th>Товар</th>
                                <th className="is-num">На складе</th>
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
                                    <td>{p.stock === 0 ? 'Нет в продаже — нужна поставка' : p.stock < 10 ? 'Заканчивается' : ''}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
            <p className="mk-hint">Остаток — сумма по всем вариантам товара. Его ставит склад при приёмке; купить можно только то, что есть на складе.</p>
        </>
    );
}

const Sample = ({ children }: { children: ReactNode }) => <p className="mk-sample">Пример: {children}</p>;

function Supplies() {
    return (
        <>
            <div className="mk-bar">
                <h2>Поставки на склад</h2>
            </div>
            <Sample>раздел появится вместе со складом BTS — заявка на поставку, приёмка и брак. Ниже — как это будет выглядеть.</Sample>
            <div className="mk-table-wrap">
                <table className="mk-table">
                    <thead>
                        <tr>
                            <th>Поставка</th>
                            <th>Дата</th>
                            <th>Товар</th>
                            <th className="is-num">Везёте</th>
                            <th className="is-num">Принято</th>
                            <th>Статус</th>
                        </tr>
                    </thead>
                    <tbody>
                        {SAMPLE_SUPPLIES.map((s) => (
                            <tr key={s.id}>
                                <td>{s.id}</td>
                                <td>{day(s.date)}</td>
                                <td>{s.title}</td>
                                <td className="is-num">{s.quantity}</td>
                                <td className="is-num">{s.accepted ?? '—'}</td>
                                <td>
                                    {s.status === 'planned' && <span className="mk-pill mk-pill--warn">Ждём на складе</span>}
                                    {s.status === 'accepted' && <span className="mk-pill mk-pill--ok">Принята</span>}
                                    {s.status === 'partial' && <span className="mk-pill">Принята частично: брак {s.quantity - (s.accepted ?? 0)}</span>}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </>
    );
}

function Orders() {
    return (
        <>
            <div className="mk-bar">
                <h2>Заказы с вашими товарами</h2>
            </div>
            <Sample>раздел появится вместе с заказами. Телефон покупателя продавцу не показывается — только имя и номер заказа.</Sample>
            <div className="mk-table-wrap">
                <table className="mk-table">
                    <thead>
                        <tr>
                            <th>Заказ</th>
                            <th>Дата</th>
                            <th>Товар</th>
                            <th className="is-num">Кол-во</th>
                            <th className="is-num">Сумма</th>
                            <th>Покупатель</th>
                            <th>Статус</th>
                        </tr>
                    </thead>
                    <tbody>
                        {SAMPLE_ORDERS.map((o) => (
                            <tr key={o.id}>
                                <td>{o.id}</td>
                                <td>{day(o.date)}</td>
                                <td>{o.title}</td>
                                <td className="is-num">{o.quantity}</td>
                                <td className="is-num">{sum(o.sum)} сум</td>
                                <td>{o.buyer}</td>
                                <td>
                                    <span className={cn('mk-pill', o.status === 'Выдан' && 'mk-pill--ok', o.status === 'Отменён' && 'mk-pill--off')}>{o.status}</span>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </>
    );
}

function Payouts() {
    const paid = SAMPLE_ORDERS.filter((o) => o.status === 'Выдан');
    const gross = paid.reduce((s, o) => s + o.sum, 0);
    const net = Math.round((gross * (100 - COMMISSION)) / 100);

    return (
        <>
            <div className="mk-bar">
                <h2>Начисления</h2>
            </div>
            <Sample>раздел появится вместе с кассой маркетплейса. Процент комиссии ({COMMISSION}%) условный — он ещё не определён.</Sample>
            <div className="mk-table-wrap">
                <table className="mk-table">
                    <thead>
                        <tr>
                            <th>Дата</th>
                            <th>Заказ</th>
                            <th className="is-num">Сумма заказа</th>
                            <th className="is-num">Комиссия</th>
                            <th className="is-num">Вам</th>
                        </tr>
                    </thead>
                    <tbody>
                        {paid.map((o) => {
                            const fee = Math.round((o.sum * COMMISSION) / 100);

                            return (
                                <tr key={o.id}>
                                    <td>{day(o.date)}</td>
                                    <td>{o.id}</td>
                                    <td className="is-num">{sum(o.sum)} сум</td>
                                    <td className="is-num">−{sum(fee)} сум</td>
                                    <td className="is-num">{sum(o.sum - fee)} сум</td>
                                </tr>
                            );
                        })}
                    </tbody>
                    <tfoot>
                        <tr>
                            <td colSpan={2}>К выплате</td>
                            <td className="is-num">{sum(gross)} сум</td>
                            <td className="is-num">−{sum(gross - net)} сум</td>
                            <td className="is-num">{sum(net)} сум</td>
                        </tr>
                    </tfoot>
                </table>
            </div>
        </>
    );
}
