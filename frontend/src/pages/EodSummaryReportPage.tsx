/**
 * EOD Daily Business Summary — "Day Book".
 *
 * A CASH / end-of-day view (distinct from the accrual P&L):
 *   • Sales IN split by how the money came in — CASH vs CREDIT (bank/card/UPI),
 *     read from the payment receipts (collections).
 *   • Money OUT itemised — Purchases · Store · Diesel · Salary · Advance · Commission.
 *     (Advances ARE counted here as real cash-out, unlike the P&L.)
 *
 *   GET  /api/v1/reports/eod-summary?from_date=&to_date=
 *   POST /api/v1/reports/eod-summary/send   (admin — fire email + Telegram now)
 */
import { useEffect, useState, useCallback } from 'react';
import { Loader2, AlertCircle, Calendar, Wallet, Landmark, TrendingDown, Scale, Send } from 'lucide-react';
import { toast } from 'sonner';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { DataTable, type ColumnDef } from '@/components/DataTable';
import api from '@/services/api';
import { getCurrentUser } from '@/hooks/useAuth';

interface EodDay {
  date: string;
  cash_sales: number;
  electronic_sales: number;
  total_sales: number;
  purchases: number;
  store_inventory: number;
  diesel: number;
  salary: number;
  advance: number;
  commission: number;
  total_expenses: number;
  net: number;
}
interface EodSummary extends Omit<EodDay, 'date'> {}
interface EodResponse {
  from_date: string;
  to_date: string;
  days: EodDay[];
  summary: EodSummary;
}

const INR = (v: number | string | null | undefined) =>
  '₹' + Number(v ?? 0).toLocaleString('en-IN', { minimumFractionDigits: 0, maximumFractionDigits: 0 });

const INR_L = (v: number) => {
  const n = Number(v ?? 0);
  const abs = Math.abs(n);
  if (abs >= 10000000) return '₹' + (n / 10000000).toFixed(2) + ' Cr';
  if (abs >= 100000) return '₹' + (n / 100000).toFixed(2) + ' L';
  return INR(n);
};

function todayISO(): string { return new Date().toISOString().split('T')[0]; }
function shiftISO(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().split('T')[0];
}
function monthStartISO(): string {
  const d = new Date();
  return new Date(d.getFullYear(), d.getMonth(), 1).toISOString().split('T')[0];
}

