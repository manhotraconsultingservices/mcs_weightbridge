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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import api from '@/services/api';
import type { Product } from '@/types';

interface CycleOutput {
  id?: string;
  product_id: string;
  product_name?: string;
  output_kg: number;
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

      {/* Cycles table */}
      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/50">
                  <th className="text-left p-3 font-medium">Date</th>
                  <th className="text-right p-3 font-medium">Cycle #</th>
                  <th className="text-right p-3 font-medium">Input</th>
                  <th className="text-right p-3 font-medium">Stage 1</th>
                  <th className="text-right p-3 font-medium">Stage 2</th>
                  <th className="text-right p-3 font-medium">Stage 3</th>
                  <th className="text-right p-3 font-medium">Output (4)</th>
                  <th className="text-right p-3 font-medium">Yield</th>
                  <th className="text-right p-3 font-medium">Belt Loss</th>
                  <th className="text-center p-3 font-medium">Status</th>
                  <th className="p-3"></th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr><td colSpan={11} className="text-center p-8 text-muted-foreground">Loading…</td></tr>
                ) : cycles.length === 0 ? (
                  <tr>
                    <td colSpan={11}>
                      <div className="flex flex-col items-center justify-center py-12 text-center">
                        <Factory className="h-10 w-10 mb-3 text-muted-foreground/40" />
                        <p className="text-sm font-medium">No cycles logged yet</p>
                        <p className="text-xs text-muted-foreground mt-1">Click "New Cycle" to record today's production.</p>
                      </div>
                    </td>
                  </tr>
                ) : cycles.map(c => (
                  <tr key={c.id} className="border-b hover:bg-muted/20">
                    <td className="p-3 font-medium">{new Date(c.cycle_date).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })}</td>
                    <td className="p-3 text-right font-mono">{c.cycle_no}</td>
                    <td className="p-3 text-right font-mono">{fmtKg(c.input_kg)}</td>
                    <td className="p-3 text-right font-mono text-muted-foreground">{fmtKg(c.stage1_output_kg)}</td>
                    <td className="p-3 text-right font-mono text-muted-foreground">{fmtKg(c.stage2_output_kg)}</td>
                    <td className="p-3 text-right font-mono text-muted-foreground">{fmtKg(c.stage3_output_kg)}</td>
                    <td className="p-3 text-right font-mono">{fmtKg(c.total_output_kg)}</td>
                    <td className="p-3 text-right">
                      <span className={`font-mono ${(c.yield_pct ?? 0) > 80 ? 'text-green-600' : (c.yield_pct ?? 0) > 60 ? 'text-amber-600' : 'text-red-600'}`}>
                        {fmtPct(c.yield_pct)}
                      </span>
                    </td>
                    <td className="p-3 text-right font-mono text-muted-foreground">{fmtPct(c.belt_loss_pct)}</td>
                    <td className="p-3 text-center">
                      {c.is_finalised
                        ? <Badge className="bg-green-100 text-green-700 hover:bg-green-100">Finalised</Badge>
                        : <Badge variant="secondary">Draft</Badge>}
                    </td>
                    <td className="p-3">
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
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

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
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
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
  const yieldPct = inp > 0 ? (totalOutputKg / inp) * 100 : 0;
  const s3 = parseFloat(stage3) || 0;
  const beltLoss = s3 > 0 ? ((s3 - totalOutputKg) / s3) * 100 : null;

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
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
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

          <div className="rounded border bg-muted/20 p-3 space-y-2">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Optional intermediate weights (for wastage-by-stage tracking)</p>
            <div className="grid grid-cols-3 gap-3">
              <div className="space-y-1">
                <Label className="text-xs">Stage 1 output (kg)</Label>
                <Input type="number" min="0" step="1" value={stage1} onChange={e => setStage1(e.target.value)} placeholder="Post primary crusher" />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Stage 2 output (kg)</Label>
                <Input type="number" min="0" step="1" value={stage2} onChange={e => setStage2(e.target.value)} placeholder="Post secondary crusher" />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Stage 3 output (kg)</Label>
                <Input type="number" min="0" step="1" value={stage3} onChange={e => setStage3(e.target.value)} placeholder="Post screening, pre-wash" />
              </div>
            </div>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label className="font-semibold">Stage 4 Outputs (per product, post-wash)</Label>
              <Button variant="outline" size="sm" onClick={addOutputRow}>
                <Plus className="mr-1 h-3 w-3" /> Add Product
              </Button>
            </div>
            {outputs.length === 0 ? (
              <p className="text-xs text-muted-foreground italic">No outputs added. Click "Add Product" to record finished goods.</p>
            ) : (
              <table className="w-full text-sm">
                <thead className="border-b">
                  <tr>
                    <th className="text-left p-1 font-medium">Product</th>
                    <th className="text-right p-1 font-medium w-32">Output (kg)</th>
                    <th className="p-1 w-10"></th>
                  </tr>
                </thead>
                <tbody>
                  {outputs.map((o, i) => (
                    <tr key={i} className="border-b">
                      <td className="p-1">
                        <Select value={o.product_id || undefined} onValueChange={v => updateOutput(i, 'product_id', v ?? '')}>
                          <SelectTrigger className="h-8 text-xs">
                            <SelectValue placeholder="Select product…" />
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

          {/* Live metrics preview */}
          <div className="rounded-lg bg-amber-50/60 border-2 border-amber-200 p-3 grid grid-cols-3 gap-2 text-xs">
            <div>
              <p className="text-muted-foreground">Total Output</p>
              <p className="font-mono font-semibold">{totalOutputKg.toLocaleString('en-IN')} kg</p>
            </div>
            <div>
              <p className="text-muted-foreground">Yield %</p>
              <p className={`font-mono font-semibold ${yieldPct > 80 ? 'text-green-700' : yieldPct > 60 ? 'text-amber-700' : 'text-red-700'}`}>
                {yieldPct.toFixed(2)}%
              </p>
            </div>
            <div>
              <p className="text-muted-foreground">Conveyor Belt Loss</p>
              <p className="font-mono font-semibold">{beltLoss == null ? '—' : `${beltLoss.toFixed(2)}%`}</p>
            </div>
          </div>
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
