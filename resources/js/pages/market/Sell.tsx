import { usePage } from '@inertiajs/react';
import { CircleCheck, CircleX } from 'lucide-react';
import { useState, type FormEvent } from 'react';
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
 * Подтверждение через OneID появится, когда его подключат.
 */
export default function MarketSell() {
    const { auth } = usePage<SharedProps>().props;
    const { data, loading, error, reload } = useApi<SellerApplication>(auth.user ? 'me/seller' : null);
    const [sent, setSent] = useState<SellerApplication | null>(null);
    const state = sent ?? data;

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
    const [sending, setSending] = useState(false);
    const ready = Object.values(state.checks).every(Boolean);

    async function submit(event: FormEvent) {
        event.preventDefault();

        if (!agreed) {
            setProblem('Без согласия с офертой заявку не отправить');

            return;
        }

        setSending(true);
        setProblem(null);

        try {
            const data = await api<{ message: string; seller: SellerApplication }>('me/seller/apply', { body: { offer: true, note: note.trim() } });

            notify(data.message);
            onSent(data.seller);
        } catch (failure) {
            setProblem(failure instanceof ApiError ? failure.message : 'Не получилось отправить заявку. Попробуйте ещё раз.');
        } finally {
            setSending(false);
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
            <div className="mk-oneid">
                <span>
                    <b>Подтвердить через OneID</b>
                    <small>Быстрый способ: ЭЦП для компании или вход для ИП. Скоро.</small>
                </span>
                <button type="button" className="mk-btn mk-btn--ghost" disabled>
                    OneID
                </button>
            </div>
            <p className="mk-or">пока — по документам компании</p>

            <ul className="mk-checks">
                {CHECKS.map(([key, label, action]) => (
                    <li key={key} className={state.checks[key] ? 'is-ok' : 'is-miss'}>
                        {state.checks[key] ? <CircleCheck size={18} aria-hidden /> : <CircleX size={18} aria-hidden />}
                        <span>
                            {label}
                            <span className="sr-only">{state.checks[key] ? ' — готово' : ' — не выполнено'}</span>
                        </span>
                        {!state.checks[key] && key !== 'owner' && <Link href={routes.cabinetCompany}>{action}</Link>}
                    </li>
                ))}
            </ul>

            {ready ? (
                <form className="mk-form" onSubmit={submit} noValidate>
                    <label className="mk-field">
                        Что будете продавать (необязательно)
                        <textarea id="mk-sell-note" rows={3} maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Например: домашний текстиль собственного производства" />
                    </label>
                    <label className="mk-check">
                        <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />
                        Принимаю оферту продавца
                    </label>
                    {problem && (
                        <small style={{ color: 'var(--danger)' }} role="alert">
                            {problem}
                        </small>
                    )}
                    <button type="submit" className="mk-btn" disabled={sending}>
                        Отправить заявку
                    </button>
                </form>
            ) : (
                <p className="mk-hint">Заявку можно будет отправить, когда выполнены все пункты. Карточка компании, ИНН и документы — в кабинете компании на SavdEx.</p>
            )}
        </>
    );
}
