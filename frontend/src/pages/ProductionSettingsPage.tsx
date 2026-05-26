/**
 * Production Settings — operator tuning for stage names + expected yields.
 *
 * The 4-stage crusher pipeline is fixed (1-4) but each stage's name, loss type,
 * expected yield %, and warning threshold can be configured. Saved to
 * app_settings under "production.stage_defaults" as a JSON blob.
 *
 * Industry-standard defaults pre-populate the form for new tenants:
 *   1. Primary Crushing — Dust & Spillage Loss — 97.5%
 *   2. Secondary Crushing — Dust & Spillage Loss — 97.0%
 *   3. Screening — Oversize Reject — 94.0%
 *   4. Washing (Conveyor Belt) — Silt / Wash Loss — 91.0%
 *
 * Overall expected plant yield is the product of all four stages.
 */
import { useEffect, useState, useCallback } from 'react';
import { Save, RotateCcw, Settings as SettingsIcon, AlertCircle, TrendingDown } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
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

const INDUSTRY_DEFAULTS: StageDefault[] = [
  { stage_no: 1, stage_name: 'Primary Crushing',       loss_type: 'Dust & Spillage Loss', expected_yield_pct: 97.5, warning_threshold_pct: 2.0 },
  { stage_no: 2, stage_name: 'Secondary Crushing',     loss_type: 'Dust & Spillage Loss', expected_yield_pct: 97.0, warning_threshold_pct: 2.0 },
  { stage_no: 3, stage_name: 'Screening',              loss_type: 'Oversize Reject',      expected_yield_pct: 94.0, warning_threshold_pct: 3.0 },
  { stage_no: 4, stage_name: 'Washing (Conveyor Belt)', loss_type: 'Silt / Wash Loss',    expected_yield_pct: 91.0, warning_threshold_pct: 3.0 },
];

function computeOverall(stages: StageDefault[]): number {
  return stages.reduce((acc, s) => acc * (s.expected_yield_pct / 100), 1) * 100;
}

