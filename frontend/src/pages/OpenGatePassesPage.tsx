/**
 * OpenGatePassesPage — "Vehicles still inside" (owner clean-up).
 *
 * A truck leaves without the guard closing its pass, so the pass sits `inside`
 * for ever. The guard's own screen is filtered to ONE day, so yesterday's stuck
 * pass is invisible there — this page looks across ALL dates. The owner closes
 * each one with a reason (recorded on the pass, and audit-logged).
 *
 * Admin-only (see lib/rbac.ts ADMIN_ROUTES) — it rewrites the gate record after
 * the fact, so it is deliberately not delegatable.
 */
import { useCallback, useEffect, useState } from 'react';
import { DoorOpen, RefreshCw, AlertTriangle, LogOut, XCircle, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { DataTable, type ColumnDef } from '@/components/DataTable';
import { toast } from 'sonner';
import api from '@/services/api';

interface OpenPass {
  id: string;
  gate_pass_no: string;
  pass_date: string | null;
  age_days: number;
  vehicle_no: string | null;
  driver_name: string | null;
  material: string | null;
  purpose: string;
  entry_time: string | null;
  entered_by: string | null;
  notes: string | null;
  token_id: string | null;
  token_no: number | null;
  token_status: string | null;
  token_still_open: boolean;
}

function fmtIST(iso: string | null) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('en-IN', {
    timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short',
    hour: '2-digit', minute: '2-digit', hour12: true,
  });
}

