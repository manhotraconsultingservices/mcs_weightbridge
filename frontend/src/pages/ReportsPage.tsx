import { useState, useEffect, useCallback } from 'react';
import { Search, Download, TrendingUp, TrendingDown } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import api from '@/services/api';

const fmt = (n: number) => '₹' + n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtWt = (n: number | null) => n == null ? '—' : n.toLocaleString('en-IN', { minimumFractionDigits: 3, maximumFractionDigits: 3 });
const today = () => new Date().toISOString().slice(0, 10);
const monthStart = () => { const d = new Date(); d.setDate(1); return d.toISOString().slice(0, 10); };
const yearStart = () => { const d = new Date(); return `${d.getFullYear()}-04-01`; };

// Date preset helper
type DatePreset = { label: string; from: () => string; to: () => string };
const DATE_PRESETS: DatePreset[] = [
  { label: 'Today',      from: today,       to: today },
  { label: 'This Month', from: monthStart,   to: today },
  { label: 'Last Month', from: () => { const d = new Date(); d.setDate(1); d.setMonth(d.getMonth() - 1); return d.toISOString().slice(0, 10); },
                          to: () => { const d = new Date(); d.setDate(0); return d.toISOString().slice(0, 10); } },
  { label: 'This FY',   from: yearStart,    to: today },
];

function DatePresetChips({ onSelect }: { onSelect: (from: string, to: string) => void }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {DATE_PRESETS.map(p => (
        <button
          key={p.label}
          type="button"
          onClick={() => onSelect(p.from(), p.to())}
          className="rounded-full border border-border px-2.5 py-0.5 text-xs font-medium text-muted-foreground hover:border-primary hover:text-primary hover:bg-primary/5 transition-colors"
        >
          {p.label}
        </button>
      ))}
    </div>
  );
}

function downloadCSV(filename: string, headers: string[], rows: (string | number | null)[][]) {
  const lines = [headers.join(','), ...rows.map(r => r.map(c => `"${c ?? ''}"`).join(','))];
  const blob = new Blob([lines.join('\n')], { type: 'text/csv' });
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = filename; a.click();
}

// ── Types ─────────────────────────────────────────────────────────────────────

interface SalesRow { id: string; invoice_no: string; invoice_date: string; party_name: string; gstin: string | null; vehicle_no: string | null; net_weight: number | null; taxable_amount: number; cgst_amount: number; sgst_amount: number; igst_amount: number; grand_total: number; payment_status: string; }
interface SalesTotals { taxable_amount: number; cgst: number; sgst: number; igst: number; grand_total: number; }
interface SalesRegister { items: SalesRow[]; totals: SalesTotals; count: number; }

interface WeightRow { id: string; token_no: number; token_date: string; token_type: string; vehicle_no: string | null; party_name: string | null; product_name: string | null; gross_weight: number | null; tare_weight: number | null; net_weight: number | null; is_manual_weight: boolean; }
interface WeightRegister { items: WeightRow[]; total_net_weight: number; count: number; }

interface PLMonth { month: string; label: string; revenue: number; cogs: number; gross_profit: number; margin_pct: number; sale_count: number; purchase_count: number; }
interface PLData { period: string; summary: { total_revenue: number; total_cogs: number; gross_profit: number; margin_pct: number; }; monthly: PLMonth[]; }

