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
import { todayISO, shiftISO, monthStartISO } from '@/lib/dateLocal';
import { Loader2, AlertCircle, Calendar, Wallet, Landmark, HandCoins, TrendingDown, Scale, Send, Download } from 'lucide-react';
import { toast } from 'sonner';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { DataTable, type ColumnDef, downloadCsv } from '@/components/DataTable';
import api from '@/services/api';
import { getCurrentUser } from '@/hooks/useAuth';
import { useIsMobile } from '@/hooks/useIsMobile';

interface EodDay {
  date: string;
  cash_sales: number;
  electronic_sales: number;
  credit_sales: number;
  total_sales: number;
  purchases: number;
  supplier_payments: number;
  store_inventory: number;
  diesel: number;
  salary: number;
  advance: number;
  commission: number;
  overhead: number;
  total_expenses: number;
  net: number;
}
interface EodSummary extends Omit<EodDay, 'date'> {}
interface EodResponse {
  from_date: string;
  to_date: string;
  basis?: 'accrual' | 'cash';
  days: EodDay[];
  summary: EodSummary;
}
type Basis = 'accrual' | 'cash';
interface EodDetailItem {
  category: string;
  ref: string;
  party: string;
  detail: string;
  amount: number;
  direction: 'in' | 'out';
}
interface EodDetailResponse {
  date: string;
  items: EodDetailItem[];
  summary: EodSummary;
}
const CATEGORY_ORDER = ['Cash Sale', 'Bank/UPI Sale', 'Credit Sale', 'Purchase', 'Supplier Payment', 'Store', 'Diesel', 'Salary', 'Advance', 'Commission', 'Expense'];

const INR = (v: number | string | null | undefined) =>
  '₹' + Number(v ?? 0).toLocaleString('en-IN', { minimumFractionDigits: 0, maximumFractionDigits: 0 });

const INR_L = (v: number) => {
  const n = Number(v ?? 0);
  const abs = Math.abs(n);
  if (abs >= 10000000) return '₹' + (n / 10000000).toFixed(2) + ' Cr';
  if (abs >= 100000) return '₹' + (n / 100000).toFixed(2) + ' L';
  return INR(n);
};


