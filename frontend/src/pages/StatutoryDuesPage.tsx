import { useState, useEffect, useCallback, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';
import { Landmark, Plus, Trash2, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { DataTable, type ColumnDef } from '@/components/DataTable';
import { getCurrentUser } from '@/hooks/useAuth';
import { todayISO, monthStartISO } from '@/lib/dateLocal';
import api from '@/services/api';

type Kind = 'royalty' | 'gst';

interface StatDoc {
  invoice_id: string | null;
  invoice_no: string | null;
  invoice_date: string;
  invoice_type?: string;
  party_name: string | null;
  amount: number;
  grand_total: number;
  item: string | null;
  item_qty: number | null;
  item_unit: string | null;
  item_rate: number | null;      // blank on a multi-line invoice — see the backend note
  vehicle_rent: number;
}
interface StatPayment {
  id: string;
  amount: number;
  paid_on: string;
  mode: string | null;
  reference: string | null;
  period_from: string | null;
  period_to: string | null;
  notes: string | null;
  created_by_name: string | null;
}
interface DuesResponse {
  kind: Kind;
  opening_due: number;
  accrued: number;
  paid: number;
  closing_due: number;
  breakdown: { output_tax?: number; itc?: number };
  documents: StatDoc[];
  payments: StatPayment[];
  notes: string[];
}

const INR = (v: number | string | null | undefined) =>
  '₹' + Number(v ?? 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function Kpi({ title, value, hint, tone = 'default' }: {
  title: string; value: string; hint?: string; tone?: 'default' | 'due' | 'paid';
}) {
  const colour = tone === 'due' ? 'text-rose-600' : tone === 'paid' ? 'text-emerald-600' : 'text-slate-800';
  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-[11px] uppercase tracking-wider text-muted-foreground">{title}</p>
        <p className={`mt-1 text-xl font-bold ${colour}`}>{value}</p>
        {hint && <p className="mt-0.5 text-[11px] text-muted-foreground">{hint}</p>}
      </CardContent>
    </Card>
  );
}

export default function StatutoryDuesPage() {
  const [kind, setKind] = useState<Kind>('royalty');
  const [from, setFrom] = useState(monthStartISO());
  const [to, setTo] = useState(todayISO());
  const [data, setData] = useState<DuesResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');
  const [payOpen, setPayOpen] = useState(false);
  const [saving, setSaving] = useState(false);

  const role = getCurrentUser()?.role;
  const canPay = role === 'admin' || role === 'accountant';
  const label = kind === 'royalty' ? 'Royalty' : 'GST';

  const [form, setForm] = useState({
    amount: '', paid_on: todayISO(), mode: 'bank', reference: '', notes: '',
  });

  const load = useCallback(async () => {
    setLoading(true); setErr('');
    try {
      const { data } = await api.get<DuesResponse>(
        `/api/v1/reports/statutory-dues?${new URLSearchParams({ kind, from_date: from, to_date: to })}`);
      setData(data);
    } catch (e) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setErr(msg || 'Could not load the report');
    } finally { setLoading(false); }
  }, [kind, from, to]);

  useEffect(() => { load(); }, [load]);

  async function savePayment() {
    if (!Number(form.amount)) { toast.error('Enter an amount'); return; }
    setSaving(true);
    try {
      await api.post('/api/v1/reports/statutory-payments', {
        kind, amount: form.amount, paid_on: form.paid_on, mode: form.mode,
        reference: form.reference, notes: form.notes,
        period_from: from, period_to: to,
      });
      toast.success(`${label} payment recorded`);
      setPayOpen(false);
      setForm({ amount: '', paid_on: todayISO(), mode: 'bank', reference: '', notes: '' });
      load();
    } catch (e) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(msg || 'Could not record the payment');
    } finally { setSaving(false); }
  }

  async function removePayment(p: StatPayment) {
    if (!confirm(`Delete this ${label} payment of ${INR(p.amount)} dated ${p.paid_on}?`)) return;
    try {
      await api.delete(`/api/v1/reports/statutory-payments/${p.id}`);
      toast.success('Payment removed');
      load();
    } catch {
      toast.error('Could not remove the payment');
    }
  }

  const docCols = useMemo<ColumnDef<StatDoc>[]>(() => {
    const cols: ColumnDef<StatDoc>[] = [
      { key: 'invoice_no', label: 'Invoice', accessor: r => r.invoice_no ?? '—',
        format: (v, r) => r.invoice_id
          ? <Link to={`/invoices/${r.invoice_id}/detail`}
                  className="font-mono text-xs font-medium text-primary hover:underline">
              {String(v ?? '—')}
            </Link>
          : <span className="font-mono text-xs">{String(v ?? '—')}</span>,
        exportValue: r => r.invoice_no ?? '' },
      { key: 'invoice_date', label: 'Date', type: 'date', accessor: r => r.invoice_date },
      { key: 'party_name', label: 'Party', accessor: r => r.party_name ?? '—' },
    ];
    if (kind === 'gst') {
      cols.push({ key: 'invoice_type', label: 'Type', type: 'enum',
        enumOptions: ['sale', 'purchase', 'credit_note', 'debit_note'],
        accessor: r => r.invoice_type ?? '—' });
    }
    cols.push(
      { key: 'item', label: 'Material', accessor: r => r.item ?? '—' },
      { key: 'item_qty', label: 'Qty', type: 'number', align: 'right', accessor: r => r.item_qty,
        format: (v, r) => v == null ? '—' : `${Number(v).toLocaleString('en-IN')}${r.item_unit ? ' ' + r.item_unit : ''}`,
        exportValue: r => r.item_qty ?? '' },
      { key: 'item_rate', label: 'Rate', type: 'number', align: 'right', accessor: r => r.item_rate,
        format: (v, r) => v == null ? '—' : `${INR(Number(v))}${r.item_unit ? '/' + r.item_unit : ''}`,
        exportValue: r => r.item_rate ?? '' },
      { key: 'vehicle_rent', label: 'Vehicle Rent', type: 'number', align: 'right',
        accessor: r => r.vehicle_rent,
        format: v => Number(v ?? 0) ? INR(Number(v)) : '—', exportValue: r => r.vehicle_rent ?? 0 },
      { key: 'amount', label: kind === 'royalty' ? 'Royalty' : 'Tax', type: 'number', align: 'right',
        accessor: r => r.amount, format: v => INR(v as number), exportValue: r => r.amount },
      { key: 'grand_total', label: 'Invoice total', type: 'number', align: 'right',
        defaultVisible: false, accessor: r => r.grand_total,
        format: v => INR(v as number), exportValue: r => r.grand_total },
    );
    return cols;
  }, [kind]);

  const payCols = useMemo<ColumnDef<StatPayment>[]>(() => [
    { key: 'paid_on', label: 'Paid on', type: 'date', accessor: r => r.paid_on },
    { key: 'amount', label: 'Amount', type: 'number', align: 'right', accessor: r => r.amount,
      format: v => INR(v as number), exportValue: r => r.amount },
    { key: 'mode', label: 'Mode', type: 'enum', enumOptions: ['cash', 'bank', 'upi', 'cheque'],
      accessor: r => r.mode ?? '—' },
    { key: 'reference', label: 'Challan / Ref', accessor: r => r.reference ?? '—' },
    { key: 'period', label: 'For period', accessor: r =>
        r.period_from && r.period_to ? `${r.period_from} → ${r.period_to}` : '—' },
    { key: 'created_by_name', label: 'Recorded by', accessor: r => r.created_by_name ?? '—' },
    { key: 'notes', label: 'Notes', defaultVisible: false, accessor: r => r.notes ?? '' },
  ], []);

  const preset = (f: string, t: string) => { setFrom(f); setTo(t); };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight flex items-center gap-2">
            <Landmark className="h-6 w-6 text-violet-600" /> Government Dues
          </h1>
          <p className="text-sm text-muted-foreground">
            Royalty and GST collected on finalised bills, what has been paid, and what is still owed.
          </p>
        </div>
        {canPay && (
          <Button onClick={() => setPayOpen(true)}>
            <Plus className="mr-1.5 h-4 w-4" /> Record {label} payment
          </Button>
        )}
      </div>

      {/* Which due, and over what period */}
      <div className="flex flex-wrap items-end gap-2">
        <div className="inline-flex rounded-md border p-0.5">
          {(['royalty', 'gst'] as const).map(k => (
            <button key={k} onClick={() => setKind(k)}
              className={`px-3 py-1.5 text-sm rounded ${kind === k ? 'bg-primary text-primary-foreground' : 'text-muted-foreground'}`}>
              {k === 'royalty' ? 'Royalty' : 'GST'}
            </button>
          ))}
        </div>
        <div>
          <Label className="text-xs">From</Label>
          <Input type="date" value={from} onChange={e => setFrom(e.target.value)} className="h-8 w-[150px]" />
        </div>
        <div>
          <Label className="text-xs">To</Label>
          <Input type="date" value={to} onChange={e => setTo(e.target.value)} className="h-8 w-[150px]" />
        </div>
        <Button variant="outline" size="sm" onClick={() => preset(monthStartISO(), todayISO())}>This month</Button>
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          <RefreshCw className={`mr-1 h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </Button>
      </div>

      {err && <div className="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm text-destructive">{err}</div>}

      {/* Opening carries the previous period's balance forward, which is the whole
          point of the report: a due does not disappear when the month rolls over. */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi title="Due from previous period" value={INR(data?.opening_due)} tone="due"
             hint={`Up to ${from}`} />
        <Kpi title={`${label} this period`} value={INR(data?.accrued)}
             hint={kind === 'gst' && data?.breakdown
               ? `Output ${INR(data.breakdown.output_tax)} − ITC ${INR(data.breakdown.itc)}`
               : 'Finalised bills only'} />
        <Kpi title="Paid this period" value={INR(data?.paid)} tone="paid" />
        <Kpi title="Still owed" value={INR(data?.closing_due)} tone="due"
             hint="Opening + this period − paid" />
      </div>

      <Card>
        <CardHeader className="pb-2">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0">
              <CardTitle className="text-base">Payments to government</CardTitle>
              <CardDescription>
                Each payment shows as money out in the Day Book on its payment date.
              </CardDescription>
            </div>
            {/* Recording is offered here as well as in the header — this card is
                where the accountant is already looking when they settle a challan. */}
            {canPay && (
              <Button size="sm" onClick={() => setPayOpen(true)}>
                <Plus className="mr-1.5 h-4 w-4" /> Record {label} payment
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent>
          <DataTable<StatPayment>
            id={`statutory.payments.${kind}`}
            data={data?.payments ?? []}
            columns={payCols}
            rowKey={r => r.id}
            exportFilename={`${kind}-payments-${from}-${to}`}
            defaultSort={{ key: 'paid_on', direction: 'desc' }}
            emptyMessage={`No ${label} payments recorded in this period`}
            rowActions={canPay ? (r => (
              <Button variant="ghost" size="sm" onClick={() => removePayment(r)}
                      title="Delete this payment">
                <Trash2 className="h-3.5 w-3.5 text-destructive" />
              </Button>
            )) : undefined}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">
            What makes up {INR(data?.accrued)} {kind === 'royalty' ? 'of royalty' : 'of GST'}
          </CardTitle>
          <CardDescription>
            Finalised bills in this period. Drafts, cancelled and superseded bills are excluded.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <DataTable<StatDoc>
            id={`statutory.docs.${kind}`}
            data={data?.documents ?? []}
            columns={docCols}
            rowKey={(r, i) => `${r.invoice_no ?? 'x'}-${i}`}
            exportFilename={`${kind}-accrual-${from}-${to}`}
            defaultSort={{ key: 'invoice_date', direction: 'desc' }}
            emptyMessage="No finalised bills in this period"
          />
        </CardContent>
      </Card>

      {data?.notes?.length ? (
        <div className="rounded-md border bg-muted/30 px-3 py-2 text-xs text-muted-foreground space-y-1">
          {data.notes.map((n, i) => <p key={i}>• {n}</p>)}
        </div>
      ) : null}

      <Dialog open={payOpen} onOpenChange={setPayOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>Record {label} payment to government</DialogTitle></DialogHeader>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <Label>Amount</Label>
              <Input type="number" step="0.01" value={form.amount} placeholder="0.00"
                     onChange={e => setForm(f => ({ ...f, amount: e.target.value }))} />
            </div>
            <div>
              <Label>Paid on</Label>
              <Input type="date" value={form.paid_on}
                     onChange={e => setForm(f => ({ ...f, paid_on: e.target.value }))} />
            </div>
            <div>
              <Label>Mode</Label>
              <Select value={form.mode} onValueChange={v => setForm(f => ({ ...f, mode: v ?? 'bank' }))}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {['bank', 'cash', 'upi', 'cheque'].map(m => (
                    <SelectItem key={m} value={m}>{m.toUpperCase()}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>Challan / reference</Label>
              <Input value={form.reference} placeholder="CIN / challan no"
                     onChange={e => setForm(f => ({ ...f, reference: e.target.value }))} />
            </div>
            <div className="sm:col-span-2">
              <Label>Notes</Label>
              <Input value={form.notes}
                     onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} />
            </div>
          </div>
          <p className="text-xs text-muted-foreground">
            Recorded against the period {from} → {to}. It will appear as money out in the Day Book
            on {form.paid_on || 'the payment date'}.
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPayOpen(false)}>Cancel</Button>
            <Button onClick={savePayment} disabled={saving}>{saving ? 'Saving…' : 'Save payment'}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
