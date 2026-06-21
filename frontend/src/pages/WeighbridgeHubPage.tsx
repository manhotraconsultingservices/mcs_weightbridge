/**
 * Weighbridge hub — Gate Register, Weigh Tickets, Movement Report,
 * Camera & Scale, Snapshots, Gate Cameras, Plate Review in tabs.
 *
 * URL sync: ?tab=gate | ?tab=tickets | ?tab=movement | ?tab=cameras |
 *           ?tab=snapshots | ?tab=anpr | ?tab=review. Default = gate.
 */
import { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { DoorOpen, Scale, BarChart3, Camera, ScanSearch, MonitorPlay, AlertTriangle } from 'lucide-react';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { MobileTabSelect } from '@/components/MobileTabSelect';

const MOBILE_TABS = [
  { value: 'gate',      label: 'Gate Register' },
  { value: 'tickets',   label: 'Weigh Tickets' },
  { value: 'movement',  label: 'Movement Report' },
  { value: 'cameras',   label: 'Camera & Scale' },
  { value: 'snapshots', label: 'Snapshots' },
  { value: 'anpr',      label: 'Gate Cameras' },
  { value: 'review',    label: 'Plate Review' },
];
import GatePassPage from './GatePassPage';
import TokenPageV1 from './TokenPageV1';
import AnprTripsPage from './AnprTripsPage';
import CameraScalePage from './CameraScalePage';
import SnapshotSearchPage from './SnapshotSearchPage';
import AnprEventsPage from './AnprEventsPage';
import AnprReviewPage from './AnprReviewPage';

type Tab = 'gate' | 'tickets' | 'movement' | 'cameras' | 'snapshots' | 'anpr' | 'review';

export default function WeighbridgeHubPage() {
  const nav = useNavigate();
  const loc = useLocation();
  const initial = (new URLSearchParams(loc.search).get('tab') as Tab) || 'gate';
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
          <TabsTrigger value="gate" className="gap-1.5"><DoorOpen className="h-3.5 w-3.5" /> Gate Register</TabsTrigger>
          <TabsTrigger value="tickets" className="gap-1.5"><Scale className="h-3.5 w-3.5" /> Weigh Tickets</TabsTrigger>
          <TabsTrigger value="movement" className="gap-1.5"><BarChart3 className="h-3.5 w-3.5" /> Movement Report</TabsTrigger>
          <TabsTrigger value="cameras" className="gap-1.5"><Camera className="h-3.5 w-3.5" /> Camera & Scale</TabsTrigger>
          <TabsTrigger value="snapshots" className="gap-1.5"><ScanSearch className="h-3.5 w-3.5" /> Snapshots</TabsTrigger>
          <TabsTrigger value="anpr" className="gap-1.5"><MonitorPlay className="h-3.5 w-3.5" /> Gate Cameras</TabsTrigger>
          <TabsTrigger value="review" className="gap-1.5"><AlertTriangle className="h-3.5 w-3.5" /> Plate Review</TabsTrigger>
        </TabsList>
        <TabsContent value="gate" className="mt-4">
          <GatePassPage />
        </TabsContent>
        <TabsContent value="tickets" className="mt-4">
          <TokenPageV1 />
        </TabsContent>
        <TabsContent value="movement" className="mt-4">
          <AnprTripsPage />
        </TabsContent>
        <TabsContent value="cameras" className="mt-4">
          <CameraScalePage />
        </TabsContent>
        <TabsContent value="snapshots" className="mt-4">
          <SnapshotSearchPage />
        </TabsContent>
        <TabsContent value="anpr" className="mt-4">
          <AnprEventsPage />
        </TabsContent>
        <TabsContent value="review" className="mt-4">
          <AnprReviewPage />
        </TabsContent>
      </Tabs>
    </div>
  );
}
