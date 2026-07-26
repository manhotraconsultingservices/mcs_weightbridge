/**
 * Device Health — live scale + camera uptime monitor.
 *
 * A standalone Watchdog Agent on each plant PC probes the local scale (via the
 * scale agent's /status) and each IP camera (by fetching a snapshot), then POSTs
 * a per-device heartbeat to /api/v1/monitor/heartbeat. This page shows the live
 * roll-up and auto-refreshes every 15 s. When a device stays down past the
 * threshold (Settings → Device Health), the owner gets a Telegram alert.
 *
 * Status per device:
 *   online  — heartbeat fresh + device healthy
 *   offline — heartbeat fresh but the device itself is failing (e.g. camera
 *             unreachable, scale serial port down)
 *   stale   — no heartbeat recently → the watchdog / PC is offline
 */
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Activity, Scale, Camera, Server, RefreshCw, CheckCircle2, XCircle, WifiOff, Trash2 } from 'lucide-react';
import api from '@/services/api';
import { getCurrentUser } from '@/hooks/useAuth';
import type { DeviceHealthResponse, DeviceHealthItem } from '@/types';

function ago(secs: number | null): string {
  if (secs == null) return '—';
  if (secs < 60) return `${Math.round(secs)}s ago`;
  if (secs < 3600) return `${Math.round(secs / 60)}m ago`;
  return `${Math.round(secs / 3600)}h ago`;
}

function deviceIcon(type: string) {
  if (type === 'scale') return Scale;
  if (type === 'agent') return Server;
  return Camera;
}

const STATUS_META: Record<string, { label: string; badge: string; icon: typeof CheckCircle2 }> = {
  online:  { label: 'Online',  badge: 'bg-emerald-500/15 text-emerald-600 border-emerald-500/30', icon: CheckCircle2 },
  offline: { label: 'Down',    badge: 'bg-rose-500/15 text-rose-600 border-rose-500/30',          icon: XCircle },
  stale:   { label: 'No signal', badge: 'bg-amber-500/15 text-amber-600 border-amber-500/30',     icon: WifiOff },
};

