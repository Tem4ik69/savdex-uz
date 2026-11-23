import { AlertTriangle, ChevronDown, ChevronUp, PackageCheck } from 'lucide-react';
import { useState } from 'react';
import { SampleNote } from '@/layouts/StaffLayout';
import { cn } from '@/lib/cn';
import { lang } from '@/market/lang';
import { when } from '@/market/orders';
import type { PointBatch } from '@/market/staff/contract';
import { staffAction, useStaffData } from '@/market/staff/data';
import { hoursAgo } from '@/market/staff/samples';
import { ptBatchesText } from '@/market/text/pt-batches';
import { staffText } from '@/market/text/staff';

interface Batches {
    batches: PointBatch[];
}

const sampleBatches = (): Batches => ({
    batches: [
        {
            number: 'PT2611A4',
            status: { code: 'sent', text: 'В пути' },
            orders: [
                { number: 'K7M2PX9QAD', places: 2, problem: null },
                { number: 'R4TW8HN3EB', places: 1, problem: null },
                { number: 'H3DK7Q2WXN', places: 1, problem: null },
                { number: 'B8NP4TZ6JC', places: 3, problem: null },
            ],
            sentAt: hoursAgo(3),
            deliveredAt: null,
        },
        {
            number: 'PT2211F9',
            status: { code: 'delivered', text: 'Принята' },
            orders: [
                { number: 'Z9CF6VJ2LM', places: 3, problem: null },
                { number: 'M5QX2RL8TE', places: 1, problem: 'Коробка помята, товар цел' },
            ],
            sentAt: hoursAgo(28),
            deliveredAt: hoursAgo(24),
        },
        {
            number: 'PT2011C2',
            status: { code: 'delivered', text: 'Принята' },
            orders: [{ number: 'W7JH3NA9PK', places: 2, problem: null }],
            sentAt: hoursAgo(76),
            deliveredAt: hoursAgo(72),
        },
    ],
});

const placesOf = (batch: PointBatch): number => batch.orders.reduce((total, o) => total + o.places, 0);

/**
 * «Принять партию» (пункт выдачи): партии со склада — сначала те, что в
 * пути. Сотрудник сверяет коробки с наклейками, отмечает проблемные
 * (нет коробки, повреждена) и принимает партию: остальные заказы сразу
 * «можно забрать». Принятые — свёрнутой историей.
 */
export function Batches() {
    const L = lang(ptBatchesText);
    const S = lang(staffText);
    const data = useStaffData<Batches>('point/batches', sampleBatches);
    const [open, setOpen] = useState<string | null>(null);

    const batches = data.data?.batches ?? [];
    const sent = batches.filter((b) => b.status.code === 'sent');
    const delivered = batches.filter((b) => b.status.code !== 'sent');

    return (
        <div className="mk-pt">
            <SampleNote show={data.sample} />
            <h2 className="mk-pt__title">{L.title}</h2>

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

            {data.data && sent.length === 0 && (
                <div className="mk-empty">
                    <span aria-hidden>🚚</span>
                    <h2>{L.emptyTitle}</h2>
                    <p>{L.emptyText}</p>
                </div>
            )}

            {sent.map((batch) => (
                <section key={batch.number} className={cn('mk-pt-card', open === batch.number && 'is-open')}>
                    <button type="button" className="mk-pt-card__hd" aria-expanded={open === batch.number} onClick={() => setOpen(open === batch.number ? null : batch.number)}>
                        <span>
                            <b>{L.batch(batch.number)}</b>
                            <small>
                                {batch.sentAt ? L.sentAt(when(batch.sentAt)) : batch.status.text} · {L.summary(batch.orders.length, placesOf(batch))}
                            </small>
                        </span>
                        <span className="mk-pt-card__go">
                            {open === batch.number ? L.close : L.open} {open === batch.number ? <ChevronUp size={18} aria-hidden /> : <ChevronDown size={18} aria-hidden />}
                        </span>
                    </button>
                    {open === batch.number && (
                        <AcceptForm
                            batch={batch}
                            sample={data.sample}
                            onAccepted={(problems) => {
                                setOpen(null);
                                data.patch((current) => ({
                                    batches: current.batches.map((b) =>
                                        b.number === batch.number
                                            ? {
                                                  ...b,
                                                  status: { code: 'delivered', text: L.statusDelivered },
                                                  deliveredAt: new Date().toISOString(),
                                                  orders: b.orders.map((o) => ({ ...o, problem: problems[o.number] ?? null })),
                                              }
                                            : b,
                                    ),
                                }));
                            }}
                        />
                    )}
                </section>
            ))}

            {delivered.length > 0 && (
                <details className="mk-pt-history">
                    <summary>{L.history(delivered.length)}</summary>
                    <ul>
                        {delivered.map((batch) => {
                            const problems = batch.orders.filter((o) => o.problem);

                            return (
                                <li key={batch.number}>
                                    <div>
                                        <b>{L.batch(batch.number)}</b>
                                        <small>
                                            {batch.deliveredAt ? L.deliveredAt(when(batch.deliveredAt)) : batch.status.text} · {L.summary(batch.orders.length, placesOf(batch))}
                                        </small>
                                    </div>
                                    {problems.length === 0 ? (
                                        <span className="mk-pill mk-pill--ok">{L.noProblems}</span>
                                    ) : (
                                        problems.map((o) => (
                                            <small key={o.number} className="mk-low">
                                                {o.number}: {L.problemShort(o.problem ?? '')}
                                            </small>
                                        ))
                                    )}
                                </li>
                            );
                        })}
                    </ul>
                </details>
            )}
        </div>
    );
}

