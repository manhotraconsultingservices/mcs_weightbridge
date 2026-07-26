import { useState, useCallback, useEffect } from 'react';
import { DoorOpen, RefreshCw, Camera, ImageOff, X, ExternalLink, FileText } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { DataTable, type ColumnDef } from '@/components/DataTable';
import { TokenDetailModal } from '@/components/TokenDetailModal';
import api from '@/services/api';

interface GatePassRow {
  id: string;
  gate_pass_no: string;
  pass_date: string;
  vehicle_no: string | null;
  vehicle_name: string | null;
  vehicle_type: string | null;
  driver_name: string | null;
  driver_phone: string | null;
  material: string | null;
  purpose: string;
  status: string;
  entry_time: string | null;
  exit_time: string | null;
  dwell_minutes: number | null;
  token_no: number | null;
  token_id: string | null;
  net_weight_mt: number | null;
  entry_photo_path: string | null;
  exit_photo_path: string | null;
  notes: string | null;
  created_by: string | null;
  invoice_id: string | null;
  invoice_no: string | null;
}

interface GatePassRegister {
  items: GatePassRow[];
  count: number;
  from_date: string;
  to_date: string;
  total_vehicles: number;
  total_exited: number;
  total_inside: number;
}

const STATUS_COLORS: Record<string, string> = {
  inside: 'bg-blue-100 text-blue-800 border-blue-300',
  exited: 'bg-green-100 text-green-800 border-green-300',
  cancelled: 'bg-red-100 text-red-800 border-red-300',
};

function fmtIST(iso: string | null) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('en-IN', {
    timeZone: 'Asia/Kolkata',
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit', hour12: true,
  });
}

function today() { return new Date().toISOString().split('T')[0]; }
function daysAgo(n: number) {
  const d = new Date(); d.setDate(d.getDate() - n);
  return d.toISOString().split('T')[0];
}

