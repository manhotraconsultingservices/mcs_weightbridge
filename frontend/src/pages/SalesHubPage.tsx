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

const MOBILE_TABS = [
  { value: 'customers', label: 'Customers' },
  { value: 'bills',     label: 'Bills' },
  { value: 'estimates', label: 'Estimates' },
  { value: 'challans',  label: 'Challans' },
  { value: 'notes',     label: 'Notes' },
];
import CustomerPickerPage from './CustomerPickerPage';
import InvoicesPage from './InvoicesPage';
import QuotationsPage from './QuotationsPage';
import DeliveryChallansPage from './DeliveryChallansPage';
import CreditDebitNotesPage from './CreditDebitNotesPage';

type Tab = 'customers' | 'bills' | 'estimates' | 'challans' | 'notes';

export default function SalesHubPage() {
  const nav = useNavigate();
  const loc = useLocation();
  const initial = (new URLSearchParams(loc.search).get('tab') as Tab) || 'customers';
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
        <MobileTabSelect value={tab} onValueChange={(v) => setTab(v as Tab)} options={MOBILE_TABS} />
        <TabsList className="hidden sm:inline-flex flex-wrap h-auto">
          <TabsTrigger value="customers" className="gap-1.5"><Users className="h-3.5 w-3.5" /> Customers</TabsTrigger>
          <TabsTrigger value="bills" className="gap-1.5"><FileText className="h-3.5 w-3.5" /> Bills</TabsTrigger>
          <TabsTrigger value="estimates" className="gap-1.5"><Receipt className="h-3.5 w-3.5" /> Estimates</TabsTrigger>
          <TabsTrigger value="challans" className="gap-1.5"><Truck className="h-3.5 w-3.5" /> Challans</TabsTrigger>
          <TabsTrigger value="notes" className="gap-1.5"><FileMinus className="h-3.5 w-3.5" /> Notes</TabsTrigger>
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
