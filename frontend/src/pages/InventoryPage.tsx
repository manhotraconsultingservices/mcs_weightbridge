import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import {
  Package, Plus, ShoppingCart, History, Settings,
  Edit, X, Check, AlertTriangle, ChevronDown, SlidersHorizontal, TrendingUp,
  LayoutGrid, List,
} from 'lucide-react';
import {
  BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer,
} from 'recharts';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from '@/components/ui/dialog';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import api from '@/services/api';
import type {
  InventoryItem, InventoryTransaction, PurchaseOrder, POItem,
  InventoryDashboard, TelegramSettings, StockStatus, ItemSupplier, MasterSupplier,
} from '@/types';

// ── Constants ─────────────────────────────────────────────────────────────────

const CATEGORY_ICONS: Record<string, string> = {
  fuel: '⛽',
  electricity: '⚡',
  parts: '🔩',
  tools: '🔧',
  other: '📦',
};

const UNITS = ['litre', 'kg', 'unit', 'set', 'pair', 'roll', 'metre', 'box'];

const STATUS_COLOR: Record<StockStatus, string> = {
  ok:  'border-t-green-500',
  low: 'border-t-yellow-500',
  out: 'border-t-red-500',
};
const STOCK_NUM_COLOR: Record<StockStatus, string> = {
  ok:  'text-green-700',
  low: 'text-yellow-600',
  out: 'text-red-600',
};

const PO_STATUS_BADGE: Record<string, { label: string; variant: 'default' | 'secondary' | 'destructive' | 'outline' }> = {
  pending_approval:   { label: 'Pending Approval', variant: 'secondary' },
  approved:           { label: 'Approved', variant: 'default' },
  rejected:           { label: 'Rejected', variant: 'destructive' },
  partially_received: { label: 'Partial', variant: 'outline' },
  received:           { label: 'Received', variant: 'default' },
};

function fmtDate(iso: string) {
  return new Date(iso).toLocaleString('en-IN', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit', hour12: true,
  });
}

function fmtNum(n: number) {
  // Show as integer if whole number, else up to 3 decimal places
  return n % 1 === 0 ? n.toString() : parseFloat(n.toFixed(3)).toString();
}

// ── UseStockDialog ─────────────────────────────────────────────────────────────

interface UseStockDialogProps {
  item: InventoryItem;
  onClose: () => void;
  onDone: () => void;
}

function UseStockDialog({ item, onClose, onDone }: UseStockDialogProps) {
  const [qty, setQty] = useState('');
  const [usedBy, setUsedBy] = useState('');
  const [usedOn, setUsedOn] = useState(new Date().toISOString().split('T')[0]);  // default today
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const [qtyError, setQtyError] = useState('');
  const [submitError, setSubmitError] = useState('');
  const [confirmed, setConfirmed] = useState(false);

  function validateQty(value: string): string {
    const q = parseFloat(value);
    if (!value || isNaN(q) || q <= 0) return 'Please enter a quantity greater than 0';
    if (q > item.current_stock) return `Only ${fmtNum(item.current_stock)} ${item.unit} available`;
    return '';
  }

  async function handleSubmit() {
    const err = validateQty(qty);
    if (err) { setQtyError(err); return; }
    if (!confirmed) { setConfirmed(true); return; }
    setSaving(true);
    setSubmitError('');
    try {
      await api.post('/api/v1/inventory/issue', {
        item_id: item.id,
        quantity: parseFloat(qty),
        notes: notes || undefined,
        used_by_name: usedBy.trim() || undefined,
        used_on: usedOn || undefined,
      });
      toast.success(`✓ ${fmtNum(parseFloat(qty))} ${item.unit} of ${item.name} recorded`);
      onDone();
    } catch (e: any) {
      setSubmitError(e?.response?.data?.detail ?? 'Failed to record usage');
      setConfirmed(false);
    } finally {
      setSaving(false);
    }
  }

  const newStock = item.current_stock - (parseFloat(qty) || 0);
  const newStatus: StockStatus = newStock <= 0 ? 'out' : newStock <= item.min_stock_level ? 'low' : 'ok';

  return (
    <Dialog open onOpenChange={() => !saving && onClose()}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle className="text-lg">
            {CATEGORY_ICONS[item.category] ?? '📦'} Use {item.name}
          </DialogTitle>
        </DialogHeader>

        {confirmed ? (
          /* ── Confirm step ── */
          <div className="py-2 space-y-4">
            <div className="rounded-xl border bg-muted/40 p-4 space-y-3 text-sm">
              <p className="text-center text-muted-foreground text-xs uppercase tracking-wide font-medium">Confirm Usage</p>
              <p className="text-center">
                You are about to record using{' '}
                <strong>{fmtNum(parseFloat(qty))} {item.unit}</strong> of{' '}
                <strong>{item.name}</strong>
              </p>
              <div className="flex items-center justify-between px-3 py-2 rounded-lg bg-background border">
                <span className="text-muted-foreground">Stock after</span>
                <span className={`font-bold text-base ${STOCK_NUM_COLOR[newStatus]}`}>
                  {fmtNum(Math.max(0, newStock))} {item.unit}
                </span>
              </div>
              {newStatus === 'out' && (
                <p className="text-xs text-red-600 text-center font-medium">⚠ This will bring stock to zero</p>
              )}
              {newStatus === 'low' && (
                <p className="text-xs text-yellow-600 text-center">Stock will fall below minimum level</p>
              )}
            </div>
            {submitError && (
              <p className="text-sm text-red-600 flex items-center gap-1 font-medium">
                <AlertTriangle className="h-4 w-4 shrink-0" /> {submitError}
              </p>
            )}
          </div>
        ) : (
          /* ── Normal form ── */
          <div className="py-2 space-y-4">
            {/* Available stock pill */}
            <div className="text-center py-4 rounded-xl bg-muted">
              <p className="text-xs text-muted-foreground uppercase tracking-wide mb-1">Available</p>
              <p className={`text-4xl font-bold ${STOCK_NUM_COLOR[item.stock_status]}`}>
                {fmtNum(item.current_stock)}
              </p>
              <p className="text-sm text-muted-foreground mt-1">{item.unit}</p>
            </div>

            <div className="space-y-1.5">
              <Label className="text-base font-medium">How many {item.unit} did you use?</Label>
              <Input
                type="number"
                min="0.001"
                step="any"
                value={qty}
                onChange={e => { setQty(e.target.value); setQtyError(''); setSubmitError(''); setConfirmed(false); }}
                placeholder={`Enter amount in ${item.unit}`}
                className={`text-2xl h-14 text-center font-bold ${qtyError ? 'border-red-500 focus-visible:ring-red-500' : ''}`}
                autoFocus
                onKeyDown={e => e.key === 'Enter' && handleSubmit()}
              />
              {qtyError && (
                <p className="text-sm text-red-600 flex items-center gap-1 font-medium">
                  <AlertTriangle className="h-4 w-4 shrink-0" /> {qtyError}
                </p>
              )}
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label className="text-sm font-medium">Used By</Label>
                <Input
                  value={usedBy}
                  onChange={e => setUsedBy(e.target.value)}
                  placeholder="Name / Machine ID"
                />
              </div>
              <div className="space-y-1.5">
                <Label className="text-sm font-medium">Used On</Label>
                <Input
                  type="date"
                  value={usedOn}
                  max={new Date().toISOString().split('T')[0]}
                  onChange={e => setUsedOn(e.target.value)}
                />
              </div>
            </div>

            <div className="space-y-1.5">
              <Label className="text-sm text-muted-foreground">Note (optional)</Label>
              <Input
                value={notes}
                onChange={e => setNotes(e.target.value)}
                placeholder="e.g. Used for JK-01-AB-1234"
              />
            </div>
          </div>
        )}

        <DialogFooter className="gap-2">
          {confirmed ? (
            <>
              <Button variant="outline" onClick={() => setConfirmed(false)} disabled={saving} className="flex-1">
                ← Back
              </Button>
              <Button onClick={handleSubmit} disabled={saving} size="lg" className="flex-1">
                {saving ? 'Saving…' : '✓ Confirm & Record'}
              </Button>
            </>
          ) : (
            <>
              <Button variant="outline" onClick={onClose} disabled={saving} className="flex-1">
                Cancel
              </Button>
              <Button onClick={handleSubmit} disabled={saving} size="lg" className="flex-1">
                ✓ Done
              </Button>
            </>
          )}
        </DialogFooter>
        <p className="text-center text-xs text-muted-foreground -mt-2 pb-1">Press Enter ↵ to confirm</p>
      </DialogContent>
    </Dialog>
  );
}

// ── AdjustStockDialog ─────────────────────────────────────────────────────────

interface AdjustStockDialogProps {
  item: InventoryItem;
  onClose: () => void;
  onDone: () => void;
}

function AdjustStockDialog({ item, onClose, onDone }: AdjustStockDialogProps) {
  const [mode, setMode] = useState<'add' | 'remove'>('add');
  const [qty, setQty] = useState('');
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);

  async function handleSubmit() {
    const q = parseFloat(qty);
    if (!qty || isNaN(q) || q <= 0) { toast.error('Enter a valid quantity greater than 0'); return; }
    if (mode === 'remove' && q > item.current_stock) {
      toast.error(`Cannot remove more than current stock (${fmtNum(item.current_stock)} ${item.unit})`);
      return;
    }
    setSaving(true);
    try {
      const finalQty = mode === 'add' ? q : -q;
      await api.post('/api/v1/inventory/adjust', {
        item_id: item.id,
        quantity: finalQty,
        reason: reason.trim() || (mode === 'add' ? 'Stock added' : 'Stock removed'),
      });
      toast.success(
        mode === 'add'
          ? `✓ Added ${fmtNum(q)} ${item.unit} to ${item.name}`
          : `✓ Removed ${fmtNum(q)} ${item.unit} from ${item.name}`
      );
      onDone();
    } catch (e: any) {
      toast.error(e?.response?.data?.detail ?? 'Failed to adjust stock');
    } finally {
      setSaving(false);
    }
  }

  const newStock = (() => {
    const q = parseFloat(qty) || 0;
    const result = mode === 'add' ? item.current_stock + q : item.current_stock - q;
    return result;
  })();

  return (
    <Dialog open onOpenChange={() => !saving && onClose()}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle className="text-lg flex items-center gap-2">
            <SlidersHorizontal className="h-5 w-5" />
            Adjust Stock — {item.name}
          </DialogTitle>
        </DialogHeader>

        <div className="py-2 space-y-4">
          {/* Current stock display */}
          <div className="text-center py-3 rounded-xl bg-muted">
            <p className="text-xs text-muted-foreground uppercase tracking-wide mb-1">Current Stock</p>
            <p className={`text-4xl font-bold ${STOCK_NUM_COLOR[item.stock_status]}`}>
              {fmtNum(item.current_stock)}
            </p>
            <p className="text-sm text-muted-foreground mt-1">{item.unit}</p>
          </div>

          {/* Add / Remove toggle */}
          <div className="grid grid-cols-2 gap-2">
            <Button
              variant={mode === 'add' ? 'default' : 'outline'}
              onClick={() => setMode('add')}
              className="gap-2"
            >
              <Plus className="h-4 w-4" /> Add Stock
            </Button>
            <Button
              variant={mode === 'remove' ? 'destructive' : 'outline'}
              onClick={() => setMode('remove')}
              className="gap-2"
            >
              <X className="h-4 w-4" /> Remove Stock
            </Button>
          </div>

          {/* Quantity */}
          <div className="space-y-1.5">
            <Label className="text-base font-medium">
              {mode === 'add' ? 'How many to add?' : 'How many to remove?'}
            </Label>
            <div className="flex items-center gap-2">
              <Input
                type="number"
                min="0.001"
                step="any"
                value={qty}
                onChange={e => setQty(e.target.value)}
                placeholder={`Amount in ${item.unit}`}
                className="text-xl h-12 text-center font-bold"
                autoFocus
                onKeyDown={e => e.key === 'Enter' && handleSubmit()}
              />
              <span className="text-sm text-muted-foreground shrink-0">{item.unit}</span>
            </div>
          </div>

          {/* New stock preview */}
          {qty && parseFloat(qty) > 0 && (
            <div className="flex items-center justify-between px-3 py-2 rounded-lg bg-muted/60 text-sm">
              <span className="text-muted-foreground">Stock after adjustment</span>
              <span className={`font-bold text-base ${newStock < 0 ? 'text-red-600' : newStock === 0 ? 'text-red-500' : 'text-green-700'}`}>
                {fmtNum(Math.max(0, newStock))} {item.unit}
              </span>
            </div>
          )}

          {/* Reason */}
          <div className="space-y-1.5">
            <Label className="text-sm text-muted-foreground">Reason (optional)</Label>
            <Input
              value={reason}
              onChange={e => setReason(e.target.value)}
              placeholder={mode === 'add' ? 'e.g. Opening balance, Purchase received' : 'e.g. Spillage, Expired'}
            />
          </div>
        </div>

        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={onClose} disabled={saving} className="flex-1">
            Cancel
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={saving}
            variant={mode === 'remove' ? 'destructive' : 'default'}
            size="lg"
            className="flex-1"
          >
            {saving ? 'Saving…' : mode === 'add' ? '+ Add to Stock' : '− Remove from Stock'}
          </Button>
        </DialogFooter>
        <p className="text-center text-xs text-muted-foreground -mt-2 pb-1">Press Enter ↵ to confirm</p>
      </DialogContent>
    </Dialog>
  );
}

// ── AddItemDialog ─────────────────────────────────────────────────────────────

interface AddItemDialogProps {
  categories: string[];
  editing: InventoryItem | null;
  onClose: () => void;
  onDone: () => void;
}

