/**
 * Production cycle entry page.
 *
 * One cycle per day per the project decision. Operator enters:
 *  - Raw input weight (boulder fed into Stage 1)
 *  - Optional intermediate weights (Stage 1, 2, 3) for wastage tracking per stage
 *  - Per-product Stage 4 (post-wash) outputs
 *
 * Finalising a cycle posts its outputs to product_stock as cycle_output movements.
 */
import { useEffect, useState, useCallback } from 'react';
import { Plus, Factory, Trash2, CheckCircle, FileEdit, History } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger } from '@/components/ui/select';
import { DataTable, type ColumnDef } from '@/components/DataTable';
import api from '@/services/api';
import type { Product } from '@/types';

interface CycleOutput {
  id?: string;
  product_id: string;
  product_name?: string;
  output_kg: number;
}

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

// Variance helper: returns class names for green/amber/red badges
function varianceTone(actual: number, expected: number, threshold: number): {
  bg: string; text: string; label: string; emoji: string;
} {
  const variance = actual - expected;
  const absVar = Math.abs(variance);
  if (absVar <= threshold / 2) {
    return { bg: 'bg-emerald-100 border-emerald-300', text: 'text-emerald-800',
             label: 'On Target', emoji: '✓' };
  }
  if (absVar <= threshold) {
    return { bg: 'bg-amber-100 border-amber-300', text: 'text-amber-800',
             label: variance > 0 ? 'Above Target' : 'Slightly Off', emoji: '◐' };
  }
  return { bg: 'bg-red-100 border-red-300', text: 'text-red-800',
           label: variance > 0 ? 'Above Target' : 'Below Target', emoji: '✕' };
}

interface ProductionCycle {
  id: string;
  cycle_no: number;
  cycle_date: string;
  input_kg: number;
  stage1_output_kg: number | null;
  stage2_output_kg: number | null;
  stage3_output_kg: number | null;
  total_output_kg: number;
  yield_pct: number | null;
  belt_loss_pct: number | null;
  wastage_kg: number;
  is_finalised: boolean;
  notes: string | null;
  outputs: CycleOutput[];
  created_at: string;
}

const today = () => new Date().toISOString().split('T')[0];
const fmtKg = (n: number | null | undefined) =>
  n == null ? '—' : `${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 2 })} kg`;
const fmtPct = (n: number | null | undefined) =>
  n == null ? '—' : `${n.toFixed(2)}%`;

