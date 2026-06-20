/**
 * Reports hub — everything an accountant/owner needs to look back at.
 *
 *   Payments · Account Statement · GST · P&L + Sales · Compliance · Activity Log
 */
import { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { CreditCard, BookOpen, FileBarChart, BarChart3, ShieldCheck, Shield, XCircle, PieChart, TrendingUp, ShieldAlert, DoorOpen, Ticket } from 'lucide-react';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import PaymentsPage from './PaymentsPage';
import LedgerPage from './LedgerPage';
import GstReportsPage from './GstReportsPage';
import ReportsPage from './ReportsPage';
import CompliancePage from './CompliancePage';
import AuditPage from './AuditPage';
import WriteOffsReportPage from './WriteOffsReportPage';
import GstSplitReportPage from './GstSplitReportPage';
import Gstr2bReconcilePage from './Gstr2bReconcilePage';
import SalesStatusReportPage from './SalesStatusReportPage';
import AnomalyReportPage from './AnomalyReportPage';
import GatePassRegisterPage from './GatePassRegisterPage';
import TokenRegisterPage from './TokenRegisterPage';

type Tab = 'payments' | 'statement' | 'gst' | 'gstr2b' | 'gst-split' | 'sales-status' | 'reports' | 'write-offs' | 'compliance' | 'activity' | 'anomaly' | 'gate-passes' | 'token-register';

export default function ReportsHubPage() {
  const { t } = useTranslation();
  const nav = useNavigate();
  const loc = useLocation();
  // Default to "reports" so /reports URL behaves like the old /reports page.
  // Sidebar links can override via ?tab=<x>.
  const initial = (new URLSearchParams(loc.search).get('tab') as Tab) || 'reports';
  const [tab, setTab] = useState<Tab>(initial);

  const TABS: { value: Tab; label: string; icon: React.ElementType }[] = [
    { value: 'payments', label: t('payment.title'), icon: CreditCard },
    { value: 'statement', label: t('reports.accountStatement'), icon: BookOpen },
    { value: 'gst', label: t('reports.gstReturns'), icon: FileBarChart },
    { value: 'gstr2b', label: t('reports.gstr2b'), icon: FileBarChart },
    { value: 'gst-split', label: t('reports.gstVsCash'), icon: PieChart },
    { value: 'sales-status', label: t('reports.salesByStatus'), icon: TrendingUp },
    { value: 'reports', label: t('reports.plSales'), icon: BarChart3 },
    { value: 'write-offs', label: t('reports.writeoffs'), icon: XCircle },
    { value: 'compliance', label: t('reports.documents'), icon: ShieldCheck },
    { value: 'activity', label: t('reports.activityLog'), icon: Shield },
    { value: 'anomaly', label: t('reports.anomaly'), icon: ShieldAlert },
    { value: 'gate-passes', label: 'Gate Pass Register', icon: DoorOpen },
    { value: 'token-register', label: 'Token Register', icon: Ticket },
  ];

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
        <TabsContent value="gstr2b" className="mt-4"><Gstr2bReconcilePage /></TabsContent>
        <TabsContent value="gst-split" className="mt-4"><GstSplitReportPage /></TabsContent>
        <TabsContent value="sales-status" className="mt-4"><SalesStatusReportPage /></TabsContent>
        <TabsContent value="reports" className="mt-4"><ReportsPage /></TabsContent>
        <TabsContent value="write-offs" className="mt-4"><WriteOffsReportPage /></TabsContent>
        <TabsContent value="compliance" className="mt-4"><CompliancePage /></TabsContent>
        <TabsContent value="activity" className="mt-4"><AuditPage /></TabsContent>
        <TabsContent value="anomaly" className="mt-4"><AnomalyReportPage /></TabsContent>
        <TabsContent value="gate-passes" className="mt-4"><GatePassRegisterPage /></TabsContent>
        <TabsContent value="token-register" className="mt-4"><TokenRegisterPage /></TabsContent>
      </Tabs>
    </div>
  );
}
