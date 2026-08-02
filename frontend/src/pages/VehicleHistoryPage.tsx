/**
 * Vehicle history — drill-down from the Fuel-vs-Rent report's vehicle link.
 *
 * Shows the business owner every diesel fill (when · how much · odometer · ₹) and
 * every rent trip (when · km · rent · customer/material) for one vehicle, plus the
 * current fuel-left / odometer estimate. Route: /vehicles/:id/history.
 */
import { useEffect, useState, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Fuel, Truck, Loader2, Gauge } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { DataTable, type ColumnDef } from '@/components/DataTable';
import api from '@/services/api';

const INR = (v: number | null | undefined) =>
  '₹' + Number(v ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 0 });
const num = (v: number | null | undefined, d = 0) =>
  Number(v ?? 0).toLocaleString('en-IN', { minimumFractionDigits: d, maximumFractionDigits: d });
const fmtDate = (s: string | null) =>
  s ? new Date(s + 'T00:00:00').toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }) : '—';

interface Fill {
  entry_date: string | null; odometer_km: number | null; litres: number | null;
  rate_per_litre: number | null; amount: number | null; fuel_source: string | null;
  tank_full: boolean; notes: string | null;
}
interface Trip {
  token_no: string | null; token_id: string; trip_date: string | null;
  rent_km: number | null; vehicle_rent: number | null; net_weight: number | null;
  party: string | null; product: string | null;
}
interface History {
  vehicle: {
    id: string; registration_no: string; tank_capacity_litres: number | null;
    benchmark_mileage_kmpl: number | null; current_odometer_km: number | null;
    fuel_left_est: number | null; odometer_est: number | null;
  };
  fuel_fills: Fill[]; trips: Trip[];
  summary: {
    total_litres: number; total_fuel_cost: number; fills_count: number;
    total_rent_km: number; total_rent_earned: number; trips_count: number;
  };
}

