/**
 * Agents (brokers / dalals) master + commission summary.
 *
 * Lists agents with their commission config + earned/paid/due (merged from
 * /agents/report-summary). Create/edit dialog. Per-row → /agents/:id report card.
 */
import { useEffect, useState, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { Plus, Pencil, FileBarChart, Loader2, Handshake, Wallet } from 'lucide-react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { DataTable, type ColumnDef } from '@/components/DataTable';
import { AgentPayoutDialog } from '@/components/AgentPayoutDialog';
import api from '@/services/api';
import type { Agent, AgentSummaryRow, CommissionType, AgentTrendResponse } from '@/types';

const INR = (v: number) => '₹' + Number(v ?? 0).toLocaleString('en-IN', { minimumFractionDigits: 2 });
const INR0 = (v: number) => '₹' + Number(v ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 0 });
const today = () => new Date().toISOString().slice(0, 10);
const daysAgo = (n: number) => { const d = new Date(); d.setDate(d.getDate() - n); return d.toISOString().slice(0, 10); };
const monthStart = () => { const d = new Date(); d.setDate(1); return d.toISOString().slice(0, 10); };
const fyStart = () => { const d = new Date(); const y = d.getMonth() >= 3 ? d.getFullYear() : d.getFullYear() - 1; return `${y}-04-01`; };
type Gran = 'day' | 'week' | 'month';

export const COMMISSION_TYPES: { value: CommissionType; label: string; unit: string }[] = [
  { value: 'per_mt', label: 'Per tonne (₹/MT)', unit: '₹ per MT' },
  { value: 'pct_of_taxable', label: '% of taxable value', unit: '% of taxable' },
  { value: 'pct_of_grand_total', label: '% of grand total', unit: '% of total' },
  { value: 'flat_per_invoice', label: 'Flat per invoice', unit: '₹ per invoice' },
];

export function commissionLabel(type: CommissionType, rate: number): string {
  switch (type) {
    case 'per_mt': return `₹${rate}/MT`;
    case 'pct_of_taxable': return `${rate}% of taxable`;
    case 'pct_of_grand_total': return `${rate}% of total`;
    case 'flat_per_invoice': return `₹${rate}/invoice`;
    default: return String(rate);
  }
}

interface Row extends Agent {
  earned: number;
  paid: number;
  due: number;
  invoice_count: number;
}

