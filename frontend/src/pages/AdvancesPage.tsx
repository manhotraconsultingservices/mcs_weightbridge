/**
 * Advances / Prepayments — a dedicated screen to record and track money a
 * customer has prepaid us (advance) or we've prepaid a supplier.
 *
 * An advance is simply a payment with NO invoice allocation — it sits on the
 * party's account as a credit and auto-applies to their next bill (Feature A).
 *
 * Reuses existing endpoints (no backend change):
 *   POST /api/v1/payments/receipts   (customer advance — allocations: [])
 *   POST /api/v1/payments/vouchers   (supplier advance — allocations: [])
 *   GET  /api/v1/reports/party-balances?party_type=customer|supplier
 */
import { useEffect, useState, useCallback, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { Wallet, Plus, Loader2, AlertCircle } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { DataTable, type ColumnDef } from '@/components/DataTable';
import { toast } from 'sonner';
import api from '@/services/api';
import type { Party } from '@/types';

const INR = (v: number) =>
  '₹' + Number(v ?? 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const PAYMENT_MODES = ['cash', 'upi', 'bank_transfer', 'cheque', 'neft', 'rtgs'];

type Mode = 'customer' | 'supplier';

interface BalanceRow {
  id: string;
  name: string;
  party_type: string;
  phone: string | null;
  city: string | null;
  bills_balance: number;
  advance: number;
  net_balance: number;
}

// ── Record-advance dialog ─────────────────────────────────────────────────────
function RecordAdvanceDialog({ open, mode, parties, presetPartyId, onClose, onSaved }: {
  open: boolean; mode: Mode; parties: Party[]; presetPartyId: string;
  onClose: () => void; onSaved: () => void;
}) {
  const [partyId, setPartyId] = useState('');
  const [amount, setAmount] = useState('');
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [payMode, setPayMode] = useState('cash');
  const [ref, setRef] = useState('');
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (open) {
      setPartyId(presetPartyId || '');
      setAmount(''); setDate(new Date().toISOString().slice(0, 10));
      setPayMode('cash'); setRef(''); setNotes(''); setError('');
    }
  }, [open, presetPartyId]);

  const partyWord = mode === 'supplier' ? 'Supplier' : 'Customer';
  const eligible = useMemo(() => parties.filter(p =>
    mode === 'supplier'
      ? (p.party_type === 'supplier' || p.party_type === 'both')
      : (p.party_type === 'customer' || p.party_type === 'both')
  ), [parties, mode]);

  async function save() {
    if (!partyId) { setError(`Pick a ${partyWord.toLowerCase()}`); return; }
    if (!amount || parseFloat(amount) <= 0) { setError('Enter a valid amount'); return; }
    setSaving(true); setError('');
    try {
      const url = mode === 'supplier' ? '/api/v1/payments/vouchers' : '/api/v1/payments/receipts';
      const dateKey = mode === 'supplier' ? 'voucher_date' : 'receipt_date';
      await api.post(url, {
        [dateKey]: date,
        party_id: partyId,
        amount: parseFloat(amount),
        payment_mode: payMode,
        reference_no: ref || null,
        notes: notes ? `Advance: ${notes}` : 'Advance / prepayment (on account)',
        allocations: [],   // no invoice → this money sits as an advance
      });
      toast.success(`Advance of ${INR(parseFloat(amount))} recorded — it will auto-apply to their next bill`);
      onSaved(); onClose();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Failed to record advance');
    } finally { setSaving(false); }
  }

  return (
    <Dialog open={open} onOpenChange={v => !v && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader><DialogTitle>Record {partyWord} Advance</DialogTitle></DialogHeader>
        <div className="space-y-3">
          {error && <p className="rounded bg-destructive/10 p-2 text-sm text-destructive">{error}</p>}
          <div className="space-y-1">
            <Label>{partyWord} *</Label>
            <Select value={partyId || undefined} onValueChange={v => setPartyId(v ?? '')}>
              <SelectTrigger><SelectValue placeholder={`Select ${partyWord.toLowerCase()}…`} /></SelectTrigger>
              <SelectContent className="max-h-72">
                {eligible.map(p => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1"><Label>Amount (₹) *</Label>
              <Input type="number" min="0.01" step="0.01" value={amount} onChange={e => setAmount(e.target.value)} placeholder="0.00" /></div>
            <div className="space-y-1"><Label>Date *</Label>
              <Input type="date" value={date} onChange={e => setDate(e.target.value)} /></div>
          </div>
          <div className="space-y-1"><Label>Mode</Label>
            <Select value={payMode} onValueChange={v => setPayMode(v ?? 'cash')}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>{PAYMENT_MODES.map(m => <SelectItem key={m} value={m}>{m.replace(/_/g, ' ').toUpperCase()}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          {payMode !== 'cash' && (
            <div className="space-y-1"><Label>Reference</Label>
              <Input value={ref} onChange={e => setRef(e.target.value)} placeholder="UTR / cheque / txn no" /></div>
          )}
          <div className="space-y-1"><Label>Notes</Label>
            <Input value={notes} onChange={e => setNotes(e.target.value)} placeholder="Optional" /></div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={save} disabled={saving}>{saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Record Advance</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────
export default function AdvancesPage() {
  const [mode, setMode] = useState<Mode>('customer');
  const [balances, setBalances] = useState<BalanceRow[]>([]);
  const [parties, setParties] = useState<Party[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [dialogOpen, setDialogOpen] = useState(false);
  const [presetPartyId, setPresetPartyId] = useState('');

  const loadBalances = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const { data } = await api.get<{ rows: BalanceRow[] }>('/api/v1/reports/party-balances', {
        params: { party_type: mode },
      });
      setBalances((data.rows ?? []).filter(r => Number(r.advance) > 0.005));
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Failed to load advance balances');
      setBalances([]);
    } finally { setLoading(false); }
  }, [mode]);

  useEffect(() => { loadBalances(); }, [loadBalances]);
  useEffect(() => {
    api.get<{ items: Party[] } | Party[]>('/api/v1/parties?page_size=500')
      .then(r => setParties(Array.isArray(r.data) ? r.data : (r.data.items ?? [])))
      .catch(() => setParties([]));
  }, []);

  const totalAdvance = useMemo(() => balances.reduce((s, r) => s + Number(r.advance || 0), 0), [balances]);
  const partyWord = mode === 'supplier' ? 'Supplier' : 'Customer';

  function openRecord(pid = '') { setPresetPartyId(pid); setDialogOpen(true); }

  const columns = useMemo<ColumnDef<BalanceRow>[]>(() => [
    { key: 'name', label: partyWord, accessor: r => r.name,
      format: (_v, r) => <Link to={`/customers/${r.id}`} className="font-medium text-primary hover:underline">{r.name}</Link>,
      exportValue: r => r.name },
    { key: 'phone', label: 'Phone', accessor: r => r.phone ?? '' },
    { key: 'city', label: 'City', accessor: r => r.city ?? '', defaultVisible: false },
    { key: 'advance', label: 'Advance on Account', type: 'number', align: 'right', accessor: r => r.advance,
      format: v => <span className="font-semibold text-emerald-600">{INR(Number(v))}</span>, exportValue: r => r.advance },
    { key: 'net_balance', label: 'Net Balance', type: 'number', align: 'right', accessor: r => r.net_balance,
      format: v => {
        const n = Number(v);
        const cls = n > 0.005 ? 'text-rose-600' : n < -0.005 ? 'text-emerald-600' : 'text-muted-foreground';
        const tag = Math.abs(n) < 0.005 ? '' : (n > 0 ? ' Dr' : ' Cr');
        return <span className={cls}>{INR(Math.abs(n))}{tag}</span>;
      }, exportValue: r => r.net_balance },
  ], [partyWord]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-bold text-slate-900 flex items-center gap-2"><Wallet className="h-5 w-5" /> Advances / Prepaid</h1>
          <p className="text-xs text-muted-foreground">
            Record money a {partyWord.toLowerCase()} prepays — it sits as a credit and auto-applies to their next bill.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex gap-1 rounded-lg border p-0.5">
            {(['customer', 'supplier'] as Mode[]).map(m => (
              <Button key={m} size="sm" variant={mode === m ? 'default' : 'ghost'}
                className="h-7 px-3 text-xs capitalize" onClick={() => setMode(m)}>
                {m === 'customer' ? 'Customers' : 'Suppliers'}
              </Button>
            ))}
          </div>
          <Button size="sm" onClick={() => openRecord()}>
            <Plus className="mr-1.5 h-4 w-4" /> Record Advance
          </Button>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
          <AlertCircle className="h-4 w-4" /> {error}
        </div>
      )}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Card><CardContent className="flex items-center gap-3 p-4">
          <div className="rounded-lg bg-emerald-50 p-2"><Wallet className="h-5 w-5 text-emerald-600" /></div>
          <div>
            <p className="text-xs text-muted-foreground">Total {partyWord} Advances (Cr)</p>
            <p className="text-lg font-bold text-emerald-600">{INR(totalAdvance)}</p>
          </div>
        </CardContent></Card>
        <Card><CardContent className="flex items-center gap-3 p-4">
          <div className="rounded-lg bg-slate-100 p-2"><Wallet className="h-5 w-5 text-slate-600" /></div>
          <div>
            <p className="text-xs text-muted-foreground">{partyWord}s with an advance</p>
            <p className="text-lg font-bold">{balances.length}</p>
          </div>
        </CardContent></Card>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-16 text-muted-foreground"><Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading…</div>
      ) : (
        <DataTable<BalanceRow>
          id="advances.balances"
          data={balances}
          columns={columns}
          rowKey={r => r.id}
          exportFilename={`advances-${mode}`}
          defaultSort={{ key: 'advance', direction: 'desc' }}
          emptyMessage={`No ${partyWord.toLowerCase()} advances on account — click "Record Advance" to add one`}
          rowActions={r => (
            <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => openRecord(r.id)}>
              <Plus className="mr-1 h-3 w-3" /> Add
            </Button>
          )}
        />
      )}

      <div className="flex items-start gap-2 text-xs text-muted-foreground bg-muted/40 rounded p-3">
        <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
        <p>
          An advance is a payment with no bill attached. It shows as a <b>credit (Cr)</b> on the party's balance and
          is <b>auto-applied (oldest first)</b> when you finalise their next {mode === 'supplier' ? 'purchase' : 'sale'} invoice —
          or apply it manually from the invoice. Fully-consumed advances drop off this list.
        </p>
      </div>

      <RecordAdvanceDialog
        open={dialogOpen}
        mode={mode}
        parties={parties}
        presetPartyId={presetPartyId}
        onClose={() => setDialogOpen(false)}
        onSaved={loadBalances}
      />
    </div>
  );
}