// ── Gate Pass Detail Dialog ───────────────────────────────────────────────────
function GatePassDetailDialog({
  pass,
  onClose,
  onViewToken,
}: {
  pass: GatePassRow | null;
  onClose: () => void;
  onViewToken: (tokenId: string) => void;
}) {
  const [lightbox, setLightbox] = useState<{ src: string; label: string } | null>(null);

  if (!pass) return null;

  const photoUrl = (path: string | null) =>
    path ? `/${path.replace(/^\//, '')}` : null;

  const entryUrl = photoUrl(pass.entry_photo_path);
  const exitUrl = photoUrl(pass.exit_photo_path);

  return (
    <>
      <Dialog open={!!pass} onOpenChange={v => !v && onClose()}>
        <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <DoorOpen className="h-4 w-4 text-primary" />
              Gate Pass
              <span className="font-mono text-primary">{pass.gate_pass_no}</span>
              <Badge className={`ml-2 text-xs ${STATUS_COLORS[pass.status] ?? ''}`}>
                {pass.status.charAt(0).toUpperCase() + pass.status.slice(1)}
              </Badge>
            </DialogTitle>
          </DialogHeader>

          <div className="space-y-4 text-sm">
            {/* Info grid */}
            <div className="grid grid-cols-2 gap-2 rounded-lg bg-muted/40 p-3">
              {[
                { label: 'Vehicle', value: pass.vehicle_no ?? '—' },
                { label: 'Vehicle Name', value: pass.vehicle_name ?? '—' },
                { label: 'Driver', value: pass.driver_name ?? '—' },
                { label: 'Driver Phone', value: pass.driver_phone ?? '—' },
                { label: 'Material', value: pass.material ?? '—' },
                { label: 'Purpose', value: pass.purpose.replace('_', ' ') },
                { label: 'Date', value: new Date(pass.pass_date).toLocaleDateString('en-IN') },
                { label: 'Dwell', value: pass.dwell_minutes != null ? `${pass.dwell_minutes} min` : '—' },
                { label: 'Entry (IST)', value: fmtIST(pass.entry_time) },
                { label: 'Exit (IST)', value: fmtIST(pass.exit_time) },
                { label: 'Net Weight', value: pass.net_weight_mt != null ? `${Number(pass.net_weight_mt).toFixed(3)} MT` : '—' },
                { label: 'Created By', value: pass.created_by ?? '—' },
              ].map(({ label, value }) => (
                <div key={label}>
                  <p className="text-xs text-muted-foreground">{label}</p>
                  <p className="font-medium capitalize">{value}</p>
                </div>
              ))}
            </div>

            {/* Notes */}
            {pass.notes && (
              <div className="rounded-lg border px-3 py-2 text-muted-foreground italic text-xs">
                {pass.notes}
              </div>
            )}

            {/* Photos — always show both slots with timestamps */}
            <div>
              <p className="text-xs font-semibold text-muted-foreground mb-2 flex items-center gap-1">
                <Camera className="h-3.5 w-3.5" /> Gate Photos
              </p>
              <div className="grid grid-cols-2 gap-3">
                {(['entry', 'exit'] as const).map(pos => {
                  const url = pos === 'entry' ? entryUrl : exitUrl;
                  const ts  = pos === 'entry' ? pass.entry_time : pass.exit_time;
                  return (
                    <div key={pos}>
                      <p className="text-xs font-medium capitalize mb-0.5">{pos} Photo</p>
                      <p className="text-[10px] text-muted-foreground mb-1">{fmtIST(ts)}</p>
                      {url ? (
                        <img
                          src={url}
                          alt={`${pos} photo`}
                          className="w-full rounded border object-cover cursor-zoom-in hover:opacity-90 transition-opacity"
                          style={{ maxHeight: 160 }}
                          onClick={() => setLightbox({ src: url, label: `${pass.gate_pass_no} — ${pos} · ${fmtIST(ts)}` })}
                        />
                      ) : (
                        <div className="flex flex-col items-center justify-center h-32 rounded border bg-muted text-muted-foreground gap-1">
                          <ImageOff className="h-4 w-4" />
                          <span className="text-xs">No photo</span>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>

            {/* View Token */}
            {pass.token_id && (
              <Button
                variant="outline"
                size="sm"
                className="w-full gap-2"
                onClick={() => { onClose(); onViewToken(pass.token_id!); }}
              >
                <ExternalLink className="h-3.5 w-3.5" />
                View Token #{pass.token_no}
              </Button>
            )}
          </div>
        </DialogContent>
      </Dialog>

      {/* Lightbox */}
      {lightbox && (
        <div
          className="fixed inset-0 z-[200] flex items-center justify-center bg-black/85 backdrop-blur-sm"
          onClick={() => setLightbox(null)}
        >
          <div className="relative max-w-4xl w-full mx-4" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-2 px-1">
              <span className="text-white text-sm font-medium">{lightbox.label}</span>
              <button
                onClick={() => setLightbox(null)}
                className="text-white/60 hover:text-white text-xs border border-white/20 rounded px-2 py-0.5 flex items-center gap-1"
              >
                <X className="h-3 w-3" /> Close
              </button>
            </div>
            <img
              src={lightbox.src}
              alt={lightbox.label}
              className="w-full rounded-lg shadow-2xl"
              style={{ maxHeight: '80vh', objectFit: 'contain' }}
            />
          </div>
        </div>
      )}
    </>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function GatePassRegisterPage() {
  const [fromDate, setFromDate] = useState(daysAgo(6));
  const [toDate, setToDate] = useState(today());
  const [status, setStatus] = useState('all');
  const [purpose, setPurpose] = useState('all');
  const [vehicleNo, setVehicleNo] = useState('');
  const [data, setData] = useState<GatePassRegister | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');
  const [selectedPass, setSelectedPass] = useState<GatePassRow | null>(null);
  const [tokenModalId, setTokenModalId] = useState<string | null>(null);

  const handleInvoicePdf = useCallback((invoiceId: string, invoiceNo: string) => {
    api.get(`/api/v1/invoices/${invoiceId}/pdf`, { responseType: 'blob' })
      .then(res => {
        const url = URL.createObjectURL(res.data as Blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${invoiceNo}.pdf`;
        a.click();
        URL.revokeObjectURL(url);
      })
      .catch(() => alert('Failed to download invoice PDF'));
  }, []);

  const fetch = useCallback(() => {
    setLoading(true);
    setErr('');
    const p = new URLSearchParams({ from_date: fromDate, to_date: toDate });
    if (status !== 'all') p.set('status', status);
    if (purpose !== 'all') p.set('purpose', purpose);
    if (vehicleNo.trim()) p.set('vehicle_no', vehicleNo.trim());
    api.get<GatePassRegister>(`/api/v1/reports/gate-pass-register?${p}`)
      .then(r => setData(r.data))
      .catch(e => {
        setData(null);
        const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
        setErr(typeof detail === 'string' ? detail : 'Failed to load gate pass data. Check the date range.');
      })
      .finally(() => setLoading(false));
  }, [fromDate, toDate, status, purpose, vehicleNo]);

  // Auto-refetch only on the structured filters — NOT on vehicleNo keystrokes.
  // The free-text vehicle filter applies via Enter / the Refresh button (fetch reads
  // the latest value), so we avoid a backend query per keypress + response races.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { fetch(); }, [fromDate, toDate, status, purpose]);

  const COLUMNS: ColumnDef<GatePassRow>[] = [
    { key: 'gate_pass_no', label: 'Gate Pass No', accessor: r => r.gate_pass_no,
      format: (v, row) => (
        <button
          className="font-mono font-semibold text-primary underline hover:opacity-75 text-left"
          onClick={() => setSelectedPass(row)}
        >
          {String(v)}
        </button>
      ),
      exportValue: r => r.gate_pass_no },
    { key: 'pass_date', label: 'Date', type: 'date', accessor: r => r.pass_date,
      format: v => new Date(String(v)).toLocaleDateString('en-IN'),
      exportValue: r => r.pass_date ? new Date(r.pass_date).toLocaleDateString('en-IN') : '' },
    { key: 'vehicle_no', label: 'Vehicle', accessor: r => r.vehicle_no ?? '—' },
    { key: 'driver_name', label: 'Driver', accessor: r => r.driver_name ?? '—' },
    { key: 'material', label: 'Material', accessor: r => r.material ?? '—' },
    { key: 'purpose', label: 'Purpose', type: 'enum',
      enumOptions: ['weighbridge', 'delivery', 'pickup', 'own_use', 'other'],
      accessor: r => r.purpose,
      format: v => <span className="capitalize">{String(v).replace('_', ' ')}</span> },
    { key: 'status', label: 'Status', type: 'enum',
      enumOptions: ['inside', 'exited', 'cancelled'],
      accessor: r => r.status,
      format: v => (
        <Badge className={`text-xs ${STATUS_COLORS[String(v)] ?? ''}`}>
          {String(v).charAt(0).toUpperCase() + String(v).slice(1)}
        </Badge>
      ),
      exportValue: r => r.status },
    { key: 'entry_time', label: 'Entry (IST)', accessor: r => r.entry_time ?? '',
      format: v => fmtIST(v as string | null), exportValue: r => fmtIST(r.entry_time) },
    { key: 'exit_time', label: 'Exit (IST)', accessor: r => r.exit_time ?? '',
      format: v => fmtIST(v as string | null), exportValue: r => fmtIST(r.exit_time) },
    { key: 'dwell_minutes', label: 'Dwell (min)', type: 'number', align: 'right',
      accessor: r => r.dwell_minutes ?? '',
      format: v => v !== '' ? `${v} min` : '—' },
    { key: 'photos', label: 'Photos', accessor: r => (r.entry_photo_path ? 1 : 0) + (r.exit_photo_path ? 1 : 0),
      format: (_, row) => (
        <button
          onClick={() => setSelectedPass(row)}
          className="flex items-center gap-1"
          title="Click to view photos"
        >
          <span className={`inline-flex items-center gap-0.5 text-[10px] px-1.5 py-0.5 rounded font-medium ${
            row.entry_photo_path ? 'bg-emerald-100 text-emerald-700 border border-emerald-300' : 'bg-muted text-muted-foreground border'
          }`}>
            <Camera className="h-2.5 w-2.5" /> IN
          </span>
          <span className={`inline-flex items-center gap-0.5 text-[10px] px-1.5 py-0.5 rounded font-medium ${
            row.exit_photo_path ? 'bg-blue-100 text-blue-700 border border-blue-300' : 'bg-muted text-muted-foreground border'
          }`}>
            <Camera className="h-2.5 w-2.5" /> OUT
          </span>
        </button>
      ),
      exportValue: r => [r.entry_photo_path ? 'Entry' : '', r.exit_photo_path ? 'Exit' : ''].filter(Boolean).join(', ') || 'None' },
    { key: 'token_no', label: 'Token #', type: 'number', accessor: r => r.token_no ?? '',
      format: (v, row) => v !== '' ? (
        <button
          className="text-primary underline hover:opacity-75 font-mono"
          onClick={() => row.token_id && setTokenModalId(row.token_id)}
        >
          #{String(v)}
        </button>
      ) : <span className="text-muted-foreground">—</span>,
      exportValue: r => r.token_no ?? '' },
    { key: 'invoice_no', label: 'Invoice', accessor: r => r.invoice_no ?? '',
      format: (v, row) => v ? (
        <button
          className="text-primary underline hover:opacity-75 font-mono flex items-center gap-1"
          onClick={() => row.invoice_id && handleInvoicePdf(row.invoice_id, String(v))}
          title="Download invoice PDF"
        >
          <FileText className="h-3 w-3" />
          {String(v)}
        </button>
      ) : <span className="text-muted-foreground">—</span>,
      exportValue: r => r.invoice_no ?? '' },
    { key: 'net_weight_mt', label: 'Net (MT)', type: 'number', align: 'right',
      accessor: r => r.net_weight_mt ?? '',
      format: v => v !== '' ? `${Number(v).toFixed(3)} MT` : '—' },
    { key: 'created_by', label: 'Created By', defaultVisible: false, accessor: r => r.created_by ?? '—' },
    { key: 'notes', label: 'Notes', defaultVisible: false, accessor: r => r.notes ?? '' },
  ];

  const items = data?.items ?? [];

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <DoorOpen className="h-5 w-5 text-primary" />
        <h2 className="text-lg font-semibold">Gate Pass Register</h2>
      </div>

      {err && <p className="text-sm text-destructive bg-destructive/10 rounded-md px-3 py-2">{err}</p>}

      {/* Filters */}
      <div className="flex flex-wrap gap-3 items-end">
        <div>
          <label className="text-xs text-muted-foreground">From</label>
          <Input type="date" value={fromDate} onChange={e => setFromDate(e.target.value)} className="h-8 w-36" />
        </div>
        <div>
          <label className="text-xs text-muted-foreground">To</label>
          <Input type="date" value={toDate} onChange={e => setToDate(e.target.value)} className="h-8 w-36" />
        </div>
        <div>
          <label className="text-xs text-muted-foreground">Status</label>
          <Select value={status} onValueChange={v => setStatus(v ?? 'all')}>
            <SelectTrigger className="h-8 w-32"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All</SelectItem>
              <SelectItem value="inside">Inside</SelectItem>
              <SelectItem value="exited">Exited</SelectItem>
              <SelectItem value="cancelled">Cancelled</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div>
          <label className="text-xs text-muted-foreground">Purpose</label>
          <Select value={purpose} onValueChange={v => setPurpose(v ?? 'all')}>
            <SelectTrigger className="h-8 w-36"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All</SelectItem>
              <SelectItem value="weighbridge">Weighbridge</SelectItem>
              <SelectItem value="delivery">Delivery</SelectItem>
              <SelectItem value="pickup">Pickup</SelectItem>
              <SelectItem value="own_use">Own Use</SelectItem>
              <SelectItem value="other">Other</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div>
          <label className="text-xs text-muted-foreground">Vehicle No</label>
          <Input value={vehicleNo} onChange={e => setVehicleNo(e.target.value)}
            placeholder="MH12AB1234" className="h-8 w-36"
            onKeyDown={e => e.key === 'Enter' && fetch()} />
        </div>
        <Button size="sm" onClick={fetch} disabled={loading} className="h-8 gap-1.5">
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
          {loading ? 'Loading…' : 'Refresh'}
        </Button>

        <div className="flex gap-1">
          {[
            { label: 'Today', from: today(), to: today() },
            { label: '7 days', from: daysAgo(6), to: today() },
            { label: '30 days', from: daysAgo(29), to: today() },
          ].map(p => (
            <Button key={p.label} variant="outline" size="sm" className="h-8 text-xs"
              onClick={() => { setFromDate(p.from); setToDate(p.to); }}>
              {p.label}
            </Button>
          ))}
        </div>
      </div>

      {/* Summary cards */}
      {data && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            { label: 'Total Passes', value: data.count },
            { label: 'Unique Vehicles', value: data.total_vehicles },
            { label: 'Currently Inside', value: data.total_inside },
            { label: 'Exited', value: data.total_exited },
          ].map(c => (
            <div key={c.label} className="rounded-lg border bg-card p-3">
              <p className="text-xs text-muted-foreground">{c.label}</p>
              <p className="text-2xl font-bold">{c.value}</p>
            </div>
          ))}
        </div>
      )}

      <DataTable<GatePassRow>
        id="reports.gate-pass-register"
        data={items}
        columns={COLUMNS}
        rowKey={r => r.id}
        exportFilename={`gate-pass-register-${fromDate}-to-${toDate}`}
        defaultSort={{ key: 'pass_date', direction: 'desc' }}
        emptyMessage="No gate passes found for the selected period."
      />

      {/* Gate pass detail dialog */}
      <GatePassDetailDialog
        pass={selectedPass}
        onClose={() => setSelectedPass(null)}
        onViewToken={id => setTokenModalId(id)}
      />

      {/* Token detail modal (opened from gate pass dialog or token # link) */}
      <TokenDetailModal
        tokenId={tokenModalId}
        onClose={() => setTokenModalId(null)}
      />
    </div>
  );
}
