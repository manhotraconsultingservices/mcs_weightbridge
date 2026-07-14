/**
 * Workforce & Payroll — workers (non-login), attendance muster, payments.
 *
 * Tabs: Workers · Attendance (Excel muster grid) · Payments · Payroll · Settings.
 * The weighbridge as system-of-record for labour cost: attendance-driven Earned
 * vs Paid (advances netted) → Balance Due per worker.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Users, Plus, Loader2, CalendarCheck, IndianRupee, ClipboardList, Settings2 } from 'lucide-react';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { MobileTabSelect } from '@/components/MobileTabSelect';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { DataTable, type ColumnDef } from '@/components/DataTable';
import api from '@/services/api';

const today = () => new Date().toISOString().split('T')[0];
const thisMonth = () => today().slice(0, 7);
const monthStart = (m: string) => `${m}-01`;
const monthEnd = (m: string) => { const [y, mm] = m.split('-').map(Number); return `${m}-${String(new Date(y, mm, 0).getDate()).padStart(2, '0')}`; };
const INR = (v: number | null | undefined) => '₹' + Number(v ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 0 });
const num = (v: number | null | undefined, d = 2) => v == null ? '—' : Number(v).toLocaleString('en-IN', { minimumFractionDigits: d, maximumFractionDigits: d });

interface Worker {
  id: string; name: string; phone: string | null; worker_type: string; rate: number;
  designation: string | null; joining_date: string | null; aadhaar_no: string | null;
  is_active: boolean; notes: string | null;
}
interface Payment {
  id: string; worker_id: string; worker_name: string | null; pay_date: string;
  payment_type: string; amount: number; mode: string; reference: string | null; notes: string | null;
}
interface SummaryRow {
  worker_id: string; name: string; worker_type: string; rate: number;
  days_units: number | null; earned: number; advances: number; settled: number;
  deductions: number; total_paid: number; balance_due: number;
}
interface AttWorker {
  worker_id: string; name: string; worker_type: string; rate: number;
  attendance: Record<string, { status: string; ot_hours: number }>; units: number | null; earned: number;
}

const TYPE_LABEL: Record<string, string> = { daily_wage: 'Daily wage', monthly_salary: 'Monthly salary' };
const PAY_LABEL: Record<string, string> = { advance: 'Advance', wage: 'Wage', salary: 'Salary', bonus: 'Bonus', deduction: 'Deduction' };
// muster cell cycle: blank → P → A → ½ → OT → blank
const NEXT_STATUS: Record<string, string> = { '': 'present', present: 'absent', absent: 'half_day', half_day: 'overtime', overtime: '' };
const CELL: Record<string, { t: string; c: string }> = {
  present:  { t: 'P',  c: 'bg-emerald-100 text-emerald-700' },
  absent:   { t: 'A',  c: 'bg-red-100 text-red-700' },
  half_day: { t: '½',  c: 'bg-amber-100 text-amber-700' },
  overtime: { t: 'OT', c: 'bg-blue-100 text-blue-700' },
  '':       { t: '',   c: 'hover:bg-muted' },
};

// ── Worker dialog ─────────────────────────────────────────────────────────────
function WorkerDialog({ open, editing, onClose, onSaved }: {
  open: boolean; editing: Worker | null; onClose: () => void; onSaved: () => void;
}) {
  const [form, setForm] = useState({ name: '', phone: '', worker_type: 'daily_wage', rate: 0, designation: '', joining_date: '', aadhaar_no: '', notes: '' });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    if (open) {
      setForm(editing ? {
        name: editing.name, phone: editing.phone ?? '', worker_type: editing.worker_type, rate: Number(editing.rate),
        designation: editing.designation ?? '', joining_date: editing.joining_date ?? '', aadhaar_no: editing.aadhaar_no ?? '', notes: editing.notes ?? '',
      } : { name: '', phone: '', worker_type: 'daily_wage', rate: 0, designation: '', joining_date: '', aadhaar_no: '', notes: '' });
      setError('');
    }
  }, [open, editing]);
  const set = (k: string, v: unknown) => setForm(f => ({ ...f, [k]: v }));
  async function submit() {
    if (!form.name.trim()) { setError('Name is required'); return; }
    setSaving(true); setError('');
    try {
      const body = { ...form, joining_date: form.joining_date || null, rate: form.rate || 0 };
      if (editing) await api.put(`/api/v1/workforce/workers/${editing.id}`, body);
      else await api.post('/api/v1/workforce/workers', body);
      onSaved(); onClose();
    } catch (e: unknown) {
      const d = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof d === 'string' ? d : 'Failed to save worker');
    } finally { setSaving(false); }
  }
  return (
    <Dialog open={open} onOpenChange={v => !v && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader><DialogTitle>{editing ? 'Edit Worker' : 'Add Worker'}</DialogTitle></DialogHeader>
        <div className="space-y-3">
          {error && <p className="rounded bg-destructive/10 p-2 text-sm text-destructive">{error}</p>}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="space-y-1"><Label>Name</Label><Input value={form.name} onChange={e => set('name', e.target.value)} placeholder="Worker name" /></div>
            <div className="space-y-1"><Label>Phone</Label><Input value={form.phone} onChange={e => set('phone', e.target.value)} /></div>
            <div className="space-y-1"><Label>Type</Label>
              <Select value={form.worker_type} onValueChange={v => set('worker_type', v ?? 'daily_wage')}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent><SelectItem value="daily_wage">Daily wage</SelectItem><SelectItem value="monthly_salary">Monthly salary</SelectItem></SelectContent>
              </Select>
            </div>
            <div className="space-y-1"><Label>{form.worker_type === 'monthly_salary' ? 'Salary (₹/month)' : 'Rate (₹/day)'}</Label>
              <Input type="number" min="0" step="1" value={form.rate || ''} onChange={e => set('rate', parseFloat(e.target.value) || 0)} /></div>
            <div className="space-y-1"><Label>Designation</Label><Input value={form.designation} onChange={e => set('designation', e.target.value)} placeholder="e.g. Loader, Operator" /></div>
            <div className="space-y-1"><Label>Joining date</Label><Input type="date" value={form.joining_date} onChange={e => set('joining_date', e.target.value)} /></div>
            <div className="space-y-1"><Label>Aadhaar</Label><Input value={form.aadhaar_no} onChange={e => set('aadhaar_no', e.target.value)} maxLength={12} /></div>
          </div>
          <div className="space-y-1"><Label>Notes</Label><Input value={form.notes} onChange={e => set('notes', e.target.value)} /></div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={submit} disabled={saving}>{saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}{editing ? 'Update' : 'Add'} Worker</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Record payment dialog ─────────────────────────────────────────────────────
function PaymentDialog({ open, workers, presetWorker, onClose, onSaved }: {
  open: boolean; workers: Worker[]; presetWorker?: string; onClose: () => void; onSaved: () => void;
}) {
  const [form, setForm] = useState({ worker_id: '', pay_date: today(), payment_type: 'advance', amount: '', mode: 'cash', reference: '', notes: '' });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    if (open) { setForm({ worker_id: presetWorker || '', pay_date: today(), payment_type: 'advance', amount: '', mode: 'cash', reference: '', notes: '' }); setError(''); }
  }, [open, presetWorker]);
  const set = (k: string, v: unknown) => setForm(f => ({ ...f, [k]: v }));
  async function submit() {
    if (!form.worker_id) { setError('Select a worker'); return; }
    if (!form.amount || parseFloat(form.amount) <= 0) { setError('Enter an amount'); return; }
    setSaving(true); setError('');
    try {
      await api.post('/api/v1/workforce/payments', { ...form, amount: parseFloat(form.amount) });
      onSaved(); onClose();
    } catch (e: unknown) {
      const d = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof d === 'string' ? d : 'Failed to record payment');
    } finally { setSaving(false); }
  }
  return (
    <Dialog open={open} onOpenChange={v => !v && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader><DialogTitle>Record Payment</DialogTitle></DialogHeader>
        <div className="space-y-3">
          {error && <p className="rounded bg-destructive/10 p-2 text-sm text-destructive">{error}</p>}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="space-y-1"><Label>Worker</Label>
              <Select value={form.worker_id} onValueChange={v => set('worker_id', v ?? '')}>
                <SelectTrigger><SelectValue placeholder="Select worker">{workers.find(w => w.id === form.worker_id)?.name}</SelectValue></SelectTrigger>
                <SelectContent>{workers.map(w => <SelectItem key={w.id} value={w.id}>{w.name}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div className="space-y-1"><Label>Date</Label><Input type="date" value={form.pay_date} onChange={e => set('pay_date', e.target.value)} /></div>
            <div className="space-y-1"><Label>Type</Label>
              <Select value={form.payment_type} onValueChange={v => set('payment_type', v ?? 'advance')}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="advance">Advance</SelectItem><SelectItem value="wage">Wage payment</SelectItem>
                  <SelectItem value="salary">Salary payment</SelectItem><SelectItem value="bonus">Bonus</SelectItem>
                  <SelectItem value="deduction">Deduction</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1"><Label>Amount (₹)</Label><Input type="number" min="0" step="1" value={form.amount} onChange={e => set('amount', e.target.value)} /></div>
            <div className="space-y-1"><Label>Mode</Label>
              <Select value={form.mode} onValueChange={v => set('mode', v ?? 'cash')}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent><SelectItem value="cash">Cash</SelectItem><SelectItem value="bank">Bank</SelectItem><SelectItem value="upi">UPI</SelectItem></SelectContent>
              </Select>
            </div>
            <div className="space-y-1"><Label>Reference</Label><Input value={form.reference} onChange={e => set('reference', e.target.value)} placeholder="optional" /></div>
          </div>
          <div className="space-y-1"><Label>Notes</Label><Input value={form.notes} onChange={e => set('notes', e.target.value)} /></div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={submit} disabled={saving}>{saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Record</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Kpi({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">{label}</p><p className={`text-2xl font-bold ${tone || ''}`}>{value}</p></CardContent></Card>;
}

// ── Main ──────────────────────────────────────────────────────────────────────
type Tab = 'workers' | 'attendance' | 'payments' | 'summary' | 'settings';

export default function WorkforcePage() {
  const loc = useLocation(); const nav = useNavigate();
  const initial = (new URLSearchParams(loc.search).get('tab') as Tab) || 'workers';
  const [tab, setTab] = useState<Tab>(initial);
  const [workers, setWorkers] = useState<Worker[]>([]);
  const [isAdmin, setIsAdmin] = useState(false);

  const loadWorkers = useCallback(async () => {
    try { const { data } = await api.get<Worker[]>('/api/v1/workforce/workers'); setWorkers(data); } catch { /* ignore */ }
  }, []);
  useEffect(() => { loadWorkers(); api.get<{ role: string }>('/api/v1/auth/me').then(r => setIsAdmin(r.data.role === 'admin')).catch(() => {}); }, [loadWorkers]);
  useEffect(() => { const p = new URLSearchParams(loc.search); if (p.get('tab') !== tab) { p.set('tab', tab); nav({ search: p.toString() }, { replace: true }); } }, [tab, loc.search, nav]);

  const TABS: { value: Tab; label: string; icon: React.ElementType }[] = [
    { value: 'workers', label: 'Workers', icon: Users },
    { value: 'attendance', label: 'Attendance', icon: CalendarCheck },
    { value: 'payments', label: 'Payments', icon: IndianRupee },
    { value: 'summary', label: 'Payroll', icon: ClipboardList },
    ...(isAdmin ? [{ value: 'settings' as Tab, label: 'Settings', icon: Settings2 }] : []),
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Users className="h-6 w-6 text-primary" />
        <div><h1 className="text-2xl font-bold tracking-tight">Workforce &amp; Payroll</h1>
          <p className="text-sm text-muted-foreground">Workers, attendance muster, wages, salary &amp; advances — the record for labour cost.</p></div>
      </div>
      <Tabs value={tab} onValueChange={v => setTab(v as Tab)}>
        <MobileTabSelect value={tab} onValueChange={v => setTab(v as Tab)} options={TABS.map(t => ({ value: t.value, label: t.label }))} />
        <TabsList className="hidden sm:inline-flex flex-wrap h-auto">
          {TABS.map(t => { const I = t.icon; return <TabsTrigger key={t.value} value={t.value} className="gap-1.5"><I className="h-3.5 w-3.5" /> {t.label}</TabsTrigger>; })}
        </TabsList>
        <TabsContent value="workers" className="mt-4"><WorkersTab workers={workers} reload={loadWorkers} /></TabsContent>
        <TabsContent value="attendance" className="mt-4"><AttendanceTab /></TabsContent>
        <TabsContent value="payments" className="mt-4"><PaymentsTab workers={workers} /></TabsContent>
        <TabsContent value="summary" className="mt-4"><SummaryTab /></TabsContent>
        {isAdmin && <TabsContent value="settings" className="mt-4"><SettingsTab /></TabsContent>}
      </Tabs>
    </div>
  );
}

