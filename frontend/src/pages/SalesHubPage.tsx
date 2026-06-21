/**
 * Sales hub — Bills (invoices) + Estimates (quotations) in tabs.
 *
 * URL sync: ?tab=bills | ?tab=estimates. Default = bills.
 * Existing routes (/invoices, /quotations) still work standalone for
 * deep-links from emails or bookmarks.
 */
import { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Users, FileText, Receipt, Truck, FileMinus } from 'lucide-react';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { MobileTabSelect } from '@/components/MobileTabSelect';
import { usePermissions } from '@/contexts/PermissionsContext';
import CustomerPickerPage from './CustomerPickerPage';
import InvoicesPage from './InvoicesPage';
import QuotationsPage from './QuotationsPage';
import DeliveryChallansPage from './DeliveryChallansPage';
import CreditDebitNotesPage from './CreditDebitNotesPage';

type Tab = 'customers' | 'bills' | 'estimates' | 'challans' | 'notes';

const TABS: { value: Tab; label: string; icon: React.ElementType }[] = [
  { value: 'customers', label: 'Customers', icon: Users },
  { value: 'bills',     label: 'Bills',     icon: FileText },
  { value: 'estimates', label: 'Estimates', icon: Receipt },
  { value: 'challans',  label: 'Challans',  icon: Truck },
  { value: 'notes',     label: 'Notes',     icon: FileMinus },
];

export default function SalesHubPage() {
  const nav = useNavigate();
  const loc = useLocation();
  const { isTabAllowed } = usePermissions();
  const visibleTabs = TABS.filter(t => isTabAllowed('/sales', t.value));
  const initialRaw = (new URLSearchParams(loc.search).get('tab') as Tab) || 'customers';
  const initial = (visibleTabs.find(t => t.value === initialRaw)?.value ?? visibleTabs[0]?.value ?? 'customers') as Tab;
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
        <TabsContent value="customers" className="mt-4">
          <CustomerPickerPage />
        </TabsContent>
        <TabsContent value="bills" className="mt-4">
          <InvoicesPage defaultType="sale" />
        </TabsContent>
        <TabsContent value="estimates" className="mt-4">
          <QuotationsPage />
        </TabsContent>
        <TabsContent value="challans" className="mt-4">
          <DeliveryChallansPage />
        </TabsContent>
        <TabsContent value="notes" className="mt-4">
          <CreditDebitNotesPage />
        </TabsContent>
      </Tabs>
    </div>
  );
}
