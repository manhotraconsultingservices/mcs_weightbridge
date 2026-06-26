import { useEffect, useState, useCallback, useMemo } from 'react';
import { Plus, Search, Pencil, Loader2, RefreshCw } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { DataTable, type ColumnDef } from '@/components/DataTable';
import api from '@/services/api';
import { moduleEnabled } from '@/hooks/useAuth';
import type { Product, ProductCategory } from '@/types';

// Bulk density (volume→weight) + raw-material (production input) are crusher-only
// concepts. Hidden for verticals where the production module is off (e.g. maize).
const SHOW_PRODUCTION_FIELDS = moduleEnabled('production');

const UNITS = ['MT', 'QUINTAL', 'KG', 'CFT', 'BRASS', 'CUM', 'PCS', 'NOS'];
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
  bulk_density: string;
  is_raw_material: boolean;
  description: string;
  is_active: boolean;
}

const emptyForm = (): ProductForm => ({
  name: '', code: '', category_id: '', hsn_code: '',
  unit: 'MT', default_rate: '0', gst_rate: '5',
  bulk_density: '',
  is_raw_material: false,
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
  const { t } = useTranslation();
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
          bulk_density: editing.bulk_density != null ? String(editing.bulk_density) : '',
          is_raw_material: !!editing.is_raw_material,
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
    setForm(prev => ({ ...prev, [k]: v ?? '' }));

  const handleSave = async () => {
    if (!form.name.trim()) { setError(t('product.nameRequired')); return; }
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
        bulk_density: form.bulk_density.trim() ? parseFloat(form.bulk_density) : null,
        is_raw_material: form.is_raw_material,
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
      setError(err.response?.data?.detail ?? t('product.failedSave'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={o => !o && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{editing ? t('product.editProduct') : t('product.addProduct')}</DialogTitle>
        </DialogHeader>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 py-2">
          <div className="col-span-2 space-y-1">
            <Label>{t('product.name')} *</Label>
            <Input value={form.name} onChange={e => set('name', e.target.value)} placeholder={t('product.namePlaceholder')} />
          </div>

          <div className="space-y-1">
            <Label>{t('product.productCode')}</Label>
            <Input value={form.code} onChange={e => set('code', e.target.value)} placeholder={t('product.codePlaceholder')} />
          </div>

          <div className="space-y-1">
            <Label>{t('product.category')}</Label>
            <Select value={form.category_id || undefined} onValueChange={v => set('category_id', v)}>
              <SelectTrigger>
                <span className="truncate text-left flex-1">
                  {form.category_id
                    ? (categories.find(c => c.id === form.category_id)?.name ?? '…')
                    : <span className="text-muted-foreground">{t('product.selectCategory')}</span>}
                </span>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="">{t('product.noneCategory')}</SelectItem>
                {categories.map(c => (
                  <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1">
            <Label>{t('product.hsnCode')}</Label>
            <Input value={form.hsn_code} onChange={e => set('hsn_code', e.target.value)} placeholder={t('product.hsnPlaceholder')} />
          </div>

          <div className="space-y-1">
            <Label>{t('product.unit')}</Label>
            <Select value={form.unit} onValueChange={v => set('unit', v)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {UNITS.map(u => <SelectItem key={u} value={u}>{u}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1">
            <Label>{t('product.defaultRateLabel')}</Label>
            <Input type="number" value={form.default_rate} onChange={e => set('default_rate', e.target.value)} min="0" step="0.01" />
          </div>

          <div className="space-y-1">
            <Label>{t('product.gstRateLabel')}</Label>
            <Select value={form.gst_rate} onValueChange={v => set('gst_rate', v)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {GST_RATES.map(r => <SelectItem key={r} value={r}>{r}%</SelectItem>)}
              </SelectContent>
            </Select>
          </div>

          {SHOW_PRODUCTION_FIELDS && (
          <div className="col-span-2 space-y-1">
            <Label>{t('product.bulkDensity')}</Label>
            <Input
              type="number"
              value={form.bulk_density}
              onChange={e => set('bulk_density', e.target.value)}
              min="0"
              step="0.01"
              placeholder={t('product.bulkDensityPlaceholder')}
            />
            <p className="text-xs text-muted-foreground">
              {t('product.bulkDensityHint')}
              <br />
              <span className="text-[10px] text-muted-foreground/80">
                {t('product.bulkDensityTip')}
              </span>
            </p>
          </div>
          )}

          {SHOW_PRODUCTION_FIELDS && (
          <div className="col-span-2 flex items-center gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2">
            <input
              type="checkbox"
              id="is_raw_material"
              checked={form.is_raw_material}
              onChange={e => set('is_raw_material', e.target.checked)}
              className="h-4 w-4"
            />
            <label htmlFor="is_raw_material" className="text-sm font-medium cursor-pointer">
              {t('product.rawMaterialLabel')}
            </label>
            <span className="text-xs text-amber-700 ml-2">
              {t('product.rawMaterialHint')}
            </span>
          </div>
          )}

          <div className="col-span-2 space-y-1">
            <Label>{t('product.description')}</Label>
            <Input value={form.description} onChange={e => set('description', e.target.value)} placeholder={t('product.descriptionPlaceholder')} />
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
              <Label htmlFor="is_active">{t('product.active')}</Label>
            </div>
          )}
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>{t('common.cancel')}</Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving ? t('product.saving') : editing ? t('common.update') : t('product.addProduct')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ------------------------------------------------------------------ //
// Products Page
// ------------------------------------------------------------------ //
// DataTable does client-side sort/filter, so we fetch a large page in one go.
// API caps page_size at 200; if a tenant exceeds 200 active products we'd need
// real pagination — for stone-crusher operations that's vanishingly rare.
const PRODUCT_FETCH_SIZE = 200;

export default function ProductsPage() {
  const { t } = useTranslation();
  const [products, setProducts] = useState<Product[]>([]);
  const [productTotal, setProductTotal] = useState(0);
  const [categories, setCategories] = useState<ProductCategory[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [search, setSearch] = useState('');
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<Product | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError('');
    try {
      const params = new URLSearchParams({ page: '1', page_size: String(PRODUCT_FETCH_SIZE) });
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
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string };
      setLoadError(err.response?.data?.detail ?? err.message ?? 'Failed to load products');
    } finally {
      setLoading(false);
    }
  }, [search]);

  useEffect(() => { load(); }, [load]);

  // Server-side search still works for legacy reasons; DataTable's per-column
  // filters operate on the returned list client-side.
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
          <h1 className="text-3xl font-bold tracking-tight">{t('product.catalog')}</h1>
          <p className="text-muted-foreground">{t('product.subtitle')}</p>
        </div>
        <Button onClick={openCreate}>
          <Plus className="mr-2 h-4 w-4" /> {t('product.addProduct')}
        </Button>
      </div>

      {/* API error banner */}
      {loadError && (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 px-4 py-2 text-sm text-destructive">
          Failed to load products: {loadError}
        </div>
      )}

      {/* Search */}
      <div className="relative max-w-sm">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          className="pl-9"
          placeholder={t('product.searchPlaceholder')}
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <Card>
          <CardContent className="pt-4">
            <p className="text-xs text-muted-foreground">{t('product.totalProducts')}</p>
            <p className="text-2xl font-bold">{productTotal}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <p className="text-xs text-muted-foreground">{t('product.activeProducts')}</p>
            <p className="text-2xl font-bold text-green-600">{products.filter(p => p.is_active).length}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <p className="text-xs text-muted-foreground">{t('product.categoriesCount')}</p>
            <p className="text-2xl font-bold">{categories.length}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <p className="text-xs text-muted-foreground">{t('product.inactiveProducts')}</p>
            <p className="text-2xl font-bold text-muted-foreground">{products.filter(p => !p.is_active).length}</p>
          </CardContent>
        </Card>
      </div>

      {/* Table — DataTable: sortable, filterable, column show/hide, CSV export */}
      <ProductsTable products={filtered} catMap={catMap} loading={loading} onEdit={openEdit} />

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

// ------------------------------------------------------------------ //
// Products DataTable
// ------------------------------------------------------------------ //
function ProductsTable({
  products, catMap, loading, onEdit,
}: {
  products: Product[];
  catMap: Record<string, string>;
  loading: boolean;
  onEdit: (p: Product) => void;
}) {
  const { t } = useTranslation();
  const [syncingId, setSyncingId] = useState<string | null>(null);
  const [syncMsg, setSyncMsg] = useState<{ id: string; text: string; ok: boolean } | null>(null);
  const [tallyEnabled, setTallyEnabled] = useState(false);

  useEffect(() => {
    api.get<{ is_enabled?: boolean }>('/api/v1/tally/config')
      .then(({ data }) => setTallyEnabled(!!data?.is_enabled))
      .catch(() => setTallyEnabled(false));
  }, []);

  async function syncToTally(p: Product) {
    setSyncingId(p.id); setSyncMsg(null);
    try {
      const { data } = await api.post<{ success: boolean; message?: string }>(
        `/api/v1/tally/sync/product/${p.id}`);
      const text = data?.message || 'Sent to Tally';
      setSyncMsg({ id: p.id, text, ok: data?.success !== false });
    } catch (e: any) {
      const detail = e?.response?.data?.detail;
      setSyncMsg({ id: p.id, text: typeof detail === 'string' ? detail : 'Tally sync failed', ok: false });
    } finally {
      setSyncingId(null);
      setTimeout(() => setSyncMsg(m => (m && m.id === p.id ? null : m)), 6000);
    }
  }

  const columns = useMemo<ColumnDef<Product>[]>(() => ([
    { key: 'name', label: t('product.colProduct'), accessor: p => p.name, className: 'font-medium' },
    { key: 'code', label: t('product.colCode'), accessor: p => p.code ?? '', className: 'text-muted-foreground' },
    {
      key: 'category', label: t('product.category'), type: 'enum',
      enumOptions: Object.values(catMap),
      accessor: p => (p.category_id ? (catMap[p.category_id] ?? '') : ''),
      className: 'text-muted-foreground',
    },
    { key: 'hsn_code', label: t('product.colHsn'), accessor: p => p.hsn_code, className: 'font-mono text-xs' },
    { key: 'unit', label: t('product.unit'), type: 'enum', enumOptions: ['MT','QUINTAL','KG','CFT','BRASS','CUM','PCS','NOS'], accessor: p => p.unit },
    {
      key: 'default_rate', label: t('product.colRate'), type: 'number', align: 'right',
      accessor: p => p.default_rate,
      format: v => Number(v).toLocaleString('en-IN', { minimumFractionDigits: 2 }),
    },
    {
      key: 'gst_rate', label: t('product.colGst'), type: 'number', align: 'right',
      accessor: p => p.gst_rate, format: v => `${v}%`,
    },
    {
      key: 'bulk_density', label: t('product.colDensity'), type: 'number', align: 'right',
      accessor: p => p.bulk_density,
      format: v => v == null ? '—' : Number(v).toFixed(2),
      className: 'text-muted-foreground',
    },
    {
      key: 'is_raw_material', label: t('product.colRaw'), type: 'enum', align: 'center',
      enumOptions: [t('product.rawBadge'), t('product.finishedLabel')],
      accessor: p => p.is_raw_material ? t('product.rawBadge') : t('product.finishedLabel'),
      format: v => v === t('product.rawBadge')
        ? <span className="inline-block px-2 py-0.5 rounded text-[10px] font-bold bg-amber-100 text-amber-700 border border-amber-300">{t('product.rawBadge')}</span>
        : <span className="text-xs text-muted-foreground">{t('product.finishedLabel')}</span>,
      defaultVisible: false,
    },
    {
      key: 'status', label: t('common.status'), type: 'enum', align: 'center',
      enumOptions: [t('product.statusActive'), t('product.statusInactive')],
      accessor: p => p.is_active ? t('product.statusActive') : t('product.statusInactive'),
      format: v => v === t('product.statusActive')
        ? <span className="inline-block px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-700">{t('product.statusActive')}</span>
        : <span className="inline-block px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-500">{t('product.statusInactive')}</span>,
    },
    { key: 'description', label: t('product.description'), defaultVisible: false, accessor: p => p.description ?? '' },
  ] as ColumnDef<Product>[]).filter(c => SHOW_PRODUCTION_FIELDS || (c.key !== 'bulk_density' && c.key !== 'is_raw_material')), [catMap, t]);

  return (
    <DataTable<Product>
      id="products.main"
      loading={loading}
      data={products}
      columns={columns}
      rowKey={p => p.id}
      exportFilename="products"
      defaultSort={{ key: 'name', direction: 'asc' }}
      emptyMessage={t('product.noProductsFound')}
      rowActions={p => (
        <div className="flex items-center gap-1 justify-end">
          {syncMsg?.id === p.id && (
            <span className={`text-xs mr-1 whitespace-nowrap ${syncMsg.ok ? 'text-emerald-600' : 'text-red-600'}`}>
              {syncMsg.text}
            </span>
          )}
          <Button
            variant="ghost" size="icon"
            onClick={() => syncToTally(p)}
            disabled={syncingId === p.id || !tallyEnabled}
            title={tallyEnabled ? 'Sync this item to Tally' : 'Enable Tally Integration in Settings → Tally to sync'}
          >
            {syncingId === p.id
              ? <Loader2 className="h-4 w-4 animate-spin" />
              : <RefreshCw className={`h-4 w-4 ${tallyEnabled ? 'text-emerald-600' : 'text-muted-foreground'}`} />}
          </Button>
          <Button variant="ghost" size="icon" onClick={() => onEdit(p)} title={t('product.editProductTitle')}>
            <Pencil className="h-4 w-4" />
          </Button>
        </div>
      )}
    />
  );
}
