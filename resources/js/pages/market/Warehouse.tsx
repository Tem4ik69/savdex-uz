import { usePage } from '@inertiajs/react';
import { Picking } from '@/components/market/staff/Picking';
import { Receiving } from '@/components/market/staff/Receiving';
import { Removals } from '@/components/market/staff/Removals';
import { Returns } from '@/components/market/staff/Returns';
import { Shipments } from '@/components/market/staff/Shipments';
import { Stock } from '@/components/market/staff/Stock';
import { Supplies } from '@/components/market/staff/Supplies';
import { Writeoffs } from '@/components/market/staff/Writeoffs';
import { StaffGate, StaffLayout, type StaffTab } from '@/layouts/StaffLayout';
import { lang } from '@/market/lang';
import type { WarehouseMe, WarehouseTab } from '@/market/staff/contract';
import { useStaffData } from '@/market/staff/data';
import { sampleWarehouseMe } from '@/market/staff/samples';
import { staffText } from '@/market/text/staff';
import { warehouseText } from '@/market/text/warehouse';
import { routes } from '@/routes';
import type { SharedProps } from '@/types';

const TABS: WarehouseTab[] = ['supplies', 'receiving', 'stock', 'picking', 'shipments', 'returns', 'removals', 'writeoffs'];

/**
 * Экран сотрудника склада (планшет) — ТЗ «2026-11-23 Команда — склад
 * маркетплейса SavdEx», раздел «Экраны»: поставки, приёмка, остатки,
 * сборка, отгрузки, возвраты, вывоз, списания. Только свой склад —
 * проверяет сервер (/market/api/warehouse/…); до адресов — образцы.
 */
export default function MarketWarehouse({ tab }: { tab: WarehouseTab }) {
    const L = lang(staffText);
    const W = lang(warehouseText);
    const { auth } = usePage<SharedProps>().props;
    const me = useStaffData<WarehouseMe>(auth.user ? 'warehouse/me' : null, sampleWarehouseMe);
    const blocked = !auth.user || (me.status !== null && !me.loading);
    const tabs: StaffTab[] = blocked
        ? []
        : TABS.map((key) => ({ key, label: W.tabs[key], href: routes.marketWarehouse(key), count: me.data?.counts[key] }));

    return (
        <StaffLayout kind="warehouse" title={`${L.warehouseTitle} · SavdEx Market`} place={me.data?.warehouse ?? null} staff={me.data?.staff.name ?? null} tabs={tabs} tab={tab}>
            {blocked ? (
                <StaffGate kind="warehouse" status={auth.user ? me.status : 401} error={me.error} reload={me.reload} />
            ) : (
                <>
                    {tab === 'supplies' && <Supplies />}
                    {tab === 'receiving' && <Receiving />}
                    {tab === 'stock' && <Stock />}
                    {tab === 'picking' && <Picking />}
                    {tab === 'shipments' && <Shipments />}
                    {tab === 'returns' && <Returns />}
                    {tab === 'removals' && <Removals />}
                    {tab === 'writeoffs' && <Writeoffs />}
                </>
            )}
        </StaffLayout>
    );
}
