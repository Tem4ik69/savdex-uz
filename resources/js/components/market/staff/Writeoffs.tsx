import { Plus } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { freeOf, sampleStock } from '@/components/market/staff/stockSample';
import { SampleNote } from '@/layouts/StaffLayout';
import { cn } from '@/lib/cn';
import { lang } from '@/market/lang';
import { when } from '@/market/orders';
import type { WarehouseStockRow, Writeoff } from '@/market/staff/contract';
import { staffAction, useStaffData } from '@/market/staff/data';
import { hoursAgo } from '@/market/staff/samples';
import { staffText } from '@/market/text/staff';
import { whWriteoffsText } from '@/market/text/wh-writeoffs';

const TONE: Record<Writeoff['status']['code'], string> = {
    requested: 'mk-pill--warn',
    approved: 'mk-pill--ok',
    rejected: 'mk-pill--off',
};

/** Образец заявок на списание (GET warehouse/writeoffs). */
function sampleWriteoffs(): { writeoffs: Writeoff[] } {
    const S = lang(whWriteoffsText).statuses;

    return {
        writeoffs: [
            {
                number: 'WO-0012',
                status: { code: 'requested', text: S.requested },
                line: { variantId: 301, title: 'Казан чугунный 12 л', options: '', sku: 'QU-KZ-12', cell: 'C-02-1', quantity: 1 },
                reason: 'Треснул при перекладке на полку',
                author: { name: 'Сотрудник склада' },
                createdAt: hoursAgo(5),
            },
            {
                number: 'WO-0009',
                status: { code: 'approved', text: S.approved },
                line: { variantId: 102, title: 'Плед флисовый', options: 'Серый, 150×200', sku: 'ST-PLD-150-GR', cell: 'A-03-3', quantity: 1 },
                reason: 'Залит водой при протечке крыши',
                author: { name: 'Сотрудник склада' },
                createdAt: hoursAgo(76),
            },
            {
                number: 'WO-0007',
                status: { code: 'rejected', text: S.rejected },
                line: { variantId: 401, title: 'Наушники беспроводные TWS', options: 'Белые', sku: 'TX-TWS-W', cell: 'D-04-2', quantity: 2 },
                reason: 'Не нашли при пересчёте',
                author: { name: 'Сотрудник склада' },
                createdAt: hoursAgo(150),
            },
        ],
    };
}

/**
 * Склад, «Списания»: склад только просит — подтверждает администратор
 * маркетплейса (решение 23.11, №7). До подтверждения остаток не меняется.
 */
