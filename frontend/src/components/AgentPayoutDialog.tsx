/** Record a commission payout to a sales partner / agent. Shared by the
 *  overview list and the per-agent dashboard. */
import { useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { toast } from 'sonner';
import api from '@/services/api';

const INR = (v: number) => '₹' + Number(v ?? 0).toLocaleString('en-IN', { minimumFractionDigits: 2 });
const MODES = ['cash', 'upi', 'bank_transfer', 'cheque', 'neft'];

export function AgentPayoutDialog({ open, agentId, agentName, due, onClose, onSaved }: {
  open: boolean; agentId: string; agentName?: string; due: number; onClose: () => void; onSaved: () => void;
}) {
  const [amount, setAmount] = useState('');
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [mode, setMode] = useState('cash');
  const [ref, setRef] = useState('');
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (open) {
      setAmount(due > 0 ? String(Number(due.toFixed(2))) : '');
      setDate(new Date().toISOString().slice(0, 10)); setMode('cash'); setRef(''); setNotes(''); setError('');
    }
  }, [open, due]);

  async function save() {
    if (!amount || parseFloat(amount) <= 0) { setError('Enter a valid amount'); return; }
    setSaving(true); setError('');
    try {
      await api.post(`/api/v1/agents/${agentId}/payouts`, {
        amount: parseFloat(amount), paid_on: date, payment_mode: mode,
        reference_no: ref || null, notes: notes || null,
      });
      toast.success(`Paid ${INR(parseFloat(amount))}${agentName ? ` to ${agentName}` : ''}`);
      onSaved(); onClose();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Failed to record payout');
    } finally { setSaving(false); }
  }

  return (
    <Dialog open={open} onOpenChange={v => !v && onClose()}>
      <DialogContent className="max-w-sm">
        <DialogHeader><DialogTitle>Record payout{agentName ? ` — ${agentName}` : ''}</DialogTitle></DialogHeader>
        <div className="space-y-3">
          {error && <p className="rounded bg-destructive/10 p-2 text-sm text-destructive">{error}</p>}
          {due > 0 && <p className="text-xs text-muted-foreground">Due: <span className="font-semibold text-rose-600">{INR(due)}</span></p>}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1"><Label>Amount (₹) *</Label>
              <Input type="number" step="0.01" value={amount} onChange={e => setAmount(e.target.value)} /></div>
            <div className="space-y-1"><Label>Date *</Label>
              <Input type="date" value={date} onChange={e => setDate(e.target.value)} /></div>
          </div>
          <div className="space-y-1"><Label>Mode</Label>
            <Select value={mode} onValueChange={v => setMode(v ?? 'cash')}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>{MODES.map(m => <SelectItem key={m} value={m}>{m.replace(/_/g, ' ').toUpperCase()}</SelectItem>)}</SelectContent>
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
