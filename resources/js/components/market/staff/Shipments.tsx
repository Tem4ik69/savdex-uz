import { Printer, Truck } from 'lucide-react';
import { useEffect, useState } from 'react';
import { ScreenLoad } from '@/components/market/staff/Picking';
import { cn } from '@/lib/cn';
import { SampleNote } from '@/layouts/StaffLayout';
import { lang } from '@/market/lang';
import { when } from '@/market/orders';
import type { Shipment, StaffStatus } from '@/market/staff/contract';
import { staffAction, useStaffData } from '@/market/staff/data';
import { hoursAgo } from '@/market/staff/samples';
import { staffText } from '@/market/text/staff';
import { shipmentsText } from '@/market/text/wh-shipments';

type ShipmentCode = Shipment['status']['code'];

interface ReadyPoint {
    code: string;
    name: string;
    orders: number;
}

const TONE: Record<ShipmentCode, string> = { draft: 'mk-pill--off', sent: 'mk-pill--warn', delivered: 'mk-pill--ok' };

const status = (code: ShipmentCode): StaffStatus<ShipmentCode> => ({ code, text: lang(shipmentsText).status[code] });

const POINTS: Record<string, { code: string; name: string; address: string }> = {
    'demo-chilanzar': { code: 'demo-chilanzar', name: 'BTS Чиланзар', address: 'Чиланзарский район, ул. Бунёдкор, 12' },
    'demo-yunusabad': { code: 'demo-yunusabad', name: 'BTS Юнусабад', address: 'Юнусабадский район, ул. Амира Темура, 107' },
};

/** Образец GET warehouse/shipments/ready. */
const sampleReady = (): { points: ReadyPoint[] } => ({
    points: [
        { code: 'demo-chilanzar', name: 'BTS Чиланзар', orders: 2 },
        { code: 'demo-yunusabad', name: 'BTS Юнусабад', orders: 3 },
    ],
});

/** Образец GET warehouse/shipments. */
const sampleShipments = (): { shipments: Shipment[] } => ({
    shipments: [
        {
            number: 'P-0412',
            status: status('sent'),
            pickupPoint: POINTS['demo-yunusabad'],
            orders: [
                { number: 'SX-24071', places: 1 },
                { number: 'SX-24075', places: 2 },
            ],
            sentAt: hoursAgo(4),
            deliveredAt: null,
        },
        {
            number: 'P-0409',
            status: status('delivered'),
            pickupPoint: POINTS['demo-chilanzar'],
            orders: [
                { number: 'SX-24012', places: 1 },
                { number: 'SX-24019', places: 1 },
                { number: 'SX-24030', places: 3 },
            ],
            sentAt: hoursAgo(28),
            deliveredAt: hoursAgo(25),
        },
    ],
});

const placesOf = (shipment: Shipment): number => shipment.orders.reduce((total, order) => total + order.places, 0);

/**
 * Склад, «Отгрузки»: по пунктам — сколько собранных заказов ждёт, «Сформировать
 * партию» (все собранные заказы пункта), список партий, «Отправить» черновик
 * и лист партии на печать (решение 23.11: обычный принтер) — номер, пункт,
 * заказы и места крупно.
 */
