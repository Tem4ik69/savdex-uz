import { Plus } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { Link } from '@/components/ui/Link';
import { cn } from '@/lib/cn';
import { MarketLayout } from '@/layouts/MarketLayout';
import { CATEGORIES, categoryOf } from '@/market/demo';
import { sum } from '@/market/format';
import { useLocal } from '@/market/local';
import { COMMISSION, seller, SELLER_ORDERS, type SellerProduct, type SellerState } from '@/market/seller';
import { routes } from '@/routes';

const TABS: [string, string][] = [
    ['overview', 'Обзор'],
    ['products', 'Мои товары'],
    ['supplies', 'Поставки'],
    ['stock', 'Остатки'],
    ['orders', 'Заказы'],
    ['payouts', 'Начисления'],
];

const PRODUCT_STATUS: Record<SellerProduct['status'], [string, string]> = {
    live: ['В продаже', 'mk-pill--ok'],
    moderation: ['На модерации', 'mk-pill--warn'],
    draft: ['Черновик', 'mk-pill--off'],
};

const day = (iso: string) => new Date(`${iso}T12:00:00`).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' });

/**
 * Кабинет продавца: обзор, товары (добавить, изменить), поставки на
 * склад, остатки, заказы, начисления. Открыт только подтверждённому
 * продавцу. Данные демо — в браузере (market/seller.ts).
 */
