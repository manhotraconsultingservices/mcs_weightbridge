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
import InvoicesPage from './InvoicesPage';
import RoyaltyPassesPage from './RoyaltyPassesPage';

type Tab = 'purchases' | 'royalty';

export default function ProcurementHubPage() {
  const nav = useNavigate();
  const loc = useLocation();
  const initial = (new URLSearchParams(loc.search).get('tab') as Tab) || 'purchases';
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
          <TabsTrigger value="purchases" className="gap-1.5"><ShoppingCart className="h-3.5 w-3.5" /> Purchase Invoices</TabsTrigger>
          <TabsTrigger value="royalty" className="gap-1.5"><Mountain className="h-3.5 w-3.5" /> Royalty & Transit Passes</TabsTrigger>
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
