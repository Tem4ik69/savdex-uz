import { usePage } from '@inertiajs/react';
import { Minus, Plus } from 'lucide-react';
import { useEffect, useState, type ReactNode } from 'react';
import { keepSampleSupplies, lineDiff, sampleSupplies } from '@/components/market/staff/suppliesSample';
import { SampleNote } from '@/layouts/StaffLayout';
import { cn } from '@/lib/cn';
import { dateText } from '@/market/format';
import { lang } from '@/market/lang';
import type { WarehouseSupply } from '@/market/staff/contract';
import { staffAction, useStaffData } from '@/market/staff/data';
import { staffText } from '@/market/text/staff';
import { whReceivingText } from '@/market/text/wh-receiving';
import { whSuppliesText } from '@/market/text/wh-supplies';

type Counts = Record<number, { accepted: number; defect: number }>;

const MAX = 99999;

/** Номер поставки из адреса: «Принять» на вкладке «Поставки» ведёт сюда с ?supply=. */
function supplyFromUrl(url: string): string | null {
    return new URLSearchParams(url.split('?')[1] ?? '').get('supply');
}

/** Убрать или поставить ?supply= в адресе, не перезагружая экран. */
function rememberSupply(number: string | null): void {
    const url = new URL(window.location.href);

    if (number) url.searchParams.set('supply', number);
    else url.searchParams.delete('supply');

    window.history.replaceState(window.history.state, '', url);
}

/**
 * Склад, «Приёмка»: выбрать поставку, которая ждёт, и пересчитать по факту —
 * по каждой строке «принято» и «брак» крупными +/−. Расхождение с заявкой
 * видно сразу и уходит продавцу (решение 23.11: принимаем факт). Отказ — с
 * причиной.
 */
export function Receiving() {
    const L = lang(whReceivingText);
    const S = lang(staffText);
    const { url } = usePage();
    // undefined — номер берём из адреса; null — выбрали «к списку»
    const [chosen, setChosen] = useState<string | null | undefined>(undefined);
    const list = useStaffData<{ supplies: WarehouseSupply[] }>('warehouse/supplies?status=submitted', sampleSupplies);
    const waiting = (list.data?.supplies ?? []).filter((supply) => supply.status.code === 'submitted');
    const number = chosen === undefined ? supplyFromUrl(url) : chosen;
    const supply = number ? (waiting.find((s) => s.number === number) ?? null) : null;

    function choose(next: string | null) {
        setChosen(next);
        rememberSupply(next);
        window.scrollTo({ top: 0 });
    }

    /** Поставку приняли или отказали: в образце — запомнить, на сервере — перечитать. */
    function done(changed: WarehouseSupply) {
        list.patch((current) => {
            const supplies = current.supplies.map((s) => (s.number === changed.number ? changed : s));

            if (list.sample) keepSampleSupplies(supplies);

            return { ...current, supplies };
        });
        choose(null);
    }

    if (supply) {
        return (
            <>
                <SampleNote show={list.sample} />
                <ReceiveForm key={supply.number} supply={supply} sample={list.sample} onBack={() => choose(null)} onDone={done} />
            </>
        );
    }

    return (
        <>
            <SampleNote show={list.sample} />
            <div className="mk-bar">
                <h2>{L.chooseTitle}</h2>
            </div>
            {number && list.data && <p className="mk-wh-warn">{L.notFound(number)}</p>}
            {list.loading && <div className="mk-skel-block" style={{ height: 160 }} aria-busy />}
            {list.error && (
                <div className="mk-failed">
                    <p>{list.error}</p>
                    <button type="button" className="mk-btn" onClick={list.reload}>
                        {S.retry}
                    </button>
                </div>
            )}
            {list.data && waiting.length === 0 && (
                <div className="mk-empty">
                    <span aria-hidden>📦</span>
                    <h2>{L.chooseEmpty}</h2>
                </div>
            )}
            {waiting.length > 0 && (
                <ul className="mk-wh-pick">
                    {waiting.map((s) => (
                        <li key={s.number}>
                            <button type="button" onClick={() => choose(s.number)}>
                                <b>{s.number}</b>
                                <span>{s.seller.name}</span>
                                <small>
                                    {L.lines(s.items.length)} · {L.units(s.items.reduce((total, item) => total + item.declared, 0))}
                                    {s.expectedAt && <> · {L.expected(dateText(new Date(s.expectedAt), false))}</>}
                                </small>
                            </button>
                        </li>
                    ))}
                </ul>
            )}
            <p className="mk-hint">{L.hint}</p>
        </>
    );
}

