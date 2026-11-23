import { useState } from 'react';
import { ScreenLoad } from '@/components/market/staff/Picking';
import { cn } from '@/lib/cn';
import { SampleNote } from '@/layouts/StaffLayout';
import { lang } from '@/market/lang';
import { when } from '@/market/orders';
import type { Removal, StaffStatus } from '@/market/staff/contract';
import { staffAction, useStaffData } from '@/market/staff/data';
import { hoursAgo } from '@/market/staff/samples';
import { staffText } from '@/market/text/staff';
import { removalsText } from '@/market/text/wh-removals';

type RemovalCode = Removal['status']['code'];

const TONE: Record<RemovalCode, string> = { requested: 'mk-pill--warn', ready: '', done: 'mk-pill--ok', cancelled: 'mk-pill--off' };

const status = (code: RemovalCode): StaffStatus<RemovalCode> => ({ code, text: lang(removalsText).status[code] });

/** Образец GET warehouse/removals. */
const sampleRemovals = (): { removals: Removal[] } => ({
    removals: [
        {
            number: 'W-0031',
            status: status('requested'),
            seller: { name: 'Texnomir' },
            items: [
                { variantId: 205, title: 'Чайник электрический 1,7 л', options: '', sku: 'TM-KTL-17', cell: 'Z-01-1', quantity: 2, kind: 'defect' },
                { variantId: 230, title: 'Казан чугунный 12 л', options: '', sku: 'TM-KZN-12', cell: 'D-02-4', quantity: 3, kind: 'good' },
            ],
            requestedAt: hoursAgo(2),
            doneAt: null,
        },
        {
            number: 'W-0029',
            status: status('ready'),
            seller: { name: 'Samarqand Tekstil' },
            items: [
                { variantId: 101, title: 'Плед флисовый 150×200', options: 'Бежевый', sku: 'ST-PLD-150-BG', cell: 'Z-01-3', quantity: 1, kind: 'defect' },
                { variantId: 140, title: 'Рюкзак городской 25 л', options: 'Серый', sku: 'ST-BP-25-GR', cell: 'Z-01-3', quantity: 1, kind: 'defect' },
            ],
            requestedAt: hoursAgo(26),
            doneAt: null,
        },
        {
            number: 'W-0024',
            status: status('done'),
            seller: { name: 'Texnomir' },
            items: [{ variantId: 210, title: 'Наушники беспроводные', options: 'Чёрные', sku: 'TM-HP-BT5-BK', cell: null, quantity: 4, kind: 'good' }],
            requestedAt: hoursAgo(96),
            doneAt: hoursAgo(72),
        },
    ],
});

/**
 * Склад, «Вывоз»: заявки продавцов забрать годный остаток или брак (брак
 * ждёт вывоза на складе, решение 23.11). Новая заявка — собрать и нажать
 * «Собрано, ждёт продавца»; продавец приехал — «Выдано продавцу».
 */
export function Removals() {
    const L = lang(removalsText);
    const S = lang(staffText);
    const removals = useStaffData<{ removals: Removal[] }>('warehouse/removals', sampleRemovals);
    const [busy, setBusy] = useState<string | null>(null);
    const all = removals.data?.removals ?? [];
    const active = all.filter((r) => r.status.code === 'requested' || r.status.code === 'ready');
    const history = all.filter((r) => r.status.code === 'done' || r.status.code === 'cancelled');

    async function act(removal: Removal, action: 'ready' | 'done') {
        if (action === 'done' && !window.confirm(L.confirmDone(removal.number, removal.seller.name))) return;

        setBusy(removal.number);

        const result = await staffAction(`warehouse/removals/${removal.number}/${action}`, {}, removals.sample, S.sampleDone);

        setBusy(null);

        if (result === null) return;

        removals.patch((d) => ({
            removals: d.removals.map((r) => (r.number === removal.number ? { ...r, status: status(action), doneAt: action === 'done' ? new Date().toISOString() : r.doneAt } : r)),
        }));
    }

    const card = (removal: Removal) => (
        <article key={removal.number} className={cn('mk-wh2-card', (removal.status.code === 'done' || removal.status.code === 'cancelled') && 'is-done')}>
            <div className="mk-wh2-card__hd">
                <div>
                    <h3>{removal.number}</h3>
                    <span className="mk-muted">{removal.doneAt ? L.doneAt(when(removal.doneAt)) : L.requestedAt(when(removal.requestedAt))}</span>
                </div>
                <span className={cn('mk-pill', TONE[removal.status.code])}>{removal.status.text}</span>
            </div>
            <p className="mk-wh2-point">{removal.seller.name}</p>
            <ul className="mk-wh2-lines">
                {removal.items.map((item) => (
                    <li key={`${item.variantId}:${item.kind}`} className="mk-wh2-line">
                        <span className="mk-wh2-line__name">
                            <b>{item.title}</b>
                            {(item.options || item.sku) && <small>{[item.options, item.sku].filter(Boolean).join(' · ')}</small>}
                        </span>
                        <span className={cn('mk-pill', item.kind === 'defect' ? 'mk-pill--warn' : 'mk-pill--ok')}>{L.kind[item.kind]}</span>
                        <span className={cn('mk-wh2-cell', !item.cell && 'is-none')}>{item.cell ?? '—'}</span>
                        <span className="mk-wh2-qty">{S.pcs(item.quantity)}</span>
                    </li>
                ))}
            </ul>
            {removal.status.code === 'requested' && (
                <div className="mk-wh2-actions">
                    <button type="button" className="mk-btn mk-btn--big" disabled={busy !== null} onClick={() => void act(removal, 'ready')}>
                        {L.ready}
                    </button>
                </div>
            )}
            {removal.status.code === 'ready' && (
                <div className="mk-wh2-actions">
                    <button type="button" className="mk-btn mk-btn--big" disabled={busy !== null} onClick={() => void act(removal, 'done')}>
                        {L.done}
                    </button>
                </div>
            )}
        </article>
    );

    return (
        <>
            <SampleNote show={removals.sample} />
            <div className="mk-bar">
                <h2>{L.title}</h2>
            </div>
            <ScreenLoad data={removals} />
            {removals.data && active.length === 0 && (
                <div className="mk-empty">
                    <span aria-hidden>🚚</span>
                    <h2>{L.emptyTitle}</h2>
                    <p>{L.emptyText}</p>
                </div>
            )}
            {active.length > 0 && (
                <section className="mk-wh2-section">
                    <h3>{L.active}</h3>
                    <div className="mk-wh2-list">{active.map(card)}</div>
                </section>
            )}
            {history.length > 0 && (
                <section className="mk-wh2-section">
                    <h3>{L.history}</h3>
                    <div className="mk-wh2-list">{history.map(card)}</div>
                </section>
            )}
            <p className="mk-hint">{L.hint}</p>
        </>
    );
}
