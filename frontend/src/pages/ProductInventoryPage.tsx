/**
 * Finished-Goods Inventory (Product Stock).
 *
 * Shows current stock per product, low/out alerts, lets admins adjust stock
 * and set min level. Movement history drill-in.
 *
 * Stock is auto-debited on sale invoice finalise and auto-credited on
 * purchase invoice finalise + production cycle finalise — see backend
 * routers/product_stock.py.
 */
import { useEffect, useState, useCallback, useMemo } from 'react';
import { Plus, Minus, History, TrendingDown, AlertTriangle, RotateCw } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { DataTable, type ColumnDef } from '@/components/DataTable';
import api from '@/services/api';

interface ProductStockRow {
  id: string;
  product_id: string;
  product_name: string;
  unit: string;
  current_stock: number;
  min_stock_level: number;
  stock_status: 'ok' | 'low' | 'out';
  last_alerted_at: string | null;
  updated_at: string;
}

interface Movement {
  id: string;
  product_id: string;
  product_name: string;
  movement_type: string;
  quantity: number;
  stock_before: number;
  stock_after: number;
  reference_type: string | null;
  reference_no: string | null;
  notes: string | null;
  created_by_name: string | null;
  created_at: string;
}

const STATUS_BADGE: Record<string, string> = {
  ok:  'bg-green-100 text-green-700 hover:bg-green-100',
  low: 'bg-amber-100 text-amber-700 hover:bg-amber-100',
  out: 'bg-red-100 text-red-700 hover:bg-red-100',
};

const MV_LABELS: Record<string, string> = {
  opening: 'Opening',
  sale: 'Sale',
  purchase: 'Purchase',
  adjustment: 'Adjustment',
  cycle_output: 'Production',
  sale_cancelled: 'Sale (cancelled)',
  purchase_cancelled: 'Purchase (cancelled)',
};

const fmt = (n: number, unit: string) =>
  `${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 3 })} ${unit}`;

export default function ProductInventoryPage() {
  const [rows, setRows] = useState<ProductStockRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<'all' | 'low' | 'out'>('all');
  const [adjustOpen, setAdjustOpen] = useState(false);
  const [adjustRow, setAdjustRow] = useState<ProductStockRow | null>(null);
  const [historyRow, setHistoryRow] = useState<ProductStockRow | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = filter !== 'all' ? `?only=${filter}` : '';
      const { data } = await api.get<{ items: ProductStockRow[] }>(`/api/v1/product-stock${params}`);
      setRows(data.items ?? []);
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => { load(); }, [load]);

  const summary = {
    total: rows.length,
    ok: rows.filter(r => r.stock_status === 'ok').length,
    low: rows.filter(r => r.stock_status === 'low').length,
    out: rows.filter(r => r.stock_status === 'out').length,
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Finished-Goods Inventory</h1>
          <p className="text-muted-foreground">
            Stock auto-updates from sales (out), purchases (in), and production cycles (in).
          </p>
        </div>
        <Button variant="outline" onClick={load}>
          <RotateCw className="mr-2 h-4 w-4" /> Refresh
        </Button>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <Card><CardContent className="pt-4">
          <p className="text-xs text-muted-foreground">Total Products</p>
          <p className="text-2xl font-bold">{summary.total}</p>
        </CardContent></Card>
        <Card><CardContent className="pt-4">
          <p className="text-xs text-muted-foreground">In Stock</p>
          <p className="text-2xl font-bold text-green-600">{summary.ok}</p>
        </CardContent></Card>
        <Card><CardContent className="pt-4">
          <p className="text-xs text-muted-foreground">Low Stock</p>
          <p className="text-2xl font-bold text-amber-600">{summary.low}</p>
        </CardContent></Card>
        <Card><CardContent className="pt-4">
          <p className="text-xs text-muted-foreground">Out of Stock</p>
          <p className="text-2xl font-bold text-red-600">{summary.out}</p>
        </CardContent></Card>
      </div>

      {/* Filter tabs */}
      <div className="flex gap-2">
        {(['all', 'low', 'out'] as const).map(k => (
          <Button
            key={k}
            variant={filter === k ? 'default' : 'outline'}
            size="sm"
            onClick={() => setFilter(k)}
          >
            {k === 'all' ? 'All' : k === 'low' ? 'Low only' : 'Out only'}
          </Button>
        ))}
      </div>

      <ProductStockTable
        rows={rows}
        loading={loading}
        onAdjust={r => { setAdjustRow(r); setAdjustOpen(true); }}
        onHistory={r => setHistoryRow(r)}
      />

      <AdjustDialog
        open={adjustOpen}
        row={adjustRow}
        onClose={() => { setAdjustOpen(false); setAdjustRow(null); }}
        onSaved={() => { setAdjustOpen(false); setAdjustRow(null); load(); }}
      />
      <HistoryDialog
        row={historyRow}
        onClose={() => setHistoryRow(null)}
      />
    </div>
  );
}