// ─── Column definitions for the cycles DataTable ─────────────────────────────
// Defined as a module-level constant so the DataTable's reference equality on
// `columns` is stable across renders.
const CYCLE_COLUMNS: ColumnDef<ProductionCycle>[] = [
  {
    key: 'cycle_date', label: 'Date', type: 'date',
    accessor: c => c.cycle_date,
    format: v => new Date(String(v)).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }),
    exportValue: c => c.cycle_date,
  },
  {
    key: 'cycle_no', label: 'Cycle #', type: 'number', align: 'right',
    accessor: c => c.cycle_no,
    className: 'font-mono',
  },
  {
    key: 'input_kg', label: 'Input', type: 'number', align: 'right',
    accessor: c => c.input_kg,
    format: v => fmtKg(v as number),
    className: 'font-mono',
  },
  {
    key: 'stage1_output_kg', label: 'Stage 1', type: 'number', align: 'right', defaultVisible: true,
    accessor: c => c.stage1_output_kg,
    format: v => fmtKg(v as number | null),
    className: 'font-mono text-muted-foreground',
  },
  {
    key: 'stage2_output_kg', label: 'Stage 2', type: 'number', align: 'right', defaultVisible: true,
    accessor: c => c.stage2_output_kg,
    format: v => fmtKg(v as number | null),
    className: 'font-mono text-muted-foreground',
  },
  {
    key: 'stage3_output_kg', label: 'Stage 3', type: 'number', align: 'right', defaultVisible: true,
    accessor: c => c.stage3_output_kg,
    format: v => fmtKg(v as number | null),
    className: 'font-mono text-muted-foreground',
  },
  {
    key: 'total_output_kg', label: 'Output (4)', type: 'number', align: 'right',
    accessor: c => c.total_output_kg,
    format: v => fmtKg(v as number),
    className: 'font-mono',
  },
  {
    // Products produced in this cycle — comma-separated, sortable by product count
    key: 'products', label: 'Products', type: 'string',
    accessor: c => c.outputs.map(o => o.product_name ?? '?').join(', '),
    format: (_, row) => (
      <div className="flex flex-wrap gap-1 max-w-[260px]">
        {row.outputs.length === 0
          ? <span className="text-muted-foreground italic text-xs">—</span>
          : row.outputs.map(o => (
              <Badge key={o.product_id} variant="secondary" className="text-[10px] font-normal">
                {o.product_name ?? '?'}
                <span className="ml-1 text-muted-foreground">
                  {(Number(o.output_kg) / 1000).toFixed(1)}t
                </span>
              </Badge>
            ))}
      </div>
    ),
    exportValue: c => c.outputs.map(o => `${o.product_name ?? '?'} (${(Number(o.output_kg) / 1000).toFixed(2)} MT)`).join('; '),
  },
  {
    key: 'yield_pct', label: 'Yield', type: 'number', align: 'right',
    accessor: c => c.yield_pct,
    format: v => {
      const n = v as number | null;
      const cls = (n ?? 0) > 80 ? 'text-green-600' : (n ?? 0) > 60 ? 'text-amber-600' : 'text-red-600';
      return <span className={`font-mono ${cls}`}>{fmtPct(n)}</span>;
    },
  },
  {
    key: 'belt_loss_pct', label: 'Belt Loss', type: 'number', align: 'right',
    accessor: c => c.belt_loss_pct,
    format: v => fmtPct(v as number | null),
    className: 'font-mono text-muted-foreground',
  },
  {
    key: 'status', label: 'Status', type: 'enum', align: 'center',
    enumOptions: ['Draft', 'Finalised'],
    accessor: c => c.is_finalised ? 'Finalised' : 'Draft',
    format: v => v === 'Finalised'
      ? <Badge className="bg-green-100 text-green-700 hover:bg-green-100">Finalised</Badge>
      : <Badge variant="secondary">Draft</Badge>,
  },
  {
    key: 'notes', label: 'Notes', type: 'string', defaultVisible: false,
    accessor: c => c.notes ?? '',
  },
];

