/**
 * Materials hub — Catalog · Rates · Stock · Production
 *
 * Consolidates 6 old sidebar items into one tabbed hub:
 *   Products + Pricing Matrix + Product Stock + Production×3.
 */
import { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Package, IndianRupee, Boxes, Factory, Activity, Settings } from 'lucide-react';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import ProductsPage from './ProductsPage';
import PricingMatrixPage from './PricingMatrixPage';
import ProductInventoryPage from './ProductInventoryPage';
import ProductionPage from './ProductionPage';
import ProductionDashboardPage from './ProductionDashboardPage';
import ProductionSettingsPage from './ProductionSettingsPage';

type Tab = 'catalog' | 'rates' | 'stock' | 'production' | 'production-dashboard' | 'production-settings';

const TABS: { value: Tab; label: string; icon: React.ElementType }[] = [
  { value: 'catalog', label: 'Catalog', icon: Package },
  { value: 'rates', label: 'Customer Rates', icon: IndianRupee },
  { value: 'stock', label: 'Stock on Hand', icon: Boxes },
  { value: 'production', label: 'Production', icon: Factory },
  { value: 'production-dashboard', label: 'Production Dashboard', icon: Activity },
  { value: 'production-settings', label: 'Production Settings', icon: Settings },
];

export default function MaterialsHubPage() {
  const nav = useNavigate();
  const loc = useLocation();
  const initial = (new URLSearchParams(loc.search).get('tab') as Tab) || 'catalog';
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
        <TabsContent value="catalog" className="mt-4"><ProductsPage /></TabsContent>
        <TabsContent value="rates" className="mt-4"><PricingMatrixPage /></TabsContent>
        <TabsContent value="stock" className="mt-4"><ProductInventoryPage /></TabsContent>
        <TabsContent value="production" className="mt-4"><ProductionPage /></TabsContent>
        <TabsContent value="production-dashboard" className="mt-4"><ProductionDashboardPage /></TabsContent>
        <TabsContent value="production-settings" className="mt-4"><ProductionSettingsPage /></TabsContent>
      </Tabs>
    </div>
  );
}
