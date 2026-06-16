import { useEffect, useState, useCallback } from 'react';
import api from '@/services/api';
import { toast } from 'sonner';
import { Plus, Loader2, X, MinusCircle, AlertTriangle, FileText } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger } from '@/components/ui/select';

interface Party { id: string; name: string }
interface Product { id: string; name: string }
interface Pass {
  id: string; pass_no: string; pass_type: string; source_name: string | null;
  party_id: string | null; party_name: string | null; mineral: string | null;
  issue_date: string | null; valid_till: string | null;
  quantity_mt: number | string; rate: number | string; amount: number | string;
  status: string; consumed_mt: number | string; balance_mt: number | string;
  utilization_pct: number; days_to_expiry: number | null;
}
interface Recon {
  authorised_mt: number; consumed_mt: number; purchase_inbound_mt: number;
  balance_mt: number; unaccounted_mt: number; pass_count: number; active_count: number; expiring_count: number;
}

const MT = (v: number | string) => Number(v ?? 0).toFixed(3) + ' MT';
const today = () => new Date().toISOString().slice(0, 10);
const monthStart = () => { const d = new Date(); d.setDate(1); return d.toISOString().slice(0, 10); };
const PASS_TYPES = ['royalty', 'e_transit', 'mineral_permit'];
const STATUS_PILL: Record<string, string> = {
  active: 'bg-emerald-100 text-emerald-700', exhausted: 'bg-blue-100 text-blue-700',
  expired: 'bg-amber-100 text-amber-700', cancelled: 'bg-gray-200 text-gray-500',
};

