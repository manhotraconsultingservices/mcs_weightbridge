/**
 * GST & Compliance hub — GST Returns · GSTR-2B (ITC) · Compliance Docs
 *
 * Split from AccountsHubPage to keep each hub under 4 tabs on mobile.
 * URL sync: ?tab=gst | ?tab=gstr2b | ?tab=compliance. Default = gst.
 */
import { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { FileBarChart, FileBarChart2, ShieldCheck } from 'lucide-react';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { MobileTabSelect } from '@/components/MobileTabSelect';
import { usePermissions } from '@/contexts/PermissionsContext';
import GstReportsPage from './GstReportsPage';
import Gstr2bReconcilePage from './Gstr2bReconcilePage';
import CompliancePage from './CompliancePage';

type Tab = 'gst' | 'gstr2b' | 'compliance';

export default function GstComplianceHubPage() {
  const { t } = useTranslation();
  const nav = useNavigate();
  const loc = useLocation();
  const { isTabAllowed } = usePermissions();

  const TABS: { value: Tab; label: string; icon: React.ElementType }[] = [
    { value: 'gst',        label: t('hubs.gstCompliance.gstReturns'),    icon: FileBarChart },
    { value: 'gstr2b',     label: t('hubs.gstCompliance.gstr2b'),        icon: FileBarChart2 },
    { value: 'compliance', label: t('hubs.gstCompliance.complianceDocs'), icon: ShieldCheck },
  ];
  const visibleTabs = TABS.filter(t => isTabAllowed('/gst-compliance', t.value));
  const initialRaw = (new URLSearchParams(loc.search).get('tab') as Tab) || 'gst';
  const initial = (visibleTabs.find(t => t.value === initialRaw)?.value ?? visibleTabs[0]?.value ?? 'gst') as Tab;
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
        <TabsContent value="gst"        className="mt-4"><GstReportsPage /></TabsContent>
        <TabsContent value="gstr2b"     className="mt-4"><Gstr2bReconcilePage /></TabsContent>
        <TabsContent value="compliance" className="mt-4"><CompliancePage /></TabsContent>
      </Tabs>
    </div>
  );
}
