/**
 * Sales Partner / Agent dashboard — date-filterable, with daily/weekly/monthly
 * commission trends, earned/paid/due KPIs, invoice drilldown, and payouts.
 *
 *   GET  /api/v1/agents/{id}/report                 (all-time KPIs + drilldown + payouts)
 *   GET  /api/v1/agents/{id}/trend?date_from&date_to&granularity
 *   POST /api/v1/agents/{id}/payouts
 */
import { useEffect, useState, useCallback, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, IndianRupee, Wallet, Scale, Loader2, Plus, Receipt } from 'lucide-react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { DataTable, type ColumnDef } from '@/components/DataTable';
import { AgentPayoutDialog } from '@/components/AgentPayoutDialog';
import api from '@/services/api';
import type { AgentReport, AgentReportInvoice, AgentTrendResponse } from '@/types';
import { commissionLabel } from './AgentsPage';

const INR = (v: number) => '₹' + Number(v ?? 0).toLocaleString('en-IN', { minimumFractionDigits: 2 });
const INR0 = (v: number) => '₹' + Number(v ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 0 });
const fmtDate = (s: string | null | undefined) =>
  s ? new Date(s).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }) : '—';

const today = () => new Date().toISOString().slice(0, 10);
const daysAgo = (n: number) => { const d = new Date(); d.setDate(d.getDate() - n); return d.toISOString().slice(0, 10); };
const monthStart = () => { const d = new Date(); d.setDate(1); return d.toISOString().slice(0, 10); };
const fyStart = () => { const d = new Date(); const y = d.getMonth() >= 3 ? d.getFullYear() : d.getFullYear() - 1; return `${y}-04-01`; };

type Gran = 'day' | 'week' | 'month';
const EARN = '#3b82f6';   // blue
const PAID = '#10b981';   // emerald