export default function EodSummaryReportPage() {
  const [fromDate, setFromDate] = useState(todayISO());
  const [toDate, setToDate] = useState(todayISO());
  const [basis, setBasis] = useState<Basis>('accrual');
  const [data, setData] = useState<EodResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isAdmin = getCurrentUser()?.role === 'admin';
  const isMobile = useIsMobile();
  const [detailDate, setDetailDate] = useState<string | null>(null);
  const [detail, setDetail] = useState<EodDetailResponse | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const openDetail = useCallback(async (d: string) => {
    setDetailDate(d); setDetail(null); setDetailLoading(true);
    try {
      const { data } = await api.get<EodDetailResponse>(`/api/v1/reports/eod-summary/detail?date=${d}&basis=${basis}`);
      setDetail(data);
    } catch {
      toast.error('Failed to load the day breakup');
    } finally {
      setDetailLoading(false);
    }
  }, [basis]);

  function downloadDetailCsv() {
    if (!detail) return;
    const header = ['Date', 'Category', 'In/Out', 'Reference', 'Party / Item', 'Detail', 'Amount'];
    const rows = detail.items.map(it => [
      detail.date, it.category, it.direction === 'in' ? 'IN' : 'OUT',
      it.ref, it.party, it.detail, String(it.amount),
    ]);
    downloadCsv(`day-book-${detail.date}.csv`, [header, ...rows]);
  }

  // Per-day CSV (used by the mobile card view, which has no DataTable export).
  function downloadDaysCsv() {
    if (!data) return;
    const outLabel = basis === 'cash' ? 'Supplier Paid' : 'Purchases';
    const header = ['Date', 'Cash Sales', 'Bank/UPI Collections', 'Total Collected', 'Credit Sales', outLabel, 'Store', 'Diesel', 'Salary', 'Advance', ...(basis === 'accrual' ? ['Commission'] : []), 'Expenses', 'Total Expenses', 'Net'];
    const rows = data.days.map(d => [
      d.date, String(d.cash_sales), String(d.electronic_sales), String(d.total_sales), String(d.credit_sales),
      String(basis === 'cash' ? d.supplier_payments : d.purchases), String(d.store_inventory), String(d.diesel), String(d.salary),
      String(d.advance), ...(basis === 'accrual' ? [String(d.commission)] : []), String(d.overhead), String(d.total_expenses), String(d.net),
    ]);
    downloadCsv(`day-book-${fromDate}-to-${toDate}.csv`, [header, ...rows]);
  }

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const { data } = await api.get<EodResponse>(
        `/api/v1/reports/eod-summary?from_date=${fromDate}&to_date=${toDate}&basis=${basis}`);
      setData(data);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Failed to load EOD summary');
    } finally {
      setLoading(false);
    }
  }, [fromDate, toDate, basis]);

  useEffect(() => { load(); }, [load]);

  async function sendNow() {
    setSending(true);
    try {
      // /send is single-day — use the range END so a selected range sends its last day,
      // not silently today.
      const target = toDate;
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
    { key: 'date', label: 'Date', accessor: r => r.date, exportValue: r => r.date,
      format: v => (
        <button
          onClick={() => openDetail(String(v))}
          className="text-blue-600 hover:underline font-medium"
          title="Click for the transaction breakup"
        >
          {new Date(String(v)).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })}
        </button>
      ) },
    { key: 'cash_sales', label: 'Cash Sales', type: 'number', align: 'right', accessor: r => r.cash_sales,
      format: v => <span className="text-emerald-700">{INR(v as number)}</span>, exportValue: r => r.cash_sales },
    { key: 'electronic_sales', label: 'Bank/UPI Collections', type: 'number', align: 'right', accessor: r => r.electronic_sales,
      format: v => <span className="text-sky-700">{INR(v as number)}</span>, exportValue: r => r.electronic_sales },
    { key: 'total_sales', label: 'Total Collected', type: 'number', align: 'right', accessor: r => r.total_sales,
      format: v => <span className="font-semibold">{INR(v as number)}</span>, exportValue: r => r.total_sales },
    // Credit sales = material sold on credit (udhaar) — the UNPAID part of the day's sale
    // invoices. Money still owed, so it is NOT in Total Collected or Net (those are cash).
    { key: 'credit_sales', label: 'Credit Sales', type: 'number', align: 'right', accessor: r => r.credit_sales,
      format: v => <span className="text-amber-700">{INR(v as number)}</span>, exportValue: r => r.credit_sales },
    // Money-out: accrual books the purchase INVOICE; cash books the supplier PAYMENT (voucher).
    ...(basis === 'cash'
      ? [{ key: 'supplier_payments', label: 'Supplier Paid', type: 'number', align: 'right', accessor: (r: EodDay) => r.supplier_payments,
          format: (v: unknown) => INR(v as number), exportValue: (r: EodDay) => r.supplier_payments } as ColumnDef<EodDay>]
      : [{ key: 'purchases', label: 'Purchases', type: 'number', align: 'right', accessor: (r: EodDay) => r.purchases,
          format: (v: unknown) => INR(v as number), exportValue: (r: EodDay) => r.purchases } as ColumnDef<EodDay>]),
    { key: 'store_inventory', label: 'Store', type: 'number', align: 'right', accessor: r => r.store_inventory,
      format: v => INR(v as number), exportValue: r => r.store_inventory },
    { key: 'diesel', label: 'Diesel', type: 'number', align: 'right', accessor: r => r.diesel,
      format: v => INR(v as number), exportValue: r => r.diesel },
    { key: 'salary', label: 'Salary', type: 'number', align: 'right', accessor: r => r.salary,
      format: v => INR(v as number), exportValue: r => r.salary },
    { key: 'advance', label: 'Advance', type: 'number', align: 'right', accessor: r => r.advance,
      format: v => INR(v as number), exportValue: r => r.advance },
    // Accrued commission is an accrual-basis cost only (cash view excludes it).
    ...(basis === 'accrual'
      ? [{ key: 'commission', label: 'Commission', type: 'number', align: 'right', accessor: (r: EodDay) => r.commission,
          format: (v: unknown) => INR(v as number), exportValue: (r: EodDay) => r.commission } as ColumnDef<EodDay>]
      : []),
    { key: 'overhead', label: 'Expenses', type: 'number', align: 'right', accessor: r => r.overhead,
      format: v => INR(v as number), exportValue: r => r.overhead },
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
        {/* Basis toggle: Accrual (bills) vs Cash (actual money paid) */}
        <div className="flex items-center rounded-md border overflow-hidden">
          {(['accrual', 'cash'] as Basis[]).map(b => (
            <button key={b} type="button" onClick={() => setBasis(b)}
              className={`h-8 px-3 text-xs font-medium capitalize ${basis === b ? 'bg-primary text-primary-foreground' : 'bg-background hover:bg-muted'}`}
              title={b === 'cash' ? 'Cash basis — actual money paid (supplier payments), commission excluded' : 'Accrual basis — purchases booked on the bill date + accrued commission'}
            >{b === 'cash' ? 'Cash' : 'Accrual'}</button>
          ))}
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
        Day book: money collected split by how it came in — <b>Cash</b> vs <b>Bank/UPI</b> (bank / card / UPI) — plus
        <b> Credit Sales</b> (material sold on credit / udhaar — the unpaid part of the day's sale bills, money still owed,
        so it is NOT in Total Collected or Net), and every rupee out.
        <b> Accrual</b> books purchases on the bill date + accrued commission; <b>Cash</b> books actual supplier payments
        (vouchers) and drops accrued commission — use it for a true cash position. Store · diesel · salary · advances · overhead
        expenses appear in both. Sent automatically to subscribed recipients every evening (email + Telegram).
        <b> Click any date</b> for the full transaction breakup + Excel download.
      </p>

      {error && (
        <div className="rounded-lg border-2 border-rose-300 bg-rose-50 px-4 py-3 text-rose-800 flex items-center gap-2">
          <AlertCircle className="h-5 w-5 shrink-0" /> {error}
        </div>
      )}

      {/* KPI cards */}
      {s && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
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
                <Landmark className="h-3.5 w-3.5 text-sky-500" /> Bank/UPI Collections
              </div>
              <div className="text-2xl font-bold text-sky-700 mt-1">{INR_L(money('electronic_sales') as number)}</div>
              <div className="text-xs text-slate-500 mt-0.5">Bank / card / UPI</div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4">
              <div className="text-xs uppercase tracking-widest text-slate-500 font-semibold flex items-center gap-1">
                <HandCoins className="h-3.5 w-3.5 text-amber-500" /> Credit Sales
              </div>
              <div className="text-2xl font-bold text-amber-700 mt-1">{INR_L(money('credit_sales') as number)}</div>
              <div className="text-xs text-slate-500 mt-0.5">On credit — not yet paid</div>
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

      {/* Per-day breakdown — tap-friendly cards on mobile, full table on desktop */}
      {data && (isMobile ? (
        <div className="space-y-2">
          <div className="flex items-center justify-between px-1">
            <span className="text-sm font-semibold">Daily breakdown</span>
            <Button onClick={downloadDaysCsv} variant="ghost" size="sm" className="h-7 gap-1 text-xs" disabled={data.days.length === 0}>
              <Download className="h-3.5 w-3.5" /> CSV
            </Button>
          </div>
          {data.days.length === 0 ? (
            <div className="text-center text-muted-foreground py-8 text-sm rounded-lg border bg-card">No sales or expenses in this range.</div>
          ) : data.days.map(d => (
            <button
              key={d.date}
              onClick={() => openDetail(d.date)}
              className="w-full text-left rounded-lg border bg-card p-3 active:bg-muted/40 transition-colors"
            >
              <div className="flex items-center justify-between mb-2">
                <span className="font-semibold text-sm">
                  {new Date(d.date).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })}
                </span>
                <span className={`text-sm font-bold ${d.net >= 0 ? 'text-emerald-700' : 'text-rose-700'}`}>{INR(d.net)}</span>
              </div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                <div className="flex justify-between"><span className="text-muted-foreground">Cash</span><span className="text-emerald-700 font-medium">{INR(d.cash_sales)}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">Bank/UPI</span><span className="text-sky-700 font-medium">{INR(d.electronic_sales)}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">Credit</span><span className="text-amber-700 font-medium">{INR(d.credit_sales)}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">Collected</span><span className="font-medium">{INR(d.total_sales)}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">Expenses</span><span className="text-rose-700 font-medium">{INR(d.total_expenses)}</span></div>
              </div>
              <div className="mt-2 text-[11px] text-blue-600 font-medium">Tap for full breakup →</div>
            </button>
          ))}
        </div>
      ) : (
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
      ))}

      {/* Per-day transaction breakup */}
      <Dialog open={detailDate !== null} onOpenChange={(o) => { if (!o) { setDetailDate(null); setDetail(null); } }}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>
              Day Book — {detailDate ? new Date(detailDate).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }) : ''}
            </DialogTitle>
          </DialogHeader>
          {detailLoading ? (
            <div className="py-10 text-center text-muted-foreground">
              <Loader2 className="h-5 w-5 animate-spin inline" /> Loading…
            </div>
          ) : detail && detail.items.length === 0 ? (
            <div className="py-10 text-center text-muted-foreground">No transactions on this day.</div>
          ) : detail ? (
            <div className="space-y-2.5 max-h-[60vh] overflow-y-auto pr-1">
              {CATEGORY_ORDER.map(cat => {
                const rows = detail.items.filter(i => i.category === cat);
                if (rows.length === 0) return null;
                const subtotal = rows.reduce((sum, r) => sum + Number(r.amount), 0);
                const isIn = rows[0].direction === 'in';
                return (
                  <div key={cat} className="rounded-lg border overflow-hidden">
                    <div className={`flex items-center justify-between px-3 py-1.5 text-xs font-semibold uppercase tracking-wide ${isIn ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700'}`}>
                      <span>{cat} · {rows.length}</span>
                      <span>{isIn ? '+' : '−'}{INR(subtotal)}</span>
                    </div>
                    <table className="w-full text-sm">
                      <tbody>
                        {rows.map((r, i) => (
                          <tr key={i} className="border-t">
                            <td className="px-3 py-1 text-muted-foreground whitespace-nowrap">{r.ref || '—'}</td>
                            <td className="px-3 py-1">
                              {r.party || '—'}
                              {r.detail ? <span className="text-muted-foreground text-xs"> · {r.detail}</span> : null}
                            </td>
                            <td className="px-3 py-1 text-right font-mono whitespace-nowrap">{INR(r.amount)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                );
              })}
              <div className="flex items-center justify-between px-3 py-2 rounded-lg bg-slate-100 font-bold">
                <span>Net (Sales − Expenses)</span>
                <span className={Number(detail.summary.net) >= 0 ? 'text-emerald-700' : 'text-rose-700'}>{INR(detail.summary.net)}</span>
              </div>
              <Button onClick={downloadDetailCsv} variant="outline" size="sm" className="w-full gap-1.5">
                <Download className="h-3.5 w-3.5" /> Download this day (Excel / CSV)
              </Button>
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}
