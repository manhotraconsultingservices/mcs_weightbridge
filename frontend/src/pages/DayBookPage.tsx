import { useCallback, useEffect, useState } from 'react';
import api from '../services/api';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Printer, Download, Settings2, RefreshCw } from 'lucide-react';
import { getCurrentUser } from '@/hooks/useAuth';

// ── Traditional Day Book (classic cash book) ───────────────────────────────
// Opening B/F → receipts / payments across Cash · Bank · CC → closing C/F.
// Backend: GET /api/v1/reports/day-book?date= · GET/PUT /reports/day-book-opening

interface Cols { cash: number; bank: number; cc: number }
interface Line { particulars: string; ref?: string | null; cash: number; bank: number; cc: number }
interface DayBook {
  date: string;
  opening: Cols;
  receipts: Line[];
  payments: Line[];
  totals: { receipts: Cols; payments: Cols };
  closing: Cols;
  notes?: string[];
}

import { todayISO } from '@/lib/dateLocal';
const INR = (v: number) => (v || 0) === 0 ? '—' : Number(v || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const today = () => todayISO();   // local wall-clock day (toISOString would give UTC)

export default function DayBookPage() {
  const isManager = ['admin', 'accountant'].includes(getCurrentUser()?.role || '');
  const [date, setDate] = useState(today());
  const [data, setData] = useState<DayBook | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');
  const [openCfg, setOpenCfg] = useState(false);

  const load = useCallback(() => {
    setLoading(true); setErr('');
    api.get<DayBook>(`/api/v1/reports/day-book?date=${date}`)
      .then(r => setData(r.data))
      .catch(() => { setData(null); setErr('Failed to load Day Book'); })
      .finally(() => setLoading(false));
  }, [date]);

  useEffect(() => { load(); }, [load]);

  function exportCsv() {
    if (!data) return;
    const rows: string[] = [];
    rows.push(`Day Book,${data.date}`);
    rows.push('');
    rows.push('Section,Particulars,Ref,Cash,Bank,CC');
    rows.push(`Opening B/F,,,"${data.opening.cash}","${data.opening.bank}","${data.opening.cc}"`);
    data.receipts.forEach(l => rows.push(`Receipt,"${l.particulars}","${l.ref || ''}","${l.cash}","${l.bank}","${l.cc}"`));
    data.payments.forEach(l => rows.push(`Payment,"${l.particulars}","${l.ref || ''}","${l.cash}","${l.bank}","${l.cc}"`));
    rows.push(`Total Receipts,,,"${data.totals.receipts.cash}","${data.totals.receipts.bank}","${data.totals.receipts.cc}"`);
    rows.push(`Total Payments,,,"${data.totals.payments.cash}","${data.totals.payments.bank}","${data.totals.payments.cc}"`);
    rows.push(`Closing C/F,,,"${data.closing.cash}","${data.closing.bank}","${data.closing.cc}"`);
    const blob = new Blob([rows.join('\n')], { type: 'text/csv' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = `day-book-${data.date}.csv`; a.click();
    URL.revokeObjectURL(a.href);
  }

  const ColHead = () => (
    <tr className="border-b bg-muted/50 text-xs uppercase tracking-wide">
      <th className="px-3 py-2 text-left font-semibold">Particulars</th>
      <th className="px-2 py-2 text-left font-semibold w-24">Voucher</th>
      <th className="px-3 py-2 text-right font-semibold w-28">Cash</th>
      <th className="px-3 py-2 text-right font-semibold w-28">Bank</th>
      <th className="px-3 py-2 text-right font-semibold w-28">CC / OD</th>
    </tr>
  );

  const Money = ({ v }: { v: number }) => <td className="px-3 py-1.5 text-right tabular-nums">{INR(v)}</td>;

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex flex-wrap items-end gap-3 print:hidden">
        <div className="space-y-1">
          <Label className="text-xs">Date</Label>
          <Input type="date" className="w-40" value={date} onChange={e => setDate(e.target.value)} />
        </div>
        <Button onClick={load} disabled={loading} variant="outline"><RefreshCw className="mr-2 h-4 w-4" />{loading ? 'Loading…' : 'Refresh'}</Button>
        <Button onClick={() => window.print()} disabled={!data}><Printer className="mr-2 h-4 w-4" />Print</Button>
        <Button onClick={exportCsv} disabled={!data} variant="outline"><Download className="mr-2 h-4 w-4" />CSV</Button>
        {isManager && (
          <Button onClick={() => setOpenCfg(true)} variant="ghost"><Settings2 className="mr-2 h-4 w-4" />Opening balance</Button>
        )}
      </div>

      {err && <p className="rounded bg-destructive/10 p-2 text-sm text-destructive print:hidden">{err}</p>}

      {data && (
        <Card className="print:border-0 print:shadow-none">
          <CardHeader className="pb-2 text-center">
            <CardTitle className="text-lg">DAY BOOK</CardTitle>
            <p className="text-sm text-muted-foreground">{new Date(data.date).toLocaleDateString('en-IN', { weekday: 'long', day: '2-digit', month: 'long', year: 'numeric' })}</p>
          </CardHeader>
          <CardContent className="space-y-6">
            {/* Receipts */}
            <div className="overflow-x-auto">
              <div className="text-sm font-semibold mb-1 text-emerald-700">RECEIPTS (Money In)</div>
              <table className="w-full min-w-max border text-sm">
                <thead><ColHead /></thead>
                <tbody>
                  <tr className="border-b bg-amber-50/60 font-medium">
                    <td className="px-3 py-1.5" colSpan={2}>Opening Balance B/F</td>
                    <Money v={data.opening.cash} /><Money v={data.opening.bank} /><Money v={data.opening.cc} />
                  </tr>
                  {data.receipts.length === 0 && (
                    <tr><td className="px-3 py-2 text-muted-foreground" colSpan={5}>No receipts</td></tr>
                  )}
                  {data.receipts.map((l, i) => (
                    <tr key={i} className="border-b">
                      <td className="px-3 py-1.5">{l.particulars}</td>
                      <td className="px-2 py-1.5 text-xs text-muted-foreground">{l.ref || ''}</td>
                      <Money v={l.cash} /><Money v={l.bank} /><Money v={l.cc} />
                    </tr>
                  ))}
                  <tr className="border-t-2 font-semibold bg-muted/40">
                    <td className="px-3 py-1.5" colSpan={2}>Total Receipts (incl. opening)</td>
                    <Money v={data.opening.cash + data.totals.receipts.cash} />
                    <Money v={data.opening.bank + data.totals.receipts.bank} />
                    <Money v={data.opening.cc + data.totals.receipts.cc} />
                  </tr>
                </tbody>
              </table>
            </div>

            {/* Payments */}
            <div className="overflow-x-auto">
              <div className="text-sm font-semibold mb-1 text-red-600">PAYMENTS (Money Out)</div>
              <table className="w-full min-w-max border text-sm">
                <thead><ColHead /></thead>
                <tbody>
                  {data.payments.length === 0 && (
                    <tr><td className="px-3 py-2 text-muted-foreground" colSpan={5}>No payments</td></tr>
                  )}
                  {data.payments.map((l, i) => (
                    <tr key={i} className="border-b">
                      <td className="px-3 py-1.5">{l.particulars}</td>
                      <td className="px-2 py-1.5 text-xs text-muted-foreground">{l.ref || ''}</td>
                      <Money v={l.cash} /><Money v={l.bank} /><Money v={l.cc} />
                    </tr>
                  ))}
                  <tr className="border-t font-semibold">
                    <td className="px-3 py-1.5" colSpan={2}>Sub Total (Payments)</td>
                    <Money v={data.totals.payments.cash} /><Money v={data.totals.payments.bank} /><Money v={data.totals.payments.cc} />
                  </tr>
                  <tr className="border-t-2 font-semibold bg-emerald-50/70">
                    <td className="px-3 py-1.5" colSpan={2}>Closing Balance C/F</td>
                    <Money v={data.closing.cash} /><Money v={data.closing.bank} /><Money v={data.closing.cc} />
                  </tr>
                </tbody>
              </table>
            </div>

            {data.notes && data.notes.length > 0 && (
              <div className="rounded-md border bg-muted/30 px-4 py-3 space-y-1 print:hidden">
                {data.notes.map((n, i) => <p key={i} className="text-[11px] text-muted-foreground">• {n}</p>)}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {isManager && <OpeningDialog open={openCfg} onClose={() => setOpenCfg(false)} onSaved={load} />}
    </div>
  );
}

// ── Opening-balance base dialog (admin/accountant) ─────────────────────────
function OpeningDialog({ open, onClose, onSaved }: { open: boolean; onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState({ as_of_date: today(), cash: '', bank: '', cc: '', note: '' });
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState('');

  useEffect(() => {
    if (!open) return;
    api.get('/api/v1/reports/day-book-opening').then(r => {
      const d = r.data || {};
      setForm({
        as_of_date: d.as_of_date || today(),
        cash: d.cash != null ? String(d.cash) : '',
        bank: d.bank != null ? String(d.bank) : '',
        cc: d.cc != null ? String(d.cc) : '',
        note: d.note || '',
      });
    }).catch(() => {});
  }, [open]);

  async function save() {
    setSaving(true); setMsg('');
    try {
      await api.put('/api/v1/reports/day-book-opening', {
        as_of_date: form.as_of_date,
        cash: form.cash === '' ? 0 : Number(form.cash),
        bank: form.bank === '' ? 0 : Number(form.bank),
        cc: form.cc === '' ? 0 : Number(form.cc),
        note: form.note,
      });
      onSaved(); onClose();
    } catch {
      setMsg('Save failed (admin/accountant only)');
    } finally { setSaving(false); }
  }

  const set = (k: string, v: string) => setForm(f => ({ ...f, [k]: v }));

  return (
    <Dialog open={open} onOpenChange={v => !v && onClose()}>
      <DialogContent>
        <DialogHeader><DialogTitle>Day Book — Opening Balance</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <p className="text-xs text-muted-foreground">
            Enter the cash-in-hand, bank (current a/c) and CC/OD balances as of a start date.
            The Day Book rolls these forward automatically — each day's closing becomes the next day's opening.
          </p>
          <div className="space-y-1">
            <Label className="text-xs">As of date</Label>
            <Input type="date" value={form.as_of_date} onChange={e => set('as_of_date', e.target.value)} />
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div className="space-y-1"><Label className="text-xs">Cash ₹</Label><Input type="number" step="0.01" value={form.cash} onChange={e => set('cash', e.target.value)} /></div>
            <div className="space-y-1"><Label className="text-xs">Bank ₹</Label><Input type="number" step="0.01" value={form.bank} onChange={e => set('bank', e.target.value)} /></div>
            <div className="space-y-1"><Label className="text-xs">CC / OD ₹</Label><Input type="number" step="0.01" value={form.cc} onChange={e => set('cc', e.target.value)} /></div>
          </div>
          <div className="space-y-1"><Label className="text-xs">Note</Label><Input value={form.note} onChange={e => set('note', e.target.value)} /></div>
          {msg && <p className="text-sm text-destructive">{msg}</p>}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Save'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
