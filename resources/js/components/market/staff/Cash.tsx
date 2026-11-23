import { ChevronLeft, ChevronRight } from 'lucide-react';
import { useState } from 'react';
import { SampleNote } from '@/layouts/StaffLayout';
import { dateText, sum } from '@/market/format';
import { lang } from '@/market/lang';
import type { PointCash } from '@/market/staff/contract';
import { useStaffData } from '@/market/staff/data';
import { ptCashText } from '@/market/text/pt-cash';
import { staffText } from '@/market/text/staff';

/** Сегодня по Ташкенту: «2026-11-23». */
function today(): string {
    return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Tashkent', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
}

/** День ± n: даты без часов, считаем в UTC — переход на летнее время не мешает. */
function shift(date: string, days: number): string {
    const value = new Date(`${date}T00:00:00Z`);

    value.setUTCDate(value.getUTCDate() + days);

    return value.toISOString().slice(0, 10);
}

/** «14:05» по времени Ташкента. */
function clock(iso: string): string {
    return new Intl.DateTimeFormat('ru-RU', { timeZone: 'Asia/Tashkent', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(iso));
}

/** Образец: сегодня и вчера — несколько выдач, раньше — пусто (видно пустой день). */
function sampleCash(date: string): PointCash {
    const at = (time: string): string => new Date(`${date}T${time}:00+05:00`).toISOString();
    const orders =
        date === today()
            ? [
                  { number: 'K7M2PX9QAD', amount: 1_290_000, issuedAt: at('10:12'), staff: 'Сотрудник пункта' },
                  { number: 'C3VN8QJ5HT', amount: 89_000, issuedAt: at('12:47'), staff: 'Сотрудник пункта' },
                  { number: 'P6WE2KL9XD', amount: 345_500, issuedAt: at('16:05'), staff: 'Второй сотрудник' },
              ]
            : date === shift(today(), -1)
              ? [
                    { number: 'G5TR7BM3NY', amount: 512_000, issuedAt: at('11:30'), staff: 'Сотрудник пункта' },
                    { number: 'U2HX9CF4LQ', amount: 74_000, issuedAt: at('18:20'), staff: 'Второй сотрудник' },
                ]
              : [];

    return { date, orders, total: orders.reduce((total, o) => total + o.amount, 0) };
}

/**
 * «Наличные» (пункт выдачи): что получено наличными при выдаче за день —
 * итог крупно и список заказов. Сдача наличных — по правилам BTS, сверка
 * с SavdEx — ночью.
 */
export function Cash() {
    const L = lang(ptCashText);
    const S = lang(staffText);
    const now = today();
    const [date, setDate] = useState(now);
    const data = useStaffData<PointCash>(`point/cash?date=${date}`, () => sampleCash(date));
    const cash = data.data;

    function choose(value: string) {
        // Пустое поле или будущий день — не берём
        if (/^\d{4}-\d{2}-\d{2}$/.test(value) && value <= now) setDate(value);
    }

    return (
        <div className="mk-pt">
            <SampleNote show={data.sample} />
            <h2 className="mk-pt__title">{L.title}</h2>

            <div className="mk-pt-day">
                <button type="button" className="mk-pt-day__arrow" onClick={() => setDate(shift(date, -1))} aria-label={L.prev}>
                    <ChevronLeft size={24} aria-hidden />
                </button>
                <label className="mk-pt-day__pick">
                    <span>{date === now ? L.today : dateText(new Date(`${date}T12:00:00+05:00`), false)}</span>
                    <input type="date" value={date} max={now} onChange={(e) => choose(e.target.value)} aria-label={L.date} />
                </label>
                <button type="button" className="mk-pt-day__arrow" onClick={() => setDate(shift(date, 1))} disabled={date >= now} aria-label={L.next}>
                    <ChevronRight size={24} aria-hidden />
                </button>
            </div>

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

            {cash && (
                <>
                    <div className="mk-pt-total">
                        <span>{L.total}</span>
                        <b>{S.money(sum(cash.total))}</b>
                        <small>{L.count(cash.orders.length)}</small>
                    </div>

                    {cash.orders.length === 0 ? (
                        <div className="mk-empty">
                            <span aria-hidden>💵</span>
                            <h2>{L.emptyTitle}</h2>
                            <p>{L.emptyText}</p>
                        </div>
                    ) : (
                        <ul className="mk-pt-list mk-pt-cash">
                            {cash.orders.map((o) => (
                                <li key={o.number}>
                                    <div className="mk-pt-list__row">
                                        <span className="mk-pt-list__main">
                                            <b>{o.number}</b>
                                            <small>
                                                {clock(o.issuedAt)} · {o.staff}
                                            </small>
                                        </span>
                                        <b className="mk-pt-cash__amount">{S.money(sum(o.amount))}</b>
                                    </div>
                                </li>
                            ))}
                        </ul>
                    )}
                </>
            )}

            <p className="mk-pt-hint">{L.note}</p>
        </div>
    );
}