function ReceiveForm({ supply, sample, onBack, onDone }: { supply: WarehouseSupply; sample: boolean; onBack: () => void; onDone: (changed: WarehouseSupply) => void }) {
    const L = lang(whReceivingText);
    const S = lang(staffText);
    const statuses = lang(whSuppliesText).statuses;
    const [counts, setCounts] = useState<Counts>(() => Object.fromEntries(supply.items.map((item) => [item.itemId, { accepted: item.declared, defect: 0 }])));
    const [dialog, setDialog] = useState<'receive' | 'reject' | null>(null);
    const [reason, setReason] = useState('');
    const [reasonError, setReasonError] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);

    const lines = supply.items.map((item) => {
        const count = counts[item.itemId] ?? { accepted: item.declared, defect: 0 };

        return { item, ...count, diff: lineDiff({ declared: item.declared, ...count }) ?? 0 };
    });
    const totals = lines.reduce((t, line) => ({ declared: t.declared + line.item.declared, accepted: t.accepted + line.accepted, defect: t.defect + line.defect }), { declared: 0, accepted: 0, defect: 0 });
    const diffs = lines.filter((line) => line.diff !== 0);

    function set(itemId: number, field: 'accepted' | 'defect', value: number) {
        setCounts((prev) => ({ ...prev, [itemId]: { ...prev[itemId], [field]: Math.min(MAX, Math.max(0, Math.floor(value) || 0)) } }));
    }

    async function receive() {
        setBusy(true);
        const items = lines.map((line) => ({ itemId: line.item.itemId, accepted: line.accepted, defect: line.defect }));
        const result = await staffAction<{ message?: string; supply?: WarehouseSupply }>(`warehouse/supplies/${supply.number}/receive`, { items }, sample, S.sampleDone);
        setBusy(false);

        if (result === null) return;

        setDialog(null);
        onDone(
            result !== 'sample' && result.supply
                ? result.supply
                : {
                      ...supply,
                      status: { code: 'received', text: statuses.received },
                      receivedAt: new Date().toISOString(),
                      items: supply.items.map((item) => ({ ...item, accepted: counts[item.itemId]?.accepted ?? item.declared, defect: counts[item.itemId]?.defect ?? 0 })),
                  },
        );
    }

    async function reject() {
        if (!reason.trim()) {
            setReasonError(S.reasonRequired);

            return;
        }

        setBusy(true);
        const result = await staffAction<{ message?: string; supply?: WarehouseSupply }>(`warehouse/supplies/${supply.number}/reject`, { reason: reason.trim() }, sample, S.sampleDone, (errors) =>
            setReasonError(errors.reason?.[0] ?? null),
        );
        setBusy(false);

        if (result === null) return;

        setDialog(null);
        onDone(result !== 'sample' && result.supply ? result.supply : { ...supply, status: { code: 'rejected', text: statuses.rejected } });
    }

    const diffText = (diff: number) => (diff < 0 ? L.short(-diff) : L.extra(diff));

    return (
        <>
            <div className="mk-bar">
                <h2>
                    {L.title} {supply.number}
                </h2>
                <button type="button" className="mk-btn mk-btn--ghost" onClick={onBack}>
                    {L.back}
                </button>
            </div>
            <p className="mk-wh-supply-head">
                <b>{supply.seller.name}</b>
                {supply.expectedAt && <span>{L.expected(dateText(new Date(supply.expectedAt), false))}</span>}
                {supply.note && <span className="mk-muted">{supply.note}</span>}
            </p>
            <ul className="mk-wh-lines">
                {lines.map(({ item, accepted, defect, diff }) => (
                    <li key={item.itemId} className={cn('mk-wh-line', diff !== 0 && 'is-diff')}>
                        <div className="mk-wh-line__title">
                            <b>{item.title}</b>
                            {item.options && <span>{item.options}</span>}
                            <small>
                                {L.declared}: <b>{S.pcs(item.declared)}</b>
                            </small>
                        </div>
                        <Stepper label={L.accepted} value={accepted} onChange={(value) => set(item.itemId, 'accepted', value)} />
                        <Stepper label={L.defect} value={defect} onChange={(value) => set(item.itemId, 'defect', value)} />
                        <span className={cn('mk-wh-diff', diff !== 0 && 'is-bad')} aria-live="polite">
                            {diff === 0 ? `✓ ${L.match}` : diffText(diff)}
                        </span>
                    </li>
                ))}
            </ul>
            <div className="mk-wh-total">
                <span>
                    <b>{L.totals}:</b> {L.totalsLine(totals.declared, totals.accepted, totals.defect)}
                    {totals.accepted + totals.defect !== totals.declared && <b className="mk-wh-bad"> · {diffText(totals.accepted + totals.defect - totals.declared)}</b>}
                </span>
                <div className="mk-wh-total__actions">
                    <button
                        type="button"
                        className="mk-btn mk-btn--ghost"
                        disabled={busy}
                        onClick={() => {
                            setReasonError(null);
                            setDialog('reject');
                        }}
                    >
                        {L.reject}
                    </button>
                    <button type="button" className="mk-btn mk-btn--big" disabled={busy} onClick={() => setDialog('receive')}>
                        {L.receive}
                    </button>
                </div>
            </div>
            <p className="mk-hint">{L.hint}</p>

            {dialog === 'receive' && (
                <Dialog title={L.confirmTitle(supply.number)} onClose={() => setDialog(null)}>
                    {diffs.length === 0 ? (
                        <p>{L.confirmExact}</p>
                    ) : (
                        <>
                            <p>{L.confirmDiff}</p>
                            <ul className="mk-wh-dialog__list">
                                {diffs.map(({ item, diff }) => (
                                    <li key={item.itemId}>
                                        {item.title}
                                        {item.options && ` · ${item.options}`} — <b className="mk-wh-bad">{diffText(diff)}</b>
                                    </li>
                                ))}
                            </ul>
                        </>
                    )}
                    <p>
                        <b>{L.totalsLine(totals.declared, totals.accepted, totals.defect)}</b>
                    </p>
                    {totals.defect > 0 && <p className="mk-muted">{L.confirmDefect(totals.defect)}</p>}
                    <div className="mk-wh-dialog__actions">
                        <button type="button" className="mk-btn mk-btn--ghost" onClick={() => setDialog(null)}>
                            {S.cancel}
                        </button>
                        <button type="button" className="mk-btn" disabled={busy} onClick={() => void receive()} autoFocus>
                            {L.receive}
                        </button>
                    </div>
                </Dialog>
            )}

            {dialog === 'reject' && (
                <Dialog title={L.rejectTitle(supply.number)} onClose={() => setDialog(null)}>
                    <p>{L.rejectHint}</p>
                    <label className="mk-field">
                        {S.reason}
                        <textarea
                            rows={3}
                            value={reason}
                            placeholder={L.rejectPlaceholder}
                            onChange={(event) => {
                                setReason(event.target.value);
                                setReasonError(null);
                            }}
                            aria-invalid={reasonError ? true : undefined}
                            autoFocus
                        />
                        {reasonError && <small className="is-error">{reasonError}</small>}
                    </label>
                    <div className="mk-wh-dialog__actions">
                        <button type="button" className="mk-btn mk-btn--ghost" onClick={() => setDialog(null)}>
                            {S.cancel}
                        </button>
                        <button type="button" className="mk-btn mk-wh-btn--danger" disabled={busy} onClick={() => void reject()}>
                            {L.reject}
                        </button>
                    </div>
                </Dialog>
            )}
        </>
    );
}

