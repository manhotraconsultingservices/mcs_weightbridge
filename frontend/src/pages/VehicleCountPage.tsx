/**
 * Gate Vehicle Count — autonomous truck/car/motorcycle/bus tally with snapshots.
 *
 * Paid, opt-in feature gated by the `vehicle_count` module (default OFF). The
 * platform admin enables it per-tenant in the Feature Modules panel. On the
 * plant side a lightweight vehicle-detection model runs on the gate camera
 * frames (Phase 3, installed on the gate PC) and POSTs one event per vehicle,
 * so no one has to click anything. This page reconciles the camera count
 * against the gate passes the guard creates manually.
 */
import { useCallback, useEffect, useState } from 'react';
import {
  Car, Truck, Bike, Bus, DoorOpen, LogOut, ClipboardCheck, AlertTriangle,
  RefreshCw, Camera as CameraIcon, Lock,
} from 'lucide-react';
import api from '@/services/api';
import { moduleEnabled } from '@/hooks/useAuth';
import { DataTable, type ColumnDef } from '@/components/DataTable';
import { todayISO, shiftISO, monthStartISO } from '@/lib/dateLocal';

interface ClassRow { vehicle_class: string; entries: number; exits: number }
interface Counts {
  from_date: string; to_date: string;
  by_class: ClassRow[];
  totals: { entries: number; exits: number };
  gate_passes_created: number;
  reconciliation: { camera_entries: number; gate_passes: number; variance: number };
}
interface EventRow {
  id: string; position: string; vehicle_class: string;
  confidence: number | null; snapshot_url: string | null;
  camera_id: string | null; detected_at: string | null;
}

const CLASS_LABEL: Record<string, string> = {
  truck: 'Truck', car: 'Car', motorcycle: 'Motorcycle', bus: 'Bus', bicycle: 'Bicycle', auto: 'Auto',
};
const classIcon = (c: string) =>
  c === 'truck' ? Truck : (c === 'motorcycle' || c === 'bicycle') ? Bike : c === 'bus' ? Bus : Car;
const clsLabel = (c: string) => CLASS_LABEL[c] || (c ? c[0].toUpperCase() + c.slice(1) : c);

function istDateTime(iso: string | null): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString('en-IN',
      { timeZone: 'Asia/Kolkata', dateStyle: 'medium', timeStyle: 'short' });
  } catch { return iso; }
}

function Kpi({ label, value, icon: Icon, tone = 'neutral' }:
  { label: string; value: number | string; icon: typeof Car; tone?: 'neutral' | 'in' | 'out' | 'ok' | 'warn' }) {
  const toneCls =
    tone === 'in' ? 'text-emerald-600' : tone === 'out' ? 'text-sky-600'
    : tone === 'warn' ? 'text-amber-600' : tone === 'ok' ? 'text-indigo-600' : 'text-foreground';
  return (
    <div className="rounded-lg border bg-card p-4">
      <div className="flex items-center gap-2 text-muted-foreground text-xs uppercase tracking-wide">
        <Icon className="h-4 w-4" /> {label}
      </div>
      <div className={`mt-1 text-2xl font-bold ${toneCls}`}>{value}</div>
    </div>
  );
}