export default function OpenGatePassesPage() {
  const [rows, setRows] = useState<OpenPass[]>([]);
  const [loading, setLoading] = useState(false);
  const [olderThan, setOlderThan] = useState('1');
  const [vehicle, setVehicle] = useState('');
  const [err, setErr] = useState('');

  // Resolve dialog
  const [target, setTarget] = useState<OpenPass | null>(null);
  const [action, setAction] = useState<'exit' | 'cancel'>('exit');
  const [reason, setReason] = useState('');
  const [cancelToken, setCancelToken] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    setLoading(true); setErr('');
    const p = new URLSearchParams({ older_than_days: olderThan });
    if (vehicle.trim()) p.set('vehicle_no', vehicle.trim());
    api.get<{ items: OpenPass[] }>(`/api/v1/gate/open-passes?${p}`)
      .then(r => setRows(r.data.items ?? []))
      .catch(e => {
        setRows([]);
        const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
        setErr(typeof d === 'string' ? d : 'Could not load open gate passes.');
      })
      .finally(() => setLoading(false));
  }, [olderThan, vehicle]);

  useEffect(() => { load(); }, [load]);

  function openResolve(row: OpenPass, act: 'exit' | 'cancel') {
    setTarget(row); setAction(act); setReason('');
    setCancelToken(row.token_still_open);
  }

  async function submit() {
    if (!target) return;
    if (!reason.trim()) { toast.error('Please give a reason — it goes on the permanent record.'); return; }
    setSaving(true);
    try {
      const { data } = await api.post<{ token_cancelled: boolean }>(
        `/api/v1/gate/passes/${target.id}/resolve`,
        { action, reason: reason.trim(), cancel_token: cancelToken },
      );
      toast.success(
        action === 'exit'
          ? `${target.vehicle_no ?? 'Vehicle'} marked exited${data.token_cancelled ? ' · token cancelled' : ''}`
          : `Gate pass ${target.gate_pass_no} cancelled${data.token_cancelled ? ' · token cancelled' : ''}`,
      );
      setTarget(null);
      load();
    } catch (e: unknown) {
      const d = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(typeof d === 'string' ? d : 'Could not close this gate pass.');
    } finally { setSaving(false); }
  }

  const oldest = rows.reduce((m, r) => Math.max(m, r.age_days), 0);
  const blocking = rows.filter(r => r.token_still_open).length;

  const COLUMNS: ColumnDef<OpenPass>[] = [
    { key: 'age_days', label: 'Days open', type: 'number', align: 'right',
      accessor: r => r.age_days,
      format: v => {
        const d = Number(v);
        const tone = d >= 7 ? 'bg-red-100 text-red-700'
          : d >= 2 ? 'bg-amber-100 text-amber-700' : 'bg-slate-100 text-slate-700';
        return <Badge className={`text-xs ${tone}`}>{d} d</Badge>;
      },
      exportValue: r => r.age_days },
    { key: 'gate_pass_no', label: 'Gate Pass', accessor: r => r.gate_pass_no,
      format: v => <span className="font-mono text-xs">{String(v)}</span> },
    { key: 'pass_date', label: 'Entry date', type: 'date', accessor: r => r.pass_date ?? '',
      format: v => v ? new Date(String(v)).toLocaleDateString('en-IN') : '—' },
    { key: 'entry_time', label: 'Entry (IST)', accessor: r => r.entry_time ?? '',
      format: v => fmtIST(v as string | null), exportValue: r => fmtIST(r.entry_time) },
    { key: 'vehicle_no', label: 'Vehicle', accessor: r => r.vehicle_no ?? '—' },
    { key: 'driver_name', label: 'Driver', defaultVisible: false, accessor: r => r.driver_name ?? '—' },
    { key: 'material', label: 'Material', defaultVisible: false, accessor: r => r.material ?? '—' },
    { key: 'purpose', label: 'Purpose', type: 'enum',
      enumOptions: ['weighbridge', 'delivery', 'pickup', 'own_use', 'other'],
      accessor: r => r.purpose, format: v => String(v).replace('_', ' ') },
    { key: 'entered_by', label: 'Entered By', accessor: r => r.entered_by ?? '—' },
    { key: 'token', label: 'Token', accessor: r => r.token_no ?? '',
      format: (_, row) => row.token_no
        ? <span className="text-xs">#{row.token_no}{row.token_still_open &&
            <Badge className="ml-1 bg-amber-100 text-amber-700 text-[10px]">still open</Badge>}</span>
        : <span className="text-muted-foreground text-xs">—</span>,
      exportValue: r => r.token_no ?? '' },
    { key: 'notes', label: 'Notes', defaultVisible: false, accessor: r => r.notes ?? '' },
  ];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold flex items-center gap-2">
            <DoorOpen className="h-5 w-5 text-primary" /> Vehicles still inside
          </h1>
          <p className="text-sm text-muted-foreground">
            Gate passes the guard never closed. Closing one records your reason and your name.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          <RefreshCw className={`h-4 w-4 mr-1 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </Button>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <Card><CardContent className="pt-4">
          <p className="text-xs text-muted-foreground">Open gate passes</p>
          <p className="text-2xl font-bold">{rows.length}</p>
        </CardContent></Card>
        <Card><CardContent className="pt-4">
          <p className="text-xs text-muted-foreground">Oldest</p>
          <p className={`text-2xl font-bold ${oldest >= 7 ? 'text-red-600' : ''}`}>{oldest} days</p>
        </CardContent></Card>
        <Card><CardContent className="pt-4">
          <p className="text-xs text-muted-foreground">Blocking a vehicle</p>
          <p className={`text-2xl font-bold ${blocking ? 'text-amber-600' : ''}`}>{blocking}</p>
          <p className="text-[11px] text-muted-foreground">token still open → that plate can't start a new trip</p>
        </CardContent></Card>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-1">
          <Label className="text-xs">Show</Label>
          <Select value={olderThan} onValueChange={v => setOlderThan(v ?? '1')}>
            <SelectTrigger className="h-9 w-56"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="0">Everything still inside (incl. today)</SelectItem>
              <SelectItem value="1">Older than today</SelectItem>
              <SelectItem value="2">2+ days old</SelectItem>
              <SelectItem value="7">A week or more</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <Label className="text-xs">Vehicle</Label>
          <Input className="h-9 w-44" value={vehicle} placeholder="e.g. HR55"
                 onChange={e => setVehicle(e.target.value)}
                 onKeyDown={e => e.key === 'Enter' && load()} />
        </div>
      </div>

      {err && (
        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>
      )}

      {olderThan === '0' && (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 flex gap-2">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          Today's list includes trucks that are genuinely on site right now — check before closing.
        </div>
      )}

      <DataTable<OpenPass>
        id="gate.openpasses"
        data={rows}
        columns={COLUMNS}
        rowKey={r => r.id}
        exportFilename="vehicles-still-inside"
        defaultSort={{ key: 'age_days', direction: 'desc' }}
        emptyMessage={loading ? 'Loading…' : 'Nothing left open — every vehicle has been signed out.'}
        rowActions={r => (
          <div className="flex gap-1">
            <Button size="sm" variant="outline" className="h-7 text-xs"
                    onClick={() => openResolve(r, 'exit')}>
              <LogOut className="h-3 w-3 mr-1" /> Mark exited
            </Button>
            <Button size="sm" variant="outline" className="h-7 text-xs text-red-600 hover:text-red-700"
                    onClick={() => openResolve(r, 'cancel')}>
              <XCircle className="h-3 w-3 mr-1" /> Cancel
            </Button>
          </div>
        )}
      />

      <Dialog open={!!target} onOpenChange={v => !v && setTarget(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>
              {action === 'exit' ? 'Mark vehicle exited' : 'Cancel gate pass'}
            </DialogTitle>
          </DialogHeader>
          {target && (
            <div className="space-y-3 text-sm">
              <div className="rounded-md bg-muted/40 p-3 space-y-0.5">
                <p><b>{target.vehicle_no ?? '—'}</b> · <span className="font-mono text-xs">{target.gate_pass_no}</span></p>
                <p className="text-xs text-muted-foreground">
                  In {fmtIST(target.entry_time)} · {target.age_days} day(s) ago
                  {target.entered_by ? ` · by ${target.entered_by}` : ''}
                </p>
              </div>
              <p className="text-xs text-muted-foreground">
                {action === 'exit'
                  ? 'Use this when the truck did leave but the exit was never recorded. The exit is stamped now, under your name.'
                  : 'Use this when the vehicle never actually came in — a duplicate or mistaken entry.'}
              </p>
              <div className="space-y-1">
                <Label className="text-xs">Reason <span className="text-red-500">*</span></Label>
                <Input value={reason} onChange={e => setReason(e.target.value)}
                       placeholder={action === 'exit' ? 'e.g. left at shift change, guard missed it' : 'e.g. duplicate entry'}
                       maxLength={200} autoFocus />
              </div>
              {target.token_still_open && (
                <label className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 p-2 text-xs">
                  <input type="checkbox" className="mt-0.5" checked={cancelToken}
                         onChange={e => setCancelToken(e.target.checked)} />
                  <span>
                    Also cancel the open weighment <b>#{target.token_no}</b>.
                    While it stays open, <b>{target.vehicle_no}</b> cannot start a new trip.
                  </span>
                </label>
              )}
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setTarget(null)} disabled={saving}>Close</Button>
            <Button onClick={submit} disabled={saving || !reason.trim()}
                    className={action === 'cancel' ? 'bg-red-600 hover:bg-red-700' : ''}>
              {saving && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}
              {action === 'exit' ? 'Mark exited' : 'Cancel pass'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
