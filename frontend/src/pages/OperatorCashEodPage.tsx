/**
 * Operator Cash — End of Day.
 *
 * Per-operator cash-in-hand for the day: cash COLLECTED (cash receipts they
 * recorded) vs cash HANDED OVER & acknowledged, and the BALANCE still to hand
 * over. The accountant/admin records + acknowledges each handover (audit trail).
 *
 *   GET  /api/v1/reports/operator-cash-eod?date=
 *   POST /api/v1/reports/cash-handover           (record + acknowledge)
 *   GET  /api/v1/reports/cash-handover?date=
 */
import { useEffect, useState, useCallback } from 'react';
import { Loader2, AlertCircle, Calendar, Wallet, HandCoins, Scale, CheckCircle2 } from 'lucide-react';
import { toast } from 'sonner';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { DataTable, type ColumnDef, downloadCsv } from '@/components/DataTable';
import api from '@/services/api';
import { getCurrentUser } from '@/hooks/useAuth';

interface OpRow {
  operator_id: string | null;
  operator_name: string;
  receipts: number;
  cash_total: number;
  handed_over: number;
  balance: number;
}
interface EodResp {
  date: string;
  operators: OpRow[];
  total_cash: number;
  total_handed_over: number;
  total_balance: number;
}
interface Handover {
  id: string;
  operator_name: string | null;
  amount: number;
  status: string;
  received_by_name: string | null;
  acknowledged_at: string | null;
  notes: string | null;
}