// ------------------------------------------------------------------ //
// Product Stock DataTable
// ------------------------------------------------------------------ //
function ProductStockTable({
  rows, loading, onAdjust, onHistory,
}: {
  rows: ProductStockRow[];
  loading: boolean;
  onAdjust: (r: ProductStockRow) => void;
  onHistory: (r: ProductStockRow) => void;
}) {
  const columns = useMemo<ColumnDef<ProductStockRow>[]>(() => [
    { key: 'product_name', label: 'Product', accessor: r => r.product_name, className: 'font-medium' },
    {
      key: 'current_stock', label: 'Current Stock', type: 'number', align: 'right',
      accessor: r => r.current_stock,
      format: (v, r) => <span className="font-mono">{fmt(Number(v), r.unit)}</span>,
    },
    {
      key: 'min_stock_level', label: 'Min Level', type: 'number', align: 'right',
      accessor: r => r.min_stock_level,
      format: (v, r) => <span className="text-muted-foreground">{fmt(Number(v), r.unit)}</span>,
    },
    {
      key: 'stock_status', label: 'Status', type: 'enum', align: 'center',
      enumOptions: ['ok', 'low', 'out'],
      accessor: r => r.stock_status,
      format: v => <Badge className={STATUS_BADGE[String(v) as 'ok' | 'low' | 'out']}>{String(v).toUpperCase()}</Badge>,
    },
    {
      key: 'updated_at', label: 'Last Updated', type: 'date', align: 'right',
      accessor: r => r.updated_at,
      format: v => (
        <span className="text-xs text-muted-foreground">
          {new Date(String(v)).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })}
        </span>
      ),
    },
    { key: 'unit', label: 'Unit', defaultVisible: false, accessor: r => r.unit },
  ], []);

  return (
    <DataTable<ProductStockRow>
      id="product-stock.main"
      loading={loading}
      data={rows}
      columns={columns}
      rowKey={r => r.id}
      exportFilename="product-stock"
      defaultSort={{ key: 'product_name', direction: 'asc' }}
      emptyMessage="No products match this filter"
      rowActions={r => (
        <div className="flex gap-1 justify-end">
          <Button variant="ghost" size="icon" title="Adjust stock" onClick={() => onAdjust(r)}>
            <Plus className="h-4 w-4" />
          </Button>
          <Button variant="ghost" size="icon" title="View history" onClick={() => onHistory(r)}>
            <History className="h-4 w-4" />
          </Button>
        </div>
      )}
    />
  );
}

// ------------------------------------------------------------------ //
// Adjust dialog (combines adjust + set-min-level + opening-stock)
// ------------------------------------------------------------------ //

