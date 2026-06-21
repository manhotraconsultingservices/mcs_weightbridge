/**
 * Production hub — Daily Production · Dashboard · Settings
 *
 * Split from InventoryProductionHubPage to keep each hub under 4 tabs on mobile.
 * URL sync: ?tab=production | ?tab=dashboard | ?tab=settings. Default = production.
 */
import { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Factory, Activity, Settings } from 'lucide-react';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { MobileTabSelect } from '@/components/MobileTabSelect';
import { usePermissions } from '@/contexts/PermissionsContext';
import ProductionPage from './ProductionPage';
import ProductionDashboardPage from './ProductionDashboardPage';
import ProductionSettingsPage from './ProductionSettingsPage';

type Tab = 'production' | 'dashboard' | 'settings';

const TABS: { value: Tab; label: string; icon: React.ElementType }[] = [
  { value: 'production', label: 'Daily Production', icon: Factory },
  { value: 'dashboard',  label: 'Dashboard',        icon: Activity },
  { value: 'settings',   label: 'Settings',         icon: Settings },
];

export default function ProductionHubPage() {
  const nav = useNavigate();
  const loc = useLocation();
  const { isTabAllowed } = usePermissions();
  const visibleTabs = TABS.filter(t => isTabAllowed('/production-hub', t.value));
  const initialRaw = (new URLSearchParams(loc.search).get('tab') as Tab) || 'production';
  const initial = (visibleTabs.find(t => t.value === initialRaw)?.value ?? visibleTabs[0]?.value ?? 'production') as Tab;
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
        <TabsContent value="production" className="mt-4"><ProductionPage /></TabsContent>
        <TabsContent value="dashboard"  className="mt-4"><ProductionDashboardPage /></TabsContent>
        <TabsContent value="settings"   className="mt-4"><ProductionSettingsPage /></TabsContent>
      </Tabs>
    </div>
  );
}