export function Shipments() {
    const L = lang(shipmentsText);
    const S = lang(staffText);
    const ready = useStaffData<{ points: ReadyPoint[] }>('warehouse/shipments/ready', sampleReady);
    const list = useStaffData<{ shipments: Shipment[] }>('warehouse/shipments', sampleShipments);
    const [busy, setBusy] = useState<string | null>(null);
    // Лист на печать: номер партии и счётчик — повторная печать того же листа
    const [print, setPrint] = useState<{ number: string; n: number } | null>(null);
    const points = (ready.data?.points ?? []).filter((p) => p.orders > 0);
    const shipments = list.data?.shipments ?? [];
    const sheet = print ? shipments.find((s) => s.number === print.number) ?? null : null;

    useEffect(() => {
        // Печатаем после отрисовки листа: он скрыт на экране и виден только на бумаге
        if (print) window.print();
    }, [print]);

    async function create(point: ReadyPoint) {
        setBusy(point.code);

        const result = await staffAction('warehouse/shipments/create', { pickupPoint: point.code }, ready.sample, S.sampleDone);

        setBusy(null);

        if (result === null) return;

        ready.patch((d) => ({ points: d.points.filter((p) => p.code !== point.code) }));
        list.patch((d) => {
            // Номера образца — условные: настоящие даст сервер
            const seed = Date.now() % 10000;
            const shipment: Shipment = {
                number: `P-${String(seed).padStart(4, '0')}`,
                status: status('draft'),
                pickupPoint: POINTS[point.code] ?? { code: point.code, name: point.name, address: '' },
                orders: Array.from({ length: point.orders }, (_, i) => ({ number: `SX-${30000 + ((seed * 7 + i) % 9999)}`, places: i === 0 ? 2 : 1 })),
                sentAt: null,
                deliveredAt: null,
            };

            return { shipments: [shipment, ...d.shipments] };
        });
    }

    async function send(shipment: Shipment) {
        if (!window.confirm(L.confirmSend(shipment.number, shipment.pickupPoint.name))) return;

        setBusy(shipment.number);

        const result = await staffAction(`warehouse/shipments/${shipment.number}/send`, {}, list.sample, S.sampleDone);

        setBusy(null);

        if (result === null) return;

        list.patch((d) => ({ shipments: d.shipments.map((s) => (s.number === shipment.number ? { ...s, status: status('sent'), sentAt: new Date().toISOString() } : s)) }));
    }

    return (
        <>
            <SampleNote show={ready.sample || list.sample} />
            <div className="mk-bar">
                <h2>{L.title}</h2>
            </div>

            <section className="mk-wh2-section">
                <h3>{L.readyTitle}</h3>
                <ScreenLoad data={ready} />
                {ready.data && points.length === 0 && <p className="mk-muted">{L.readyEmpty}</p>}
                {points.length > 0 && (
                    <div className="mk-wh2-list">
                        {points.map((point) => (
                            <article key={point.code} className="mk-wh2-card mk-wh2-ready">
                                <div>
                                    <h3>{point.name}</h3>
                                    <span className="mk-wh2-big">{L.readyOrders(point.orders)}</span>
                                </div>
                                <button type="button" className="mk-btn mk-btn--big" disabled={busy !== null} onClick={() => void create(point)}>
                                    <Truck size={20} aria-hidden /> {L.create}
                                </button>
                            </article>
                        ))}
                    </div>
                )}
            </section>

            <section className="mk-wh2-section">
                <h3>{L.listTitle}</h3>
                <ScreenLoad data={list} />
                {list.data && shipments.length === 0 && <p className="mk-muted">{L.listEmpty}</p>}
                <div className="mk-wh2-list">
                    {shipments.map((shipment) => (
                        <article key={shipment.number} className={cn('mk-wh2-card', shipment.status.code === 'delivered' && 'is-done')}>
                            <div className="mk-wh2-card__hd">
                                <div>
                                    <h3>{shipment.number}</h3>
                                    {shipment.deliveredAt ? (
                                        <span className="mk-muted">{L.deliveredAt(when(shipment.deliveredAt))}</span>
                                    ) : (
                                        shipment.sentAt && <span className="mk-muted">{L.sentAt(when(shipment.sentAt))}</span>
                                    )}
                                </div>
                                <span className={cn('mk-pill', TONE[shipment.status.code])}>{shipment.status.text}</span>
                            </div>
                            <p className="mk-wh2-point">
                                {shipment.pickupPoint.name}
                                {shipment.pickupPoint.address && <small className="mk-muted">{shipment.pickupPoint.address}</small>}
                            </p>
                            <p className="mk-wh2-big">{L.ordersPlaces(shipment.orders.length, placesOf(shipment))}</p>
                            <details className="mk-wh2-details">
                                <summary>{L.showOrders}</summary>
                                <ul>
                                    {shipment.orders.map((order) => (
                                        <li key={order.number}>
                                            <b>{order.number}</b> <span>{S.places(order.places)}</span>
                                        </li>
                                    ))}
                                </ul>
                            </details>
                            <div className="mk-wh2-actions">
                                {shipment.status.code === 'draft' && (
                                    <button type="button" className="mk-btn mk-btn--big" disabled={busy !== null} onClick={() => void send(shipment)}>
                                        <Truck size={20} aria-hidden /> {L.send}
                                    </button>
                                )}
                                <button type="button" className="mk-btn mk-btn--ghost mk-btn--big" onClick={() => setPrint({ number: shipment.number, n: (print?.n ?? 0) + 1 })}>
                                    <Printer size={20} aria-hidden /> {L.print}
                                </button>
                            </div>
                        </article>
                    ))}
                </div>
            </section>
            <p className="mk-hint">{L.hint}</p>

            {sheet && <PackingList shipment={sheet} />}
        </>
    );
}

/** Лист партии для печати: на экране скрыт, на бумаге — только он (staff-warehouse-b.css, @media print). */
function PackingList({ shipment }: { shipment: Shipment }) {
    const L = lang(shipmentsText);
    const places = placesOf(shipment);

    return (
        <div className="mk-wh2-print" aria-hidden>
            <h1>{L.sheetTitle(shipment.number)}</h1>
            <p className="mk-wh2-print__to">
                <span>{L.sheetTo}:</span> <b>{shipment.pickupPoint.name}</b>
                {shipment.pickupPoint.address && <small>{shipment.pickupPoint.address}</small>}
            </p>
            <p className="mk-wh2-print__total">{L.sheetTotal(shipment.orders.length, places)}</p>
            <table>
                <thead>
                    <tr>
                        <th>{L.sheetOrder}</th>
                        <th>{L.sheetPlaces}</th>
                        <th>{L.sheetCheck}</th>
                    </tr>
                </thead>
                <tbody>
                    {shipment.orders.map((order) => (
                        <tr key={order.number}>
                            <td>{order.number}</td>
                            <td>{order.places}</td>
                            <td />
                        </tr>
                    ))}
                </tbody>
            </table>
            <div className="mk-wh2-print__sign">
                <span>{L.sheetGave}: ____________________</span>
                <span>{L.sheetTook}: ____________________</span>
            </div>
            <small>{L.sheetPrinted(when(new Date().toISOString()))}</small>
        </div>
    );
}