function AdjustDialog({
  open, row, onClose, onSaved,
}: {
  open: boolean;
  row: ProductStockRow | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [mode, setMode] = useState<'adjust' | 'min' | 'opening'>('adjust');
  const [quantity, setQuantity] = useState('');
  const [direction, setDirection] = useState<'in' | 'out'>('in');
  const [reason, setReason] = useState('');
  const [minLevel, setMinLevel] = useState('');
  const [openingQty, setOpeningQty] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open && row) {
      setMode(row.current_stock === 0 ? 'opening' : 'adjust');
      setQuantity('');
      setDirection('in');
      setReason('');
      setMinLevel(String(row.min_stock_level));
      setOpeningQty('');
    }
  }, [open, row]);

  if (!row) return null;

  const handleSave = async () => {
    setSaving(true);
    try {
      if (mode === 'adjust') {
        const qty = parseFloat(quantity);
        if (!Number.isFinite(qty) || qty <= 0) { toast.error('Enter a positive quantity'); setSaving(false); return; }
        if (!reason.trim()) { toast.error('Reason is required'); setSaving(false); return; }
        const signed = direction === 'in' ? qty : -qty;
        await api.post('/api/v1/product-stock/adjust', {
          product_id: row.product_id, quantity: signed, reason: reason.trim(),
        });
        toast.success(`Stock ${direction === 'in' ? 'added' : 'removed'}: ${qty} ${row.unit}`);
      } else if (mode === 'min') {
        const lvl = parseFloat(minLevel);
        if (!Number.isFinite(lvl) || lvl < 0) { toast.error('Min level must be >= 0'); setSaving(false); return; }
        await api.put(`/api/v1/product-stock/${row.product_id}/min-level`, { min_stock_level: lvl });
        toast.success('Min stock level updated');
      } else {
        const qty = parseFloat(openingQty);
        if (!Number.isFinite(qty) || qty <= 0) { toast.error('Enter a positive opening quantity'); setSaving(false); return; }
        await api.post('/api/v1/product-stock/opening', {
          product_id: row.product_id, opening_quantity: qty, notes: 'Opening stock entry',
        });
        toast.success(`Opening stock set: ${qty} ${row.unit}`);
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
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{row.product_name}</DialogTitle>
        </DialogHeader>

        <p className="text-xs text-muted-foreground">
          Current stock: <span className="font-mono font-semibold">{fmt(row.current_stock, row.unit)}</span> ·
          Min level: <span className="font-mono">{fmt(row.min_stock_level, row.unit)}</span>
        </p>

        <div className="flex gap-2 my-2">
          {row.current_stock === 0 && (
            <Button size="sm" variant={mode === 'opening' ? 'default' : 'outline'} onClick={() => setMode('opening')}>
              Opening Stock
            </Button>
          )}
          <Button size="sm" variant={mode === 'adjust' ? 'default' : 'outline'} onClick={() => setMode('adjust')}>
            Adjust Stock
          </Button>
          <Button size="sm" variant={mode === 'min' ? 'default' : 'outline'} onClick={() => setMode('min')}>
            Set Min Level
          </Button>
        </div>

        {mode === 'adjust' && (
          <div className="space-y-3">
            <div className="flex gap-2">
              <Button
                size="sm"
                variant={direction === 'in' ? 'default' : 'outline'}
                onClick={() => setDirection('in')}
                className="flex-1"
              ><Plus className="mr-1 h-3 w-3" /> Add</Button>
              <Button
                size="sm"
                variant={direction === 'out' ? 'default' : 'outline'}
                onClick={() => setDirection('out')}
                className="flex-1"
              ><Minus className="mr-1 h-3 w-3" /> Remove</Button>
            </div>
            <div className="space-y-1">
              <Label>Quantity ({row.unit})</Label>
              <Input type="number" min="0" step="0.001" value={quantity} onChange={e => setQuantity(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label>Reason</Label>
              <Input value={reason} onChange={e => setReason(e.target.value)} placeholder="e.g. Stocktake variance, damage write-off" />
            </div>
          </div>
        )}

        {mode === 'min' && (
          <div className="space-y-1">
            <Label>New Min Stock Level ({row.unit})</Label>
            <Input type="number" min="0" step="0.001" value={minLevel} onChange={e => setMinLevel(e.target.value)} />
            <p className="text-xs text-muted-foreground">Triggers low-stock alerts when current stock reaches this level.</p>
          </div>
        )}

        {mode === 'opening' && (
          <div className="space-y-1">
            <Label>Opening Stock ({row.unit})</Label>
            <Input type="number" min="0" step="0.001" value={openingQty} onChange={e => setOpeningQty(e.target.value)} />
            <p className="text-xs text-muted-foreground">One-time bootstrap. Use Adjust Stock for any later changes.</p>
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={handleSave} disabled={saving}>{saving ? 'Saving…' : 'Save'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ------------------------------------------------------------------ //
// History dialog — movement log
// ------------------------------------------------------------------ //

function HistoryDialog({ row, onClose }: { row: ProductStockRow | null; onClose: () => void }) {
  const [movements, setMovements] = useState<Movement[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!row) return;
    setLoading(true);
    api.get<{ items: Movement[] }>(`/api/v1/product-stock/movements?product_id=${row.product_id}&page_size=100`)
      .then(({ data }) => setMovements(data.items ?? []))
      .finally(() => setLoading(false));
  }, [row]);

  if (!row) return null;

  return (
    <Dialog open={!!row} onOpenChange={o => !o && onClose()}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>{row.product_name} — Movement History</DialogTitle>
        </DialogHeader>
        <div className="max-h-[60vh] overflow-y-auto">
          {loading ? (
            <p className="text-center py-6 text-muted-foreground">Loading…</p>
          ) : movements.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-10 text-muted-foreground">
              <TrendingDown className="h-8 w-8 mb-2 opacity-40" />
              <p className="text-sm">No movements yet for this product.</p>
            </div>
          ) : (
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-background border-b">
                <tr>
                  <th className="text-left p-2">Date</th>
                  <th className="text-left p-2">Type</th>
                  <th className="text-right p-2">Qty</th>
                  <th className="text-right p-2">Before → After</th>
                  <th className="text-left p-2">Reference</th>
                  <th className="text-left p-2">Notes</th>
                </tr>
              </thead>
              <tbody>
                {movements.map(m => (
                  <tr key={m.id} className="border-b hover:bg-muted/20">
                    <td className="p-2">{new Date(m.created_at).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })}</td>
                    <td className="p-2">{MV_LABELS[m.movement_type] ?? m.movement_type}</td>
                    <td className={`p-2 text-right font-mono ${Number(m.quantity) >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                      {Number(m.quantity) >= 0 ? '+' : ''}{fmt(Number(m.quantity), row.unit)}
                    </td>
                    <td className="p-2 text-right font-mono text-muted-foreground">
                      {Number(m.stock_before).toLocaleString('en-IN', { maximumFractionDigits: 3 })}
                      {' → '}
                      {Number(m.stock_after).toLocaleString('en-IN', { maximumFractionDigits: 3 })}
                    </td>
                    <td className="p-2 text-muted-foreground">{m.reference_no ?? '—'}</td>
                    <td className="p-2 text-muted-foreground truncate max-w-xs">{m.notes ?? ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Close</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// Suppress unused-import warnings for icons we use conditionally
void AlertTriangle;
