import { CheckCircle2, Lock, PackageX, Search } from 'lucide-react';
import { type FormEvent, useState } from 'react';
import { SampleNote } from '@/layouts/StaffLayout';
import { api, ApiError } from '@/market/api';
import { sum } from '@/market/format';
import { lang } from '@/market/lang';
import { when } from '@/market/orders';
import type { PointOrder } from '@/market/staff/contract';
import { staffAction } from '@/market/staff/data';
import { hoursAgo } from '@/market/staff/samples';
import { notify } from '@/market/store';
import { ptIssueText } from '@/market/text/pt-issue';
import { staffText } from '@/market/text/staff';

/** Ответ на ввод кода (staff/contract.ts). */
interface IssueResult {
    result: 'issued' | 'wrong' | 'locked';
    attemptsLeft: number;
    lockedUntil: string | null;
    message?: string;
}

/** Верный код в образце — один на все заказы, написан в подсказке. */
const SAMPLE_CODE = '123456';

/** Пауза после 5 неверных кодов (решение 23.11) — в образце 30 минут. */
const SAMPLE_LOCK_MINUTES = 30;

/** Номер с наклейки: как в адресе заказа — 8–16 латинских букв и цифр. */
const NUMBER = /^[0-9A-Z]{8,16}$/;

/** Статусы, при которых выдавать уже нечего: сервер всё равно откажет, но кнопку не показываем. */
const FINAL = new Set(['issued', 'refused', 'cancelled', 'returned', 'expired']);

const sampleOrders = (): PointOrder[] => [
    {
        number: 'K7M2PX9QAD',
        status: { code: 'ready', text: 'Можно забрать' },
        places: 2,
        toPay: 1_290_000,
        until: hoursAgo(-24 * 5),
        lockedUntil: null,
        attemptsLeft: 5,
    },
    {
        number: 'R4TW8HN3EB',
        status: { code: 'ready', text: 'Можно забрать' },
        places: 1,
        toPay: null,
        until: hoursAgo(-24 * 2),
        lockedUntil: null,
        attemptsLeft: 5,
    },
    {
        number: 'Z9CF6VJ2LM',
        status: { code: 'ready', text: 'Можно забрать' },
        places: 3,
        toPay: 456_000,
        until: hoursAgo(-24 * 6),
        lockedUntil: hoursAgo(-0.4),
        attemptsLeft: 0,
    },
];