interface StockItem { product_name: string; hsn_code: string; unit: string; rate: number; qty_purchased: number; value_purchased: number; qty_sold: number; value_sold: number; closing_qty: number; closing_value: number; }
interface StockData { period: string; items: StockItem[]; totals: { qty_purchased: number; qty_sold: number; closing_value: number; }; }

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function ReportsPage() {
  const [tab, setTab] = useState('sales');

  // Sales register
  const [salesFrom, setSalesFrom] = useState(monthStart());
  const [salesTo, setSalesTo] = useState(today());
  const [salesType, setSalesType] = useState('sale');
  const [salesData, setSalesData] = useState<SalesRegister | null>(null);
  const [salesLoading, setSalesLoading] = useState(false);

  // Weight register
  const [wtFrom, setWtFrom] = useState(monthStart());
  const [wtTo, setWtTo] = useState(today());
  const [wtType, setWtType] = useState('');
  const [wtData, setWtData] = useState<WeightRegister | null>(null);
  const [wtLoading, setWtLoading] = useState(false);

  // P&L
  const [plFrom, setPlFrom] = useState(yearStart());
  const [plTo, setPlTo] = useState(today());
  const [plData, setPlData] = useState<PLData | null>(null);
  const [plLoading, setPlLoading] = useState(false);

  // Stock Summary
  const [stFrom, setStFrom] = useState(yearStart());
  const [stTo, setStTo] = useState(today());
  const [stData, setStData] = useState<StockData | null>(null);
  const [stLoading, setStLoading] = useState(false);

  const fetchSales = useCallback(() => {
    setSalesLoading(true);
    api.get<SalesRegister>(`/api/v1/reports/sales-register?${new URLSearchParams({ from_date: salesFrom, to_date: salesTo, invoice_type: salesType })}`)
      .then(r => setSalesData(r.data)).catch(() => setSalesData(null)).finally(() => setSalesLoading(false));
  }, [salesFrom, salesTo, salesType]);

  // Auto-fetch sales report on page load
  useEffect(() => { fetchSales(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function fetchWeight() {
    setWtLoading(true);
    const p = new URLSearchParams({ from_date: wtFrom, to_date: wtTo });
    if (wtType) p.set('token_type', wtType);
    api.get<WeightRegister>(`/api/v1/reports/weight-register?${p}`)
      .then(r => setWtData(r.data)).catch(() => setWtData(null)).finally(() => setWtLoading(false));
  }

  async function fetchPL() {
    setPlLoading(true);
    api.get<PLData>(`/api/v1/reports/profit-loss?${new URLSearchParams({ from_date: plFrom, to_date: plTo })}`)
      .then(r => setPlData(r.data)).catch(() => setPlData(null)).finally(() => setPlLoading(false));
  }

  async function fetchStock() {
    setStLoading(true);
    api.get<StockData>(`/api/v1/reports/stock-summary?${new URLSearchParams({ from_date: stFrom, to_date: stTo })}`)
      .then(r => setStData(r.data)).catch(() => setStData(null)).finally(() => setStLoading(false));
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Reports</h1>
        <p className="text-muted-foreground">Sales register · Weight register · P&L · Stock summary</p>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="sales">Sales / Purchase Register</TabsTrigger>
          <TabsTrigger value="weight">Weight Register</TabsTrigger>
          <TabsTrigger value="pl">Profit & Loss</TabsTrigger>
          <TabsTrigger value="stock">Stock Summary</TabsTrigger>
        </TabsList>

        {/* ── Sales Register ── */}
        <TabsContent value="sales" className="mt-4 space-y-4">
          <DatePresetChips onSelect={(f, t) => { setSalesFrom(f); setSalesTo(t); }} />
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-1"><Label className="text-xs">From</Label><Input type="date" className="w-36" value={salesFrom} onChange={e => setSalesFrom(e.target.value)} /></div>
            <div className="space-y-1"><Label className="text-xs">To</Label><Input type="date" className="w-36" value={salesTo} onChange={e => setSalesTo(e.target.value)} /></div>
            <div className="space-y-1">
              <Label className="text-xs">Type</Label>
              <Select value={salesType} onValueChange={v => setSalesType(v ?? 'sale')}>
                <SelectTrigger className="w-32"><SelectValue /></SelectTrigger>
                <SelectContent><SelectItem value="sale">Sales</SelectItem><SelectItem value="purchase">Purchase</SelectItem></SelectContent>
              </Select>
            </div>
            <Button onClick={fetchSales} disabled={salesLoading}><Search className="mr-2 h-4 w-4" />{salesLoading ? 'Loading…' : 'Generate'}</Button>
            {salesData && salesData.items.length > 0 && (
              <Button variant="outline" onClick={() => downloadCSV(`sales-register-${salesFrom}-${salesTo}.csv`, ['Invoice No', 'Date', 'Party', 'GSTIN', 'Vehicle', 'Net Wt (MT)', 'Taxable', 'CGST', 'SGST', 'IGST', 'Total', 'Status'], salesData.items.map(r => [r.invoice_no, r.invoice_date, r.party_name, r.gstin, r.vehicle_no, r.net_weight, r.taxable_amount, r.cgst_amount, r.sgst_amount, r.igst_amount, r.grand_total, r.payment_status]))}>
                <Download className="mr-2 h-4 w-4" /> CSV
              </Button>
            )}
          </div>
          {salesData && (
            <Card><CardContent className="p-0">
              <table className="w-full text-sm">
                <thead><tr className="border-b bg-muted/50">
                  <th className="px-3 py-2 text-left font-medium text-muted-foreground">Invoice</th>
                  <th className="px-3 py-2 text-left font-medium text-muted-foreground">Party</th>
                  <th className="px-3 py-2 text-right font-medium text-muted-foreground">Net Wt (MT)</th>
                  <th className="px-3 py-2 text-right font-medium text-muted-foreground">Taxable</th>
                  <th className="px-3 py-2 text-right font-medium text-muted-foreground">GST</th>
                  <th className="px-3 py-2 text-right font-medium text-muted-foreground">Total</th>
                  <th className="px-3 py-2 text-center font-medium text-muted-foreground">Status</th>
                </tr></thead>
                <tbody>
                  {salesData.items.map(r => (
                    <tr key={r.id} className="border-b hover:bg-muted/20">
                      <td className="px-3 py-2"><p className="font-mono text-xs font-medium">{r.invoice_no}</p><p className="text-xs text-muted-foreground">{r.invoice_date}</p></td>
                      <td className="px-3 py-2"><p className="text-sm">{r.party_name}</p>{r.gstin && <p className="text-xs text-muted-foreground font-mono">{r.gstin}</p>}</td>
                      <td className="px-3 py-2 text-right text-muted-foreground">{fmtWt(r.net_weight)}</td>
                      <td className="px-3 py-2 text-right">{fmt(r.taxable_amount)}</td>
                      <td className="px-3 py-2 text-right text-muted-foreground">{fmt(r.cgst_amount + r.sgst_amount + r.igst_amount)}</td>
                      <td className="px-3 py-2 text-right font-semibold">{fmt(r.grand_total)}</td>
                      <td className="px-3 py-2 text-center"><span className={`text-[10px] px-1.5 py-0.5 rounded capitalize ${r.payment_status === 'paid' ? 'bg-green-100 text-green-800' : r.payment_status === 'partial' ? 'bg-yellow-100 text-yellow-800' : 'bg-red-100 text-red-800'}`}>{r.payment_status}</span></td>
                    </tr>
                  ))}
                  {salesData.items.length > 0 && (
                    <tr className="bg-muted/30 font-semibold">
                      <td colSpan={3} className="px-3 py-2">Total ({salesData.count} invoices)</td>
                      <td className="px-3 py-2 text-right">{fmt(salesData.totals.taxable_amount)}</td>
                      <td className="px-3 py-2 text-right">{fmt(salesData.totals.cgst + salesData.totals.sgst + salesData.totals.igst)}</td>
                      <td className="px-3 py-2 text-right">{fmt(salesData.totals.grand_total)}</td>
                      <td />
                    </tr>
                  )}
                </tbody>
              </table>
              {salesData.items.length === 0 && <div className="py-12 text-center text-muted-foreground text-sm">No records found.</div>}
            </CardContent></Card>
          )}
        </TabsContent>

        {/* ── Weight Register ── */}
        <TabsContent value="weight" className="mt-4 space-y-4">
          <DatePresetChips onSelect={(f, t) => { setWtFrom(f); setWtTo(t); }} />
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-1"><Label className="text-xs">From</Label><Input type="date" className="w-36" value={wtFrom} onChange={e => setWtFrom(e.target.value)} /></div>
            <div className="space-y-1"><Label className="text-xs">To</Label><Input type="date" className="w-36" value={wtTo} onChange={e => setWtTo(e.target.value)} /></div>
            <div className="space-y-1">
              <Label className="text-xs">Type</Label>
              <Select value={wtType || 'all'} onValueChange={v => setWtType((v ?? 'all') === 'all' ? '' : (v ?? ''))}>
                <SelectTrigger className="w-32"><SelectValue /></SelectTrigger>
                <SelectContent><SelectItem value="all">All</SelectItem><SelectItem value="sale">Sale</SelectItem><SelectItem value="purchase">Purchase</SelectItem><SelectItem value="general">General</SelectItem></SelectContent>
              </Select>
            </div>
            <Button onClick={fetchWeight} disabled={wtLoading}><Search className="mr-2 h-4 w-4" />{wtLoading ? 'Loading…' : 'Generate'}</Button>
            {wtData && wtData.items.length > 0 && (
              <Button variant="outline" onClick={() => downloadCSV(`weight-register-${wtFrom}-${wtTo}.csv`, ['Token No', 'Date', 'Type', 'Vehicle', 'Party', 'Product', 'Gross (MT)', 'Tare (MT)', 'Net (MT)', 'Manual'], wtData.items.map(r => [r.token_no, r.token_date, r.token_type, r.vehicle_no, r.party_name, r.product_name, r.gross_weight, r.tare_weight, r.net_weight, r.is_manual_weight ? 'Yes' : 'No']))}>
                <Download className="mr-2 h-4 w-4" /> CSV
              </Button>
            )}
          </div>
          {wtData && (
            <Card><CardContent className="p-0">
              <table className="w-full text-sm">
                <thead><tr className="border-b bg-muted/50">
                  <th className="px-3 py-2 text-left font-medium text-muted-foreground">Token</th>
                  <th className="px-3 py-2 text-left font-medium text-muted-foreground">Vehicle</th>
                  <th className="px-3 py-2 text-left font-medium text-muted-foreground">Party / Product</th>
                  <th className="px-3 py-2 text-right font-medium text-muted-foreground">Gross (MT)</th>
                  <th className="px-3 py-2 text-right font-medium text-muted-foreground">Tare (MT)</th>
                  <th className="px-3 py-2 text-right font-medium text-muted-foreground">Net (MT)</th>
                </tr></thead>
                <tbody>
                  {wtData.items.map(r => (
                    <tr key={r.id} className="border-b hover:bg-muted/20">
                      <td className="px-3 py-2"><p className="font-medium">#{r.token_no}</p><p className="text-xs text-muted-foreground">{r.token_date} · {r.token_type}</p></td>
                      <td className="px-3 py-2 font-mono text-xs">{r.vehicle_no || '—'}</td>
                      <td className="px-3 py-2"><p className="text-sm">{r.party_name || '—'}</p>{r.product_name && <p className="text-xs text-muted-foreground">{r.product_name}</p>}</td>
                      <td className="px-3 py-2 text-right">{fmtWt(r.gross_weight)}</td>
                      <td className="px-3 py-2 text-right">{fmtWt(r.tare_weight)}</td>
                      <td className="px-3 py-2 text-right font-semibold">{fmtWt(r.net_weight)}</td>
                    </tr>
                  ))}
                  {wtData.items.length > 0 && (
                    <tr className="bg-muted/30 font-semibold">
                      <td colSpan={5} className="px-3 py-2">Total ({wtData.count} tokens)</td>
                      <td className="px-3 py-2 text-right">{fmtWt(wtData.total_net_weight)}</td>
                    </tr>
                  )}
                </tbody>
              </table>
              {wtData.items.length === 0 && <div className="py-12 text-center text-muted-foreground text-sm">No completed tokens found.</div>}
            </CardContent></Card>
          )}
        </TabsContent>

        {/* ── Profit & Loss ── */}
        <TabsContent value="pl" className="mt-4 space-y-4">
          <DatePresetChips onSelect={(f, t) => { setPlFrom(f); setPlTo(t); }} />
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-1"><Label className="text-xs">From</Label><Input type="date" className="w-36" value={plFrom} onChange={e => setPlFrom(e.target.value)} /></div>
            <div className="space-y-1"><Label className="text-xs">To</Label><Input type="date" className="w-36" value={plTo} onChange={e => setPlTo(e.target.value)} /></div>
            <Button onClick={fetchPL} disabled={plLoading}><Search className="mr-2 h-4 w-4" />{plLoading ? 'Loading…' : 'Generate'}</Button>
            {plData && plData.monthly.length > 0 && (
              <Button variant="outline" onClick={() => downloadCSV(`pl-report-${plFrom}-${plTo}.csv`, ['Month', 'Revenue', 'Purchases (COGS)', 'Gross Profit', 'Margin %', 'Sale Invoices', 'Purchase Invoices'], plData.monthly.map(r => [r.label, r.revenue, r.cogs, r.gross_profit, r.margin_pct, r.sale_count, r.purchase_count]))}>
                <Download className="mr-2 h-4 w-4" /> CSV
              </Button>
            )}
          </div>

          {plData && (
            <div className="space-y-4">
              {/* Summary cards */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <Card>
                  <CardHeader className="pb-1"><CardTitle className="text-xs font-medium text-muted-foreground flex items-center gap-1"><TrendingUp className="h-3 w-3 text-green-600" /> Total Revenue</CardTitle></CardHeader>
                  <CardContent><p className="text-2xl font-bold text-green-700">{fmt(plData.summary.total_revenue)}</p></CardContent>
                </Card>
                <Card>
                  <CardHeader className="pb-1"><CardTitle className="text-xs font-medium text-muted-foreground flex items-center gap-1"><TrendingDown className="h-3 w-3 text-red-500" /> Total Purchases</CardTitle></CardHeader>
                  <CardContent><p className="text-2xl font-bold text-red-600">{fmt(plData.summary.total_cogs)}</p></CardContent>
                </Card>
                <Card>
                  <CardHeader className="pb-1"><CardTitle className="text-xs font-medium text-muted-foreground">Gross Profit</CardTitle></CardHeader>
                  <CardContent><p className={`text-2xl font-bold ${plData.summary.gross_profit >= 0 ? 'text-green-700' : 'text-red-600'}`}>{fmt(plData.summary.gross_profit)}</p></CardContent>
                </Card>
                <Card>
                  <CardHeader className="pb-1"><CardTitle className="text-xs font-medium text-muted-foreground">Margin</CardTitle></CardHeader>
                  <CardContent><p className={`text-2xl font-bold ${plData.summary.margin_pct >= 0 ? 'text-green-700' : 'text-red-600'}`}>{plData.summary.margin_pct.toFixed(1)}%</p></CardContent>
                </Card>
              </div>

              {/* Monthly breakdown */}
              <Card>
                <CardHeader className="pb-2"><CardTitle className="text-sm">Monthly Breakdown</CardTitle></CardHeader>
                <CardContent className="p-0">
                  <table className="w-full text-sm">
                    <thead><tr className="border-b bg-muted/50">
                      <th className="px-3 py-2 text-left font-medium text-muted-foreground">Month</th>
                      <th className="px-3 py-2 text-right font-medium text-muted-foreground">Revenue</th>
                      <th className="px-3 py-2 text-right font-medium text-muted-foreground">Purchases</th>
                      <th className="px-3 py-2 text-right font-medium text-muted-foreground">Gross Profit</th>
                      <th className="px-3 py-2 text-right font-medium text-muted-foreground">Margin</th>
                      <th className="px-3 py-2 text-center font-medium text-muted-foreground">Invoices</th>
                    </tr></thead>
                    <tbody>
                      {plData.monthly.map((r, i) => (
                        <tr key={i} className="border-b hover:bg-muted/20">
                          <td className="px-3 py-2 font-medium">{r.label}</td>
                          <td className="px-3 py-2 text-right text-green-700 font-medium">{fmt(r.revenue)}</td>
                          <td className="px-3 py-2 text-right text-red-600">{fmt(r.cogs)}</td>
                          <td className={`px-3 py-2 text-right font-semibold ${r.gross_profit >= 0 ? 'text-green-700' : 'text-red-600'}`}>{fmt(r.gross_profit)}</td>
                          <td className={`px-3 py-2 text-right text-sm ${r.margin_pct >= 0 ? 'text-green-700' : 'text-red-600'}`}>{r.margin_pct.toFixed(1)}%</td>
                          <td className="px-3 py-2 text-center text-xs text-muted-foreground">{r.sale_count}S / {r.purchase_count}P</td>
                        </tr>
                      ))}
                      <tr className="bg-muted/30 font-bold border-t-2">
                        <td className="px-3 py-2">Total</td>
                        <td className="px-3 py-2 text-right text-green-700">{fmt(plData.summary.total_revenue)}</td>
                        <td className="px-3 py-2 text-right text-red-600">{fmt(plData.summary.total_cogs)}</td>
                        <td className={`px-3 py-2 text-right ${plData.summary.gross_profit >= 0 ? 'text-green-700' : 'text-red-600'}`}>{fmt(plData.summary.gross_profit)}</td>
                        <td className={`px-3 py-2 text-right ${plData.summary.margin_pct >= 0 ? 'text-green-700' : 'text-red-600'}`}>{plData.summary.margin_pct.toFixed(1)}%</td>
                        <td />
                      </tr>
                    </tbody>
                  </table>
                  {plData.monthly.length === 0 && <div className="py-12 text-center text-muted-foreground text-sm">No finalized invoices in this period.</div>}
                </CardContent>
              </Card>
            </div>
          )}
        </TabsContent>

        {/* ── Stock Summary ── */}
        <TabsContent value="stock" className="mt-4 space-y-4">
          <DatePresetChips onSelect={(f, t) => { setStFrom(f); setStTo(t); }} />
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-1"><Label className="text-xs">From</Label><Input type="date" className="w-36" value={stFrom} onChange={e => setStFrom(e.target.value)} /></div>
            <div className="space-y-1"><Label className="text-xs">To</Label><Input type="date" className="w-36" value={stTo} onChange={e => setStTo(e.target.value)} /></div>
            <Button onClick={fetchStock} disabled={stLoading}><Search className="mr-2 h-4 w-4" />{stLoading ? 'Loading…' : 'Generate'}</Button>
            {stData && stData.items.length > 0 && (
              <Button variant="outline" onClick={() => downloadCSV(`stock-summary-${stFrom}-${stTo}.csv`, ['Product', 'HSN', 'Unit', 'Rate', 'Qty Purchased', 'Value Purchased', 'Qty Sold', 'Value Sold', 'Closing Qty', 'Closing Value'], stData.items.map(r => [r.product_name, r.hsn_code, r.unit, r.rate, r.qty_purchased, r.value_purchased, r.qty_sold, r.value_sold, r.closing_qty, r.closing_value]))}>
                <Download className="mr-2 h-4 w-4" /> CSV
              </Button>
            )}
          </div>

          {stData && (
            <div className="space-y-4">
              <div className="grid grid-cols-3 gap-4">
                <Card><CardHeader className="pb-1"><CardTitle className="text-xs font-medium text-muted-foreground">Total Purchased</CardTitle></CardHeader><CardContent><p className="text-2xl font-bold">{stData.totals.qty_purchased.toLocaleString('en-IN', { maximumFractionDigits: 3 })}</p><p className="text-xs text-muted-foreground">units</p></CardContent></Card>
                <Card><CardHeader className="pb-1"><CardTitle className="text-xs font-medium text-muted-foreground">Total Sold</CardTitle></CardHeader><CardContent><p className="text-2xl font-bold">{stData.totals.qty_sold.toLocaleString('en-IN', { maximumFractionDigits: 3 })}</p><p className="text-xs text-muted-foreground">units</p></CardContent></Card>
                <Card><CardHeader className="pb-1"><CardTitle className="text-xs font-medium text-muted-foreground">Closing Stock Value</CardTitle></CardHeader><CardContent><p className="text-2xl font-bold">{fmt(stData.totals.closing_value)}</p></CardContent></Card>
              </div>

              <Card>
                <CardHeader className="pb-2"><CardTitle className="text-sm">Product-wise Stock</CardTitle></CardHeader>
                <CardContent className="p-0">
                  <table className="w-full text-sm">
                    <thead><tr className="border-b bg-muted/50">
                      <th className="px-3 py-2 text-left font-medium text-muted-foreground">Product</th>
                      <th className="px-3 py-2 text-left font-medium text-muted-foreground">HSN / Unit</th>
                      <th className="px-3 py-2 text-right font-medium text-muted-foreground">Purchased</th>
                      <th className="px-3 py-2 text-right font-medium text-muted-foreground">Sold</th>
                      <th className="px-3 py-2 text-right font-medium text-muted-foreground">Closing Qty</th>
                      <th className="px-3 py-2 text-right font-medium text-muted-foreground">Closing Value</th>
                    </tr></thead>
                    <tbody>
                      {stData.items.map((r, i) => (
                        <tr key={i} className="border-b hover:bg-muted/20">
                          <td className="px-3 py-2 font-medium">{r.product_name}</td>
                          <td className="px-3 py-2 text-muted-foreground text-xs"><p className="font-mono">{r.hsn_code}</p><p>{r.unit}</p></td>
                          <td className="px-3 py-2 text-right">
                            <p>{r.qty_purchased.toLocaleString('en-IN', { maximumFractionDigits: 3 })}</p>
                            <p className="text-xs text-muted-foreground">{fmt(r.value_purchased)}</p>
                          </td>
                          <td className="px-3 py-2 text-right">
                            <p>{r.qty_sold.toLocaleString('en-IN', { maximumFractionDigits: 3 })}</p>
                            <p className="text-xs text-muted-foreground">{fmt(r.value_sold)}</p>
                          </td>
                          <td className={`px-3 py-2 text-right font-semibold ${r.closing_qty < 0 ? 'text-red-600' : ''}`}>{r.closing_qty.toLocaleString('en-IN', { maximumFractionDigits: 3 })}</td>
                          <td className={`px-3 py-2 text-right font-semibold ${r.closing_value < 0 ? 'text-red-600' : ''}`}>{fmt(r.closing_value)}</td>
                        </tr>
                      ))}
                      {stData.items.length > 0 && (
                        <tr className="bg-muted/30 font-bold border-t-2">
                          <td colSpan={4} className="px-3 py-2">Total ({stData.items.length} products)</td>
                          <td className="px-3 py-2 text-right">{stData.totals.qty_purchased.toLocaleString('en-IN', { maximumFractionDigits: 3 })} in / {stData.totals.qty_sold.toLocaleString('en-IN', { maximumFractionDigits: 3 })} out</td>
                          <td className="px-3 py-2 text-right">{fmt(stData.totals.closing_value)}</td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                  {stData.items.length === 0 && <div className="py-12 text-center text-muted-foreground text-sm">No stock movements found. Add products to invoices to track stock.</div>}
                </CardContent>
              </Card>
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
