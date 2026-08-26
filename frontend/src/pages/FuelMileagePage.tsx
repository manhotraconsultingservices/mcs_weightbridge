/**
 * Fleet Fuel & Mileage — diesel-leakage detection.
 *
 * Tabs: Fuel Log · Mileage Report · Rent vs Fuel (utilisation) · Trends · Leakage · Settings.
 * Records diesel fills (a plant-tank fill deducts from store diesel stock) and
 * shows per-vehicle mileage vs benchmark → excess litres / ₹ = the leakage signal.
 */
import { useState, useEffect, useCallback } from 'react';
import { useLocation, useNavigate, Link } from 'react-router-dom';
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, ReferenceLine,
} from 'recharts';
import { Fuel, Plus, Loader2, AlertTriangle, Droplet, TrendingDown, Gauge, Settings2, IndianRupee, Link as LinkIcon } from 'lucide-react';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { MobileTabSelect } from '@/components/MobileTabSelect';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { DataTable, type ColumnDef } from '@/components/DataTable';
import api from '@/services/api';
import type { Vehicle } from '@/types';

const today = () => new Date().toISOString().split('T')[0];
const daysAgo = (n: number) => new Date(Date.now() - n * 86400000).toISOString().split('T')[0];
const INR = (v: number | null | undefined) =>
  '₹' + Number(v ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 0 });
const num = (v: number | null | undefined, d = 1) =>
  v == null ? '—' : Number(v).toLocaleString('en-IN', { minimumFractionDigits: d, maximumFractionDigits: d });

interface FuelEntry {
  id: string; vehicle_id: string; registration_no: string | null;
  entry_date: string; odometer_km: number; litres: number;
  rate_per_litre: number | null; amount: number | null;
  fuel_source: string; station_name: string | null; po_no: string | null;
  tank_full: boolean; driver_name: string | null; notes: string | null;
  distance_km: number | null; interval_kmpl: number | null; flags: string[];
}
interface PumpStation {
  station_name: string; po_count: number; unpaid_count: number;
  total_billed: number; total_paid: number; outstanding: number; oldest_unpaid_date: string | null;
  advance: number; net_due: number;
  supplier_party_id: string | null; supplier_name: string | null;
}
interface PumpPO {
  id: string; po_no: string; station_name: string; po_date: string | null;
  vehicle_no: string | null; litres: number; rate_per_litre: number; amount: number;
  amount_paid: number; outstanding: number; status: string; notes: string | null;
}
interface MileageRow {
  vehicle_id: string; registration_no: string;
  distance_km: number; litres: number; actual_kmpl: number | null;
  benchmark_kmpl: number | null; benchmark_source: string;
  deviation_pct: number | null; expected_litres: number | null;
  expected_km: number | null; km_shortfall: number | null;
  excess_litres: number | null; excess_cost: number | null;
  tank_capacity_litres: number | null; fuel_left_litres: number | null;
  range_km: number | null;
  range_basis: string | null; range_note: string | null;
  status: string; flags: string[];
}
interface SeriesPoint { period: string; distance_km: number; litres: number; actual_kmpl: number | null; cost: number; }
interface Totals { vehicles: number; distance_km: number; litres: number; avg_kmpl: number | null; total_excess_cost: number; leaking_vehicles: number; }

const STATUS_STYLE: Record<string, string> = {
  leak: 'bg-red-100 text-red-700 border-red-200',
  watch: 'bg-amber-100 text-amber-700 border-amber-200',
  ok: 'bg-emerald-100 text-emerald-700 border-emerald-200',
  unknown: 'bg-muted text-muted-foreground',
};
const FLAG_LABEL: Record<string, string> = {
  odometer_rollback: 'Meter rollback',
  litres_over_tank: 'Fill > tank',
};

