/**
 * Write-off report — list every invoice written off in a date range,
 * with per-customer aggregation and per-row detail.
 *
 *   GET /api/v1/reports/write-offs?from_date=&to_date=&party_id=
 */
import { useEffect, useState, useCallback, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { XCircle, Users, Loader2, AlertCircle, Calendar } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { DataTable, type ColumnDef, downloadCsv } from '@/components/DataTable';
import api from '@/services/api';

interface WriteOffRow {
  invoice_id: string;
  invoice_no: string | null;
  invoice_date: string | null;
  invoice_type: string;
  party_id: string | null;
  party_name: string;
  party_phone: string | null;
  grand_total: number;
  write_off_amount: number;
  write_off_reason: string;
  write_off_at: string | null;
  written_off_by: string;
}
interface WriteOffByParty {
  party_id: string | null;
  party_name: string;
  party_phone: string | null;
  count: number;
  total_amount: number;
}
interface WriteOffReportResponse {
  period: string;
  items: WriteOffRow[];
  by_party: WriteOffByParty[];
  totals: { count: number; amount: number; customer_count: number };
}

const INR = (v: number) =>
  '₹' + Number(v ?? 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const fmtDate = (s: string | null | undefined) =>
  s ? new Date(s).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }) : '—';

function defaultFromDate(): string {
  const d = new Date();
  d.setMonth(d.getMonth() - 6);   // last 6 months by default
  return d.toISOString().split('T')[0];
}
function todayISO(): string {
  return new Date().toISOString().split('T')[0];
}

