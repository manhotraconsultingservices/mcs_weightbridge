import { useEffect, useState, useCallback } from 'react';
import api from '@/services/api';
import { toast } from 'sonner';
import { Plus, Loader2, CheckCircle2, FileMinus, FilePlus } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger } from '@/components/ui/select';
import { PrintButton } from '@/components/PrintButton';

interface Note {
  id: string; invoice_no: string | null; invoice_date: string; invoice_type: string;
  party: { name: string } | null; grand_total: number | string; status: string;
  note_reason: string | null; notes: string | null;
}
interface SrcInvoice { id: string; invoice_no: string | null; invoice_type: string; status: string; party: { name: string } | null; grand_total: number | string }

const INR = (v: number | string) => '₹' + Number(v ?? 0).toLocaleString('en-IN', { minimumFractionDigits: 2 });

export default function CreditDebitNotesPage() {
  const [notes, setNotes] = useState<Note[]>([]);
  const [sources, setSources] = useState<SrcInvoice[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [form, setForm] = useState({ invoice_id: '', note_type: 'credit', reason: '' });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [cn, dn] = await Promise.all([
        api.get('/api/v1/invoices', { params: { invoice_type: 'credit_note', page_size: 100 } }),
        api.get('/api/v1/invoices', { params: { invoice_type: 'debit_note', page_size: 100 } }),
      ]);
      const all = [...(cn.data.items ?? []), ...(dn.data.items ?? [])]
        .sort((a, b) => (b.invoice_date || '').localeCompare(a.invoice_date || ''));
      setNotes(all);
    } catch { /* inline */ } finally { setLoading(false); }
  }, []);

  useEffect(() => {
    load();
    // Source invoices a note can be raised against: finalised sale + purchase.
    // status=final filters server-side; page_size capped at 100 by the API.
    Promise.all([
      api.get('/api/v1/invoices', { params: { invoice_type: 'sale', status: 'final', page_size: 100 } }),
      api.get('/api/v1/invoices', { params: { invoice_type: 'purchase', status: 'final', page_size: 100 } }),
    ]).then(([s, p]) => {
      const fin = [...(s.data.items ?? []), ...(p.data.items ?? [])].filter((i: SrcInvoice) => i.invoice_no);
      setSources(fin);
    }).catch(() => {});
  }, [load]);

  async function submit() {
    setErr('');
    if (!form.invoice_id) { setErr('Select the invoice this note adjusts.'); return; }
    if (!form.reason.trim()) { setErr('A reason is required.'); return; }
    setBusy(true);
    try {
      await api.post(`/api/v1/invoices/${form.invoice_id}/issue-note`, {
        note_type: form.note_type, reason: form.reason.trim(),
      });
      toast.success(`${form.note_type === 'credit' ? 'Credit' : 'Debit'} note draft created — finalise it to assign a number`);
      setOpen(false); setForm({ invoice_id: '', note_type: 'credit', reason: '' }); load();
    } catch (e: unknown) {
      setErr((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Could not create note');
    } finally { setBusy(false); }
  }

  async function finalise(n: Note) {
    if (!confirm('Finalise this note? It will be assigned a permanent CN/DN number.')) return;
    try {
      await api.post(`/api/v1/invoices/${n.id}/finalise`);
      toast.success('Note finalised');
      load();
    } catch (e: unknown) {
      toast.error((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Finalise failed');
    }
  }

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">Credit / Debit Notes</h1>
          <p className="text-xs text-muted-foreground">GST adjustment documents (CDNR). Issued against a finalised invoice; flow to GSTR-1.</p>
        </div>
        <Button onClick={() => { setErr(''); setOpen(true); }} className="gap-1.5"><Plus className="h-4 w-4" /> New Note</Button>
      </div>

      <div className="rounded-lg border overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-muted/40 text-xs">
            <tr className="[&>th]:px-3 [&>th]:py-2 [&>th]:text-left">
              <th>Note No</th><th>Date</th><th>Type</th><th>Party</th><th>Reason</th>
              <th className="text-right">Amount</th><th>Status</th><th></th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={8} className="px-3 py-6 text-center text-muted-foreground"><Loader2 className="inline h-4 w-4 animate-spin" /> Loading…</td></tr>}
            {!loading && notes.length === 0 && <tr><td colSpan={8} className="px-3 py-6 text-center text-muted-foreground">No credit/debit notes yet.</td></tr>}
            {notes.map(n => {
              const isCredit = n.invoice_type === 'credit_note';
              return (
                <tr key={n.id} className="border-t [&>td]:px-3 [&>td]:py-2">
                  <td className="font-mono font-semibold">{n.invoice_no ?? <span className="italic text-muted-foreground">draft</span>}</td>
                  <td>{new Date(n.invoice_date).toLocaleDateString('en-IN')}</td>
                  <td>
                    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium ${isCredit ? 'bg-rose-100 text-rose-700' : 'bg-amber-100 text-amber-700'}`}>
                      {isCredit ? <FileMinus className="h-3 w-3" /> : <FilePlus className="h-3 w-3" />}
                      {isCredit ? 'Credit' : 'Debit'}
                    </span>
                  </td>
                  <td className="max-w-[160px] truncate">{n.party?.name ?? 'Cash'}</td>
                  <td className="max-w-[200px] truncate text-xs text-muted-foreground" title={n.note_reason ?? ''}>{n.note_reason ?? '—'}</td>
                  <td className="text-right">{INR(n.grand_total)}</td>
                  <td><span className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${n.status === 'final' ? 'bg-emerald-100 text-emerald-700' : 'bg-blue-100 text-blue-700'}`}>{n.status}</span></td>
                  <td>
                    <div className="flex items-center gap-1 justify-end">
                      <PrintButton a4Url={`/api/v1/invoices/${n.id}/pdf`} url={`/api/v1/invoices/${n.id}/pdf`} iconOnly />
                      {n.status === 'draft' && (
                        <button onClick={() => finalise(n)} title="Finalise (assign number)"
                          className="inline-flex h-7 w-7 items-center justify-center rounded-md hover:bg-accent text-emerald-700">
                          <CheckCircle2 className="h-3.5 w-3.5" />
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* New note dialog */}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader><DialogTitle>New Credit / Debit Note</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1">
              <Label className="text-xs">Against invoice</Label>
              <Select value={form.invoice_id || undefined} onValueChange={v => setForm(f => ({ ...f, invoice_id: v ?? '' }))}>
                <SelectTrigger>
                  <span className="truncate text-left flex-1">
                    {form.invoice_id ? (sources.find(s => s.id === form.invoice_id)?.invoice_no ?? '…') : <span className="text-muted-foreground">Select a finalised invoice…</span>}
                  </span>
                </SelectTrigger>
                <SelectContent>
                  {sources.map(s => (
                    <SelectItem key={s.id} value={s.id}>
                      <span className="font-mono">{s.invoice_no}</span>
                      <span className="text-muted-foreground text-xs ml-2">{s.party?.name ?? 'Cash'} · {INR(s.grand_total)}</span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Note type</Label>
              <Select value={form.note_type} onValueChange={v => setForm(f => ({ ...f, note_type: v ?? 'credit' }))}>
                <SelectTrigger><span className="capitalize">{form.note_type} note</span></SelectTrigger>
                <SelectContent>
                  <SelectItem value="credit">Credit note (reduce what customer owes)</SelectItem>
                  <SelectItem value="debit">Debit note (increase what customer owes)</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Reason</Label>
              <Input value={form.reason} onChange={e => setForm(f => ({ ...f, reason: e.target.value }))} placeholder="e.g. Sales return — short supply, rate revision" />
            </div>
            <p className="text-[11px] text-muted-foreground">A draft is created cloning the invoice's items + tax. Edit it under Bills if needed, then finalise to assign a CN/DN number.</p>
            {err && <p className="text-xs text-red-600">{err}</p>}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button onClick={submit} disabled={busy} className="gap-1.5">{busy && <Loader2 className="h-4 w-4 animate-spin" />} Create Note</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
