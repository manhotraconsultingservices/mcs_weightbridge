/**
 * Agents (brokers / dalals) master + commission summary.
 *
 * Lists agents with their commission config + earned/paid/due (merged from
 * /agents/report-summary). Create/edit dialog. Per-row → /agents/:id report card.
 */
import { useEffect, useState, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { Plus, Pencil, FileBarChart, Loader2, Users } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { DataTable, type ColumnDef } from '@/components/DataTable';
import api from '@/services/api';
import type { Agent, AgentSummaryRow, CommissionType } from '@/types';

const INR = (v: number) => '₹' + Number(v ?? 0).toLocaleString('en-IN', { minimumFractionDigits: 2 });

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
        <DialogHeader><DialogTitle>{agent ? 'Edit Agent' : 'New Agent'}</DialogTitle></DialogHeader>
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

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold text-slate-900 flex items-center gap-2"><Users className="h-5 w-5" /> Agents</h1>
          <p className="text-xs text-muted-foreground">Brokers/dalals — commission earned per agent, and payouts.</p>
        </div>
        <Button size="sm" onClick={() => { setEditing(null); setDialogOpen(true); }}>
          <Plus className="mr-1.5 h-4 w-4" /> New Agent
        </Button>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">Total Earned</p><p className="text-lg font-bold">{INR(totals.earned)}</p></CardContent></Card>
        <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">Total Paid</p><p className="text-lg font-bold text-emerald-600">{INR(totals.paid)}</p></CardContent></Card>
        <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">Total Due</p><p className="text-lg font-bold text-rose-600">{INR(totals.due)}</p></CardContent></Card>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-16 text-muted-foreground"><Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading…</div>
      ) : (
        <DataTable<Row>
          id="agents.main"
          data={rows}
          columns={columns}
          rowKey={r => r.id}
          exportFilename="agents"
          defaultSort={{ key: 'due', direction: 'desc' }}
          emptyMessage="No agents yet — add one to start tracking commission"
          rowActions={r => (
            <div className="flex gap-1">
              <Button size="icon" variant="ghost" className="h-7 w-7" title="Report card" onClick={() => nav(`/agents/${r.id}`)}>
                <FileBarChart className="h-3.5 w-3.5 text-blue-600" />
              </Button>
              <Button size="icon" variant="ghost" className="h-7 w-7" title="Edit" onClick={() => { setEditing(r); setDialogOpen(true); }}>
                <Pencil className="h-3.5 w-3.5 text-slate-500" />
              </Button>
            </div>
          )}
        />
      )}

      <AgentDialog open={dialogOpen} agent={editing} onClose={() => setDialogOpen(false)} onSaved={load} />
    </div>
  );
}