export default function ProductionPage() {
  const [cycles, setCycles] = useState<ProductionCycle[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<ProductionCycle | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [cy, pr] = await Promise.all([
        api.get<{ items: ProductionCycle[] }>('/api/v1/production/cycles?page_size=50'),
        api.get<{ items: Product[] } | Product[]>('/api/v1/products?page_size=200'),
      ]);
      setCycles(cy.data.items ?? []);
      const prods = Array.isArray(pr.data) ? pr.data : (pr.data as { items: Product[] }).items ?? [];
      setProducts(prods.filter(p => p.is_active));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const openCreate = () => { setEditing(null); setDialogOpen(true); };
  const openEdit = (c: ProductionCycle) => { setEditing(c); setDialogOpen(true); };

  const handleFinalise = async (c: ProductionCycle) => {
    if (!confirm(`Finalise cycle ${c.cycle_date}? Stock will be credited for ${c.outputs.length} product(s). This can't be undone.`)) return;
    try {
      await api.post(`/api/v1/production/cycles/${c.id}/finalise`);
      toast.success('Cycle finalised and stock posted');
      load();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail ?? 'Failed to finalise');
    }
  };

  const handleDelete = async (c: ProductionCycle) => {
    if (!confirm(`Delete draft cycle ${c.cycle_date}?`)) return;
    try {
      await api.delete(`/api/v1/production/cycles/${c.id}`);
      toast.success('Cycle deleted');
      load();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail ?? 'Delete failed');
    }
  };

  const totals = cycles.reduce((acc, c) => {
    acc.input += Number(c.input_kg || 0);
    acc.output += Number(c.total_output_kg || 0);
    if (c.yield_pct) { acc.yields.push(c.yield_pct); }
    return acc;
  }, { input: 0, output: 0, yields: [] as number[] });
  const avgYield = totals.yields.length > 0 ? totals.yields.reduce((a, b) => a + b, 0) / totals.yields.length : 0;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Production Cycles</h1>
          <p className="text-muted-foreground">
            One cycle per day. Track input, stage-wise weights, and per-product Stage 4 outputs.
          </p>
        </div>
        <Button onClick={openCreate}>
          <Plus className="mr-2 h-4 w-4" /> New Cycle
        </Button>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <Card><CardContent className="pt-4">
          <p className="text-xs text-muted-foreground">Cycles</p>
          <p className="text-2xl font-bold">{cycles.length}</p>
        </CardContent></Card>
        <Card><CardContent className="pt-4">
          <p className="text-xs text-muted-foreground">Total Input</p>
          <p className="text-2xl font-bold">{(totals.input / 1000).toFixed(2)} MT</p>
        </CardContent></Card>
        <Card><CardContent className="pt-4">
          <p className="text-xs text-muted-foreground">Total Output</p>
          <p className="text-2xl font-bold text-green-600">{(totals.output / 1000).toFixed(2)} MT</p>
        </CardContent></Card>
        <Card><CardContent className="pt-4">
          <p className="text-xs text-muted-foreground">Avg Yield</p>
          <p className={`text-2xl font-bold ${avgYield > 80 ? 'text-green-600' : avgYield > 60 ? 'text-amber-600' : 'text-red-600'}`}>
            {avgYield.toFixed(1)}%
          </p>
        </CardContent></Card>
      </div>

      {/* Cycles table — uses reusable DataTable (sortable, filterable, column show/hide, CSV export) */}
      <DataTable<ProductionCycle>
        id="production.cycles"
        loading={loading}
        data={cycles}
        rowKey={c => c.id}
        exportFilename="production-cycles"
        defaultSort={{ key: 'cycle_date', direction: 'desc' }}
        emptyMessage={`No cycles logged yet. Click "New Cycle" to record today's production.`}
        columns={CYCLE_COLUMNS}
        rowActions={c => (
          <div className="flex gap-1 justify-end">
            <Button variant="ghost" size="icon" title="Edit" onClick={() => openEdit(c)} disabled={c.is_finalised}>
              <FileEdit className="h-4 w-4" />
            </Button>
            {!c.is_finalised && (
              <Button variant="ghost" size="icon" title="Finalise" onClick={() => handleFinalise(c)}>
                <CheckCircle className="h-4 w-4 text-green-600" />
              </Button>
            )}
            {!c.is_finalised && (
              <Button variant="ghost" size="icon" title="Delete" onClick={() => handleDelete(c)}>
                <Trash2 className="h-4 w-4 text-red-600" />
              </Button>
            )}
          </div>
        )}
      />
      {!loading && cycles.length === 0 && (
        <div className="flex flex-col items-center justify-center py-8 text-center">
          <Factory className="h-10 w-10 mb-2 text-muted-foreground/40" />
          <p className="text-sm font-medium">No cycles logged yet</p>
        </div>
      )}

      <CycleDialog
        open={dialogOpen}
        editing={editing}
        products={products}
        onClose={() => setDialogOpen(false)}
        onSaved={() => { setDialogOpen(false); load(); }}
      />
    </div>
  );
}

// ------------------------------------------------------------------ //
// Cycle dialog (create + edit)
// ------------------------------------------------------------------ //