export default function EodSummaryReportPage() {
  const [fromDate, setFromDate] = useState(todayISO());
  const [toDate, setToDate] = useState(todayISO());
  const [data, setData] = useState<EodResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isAdmin = getCurrentUser()?.role === 'admin';

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const { data } = await api.get<EodResponse>(
        `/api/v1/reports/eod-summary?from_date=${fromDate}&to_date=${toDate}`);
      setData(data);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Failed to load EOD summary');
    } finally {
      setLoading(false);
    }
  }, [fromDate, toDate]);

  useEffect(() => { load(); }, [load]);

  async function sendNow() {
    setSending(true);
    try {
      const target = toDate === fromDate ? toDate : todayISO();
      const { data } = await api.post<{ ok: boolean; date: string }>(
        `/api/v1/reports/eod-summary/send?target_date=${target}`);
      toast.success(`Day-book for ${data.date} sent to subscribed recipients (email + Telegram).`);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(typeof detail === 'string' ? detail : 'Failed to send — check Notifications config.');
    } finally {
      setSending(false);
    }
  }

  function preset(from: string, to: string) { setFromDate(from); setToDate(to); }

  const s = data?.summary;
  const money = (k: keyof EodSummary) => (s ? s[k] : 0);

  const columns: ColumnDef<EodDay>[] = [
    { key: 'date', label: 'Date', accessor: r => r.date,
      format: v => new Date(String(v)).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }) },
    { key: 'cash_sales', label: 'Cash Sales', type: 'number', align: 'right', accessor: r => r.cash_sales,
      format: v => <span className="text-emerald-700">{INR(v as number)}</span>, exportValue: r => r.cash_sales },
    { key: 'electronic_sales', label: 'Credit (Bank/UPI)', type: 'number', align: 'right', accessor: r => r.electronic_sales,
      format: v => <span className="text-sky-700">{INR(v as number)}</span>, exportValue: r => r.electronic_sales },
    { key: 'total_sales', label: 'Total Sales', type: 'number', align: 'right', accessor: r => r.total_sales,
      format: v => <span className="font-semibold">{INR(v as number)}</span>, exportValue: r => r.total_sales },
    { key: 'purchases', label: 'Purchases', type: 'number', align: 'right', accessor: r => r.purchases,
      format: v => INR(v as number), exportValue: r => r.purchases },
    { key: 'store_inventory', label: 'Store', type: 'number', align: 'right', accessor: r => r.store_inventory,
      format: v => INR(v as number), exportValue: r => r.store_inventory },
    { key: 'diesel', label: 'Diesel', type: 'number', align: 'right', accessor: r => r.diesel,
      format: v => INR(v as number), exportValue: r => r.diesel },
    { key: 'salary', label: 'Salary', type: 'number', align: 'right', accessor: r => r.salary,
      format: v => INR(v as number), exportValue: r => r.salary },
    { key: 'advance', label: 'Advance', type: 'number', align: 'right', accessor: r => r.advance,
      format: v => INR(v as number), exportValue: r => r.advance },
    { key: 'commission', label: 'Commission', type: 'number', align: 'right', accessor: r => r.commission,
      format: v => INR(v as number), exportValue: r => r.commission },
    { key: 'total_expenses', label: 'Total Expenses', type: 'number', align: 'right', accessor: r => r.total_expenses,
      format: v => <span className="font-semibold text-rose-700">{INR(v as number)}</span>, exportValue: r => r.total_expenses },
    { key: 'net', label: 'Net', type: 'number', align: 'right', accessor: r => r.net,
      format: v => <span className={`font-bold ${Number(v) >= 0 ? 'text-emerald-700' : 'text-rose-700'}`}>{INR(v as number)}</span>,
      exportValue: r => r.net },
  ];

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
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="sm" className="h-8 text-xs" onClick={() => preset(todayISO(), todayISO())}>Today</Button>
          <Button variant="ghost" size="sm" className="h-8 text-xs" onClick={() => preset(shiftISO(-1), shiftISO(-1))}>Yesterday</Button>
          <Button variant="ghost" size="sm" className="h-8 text-xs" onClick={() => preset(shiftISO(-6), todayISO())}>Last 7</Button>
          <Button variant="ghost" size="sm" className="h-8 text-xs" onClick={() => preset(monthStartISO(), todayISO())}>This Month</Button>
        </div>
        <Button onClick={load} disabled={loading} variant="outline" size="sm">
          {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : 'Refresh'}
        </Button>
        {isAdmin && (
          <Button onClick={sendNow} disabled={sending} size="sm" className="ml-auto gap-1.5">
            {sending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
            Send now
          </Button>
        )}
      </div>

      <p className="text-xs text-muted-foreground -mt-1">
        Day book: sales split by how money came in (<b>Cash</b> vs <b>Credit</b> = bank / card / UPI), and every rupee out
        (purchases · store · diesel · salary · advances · commission). Advances are counted as cash-out here.
        Sent automatically to subscribed recipients every evening (email + Telegram).
      </p>

      {error && (
        <div className="rounded-lg border-2 border-rose-300 bg-rose-50 px-4 py-3 text-rose-800 flex items-center gap-2">
          <AlertCircle className="h-5 w-5 shrink-0" /> {error}
        </div>
      )}

      {/* KPI cards */}
      {s && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Card>
            <CardContent className="p-4">
              <div className="text-xs uppercase tracking-widest text-slate-500 font-semibold flex items-center gap-1">
                <Wallet className="h-3.5 w-3.5 text-emerald-500" /> Cash Sales
              </div>
              <div className="text-2xl font-bold text-emerald-700 mt-1">{INR_L(money('cash_sales') as number)}</div>
              <div className="text-xs text-slate-500 mt-0.5">Collected in cash</div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4">
              <div className="text-xs uppercase tracking-widest text-slate-500 font-semibold flex items-center gap-1">
                <Landmark className="h-3.5 w-3.5 text-sky-500" /> Credit Sales
              </div>
              <div className="text-2xl font-bold text-sky-700 mt-1">{INR_L(money('electronic_sales') as number)}</div>
              <div className="text-xs text-slate-500 mt-0.5">Bank / card / UPI</div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4">
              <div className="text-xs uppercase tracking-widest text-slate-500 font-semibold flex items-center gap-1">
                <TrendingDown className="h-3.5 w-3.5 text-rose-500" /> Total Expenses
              </div>
              <div className="text-2xl font-bold text-rose-700 mt-1">{INR_L(money('total_expenses') as number)}</div>
              <div className="text-xs text-slate-500 mt-0.5">Purchases + all costs</div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4">
              <div className="text-xs uppercase tracking-widest text-slate-500 font-semibold flex items-center gap-1">
                <Scale className="h-3.5 w-3.5 text-slate-500" /> Net (Sales − Exp.)
              </div>
              <div className={`text-2xl font-bold mt-1 ${Number(money('net')) >= 0 ? 'text-emerald-700' : 'text-rose-700'}`}>
                {INR_L(money('net') as number)}
              </div>
              <div className="text-xs text-slate-500 mt-0.5">Total sales {INR_L(money('total_sales') as number)}</div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Per-day table */}
      {data && (
        <Card>
          <CardContent className="p-0">
            <div className="text-sm font-semibold text-slate-700 px-3 pt-3 pb-1">Daily breakdown</div>
            <DataTable<EodDay>
              id="eod.daily"
              data={data.days}
              columns={columns}
              rowKey={r => r.date}
              defaultSort={{ key: 'date', direction: 'desc' }}
              exportFilename={`day-book-${fromDate}-to-${toDate}`}
              emptyMessage="No sales or expenses in this range."
            />
          </CardContent>
        </Card>
      )}
    </div>
  );
}
