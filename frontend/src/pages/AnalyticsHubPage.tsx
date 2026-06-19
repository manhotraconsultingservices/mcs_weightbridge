/**
 * Analytics hub — P&L & Sales · Anomaly Detection · Write-offs ·
 * Sales by Status · GST vs Cash in tabs.
 *
 * URL sync: ?tab=pl | ?tab=anomaly | ?tab=write-offs | ?tab=sales-status |
 *           ?tab=gst-split. Default = pl.
 * Existing routes (/reports, etc.) still work standalone for deep-links
 * from emails or bookmarks.
 */
import { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { TrendingUp, ShieldAlert, XCircle, BarChart3, PieChart } from 'lucide-react';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import ReportsPage from './ReportsPage';
import AnomalyReportPage from './AnomalyReportPage';
import WriteOffsReportPage from './WriteOffsReportPage';
import SalesStatusReportPage from './SalesStatusReportPage';
import GstSplitReportPage from './GstSplitReportPage';

type Tab = 'pl' | 'anomaly' | 'write-offs' | 'sales-status' | 'gst-split';

export default function AnalyticsHubPage() {
  const nav = useNavigate();
  const loc = useLocation();
  const initial = (new URLSearchParams(loc.search).get('tab') as Tab) || 'pl';
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
          <TabsTrigger value="pl" className="gap-1.5"><TrendingUp className="h-3.5 w-3.5" /> P&amp;L &amp; Sales</TabsTrigger>
          <TabsTrigger value="anomaly" className="gap-1.5"><ShieldAlert className="h-3.5 w-3.5" /> Anomaly Detection</TabsTrigger>
          <TabsTrigger value="write-offs" className="gap-1.5"><XCircle className="h-3.5 w-3.5" /> Write-offs</TabsTrigger>
          <TabsTrigger value="sales-status" className="gap-1.5"><BarChart3 className="h-3.5 w-3.5" /> Sales by Status</TabsTrigger>
          <TabsTrigger value="gst-split" className="gap-1.5"><PieChart className="h-3.5 w-3.5" /> GST vs Cash</TabsTrigger>
        </TabsList>
        <TabsContent value="pl" className="mt-4">
          <ReportsPage />
        </TabsContent>
        <TabsContent value="anomaly" className="mt-4">
          <AnomalyReportPage />
        </TabsContent>
        <TabsContent value="write-offs" className="mt-4">
          <WriteOffsReportPage />
        </TabsContent>
        <TabsContent value="sales-status" className="mt-4">
          <SalesStatusReportPage />
        </TabsContent>
        <TabsContent value="gst-split" className="mt-4">
          <GstSplitReportPage />
        </TabsContent>
      </Tabs>
    </div>
  );
}