// ── Workers tab ───────────────────────────────────────────────────────────────
function WorkersTab({ workers, reload }: { workers: Worker[]; reload: () => void }) {
  const [dialog, setDialog] = useState(false);
  const [editing, setEditing] = useState<Worker | null>(null);
  const COLS: ColumnDef<Worker>[] = [
    { key: 'name', label: 'Name', accessor: r => r.name },
    { key: 'worker_type', label: 'Type', type: 'enum', enumOptions: ['Daily wage', 'Monthly salary'], accessor: r => TYPE_LABEL[r.worker_type] || r.worker_type },
    { key: 'rate', label: 'Rate', type: 'number', align: 'right', accessor: r => Number(r.rate), format: (_v, r) => `${INR(r.rate)}${r.worker_type === 'monthly_salary' ? '/mo' : '/day'}` },
    { key: 'designation', label: 'Role', accessor: r => r.designation || '—' },
    { key: 'phone', label: 'Phone', accessor: r => r.phone || '—' },
    { key: 'joining_date', label: 'Joined', type: 'date', defaultVisible: false, accessor: r => r.joining_date || '', format: v => v ? new Date(String(v)).toLocaleDateString('en-IN') : '—' },
  ];
  return (
    <div className="space-y-3">
      <div className="flex justify-end"><Button onClick={() => { setEditing(null); setDialog(true); }}><Plus className="mr-2 h-4 w-4" /> Add Worker</Button></div>
      <DataTable<Worker> id="workforce.workers" data={workers} columns={COLS} rowKey={r => r.id} exportFilename="workers"
        defaultSort={{ key: 'name', direction: 'asc' }} emptyMessage="No workers yet — add your first person"
        rowActions={r => <Button size="sm" variant="ghost" onClick={() => { setEditing(r); setDialog(true); }}>Edit</Button>} />
      <WorkerDialog open={dialog} editing={editing} onClose={() => setDialog(false)} onSaved={reload} />
    </div>
  );
}

