/**
 * Operations hub — Vehicles · Store Inventory · Camera & Scale · Snapshot Search.
 *
 * Daily operational kit that's not directly customer/finance-facing.
 */
import { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Truck, Warehouse, MonitorPlay, ScanSearch } from 'lucide-react';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import VehiclesPage from './VehiclesPage';
import InventoryPage from './InventoryPage';
import CameraScalePage from './CameraScalePage';
import SnapshotSearchPage from './SnapshotSearchPage';

type Tab = 'vehicles' | 'store' | 'camera-scale' | 'snapshots';

const TABS: { value: Tab; label: string; icon: React.ElementType }[] = [
  { value: 'vehicles', label: 'Vehicles', icon: Truck },
  { value: 'store', label: 'Store Inventory', icon: Warehouse },
  { value: 'camera-scale', label: 'Camera & Scale', icon: MonitorPlay },
  { value: 'snapshots', label: 'Snapshot Search', icon: ScanSearch },
];

export default function OperationsHubPage() {
  const nav = useNavigate();
  const loc = useLocation();
  const initial = (new URLSearchParams(loc.search).get('tab') as Tab) || 'vehicles';
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
        <TabsContent value="vehicles" className="mt-4"><VehiclesPage /></TabsContent>
        <TabsContent value="store" className="mt-4"><InventoryPage /></TabsContent>
        <TabsContent value="camera-scale" className="mt-4"><CameraScalePage /></TabsContent>
        <TabsContent value="snapshots" className="mt-4"><SnapshotSearchPage /></TabsContent>
      </Tabs>
    </div>
  );
}
