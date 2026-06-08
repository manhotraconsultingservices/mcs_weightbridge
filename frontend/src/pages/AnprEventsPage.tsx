/**
 * ANPR Events — full audit log of every plate detection.
 *
 * Powered by GET /api/v1/anpr/events. Uses the shared DataTable component
 * so the operator gets sorting, per-column filtering, column show/hide,
 * and CSV export out of the box.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Camera, RefreshCw, Eye, AlertCircle } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { DataTable, type ColumnDef } from '@/components/DataTable';
import api from '@/services/api';
import type { AnprEvent, AnprEventListResponse, AnprStats } from '@/types';

const DIRECTIONS = ['entry', 'exit', 'unmatched', 'duplicate'] as const;

function today() {
  return new Date().toISOString().split('T')[0];
}
function daysAgo(n: number) {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().split('T')[0];
}

function DirectionBadge({ direction }: { direction: string }) {
  const cfg: Record<string, { label: string; cls: string }> = {
    entry:     { label: 'ENTRY',     cls: 'bg-emerald-100 text-emerald-700 border-emerald-300' },
    exit:      { label: 'EXIT',      cls: 'bg-blue-100 text-blue-700 border-blue-300' },
    unmatched: { label: 'UNMATCHED', cls: 'bg-amber-100 text-amber-700 border-amber-300' },
    duplicate: { label: 'DUPE',      cls: 'bg-gray-100 text-gray-600 border-gray-300' },
    heartbeat: { label: 'HB',        cls: 'bg-purple-100 text-purple-700 border-purple-300' },
  };
  const c = cfg[direction] ?? cfg.unmatched;
  return (
    <span className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-bold ${c.cls}`}>
      {c.label}
    </span>
  );
}

export default function AnprEventsPage() {
  const [events, setEvents] = useState<AnprEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState<AnprStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // Filters — server-side
  const [dateFrom, setDateFrom] = useState(daysAgo(7));
  const [dateTo, setDateTo] = useState(today());
  const [direction, setDirection] = useState<string>('');
  const [plate, setPlate] = useState('');
  const [needsReview, setNeedsReview] = useState<string>(''); // '' | 'true' | 'false'

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({
        page: '1', page_size: '200',
        date_from: dateFrom, date_to: dateTo,
      });
      if (direction) params.set('direction', direction);
      if (plate) params.set('plate', plate);
      if (needsReview) params.set('needs_review', needsReview);
      const [evRes, statsRes] = await Promise.all([
        api.get<AnprEventListResponse>(`/api/v1/anpr/events?${params}`),
        api.get<AnprStats>(`/api/v1/anpr/stats?date_from=${dateFrom}&date_to=${dateTo}`),
      ]);
      setEvents(evRes.data.items ?? []);
      setTotal(evRes.data.total ?? 0);
      setStats(statsRes.data);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Failed to load events');
    } finally {
      setLoading(false);
    }
  }, [dateFrom, dateTo, direction, plate, needsReview]);

  useEffect(() => { load(); }, [load]);

  const columns = useMemo<ColumnDef<AnprEvent>[]>(() => [
    {
      key: 'detected_at', label: 'Detected', type: 'date',
      accessor: e => e.detected_at,
      format: v => new Date(String(v)).toLocaleString('en-IN', { hour12: false }),
      className: 'whitespace-nowrap',
    },
    {
      key: 'plate', label: 'Plate',
      accessor: e => e.plate_normalized,
      format: (v, e) => (
        <div className="flex items-center gap-1.5">
          <span className="font-mono font-bold">{String(v)}</span>
          {e?.vehicle == null && (
            <span title="Unknown plate" className="inline-flex"><AlertCircle className="h-3 w-3 text-amber-600" /></span>
          )}
        </div>
      ),
    },
    {
      key: 'direction', label: 'Direction', type: 'enum',
      enumOptions: [...DIRECTIONS],
      accessor: e => e.direction,
      format: v => <DirectionBadge direction={String(v)} />,
      align: 'center',
    },
    {
      key: 'token_no', label: 'Token', type: 'number', align: 'right',
      accessor: e => e.token?.token_no ?? null,
      format: v => v != null ? `#${v}` : <span className="text-muted-foreground">—</span>,
      className: 'whitespace-nowrap',
    },
    {
      key: 'gate_pass_no', label: 'Gate Pass',
      accessor: e => e.token?.gate_pass_no ?? '',
      format: v => v ? <code className="text-[11px]">{String(v)}</code> : <span className="text-muted-foreground">—</span>,
      className: 'whitespace-nowrap',
    },
    {
      key: 'party_name', label: 'Party',
      accessor: e => e.token?.party_name ?? '',
      format: v => v || <span className="text-muted-foreground">—</span>,
    },
    {
      key: 'product_name', label: 'Material',
      accessor: e => e.token?.product_name ?? '',
      format: v => v || <span className="text-muted-foreground">—</span>,
    },
    {
      key: 'confidence', label: 'Conf.', type: 'number', align: 'right',
      accessor: e => e.confidence,
      // Pydantic Decimal → JSON string → coerce with Number()
      format: v => v != null ? `${(Number(v) * 100).toFixed(0)}%` : '—',
      defaultVisible: false,
    },
    {
      key: 'source', label: 'Source', type: 'enum',
      enumOptions: ['local_fastalpr', 'hikvision_webhook', 'dahua_webhook', 'cloud_platerec', 'manual'],
      accessor: e => e.source,
      format: v => <span className="text-[10px] text-muted-foreground">{String(v)}</span>,
      defaultVisible: false,
    },
    {
      key: 'camera_id', label: 'Camera', type: 'enum',
      enumOptions: ['front', 'top'],
      accessor: e => e.camera_id,
      defaultVisible: false,
    },
    {
      key: 'review', label: 'Review', type: 'enum', align: 'center',
      enumOptions: ['Pending', 'OK'],
      accessor: e => e.needs_review ? (e.reviewed_at ? 'OK' : 'Pending') : 'OK',
      format: v => v === 'Pending'
        ? <Badge variant="outline" className="border-amber-400 text-amber-700 text-[10px]">Review</Badge>
        : <span className="text-[10px] text-muted-foreground">—</span>,
    },
    {
      key: 'snapshot', label: 'Image', defaultVisible: true, align: 'center',
      accessor: e => e.snapshot_path ? 'yes' : 'no',
      format: (_v, e) => e?.snapshot_path
        ? <a href={`/${e.snapshot_path}`} target="_blank" rel="noopener noreferrer" className="inline-flex">
            <Camera className="h-4 w-4 text-blue-600 hover:text-blue-700" />
          </a>
        : <span className="text-muted-foreground">—</span>,
    },
  ], []);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-3xl font-bold tracking-tight flex items-center gap-2">
            <Camera className="h-7 w-7 text-blue-600" /> Gate Camera Events
          </h1>
          <p className="text-muted-foreground text-sm">
            Every plate detection from the gate camera — entries, exits, and review queue.
          </p>
        </div>
        <Button variant="outline" onClick={load} disabled={loading}>
          <RefreshCw className={`h-4 w-4 mr-2 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </Button>
      </div>

      {error && (
        <div className="rounded-md border border-rose-300 bg-rose-50 p-3 text-sm text-rose-800">
          {error}
        </div>
      )}

      {/* KPI strip */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
        <KpiCard title="Entries" value={stats?.entries ?? 0} color="text-emerald-700" />
        <KpiCard title="Exits"   value={stats?.exits ?? 0} color="text-blue-700" />
        <KpiCard title="Unique vehicles" value={stats?.unique_vehicles ?? 0} color="text-slate-800" />
        <KpiCard title="Currently inside" value={stats?.currently_inside ?? 0} color="text-amber-700" />
        <KpiCard title="Avg dwell"
                 value={`${Math.round(stats?.avg_dwell_minutes ?? 0)} min`} color="text-slate-800" />
      </div>

      {/* Filters */}
      <Card>
        <CardContent className="pt-4">
          <div className="flex flex-wrap items-end gap-3">
            <Field label="From">
              <Input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} className="w-40" />
            </Field>
            <Field label="To">
              <Input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} className="w-40" />
            </Field>
            <Field label="Direction">
              <select className="h-10 rounded-md border border-input bg-background px-3 text-sm"
                      value={direction} onChange={e => setDirection(e.target.value)}>
                <option value="">All</option>
                {DIRECTIONS.map(d => <option key={d} value={d}>{d}</option>)}
              </select>
            </Field>
            <Field label="Plate">
              <Input placeholder="MH12AB1234" value={plate}
                     onChange={e => setPlate(e.target.value.toUpperCase())} className="w-44 font-mono" />
            </Field>
            <Field label="Review status">
              <select className="h-10 rounded-md border border-input bg-background px-3 text-sm"
                      value={needsReview} onChange={e => setNeedsReview(e.target.value)}>
                <option value="">All</option>
                <option value="true">Needs review</option>
                <option value="false">No review needed</option>
              </select>
            </Field>
            <div className="ml-auto flex items-center gap-3">
              <span className="text-xs text-muted-foreground">
                Showing {events.length} of {total}
              </span>
              <Button variant="outline" size="sm"
                      onClick={() => { setDirection(''); setPlate(''); setNeedsReview(''); setDateFrom(daysAgo(7)); setDateTo(today()); }}>
                <Eye className="h-3.5 w-3.5 mr-1" /> Reset
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <DataTable<AnprEvent>
        id="anpr.events"
        data={events}
        columns={columns}
        rowKey={e => e.id}
        loading={loading}
        exportFilename={`anpr-events-${dateFrom}-to-${dateTo}`}
        defaultSort={{ key: 'detected_at', direction: 'desc' }}
        emptyMessage={loading ? 'Loading…' : 'No events in this window. Try widening the date range.'}
      />
    </div>
  );
}

function KpiCard({ title, value, color }: { title: string; value: number | string; color: string }) {
  return (
    <Card>
      <CardContent className="pt-4">
        <p className="text-xs text-muted-foreground uppercase tracking-widest">{title}</p>
        <p className={`text-2xl font-bold ${color}`}>{value}</p>
      </CardContent>
    </Card>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[10px] uppercase tracking-widest text-muted-foreground">{label}</span>
      {children}
    </div>
  );
}
