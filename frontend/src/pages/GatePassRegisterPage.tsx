import { useState, useCallback, useEffect } from 'react';
import { DoorOpen, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { DataTable, type ColumnDef } from '@/components/DataTable';
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
  net_weight_mt: number | null;
  notes: string | null;
  created_by: string | null;
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

const COLUMNS: ColumnDef<GatePassRow>[] = [
  { key: 'gate_pass_no', label: 'Gate Pass No', accessor: r => r.gate_pass_no,
    format: v => <span className="font-mono font-semibold">{String(v)}</span> },
  { key: 'pass_date', label: 'Date', type: 'date', accessor: r => r.pass_date,
    format: v => new Date(String(v)).toLocaleDateString('en-IN') },
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
    format: v => fmtIST(v as string | null) },
  { key: 'exit_time', label: 'Exit (IST)', accessor: r => r.exit_time ?? '',
    format: v => fmtIST(v as string | null) },
  { key: 'dwell_minutes', label: 'Dwell (min)', type: 'number', align: 'right',
    accessor: r => r.dwell_minutes ?? '',
    format: v => v !== '' ? `${v} min` : '—' },
  { key: 'token_no', label: 'Token #', type: 'number', accessor: r => r.token_no ?? '',
    format: v => v !== '' ? `#${v}` : '—' },
  { key: 'net_weight_mt', label: 'Net (MT)', type: 'number', align: 'right',
    accessor: r => r.net_weight_mt ?? '',
    format: v => v !== '' ? `${Number(v).toFixed(3)} MT` : '—' },
  { key: 'created_by', label: 'Created By', defaultVisible: false, accessor: r => r.created_by ?? '—' },
  { key: 'notes', label: 'Notes', defaultVisible: false, accessor: r => r.notes ?? '' },
];

export default function GatePassRegisterPage() {
  const [fromDate, setFromDate] = useState(daysAgo(6));
  const [toDate, setToDate] = useState(today());
  const [status, setStatus] = useState('all');
  const [purpose, setPurpose] = useState('all');
  const [vehicleNo, setVehicleNo] = useState('');
  const [data, setData] = useState<GatePassRegister | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');

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
        setErr((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to load gate pass data. Check the console for details.');
      })
      .finally(() => setLoading(false));
  }, [fromDate, toDate, status, purpose, vehicleNo]);

  useEffect(() => { fetch(); }, [fetch]);

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

        {/* Quick date presets */}
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
    </div>
  );
}
