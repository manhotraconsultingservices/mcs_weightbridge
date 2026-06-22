/**
 * Analytics hub — P&L & Sales · Sales by Status · GST vs Cash · Write-offs
 *
 * Anomaly Detection / Gate Pass Register / Token Register moved to FraudRegistersHubPage (/fraud-registers).
 * URL sync: ?tab=pl | ?tab=sales-status | ?tab=gst-split | ?tab=write-offs. Default = pl.
 */
import { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { TrendingUp, BarChart3, PieChart, XCircle } from 'lucide-react';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { MobileTabSelect } from '@/components/MobileTabSelect';
import { usePermissions } from '@/contexts/PermissionsContext';
import ReportsPage from './ReportsPage';
import SalesStatusReportPage from './SalesStatusReportPage';
import GstSplitReportPage from './GstSplitReportPage';
import WriteOffsReportPage from './WriteOffsReportPage';

type Tab = 'pl' | 'sales-status' | 'gst-split' | 'write-offs';

export default function AnalyticsHubPage() {
  const { t } = useTranslation();
  const nav = useNavigate();
  const loc = useLocation();
  const { isTabAllowed } = usePermissions();

  const TABS: { value: Tab; label: string; icon: React.ElementType }[] = [
    { value: 'pl',           label: t('hubs.analytics.plSales'),       icon: TrendingUp },
    { value: 'sales-status', label: t('hubs.analytics.salesByStatus'), icon: BarChart3 },
    { value: 'gst-split',    label: t('hubs.analytics.gstVsCash'),     icon: PieChart },
    { value: 'write-offs',   label: t('hubs.analytics.writeoffs'),     icon: XCircle },
  ];
  const visibleTabs = TABS.filter(t => isTabAllowed('/analytics', t.value));
  const initialRaw = (new URLSearchParams(loc.search).get('tab') as Tab) || 'pl';
  const initial = (visibleTabs.find(t => t.value === initialRaw)?.value ?? visibleTabs[0]?.value ?? 'pl') as Tab;
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
        <TabsContent value="pl"           className="mt-4"><ReportsPage /></TabsContent>
        <TabsContent value="sales-status" className="mt-4"><SalesStatusReportPage /></TabsContent>
        <TabsContent value="gst-split"    className="mt-4"><GstSplitReportPage /></TabsContent>
        <TabsContent value="write-offs"   className="mt-4"><WriteOffsReportPage /></TabsContent>
      </Tabs>
    </div>
  );
}
