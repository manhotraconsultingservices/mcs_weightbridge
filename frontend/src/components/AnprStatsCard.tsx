/**
 * Owner-dashboard widget — today's gate camera activity.
 *
 * Reads /api/v1/anpr/stats for today and renders four numbers:
 *   IN today · OUT today · Currently inside · Unmatched
 *
 * Auto-refreshes every 60 s. Renders nothing when ANPR is disabled
 * (the stats endpoint returns 0 for everything, but we hide the card
 * to keep the dashboard tidy).
 */
import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Camera, ArrowDownToLine, ArrowUpFromLine, AlertTriangle, Users, ChevronRight } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import api from '@/services/api';
import type { AnprStats, AnprConfig } from '@/types';

function today() {
  return new Date().toISOString().split('T')[0];
}

export default function AnprStatsCard() {
  const [stats, setStats] = useState<AnprStats | null>(null);
  const [enabled, setEnabled] = useState<boolean | null>(null); // null = unknown

  const load = useCallback(async () => {
    try {
      const t = today();
      // First check if ANPR is enabled at all — if not, hide the card.
      if (enabled === null || enabled === false) {
        try {
          const cfg = await api.get<AnprConfig>('/api/v1/anpr/config');
          setEnabled(cfg.data.enabled);
          if (!cfg.data.enabled) return;
        } catch {
          // Non-admins can't fetch /config (admin-only). Just try /stats instead.
          setEnabled(true);  // optimistic
        }
      }
      const res = await api.get<AnprStats>(`/api/v1/anpr/stats?date_from=${t}&date_to=${t}`);
      setStats(res.data);
    } catch {
      /* hide on error */
    }
  }, [enabled]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    const id = setInterval(load, 60_000);
    return () => clearInterval(id);
  }, [load]);

  if (enabled === false) return null;
  if (!stats) return null;

  // If there's no traffic AND no setup, don't clutter the dashboard.
  if (stats.entries === 0 && stats.exits === 0 && stats.currently_inside === 0 && stats.unmatched === 0) {
    return null;
  }

  return (
    <Card>
      <CardContent className="pt-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-bold uppercase tracking-widest text-slate-700 flex items-center gap-2">
            <Camera className="h-4 w-4 text-blue-600" /> Gate Cameras Today
          </h3>
          <Link to="/anpr/live" className="text-xs text-blue-600 hover:underline flex items-center gap-0.5">
            Live view <ChevronRight className="h-3 w-3" />
          </Link>
        </div>
        <div className="grid grid-cols-4 gap-2">
          <MiniKpi icon={ArrowDownToLine} label="In" value={stats.entries} color="text-emerald-700" bg="bg-emerald-50" />
          <MiniKpi icon={ArrowUpFromLine} label="Out" value={stats.exits} color="text-blue-700" bg="bg-blue-50" />
          <MiniKpi icon={Users} label="Inside" value={stats.currently_inside} color="text-amber-700" bg="bg-amber-50" />
          <MiniKpi icon={AlertTriangle} label="Review" value={stats.unmatched} color="text-rose-700" bg="bg-rose-50" />
        </div>
        {stats.unmatched > 0 && (
          <div className="mt-3 text-[11px] text-rose-700">
            <Link to="/anpr/review" className="hover:underline">
              ⚠ {stats.unmatched} plate{stats.unmatched > 1 ? 's' : ''} need{stats.unmatched === 1 ? 's' : ''} review →
            </Link>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function MiniKpi({
  icon: Icon, label, value, color, bg,
}: { icon: React.ElementType; label: string; value: number; color: string; bg: string }) {
  return (
    <div className={`rounded-lg ${bg} p-2 text-center`}>
      <Icon className={`h-4 w-4 mx-auto mb-1 ${color}`} />
      <div className={`text-2xl font-bold tabular-nums ${color}`}>{value}</div>
      <div className="text-[10px] uppercase tracking-widest text-muted-foreground">{label}</div>
    </div>
  );
}
