import { useState } from 'react';
import { lineDiff, sampleSupplies } from '@/components/market/staff/suppliesSample';
import { Link } from '@/components/ui/Link';
import { SampleNote } from '@/layouts/StaffLayout';
import { cn } from '@/lib/cn';
import { dateText } from '@/market/format';
import { lang } from '@/market/lang';
import { when } from '@/market/orders';
import type { WarehouseSupply } from '@/market/staff/contract';
import { useStaffData } from '@/market/staff/data';
import { staffText } from '@/market/text/staff';
import { whSuppliesText } from '@/market/text/wh-supplies';
import { routes } from '@/routes';

type Filter = WarehouseSupply['status']['code'];

const FILTERS: Filter[] = ['submitted', 'received', 'rejected'];

const TONE: Record<Filter, string> = {
    submitted: 'mk-pill--warn',
    received: 'mk-pill--ok',
    rejected: 'mk-pill--off',
};

/**
 * Склад, «Поставки»: что продавцы везут на склад, что уже приняли и в чём
 * отказали. Принимают на вкладке «Приёмка» — кнопка ведёт туда с номером.
 * Расхождение с заявкой видно в строке (склад принимает факт, решение 23.11).
 */
export function Supplies() {
    const L = lang(whSuppliesText);
    const S = lang(staffText);
    const [filter, setFilter] = useState<Filter>('submitted');
    const list = useStaffData<{ supplies: WarehouseSupply[] }>(`warehouse/supplies?status=${filter}`, sampleSupplies);
    // Сервер отдаёт уже отобранные; образец — все сразу
    const supplies = (list.data?.supplies ?? []).filter((supply) => supply.status.code === filter);

    return (
        <>
            <SampleNote show={list.sample} />
            <div className="mk-bar">
                <h2>{L.title}</h2>
            </div>
            <div className="mk-wh-chips" role="group" aria-label={L.filterLabel}>
                {FILTERS.map((code) => (
                    <button key={code} type="button" className="mk-wh-chip" aria-pressed={code === filter} onClick={() => setFilter(code)}>
                        {L.filters[code]}
                    </button>
                ))}
            </div>
            {list.loading && <div className="mk-skel-block" style={{ height: 200 }} aria-busy />}
            {list.error && (
                <div className="mk-failed">
                    <p>{list.error}</p>
                    <button type="button" className="mk-btn" onClick={list.reload}>
                        {S.retry}
                    </button>
                </div>
            )}
            {list.data && supplies.length === 0 && (
                <div className="mk-empty">
                    <span aria-hidden>🚚</span>
                    <h2>{L.emptyTitle}</h2>
                    <p>{L.empty[filter]}</p>
                </div>
            )}
            {supplies.length > 0 && (
                <div className="mk-table-wrap">
                    <table className="mk-table mk-wh-table">
                        <thead>
                            <tr>
                                <th>{L.colSupply}</th>
                                <th>{S.seller}</th>
                                <th>{L.colExpected}</th>
                                <th>{L.colItems}</th>
                                <th>{S.status}</th>
                                {filter === 'submitted' && <th />}
                            </tr>
                        </thead>
                        <tbody>
                            {supplies.map((supply) => (
                                <tr key={supply.number}>
                                    <td>
                                        <b>{supply.number}</b>
                                        {supply.receivedAt ? (
                                            <small className="mk-muted">{L.receivedAt(when(supply.receivedAt))}</small>
                                        ) : (
                                            supply.submittedAt && <small className="mk-muted">{L.submittedAt(when(supply.submittedAt))}</small>
                                        )}
                                    </td>
                                    <td>{supply.seller.name}</td>
                                    <td>{supply.expectedAt ? dateText(new Date(supply.expectedAt), false) : <span className="mk-muted">{L.noDate}</span>}</td>
                                    <td>
                                        <ul className="mk-supply-items mk-wh-items">
                                            {supply.items.map((item) => {
                                                const diff = lineDiff(item);

                                                return (
                                                    <li key={item.itemId}>
                                                        <span>
                                                            {item.title}
                                                            {item.options && <small> · {item.options}</small>}
                                                        </span>
                                                        <small>
                                                            {L.declared(item.declared)}
                                                            {item.accepted !== null && <> · {L.accepted(item.accepted, item.defect ?? 0)}</>}
                                                        </small>
                                                        {diff !== null && diff !== 0 && <small className="mk-low">{diff < 0 ? L.short(-diff) : L.extra(diff)}</small>}
                                                    </li>
                                                );
                                            })}
                                        </ul>
                                        {supply.note && <small className="mk-muted">{supply.note}</small>}
                                    </td>
                                    <td>
                                        <span className={cn('mk-pill', TONE[supply.status.code])}>{supply.status.text}</span>
                                    </td>
                                    {filter === 'submitted' && (
                                        <td>
                                            {supply.status.code === 'submitted' && (
                                                <Link href={`${routes.marketWarehouse('receiving')}&supply=${encodeURIComponent(supply.number)}`} className="mk-btn">
                                                    {L.receive}
                                                </Link>
                                            )}
                                        </td>
                                    )}
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