// Cash reconciliation → show paise (2dp), never drop sub-rupee differences.
const INR = (v: number | string | null | undefined) =>
  '₹' + Number(v ?? 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
import { todayISO } from '@/lib/dateLocal';   // local wall-clock day (toISOString → UTC)

export default function OperatorCashEodPage() {
  const [date, setDate] = useState(todayISO());
  const [data, setData] = useState<EodResp | null>(null);
  const [handovers, setHandovers] = useState<Handover[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dlg, setDlg] = useState<OpRow | null>(null);
  const [amount, setAmount] = useState('');
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const role = getCurrentUser()?.role ?? '';
  const canReceive = ['admin', 'accountant', 'store_manager'].includes(role);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const [r1, r2] = await Promise.all([
        api.get<EodResp>(`/api/v1/reports/operator-cash-eod?date=${date}`),
        api.get<{ handovers: Handover[] }>(`/api/v1/reports/cash-handover?date=${date}`),
      ]);
      setData(r1.data);
      setHandovers(r2.data.handovers ?? []);
    } catch (e: unknown) {
      const d = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof d === 'string' ? d : 'Failed to load operator cash');
    } finally {
      setLoading(false);
    }
  }, [date]);

  useEffect(() => { load(); }, [load]);

  function openHandover(op: OpRow) {
    setDlg(op);
    setAmount(op.balance > 0 ? op.balance.toFixed(2) : '');   // exact paise, no rounding
    setNotes('');
  }

  async function recordHandover() {
    if (!dlg) return;
    const amt = parseFloat(amount);
    if (!amt || amt <= 0) { toast.error('Enter a valid amount'); return; }
    setSaving(true);
    try {
      await api.post('/api/v1/reports/cash-handover', {
        operator_id: dlg.operator_id,
        operator_name: dlg.operator_name,
        amount: amt,
        handover_date: date,
        notes: notes || undefined,
        acknowledge: true,
      });
      toast.success(`${INR(amt)} from ${dlg.operator_name} acknowledged & recorded.`);
      setDlg(null);
      load();
    } catch (e: unknown) {
      const d = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(typeof d === 'string' ? d : 'Failed to record handover');
    } finally {
      setSaving(false);
    }
  }

  const cols: ColumnDef<OpRow>[] = [
    { key: 'operator_name', label: 'Operator', accessor: r => r.operator_name },
    { key: 'receipts', label: 'Receipts', type: 'number', align: 'right', accessor: r => r.receipts },
    { key: 'cash_total', label: 'Cash Collected', type: 'number', align: 'right', accessor: r => r.cash_total,
      format: v => <span className="text-emerald-700 font-medium">{INR(v as number)}</span>, exportValue: r => r.cash_total },
    { key: 'handed_over', label: 'Handed Over', type: 'number', align: 'right', accessor: r => r.handed_over,
      format: v => INR(v as number), exportValue: r => r.handed_over },
    { key: 'balance', label: 'Balance to Hand Over', type: 'number', align: 'right', accessor: r => r.balance,
      format: v => {
        const n = Number(v);
        // >0 = still owed to accounts; <0 = OVER-handed (anomaly) → flag amber, not "settled".
        if (n < -0.005) return <span className="text-amber-700 font-semibold" title="Handed over MORE than collected — check for a duplicate/back-dated handover">⚠ {INR(Math.abs(n))} over</span>;
        return <span className={n > 0.005 ? 'text-rose-700 font-semibold' : 'text-emerald-600'}>{INR(n)}</span>;
      }, exportValue: r => r.balance },
    ...(canReceive ? [{
      key: 'act', label: '', accessor: (r: OpRow) => '',
      format: (_v: unknown, r: OpRow) => r.balance > 0
        ? <Button size="sm" variant="outline" className="h-7 gap-1 text-xs" onClick={() => openHandover(r)}><HandCoins className="h-3.5 w-3.5" /> Receive cash</Button>
        : <span className="text-emerald-600 text-xs flex items-center gap-1"><CheckCircle2 className="h-3.5 w-3.5" /> settled</span>,
    } as ColumnDef<OpRow>] : []),
  ];

  function exportCsv() {
    if (!data) return;
    const header = ['Operator', 'Receipts', 'Cash Collected', 'Handed Over', 'Balance'];
    const rows = data.operators.map(o => [o.operator_name, String(o.receipts), String(o.cash_total), String(o.handed_over), String(o.balance)]);
    downloadCsv(`operator-cash-${date}.csv`, [header, ...rows]);
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3 p-3 rounded-lg border bg-card">
        <div className="space-y-1">
          <label className="text-xs font-medium text-muted-foreground flex items-center gap-1"><Calendar className="h-3 w-3" /> Date</label>
          <Input type="date" value={date} onChange={e => setDate(e.target.value)} className="h-8 w-40 text-sm" />
        </div>
        <Button variant="ghost" size="sm" className="h-8 text-xs" onClick={() => setDate(todayISO())}>Today</Button>
        <Button onClick={load} disabled={loading} variant="outline" size="sm">{loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : 'Refresh'}</Button>
        <Button onClick={exportCsv} disabled={!data} variant="outline" size="sm" className="ml-auto">Export CSV</Button>
      </div>

      <p className="text-xs text-muted-foreground -mt-1">
        Cash each operator collected today vs what they've handed over to accounts. The accountant taps
        <b> Receive cash</b> to acknowledge a handover — it's recorded with their name + time as the audit trail.
      </p>

      {error && <div className="rounded-lg border-2 border-rose-300 bg-rose-50 px-4 py-3 text-rose-800 flex items-center gap-2"><AlertCircle className="h-5 w-5 shrink-0" /> {error}</div>}

      {data && (
        <div className="grid grid-cols-3 gap-3">
          <Card><CardContent className="p-4">
            <div className="text-xs uppercase tracking-widest text-slate-500 font-semibold flex items-center gap-1"><Wallet className="h-3.5 w-3.5 text-emerald-500" /> Collected</div>
            <div className="text-2xl font-bold text-emerald-700 mt-1">{INR(data.total_cash)}</div>
          </CardContent></Card>
          <Card><CardContent className="p-4">
            <div className="text-xs uppercase tracking-widest text-slate-500 font-semibold flex items-center gap-1"><HandCoins className="h-3.5 w-3.5 text-sky-500" /> Handed Over</div>
            <div className="text-2xl font-bold text-sky-700 mt-1">{INR(data.total_handed_over)}</div>
          </CardContent></Card>
          <Card><CardContent className="p-4">
            <div className="text-xs uppercase tracking-widest text-slate-500 font-semibold flex items-center gap-1"><Scale className="h-3.5 w-3.5 text-rose-500" /> Balance</div>
            <div className={`text-2xl font-bold mt-1 ${data.total_balance > 0 ? 'text-rose-700' : 'text-emerald-700'}`}>{INR(data.total_balance)}</div>
          </CardContent></Card>
        </div>
      )}

      {data && (
        <Card><CardContent className="p-0">
          <div className="text-sm font-semibold text-slate-700 px-3 pt-3 pb-1">Per operator</div>
          <DataTable<OpRow> id="operator.cash.eod" data={data.operators} columns={cols} rowKey={r => r.operator_id ?? r.operator_name}
            defaultSort={{ key: 'cash_total', direction: 'desc' }} exportFilename={`operator-cash-${date}`}
            emptyMessage="No cash collected on this day." />
        </CardContent></Card>
      )}

      {handovers.length > 0 && (
        <Card><CardContent className="p-3">
          <div className="text-sm font-semibold text-slate-700 mb-2">Handovers acknowledged today</div>
          <ul className="space-y-1.5 text-sm">
            {handovers.map(h => (
              <li key={h.id} className="flex items-center justify-between rounded-md border px-3 py-1.5">
                <span>{h.operator_name ?? 'Operator'} → <b>{h.received_by_name ?? '—'}</b>{h.notes ? <span className="text-muted-foreground text-xs"> · {h.notes}</span> : null}</span>
                <span className="flex items-center gap-2">
                  <b className="font-mono">{INR(h.amount)}</b>
                  {h.status === 'acknowledged'
                    ? <span className="text-emerald-600 text-xs flex items-center gap-1"><CheckCircle2 className="h-3.5 w-3.5" /> acknowledged</span>
                    : <span className="text-amber-600 text-xs">pending</span>}
                </span>
              </li>
            ))}
          </ul>
        </CardContent></Card>
      )}

      {/* Record handover dialog */}
      <Dialog open={dlg !== null} onOpenChange={(o) => { if (!o) setDlg(null); }}>
        <DialogContent className="max-w-sm">
          <DialogHeader><DialogTitle>Receive cash from {dlg?.operator_name}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <p className="text-xs text-muted-foreground">
              Collected {INR(dlg?.cash_total)} · already handed {INR(dlg?.handed_over)} · balance {INR(dlg?.balance)}.
            </p>
            <div className="space-y-1">
              <label className="text-xs font-medium">Amount received (₹)</label>
              <Input type="number" min="0" value={amount} onChange={e => setAmount(e.target.value)} />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium">Note (optional)</label>
              <Input value={notes} onChange={e => setNotes(e.target.value)} placeholder="e.g. deposited to bank / denomination" />
            </div>
            <Button onClick={recordHandover} disabled={saving} className="w-full gap-1.5">
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
              Acknowledge &amp; record {amount ? INR(parseFloat(amount)) : ''}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
