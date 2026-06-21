/**
 * Procurement hub — Purchase Invoices + Royalty & Transit Passes in tabs.
 *
 * URL sync: ?tab=purchases | ?tab=royalty. Default = purchases.
 * Existing routes (/purchase-invoices, /royalty) still work standalone for
 * deep-links from emails or bookmarks.
 */
import { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { ShoppingCart, Mountain } from 'lucide-react';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { MobileTabSelect } from '@/components/MobileTabSelect';
import { usePermissions } from '@/contexts/PermissionsContext';
import InvoicesPage from './InvoicesPage';
import RoyaltyPassesPage from './RoyaltyPassesPage';

type Tab = 'purchases' | 'royalty';

const TABS: { value: Tab; label: string; icon: React.ElementType }[] = [
  { value: 'purchases', label: 'Purchase Invoices',      icon: ShoppingCart },
  { value: 'royalty',   label: 'Royalty & Transit Passes', icon: Mountain },
];

export default function ProcurementHubPage() {
  const nav = useNavigate();
  const loc = useLocation();
  const { isTabAllowed } = usePermissions();
  const visibleTabs = TABS.filter(t => isTabAllowed('/procurement', t.value));
  const initialRaw = (new URLSearchParams(loc.search).get('tab') as Tab) || 'purchases';
  const initial = (visibleTabs.find(t => t.value === initialRaw)?.value ?? visibleTabs[0]?.value ?? 'purchases') as Tab;
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
        <TabsContent value="purchases" className="mt-4">
          <InvoicesPage defaultType="purchase" />
        </TabsContent>
        <TabsContent value="royalty" className="mt-4">
          <RoyaltyPassesPage />
        </TabsContent>
      </Tabs>
    </div>
  );
}
