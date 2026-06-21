/**
 * Operations hub — Vehicles · Store Inventory · Camera & Scale · Snapshot Search
 * · Gate Cameras (ANPR events) · Plate Review (ANPR unmatched queue).
 *
 * Daily operational kit that's not directly customer/finance-facing.
 */
import { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Truck, Warehouse, MonitorPlay, ScanSearch, Camera, AlertTriangle, FileText } from 'lucide-react';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { MobileTabSelect } from '@/components/MobileTabSelect';
import VehiclesPage from './VehiclesPage';
import InventoryPage from './InventoryPage';
import CameraScalePage from './CameraScalePage';
import SnapshotSearchPage from './SnapshotSearchPage';
import AnprEventsPage from './AnprEventsPage';
import AnprReviewPage from './AnprReviewPage';
import AnprTripsPage from './AnprTripsPage';

type Tab = 'vehicles' | 'store' | 'camera-scale' | 'snapshots' | 'anpr-trips' | 'anpr-events' | 'anpr-review';

const TABS: { value: Tab; label: string; icon: React.ElementType }[] = [
  { value: 'vehicles', label: 'Vehicles', icon: Truck },
  { value: 'store', label: 'Store Inventory', icon: Warehouse },
  { value: 'camera-scale', label: 'Camera & Scale', icon: MonitorPlay },
  { value: 'snapshots', label: 'Snapshot Search', icon: ScanSearch },
  { value: 'anpr-trips', label: 'Movement Report', icon: FileText },
  { value: 'anpr-events', label: 'Gate Cameras', icon: Camera },
  { value: 'anpr-review', label: 'Plate Review', icon: AlertTriangle },
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
        <TabsContent value="vehicles" className="mt-4"><VehiclesPage /></TabsContent>
        <TabsContent value="store" className="mt-4"><InventoryPage /></TabsContent>
        <TabsContent value="camera-scale" className="mt-4"><CameraScalePage /></TabsContent>
        <TabsContent value="snapshots" className="mt-4"><SnapshotSearchPage /></TabsContent>
        <TabsContent value="anpr-trips" className="mt-4"><AnprTripsPage /></TabsContent>
        <TabsContent value="anpr-events" className="mt-4"><AnprEventsPage /></TabsContent>
        <TabsContent value="anpr-review" className="mt-4"><AnprReviewPage /></TabsContent>
      </Tabs>
    </div>
  );
}
