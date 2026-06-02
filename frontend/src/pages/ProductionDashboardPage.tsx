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
  ResponsiveContainer, CartesianGrid, ReferenceLine,
} from 'recharts';
import { Activity, TrendingDown, Factory, AlertOctagon, Target } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import api from '@/services/api';

interface StageDefault {
  stage_no: number;
  stage_name: string;
  loss_type: string;
  expected_yield_pct: number;
  warning_threshold_pct: number;
}
interface StageDefaultsResponse {
  stages: StageDefault[];
  overall_expected_yield_pct: number;
}

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
  const [defaults, setDefaults] = useState<StageDefaultsResponse | null>(null);
  const [days, setDays] = useState(30);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [d, sd] = await Promise.all([
        api.get<DashboardData>(`/api/v1/production/dashboard?days=${days}`),
        api.get<StageDefaultsResponse>('/api/v1/production/stage-defaults'),
      ]);
      setData(d.data);
      setDefaults(sd.data);
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => { load(); }, [load]);

  const s = data?.summary;
  const targetYield = defaults?.overall_expected_yield_pct ?? 80.8;
  const yieldVariance = s ? s.avg_yield_pct - targetYield : 0;
  const variancePositive = yieldVariance >= 0;

  // Build labels for stacked-bar chart from stage defaults
  const stageLabel = (n: number): string => {
    if (!defaults) return `Stage ${n}`;
    const sd = defaults.stages.find(x => x.stage_no === n);
    return sd ? `S${n}: ${sd.stage_name}` : `Stage ${n}`;
  };

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
              <p className="text-xs text-muted-foreground">Avg Plant Yield</p>
              <p className={`text-2xl font-bold ${(s?.avg_yield_pct ?? 0) > 80 ? 'text-green-600' : (s?.avg_yield_pct ?? 0) > 60 ? 'text-amber-600' : 'text-red-600'}`}>
                {(s?.avg_yield_pct ?? 0).toFixed(1)}%
              </p>
              <p className="text-xs text-muted-foreground">{((s?.output_total_kg ?? 0) / 1000).toFixed(1)} MT output</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 flex items-start gap-3">
            <Target className={`h-8 w-8 opacity-70 ${variancePositive ? 'text-emerald-600' : 'text-red-600'}`} />
            <div>
              <p className="text-xs text-muted-foreground">vs Target ({targetYield.toFixed(1)}%)</p>
              <p className={`text-2xl font-bold ${variancePositive ? 'text-emerald-700' : 'text-red-700'}`}>
                {variancePositive ? '+' : ''}{yieldVariance.toFixed(2)}%
              </p>
              <p className="text-xs text-muted-foreground">
                {variancePositive ? 'Above target' : 'Below target'}
              </p>
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
          <div className="flex items-center justify-between mb-2">
            <h2 className="font-semibold">Plant Yield % Trend</h2>
            <Badge variant="outline" className="text-xs">
              <Target className="h-3 w-3 mr-1" /> Target {targetYield.toFixed(1)}%
            </Badge>
          </div>
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
                <ReferenceLine
                  y={targetYield}
                  stroke="#dc2626"
                  strokeDasharray="6 4"
                  label={{ value: `Target ${targetYield.toFixed(1)}%`, position: 'right', fill: '#dc2626', fontSize: 11 }}
                />
                <Line type="monotone" dataKey="yield_pct" name="Actual Yield %" stroke="#16a34a" strokeWidth={2} dot={{ r: 3 }} />
              </LineChart>
            </ResponsiveContainer>
          )}
          <p className="text-xs text-muted-foreground mt-2">
            Red dashed line is the configured target (Settings → Production Settings). Points above are over-performing;
            below need investigation (worn liners, wet feed, oversize boulder, belt issues).
          </p>
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
                <Bar dataKey="stage1_loss_pct" stackId="a" name={stageLabel(1)} fill="#3b82f6" />
                <Bar dataKey="stage2_loss_pct" stackId="a" name={stageLabel(2)} fill="#06b6d4" />
                <Bar dataKey="stage3_loss_pct" stackId="a" name={stageLabel(3)} fill="#a855f7" />
                <Bar dataKey="belt_loss_pct"   stackId="a" name={stageLabel(4)} fill="#f97316" />
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
                <XAxis
                  type="number"
                  tickFormatter={v => `${(v / 1000).toFixed(1)}`}
                  label={{ value: 'MT', position: 'insideBottomRight', offset: -2 }}
                />
                <YAxis dataKey="product_name" type="category" width={140} />
                <Tooltip formatter={(v: number) => `${(v / 1000).toFixed(2)} MT`} />
                <Bar dataKey="total_output_kg" name="Total Output (MT)" fill="#10b981" />
              </BarChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
