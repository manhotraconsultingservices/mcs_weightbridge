import { useState, useCallback, useEffect } from 'react';
import { Ticket, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { DataTable, type ColumnDef } from '@/components/DataTable';
import { TokenDetailModal } from '@/components/TokenDetailModal';
import api from '@/services/api';

interface TokenRow {
  id: string;
  token_no: number | null;
  token_date: string;
  created_at: string | null;
  token_type: string;
  status: string;
  source: string;
  vehicle_no: string | null;
  vehicle_type: string | null;
  party_name: string | null;
  product_name: string | null;
  weight_method: string;
  gross_weight_mt: number | null;
  tare_weight_mt: number | null;
  net_weight_mt: number | null;
  volume_cft: number | null;
  gate_pass_no: string | null;
  invoice_no: string | null;
  invoice_status: string | null;
  grand_total: number | null;
  is_manual_weight: boolean;
}

interface TokenRegister {
  items: TokenRow[];
  count: number;
  from_date: string;
  to_date: string;
  total_net_weight_mt: number;
  completed_count: number;
  cancelled_count: number;
}

const STATUS_COLORS: Record<string, string> = {
  OPEN: 'bg-blue-100 text-blue-800 border-blue-300',
  FIRST_WEIGHT: 'bg-yellow-100 text-yellow-800 border-yellow-300',
  LOADING: 'bg-orange-100 text-orange-800 border-orange-300',
  SECOND_WEIGHT: 'bg-purple-100 text-purple-800 border-purple-300',
  COMPLETED: 'bg-green-100 text-green-800 border-green-300',
  CANCELLED: 'bg-red-100 text-red-800 border-red-300',
};

const TYPE_COLORS: Record<string, string> = {
  sale: 'bg-emerald-100 text-emerald-800',
  purchase: 'bg-sky-100 text-sky-800',
  general: 'bg-slate-100 text-slate-800',
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

const INR = (v: number | null) =>
  v != null ? '₹' + Number(v).toLocaleString('en-IN', { minimumFractionDigits: 2 }) : '—';

export default function TokenRegisterPage() {
  const [fromDate, setFromDate] = useState(daysAgo(6));
  const [toDate, setToDate] = useState(today());
  const [tokenType, setTokenType] = useState('all');
  const [status, setStatus] = useState('all');
  const [data, setData] = useState<TokenRegister | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');
  const [selectedTokenId, setSelectedTokenId] = useState<string | null>(null);

  const fetch = useCallback(() => {
    setLoading(true);
    setErr('');
    const p = new URLSearchParams({ from_date: fromDate, to_date: toDate });
    if (tokenType !== 'all') p.set('token_type', tokenType);
    if (status !== 'all') p.set('status', status);
    api.get<TokenRegister>(`/api/v1/reports/token-register?${p}`)
      .then(r => setData(r.data))
      .catch(e => {
        setData(null);
        const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
        setErr(typeof detail === 'string' ? detail : 'Failed to load token data. Check the date range.');
      })
      .finally(() => setLoading(false));
  }, [fromDate, toDate, tokenType, status]);

  useEffect(() => { fetch(); }, [fetch]);

  const COLUMNS: ColumnDef<TokenRow>[] = [
    { key: 'token_no', label: 'Token #', type: 'number', accessor: r => r.token_no ?? '',
      format: (v, row) => v !== '' ? (
        <button
          className="font-mono font-semibold text-primary underline hover:opacity-75"
          onClick={() => setSelectedTokenId(row.id)}
        >
          #{String(v)}
        </button>
      ) : <span className="text-muted-foreground text-xs">—</span>,
      exportValue: r => r.token_no ?? '' },
    { key: 'token_date', label: 'Date', type: 'date', accessor: r => r.token_date,
      format: v => new Date(String(v)).toLocaleDateString('en-IN') },
    { key: 'created_at', label: 'Time (IST)', accessor: r => r.created_at ?? '',
      format: v => fmtIST(v as string | null) },
    { key: 'token_type', label: 'Type', type: 'enum',
      enumOptions: ['sale', 'purchase', 'general'],
      accessor: r => r.token_type,
      format: v => <Badge className={`text-xs ${TYPE_COLORS[String(v)] ?? ''}`}>{String(v)}</Badge>,
      exportValue: r => r.token_type },
    { key: 'status', label: 'Status', type: 'enum',
      enumOptions: ['OPEN', 'FIRST_WEIGHT', 'LOADING', 'SECOND_WEIGHT', 'COMPLETED', 'CANCELLED'],
      accessor: r => r.status,
      format: v => (
        <Badge className={`text-xs ${STATUS_COLORS[String(v)] ?? ''}`}>
          {String(v).replace('_', ' ')}
        </Badge>
      ),
      exportValue: r => r.status },
    { key: 'vehicle_no', label: 'Vehicle', accessor: r => r.vehicle_no ?? '—' },
    { key: 'party_name', label: 'Party', accessor: r => r.party_name ?? '—' },
    { key: 'product_name', label: 'Material', accessor: r => r.product_name ?? '—' },
    { key: 'net_weight_mt', label: 'Net (MT)', type: 'number', align: 'right',
      accessor: r => r.net_weight_mt ?? '',
      format: v => v !== '' ? `${Number(v).toFixed(3)} MT` : '—' },
    { key: 'gross_weight_mt', label: 'Gross (MT)', type: 'number', align: 'right',
      defaultVisible: false,
      accessor: r => r.gross_weight_mt ?? '',
      format: v => v !== '' ? `${Number(v).toFixed(3)} MT` : '—' },
    { key: 'tare_weight_mt', label: 'Tare (MT)', type: 'number', align: 'right',
      defaultVisible: false,
      accessor: r => r.tare_weight_mt ?? '',
      format: v => v !== '' ? `${Number(v).toFixed(3)} MT` : '—' },
    { key: 'volume_cft', label: 'Volume (CFT)', type: 'number', align: 'right',
      defaultVisible: false,
      accessor: r => r.volume_cft ?? '',
      format: v => v !== '' && Number(v) > 0 ? `${Number(v).toFixed(2)} CFT` : '—' },
    { key: 'gate_pass_no', label: 'Gate Pass', accessor: r => r.gate_pass_no ?? '—',
      format: v => v !== '—' ? <span className="font-mono text-xs">{String(v)}</span> : <span className="text-muted-foreground">—</span> },
    { key: 'invoice_no', label: 'Invoice', accessor: r => r.invoice_no ?? '—' },
    { key: 'grand_total', label: 'Invoice Amt', type: 'number', align: 'right',
      accessor: r => r.grand_total ?? '',
      format: v => INR(v !== '' ? Number(v) : null),
      exportValue: r => r.grand_total ?? '' },
    { key: 'source', label: 'Source', type: 'enum',
      enumOptions: ['manual', 'anpr', 'kiosk'],
      defaultVisible: false,
      accessor: r => r.source,
      format: v => <span className="capitalize text-xs">{String(v)}</span> },
    { key: 'is_manual_weight', label: 'Manual Wt?', defaultVisible: false,
      accessor: r => r.is_manual_weight ? 'Yes' : 'No' },
  ];

  const items = data?.items ?? [];

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Ticket className="h-5 w-5 text-primary" />
        <h2 className="text-lg font-semibold">Token Register</h2>
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
          <label className="text-xs text-muted-foreground">Type</label>
          <Select value={tokenType} onValueChange={v => setTokenType(v ?? 'all')}>
            <SelectTrigger className="h-8 w-32"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Types</SelectItem>
              <SelectItem value="sale">Sale</SelectItem>
              <SelectItem value="purchase">Purchase</SelectItem>
              <SelectItem value="general">General</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div>
          <label className="text-xs text-muted-foreground">Status</label>
          <Select value={status} onValueChange={v => setStatus(v ?? 'all')}>
            <SelectTrigger className="h-8 w-40"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Statuses</SelectItem>
              <SelectItem value="OPEN">Open</SelectItem>
              <SelectItem value="FIRST_WEIGHT">First Weight</SelectItem>
              <SelectItem value="LOADING">Loading</SelectItem>
              <SelectItem value="SECOND_WEIGHT">Second Weight</SelectItem>
              <SelectItem value="COMPLETED">Completed</SelectItem>
              <SelectItem value="CANCELLED">Cancelled</SelectItem>
            </SelectContent>
          </Select>
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
            { label: 'Total Tokens', value: data.count },
            { label: 'Completed', value: data.completed_count },
            { label: 'Cancelled', value: data.cancelled_count },
            { label: 'Total Net Weight', value: `${Number(data.total_net_weight_mt ?? 0).toFixed(2)} MT` },
          ].map(c => (
            <div key={c.label} className="rounded-lg border bg-card p-3">
              <p className="text-xs text-muted-foreground">{c.label}</p>
              <p className="text-2xl font-bold">{c.value}</p>
            </div>
          ))}
        </div>
      )}

      <DataTable<TokenRow>
        id="reports.token-register"
        data={items}
        columns={COLUMNS}
        rowKey={r => r.id}
        exportFilename={`token-register-${fromDate}-to-${toDate}`}
        defaultSort={{ key: 'token_date', direction: 'desc' }}
        emptyMessage="No tokens found for the selected period."
      />

      {/* Token detail modal */}
      <TokenDetailModal
        tokenId={selectedTokenId}
        onClose={() => setSelectedTokenId(null)}
      />
    </div>
  );
}
