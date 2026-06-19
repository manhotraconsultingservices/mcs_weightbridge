/**
 * Accounts hub — Payments · Account Statement · GST Returns · GSTR-2B (ITC) ·
 * Compliance Docs · Activity Log in tabs.
 *
 * URL sync: ?tab=payments | ?tab=statement | ?tab=gst | ?tab=gstr2b |
 *           ?tab=compliance | ?tab=activity. Default = payments.
 * Existing routes (/payments, /ledger, /gst-reports, etc.) still work
 * standalone for deep-links from emails or bookmarks.
 */
import { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { CreditCard, BookOpen, FileBarChart, FileBarChart2, ShieldCheck, Shield } from 'lucide-react';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import PaymentsPage from './PaymentsPage';
import LedgerPage from './LedgerPage';
import GstReportsPage from './GstReportsPage';
import Gstr2bReconcilePage from './Gstr2bReconcilePage';
import CompliancePage from './CompliancePage';
import AuditPage from './AuditPage';

type Tab = 'payments' | 'statement' | 'gst' | 'gstr2b' | 'compliance' | 'activity';

export default function AccountsHubPage() {
  const nav = useNavigate();
  const loc = useLocation();
  const initial = (new URLSearchParams(loc.search).get('tab') as Tab) || 'payments';
  const [tab, setTab] = useState<Tab>(initial);

  // Keep URL in sync so refresh / share preserves the active tab
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
        <TabsList>
          <TabsTrigger value="payments" className="gap-1.5"><CreditCard className="h-3.5 w-3.5" /> Payments</TabsTrigger>
          <TabsTrigger value="statement" className="gap-1.5"><BookOpen className="h-3.5 w-3.5" /> Account Statement</TabsTrigger>
          <TabsTrigger value="gst" className="gap-1.5"><FileBarChart className="h-3.5 w-3.5" /> GST Returns</TabsTrigger>
          <TabsTrigger value="gstr2b" className="gap-1.5"><FileBarChart2 className="h-3.5 w-3.5" /> GSTR-2B (ITC)</TabsTrigger>
          <TabsTrigger value="compliance" className="gap-1.5"><ShieldCheck className="h-3.5 w-3.5" /> Compliance Docs</TabsTrigger>
          <TabsTrigger value="activity" className="gap-1.5"><Shield className="h-3.5 w-3.5" /> Activity Log</TabsTrigger>
        </TabsList>
        <TabsContent value="payments" className="mt-4">
          <PaymentsPage />
        </TabsContent>
        <TabsContent value="statement" className="mt-4">
          <LedgerPage />
        </TabsContent>
        <TabsContent value="gst" className="mt-4">
          <GstReportsPage />
        </TabsContent>
        <TabsContent value="gstr2b" className="mt-4">
          <Gstr2bReconcilePage />
        </TabsContent>
        <TabsContent value="compliance" className="mt-4">
          <CompliancePage />
        </TabsContent>
        <TabsContent value="activity" className="mt-4">
          <AuditPage />
        </TabsContent>
      </Tabs>
    </div>
  );
}
