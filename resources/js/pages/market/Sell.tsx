import { usePage } from '@inertiajs/react';
import { CircleCheck, CircleX } from 'lucide-react';
import { useEffect, useState, type FormEvent } from 'react';
import { Link } from '@/components/ui/Link';
import { MarketLayout } from '@/layouts/MarketLayout';
import { api, ApiError, useApi } from '@/market/api';
import { notify } from '@/market/store';
import type { SellerApplication } from '@/market/types';
import { routes } from '@/routes';
import type { SharedProps } from '@/types';

/** Что нужно для заявки — в порядке, в котором это делают. */
const CHECKS: [keyof SellerApplication['checks'], string, string][] = [
    ['company', 'Компания или ИП на SavdEx', 'Создайте карточку компании'],
    ['owner', 'Заявку подаёт владелец компании', 'Войдите под владельцем компании'],
    ['tin', 'В карточке компании указан ИНН', 'Укажите ИНН'],
    ['documents', 'Загружен документ о регистрации', 'Загрузите документ'],
];

/**
 * «Стать продавцом»: что это даёт, как устроено и заявка
 * (/market/api/me/seller). Продавец — компания на SavdEx: её карточка,
 * ИНН и документы уже есть в кабинете, копий здесь нет. Заявку подаёт
 * владелец, модератор подтверждает или отклоняет с причиной.
 * Подтверждение через OneID (/market/api/oneid/start) — быстрый путь:
 * ЭЦП для компании или вход для ИП, ИНН сверяется с компанией на SavdEx.
 * OneID возвращает человека сюда же с итогом в адресе (?oneid=…).
 */

