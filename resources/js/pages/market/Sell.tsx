import { usePage } from '@inertiajs/react';
import { CircleCheck, CircleX } from 'lucide-react';
import { useEffect, useState, type FormEvent } from 'react';
import { Link } from '@/components/ui/Link';
import { MarketLayout } from '@/layouts/MarketLayout';
import { api, ApiError, useApi } from '@/market/api';
import { lang } from '@/market/lang';
import { notify } from '@/market/store';
import { sellText } from '@/market/text/sell';
import type { SellerApplication } from '@/market/types';
import { routes } from '@/routes';
import type { SharedProps } from '@/types';

/** Что нужно для заявки — в порядке, в котором это делают. */
const CHECKS: (keyof SellerApplication['checks'])[] = ['company', 'owner', 'tin', 'documents'];

/**
 * «Стать продавцом»: что это даёт, как устроено и заявка
 * (/market/api/me/seller). Продавец — компания на SavdEx: её карточка,
 * ИНН и документы уже есть в кабинете, копий здесь нет. Заявку подаёт
 * владелец, модератор подтверждает или отклоняет с причиной.
 * Подтверждение через OneID (/market/api/oneid/start) — быстрый путь:
 * ЭЦП для компании или вход для ИП, ИНН сверяется с компанией на SavdEx.
 * OneID возвращает человека сюда же с итогом в адресе (?oneid=…).
 */

/** Итоги возврата из OneID и тон сообщения (true — предупреждение); тексты — в sellText.oneid. */
const ONEID_RESULTS: Record<string, boolean> = {
    ok: false,
    review: false,
    off: true,
    denied: true,
    expired: true,
    mismatch: true,
    blocked: true,
    error: true,
};
export default function MarketSell() {
    const L = lang(sellText);
    const { auth } = usePage<SharedProps>().props;
    const { data, loading, error, reload } = useApi<SellerApplication>(auth.user ? 'me/seller' : null);
    const [sent, setSent] = useState<SellerApplication | null>(null);
    const [oneid, setOneid] = useState<string | null>(null);
    const state = sent ?? data;

    // Итог возврата из OneID — из адреса, один раз; сам адрес чистим
    useEffect(() => {
        const params = new URLSearchParams(window.location.search);
        const result = params.get('oneid');

        if (!result) return;

        setOneid(Object.hasOwn(ONEID_RESULTS, result) ? result : 'error');
        params.delete('oneid');
        window.history.replaceState(window.history.state, '', window.location.pathname + (params.toString() ? `?${params}` : ''));
    }, []);

    return (
        <MarketLayout title={L.title}>
            <div className="mk-in">
                <nav className="mk-bc" aria-label={L.crumbs}>
                    <Link href={routes.market}>{L.home}</Link>› {L.becomeSeller}
                </nav>

                <div className="mk-sell">
                    <section className="mk-sell__hero">
                        <h1>{L.heroTitle}</h1>
                        <p>{L.heroText}</p>
                        <ol className="mk-sell__steps">
                            {L.steps.map(([step, hint]) => (
                                <li key={step}>
                                    <span>
                                        <b>{step}</b>
                                        <small>{hint}</small>
                                    </span>
                                </li>
                            ))}
                        </ol>
                    </section>

                    <section className="mk-panel" aria-busy={loading}>
                        {oneid && (
                            <p className={ONEID_RESULTS[oneid] ? 'mk-sample' : 'mk-ok-note'} role="status">
                                {L.oneid[oneid]}
                            </p>
                        )}
                        {!auth.user && (
                            <div className="mk-status">
                                <h2>{L.application}</h2>
                                <p>{L.gateText}</p>
                                <Link href={routes.loginBack(routes.marketSell)} className="mk-btn">
                                    {L.loginOrRegister}
                                </Link>
                            </div>
                        )}

                        {loading && <div className="mk-skel-block" style={{ height: 260 }} />}

                        {error && !state && (
                            <div className="mk-status">
                                <h2>{L.loadFailed}</h2>
                                <p>{error}</p>
                                <button type="button" className="mk-btn" onClick={reload}>
                                    {L.retry}
                                </button>
                            </div>
                        )}

                        {state && (state.status === null || state.status === 'rejected') && <Application state={state} onSent={setSent} />}

                        {state?.status === 'pending' && (
                            <div className="mk-status">
                                <span aria-hidden>⏳</span>
                                <h2>{L.pendingTitle}</h2>
                                <p>{L.pendingText}</p>
                            </div>
                        )}

                        {state?.status === 'approved' && (
                            <div className="mk-status">
                                <span aria-hidden>✅</span>
                                <h2>{L.approvedTitle}</h2>
                                <p>{L.approvedText}</p>
                                <Link href={routes.marketSeller()} className="mk-btn">
                                    {L.openCabinet}
                                </Link>
                            </div>
                        )}

                        {state?.status === 'blocked' && (
                            <div className="mk-status">
                                <span aria-hidden>⛔</span>
                                <h2>{L.blockedTitle}</h2>
                                <p>{L.blockedText}</p>
                                <Link href={routes.help} className="mk-btn mk-btn--ghost">
                                    {L.help}
                                </Link>
                            </div>
                        )}
                    </section>
                </div>
            </div>
        </MarketLayout>
    );
}