export default function DeviceHealthPage() {
  const { t } = useTranslation();
  const [data, setData] = useState<DeviceHealthResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [lastFetch, setLastFetch] = useState<Date>(new Date());

  const refresh = useCallback(async () => {
    try {
      const res = await api.get<DeviceHealthResponse>('/api/v1/monitor/health');
      setData(res.data);
      setErr(null);
      setLastFetch(new Date());
    } catch (e: any) {
      setErr(e?.response?.data?.detail || e?.message || 'Failed to load device health');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => {
    const id = setInterval(refresh, 15_000);
    return () => clearInterval(id);
  }, [refresh]);

  const isAdmin = getCurrentUser()?.role === 'admin';
  const removeDevice = useCallback(async (d: DeviceHealthItem) => {
    if (!window.confirm(
      `Remove "${d.label}" from Device Health?\n\nFirst make sure this device is no longer listed in that PC's watchdog_agent.json (and the watchdog restarted) — otherwise it will re-appear on the next heartbeat.`
    )) return;
    try {
      await api.delete(`/api/v1/monitor/devices/${encodeURIComponent(d.device_key)}`);
      await refresh();
    } catch (e: any) {
      setErr(e?.response?.data?.detail || e?.message || 'Failed to remove device');
    }
  }, [refresh]);

  const devices = data?.devices ?? [];
  const summary = data?.summary ?? { total: 0, online: 0, down: 0 };
  const cfg = data?.config;

  return (
    <div className="p-4 md:p-6 max-w-6xl mx-auto">
      <header className="flex flex-wrap items-center justify-between gap-3 mb-5">
        <div className="flex items-center gap-3">
          <Activity className="h-7 w-7 text-primary" />
          <div>
            <h1 className="text-2xl font-bold tracking-tight">{t('deviceHealth.title', 'Device Health')}</h1>
            <p className="text-xs text-muted-foreground">
              {t('deviceHealth.subtitle', 'Scale & camera uptime')} · {t('deviceHealth.updated', 'updated')}{' '}
              {lastFetch.toLocaleTimeString('en-IN', { hour12: false })}
              {cfg && !cfg.enabled && (
                <span className="ml-2 text-amber-600">· {t('deviceHealth.alertsOff', 'alerts off')}</span>
              )}
            </p>
          </div>
        </div>
        <button onClick={refresh}
                className="flex items-center gap-2 px-3 py-2 rounded-lg border bg-card hover:bg-accent text-sm">
          <RefreshCw className="h-4 w-4" /> {t('common.refresh', 'Refresh')}
        </button>
      </header>

      {/* KPI strip */}
      <section className="grid grid-cols-3 gap-3 md:gap-4 mb-6">
        <Kpi label={t('deviceHealth.devices', 'Devices')} value={summary.total} tone="neutral" />
        <Kpi label={t('deviceHealth.online', 'Online')} value={summary.online} tone="ok" />
        <Kpi label={t('deviceHealth.down', 'Down')} value={summary.down} tone={summary.down > 0 ? 'bad' : 'neutral'} />
      </section>

      {err && (
        <div className="mb-4 rounded-lg border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-600">
          {err}
        </div>
      )}

      {loading ? (
        <div className="text-center text-muted-foreground py-16">{t('common.loading', 'Loading…')}</div>
      ) : devices.length === 0 ? (
        <div className="rounded-xl border border-dashed p-10 text-center">
          <Activity className="h-10 w-10 mx-auto mb-3 text-muted-foreground/50" />
          <p className="font-medium">{t('deviceHealth.emptyTitle', 'No devices are reporting yet')}</p>
          <p className="text-sm text-muted-foreground mt-1 max-w-md mx-auto">
            {t('deviceHealth.emptyHint',
              'Install the Watchdog Agent on each plant PC (weighbridge + gate). It probes the scale and cameras and reports their status here every 30 seconds.')}
          </p>
        </div>
      ) : (
        <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 md:gap-4">
          {devices.map((d) => (
            <DeviceCard key={d.device_key} d={d} onRemove={isAdmin ? removeDevice : undefined} />
          ))}
        </section>
      )}
    </div>
  );
}

function Kpi({ label, value, tone }: { label: string; value: number; tone: 'ok' | 'bad' | 'neutral' }) {
  const color = tone === 'ok' ? 'text-emerald-600' : tone === 'bad' ? 'text-rose-600' : 'text-foreground';
  return (
    <div className="rounded-xl border bg-card p-4">
      <div className={`text-3xl font-black ${color}`}>{value}</div>
      <div className="text-xs uppercase tracking-wide text-muted-foreground mt-1">{label}</div>
    </div>
  );
}

function DeviceCard({ d, onRemove }: { d: DeviceHealthItem; onRemove?: (d: DeviceHealthItem) => void }) {
  const DIcon = deviceIcon(d.device_type);
  const meta = STATUS_META[d.status] ?? STATUS_META.stale;
  const SIcon = meta.icon;
  return (
    <div className="rounded-xl border bg-card p-4 flex flex-col gap-2">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <DIcon className="h-5 w-5 text-muted-foreground shrink-0" />
          <div className="min-w-0">
            <div className="font-semibold truncate">{d.label}</div>
            <div className="text-xs text-muted-foreground truncate">
              {d.device_type}{d.site ? ` · ${d.site}` : ''}
            </div>
          </div>
        </div>
        <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium shrink-0 ${meta.badge}`}>
          <SIcon className="h-3.5 w-3.5" /> {meta.label}
        </span>
      </div>
      <div className="text-xs text-muted-foreground flex items-center justify-between">
        <span>seen {ago(d.last_seen_age_secs)}</span>
        {onRemove && (
          <button
            onClick={() => onRemove(d)}
            title="Remove this device from the dashboard (admin)"
            className="inline-flex items-center gap-1 text-muted-foreground hover:text-rose-600 transition-colors"
          >
            <Trash2 className="h-3.5 w-3.5" /> Remove
          </button>
        )}
      </div>
      {d.status !== 'online' && d.last_error && (
        <div className="text-xs text-rose-600 truncate" title={d.last_error}>{d.last_error}</div>
      )}
    </div>
  );
}
