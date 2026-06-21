/**
 * Cameras & ANPR hub — Camera & Scale · Snapshot Search · Gate Cameras (events) · Plate Review
 *
 * Split from WeighbridgeHubPage to keep each hub under 4 tabs on mobile.
 * URL sync: ?tab=cameras | ?tab=snapshots | ?tab=anpr | ?tab=review. Default = cameras.
 */
import { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { MonitorPlay, ScanSearch, Camera, AlertTriangle } from 'lucide-react';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { MobileTabSelect } from '@/components/MobileTabSelect';
import CameraScalePage from './CameraScalePage';
import SnapshotSearchPage from './SnapshotSearchPage';
import AnprEventsPage from './AnprEventsPage';
import AnprReviewPage from './AnprReviewPage';

type Tab = 'cameras' | 'snapshots' | 'anpr' | 'review';

const TABS: { value: Tab; label: string; icon: React.ElementType }[] = [
  { value: 'cameras',   label: 'Camera & Scale',  icon: MonitorPlay },
  { value: 'snapshots', label: 'Snapshots',        icon: ScanSearch },
  { value: 'anpr',      label: 'Gate Cameras',     icon: Camera },
  { value: 'review',    label: 'Plate Review',     icon: AlertTriangle },
];

export default function CamerasAnprHubPage() {
  const nav = useNavigate();
  const loc = useLocation();
  const initial = (new URLSearchParams(loc.search).get('tab') as Tab) || 'cameras';
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
        <TabsContent value="cameras"   className="mt-4"><CameraScalePage /></TabsContent>
        <TabsContent value="snapshots" className="mt-4"><SnapshotSearchPage /></TabsContent>
        <TabsContent value="anpr"      className="mt-4"><AnprEventsPage /></TabsContent>
        <TabsContent value="review"    className="mt-4"><AnprReviewPage /></TabsContent>
      </Tabs>
    </div>
  );
}
