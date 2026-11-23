import { Head, router, usePage } from '@inertiajs/react';
import { LogOut, MapPin } from 'lucide-react';
import type { ReactNode } from 'react';
import { FlashToast } from '@/components/FlashToast';
import { Link } from '@/components/ui/Link';
import { cn } from '@/lib/cn';
import { lang } from '@/market/lang';
import { useNotice } from '@/market/store';
import { staffText } from '@/market/text/staff';
import { routes } from '@/routes';
import type { SharedProps } from '@/types';

export interface StaffTab {
    key: string;
    label: string;
    href: string;
    /** Сколько ждёт работы — кружок на вкладке */
    count?: number;
}

/**
 * Раскладка экранов сотрудников склада (планшет) и пункта выдачи
 * (телефон): без витрины — название места, сотрудник, «Выйти» и крупные
 * вкладки. На телефоне вкладки пункта — нижней панелью, под большой палец.
 */
export function StaffLayout({
    kind,
    title,
    place,
    staff,
    tabs,
    tab,
    children,
}: {
    kind: 'warehouse' | 'point';
    title: string;
    /** Склад или пункт: название и адрес; null — ещё не загрузились */
    place: { name: string; address: string } | null;
    staff: string | null;
    tabs: StaffTab[];
    tab: string;
    children: ReactNode;
}) {
    const L = lang(staffText);
    const { auth } = usePage<SharedProps>().props;
    const notice = useNotice();

    return (
        <div className={cn('mk mk-staff', `mk-staff--${kind}`)}>
            <Head title={title} />
            <header className="mk-staff__hd">
                <div className="mk-staff__in">
                    <span className="mk-staff__logo notranslate" translate="no">
                        Savd<b>Ex</b> <i>{kind === 'warehouse' ? L.warehouseTitle : L.pointTitle}</i>
                    </span>
                    {place && (
                        <span className="mk-staff__place">
                            <MapPin size={14} aria-hidden /> <b>{place.name}</b> <span>{place.address}</span>
                        </span>
                    )}
                    {auth.user && (
                        <span className="mk-staff__user">
                            {staff ?? auth.user.name}
                            <button type="button" onClick={() => router.post(routes.logout)} aria-label={L.logout}>
                                <LogOut size={16} aria-hidden /> <span>{L.logout}</span>
                            </button>
                        </span>
                    )}
                </div>
                {tabs.length > 0 && (
                    <nav className="mk-staff__tabs" aria-label={L.tabsLabel}>
                        <div className="mk-staff__in">
                            {tabs.map((t) => (
                                <Link key={t.key} href={t.href} aria-current={t.key === tab ? 'page' : undefined} preserveScroll>
                                    {t.label}
                                    {t.count ? <span className="mk-staff__count">{t.count}</span> : null}
                                </Link>
                            ))}
                        </div>
                    </nav>
                )}
            </header>
            <main id="main" className="mk-staff__main">
                <div className="mk-staff__in">
                    {children}
                </div>
            </main>
            <FlashToast />
            {notice && (
                <div key={notice.id} className={cn('mk-toast', notice.error && 'mk-toast--error')} role="status">
                    {notice.text}
                </div>
            )}
        </div>
    );
}

/** Гость, чужой или сбой загрузки — вместо экрана. */
export function StaffGate({ kind, status, error, reload }: { kind: 'warehouse' | 'point'; status: number | null; error: string | null; reload: () => void }) {
    const L = lang(staffText);
    const { auth } = usePage<SharedProps>().props;
    const back = kind === 'warehouse' ? routes.marketWarehouse() : routes.marketPoint();

    if (!auth.user || status === 401) {
        return (
            <div className="mk-gate">
                <h2>{L.loginTitle}</h2>
                <p>{L.loginText}</p>
                <Link href={routes.loginBack(back)} className="mk-btn">
                    {L.login}
                </Link>
            </div>
        );
    }

    if (status === 403) {
        return (
            <div className="mk-gate">
                <h2>{L.deniedTitle}</h2>
                <p>{error ?? (kind === 'warehouse' ? L.deniedWarehouse : L.deniedPoint)}</p>
            </div>
        );
    }

    return (
        <div className="mk-failed">
            <h2>{L.failed}</h2>
            <p>{error}</p>
            <button type="button" className="mk-btn" onClick={reload}>
                {L.retry}
            </button>
        </div>
    );
}

/** Полоска «Образец»: адреса раздела на сервере ещё нет (market/staff/data.ts). */
export function SampleNote({ show }: { show: boolean }) {
    const L = lang(staffText);

    if (!show) return null;

    return (
        <p className="mk-sample">
            <b>{L.sampleTitle}:</b> {L.sampleText}
        </p>
    );
}
