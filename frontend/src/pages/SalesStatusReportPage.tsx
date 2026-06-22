import { useEffect, useState, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import api from '@/services/api';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  PieChart, Pie, Cell,
} from 'recharts';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Loader2, FileText, CheckCircle2, Layers, Download } from 'lucide-react';

interface StatusBucket { count: number; amount: number }
interface Series { period: string; label: string; draft: number; final: number; total: number }
interface Result {
  granularity: string;
  summary: { draft: StatusBucket; final: StatusBucket; cancelled: StatusBucket; total_count: number; total_amount: number };
  series: Series[];
}

const INR = (v: number) => '₹' + Number(v ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 0 });
const INR2 = (v: number) => '₹' + Number(v ?? 0).toLocaleString('en-IN', { minimumFractionDigits: 2 });
const today = () => new Date().toISOString().slice(0, 10);
const daysAgo = (n: number) => { const d = new Date(); d.setDate(d.getDate() - n); return d.toISOString().slice(0, 10); };
const monthStart = () => { const d = new Date(); d.setDate(1); return d.toISOString().slice(0, 10); };

const DRAFT_COLOR = '#f59e0b';   // amber
const FINAL_COLOR = '#10b981';   // emerald

type TaxFilter = 'all' | 'gst' | 'non_gst';
const TAX_FILTERS: { value: TaxFilter; label: string }[] = [
  { value: 'all',     label: 'All' },
  { value: 'gst',     label: 'INV (GST)' },
  { value: 'non_gst', label: 'CINV (Cash)' },
];

