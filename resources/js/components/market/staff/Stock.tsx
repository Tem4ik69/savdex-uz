import { Search } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { filterStock, freeOf, sampleStock } from '@/components/market/staff/stockSample';
import { SampleNote } from '@/layouts/StaffLayout';
import { cn } from '@/lib/cn';
import { lang } from '@/market/lang';
import type { WarehouseStockRow } from '@/market/staff/contract';
import { useStaffData } from '@/market/staff/data';
import { staffText } from '@/market/text/staff';
import { whStockText } from '@/market/text/wh-stock';

/**
 * Склад, «Остатки»: что лежит, где и сколько свободно. Только смотреть —
 * остаток меняют движения (приёмка, выдача, вывоз, списание), не руки.
 */
export function Stock() {
    const L = lang(whStockText);
    const S = lang(staffText);
    const [query, setQuery] = useState('');
    const [q, setQ] = useState('');

    // Искать на сервере, когда перестали печатать
    useEffect(() => {
        const timer = window.setTimeout(() => setQ(query.trim()), 300);

        return () => window.clearTimeout(timer);
    }, [query]);

    const stock = useStaffData<{ stock: WarehouseStockRow[] }>(q ? `warehouse/stock?q=${encodeURIComponent(q)}` : 'warehouse/stock', sampleStock);
    // Пока ищется новое — показываем прежний список, без мигания
    const last = useRef<WarehouseStockRow[] | null>(null);

    if (stock.data) last.current = stock.sample ? filterStock(stock.data.stock, q) : stock.data.stock;

    const rows = last.current;
    const totals = (rows ?? []).reduce(
        (t, row) => ({ quantity: t.quantity + row.quantity, reserved: t.reserved + row.reserved, free: t.free + freeOf(row), defect: t.defect + row.defect }),
        { quantity: 0, reserved: 0, free: 0, defect: 0 },
    );

    return (
        <>
            <SampleNote show={stock.sample} />
            <div className="mk-bar">
                <h2>{L.title}</h2>
            </div>
            <label className="mk-wh-search">
                <Search size={20} aria-hidden />
                <input type="search" value={query} placeholder={L.searchPlaceholder} aria-label={S.search} onChange={(event) => setQuery(event.target.value)} />
            </label>
            {stock.loading && rows === null && <div className="mk-skel-block" style={{ height: 240 }} aria-busy />}
            {stock.error && (
                <div className="mk-failed">
                    <p>{stock.error}</p>
                    <button type="button" className="mk-btn" onClick={stock.reload}>
                        {S.retry}
                    </button>
                </div>
            )}
            {rows && rows.length === 0 && !stock.error && (
                <div className="mk-empty">
                    <span aria-hidden>{q ? '🔍' : '📦'}</span>
                    <h2>{q ? L.notFoundTitle : L.emptyTitle}</h2>
                    <p>{q ? L.notFoundText : L.emptyText}</p>
                </div>
            )}
            {rows && rows.length > 0 && !stock.error && (
                <div className={cn('mk-table-wrap', stock.loading && 'mk-wh-stale')}>
                    <table className="mk-table mk-wh-table">
                        <thead>
                            <tr>
                                <th>{S.product}</th>
                                <th>{L.colSku}</th>
                                <th>{S.seller}</th>
                                <th>{S.cell}</th>
                                <th className="is-num">{L.colShelf}</th>
                                <th className="is-num">{L.colReserved}</th>
                                <th className="is-num">{L.colFree}</th>
                                <th className="is-num">{L.colDefect}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {rows.map((row) => (
                                <tr key={row.variantId}>
                                    <td>
                                        <b>{row.title}</b>
                                        {row.options && <small className="mk-muted">{row.options}</small>}
                                    </td>
                                    <td className="mk-wh-mono">{row.sku ?? '—'}</td>
                                    <td>{row.seller.name}</td>
                                    <td className="mk-wh-mono">{row.cell ?? '—'}</td>
                                    <td className="is-num">{row.quantity}</td>
                                    <td className="is-num">{row.reserved}</td>
                                    <td className="is-num">
                                        <b>{freeOf(row)}</b>
                                    </td>
                                    <td className={cn('is-num', row.defect > 0 && 'mk-wh-bad')}>{row.defect}</td>
                                </tr>
                            ))}
                        </tbody>
                        <tfoot>
                            <tr>
                                <td colSpan={4}>{L.totals(rows.length)}</td>
                                <td className="is-num">{totals.quantity}</td>
                                <td className="is-num">{totals.reserved}</td>
                                <td className="is-num">{totals.free}</td>
                                <td className={cn('is-num', totals.defect > 0 && 'mk-wh-bad')}>{totals.defect}</td>
                            </tr>
                        </tfoot>
                    </table>
                </div>
            )}
            <p className="mk-hint">{L.hint}</p>
        </>
    );
}