export function Writeoffs() {
    const L = lang(whWriteoffsText);
    const S = lang(staffText);
    const list = useStaffData<{ writeoffs: Writeoff[] }>('warehouse/writeoffs', sampleWriteoffs);
    const [creating, setCreating] = useState(false);

    return (
        <>
            <SampleNote show={list.sample} />
            <div className="mk-bar">
                <h2>{L.title}</h2>
                {!creating && (
                    <button type="button" className="mk-btn" onClick={() => setCreating(true)}>
                        <Plus size={18} aria-hidden /> {L.add}
                    </button>
                )}
            </div>
            {creating && (
                <WriteoffForm
                    sample={list.sample}
                    onClose={() => setCreating(false)}
                    onCreated={(created) => {
                        setCreating(false);
                        list.patch((current) => ({ ...current, writeoffs: created ? [created, ...current.writeoffs] : current.writeoffs }));
                    }}
                />
            )}
            {list.loading && <div className="mk-skel-block" style={{ height: 200 }} aria-busy />}
            {list.error && (
                <div className="mk-failed">
                    <p>{list.error}</p>
                    <button type="button" className="mk-btn" onClick={list.reload}>
                        {S.retry}
                    </button>
                </div>
            )}
            {list.data && list.data.writeoffs.length === 0 && !creating && (
                <div className="mk-empty">
                    <span aria-hidden>🗂️</span>
                    <h2>{L.emptyTitle}</h2>
                    <p>{L.emptyText}</p>
                </div>
            )}
            {list.data && list.data.writeoffs.length > 0 && (
                <div className="mk-table-wrap">
                    <table className="mk-table mk-wh-table">
                        <thead>
                            <tr>
                                <th>{L.colNumber}</th>
                                <th>{S.product}</th>
                                <th className="is-num">{S.quantity}</th>
                                <th>{S.reason}</th>
                                <th>{L.colAuthor}</th>
                                <th>{S.status}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {list.data.writeoffs.map((writeoff) => (
                                <tr key={writeoff.number}>
                                    <td>
                                        <b>{writeoff.number}</b>
                                        <small className="mk-muted">{when(writeoff.createdAt)}</small>
                                    </td>
                                    <td>
                                        <b>{writeoff.line.title}</b>
                                        {(writeoff.line.options || writeoff.line.cell) && (
                                            <small className="mk-muted">{[writeoff.line.options, writeoff.line.cell && `${S.cell} ${writeoff.line.cell}`].filter(Boolean).join(' · ')}</small>
                                        )}
                                    </td>
                                    <td className="is-num">{S.pcs(writeoff.line.quantity)}</td>
                                    <td className="mk-wh-reason">{writeoff.reason}</td>
                                    <td>{writeoff.author.name}</td>
                                    <td>
                                        <span className={cn('mk-pill', TONE[writeoff.status.code])}>{writeoff.status.text}</span>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
            <p className="mk-hint">{L.hint}</p>
        </>
    );
}

/** Заявка: вариант с остатка, сколько (не больше свободного) и причина. */
function WriteoffForm({ sample, onClose, onCreated }: { sample: boolean; onClose: () => void; onCreated: (created: Writeoff | null) => void }) {
    const L = lang(whWriteoffsText);
    const S = lang(staffText);
    const stock = useStaffData<{ stock: WarehouseStockRow[] }>('warehouse/stock', sampleStock);
    const [variantId, setVariantId] = useState('');
    const [quantity, setQuantity] = useState('1');
    const [reason, setReason] = useState('');
    const [errors, setErrors] = useState<Record<string, string>>({});
    const [busy, setBusy] = useState(false);

    const rows = stock.data?.stock ?? [];
    const row = rows.find((r) => String(r.variantId) === variantId) ?? null;
    const free = row ? freeOf(row) : 0;

    async function submit(event: FormEvent) {
        event.preventDefault();

        const amount = Number(quantity);
        const found: Record<string, string> = {};

        if (!row) found.variantId = L.chooseRequired;
        if (!Number.isInteger(amount) || amount < 1) found.quantity = L.quantityRequired;
        else if (row && amount > free) found.quantity = L.quantityMax(free);
        if (!reason.trim()) found.reason = S.reasonRequired;

        setErrors(found);

        if (Object.keys(found).length > 0 || !row) return;

        setBusy(true);
        const result = await staffAction<{ message?: string; writeoff?: Writeoff }>(
            'warehouse/writeoffs/create',
            { variantId: row.variantId, quantity: amount, reason: reason.trim() },
            sample,
            S.sampleDone,
            (fields) => setErrors(Object.fromEntries(Object.entries(fields).map(([key, texts]) => [key, texts[0] ?? '']))),
        );
        setBusy(false);

        if (result === null) return;

        onCreated(
            result === 'sample'
                ? {
                      number: `WO-${String(Date.now()).slice(-4)}`,
                      status: { code: 'requested', text: L.statuses.requested },
                      line: { variantId: row.variantId, title: row.title, options: row.options, sku: row.sku, cell: row.cell ?? null, quantity: amount },
                      reason: reason.trim(),
                      author: { name: 'Сотрудник склада' },
                      createdAt: new Date().toISOString(),
                  }
                : (result.writeoff ?? null),
        );
    }

    return (
        <form className="mk-panel mk-form mk-form--2 mk-wh-form" onSubmit={(event) => void submit(event)} noValidate>
            <h2 className="mk-field--wide">{L.formTitle}</h2>
            <label className="mk-field mk-field--wide">
                {L.variant}
                <select
                    value={variantId}
                    onChange={(event) => {
                        setVariantId(event.target.value);
                        setErrors((prev) => ({ ...prev, variantId: '', quantity: '' }));
                    }}
                    disabled={stock.loading}
                    aria-invalid={errors.variantId ? true : undefined}
                >
                    <option value="">{stock.loading ? S.loading : L.choose}</option>
                    {rows.map((r) => (
                        <option key={r.variantId} value={r.variantId} disabled={freeOf(r) === 0}>
                            {[r.title, r.options, r.cell, r.seller.name].filter(Boolean).join(' · ')} — {freeOf(r) > 0 ? L.free(freeOf(r)) : L.noFree}
                        </option>
                    ))}
                </select>
                {errors.variantId && <small className="is-error">{errors.variantId}</small>}
                {stock.error && <small className="is-error">{stock.error}</small>}
            </label>
            <label className="mk-field">
                {S.quantity}
                <input
                    type="number"
                    inputMode="numeric"
                    min={1}
                    max={free || undefined}
                    value={quantity}
                    onChange={(event) => {
                        setQuantity(event.target.value);
                        setErrors((prev) => ({ ...prev, quantity: '' }));
                    }}
                    aria-invalid={errors.quantity ? true : undefined}
                />
                {errors.quantity ? <small className="is-error">{errors.quantity}</small> : row && <small>{L.free(free)}</small>}
            </label>
            <label className="mk-field mk-field--wide">
                {S.reason}
                <textarea
                    rows={3}
                    value={reason}
                    placeholder={L.reasonPlaceholder}
                    onChange={(event) => {
                        setReason(event.target.value);
                        setErrors((prev) => ({ ...prev, reason: '' }));
                    }}
                    aria-invalid={errors.reason ? true : undefined}
                />
                {errors.reason && <small className="is-error">{errors.reason}</small>}
            </label>
            <p className="mk-field--wide mk-wh-note">{L.hint}</p>
            <div className="mk-field--wide mk-wh-form__actions">
                <button type="button" className="mk-btn mk-btn--ghost" onClick={onClose}>
                    {S.cancel}
                </button>
                <button type="submit" className="mk-btn" disabled={busy}>
                    {L.submit}
                </button>
            </div>
        </form>
    );
}