export default function AgentReportPage() {
  const { id = '' } = useParams();
  const nav = useNavigate();
  const [report, setReport] = useState<AgentReport | null>(null);
  const [trend, setTrend] = useState<AgentTrendResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [payoutOpen, setPayoutOpen] = useState(false);
  const [from, setFrom] = useState(fyStart());
  const [to, setTo] = useState(today());
  const [gran, setGran] = useState<Gran>('month');

  const loadReport = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    try {
      const { data } = await api.get<AgentReport>(`/api/v1/agents/${id}/report`);
      setReport(data);
    } catch { setReport(null); } finally { setLoading(false); }
  }, [id]);

  const loadTrend = useCallback(async () => {
    if (!id) return;
    try {
      const { data } = await api.get<AgentTrendResponse>(`/api/v1/agents/${id}/trend`, {
        params: { date_from: from, date_to: to, granularity: gran },
      });
      setTrend(data);
    } catch { setTrend(null); }
  }, [id, from, to, gran]);

  useEffect(() => { loadReport(); }, [loadReport]);
  useEffect(() => { loadTrend(); }, [loadTrend]);

  const rangeTotals = trend?.totals ?? { earned: 0, paid: 0, invoice_count: 0 };

  const invColumns = useMemo<ColumnDef<AgentReportInvoice>[]>(() => [
    { key: 'invoice_no', label: 'Invoice', accessor: r => r.invoice_no ?? '—' },
    { key: 'invoice_date', label: 'Date', type: 'date', accessor: r => r.invoice_date, format: v => fmtDate(String(v)) },
    { key: 'party_name', label: 'Customer', accessor: r => r.party_name ?? '—' },
    { key: 'net_weight_mt', label: 'Net (MT)', type: 'number', align: 'right', accessor: r => r.net_weight_mt, format: v => Number(v).toFixed(3) },
    { key: 'grand_total', label: 'Bill Total', type: 'number', align: 'right', accessor: r => r.grand_total, format: v => INR(Number(v)), exportValue: r => r.grand_total },
    { key: 'commission_amount', label: 'Commission', type: 'number', align: 'right', accessor: r => r.commission_amount, format: v => <span className="font-semibold text-blue-600">{INR(Number(v))}</span>, exportValue: r => r.commission_amount },
  ], []);

  if (loading && !report) {
    return <div className="flex items-center justify-center py-24 text-muted-foreground"><Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading…</div>;
  }
  if (!report) {
    return (
      <div className="py-16 text-center">
        <p className="text-sm text-muted-foreground">Sales partner not found.</p>
        <Button variant="outline" className="mt-4" onClick={() => nav('/agents')}><ArrowLeft className="mr-2 h-4 w-4" /> Back</Button>
      </div>
    );
  }
  const a = report.agent;

  const PRESETS: { label: string; f: () => void }[] = [
    { label: 'This month', f: () => { setFrom(monthStart()); setTo(today()); setGran('day'); } },
    { label: 'Last 30d', f: () => { setFrom(daysAgo(30)); setTo(today()); setGran('day'); } },
    { label: 'Last 90d', f: () => { setFrom(daysAgo(90)); setTo(today()); setGran('week'); } },
    { label: 'This FY', f: () => { setFrom(fyStart()); setTo(today()); setGran('month'); } },
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="flex items-start gap-3">
          <Button variant="ghost" size="icon" onClick={() => nav('/agents')} title="Back"><ArrowLeft className="h-4 w-4" /></Button>
          <div>
            <h1 className="text-xl font-bold text-slate-900">{a.name}</h1>
            <p className="text-xs text-muted-foreground">
              Sales Partner / Agent · {commissionLabel(a.commission_type, a.commission_rate)}{a.phone ? ` · ${a.phone}` : ''}
            </p>
          </div>
        </div>
        <Button size="sm" onClick={() => setPayoutOpen(true)}><Plus className="mr-1.5 h-4 w-4" /> Record payout</Button>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-end gap-2">
        {PRESETS.map(p => <Button key={p.label} variant="outline" size="sm" className="h-8 text-xs" onClick={p.f}>{p.label}</Button>)}
        <Input type="date" value={from} onChange={e => setFrom(e.target.value)} className="h-8 w-36 text-xs" />
        <span className="text-muted-foreground text-xs pb-2">→</span>
        <Input type="date" value={to} onChange={e => setTo(e.target.value)} className="h-8 w-36 text-xs" />
        <div className="flex gap-0.5 rounded-lg border p-0.5 ml-auto">
          {(['day', 'week', 'month'] as Gran[]).map(g => (
            <Button key={g} size="sm" variant={gran === g ? 'default' : 'ghost'} className="h-7 px-2.5 text-xs capitalize" onClick={() => setGran(g)}>{g}</Button>
          ))}
        </div>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <div className="rounded-xl border bg-gradient-to-br from-rose-50 to-white p-4">
          <div className="flex items-center gap-2 text-rose-600"><Scale className="h-4 w-4" /><span className="text-xs font-medium">Due (all-time)</span></div>
          <p className="mt-1 text-2xl font-bold text-rose-700">{INR0(report.due)}</p>
          <p className="text-[10px] text-muted-foreground">earned {INR0(report.earned)} · paid {INR0(report.paid)}</p>
        </div>
        <div className="rounded-xl border bg-gradient-to-br from-blue-50 to-white p-4">
          <div className="flex items-center gap-2 text-blue-600"><IndianRupee className="h-4 w-4" /><span className="text-xs font-medium">Earned (range)</span></div>
          <p className="mt-1 text-2xl font-bold text-blue-700">{INR0(rangeTotals.earned)}</p>
        </div>
        <div className="rounded-xl border bg-gradient-to-br from-emerald-50 to-white p-4">
          <div className="flex items-center gap-2 text-emerald-600"><Wallet className="h-4 w-4" /><span className="text-xs font-medium">Paid (range)</span></div>
          <p className="mt-1 text-2xl font-bold text-emerald-700">{INR0(rangeTotals.paid)}</p>
        </div>
        <div className="rounded-xl border bg-gradient-to-br from-slate-50 to-white p-4">
          <div className="flex items-center gap-2 text-slate-600"><Receipt className="h-4 w-4" /><span className="text-xs font-medium">Bills (range)</span></div>
          <p className="mt-1 text-2xl font-bold text-slate-700">{rangeTotals.invoice_count}</p>
        </div>
      </div>

      {/* Trend */}
      <Card><CardContent className="p-4">
        <p className="mb-2 text-sm font-medium">Commission trend — earned vs paid <span className="text-muted-foreground">({gran})</span></p>
        {trend && trend.series.length > 0 ? (
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={trend.series} margin={{ top: 8, right: 8, left: 8, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} opacity={0.4} />
              <XAxis dataKey="label" tick={{ fontSize: 11 }} interval="preserveStartEnd" />
              <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => INR0(Number(v))} width={64} />
              <Tooltip formatter={(v: number, n) => [INR(Number(v)), n === 'earned' ? 'Earned' : 'Paid']} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="earned" name="Earned" fill={EARN} radius={[3, 3, 0, 0]} />
              <Bar dataKey="paid" name="Paid" fill={PAID} radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <div className="py-16 text-center text-sm text-muted-foreground">No commission in this range</div>
        )}
      </CardContent></Card>

      {/* Drilldown */}
      <div>
        <p className="mb-2 text-sm font-medium">Commission-earning invoices (all-time)</p>
        <DataTable<AgentReportInvoice>
          id="agent.report.invoices" data={report.invoices} columns={invColumns} rowKey={r => r.invoice_id}
          exportFilename={`agent-${a.name}-commission`} defaultSort={{ key: 'invoice_date', direction: 'desc' }}
          emptyMessage="No commission-earning invoices yet" />
      </div>

      {report.payouts.length > 0 && (
        <div>
          <p className="mb-2 text-sm font-medium">Payouts</p>
          <Card><CardContent className="p-0"><div className="divide-y">
            {report.payouts.map(p => (
              <div key={p.id} className="flex items-center justify-between px-4 py-2 text-sm">
                <div><span className="font-medium">{INR(p.amount)}</span>
                  <span className="ml-2 text-xs text-muted-foreground">{fmtDate(p.paid_on)} · {(p.payment_mode ?? '').replace(/_/g, ' ')}</span></div>
                <span className="text-xs text-muted-foreground">{p.reference_no ?? ''}</span>
              </div>
            ))}
          </div></CardContent></Card>
        </div>
      )}

      <AgentPayoutDialog open={payoutOpen} agentId={a.id} agentName={a.name} due={report.due}
        onClose={() => setPayoutOpen(false)} onSaved={() => { loadReport(); loadTrend(); }} />
    </div>
  );
}
