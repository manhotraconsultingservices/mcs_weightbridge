import { useState } from 'react';
import api from '@/services/api';
import { toast } from 'sonner';
import { Upload, Loader2, CheckCircle2, AlertTriangle, FileWarning, FileQuestion } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

interface Row { gstin: string; supplier: string; inv_no: string; inv_date: string; taxable: number; igst: number; cgst: number; sgst: number; total_tax: number; book_tax?: number; book_taxable?: number; diff_tax?: number }
interface Result {
  summary: {
    twob_count: number; twob_taxable: number; twob_total_tax: number;
    books_count: number; matched_count: number; matched_tax: number;
    value_mismatch_count: number;
    in_2b_not_books_count: number; in_2b_not_books_tax: number;
    in_books_not_2b_count: number; in_books_not_2b_tax: number;
  };
  matched: Row[]; value_mismatch: Row[]; in_2b_not_books: Row[]; in_books_not_2b: Row[];
}

const INR = (v: number) => '₹' + Number(v ?? 0).toLocaleString('en-IN', { minimumFractionDigits: 2 });
type Tab = 'matched' | 'value_mismatch' | 'in_2b_not_books' | 'in_books_not_2b';

export default function Gstr2bReconcilePage() {
  const [file, setFile] = useState<File | null>(null);
  const [range, setRange] = useState({ from: '', to: '' });
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<Result | null>(null);
  const [tab, setTab] = useState<Tab>('in_2b_not_books');

  async function run() {
    if (!file) { toast.error('Choose your GSTR-2B JSON file first'); return; }
    setBusy(true); setRes(null);
    try {
      const fd = new FormData();
      fd.append('file', file);
      const params: Record<string, string> = {};
      if (range.from) params.date_from = range.from;
      if (range.to) params.date_to = range.to;
      const r = await api.post<Result>('/api/v1/reports/gstr2b-reconcile', fd, {
        params, headers: { 'Content-Type': 'multipart/form-data' },
      });
      setRes(r.data);
      toast.success('Reconciliation complete');
    } catch (e: unknown) {
      toast.error((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Reconcile failed');
    } finally { setBusy(false); }
  }

  const TABS: { k: Tab; label: string; rows: Row[]; icon: typeof CheckCircle2; tone: string }[] = res ? [
    { k: 'in_2b_not_books', label: `In 2B, not in books (${res.in_2b_not_books.length})`, rows: res.in_2b_not_books, icon: FileQuestion, tone: 'text-blue-700' },
    { k: 'in_books_not_2b', label: `In books, not in 2B (${res.in_books_not_2b.length})`, rows: res.in_books_not_2b, icon: FileWarning, tone: 'text-amber-700' },
    { k: 'value_mismatch', label: `Value mismatch (${res.value_mismatch.length})`, rows: res.value_mismatch, icon: AlertTriangle, tone: 'text-rose-700' },
    { k: 'matched', label: `Matched (${res.matched.length})`, rows: res.matched, icon: CheckCircle2, tone: 'text-emerald-700' },
  ] : [];
  const activeRows = TABS.find(t => t.k === tab)?.rows ?? [];

  return (
    <div className="p-4 space-y-4">
      <div>
        <h1 className="text-xl font-bold">GSTR-2B Reconciliation</h1>
        <p className="text-xs text-muted-foreground">Upload the GSTR-2B JSON from the GST portal and match it against your purchase invoices to verify ITC.</p>
      </div>

      <div className="rounded-lg border p-4 flex flex-wrap items-end gap-3">
        <div className="space-y-1">
          <Label className="text-xs">GSTR-2B JSON</Label>
          <Input type="file" accept=".json,application/json" onChange={e => setFile(e.target.files?.[0] ?? null)} className="text-xs" />
        </div>
        <div className="space-y-1"><Label className="text-xs">From (optional)</Label><Input type="date" value={range.from} onChange={e => setRange(r => ({ ...r, from: e.target.value }))} className="h-9 w-40 text-xs" /></div>
        <div className="space-y-1"><Label className="text-xs">To (optional)</Label><Input type="date" value={range.to} onChange={e => setRange(r => ({ ...r, to: e.target.value }))} className="h-9 w-40 text-xs" /></div>
        <Button onClick={run} disabled={busy} className="gap-1.5">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />} Reconcile</Button>
      </div>

      {res && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div className="rounded-lg border p-3"><p className="text-[11px] text-muted-foreground">2B ITC (total tax)</p><p className="text-lg font-bold">{INR(res.summary.twob_total_tax)}</p><p className="text-[10px] text-muted-foreground">{res.summary.twob_count} invoices</p></div>
            <div className="rounded-lg border p-3 bg-emerald-50 border-emerald-200"><p className="text-[11px] text-muted-foreground">Matched ITC</p><p className="text-lg font-bold text-emerald-700">{INR(res.summary.matched_tax)}</p><p className="text-[10px] text-muted-foreground">{res.summary.matched_count} invoices</p></div>
            <div className="rounded-lg border p-3 bg-blue-50 border-blue-200"><p className="text-[11px] text-muted-foreground">ITC available, not booked</p><p className="text-lg font-bold text-blue-700">{INR(res.summary.in_2b_not_books_tax)}</p><p className="text-[10px] text-muted-foreground">{res.summary.in_2b_not_books_count} invoices → enter these</p></div>
            <div className="rounded-lg border p-3 bg-amber-50 border-amber-200"><p className="text-[11px] text-muted-foreground">ITC at risk (not in 2B)</p><p className="text-lg font-bold text-amber-700">{INR(res.summary.in_books_not_2b_tax)}</p><p className="text-[10px] text-muted-foreground">{res.summary.in_books_not_2b_count} invoices → chase supplier</p></div>
          </div>

          <div className="flex gap-1 flex-wrap">
            {TABS.map(t => {
              const Icon = t.icon;
              return (
                <button key={t.k} onClick={() => setTab(t.k)} className={`px-3 py-1.5 rounded-md text-xs font-medium flex items-center gap-1.5 border ${tab === t.k ? 'bg-slate-900 text-white' : 'bg-white hover:bg-slate-50'}`}>
                  <Icon className={`h-3.5 w-3.5 ${tab === t.k ? '' : t.tone}`} /> {t.label}
                </button>
              );
            })}
          </div>

          <div className="rounded-lg border overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted/40 text-xs"><tr className="[&>th]:px-3 [&>th]:py-2 [&>th]:text-left"><th>GSTIN</th><th>Supplier</th><th>Invoice</th><th>Date</th><th className="text-right">Taxable</th><th className="text-right">Tax (2B)</th>{tab === 'value_mismatch' && <th className="text-right">Tax (books)</th>}{tab === 'value_mismatch' && <th className="text-right">Diff</th>}</tr></thead>
              <tbody>
                {activeRows.length === 0 && <tr><td colSpan={8} className="px-3 py-6 text-center text-muted-foreground">Nothing in this bucket — clean.</td></tr>}
                {activeRows.map((r, i) => (
                  <tr key={i} className="border-t [&>td]:px-3 [&>td]:py-2">
                    <td className="font-mono text-xs">{r.gstin}</td>
                    <td className="max-w-[180px] truncate">{r.supplier || '—'}</td>
                    <td className="font-mono text-xs">{r.inv_no}</td>
                    <td className="text-xs">{r.inv_date}</td>
                    <td className="text-right">{INR(r.taxable)}</td>
                    <td className="text-right">{INR(r.total_tax)}</td>
                    {tab === 'value_mismatch' && <td className="text-right">{INR(r.book_tax ?? 0)}</td>}
                    {tab === 'value_mismatch' && <td className={`text-right font-medium ${(r.diff_tax ?? 0) !== 0 ? 'text-rose-600' : ''}`}>{INR(r.diff_tax ?? 0)}</td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
