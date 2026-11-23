import { Check, Minus, Plus } from 'lucide-react';
import { useState } from 'react';
import { cn } from '@/lib/cn';
import { SampleNote } from '@/layouts/StaffLayout';
import { lang } from '@/market/lang';
import { when } from '@/market/orders';
import type { PickingOrder, StaffStatus } from '@/market/staff/contract';
import { staffAction, useStaffData, type StaffData } from '@/market/staff/data';
import { hoursAgo } from '@/market/staff/samples';
import { staffText } from '@/market/text/staff';
import { pickingText } from '@/market/text/wh-picking';

type PickingCode = PickingOrder['status']['code'];

// Сначала то, что уже в руках, потом новое, собранное — в конце
const ORDER: Record<PickingCode, number> = { assembling: 0, paid: 1, assembled: 2 };
const TONE: Record<PickingCode, string> = { paid: 'mk-pill--warn', assembling: '', assembled: 'mk-pill--ok' };

const status = (code: PickingCode): StaffStatus<PickingCode> => ({ code, text: lang(pickingText).status[code] });

/** Образец ответа GET warehouse/picking — пока адреса нет. */
const samplePicking = (): { orders: PickingOrder[] } => ({
    orders: [
        {
            number: 'SX-24117',
            status: status('paid'),
            pickupPoint: { code: 'demo-chilanzar', name: 'BTS Чиланзар' },
            items: [
                { variantId: 101, title: 'Плед флисовый 150×200', options: 'Бежевый', sku: 'ST-PLD-150-BG', cell: 'A-03-2', quantity: 2 },
                { variantId: 205, title: 'Чайник электрический 1,7 л', options: '', sku: 'TM-KTL-17', cell: 'C-11-1', quantity: 1 },
            ],
            createdAt: hoursAgo(3),
        },
        {
            number: 'SX-24109',
            status: status('assembling'),
            pickupPoint: { code: 'demo-yunusabad', name: 'BTS Юнусабад' },
            items: [
                { variantId: 210, title: 'Наушники беспроводные', options: 'Чёрные', sku: 'TM-HP-BT5-BK', cell: 'C-04-3', quantity: 1 },
                { variantId: 140, title: 'Рюкзак городской 25 л', options: 'Серый', sku: 'ST-BP-25-GR', cell: 'B-07-1', quantity: 1 },
                { variantId: 102, title: 'Плед флисовый 150×200', options: 'Синий', sku: 'ST-PLD-150-BL', cell: 'A-03-3', quantity: 1 },
            ],
            createdAt: hoursAgo(5),
        },
        {
            number: 'SX-24121',
            status: status('paid'),
            pickupPoint: { code: 'demo-yunusabad', name: 'BTS Юнусабад' },
            items: [{ variantId: 230, title: 'Казан чугунный 12 л', options: '', sku: 'TM-KZN-12', cell: null, quantity: 1 }],
            createdAt: hoursAgo(1),
        },
        {
            number: 'SX-24098',
            status: status('assembled'),
            pickupPoint: { code: 'demo-chilanzar', name: 'BTS Чиланзар' },
            items: [{ variantId: 205, title: 'Чайник электрический 1,7 л', options: '', sku: 'TM-KTL-17', cell: 'C-11-1', quantity: 2 }],
            createdAt: hoursAgo(9),
        },
    ],
});

/**
 * Склад, «Сборка»: заказы к сборке по пунктам выдачи. «Начать сборку» —
 * строки становятся списком «положил — отметил» (отметки — только на этом
 * планшете), «Собрано» — когда отмечено всё, со счётом мест. Только заказ
 * целиком (решение 23.11): неполный заказ не собирается.
 */