export default function VehicleHistoryPage() {
  const { id } = useParams<{ id: string }>();
  const nav = useNavigate();
  const [data, setData] = useState<History | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(() => {
    if (!id) return;
    setLoading(true);
    api.get<History>(`/api/v1/fuel/vehicle/${id}/history`)
      .then(r => setData(r.data))
      .catch(e => setError((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed to load vehicle history'))
      .finally(() => setLoading(false));
  }, [id]);
  useEffect(() => { load(); }, [load]);

  const FILL_COLS: ColumnDef<Fill>[] = [
    { key: 'entry_date', label: 'Date', type: 'date', accessor: r => r.entry_date, format: v => fmtDate(v as string) },
    { key: 'odometer_km', label: 'Odometer (km)', type: 'number', align: 'right', accessor: r => r.odometer_km ?? -1,
      format: (_v, r) => r.odometer_km == null ? '—' : num(r.odometer_km, 0), exportValue: r => r.odometer_km ?? '' },
    { key: 'litres', label: 'Litres', type: 'number', align: 'right', accessor: r => r.litres ?? 0, format: v => num(v as number, 2) },
    { key: 'rate_per_litre', label: 'Rate ₹/L', type: 'number', align: 'right', accessor: r => r.rate_per_litre ?? 0,
      format: (_v, r) => r.rate_per_litre ? INR(r.rate_per_litre) : '—', exportValue: r => r.rate_per_litre ?? '' },
    { key: 'amount', label: 'Amount ₹', type: 'number', align: 'right', accessor: r => r.amount ?? 0,
      format: (_v, r) => r.amount ? <span className="text-rose-700">{INR(r.amount)}</span> : '—', exportValue: r => r.amount ?? '' },
    { key: 'fuel_source', label: 'Source', type: 'enum', enumOptions: ['plant_tank', 'outside_pump', 'other'],
      accessor: r => r.fuel_source ?? '', format: v => v ? String(v).replace(/_/g, ' ') : '—' },
    { key: 'tank_full', label: 'Tank full', accessor: r => r.tank_full ? 'Yes' : 'No',
      format: (_v, r) => r.tank_full ? <Badge variant="outline" className="text-[10px]">Full</Badge> : <span className="text-slate-400">—</span> },
  ];
  const TRIP_COLS: ColumnDef<Trip>[] = [
    { key: 'trip_date', label: 'Date', type: 'date', accessor: r => r.trip_date, format: v => fmtDate(v as string) },
    { key: 'token_no', label: 'Token', accessor: r => r.token_no ?? '', format: (_v, r) => r.token_no ?? '—' },
    { key: 'party', label: 'Customer', accessor: r => r.party ?? '', format: (_v, r) => r.party ?? '—' },
    { key: 'product', label: 'Material', accessor: r => r.product ?? '', format: (_v, r) => r.product ?? '—' },
    { key: 'rent_km', label: 'Rent km', type: 'number', align: 'right', accessor: r => r.rent_km ?? 0, format: v => num(v as number, 0) },
    { key: 'vehicle_rent', label: 'Rent ₹', type: 'number', align: 'right', accessor: r => r.vehicle_rent ?? 0,
      format: (_v, r) => <span className="text-emerald-700">{INR(r.vehicle_rent)}</span>, exportValue: r => r.vehicle_rent ?? 0 },
  ];

  if (loading) return <div className="flex justify-center py-16"><Loader2 className="h-6 w-6 animate-spin text-slate-400" /></div>;
  if (error) return (
    <div className="space-y-3">
      <Button variant="ghost" size="sm" onClick={() => nav(-1)}><ArrowLeft className="h-4 w-4 mr-1" /> Back</Button>
      <div className="rounded-lg border-2 border-rose-300 bg-rose-50 px-4 py-3 text-rose-800 text-sm">{error}</div>
    </div>
  );
  if (!data) return null;
  const v = data.vehicle; const s = data.summary;

  return (
    <div className="space-y-4">
      <Button variant="ghost" size="sm" onClick={() => nav(-1)}><ArrowLeft className="h-4 w-4 mr-1" /> Back</Button>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-lg"><Truck className="h-5 w-5 text-blue-600" /> {v.registration_no}</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          <Kpi label="Tank capacity" value={v.tank_capacity_litres ? `${num(v.tank_capacity_litres, 0)} L` : '—'} />
          <Kpi label="Benchmark" value={v.benchmark_mileage_kmpl ? `${num(v.benchmark_mileage_kmpl, 1)} km/L` : '—'} />
          <Kpi label="Odometer" value={v.odometer_est != null ? `${num(v.odometer_est, 0)} km` : '—'} />
          <Kpi label="Fuel left ≈" accent
            value={v.fuel_left_est != null ? `${num(v.fuel_left_est, 1)}${v.tank_capacity_litres ? ` / ${num(v.tank_capacity_litres, 0)}` : ''} L` : '—'} />
          <Kpi label="Total diesel" value={`${num(s.total_litres, 1)} L`} />
          <Kpi label="Total fuel ₹" value={INR(s.total_fuel_cost)} />
        </CardContent>
      </Card>

      <div>
        <h2 className="text-sm font-semibold mb-2 flex items-center gap-1.5">
          <Fuel className="h-4 w-4 text-rose-600" /> Diesel fills ({s.fills_count})
        </h2>
        <DataTable<Fill> id={`vehhist.fills.${id}`} data={data.fuel_fills} columns={FILL_COLS}
          rowKey={(r, i) => `${r.entry_date}|${r.odometer_km}|${i}`} exportFilename={`${v.registration_no}-fuel`}
          defaultSort={{ key: 'odometer_km', direction: 'desc' }} emptyMessage="No diesel fills recorded" />
      </div>

      <div>
        <h2 className="text-sm font-semibold mb-2 flex items-center gap-1.5">
          <Gauge className="h-4 w-4 text-blue-600" /> Rent trips ({s.trips_count}) — {num(s.total_rent_km, 0)} km · {INR(s.total_rent_earned)}
        </h2>
        <DataTable<Trip> id={`vehhist.trips.${id}`} data={data.trips} columns={TRIP_COLS}
          rowKey={(r, i) => r.token_id ?? String(i)} exportFilename={`${v.registration_no}-trips`}
          defaultSort={{ key: 'trip_date', direction: 'desc' }} emptyMessage="No rent trips recorded" />
      </div>
    </div>
  );
}

function Kpi({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className={`rounded-lg border p-2 ${accent ? 'border-amber-300 bg-amber-50' : 'bg-muted/30'}`}>
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="font-semibold text-sm">{value}</div>
    </div>
  );
}
