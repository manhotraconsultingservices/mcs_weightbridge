/**
 * Materials hub — Catalog · Rates · Stock · Production
 *
 * Consolidates 6 old sidebar items into one tabbed hub:
 *   Products + Pricing Matrix + Product Stock + Production×3.
 */
import { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Package, IndianRupee, Boxes, Factory, Activity, Settings, Mountain } from 'lucide-react';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { MobileTabSelect } from '@/components/MobileTabSelect';
import ProductsPage from './ProductsPage';
import PricingMatrixPage from './PricingMatrixPage';
import ProductInventoryPage from './ProductInventoryPage';
import ProductionPage from './ProductionPage';
import ProductionDashboardPage from './ProductionDashboardPage';
import ProductionSettingsPage from './ProductionSettingsPage';
import RoyaltyPassesPage from './RoyaltyPassesPage';

type Tab = 'catalog' | 'rates' | 'stock' | 'royalty' | 'production' | 'production-dashboard' | 'production-settings';

export default function MaterialsHubPage() {
  const { t } = useTranslation();
  const nav = useNavigate();
  const loc = useLocation();
  const initial = (new URLSearchParams(loc.search).get('tab') as Tab) || 'catalog';

  const TABS: { value: Tab; label: string; icon: React.ElementType }[] = [
    { value: 'catalog',              label: t('hubs.materials.catalog'),              icon: Package },
    { value: 'rates',                label: t('hubs.materials.customerRates'),        icon: IndianRupee },
    { value: 'stock',                label: t('hubs.materials.stockOnHand'),          icon: Boxes },
    { value: 'royalty',              label: t('hubs.procurement.royaltyPasses'),      icon: Mountain },
    { value: 'production',           label: t('hubs.materials.production'),           icon: Factory },
    { value: 'production-dashboard', label: t('hubs.materials.productionDashboard'), icon: Activity },
    { value: 'production-settings',  label: t('hubs.materials.productionSettings'),  icon: Settings },
  ];
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
        <TabsContent value="catalog" className="mt-4"><ProductsPage /></TabsContent>
        <TabsContent value="rates" className="mt-4"><PricingMatrixPage /></TabsContent>
        <TabsContent value="stock" className="mt-4"><ProductInventoryPage /></TabsContent>
        <TabsContent value="royalty" className="mt-4"><RoyaltyPassesPage /></TabsContent>
        <TabsContent value="production" className="mt-4"><ProductionPage /></TabsContent>
        <TabsContent value="production-dashboard" className="mt-4"><ProductionDashboardPage /></TabsContent>
        <TabsContent value="production-settings" className="mt-4"><ProductionSettingsPage /></TabsContent>
      </Tabs>
    </div>
  );
}
