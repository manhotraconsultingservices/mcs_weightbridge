/**
 * Agent report card — earned / paid / due + invoice drilldown + payouts.
 *
 *   GET  /api/v1/agents/{id}/report?date_from&date_to
 *   POST /api/v1/agents/{id}/payouts
 */
import { useEffect, useState, useCallback, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, IndianRupee, Wallet, Scale, Loader2, Plus, Receipt } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { DataTable, type ColumnDef } from '@/components/DataTable';
import api from '@/services/api';
import type { AgentReport, AgentReportInvoice } from '@/types';
import { commissionLabel } from './AgentsPage';

const INR = (v: number) => '₹' + Number(v ?? 0).toLocaleString('en-IN', { minimumFractionDigits: 2 });
const fmtDate = (s: string | null | undefined) =>
  s ? new Date(s).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }) : '—';
const PAYOUT_MODES = ['cash', 'upi', 'bank_transfer', 'cheque', 'neft'];

function PayoutDialog({ open, agentId, due, onClose, onSaved }: {
  open: boolean; agentId: string; due: number; onClose: () => void; onSaved: () => void;
}) {
  const [amount, setAmount] = useState('');
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [mode, setMode] = useState('cash');
  const [ref, setRef] = useState('');
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (open) { setAmount(due > 0 ? String(due) : ''); setDate(new Date().toISOString().slice(0, 10)); setMode('cash'); setRef(''); setNotes(''); setError(''); }
  }, [open, due]);

  async function save() {
    if (!amount || parseFloat(amount) <= 0) { setError('Enter a valid amount'); return; }
    setSaving(true); setError('');
    try {
      await api.post(`/api/v1/agents/${agentId}/payouts`, {
        amount: parseFloat(amount), paid_on: date, payment_mode: mode,
        reference_no: ref || null, notes: notes || null,
      });
      onSaved(); onClose();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Failed to record payout');
    } finally { setSaving(false); }
  }

  return (
    <Dialog open={open} onOpenChange={v => !v && onClose()}>
      <DialogContent className="max-w-sm">
        <DialogHeader><DialogTitle>Record commission payout</DialogTitle></DialogHeader>
        <div className="space-y-3">
          {error && <p className="rounded bg-destructive/10 p-2 text-sm text-destructive">{error}</p>}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1"><Label>Amount (₹) *</Label>
              <Input type="number" step="0.01" value={amount} onChange={e => setAmount(e.target.value)} /></div>
            <div className="space-y-1"><Label>Date *</Label>
              <Input type="date" value={date} onChange={e => setDate(e.target.value)} /></div>
          </div>
          <div className="space-y-1"><Label>Mode</Label>
            <Select value={mode} onValueChange={v => setMode(v ?? 'cash')}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>{PAYOUT_MODES.map(m => <SelectItem key={m} value={m}>{m.replace(/_/g, ' ').toUpperCase()}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div className="space-y-1"><Label>Reference</Label>
            <Input value={ref} onChange={e => setRef(e.target.value)} placeholder="UTR / cheque no" /></div>
          <div className="space-y-1"><Label>Notes</Label>
            <Input value={notes} onChange={e => setNotes(e.target.value)} /></div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={save} disabled={saving}>{saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Record payout</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function AgentReportPage() {
  const { id = '' } = useParams();
  const nav = useNavigate();
  const [report, setReport] = useState<AgentReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [payoutOpen, setPayoutOpen] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    try {
      const { data } = await api.get<AgentReport>(`/api/v1/agents/${id}/report`);
      setReport(data);
    } catch { setReport(null); } finally { setLoading(false); }
  }, [id]);
  useEffect(() => { load(); }, [load]);

  const invColumns = useMemo<ColumnDef<AgentReportInvoice>[]>(() => [
    { key: 'invoice_no', label: 'Invoice', accessor: r => r.invoice_no ?? '—' },
    { key: 'invoice_date', label: 'Date', type: 'date', accessor: r => r.invoice_date, format: v => fmtDate(String(v)) },
    { key: 'party_name', label: 'Customer', accessor: r => r.party_name ?? '—' },
    { key: 'net_weight_mt', label: 'Net (MT)', type: 'number', align: 'right', accessor: r => r.net_weight_mt, format: v => Number(v).toFixed(3) },
    { key: 'grand_total', label: 'Bill Total', type: 'number', align: 'right', accessor: r => r.grand_total, format: v => INR(Number(v)), exportValue: r => r.grand_total },
    { key: 'commission_amount', label: 'Commission', type: 'number', align: 'right', accessor: r => r.commission_amount,
      format: v => <span className="font-semibold text-blue-600">{INR(Number(v))}</span>, exportValue: r => r.commission_amount },
  ], []);

  if (loading && !report) {
    return <div className="flex items-center justify-center py-24 text-muted-foreground"><Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading…</div>;
  }
  if (!report) {
    return (
      <div className="py-16 text-center">
        <p className="text-sm text-muted-foreground">Agent not found.</p>
        <Button variant="outline" className="mt-4" onClick={() => nav('/agents')}><ArrowLeft className="mr-2 h-4 w-4" /> Back to Agents</Button>
      </div>
    );
  }
  const a = report.agent;

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <Button variant="ghost" size="icon" onClick={() => nav('/agents')} title="Back"><ArrowLeft className="h-4 w-4" /></Button>
          <div>
            <h1 className="text-xl font-bold text-slate-900">{a.name}</h1>
            <p className="text-xs text-muted-foreground">
              Commission: {commissionLabel(a.commission_type, a.commission_rate)}
              {a.phone ? ` · ${a.phone}` : ''}
            </p>
          </div>
        </div>
        <Button size="sm" onClick={() => setPayoutOpen(true)}><Plus className="mr-1.5 h-4 w-4" /> Record payout</Button>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Card><CardContent className="flex items-center gap-3 p-4">
          <div className="rounded-lg bg-blue-50 p-2"><IndianRupee className="h-5 w-5 text-blue-600" /></div>
          <div><p className="text-xs text-muted-foreground">Earned</p><p className="text-lg font-bold">{INR(report.earned)}</p></div>
        </CardContent></Card>
        <Card><CardContent className="flex items-center gap-3 p-4">
          <div className="rounded-lg bg-emerald-50 p-2"><Wallet className="h-5 w-5 text-emerald-600" /></div>
          <div><p className="text-xs text-muted-foreground">Paid</p><p className="text-lg font-bold text-emerald-600">{INR(report.paid)}</p></div>
        </CardContent></Card>
        <Card><CardContent className="flex items-center gap-3 p-4">
          <div className="rounded-lg bg-rose-50 p-2"><Scale className="h-5 w-5 text-rose-600" /></div>
          <div><p className="text-xs text-muted-foreground">Due</p><p className="text-lg font-bold text-rose-600">{INR(report.due)}</p></div>
        </CardContent></Card>
        <Card><CardContent className="flex items-center gap-3 p-4">
          <div className="rounded-lg bg-slate-100 p-2"><Receipt className="h-5 w-5 text-slate-600" /></div>
          <div><p className="text-xs text-muted-foreground">Bills</p><p className="text-lg font-bold">{report.invoice_count}</p>
            <p className="text-[10px] text-muted-foreground">{INR(report.total_sale_value)} value</p></div>
        </CardContent></Card>
      </div>

      <div>
        <p className="mb-2 text-sm font-medium">Commission-earning invoices</p>
        <DataTable<AgentReportInvoice>
          id="agent.report.invoices"
          data={report.invoices}
          columns={invColumns}
          rowKey={r => r.invoice_id}
          exportFilename={`agent-${a.name}-commission`}
          defaultSort={{ key: 'invoice_date', direction: 'desc' }}
          emptyMessage="No commission-earning invoices yet"
        />
      </div>

      {report.payouts.length > 0 && (
        <div>
          <p className="mb-2 text-sm font-medium">Payouts</p>
          <Card><CardContent className="p-0">
            <div className="divide-y">
              {report.payouts.map(p => (
                <div key={p.id} className="flex items-center justify-between px-4 py-2 text-sm">
                  <div>
                    <span className="font-medium">{INR(p.amount)}</span>
                    <span className="ml-2 text-xs text-muted-foreground">{fmtDate(p.paid_on)} · {(p.payment_mode ?? '').replace(/_/g, ' ')}</span>
                  </div>
                  <span className="text-xs text-muted-foreground">{p.reference_no ?? ''}</span>
                </div>
              ))}
            </div>
          </CardContent></Card>
        </div>
      )}

      <PayoutDialog open={payoutOpen} agentId={a.id} due={report.due} onClose={() => setPayoutOpen(false)} onSaved={load} />
    </div>
  );
}