function CycleDialog({
  open, editing, products, onClose, onSaved,
}: {
  open: boolean;
  editing: ProductionCycle | null;
  products: Product[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [cycleDate, setCycleDate] = useState(today());
  const [inputKg, setInputKg] = useState('');
  const [stage1, setStage1] = useState('');
  const [stage2, setStage2] = useState('');
  const [stage3, setStage3] = useState('');
  const [notes, setNotes] = useState('');
  const [outputs, setOutputs] = useState<CycleOutput[]>([]);
  const [stageDefaults, setStageDefaults] = useState<StageDefault[]>([]);
  const [overallExpected, setOverallExpected] = useState<number>(80.8);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    // Load stage defaults each time the dialog opens
    api.get<StageDefaultsResponse>('/api/v1/production/stage-defaults').then(res => {
      setStageDefaults(res.data.stages);
      setOverallExpected(res.data.overall_expected_yield_pct);
    }).catch(() => {});

    if (editing) {
      setCycleDate(editing.cycle_date);
      setInputKg(String(editing.input_kg));
      setStage1(editing.stage1_output_kg != null ? String(editing.stage1_output_kg) : '');
      setStage2(editing.stage2_output_kg != null ? String(editing.stage2_output_kg) : '');
      setStage3(editing.stage3_output_kg != null ? String(editing.stage3_output_kg) : '');
      setNotes(editing.notes ?? '');
      setOutputs(editing.outputs.map(o => ({ product_id: o.product_id, output_kg: o.output_kg })));
    } else {
      setCycleDate(today());
      setInputKg('');
      setStage1(''); setStage2(''); setStage3('');
      setNotes('');
      setOutputs([]);
    }
  }, [open, editing]);

  const addOutputRow = () => setOutputs(o => [...o, { product_id: '', output_kg: 0 }]);
  const removeOutput = (idx: number) => setOutputs(o => o.filter((_, i) => i !== idx));
  const updateOutput = (idx: number, key: keyof CycleOutput, value: string | number) =>
    setOutputs(o => o.map((row, i) => i === idx ? { ...row, [key]: value } : row));

  const totalOutputKg = outputs.reduce((s, o) => s + Number(o.output_kg || 0), 0);
  const inp = parseFloat(inputKg) || 0;
  const s1 = parseFloat(stage1) || 0;
  const s2 = parseFloat(stage2) || 0;
  const s3 = parseFloat(stage3) || 0;
  const yieldPct = inp > 0 ? (totalOutputKg / inp) * 100 : 0;
  const beltLoss = s3 > 0 ? ((s3 - totalOutputKg) / s3) * 100 : null;

  // Per-stage yield calculations (each stage's output / previous stage's input)
  // Returns null if we don't have enough data to compute
  const stage1Yield = (inp > 0 && s1 > 0) ? (s1 / inp) * 100 : null;
  const stage2Yield = (s1 > 0 && s2 > 0) ? (s2 / s1) * 100 : null;
  const stage3Yield = (s2 > 0 && s3 > 0) ? (s3 / s2) * 100 : null;
  const stage4Yield = (s3 > 0 && totalOutputKg > 0) ? (totalOutputKg / s3) * 100 : null;
  const stageYields: (number | null)[] = [stage1Yield, stage2Yield, stage3Yield, stage4Yield];

  // Get default for a stage by number, with fallback
  const defaultFor = (n: number): StageDefault | undefined =>
    stageDefaults.find(s => s.stage_no === n);

  const handleSave = async () => {
    if (!inputKg || parseFloat(inputKg) <= 0) { toast.error('Input weight must be > 0'); return; }
    const cleanedOutputs = outputs
      .filter(o => o.product_id && Number(o.output_kg) > 0)
      .map(o => ({ product_id: o.product_id, output_kg: Number(o.output_kg) }));

    setSaving(true);
    try {
      const payload = {
        cycle_date: cycleDate,
        input_kg: parseFloat(inputKg),
        stage1_output_kg: stage1 ? parseFloat(stage1) : null,
        stage2_output_kg: stage2 ? parseFloat(stage2) : null,
        stage3_output_kg: stage3 ? parseFloat(stage3) : null,
        notes: notes.trim() || null,
        outputs: cleanedOutputs,
      };
      if (editing) {
        await api.put(`/api/v1/production/cycles/${editing.id}`, payload);
        toast.success('Cycle updated');
      } else {
        await api.post('/api/v1/production/cycles', payload);
        toast.success('Cycle created');
      }
      onSaved();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail ?? 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={o => !o && onClose()}>
      <DialogContent className="max-w-5xl w-[95vw] max-h-[92vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{editing ? `Edit Cycle — ${editing.cycle_date}` : 'New Production Cycle'}</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>Cycle Date *</Label>
              <Input type="date" value={cycleDate} onChange={e => setCycleDate(e.target.value)} disabled={!!editing} />
            </div>
            <div className="space-y-1">
              <Label>Input Weight (kg) — raw boulder *</Label>
              <Input type="number" min="0" step="1" value={inputKg} onChange={e => setInputKg(e.target.value)} />
            </div>
          </div>

          {/* Stages 1-3: simple weight entry with live yield card per stage */}
          <div className="space-y-2">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Process Stages</p>
            {[
              { n: 1, value: stage1, setter: setStage1, prevWeight: inp,
                placeholder: 'Output after primary crusher' },
              { n: 2, value: stage2, setter: setStage2, prevWeight: s1,
                placeholder: 'Output after secondary crusher' },
              { n: 3, value: stage3, setter: setStage3, prevWeight: s2,
                placeholder: 'Output after screening (pre-wash)' },
            ].map(({ n, value, setter, prevWeight, placeholder }) => {
              const def = defaultFor(n);
              const actualYield = stageYields[n - 1];
              const expected = def?.expected_yield_pct ?? 0;
              const threshold = def?.warning_threshold_pct ?? 2;
              const tone = actualYield != null
                ? varianceTone(actualYield, expected, threshold)
                : null;
              const lossKg = (prevWeight > 0 && parseFloat(value) > 0)
                ? prevWeight - parseFloat(value)
                : null;
              const lossPct = actualYield != null ? 100 - actualYield : null;

              return (
                <div key={n} className={`rounded-lg border-2 p-3 ${tone?.bg ?? 'border-border bg-card'}`}>
                  <div className="flex items-center justify-between mb-2 gap-2">
                    <div className="flex items-center gap-2 min-w-0">
                      <Badge variant="outline" className="shrink-0 h-5 px-1.5 text-[10px] font-bold">
                        STAGE {n}
                      </Badge>
                      <span className="font-semibold text-sm truncate">
                        {def?.stage_name ?? `Stage ${n}`}
                      </span>
                    </div>
                    {def && (
                      <span className="text-[10px] text-muted-foreground shrink-0">
                        Target yield: {def.expected_yield_pct.toFixed(1)}%
                      </span>
                    )}
                  </div>
                  <div className="grid grid-cols-12 gap-2 items-end">
                    <div className="col-span-5">
                      <Label className="text-[10px]">Output weight (kg)</Label>
                      <Input
                        type="number" min="0" step="1"
                        value={value} onChange={e => setter(e.target.value)}
                        placeholder={placeholder}
                        className="h-8 text-sm"
                      />
                    </div>
                    <div className="col-span-2 text-center">
                      <Label className="text-[10px]">Yield %</Label>
                      <p className={`font-mono font-bold text-sm ${tone?.text ?? 'text-muted-foreground'}`}>
                        {actualYield != null ? `${actualYield.toFixed(2)}%` : '—'}
                      </p>
                    </div>
                    <div className="col-span-3 text-center">
                      <Label className="text-[10px]">{def?.loss_type ?? 'Loss'}</Label>
                      <p className="font-mono text-xs">
                        {lossKg != null && lossPct != null
                          ? <>{lossPct.toFixed(2)}% <span className="text-muted-foreground">({lossKg.toLocaleString('en-IN', { maximumFractionDigits: 0 })} kg)</span></>
                          : '—'}
                      </p>
                    </div>
                    <div className="col-span-2 text-center">
                      {tone ? (
                        <Badge className={`${tone.bg} ${tone.text} border text-[9px] font-semibold`}>
                          {tone.emoji} {tone.label}
                        </Badge>
                      ) : (
                        <span className="text-[10px] text-muted-foreground italic">Enter weight</span>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Stage 4: per-product outputs */}
          <div className={`rounded-lg border-2 p-3 ${
            (() => {
              const def = defaultFor(4);
              const yp = stage4Yield;
              if (yp == null || !def) return 'border-border bg-card';
              return varianceTone(yp, def.expected_yield_pct, def.warning_threshold_pct).bg;
            })()
          }`}>
            <div className="flex items-center justify-between mb-2 gap-2">
              <div className="flex items-center gap-2 min-w-0">
                <Badge variant="outline" className="shrink-0 h-5 px-1.5 text-[10px] font-bold">
                  STAGE 4
                </Badge>
                <span className="font-semibold text-sm truncate">
                  {defaultFor(4)?.stage_name ?? 'Washing (Conveyor Belt)'}
                </span>
              </div>
              <Button variant="outline" size="sm" onClick={addOutputRow}>
                <Plus className="mr-1 h-3 w-3" /> Add Product
              </Button>
            </div>

            {/* Stage 4 live metrics */}
            <div className="grid grid-cols-4 gap-2 mb-3 text-center text-xs">
              <div>
                <p className="text-muted-foreground">Total Output</p>
                <p className="font-mono font-semibold">{totalOutputKg.toLocaleString('en-IN', { maximumFractionDigits: 0 })} kg</p>
              </div>
              <div>
                <p className="text-muted-foreground">Stage 4 Yield</p>
                <p className="font-mono font-semibold">
                  {stage4Yield != null ? `${stage4Yield.toFixed(2)}%` : '—'}
                </p>
              </div>
              <div>
                <p className="text-muted-foreground">{defaultFor(4)?.loss_type ?? 'Belt Loss'}</p>
                <p className="font-mono font-semibold">
                  {beltLoss != null ? `${beltLoss.toFixed(2)}%` : '—'}
                </p>
              </div>
              <div>
                <p className="text-muted-foreground">Target Yield</p>
                <p className="font-mono font-semibold">
                  {defaultFor(4)?.expected_yield_pct.toFixed(1) ?? '—'}%
                </p>
              </div>
            </div>

            {/* Per-product Stage 4 outputs table */}
            {outputs.length === 0 ? (
              <p className="text-xs text-muted-foreground italic">No outputs added. Click "Add Product" above to record finished goods.</p>
            ) : (
              <table className="w-full text-sm">
                <thead className="border-b">
                  <tr>
                    <th className="text-left p-1 font-medium" style={{ minWidth: '320px' }}>Product</th>
                    <th className="text-right p-1 font-medium w-40">Output (kg)</th>
                    <th className="p-1 w-10"></th>
                  </tr>
                </thead>
                <tbody>
                  {outputs.map((o, i) => (
                    <tr key={i} className="border-b">
                      <td className="p-1">
                        <Select value={o.product_id || undefined} onValueChange={v => updateOutput(i, 'product_id', v ?? '')}>
                          <SelectTrigger className="h-8 text-xs">
                            <span className="truncate text-left flex-1">
                              {o.product_id
                                ? (products.find(p => p.id === o.product_id)?.name ?? '…')
                                : <span className="text-muted-foreground">Select product…</span>}
                            </span>
                          </SelectTrigger>
                          <SelectContent>
                            {products.map(p => (
                              <SelectItem key={p.id} value={p.id} disabled={outputs.some((x, j) => j !== i && x.product_id === p.id)}>
                                {p.name}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </td>
                      <td className="p-1">
                        <Input type="number" min="0" step="1" className="h-8 text-xs text-right"
                          value={o.output_kg || ''} onChange={e => updateOutput(i, 'output_kg', parseFloat(e.target.value) || 0)} />
                      </td>
                      <td className="p-1">
                        <Button variant="ghost" size="icon" onClick={() => removeOutput(i)}>
                          <Trash2 className="h-3 w-3 text-red-500" />
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div className="space-y-1">
            <Label>Notes</Label>
            <Input value={notes} onChange={e => setNotes(e.target.value)} placeholder="Optional — anything unusual about this run" />
          </div>

          {/* Plant-level overall metrics */}
          {(() => {
            const overallTone = (yieldPct > 0)
              ? varianceTone(yieldPct, overallExpected, 3)
              : null;
            const processLoss = inp > 0 ? 100 - yieldPct : 0;
            return (
              <div className={`rounded-lg border-2 p-3 ${overallTone?.bg ?? 'bg-blue-50/60 border-blue-200'}`}>
                <div className="flex items-center justify-between mb-2">
                  <p className="font-bold text-sm">🏭 Plant-level Summary</p>
                  {overallTone && (
                    <Badge className={`${overallTone.bg} ${overallTone.text} border text-[10px] font-semibold`}>
                      {overallTone.emoji} {overallTone.label}
                    </Badge>
                  )}
                </div>
                <div className="grid grid-cols-4 gap-2 text-center text-xs">
                  <div>
                    <p className="text-muted-foreground">Raw Input</p>
                    <p className="font-mono font-semibold">{(inp / 1000).toFixed(2)} MT</p>
                  </div>
                  <div>
                    <p className="text-muted-foreground">Final Output</p>
                    <p className="font-mono font-semibold">{(totalOutputKg / 1000).toFixed(2)} MT</p>
                  </div>
                  <div>
                    <p className="text-muted-foreground">Plant Yield</p>
                    <p className={`font-mono font-bold text-sm ${overallTone?.text ?? 'text-muted-foreground'}`}>
                      {inp > 0 ? `${yieldPct.toFixed(2)}%` : '—'}
                    </p>
                    <p className="text-[9px] text-muted-foreground">target {overallExpected.toFixed(1)}%</p>
                  </div>
                  <div>
                    <p className="text-muted-foreground">Process Loss</p>
                    <p className="font-mono font-semibold">
                      {inp > 0 ? `${processLoss.toFixed(2)}%` : '—'}
                    </p>
                    <p className="text-[9px] text-muted-foreground">
                      {inp > 0 ? `${((inp - totalOutputKg) / 1000).toFixed(2)} MT lost` : ''}
                    </p>
                  </div>
                </div>
              </div>
            );
          })()}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={handleSave} disabled={saving}>{saving ? 'Saving…' : editing ? 'Update Draft' : 'Create Cycle (Draft)'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

void History;  // reserved for future revision history view