function AddItemDialog({ categories, editing, onClose, onDone }: AddItemDialogProps) {
  const [form, setForm] = useState({
    name: editing?.name ?? '',
    category: editing?.category ?? (categories[0] ?? 'fuel'),
    unit: editing?.unit ?? 'unit',
    min_stock_level: editing ? String(editing.min_stock_level) : '0',
    reorder_quantity: editing ? String(editing.reorder_quantity ?? 0) : '0',
    auto_po_enabled: editing?.auto_po_enabled ?? false,
    description: editing?.description ?? '',
    initial_stock: '0',   // only used on create; sets opening balance via adjust endpoint
  });
  const [saving, setSaving] = useState(false);

  function set(k: string, v: string) { setForm(f => ({ ...f, [k]: v })); }

  async function handleSubmit() {
    if (!form.name.trim()) { toast.error('Item name is required'); return; }
    const reorderQty = parseFloat(form.reorder_quantity) || 0;
    if (form.auto_po_enabled && reorderQty <= 0) {
      toast.error('Set a reorder quantity to enable auto-PO');
      return;
    }
    setSaving(true);
    try {
      const body = {
        name: form.name.trim(),
        category: form.category,
        unit: form.unit,
        min_stock_level: parseFloat(form.min_stock_level) || 0,
        reorder_quantity: reorderQty,
        auto_po_enabled: form.auto_po_enabled,
        description: form.description.trim() || undefined,
      };
      if (editing) {
        await api.put(`/api/v1/inventory/items/${editing.id}`, body);
        toast.success('Item updated');
      } else {
        const res = await api.post<{ id: string }>('/api/v1/inventory/items', body);
        // Set opening stock balance if provided
        const openingStock = parseFloat(form.initial_stock) || 0;
        if (openingStock > 0) {
          await api.post('/api/v1/inventory/adjust', {
            item_id: res.data.id,
            quantity: openingStock,
            reason: 'Opening balance',
          });
        }
        toast.success('Item added to inventory');
      }
      onDone();
    } catch (e: any) {
      toast.error(e?.response?.data?.detail ?? 'Failed to save item');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open onOpenChange={() => !saving && onClose()}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>{editing ? 'Edit Item' : 'Add New Item'}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 py-2">
          <div className="space-y-1.5">
            <Label>Item Name *</Label>
            <Input value={form.name} onChange={e => set('name', e.target.value)} placeholder="e.g. Diesel, Drill Bits" autoFocus />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label>Category</Label>
              <Select value={form.category} onValueChange={v => set('category', v)}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {categories.map(c => (
                    <SelectItem key={c} value={c}>
                      {CATEGORY_ICONS[c] ?? '📦'} {c.charAt(0).toUpperCase() + c.slice(1)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>Unit</Label>
              <Select value={form.unit} onValueChange={v => set('unit', v)}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {UNITS.map(u => <SelectItem key={u} value={u}>{u}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="space-y-1.5">
            <Label>Low Stock Alert Below</Label>
            <div className="flex items-center gap-2">
              <Input
                type="number"
                min="0"
                value={form.min_stock_level}
                onChange={e => set('min_stock_level', e.target.value)}
                className="w-28"
              />
              <span className="text-sm text-muted-foreground">{form.unit}</span>
            </div>
          </div>

          {/* Opening stock — only for new items */}
          {!editing && (
            <div className="space-y-1.5">
              <Label>Current Stock (Opening Balance)</Label>
              <div className="flex items-center gap-2">
                <Input
                  type="number"
                  min="0"
                  step="any"
                  value={form.initial_stock}
                  onChange={e => set('initial_stock', e.target.value)}
                  className="w-28 font-semibold"
                />
                <span className="text-sm text-muted-foreground">{form.unit}</span>
              </div>
              <p className="text-xs text-muted-foreground">
                How much stock do you have right now? Leave as 0 if starting fresh.
              </p>
            </div>
          )}

          {/* Auto-PO section */}
          <div className="rounded-lg border border-dashed p-3 space-y-3 bg-muted/30">
            <div className="flex items-center justify-between">
              <div>
                <Label className="text-sm font-medium">🤖 Auto-create Purchase Order</Label>
                <p className="text-xs text-muted-foreground mt-0.5">
                  System will automatically raise a PO for approval when stock falls to the minimum.
                </p>
              </div>
              <Switch
                checked={form.auto_po_enabled}
                onCheckedChange={v => setForm(f => ({ ...f, auto_po_enabled: v }))}
              />
            </div>
            {form.auto_po_enabled && (
              <div className="space-y-1.5">
                <Label className="text-sm">Reorder Quantity</Label>
                <div className="flex items-center gap-2">
                  <Input
                    type="number"
                    min="0.001"
                    step="any"
                    value={form.reorder_quantity}
                    onChange={e => set('reorder_quantity', e.target.value)}
                    placeholder="How much to order"
                    className="w-28"
                  />
                  <span className="text-sm text-muted-foreground">{form.unit}</span>
                </div>
                <p className="text-xs text-muted-foreground">
                  A draft PO for this quantity will be sent to the manager for approval.
                </p>
              </div>
            )}
          </div>

          <div className="space-y-1.5">
            <Label className="text-sm text-muted-foreground">Description (optional)</Label>
            <Input value={form.description} onChange={e => set('description', e.target.value)} placeholder="Short description" />
          </div>
        </div>
        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={onClose} disabled={saving}>Cancel</Button>
          <Button onClick={handleSubmit} disabled={saving}>{saving ? 'Saving…' : editing ? 'Update' : 'Add Item'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── ManageSuppliersDialog ─────────────────────────────────────────────────────

interface ManageSuppliersDialogProps {
  item: InventoryItem;
  onClose: () => void;
  onDone: () => void;
}

const EMPTY_SUP_FORM = {
  supplier_name: '', is_preferred: false,
  lead_time_days: '', agreed_unit_price: '', moq: '', notes: '',
};

function ManageSuppliersDialog({ item, onClose, onDone }: ManageSuppliersDialogProps) {
  const [suppliers, setSuppliers] = useState<ItemSupplier[]>(item.suppliers ?? []);
  const [addForm, setAddForm] = useState({ ...EMPTY_SUP_FORM });
  const [showAddForm, setShowAddForm] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState({ ...EMPTY_SUP_FORM });
  const [saving, setSaving] = useState(false);
  const [masterSuppliers, setMasterSuppliers] = useState<Array<{id: string; name: string}>>([]);

  useEffect(() => {
    api.get<{ suppliers: Array<{id: string; name: string}> }>('/api/v1/inventory/items/supplier-names')
      .then(r => setMasterSuppliers(r.data.suppliers ?? []))
      .catch(() => {});
  }, []);

  function setAdd(k: string, v: string | boolean) { setAddForm(f => ({ ...f, [k]: v })); }
  function setEdit(k: string, v: string | boolean) { setEditForm(f => ({ ...f, [k]: v })); }

  async function handleAdd() {
    if (!addForm.supplier_name.trim()) { toast.error('Supplier name is required'); return; }
    setSaving(true);
    try {
      // Find matching master supplier
      const match = masterSuppliers.find(s => s.name.toLowerCase() === addForm.supplier_name.trim().toLowerCase());
      let finalMasterId: string | null = match?.id ?? null;
      // If no match, create master entry
      if (!finalMasterId && addForm.supplier_name.trim()) {
        try {
          const res = await api.post<{id: string; name: string}>('/api/v1/inventory/suppliers', { name: addForm.supplier_name.trim() });
          finalMasterId = res.data.id;
          setMasterSuppliers(prev => [...prev, { id: res.data.id, name: res.data.name }]);
        } catch { /* use name without master link */ }
      }
      const { data } = await api.post<ItemSupplier>(`/api/v1/inventory/items/${item.id}/suppliers`, {
        supplier_name: addForm.supplier_name.trim(),
        master_supplier_id: finalMasterId,
        is_preferred: addForm.is_preferred,
        lead_time_days: addForm.lead_time_days ? parseInt(addForm.lead_time_days) : null,
        agreed_unit_price: addForm.agreed_unit_price ? parseFloat(addForm.agreed_unit_price) : null,
        moq: addForm.moq ? parseFloat(addForm.moq) : null,
        notes: addForm.notes.trim() || null,
      });
      setSuppliers(prev => {
        // If new supplier is preferred, unset others
        const updated = data.is_preferred ? prev.map(s => ({ ...s, is_preferred: false })) : [...prev];
        return [...updated, data];
      });
      setAddForm({ ...EMPTY_SUP_FORM });
      setShowAddForm(false);
      onDone();
    } catch (e: any) {
      toast.error(e?.response?.data?.detail ?? 'Failed to add supplier');
    } finally {
      setSaving(false);
    }
  }

  function startEdit(s: ItemSupplier) {
    setEditId(s.id);
    setEditForm({
      supplier_name: s.supplier_name,
      is_preferred: s.is_preferred,
      lead_time_days: s.lead_time_days != null ? String(s.lead_time_days) : '',
      agreed_unit_price: s.agreed_unit_price != null ? String(s.agreed_unit_price) : '',
      moq: s.moq != null ? String(s.moq) : '',
      notes: s.notes ?? '',
    });
  }

  async function handleUpdate() {
    if (!editForm.supplier_name.trim()) { toast.error('Supplier name is required'); return; }
    setSaving(true);
    try {
      const { data } = await api.put<ItemSupplier>(`/api/v1/inventory/items/${item.id}/suppliers/${editId}`, {
        supplier_name: editForm.supplier_name.trim(),
        is_preferred: editForm.is_preferred,
        lead_time_days: editForm.lead_time_days ? parseInt(editForm.lead_time_days) : null,
        agreed_unit_price: editForm.agreed_unit_price ? parseFloat(editForm.agreed_unit_price) : null,
        moq: editForm.moq ? parseFloat(editForm.moq) : null,
        notes: editForm.notes.trim() || null,
      });
      setSuppliers(prev => prev.map(s => {
        if (data.is_preferred && s.id !== data.id) return { ...s, is_preferred: false };
        return s.id === data.id ? data : s;
      }));
      setEditId(null);
      onDone();
    } catch (e: any) {
      toast.error(e?.response?.data?.detail ?? 'Failed to update supplier');
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(sid: string) {
    setSaving(true);
    try {
      await api.delete(`/api/v1/inventory/items/${item.id}/suppliers/${sid}`);
      setSuppliers(prev => prev.filter(s => s.id !== sid));
      onDone();
    } catch {
      toast.error('Failed to remove supplier');
    } finally {
      setSaving(false);
    }
  }

  async function handleSetPreferred(sid: string) {
    setSaving(true);
    try {
      const { data } = await api.put<ItemSupplier>(`/api/v1/inventory/items/${item.id}/suppliers/${sid}`, { is_preferred: true });
      setSuppliers(prev => prev.map(s => ({
        ...s,
        is_preferred: s.id === sid ? data.is_preferred : false,
      })));
      onDone();
    } catch {
      toast.error('Failed to set preferred supplier');
    } finally {
      setSaving(false);
    }
  }

  function SupplierInfoRow({ label, children }: { label: string; children: React.ReactNode }) {
    return (
      <div className="flex gap-2 text-xs">
        <span className="text-muted-foreground w-20 shrink-0">{label}</span>
        <span className="font-medium">{children}</span>
      </div>
    );
  }

  return (
    <Dialog open onOpenChange={() => !saving && onClose()}>
      <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-base">
            🏭 Suppliers — <span className="font-semibold text-primary">{item.name}</span>
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-3 py-1">
          {suppliers.length === 0 && !showAddForm && (
            <p className="text-center text-sm text-muted-foreground py-4">
              No suppliers added yet. Click "+ Add Supplier" to get started.
            </p>
          )}

          {suppliers.map(s => (
            <div key={s.id} className={`rounded-lg border p-3 space-y-2 ${s.is_preferred ? 'border-primary/60 bg-primary/5' : 'bg-muted/20'}`}>
              {editId === s.id ? (
                /* ── Inline edit form ── */
                <div className="space-y-2">
                  <Input
                    list="master-suppliers-list-edit"
                    value={editForm.supplier_name}
                    onChange={e => setEdit('supplier_name', e.target.value)}
                    placeholder="Supplier name"
                    className="h-8"
                  />
                  <datalist id="master-suppliers-list-edit">
                    {masterSuppliers.map(s => <option key={s.id} value={s.name} />)}
                  </datalist>
                  <div className="grid grid-cols-3 gap-2">
                    <div className="space-y-1">
                      <Label className="text-xs text-muted-foreground">ETA (days)</Label>
                      <Input type="number" min="0" value={editForm.lead_time_days}
                        onChange={e => setEdit('lead_time_days', e.target.value)} placeholder="e.g. 3" className="h-8" />
                    </div>
                    <div className="space-y-1">
                      <Label className="text-xs text-muted-foreground">Agreed Price (₹/{item.unit})</Label>
                      <Input type="number" min="0" step="any" value={editForm.agreed_unit_price}
                        onChange={e => setEdit('agreed_unit_price', e.target.value)} placeholder="0.00" className="h-8" />
                    </div>
                    <div className="space-y-1">
                      <Label className="text-xs text-muted-foreground">MOQ ({item.unit})</Label>
                      <Input type="number" min="0" step="any" value={editForm.moq}
                        onChange={e => setEdit('moq', e.target.value)} placeholder="0" className="h-8" />
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <input type="checkbox" id={`ep-${s.id}`} checked={editForm.is_preferred as boolean}
                      onChange={e => setEdit('is_preferred', e.target.checked)} className="h-3.5 w-3.5" />
                    <Label htmlFor={`ep-${s.id}`} className="text-xs cursor-pointer">⭐ Set as preferred supplier</Label>
                  </div>
                  <Input value={editForm.notes} onChange={e => setEdit('notes', e.target.value)}
                    placeholder="Notes (optional)" className="h-8 text-xs" />
                  <div className="flex gap-2 pt-1">
                    <Button size="sm" onClick={handleUpdate} disabled={saving} className="flex-1">Save</Button>
                    <Button size="sm" variant="outline" onClick={() => setEditId(null)} disabled={saving} className="flex-1">Cancel</Button>
                  </div>
                </div>
              ) : (
                /* ── Display row ── */
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-sm">{s.supplier_name}</span>
                      {s.is_preferred && (
                        <span className="text-[10px] bg-primary text-primary-foreground px-1.5 py-0.5 rounded-full font-medium">
                          ⭐ Preferred
                        </span>
                      )}
                    </div>
                    <div className="flex gap-1">
                      {!s.is_preferred && (
                        <Button variant="ghost" size="sm" className="h-6 text-xs px-2 text-muted-foreground"
                          onClick={() => handleSetPreferred(s.id)} disabled={saving}>
                          Set Preferred
                        </Button>
                      )}
                      <Button variant="ghost" size="icon" className="h-6 w-6"
                        onClick={() => startEdit(s)} disabled={saving}>
                        <Edit className="h-3 w-3" />
                      </Button>
                      <Button variant="ghost" size="icon" className="h-6 w-6 text-destructive hover:text-destructive"
                        onClick={() => handleDelete(s.id)} disabled={saving}>
                        <X className="h-3 w-3" />
                      </Button>
                    </div>
                  </div>
                  <div className="space-y-0.5">
                    {s.lead_time_days != null && <SupplierInfoRow label="⏱ ETA">{s.lead_time_days} day{s.lead_time_days !== 1 ? 's' : ''}</SupplierInfoRow>}
                    {s.agreed_unit_price != null && <SupplierInfoRow label="💰 Price">₹{parseFloat(String(s.agreed_unit_price)).toFixed(2)} / {item.unit}</SupplierInfoRow>}
                    {s.moq != null && <SupplierInfoRow label="📦 MOQ">{fmtNum(Number(s.moq))} {item.unit}</SupplierInfoRow>}
                    {s.notes && <SupplierInfoRow label="📝 Notes">{s.notes}</SupplierInfoRow>}
                  </div>
                </div>
              )}
            </div>
          ))}

          {/* Add supplier form */}
          {showAddForm ? (
            <div className="rounded-lg border border-dashed p-3 space-y-2 bg-muted/10">
              <Label className="text-sm font-semibold">New Supplier</Label>
              <Input
                list="master-suppliers-list"
                value={addForm.supplier_name}
                onChange={e => setAdd('supplier_name', e.target.value)}
                placeholder="Type or select supplier from master *"
                autoFocus
                className="h-9"
              />
              <datalist id="master-suppliers-list">
                {masterSuppliers.map(s => <option key={s.id} value={s.name} />)}
              </datalist>
              {addForm.supplier_name.trim() && !masterSuppliers.find(s => s.name.toLowerCase() === addForm.supplier_name.trim().toLowerCase()) && (
                <p className="text-xs text-blue-600">✨ "{addForm.supplier_name.trim()}" will be added to the master supplier list</p>
              )}
              <div className="grid grid-cols-3 gap-2">
                <div className="space-y-1">
                  <Label className="text-xs text-muted-foreground">ETA (days)</Label>
                  <Input type="number" min="0" value={addForm.lead_time_days}
                    onChange={e => setAdd('lead_time_days', e.target.value)} placeholder="e.g. 3" className="h-8" />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs text-muted-foreground">Agreed Price (₹/{item.unit})</Label>
                  <Input type="number" min="0" step="any" value={addForm.agreed_unit_price}
                    onChange={e => setAdd('agreed_unit_price', e.target.value)} placeholder="0.00" className="h-8" />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs text-muted-foreground">MOQ ({item.unit})</Label>
                  <Input type="number" min="0" step="any" value={addForm.moq}
                    onChange={e => setAdd('moq', e.target.value)} placeholder="0" className="h-8" />
                </div>
              </div>
              <div className="flex items-center gap-2">
                <input type="checkbox" id="add-preferred" checked={addForm.is_preferred as boolean}
                  onChange={e => setAdd('is_preferred', e.target.checked)} className="h-3.5 w-3.5" />
                <Label htmlFor="add-preferred" className="text-xs cursor-pointer">⭐ Set as preferred supplier</Label>
              </div>
              <Input value={addForm.notes} onChange={e => setAdd('notes', e.target.value)}
                placeholder="Notes (optional)" className="h-8 text-xs" />
              <div className="flex gap-2 pt-1">
                <Button size="sm" onClick={handleAdd} disabled={saving} className="flex-1">Add Supplier</Button>
                <Button size="sm" variant="outline" onClick={() => { setShowAddForm(false); setAddForm({ ...EMPTY_SUP_FORM }); }}
                  disabled={saving} className="flex-1">Cancel</Button>
              </div>
            </div>
          ) : (
            <Button variant="ghost" size="sm" onClick={() => setShowAddForm(true)}
              className="w-full border border-dashed text-primary">
              <Plus className="h-3.5 w-3.5 mr-1" /> Add Supplier
            </Button>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={saving}>Close</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── StockCard ─────────────────────────────────────────────────────────────────

interface StockCardProps {
  item: InventoryItem;
  isAdmin: boolean;
  onUse: (item: InventoryItem) => void;
  onEdit: (item: InventoryItem) => void;
  onAdjust: (item: InventoryItem) => void;
  onManageSuppliers: (item: InventoryItem) => void;
}

function StockCard({ item, isAdmin, onUse, onEdit, onAdjust, onManageSuppliers }: StockCardProps) {
  const icon = CATEGORY_ICONS[item.category] ?? '📦';
  const preferred = item.suppliers?.find(s => s.is_preferred) ?? item.suppliers?.[0] ?? null;
  return (
    <Card className={`border-t-4 ${STATUS_COLOR[item.stock_status]} shadow-sm hover:shadow-md transition-shadow`}>
      <CardContent className="pt-5 pb-4 px-5">
        <div className="flex items-start justify-between mb-2">
          <span className="text-3xl">{icon}</span>
          {isAdmin && (
            <div className="flex items-center gap-0.5 -mr-1 -mt-1">
              <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground"
                onClick={() => onAdjust(item)} title="Adjust stock">
                <SlidersHorizontal className="h-3.5 w-3.5" />
              </Button>
              <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground"
                onClick={() => onManageSuppliers(item)} title="Manage suppliers">
                <span className="text-xs">🏭</span>
              </Button>
              <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground"
                onClick={() => onEdit(item)} title="Edit item">
                <Edit className="h-3.5 w-3.5" />
              </Button>
            </div>
          )}
        </div>
        <p className="text-xs text-muted-foreground uppercase tracking-wide mb-0.5">
          {item.category}
        </p>
        <h3 className="text-base font-semibold leading-snug mb-4">{item.name}</h3>

        {/* Big stock number */}
        <div className={`text-5xl font-black mb-1 leading-none ${STOCK_NUM_COLOR[item.stock_status]}`}>
          {fmtNum(item.current_stock)}
        </div>
        <p className="text-sm text-muted-foreground mb-3">{item.unit}</p>

        {item.stock_status === 'low' && (
          <p className="text-xs text-yellow-600 flex items-center gap-1 mb-2">
            <AlertTriangle className="h-3 w-3" />
            Low — min {fmtNum(item.min_stock_level)} {item.unit}
          </p>
        )}
        {item.stock_status === 'out' && (
          <p className="text-xs text-red-600 font-medium mb-2">⚠ Out of stock — order needed</p>
        )}
        {item.auto_po_enabled && (
          <p className="text-xs text-blue-600 mb-2 flex items-center gap-1">
            🤖 Auto-reorder {fmtNum(item.reorder_quantity)} {item.unit}
          </p>
        )}
        {preferred && (
          <p className="text-xs text-muted-foreground mb-2 truncate" title={preferred.supplier_name}>
            🏭 {preferred.is_preferred ? '⭐ ' : ''}{preferred.supplier_name}
            {preferred.agreed_unit_price != null && ` · ₹${parseFloat(String(preferred.agreed_unit_price)).toFixed(2)}/${item.unit}`}
            {preferred.lead_time_days != null && ` · ${preferred.lead_time_days}d ETA`}
          </p>
        )}

        <Button
          className="w-full"
          size="lg"
          variant={item.stock_status === 'out' ? 'outline' : 'default'}
          disabled={item.stock_status === 'out'}
          onClick={() => onUse(item)}
        >
          {item.stock_status === 'out' ? 'Out of Stock' : 'Use Stock'}
        </Button>
      </CardContent>
    </Card>
  );
}

// ── EditPODialog ──────────────────────────────────────────────────────────────

interface EditPODialogProps {
  po: PurchaseOrder;
  items: InventoryItem[];
  onClose: () => void;
  onDone: () => void;
}

function EditPODialog({ po, items: propItems, onClose, onDone }: EditPODialogProps) {
  // Load items from API directly — don't rely on parent's possibly-empty cache
  const [allItems, setAllItems] = useState<InventoryItem[]>(propItems.filter(i => i.is_active));
  const [loadingItems, setLoadingItems] = useState(propItems.length === 0);
  const [knownSuppliers, setKnownSuppliers] = useState<string[]>([]);

  useEffect(() => {
    if (propItems.length > 0) { setAllItems(propItems.filter(i => i.is_active)); return; }
    api.get<{ items: InventoryItem[] }>('/api/v1/inventory/items')
      .then(r => setAllItems(r.data.items.filter(i => i.is_active)))
      .catch(() => toast.error('Failed to load items'))
      .finally(() => setLoadingItems(false));
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    api.get<{ suppliers: Array<{id: string; name: string}> }>('/api/v1/inventory/items/supplier-names')
      .then(r => setKnownSuppliers((r.data.suppliers ?? []).map(s => s.name)))
      .catch(() => { /* silent */ });
  }, []);

  const [lines, setLines] = useState<{ item_id: string; quantity_ordered: string; unit_price: string }[]>(
    po.items.map(pi => ({
      item_id: pi.item_id,
      quantity_ordered: String(pi.quantity_ordered),
      unit_price: pi.unit_price != null ? String(pi.unit_price) : '',
    }))
  );
  const [supplier, setSupplier] = useState(po.supplier_name ?? '');
  const [expectedDate, setExpectedDate] = useState(po.expected_date ?? '');
  const [notes, setNotes] = useState(po.notes ?? '');
  const [saving, setSaving] = useState(false);

  function addLine() { setLines(l => [...l, { item_id: '', quantity_ordered: '', unit_price: '' }]); }
  function removeLine(i: number) { if (lines.length > 1) setLines(l => l.filter((_, idx) => idx !== i)); }
  function updateLine(i: number, k: string, v: string) {
    setLines(l => l.map((line, idx) => idx === i ? { ...line, [k]: v } : line));
  }
  function handleItemSelect(i: number, itemId: string) {
    const it = allItems.find(x => x.id === itemId);
    const preferred = it?.suppliers?.find(s => s.is_preferred) ?? it?.suppliers?.[0] ?? null;
    const price = preferred?.agreed_unit_price != null ? String(preferred.agreed_unit_price) : lines[i].unit_price;
    setLines(l => l.map((line, idx) => idx === i
      ? { ...line, item_id: itemId, unit_price: price }
      : line
    ));
  }

  async function handleSubmit() {
    const validLines = lines.filter(l => l.item_id && l.quantity_ordered && parseFloat(l.quantity_ordered) > 0);
    if (!validLines.length) { toast.error('Add at least one item with a quantity'); return; }
    setSaving(true);
    try {
      await api.put(`/api/v1/inventory/purchase-orders/${po.id}`, {
        supplier_name: supplier.trim() || null,
        expected_date: expectedDate || null,
        notes: notes.trim() || null,
        items: validLines.map(l => ({
          item_id: l.item_id,
          quantity_ordered: parseFloat(l.quantity_ordered),
          unit_price: l.unit_price ? parseFloat(l.unit_price) : undefined,
        })),
      });
      toast.success(`${po.po_no} updated`);
      onDone();
    } catch (e: any) {
      toast.error(e?.response?.data?.detail ?? 'Failed to update order');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open onOpenChange={() => !saving && onClose()}>
      <DialogContent className="max-w-md max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            ✏️ Edit PO <span className="font-mono text-primary">{po.po_no}</span>
          </DialogTitle>
        </DialogHeader>

        {loadingItems ? (
          <div className="py-8 text-center text-sm text-muted-foreground">Loading items…</div>
        ) : (
          <div className="space-y-4 py-1">

            {/* Line items — stacked layout: item on top, qty+price+delete below */}
            <div className="space-y-3">
              <Label className="text-sm font-semibold">Items Ordered</Label>
              {lines.map((line, i) => {
                const selectedItem = allItems.find(it => it.id === line.item_id);
                const preferred = selectedItem?.suppliers?.find(s => s.is_preferred) ?? selectedItem?.suppliers?.[0] ?? null;
                const qty = parseFloat(line.quantity_ordered);
                const moqWarning = preferred?.moq != null && qty > 0 && qty < Number(preferred.moq);
                return (
                  <div key={i} className="rounded-lg border p-3 space-y-2 bg-muted/20">
                    {/* Item picker — full width */}
                    <div className="flex items-center gap-2">
                      <div className="flex-1">
                        <Select value={line.item_id} onValueChange={v => handleItemSelect(i, v)}>
                          <SelectTrigger className="h-9">
                            <SelectValue placeholder="Select item…" />
                          </SelectTrigger>
                          <SelectContent>
                            {allItems.map(it => (
                              <SelectItem key={it.id} value={it.id}>
                                {CATEGORY_ICONS[it.category] ?? '📦'} {it.name} ({it.unit})
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <Button
                        variant="ghost" size="icon"
                        className="h-9 w-9 shrink-0 text-muted-foreground hover:text-destructive"
                        onClick={() => removeLine(i)}
                        disabled={lines.length === 1}
                      >
                        <X className="h-4 w-4" />
                      </Button>
                    </div>
                    {/* Qty + Price on the same row below */}
                    <div className="grid grid-cols-2 gap-2">
                      <div className="space-y-1">
                        <Label className="text-xs text-muted-foreground">
                          Quantity{selectedItem ? ` (${selectedItem.unit})` : ''}
                        </Label>
                        <Input
                          type="number" min="0.001" step="any"
                          value={line.quantity_ordered}
                          onChange={e => updateLine(i, 'quantity_ordered', e.target.value)}
                          placeholder="0"
                          className="h-8"
                        />
                      </div>
                      <div className="space-y-1">
                        <Label className="text-xs text-muted-foreground">Unit Price (₹)</Label>
                        <Input
                          type="number" min="0" step="any"
                          value={line.unit_price}
                          onChange={e => updateLine(i, 'unit_price', e.target.value)}
                          placeholder={preferred?.agreed_unit_price != null ? `Agreed: ₹${preferred.agreed_unit_price}` : 'Optional'}
                          className="h-8"
                        />
                      </div>
                    </div>
                    {/* Supplier info chips */}
                    {preferred && (
                      <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-muted-foreground pt-0.5">
                        <span>🏭 {preferred.supplier_name}</span>
                        {preferred.lead_time_days != null && <span>⏱ ETA: {preferred.lead_time_days}d</span>}
                        {preferred.moq != null && <span>📦 MOQ: {fmtNum(Number(preferred.moq))} {selectedItem?.unit}</span>}
                        {preferred.agreed_unit_price != null && <span>💰 Agreed: ₹{parseFloat(String(preferred.agreed_unit_price)).toFixed(2)}/{selectedItem?.unit}</span>}
                      </div>
                    )}
                    {moqWarning && (
                      <p className="text-[11px] text-yellow-600 flex items-center gap-1">
                        <AlertTriangle className="h-3 w-3" />
                        Below MOQ ({fmtNum(Number(preferred!.moq))} {selectedItem?.unit})
                      </p>
                    )}
                  </div>
                );
              })}
              <Button variant="ghost" size="sm" onClick={addLine} className="text-primary w-full border border-dashed">
                <Plus className="h-3.5 w-3.5 mr-1" /> Add Another Item
              </Button>
            </div>

            {/* Supplier + Date */}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label className="text-sm">Supplier Name</Label>
                <Input
                  list="supplier-names-edit"
                  value={supplier}
                  onChange={e => setSupplier(e.target.value)}
                  placeholder="Type or select supplier"
                />
                <datalist id="supplier-names-edit">
                  {knownSuppliers.map(n => <option key={n} value={n} />)}
                </datalist>
              </div>
              <div className="space-y-1.5">
                <Label className="text-sm">Expected Date</Label>
                <Input type="date" value={expectedDate} onChange={e => setExpectedDate(e.target.value)} />
              </div>
            </div>

            {/* Notes — textarea to show long auto-generated notes fully */}
            <div className="space-y-1.5">
              <Label className="text-sm">Notes</Label>
              <textarea
                value={notes}
                onChange={e => setNotes(e.target.value)}
                placeholder="Optional"
                rows={3}
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring resize-none"
              />
            </div>
          </div>
        )}

        <DialogFooter className="gap-2 pt-2">
          <Button variant="outline" onClick={onClose} disabled={saving}>Cancel</Button>
          <Button onClick={handleSubmit} disabled={saving || loadingItems}>
            {saving ? 'Saving…' : 'Save Changes'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── NewPODialog ───────────────────────────────────────────────────────────────

interface NewPODialogProps {
  items: InventoryItem[];
  onClose: () => void;
  onDone: () => void;
}

interface POLineForm {
  item_id: string;
  quantity_ordered: string;
  unit_price: string;
}

function NewPODialog({ items, onClose, onDone }: NewPODialogProps) {
  const outOfStock = items.filter(i => i.stock_status === 'out' && i.is_active);
  const initialLines: POLineForm[] = outOfStock.length > 0
    ? outOfStock.map(i => ({ item_id: i.id, quantity_ordered: '', unit_price: '' }))
    : [{ item_id: '', quantity_ordered: '', unit_price: '' }];
  const [lines, setLines] = useState<POLineForm[]>(initialLines);
  const [supplier, setSupplier] = useState('');
  const [expectedDate, setExpectedDate] = useState('');
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const [knownSuppliers, setKnownSuppliers] = useState<string[]>([]);

  useEffect(() => {
    api.get<{ suppliers: Array<{id: string; name: string}> }>('/api/v1/inventory/items/supplier-names')
      .then(r => setKnownSuppliers((r.data.suppliers ?? []).map(s => s.name)))
      .catch(() => { /* silent */ });
  }, []);

  const activeItems = items.filter(i => i.is_active);

  function addLine() { setLines(l => [...l, { item_id: '', quantity_ordered: '', unit_price: '' }]); }
  function removeLine(i: number) { setLines(l => l.filter((_, idx) => idx !== i)); }
  function updateLine(i: number, k: keyof POLineForm, v: string) {
    setLines(l => l.map((line, idx) => idx === i ? { ...line, [k]: v } : line));
  }

  function handleItemSelect(i: number, itemId: string) {
    const it = activeItems.find(x => x.id === itemId);
    const preferred = it?.suppliers?.find(s => s.is_preferred) ?? it?.suppliers?.[0] ?? null;
    const price = preferred?.agreed_unit_price != null ? String(preferred.agreed_unit_price) : '';
    // Auto-fill supplier from preferred if not already set
    if (preferred && !supplier) setSupplier(preferred.supplier_name);
    setLines(l => l.map((line, idx) => idx === i
      ? { ...line, item_id: itemId, unit_price: price }
      : line
    ));
  }

  async function handleSubmit() {
    const validLines = lines.filter(l => l.item_id && l.quantity_ordered && parseFloat(l.quantity_ordered) > 0);
    if (!validLines.length) { toast.error('Add at least one item with a quantity'); return; }
    setSaving(true);
    try {
      await api.post('/api/v1/inventory/purchase-orders', {
        supplier_name: supplier.trim() || undefined,
        expected_date: expectedDate || undefined,
        notes: notes.trim() || undefined,
        items: validLines.map(l => ({
          item_id: l.item_id,
          quantity_ordered: parseFloat(l.quantity_ordered),
          unit_price: l.unit_price ? parseFloat(l.unit_price) : undefined,
        })),
      });
      toast.success('Purchase order submitted for approval');
      onDone();
    } catch (e: any) {
      toast.error(e?.response?.data?.detail ?? 'Failed to create order');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open onOpenChange={() => !saving && onClose()}>
      <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>🛒 New Purchase Order</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2">

          {/* Line items — stacked card per item */}
          <div className="space-y-2">
            <Label className="text-base font-semibold">What do you need?</Label>
            {outOfStock.length > 0 && (
              <p className="text-xs text-blue-600 flex items-center gap-1.5 px-1">
                ℹ️ {outOfStock.length} out-of-stock item{outOfStock.length !== 1 ? 's' : ''} pre-filled — review and add quantities
              </p>
            )}
            {lines.map((line, i) => {
              const selectedItem = activeItems.find(it => it.id === line.item_id);
              const preferred = selectedItem?.suppliers?.find(s => s.is_preferred) ?? selectedItem?.suppliers?.[0] ?? null;
              const qty = parseFloat(line.quantity_ordered);
              const moqWarning = preferred?.moq != null && qty > 0 && qty < Number(preferred.moq);
              return (
                <div key={i} className="rounded-lg border p-3 space-y-2 bg-muted/20">
                  {/* Item select + remove */}
                  <div className="flex items-center gap-2">
                    <div className="flex-1">
                      <Select value={line.item_id} onValueChange={v => handleItemSelect(i, v)}>
                        <SelectTrigger className="h-9">
                          <SelectValue placeholder="Select item…" />
                        </SelectTrigger>
                        <SelectContent>
                          {activeItems.map(it => (
                            <SelectItem key={it.id} value={it.id}>
                              {CATEGORY_ICONS[it.category] ?? '📦'} {it.name} ({it.unit})
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    {lines.length > 1 && (
                      <Button variant="ghost" size="icon" className="h-9 w-9 text-muted-foreground shrink-0 hover:text-destructive"
                        onClick={() => removeLine(i)}>
                        <X className="h-4 w-4" />
                      </Button>
                    )}
                  </div>
                  {/* Qty + Price */}
                  <div className="grid grid-cols-2 gap-2">
                    <div className="space-y-1">
                      <Label className="text-xs text-muted-foreground">
                        Quantity{selectedItem ? ` (${selectedItem.unit})` : ''}
                      </Label>
                      <Input type="number" min="0.001" step="any"
                        value={line.quantity_ordered}
                        onChange={e => updateLine(i, 'quantity_ordered', e.target.value)}
                        placeholder="0" className="h-8" />
                    </div>
                    <div className="space-y-1">
                      <Label className="text-xs text-muted-foreground">Unit Price (₹)</Label>
                      <Input type="number" min="0" step="any"
                        value={line.unit_price}
                        onChange={e => updateLine(i, 'unit_price', e.target.value)}
                        placeholder={preferred?.agreed_unit_price != null ? `Agreed: ₹${preferred.agreed_unit_price}` : 'Optional'}
                        className="h-8" />
                    </div>
                  </div>
                  {/* Supplier info chip */}
                  {preferred && (
                    <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-muted-foreground pt-0.5">
                      <span>🏭 {preferred.supplier_name}</span>
                      {preferred.lead_time_days != null && <span>⏱ ETA: {preferred.lead_time_days}d</span>}
                      {preferred.moq != null && <span>📦 MOQ: {fmtNum(Number(preferred.moq))} {selectedItem?.unit}</span>}
                      {preferred.agreed_unit_price != null && <span>💰 Agreed: ₹{parseFloat(String(preferred.agreed_unit_price)).toFixed(2)}/{selectedItem?.unit}</span>}
                    </div>
                  )}
                  {moqWarning && (
                    <p className="text-[11px] text-yellow-600 flex items-center gap-1">
                      <AlertTriangle className="h-3 w-3" />
                      Below MOQ ({fmtNum(Number(preferred!.moq))} {selectedItem?.unit})
                    </p>
                  )}
                </div>
              );
            })}
            <Button variant="ghost" size="sm" className="text-primary w-full border border-dashed" onClick={addLine}>
              <Plus className="h-3.5 w-3.5 mr-1" /> Add Another Item
            </Button>
          </div>

          <div className="grid grid-cols-2 gap-3 pt-2 border-t">
            <div className="space-y-1.5">
              <Label className="text-sm text-muted-foreground">Supplier</Label>
              {/* datalist allows typing + picking from known names */}
              <Input
                list="supplier-names-new"
                value={supplier}
                onChange={e => setSupplier(e.target.value)}
                placeholder="Type or select supplier"
              />
              <datalist id="supplier-names-new">
                {knownSuppliers.map(n => <option key={n} value={n} />)}
              </datalist>
            </div>
            <div className="space-y-1.5">
              <Label className="text-sm text-muted-foreground">Expected By</Label>
              <Input type="date" value={expectedDate} onChange={e => setExpectedDate(e.target.value)} />
            </div>
          </div>

          <div className="space-y-1.5">
            <Label className="text-sm text-muted-foreground">Notes (optional)</Label>
            <Input value={notes} onChange={e => setNotes(e.target.value)} placeholder="Any special instructions" />
          </div>
        </div>
        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={onClose} disabled={saving}>Cancel</Button>
          <Button onClick={handleSubmit} disabled={saving}>
            {saving ? 'Submitting…' : 'Raise Purchase Order'}
          </Button>
        </DialogFooter>
        <p className="text-center text-xs text-muted-foreground -mt-2 pb-1">Press Enter ↵ to confirm</p>
      </DialogContent>
    </Dialog>
  );
}

// ── RejectDialog ──────────────────────────────────────────────────────────────

interface RejectDialogProps {
  po: PurchaseOrder;
  onClose: () => void;
  onDone: () => void;
}

function RejectDialog({ po, onClose, onDone }: RejectDialogProps) {
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);

  async function handleReject() {
    if (!reason.trim()) { toast.error('Please enter a reason for rejection'); return; }
    setSaving(true);
    try {
      await api.post(`/api/v1/inventory/purchase-orders/${po.id}/reject`, { reason: reason.trim() });
      toast.success('Purchase order rejected');
      onDone();
    } catch (e: any) {
      toast.error(e?.response?.data?.detail ?? 'Failed to reject');
    } finally { setSaving(false); }
  }

  return (
    <Dialog open onOpenChange={() => !saving && onClose()}>
      <DialogContent className="max-w-sm">
        <DialogHeader><DialogTitle>Reject {po.po_no}?</DialogTitle></DialogHeader>
        <div className="py-2 space-y-3">
          <p className="text-sm text-muted-foreground">Please provide a reason so the requester knows what to fix.</p>
          <div className="space-y-1.5">
            <Label>Reason *</Label>
            <Input value={reason} onChange={e => setReason(e.target.value)} placeholder="e.g. Budget not approved" autoFocus />
          </div>
        </div>
        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={onClose} disabled={saving}>Cancel</Button>
          <Button variant="destructive" onClick={handleReject} disabled={saving}>
            {saving ? 'Rejecting…' : 'Reject Order'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── ReceiveGoodsDialog ────────────────────────────────────────────────────────

interface ReceiveDialogProps {
  po: PurchaseOrder;
  onClose: () => void;
  onDone: () => void;
}

function ReceiveGoodsDialog({ po, onClose, onDone }: ReceiveDialogProps) {
  const [quantities, setQuantities] = useState<Record<string, string>>(
    Object.fromEntries(po.items.map(pi => [pi.id, '']))
  );
  const [saving, setSaving] = useState(false);

  async function handleSubmit() {
    const lines = po.items
      .map(pi => ({ po_item_id: pi.id, quantity_received: parseFloat(quantities[pi.id] || '0') }))
      .filter(l => l.quantity_received > 0);
    if (!lines.length) { toast.error('Enter quantity received for at least one item'); return; }
    setSaving(true);
    try {
      await api.post(`/api/v1/inventory/purchase-orders/${po.id}/receive`, { items: lines });
      toast.success('Stock added to inventory');
      onDone();
    } catch (e: any) {
      toast.error(e?.response?.data?.detail ?? 'Failed to receive goods');
    } finally { setSaving(false); }
  }

  const remaining = (pi: POItem) => Math.max(0, pi.quantity_ordered - pi.quantity_received);

  return (
    <Dialog open onOpenChange={() => !saving && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>📦 Receive Goods — {po.po_no}</DialogTitle>
        </DialogHeader>
        {po.supplier_name && (
          <p className="text-sm text-muted-foreground -mt-2">Supplier: {po.supplier_name}</p>
        )}
        <div className="space-y-3 py-2">
          {po.items.map(pi => (
            <div key={pi.id} className="rounded-lg border p-3 space-y-2">
              <div className="flex items-center justify-between">
                <p className="font-medium text-sm">{pi.item_name}</p>
                <p className="text-xs text-muted-foreground">
                  Remaining: {fmtNum(remaining(pi))} {pi.unit}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Input
                  type="number"
                  min="0"
                  max={String(remaining(pi))}
                  step="any"
                  value={quantities[pi.id]}
                  onChange={e => setQuantities(q => ({ ...q, [pi.id]: e.target.value }))}
                  placeholder={`Qty in ${pi.unit}`}
                  className="h-9"
                />
                <span className="text-sm text-muted-foreground shrink-0">{pi.unit}</span>
              </div>
            </div>
          ))}
        </div>
        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={onClose} disabled={saving}>Cancel</Button>
          <Button onClick={handleSubmit} disabled={saving}>
            {saving ? 'Adding to stock…' : 'Confirm Receipt'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── SettingsTab ───────────────────────────────────────────────────────────────

interface SettingsTabProps {
  isAdmin: boolean;
}

function SettingsTab({ isAdmin }: SettingsTabProps) {
  const [tg, setTg] = useState<TelegramSettings>({ bot_token: '', chat_id: '', report_time: '20:00', enabled: false });
  const [loadingTg, setLoadingTg] = useState(true);
  const [savingTg, setSavingTg] = useState(false);
  const [testingTg, setTestingTg] = useState(false);
  const [sendingReport, setSendingReport] = useState(false);

  const [categories, setCategories] = useState<string[]>([]);
  const [newCat, setNewCat] = useState('');
  const [savingCats, setSavingCats] = useState(false);

  const [masterSuppliers, setMasterSuppliers] = useState<Array<{id: string; name: string; contact_person: string|null; phone: string|null; email: string|null; is_active: boolean}>>([]);
  const [newSupplierName, setNewSupplierName] = useState('');
  const [savingSupplier, setSavingSupplier] = useState(false);

  const loadSettings = useCallback(async () => {
    try {
      const [tgRes, catRes, msRes] = await Promise.all([
        api.get<TelegramSettings>('/api/v1/inventory/settings'),
        api.get<{ categories: string[] }>('/api/v1/inventory/settings/categories'),
        api.get<any[]>('/api/v1/inventory/suppliers'),
      ]);
      setTg(tgRes.data);
      setCategories(catRes.data.categories);
      setMasterSuppliers(msRes.data);
    } catch { toast.error('Failed to load settings'); }
    finally { setLoadingTg(false); }
  }, []);

  useEffect(() => { loadSettings(); }, [loadSettings]);

  async function saveTg() {
    setSavingTg(true);
    try {
      const res = await api.put<TelegramSettings>('/api/v1/inventory/settings', tg);
      setTg(res.data);
      toast.success('Telegram settings saved');
    } catch (e: any) {
      toast.error(e?.response?.data?.detail ?? 'Failed to save');
    } finally { setSavingTg(false); }
  }

  async function testTg() {
    setTestingTg(true);
    try {
      await api.post('/api/v1/inventory/settings/test');
      toast.success('Test message sent! Check your Telegram.');
    } catch (e: any) {
      toast.error(e?.response?.data?.detail ?? 'Test failed — check token and chat ID');
    } finally { setTestingTg(false); }
  }

  async function sendReportNow() {
    setSendingReport(true);
    try {
      await api.post('/api/v1/inventory/daily-report/send');
      toast.success('Daily report sent to Telegram!');
    } catch (e: any) {
      toast.error(e?.response?.data?.detail ?? 'Failed to send report');
    } finally { setSendingReport(false); }
  }

  function addCategory() {
    const c = newCat.trim().toLowerCase();
    if (!c) return;
    if (categories.includes(c)) { toast.error('Category already exists'); return; }
    setCategories(cats => [...cats, c]);
    setNewCat('');
  }

  function removeCategory(cat: string) {
    if (categories.length <= 1) { toast.error('At least one category is required'); return; }
    setCategories(cats => cats.filter(c => c !== cat));
  }

  async function saveCategories() {
    setSavingCats(true);
    try {
      await api.put('/api/v1/inventory/settings/categories', { categories });
      toast.success('Categories saved');
    } catch (e: any) {
      toast.error(e?.response?.data?.detail ?? 'Failed to save categories');
    } finally { setSavingCats(false); }
  }

  async function addMasterSupplier() {
    if (!newSupplierName.trim()) return;
    setSavingSupplier(true);
    try {
      const res = await api.post('/api/v1/inventory/suppliers', { name: newSupplierName.trim() });
      setMasterSuppliers(prev => [...prev, res.data]);
      setNewSupplierName('');
      toast.success('Supplier added to master');
    } catch (e: any) {
      toast.error(e?.response?.data?.detail ?? 'Failed to add supplier');
    } finally { setSavingSupplier(false); }
  }

  async function deleteMasterSupplier(id: string) {
    try {
      await api.delete(`/api/v1/inventory/suppliers/${id}`);
      setMasterSuppliers(prev => prev.filter(s => s.id !== id));
      toast.success('Supplier removed');
    } catch { toast.error('Failed to remove supplier'); }
  }

  if (!isAdmin) {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-center">
        <Settings className="h-12 w-12 text-muted-foreground mb-4 opacity-40" />
        <p className="text-muted-foreground">Admin access required to view settings.</p>
      </div>
    );
  }

  if (loadingTg) {
    return <div className="py-12 text-center text-muted-foreground">Loading settings…</div>;
  }

  return (
    <div className="space-y-6 max-w-lg">

      {/* Telegram Card */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            📱 Telegram Daily Report
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-xs text-muted-foreground">
            An inventory summary is automatically sent to your Telegram group or channel every evening.
          </p>

          <div className="flex items-center gap-3">
            <Switch
              checked={tg.enabled}
              onCheckedChange={v => setTg(t => ({ ...t, enabled: v }))}
            />
            <Label>{tg.enabled ? 'Enabled' : 'Disabled'}</Label>
          </div>

          <div className="space-y-1.5">
            <Label>Bot Token</Label>
            <Input
              type="password"
              value={tg.bot_token}
              onChange={e => setTg(t => ({ ...t, bot_token: e.target.value }))}
              placeholder="1234567890:ABCdef..."
            />
            <p className="text-xs text-muted-foreground">Get this from @BotFather on Telegram</p>
          </div>

          <div className="space-y-1.5">
            <Label>Chat ID</Label>
            <Input
              value={tg.chat_id}
              onChange={e => setTg(t => ({ ...t, chat_id: e.target.value }))}
              placeholder="-1001234567890 or @channelname"
            />
          </div>

          <div className="space-y-1.5">
            <Label>Report Time (24-hour)</Label>
            <Input
              type="time"
              value={tg.report_time}
              onChange={e => setTg(t => ({ ...t, report_time: e.target.value }))}
              className="w-36"
            />
          </div>

          <div className="flex gap-2 pt-2">
            <Button onClick={saveTg} disabled={savingTg} className="flex-1">
              {savingTg ? 'Saving…' : 'Save Settings'}
            </Button>
            <Button variant="outline" onClick={testTg} disabled={testingTg}>
              {testingTg ? 'Sending…' : 'Test'}
            </Button>
            <Button variant="outline" onClick={sendReportNow} disabled={sendingReport}>
              {sendingReport ? 'Sending…' : 'Send Now'}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Master Suppliers */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">🏭 Master Supplier List</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-xs text-muted-foreground">
            Maintain your approved supplier directory. These are shown as suggestions when adding suppliers to items or raising purchase orders.
          </p>
          <div className="space-y-1 max-h-48 overflow-y-auto">
            {masterSuppliers.length === 0 && (
              <p className="text-xs text-muted-foreground py-2 text-center">No suppliers yet.</p>
            )}
            {masterSuppliers.map(s => (
              <div key={s.id} className="flex items-center justify-between px-3 py-1.5 rounded-md bg-muted/40 text-sm">
                <span className="font-medium">{s.name}</span>
                {isAdmin && (
                  <Button variant="ghost" size="icon" className="h-6 w-6 text-muted-foreground hover:text-destructive"
                    onClick={() => deleteMasterSupplier(s.id)}>
                    <X className="h-3 w-3" />
                  </Button>
                )}
              </div>
            ))}
          </div>
          {isAdmin && (
            <div className="flex gap-2">
              <Input
                value={newSupplierName}
                onChange={e => setNewSupplierName(e.target.value)}
                placeholder="New supplier name"
                className="flex-1"
                onKeyDown={e => e.key === 'Enter' && addMasterSupplier()}
              />
              <Button onClick={addMasterSupplier} disabled={savingSupplier || !newSupplierName.trim()} size="sm">
                <Plus className="h-4 w-4 mr-1" /> Add
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Categories Card */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">📁 Item Categories</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-2">
            {categories.map(cat => (
              <div key={cat} className="flex items-center gap-1 bg-muted rounded-full px-3 py-1">
                <span className="text-sm">{CATEGORY_ICONS[cat] ?? '📦'} {cat}</span>
                <button onClick={() => removeCategory(cat)} className="ml-1 text-muted-foreground hover:text-destructive">
                  <X className="h-3 w-3" />
                </button>
              </div>
            ))}
          </div>
          <div className="flex gap-2">
            <Input
              value={newCat}
              onChange={e => setNewCat(e.target.value)}
              placeholder="New category name"
              onKeyDown={e => e.key === 'Enter' && addCategory()}
              className="flex-1"
            />
            <Button variant="outline" onClick={addCategory} size="sm">
              <Plus className="h-4 w-4 mr-1" /> Add
            </Button>
          </div>
          <Button onClick={saveCategories} disabled={savingCats} size="sm" className="w-full">
            {savingCats ? 'Saving…' : 'Save Categories'}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

// ── Analytics Tab ─────────────────────────────────────────────────────────────

interface AnalyticsData {
  trend: { date: string; issues: number; receipts: number }[];
  top_consumed: { item_id: string; item_name: string; unit: string; total_qty: number }[];
  category_breakdown: { category: string; total: number }[];
  summary: { total_issues: number; total_receipts: number; issue_count: number; receipt_count: number };
}

type AnalyticsPreset = 'today' | '7d' | '30d' | 'month' | 'last_month' | 'custom';

const PRESET_LABELS: Record<AnalyticsPreset, string> = {
  today:      'Today',
  '7d':       'Last 7 Days',
  '30d':      'Last 30 Days',
  month:      'This Month',
  last_month: 'Last Month',
  custom:     'Custom',
};

function getPresetDates(preset: AnalyticsPreset): { from: string; to: string } {
  const today = new Date();
  const toStr = today.toISOString().split('T')[0];
  switch (preset) {
    case 'today': return { from: toStr, to: toStr };
    case '7d': {
      const d = new Date(today); d.setDate(d.getDate() - 6);
      return { from: d.toISOString().split('T')[0], to: toStr };
    }
    case '30d': {
      const d = new Date(today); d.setDate(d.getDate() - 29);
      return { from: d.toISOString().split('T')[0], to: toStr };
    }
    case 'month': {
      const d = new Date(today.getFullYear(), today.getMonth(), 1);
      return { from: d.toISOString().split('T')[0], to: toStr };
    }
    case 'last_month': {
      const first = new Date(today.getFullYear(), today.getMonth() - 1, 1);
      const last  = new Date(today.getFullYear(), today.getMonth(), 0);
      return { from: first.toISOString().split('T')[0], to: last.toISOString().split('T')[0] };
    }
    default: return { from: toStr, to: toStr };
  }
}

const CAT_COLORS: Record<string, string> = {
  fuel: '#f59e0b', electricity: '#3b82f6', parts: '#8b5cf6',
  tools: '#10b981', other: '#6b7280',
};
const CHART_PALETTE = ['#3b82f6','#f59e0b','#10b981','#8b5cf6','#ef4444','#06b6d4','#f97316','#84cc16'];

interface AnalyticsTabProps { items: InventoryItem[] }

function AnalyticsTab({ items }: AnalyticsTabProps) {
  const [preset, setPreset]         = useState<AnalyticsPreset>('30d');
  const [customFrom, setCustomFrom] = useState('');
  const [customTo, setCustomTo]     = useState('');
  const [granularity, setGranularity] = useState<'daily' | 'weekly' | 'monthly'>('daily');
  const [itemFilter, setItemFilter] = useState('');
  const [data, setData]             = useState<AnalyticsData | null>(null);
  const [loading, setLoading]       = useState(false);

  const { from, to } = preset === 'custom'
    ? { from: customFrom, to: customTo }
    : getPresetDates(preset);

  const loadAnalytics = useCallback(async () => {
    if (!from || !to) return;
    setLoading(true);
    try {
      const params = new URLSearchParams({ date_from: from, date_to: to, granularity });
      if (itemFilter) params.set('item_id', itemFilter);
      const { data: res } = await api.get<AnalyticsData>(`/api/v1/inventory/analytics?${params}`);
      setData(res);
    } catch {
      toast.error('Failed to load analytics');
    } finally {
      setLoading(false);
    }
  }, [from, to, granularity, itemFilter]);

  useEffect(() => { loadAnalytics(); }, [loadAnalytics]);

  function fmtAxisDate(dateStr: string) {
    const d = new Date(dateStr + 'T00:00:00');
    if (granularity === 'monthly')
      return d.toLocaleDateString('en-IN', { month: 'short', year: '2-digit' });
    return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' });
  }

  function n2(v: number) {
    return v % 1 === 0 ? v.toString() : parseFloat(v.toFixed(2)).toString();
  }

  const netChange = data ? data.summary.total_receipts - data.summary.total_issues : 0;

  return (
    <div className="space-y-5 py-2">
      {/* ── Controls bar ─────────────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-end gap-3">
        {/* Preset chips */}
        <div className="flex flex-wrap gap-1.5">
          {(Object.entries(PRESET_LABELS) as [AnalyticsPreset, string][]).map(([key, label]) => (
            <button
              key={key}
              onClick={() => setPreset(key)}
              className={`px-3 py-1.5 rounded-full text-xs font-medium border transition-colors ${
                preset === key
                  ? 'bg-primary text-primary-foreground border-primary'
                  : 'bg-background text-muted-foreground border-border hover:border-primary/50 hover:text-foreground'
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {/* Custom date pickers — only shown when custom is active */}
        {preset === 'custom' && (
          <div className="flex items-center gap-2">
            <Input type="date" value={customFrom} onChange={e => setCustomFrom(e.target.value)} className="w-36 h-8 text-xs" />
            <span className="text-muted-foreground text-xs">to</span>
            <Input type="date" value={customTo} onChange={e => setCustomTo(e.target.value)} className="w-36 h-8 text-xs" />
          </div>
        )}

        <div className="flex-1" />

        {/* Item drill-down filter */}
        <Select value={itemFilter || '_all'} onValueChange={v => setItemFilter(v === '_all' ? '' : v)}>
          <SelectTrigger className="w-44 h-8 text-xs">
            <SelectValue>
              {itemFilter ? (items.find(i => i.id === itemFilter)?.name ?? 'All Items') : 'All Items'}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="_all">All Items</SelectItem>
            {items.map(i => (
              <SelectItem key={i.id} value={i.id}>{i.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>

        {/* Granularity toggle */}
        <div className="flex rounded-md border bg-muted overflow-hidden text-xs">
          {(['daily', 'weekly', 'monthly'] as const).map(g => (
            <button
              key={g}
              onClick={() => setGranularity(g)}
              className={`px-3 py-1.5 font-medium capitalize transition-colors ${
                granularity === g
                  ? 'bg-background shadow-sm text-foreground'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              {g.charAt(0).toUpperCase() + g.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {/* ── Loading state ─────────────────────────────────────────────────────── */}
      {loading && (
        <div className="flex items-center justify-center h-64 text-muted-foreground gap-2">
          <div className="h-4 w-4 border-2 border-primary border-t-transparent rounded-full animate-spin" />
          <span className="text-sm">Loading analytics…</span>
        </div>
      )}

      {/* ── Data ─────────────────────────────────────────────────────────────── */}
      {!loading && data && (
        <>
          {/* Summary stat cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div className="rounded-lg border bg-card p-4">
              <p className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium">Total Consumed</p>
              <p className="text-2xl font-bold text-red-600 mt-1">{n2(data.summary.total_issues)}</p>
              <p className="text-xs text-muted-foreground mt-0.5">{data.summary.issue_count} issue transactions</p>
            </div>
            <div className="rounded-lg border bg-card p-4">
              <p className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium">Total Received</p>
              <p className="text-2xl font-bold text-green-600 mt-1">{n2(data.summary.total_receipts)}</p>
              <p className="text-xs text-muted-foreground mt-0.5">{data.summary.receipt_count} PO receipts</p>
            </div>
            <div className="rounded-lg border bg-card p-4">
              <p className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium">Net Stock Change</p>
              <p className={`text-2xl font-bold mt-1 ${netChange >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                {netChange >= 0 ? '+' : ''}{n2(netChange)}
              </p>
              <p className="text-xs text-muted-foreground mt-0.5">receipts − consumption</p>
            </div>
            <div className="rounded-lg border bg-card p-4">
              <p className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium">Top Consumed</p>
              {data.top_consumed[0] ? (
                <>
                  <p className="text-base font-bold mt-1 leading-tight truncate">{data.top_consumed[0].item_name}</p>
                  <p className="text-xs text-muted-foreground mt-0.5">{n2(data.top_consumed[0].total_qty)} {data.top_consumed[0].unit}</p>
                </>
              ) : (
                <p className="text-sm text-muted-foreground mt-1">No data</p>
              )}
            </div>
          </div>

          {/* Trend Chart */}
          <div className="rounded-lg border bg-card p-4">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-semibold flex items-center gap-2">
                <TrendingUp className="h-4 w-4 text-primary" />
                Consumption &amp; Receipt Trend
              </h3>
              <span className="text-xs text-muted-foreground">
                {from === to ? from : `${from} → ${to}`}
              </span>
            </div>
            {data.trend.length === 0 ? (
              <div className="h-48 flex items-center justify-center text-muted-foreground text-sm border-2 border-dashed rounded-lg">
                No transaction data for this period
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={data.trend} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="hsl(var(--border))" />
                  <XAxis
                    dataKey="date"
                    tickFormatter={fmtAxisDate}
                    tick={{ fontSize: 11 }}
                    tickLine={false}
                    axisLine={false}
                  />
                  <YAxis tick={{ fontSize: 11 }} tickLine={false} axisLine={false} width={42} />
                  <Tooltip
                    formatter={(val: number, name: string) => [
                      n2(val),
                      name === 'issues' ? '⬇ Consumed' : '⬆ Received',
                    ]}
                    labelFormatter={fmtAxisDate}
                    contentStyle={{ borderRadius: '6px', fontSize: '12px', border: '1px solid hsl(var(--border))' }}
                  />
                  <Legend
                    formatter={v => v === 'issues' ? 'Consumed' : 'Received'}
                    iconType="square"
                    wrapperStyle={{ fontSize: '12px' }}
                  />
                  <Bar dataKey="issues"   name="issues"   fill="#ef4444" radius={[3,3,0,0]} maxBarSize={40} />
                  <Bar dataKey="receipts" name="receipts" fill="#22c55e" radius={[3,3,0,0]} maxBarSize={40} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>

          {/* Bottom row: Top Consumed + Category Breakdown */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Top consumed items — horizontal bar */}
            <div className="rounded-lg border bg-card p-4">
              <h3 className="text-sm font-semibold mb-4">🏆 Top Consumed Items</h3>
              {data.top_consumed.length === 0 ? (
                <div className="h-40 flex items-center justify-center text-muted-foreground text-sm border-2 border-dashed rounded-lg">
                  No consumption data
                </div>
              ) : (
                <ResponsiveContainer width="100%" height={Math.max(180, data.top_consumed.length * 38)}>
                  <BarChart
                    data={data.top_consumed.map(d => ({
                      ...d,
                      label: d.item_name.length > 18 ? d.item_name.slice(0, 16) + '…' : d.item_name,
                    }))}
                    layout="vertical"
                    margin={{ top: 0, right: 24, left: 0, bottom: 0 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="hsl(var(--border))" />
                    <XAxis type="number" tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
                    <YAxis type="category" dataKey="label" tick={{ fontSize: 11 }} tickLine={false} axisLine={false} width={100} />
                    <Tooltip
                      formatter={(val: number, _name: string, props: any) => [
                        `${n2(val)} ${props.payload.unit}`,
                        'Consumed',
                      ]}
                      contentStyle={{ borderRadius: '6px', fontSize: '12px', border: '1px solid hsl(var(--border))' }}
                    />
                    <Bar dataKey="total_qty" name="Consumed" radius={[0,3,3,0]} maxBarSize={24}>
                      {data.top_consumed.map((_, i) => (
                        <Cell key={i} fill={CHART_PALETTE[i % CHART_PALETTE.length]} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>

            {/* Category breakdown — donut */}
            <div className="rounded-lg border bg-card p-4">
              <h3 className="text-sm font-semibold mb-4">📊 Consumption by Category</h3>
              {data.category_breakdown.length === 0 ? (
                <div className="h-40 flex items-center justify-center text-muted-foreground text-sm border-2 border-dashed rounded-lg">
                  No category data
                </div>
              ) : (
                <>
                  <ResponsiveContainer width="100%" height={200}>
                    <PieChart>
                      <Pie
                        data={data.category_breakdown}
                        dataKey="total"
                        nameKey="category"
                        cx="50%" cy="50%"
                        innerRadius={55}
                        outerRadius={88}
                        paddingAngle={2}
                      >
                        {data.category_breakdown.map((entry, i) => (
                          <Cell
                            key={i}
                            fill={CAT_COLORS[entry.category] ?? CHART_PALETTE[i % CHART_PALETTE.length]}
                          />
                        ))}
                      </Pie>
                      <Tooltip
                        formatter={(val: number) => n2(val)}
                        contentStyle={{ borderRadius: '6px', fontSize: '12px', border: '1px solid hsl(var(--border))' }}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                  <div className="flex flex-wrap gap-x-4 gap-y-1.5 mt-1 justify-center">
                    {data.category_breakdown.map((entry, i) => (
                      <div key={i} className="flex items-center gap-1.5 text-xs text-muted-foreground capitalize">
                        <span
                          className="h-2.5 w-2.5 rounded-sm flex-shrink-0"
                          style={{ backgroundColor: CAT_COLORS[entry.category] ?? CHART_PALETTE[i % CHART_PALETTE.length] }}
                        />
                        {entry.category} ({n2(entry.total)})
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          </div>
        </>
      )}

      {/* Empty state when no data after load */}
      {!loading && !data && (
        <div className="flex flex-col items-center justify-center h-64 text-muted-foreground gap-3">
          <TrendingUp className="h-10 w-10 opacity-30" />
          <p className="text-sm">Select a date range above to view analytics</p>
        </div>
      )}
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function InventoryPage() {
  const [activeTab, setActiveTab] = useState<'stock' | 'orders' | 'history' | 'analytics' | 'settings'>('stock');
  const [dashboard, setDashboard] = useState<InventoryDashboard | null>(null);
  const [categories, setCategories] = useState<string[]>(['fuel', 'electricity', 'parts', 'tools', 'other']);
  const [loading, setLoading] = useState(true);
  const [viewMode, setViewMode] = useState<'table' | 'card'>('table');

  // Orders state
  const [orders, setOrders] = useState<PurchaseOrder[]>([]);
  const [orderStatusFilter, setOrderStatusFilter] = useState<string>('all');
  const [orderSearch, setOrderSearch] = useState('');
  const [orderDateFrom, setOrderDateFrom] = useState('');
  const [orderDateTo, setOrderDateTo] = useState('');
  const [orderSort, setOrderSort] = useState<{ col: string; dir: 'asc' | 'desc' }>({ col: 'created_at', dir: 'desc' });
  const [loadingOrders, setLoadingOrders] = useState(false);

  // History state
  const [transactions, setTransactions] = useState<InventoryTransaction[]>([]);
  const [txTotal, setTxTotal] = useState(0);
  const [txPage, setTxPage] = useState(1);
  const [txDateFrom, setTxDateFrom] = useState('');
  const [txDateTo, setTxDateTo] = useState('');
  const [txItemFilter, setTxItemFilter] = useState('');
  const [txTypeFilter, setTxTypeFilter] = useState('');
  const [loadingTx, setLoadingTx] = useState(false);

  // Dialog state
  const [useStockItem, setUseStockItem] = useState<InventoryItem | null>(null);
  const [adjustingItem, setAdjustingItem] = useState<InventoryItem | null>(null);
  const [suppliersTarget, setSuppliersTarget] = useState<InventoryItem | null>(null);
  const [showAddItem, setShowAddItem] = useState(false);
  const [editingItem, setEditingItem] = useState<InventoryItem | null>(null);
  const [showNewPO, setShowNewPO] = useState(false);
  const [editingPO, setEditingPO] = useState<PurchaseOrder | null>(null);
  const [rejectPO, setRejectPO] = useState<PurchaseOrder | null>(null);
  const [receivePO, setReceivePO] = useState<PurchaseOrder | null>(null);

  // User role
  const [isAdmin, setIsAdmin] = useState(false);

  useEffect(() => {
    api.get<{ role: string }>('/api/v1/auth/me')
      .then(r => setIsAdmin(r.data.role === 'admin' || r.data.role === 'store_manager'))
      .catch(() => {});
  }, []);

  // Auto-refresh poll
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadDashboard = useCallback(async () => {
    try {
      const [dashRes, catRes] = await Promise.all([
        api.get<InventoryDashboard>('/api/v1/inventory/dashboard'),
        api.get<{ categories: string[] }>('/api/v1/inventory/settings/categories'),
      ]);
      setDashboard(dashRes.data);
      setCategories(catRes.data.categories);
    } catch { /* silent on poll */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    loadDashboard();
    pollRef.current = setInterval(loadDashboard, 30_000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [loadDashboard]);

  const loadOrders = useCallback(async () => {
    setLoadingOrders(true);
    try {
      const params = orderStatusFilter !== 'all' ? `?status=${orderStatusFilter}` : '';
      const res = await api.get<{ items: PurchaseOrder[]; total: number }>(`/api/v1/inventory/purchase-orders${params}`);
      setOrders(res.data.items);
    } catch { toast.error('Failed to load orders'); }
    finally { setLoadingOrders(false); }
  }, [orderStatusFilter]);

  useEffect(() => {
    if (activeTab === 'orders') loadOrders();
  }, [activeTab, loadOrders]);

  const loadTransactions = useCallback(async () => {
    setLoadingTx(true);
    try {
      const params = new URLSearchParams({ page: String(txPage), page_size: '50' });
      if (txDateFrom) params.set('date_from', txDateFrom);
      if (txDateTo)   params.set('date_to', txDateTo);
      if (txItemFilter) params.set('item_id', txItemFilter);
      if (txTypeFilter) params.set('transaction_type', txTypeFilter);
      const res = await api.get<{ items: InventoryTransaction[]; total: number }>(`/api/v1/inventory/transactions?${params}`);
      setTransactions(res.data.items);
      setTxTotal(res.data.total);
    } catch { toast.error('Failed to load history'); }
    finally { setLoadingTx(false); }
  }, [txPage, txDateFrom, txDateTo, txItemFilter, txTypeFilter]);

  useEffect(() => {
    if (activeTab === 'history') loadTransactions();
  }, [activeTab, loadTransactions]);

  async function approveOrder(poId: string) {
    try {
      await api.post(`/api/v1/inventory/purchase-orders/${poId}/approve`);
      toast.success('Purchase order approved');
      loadOrders();
    } catch (e: any) { toast.error(e?.response?.data?.detail ?? 'Failed to approve'); }
  }

  const items = dashboard?.items ?? [];
  const pendingCount = dashboard?.pending_po_count ?? 0;
  const recentTxns = dashboard?.recent_transactions ?? [];

  // ── Render ──────────────────────────────────────────────────────────────────
  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Package className="h-6 w-6" /> Store Inventory
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Track raw materials — Fuel, Parts, Tools &amp; more
          </p>
        </div>
        <div className="flex gap-2">
          <div className="flex rounded-md border overflow-hidden">
            <Button
              variant={viewMode === 'table' ? 'default' : 'outline'}
              size="sm"
              className="rounded-none border-0 px-2.5"
              onClick={() => setViewMode('table')}
              title="Table view"
            >
              <List className="h-4 w-4" />
            </Button>
            <Button
              variant={viewMode === 'card' ? 'default' : 'outline'}
              size="sm"
              className="rounded-none border-0 border-l px-2.5"
              onClick={() => setViewMode('card')}
              title="Card view"
            >
              <LayoutGrid className="h-4 w-4" />
            </Button>
          </div>
          <Button onClick={() => setShowNewPO(true)} variant="outline" size="sm">
            <ShoppingCart className="h-4 w-4 mr-1.5" /> Order More
          </Button>
          {isAdmin && (
            <Button onClick={() => { setEditingItem(null); setShowAddItem(true); }} size="sm">
              <Plus className="h-4 w-4 mr-1.5" /> Add Item
            </Button>
          )}
        </div>
      </div>

      {/* Pending approval badge */}
      {pendingCount > 0 && (
        <div
          className="flex items-center gap-2 px-4 py-2.5 rounded-lg bg-amber-50 border border-amber-200 text-amber-800 text-sm cursor-pointer hover:bg-amber-100 transition-colors"
          onClick={() => { setActiveTab('orders'); setOrderStatusFilter('pending_approval'); }}
        >
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span>
            <strong>{pendingCount}</strong> purchase order{pendingCount !== 1 ? 's' : ''} waiting for approval — click to review
          </span>
        </div>
      )}

      <Tabs value={activeTab} onValueChange={v => setActiveTab(v as any)}>
        <TabsList>
          <TabsTrigger value="stock">📦 Stock</TabsTrigger>
          <TabsTrigger value="orders" className="relative">
            📋 Orders
            {pendingCount > 0 && (
              <span className="absolute -top-1 -right-1 bg-amber-500 text-white text-[10px] font-bold rounded-full h-4 w-4 flex items-center justify-center">
                {pendingCount}
              </span>
            )}
          </TabsTrigger>
          <TabsTrigger value="history">📊 History</TabsTrigger>
          <TabsTrigger value="analytics">📈 Analytics</TabsTrigger>
          {isAdmin && <TabsTrigger value="settings">⚙️ Settings</TabsTrigger>}
        </TabsList>

        {/* ── Tab 1: Stock ───────────────────────────────────────────────────── */}
        <TabsContent value="stock" className="mt-4">
          {loading ? (
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
              {[...Array(4)].map((_, i) => (
                <Card key={i} className="border-t-4 border-t-muted animate-pulse">
                  <CardContent className="pt-5 pb-4 px-5 space-y-3">
                    <div className="h-8 w-8 bg-muted rounded-full" />
                    <div className="h-4 bg-muted rounded w-3/4" />
                    <div className="h-12 bg-muted rounded w-1/2" />
                    <div className="h-10 bg-muted rounded" />
                  </CardContent>
                </Card>
              ))}
            </div>
          ) : items.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-24 text-center">
              <Package className="h-16 w-16 text-muted-foreground mb-4 opacity-30" />
              <h3 className="text-lg font-semibold mb-2">No inventory items yet</h3>
              <p className="text-muted-foreground text-sm mb-6 max-w-xs">
                Add your first item — Diesel, Engine Oil, Drill Bits — and start tracking your stock.
              </p>
              {isAdmin && (
                <Button onClick={() => { setEditingItem(null); setShowAddItem(true); }}>
                  <Plus className="h-4 w-4 mr-1.5" /> Add First Item
                </Button>
              )}
            </div>
          ) : viewMode === 'card' ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {items.map(item => (
                <StockCard
                  key={item.id}
                  item={item}
                  isAdmin={isAdmin}
                  onUse={setUseStockItem}
                  onEdit={item => { setEditingItem(item); setShowAddItem(true); }}
                  onAdjust={setAdjustingItem}
                  onManageSuppliers={setSuppliersTarget}
                />
              ))}
            </div>
          ) : (
            <>
              <div className="rounded-lg border overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-muted/50 border-b">
                    <tr>
                      <th className="text-left px-4 py-3 font-medium">Item</th>
                      <th className="text-left px-4 py-3 font-medium hidden sm:table-cell">Category</th>
                      <th className="text-right px-4 py-3 font-medium">Stock</th>
                      <th className="text-center px-4 py-3 font-medium">Status</th>
                      <th className="text-left px-4 py-3 font-medium hidden md:table-cell">Preferred Supplier</th>
                      <th className="text-right px-4 py-3 font-medium hidden lg:table-cell">Min Level</th>
                      <th className="text-right px-4 py-3 font-medium">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {items.map((item) => {
                      const preferred = item.suppliers?.find(s => s.is_preferred) ?? item.suppliers?.[0] ?? null;
                      return (
                        <tr key={item.id} className="hover:bg-muted/30">
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-2">
                              <span className="text-lg">{CATEGORY_ICONS[item.category] ?? '📦'}</span>
                              <div>
                                <p className="font-semibold leading-tight">{item.name}</p>
                                {item.description && <p className="text-xs text-muted-foreground truncate max-w-[160px]">{item.description}</p>}
                              </div>
                            </div>
                          </td>
                          <td className="px-4 py-3 hidden sm:table-cell">
                            <span className="text-xs px-2 py-0.5 rounded-full bg-muted font-medium capitalize">{item.category}</span>
                          </td>
                          <td className="px-4 py-3 text-right">
                            <span className={`text-xl font-black ${STOCK_NUM_COLOR[item.stock_status]}`}>
                              {fmtNum(item.current_stock)}
                            </span>
                            <span className="text-xs text-muted-foreground ml-1">{item.unit}</span>
                          </td>
                          <td className="px-4 py-3 text-center">
                            {item.stock_status === 'ok'  && <span className="inline-block text-xs px-2 py-0.5 rounded-full bg-green-100 text-green-700 font-medium">OK</span>}
                            {item.stock_status === 'low' && <span className="inline-block text-xs px-2 py-0.5 rounded-full bg-yellow-100 text-yellow-700 font-medium">LOW</span>}
                            {item.stock_status === 'out' && <span className="inline-block text-xs px-2 py-0.5 rounded-full bg-red-100 text-red-700 font-medium">OUT</span>}
                          </td>
                          <td className="px-4 py-3 hidden md:table-cell">
                            {preferred ? (
                              <div className="text-xs">
                                <p className="font-medium">{preferred.is_preferred ? '⭐ ' : ''}{preferred.supplier_name}</p>
                                <p className="text-muted-foreground">
                                  {preferred.agreed_unit_price != null && `₹${parseFloat(String(preferred.agreed_unit_price)).toFixed(2)}/${item.unit}`}
                                  {preferred.lead_time_days != null && ` · ${preferred.lead_time_days}d ETA`}
                                  {preferred.moq != null && ` · MOQ: ${fmtNum(Number(preferred.moq))}`}
                                </p>
                              </div>
                            ) : (
                              <span className="text-xs text-muted-foreground">—</span>
                            )}
                          </td>
                          <td className="px-4 py-3 text-right hidden lg:table-cell">
                            <span className="text-xs text-muted-foreground">{fmtNum(item.min_stock_level)} {item.unit}</span>
                          </td>
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-1 justify-end">
                              <Button
                                size="sm"
                                variant={item.stock_status === 'out' ? 'outline' : 'default'}
                                disabled={item.stock_status === 'out'}
                                className="h-7 text-xs px-2"
                                onClick={() => setUseStockItem(item)}
                              >
                                {item.stock_status === 'out' ? 'Out' : 'Use'}
                              </Button>
                              {isAdmin && (
                                <>
                                  <Button size="icon" variant="ghost" className="h-7 w-7" title="Adjust stock"
                                    onClick={() => setAdjustingItem(item)}>
                                    <SlidersHorizontal className="h-3.5 w-3.5" />
                                  </Button>
                                  <Button size="icon" variant="ghost" className="h-7 w-7" title="Manage suppliers"
                                    onClick={() => setSuppliersTarget(item)}>
                                    <span className="text-xs">🏭</span>
                                  </Button>
                                  <Button size="icon" variant="ghost" className="h-7 w-7" title="Edit item"
                                    onClick={() => { setEditingItem(item); setShowAddItem(true); }}>
                                    <Edit className="h-3.5 w-3.5" />
                                  </Button>
                                </>
                              )}
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {/* Recent activity strip */}
              {recentTxns.length > 0 && (
                <div className="mt-6">
                  <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide mb-3">
                    Recent Activity
                  </h3>
                  <div className="space-y-1">
                    {recentTxns.slice(0, 5).map(txn => (
                      <div key={txn.id} className="flex items-center justify-between text-sm px-3 py-2 rounded-lg hover:bg-muted/50">
                        <div className="flex items-center gap-3">
                          <span className={`font-bold text-xs px-1.5 py-0.5 rounded ${
                            txn.transaction_type === 'receipt' ? 'bg-green-100 text-green-700' :
                            txn.transaction_type === 'issue'   ? 'bg-red-100 text-red-700' :
                            'bg-gray-100 text-gray-700'
                          }`}>
                            {txn.transaction_type === 'receipt' ? 'IN' :
                             txn.transaction_type === 'issue'   ? 'OUT' : 'ADJ'}
                          </span>
                          <span className="font-medium">{txn.item_name}</span>
                          {txn.notes && <span className="text-muted-foreground hidden sm:inline">{txn.notes}</span>}
                        </div>
                        <div className="flex items-center gap-3 text-right">
                          <span className={`font-semibold ${
                            txn.transaction_type === 'receipt' ? 'text-green-700' :
                            txn.transaction_type === 'issue'   ? 'text-red-600' : 'text-muted-foreground'
                          }`}>
                            {txn.transaction_type === 'issue' ? '-' : '+'}{fmtNum(Math.abs(txn.quantity))}
                          </span>
                          <span className="text-xs text-muted-foreground hidden sm:block">
                            {new Date(txn.created_at).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </TabsContent>

        {/* ── Tab 2: Orders ──────────────────────────────────────────────────── */}
        <TabsContent value="orders" className="mt-4">
          {/* Toolbar: search + status filter + date range + new order button */}
          <div className="flex flex-wrap gap-3 mb-4 items-center">
            <Input
              value={orderSearch}
              onChange={e => setOrderSearch(e.target.value)}
              placeholder="Search PO#, item, supplier, requested by…"
              className="w-64"
            />
            <Select value={orderStatusFilter} onValueChange={setOrderStatusFilter}>
              <SelectTrigger className="w-44">
                <SelectValue placeholder="All statuses" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Statuses</SelectItem>
                <SelectItem value="pending_approval">Pending Approval</SelectItem>
                <SelectItem value="approved">Approved</SelectItem>
                <SelectItem value="partially_received">Partial</SelectItem>
                <SelectItem value="received">Received</SelectItem>
                <SelectItem value="rejected">Rejected</SelectItem>
              </SelectContent>
            </Select>
            <div className="flex items-center gap-1.5">
              <input
                type="date"
                value={orderDateFrom}
                onChange={e => setOrderDateFrom(e.target.value)}
                className="border rounded-md px-2.5 py-1.5 text-sm bg-background focus:outline-none focus:ring-2 focus:ring-ring"
                title="From date"
              />
              <span className="text-muted-foreground text-sm">–</span>
              <input
                type="date"
                value={orderDateTo}
                onChange={e => setOrderDateTo(e.target.value)}
                className="border rounded-md px-2.5 py-1.5 text-sm bg-background focus:outline-none focus:ring-2 focus:ring-ring"
                title="To date"
              />
            </div>
            {(orderSearch || orderStatusFilter !== 'all' || orderDateFrom || orderDateTo) && (
              <Button variant="ghost" size="sm" onClick={() => { setOrderSearch(''); setOrderStatusFilter('all'); setOrderDateFrom(''); setOrderDateTo(''); }}>
                <X className="h-3.5 w-3.5 mr-1" /> Clear
              </Button>
            )}
            <div className="flex-1" />
            <Button onClick={() => setShowNewPO(true)} size="sm">
              <Plus className="h-4 w-4 mr-1.5" /> New Order
            </Button>
          </div>

          {loadingOrders ? (
            <div className="py-8 text-center text-muted-foreground">Loading orders…</div>
          ) : orders.length === 0 ? (
            <div className="flex flex-col items-center py-20 text-center">
              <ShoppingCart className="h-14 w-14 text-muted-foreground mb-4 opacity-30" />
              <h3 className="text-base font-semibold mb-1">No orders yet</h3>
              <p className="text-sm text-muted-foreground mb-6">Click "Order More" to raise a purchase request.</p>
            </div>
          ) : (() => {
            // ── Client-side filter ────────────────────────────────────────────
            const q = orderSearch.toLowerCase();
            const filtered = orders.filter(po => {
              // Text search
              if (q) {
                const itemText = po.items.map(i => i.item_name).join(' ').toLowerCase();
                const textMatch =
                  po.po_no.toLowerCase().includes(q) ||
                  itemText.includes(q) ||
                  (po.supplier_name ?? '').toLowerCase().includes(q) ||
                  po.requested_by_name.toLowerCase().includes(q);
                if (!textMatch) return false;
              }
              // Date range filter on created_at
              const created = po.created_at?.slice(0, 10) ?? '';
              if (orderDateFrom && created < orderDateFrom) return false;
              if (orderDateTo && created > orderDateTo) return false;
              return true;
            });

            // ── Client-side sort ──────────────────────────────────────────────
            const sorted = [...filtered].sort((a, b) => {
              let av: any, bv: any;
              switch (orderSort.col) {
                case 'po_no':         av = a.po_no;              bv = b.po_no; break;
                case 'status':        av = a.status;             bv = b.status; break;
                case 'items':         av = a.items[0]?.item_name ?? ''; bv = b.items[0]?.item_name ?? ''; break;
                case 'supplier':      av = a.supplier_name ?? ''; bv = b.supplier_name ?? ''; break;
                case 'requested_by':  av = a.requested_by_name;  bv = b.requested_by_name; break;
                case 'expected_date': av = a.expected_date ?? ''; bv = b.expected_date ?? ''; break;
                default:              av = a.created_at;         bv = b.created_at;
              }
              if (av < bv) return orderSort.dir === 'asc' ? -1 : 1;
              if (av > bv) return orderSort.dir === 'asc' ? 1 : -1;
              return 0;
            });

            function SortTh({ col, label, className = '' }: { col: string; label: string; className?: string }) {
              const active = orderSort.col === col;
              return (
                <th
                  className={`p-3 font-medium text-left cursor-pointer select-none whitespace-nowrap hover:bg-muted/70 transition-colors ${className}`}
                  onClick={() => setOrderSort(s => ({ col, dir: s.col === col && s.dir === 'asc' ? 'desc' : 'asc' }))}
                >
                  <span className="flex items-center gap-1">
                    {label}
                    <span className="text-muted-foreground text-xs">
                      {active ? (orderSort.dir === 'asc' ? '▲' : '▼') : '⇅'}
                    </span>
                  </span>
                </th>
              );
            }

            return sorted.length === 0 ? (
              <div className="py-12 text-center text-muted-foreground text-sm">
                No orders match the current filters.
              </div>
            ) : (
              <div className="rounded-lg border overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-muted/50 border-b">
                    <tr>
                      <SortTh col="po_no"         label="PO #" />
                      <SortTh col="status"        label="Status" />
                      <SortTh col="items"         label="Items" />
                      <SortTh col="supplier"      label="Supplier" />
                      <SortTh col="requested_by"  label="Requested By" className="hidden md:table-cell" />
                      <SortTh col="expected_date" label="Expected" className="hidden lg:table-cell" />
                      <SortTh col="created_at"    label="Created" className="hidden lg:table-cell" />
                      <th className="p-3 font-medium text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sorted.map((po, idx) => {
                      const badge = PO_STATUS_BADGE[po.status] ?? { label: po.status, variant: 'outline' as const };
                      const itemsSummary = po.items.map(pi => `${pi.item_name} ×${fmtNum(pi.quantity_ordered)}`).join(', ');
                      return (
                        <tr key={po.id} className={`border-b last:border-0 hover:bg-muted/30 transition-colors ${idx % 2 === 0 ? '' : 'bg-muted/10'}`}>
                          {/* PO # */}
                          <td className="p-3">
                            <div className="flex items-center gap-1.5 flex-wrap">
                              <span className="font-mono font-semibold text-sm">{po.po_no}</span>
                              {po.is_auto_generated && (
                                <span className="text-[10px] text-blue-600 border border-blue-200 bg-blue-50 rounded px-1 py-0.5 leading-none">🤖 Auto</span>
                              )}
                            </div>
                          </td>

                          {/* Status */}
                          <td className="p-3">
                            <Badge variant={badge.variant as any} className="whitespace-nowrap">{badge.label}</Badge>
                            {po.rejection_reason && (
                              <p className="text-xs text-destructive mt-1 max-w-[140px] truncate" title={po.rejection_reason}>
                                {po.rejection_reason}
                              </p>
                            )}
                          </td>

                          {/* Items */}
                          <td className="p-3 max-w-[200px]">
                            <p className="truncate text-sm" title={itemsSummary}>{itemsSummary}</p>
                          </td>

                          {/* Supplier */}
                          <td className="p-3 text-muted-foreground text-sm">
                            {po.supplier_name ?? <span className="italic opacity-50">—</span>}
                          </td>

                          {/* Requested By */}
                          <td className="p-3 text-muted-foreground text-xs hidden md:table-cell whitespace-nowrap">
                            {po.requested_by_name}
                          </td>

                          {/* Expected */}
                          <td className="p-3 text-muted-foreground text-xs hidden lg:table-cell whitespace-nowrap">
                            {po.expected_date
                              ? new Date(po.expected_date + 'T00:00:00').toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
                              : '—'}
                          </td>

                          {/* Created */}
                          <td className="p-3 text-muted-foreground text-xs hidden lg:table-cell whitespace-nowrap">
                            {new Date(po.created_at).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })}
                          </td>

                          {/* Actions */}
                          <td className="p-3 text-right">
                            <div className="flex items-center justify-end gap-1.5">
                              {po.status === 'pending_approval' && isAdmin && (
                                <>
                                  <Button size="sm" variant="outline" className="h-7 px-2.5 text-xs" onClick={() => setEditingPO(po)}>
                                    <Edit className="h-3 w-3 mr-1" /> Edit
                                  </Button>
                                  <Button size="sm" className="h-7 px-2.5 text-xs" onClick={() => approveOrder(po.id)}>
                                    <Check className="h-3 w-3 mr-1" /> Approve
                                  </Button>
                                  <Button size="sm" variant="destructive" className="h-7 px-2.5 text-xs" onClick={() => setRejectPO(po)}>
                                    <X className="h-3 w-3 mr-1" /> Reject
                                  </Button>
                                </>
                              )}
                              {(po.status === 'approved' || po.status === 'partially_received') && isAdmin && (
                                <Button size="sm" variant="outline" className="h-7 px-2.5 text-xs" onClick={() => setReceivePO(po)}>
                                  📦 Receive
                                </Button>
                              )}
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                <div className="px-3 py-2 border-t bg-muted/30 text-xs text-muted-foreground">
                  Showing {sorted.length} of {orders.length} order{orders.length !== 1 ? 's' : ''}
                </div>
              </div>
            );
          })()}
        </TabsContent>

        {/* ── Tab 3: History ─────────────────────────────────────────────────── */}
        <TabsContent value="history" className="mt-4">
          {/* Filters */}
          <div className="flex flex-wrap gap-3 mb-4">
            <Input
              type="date"
              value={txDateFrom}
              onChange={e => { setTxDateFrom(e.target.value); setTxPage(1); }}
              className="w-36"
              placeholder="From"
            />
            <Input
              type="date"
              value={txDateTo}
              onChange={e => { setTxDateTo(e.target.value); setTxPage(1); }}
              className="w-36"
              placeholder="To"
            />
            <Select value={txItemFilter || '_all'} onValueChange={v => { setTxItemFilter(v === '_all' ? '' : v); setTxPage(1); }}>
              <SelectTrigger className="w-44">
                <SelectValue>
                  {txItemFilter ? (items.find(i => i.id === txItemFilter)?.name ?? 'All Items') : 'All Items'}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="_all">All Items</SelectItem>
                {items.map(it => <SelectItem key={it.id} value={it.id}>{it.name}</SelectItem>)}
              </SelectContent>
            </Select>
            <Select value={txTypeFilter || '_all'} onValueChange={v => { setTxTypeFilter(v === '_all' ? '' : v); setTxPage(1); }}>
              <SelectTrigger className="w-36">
                <SelectValue>
                  {txTypeFilter === 'issue' ? 'Issue (OUT)' : txTypeFilter === 'receipt' ? 'Receipt (IN)' : txTypeFilter === 'adjustment' ? 'Adjustment' : 'All Types'}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="_all">All Types</SelectItem>
                <SelectItem value="issue">Issue (OUT)</SelectItem>
                <SelectItem value="receipt">Receipt (IN)</SelectItem>
                <SelectItem value="adjustment">Adjustment</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {loadingTx ? (
            <div className="py-8 text-center text-muted-foreground">Loading history…</div>
          ) : transactions.length === 0 ? (
            <div className="py-16 text-center text-muted-foreground">
              <History className="h-12 w-12 mx-auto mb-3 opacity-30" />
              <p>No transactions found for the selected filters.</p>
            </div>
          ) : (
            <>
              <div className="rounded-lg border overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-muted/50 border-b">
                    <tr>
                      <th className="text-left p-3 font-medium">Recorded On</th>
                      <th className="text-left p-3 font-medium">Item</th>
                      <th className="text-center p-3 font-medium">Type</th>
                      <th className="text-right p-3 font-medium">Qty</th>
                      <th className="text-right p-3 font-medium hidden sm:table-cell">Stock After</th>
                      <th className="text-left p-3 font-medium hidden md:table-cell">Used By</th>
                      <th className="text-left p-3 font-medium hidden lg:table-cell">Used On</th>
                      <th className="text-left p-3 font-medium hidden md:table-cell">Note</th>
                    </tr>
                  </thead>
                  <tbody>
                    {transactions.map((txn, idx) => (
                      <tr key={txn.id} className={idx % 2 === 0 ? '' : 'bg-muted/20'}>
                        <td className="p-3 text-xs text-muted-foreground whitespace-nowrap">
                          {fmtDate(txn.created_at)}
                        </td>
                        <td className="p-3 font-medium">{txn.item_name}</td>
                        <td className="p-3 text-center">
                          <span className={`inline-block text-xs font-bold px-2 py-0.5 rounded ${
                            txn.transaction_type === 'receipt'    ? 'bg-green-100 text-green-700' :
                            txn.transaction_type === 'issue'      ? 'bg-red-100 text-red-700' :
                            'bg-gray-100 text-gray-600'
                          }`}>
                            {txn.transaction_type === 'receipt' ? 'IN' :
                             txn.transaction_type === 'issue'   ? 'OUT' : 'ADJ'}
                          </span>
                        </td>
                        <td className={`p-3 text-right font-semibold ${
                          txn.transaction_type === 'receipt' ? 'text-green-700' :
                          txn.transaction_type === 'issue'   ? 'text-red-600' : ''
                        }`}>
                          {txn.transaction_type === 'issue' ? '-' : txn.transaction_type === 'receipt' ? '+' : ''}
                          {fmtNum(Math.abs(txn.quantity))}
                        </td>
                        <td className="p-3 text-right text-muted-foreground hidden sm:table-cell">
                          {fmtNum(txn.stock_after)}
                        </td>
                        <td className="p-3 text-xs hidden md:table-cell">
                          {txn.used_by_name
                            ? <span className="font-medium text-foreground">{txn.used_by_name}</span>
                            : <span className="text-muted-foreground">{txn.created_by_name ?? '—'}</span>
                          }
                        </td>
                        <td className="p-3 text-xs text-muted-foreground hidden lg:table-cell whitespace-nowrap">
                          {txn.used_on
                            ? new Date(txn.used_on + 'T00:00:00').toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
                            : '—'
                          }
                        </td>
                        <td className="p-3 text-xs text-muted-foreground hidden md:table-cell truncate max-w-[180px]">
                          {txn.notes ?? txn.reference_no ?? '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              <div className="flex items-center justify-between mt-3 text-sm text-muted-foreground">
                <span>Showing {transactions.length} of {txTotal}</span>
                <div className="flex gap-2">
                  <Button variant="outline" size="sm" disabled={txPage <= 1}
                    onClick={() => setTxPage(p => p - 1)}>← Prev</Button>
                  <Button variant="outline" size="sm" disabled={txPage * 50 >= txTotal}
                    onClick={() => setTxPage(p => p + 1)}>Next →</Button>
                </div>
              </div>
            </>
          )}
        </TabsContent>

        {/* ── Tab 4: Settings ────────────────────────────────────────────────── */}
        <TabsContent value="settings" className="mt-4">
          <SettingsTab isAdmin={isAdmin} />
        </TabsContent>

        {/* ── Tab 5: Analytics ───────────────────────────────────────────────── */}
        <TabsContent value="analytics" className="mt-4">
          <AnalyticsTab items={dashboard?.items ?? []} />
        </TabsContent>
      </Tabs>

      {/* ── Dialogs ────────────────────────────────────────────────────────────── */}
      {useStockItem && (
        <UseStockDialog
          item={useStockItem}
          onClose={() => setUseStockItem(null)}
          onDone={() => { setUseStockItem(null); loadDashboard(); }}
        />
      )}

      {adjustingItem && (
        <AdjustStockDialog
          item={adjustingItem}
          onClose={() => setAdjustingItem(null)}
          onDone={() => { setAdjustingItem(null); loadDashboard(); }}
        />
      )}

      {suppliersTarget && (
        <ManageSuppliersDialog
          item={suppliersTarget}
          onClose={() => setSuppliersTarget(null)}
          onDone={() => loadDashboard()}
        />
      )}

      {showAddItem && (
        <AddItemDialog
          categories={categories}
          editing={editingItem}
          onClose={() => { setShowAddItem(false); setEditingItem(null); }}
          onDone={() => { setShowAddItem(false); setEditingItem(null); loadDashboard(); }}
        />
      )}

      {showNewPO && (
        <NewPODialog
          items={items}
          onClose={() => setShowNewPO(false)}
          onDone={() => { setShowNewPO(false); loadOrders(); if (activeTab !== 'orders') setActiveTab('orders'); }}
        />
      )}

      {editingPO && (
        <EditPODialog
          po={editingPO}
          items={items}
          onClose={() => setEditingPO(null)}
          onDone={() => { setEditingPO(null); loadOrders(); }}
        />
      )}

      {rejectPO && (
        <RejectDialog
          po={rejectPO}
          onClose={() => setRejectPO(null)}
          onDone={() => { setRejectPO(null); loadOrders(); }}
        />
      )}

      {receivePO && (
        <ReceiveGoodsDialog
          po={receivePO}
          onClose={() => setReceivePO(null)}
          onDone={() => { setReceivePO(null); loadDashboard(); loadOrders(); }}
        />
      )}
    </div>
  );
}
