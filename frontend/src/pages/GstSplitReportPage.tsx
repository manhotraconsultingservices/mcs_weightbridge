/**
 * GST split report — counts + totals of GST vs non-GST (Bill of Supply)
 * invoices for a date range.
 *
 *   GET /api/v1/reports/gst-split?from_date=&to_date=&invoice_type=
 */
import { useEffect, useState, useCallback, useMemo } from 'react';
import { Link } from 'react-router-dom';
import {
  FileText, FileX, Loader2, AlertCircle, Calendar, Users, Receipt,
} from 'lucide-react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { DataTable, type ColumnDef, downloadCsv } from '@/components/DataTable';
import api from '@/services/api';

interface MonthlySplit {
  month: string;
  label: string;
  gst_count: number;
  non_gst_count: number;
  gst_amount: number;
  non_gst_amount: number;
}
interface TopCashCustomer {
  party_id: string | null;
  party_name: string;
  count: number;
  total_amount: number;
}
interface GstSplitResponse {
  period: string;
  summary: {
    gst_count: number;
    non_gst_count: number;
    gst_amount: number;
    non_gst_amount: number;
    gst_tax_collected: number;
    total_count: number;
    total_amount: number;
    gst_share_pct: number;
    non_gst_share_pct: number;
  };
  monthly: MonthlySplit[];
  top_cash_customers: TopCashCustomer[];
}

