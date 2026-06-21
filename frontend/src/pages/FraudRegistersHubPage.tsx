/**
 * Fraud & Registers hub — Anomaly Detection · Gate Pass Register · Token Register
 *
 * Split from AnalyticsHubPage to keep each hub under 4 tabs on mobile.
 * URL sync: ?tab=anomaly | ?tab=gate-passes | ?tab=token-register. Default = anomaly.
 */
import { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { ShieldAlert, DoorOpen, Ticket } from 'lucide-react';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { MobileTabSelect } from '@/components/MobileTabSelect';
import { usePermissions } from '@/contexts/PermissionsContext';
import AnomalyReportPage from './AnomalyReportPage';
import GatePassRegisterPage from './GatePassRegisterPage';
import TokenRegisterPage from './TokenRegisterPage';

type Tab = 'anomaly' | 'gate-passes' | 'token-register';

const TABS: { value: Tab; label: string; icon: React.ElementType }[] = [
  { value: 'anomaly',        label: 'Anomaly Detection',  icon: ShieldAlert },
  { value: 'gate-passes',    label: 'Gate Pass Register', icon: DoorOpen },
  { value: 'token-register', label: 'Token Register',     icon: Ticket },
];

export default function FraudRegistersHubPage() {
  const nav = useNavigate();
  const loc = useLocation();
  const { isTabAllowed } = usePermissions();
  const visibleTabs = TABS.filter(t => isTabAllowed('/fraud-registers', t.value));
  const initialRaw = (new URLSearchParams(loc.search).get('tab') as Tab) || 'anomaly';
  const initial = (visibleTabs.find(t => t.value === initialRaw)?.value ?? visibleTabs[0]?.value ?? 'anomaly') as Tab;
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
        <TabsContent value="anomaly"        className="mt-4"><AnomalyReportPage /></TabsContent>
        <TabsContent value="gate-passes"    className="mt-4"><GatePassRegisterPage /></TabsContent>
        <TabsContent value="token-register" className="mt-4"><TokenRegisterPage /></TabsContent>
      </Tabs>
    </div>
  );
}