function Application({ state, onSent }: { state: SellerApplication; onSent: (next: SellerApplication) => void }) {
    const L = lang(sellText);
    const [agreed, setAgreed] = useState(false);
    const [note, setNote] = useState('');
    const [problem, setProblem] = useState<string | null>(null);
    const [sending, setSending] = useState<'oneid' | 'documents' | null>(null);
    const ready = Object.values(state.checks).every(Boolean);
    // Для OneID документы не нужны: компанию подтверждает сам OneID
    const oneidReady = state.checks.company && state.checks.owner && state.checks.tin;

    function offer(): boolean {
        if (agreed) return true;

        setProblem(L.needOffer);

        return false;
    }

    async function viaOneid() {
        if (!offer()) return;

        setSending('oneid');
        setProblem(null);

        try {
            const { redirect } = await api<{ redirect: string }>('oneid/start', { body: { offer: true } });

            window.location.assign(redirect);
        } catch (failure) {
            setProblem(failure instanceof ApiError ? failure.message : L.oneidFailed);
            setSending(null);
        }
    }

    async function submit(event: FormEvent) {
        event.preventDefault();

        if (!offer()) return;

        setSending('documents');
        setProblem(null);

        try {
            const data = await api<{ message: string; seller: SellerApplication }>('me/seller/apply', { body: { offer: true, note: note.trim() } });

            notify(data.message);
            onSent(data.seller);
        } catch (failure) {
            setProblem(failure instanceof ApiError ? failure.message : L.sendFailed);
        } finally {
            setSending(null);
        }
    }

    return (
        <>
            <h2>{L.application}</h2>
            {state.status === 'rejected' && (
                <p className="mk-sample">
                    {L.rejected(state.rejectReason)}
                </p>
            )}

            <ul className="mk-checks">
                {CHECKS.map((key) => (
                    <li key={key} className={state.checks[key] ? 'is-ok' : 'is-miss'}>
                        {state.checks[key] ? <CircleCheck size={18} aria-hidden /> : <CircleX size={18} aria-hidden />}
                        <span>
                            {L.checks[key][0]}
                            {key === 'documents' && <small className="mk-checks__hint">{L.documentsHint}</small>}
                            <span className="sr-only">{state.checks[key] ? L.done : L.notDone}</span>
                        </span>
                        {!state.checks[key] && key !== 'owner' && <Link href={routes.cabinetCompany}>{L.checks[key][1]}</Link>}
                    </li>
                ))}
            </ul>

            <form className="mk-form" onSubmit={(event) => void submit(event)} noValidate>
                <label className="mk-check">
                    <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />
                    {L.acceptOffer}
                </label>

                <div className="mk-oneid">
                    <span>
                        <b>{L.oneidTitle}</b>
                        <small>{L.oneidText}</small>
                    </span>
                    <button type="button" className="mk-btn" disabled={!oneidReady || sending !== null} onClick={() => void viaOneid()}>
                        OneID
                    </button>
                </div>

                <p className="mk-or">{L.or}</p>

                <label className="mk-field">
                    {L.noteLabel}
                    <textarea id="mk-sell-note" rows={3} maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} placeholder={L.notePlaceholder} />
                </label>
                {problem && (
                    <small style={{ color: 'var(--danger)' }} role="alert">
                        {problem}
                    </small>
                )}
                <button type="submit" className="mk-btn mk-btn--ghost" disabled={!ready || sending !== null}>
                    {L.submit}
                </button>
                {!oneidReady && <p className="mk-hint">{L.needAll}</p>}
                {oneidReady && !ready && <p className="mk-hint">{L.needDocuments}</p>}
            </form>
        </>
    );
}