export default function ProductionSettingsPage() {
  const [stages, setStages] = useState<StageDefault[]>(INDUSTRY_DEFAULTS);
  const [originalStages, setOriginalStages] = useState<StageDefault[]>(INDUSTRY_DEFAULTS);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get<StageDefaultsResponse>('/api/v1/production/stage-defaults');
      setStages(res.data.stages);
      setOriginalStages(res.data.stages);
    } catch {
      toast.error('Failed to load stage defaults');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const dirty = JSON.stringify(stages) !== JSON.stringify(originalStages);
  const overallExpected = computeOverall(stages);

  function updateStage<K extends keyof StageDefault>(stage_no: number, key: K, value: StageDefault[K]) {
    setStages(s => s.map(st => st.stage_no === stage_no ? { ...st, [key]: value } : st));
  }

  async function handleSave() {
    // Validation
    for (const s of stages) {
      if (!s.stage_name.trim()) {
        toast.error(`Stage ${s.stage_no}: name required`);
        return;
      }
      if (s.expected_yield_pct <= 0 || s.expected_yield_pct > 100) {
        toast.error(`Stage ${s.stage_no}: yield must be between 0 and 100`);
        return;
      }
      if (s.warning_threshold_pct < 0 || s.warning_threshold_pct > 50) {
        toast.error(`Stage ${s.stage_no}: threshold must be between 0 and 50`);
        return;
      }
    }
    setSaving(true);
    try {
      const res = await api.put<StageDefaultsResponse>('/api/v1/production/stage-defaults', { stages });
      setStages(res.data.stages);
      setOriginalStages(res.data.stages);
      toast.success(`Saved — new plant yield target: ${res.data.overall_expected_yield_pct.toFixed(2)}%`);
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail ?? 'Save failed');
    } finally {
      setSaving(false);
    }
  }

  function handleResetToIndustry() {
    if (!confirm('Reset all 4 stages to industry-standard defaults? Save afterwards to persist.')) return;
    setStages([...INDUSTRY_DEFAULTS]);
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight flex items-center gap-2">
            <SettingsIcon className="h-7 w-7" /> Production Stage Defaults
          </h1>
          <p className="text-muted-foreground">
            Tune the 4-stage crusher pipeline. Defaults are used to flag below-target yield on every cycle.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={handleResetToIndustry}>
            <RotateCcw className="mr-2 h-4 w-4" /> Reset to industry defaults
          </Button>
          <Button onClick={handleSave} disabled={!dirty || saving}>
            <Save className="mr-2 h-4 w-4" />
            {saving ? 'Saving…' : 'Save Changes'}
          </Button>
        </div>
      </div>

      {/* Overall expected yield card */}
      <Card>
        <CardContent className="pt-4 flex items-center justify-between flex-wrap gap-2">
          <div className="flex items-center gap-3">
            <div className="rounded-full bg-emerald-100 p-2">
              <TrendingDown className="h-5 w-5 text-emerald-700 rotate-180" />
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Overall Expected Plant Yield</p>
              <p className="text-2xl font-bold text-emerald-700">{overallExpected.toFixed(2)}%</p>
              <p className="text-xs text-muted-foreground">
                Compound of all 4 stages: {stages.map(s => `${s.expected_yield_pct.toFixed(1)}%`).join(' × ')}
              </p>
            </div>
          </div>
          <div className="text-xs text-muted-foreground max-w-md text-right">
            Cycles with plant yield within ±1.5% of target are tagged "On Target".
            Below the warning thresholds → operations team is alerted.
          </div>
        </CardContent>
      </Card>

      {/* Per-stage editor cards */}
      <div className="space-y-3">
        {loading ? (
          <p className="text-center text-muted-foreground py-8">Loading…</p>
        ) : stages.map((s) => {
          const lossPct = 100 - s.expected_yield_pct;
          return (
            <Card key={s.stage_no} className="overflow-hidden">
              <CardContent className="p-0">
                <div className="bg-muted/30 px-4 py-2 border-b flex items-center gap-2">
                  <Badge variant="outline" className="h-6 px-2 font-bold">STAGE {s.stage_no}</Badge>
                  <p className="font-semibold">{s.stage_name || `(unnamed)`}</p>
                  <span className="text-xs text-muted-foreground ml-auto">
                    Loss: {lossPct.toFixed(2)}% expected
                  </span>
                </div>
                <div className="p-4 grid grid-cols-1 md:grid-cols-4 gap-4">
                  <div className="space-y-1 md:col-span-2">
                    <Label className="text-xs">Stage Name</Label>
                    <Input
                      value={s.stage_name}
                      onChange={e => updateStage(s.stage_no, 'stage_name', e.target.value)}
                      placeholder="e.g. Primary Crushing"
                    />
                  </div>
                  <div className="space-y-1 md:col-span-2">
                    <Label className="text-xs">Loss Type (industry term)</Label>
                    <Input
                      value={s.loss_type}
                      onChange={e => updateStage(s.stage_no, 'loss_type', e.target.value)}
                      placeholder="e.g. Silt Loss"
                    />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">Expected Yield %</Label>
                    <Input
                      type="number" min="0" max="100" step="0.1"
                      value={s.expected_yield_pct}
                      onChange={e => updateStage(s.stage_no, 'expected_yield_pct', parseFloat(e.target.value) || 0)}
                    />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">Warning Threshold ±%</Label>
                    <Input
                      type="number" min="0" max="50" step="0.5"
                      value={s.warning_threshold_pct}
                      onChange={e => updateStage(s.stage_no, 'warning_threshold_pct', parseFloat(e.target.value) || 0)}
                    />
                    <p className="text-[10px] text-muted-foreground">
                      Beyond this variance, the cycle is flagged.
                    </p>
                  </div>
                  <div className="md:col-span-2 flex items-end">
                    <div className="text-xs space-y-1 w-full bg-amber-50 border border-amber-200 rounded p-2">
                      <p className="text-amber-700 font-semibold">Expected this stage:</p>
                      <p>Yield: <span className="font-mono">{s.expected_yield_pct.toFixed(2)}%</span></p>
                      <p>Loss: <span className="font-mono">{lossPct.toFixed(2)}%</span></p>
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      <div className="flex items-start gap-2 text-xs text-muted-foreground bg-muted/40 rounded p-3">
        <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
        <div>
          <p className="font-medium">How these defaults are used</p>
          <p>
            When operators create a production cycle, they enter actual weights at each stage.
            The system computes the actual yield % and compares it to your expected yield. If the
            variance exceeds the warning threshold, the stage card turns amber or red so operations
            can investigate (worn liners, wet feed, oversized boulder, etc.). Below the threshold,
            it stays green — On Target.
          </p>
        </div>
      </div>
    </div>
  );
}