// ── Attendance muster — Daily / Weekly / Monthly ──────────────────────────────
const STATUS_OPTS = [
  { v: 'present', label: 'Present' },
  { v: 'half_day', label: 'Half-day' },
  { v: 'overtime', label: 'Overtime' },
  { v: 'absent', label: 'Absent' },
  { v: 'clear', label: '— (clear)' },
];
const WD = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];
const addDays = (iso: string, n: number) => { const d = new Date(iso); d.setDate(d.getDate() + n); return d.toISOString().split('T')[0]; };
const startOfWeek = (iso: string) => { const d = new Date(iso); d.setDate(d.getDate() - ((d.getDay() + 6) % 7)); return d.toISOString().split('T')[0]; };

function AttendanceTab() {
  const [view, setView] = useState<'daily' | 'weekly' | 'monthly'>('monthly');
  const [ref, setRef] = useState(today());
  const [days, setDays] = useState<string[]>([]);
  const [rows, setRows] = useState<AttWorker[]>([]);
  const [loading, setLoading] = useState(false);

  const range = useMemo(() => {
    if (view === 'daily') return { from: ref, to: ref };
    if (view === 'weekly') { const mon = startOfWeek(ref); return { from: mon, to: addDays(mon, 6) }; }
    const m = ref.slice(0, 7); return { from: monthStart(m), to: monthEnd(m) };
  }, [view, ref]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const p = new URLSearchParams({ date_from: range.from, date_to: range.to });
      const { data } = await api.get<{ days: string[]; workers: AttWorker[] }>(`/api/v1/workforce/attendance?${p}`);
      setDays(data.days); setRows(data.workers);
    } catch { setDays([]); setRows([]); } finally { setLoading(false); }
  }, [range.from, range.to]);
  useEffect(() => { load(); }, [load]);

  const setCell = async (worker: AttWorker, date: string, status: string, ot: number) => {
    setRows(rs => rs.map(w => {
      if (w.worker_id !== worker.worker_id) return w;
      const att = { ...w.attendance };
      if (status === 'clear') delete att[date]; else att[date] = { status, ot_hours: ot };
      return { ...w, attendance: att };
    }));
    try { await api.post('/api/v1/workforce/attendance', { worker_id: worker.worker_id, att_date: date, status, ot_hours: ot }); load(); }
    catch { load(); }
  };
  const cycle = (w: AttWorker, date: string) => {
    const next = NEXT_STATUS[w.attendance[date]?.status || ''] ?? 'present';
    setCell(w, date, next === '' ? 'clear' : next, next === 'overtime' ? 2 : 0);
  };
  const markAllPresent = async (date: string) => {
    try { await api.post('/api/v1/workforce/attendance/bulk', { items: rows.filter(r => r.worker_type !== 'monthly_salary').map(r => ({ worker_id: r.worker_id, att_date: date, status: 'present', ot_hours: 0 })) }); load(); }
    catch { /* ignore */ }
  };
  const shift = (dir: number) => {
    if (view === 'daily') setRef(addDays(ref, dir));
    else if (view === 'weekly') setRef(addDays(ref, dir * 7));
    else { const [y, m] = ref.slice(0, 7).split('-').map(Number); setRef(new Date(y, m - 1 + dir, 1).toISOString().split('T')[0]); }
  };
  const label = view === 'daily'
    ? new Date(range.from).toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' })
    : view === 'weekly'
      ? `${new Date(range.from).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })} – ${new Date(range.to).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}`
      : new Date(range.from).toLocaleDateString('en-IN', { month: 'long', year: 'numeric' });

  // a status dropdown for one worker/day (used in daily + weekly views)
  const statusSelect = (w: AttWorker, d: string, wide?: boolean) => {
    const st = w.attendance[d]?.status || '';
    return (
      <Select value={st || undefined} onValueChange={v => setCell(w, d, v ?? 'clear', v === 'overtime' ? (w.attendance[d]?.ot_hours || 2) : 0)}>
        <SelectTrigger className={`h-9 ${wide ? 'w-44' : 'w-[88px]'} ${st ? CELL[st]?.c : ''}`}><SelectValue placeholder="— mark" /></SelectTrigger>
        <SelectContent>{STATUS_OPTS.map(o => <SelectItem key={o.v} value={o.v}>{o.label}</SelectItem>)}</SelectContent>
      </Select>
    );
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="inline-flex rounded-md border p-0.5">
          {(['daily', 'weekly', 'monthly'] as const).map(v => (
            <button key={v} onClick={() => setView(v)} className={`px-3 py-1 text-sm rounded capitalize ${view === v ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'}`}>{v}</button>
          ))}
        </div>
        <Button variant="outline" size="sm" onClick={() => shift(-1)}>‹</Button>
        <span className="text-sm font-medium min-w-[170px] text-center">{label}</span>
        <Button variant="outline" size="sm" onClick={() => shift(1)}>›</Button>
        <Button variant="ghost" size="sm" onClick={() => setRef(today())}>Today</Button>
        <div className="flex-1" />
        <div className="hidden md:flex items-center gap-2 text-xs text-muted-foreground">
          <span className="px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700">P</span>
          <span className="px-1.5 py-0.5 rounded bg-red-100 text-red-700">A</span>
          <span className="px-1.5 py-0.5 rounded bg-amber-100 text-amber-700">½</span>
          <span className="px-1.5 py-0.5 rounded bg-blue-100 text-blue-700">OT</span>
        </div>
      </div>

      {loading ? <div className="flex justify-center py-10"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
        : rows.length === 0 ? <p className="py-10 text-center text-sm text-muted-foreground">No active workers. Add workers first, then mark attendance here.</p>
        : view === 'daily' ? (
        <Card><CardContent className="p-0 divide-y">
          {rows.map(w => (
            <div key={w.worker_id} className="flex items-center gap-3 px-4 py-3">
              <div className="flex-1 font-medium">{w.name}{w.worker_type === 'monthly_salary' && <span className="ml-1 text-[10px] text-muted-foreground">(salary)</span>}</div>
              {w.worker_type === 'monthly_salary' ? <span className="text-xs text-muted-foreground">salaried</span> : statusSelect(w, range.from, true)}
              <div className="w-24 text-right font-mono text-sm">{INR(w.earned)}</div>
            </div>
          ))}
        </CardContent></Card>
      ) : (
        <Card><CardContent className="p-0 overflow-x-auto">
          <table className="min-w-max text-sm border-collapse">
            <thead><tr className="border-b">
              <th className="sticky left-0 z-10 bg-background px-3 py-2 text-left font-medium min-w-[130px]">Worker</th>
              {days.map(d => {
                const dn = Number(d.slice(8)); const dow = new Date(d).getDay();
                return <th key={d} className={`px-1.5 py-1.5 text-center font-normal text-[11px] ${dow === 0 ? 'text-red-500' : 'text-muted-foreground'}`}>
                  <button className="leading-tight hover:underline" title="Mark all present this day" onClick={() => markAllPresent(d)}>
                    <div>{WD[dow]}</div><div className="font-semibold text-foreground">{dn}</div>
                  </button>
                </th>;
              })}
              <th className="px-2 py-2 text-right font-medium">Days</th>
              <th className="px-2 py-2 text-right font-medium">Earned</th>
            </tr></thead>
            <tbody>
              {rows.map(w => (
                <tr key={w.worker_id} className="border-b hover:bg-muted/20">
                  <td className="sticky left-0 z-10 bg-background px-3 py-1.5 font-medium whitespace-nowrap">
                    {w.name}{w.worker_type === 'monthly_salary' && <span className="ml-1 text-[10px] text-muted-foreground">(salary)</span>}
                  </td>
                  {days.map(d => (
                    <td key={d} className="p-1 text-center">
                      {w.worker_type === 'monthly_salary' ? <span className="text-muted-foreground">—</span>
                        : view === 'weekly' ? statusSelect(w, d)
                        : (() => { const cell = CELL[w.attendance[d]?.status || ''] || CELL['']; return <button onClick={() => cycle(w, d)} className={`h-9 w-9 rounded text-xs font-semibold ${cell.c}`} title={w.attendance[d]?.status || 'mark'}>{cell.t}</button>; })()}
                    </td>
                  ))}
                  <td className="px-2 text-right font-mono">{w.units == null ? '—' : num(w.units, 1)}</td>
                  <td className="px-2 text-right font-mono">{INR(w.earned)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent></Card>
      )}
      <p className="text-[11px] text-muted-foreground">
        {view === 'monthly' ? 'Tap a cell to cycle blank → P → A → ½ → OT; tap a day header to mark all present.'
          : view === 'weekly' ? 'Pick a status per day from the dropdown; tap a day header to mark all present.'
          : 'Pick each worker’s status for the day from the dropdown.'} Salary workers earn the monthly rate (attendance shown for record only).
      </p>
    </div>
  );
}

// ── Payments tab ──────────────────────────────────────────────────────────────
function PaymentsTab({ workers }: { workers: Worker[] }) {
  const [rows, setRows] = useState<Payment[]>([]);
  const [loading, setLoading] = useState(false);
  const [dialog, setDialog] = useState(false);
  const [from, setFrom] = useState(monthStart(thisMonth()));
  const [to, setTo] = useState(today());

  const load = useCallback(async () => {
    setLoading(true);
    try { const p = new URLSearchParams({ date_from: from, date_to: to }); const { data } = await api.get<{ items: Payment[] }>(`/api/v1/workforce/payments?${p}`); setRows(data.items ?? []); }
    catch { setRows([]); } finally { setLoading(false); }
  }, [from, to]);
  useEffect(() => { load(); }, [load]);

  const COLS: ColumnDef<Payment>[] = [
    { key: 'pay_date', label: 'Date', type: 'date', accessor: r => r.pay_date, format: v => new Date(String(v)).toLocaleDateString('en-IN') },
    { key: 'worker_name', label: 'Worker', accessor: r => r.worker_name || '—' },
    { key: 'payment_type', label: 'Type', type: 'enum', enumOptions: Object.values(PAY_LABEL), accessor: r => PAY_LABEL[r.payment_type] || r.payment_type,
      format: (_v, r) => <Badge variant="outline" className={r.payment_type === 'advance' ? 'bg-amber-50 text-amber-700' : r.payment_type === 'deduction' ? 'bg-red-50 text-red-700' : 'bg-emerald-50 text-emerald-700'}>{PAY_LABEL[r.payment_type] || r.payment_type}</Badge> },
    { key: 'amount', label: 'Amount', type: 'number', align: 'right', accessor: r => r.amount, format: v => INR(Number(v)) },
    { key: 'mode', label: 'Mode', type: 'enum', enumOptions: ['cash', 'bank', 'upi'], accessor: r => r.mode },
    { key: 'reference', label: 'Ref', defaultVisible: false, accessor: r => r.reference || '—' },
    { key: 'notes', label: 'Notes', defaultVisible: false, accessor: r => r.notes || '—' },
  ];
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-2">
        <div className="space-y-1"><Label className="text-xs">From</Label><Input type="date" value={from} onChange={e => setFrom(e.target.value)} className="h-9 w-40" /></div>
        <div className="space-y-1"><Label className="text-xs">To</Label><Input type="date" value={to} onChange={e => setTo(e.target.value)} className="h-9 w-40" /></div>
        <div className="flex-1" />
        <Button onClick={() => setDialog(true)}><Plus className="mr-2 h-4 w-4" /> Record Payment</Button>
      </div>
      {loading ? <div className="flex justify-center py-10"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
        : <DataTable<Payment> id="workforce.payments" data={rows} columns={COLS} rowKey={r => r.id} exportFilename="worker-payments" defaultSort={{ key: 'pay_date', direction: 'desc' }} emptyMessage="No payments in this range" />}
      <PaymentDialog open={dialog} workers={workers} onClose={() => setDialog(false)} onSaved={load} />
    </div>
  );
}

// ── Payroll summary tab ───────────────────────────────────────────────────────
function SummaryTab() {
  const [from, setFrom] = useState(monthStart(thisMonth()));
  const [to, setTo] = useState(monthEnd(thisMonth()));
  const [rows, setRows] = useState<SummaryRow[]>([]);
  const [totals, setTotals] = useState<Record<string, number> | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try { const p = new URLSearchParams({ date_from: from, date_to: to }); const { data } = await api.get<{ summary: SummaryRow[]; totals: Record<string, number> }>(`/api/v1/workforce/summary?${p}`); setRows(data.summary ?? []); setTotals(data.totals); }
    catch { setRows([]); setTotals(null); } finally { setLoading(false); }
  }, [from, to]);
  useEffect(() => { load(); }, [load]);

  const COLS: ColumnDef<SummaryRow>[] = [
    { key: 'name', label: 'Worker', accessor: r => r.name },
    { key: 'worker_type', label: 'Type', type: 'enum', enumOptions: ['Daily wage', 'Monthly salary'], accessor: r => TYPE_LABEL[r.worker_type] || r.worker_type },
    { key: 'days_units', label: 'Days', type: 'number', align: 'right', accessor: r => r.days_units ?? 0, format: (_v, r) => r.days_units == null ? '—' : num(r.days_units, 1), exportValue: r => r.days_units ?? '' },
    { key: 'earned', label: 'Earned', type: 'number', align: 'right', accessor: r => r.earned, format: v => INR(Number(v)) },
    { key: 'advances', label: 'Advances', type: 'number', align: 'right', accessor: r => r.advances, format: v => INR(Number(v)) },
    { key: 'total_paid', label: 'Total Paid', type: 'number', align: 'right', accessor: r => r.total_paid, format: v => INR(Number(v)) },
    { key: 'balance_due', label: 'Balance Due', type: 'number', align: 'right', accessor: r => r.balance_due,
      format: v => <span className={Number(v) > 0 ? 'font-semibold text-emerald-700' : Number(v) < 0 ? 'font-semibold text-red-600' : ''}>{INR(Number(v))}</span>, exportValue: r => r.balance_due },
  ];
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-2">
        <div className="space-y-1"><Label className="text-xs">From</Label><Input type="date" value={from} onChange={e => setFrom(e.target.value)} className="h-9 w-40" /></div>
        <div className="space-y-1"><Label className="text-xs">To</Label><Input type="date" value={to} onChange={e => setTo(e.target.value)} className="h-9 w-40" /></div>
        <div className="flex gap-1">
          <Button variant="outline" size="sm" onClick={() => { setFrom(monthStart(thisMonth())); setTo(monthEnd(thisMonth())); }}>This month</Button>
        </div>
      </div>
      {totals && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Kpi label="Total earned" value={INR(totals.earned)} />
          <Kpi label="Advances given" value={INR(totals.advances)} tone="text-amber-600" />
          <Kpi label="Total paid" value={INR(totals.total_paid)} />
          <Kpi label="Balance due to workers" value={INR(totals.balance_due)} tone={totals.balance_due > 0 ? 'text-emerald-700' : 'text-red-600'} />
        </div>
      )}
      {loading ? <div className="flex justify-center py-10"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
        : <DataTable<SummaryRow> id="workforce.summary" data={rows} columns={COLS} rowKey={r => r.worker_id} exportFilename="payroll-summary" defaultSort={{ key: 'balance_due', direction: 'desc' }} emptyMessage="No workers/data for this range" />}
      <p className="text-[11px] text-muted-foreground">Balance Due = Earned − Total Paid (advances netted). Positive = owed to the worker; negative = net advance / overpaid.</p>
    </div>
  );
}

