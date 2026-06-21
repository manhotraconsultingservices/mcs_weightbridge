/**
 * Accounts hub — Payments · Account Statement · Activity Log
 *
 * GST Returns / GSTR-2B / Compliance moved to GstComplianceHubPage (/gst-compliance).
 * URL sync: ?tab=payments | ?tab=statement | ?tab=activity. Default = payments.
 */
import { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { CreditCard, BookOpen, Shield } from 'lucide-react';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { MobileTabSelect } from '@/components/MobileTabSelect';
import PaymentsPage from './PaymentsPage';
import LedgerPage from './LedgerPage';
import AuditPage from './AuditPage';

type Tab = 'payments' | 'statement' | 'activity';

const TABS: { value: Tab; label: string; icon: React.ElementType }[] = [
  { value: 'payments',  label: 'Payments',          icon: CreditCard },
  { value: 'statement', label: 'Account Statement', icon: BookOpen },
  { value: 'activity',  label: 'Activity Log',      icon: Shield },
];

export default function AccountsHubPage() {
  const nav = useNavigate();
  const loc = useLocation();
  const initial = (new URLSearchParams(loc.search).get('tab') as Tab) || 'payments';
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
        <TabsContent value="payments"  className="mt-4"><PaymentsPage /></TabsContent>
        <TabsContent value="statement" className="mt-4"><LedgerPage /></TabsContent>
        <TabsContent value="activity"  className="mt-4"><AuditPage /></TabsContent>
      </Tabs>
    </div>
  );
}
