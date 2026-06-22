/**
 * ANPR Live Wallboard — full-bleed screen for the gate office.
 *
 * Auto-polls /anpr/events?page_size=20 every 5 seconds. Shows the latest
 * 20 detections with snapshot thumbnails on the left and 4 big KPIs on
 * the right (entries today / exits today / currently inside / unmatched).
 *
 * Designed to be displayed on a wall-mounted TV so the owner / manager
 * can see truck movement at a glance from anywhere on site.
 */
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Camera, ArrowDownToLine, ArrowUpFromLine, AlertTriangle, Users, RefreshCw } from 'lucide-react';
import api from '@/services/api';
import type { AnprEvent, AnprEventListResponse, AnprStats } from '@/types';

function today() {
  return new Date().toISOString().split('T')[0];
}

export default function AnprLivePage() {
  const { t } = useTranslation();
  const [events, setEvents] = useState<AnprEvent[]>([]);
  const [stats, setStats] = useState<AnprStats | null>(null);
  const [lastFetch, setLastFetch] = useState<Date>(new Date());

  const refresh = useCallback(async () => {
    try {
      const t = today();
      const [evRes, statsRes] = await Promise.all([
        api.get<AnprEventListResponse>('/api/v1/anpr/events?page=1&page_size=20'),
        api.get<AnprStats>(`/api/v1/anpr/stats?date_from=${t}&date_to=${t}`),
      ]);
      setEvents(evRes.data.items ?? []);
      setStats(statsRes.data);
      setLastFetch(new Date());
    } catch {
      /* keep last state on transient errors */
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => {
    const id = setInterval(refresh, 5_000);
    return () => clearInterval(id);
  }, [refresh]);

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 p-6">
      <header className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <Camera className="h-8 w-8 text-emerald-400" />
          <div>
            <h1 className="text-3xl font-black tracking-tight">{t('anpr.liveTitle')}</h1>
            <p className="text-xs text-slate-400 uppercase tracking-widest">
              Auto-refresh every 5 s · last update {lastFetch.toLocaleTimeString('en-IN', { hour12: false })}
            </p>
          </div>
        </div>
        <button onClick={refresh}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-sm text-slate-200">
          <RefreshCw className="h-4 w-4" /> {t('common.refresh')}
        </button>
      </header>

      {/* KPI tiles */}
      <section className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <BigKpi icon={ArrowDownToLine} label={t('anpr.entriesToday').toUpperCase()} value={stats?.entries ?? 0}
                color="text-emerald-400" bg="bg-emerald-500/10 border-emerald-700/40" />
        <BigKpi icon={ArrowUpFromLine} label={t('anpr.exitsToday').toUpperCase()} value={stats?.exits ?? 0}
                color="text-blue-400" bg="bg-blue-500/10 border-blue-700/40" />
        <BigKpi icon={Users} label={t('anpr.currentlyInside').toUpperCase()} value={stats?.currently_inside ?? 0}
                color="text-amber-400" bg="bg-amber-500/10 border-amber-700/40" />
        <BigKpi icon={AlertTriangle} label={t('anpr.unmatched').toUpperCase()} value={stats?.unmatched ?? 0}
                color="text-rose-400" bg="bg-rose-500/10 border-rose-700/40" />
      </section>

      {/* Last-20 strip */}
      <section className="rounded-2xl border-2 border-slate-700/50 bg-slate-800/50 p-4">
        <h2 className="text-base font-bold uppercase tracking-widest text-slate-300 mb-3">
          {t('anpr.last20Detections')}
        </h2>
        {events.length === 0 ? (
          <div className="text-center text-slate-500 py-12">
            {t('anpr.noDetectionsToday')}
          </div>
        ) : (
          <div className="grid grid-cols-2 lg:grid-cols-4 xl:grid-cols-5 gap-3">
            {events.map(ev => <DetectionTile key={ev.id} ev={ev} />)}
          </div>
        )}
      </section>
    </div>
  );
}

function BigKpi({
  icon: Icon, label, value, color, bg,
}: {
  icon: React.ElementType; label: string; value: number | string;
  color: string; bg: string;
}) {
  return (
    <div className={`rounded-2xl border-2 ${bg} px-6 py-5 flex items-center gap-4`}>
      <Icon className={`h-12 w-12 ${color}`} />
      <div>
        <p className="text-[10px] uppercase tracking-widest text-slate-400 font-semibold">{label}</p>
        <p className={`text-5xl font-black ${color} tabular-nums`}>{value}</p>
      </div>
    </div>
  );
}

function DetectionTile({ ev }: { ev: AnprEvent }) {
  const ts = new Date(ev.detected_at);
  const isEntry = ev.direction === 'entry';
  const isExit = ev.direction === 'exit';
  const borderColor =
    isEntry ? 'border-emerald-600/50 bg-emerald-950/30'
    : isExit ? 'border-blue-600/50 bg-blue-950/30'
    : ev.direction === 'unmatched' ? 'border-amber-600/50 bg-amber-950/30'
    : 'border-slate-700/50 bg-slate-900/50';
  return (
    <div className={`rounded-xl border-2 ${borderColor} overflow-hidden`}>
      <div className="aspect-video bg-black flex items-center justify-center">
        {ev.snapshot_path ? (
          <img src={`/${ev.snapshot_path}`} alt={ev.plate_normalized}
               className="w-full h-full object-cover" loading="lazy" />
        ) : (
          <Camera className="h-8 w-8 text-slate-700" />
        )}
      </div>
      <div className="px-3 py-2 space-y-1">
        <div className="flex items-center justify-between gap-2">
          <span className="font-mono font-bold text-base text-slate-100 tracking-wide">{ev.plate_normalized}</span>
          {isEntry && <span className="text-[10px] font-bold text-emerald-400">↓ IN</span>}
          {isExit && <span className="text-[10px] font-bold text-blue-400">↑ OUT</span>}
          {ev.direction === 'unmatched' && <span className="text-[10px] font-bold text-amber-400">?</span>}
        </div>
        {ev.token?.gate_pass_no && (
          <div className="text-[10px] text-slate-400 font-mono">{ev.token.gate_pass_no}</div>
        )}
        <div className="text-[10px] text-slate-500">
          {ts.toLocaleTimeString('en-IN', { hour12: false })}
          {ev.token?.party_name && <> · {ev.token.party_name}</>}
        </div>
      </div>
    </div>
  );
}