/** «14:05» по времени Ташкента. */
function clock(iso: string): string {
    return new Intl.DateTimeFormat('ru-RU', { timeZone: 'Asia/Tashkent', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(iso));
}

const isLocked = (order: PointOrder): boolean => order.lockedUntil !== null && new Date(order.lockedUntil).getTime() > Date.now();

type Done = { kind: 'issued'; order: PointOrder } | { kind: 'refused'; order: PointOrder };

/**
 * «Выдать по коду» (телефон сотрудника пункта): номер с наклейки → заказ
 * (места, сколько получить наличными, срок) → 6 цифр кода покупателя →
 * «Выдан». Имени и телефона покупателя экран не получает (решение 23.11).
 * Отказ при получении — только от всего заказа (решение 23.11, №4).
 *
 * Пока на сервере нет адреса point/orders/<номер> — образец: заказы и их
 * попытки живут в этой вкладке, верный код — 123456.
 */
export function Issue() {
    const L = lang(ptIssueText);
    const S = lang(staffText);
    const [number, setNumber] = useState('');
    const [numberError, setNumberError] = useState<string | null>(null);
    const [searching, setSearching] = useState(false);
    const [notFound, setNotFound] = useState(false);
    const [order, setOrder] = useState<PointOrder | null>(null);
    /** Адреса ещё нет: ищем и выдаём по образцу */
    const [sample, setSample] = useState(false);
    const [samples, setSamples] = useState<PointOrder[]>(sampleOrders);
    const [code, setCode] = useState('');
    const [codeError, setCodeError] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    const [refusing, setRefusing] = useState(false);
    const [reason, setReason] = useState('');
    const [reasonError, setReasonError] = useState<string | null>(null);
    const [done, setDone] = useState<Done | null>(null);

    function reset() {
        setNumber('');
        setNumberError(null);
        setNotFound(false);
        setOrder(null);
        setCode('');
        setCodeError(null);
        setRefusing(false);
        setReason('');
        setReasonError(null);
        setDone(null);
    }

    /** Заказ поменялся: на экране и, в образце, в списке образцов. */
    function update(next: PointOrder, inSample: boolean) {
        setOrder(next);

        if (inSample) setSamples((list) => list.map((o) => (o.number === next.number ? next : o)));
    }

    async function find(event: FormEvent) {
        event.preventDefault();

        const clean = number.replace(/[\s-]/g, '').toUpperCase();

        setNumber(clean);
        setNotFound(false);
        setOrder(null);
        setCode('');
        setCodeError(null);
        setRefusing(false);

        if (!NUMBER.test(clean)) {
            setNumberError(L.numberInvalid);

            return;
        }

        setNumberError(null);
        setSearching(true);

        try {
            const found = await api<PointOrder>(`point/orders/${clean}`, { loginRedirect: false });

            setSample(false);
            setOrder(found);
        } catch (failure) {
            if (!(failure instanceof ApiError)) return;

            if (failure.status === 404 && typeof failure.data.message === 'string') {
                // Адрес есть, заказа нет (или он чужого пункта)
                setSample(false);
                setNotFound(true);
            } else if (failure.status === 404) {
                // 404 без JSON — адреса ещё нет: ищем в образце
                const found = samples.find((o) => o.number === clean) ?? null;

                setSample(true);
                setOrder(found);
                setNotFound(found === null);
            } else {
                notify(failure.message, true);
            }
        } finally {
            setSearching(false);
        }
    }

    async function issue(event: FormEvent) {
        event.preventDefault();

        if (!order) return;

        if (!/^\d{6}$/.test(code)) {
            setCodeError(L.codeInvalid);

            return;
        }

        setCodeError(null);
        setBusy(true);

        const response = await staffAction<IssueResult>(`point/orders/${order.number}/issue`, { code }, sample, S.sampleDone, (fields) =>
            setCodeError(fields.code?.[0] ?? null),
        );

        setBusy(false);

        if (response === null) return;

        const result: IssueResult = response === 'sample' ? sampleIssue(order, code) : response;

        if (result.result === 'issued') {
            const issued: PointOrder = { ...order, status: { code: 'issued', text: L.issued }, attemptsLeft: result.attemptsLeft, lockedUntil: null };

            update(issued, sample);
            setDone({ kind: 'issued', order });

            return;
        }

        update({ ...order, attemptsLeft: result.attemptsLeft, lockedUntil: result.lockedUntil }, sample);
        setCode('');
        setCodeError(result.result === 'wrong' ? L.wrong(result.attemptsLeft) : null);
    }

    async function refuse(event: FormEvent) {
        event.preventDefault();

        if (!order) return;

        const text = reason.trim();

        if (!text) {
            setReasonError(S.reasonRequired);

            return;
        }

        setReasonError(null);
        setBusy(true);

        const response = await staffAction(`point/orders/${order.number}/refuse`, { reason: text }, sample, S.sampleDone, (fields) => setReasonError(fields.reason?.[0] ?? null));

        setBusy(false);

        if (response === null) return;

        update({ ...order, status: { code: 'refused', text: L.refuse } }, sample);
        setDone({ kind: 'refused', order });
    }

    /** Образец: верный код — выдан; неверный — минус попытка, на нуле — пауза. */
    function sampleIssue(current: PointOrder, entered: string): IssueResult {
        if (isLocked(current)) return { result: 'locked', attemptsLeft: 0, lockedUntil: current.lockedUntil };

        if (entered === SAMPLE_CODE) return { result: 'issued', attemptsLeft: current.attemptsLeft, lockedUntil: null };

        // Пауза прошла — снова 5 попыток
        const left = (current.lockedUntil !== null ? 5 : current.attemptsLeft) - 1;

        if (left > 0) return { result: 'wrong', attemptsLeft: left, lockedUntil: null };

        return { result: 'locked', attemptsLeft: 0, lockedUntil: new Date(Date.now() + SAMPLE_LOCK_MINUTES * 60_000).toISOString() };
    }

    if (done) {
        const refused = done.kind === 'refused';

        return (
            <section className={refused ? 'mk-pt-done mk-pt-done--refused' : 'mk-pt-done'} role="status" aria-live="polite">
                <SampleNote show={sample} />
                {refused ? <PackageX size={64} aria-hidden /> : <CheckCircle2 size={72} aria-hidden />}
                <h2>{refused ? L.refused : L.issued}</h2>
                <p className="mk-pt-done__number">{done.order.number}</p>
                {refused ? (
                    <p>{L.refusedText}</p>
                ) : (
                    <>
                        {done.order.toPay !== null && <p className="mk-pt-done__cash">{L.collectCash(sum(done.order.toPay))}</p>}
                        <p>{L.issuedText(L.places(done.order.places))}</p>
                    </>
                )}
                <button type="button" className="mk-btn mk-btn--big mk-btn--block" onClick={reset} autoFocus>
                    {L.next}
                </button>
            </section>
        );
    }

    const locked = order !== null && isLocked(order);
    const issuable = order !== null && !FINAL.has(order.status.code);

    return (
        <div className="mk-pt">
            <SampleNote show={sample} />
            <h2 className="mk-pt__title">{L.title}</h2>

            <form className="mk-pt-step" onSubmit={(e) => void find(e)} noValidate>
                <label className="mk-pt-big">
                    <span>{L.numberLabel}</span>
                    <input
                        value={number}
                        onChange={(e) => setNumber(e.target.value.toUpperCase())}
                        autoCapitalize="characters"
                        autoCorrect="off"
                        autoComplete="off"
                        spellCheck={false}
                        enterKeyHint="search"
                        maxLength={20}
                        placeholder="K7M2PX9QAD"
                        aria-invalid={numberError !== null}
                        autoFocus
                    />
                    <small className={numberError ? 'is-error' : undefined}>{numberError ?? L.numberHint}</small>
                </label>
                <button type="submit" className="mk-btn mk-btn--big mk-btn--block" disabled={searching}>
                    <Search size={20} aria-hidden /> {searching ? L.searching : L.find}
                </button>
            </form>

            {sample && <p className="mk-pt-hint">{L.sampleHint(samples.map((o) => o.number).join(', '))}</p>}

            {notFound && (
                <div className="mk-pt-alert" role="alert">
                    <b>{L.notFound}</b>
                    <span>{L.notFoundText}</span>
                </div>
            )}

            {order && (
                <section className="mk-pt-order" aria-label={`${S.order} ${order.number}`}>
                    <div className="mk-pt-order__hd">
                        <b className="mk-pt-order__number">{order.number}</b>
                        <span className="mk-pill">{order.status.text}</span>
                    </div>
                    <dl className="mk-pt-order__facts">
                        <div>
                            <dt>{L.placesLabel}</dt>
                            <dd>{L.places(order.places)}</dd>
                        </div>
                        {order.until && (
                            <div>
                                <dt>{L.until}</dt>
                                <dd>{when(order.until)}</dd>
                            </div>
                        )}
                    </dl>
                    {order.toPay !== null ? (
                        <p className="mk-pt-order__pay">
                            <span>{L.toPay}</span>
                            <b>{S.money(sum(order.toPay))}</b>
                        </p>
                    ) : (
                        <p className="mk-pt-order__paid">{L.paidCard}</p>
                    )}

                    {!issuable && <p className="mk-pt-alert">{L.notIssuable(order.status.text)}</p>}

                    {issuable && locked && order.lockedUntil && (
                        <div className="mk-pt-alert" role="alert">
                            <b>
                                <Lock size={18} aria-hidden /> {L.locked(clock(order.lockedUntil))}
                            </b>
                            <span>{L.lockedText}</span>
                        </div>
                    )}

                    {issuable && !locked && !refusing && (
                        <form className="mk-pt-step" onSubmit={(e) => void issue(e)} noValidate>
                            <label className="mk-pt-big mk-pt-big--code">
                                <span>{L.codeLabel}</span>
                                <input
                                    value={code}
                                    onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                                    inputMode="numeric"
                                    autoComplete="one-time-code"
                                    enterKeyHint="done"
                                    pattern="[0-9]{6}"
                                    maxLength={6}
                                    placeholder="••••••"
                                    aria-invalid={codeError !== null}
                                    autoFocus
                                />
                                <small className={codeError ? 'is-error' : undefined} role={codeError ? 'alert' : undefined}>
                                    {codeError ?? L.codeHint}
                                </small>
                            </label>
                            <button type="submit" className="mk-btn mk-btn--big mk-btn--block mk-pt-go" disabled={busy || code.length !== 6}>
                                {busy ? L.issuing : L.issue}
                            </button>
                        </form>
                    )}

                    {issuable && !refusing && (
                        <button type="button" className="mk-btn mk-btn--ghost mk-btn--block mk-pt-tall" onClick={() => setRefusing(true)}>
                            {L.refuse}
                        </button>
                    )}

                    {issuable && refusing && (
                        <form className="mk-pt-step mk-pt-refuse" onSubmit={(e) => void refuse(e)} noValidate>
                            <h3>{L.refuseTitle}</h3>
                            <p>{L.refuseText}</p>
                            <label className="mk-field">
                                {S.reason}
                                <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3} maxLength={500} placeholder={L.refusePlaceholder} autoFocus />
                                {reasonError && <small className="is-error">{reasonError}</small>}
                            </label>
                            <button type="submit" className="mk-btn mk-btn--big mk-btn--block mk-pt-danger" disabled={busy}>
                                {L.refuseConfirm}
                            </button>
                            <button type="button" className="mk-btn mk-btn--ghost mk-btn--block mk-pt-tall" disabled={busy} onClick={() => setRefusing(false)}>
                                {S.cancel}
                            </button>
                        </form>
                    )}

                    <button type="button" className="mk-pt-link" onClick={reset}>
                        {L.other}
                    </button>
                </section>
            )}
        </div>
    );
}
