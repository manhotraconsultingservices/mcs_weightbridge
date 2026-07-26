import { useState, useEffect, useCallback } from 'react';
import { MobileTabSelect } from '@/components/MobileTabSelect';
import { Search, TrendingUp, TrendingDown } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { DataTable, type ColumnDef } from '@/components/DataTable';
import api from '@/services/api';

const fmt = (n: number) => '₹' + n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtWt = (n: number | null) => n == null ? '—' : n.toLocaleString('en-IN', { minimumFractionDigits: 3, maximumFractionDigits: 3 });
const today = () => new Date().toISOString().slice(0, 10);
const monthStart = () => { const d = new Date(); d.setDate(1); return d.toISOString().slice(0, 10); };
const yearStart = () => { const d = new Date(); return `${d.getFullYear()}-04-01`; };

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

// ── Types ─────────────────────────────────────────────────────────────────────

interface SalesRow { id: string; invoice_no: string; invoice_date: string; party_name: string; gstin: string | null; vehicle_no: string | null; net_weight: number | null; taxable_amount: number; cgst_amount: number; sgst_amount: number; igst_amount: number; grand_total: number; payment_status: string; }
interface SalesTotals { taxable_amount: number; cgst: number; sgst: number; igst: number; grand_total: number; }
interface SalesRegister { items: SalesRow[]; totals: SalesTotals; count: number; }

interface WeightRow { id: string; token_no: number; token_date: string; token_type: string; vehicle_no: string | null; party_name: string | null; product_name: string | null; gross_weight: number | null; tare_weight: number | null; net_weight: number | null; is_manual_weight: boolean; }
interface WeightRegister { items: WeightRow[]; total_net_weight: number; count: number; }

interface PLMonth { month: string; label: string; revenue: number; cogs: number; gross_profit: number; labour: number; store_inventory: number; fuel: number; commission: number; overhead?: number; write_off: number; operating_expenses: number; total_expenses: number; net_profit: number; margin_pct: number; sale_count: number; purchase_count: number; }
interface PLData { period: string; summary: { total_revenue: number; total_cogs: number; purchases?: number; opening_stock?: number | null; closing_stock?: number | null; stock_adjustment?: number; stock_adjusted?: boolean; gross_profit: number; labour: number; store_inventory: number; fuel: number; commission: number; overhead?: number; total_write_off: number; operating_expenses: number; total_expenses: number; net_profit: number; margin_pct: number; }; monthly: PLMonth[]; notes?: string[]; }

interface StockItem { product_name: string; hsn_code: string; unit: string; rate: number; qty_purchased: number; value_purchased: number; qty_sold: number; value_sold: number; closing_qty: number; closing_value: number; }
interface StockData { period: string; items: StockItem[]; totals: { qty_purchased_by_unit: Record<string, number>; qty_sold_by_unit: Record<string, number>; value_purchased: number; value_sold: number; closing_value: number; }; }

// ── Column definitions ────────────────────────────────────────────────────────