export default function VehicleCountPage() {
  const enabled = moduleEnabled('vehicle_count');

  const [from, setFrom] = useState(todayISO());
  const [to, setTo] = useState(todayISO());
  const [counts, setCounts] = useState<Counts | null>(null);
  const [events, setEvents] = useState<EventRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [lightbox, setLightbox] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [c, e] = await Promise.all([
        api.get<Counts>('/api/v1/vehicle-count/counts', { params: { from_date: from, to_date: to } }),
        api.get<{ items: EventRow[] }>('/api/v1/vehicle-count/events',
          { params: { from_date: from, to_date: to, page: 1, page_size: 500 } }),
      ]);
      setCounts(c.data);
      setEvents(e.data.items || []);
      setErr(null);
    } catch (ex: any) {
      setErr(ex?.response?.data?.detail || ex?.message || 'Failed to load vehicle counts');
    } finally {
      setLoading(false);
    }
  }, [from, to]);

  useEffect(() => { if (enabled) refresh(); }, [enabled, refresh]);

  // ── Premium gate — hidden/blocked unless the platform admin enabled the module ──
  if (!enabled) {
    return (
      <div className="mx-auto max-w-lg mt-16 rounded-lg border bg-card p-8 text-center">
        <Lock className="mx-auto h-10 w-10 text-muted-foreground" />
        <h1 className="mt-4 text-xl font-bold">Gate Vehicle Count</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          This is a premium add-on. It automatically counts trucks, cars and motorcycles
          entering and exiting the gate (with snapshots) and reconciles them against the
          gate passes your guard creates.
        </p>
        <p className="mt-3 text-sm font-medium">
          Contact support to enable it for your account.
        </p>
      </div>
    );
  }

  const presets: [string, () => void][] = [
    ['Today', () => { setFrom(todayISO()); setTo(todayISO()); }],
    ['Yesterday', () => { setFrom(shiftISO(-1)); setTo(shiftISO(-1)); }],
    ['Last 7 days', () => { setFrom(shiftISO(-6)); setTo(todayISO()); }],
    ['This month', () => { setFrom(monthStartISO()); setTo(todayISO()); }],
  ];

  const variance = counts?.reconciliation.variance ?? 0;
  const columns: ColumnDef<EventRow>[] = [
    {
      key: 'detected_at', label: 'Time (IST)', type: 'string',
      accessor: r => r.detected_at || '', format: v => istDateTime(String(v || '') || null),
      exportValue: r => istDateTime(r.detected_at),
    },
    {
      key: 'position', label: 'Direction', type: 'enum', enumOptions: ['entry', 'exit'],
      accessor: r => r.position,
      format: v => {
        const inn = v === 'entry';
        const I = inn ? DoorOpen : LogOut;
        return (
          <span className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-medium ${
            inn ? 'bg-emerald-500/15 text-emerald-600' : 'bg-sky-500/15 text-sky-600'}`}>
            <I className="h-3 w-3" />{inn ? 'IN' : 'OUT'}
          </span>
        );
      },
      exportValue: r => (r.position === 'entry' ? 'IN' : 'OUT'),
    },
    {
      key: 'vehicle_class', label: 'Vehicle', type: 'enum',
      enumOptions: ['truck', 'car', 'motorcycle', 'bus', 'bicycle', 'auto'],
      accessor: r => r.vehicle_class,
      format: v => {
        const I = classIcon(String(v));
        return <span className="inline-flex items-center gap-1.5"><I className="h-4 w-4 text-muted-foreground" />{clsLabel(String(v))}</span>;
      },
      exportValue: r => clsLabel(r.vehicle_class),
    },
    {
      key: 'confidence', label: 'Confidence', type: 'number', align: 'right',
      accessor: r => r.confidence ?? 0,
      format: v => (v ? `${Math.round(Number(v) * 100)}%` : '—'),
      exportValue: r => (r.confidence != null ? Math.round(r.confidence * 100) : ''),
    },
    {
      key: 'snapshot_url', label: 'Snapshot', type: 'string', accessor: r => r.snapshot_url || '',
      format: v => v
        ? <img src={String(v)} alt="vehicle" className="h-10 w-16 rounded object-cover cursor-pointer border"
               onClick={() => setLightbox(String(v))} />
        : <span className="text-muted-foreground text-xs">—</span>,
      exportValue: r => r.snapshot_url || '',
    },
  ];

  return (
    <div className="space-y-4 p-1">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <Car className="h-6 w-6" /> Gate Vehicle Count
          </h1>
          <p className="text-sm text-muted-foreground">
            Autonomous camera tally of vehicles in/out — reconciled against guard gate passes.
          </p>
        </div>
        <button onClick={refresh} disabled={loading}
          className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm hover:bg-accent disabled:opacity-50">
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </button>
      </div>

      {/* Date range + presets */}
      <div className="flex flex-wrap items-center gap-2">
        {presets.map(([label, fn]) => (
          <button key={label} onClick={fn}
            className="rounded-md border px-2.5 py-1 text-xs hover:bg-accent">{label}</button>
        ))}
        <span className="mx-1 text-muted-foreground">|</span>
        <input type="date" value={from} onChange={e => setFrom(e.target.value)}
          className="rounded-md border bg-background px-2 py-1 text-sm" />
        <span className="text-muted-foreground">→</span>
        <input type="date" value={to} onChange={e => setTo(e.target.value)}
          className="rounded-md border bg-background px-2 py-1 text-sm" />
      </div>

      {err && <div className="rounded-md border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-600">{err}</div>}

      {/* KPI cards */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="Vehicles IN" value={counts?.totals.entries ?? 0} icon={DoorOpen} tone="in" />
        <Kpi label="Vehicles OUT" value={counts?.totals.exits ?? 0} icon={LogOut} tone="out" />
        <Kpi label="Gate Passes (guard)" value={counts?.gate_passes_created ?? 0} icon={ClipboardCheck} tone="ok" />
        <Kpi label="Unlogged (IN − passes)" value={variance} icon={AlertTriangle} tone={variance > 0 ? 'warn' : 'neutral'} />
      </div>

      {/* Reconciliation banner */}
      {counts && (
        <div className={`rounded-lg border px-4 py-3 text-sm ${
          variance > 0 ? 'border-amber-500/30 bg-amber-500/10'
          : variance < 0 ? 'border-sky-500/30 bg-sky-500/10'
          : 'border-emerald-500/30 bg-emerald-500/10'}`}>
          Camera counted <b>{counts.reconciliation.camera_entries}</b> vehicle(s) in ·
          guard created <b>{counts.reconciliation.gate_passes}</b> gate pass(es) ·{' '}
          {variance > 0
            ? <span className="text-amber-700"><b>{variance}</b> arrival(s) not logged by the guard</span>
            : variance < 0
            ? <span className="text-sky-700"><b>{Math.abs(variance)}</b> more pass(es) than camera detections</span>
            : <span className="text-emerald-700">fully reconciled</span>}
        </div>
      )}

      {/* Per-class breakdown */}
      {counts && counts.by_class.length > 0 && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {counts.by_class.map(b => {
            const I = classIcon(b.vehicle_class);
            return (
              <div key={b.vehicle_class} className="rounded-lg border bg-card p-3">
                <div className="flex items-center gap-2 font-medium"><I className="h-4 w-4" />{clsLabel(b.vehicle_class)}</div>
                <div className="mt-1 flex gap-4 text-sm">
                  <span className="text-emerald-600">IN {b.entries}</span>
                  <span className="text-sky-600">OUT {b.exits}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Events table */}
      <DataTable<EventRow>
        id="vehicle-count.events"
        data={events}
        columns={columns}
        rowKey={r => r.id}
        exportFilename="gate-vehicle-events"
        defaultSort={{ key: 'detected_at', direction: 'desc' }}
        emptyMessage={
          events.length === 0 && !loading
            ? 'No vehicles counted for this range yet. The gate-camera counter runs on the plant PC — counting begins once the vehicle-detection agent is installed there.'
            : 'No events'
        }
      />

      {lightbox && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-6" onClick={() => setLightbox(null)}>
          <img src={lightbox} alt="vehicle snapshot" className="max-h-[85vh] max-w-full rounded-lg" />
        </div>
      )}

      <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <CameraIcon className="h-3.5 w-3.5" />
        Counts are an autonomous audit tally from periodic gate-camera snapshots, not a certified turnstile count.
      </p>
    </div>
  );
}
