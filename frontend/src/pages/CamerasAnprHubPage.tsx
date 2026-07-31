/**
 * Cameras & ANPR hub — Camera & Scale · Snapshot Search · Gate Cameras (events) · Plate Review
 *
 * Split from WeighbridgeHubPage to keep each hub under 4 tabs on mobile.
 * URL sync: ?tab=cameras | ?tab=snapshots | ?tab=anpr | ?tab=review. Default = cameras.
 */
import { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { MonitorPlay, ScanSearch, Camera, AlertTriangle, Video } from 'lucide-react';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { MobileTabSelect } from '@/components/MobileTabSelect';
import { usePermissions } from '@/contexts/PermissionsContext';
import { useIsMobile } from '@/hooks/useIsMobile';
import CameraScalePage from './CameraScalePage';
import SnapshotSearchPage from './SnapshotSearchPage';
import AnprEventsPage from './AnprEventsPage';
import AnprReviewPage from './AnprReviewPage';
import GateCameraLivePage from './GateCameraLivePage';

type Tab = 'cameras' | 'snapshots' | 'gate-live' | 'anpr' | 'review';

export default function CamerasAnprHubPage() {
  const { t } = useTranslation();
  const nav = useNavigate();
  const loc = useLocation();
  const { isTabAllowed } = usePermissions();
  const isMobile = useIsMobile();

  const TABS: { value: Tab; label: string; icon: React.ElementType }[] = [
    { value: 'cameras',    label: t('hubs.camerasAnpr.cameraScale'),    icon: MonitorPlay },
    { value: 'snapshots',  label: t('hubs.camerasAnpr.snapshotSearch'), icon: ScanSearch },
    { value: 'gate-live',  label: t('hubs.camerasAnpr.anprLive'),       icon: Video },
    { value: 'anpr',       label: t('hubs.camerasAnpr.anprEvents'),     icon: Camera },
    { value: 'review',     label: t('hubs.camerasAnpr.plateReview'),    icon: AlertTriangle },
  ];
  // Hidden on mobile/PWA: Camera & Scale monitor (streams over ws://localhost, plant-PC
  // only) + ANPR Events. The internet-relayed Gate live feed stays.
  const HIDE_ON_MOBILE = new Set<Tab>(['cameras', 'anpr']);
  const visibleTabs = TABS.filter(t => isTabAllowed('/cameras-anpr', t.value)
    && !(isMobile && HIDE_ON_MOBILE.has(t.value)));
  const initialRaw = (new URLSearchParams(loc.search).get('tab') as Tab) || 'cameras';
  const initial = (visibleTabs.find(t => t.value === initialRaw)?.value ?? visibleTabs[0]?.value ?? 'cameras') as Tab;
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
        <TabsContent value="cameras"   className="mt-4"><CameraScalePage /></TabsContent>
        <TabsContent value="snapshots" className="mt-4"><SnapshotSearchPage /></TabsContent>
        <TabsContent value="gate-live" className="mt-4"><GateCameraLivePage /></TabsContent>
        <TabsContent value="anpr"      className="mt-4"><AnprEventsPage /></TabsContent>
        <TabsContent value="review"    className="mt-4"><AnprReviewPage /></TabsContent>
      </Tabs>
    </div>
  );
}