export default function RoyaltyPassesPage() {
  const [rows, setRows] = useState<Pass[]>([]);
  const [recon, setRecon] = useState<Recon | null>(null);
  const [parties, setParties] = useState<Party[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(false);
  const [range, setRange] = useState({ from: monthStart(), to: today() });
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [consumeFor, setConsumeFor] = useState<Pass | null>(null);
  const [consumeForm, setConsumeForm] = useState({ quantity_mt: '', notes: '' });

  const [form, setForm] = useState({
    pass_no: '', pass_type: 'royalty', source_name: '', party_id: '', product_id: '', mineral: '',
    issue_date: today(), valid_till: '', quantity_mt: '', rate: '', amount: '', vehicle_no: '', notes: '',
  });

  const load = useCallback(async () => {
    setLoading(true);
    // Passes load on their own — a reconciliation failure must NEVER blank the table.
    try {
      const p = await api.get('/api/v1/royalty/passes', { params: { page_size: 300 } });
      setRows(p.data.items ?? []);
    } catch {
      toast.error('Could not load royalty passes');
    } finally {
      setLoading(false);
    }
    // Reconciliation is best-effort (powers the KPI strip only).
    try {
      const r = await api.get('/api/v1/royalty/reconciliation', { params: { date_from: range.from, date_to: range.to } });
      setRecon(r.data);
    } catch { /* recon optional — KPIs just stay blank */ }
  }, [range.from, range.to]);

  useEffect(() => {
    load();
    api.get('/api/v1/parties', { params: { page_size: 500 } }).then(r => setParties(Array.isArray(r.data) ? r.data : r.data.items ?? [])).catch(() => {});
    api.get('/api/v1/products', { params: { page_size: 500 } }).then(r => setProducts(Array.isArray(r.data) ? r.data : r.data.items ?? [])).catch(() => {});
  }, [load]);

  function resetForm() {
    setForm({ pass_no: '', pass_type: 'royalty', source_name: '', party_id: '', product_id: '', mineral: '',
      issue_date: today(), valid_till: '', quantity_mt: '', rate: '', amount: '', vehicle_no: '', notes: '' });
    setErr('');
  }

  async function submit() {
    setErr('');
    if (!form.pass_no.trim()) { setErr('Pass number is required.'); return; }
    if (!(Number(form.quantity_mt) > 0)) { setErr('Authorised quantity (MT) must be greater than zero.'); return; }
    setBusy(true);
    try {
      await api.post('/api/v1/royalty/passes', {
        pass_no: form.pass_no, pass_type: form.pass_type,
        source_name: form.source_name || undefined,
        party_id: form.party_id || undefined, product_id: form.product_id || undefined,
        mineral: form.mineral || undefined,
        issue_date: form.issue_date || undefined, valid_till: form.valid_till || undefined,
        quantity_mt: Number(form.quantity_mt), rate: Number(form.rate || 0), amount: Number(form.amount || 0),
        vehicle_no: form.vehicle_no || undefined, notes: form.notes || undefined,
      });
      toast.success('Royalty pass added'); setOpen(false); resetForm(); load();
    } catch (e: unknown) {
      setErr((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Could not save pass');
    } finally { setBusy(false); }
  }

  async function doConsume() {
    if (!consumeFor) return;
    if (!(Number(consumeForm.quantity_mt) > 0)) { toast.error('Enter a quantity'); return; }
    try {
      await api.post(`/api/v1/royalty/passes/${consumeFor.id}/consume`, {
        quantity_mt: Number(consumeForm.quantity_mt), notes: consumeForm.notes || undefined,
      });
      toast.success('Consumption recorded');
      setConsumeFor(null); setConsumeForm({ quantity_mt: '', notes: '' }); load();
    } catch (e: unknown) {
      toast.error((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed');
    }
  }

  async function cancel(p: Pass) {
    if (!confirm(`Cancel pass ${p.pass_no}?`)) return;
    try { await api.post(`/api/v1/royalty/passes/${p.id}/cancel`); toast.success('Pass cancelled'); load(); }
    catch { toast.error('Cancel failed'); }
  }

  const expiring = rows.filter(p => p.status === 'active' && p.days_to_expiry != null && p.days_to_expiry <= 15);

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-xl font-bold">Royalty / Transit Passes</h1>
          <p className="text-xs text-muted-foreground">Track mineral royalty & e-transit passes; reconcile authorised qty vs inbound loads.</p>
        </div>
        <div className="flex items-center gap-2">
          <Input type="date" className="h-8 w-36 text-xs" value={range.from} onChange={e => setRange(r => ({ ...r, from: e.target.value }))} />
          <span className="text-xs text-muted-foreground">→</span>
          <Input type="date" className="h-8 w-36 text-xs" value={range.to} onChange={e => setRange(r => ({ ...r, to: e.target.value }))} />
          <Button onClick={() => { resetForm(); setOpen(true); }} className="gap-1.5"><Plus className="h-4 w-4" /> New Pass</Button>
        </div>
      </div>

      {/* Reconciliation cards */}
      {recon && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          {[
            { label: 'Authorised', val: recon.authorised_mt, hint: 'on passes issued in range' },
            { label: 'Consumed', val: recon.consumed_mt, hint: 'drawn against passes' },
            { label: 'Purchase inbound', val: recon.purchase_inbound_mt, hint: 'completed purchase tokens' },
            { label: 'Pass balance', val: recon.balance_mt, hint: 'authorised − consumed' },
            { label: 'Unaccounted', val: recon.unaccounted_mt, hint: 'inbound − consumed', warn: recon.unaccounted_mt > 0.5 },
          ].map(c => (
            <div key={c.label} className={`rounded-lg border p-3 ${c.warn ? 'border-amber-300 bg-amber-50' : ''}`}>
              <p className="text-[11px] text-muted-foreground">{c.label}</p>
              <p className={`text-lg font-bold ${c.warn ? 'text-amber-700' : ''}`}>{MT(c.val)}</p>
              <p className="text-[10px] text-muted-foreground">{c.hint}</p>
            </div>
          ))}
        </div>
      )}

      {expiring.length > 0 && (
        <div className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800 flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          {expiring.length} pass(es) expiring within 15 days: {expiring.map(p => p.pass_no).join(', ')}
        </div>
      )}

      {/* Passes table */}
      <div className="rounded-lg border overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-muted/40 text-xs">
            <tr className="[&>th]:px-3 [&>th]:py-2 [&>th]:text-left">
              <th>Pass No</th><th>Type</th><th>Source / Supplier</th><th>Mineral</th>
              <th>Valid Till</th><th className="w-48">Utilisation</th><th>Status</th><th></th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={8} className="px-3 py-6 text-center text-muted-foreground"><Loader2 className="inline h-4 w-4 animate-spin" /> Loading…</td></tr>}
            {!loading && rows.length === 0 && <tr><td colSpan={8} className="px-3 py-6 text-center text-muted-foreground">No royalty passes yet.</td></tr>}
            {rows.map(p => {
              const pct = Math.min(100, Number(p.utilization_pct) || 0);
              const over = Number(p.balance_mt) < 0;
              return (
                <tr key={p.id} className="border-t [&>td]:px-3 [&>td]:py-2 align-middle">
                  <td className="font-mono font-semibold">{p.pass_no}</td>
                  <td className="text-xs capitalize">{p.pass_type.replace('_', ' ')}</td>
                  <td className="max-w-[170px] truncate">{p.source_name ?? p.party_name ?? '—'}</td>
                  <td className="text-xs">{p.mineral ?? '—'}</td>
                  <td className="text-xs">{p.valid_till ? new Date(p.valid_till).toLocaleDateString('en-IN') : '—'}{p.days_to_expiry != null && p.days_to_expiry <= 15 && p.status === 'active' && <span className="text-amber-600"> ({p.days_to_expiry}d)</span>}</td>
                  <td>
                    <div className="h-2 rounded-full bg-muted overflow-hidden">
                      <div className={`h-full ${over ? 'bg-red-500' : pct > 85 ? 'bg-amber-500' : 'bg-emerald-500'}`} style={{ width: `${pct}%` }} />
                    </div>
                    <p className="text-[10px] text-muted-foreground mt-0.5">{MT(p.consumed_mt)} / {MT(p.quantity_mt)} · bal {MT(p.balance_mt)}</p>
                  </td>
                  <td><span className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${STATUS_PILL[p.status] ?? ''}`}>{p.status}</span></td>
                  <td>
                    <div className="flex items-center gap-1 justify-end">
                      {p.status !== 'cancelled' && (
                        <button onClick={() => { setConsumeFor(p); setConsumeForm({ quantity_mt: '', notes: '' }); }} title="Record consumption"
                          className="inline-flex h-7 w-7 items-center justify-center rounded-md hover:bg-accent text-blue-700"><MinusCircle className="h-3.5 w-3.5" /></button>
                      )}
                      {p.status !== 'cancelled' && (
                        <button onClick={() => cancel(p)} title="Cancel pass"
                          className="inline-flex h-7 w-7 items-center justify-center rounded-md hover:bg-accent text-red-600"><X className="h-3.5 w-3.5" /></button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* New pass dialog */}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader><DialogTitle className="flex items-center gap-2"><FileText className="h-4 w-4" /> New Royalty / Transit Pass</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div className="grid grid-cols-3 gap-3">
              <div className="space-y-1"><Label className="text-xs">Pass No *</Label><Input value={form.pass_no} onChange={e => setForm(f => ({ ...f, pass_no: e.target.value }))} /></div>
              <div className="space-y-1">
                <Label className="text-xs">Type</Label>
                <Select value={form.pass_type} onValueChange={v => setForm(f => ({ ...f, pass_type: v ?? 'royalty' }))}>
                  <SelectTrigger><span className="capitalize">{form.pass_type.replace('_', ' ')}</span></SelectTrigger>
                  <SelectContent>{PASS_TYPES.map(t => <SelectItem key={t} value={t}><span className="capitalize">{t.replace('_', ' ')}</span></SelectItem>)}</SelectContent>
                </Select>
              </div>
              <div className="space-y-1"><Label className="text-xs">Vehicle No</Label><Input value={form.vehicle_no} onChange={e => setForm(f => ({ ...f, vehicle_no: e.target.value.toUpperCase() }))} /></div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1"><Label className="text-xs">Source (mine/quarry)</Label><Input value={form.source_name} onChange={e => setForm(f => ({ ...f, source_name: e.target.value }))} /></div>
              <div className="space-y-1">
                <Label className="text-xs">Supplier (party)</Label>
                <Select value={form.party_id || undefined} onValueChange={v => setForm(f => ({ ...f, party_id: v ?? '' }))}>
                  <SelectTrigger><span className="truncate text-left flex-1">{form.party_id ? (parties.find(p => p.id === form.party_id)?.name ?? '…') : <span className="text-muted-foreground">Optional…</span>}</span></SelectTrigger>
                  <SelectContent>{parties.map(p => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}</SelectContent>
                </Select>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label className="text-xs">Mineral / Material</Label>
                <Select value={form.product_id || undefined} onValueChange={v => { const pr = products.find(x => x.id === v); setForm(f => ({ ...f, product_id: v ?? '', mineral: pr?.name ?? f.mineral })); }}>
                  <SelectTrigger><span className="truncate text-left flex-1">{form.product_id ? (products.find(p => p.id === form.product_id)?.name ?? '…') : (form.mineral || <span className="text-muted-foreground">Select / type below…</span>)}</span></SelectTrigger>
                  <SelectContent>{products.map(p => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}</SelectContent>
                </Select>
              </div>
              <div className="space-y-1"><Label className="text-xs">…or free-text mineral</Label><Input value={form.mineral} onChange={e => setForm(f => ({ ...f, mineral: e.target.value }))} placeholder="e.g. Boulder / Gitti" /></div>
            </div>
            <div className="grid grid-cols-3 gap-3">
              <div className="space-y-1"><Label className="text-xs">Authorised Qty (MT) *</Label><Input type="number" step="0.001" value={form.quantity_mt} onChange={e => setForm(f => ({ ...f, quantity_mt: e.target.value }))} /></div>
              <div className="space-y-1"><Label className="text-xs">Rate (₹/MT)</Label><Input type="number" step="0.01" value={form.rate} onChange={e => setForm(f => ({ ...f, rate: e.target.value }))} /></div>
              <div className="space-y-1"><Label className="text-xs">Royalty Amount (₹)</Label><Input type="number" step="0.01" value={form.amount} onChange={e => setForm(f => ({ ...f, amount: e.target.value }))} /></div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1"><Label className="text-xs">Issue Date</Label><Input type="date" value={form.issue_date} onChange={e => setForm(f => ({ ...f, issue_date: e.target.value }))} /></div>
              <div className="space-y-1"><Label className="text-xs">Valid Till</Label><Input type="date" value={form.valid_till} onChange={e => setForm(f => ({ ...f, valid_till: e.target.value }))} /></div>
            </div>
            <div className="space-y-1"><Label className="text-xs">Notes</Label><Input value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} /></div>
            {err && <p className="text-xs text-red-600">{err}</p>}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button onClick={submit} disabled={busy} className="gap-1.5">{busy && <Loader2 className="h-4 w-4 animate-spin" />} Add Pass</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Consume dialog */}
      <Dialog open={!!consumeFor} onOpenChange={o => !o && setConsumeFor(null)}>
        <DialogContent className="max-w-sm">
          <DialogHeader><DialogTitle>Record consumption — {consumeFor?.pass_no}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <p className="text-xs text-muted-foreground">Balance: <b>{consumeFor ? MT(consumeFor.balance_mt) : '—'}</b></p>
            <div className="space-y-1"><Label className="text-xs">Quantity drawn (MT)</Label><Input type="number" step="0.001" value={consumeForm.quantity_mt} onChange={e => setConsumeForm(f => ({ ...f, quantity_mt: e.target.value }))} autoFocus /></div>
            <div className="space-y-1"><Label className="text-xs">Note (e.g. token / vehicle)</Label><Input value={consumeForm.notes} onChange={e => setConsumeForm(f => ({ ...f, notes: e.target.value }))} /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConsumeFor(null)}>Cancel</Button>
            <Button onClick={doConsume}>Record</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
