/**
 * CRM hub — Customers + Suppliers, each a filtered party picker.
 *
 * URL sync: ?tab=customers | ?tab=suppliers. Default = customers.
 * Each card → /customers/:id (the full Customer/Supplier 360 profile).
 * Standalone /customers (all types) still works for deep-links.
 */
import { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Users, Truck } from 'lucide-react';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { MobileTabSelect } from '@/components/MobileTabSelect';
import { usePermissions } from '@/contexts/PermissionsContext';
import CustomerPickerPage from './CustomerPickerPage';

type Tab = 'customers' | 'suppliers';

export default function CrmHubPage() {
  const { t } = useTranslation();
  const nav = useNavigate();
  const loc = useLocation();
  const { isTabAllowed } = usePermissions();

  const TABS: { value: Tab; label: string; icon: React.ElementType }[] = [
    { value: 'customers', label: t('hubs.crm.customers'), icon: Users },
    { value: 'suppliers', label: t('hubs.crm.suppliers'), icon: Truck },
  ];
  const visibleTabs = TABS.filter(tb => isTabAllowed('/crm', tb.value));
  const initialRaw = (new URLSearchParams(loc.search).get('tab') as Tab) || 'customers';
  const initial = (visibleTabs.find(tb => tb.value === initialRaw)?.value ?? visibleTabs[0]?.value ?? 'customers') as Tab;
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
        <MobileTabSelect value={tab} onValueChange={(v) => setTab(v as Tab)} options={visibleTabs.map(tb => ({ value: tb.value, label: tb.label }))} />
        <TabsList className="hidden sm:inline-flex flex-wrap h-auto">
          {visibleTabs.map(tb => {
            const Icon = tb.icon;
            return (
              <TabsTrigger key={tb.value} value={tb.value} className="gap-1.5">
                <Icon className="h-3.5 w-3.5" /> {tb.label}
              </TabsTrigger>
            );
          })}
        </TabsList>
        <TabsContent value="customers" className="mt-4">
          <CustomerPickerPage lockType="customer" />
        </TabsContent>
        <TabsContent value="suppliers" className="mt-4">
          <CustomerPickerPage lockType="supplier" />
        </TabsContent>
      </Tabs>
    </div>
  );
}