export function Picking() {
    const L = lang(pickingText);
    const S = lang(staffText);
    const picking = useStaffData<{ orders: PickingOrder[] }>('warehouse/picking', samplePicking);
    const [point, setPoint] = useState<string | null>(null);
    const [ticks, setTicks] = useState<Record<string, number[]>>({});
    const [asking, setAsking] = useState<string | null>(null);
    const [places, setPlaces] = useState(1);
    const [busy, setBusy] = useState<string | null>(null);
    const orders = picking.data?.orders ?? [];
    const points = [...new Map(orders.map((o) => [o.pickupPoint.code, o.pickupPoint.name])).entries()];
    const shown = orders.filter((o) => point === null || o.pickupPoint.code === point).sort((a, b) => ORDER[a.status.code] - ORDER[b.status.code]);

    function tick(order: string, variantId: number) {
        const current = ticks[order] ?? [];

        setTicks({ ...ticks, [order]: current.includes(variantId) ? current.filter((id) => id !== variantId) : [...current, variantId] });
    }

    async function start(order: PickingOrder) {
        setBusy(order.number);

        const result = await staffAction(`warehouse/picking/${order.number}/start`, {}, picking.sample, S.sampleDone);

        setBusy(null);

        if (result === null) return;

        picking.patch((d) => ({ orders: d.orders.map((o) => (o.number === order.number ? { ...o, status: status('assembling') } : o)) }));
    }

    async function done(order: PickingOrder) {
        setBusy(order.number);

        const result = await staffAction(`warehouse/picking/${order.number}/done`, { places }, picking.sample, S.sampleDone);

        setBusy(null);

        if (result === null) return;

        setAsking(null);
        setTicks((prev) => {
            const next = { ...prev };

            delete next[order.number];

            return next;
        });
        picking.patch((d) => ({ orders: d.orders.map((o) => (o.number === order.number ? { ...o, status: status('assembled') } : o)) }));
    }

    return (
        <>
            <SampleNote show={picking.sample} />
            <div className="mk-bar">
                <h2>{L.title}</h2>
            </div>
            <ScreenLoad data={picking} />
            {picking.data && orders.length === 0 && (
                <div className="mk-empty">
                    <span aria-hidden>📦</span>
                    <h2>{L.emptyTitle}</h2>
                    <p>{L.emptyText}</p>
                </div>
            )}
            {points.length > 1 && (
                <div className="mk-wh2-chips" role="group" aria-label={L.filterLabel}>
                    <button type="button" aria-pressed={point === null} onClick={() => setPoint(null)}>
                        {L.all} <span>{orders.length}</span>
                    </button>
                    {points.map(([code, name]) => (
                        <button key={code} type="button" aria-pressed={point === code} onClick={() => setPoint(code)}>
                            {name} <span>{orders.filter((o) => o.pickupPoint.code === code).length}</span>
                        </button>
                    ))}
                </div>
            )}
            <div className="mk-wh2-list">
                {shown.map((order) => {
                    const ticked = ticks[order.number] ?? [];
                    const count = order.items.filter((item) => ticked.includes(item.variantId)).length;
                    const all = count === order.items.length;
                    const collecting = order.status.code === 'assembling';

                    return (
                        <article key={order.number} className={cn('mk-wh2-card', order.status.code === 'assembled' && 'is-done')}>
                            <div className="mk-wh2-card__hd">
                                <div>
                                    <h3>{order.number}</h3>
                                    <span className="mk-muted">{L.created(when(order.createdAt))}</span>
                                </div>
                                <span className={cn('mk-pill', TONE[order.status.code])}>{order.status.text}</span>
                            </div>
                            <p className="mk-wh2-point">{L.point(order.pickupPoint.name)}</p>
                            <ul className="mk-wh2-lines">
                                {order.items.map((item) => {
                                    const on = ticked.includes(item.variantId) || order.status.code === 'assembled';
                                    const body = (
                                        <>
                                            {collecting && <span className="mk-wh2-check" aria-hidden>{on && <Check size={20} />}</span>}
                                            <span className="mk-wh2-line__name">
                                                <b>{item.title}</b>
                                                {(item.options || item.sku) && <small>{[item.options, item.sku].filter(Boolean).join(' · ')}</small>}
                                            </span>
                                            <span className={cn('mk-wh2-cell', !item.cell && 'is-none')}>{item.cell ?? L.noCell}</span>
                                            <span className="mk-wh2-qty">{S.pcs(item.quantity)}</span>
                                        </>
                                    );

                                    return (
                                        <li key={item.variantId}>
                                            {collecting ? (
                                                <button type="button" className={cn('mk-wh2-line', on && 'is-on')} aria-pressed={on} onClick={() => tick(order.number, item.variantId)}>
                                                    {body}
                                                </button>
                                            ) : (
                                                <div className="mk-wh2-line">{body}</div>
                                            )}
                                        </li>
                                    );
                                })}
                            </ul>
                            {collecting && (
                                <p className="mk-muted">
                                    {all ? '' : `${L.tickHint} `}
                                    {L.ticked(count, order.items.length)}
                                </p>
                            )}
                            {order.status.code === 'paid' && (
                                <div className="mk-wh2-actions">
                                    <button type="button" className="mk-btn mk-btn--big" disabled={busy !== null} onClick={() => void start(order)}>
                                        {L.start}
                                    </button>
                                </div>
                            )}
                            {collecting && asking !== order.number && (
                                <div className="mk-wh2-actions">
                                    <button
                                        type="button"
                                        className="mk-btn mk-btn--big"
                                        disabled={!all || busy !== null}
                                        title={all ? undefined : L.doneDisabled}
                                        onClick={() => {
                                            setPlaces(1);
                                            setAsking(order.number);
                                        }}
                                    >
                                        {L.done}
                                    </button>
                                </div>
                            )}
                            {collecting && asking === order.number && (
                                <div className="mk-wh2-ask">
                                    <b>{L.placesTitle}</b>
                                    <Stepper value={places} min={1} max={99} onChange={setPlaces} label={L.placesLabel} />
                                    <small className="mk-muted">{L.placesHint}</small>
                                    <div className="mk-wh2-actions">
                                        <button type="button" className="mk-btn mk-btn--big" disabled={busy !== null} onClick={() => void done(order)}>
                                            {L.placesConfirm}
                                        </button>
                                        <button type="button" className="mk-btn mk-btn--ghost mk-btn--big" onClick={() => setAsking(null)}>
                                            {S.cancel}
                                        </button>
                                    </div>
                                </div>
                            )}
                            {order.status.code === 'assembled' && <p className="mk-wh2-note">{L.readyNote}</p>}
                        </article>
                    );
                })}
            </div>
            <p className="mk-hint">{L.wholeHint}</p>
        </>
    );
}

