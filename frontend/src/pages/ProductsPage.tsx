import { useEffect, useState, useCallback } from 'react';
import { Plus, Search, Pencil, Package } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import api from '@/services/api';
import type { Product, ProductCategory } from '@/types';

const UNITS = ['MT', 'KG', 'CFT', 'BRASS', 'CUM', 'PCS', 'NOS'];
const GST_RATES = ['0', '5', '12', '18', '28'];

// ------------------------------------------------------------------ //
// Product form
// ------------------------------------------------------------------ //
interface ProductForm {
  name: string;
  code: string;
  category_id: string;
  hsn_code: string;
  unit: string;
  default_rate: string;
  gst_rate: string;
  description: string;
  is_active: boolean;
}

const emptyForm = (): ProductForm => ({
  name: '', code: '', category_id: '', hsn_code: '',
  unit: 'MT', default_rate: '0', gst_rate: '5',
  description: '', is_active: true,
});

interface ProductDialogProps {
  open: boolean;
  editing: Product | null;
  categories: ProductCategory[];
  onClose: () => void;
  onSaved: (p: Product) => void;
}

function ProductDialog({ open, editing, categories, onClose, onSaved }: ProductDialogProps) {
  const [form, setForm] = useState<ProductForm>(emptyForm());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (open) {
      if (editing) {
        setForm({
          name: editing.name,
          code: editing.code ?? '',
          category_id: editing.category_id ?? '',
          hsn_code: editing.hsn_code ?? '',
          unit: editing.unit,
          default_rate: String(editing.default_rate),
          gst_rate: String(editing.gst_rate),
          description: editing.description ?? '',
          is_active: editing.is_active,
        });
      } else {
        setForm(emptyForm());
      }
      setError('');
    }
  }, [open, editing]);

  const set = (k: keyof ProductForm, v: string | boolean | null) =>
    setForm(f => ({ ...f, [k]: v ?? '' }));

  const handleSave = async () => {
    if (!form.name.trim()) { setError('Product name is required'); return; }
    setSaving(true);
    setError('');
    try {
      const payload = {
        name: form.name.trim(),
        code: form.code.trim() || null,
        category_id: form.category_id || null,
        hsn_code: form.hsn_code.trim(),
        unit: form.unit,
        default_rate: parseFloat(form.default_rate) || 0,
        gst_rate: parseFloat(form.gst_rate) || 0,
        description: form.description.trim() || null,
        is_active: form.is_active,
      };
      let res;
      if (editing) {
        res = await api.put<Product>(`/api/v1/products/${editing.id}`, payload);
      } else {
        res = await api.post<Product>('/api/v1/products', payload);
      }
      onSaved(res.data);
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      setError(err.response?.data?.detail ?? 'Failed to save product');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={o => !o && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{editing ? 'Edit Product' : 'Add Product'}</DialogTitle>
        </DialogHeader>

        <div className="grid grid-cols-2 gap-4 py-2">
          <div className="col-span-2 space-y-1">
            <Label>Product Name *</Label>
            <Input value={form.name} onChange={e => set('name', e.target.value)} placeholder="e.g. Gitti 20mm" />
          </div>

          <div className="space-y-1">
            <Label>Product Code</Label>
            <Input value={form.code} onChange={e => set('code', e.target.value)} placeholder="e.g. GTT20" />
          </div>

          <div className="space-y-1">
            <Label>Category</Label>
            <Select value={form.category_id || undefined} onValueChange={v => set('category_id', v)}>
              <SelectTrigger>
                <span className="truncate text-left flex-1">
                  {form.category_id
                    ? (categories.find(c => c.id === form.category_id)?.name ?? '…')
                    : <span className="text-muted-foreground">Select category</span>}
                </span>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="">— None —</SelectItem>
                {categories.map(c => (
                  <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1">
            <Label>HSN Code</Label>
            <Input value={form.hsn_code} onChange={e => set('hsn_code', e.target.value)} placeholder="e.g. 2517" />
          </div>

          <div className="space-y-1">
            <Label>Unit</Label>
            <Select value={form.unit} onValueChange={v => set('unit', v)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {UNITS.map(u => <SelectItem key={u} value={u}>{u}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1">
            <Label>Default Rate (₹)</Label>
            <Input type="number" value={form.default_rate} onChange={e => set('default_rate', e.target.value)} min="0" step="0.01" />
          </div>

          <div className="space-y-1">
            <Label>GST Rate (%)</Label>
            <Select value={form.gst_rate} onValueChange={v => set('gst_rate', v)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {GST_RATES.map(r => <SelectItem key={r} value={r}>{r}%</SelectItem>)}
              </SelectContent>
            </Select>
          </div>

          <div className="col-span-2 space-y-1">
            <Label>Description</Label>
            <Input value={form.description} onChange={e => set('description', e.target.value)} placeholder="Optional notes" />
          </div>

          {editing && (
            <div className="col-span-2 flex items-center gap-2">
              <input
                type="checkbox"
                id="is_active"
                checked={form.is_active}
                onChange={e => set('is_active', e.target.checked)}
                className="h-4 w-4"
              />
              <Label htmlFor="is_active">Active</Label>
            </div>
          )}
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving ? 'Saving…' : editing ? 'Update' : 'Add Product'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ------------------------------------------------------------------ //
// Products Page
// ------------------------------------------------------------------ //
const PRODUCT_PAGE_SIZE = 50;

export default function ProductsPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [productTotal, setProductTotal] = useState(0);
  const [productPage, setProductPage] = useState(1);
  const [categories, setCategories] = useState<ProductCategory[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<Product | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page: String(productPage), page_size: String(PRODUCT_PAGE_SIZE) });
      if (search) params.set('search', search);
      const [pRes, cRes] = await Promise.all([
        api.get<{ items: Product[]; total: number } | Product[]>(`/api/v1/products?${params}`),
        api.get<ProductCategory[]>('/api/v1/product-categories'),
      ]);
      if (Array.isArray(pRes.data)) {
        setProducts(pRes.data);
        setProductTotal(pRes.data.length);
      } else {
        setProducts(pRes.data.items ?? []);
        setProductTotal(pRes.data.total ?? 0);
      }
      setCategories(Array.isArray(cRes.data) ? cRes.data : []);
    } finally {
      setLoading(false);
    }
  }, [productPage, search]);

  useEffect(() => { setProductPage(1); }, [search]);

  useEffect(() => { load(); }, [load]);

  // search is now sent to the backend; products already filtered server-side
  const filtered = products;

  const catMap = Object.fromEntries(categories.map(c => [c.id, c.name]));

  const openCreate = () => { setEditing(null); setDialogOpen(true); };
  const openEdit = (p: Product) => { setEditing(p); setDialogOpen(true); };

  const handleSaved = (_p: Product) => {
    setDialogOpen(false);
    load();
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Product Catalog</h1>
          <p className="text-muted-foreground">Manage materials, HSN codes, rates and GST</p>
        </div>
        <Button onClick={openCreate}>
          <Plus className="mr-2 h-4 w-4" /> Add Product
        </Button>
      </div>

      {/* Search */}
      <div className="relative max-w-sm">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          className="pl-9"
          placeholder="Search name, code, HSN…"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <Card>
          <CardContent className="pt-4">
            <p className="text-xs text-muted-foreground">Total Products</p>
            <p className="text-2xl font-bold">{productTotal}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <p className="text-xs text-muted-foreground">Active</p>
            <p className="text-2xl font-bold text-green-600">{products.filter(p => p.is_active).length}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <p className="text-xs text-muted-foreground">Categories</p>
            <p className="text-2xl font-bold">{categories.length}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <p className="text-xs text-muted-foreground">Inactive</p>
            <p className="text-2xl font-bold text-muted-foreground">{products.filter(p => !p.is_active).length}</p>
          </CardContent>
        </Card>
      </div>

      {/* Table */}
      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/50">
                  <th className="text-left p-3 font-medium">Product</th>
                  <th className="text-left p-3 font-medium">Code</th>
                  <th className="text-left p-3 font-medium">Category</th>
                  <th className="text-left p-3 font-medium">HSN</th>
                  <th className="text-left p-3 font-medium">Unit</th>
                  <th className="text-right p-3 font-medium">Rate (₹)</th>
                  <th className="text-right p-3 font-medium">GST%</th>
                  <th className="text-center p-3 font-medium">Status</th>
                  <th className="p-3"></th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr><td colSpan={9} className="text-center p-8 text-muted-foreground">Loading…</td></tr>
                ) : filtered.length === 0 ? (
                  <tr>
                    <td colSpan={9}>
                      <div className="flex flex-col items-center justify-center py-16 px-4 text-center">
                        <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-muted">
                          <Package className="h-8 w-8 text-muted-foreground/40" />
                        </div>
                        <h3 className="text-sm font-semibold">No products found</h3>
                        <p className="mt-1 max-w-xs text-xs text-muted-foreground">
                          Try adjusting your search or add a new product.
                        </p>
                      </div>
                    </td>
                  </tr>
                ) : (
                  filtered.map(p => (
                    <tr key={p.id} className="border-b hover:bg-muted/30 transition-colors">
                      <td className="p-3 font-medium">{p.name}</td>
                      <td className="p-3 text-muted-foreground">{p.code ?? '—'}</td>
                      <td className="p-3 text-muted-foreground">{p.category_id ? (catMap[p.category_id] ?? '—') : '—'}</td>
                      <td className="p-3 font-mono text-xs">{p.hsn_code || '—'}</td>
                      <td className="p-3">{p.unit}</td>
                      <td className="p-3 text-right">
                        {p.default_rate.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                      </td>
                      <td className="p-3 text-right">{p.gst_rate}%</td>
                      <td className="p-3 text-center">
                        <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                          p.is_active ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'
                        }`}>
                          {p.is_active ? 'Active' : 'Inactive'}
                        </span>
                      </td>
                      <td className="p-3">
                        <Button variant="ghost" size="icon" onClick={() => openEdit(p)}>
                          <Pencil className="h-4 w-4" />
                        </Button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {productTotal > PRODUCT_PAGE_SIZE && (
            <div className="flex items-center justify-between px-4 py-3 border-t text-sm">
              <span className="text-muted-foreground">
                Showing {(productPage - 1) * PRODUCT_PAGE_SIZE + 1}–{Math.min(productPage * PRODUCT_PAGE_SIZE, productTotal)} of {productTotal}
              </span>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" disabled={productPage <= 1} onClick={() => setProductPage(p => p - 1)}>Prev</Button>
                <span className="flex items-center px-2">{productPage} / {Math.ceil(productTotal / PRODUCT_PAGE_SIZE)}</span>
                <Button variant="outline" size="sm" disabled={productPage * PRODUCT_PAGE_SIZE >= productTotal} onClick={() => setProductPage(p => p + 1)}>Next</Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <ProductDialog
        open={dialogOpen}
        editing={editing}
        categories={categories}
        onClose={() => setDialogOpen(false)}
        onSaved={handleSaved}
      />
    </div>
  );
}