// ── Settings tab ──────────────────────────────────────────────────────────────
function SettingsTab() {
  const [cfg, setCfg] = useState<Record<string, unknown>>({});
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState('');
  useEffect(() => { api.get<Record<string, unknown>>('/api/v1/workforce/config').then(r => setCfg(r.data)).catch(() => {}); }, []);
  const set = (k: string, v: unknown) => setCfg(c => ({ ...c, [k]: v }));
  async function save() { setSaving(true); setMsg(''); try { await api.put('/api/v1/workforce/config', cfg); setMsg('Saved'); } catch { setMsg('Save failed'); } finally { setSaving(false); } }
  return (
    <Card><CardContent className="p-5 space-y-4 max-w-md">
      <div className="space-y-1"><Label>Half-day factor</Label>
        <Input type="number" min="0" max="1" step="0.05" value={Number(cfg.half_day_factor ?? 0.5)} onChange={e => set('half_day_factor', parseFloat(e.target.value) || 0)} />
        <p className="text-[11px] text-muted-foreground">Fraction of a day's wage a half-day earns (default 0.5).</p></div>
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1"><Label>Work hours/day</Label>
          <Input type="number" min="1" step="1" value={Number(cfg.work_hours ?? 8)} onChange={e => set('work_hours', parseFloat(e.target.value) || 8)} /></div>
        <div className="space-y-1"><Label>OT factor</Label>
          <Input type="number" min="0" step="0.25" value={Number(cfg.ot_factor ?? 1)} onChange={e => set('ot_factor', parseFloat(e.target.value) || 0)} />
          <p className="text-[11px] text-muted-foreground">OT hour = (rate ÷ hours) × factor.</p></div>
      </div>
      <div className="flex items-center gap-3"><Button onClick={save} disabled={saving}>{saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Save</Button>{msg && <span className="text-sm text-muted-foreground">{msg}</span>}</div>
    </CardContent></Card>
  );
}