const SALES_COLS: ColumnDef<SalesRow>[] = [
  { key: 'invoice_no',     label: 'Invoice No',    accessor: r => r.invoice_no,
    format: v => <span className="font-mono text-xs font-medium">{String(v ?? '—')}</span> },
  { key: 'invoice_date',   label: 'Date',          accessor: r => r.invoice_date, type: 'date' },
  { key: 'party_name',     label: 'Party',         accessor: r => r.party_name },
  { key: 'gstin',          label: 'GSTIN',         accessor: r => r.gstin ?? '—', defaultVisible: false },
  { key: 'vehicle_no',     label: 'Vehicle',       accessor: r => r.vehicle_no ?? '—' },
  { key: 'net_weight',     label: 'Net Wt (MT)',   accessor: r => r.net_weight, type: 'number', align: 'right',
    format: v => fmtWt(v as number | null), exportValue: r => r.net_weight ?? '' },
  { key: 'taxable_amount', label: 'Taxable',       accessor: r => r.taxable_amount, type: 'number', align: 'right',
    format: v => fmt(v as number), exportValue: r => r.taxable_amount },
  { key: 'cgst_amount',    label: 'CGST',          accessor: r => r.cgst_amount, type: 'number', align: 'right',
    format: v => fmt(v as number), defaultVisible: false, exportValue: r => r.cgst_amount },
  { key: 'sgst_amount',    label: 'SGST',          accessor: r => r.sgst_amount, type: 'number', align: 'right',
    format: v => fmt(v as number), defaultVisible: false, exportValue: r => r.sgst_amount },
  { key: 'igst_amount',    label: 'IGST',          accessor: r => r.igst_amount, type: 'number', align: 'right',
    format: v => fmt(v as number), defaultVisible: false, exportValue: r => r.igst_amount },
  { key: 'gst_total',      label: 'GST',           accessor: r => r.cgst_amount + r.sgst_amount + r.igst_amount, type: 'number', align: 'right',
    format: v => fmt(v as number), exportValue: r => r.cgst_amount + r.sgst_amount + r.igst_amount },
  { key: 'grand_total',    label: 'Total',         accessor: r => r.grand_total, type: 'number', align: 'right',
    format: v => <span className="font-semibold">{fmt(v as number)}</span>, exportValue: r => r.grand_total },
  { key: 'payment_status', label: 'Status',        accessor: r => r.payment_status, type: 'enum',
    enumOptions: ['paid', 'partial', 'unpaid'],
    format: v => {
      const s = String(v);
      return <span className={`text-[10px] px-1.5 py-0.5 rounded capitalize ${s === 'paid' ? 'bg-green-100 text-green-800' : s === 'partial' ? 'bg-yellow-100 text-yellow-800' : 'bg-red-100 text-red-800'}`}>{s}</span>;
    } },
];

