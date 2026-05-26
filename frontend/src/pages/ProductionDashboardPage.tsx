/**
 * Production Dashboard — yield, wastage, and conveyor-belt performance.
 *
 * Charts (from /api/v1/production/dashboard):
 *  1. Yield % trend (line)
 *  2. Wastage % by stage (stacked bar)
 *  3. Top product outputs
 *  4. Summary KPI cards including conveyor-belt avg loss
 */
import { useEffect, useState, useCallback } from 'react';
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip, Legend,
  ResponsiveContainer, CartesianGrid,
} from 'recharts';
import { Activity, TrendingDown, Factory, AlertOctagon } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import api from '@/services/api';

interface DashboardData {
  yield_trend: { date: string; yield_pct: number; input_kg: number; output_kg: number }[];
  wastage_by_stage: {
    date: string;
    stage1_loss_pct: number;
    stage2_loss_pct: number;
    stage3_loss_pct: number;
    belt_loss_pct: number;
  }[];
  top_outputs: { product_id: string; product_name: string; total_output_kg: number; avg_output_per_cycle: number }[];
  summary: {
    cycles_count: number;
    input_total_kg: number;
    output_total_kg: number;
    avg_yield_pct: number;
    avg_belt_loss_pct: number;
    total_wastage_kg: number;
  };
}

export default function ProductionDashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [days, setDays] = useState(30);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data: d } = await api.get<DashboardData>(`/api/v1/production/dashboard?days=${days}`);
      setData(d);
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => { load(); }, [load]);

  const s = data?.summary;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Production Dashboard</h1>
          <p className="text-muted-foreground">Yield, wastage, and conveyor-belt performance over time.</p>
        </div>
        <div className="flex gap-2">
          {[7, 30, 90, 365].map(d => (
            <Button key={d} size="sm" variant={days === d ? 'default' : 'outline'} onClick={() => setDays(d)}>
              {d === 365 ? '1 Year' : `${d} Days`}
            </Button>
          ))}
        </div>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card>
          <CardContent className="pt-4 flex items-start gap-3">
            <Factory className="h-8 w-8 text-blue-600 opacity-70" />
            <div>
              <p className="text-xs text-muted-foreground">Cycles</p>
              <p className="text-2xl font-bold">{s?.cycles_count ?? 0}</p>
              <p className="text-xs text-muted-foreground">{((s?.input_total_kg ?? 0) / 1000).toFixed(1)} MT input</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 flex items-start gap-3">
            <Activity className={`h-8 w-8 opacity-70 ${(s?.avg_yield_pct ?? 0) > 80 ? 'text-green-600' : (s?.avg_yield_pct ?? 0) > 60 ? 'text-amber-600' : 'text-red-600'}`} />
            <div>
              <p className="text-xs text-muted-foreground">Avg Yield</p>
              <p className={`text-2xl font-bold ${(s?.avg_yield_pct ?? 0) > 80 ? 'text-green-600' : (s?.avg_yield_pct ?? 0) > 60 ? 'text-amber-600' : 'text-red-600'}`}>
                {(s?.avg_yield_pct ?? 0).toFixed(1)}%
              </p>
              <p className="text-xs text-muted-foreground">{((s?.output_total_kg ?? 0) / 1000).toFixed(1)} MT output</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 flex items-start gap-3">
            <TrendingDown className="h-8 w-8 text-orange-600 opacity-70" />
            <div>
              <p className="text-xs text-muted-foreground">Conveyor Belt Loss (avg)</p>
              <p className="text-2xl font-bold text-orange-700">{(s?.avg_belt_loss_pct ?? 0).toFixed(2)}%</p>
              <p className="text-xs text-muted-foreground">Stage 4 wash loss</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 flex items-start gap-3">
            <AlertOctagon className="h-8 w-8 text-red-600 opacity-70" />
            <div>
              <p className="text-xs text-muted-foreground">Total Wastage</p>
              <p className="text-2xl font-bold text-red-700">{((s?.total_wastage_kg ?? 0) / 1000).toFixed(1)} MT</p>
              <p className="text-xs text-muted-foreground">All stages combined</p>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Yield Trend */}
      <Card>
        <CardContent className="pt-4">
          <h2 className="font-semibold mb-2">Yield % Trend</h2>
          {loading ? (
            <div className="h-72 flex items-center justify-center text-muted-foreground text-sm">Loading…</div>
          ) : (
            <ResponsiveContainer width="100%" height={280}>
              <LineChart data={data?.yield_trend ?? []}>
                <CartesianGrid strokeDasharray="3 3" opacity={0.4} />
                <XAxis dataKey="date" />
                <YAxis domain={[0, 100]} tickFormatter={v => `${v}%`} />
                <Tooltip formatter={(v: number) => `${v}%`} />
                <Legend />
                <Line type="monotone" dataKey="yield_pct" name="Yield %" stroke="#16a34a" strokeWidth={2} dot={{ r: 3 }} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>

      {/* Wastage by stage */}
      <Card>
        <CardContent className="pt-4">
          <h2 className="font-semibold mb-2">Wastage % by Stage</h2>
          <p className="text-xs text-muted-foreground mb-2">
            Each bar shows the loss at each stage of the day's cycle. The orange bar (belt loss) is the key
            measure of conveyor-belt washing efficiency.
          </p>
          {loading ? (
            <div className="h-72 flex items-center justify-center text-muted-foreground text-sm">Loading…</div>
          ) : (
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={data?.wastage_by_stage ?? []}>
                <CartesianGrid strokeDasharray="3 3" opacity={0.4} />
                <XAxis dataKey="date" />
                <YAxis tickFormatter={v => `${v}%`} />
                <Tooltip formatter={(v: number) => `${v}%`} />
                <Legend />
                <Bar dataKey="stage1_loss_pct" stackId="a" name="Stage 1 (Primary)" fill="#3b82f6" />
                <Bar dataKey="stage2_loss_pct" stackId="a" name="Stage 2 (Secondary)" fill="#06b6d4" />
                <Bar dataKey="stage3_loss_pct" stackId="a" name="Stage 3 (Screening)" fill="#a855f7" />
                <Bar dataKey="belt_loss_pct" stackId="a" name="Stage 4 (Conveyor Belt Wash)" fill="#f97316" />
              </BarChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>

      {/* Top product outputs */}
      <Card>
        <CardContent className="pt-4">
          <h2 className="font-semibold mb-2">Top Products by Output Volume</h2>
          {loading ? (
            <div className="h-64 flex items-center justify-center text-muted-foreground text-sm">Loading…</div>
          ) : !data?.top_outputs?.length ? (
            <div className="flex flex-col items-center justify-center py-12 text-muted-foreground text-sm">
              <Factory className="h-8 w-8 mb-2 opacity-40" />
              <p>No production data in this window.</p>
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={data.top_outputs} layout="vertical" margin={{ left: 80 }}>
                <CartesianGrid strokeDasharray="3 3" opacity={0.4} />
                <XAxis type="number" tickFormatter={v => `${(v / 1000).toFixed(1)}`} />
                <YAxis dataKey="product_name" type="category" width={140} />
                <Tooltip formatter={(v: number) => `${(v / 1000).toFixed(2)} MT`} />
                <Bar dataKey="total_output_kg" name="Total Output" fill="#10b981" />
              </BarChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