/** Крупный счётчик под палец: − число + (число можно и набрать). */
function Stepper({ label, value, onChange }: { label: string; value: number; onChange: (value: number) => void }) {
    const L = lang(whReceivingText);

    return (
        <div className="mk-wh-stepper">
            <span>{label}</span>
            <div>
                <button type="button" onClick={() => onChange(value - 1)} disabled={value <= 0} aria-label={L.less(label)}>
                    <Minus size={22} aria-hidden />
                </button>
                <input
                    type="number"
                    inputMode="numeric"
                    min={0}
                    max={MAX}
                    value={value}
                    aria-label={label}
                    onFocus={(event) => event.target.select()}
                    onChange={(event) => onChange(Number(event.target.value))}
                />
                <button type="button" onClick={() => onChange(value + 1)} disabled={value >= MAX} aria-label={L.more(label)}>
                    <Plus size={22} aria-hidden />
                </button>
            </div>
        </div>
    );
}

/** Окно подтверждения поверх экрана; Esc и щелчок мимо — закрыть. */
function Dialog({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
    useEffect(() => {
        const onKey = (event: KeyboardEvent) => event.key === 'Escape' && onClose();

        window.addEventListener('keydown', onKey);

        return () => window.removeEventListener('keydown', onKey);
    }, [onClose]);

    return (
        <div className="mk-wh-dialog" onClick={(event) => event.target === event.currentTarget && onClose()}>
            <div className="mk-wh-dialog__box" role="dialog" aria-modal="true" aria-label={title}>
                <h3>{title}</h3>
                {children}
            </div>
        </div>
    );
}