const WEIGHT_COLS: ColumnDef<WeightRow>[] = [
  { key: 'token_no',      label: 'Token No',   accessor: r => r.token_no,   type: 'number',
    format: v => <span className="font-medium">#{String(v ?? '')}</span> },
  { key: 'token_date',    label: 'Date',       accessor: r => r.token_date, type: 'date' },
  { key: 'token_type',    label: 'Type',       accessor: r => r.token_type, type: 'enum',
    enumOptions: ['sale', 'purchase', 'general'] },
  { key: 'vehicle_no',    label: 'Vehicle',    accessor: r => r.vehicle_no ?? '—' },
  { key: 'party_name',    label: 'Party',      accessor: r => r.party_name ?? '—' },
  { key: 'product_name',  label: 'Product',    accessor: r => r.product_name ?? '—', defaultVisible: false },
  { key: 'gross_weight',  label: 'Gross (MT)', accessor: r => r.gross_weight, type: 'number', align: 'right',
    format: v => fmtWt(v as number | null), exportValue: r => r.gross_weight ?? '' },
  { key: 'tare_weight',   label: 'Tare (MT)',  accessor: r => r.tare_weight,  type: 'number', align: 'right',
    format: v => fmtWt(v as number | null), exportValue: r => r.tare_weight ?? '' },
  { key: 'net_weight',    label: 'Net (MT)',   accessor: r => r.net_weight,   type: 'number', align: 'right',
    format: v => <span className="font-semibold">{fmtWt(v as number | null)}</span>, exportValue: r => r.net_weight ?? '' },
  { key: 'is_manual',     label: 'Manual',     accessor: r => r.is_manual_weight ? 'Yes' : 'No', defaultVisible: false },
];

const PL_COLS: ColumnDef<PLMonth>[] = [
  { key: 'label',          label: 'Month',       accessor: r => r.label },
  { key: 'revenue',        label: 'Revenue',     accessor: r => r.revenue, type: 'number', align: 'right',
    format: v => <span className="text-green-700 font-medium">{fmt(v as number)}</span>, exportValue: r => r.revenue },
  { key: 'cogs',           label: 'Purchases',   accessor: r => r.cogs,    type: 'number', align: 'right',
    format: v => <span className="text-red-600">{fmt(v as number)}</span>, exportValue: r => r.cogs },
  { key: 'gross_profit',   label: 'Gross Profit', accessor: r => r.gross_profit, type: 'number', align: 'right',
    format: v => <span className={`font-semibold ${(v as number) >= 0 ? 'text-green-700' : 'text-red-600'}`}>{fmt(v as number)}</span>, exportValue: r => r.gross_profit },
  { key: 'labour',         label: 'Labour',      accessor: r => r.labour, type: 'number', align: 'right',
    format: v => <span className="text-red-600">{fmt(v as number)}</span>, exportValue: r => r.labour },
  { key: 'store_inventory', label: 'Store',      accessor: r => r.store_inventory, type: 'number', align: 'right',
    format: v => <span className="text-red-600">{fmt(v as number)}</span>, exportValue: r => r.store_inventory, defaultVisible: false },
  { key: 'fuel',           label: 'Fuel',        accessor: r => r.fuel, type: 'number', align: 'right',
    format: v => <span className="text-red-600">{fmt(v as number)}</span>, exportValue: r => r.fuel, defaultVisible: false },
  { key: 'commission',     label: 'Commission',  accessor: r => r.commission, type: 'number', align: 'right',
    format: v => <span className="text-red-600">{fmt(v as number)}</span>, exportValue: r => r.commission, defaultVisible: false },
  { key: 'overhead',       label: 'Overhead',    accessor: r => r.overhead ?? 0, type: 'number', align: 'right',
    format: v => <span className="text-red-600">{fmt(v as number)}</span>, exportValue: r => r.overhead ?? 0, defaultVisible: false },
  { key: 'total_expenses', label: 'Expenses',    accessor: r => r.total_expenses, type: 'number', align: 'right',
    format: v => <span className="text-red-600 font-medium">{fmt(v as number)}</span>, exportValue: r => r.total_expenses },
  { key: 'net_profit',     label: 'Net Profit',  accessor: r => r.net_profit, type: 'number', align: 'right',
    format: v => <span className={`font-semibold ${(v as number) >= 0 ? 'text-green-700' : 'text-red-600'}`}>{fmt(v as number)}</span>, exportValue: r => r.net_profit },
  { key: 'margin_pct',     label: 'Margin %',    accessor: r => r.margin_pct, type: 'number', align: 'right',
    format: v => <span className={(v as number) >= 0 ? 'text-green-700' : 'text-red-600'}>{(v as number).toFixed(1)}%</span>, exportValue: r => r.margin_pct },
  { key: 'sale_count',     label: 'Sales #',     accessor: r => r.sale_count, type: 'number', align: 'right', defaultVisible: false },
  { key: 'purchase_count', label: 'Purchases #', accessor: r => r.purchase_count, type: 'number', align: 'right', defaultVisible: false },
];

const STOCK_COLS: ColumnDef<StockItem>[] = [
  { key: 'product_name',    label: 'Product',         accessor: r => r.product_name },
  { key: 'hsn_code',        label: 'HSN',             accessor: r => r.hsn_code, defaultVisible: false },
  { key: 'unit',            label: 'Unit',            accessor: r => r.unit, defaultVisible: false },
  { key: 'qty_purchased',   label: 'Qty Purchased',   accessor: r => r.qty_purchased, type: 'number', align: 'right',
    format: v => (v as number).toLocaleString('en-IN', { maximumFractionDigits: 3 }) },
  { key: 'value_purchased', label: 'Value Purchased', accessor: r => r.value_purchased, type: 'number', align: 'right',
    format: v => fmt(v as number), exportValue: r => r.value_purchased },
  { key: 'qty_sold',        label: 'Qty Sold',        accessor: r => r.qty_sold, type: 'number', align: 'right',
    format: v => (v as number).toLocaleString('en-IN', { maximumFractionDigits: 3 }) },
  { key: 'value_sold',      label: 'Value Sold',      accessor: r => r.value_sold, type: 'number', align: 'right',
    format: v => fmt(v as number), exportValue: r => r.value_sold },
  { key: 'closing_qty',     label: 'Closing Qty',     accessor: r => r.closing_qty, type: 'number', align: 'right',
    format: v => <span className={`font-semibold ${(v as number) < 0 ? 'text-red-600' : ''}`}>{(v as number).toLocaleString('en-IN', { maximumFractionDigits: 3 })}</span>,
    exportValue: r => r.closing_qty },
  { key: 'closing_value',   label: 'Closing Value',   accessor: r => r.closing_value, type: 'number', align: 'right',
    format: v => <span className={`font-semibold ${(v as number) < 0 ? 'text-red-600' : ''}`}>{fmt(v as number)}</span>,
    exportValue: r => r.closing_value },
];

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
  // F3 — manual opening/closing stock values (₹) for stock-adjusted COGS
  const [openingStock, setOpeningStock] = useState('');
  const [closingStock, setClosingStock] = useState('');
  const [stockValSaving, setStockValSaving] = useState(false);
  const [stockValMsg, setStockValMsg] = useState('');

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

  // Pre-fill saved manual stock values (accountant's CA figures) for the P&L tab
  useEffect(() => {
    api.get<{ opening: number | null; closing: number | null }>('/api/v1/reports/stock-valuation')
      .then(r => {
        if (r.data?.opening != null) setOpeningStock(String(r.data.opening));
        if (r.data?.closing != null) setClosingStock(String(r.data.closing));
      }).catch(() => {});
  }, []);

  async function fetchPL() {
    setPlLoading(true);
    const p = new URLSearchParams({ from_date: plFrom, to_date: plTo });
    if (openingStock.trim() !== '') p.set('opening_stock', openingStock.trim());
    if (closingStock.trim() !== '') p.set('closing_stock', closingStock.trim());
    api.get<PLData>(`/api/v1/reports/profit-loss?${p}`)
      .then(r => setPlData(r.data)).catch(() => setPlData(null)).finally(() => setPlLoading(false));
  }

  async function saveStockVal() {
    setStockValSaving(true); setStockValMsg('');
    try {
      await api.put('/api/v1/reports/stock-valuation', {
        opening: openingStock.trim() === '' ? null : Number(openingStock),
        closing: closingStock.trim() === '' ? null : Number(closingStock),
      });
      setStockValMsg('Saved');
      setTimeout(() => setStockValMsg(''), 2500);
    } catch {
      setStockValMsg('Save failed (accountant/admin only)');
    } finally { setStockValSaving(false); }
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
        <p className="text-muted-foreground">Sales register · Weight register · P&amp;L · Stock summary</p>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <MobileTabSelect value={tab} onValueChange={setTab} options={[{ value: 'sales', label: 'Sales / Purchase Register' }, { value: 'weight', label: 'Weight Register' }, { value: 'pl', label: 'Profit & Loss' }, { value: 'stock', label: 'Stock Summary' }]} />
        <TabsList className="hidden sm:inline-flex">
          <TabsTrigger value="sales">Sales / Purchase Register</TabsTrigger>
          <TabsTrigger value="weight">Weight Register</TabsTrigger>
          <TabsTrigger value="pl">Profit &amp; Loss</TabsTrigger>
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
          </div>
          {salesData && (
            <div className="space-y-3">
              <DataTable<SalesRow>
                id="reports.sales"
                columns={SALES_COLS}
                data={salesData.items}
                loading={salesLoading}
                rowKey={r => r.id}
                exportFilename={`sales-register-${salesFrom}-${salesTo}`}
                defaultSort={{ key: 'invoice_date', direction: 'desc' }}
                emptyMessage="No records found."
              />
              {salesData.items.length > 0 && (
                <div className="flex flex-wrap gap-4 rounded-md border bg-muted/30 px-4 py-2 text-sm">
                  <span className="text-muted-foreground">{salesData.count} invoices</span>
                  <span>Taxable: <strong>{fmt(salesData.totals.taxable_amount)}</strong></span>
                  <span>GST: <strong>{fmt(salesData.totals.cgst + salesData.totals.sgst + salesData.totals.igst)}</strong></span>
                  <span>Total: <strong>{fmt(salesData.totals.grand_total)}</strong></span>
                </div>
              )}
            </div>
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
          </div>
          {wtData && (
            <div className="space-y-3">
              <DataTable<WeightRow>
                id="reports.weight"
                columns={WEIGHT_COLS}
                data={wtData.items}
                loading={wtLoading}
                rowKey={r => r.id}
                exportFilename={`weight-register-${wtFrom}-${wtTo}`}
                emptyMessage="No completed tokens found."
              />
              {wtData.items.length > 0 && (
                <div className="flex flex-wrap gap-4 rounded-md border bg-muted/30 px-4 py-2 text-sm">
                  <span className="text-muted-foreground">{wtData.count} tokens</span>
                  <span>Total Net Weight: <strong>{fmtWt(wtData.total_net_weight)} MT</strong></span>
                </div>
              )}
            </div>
          )}
        </TabsContent>

        {/* ── Profit & Loss ── */}
        <TabsContent value="pl" className="mt-4 space-y-4">
          <DatePresetChips onSelect={(f, t) => { setPlFrom(f); setPlTo(t); }} />
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-1"><Label className="text-xs">From</Label><Input type="date" className="w-36" value={plFrom} onChange={e => setPlFrom(e.target.value)} /></div>
            <div className="space-y-1"><Label className="text-xs">To</Label><Input type="date" className="w-36" value={plTo} onChange={e => setPlTo(e.target.value)} /></div>
            <div className="space-y-1"><Label className="text-xs">Opening stock ₹</Label><Input type="number" min="0" step="0.01" placeholder="optional" className="w-32" value={openingStock} onChange={e => setOpeningStock(e.target.value)} /></div>
            <div className="space-y-1"><Label className="text-xs">Closing stock ₹</Label><Input type="number" min="0" step="0.01" placeholder="optional" className="w-32" value={closingStock} onChange={e => setClosingStock(e.target.value)} /></div>
            <Button onClick={fetchPL} disabled={plLoading}><Search className="mr-2 h-4 w-4" />{plLoading ? 'Loading…' : 'Generate'}</Button>
            <Button variant="outline" onClick={saveStockVal} disabled={stockValSaving}>{stockValSaving ? 'Saving…' : 'Save stock values'}</Button>
            {stockValMsg && <span className="text-xs text-muted-foreground self-center">{stockValMsg}</span>}
          </div>
          <p className="text-[11px] text-muted-foreground">
            Enter opening &amp; closing stock value (₹, your CA's figures) for a goods-sold COGS = opening + purchases − closing. Leave blank to use purchases-in-period.
          </p>

          {plData && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <Card>
                  <CardHeader className="pb-1"><CardTitle className="text-xs font-medium text-muted-foreground flex items-center gap-1"><TrendingUp className="h-3 w-3 text-green-600" /> Total Revenue</CardTitle></CardHeader>
                  <CardContent><p className="text-2xl font-bold text-green-700">{fmt(plData.summary.total_revenue)}</p></CardContent>
                </Card>
                <Card>
                  <CardHeader className="pb-1"><CardTitle className="text-xs font-medium text-muted-foreground">Gross Profit</CardTitle></CardHeader>
                  <CardContent><p className={`text-2xl font-bold ${plData.summary.gross_profit >= 0 ? 'text-green-700' : 'text-red-600'}`}>{fmt(plData.summary.gross_profit)}</p></CardContent>
                </Card>
                <Card>
                  <CardHeader className="pb-1"><CardTitle className="text-xs font-medium text-muted-foreground flex items-center gap-1"><TrendingDown className="h-3 w-3 text-red-500" /> Total Expenses</CardTitle></CardHeader>
                  <CardContent><p className="text-2xl font-bold text-red-600">{fmt(plData.summary.total_expenses)}</p></CardContent>
                </Card>
                <Card>
                  <CardHeader className="pb-1"><CardTitle className="text-xs font-medium text-muted-foreground">Net Profit</CardTitle></CardHeader>
                  <CardContent><p className={`text-2xl font-bold ${plData.summary.net_profit >= 0 ? 'text-green-700' : 'text-red-600'}`}>{fmt(plData.summary.net_profit)}</p>
                    <p className={`text-xs ${plData.summary.margin_pct >= 0 ? 'text-green-600' : 'text-red-500'}`}>{plData.summary.margin_pct.toFixed(1)}% margin</p></CardContent>
                </Card>
              </div>

              {/* Full P&L statement — every operating expense that reduces profit */}
              <Card>
                <CardHeader className="pb-2"><CardTitle className="text-sm">Profit &amp; Loss Statement</CardTitle></CardHeader>
                <CardContent className="p-0">
                  {(() => {
                    const s = plData.summary;
                    const Row = ({ label, value, kind }: { label: string; value: number; kind?: 'in' | 'out' | 'sub' | 'net' }) => (
                      <div className={`flex justify-between px-4 py-2 text-sm ${kind === 'sub' || kind === 'net' ? 'font-semibold border-t' : ''} ${kind === 'net' ? 'border-t-2 bg-muted/40' : ''}`}>
                        <span className={kind === 'out' ? 'pl-4 text-muted-foreground' : ''}>{label}</span>
                        <span className={kind === 'in' ? 'text-green-700' : kind === 'out' ? 'text-red-600' : (value >= 0 ? 'text-green-700' : 'text-red-600')}>
                          {kind === 'out' ? '− ' : ''}{fmt(Math.abs(value))}
                        </span>
                      </div>
                    );
                    return (
                      <div className="divide-y">
                        <Row label="Revenue (net of credit/debit notes)" value={s.total_revenue} kind="in" />
                        {s.stock_adjusted ? (
                          <>
                            <Row label="Opening stock" value={s.opening_stock ?? 0} kind="in" />
                            <Row label="Purchases in period" value={s.purchases ?? 0} kind="out" />
                            <Row label="Closing stock" value={s.closing_stock ?? 0} kind="in" />
                            <Row label="COGS (goods sold = opening + purchases − closing)" value={s.total_cogs} kind="out" />
                          </>
                        ) : (
                          <Row label="Purchases (COGS)" value={s.total_cogs} kind="out" />
                        )}
                        <Row label="Gross Profit" value={s.gross_profit} kind="sub" />
                        <Row label="Labour (wages + salary)" value={s.labour} kind="out" />
                        <Row label="Store inventory (purchased)" value={s.store_inventory} kind="out" />
                        <Row label="Fuel / diesel" value={s.fuel} kind="out" />
                        <Row label="Agent commission" value={s.commission} kind="out" />
                        <Row label="Overhead expenses" value={s.overhead ?? 0} kind="out" />
                        <Row label="Bad-debt write-offs" value={s.total_write_off} kind="out" />
                        <Row label="Total operating expenses" value={s.total_expenses} kind="sub" />
                        <Row label="Net Profit" value={s.net_profit} kind="net" />
                      </div>
                    );
                  })()}
                </CardContent>
              </Card>

              {plData.notes && plData.notes.length > 0 && (
                <div className="rounded-md border bg-muted/30 px-4 py-3 space-y-1">
                  {plData.notes.map((n, i) => (
                    <p key={i} className="text-[11px] text-muted-foreground">• {n}</p>
                  ))}
                </div>
              )}

              <Card>
                <CardHeader className="pb-2"><CardTitle className="text-sm">Monthly Breakdown</CardTitle></CardHeader>
                <CardContent className="p-0">
                  <DataTable<PLMonth>
                    id="reports.pl"
                    columns={PL_COLS}
                    data={plData.monthly}
                    rowKey={(_, i) => String(i)}
                    exportFilename={`pl-report-${plFrom}-${plTo}`}
                    emptyMessage="No finalized invoices in this period."
                  />
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
          </div>

          {stData && (
            <div className="space-y-4">
              <div className="grid grid-cols-3 gap-4">
                <Card>
                  <CardHeader className="pb-1"><CardTitle className="text-xs font-medium text-muted-foreground">Total Purchase Value</CardTitle></CardHeader>
                  <CardContent>
                    <p className="text-2xl font-bold">{fmt(stData.totals.value_purchased)}</p>
                    <p className="text-xs text-muted-foreground">{Object.entries(stData.totals.qty_purchased_by_unit).map(([u, q]) => `${q.toLocaleString('en-IN', { maximumFractionDigits: 3 })} ${u}`).join(' · ') || '—'}</p>
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader className="pb-1"><CardTitle className="text-xs font-medium text-muted-foreground">Total Sales Value</CardTitle></CardHeader>
                  <CardContent>
                    <p className="text-2xl font-bold">{fmt(stData.totals.value_sold)}</p>
                    <p className="text-xs text-muted-foreground">{Object.entries(stData.totals.qty_sold_by_unit).map(([u, q]) => `${q.toLocaleString('en-IN', { maximumFractionDigits: 3 })} ${u}`).join(' · ') || '—'}</p>
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader className="pb-1"><CardTitle className="text-xs font-medium text-muted-foreground">Closing Stock Value</CardTitle></CardHeader>
                  <CardContent><p className="text-2xl font-bold">{fmt(stData.totals.closing_value)}</p></CardContent>
                </Card>
              </div>

              <Card>
                <CardHeader className="pb-2"><CardTitle className="text-sm">Product-wise Stock</CardTitle></CardHeader>
                <CardContent className="p-0">
                  <DataTable<StockItem>
                    id="reports.stock"
                    columns={STOCK_COLS}
                    data={stData.items}
                    rowKey={(_, i) => String(i)}
                    exportFilename={`stock-summary-${stFrom}-${stTo}`}
                    emptyMessage="No stock movements found. Add products to invoices to track stock."
                  />
                </CardContent>
              </Card>
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
