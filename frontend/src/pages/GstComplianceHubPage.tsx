/**
 * GST & Compliance hub — GST Returns · GSTR-2B (ITC) · Compliance Docs
 *
 * Split from AccountsHubPage to keep each hub under 4 tabs on mobile.
 * URL sync: ?tab=gst | ?tab=gstr2b | ?tab=compliance. Default = gst.
 */
import { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { FileBarChart, FileBarChart2, ShieldCheck } from 'lucide-react';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { MobileTabSelect } from '@/components/MobileTabSelect';
import GstReportsPage from './GstReportsPage';
import Gstr2bReconcilePage from './Gstr2bReconcilePage';
import CompliancePage from './CompliancePage';

type Tab = 'gst' | 'gstr2b' | 'compliance';

const TABS: { value: Tab; label: string; icon: React.ElementType }[] = [
  { value: 'gst',        label: 'GST Returns',    icon: FileBarChart },
  { value: 'gstr2b',     label: 'GSTR-2B (ITC)',  icon: FileBarChart2 },
  { value: 'compliance', label: 'Compliance Docs', icon: ShieldCheck },
];

export default function GstComplianceHubPage() {
  const nav = useNavigate();
  const loc = useLocation();
  const initial = (new URLSearchParams(loc.search).get('tab') as Tab) || 'gst';
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
        <MobileTabSelect value={tab} onValueChange={(v) => setTab(v as Tab)} options={TABS.map(t => ({ value: t.value, label: t.label }))} />
        <TabsList className="hidden sm:inline-flex flex-wrap h-auto">
          {TABS.map(t => {
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
