/**
 * Inventory & Production hub — Finished Goods · Store Inventory · Products Catalog · Customer Rates
 *
 * Production / Dashboard / Settings moved to ProductionHubPage (/production-hub).
 * URL sync: ?tab=stock | ?tab=store | ?tab=catalog | ?tab=rates. Default = stock.
 */
import { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Boxes, Warehouse, Package } from 'lucide-react';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { MobileTabSelect } from '@/components/MobileTabSelect';
import { usePermissions } from '@/contexts/PermissionsContext';
import ProductInventoryPage from './ProductInventoryPage';
import InventoryPage from './InventoryPage';
import ProductsPage from './ProductsPage';

type Tab = 'stock' | 'store' | 'catalog';

export default function InventoryProductionHubPage() {
  const { t } = useTranslation();
  const nav = useNavigate();
  const loc = useLocation();
  const { isTabAllowed } = usePermissions();

  const TABS: { value: Tab; label: string; icon: React.ElementType }[] = [
    { value: 'stock',   label: t('hubs.materials.stockOnHand'),          icon: Boxes },
    { value: 'store',   label: t('hubs.inventoryProduction.storeInventory'), icon: Warehouse },
    { value: 'catalog', label: t('hubs.materials.catalog'),               icon: Package },
  ];
  const visibleTabs = TABS.filter(t => isTabAllowed('/inventory-hub', t.value));
  const initialRaw = (new URLSearchParams(loc.search).get('tab') as Tab) || 'stock';
  const initial = (visibleTabs.find(tab => tab.value === initialRaw)?.value ?? visibleTabs[0]?.value ?? 'stock') as Tab;
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
        <TabsContent value="stock"   className="mt-4"><ProductInventoryPage /></TabsContent>
        <TabsContent value="store"   className="mt-4"><InventoryPage /></TabsContent>
        <TabsContent value="catalog" className="mt-4"><ProductsPage /></TabsContent>
      </Tabs>
    </div>
  );
}
