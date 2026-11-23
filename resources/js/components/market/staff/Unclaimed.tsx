import { Undo2 } from 'lucide-react';
import { useState } from 'react';
import { SampleNote } from '@/layouts/StaffLayout';
import { cn } from '@/lib/cn';
import { lang } from '@/market/lang';
import { when } from '@/market/orders';
import type { UnclaimedOrder } from '@/market/staff/contract';
import { staffAction, useStaffData } from '@/market/staff/data';
import { hoursAgo } from '@/market/staff/samples';
import { ptUnclaimedText } from '@/market/text/pt-unclaimed';
import { staffText } from '@/market/text/staff';

interface Unclaimed {
    orders: UnclaimedOrder[];
}

const sampleUnclaimed = (): Unclaimed => ({
    orders: [
        { number: 'D4XK8MP2RT', places: 1, reason: { code: 'expired', text: 'Не забрали за 7 дней' }, readyAt: hoursAgo(24 * 7 + 5), returnBatch: null },
        { number: 'N6TQ3HW9ZB', places: 2, reason: { code: 'expired', text: 'Не забрали за 7 дней' }, readyAt: hoursAgo(24 * 8), returnBatch: null },
        { number: 'F2JL7VC5QE', places: 1, reason: { code: 'refused', text: 'Отказ при получении' }, readyAt: hoursAgo(26), returnBatch: null },
        { number: 'Y8BR4GN6KA', places: 3, reason: { code: 'expired', text: 'Не забрали за 7 дней' }, readyAt: hoursAgo(24 * 9), returnBatch: 'RT2111B7' },
    ],
});

/** Номер возвратной партии в образце — на настоящих данных его даёт сервер. */
const sampleBatchNumber = (): string => `RT${Date.now().toString(36).slice(-6).toUpperCase()}`;

/**
 * «Невостребованные» (пункт выдачи): не забрали за 7 дней и отказы при
 * получении. Сотрудник отмечает коробки и собирает возвратную партию на
 * склад; заказы, уже лежащие в возвратной партии, показаны с её номером.
 */
export function Unclaimed() {
    const L = lang(ptUnclaimedText);
    const S = lang(staffText);
    const data = useStaffData<Unclaimed>('point/unclaimed', sampleUnclaimed);
    const [chosen, setChosen] = useState<string[]>([]);
    const [busy, setBusy] = useState(false);

    const orders = data.data?.orders ?? [];
    const free = orders.filter((o) => o.returnBatch === null);
    // Отметки — только у тех, что ещё не в партии (после перечитывания могли уйти)
    const picked = chosen.filter((n) => free.some((o) => o.number === n));
    const all = free.length > 0 && picked.length === free.length;

    function toggle(number: string) {
        setChosen((list) => (list.includes(number) ? list.filter((n) => n !== number) : [...list, number]));
    }

    async function create() {
        if (picked.length === 0 || !window.confirm(L.confirm(picked.length))) return;

        setBusy(true);

        const result = await staffAction('point/returns/create', { orders: picked }, data.sample, S.sampleDone);

        setBusy(false);

        if (result === null) return;

        const batch = sampleBatchNumber();

        setChosen([]);
        data.patch((current) => ({ orders: current.orders.map((o) => (picked.includes(o.number) ? { ...o, returnBatch: batch } : o)) }));
    }

    return (
        <div className="mk-pt">
            <SampleNote show={data.sample} />
            <h2 className="mk-pt__title">{L.title}</h2>
            <p className="mk-pt-hint">{L.intro}</p>

            {data.loading && <p className="mk-pt-hint">{S.loading}</p>}
            {data.error && (
                <div className="mk-failed">
                    <h2>{S.failed}</h2>
                    <p>{data.error}</p>
                    <button type="button" className="mk-btn" onClick={data.reload}>
                        {S.retry}
                    </button>
                </div>
            )}

            {data.data && orders.length === 0 && (
                <div className="mk-empty">
                    <span aria-hidden>📦</span>
                    <h2>{L.emptyTitle}</h2>
                    <p>{L.emptyText}</p>
                </div>
            )}

            {free.length > 1 && (
                <button type="button" className="mk-pt-link" onClick={() => setChosen(all ? [] : free.map((o) => o.number))}>
                    {all ? L.selectNone : L.selectAll}
                </button>
            )}

            {orders.length > 0 && (
                <ul className="mk-pt-list">
                    {orders.map((o) => {
                        const inBatch = o.returnBatch !== null;
                        const body = (
                            <>
                                <span className="mk-pt-list__main">
                                    <b>{o.number}</b>
                                    <small>
                                        {S.places(o.places)}
                                        {o.readyAt && ` · ${L.readyAt(when(o.readyAt))}`}
                                    </small>
                                </span>
                                <span className={cn('mk-pill', o.reason.code === 'refused' ? 'mk-pill--off' : 'mk-pill--warn')}>{o.reason.text}</span>
                                {inBatch && <span className="mk-pt-list__batch">{L.inBatch(o.returnBatch ?? '')}</span>}
                            </>
                        );

                        return (
                            <li key={o.number} className={cn(inBatch && 'is-done')}>
                                {inBatch ? (
                                    <div className="mk-pt-list__row">{body}</div>
                                ) : (
                                    <label className="mk-pt-list__row">
                                        <input type="checkbox" checked={picked.includes(o.number)} onChange={() => toggle(o.number)} />
                                        {body}
                                    </label>
                                )}
                            </li>
                        );
                    })}
                </ul>
            )}

            {free.length > 0 && (
                <div className="mk-pt-sticky">
                    <button type="button" className="mk-btn mk-btn--big mk-btn--block" disabled={busy || picked.length === 0} onClick={() => void create()}>
                        <Undo2 size={20} aria-hidden /> {L.create(picked.length)}
                    </button>
                    {picked.length === 0 && <p className="mk-pt-hint">{L.createHint}</p>}
                </div>
            )}
        </div>
    );
}