export default function MarketSeller({ tab }: { tab: string }) {
    const state = useLocal(seller);

    if (state.application !== 'approved') {
        return (
            <MarketLayout title="Кабинет продавца · SavdEx Market">
                <div className="mk-in" style={{ paddingTop: 24 }}>
                    <div className="mk-gate">
                        <h2>Кабинет продавца пока закрыт</h2>
                        <p>
                            {state.application === 'pending'
                                ? 'Ваша заявка на проверке. Кабинет откроется, как только модератор её подтвердит.'
                                : 'Он открывается после заявки и проверки документов.'}
                        </p>
                        <Link href={routes.marketSell} className="mk-btn">
                            {state.application === 'pending' ? 'Посмотреть заявку' : 'Стать продавцом'}
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
                    <h1>{state.company || 'Кабинет продавца'}</h1>
                    <span className="mk-pill mk-pill--ok">Продавец подтверждён</span>
                </div>
                <nav className="mk-tabs" aria-label="Разделы кабинета">
                    {TABS.map(([key, label]) => (
                        <Link key={key} href={routes.marketSeller(key)} aria-current={tab === key ? 'page' : undefined} preserveScroll>
                            {label}
                        </Link>
                    ))}
                </nav>

                {tab === 'overview' && <Overview state={state} />}
                {tab === 'products' && <Products state={state} />}
                {tab === 'supplies' && <Supplies state={state} />}
                {tab === 'stock' && <Stock state={state} />}
                {tab === 'orders' && <Orders />}
                {tab === 'payouts' && <Payouts />}
            </div>
        </MarketLayout>
    );
}

const paid = SELLER_ORDERS.filter((o) => o.status === 'Выдан');
const gross = paid.reduce((s, o) => s + o.sum, 0);
const net = Math.round((gross * (100 - COMMISSION)) / 100);

function Overview({ state }: { state: SellerState }) {
    const stock = state.products.reduce((s, p) => s + p.stock, 0);
    const low = state.products.filter((p) => p.status === 'live' && p.stock - p.reserved < 10);

    return (
        <>
            <div className="mk-kpis">
                <div className="mk-kpi">
                    <small>Продажи за 30 дней</small>
                    <b>{sum(gross)} сум</b>
                    <span>{paid.length} выданных заказа</span>
                </div>
                <div className="mk-kpi">
                    <small>К выплате</small>
                    <b>{sum(net)} сум</b>
                    <span>после комиссии {COMMISSION}%</span>
                </div>
                <div className="mk-kpi">
                    <small>На складе</small>
                    <b>{sum(stock)} шт.</b>
                    <span>{state.products.length} товаров</span>
                </div>
                <div className="mk-kpi">
                    <small>Заказов в работе</small>
                    <b>{SELLER_ORDERS.filter((o) => o.status === 'Можно забрать').length}</b>
                    <span>ждут покупателя в пункте</span>
                </div>
            </div>
            {low.length > 0 && (
                <section className="mk-panel">
                    <h2>Заканчивается на складе</h2>
                    <p>
                        {low.map((p) => p.title).join('; ')} — осталось меньше 10 штук.{' '}
                        <Link href={routes.marketSeller('supplies')} style={{ color: 'var(--primary-700)', fontWeight: 700 }}>
                            Создать поставку
                        </Link>
                    </p>
                </section>
            )}
        </>
    );
}

function Products({ state }: { state: SellerState }) {
    const [editing, setEditing] = useState<SellerProduct | 'new' | null>(null);

    function save(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();

        const form = new FormData(event.currentTarget);
        const title = String(form.get('title') ?? '').trim();
        const price = Number(String(form.get('price') ?? '').replace(/\D/g, ''));
        const old = Number(String(form.get('old') ?? '').replace(/\D/g, ''));

        if (!title || !price) return;

        const fields = { title, price, oldPrice: old > price ? old : null, category: String(form.get('category')), sku: String(form.get('sku') ?? '').trim() };

        if (editing === 'new') {
            const category = categoryOf(fields.category);
            const id = Math.max(1000, ...state.products.map((p) => p.id)) + 1;

            seller.set({
                ...state,
                // Новый товар ждёт модерации и поставки: продаётся только принятое на склад
                products: [...state.products, { id, emoji: category?.emoji ?? '📦', stock: 0, reserved: 0, status: 'moderation', ...fields }],
            });
        } else if (editing) {
            seller.set({ ...state, products: state.products.map((p) => (p.id === editing.id ? { ...p, ...fields } : p)) });
        }

        setEditing(null);
    }

    const current = editing && editing !== 'new' ? editing : null;

    return (
        <>
            <div className="mk-bar">
                <h2>Мои товары</h2>
                <button type="button" className="mk-btn" onClick={() => setEditing('new')}>
                    <Plus size={18} aria-hidden /> Добавить товар
                </button>
            </div>

            {editing && (
                <section className="mk-panel" style={{ marginBottom: 16, marginTop: 0 }}>
                    <h2>{current ? 'Изменить товар' : 'Новый товар'}</h2>
                    <form key={current?.id ?? 'new'} className="mk-form mk-form--2" onSubmit={save}>
                        <label className="mk-field mk-field--wide">
                            Название
                            <input id="mk-p-title" name="title" defaultValue={current?.title} required placeholder="Например: Плед шерстяной 150×200" />
                        </label>
                        <label className="mk-field">
                            Категория
                            <select id="mk-p-category" name="category" defaultValue={current?.category ?? CATEGORIES[0].slug}>
                                {CATEGORIES.map((c) => (
                                    <option key={c.slug} value={c.slug}>
                                        {c.name}
                                    </option>
                                ))}
                            </select>
                        </label>
                        <label className="mk-field">
                            Артикул
                            <input id="mk-p-sku" name="sku" defaultValue={current?.sku} placeholder="ST-1042" />
                        </label>
                        <label className="mk-field">
                            Цена, сум
                            <input id="mk-p-price" name="price" inputMode="numeric" defaultValue={current?.price} required />
                        </label>
                        <label className="mk-field">
                            Старая цена, сум
                            <input id="mk-p-old" name="old" inputMode="numeric" defaultValue={current?.oldPrice ?? ''} />
                            <small>Если заполнить — на карточке появится скидка</small>
                        </label>
                        <div className="mk-field--wide" style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                            <button type="submit" className="mk-btn">
                                {current ? 'Сохранить' : 'Отправить на модерацию'}
                            </button>
                            <button type="button" className="mk-btn mk-btn--ghost" onClick={() => setEditing(null)}>
                                Отмена
                            </button>
                        </div>
                    </form>
                    <p className="mk-hint">В полной версии здесь будут фото (до 10), описание, характеристики, варианты, ИКПУ, штрихкод, вес и габариты.</p>
                </section>
            )}

            <div className="mk-table-wrap">
                <table className="mk-table">
                    <thead>
                        <tr>
                            <th>Товар</th>
                            <th>Артикул</th>
                            <th className="is-num">Цена</th>
                            <th className="is-num">На складе</th>
                            <th>Статус</th>
                            <th />
                        </tr>
                    </thead>
                    <tbody>
                        {state.products.map((p) => (
                            <tr key={p.id}>
                                <td>
                                    <div className="mk-table__item">
                                        <span aria-hidden>{p.emoji}</span>
                                        {p.title}
                                    </div>
                                </td>
                                <td>{p.sku || '—'}</td>
                                <td className="is-num">{sum(p.price)} сум</td>
                                <td className={cn('is-num', p.stock === 0 && 'mk-low')}>{p.stock}</td>
                                <td>
                                    <span className={cn('mk-pill', PRODUCT_STATUS[p.status][1])}>{PRODUCT_STATUS[p.status][0]}</span>
                                </td>
                                <td>
                                    <button type="button" onClick={() => setEditing(p)}>
                                        Изменить
                                    </button>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
            <p className="mk-hint">Первые пять товаров нового продавца проверяет модератор. Товар появляется в каталоге, когда склад примет поставку.</p>
        </>
    );
}

function Supplies({ state }: { state: SellerState }) {
    const [open, setOpen] = useState(false);

    function create(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();

        const form = new FormData(event.currentTarget);
        const quantity = Number(form.get('quantity'));
        const date = String(form.get('date'));

        if (!quantity || !date) return;

        seller.set({
            ...state,
            supplies: [
                { id: `П-${String(35 + state.supplies.length).padStart(4, '0')}`, date, productId: Number(form.get('product')), quantity, accepted: null, status: 'planned' },
                ...state.supplies,
            ],
        });
        setOpen(false);
    }

    /** Демо: склад принял поставку целиком — остаток вырос, товар вышел в продажу. */
    function accept(id: string) {
        const supply = state.supplies.find((s) => s.id === id);

        if (!supply) return;

        seller.set({
            ...state,
            supplies: state.supplies.map((s) => (s.id === id ? { ...s, accepted: s.quantity, status: 'accepted' } : s)),
            products: state.products.map((p) => (p.id === supply.productId ? { ...p, stock: p.stock + supply.quantity, status: 'live' } : p)),
        });
    }

    return (
        <>
            <div className="mk-bar">
                <h2>Поставки на склад</h2>
                <button type="button" className="mk-btn" onClick={() => setOpen(true)}>
                    <Plus size={18} aria-hidden /> Новая поставка
                </button>
            </div>

            {open && (
                <section className="mk-panel" style={{ marginBottom: 16, marginTop: 0 }}>
                    <h2>Заявка на поставку</h2>
                    <form className="mk-form mk-form--2" onSubmit={create}>
                        <label className="mk-field mk-field--wide">
                            Товар
                            <select id="mk-s-product" name="product">
                                {state.products.map((p) => (
                                    <option key={p.id} value={p.id}>
                                        {p.title}
                                    </option>
                                ))}
                            </select>
                        </label>
                        <label className="mk-field">
                            Количество, шт.
                            <input id="mk-s-quantity" name="quantity" type="number" min={1} required />
                        </label>
                        <label className="mk-field">
                            Когда привезёте
                            <input id="mk-s-date" name="date" type="date" required />
                        </label>
                        <div className="mk-field--wide" style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                            <button type="submit" className="mk-btn">
                                Создать заявку
                            </button>
                            <button type="button" className="mk-btn mk-btn--ghost" onClick={() => setOpen(false)}>
                                Отмена
                            </button>
                        </div>
                    </form>
                    <p className="mk-hint">Склад BTS в Ташкенте принимает товар по заявке: пересчитывает, отмечает брак — и остаток становится доступен к продаже.</p>
                </section>
            )}

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
                            <th />
                        </tr>
                    </thead>
                    <tbody>
                        {state.supplies.map((s) => (
                            <tr key={s.id}>
                                <td>{s.id}</td>
                                <td>{day(s.date)}</td>
                                <td>{state.products.find((p) => p.id === s.productId)?.title ?? '—'}</td>
                                <td className="is-num">{s.quantity}</td>
                                <td className="is-num">{s.accepted ?? '—'}</td>
                                <td>
                                    {s.status === 'planned' && <span className="mk-pill mk-pill--warn">Ждём на складе</span>}
                                    {s.status === 'accepted' && <span className="mk-pill mk-pill--ok">Принята</span>}
                                    {s.status === 'partial' && <span className="mk-pill">Принята частично: брак {s.quantity - (s.accepted ?? 0)}</span>}
                                </td>
                                <td>
                                    {s.status === 'planned' && (
                                        <button type="button" className="mk-demo-btn" onClick={() => accept(s.id)}>
                                            Демо: склад принял
                                        </button>
                                    )}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </>
    );
}

function Stock({ state }: { state: SellerState }) {
    return (
        <>
            <div className="mk-bar">
                <h2>Остатки на складе</h2>
            </div>
            <div className="mk-table-wrap">
                <table className="mk-table">
                    <thead>
                        <tr>
                            <th>Товар</th>
                            <th className="is-num">На складе</th>
                            <th className="is-num">В резерве</th>
                            <th className="is-num">Доступно</th>
                            <th />
                        </tr>
                    </thead>
                    <tbody>
                        {state.products.map((p) => {
                            const free = Math.max(0, p.stock - p.reserved);

                            return (
                                <tr key={p.id}>
                                    <td>
                                        <div className="mk-table__item">
                                            <span aria-hidden>{p.emoji}</span>
                                            {p.title}
                                        </div>
                                    </td>
                                    <td className="is-num">{p.stock}</td>
                                    <td className="is-num">{Math.min(p.reserved, p.stock)}</td>
                                    <td className={cn('is-num', free < 10 && 'mk-low')}>{free}</td>
                                    <td>{free === 0 ? 'Нет в продаже — нужна поставка' : free < 10 ? 'Заканчивается' : ''}</td>
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
            </div>
            <p className="mk-hint">В резерве — товар под оформленные заказы. Купить можно только «доступно»: остаток не уходит в минус.</p>
        </>
    );
}

function Orders() {
    return (
        <>
            <div className="mk-bar">
                <h2>Заказы с вашими товарами</h2>
            </div>
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
                        {SELLER_ORDERS.map((o) => (
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
            <p className="mk-hint">Собирает и выдаёт заказ склад и пункт выдачи. Телефон покупателя продавцу не показывается — только имя и номер заказа.</p>
        </>
    );
}

function Payouts() {
    return (
        <>
            <div className="mk-bar">
                <h2>Начисления</h2>
                <span className="mk-pill">Комиссия площадки {COMMISSION}%</span>
            </div>
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
            <p className="mk-hint">
                Начисление появляется, когда заказ выдан покупателю. Выплаты пока проводит касса площадки вручную; процент комиссии в демо
                условный.
            </p>
        </>
    );
}
