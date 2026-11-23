import { useState } from 'react';
import { ScreenLoad, Stepper } from '@/components/market/staff/Picking';
import { cn } from '@/lib/cn';
import { SampleNote } from '@/layouts/StaffLayout';
import { lang, marketLocale } from '@/market/lang';
import { when } from '@/market/orders';
import type { ReturnBatch, StaffStatus } from '@/market/staff/contract';
import { staffAction, useStaffData } from '@/market/staff/data';
import { hoursAgo } from '@/market/staff/samples';
import { staffText } from '@/market/text/staff';
import { returnsText } from '@/market/text/wh-returns';

type ReturnCode = ReturnBatch['status']['code'];

/** Разбор строки: годное и брак; остаток до количества — недостача. */
interface Count {
    good: number;
    defect: number;
}

const status = (code: ReturnCode): StaffStatus<ReturnCode> => ({ code, text: lang(returnsText).status[code] });

/** Образец GET warehouse/returns. Причина — текст с сервера на языке страницы. */
const sampleReturns = (): { batches: ReturnBatch[] } => {
    const ru = marketLocale() === 'ru';

    return {
        batches: [
            {
                number: 'V-0057',
                status: status('sent'),
                pickupPoint: { name: 'BTS Чиланзар' },
                orders: [
                    {
                        number: 'SX-23980',
                        reason: ru ? 'Не забрали за 7 дней' : '7 kun ichida olib ketilmadi',
                        items: [
                            { variantId: 101, title: 'Плед флисовый 150×200', options: 'Бежевый', sku: 'ST-PLD-150-BG', quantity: 1 },
                            { variantId: 140, title: 'Рюкзак городской 25 л', options: 'Серый', sku: 'ST-BP-25-GR', quantity: 1 },
                        ],
                    },
                    {
                        number: 'SX-24006',
                        reason: ru ? 'Отказ при получении: не тот цвет' : 'Olishda rad etildi: rangi boshqa',
                        items: [{ variantId: 210, title: 'Наушники беспроводные', options: 'Чёрные', sku: 'TM-HP-BT5-BK', quantity: 2 }],
                    },
                ],
                sentAt: hoursAgo(6),
            },
            {
                number: 'V-0051',
                status: status('received'),
                pickupPoint: { name: 'BTS Юнусабад' },
                orders: [
                    {
                        number: 'SX-23911',
                        reason: ru ? 'Отказ при получении: вмятина на корпусе' : 'Olishda rad etildi: korpusida pachoq',
                        items: [{ variantId: 205, title: 'Чайник электрический 1,7 л', options: '', sku: 'TM-KTL-17', quantity: 1 }],
                    },
                ],
                sentAt: hoursAgo(50),
            },
        ],
    };
};

const key = (order: string, variantId: number) => `${order}:${variantId}`;

/**
 * Склад, «Возвраты»: партии из пунктов — невостребованное за 7 дней и отказы
 * (решение 23.11). Едущую партию принимаем построчно: сколько годно (по
 * умолчанию всё), сколько брак; годное — снова в остаток, брак ждёт вывоза
 * продавцом.
 */