const INR = (v: number) =>
  '₹' + Number(v ?? 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const INR_L = (v: number) => {
  const n = Number(v ?? 0);
  const abs = Math.abs(n);
  if (abs >= 10000000) return '₹' + (n / 10000000).toFixed(2) + ' Cr';
  if (abs >= 100000) return '₹' + (n / 100000).toFixed(2) + ' L';
  return INR(n);
};

function defaultFromDate(): string {
  const d = new Date();
  d.setMonth(d.getMonth() - 3);
  return d.toISOString().split('T')[0];
}
function todayISO(): string { return new Date().toISOString().split('T')[0]; }

export default function GstSplitReportPage() {
  const [fromDate, setFromDate] = useState(defaultFromDate());
  const [toDate, setToDate] = useState(todayISO());
  const [invoiceType, setInvoiceType] = useState<'all' | 'sale' | 'purchase'>('all');
  const [data, setData] = useState<GstSplitResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const params = new URLSearchParams();
      params.set('from_date', fromDate);
      params.set('to_date', toDate);
      if (invoiceType !== 'all') params.set('invoice_type', invoiceType);
      const { data } = await api.get<GstSplitResponse>(`/api/v1/reports/gst-split?${params}`);
      setData(data);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Failed to load GST split');
    } finally {
      setLoading(false);
    }
  }, [fromDate, toDate, invoiceType]);

  useEffect(() => { load(); }, [load]);

  const customerCols = useMemo<ColumnDef<TopCashCustomer>[]>(() => [
    {
      key: 'party_name', label: 'Customer', accessor: r => r.party_name,
      format: (_v, row) => row.party_id ? (
        <Link to={`/customers/${row.party_id}`} className="text-blue-600 hover:underline">
          {row.party_name}
        </Link>
      ) : <span>{row.party_name}</span>,
    },
    { key: 'count', label: 'Cash Invoices', type: 'number', align: 'right', accessor: r => r.count },
    {
      key: 'total_amount', label: 'Total ₹', type: 'number', align: 'right',
      accessor: r => r.total_amount,
      format: v => <span className="font-bold text-amber-700">{INR(Number(v))}</span>,
    },
  ], []);

  function exportCSV() {
    if (!data) return;
    const header = ['Month', 'GST count', 'GST amount ₹', 'Non-GST count', 'Non-GST amount ₹', 'Total ₹'];
    const rows = data.monthly.map(m => [
      m.label,
      String(m.gst_count),
      String(m.gst_amount),
      String(m.non_gst_count),
      String(m.non_gst_amount),
      String(Number(m.gst_amount) + Number(m.non_gst_amount)),
    ]);
    downloadCsv(`gst-split-${fromDate}-to-${toDate}.csv`, [header, ...rows]);
  }

  return (
    <div className="space-y-4">
      {/* Filter bar */}
      <div className="flex flex-wrap items-end gap-3 p-3 rounded-lg border bg-card">
        <div className="space-y-1">
          <label className="text-xs font-medium text-muted-foreground flex items-center gap-1">
            <Calendar className="h-3 w-3" /> From
          </label>
          <Input type="date" value={fromDate} onChange={e => setFromDate(e.target.value)} className="h-8 w-36 text-sm" />
        </div>
        <div className="space-y-1">
          <label className="text-xs font-medium text-muted-foreground">To</label>
          <Input type="date" value={toDate} onChange={e => setToDate(e.target.value)} className="h-8 w-36 text-sm" />
        </div>
        <div className="space-y-1">
          <label className="text-xs font-medium text-muted-foreground">Type</label>
          <Select value={invoiceType} onValueChange={v => setInvoiceType((v as typeof invoiceType) ?? 'all')}>
            <SelectTrigger className="h-8 w-36 text-sm"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All</SelectItem>
              <SelectItem value="sale">Sale only</SelectItem>
              <SelectItem value="purchase">Purchase only</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <Button onClick={load} disabled={loading} variant="outline" size="sm">
          {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : 'Refresh'}
        </Button>
        <Button onClick={exportCSV} disabled={!data} variant="outline" size="sm" className="ml-auto">
          Export CSV
        </Button>
      </div>

      {error && (
        <div className="rounded-lg border-2 border-rose-300 bg-rose-50 px-4 py-3 text-rose-800 flex items-center gap-2">
          <AlertCircle className="h-5 w-5 shrink-0" /> {error}
        </div>
      )}

      {/* Summary KPIs */}
      {data && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Card>
            <CardContent className="p-4">
              <div className="text-xs uppercase tracking-widest text-slate-500 font-semibold flex items-center gap-1">
                <FileText className="h-3.5 w-3.5 text-emerald-500" /> GST Invoices
              </div>
              <div className="text-2xl font-bold text-emerald-700 mt-1">{data.summary.gst_count}</div>
              <div className="text-xs text-slate-500 mt-0.5">
                {INR_L(data.summary.gst_amount)} · {data.summary.gst_share_pct.toFixed(1)}% of revenue
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4">
              <div className="text-xs uppercase tracking-widest text-slate-500 font-semibold flex items-center gap-1">
                <FileX className="h-3.5 w-3.5 text-amber-500" /> Cash (Bill of Supply)
              </div>
              <div className="text-2xl font-bold text-amber-700 mt-1">{data.summary.non_gst_count}</div>
              <div className="text-xs text-slate-500 mt-0.5">
                {INR_L(data.summary.non_gst_amount)} · {data.summary.non_gst_share_pct.toFixed(1)}% of revenue
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4">
              <div className="text-xs uppercase tracking-widest text-slate-500 font-semibold flex items-center gap-1">
                <Receipt className="h-3.5 w-3.5 text-blue-500" /> Total
              </div>
              <div className="text-2xl font-bold text-slate-900 mt-1">{data.summary.total_count}</div>
              <div className="text-xs text-slate-500 mt-0.5">{INR_L(data.summary.total_amount)} all invoices</div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4">
              <div className="text-xs uppercase tracking-widest text-slate-500 font-semibold">GST Tax Collected</div>
              <div className="text-2xl font-bold text-blue-700 mt-1">{INR_L(data.summary.gst_tax_collected)}</div>
              <div className="text-xs text-slate-500 mt-0.5">CGST + SGST + IGST</div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Monthly chart */}
      {data && data.monthly.length > 0 && (
        <Card>
          <CardContent className="p-3">
            <div className="text-sm font-semibold text-slate-700 mb-2">Monthly Breakdown</div>
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={data.monthly}>
                <CartesianGrid strokeDasharray="3 3" opacity={0.4} />
                <XAxis dataKey="label" />
                <YAxis tickFormatter={v => `₹${(v / 100000).toFixed(0)}L`} />
                <Tooltip formatter={(v: number) => INR(v)} />
                <Legend />
                <Bar dataKey="gst_amount" stackId="a" name="GST ₹" fill="#10b981" />
                <Bar dataKey="non_gst_amount" stackId="a" name="Non-GST ₹" fill="#f59e0b" />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}

      {/* Monthly table */}
      {data && data.monthly.length > 0 && (
        <Card>
          <CardContent className="p-3">
            <div className="text-sm font-semibold text-slate-700 mb-2">Per-Month Detail</div>
            <table className="w-full text-sm">
              <thead className="text-xs uppercase text-slate-500">
                <tr>
                  <th className="text-left p-2">Month</th>
                  <th className="text-right p-2 text-emerald-700">GST Count</th>
                  <th className="text-right p-2 text-emerald-700">GST ₹</th>
                  <th className="text-right p-2 text-amber-700">Cash Count</th>
                  <th className="text-right p-2 text-amber-700">Cash ₹</th>
                  <th className="text-right p-2">Total ₹</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.monthly.map(m => (
                  <tr key={m.month} className="hover:bg-slate-50">
                    <td className="p-2 font-medium">{m.label}</td>
                    <td className="p-2 text-right">{m.gst_count}</td>
                    <td className="p-2 text-right text-emerald-700">{INR(m.gst_amount)}</td>
                    <td className="p-2 text-right">{m.non_gst_count}</td>
                    <td className="p-2 text-right text-amber-700">{INR(m.non_gst_amount)}</td>
                    <td className="p-2 text-right font-bold">{INR(Number(m.gst_amount) + Number(m.non_gst_amount))}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}

      {/* Top cash customers */}
      {data && data.top_cash_customers.length > 0 && (
        <Card>
          <CardContent className="p-3">
            <div className="text-sm font-semibold text-slate-700 mb-2 flex items-center gap-1">
              <Users className="h-3.5 w-3.5 text-amber-500" /> Top Cash Customers (no-GST)
            </div>
            <DataTable<TopCashCustomer>
              id="gst-split.top-cash"
              data={data.top_cash_customers}
              columns={customerCols}
              rowKey={r => r.party_id ?? r.party_name}
              defaultSort={{ key: 'total_amount', direction: 'desc' }}
              exportFilename={`top-cash-customers-${fromDate}-to-${toDate}`}
            />
          </CardContent>
        </Card>
      )}
    </div>
  );
}
