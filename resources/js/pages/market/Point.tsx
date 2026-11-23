import { usePage } from '@inertiajs/react';
import { Batches } from '@/components/market/staff/Batches';
import { Cash } from '@/components/market/staff/Cash';
import { Issue } from '@/components/market/staff/Issue';
import { Unclaimed } from '@/components/market/staff/Unclaimed';
import { StaffGate, StaffLayout, type StaffTab } from '@/layouts/StaffLayout';
import { lang } from '@/market/lang';
import type { PointMe, PointTab } from '@/market/staff/contract';
import { useStaffData } from '@/market/staff/data';
import { samplePointMe } from '@/market/staff/samples';
import { pointText } from '@/market/text/point';
import { staffText } from '@/market/text/staff';
import { routes } from '@/routes';
import type { SharedProps } from '@/types';

const TABS: PointTab[] = ['issue', 'batches', 'unclaimed', 'cash'];

/**
 * Экран сотрудника пункта выдачи (телефон): выдать по коду, принять
 * партию, невостребованные, наличные за день. Только свой пункт — проверяет
 * сервер (/market/api/point/…); имени и телефона покупателя экран не
 * видит (решение 23.11). До адресов — образцы.
 */
export default function MarketPoint({ tab }: { tab: PointTab }) {
    const L = lang(staffText);
    const P = lang(pointText);
    const { auth } = usePage<SharedProps>().props;
    const me = useStaffData<PointMe>(auth.user ? 'point/me' : null, samplePointMe);
    const blocked = !auth.user || (me.status !== null && !me.loading);
    const tabs: StaffTab[] = blocked ? [] : TABS.map((key) => ({ key, label: P.tabs[key], href: routes.marketPoint(key), count: me.data?.counts[key] }));

    return (
        <StaffLayout kind="point" title={`${L.pointTitle} · SavdEx Market`} place={me.data?.point ?? null} staff={me.data?.staff.name ?? null} tabs={tabs} tab={tab}>
            {blocked ? (
                <StaffGate kind="point" status={auth.user ? me.status : 401} error={me.error} reload={me.reload} />
            ) : (
                <>
                    {tab === 'issue' && <Issue />}
                    {tab === 'batches' && <Batches />}
                    {tab === 'unclaimed' && <Unclaimed />}
                    {tab === 'cash' && <Cash />}
                </>
            )}
        </StaffLayout>
    );
}
