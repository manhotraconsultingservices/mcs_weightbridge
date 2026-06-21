/**
 * Inventory & Production hub — Finished Goods, Production, Production Dashboard,
 * Store Inventory, Products Catalog, Customer Rates, Prod. Settings in tabs.
 *
 * URL sync: ?tab=stock | ?tab=production | ?tab=production-dash | ?tab=store |
 *           ?tab=catalog | ?tab=rates | ?tab=prod-settings. Default = stock.
 */
import { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Boxes, Factory, Activity, Warehouse, Package, IndianRupee, Settings } from 'lucide-react';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { MobileTabSelect } from '@/components/MobileTabSelect';

const MOBILE_TABS = [
  { value: 'stock',          label: 'Finished Goods' },
  { value: 'production',     label: 'Production' },
  { value: 'production-dash',label: 'Prod. Dashboard' },
  { value: 'store',          label: 'Store Inventory' },
  { value: 'catalog',        label: 'Products Catalog' },
  { value: 'rates',          label: 'Customer Rates' },
  { value: 'prod-settings',  label: 'Prod. Settings' },
];
import ProductInventoryPage from './ProductInventoryPage';
import ProductionPage from './ProductionPage';
import ProductionDashboardPage from './ProductionDashboardPage';
import InventoryPage from './InventoryPage';
import ProductsPage from './ProductsPage';
import PricingMatrixPage from './PricingMatrixPage';
import ProductionSettingsPage from './ProductionSettingsPage';

type Tab = 'stock' | 'production' | 'production-dash' | 'store' | 'catalog' | 'rates' | 'prod-settings';

export default function InventoryProductionHubPage() {
  const nav = useNavigate();
  const loc = useLocation();
  const initial = (new URLSearchParams(loc.search).get('tab') as Tab) || 'stock';
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
          <TabsTrigger value="stock" className="gap-1.5"><Boxes className="h-3.5 w-3.5" /> Finished Goods</TabsTrigger>
          <TabsTrigger value="production" className="gap-1.5"><Factory className="h-3.5 w-3.5" /> Production</TabsTrigger>
          <TabsTrigger value="production-dash" className="gap-1.5"><Activity className="h-3.5 w-3.5" /> Prod. Dashboard</TabsTrigger>
          <TabsTrigger value="store" className="gap-1.5"><Warehouse className="h-3.5 w-3.5" /> Store Inventory</TabsTrigger>
          <TabsTrigger value="catalog" className="gap-1.5"><Package className="h-3.5 w-3.5" /> Products Catalog</TabsTrigger>
          <TabsTrigger value="rates" className="gap-1.5"><IndianRupee className="h-3.5 w-3.5" /> Customer Rates</TabsTrigger>
          <TabsTrigger value="prod-settings" className="gap-1.5"><Settings className="h-3.5 w-3.5" /> Prod. Settings</TabsTrigger>
        </TabsList>
        <TabsContent value="stock" className="mt-4">
          <ProductInventoryPage />
        </TabsContent>
        <TabsContent value="production" className="mt-4">
          <ProductionPage />
        </TabsContent>
        <TabsContent value="production-dash" className="mt-4">
          <ProductionDashboardPage />
        </TabsContent>
        <TabsContent value="store" className="mt-4">
          <InventoryPage />
        </TabsContent>
        <TabsContent value="catalog" className="mt-4">
          <ProductsPage />
        </TabsContent>
        <TabsContent value="rates" className="mt-4">
          <PricingMatrixPage />
        </TabsContent>
        <TabsContent value="prod-settings" className="mt-4">
          <ProductionSettingsPage />
        </TabsContent>
      </Tabs>
    </div>
  );
}
