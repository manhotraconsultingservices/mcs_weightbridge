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
import { DataTable, type ColumnDef } from '@/components/DataTable';

interface Note {
  id: string; invoice_no: string | null; invoice_date: string; invoice_type: string;
  party: { name: string } | null; grand_total: number | string; status: string;
  note_reason: string | null; notes: string | null;
}
interface SrcInvoice { id: string; invoice_no: string | null; invoice_type: string; status: string; party: { name: string } | null; grand_total: number | string }

const INR = (v: number | string) => '₹' + Number(v ?? 0).toLocaleString('en-IN', { minimumFractionDigits: 2 });

const NOTE_COLUMNS: ColumnDef<Note>[] = [
  {
    key: 'invoice_no', label: 'Note No', type: 'string',
    accessor: n => n.invoice_no ?? '',
    format: (_, n) => (n as Note).invoice_no
      ? <span className="font-mono font-semibold">{(n as Note).invoice_no}</span>
      : <span className="italic text-muted-foreground">draft</span>,
  },
  {
    key: 'invoice_date', label: 'Date', type: 'date',
    accessor: n => n.invoice_date,
    format: v => new Date(String(v)).toLocaleDateString('en-IN'),
  },
  {
    key: 'invoice_type', label: 'Type', type: 'enum', enumOptions: ['credit_note', 'debit_note'],
    accessor: n => n.invoice_type,
    format: (_, n) => {
      const isCredit = (n as Note).invoice_type === 'credit_note';
      return (
        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium ${isCredit ? 'bg-rose-100 text-rose-700' : 'bg-amber-100 text-amber-700'}`}>
          {isCredit ? <FileMinus className="h-3 w-3" /> : <FilePlus className="h-3 w-3" />}
          {isCredit ? 'Credit' : 'Debit'}
        </span>
      );
    },
    exportValue: n => n.invoice_type === 'credit_note' ? 'Credit' : 'Debit',
  },
  {
    key: 'party', label: 'Party', type: 'string',
    accessor: n => n.party?.name ?? 'Cash',
    className: 'max-w-[160px] truncate',
  },
  {
    key: 'note_reason', label: 'Reason', type: 'string',
    accessor: n => n.note_reason ?? '',
    format: (v) => <span className="text-xs text-muted-foreground">{String(v) || '—'}</span>,
    className: 'max-w-[200px] truncate',
  },
  {
    key: 'grand_total', label: 'Amount', type: 'number', align: 'right',
    accessor: n => Number(n.grand_total ?? 0),
    format: (v) => INR(v as number),
    exportValue: n => Number(n.grand_total ?? 0),
  },
  {
    key: 'status', label: 'Status', type: 'enum', enumOptions: ['draft', 'final'],
    accessor: n => n.status,
    format: (v) => (
      <span className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${v === 'final' ? 'bg-emerald-100 text-emerald-700' : 'bg-blue-100 text-blue-700'}`}>
        {String(v)}
      </span>
    ),
  },
];

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

      <DataTable<Note>
        id="creditdebitnotes.main"
        data={notes}
        loading={loading}
        columns={NOTE_COLUMNS}
        rowKey={n => n.id}
        exportFilename="credit-debit-notes"
        defaultSort={{ key: 'invoice_date', direction: 'desc' }}
        emptyMessage="No credit/debit notes yet."
        rowActions={n => (
          <div className="flex items-center gap-1 justify-end">
            <PrintButton a4Url={`/api/v1/invoices/${n.id}/pdf`} url={`/api/v1/invoices/${n.id}/pdf`} iconOnly />
            {n.status === 'draft' && (
              <button onClick={() => finalise(n)} title="Finalise (assign number)"
                className="inline-flex h-7 w-7 items-center justify-center rounded-md hover:bg-accent text-emerald-700">
                <CheckCircle2 className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        )}
      />

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
