import { useState, type FormEvent } from 'react';
import { Link } from '@/components/ui/Link';
import { MarketLayout } from '@/layouts/MarketLayout';
import { CATEGORIES } from '@/market/demo';
import { useLocal } from '@/market/local';
import { seller } from '@/market/seller';
import { routes } from '@/routes';

/**
 * «Стать продавцом»: что это даёт, как устроено и заявка.
 *
 * Подтверждение через OneID появится, когда его подключат; до тех пор —
 * заявка с документами и проверка модератором (ТЗ, раздел 4). Заявка в
 * демо хранится в браузере, «одобрить» её можно кнопкой демо.
 */
export default function MarketSell() {
    const state = useLocal(seller);
    const [company, setCompany] = useState('');
    const [tin, setTin] = useState('');
    const [agreed, setAgreed] = useState(false);
    const [tried, setTried] = useState(false);

    const tinOk = /^\d{9}$|^\d{14}$/.test(tin.trim());
    const companyOk = company.trim().length > 2;

    function submit(event: FormEvent) {
        event.preventDefault();
        setTried(true);

        if (!tinOk || !companyOk || !agreed) return;

        seller.set({ ...state, application: 'pending', company: company.trim() });
    }

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
                                    <small>Первые пять проверяет модератор, дальше — сразу в продажу</small>
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

                    <section className="mk-panel">
                        {state.application === 'none' && (
                            <>
                                <h2>Заявка продавца</h2>
                                <div className="mk-oneid">
                                    <span>
                                        <b>Подтвердить через OneID</b>
                                        <small>Быстрый способ: ЭЦП для компании или вход для ИП. Скоро.</small>
                                    </span>
                                    <button type="button" className="mk-btn mk-btn--ghost" disabled>
                                        OneID
                                    </button>
                                </div>
                                <p className="mk-or">или заявка с документами</p>
                                <form className="mk-form mk-form--2" onSubmit={submit} noValidate>
                                    <label className="mk-field mk-field--wide">
                                        Название компании или ИП
                                        <input id="mk-company" value={company} onChange={(e) => setCompany(e.target.value)} />
                                        {tried && !companyOk && <small className="is-error">Укажите название, как в документах</small>}
                                    </label>
                                    <label className="mk-field">
                                        ИНН или ПИНФЛ
                                        <input id="mk-tin" inputMode="numeric" value={tin} onChange={(e) => setTin(e.target.value)} placeholder="9 или 14 цифр" />
                                        {tried && !tinOk && <small className="is-error">ИНН — 9 цифр, ПИНФЛ — 14</small>}
                                    </label>
                                    <label className="mk-field">
                                        Что будете продавать
                                        <select id="mk-sell-category" defaultValue={CATEGORIES[0].slug}>
                                            {CATEGORIES.map((c) => (
                                                <option key={c.slug} value={c.slug}>
                                                    {c.name}
                                                </option>
                                            ))}
                                        </select>
                                    </label>
                                    <label className="mk-field mk-field--wide">
                                        Документы: свидетельство о регистрации
                                        <input id="mk-docs" type="file" accept=".pdf,image/*" style={{ paddingTop: 9 }} />
                                        <small>PDF или фото, до 10 МБ. В демо файл никуда не отправляется.</small>
                                    </label>
                                    <label className="mk-check mk-field--wide">
                                        <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />
                                        Принимаю оферту продавца
                                    </label>
                                    {tried && !agreed && (
                                        <small className="mk-field--wide" style={{ color: 'var(--danger)' }}>
                                            Без согласия с офертой заявку не отправить
                                        </small>
                                    )}
                                    <button type="submit" className="mk-btn mk-field--wide">
                                        Отправить заявку
                                    </button>
                                </form>
                            </>
                        )}

                        {state.application === 'pending' && (
                            <div className="mk-status">
                                <span aria-hidden>⏳</span>
                                <h2>Заявка на проверке</h2>
                                <p>
                                    «{state.company}» — модератор проверит документы и ответит в уведомлениях. Обычно это занимает один
                                    рабочий день. Кабинет продавца откроется после подтверждения.
                                </p>
                                <button type="button" className="mk-demo-btn" onClick={() => seller.set({ ...state, application: 'approved' })}>
                                    Демо: одобрить заявку
                                </button>
                            </div>
                        )}

                        {state.application === 'approved' && (
                            <div className="mk-status">
                                <span aria-hidden>✅</span>
                                <h2>Вы — продавец SavdEx Market</h2>
                                <p>Заявка подтверждена. Добавьте товары и создайте первую поставку на склад.</p>
                                <Link href={routes.marketSeller()} className="mk-btn">
                                    Открыть кабинет продавца
                                </Link>
                                <button type="button" className="mk-demo-btn" onClick={() => seller.set({ ...state, application: 'none', company: '' })}>
                                    Демо: начать заново
                                </button>
                            </div>
                        )}
                    </section>
                </div>
            </div>
        </MarketLayout>
    );
}