/** Итоги возврата из OneID: что произошло и тон сообщения. */
const ONEID_RESULTS: Record<string, [string, boolean]> = {
    ok: ['OneID подтвердил компанию — вы продавец SavdEx Market.', false],
    review: ['OneID пройден, заявка ушла модератору на проверку.', false],
    off: ['Подтверждение через OneID пока не подключено — подайте заявку с документами.', true],
    denied: ['Вход в OneID отменён. Попробуйте ещё раз или подайте заявку с документами.', true],
    expired: ['Время на подтверждение вышло. Начните заново.', true],
    mismatch: ['ИНН в OneID не совпал с ИНН компании на SavdEx. Проверьте ИНН в карточке компании или подайте заявку с документами.', true],
    blocked: ['Продажи компании приостановлены — подтвердить через OneID нельзя. Напишите в поддержку.', true],
    error: ['OneID не ответил. Попробуйте позже или подайте заявку с документами.', true],
};
export default function MarketSell() {
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

        setOneid(ONEID_RESULTS[result] ? result : 'error');
        params.delete('oneid');
        window.history.replaceState(window.history.state, '', window.location.pathname + (params.toString() ? `?${params}` : ''));
    }, []);

    return (
        <MarketLayout title="Стать продавцом · SavdEx Market">
            <div className="mk-in">
                <nav className="mk-bc" aria-label="Путь">
                    <Link href={routes.market}>Главная</Link>› Стать продавцом
                </nav>

                <div className="mk-sell">
                    <section className="mk-sell__hero">
                        <h1>Продавайте на SavdEx Market — склад, выдача и оплата на нас</h1>
                        <p>Вы привозите товар на склад в Ташкенте. Мы храним его, принимаем оплату и выдаём заказы в пунктах BTS.</p>
                        <ol className="mk-sell__steps">
                            <li>
                                <span>
                                    <b>Подайте заявку</b>
                                    <small>Компания или ИП на SavdEx; проверка документов</small>
                                </span>
                            </li>
                            <li>
                                <span>
                                    <b>Добавьте товары</b>
                                    <small>Первые товары проверяет модератор, дальше — сразу в продажу</small>
                                </span>
                            </li>
                            <li>
                                <span>
                                    <b>Привезите поставку на склад</b>
                                    <small>Продаётся только то, что принято на склад</small>
                                </span>
                            </li>
                            <li>
                                <span>
                                    <b>Получайте начисления</b>
                                    <small>За каждый выданный заказ — за вычетом комиссии площадки</small>
                                </span>
                            </li>
                        </ol>
                    </section>

                    <section className="mk-panel" aria-busy={loading}>
                        {oneid && (
                            <p className={ONEID_RESULTS[oneid][1] ? 'mk-sample' : 'mk-ok-note'} role="status">
                                {ONEID_RESULTS[oneid][0]}
                            </p>
                        )}
                        {!auth.user && (
                            <div className="mk-status">
                                <h2>Заявка продавца</h2>
                                <p>Продавец — это компания или ИП на SavdEx. Войдите в аккаунт компании, чтобы подать заявку.</p>
                                <Link href={routes.loginBack(routes.marketSell)} className="mk-btn">
                                    Войти или зарегистрироваться
                                </Link>
                            </div>
                        )}

                        {loading && <div className="mk-skel-block" style={{ height: 260 }} />}

                        {error && !state && (
                            <div className="mk-status">
                                <h2>Не получилось загрузить заявку</h2>
                                <p>{error}</p>
                                <button type="button" className="mk-btn" onClick={reload}>
                                    Повторить
                                </button>
                            </div>
                        )}

                        {state && (state.status === null || state.status === 'rejected') && <Application state={state} onSent={setSent} />}

                        {state?.status === 'pending' && (
                            <div className="mk-status">
                                <span aria-hidden>⏳</span>
                                <h2>Заявка на проверке</h2>
                                <p>Модератор проверит документы компании и ответит в уведомлениях. Кабинет продавца откроется после подтверждения.</p>
                            </div>
                        )}

                        {state?.status === 'approved' && (
                            <div className="mk-status">
                                <span aria-hidden>✅</span>
                                <h2>Вы — продавец SavdEx Market</h2>
                                <p>Заявка подтверждена. Добавьте товары — после проверки и приёмки на складе они появятся в каталоге.</p>
                                <Link href={routes.marketSeller()} className="mk-btn">
                                    Открыть кабинет продавца
                                </Link>
                            </div>
                        )}

                        {state?.status === 'blocked' && (
                            <div className="mk-status">
                                <span aria-hidden>⛔</span>
                                <h2>Продажи приостановлены</h2>
                                <p>Модератор приостановил продажи вашей компании. Напишите в поддержку — подскажем, что исправить.</p>
                                <Link href={routes.help} className="mk-btn mk-btn--ghost">
                                    Помощь
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
    const [agreed, setAgreed] = useState(false);
    const [note, setNote] = useState('');
    const [problem, setProblem] = useState<string | null>(null);
    const [sending, setSending] = useState<'oneid' | 'documents' | null>(null);
    const ready = Object.values(state.checks).every(Boolean);
    // Для OneID документы не нужны: компанию подтверждает сам OneID
    const oneidReady = state.checks.company && state.checks.owner && state.checks.tin;

    function offer(): boolean {
        if (agreed) return true;

        setProblem('Без согласия с офертой заявку не отправить');

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
            setProblem(failure instanceof ApiError ? failure.message : 'Не получилось открыть OneID. Попробуйте ещё раз.');
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
            setProblem(failure instanceof ApiError ? failure.message : 'Не получилось отправить заявку. Попробуйте ещё раз.');
        } finally {
            setSending(null);
        }
    }

    return (
        <>
            <h2>Заявка продавца</h2>
            {state.status === 'rejected' && (
                <p className="mk-sample">
                    Прошлую заявку отклонили{state.rejectReason ? `: ${state.rejectReason}` : '.'} Исправьте и подайте снова.
                </p>
            )}

            <ul className="mk-checks">
                {CHECKS.map(([key, label, action]) => (
                    <li key={key} className={state.checks[key] ? 'is-ok' : 'is-miss'}>
                        {state.checks[key] ? <CircleCheck size={18} aria-hidden /> : <CircleX size={18} aria-hidden />}
                        <span>
                            {label}
                            {key === 'documents' && <small className="mk-checks__hint"> — не нужен при подтверждении через OneID</small>}
                            <span className="sr-only">{state.checks[key] ? ' — готово' : ' — не выполнено'}</span>
                        </span>
                        {!state.checks[key] && key !== 'owner' && <Link href={routes.cabinetCompany}>{action}</Link>}
                    </li>
                ))}
            </ul>

            <form className="mk-form" onSubmit={(event) => void submit(event)} noValidate>
                <label className="mk-check">
                    <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />
                    Принимаю оферту продавца
                </label>

                <div className="mk-oneid">
                    <span>
                        <b>Подтвердить через OneID</b>
                        <small>Быстро: ЭЦП для компании или вход для ИП. ИНН сверим с карточкой компании.</small>
                    </span>
                    <button type="button" className="mk-btn" disabled={!oneidReady || sending !== null} onClick={() => void viaOneid()}>
                        OneID
                    </button>
                </div>

                <p className="mk-or">или заявка с документами — проверит модератор</p>

                <label className="mk-field">
                    Что будете продавать (необязательно)
                    <textarea id="mk-sell-note" rows={3} maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Например: домашний текстиль собственного производства" />
                </label>
                {problem && (
                    <small style={{ color: 'var(--danger)' }} role="alert">
                        {problem}
                    </small>
                )}
                <button type="submit" className="mk-btn mk-btn--ghost" disabled={!ready || sending !== null}>
                    Отправить заявку с документами
                </button>
                {!oneidReady && <p className="mk-hint">Для заявки нужны карточка компании, ИНН и вход владельца — всё это в кабинете компании на SavdEx.</p>}
                {oneidReady && !ready && <p className="mk-hint">Для заявки с документами загрузите документ о регистрации — или подтвердите компанию через OneID.</p>}
            </form>
        </>
    );
}
