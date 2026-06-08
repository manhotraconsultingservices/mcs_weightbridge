/**
 * Daily Vehicle Movement Report.
 *
 * One row per vehicle visit — pairs the ANPR entry detection with its
 * matching exit (when available) and joins the linked invoice. This is
 * the human-friendly "report" view of gate-camera activity, distinct
 * from the per-event log at /anpr/events.
 *
 * Powered by GET /api/v1/anpr/trips.
 * Admin can fire the same Telegram digest on demand with the
 * "Send Daily Report Now" button, which calls
 * POST /api/v1/anpr/daily-summary/send.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { RefreshCw, Send, Camera, FileText, ExternalLink } from 'lucide-react';
import { Link } from 'react-router-dom';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { DataTable, type ColumnDef } from '@/components/DataTable';
import api from '@/services/api';
import { useAuth } from '@/hooks/useAuth';
import type { AnprTrip, AnprTripListResponse } from '@/types';

function today() {
  return new Date().toISOString().split('T')[0];
}
function fmtTime(iso: string | null) {
  if (!iso) return '—';
  return new Date(iso).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false });
}
function fmtINR(n: number | null) {
  if (n == null) return '—';
  return '₹' + Number(n).toLocaleString('en-IN', { maximumFractionDigits: 0 });
}

export default function AnprTripsPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';
  const [data, setData] = useState<AnprTripListResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [msg, setMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null);

  const [dateFrom, setDateFrom] = useState(today());
  const [dateTo, setDateTo] = useState(today());

  const load = useCallback(async () => {
    setLoading(true);
    setMsg(null);
    try {
      const { data } = await api.get<AnprTripListResponse>(
        `/api/v1/anpr/trips?date_from=${dateFrom}&date_to=${dateTo}&page=1&page_size=500`
      );
      setData(data);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setMsg({ kind: 'err', text: typeof detail === 'string' ? detail : 'Failed to load trips' });
    } finally {
      setLoading(false);
    }
  }, [dateFrom, dateTo]);

  useEffect(() => { load(); }, [load]);

  async function sendDigest() {
    setSending(true);
    setMsg(null);
    try {
      const { data: res } = await api.post<{ ok: boolean; trip_count: number; entries: number; exits: number }>(
        `/api/v1/anpr/daily-summary/send?target_date=${dateTo}`,
      );
      setMsg({
        kind: 'ok',
        text: `Telegram report sent — ${res.trip_count} trip${res.trip_count === 1 ? '' : 's'} · ${res.entries} in · ${res.exits} out.`,
      });
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setMsg({ kind: 'err', text: typeof detail === 'string' ? detail : 'Failed to send daily report' });
    } finally {
      setSending(false);
    }
  }

  const columns = useMemo<ColumnDef<AnprTrip>[]>(() => [
    {
      key: 'entry_time', label: 'Entry', type: 'date',
      accessor: t => t.entry_time,
      format: v => fmtTime(v as string | null),
      className: 'whitespace-nowrap font-mono',
    },
    {
      key: 'exit_time', label: 'Exit', type: 'date',
      accessor: t => t.exit_time,
      format: (v, t) => t?.exit_time
        ? <span className="font-mono">{fmtTime(v as string)}</span>
        : <Badge variant="outline" className="border-amber-400 text-amber-700 text-[10px]">Inside</Badge>,
      className: 'whitespace-nowrap',
    },
    {
      key: 'dwell_minutes', label: 'Dwell', type: 'number', align: 'right',
      accessor: t => t.dwell_minutes,
      format: v => v != null ? `${v} min` : <span className="text-muted-foreground">—</span>,
      className: 'whitespace-nowrap',
    },
    {
      key: 'vehicle_no', label: 'Vehicle',
      accessor: t => t.vehicle_no,
      format: v => <span className="font-mono font-bold">{String(v)}</span>,
    },
    {
      key: 'gate_pass_no', label: 'Gate Pass',
      accessor: t => t.gate_pass_no ?? '',
      format: v => v ? <code className="text-[11px]">{String(v)}</code> : <span className="text-muted-foreground">—</span>,
      className: 'whitespace-nowrap',
    },
    {
      key: 'token_no', label: 'Token', type: 'number', align: 'right',
      accessor: t => t.token_no,
      format: v => v != null ? `#${v}` : <span className="text-muted-foreground">—</span>,
      className: 'whitespace-nowrap',
    },
    {
      key: 'party_name', label: 'Party',
      accessor: t => t.party_name ?? '',
      format: v => v || <span className="text-muted-foreground">—</span>,
    },
    {
      key: 'product_name', label: 'Material',
      accessor: t => t.product_name ?? '',
      format: v => v || <span className="text-muted-foreground">—</span>,
    },
    {
      key: 'net_weight_mt', label: 'Net (MT)', type: 'number', align: 'right',
      accessor: t => t.net_weight_mt,
      // Decimal → JSON string — coerce with Number() before .toFixed()
      format: v => v != null ? Number(v).toFixed(3) : <span className="text-muted-foreground">—</span>,
      className: 'whitespace-nowrap font-mono',
    },
    {
      key: 'invoice_no', label: 'Invoice',
      accessor: t => t.invoice_no ?? '',
      format: (v, t) => {
        if (!v) return <span className="text-muted-foreground">—</span>;
        return (
          <Link to={`/invoices?id=${t?.invoice_id}`} className="inline-flex items-center gap-1 text-blue-600 hover:underline">
            {String(v)} <ExternalLink className="h-3 w-3" />
          </Link>
        );
      },
      className: 'whitespace-nowrap',
    },
    {
      key: 'invoice_status', label: 'Inv Status', type: 'enum', align: 'center',
      enumOptions: ['draft', 'final', 'cancelled'],
      accessor: t => t.invoice_status ?? '',
      format: v => v
        ? <span className={`text-[10px] uppercase font-bold ${
            v === 'final' ? 'text-emerald-700' : v === 'cancelled' ? 'text-rose-700' : 'text-amber-700'
          }`}>{String(v)}</span>
        : <span className="text-muted-foreground">—</span>,
      defaultVisible: false,
    },
    {
      key: 'payment_status', label: 'Paid', type: 'enum', align: 'center',
      enumOptions: ['unpaid', 'partial', 'paid'],
      accessor: t => t.payment_status ?? '',
      format: v => v
        ? <span className={`text-[10px] uppercase font-bold ${
            v === 'paid' ? 'text-emerald-700' : v === 'partial' ? 'text-amber-700' : 'text-rose-700'
          }`}>{String(v)}</span>
        : <span className="text-muted-foreground">—</span>,
      defaultVisible: false,
    },
    {
      key: 'grand_total', label: 'Amount', type: 'number', align: 'right',
      accessor: t => t.grand_total,
      format: v => fmtINR(v as number | null),
      className: 'whitespace-nowrap',
    },
    {
      key: 'status', label: 'Token Status', type: 'enum', align: 'center',
      enumOptions: ['OPEN', 'FIRST_WEIGHT', 'LOADING', 'SECOND_WEIGHT', 'COMPLETED', 'CANCELLED'],
      accessor: t => t.status,
      format: v => <span className="text-[10px] font-bold">{String(v)}</span>,
      defaultVisible: false,
    },
    {
      key: 'source', label: 'Source', type: 'enum', align: 'center',
      enumOptions: ['anpr', 'manual', 'kiosk'],
      accessor: t => t.source,
      format: v => v === 'anpr'
        ? <span className="inline-flex items-center gap-0.5 text-[10px] font-bold text-blue-700">🤖 ANPR</span>
        : <span className="text-[10px] text-muted-foreground uppercase">{String(v)}</span>,
      defaultVisible: false,
    },
  ], []);

  const trips = data?.items ?? [];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-3xl font-bold tracking-tight flex items-center gap-2">
            <FileText className="h-7 w-7 text-blue-600" /> Daily Movement Report
          </h1>
          <p className="text-muted-foreground text-sm">
            One row per vehicle visit — entry, exit, dwell time, token, and invoice in one place.
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <Button variant="outline" onClick={load} disabled={loading}>
            <RefreshCw className={`h-4 w-4 mr-2 ${loading ? 'animate-spin' : ''}`} /> Refresh
          </Button>
          {isAdmin && (
            <Button onClick={sendDigest} disabled={sending || !trips.length}
                    title="Fire today's report via Telegram to subscribed recipients">
              <Send className={`h-4 w-4 mr-2 ${sending ? 'animate-pulse' : ''}`} />
              {sending ? 'Sending…' : 'Send Daily Report'}
            </Button>
          )}
        </div>
      </div>

      {msg && (
        <div className={`rounded-md border px-3 py-2 text-sm ${
          msg.kind === 'ok' ? 'border-emerald-300 bg-emerald-50 text-emerald-800'
                            : 'border-rose-300 bg-rose-50 text-rose-800'
        }`}>{msg.text}</div>
      )}

      {/* KPI strip */}
      <div className="grid grid-cols-2 sm:grid-cols-6 gap-3">
        <KpiCard title="Entries" value={data?.entries ?? 0} color="text-emerald-700" />
        <KpiCard title="Exits"   value={data?.exits ?? 0} color="text-blue-700" />
        <KpiCard title="Inside"  value={data?.currently_inside ?? 0} color="text-amber-700" />
        <KpiCard title="Tonnage" value={`${Number(data?.total_tonnage_mt ?? 0).toFixed(2)} MT`} color="text-slate-800" />
        <KpiCard title="Revenue" value={fmtINR(data?.total_revenue ?? 0)} color="text-violet-700" />
        <KpiCard title="Avg Dwell" value={`${Math.round(data?.avg_dwell_minutes ?? 0)} min`} color="text-slate-800" />
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
            <div className="ml-auto flex items-center gap-3">
              <Button variant="outline" size="sm" onClick={() => { setDateFrom(today()); setDateTo(today()); }}>
                Today
              </Button>
              <Button variant="outline" size="sm" onClick={() => {
                const d = new Date(); d.setDate(d.getDate() - 7);
                setDateFrom(d.toISOString().split('T')[0]); setDateTo(today());
              }}>Last 7 days</Button>
              <Button variant="outline" size="sm" onClick={() => {
                const d = new Date(); d.setDate(d.getDate() - 30);
                setDateFrom(d.toISOString().split('T')[0]); setDateTo(today());
              }}>Last 30 days</Button>
              <span className="text-xs text-muted-foreground ml-2">
                {trips.length} of {data?.total ?? 0} trips
              </span>
            </div>
          </div>
        </CardContent>
      </Card>

      <DataTable<AnprTrip>
        id="anpr.trips"
        data={trips}
        columns={columns}
        rowKey={t => t.token_id}
        loading={loading}
        exportFilename={`vehicle-movement-${dateFrom}-to-${dateTo}`}
        defaultSort={{ key: 'entry_time', direction: 'desc' }}
        emptyMessage={loading
          ? 'Loading…'
          : 'No vehicle movements in this window. Either ANPR is not yet recording, or the date range is too narrow.'}
      />

      {trips.length === 0 && !loading && (
        <div className="text-center text-xs text-muted-foreground border rounded-lg bg-slate-50 p-4">
          <Camera className="h-5 w-5 mx-auto mb-1 text-slate-400" />
          Tip: this report only shows trips where the ANPR system recorded an entry or exit.
          Enable ANPR in Settings → ANPR to start populating this report.
        </div>
      )}
    </div>
  );
}

function KpiCard({ title, value, color }: { title: string; value: number | string; color: string }) {
  return (
    <Card>
      <CardContent className="pt-4">
        <p className="text-xs text-muted-foreground uppercase tracking-widest">{title}</p>
        <p className={`text-xl font-bold ${color}`}>{value}</p>
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
