/**
 * Reports hub — everything an accountant/owner needs to look back at.
 *
 *   Payments · Account Statement · GST · P&L + Sales · Compliance · Activity Log
 */
import { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { CreditCard, BookOpen, FileBarChart, BarChart3, ShieldCheck, Shield } from 'lucide-react';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import PaymentsPage from './PaymentsPage';
import LedgerPage from './LedgerPage';
import GstReportsPage from './GstReportsPage';
import ReportsPage from './ReportsPage';
import CompliancePage from './CompliancePage';
import AuditPage from './AuditPage';

type Tab = 'payments' | 'statement' | 'gst' | 'reports' | 'compliance' | 'activity';

const TABS: { value: Tab; label: string; icon: React.ElementType }[] = [
  { value: 'payments', label: 'Payments', icon: CreditCard },
  { value: 'statement', label: 'Account Statement', icon: BookOpen },
  { value: 'gst', label: 'GST', icon: FileBarChart },
  { value: 'reports', label: 'P&L + Sales', icon: BarChart3 },
  { value: 'compliance', label: 'Documents', icon: ShieldCheck },
  { value: 'activity', label: 'Activity Log', icon: Shield },
];

export default function ReportsHubPage() {
  const nav = useNavigate();
  const loc = useLocation();
  // Default to "reports" so /reports URL behaves like the old /reports page.
  // Sidebar links can override via ?tab=<x>.
  const initial = (new URLSearchParams(loc.search).get('tab') as Tab) || 'reports';
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
        <TabsList className="flex-wrap h-auto">
          {TABS.map(t => {
            const Icon = t.icon;
            return (
              <TabsTrigger key={t.value} value={t.value} className="gap-1.5">
                <Icon className="h-3.5 w-3.5" /> {t.label}
              </TabsTrigger>
            );
          })}
        </TabsList>
        <TabsContent value="payments" className="mt-4"><PaymentsPage /></TabsContent>
        <TabsContent value="statement" className="mt-4"><LedgerPage /></TabsContent>
        <TabsContent value="gst" className="mt-4"><GstReportsPage /></TabsContent>
        <TabsContent value="reports" className="mt-4"><ReportsPage /></TabsContent>
        <TabsContent value="compliance" className="mt-4"><CompliancePage /></TabsContent>
        <TabsContent value="activity" className="mt-4"><AuditPage /></TabsContent>
      </Tabs>
    </div>
  );
}