export default function WriteOffsReportPage() {
  const [fromDate, setFromDate] = useState(defaultFromDate());
  const [toDate, setToDate] = useState(todayISO());
  const [data, setData] = useState<WriteOffReportResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await api.get<WriteOffReportResponse>(
        `/api/v1/reports/write-offs?from_date=${fromDate}&to_date=${toDate}`,
      );
      setData(data);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Failed to load write-off report');
    } finally {
      setLoading(false);
    }
  }, [fromDate, toDate]);

  useEffect(() => { load(); }, [load]);

  // ── By-Party DataTable columns ─────────────────────────────────────
  const partyColumns = useMemo<ColumnDef<WriteOffByParty>[]>(() => [
    {
      key: 'party_name', label: 'Customer',
      accessor: r => r.party_name,
      format: (_v, row) => row.party_id ? (
        <Link to={`/customers/${row.party_id}`} className="text-blue-600 hover:underline font-medium">
          {row.party_name}
        </Link>
      ) : <span className="text-slate-700">{row.party_name}</span>,
    },
    { key: 'party_phone', label: 'Phone', accessor: r => r.party_phone ?? '', className: 'font-mono text-xs' },
    {
      key: 'count', label: 'Write-offs', type: 'number', align: 'right',
      accessor: r => r.count,
      format: v => <span className="font-bold text-amber-700">{String(v)}</span>,
    },
    {
      key: 'total_amount', label: 'Total ₹', type: 'number', align: 'right',
      accessor: r => r.total_amount,
      format: v => <span className="font-bold text-rose-700">{INR(Number(v))}</span>,
    },
  ], []);

  // ── All-rows DataTable columns ─────────────────────────────────────
  const rowColumns = useMemo<ColumnDef<WriteOffRow>[]>(() => [
    {
      key: 'invoice_no', label: 'Invoice #', accessor: r => r.invoice_no ?? '',
      className: 'font-mono text-xs',
      format: (_v, row) => (
        <Link to={`/${row.invoice_type === 'purchase' ? 'purchase-' : ''}invoices?inv=${row.invoice_id}`}
              className="text-blue-600 hover:underline">
          {row.invoice_no ?? '—'}
        </Link>
      ),
    },
    {
      key: 'invoice_date', label: 'Invoice Date', type: 'date',
      accessor: r => r.invoice_date ?? '',
      format: v => fmtDate(String(v)),
    },
    {
      key: 'party_name', label: 'Customer', accessor: r => r.party_name,
      format: (_v, row) => row.party_id ? (
        <Link to={`/customers/${row.party_id}`} className="text-blue-600 hover:underline">
          {row.party_name}
        </Link>
      ) : row.party_name,
    },
    { key: 'invoice_type', label: 'Type', type: 'enum', enumOptions: ['sale', 'purchase'],
      accessor: r => r.invoice_type,
      format: v => <Badge variant="outline" className="text-[9px] uppercase">{String(v)}</Badge> },
    { key: 'grand_total', label: 'Invoice ₹', type: 'number', align: 'right',
      accessor: r => r.grand_total, format: v => INR(Number(v)) },
    {
      key: 'write_off_amount', label: 'Written-off ₹', type: 'number', align: 'right',
      accessor: r => r.write_off_amount,
      format: v => <span className="font-bold text-rose-700">{INR(Number(v))}</span>,
    },
    { key: 'write_off_reason', label: 'Reason', accessor: r => r.write_off_reason,
      className: 'text-xs text-slate-600' },
    { key: 'written_off_by', label: 'By', accessor: r => r.written_off_by,
      defaultVisible: false, className: 'text-xs text-slate-500' },
    {
      key: 'write_off_at', label: 'When', type: 'date', accessor: r => r.write_off_at ?? '',
      format: v => fmtDate(String(v)),
    },
  ], []);

  function exportCSV() {
    if (!data) return;
    const header = ['Invoice No', 'Invoice Date', 'Type', 'Customer', 'Phone',
                    'Invoice ₹', 'Written-off ₹', 'Reason', 'Written-off at', 'By'];
    const rows = data.items.map(r => [
      r.invoice_no ?? '',
      r.invoice_date ?? '',
      r.invoice_type,
      r.party_name,
      r.party_phone ?? '',
      String(r.grand_total),
      String(r.write_off_amount),
      r.write_off_reason,
      r.write_off_at ?? '',
      r.written_off_by,
    ]);
    downloadCsv(`write-offs-${fromDate}-to-${toDate}.csv`, [header, ...rows]);
  }

  return (
    <div className="space-y-4">
      {/* ── Filter bar ─────────────────────────────────────────── */}
      <div className="flex flex-wrap items-end gap-3 p-3 rounded-lg border bg-card">
        <div className="space-y-1">
          <label className="text-xs font-medium text-muted-foreground flex items-center gap-1">
            <Calendar className="h-3 w-3" /> From
          </label>
          <Input
            type="date"
            value={fromDate}
            onChange={e => setFromDate(e.target.value)}
            className="h-8 w-36 text-sm"
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs font-medium text-muted-foreground">To</label>
          <Input
            type="date"
            value={toDate}
            onChange={e => setToDate(e.target.value)}
            className="h-8 w-36 text-sm"
          />
        </div>
        <Button onClick={load} disabled={loading} variant="outline" size="sm">
          {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : 'Refresh'}
        </Button>
        <Button onClick={exportCSV} disabled={!data || data.items.length === 0} variant="outline" size="sm" className="ml-auto">
          Export CSV
        </Button>
      </div>

      {error && (
        <div className="rounded-lg border-2 border-rose-300 bg-rose-50 px-4 py-3 text-rose-800 flex items-center gap-2">
          <AlertCircle className="h-5 w-5 shrink-0" /> {error}
        </div>
      )}

      {/* ── Summary KPIs ──────────────────────────────────────── */}
      {data && (
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          <Card>
            <CardContent className="p-4">
              <div className="text-xs uppercase tracking-widest text-slate-500 font-semibold flex items-center gap-1">
                <XCircle className="h-3.5 w-3.5 text-rose-500" /> Total Written Off
              </div>
              <div className="text-2xl font-bold text-rose-700 mt-1">{INR(data.totals.amount)}</div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4">
              <div className="text-xs uppercase tracking-widest text-slate-500 font-semibold">Invoices</div>
              <div className="text-2xl font-bold text-slate-900 mt-1">{data.totals.count}</div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4">
              <div className="text-xs uppercase tracking-widest text-slate-500 font-semibold flex items-center gap-1">
                <Users className="h-3.5 w-3.5 text-blue-500" /> Customers Affected
              </div>
              <div className="text-2xl font-bold text-slate-900 mt-1">{data.totals.customer_count}</div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* ── By customer table ─────────────────────────────────── */}
      {data && data.by_party.length > 0 && (
        <Card>
          <CardContent className="p-3">
            <div className="text-sm font-semibold text-slate-700 mb-2">By Customer</div>
            <DataTable<WriteOffByParty>
              id="writeoffs.by_party"
              data={data.by_party}
              columns={partyColumns}
              rowKey={r => r.party_id ?? r.party_name}
              defaultSort={{ key: 'total_amount', direction: 'desc' }}
              exportFilename={`write-offs-by-customer-${fromDate}-to-${toDate}`}
              emptyMessage="No write-offs in this period."
            />
          </CardContent>
        </Card>
      )}

      {/* ── All write-offs table ─────────────────────────────── */}
      <Card>
        <CardContent className="p-3">
          <div className="text-sm font-semibold text-slate-700 mb-2">
            All Write-offs {data && `(${data.items.length})`}
          </div>
          <DataTable<WriteOffRow>
            id="writeoffs.rows"
            data={data?.items ?? []}
            loading={loading}
            columns={rowColumns}
            rowKey={r => r.invoice_id}
            defaultSort={{ key: 'write_off_at', direction: 'desc' }}
            exportFilename={`write-offs-${fromDate}-to-${toDate}`}
            emptyMessage="No write-offs in this period. Pick a wider date range or write off a stuck invoice."
          />
        </CardContent>
      </Card>
    </div>
  );
}
