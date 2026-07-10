/**
 * Accounts hub — Payments · Account Statement · Activity Log
 *
 * GST Returns / GSTR-2B / Compliance moved to GstComplianceHubPage (/gst-compliance).
 * URL sync: ?tab=payments | ?tab=statement | ?tab=activity. Default = payments.
 */
import { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { CreditCard, BookOpen, Shield, Wallet, HandCoins } from 'lucide-react';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { MobileTabSelect } from '@/components/MobileTabSelect';
import { usePermissions } from '@/contexts/PermissionsContext';
import PaymentsPage from './PaymentsPage';
import LedgerPage from './LedgerPage';
import AuditPage from './AuditPage';
import PartyBalancesPage from './PartyBalancesPage';
import AdvancesPage from './AdvancesPage';

type Tab = 'payments' | 'statement' | 'balances' | 'advances' | 'activity';

export default function AccountsHubPage() {
  const { t } = useTranslation();
  const nav = useNavigate();
  const loc = useLocation();
  const { isTabAllowed } = usePermissions();

  const TABS: { value: Tab; label: string; icon: React.ElementType }[] = [
    { value: 'payments',  label: t('hubs.accounts.payments'),  icon: CreditCard },
    { value: 'statement', label: t('hubs.accounts.ledger'),    icon: BookOpen },
    { value: 'balances',  label: 'Balances',                   icon: Wallet },
    { value: 'advances',  label: 'Advances',                   icon: HandCoins },
    { value: 'activity',  label: t('hubs.accounts.activity'),  icon: Shield },
  ];
  const visibleTabs = TABS.filter(t => isTabAllowed('/accounts', t.value));
  const initialRaw = (new URLSearchParams(loc.search).get('tab') as Tab) || 'payments';
  const initial = (visibleTabs.find(t => t.value === initialRaw)?.value ?? visibleTabs[0]?.value ?? 'payments') as Tab;
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
        <TabsContent value="payments"  className="mt-4"><PaymentsPage /></TabsContent>
        <TabsContent value="statement" className="mt-4"><LedgerPage /></TabsContent>
        <TabsContent value="balances"  className="mt-4"><PartyBalancesPage /></TabsContent>
        <TabsContent value="advances"  className="mt-4"><AdvancesPage /></TabsContent>
        <TabsContent value="activity"  className="mt-4"><AuditPage /></TabsContent>
      </Tabs>
    </div>
  );
}
