/**
 * Weighbridge hub — Gate Register · Weigh Tickets · Movement Report
 *
 * Camera & Scale / Snapshots / ANPR moved to CamerasAnprHubPage (/cameras-anpr).
 * URL sync: ?tab=gate | ?tab=tickets | ?tab=movement. Default = gate.
 */
import { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { DoorOpen, Scale, BarChart3 } from 'lucide-react';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { MobileTabSelect } from '@/components/MobileTabSelect';
import { usePermissions } from '@/contexts/PermissionsContext';
import GatePassPage from './GatePassPage';
import TokenPageV1 from './TokenPageV1';
import AnprTripsPage from './AnprTripsPage';

type Tab = 'gate' | 'tickets' | 'movement';

export default function WeighbridgeHubPage() {
  const { t } = useTranslation();
  const nav = useNavigate();
  const loc = useLocation();
  const { isTabAllowed } = usePermissions();

  const TABS: { value: Tab; label: string; icon: React.ElementType }[] = [
    { value: 'gate',     label: t('hubs.weighbridge.gateRegister'),    icon: DoorOpen },
    { value: 'tickets',  label: t('hubs.weighbridge.weighTickets'),    icon: Scale },
    { value: 'movement', label: t('hubs.weighbridge.movementReport'),  icon: BarChart3 },
  ];
  const visibleTabs = TABS.filter(t => isTabAllowed('/weighbridge', t.value));
  const initialRaw = (new URLSearchParams(loc.search).get('tab') as Tab) || 'gate';
  const initial = (visibleTabs.find(t => t.value === initialRaw)?.value ?? visibleTabs[0]?.value ?? 'gate') as Tab;
  const [tab, setTab] = useState<Tab>(initial);

  useEffect(() => {
    const params = new URLSearchParams(loc.search);
    if (params.get('tab') !== tab) {
      params.set('tab', tab);
      nav({ search: params.toString() }, { replace: true });
    }
  }, [tab, loc.search, nav]);

  return (
    <div className="space-y-3">
      <Tabs value={tab} onValueChange={(v) => setTab(v as Tab)}>
        <MobileTabSelect value={tab} onValueChange={(v) => setTab(v as Tab)} options={visibleTabs.map(t => ({ value: t.value, label: t.label }))} />
        <TabsList className="hidden sm:inline-flex flex-wrap h-auto">
          {visibleTabs.map(t => {
            const Icon = t.icon;
            return (
              <TabsTrigger key={t.value} value={t.value} className="gap-1.5">
                <Icon className="h-3.5 w-3.5" /> {t.label}
              </TabsTrigger>
            );
          })}
        </TabsList>
        <TabsContent value="gate"     className="mt-4"><GatePassPage /></TabsContent>
        <TabsContent value="tickets"  className="mt-4"><TokenPageV1 /></TabsContent>
        <TabsContent value="movement" className="mt-4"><AnprTripsPage /></TabsContent>
      </Tabs>
    </div>
  );
}