// ── Record Fill dialog ────────────────────────────────────────────────────────
function RecordFillDialog({ open, vehicles, onClose, onSaved, stations = [] }: {
  open: boolean; vehicles: Vehicle[]; onClose: () => void; onSaved: () => void; stations?: string[];
}) {
  const [form, setForm] = useState({
    vehicle_id: '', entry_date: today(), odometer_km: '', litres: '',
    rate_per_litre: '', fuel_source: 'plant_tank', station_name: '', on_credit: true,
    tank_full: true, notes: '',
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<FuelEntry | null>(null);
  const atPump = form.fuel_source === 'outside_pump' || form.fuel_source === 'other';

  useEffect(() => {
    if (open) {
      setForm({ vehicle_id: '', entry_date: today(), odometer_km: '', litres: '', rate_per_litre: '', fuel_source: 'plant_tank', station_name: '', on_credit: true, tank_full: true, notes: '' });
      setError(''); setResult(null);
    }
  }, [open]);
  const fillAmount = (parseFloat(form.litres || '0') || 0) * (parseFloat(form.rate_per_litre || '0') || 0);
  const set = (k: string, v: unknown) => setForm(f => ({ ...f, [k]: v }));

  async function submit() {
    if (!form.vehicle_id) { setError('Select a vehicle'); return; }
    // Litres is optional: a 0-litre entry is an odometer-only update (no fill).
    if (!form.odometer_km) { setError('Odometer reading is required'); return; }
    if (atPump && form.on_credit && !form.station_name.trim()) {
      setError('Enter the petrol pump / station name for a credit fill'); return;
    }
    // A pump fill's amount IS the expense — without it the fill cannot reach the
    // Day Book or the pump's credit balance, so stop it here rather than let it
    // save into a state nothing can account for.
    if (atPump && parseFloat(form.litres || '0') > 0 && !parseFloat(form.rate_per_litre || '0')) {
      setError('Enter the rate per litre — a petrol-pump fill needs its cost to reach the Day Book and Pump Credit');
      return;
    }
    setSaving(true); setError(''); setResult(null);
    try {
      const { data } = await api.post<FuelEntry>('/api/v1/fuel/entries', {
        vehicle_id: form.vehicle_id,
        entry_date: form.entry_date,
        odometer_km: parseFloat(form.odometer_km),
        litres: form.litres ? parseFloat(form.litres) : 0,
        rate_per_litre: form.rate_per_litre ? parseFloat(form.rate_per_litre) : null,
        fuel_source: form.fuel_source,
        station_name: atPump ? (form.station_name.trim() || null) : null,
        on_credit: atPump ? form.on_credit : false,
        tank_full: form.tank_full,
        notes: form.notes || null,
      });
      setResult(data);
      onSaved();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Failed to record the fill');
    } finally { setSaving(false); }
  }

  return (
    <Dialog open={open} onOpenChange={v => !v && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader><DialogTitle>Record Diesel Fill</DialogTitle></DialogHeader>
        <div className="space-y-4">
          {error && <p className="rounded bg-destructive/10 p-2 text-sm text-destructive">{error}</p>}
          {result && (
            <div className="rounded border border-emerald-200 bg-emerald-50 p-2 text-xs text-emerald-800">
              Saved. {result.interval_kmpl != null
                ? <>This fill ran <b>{num(result.interval_kmpl, 2)} km/l</b> over {num(result.distance_km)} km.</>
                : <>First fill for this vehicle — mileage starts from the next fill.</>}
              {result.flags?.length ? <span className="ml-1 text-amber-700">⚠ {result.flags.map(f => FLAG_LABEL[f] || f).join(', ')}</span> : null}
              {result.po_no ? <div className="mt-1 text-amber-800">📄 Credit PO <b>{result.po_no}</b> created against <b>{result.station_name}</b>.</div> : null}
            </div>
          )}
          <datalist id="fuel-stations">{stations.map(s => <option key={s} value={s} />)}</datalist>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>Vehicle</Label>
              <Select value={form.vehicle_id} onValueChange={v => set('vehicle_id', v ?? '')}>
                <SelectTrigger><SelectValue placeholder="Select vehicle">
                  {vehicles.find(v => v.id === form.vehicle_id)?.registration_no}
                </SelectValue></SelectTrigger>
                <SelectContent>
                  {vehicles.map(v => <SelectItem key={v.id} value={v.id}>{v.registration_no}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label>Date</Label>
              <Input type="date" value={form.entry_date} onChange={e => set('entry_date', e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label>Odometer (km)</Label>
              <Input type="number" min="0" step="1" value={form.odometer_km} onChange={e => set('odometer_km', e.target.value)} placeholder="Meter reading" />
            </div>
            <div className="space-y-1">
              <Label>Diesel (litres)</Label>
              <Input type="number" min="0" step="0.01" value={form.litres} onChange={e => set('litres', e.target.value)} placeholder="Litres filled (leave blank / 0 to only update odometer)" />
              <p className="text-[10px] text-muted-foreground">Leave blank or 0 to just record a new odometer reading without a fill.</p>
            </div>
            <div className="space-y-1">
              <Label>Rate (₹/litre){atPump && <span className="text-destructive"> *</span>}</Label>
              <Input type="number" min="0" step="0.01" value={form.rate_per_litre}
                onChange={e => set('rate_per_litre', e.target.value)}
                placeholder={atPump ? 'Required for a pump fill' : 'optional (plant tank is costed from store stock)'} />
              {fillAmount > 0 && (
                <p className="text-[11px] font-medium text-foreground">
                  Amount: ₹{fillAmount.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                </p>
              )}
            </div>
            <div className="space-y-1">
              <Label>Source</Label>
              <Select value={form.fuel_source} onValueChange={v => set('fuel_source', v ?? 'plant_tank')}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="plant_tank">Plant tank (deduct stock)</SelectItem>
                  <SelectItem value="outside_pump">Outside pump</SelectItem>
                  <SelectItem value="other">Other</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          {atPump && (
            <div className="rounded-lg border border-amber-200 bg-amber-50/60 p-3 space-y-3">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div className="space-y-1">
                  <Label>Petrol pump / station <span className="text-destructive">*</span></Label>
                  <Input list="fuel-stations" value={form.station_name}
                    onChange={e => set('station_name', e.target.value)}
                    placeholder="e.g. HP Petrol Pump - NH48" />
                </div>
                <label className="flex items-center gap-2 text-sm sm:pt-6">
                  <input type="checkbox" checked={form.on_credit} onChange={e => set('on_credit', e.target.checked)} />
                  On credit — auto-create a PO to pay the pump later
                </label>
              </div>
              <p className="text-[11px] text-amber-800">
                {form.on_credit
                  ? (fillAmount > 0
                      ? `₹${fillAmount.toLocaleString('en-IN', { minimumFractionDigits: 2 })} will be owed to this pump — a purchase order is created against it (no stock movement). Track and pay it in the "Pump Credit" tab.`
                      : 'A purchase order is created against this pump (no stock movement). Enter the rate above so the amount owed can be recorded.')
                  : 'Paid at the pump (cash) — no credit PO will be created; it shows as fuel money-out in the Day Book.'}
              </p>
            </div>
          )}
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={form.tank_full} onChange={e => set('tank_full', e.target.checked)} />
            Filled to full tank (improves mileage accuracy)
          </label>
          <div className="space-y-1">
            <Label>Notes</Label>
            <Input value={form.notes} onChange={e => set('notes', e.target.value)} placeholder="optional" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Close</Button>
          <Button onClick={submit} disabled={saving}>
            {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Record Fill
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── KPI card ──────────────────────────────────────────────────────────────────
function Kpi({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: string }) {
  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className={`text-2xl font-bold ${tone || ''}`}>{value}</p>
        {sub && <p className="text-[11px] text-muted-foreground">{sub}</p>}
      </CardContent>
    </Card>
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────
// ── Utilisation tab — rent (km/₹ from Sales tokens) vs fuel (L/₹) per vehicle ──
interface UtilRow {
  vehicle_id: string; registration_no: string; trips: number;
  rent_km: number; rent_earned: number; fuel_litres: number; fuel_cost: number;
  net: number; fuel_left_est: number | null; odometer_km: number | null;
  tank_capacity_litres: number | null; benchmark_mileage_kmpl: number | null;
  range_km: number | null; range_basis: string | null; range_note: string | null;
}
interface UtilResp {
  date_from: string; date_to: string; rows: UtilRow[];
  totals: { trips: number; rent_km: number; rent_earned: number; fuel_litres: number; fuel_cost: number; net: number };
}

function UtilizationTab() {
  const [from, setFrom] = useState(daysAgo(30));
  const [to, setTo] = useState(today());
  const [data, setData] = useState<UtilResp | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    api.get<UtilResp>(`/api/v1/fuel/vehicle-utilization?date_from=${from}&date_to=${to}`)
      .then(r => setData(r.data)).catch(() => setData(null)).finally(() => setLoading(false));
  }, [from, to]);
  useEffect(() => { load(); }, [load]);

  const tot = data?.totals;
  const monthStart = () => { const d = new Date(); return new Date(d.getFullYear(), d.getMonth(), 1).toISOString().split('T')[0]; };
  const preset = (f: string, t: string) => { setFrom(f); setTo(t); };

  const COLS: ColumnDef<UtilRow>[] = [
    { key: 'registration_no', label: 'Vehicle', accessor: r => r.registration_no,
      format: (_v, r) => <Link to={`/vehicles/${r.vehicle_id}/history`}
        className="font-medium text-blue-700 hover:underline">{r.registration_no}</Link>,
      exportValue: r => r.registration_no },
    { key: 'trips', label: 'Trips', type: 'number', align: 'right', accessor: r => r.trips },
    { key: 'rent_km', label: 'Rent km', type: 'number', align: 'right', accessor: r => r.rent_km, format: v => num(v as number, 0) },
    { key: 'rent_earned', label: 'Rent ₹', type: 'number', align: 'right', accessor: r => r.rent_earned,
      format: v => <span className="text-emerald-700">{INR(v as number)}</span>, exportValue: r => r.rent_earned },
    { key: 'fuel_litres', label: 'Fuel (L)', type: 'number', align: 'right', accessor: r => r.fuel_litres, format: v => num(v as number, 1) },
    { key: 'fuel_cost', label: 'Fuel ₹', type: 'number', align: 'right', accessor: r => r.fuel_cost,
      format: v => <span className="text-rose-700">{INR(v as number)}</span>, exportValue: r => r.fuel_cost },
    { key: 'net', label: 'Net (Rent − Fuel)', type: 'number', align: 'right', accessor: r => r.net,
      format: v => <span className={`font-semibold ${Number(v) >= 0 ? 'text-emerald-700' : 'text-rose-700'}`}>{INR(v as number)}</span>,
      exportValue: r => r.net },
    { key: 'odometer_km', label: 'Odometer (km)', type: 'number', align: 'right', accessor: r => r.odometer_km ?? -1,
      format: (_v, r) => r.odometer_km == null ? '—' : num(r.odometer_km, 0),
      exportValue: r => r.odometer_km ?? '' },
    { key: 'fuel_left_est', label: 'Fuel left ≈ (L)', type: 'number', align: 'right', accessor: r => r.fuel_left_est ?? -1,
      format: (_v, r) => r.fuel_left_est == null
        ? <span className="text-muted-foreground" title={r.range_note || ''}>—</span>
        : <>{num(r.fuel_left_est, 1)}{r.tank_capacity_litres ? <span className="text-muted-foreground"> / {num(r.tank_capacity_litres, 0)}</span> : null}</>,
      exportValue: r => r.fuel_left_est ?? '' },
    { key: 'range_km', label: 'Can run (km)', type: 'number', align: 'right', accessor: r => r.range_km ?? -1,
      format: (_v, r) => r.range_km == null
        ? <span className="text-muted-foreground" title={r.range_note || ''}>—</span>
        : <span className={r.range_km < 100 ? 'font-semibold text-amber-600' : ''}
                title={`Before refuelling, at the ${r.range_basis === 'actual' ? 'mileage this vehicle actually achieves' : 'benchmark mileage'}`}>
            {num(r.range_km, 0)} km
          </span>,
      exportValue: r => r.range_km ?? '' },
  ];
  const chartData = (data?.rows ?? []).slice(0, 12).map(r => ({ name: r.registration_no, Rent: r.rent_earned, Fuel: r.fuel_cost }));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3 p-3 rounded-lg border bg-card">
        <div className="space-y-1"><Label className="text-xs">From</Label>
          <Input type="date" value={from} onChange={e => setFrom(e.target.value)} className="h-8 w-36 text-sm" /></div>
        <div className="space-y-1"><Label className="text-xs">To</Label>
          <Input type="date" value={to} onChange={e => setTo(e.target.value)} className="h-8 w-36 text-sm" /></div>
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="sm" className="h-8 text-xs" onClick={() => preset(today(), today())}>Today</Button>
          <Button variant="ghost" size="sm" className="h-8 text-xs" onClick={() => preset(daysAgo(6), today())}>Last 7</Button>
          <Button variant="ghost" size="sm" className="h-8 text-xs" onClick={() => preset(daysAgo(29), today())}>Last 30</Button>
          <Button variant="ghost" size="sm" className="h-8 text-xs" onClick={() => preset(monthStart(), today())}>This Month</Button>
        </div>
        <Button onClick={load} disabled={loading} variant="outline" size="sm">
          {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : 'Refresh'}</Button>
      </div>
      <p className="text-xs text-muted-foreground -mt-1">
        Own-vehicle rent-out performance: <b>km run</b> and <b>rent earned</b> (from Sales tokens) vs <b>fuel burnt</b>
        (from the fuel log), and the <b>net</b> per vehicle. <b>Fuel left ≈</b> tank at the last brim-full fill,
        plus any top-ups since, less the distance driven since ÷ the mileage this vehicle actually
        achieves (its benchmark only when there is too little fill history to measure). It drops as the
        vehicle runs Sales trips. Needs tank capacity and at least one brim-full fill — the same figure
        appears on the Mileage Report tab.
      </p>

      {tot && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <Card><CardContent className="p-4"><div className="text-xs uppercase tracking-widest text-slate-500 font-semibold">Rent km</div>
            <div className="text-2xl font-bold text-slate-800 mt-1">{num(tot.rent_km, 0)}</div><div className="text-xs text-slate-500">{tot.trips} trips</div></CardContent></Card>
          <Card><CardContent className="p-4"><div className="text-xs uppercase tracking-widest text-slate-500 font-semibold flex items-center gap-1"><IndianRupee className="h-3.5 w-3.5 text-emerald-500" /> Rent earned</div>
            <div className="text-2xl font-bold text-emerald-700 mt-1">{INR(tot.rent_earned)}</div></CardContent></Card>
          <Card><CardContent className="p-4"><div className="text-xs uppercase tracking-widest text-slate-500 font-semibold flex items-center gap-1"><Droplet className="h-3.5 w-3.5 text-sky-500" /> Fuel</div>
            <div className="text-2xl font-bold text-sky-700 mt-1">{num(tot.fuel_litres, 0)} L</div></CardContent></Card>
          <Card><CardContent className="p-4"><div className="text-xs uppercase tracking-widest text-slate-500 font-semibold">Fuel cost</div>
            <div className="text-2xl font-bold text-rose-700 mt-1">{INR(tot.fuel_cost)}</div></CardContent></Card>
          <Card><CardContent className="p-4"><div className="text-xs uppercase tracking-widest text-slate-500 font-semibold">Net</div>
            <div className={`text-2xl font-bold mt-1 ${tot.net >= 0 ? 'text-emerald-700' : 'text-rose-700'}`}>{INR(tot.net)}</div><div className="text-xs text-slate-500">Rent − Fuel</div></CardContent></Card>
        </div>
      )}

      {chartData.length > 0 && (
        <Card><CardContent className="p-4">
          <div className="text-sm font-semibold text-slate-700 mb-2">Rent earned vs Fuel cost by vehicle</div>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="name" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 10 }} tickFormatter={v => `₹${(v / 1000).toFixed(0)}k`} width={48} />
              <Tooltip formatter={(v: number) => INR(v)} />
              <Legend />
              <Bar dataKey="Rent" fill="#10b981" radius={[3, 3, 0, 0]} />
              <Bar dataKey="Fuel" fill="#f43f5e" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </CardContent></Card>
      )}

      <Card><CardContent className="p-0">
        {loading ? <div className="py-10 text-center text-muted-foreground"><Loader2 className="h-5 w-5 animate-spin inline" /> Loading…</div>
          : <DataTable<UtilRow> id="fuel.utilization" data={data?.rows ?? []} columns={COLS} rowKey={r => r.vehicle_id}
              exportFilename={`vehicle-utilization-${from}-to-${to}`} defaultSort={{ key: 'net', direction: 'desc' }}
              emptyMessage="No rent trips or fuel entries in this range." />}
      </CardContent></Card>
    </div>
  );
}

// ── Petrol-pump credit tab ─────────────────────────────────────────────────────
function RecordPumpPaymentDialog({ open, station, dueHint, onClose, onSaved }: {
  open: boolean; station: string; dueHint: number; onClose: () => void; onSaved: () => void;
}) {
  const [form, setForm] = useState({ amount: '', payment_date: today(), mode: 'bank', reference: '' });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => { if (open) { setForm({ amount: dueHint ? String(Math.round(dueHint)) : '', payment_date: today(), mode: 'bank', reference: '' }); setError(''); } }, [open, dueHint]);
  const set = (k: string, v: unknown) => setForm(f => ({ ...f, [k]: v }));
  async function submit() {
    if (!form.amount || parseFloat(form.amount) <= 0) { setError('Enter a valid amount'); return; }
    setSaving(true); setError('');
    try {
      await api.post('/api/v1/fuel/pump-payments', {
        station_name: station, amount: parseFloat(form.amount),
        payment_date: form.payment_date, mode: form.mode, reference: form.reference || null,
      });
      onSaved(); onClose();
    } catch (e: unknown) {
      const d = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof d === 'string' ? d : 'Failed to record the payment');
    } finally { setSaving(false); }
  }
  return (
    <Dialog open={open} onOpenChange={v => !v && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader><DialogTitle>Pay petrol pump</DialogTitle></DialogHeader>
        <div className="space-y-3">
          {error && <p className="rounded bg-destructive/10 p-2 text-sm text-destructive">{error}</p>}
          <div className="text-sm"><span className="text-muted-foreground">Pump:</span> <b>{station}</b>
            {dueHint > 0 && <span className="text-muted-foreground"> · outstanding {INR(dueHint)}</span>}</div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="space-y-1"><Label>Amount (₹)</Label>
              <Input type="number" min="0" step="0.01" value={form.amount} onChange={e => set('amount', e.target.value)} /></div>
            <div className="space-y-1"><Label>Date</Label>
              <Input type="date" value={form.payment_date} onChange={e => set('payment_date', e.target.value)} /></div>
            <div className="space-y-1"><Label>Mode</Label>
              <Select value={form.mode} onValueChange={v => set('mode', v ?? 'bank')}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="cash">Cash</SelectItem>
                  <SelectItem value="bank">Bank transfer</SelectItem>
                  <SelectItem value="upi">UPI</SelectItem>
                  <SelectItem value="cheque">Cheque</SelectItem>
                </SelectContent>
              </Select></div>
            <div className="space-y-1"><Label>Reference</Label>
              <Input value={form.reference} onChange={e => set('reference', e.target.value)} placeholder="optional" /></div>
          </div>
          <p className="text-[11px] text-muted-foreground">Applied oldest-PO-first against this pump's dues.</p>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={submit} disabled={saving}>{saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Record Payment</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function PumpCreditTab() {
  const nav = useNavigate();
  const [stations, setStations] = useState<PumpStation[]>([]);
  const [totals, setTotals] = useState<{ total_billed: number; total_paid: number; outstanding: number; advance: number; net_due: number; pumps_with_advance: number; pumps_with_dues: number; po_count: number } | null>(null);
  const [pos, setPos] = useState<PumpPO[]>([]);
  const [loading, setLoading] = useState(true);
  const [payStation, setPayStation] = useState<{ name: string; due: number } | null>(null);
  const [linkStation, setLinkStation] = useState<{ name: string; current: string | null } | null>(null);
  const [suppliers, setSuppliers] = useState<{ id: string; name: string }[]>([]);
  useEffect(() => {
    api.get<{ items?: { id: string; name: string; party_type: string }[] } | { id: string; name: string; party_type: string }[]>('/api/v1/parties?page_size=500')
      .then(r => { const arr = Array.isArray(r.data) ? r.data : (r.data.items ?? []); setSuppliers(arr.filter(p => p.party_type !== 'customer').map(p => ({ id: p.id, name: p.name }))); })
      .catch(() => {});
  }, []);

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([
      api.get('/api/v1/fuel/pump-outstanding'),
      api.get('/api/v1/fuel/pump-pos'),
    ]).then(([o, p]) => {
      setStations(o.data.stations ?? []); setTotals(o.data.totals ?? null);
      setPos(p.data.items ?? []);
    }).catch(() => {}).finally(() => setLoading(false));
  }, []);
  useEffect(() => { load(); }, [load]);

  const STATION_COLS: ColumnDef<PumpStation>[] = [
    { key: 'station_name', label: 'Petrol pump', accessor: r => r.station_name },
    { key: 'supplier_name', label: 'Supplier', accessor: r => r.supplier_name ?? '',
      format: (_v, r) => r.supplier_name
        ? <button className="text-primary hover:underline" onClick={() => nav(`/customers/${r.supplier_party_id}`)}>{r.supplier_name}</button>
        : <span className="text-muted-foreground text-xs">— not linked</span>,
      exportValue: r => r.supplier_name ?? '' },
    { key: 'po_count', label: 'Fills/POs', type: 'number', align: 'right', accessor: r => r.po_count },
    { key: 'total_billed', label: 'Billed', type: 'number', align: 'right', accessor: r => r.total_billed, format: v => INR(v as number) },
    { key: 'total_paid', label: 'Paid', type: 'number', align: 'right', accessor: r => r.total_paid, format: v => INR(v as number) },
    { key: 'advance', label: 'Advance with pump', type: 'number', align: 'right', accessor: r => r.advance ?? 0,
      format: (_v, r) => (r.advance ?? 0) > 0
        ? <span className="font-semibold text-emerald-700" title="Paid to this pump beyond what it has billed. The next credit fill here draws it down automatically.">{INR(r.advance)}</span>
        : <span className="text-muted-foreground">—</span>,
      exportValue: r => r.advance ?? 0 },
    { key: 'net_due', label: 'Outstanding', type: 'number', align: 'right', accessor: r => r.net_due ?? r.outstanding,
      format: (_v, r) => {
        const due = r.net_due ?? r.outstanding;
        if (due > 0) return <span className="font-semibold text-rose-600">{INR(due)}</span>;
        return (r.advance ?? 0) > 0
          ? <span className="text-emerald-700" title="Nothing owed — this pump is holding an advance">in advance</span>
          : <span className="text-emerald-600">{INR(0)}</span>;
      }, exportValue: r => r.net_due ?? r.outstanding },
    { key: 'oldest_unpaid_date', label: 'Oldest due', type: 'date', accessor: r => r.oldest_unpaid_date, format: v => v ? String(v) : '—' },
  ];
  const PO_COLS: ColumnDef<PumpPO>[] = [
    { key: 'po_no', label: 'PO No', accessor: r => r.po_no },
    { key: 'po_date', label: 'Date', type: 'date', accessor: r => r.po_date, format: v => v ? String(v) : '—' },
    { key: 'station_name', label: 'Petrol pump', accessor: r => r.station_name },
    { key: 'vehicle_no', label: 'Vehicle', accessor: r => r.vehicle_no ?? '—' },
    { key: 'litres', label: 'Litres', type: 'number', align: 'right', accessor: r => r.litres, format: v => num(v as number, 2) },
    { key: 'amount', label: 'Amount', type: 'number', align: 'right', accessor: r => r.amount, format: v => INR(v as number) },
    { key: 'amount_paid', label: 'Paid', type: 'number', align: 'right', accessor: r => r.amount_paid, format: v => INR(v as number) },
    { key: 'outstanding', label: 'Due', type: 'number', align: 'right', accessor: r => r.outstanding, format: v => INR(v as number) },
    { key: 'status', label: 'Status', type: 'enum', enumOptions: ['unpaid', 'partial', 'paid'], accessor: r => r.status,
      format: v => { const s = String(v); const c = s === 'paid' ? 'bg-emerald-100 text-emerald-700' : s === 'partial' ? 'bg-amber-100 text-amber-700' : 'bg-rose-100 text-rose-700'; return <span className={`text-[11px] font-semibold px-2 py-0.5 rounded-full ${c}`}>{s.toUpperCase()}</span>; }, exportValue: r => r.status },
  ];
  const KPI = ({ label, value, tone }: { label: string; value: string; tone?: string }) => (
    <Card><CardContent className="p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`text-xl font-bold ${tone ?? ''}`}>{value}</div>
    </CardContent></Card>
  );

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-blue-200 bg-blue-50/50 p-3 text-xs text-blue-800">
        Every credit fill at a petrol pump auto-creates a PO here (no stock movement). This is your <b>outstanding to pay each pump</b>. Record a payment to settle the oldest POs first. Pay more than is due and the surplus is held as an <b>advance with that pump</b> — the next credit fill there is offset against it automatically.
      </div>
      {loading ? <div className="py-10 text-center text-muted-foreground"><Loader2 className="h-5 w-5 animate-spin inline" /> Loading…</div> : (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <KPI label="Total outstanding" value={INR(totals?.net_due ?? totals?.outstanding ?? 0)} tone={(totals?.net_due ?? 0) > 0 ? 'text-rose-600' : 'text-emerald-600'} />
            <KPI label="Advance with pumps" value={INR(totals?.advance ?? 0)} tone={(totals?.advance ?? 0) > 0 ? 'text-emerald-700' : ''} />
            <KPI label="Pumps with dues" value={String(totals?.pumps_with_dues ?? 0)} />
            <KPI label="Billed on credit" value={INR(totals?.total_billed ?? 0)} />
            <KPI label="Paid to pumps" value={INR(totals?.total_paid ?? 0)} />
          </div>

          <Card>
            <CardHeader className="pb-2"><CardTitle className="text-sm">Outstanding by petrol pump</CardTitle></CardHeader>
            <CardContent className="p-0">
              <DataTable<PumpStation> id="fuel.pumpOutstanding" data={stations} columns={STATION_COLS}
                rowKey={r => r.station_name} exportFilename="petrol-pump-outstanding"
                defaultSort={{ key: 'outstanding', direction: 'desc' }}
                emptyMessage="No credit fuel purchases yet."
                rowActions={r => (
                  <div className="flex gap-1.5 justify-end">
                    <Button size="sm" variant="ghost" className="gap-1" onClick={() => setLinkStation({ name: r.station_name, current: r.supplier_party_id })}>
                      <LinkIcon className="h-3.5 w-3.5" /> {r.supplier_party_id ? 'Re-link' : 'Link'}
                    </Button>
                    {r.outstanding > 0 && (
                      <Button size="sm" variant="outline" className="gap-1.5" onClick={() => setPayStation({ name: r.station_name, due: r.outstanding })}>
                        <IndianRupee className="h-3.5 w-3.5" /> Pay
                      </Button>
                    )}
                  </div>
                )} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2"><CardTitle className="text-sm">Purchase orders (per fill)</CardTitle></CardHeader>
            <CardContent className="p-0">
              <DataTable<PumpPO> id="fuel.pumpPos" data={pos} columns={PO_COLS} rowKey={r => r.id}
                exportFilename="petrol-pump-pos" defaultSort={{ key: 'po_date', direction: 'desc' }}
                emptyMessage="No pump POs yet." />
            </CardContent>
          </Card>
        </>
      )}
      <RecordPumpPaymentDialog open={!!payStation} station={payStation?.name ?? ''} dueHint={payStation?.due ?? 0}
        onClose={() => setPayStation(null)} onSaved={load} />
      <Dialog open={!!linkStation} onOpenChange={v => !v && setLinkStation(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader><DialogTitle>Link pump to a supplier</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">Link <b>{linkStation?.name}</b> to a supplier party so this petrol pump appears as a vendor and its dues show on the supplier's 360 page.</p>
            <Select value={linkStation?.current ?? 'none'}
              onValueChange={async v => {
                await api.post('/api/v1/fuel/pump-suppliers', { station_name: linkStation?.name, party_id: v === 'none' ? null : v });
                setLinkStation(null); load();
              }}>
              <SelectTrigger><SelectValue placeholder="Choose a supplier" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="none">— Not linked —</SelectItem>
                {suppliers.map(s => <SelectItem key={s.id} value={s.id}>{s.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <DialogFooter><Button variant="outline" onClick={() => setLinkStation(null)}>Close</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

type Tab = 'log' | 'pump' | 'report' | 'utilization' | 'trends' | 'leakage' | 'settings';

export default function FuelMileagePage() {
  const loc = useLocation(); const nav = useNavigate();
  const initial = (new URLSearchParams(loc.search).get('tab') as Tab) || 'log';
  const [tab, setTab] = useState<Tab>(initial);
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [isAdmin, setIsAdmin] = useState(false);

  useEffect(() => {
    api.get<{ items?: Vehicle[] } | Vehicle[]>('/api/v1/vehicles?page_size=500')
      .then(r => setVehicles(Array.isArray(r.data) ? r.data : (r.data.items ?? [])))
      .catch(() => {});
    api.get<{ role: string }>('/api/v1/auth/me').then(r => setIsAdmin(r.data.role === 'admin')).catch(() => {});
  }, []);
  useEffect(() => {
    const p = new URLSearchParams(loc.search);
    if (p.get('tab') !== tab) { p.set('tab', tab); nav({ search: p.toString() }, { replace: true }); }
  }, [tab, loc.search, nav]);

  const TABS: { value: Tab; label: string; icon: React.ElementType }[] = [
    { value: 'log', label: 'Fuel Log', icon: Droplet },
    { value: 'pump', label: 'Pump Credit', icon: IndianRupee },
    { value: 'report', label: 'Mileage Report', icon: Gauge },
    { value: 'utilization', label: 'Rent vs Fuel', icon: IndianRupee },
    { value: 'trends', label: 'Trends', icon: TrendingDown },
    { value: 'leakage', label: 'Leakage Alerts', icon: AlertTriangle },
    ...(isAdmin ? [{ value: 'settings' as Tab, label: 'Settings', icon: Settings2 }] : []),
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Fuel className="h-6 w-6 text-primary" />
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Fuel &amp; Mileage</h1>
          <p className="text-sm text-muted-foreground">Diesel consumption, mileage vs benchmark, and leakage detection.</p>
        </div>
      </div>
      <Tabs value={tab} onValueChange={v => setTab(v as Tab)}>
        <MobileTabSelect value={tab} onValueChange={v => setTab(v as Tab)} options={TABS.map(t => ({ value: t.value, label: t.label }))} />
        <TabsList className="hidden sm:inline-flex flex-wrap h-auto">
          {TABS.map(t => { const I = t.icon; return (
            <TabsTrigger key={t.value} value={t.value} className="gap-1.5"><I className="h-3.5 w-3.5" /> {t.label}</TabsTrigger>
          ); })}
        </TabsList>
        <TabsContent value="log" className="mt-4"><FuelLogTab vehicles={vehicles} /></TabsContent>
        <TabsContent value="pump" className="mt-4"><PumpCreditTab /></TabsContent>
        <TabsContent value="report" className="mt-4"><MileageReportTab /></TabsContent>
        <TabsContent value="utilization" className="mt-4"><UtilizationTab /></TabsContent>
        <TabsContent value="trends" className="mt-4"><TrendsTab vehicles={vehicles} /></TabsContent>
        <TabsContent value="leakage" className="mt-4"><LeakageTab /></TabsContent>
        {isAdmin && <TabsContent value="settings" className="mt-4"><FuelSettingsTab /></TabsContent>}
      </Tabs>
    </div>
  );
}

// ── Fuel Log tab ──────────────────────────────────────────────────────────────
function FuelLogTab({ vehicles }: { vehicles: Vehicle[] }) {
  const [rows, setRows] = useState<FuelEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [dialog, setDialog] = useState(false);
  const [from, setFrom] = useState(daysAgo(30));
  const [to, setTo] = useState(today());

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const p = new URLSearchParams({ date_from: from, date_to: to, page_size: '500' });
      const { data } = await api.get<{ items: FuelEntry[] }>(`/api/v1/fuel/entries?${p}`);
      setRows(data.items ?? []);
    } catch { setRows([]); } finally { setLoading(false); }
  }, [from, to]);
  useEffect(() => { load(); }, [load]);

  const COLS: ColumnDef<FuelEntry>[] = [
    { key: 'entry_date', label: 'Date', type: 'date', accessor: r => r.entry_date, format: v => new Date(String(v)).toLocaleDateString('en-IN') },
    { key: 'registration_no', label: 'Vehicle', accessor: r => r.registration_no || '—',
      format: (_v, r) => r.vehicle_id
        ? <Link to={`/vehicles/${r.vehicle_id}/history`} className="font-medium text-blue-700 hover:underline">{r.registration_no || '—'}</Link>
        : (r.registration_no || '—'),
      exportValue: r => r.registration_no || '' },
    { key: 'odometer_km', label: 'Odometer', type: 'number', align: 'right', accessor: r => r.odometer_km, format: v => `${num(Number(v))} km` },
    { key: 'distance_km', label: 'Distance', type: 'number', align: 'right', accessor: r => r.distance_km ?? 0, format: (_v, r) => r.distance_km == null ? '—' : `${num(r.distance_km)} km`, exportValue: r => r.distance_km ?? '' },
    { key: 'litres', label: 'Litres', type: 'number', align: 'right', accessor: r => r.litres, format: v => num(Number(v), 2) },
    { key: 'interval_kmpl', label: 'km/l', type: 'number', align: 'right', accessor: r => r.interval_kmpl ?? 0, format: (_v, r) => r.interval_kmpl == null ? '—' : num(r.interval_kmpl, 2), exportValue: r => r.interval_kmpl ?? '' },
    { key: 'amount', label: 'Amount', type: 'number', align: 'right', accessor: r => r.amount ?? 0, format: (_v, r) => r.amount == null ? '—' : INR(r.amount), exportValue: r => r.amount ?? '' },
    { key: 'fuel_source', label: 'Source', type: 'enum', enumOptions: ['plant_tank', 'outside_pump', 'other'], accessor: r => r.fuel_source, format: v => String(v).replace(/_/g, ' ') },
    { key: 'flags', label: 'Flags', accessor: r => (r.flags || []).join(','), format: (_v, r) => (r.flags?.length ? <span className="text-amber-600 text-xs">{r.flags.map(f => FLAG_LABEL[f] || f).join(', ')}</span> : <span className="text-muted-foreground">—</span>), exportValue: r => (r.flags || []).map(f => FLAG_LABEL[f] || f).join('; ') },
  ];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-2">
        <div className="space-y-1"><Label className="text-xs">From</Label><Input type="date" value={from} onChange={e => setFrom(e.target.value)} className="h-9 w-40" /></div>
        <div className="space-y-1"><Label className="text-xs">To</Label><Input type="date" value={to} onChange={e => setTo(e.target.value)} className="h-9 w-40" /></div>
        <div className="flex-1" />
        <Button onClick={() => setDialog(true)}><Plus className="mr-2 h-4 w-4" /> Record Fill</Button>
      </div>
      {loading ? <div className="flex justify-center py-10"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
        : <DataTable<FuelEntry> id="fuel.log" data={rows} columns={COLS} rowKey={r => r.id} exportFilename="fuel-log" defaultSort={{ key: 'entry_date', direction: 'desc' }} emptyMessage="No fills recorded in this range" />}
      <RecordFillDialog open={dialog} vehicles={vehicles} onClose={() => setDialog(false)} onSaved={load}
        stations={[...new Set(rows.map(r => r.station_name).filter((s): s is string => !!s))]} />
    </div>
  );
}

// ── Mileage Report tab ────────────────────────────────────────────────────────
function MileageReportTab() {
  const [from, setFrom] = useState(daysAgo(30));
  const [to, setTo] = useState(today());
  const [gran, setGran] = useState('day');
  const [rows, setRows] = useState<MileageRow[]>([]);
  const [totals, setTotals] = useState<Totals | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const p = new URLSearchParams({ date_from: from, date_to: to, granularity: gran });
      const { data } = await api.get<{ summary: MileageRow[]; totals: Totals }>(`/api/v1/fuel/mileage-report?${p}`);
      setRows(data.summary ?? []); setTotals(data.totals);
    } catch { setRows([]); setTotals(null); } finally { setLoading(false); }
  }, [from, to, gran]);
  useEffect(() => { load(); }, [load]);

  const COLS: ColumnDef<MileageRow>[] = [
    { key: 'registration_no', label: 'Vehicle', accessor: r => r.registration_no,
      format: (_v, r) => r.vehicle_id
        ? <Link to={`/vehicles/${r.vehicle_id}/history`} className="font-medium text-blue-700 hover:underline">{r.registration_no}</Link>
        : r.registration_no,
      exportValue: r => r.registration_no },
    { key: 'distance_km', label: 'Distance (actual)', type: 'number', align: 'right', accessor: r => r.distance_km, format: v => `${num(Number(v))} km` },
    { key: 'expected_km', label: 'Expected KM', type: 'number', align: 'right', accessor: r => r.expected_km ?? 0,
      format: (_v, r) => r.expected_km == null ? '—' : <span className="text-slate-600" title="Diesel consumed × benchmark km/l — the distance this vehicle should have covered">{num(r.expected_km)} km</span>,
      exportValue: r => r.expected_km ?? '' },
    { key: 'km_shortfall', label: 'KM Short', type: 'number', align: 'right', accessor: r => r.km_shortfall ?? 0,
      format: (_v, r) => r.km_shortfall == null ? '—' : <span className={r.km_shortfall > 0 ? 'text-red-600 font-semibold' : 'text-emerald-600'} title="Expected KM − actual distance. Positive = covered fewer km than the fuel should have delivered (leak / idling / theft).">{num(r.km_shortfall)} km</span>,
      exportValue: r => r.km_shortfall ?? '' },
    { key: 'litres', label: 'Diesel', type: 'number', align: 'right', accessor: r => r.litres, format: v => `${num(Number(v), 1)} L` },
    { key: 'actual_kmpl', label: 'Actual km/l', type: 'number', align: 'right', accessor: r => r.actual_kmpl ?? 0, format: (_v, r) => r.actual_kmpl == null ? '—' : num(r.actual_kmpl, 2), exportValue: r => r.actual_kmpl ?? '' },
    { key: 'benchmark_kmpl', label: 'Benchmark', type: 'number', align: 'right', accessor: r => r.benchmark_kmpl ?? 0, format: (_v, r) => r.benchmark_kmpl == null ? '—' : `${num(r.benchmark_kmpl, 2)}${r.benchmark_source === 'auto' ? ' (auto)' : ''}`, exportValue: r => r.benchmark_kmpl ?? '' },
    { key: 'deviation_pct', label: 'Deviation', type: 'number', align: 'right', accessor: r => r.deviation_pct ?? 0, format: (_v, r) => r.deviation_pct == null ? '—' : <span className={r.deviation_pct >= 15 ? 'text-red-600 font-semibold' : r.deviation_pct >= 7.5 ? 'text-amber-600' : ''}>{num(r.deviation_pct, 1)}%</span>, exportValue: r => r.deviation_pct ?? '' },
    { key: 'fuel_left_litres', label: 'Fuel left ≈ (L)', type: 'number', align: 'right',
      accessor: r => r.fuel_left_litres ?? -1,
      format: (_v, r) => r.fuel_left_litres == null
        ? <span className="text-muted-foreground" title={r.range_note || ''}>—</span>
        : <span>{num(r.fuel_left_litres, 1)}{r.tank_capacity_litres ? <span className="text-muted-foreground"> / {num(r.tank_capacity_litres, 0)}</span> : null}</span>,
      exportValue: r => r.fuel_left_litres ?? '' },
    { key: 'range_km', label: 'Can run (km)', type: 'number', align: 'right',
      accessor: r => r.range_km ?? -1,
      format: (_v, r) => r.range_km == null
        ? <span className="text-muted-foreground" title={r.range_note || ''}>—</span>
        : <span className={r.range_km < 100 ? 'font-semibold text-amber-600' : ''}
                title={`Before refuelling, at the ${r.range_basis === 'actual' ? 'mileage this vehicle actually achieves' : 'benchmark mileage'}`}>
            {num(r.range_km, 0)} km
          </span>,
      exportValue: r => r.range_km ?? '' },
    { key: 'excess_litres', label: 'Excess L', type: 'number', align: 'right', accessor: r => r.excess_litres ?? 0, format: (_v, r) => r.excess_litres == null ? '—' : num(r.excess_litres, 1), exportValue: r => r.excess_litres ?? '' },
    { key: 'excess_cost', label: 'Excess ₹', type: 'number', align: 'right', accessor: r => r.excess_cost ?? 0, format: (_v, r) => r.excess_cost == null
        ? <span className="text-muted-foreground" title="No rate recorded on the fills for this vehicle — enter the rate per litre when recording a fill to see the cost">—</span>
        : <span className={(r.excess_cost || 0) > 0 ? 'text-red-600 font-semibold' : ''}>{INR(r.excess_cost)}</span>, exportValue: r => r.excess_cost ?? '' },
    { key: 'status', label: 'Status', type: 'enum', enumOptions: ['leak', 'watch', 'ok', 'unknown'], accessor: r => r.status, format: v => <Badge variant="outline" className={STATUS_STYLE[String(v)]}>{String(v)}</Badge> },
  ];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-2">
        <div className="space-y-1"><Label className="text-xs">From</Label><Input type="date" value={from} onChange={e => setFrom(e.target.value)} className="h-9 w-40" /></div>
        <div className="space-y-1"><Label className="text-xs">To</Label><Input type="date" value={to} onChange={e => setTo(e.target.value)} className="h-9 w-40" /></div>
        <div className="space-y-1"><Label className="text-xs">Granularity</Label>
          <Select value={gran} onValueChange={v => setGran(v ?? 'day')}>
            <SelectTrigger className="h-9 w-32"><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value="day">Daily</SelectItem><SelectItem value="week">Weekly</SelectItem><SelectItem value="month">Monthly</SelectItem></SelectContent>
          </Select>
        </div>
        <div className="flex gap-1">
          <Button variant="outline" size="sm" onClick={() => { setFrom(daysAgo(7)); setTo(today()); }}>7d</Button>
          <Button variant="outline" size="sm" onClick={() => { setFrom(daysAgo(30)); setTo(today()); }}>30d</Button>
          <Button variant="outline" size="sm" onClick={() => { setFrom(daysAgo(90)); setTo(today()); }}>90d</Button>
        </div>
      </div>
      {totals && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <Kpi label="Fleet distance" value={`${num(totals.distance_km)} km`} />
          <Kpi label="Diesel used" value={`${num(totals.litres, 0)} L`} />
          <Kpi label="Fleet mileage" value={totals.avg_kmpl == null ? '—' : `${num(totals.avg_kmpl, 2)} km/l`} />
          <Kpi label="Excess diesel cost" value={INR(totals.total_excess_cost)} tone={(totals.total_excess_cost || 0) > 0 ? 'text-red-600' : ''} sub="vs benchmark" />
          <Kpi label="Leaking vehicles" value={String(totals.leaking_vehicles)} tone={totals.leaking_vehicles > 0 ? 'text-red-600' : 'text-emerald-600'} />
        </div>
      )}
      {loading ? <div className="flex justify-center py-10"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
        : <DataTable<MileageRow> id="fuel.mileage" data={rows} columns={COLS} rowKey={r => r.vehicle_id} exportFilename="mileage-report" emptyMessage="No mileage data — record at least two fills per vehicle" />}
    </div>
  );
}

// ── Trends tab ────────────────────────────────────────────────────────────────
function TrendsTab({ vehicles }: { vehicles: Vehicle[] }) {
  const [vehicleId, setVehicleId] = useState('');
  const [gran, setGran] = useState('week');
  const [series, setSeries] = useState<SeriesPoint[]>([]);
  const [benchmark, setBenchmark] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => { if (!vehicleId && vehicles.length) setVehicleId(vehicles[0].id); }, [vehicles, vehicleId]);
  const load = useCallback(async () => {
    if (!vehicleId) return;
    setLoading(true);
    try {
      const p = new URLSearchParams({ date_from: daysAgo(180), date_to: today(), granularity: gran, vehicle_id: vehicleId });
      const { data } = await api.get<{ series: SeriesPoint[]; summary: MileageRow[] }>(`/api/v1/fuel/mileage-report?${p}`);
      setSeries(data.series ?? []);
      setBenchmark(data.summary?.[0]?.benchmark_kmpl ?? null);
    } catch { setSeries([]); } finally { setLoading(false); }
  }, [vehicleId, gran]);
  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-2">
        <div className="space-y-1"><Label className="text-xs">Vehicle</Label>
          <Select value={vehicleId} onValueChange={v => setVehicleId(v ?? '')}>
            <SelectTrigger className="h-9 w-48"><SelectValue placeholder="Select vehicle">
              {vehicles.find(v => v.id === vehicleId)?.registration_no}
            </SelectValue></SelectTrigger>
            <SelectContent>{vehicles.map(v => <SelectItem key={v.id} value={v.id}>{v.registration_no}</SelectItem>)}</SelectContent>
          </Select>
        </div>
        <div className="space-y-1"><Label className="text-xs">Granularity</Label>
          <Select value={gran} onValueChange={v => setGran(v ?? 'week')}>
            <SelectTrigger className="h-9 w-32"><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value="day">Daily</SelectItem><SelectItem value="week">Weekly</SelectItem><SelectItem value="month">Monthly</SelectItem></SelectContent>
          </Select>
        </div>
      </div>
      {loading ? <div className="flex justify-center py-10"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
        : series.length === 0 ? <p className="py-10 text-center text-sm text-muted-foreground">No fills for this vehicle in the last 180 days.</p>
        : (
        <>
          <Card><CardHeader className="pb-2"><CardTitle className="text-sm">Mileage vs Benchmark (km/l)</CardTitle></CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={260}>
                <LineChart data={series} margin={{ left: -10, right: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                  <XAxis dataKey="period" fontSize={11} /><YAxis fontSize={11} />
                  <Tooltip /><Legend />
                  {benchmark != null && <ReferenceLine y={benchmark} stroke="#16a34a" strokeDasharray="5 3" label={{ value: `benchmark ${num(benchmark, 1)}`, fontSize: 10, fill: '#16a34a' }} />}
                  <Line type="monotone" dataKey="actual_kmpl" name="Actual km/l" stroke="#2563eb" strokeWidth={2} dot={{ r: 3 }} connectNulls />
                </LineChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
          <Card><CardHeader className="pb-2"><CardTitle className="text-sm">Diesel consumed &amp; distance per period</CardTitle></CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={series} margin={{ left: -10, right: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                  <XAxis dataKey="period" fontSize={11} /><YAxis yAxisId="l" fontSize={11} /><YAxis yAxisId="r" orientation="right" fontSize={11} />
                  <Tooltip /><Legend />
                  <Bar yAxisId="l" dataKey="litres" name="Diesel (L)" fill="#f59e0b" radius={[3, 3, 0, 0]} />
                  <Bar yAxisId="r" dataKey="distance_km" name="Distance (km)" fill="#3b82f6" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}

// ── Leakage tab ───────────────────────────────────────────────────────────────
function LeakageTab() {
  const [days, setDays] = useState(30);
  const [alerts, setAlerts] = useState<MileageRow[]>([]);
  const [threshold, setThreshold] = useState(15);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get<{ alerts: MileageRow[]; threshold_pct: number }>(`/api/v1/fuel/leakage-alerts?days=${days}`);
      setAlerts(data.alerts ?? []); setThreshold(data.threshold_pct ?? 15);
    } catch { setAlerts([]); } finally { setLoading(false); }
  }, [days]);
  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Label className="text-xs">Window</Label>
        <Select value={String(days)} onValueChange={v => setDays(Number(v ?? 30))}>
          <SelectTrigger className="h-9 w-32"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value="7">Last 7 days</SelectItem><SelectItem value="30">Last 30 days</SelectItem><SelectItem value="90">Last 90 days</SelectItem></SelectContent>
        </Select>
        <span className="text-xs text-muted-foreground">Flagging mileage ≥ {threshold}% below benchmark</span>
      </div>
      {loading ? <div className="flex justify-center py-10"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
        : alerts.length === 0 ? (
        <Card><CardContent className="py-12 text-center">
          <div className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-full bg-emerald-100"><Fuel className="h-7 w-7 text-emerald-600" /></div>
          <p className="font-medium">No leakage detected</p>
          <p className="text-sm text-muted-foreground">Every vehicle is within its benchmark for this window.</p>
        </CardContent></Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {alerts.map(a => (
            <Card key={a.vehicle_id} className={a.status === 'leak' ? 'border-red-200' : 'border-amber-200'}>
              <CardContent className="p-4">
                <div className="flex items-start justify-between">
                  <div>
                    <p className="font-semibold">
                      {a.vehicle_id
                        ? <Link to={`/vehicles/${a.vehicle_id}/history`} className="text-blue-700 hover:underline">{a.registration_no}</Link>
                        : a.registration_no}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {num(a.actual_kmpl, 2)} km/l vs benchmark {num(a.benchmark_kmpl, 2)}{a.benchmark_source === 'auto' ? ' (auto)' : ''}
                    </p>
                  </div>
                  <Badge variant="outline" className={STATUS_STYLE[a.status]}>{num(a.deviation_pct, 1)}% below</Badge>
                </div>
                <div className="mt-3 grid grid-cols-3 gap-2 text-center">
                  <div><p className="text-xs text-muted-foreground">Distance</p><p className="text-sm font-mono">{num(a.distance_km)} km</p></div>
                  <div><p className="text-xs text-muted-foreground">Excess diesel</p><p className="text-sm font-mono text-red-600">{num(a.excess_litres, 1)} L</p></div>
                  <div><p className="text-xs text-muted-foreground">Excess ₹</p><p className="text-sm font-mono text-red-600">{a.excess_cost == null ? <span className="text-muted-foreground" title="No rate per litre recorded on the fills for this vehicle">no rate</span> : INR(a.excess_cost)}</p></div>
                  <div><p className="text-xs text-muted-foreground">Can still run</p><p className="text-sm font-mono">{a.range_km == null ? <span className="text-muted-foreground" title={a.range_note || ''}>—</span> : `${num(a.range_km, 0)} km`}</p></div>
                </div>
                {a.flags?.length ? <p className="mt-2 text-xs text-amber-700">⚠ {a.flags.map(f => FLAG_LABEL[f] || f).join(', ')}</p> : null}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Settings tab ──────────────────────────────────────────────────────────────
interface InvItem { id: string; name: string; unit: string; current_stock: number; }
function FuelSettingsTab() {
  const [cfg, setCfg] = useState<Record<string, unknown>>({});
  const [items, setItems] = useState<InvItem[]>([]);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState('');

  useEffect(() => {
    api.get<Record<string, unknown>>('/api/v1/fuel/config').then(r => setCfg(r.data)).catch(() => {});
    api.get<{ items?: InvItem[] } | InvItem[]>('/api/v1/inventory/items').then(r => setItems(Array.isArray(r.data) ? r.data : (r.data.items ?? []))).catch(() => {});
  }, []);
  const set = (k: string, v: unknown) => setCfg(c => ({ ...c, [k]: v }));

  async function save() {
    setSaving(true); setMsg('');
    try { await api.put('/api/v1/fuel/config', cfg); setMsg('Saved'); }
    catch { setMsg('Save failed'); } finally { setSaving(false); }
  }

  return (
    <Card><CardContent className="p-5 space-y-4 max-w-xl">
      <div className="space-y-1">
        <Label>Diesel store item (plant tank)</Label>
        <Select value={String(cfg.diesel_item_id ?? '')} onValueChange={v => set('diesel_item_id', v || null)}>
          <SelectTrigger><SelectValue placeholder="None — plant-tank fills won't deduct stock">
            {items.find(i => i.id === cfg.diesel_item_id)?.name}
          </SelectValue></SelectTrigger>
          <SelectContent>
            {items.map(i => <SelectItem key={i.id} value={i.id}>{i.name} ({num(i.current_stock, 0)} {i.unit})</SelectItem>)}
          </SelectContent>
        </Select>
        <p className="text-[11px] text-muted-foreground">A plant-tank fill deducts its litres from this store item. Create a "Diesel" item (unit Litre) under Store Inventory first.</p>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1"><Label>Leakage threshold (%)</Label>
          <Input type="number" min="1" step="1" value={Number(cfg.deviation_threshold_pct ?? 15)} onChange={e => set('deviation_threshold_pct', parseFloat(e.target.value) || 0)} />
          <p className="text-[11px] text-muted-foreground">Flag when mileage is this % below benchmark.</p>
        </div>
        <div className="space-y-1"><Label>Min distance (km)</Label>
          <Input type="number" min="0" step="1" value={Number(cfg.min_distance_km ?? 50)} onChange={e => set('min_distance_km', parseFloat(e.target.value) || 0)} />
          <p className="text-[11px] text-muted-foreground">Ignore very short intervals.</p>
        </div>
        <div className="space-y-1"><Label>Auto-learn window (days)</Label>
          <Input type="number" min="7" step="1" value={Number(cfg.auto_learn_days ?? 90)} onChange={e => set('auto_learn_days', parseFloat(e.target.value) || 0)} />
          <p className="text-[11px] text-muted-foreground">History used to learn each vehicle's baseline.</p>
        </div>
        <label className="flex items-center gap-2 text-sm pt-6">
          <input type="checkbox" checked={cfg.alert_enabled !== false} onChange={e => set('alert_enabled', e.target.checked)} />
          Send leakage alert on a leaking fill
        </label>
        <div className="space-y-1">
          <Label>Petrol-pump due alert (₹)</Label>
          <Input type="number" min="0" step="1000" value={Number(cfg.pump_alert_threshold ?? 0)} onChange={e => set('pump_alert_threshold', parseFloat(e.target.value) || 0)} />
          <p className="text-[11px] text-muted-foreground">Telegram alert when a pump's outstanding crosses this. 0 = off.</p>
        </div>
      </div>
      <div className="flex items-center gap-3">
        <Button onClick={save} disabled={saving}>{saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}Save Settings</Button>
        {msg && <span className="text-sm text-muted-foreground">{msg}</span>}
      </div>
    </CardContent></Card>
  );
}