/** Счётчик «− 3 +» под палец: места, годное и брак на возвратах. */
export function Stepper({ value, min, max, onChange, label }: { value: number; min: number; max: number; onChange: (value: number) => void; label: string }) {
    const L = lang(pickingText);

    return (
        <span className="mk-wh2-stepper" role="group" aria-label={label}>
            <button type="button" aria-label={`${label}: ${L.less}`} disabled={value <= min} onClick={() => onChange(Math.max(min, value - 1))}>
                <Minus size={20} aria-hidden />
            </button>
            <output aria-live="polite">{value}</output>
            <button type="button" aria-label={`${label}: ${L.more}`} disabled={value >= max} onClick={() => onChange(Math.min(max, value + 1))}>
                <Plus size={20} aria-hidden />
            </button>
        </span>
    );
}

/** Загрузка и сбой раздела склада: скелет, пока нет данных, и «Повторить». */
export function ScreenLoad({ data }: { data: Pick<StaffData<unknown>, 'data' | 'loading' | 'error' | 'reload'> }) {
    const S = lang(staffText);

    if (data.loading && !data.data) return <div className="mk-skel-block" style={{ height: 240 }} aria-busy aria-label={S.loading} />;

    if (!data.error) return null;

    return (
        <div className="mk-failed">
            <h2>{S.failed}</h2>
            <p>{data.error}</p>
            <button type="button" className="mk-btn" onClick={data.reload}>
                {S.retry}
            </button>
        </div>
    );
}