export function Returns() {
    const L = lang(returnsText);
    const S = lang(staffText);
    const returns = useStaffData<{ batches: ReturnBatch[] }>('warehouse/returns', sampleReturns);
    const [counts, setCounts] = useState<Record<string, Count>>({});
    const [busy, setBusy] = useState<string | null>(null);
    const batches = [...(returns.data?.batches ?? [])].sort((a, b) => Number(a.status.code === 'received') - Number(b.status.code === 'received'));

    const countOf = (order: string, variantId: number, quantity: number): Count => counts[key(order, variantId)] ?? { good: quantity, defect: 0 };

    // Годное и брак не больше количества: прибавили одно — другое уступает
    function set(order: string, variantId: number, quantity: number, field: keyof Count, value: number) {
        const current = countOf(order, variantId, quantity);
        const other: keyof Count = field === 'good' ? 'defect' : 'good';

        setCounts({ ...counts, [key(order, variantId)]: { ...current, [field]: value, [other]: Math.min(current[other], quantity - value) } as Count });
    }

    async function receive(batch: ReturnBatch) {
        const items = batch.orders.flatMap((order) => order.items.map((item) => ({ order: order.number, variantId: item.variantId, ...countOf(order.number, item.variantId, item.quantity) })));
        const good = items.reduce((total, item) => total + item.good, 0);
        const defect = items.reduce((total, item) => total + item.defect, 0);
        const quantity = batch.orders.reduce((total, order) => total + order.items.reduce((sum, item) => sum + item.quantity, 0), 0);

        if (quantity > good + defect && !window.confirm(L.confirmShort(quantity - good - defect))) return;
        if (quantity === good + defect && !window.confirm(L.confirmReceive(batch.number, good, defect))) return;

        setBusy(batch.number);

        const result = await staffAction(`warehouse/returns/${batch.number}/receive`, { items }, returns.sample, S.sampleDone);

        setBusy(null);

        if (result === null) return;

        returns.patch((d) => ({ batches: d.batches.map((b) => (b.number === batch.number ? { ...b, status: status('received') } : b)) }));
    }

    return (
        <>
            <SampleNote show={returns.sample} />
            <div className="mk-bar">
                <h2>{L.title}</h2>
            </div>
            <ScreenLoad data={returns} />
            {returns.data && batches.length === 0 && (
                <div className="mk-empty">
                    <span aria-hidden>↩️</span>
                    <h2>{L.emptyTitle}</h2>
                    <p>{L.emptyText}</p>
                </div>
            )}
            <div className="mk-wh2-stack">
                {batches.map((batch) => {
                    const open = batch.status.code === 'sent';
                    let good = 0;
                    let defect = 0;

                    return (
                        <article key={batch.number} className={cn('mk-wh2-card', !open && 'is-done')}>
                            <div className="mk-wh2-card__hd">
                                <div>
                                    <h3>{batch.number}</h3>
                                    <span className="mk-muted">
                                        {L.from(batch.pickupPoint.name)}
                                        {batch.sentAt && ` · ${L.sentAt(when(batch.sentAt))}`}
                                    </span>
                                </div>
                                <span className={cn('mk-pill', open ? 'mk-pill--warn' : 'mk-pill--ok')}>{batch.status.text}</span>
                            </div>
                            {batch.orders.map((order) => (
                                <div key={order.number} className="mk-wh2-return">
                                    <p>
                                        <b>{order.number}</b> <span className="mk-muted">{order.reason}</span>
                                    </p>
                                    <ul className="mk-wh2-lines">
                                        {order.items.map((item) => {
                                            const count = countOf(order.number, item.variantId, item.quantity);
                                            const short = item.quantity - count.good - count.defect;

                                            good += count.good;
                                            defect += count.defect;

                                            return (
                                                <li key={item.variantId} className="mk-wh2-line mk-wh2-line--return">
                                                    <span className="mk-wh2-line__name">
                                                        <b>{item.title}</b>
                                                        {(item.options || item.sku) && <small>{[item.options, item.sku].filter(Boolean).join(' · ')}</small>}
                                                        {open && short > 0 && <small className="mk-low">{L.short(short)}</small>}
                                                    </span>
                                                    <span className="mk-wh2-qty">{S.pcs(item.quantity)}</span>
                                                    {open && (
                                                        <span className="mk-wh2-split">
                                                            <span>
                                                                <span>{L.good}</span>
                                                                <Stepper value={count.good} min={0} max={item.quantity} label={`${L.good}, ${item.title}`} onChange={(v) => set(order.number, item.variantId, item.quantity, 'good', v)} />
                                                            </span>
                                                            <span className="is-defect">
                                                                <span>{L.defect}</span>
                                                                <Stepper value={count.defect} min={0} max={item.quantity} label={`${L.defect}, ${item.title}`} onChange={(v) => set(order.number, item.variantId, item.quantity, 'defect', v)} />
                                                            </span>
                                                        </span>
                                                    )}
                                                </li>
                                            );
                                        })}
                                    </ul>
                                </div>
                            ))}
                            {open && (
                                <div className="mk-wh2-actions">
                                    <span className="mk-wh2-big">{L.totals(good, defect)}</span>
                                    <button type="button" className="mk-btn mk-btn--big" disabled={busy !== null} onClick={() => void receive(batch)}>
                                        {L.receive}
                                    </button>
                                </div>
                            )}
                        </article>
                    );
                })}
            </div>
            <p className="mk-hint">{L.hint}</p>
        </>
    );
}