export default function SalesStatusReportPage() {
  const { t } = useTranslation();
  const [range, setRange] = useState({ from: monthStart(), to: today() });
  const [gran, setGran] = useState<'day' | 'week' | 'month'>('day');
  const [taxFilter, setTaxFilter] = useState<TaxFilter>('all');
  const [res, setRes] = useState<Result | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string> = { from_date: range.from, to_date: range.to, granularity: gran };
      if (taxFilter !== 'all') params.tax_type = taxFilter;
      const r = await api.get<Result>('/api/v1/reports/sales-by-status', { params });
      setRes(r.data);
    } catch { /* inline */ } finally { setLoading(false); }
  }, [range.from, range.to, gran, taxFilter]);

  useEffect(() => { load(); }, [load]);

  function preset(from: string) { setRange({ from, to: today() }); }

  function exportCsv() {
    if (!res) return;
    const rows = [['Period', 'Draft (₹)', 'Final/Complete (₹)', 'Total (₹)']];
    res.series.forEach(s => rows.push([s.label, String(s.draft), String(s.final), String(s.total)]));
    const csv = rows.map(r => r.map(c => `"${c}"`).join(',')).join('\n');
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
    const a = document.createElement('a');
    a.href = url; a.download = `sales-by-status_${range.from}_${range.to}.csv`; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  }

  const pieData = res ? [
    { name: 'Draft', value: res.summary.draft.amount, color: DRAFT_COLOR },
    { name: 'Final / Complete', value: res.summary.final.amount, color: FINAL_COLOR },
  ].filter(d => d.value > 0) : [];

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-xl font-bold">{t('salesStatus.title')}</h1>
          <p className="text-xs text-muted-foreground">{t('salesStatus.subtitle')}</p>
        </div>
        <Button variant="outline" size="sm" onClick={exportCsv} disabled={!res?.series.length} className="gap-1.5"><Download className="h-3.5 w-3.5" /> CSV</Button>
      </div>

      {/* Controls */}
      <div className="rounded-lg border p-3 flex flex-wrap items-end gap-3">
        <div className="space-y-1"><Label className="text-xs">From</Label><Input type="date" className="h-9 w-40 text-xs" value={range.from} onChange={e => setRange(r => ({ ...r, from: e.target.value }))} /></div>
        <div className="space-y-1"><Label className="text-xs">To</Label><Input type="date" className="h-9 w-40 text-xs" value={range.to} onChange={e => setRange(r => ({ ...r, to: e.target.value }))} /></div>
        <div className="flex gap-1">
          <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => preset(monthStart())}>This month</Button>
          <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => preset(daysAgo(30))}>30 days</Button>
          <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => preset(daysAgo(90))}>90 days</Button>
        </div>
        <div className="flex gap-1">
          {TAX_FILTERS.map(f => (
            <Button key={f.value} variant={taxFilter === f.value ? 'default' : 'outline'} size="sm" className="h-7 text-xs" onClick={() => setTaxFilter(f.value)}>{f.label}</Button>
          ))}
        </div>
        <div className="flex gap-1 ml-auto">
          {(['day', 'week', 'month'] as const).map(g => (
            <Button key={g} variant={gran === g ? 'default' : 'outline'} size="sm" className="h-7 text-xs capitalize" onClick={() => setGran(g)}>
              {g === 'day' ? t('salesStatus.granularityDay') : g === 'week' ? t('salesStatus.granularityWeek') : t('salesStatus.granularityMonth')}
            </Button>
          ))}
        </div>
      </div>

      {loading && <div className="py-10 text-center text-muted-foreground"><Loader2 className="inline h-5 w-5 animate-spin" /> Loading…</div>}

      {res && !loading && (
        <>
          {/* KPI cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div className="rounded-lg border p-3 bg-amber-50 border-amber-200">
              <p className="text-[11px] text-muted-foreground flex items-center gap-1"><FileText className="h-3.5 w-3.5" /> {t('salesStatus.draftAmount')}</p>
              <p className="text-lg font-bold text-amber-700">{INR(res.summary.draft.amount)}</p>
              <p className="text-[10px] text-muted-foreground">{res.summary.draft.count} invoice(s)</p>
            </div>
            <div className="rounded-lg border p-3 bg-emerald-50 border-emerald-200">
              <p className="text-[11px] text-muted-foreground flex items-center gap-1"><CheckCircle2 className="h-3.5 w-3.5" /> {t('salesStatus.finalAmount')}</p>
              <p className="text-lg font-bold text-emerald-700">{INR(res.summary.final.amount)}</p>
              <p className="text-[10px] text-muted-foreground">{res.summary.final.count} invoice(s)</p>
            </div>
            <div className="rounded-lg border p-3">
              <p className="text-[11px] text-muted-foreground flex items-center gap-1"><Layers className="h-3.5 w-3.5" /> {t('salesStatus.totalAmount')}</p>
              <p className="text-lg font-bold">{INR(res.summary.total_amount)}</p>
              <p className="text-[10px] text-muted-foreground">{res.summary.total_count} invoice(s)</p>
            </div>
            <div className="rounded-lg border p-3">
              <p className="text-[11px] text-muted-foreground">{t('salesStatus.draftShare')}</p>
              <p className="text-lg font-bold">{res.summary.total_amount > 0 ? Math.round(res.summary.draft.amount / res.summary.total_amount * 100) : 0}%</p>
              <p className="text-[10px] text-muted-foreground">of total billed value</p>
            </div>
          </div>

          {/* Charts */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
            <div className="lg:col-span-2 rounded-lg border p-4">
              <p className="text-sm font-semibold mb-3">Sales amount by status — per {res.granularity}</p>
              {res.series.length === 0 ? (
                <p className="py-16 text-center text-sm text-muted-foreground">No sale invoices in this range.</p>
              ) : (
                <ResponsiveContainer width="100%" height={320}>
                  <BarChart data={res.series} margin={{ top: 4, right: 8, left: 8, bottom: 4 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="label" tick={{ fontSize: 11 }} />
                    <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => '₹' + (v / 1000).toFixed(0) + 'k'} />
                    <Tooltip formatter={(v: number) => INR2(v)} />
                    <Legend />
                    <Bar dataKey="draft" name="Draft" stackId="s" fill={DRAFT_COLOR} radius={[0, 0, 0, 0]} />
                    <Bar dataKey="final" name="Final / Complete" stackId="s" fill={FINAL_COLOR} radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>
            <div className="rounded-lg border p-4">
              <p className="text-sm font-semibold mb-3">Draft vs Complete share</p>
              {pieData.length === 0 ? (
                <p className="py-16 text-center text-sm text-muted-foreground">No data.</p>
              ) : (
                <ResponsiveContainer width="100%" height={320}>
                  <PieChart>
                    <Pie data={pieData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={100} label={(e: { name: string; percent?: number }) => `${e.name}: ${Math.round((e.percent ?? 0) * 100)}%`}>
                      {pieData.map((d, i) => <Cell key={i} fill={d.color} />)}
                    </Pie>
                    <Tooltip formatter={(v: number) => INR2(v)} />
                  </PieChart>
                </ResponsiveContainer>
              )}
            </div>
          </div>

          {res.summary.cancelled.count > 0 && (
            <p className="text-xs text-muted-foreground">Note: {res.summary.cancelled.count} cancelled invoice(s) worth {INR(res.summary.cancelled.amount)} are excluded from the chart.</p>
          )}
        </>
      )}
    </div>
  );
}