function AgentDialog({ open, agent, onClose, onSaved }: {
  open: boolean; agent: Agent | null; onClose: () => void; onSaved: () => void;
}) {
  const [form, setForm] = useState({
    name: '', phone: '', gstin: '', pan: '', address: '',
    commission_type: 'pct_of_taxable' as CommissionType, commission_rate: '0', notes: '',
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (open) {
      setError('');
      setForm(agent ? {
        name: agent.name, phone: agent.phone ?? '', gstin: agent.gstin ?? '', pan: agent.pan ?? '',
        address: agent.address ?? '', commission_type: agent.commission_type,
        commission_rate: String(agent.commission_rate ?? 0), notes: agent.notes ?? '',
      } : { name: '', phone: '', gstin: '', pan: '', address: '', commission_type: 'pct_of_taxable', commission_rate: '0', notes: '' });
    }
  }, [open, agent]);

  async function save() {
    if (!form.name.trim()) { setError('Name is required'); return; }
    setSaving(true); setError('');
    try {
      const body = {
        name: form.name.trim(), phone: form.phone || null, gstin: form.gstin || null,
        pan: form.pan || null, address: form.address || null,
        commission_type: form.commission_type, commission_rate: parseFloat(form.commission_rate) || 0,
        notes: form.notes || null,
      };
      if (agent) await api.put(`/api/v1/agents/${agent.id}`, body);
      else await api.post('/api/v1/agents', body);
      onSaved(); onClose();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Failed to save agent');
    } finally { setSaving(false); }
  }

  const unit = COMMISSION_TYPES.find(c => c.value === form.commission_type)?.unit ?? '';

  return (
    <Dialog open={open} onOpenChange={v => !v && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader><DialogTitle>{agent ? 'Edit Sales Partner' : 'New Sales Partner'}</DialogTitle></DialogHeader>
        <div className="space-y-3">
          {error && <p className="rounded bg-destructive/10 p-2 text-sm text-destructive">{error}</p>}
          <div className="space-y-1"><Label>Name *</Label>
            <Input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} /></div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1"><Label>Phone</Label>
              <Input value={form.phone} onChange={e => setForm(f => ({ ...f, phone: e.target.value }))} /></div>
            <div className="space-y-1"><Label>GSTIN</Label>
              <Input value={form.gstin} onChange={e => setForm(f => ({ ...f, gstin: e.target.value }))} /></div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1"><Label>Commission basis</Label>
              <Select value={form.commission_type} onValueChange={v => setForm(f => ({ ...f, commission_type: (v ?? 'pct_of_taxable') as CommissionType }))}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {COMMISSION_TYPES.map(c => <SelectItem key={c.value} value={c.value}>{c.label}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1"><Label>Rate ({unit})</Label>
              <Input type="number" step="0.001" value={form.commission_rate}
                onChange={e => setForm(f => ({ ...f, commission_rate: e.target.value }))} /></div>
          </div>
          <div className="space-y-1"><Label>Notes</Label>
            <Input value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} /></div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={save} disabled={saving}>{saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Save</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function AgentsPage() {
  const nav = useNavigate();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [summary, setSummary] = useState<AgentSummaryRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<Agent | null>(null);
  const [trend, setTrend] = useState<AgentTrendResponse | null>(null);
  const [from, setFrom] = useState(fyStart());
  const [to, setTo] = useState(today());
  const [gran, setGran] = useState<Gran>('month');
  const [payoutAgent, setPayoutAgent] = useState<Row | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [a, s] = await Promise.all([
        api.get<{ items: Agent[] }>('/api/v1/agents?page_size=500'),
        api.get<AgentSummaryRow[]>('/api/v1/agents/report-summary'),
      ]);
      setAgents(a.data.items ?? []);
      setSummary(s.data ?? []);
    } catch { /* surfaced via empty table */ } finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const loadTrend = useCallback(async () => {
    try {
      const { data } = await api.get<AgentTrendResponse>('/api/v1/agents/trend', {
        params: { date_from: from, date_to: to, granularity: gran },
      });
      setTrend(data);
    } catch { setTrend(null); }
  }, [from, to, gran]);
  useEffect(() => { loadTrend(); }, [loadTrend]);

  const rows = useMemo<Row[]>(() => {
    const byId = new Map(summary.map(s => [s.agent_id, s]));
    return agents.map(a => {
      const s = byId.get(a.id);
      return { ...a, earned: s?.earned ?? 0, paid: s?.paid ?? 0, due: s?.due ?? 0, invoice_count: s?.invoice_count ?? 0 };
    });
  }, [agents, summary]);

  const totals = useMemo(() => rows.reduce((acc, r) => ({
    earned: acc.earned + r.earned, paid: acc.paid + r.paid, due: acc.due + r.due,
  }), { earned: 0, paid: 0, due: 0 }), [rows]);

  const columns = useMemo<ColumnDef<Row>[]>(() => [
    { key: 'name', label: 'Agent', accessor: r => r.name,
      format: (_v, r) => <span className="font-medium">{r.name}</span> },
    { key: 'commission', label: 'Commission', accessor: r => commissionLabel(r.commission_type, r.commission_rate),
      exportValue: r => commissionLabel(r.commission_type, r.commission_rate) },
    { key: 'phone', label: 'Phone', accessor: r => r.phone ?? '' },
    { key: 'invoice_count', label: 'Bills', type: 'number', align: 'right', accessor: r => r.invoice_count },
    { key: 'earned', label: 'Earned', type: 'number', align: 'right', accessor: r => r.earned, format: v => INR(Number(v)), exportValue: r => r.earned },
    { key: 'paid', label: 'Paid', type: 'number', align: 'right', accessor: r => r.paid, format: v => INR(Number(v)), exportValue: r => r.paid },
    { key: 'due', label: 'Due', type: 'number', align: 'right', accessor: r => r.due,
      format: v => <span className={`font-semibold ${Number(v) > 0.005 ? 'text-rose-600' : 'text-muted-foreground'}`}>{INR(Number(v))}</span>,
      exportValue: r => r.due },
  ], []);

  const leaderboard = useMemo(
    () => [...rows].filter(r => r.due > 0.5).sort((a, b) => b.due - a.due).slice(0, 6).map(r => ({ name: r.name, due: r.due })),
    [rows]);

  const PRESETS: { label: string; f: () => void }[] = [
    { label: 'This month', f: () => { setFrom(monthStart()); setTo(today()); setGran('day'); } },
    { label: 'Last 30d', f: () => { setFrom(daysAgo(30)); setTo(today()); setGran('day'); } },
    { label: 'Last 90d', f: () => { setFrom(daysAgo(90)); setTo(today()); setGran('week'); } },
    { label: 'This FY', f: () => { setFrom(fyStart()); setTo(today()); setGran('month'); } },
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-lg font-bold text-slate-900 flex items-center gap-2"><Handshake className="h-5 w-5" /> Sales Partner / Agents</h1>
          <p className="text-xs text-muted-foreground">Commission earned per partner, trends, and payouts.</p>
        </div>
        <Button size="sm" onClick={() => { setEditing(null); setDialogOpen(true); }}>
          <Plus className="mr-1.5 h-4 w-4" /> New Partner
        </Button>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">Total Earned</p><p className="text-lg font-bold">{INR(totals.earned)}</p></CardContent></Card>
        <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">Total Paid</p><p className="text-lg font-bold text-emerald-600">{INR(totals.paid)}</p></CardContent></Card>
        <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">Total Due</p><p className="text-lg font-bold text-rose-600">{INR(totals.due)}</p></CardContent></Card>
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

      {/* Trend + leaderboard */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
        <Card className="lg:col-span-2"><CardContent className="p-4">
          <p className="mb-2 text-sm font-medium">Commission trend — earned vs paid <span className="text-muted-foreground">({gran})</span></p>
          {trend && trend.series.length > 0 ? (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={trend.series} margin={{ top: 8, right: 8, left: 8, bottom: 4 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} opacity={0.4} />
                <XAxis dataKey="label" tick={{ fontSize: 11 }} interval="preserveStartEnd" />
                <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => INR0(Number(v))} width={64} />
                <Tooltip formatter={(v: number, n) => [INR(Number(v)), n === 'earned' ? 'Earned' : 'Paid']} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Bar dataKey="earned" name="Earned" fill="#3b82f6" radius={[3, 3, 0, 0]} />
                <Bar dataKey="paid" name="Paid" fill="#10b981" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : <div className="py-14 text-center text-sm text-muted-foreground">No commission in this range</div>}
        </CardContent></Card>
        <Card><CardContent className="p-4">
          <p className="mb-2 text-sm font-medium">Top partners by due</p>
          {leaderboard.length > 0 ? (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={leaderboard} layout="vertical" margin={{ top: 4, right: 12, left: 8, bottom: 4 }}>
                <XAxis type="number" tick={{ fontSize: 10 }} tickFormatter={(v) => INR0(Number(v))} />
                <YAxis type="category" dataKey="name" tick={{ fontSize: 10 }} width={90} />
                <Tooltip formatter={(v: number) => [INR(Number(v)), 'Due']} />
                <Bar dataKey="due" fill="#f43f5e" radius={[0, 3, 3, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : <div className="py-14 text-center text-sm text-muted-foreground">Nothing due</div>}
        </CardContent></Card>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-16 text-muted-foreground"><Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading…</div>
      ) : (
        <DataTable<Row>
          id="agents.main"
          data={rows}
          columns={columns}
          rowKey={r => r.id}
          exportFilename="sales-partners"
          defaultSort={{ key: 'due', direction: 'desc' }}
          emptyMessage="No sales partners yet — add one to start tracking commission"
          rowActions={r => (
            <div className="flex gap-1">
              <Button size="icon" variant="ghost" className="h-7 w-7" title="Dashboard" onClick={() => nav(`/agents/${r.id}`)}>
                <FileBarChart className="h-3.5 w-3.5 text-blue-600" />
              </Button>
              <Button size="icon" variant="ghost" className="h-7 w-7" title="Record payout" onClick={() => setPayoutAgent(r)}>
                <Wallet className="h-3.5 w-3.5 text-emerald-600" />
              </Button>
              <Button size="icon" variant="ghost" className="h-7 w-7" title="Edit" onClick={() => { setEditing(r); setDialogOpen(true); }}>
                <Pencil className="h-3.5 w-3.5 text-slate-500" />
              </Button>
            </div>
          )}
        />
      )}

      <AgentDialog open={dialogOpen} agent={editing} onClose={() => setDialogOpen(false)} onSaved={load} />
      {payoutAgent && (
        <AgentPayoutDialog open={!!payoutAgent} agentId={payoutAgent.id} agentName={payoutAgent.name} due={payoutAgent.due}
          onClose={() => setPayoutAgent(null)} onSaved={() => { setPayoutAgent(null); load(); loadTrend(); }} />
      )}
    </div>
  );
}