/** Сверка партии: по каждому заказу — «всё в порядке» или «проблема» с описанием. */
function AcceptForm({ batch, sample, onAccepted }: { batch: PointBatch; sample: boolean; onAccepted: (problems: Record<string, string>) => void }) {
    const L = lang(ptBatchesText);
    const S = lang(staffText);
    /** Номер заказа → описание проблемы; нет ключа — всё в порядке */
    const [problems, setProblems] = useState<Record<string, string>>({});
    const [missing, setMissing] = useState<string[]>([]);
    const [busy, setBusy] = useState(false);
    const marked = Object.keys(problems);

    function toggle(order: string) {
        setProblems((current) => {
            const next = { ...current };

            if (order in next) delete next[order];
            else next[order] = '';

            return next;
        });
        setMissing((list) => list.filter((n) => n !== order));
    }

    async function accept() {
        const empty = marked.filter((n) => !problems[n].trim());

        setMissing(empty);

        if (empty.length > 0) return;

        setBusy(true);

        const list = marked.map((order) => ({ order, note: problems[order].trim() }));
        const result = await staffAction(`point/batches/${batch.number}/accept`, { problems: list }, sample, S.sampleDone);

        setBusy(false);

        if (result !== null) onAccepted(Object.fromEntries(list.map((p) => [p.order, p.note])));
    }

    return (
        <div className="mk-pt-card__body">
            <p className="mk-pt-hint">{L.checkHint}</p>
            <ul className="mk-pt-checklist">
                {batch.orders.map((o) => {
                    const problem = o.number in problems;

                    return (
                        <li key={o.number} className={cn(problem && 'is-problem')}>
                            <div className="mk-pt-checklist__row">
                                <span>
                                    <b>{o.number}</b>
                                    <small>{S.places(o.places)}</small>
                                </span>
                                <button type="button" className={cn('mk-pt-toggle', problem && 'is-on')} aria-pressed={problem} onClick={() => toggle(o.number)}>
                                    {problem ? <AlertTriangle size={18} aria-hidden /> : <PackageCheck size={18} aria-hidden />} {problem ? L.problem : L.problemOff}
                                </button>
                            </div>
                            {problem && (
                                <label className="mk-field">
                                    {L.problemLabel}
                                    <input
                                        value={problems[o.number]}
                                        onChange={(e) => setProblems((current) => ({ ...current, [o.number]: e.target.value }))}
                                        maxLength={300}
                                        placeholder={L.problemPlaceholder}
                                        aria-invalid={missing.includes(o.number)}
                                        autoFocus
                                    />
                                    {missing.includes(o.number) && <small className="is-error">{L.problemRequired}</small>}
                                </label>
                            )}
                        </li>
                    );
                })}
            </ul>
            <button type="button" className="mk-btn mk-btn--big mk-btn--block" disabled={busy} onClick={() => void accept()}>
                {marked.length > 0 ? L.acceptWith(marked.length) : L.accept}
            </button>
            <p className="mk-pt-hint">{L.acceptHint}</p>
        </div>
    );
}
