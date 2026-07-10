/**
 * Pricing — three tabs:
 *   • Default Rates   → bulk-edit products.default_rate (+ GST%) for ALL products
 *                       at once (no more editing items one by one).
 *   • Customer Rates  → per-customer overrides (party_rates)
 *   • Supplier Rates  → per-supplier/farmer overrides (party_rates)
 *
 * Backend:
 *   PUT  /api/v1/products/default-rates            → bulk set default_rate/gst_rate
 *   GET  /api/v1/parties/rates/matrix              → all active (party, product, rate) cells
 *   POST /api/v1/parties/{party_id}/rates/bulk     → bulk save for one party
 */
import { useEffect, useState, useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Search, Save, IndianRupee, Copy, AlertCircle, RotateCcw, Download, Wand2 } from 'lucide-react';
import { downloadCsv } from '@/components/DataTable';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import api from '@/services/api';
import type { Party, Product } from '@/types';

interface MatrixCell {
  party_id: string;
  product_id: string;
  rate: number;
  effective_from: string;
}

// One row in the editable party grid for the currently selected party
interface Row {
  product_id: string;
  product_name: string;
  default_rate: number;
  override: string;       // empty = no override (use default), else parsed as number
  dirty: boolean;
}

const INR = (v: number) =>
  Number(v ?? 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

type Tab = 'default' | 'customer' | 'supplier';

// ── Default-rates bulk editor ────────────────────────────────────────────────
interface DefRow {
  product_id: string;
  name: string;
  unit: string;
  hsn_code: string;
  rate: string;   // default_rate as string (editable)
  gst: string;    // gst_rate as string (editable)
  dirty: boolean;
}

function DefaultRatesEditor({ products, onSaved }: { products: Product[]; onSaved: () => void }) {
  const [rows, setRows] = useState<DefRow[]>([]);
  const [search, setSearch] = useState('');
  const [saving, setSaving] = useState(false);
  const [fillRate, setFillRate] = useState('');

  useEffect(() => {
    setRows(products.map(p => ({
      product_id: p.id,
      name: p.name,
      unit: p.unit,
      hsn_code: p.hsn_code,
      rate: String(Number(p.default_rate ?? 0)),
      gst: String(Number(p.gst_rate ?? 0)),
      dirty: false,
    })));
  }, [products]);

  const filtered = useMemo(() => {
    const q = search.toLowerCase().trim();
    if (!q) return rows;
    return rows.filter(r => r.name.toLowerCase().includes(q) || r.hsn_code.toLowerCase().includes(q));
  }, [rows, search]);

  const dirtyCount = rows.filter(r => r.dirty).length;

  function setField(id: string, key: 'rate' | 'gst', value: string) {
    setRows(rs => rs.map(r => r.product_id === id ? { ...r, [key]: value, dirty: true } : r));
  }

  // "Set all shown to ₹X" — fills the default_rate of every currently-filtered row.
  function applyToShown() {
    const v = fillRate.trim();
    if (v === '' || !Number.isFinite(parseFloat(v)) || parseFloat(v) < 0) {
      toast.error('Enter a valid rate to apply');
      return;
    }
    const shown = new Set(filtered.map(r => r.product_id));
    setRows(rs => rs.map(r => shown.has(r.product_id) ? { ...r, rate: v, dirty: true } : r));
    toast.info(`Set ${shown.size} product${shown.size !== 1 ? 's' : ''} to ₹${v} — review and Save`);
  }

  async function handleSave() {
    if (dirtyCount === 0) return;
    setSaving(true);
    try {
      const items = rows.filter(r => r.dirty).map(r => {
        const rate = parseFloat(r.rate);
        const gst = parseFloat(r.gst);
        if (!Number.isFinite(rate) || rate < 0) throw new Error(`Invalid rate for ${r.name}`);
        if (!Number.isFinite(gst) || gst < 0) throw new Error(`Invalid GST% for ${r.name}`);
        return { product_id: r.product_id, default_rate: rate, gst_rate: gst };
      });
      const res = await api.put<{ updated: number }>('/api/v1/products/default-rates', { items });
      toast.success(`Updated default rates for ${res.data.updated} product${res.data.updated !== 1 ? 's' : ''}`);
      onSaved();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string };
      toast.error(err.response?.data?.detail ?? err.message ?? 'Save failed');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <CardContent className="p-3 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="relative w-full max-w-xs">
            <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
            <Input className="pl-8 h-8 text-xs" placeholder="Search product / HSN…"
              value={search} onChange={e => setSearch(e.target.value)} />
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            {/* Set-all helper */}
            <div className="flex items-center gap-1">
              <Input type="number" min="0" step="0.01" placeholder="₹ rate"
                className="h-8 w-24 text-xs text-right" value={fillRate}
                onChange={e => setFillRate(e.target.value)} />
              <Button variant="outline" size="sm" onClick={applyToShown} title="Set every shown product to this rate">
                <Wand2 className="mr-1 h-3 w-3" /> Set all shown
              </Button>
            </div>
            <Button variant="outline" size="sm" title="Export as CSV"
              onClick={() => downloadCsv(`default-rates-${new Date().toISOString().slice(0, 10)}`,
                [['Product', 'HSN', 'Unit', 'Default Rate', 'GST %'],
                 ...rows.map(r => [r.name, r.hsn_code, r.unit, r.rate, r.gst])])}>
              <Download className="mr-1 h-3 w-3" /> CSV
            </Button>
            <Button size="sm" onClick={handleSave} disabled={dirtyCount === 0 || saving}>
              <Save className="mr-1 h-3 w-3" />
              {saving ? 'Saving…' : `Save${dirtyCount ? ` (${dirtyCount})` : ''}`}
            </Button>
          </div>
        </div>
        {dirtyCount > 0 && (
          <p className="text-xs text-amber-600">{dirtyCount} unsaved change{dirtyCount !== 1 ? 's' : ''}</p>
        )}

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/50">
                <th className="text-left p-2 font-medium">Product</th>
                <th className="text-left p-2 font-medium">HSN</th>
                <th className="text-center p-2 font-medium">Unit</th>
                <th className="text-right p-2 font-medium">Default Rate (₹)</th>
                <th className="text-right p-2 font-medium">GST %</th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr><td colSpan={5} className="p-6 text-center text-muted-foreground text-xs">No products</td></tr>
              ) : filtered.map(r => (
                <tr key={r.product_id} className={`border-b hover:bg-muted/20 ${r.dirty ? 'bg-amber-50/60' : ''}`}>
                  <td className="p-2">{r.name}</td>
                  <td className="p-2 text-muted-foreground text-xs">{r.hsn_code}</td>
                  <td className="p-2 text-center text-xs">{r.unit}</td>
                  <td className="p-2 text-right">
                    <Input type="number" min="0" step="0.01"
                      className="h-7 text-xs text-right inline-block w-28"
                      value={r.rate} onChange={e => setField(r.product_id, 'rate', e.target.value)} />
                  </td>
                  <td className="p-2 text-right">
                    <Input type="number" min="0" step="0.01"
                      className="h-7 text-xs text-right inline-block w-20"
                      value={r.gst} onChange={e => setField(r.product_id, 'gst', e.target.value)} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────
export default function PricingMatrixPage() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>('default');
  const [parties, setParties] = useState<Party[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [cells, setCells] = useState<MatrixCell[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedPartyId, setSelectedPartyId] = useState<string>('');
  const [rows, setRows] = useState<Row[]>([]);
  const [saving, setSaving] = useState(false);
  const [partySearch, setPartySearch] = useState('');
  const [copyFromOpen, setCopyFromOpen] = useState(false);
  const [copyFromParty, setCopyFromParty] = useState('');

  // Party rate mode is derived from the active tab (customer vs supplier).
  const mode: 'customer' | 'supplier' = tab === 'supplier' ? 'supplier' : 'customer';

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [pa, pr, ma] = await Promise.all([
        api.get<{ items: Party[] } | Party[]>('/api/v1/parties?page_size=500'),
        api.get<{ items: Product[] } | Product[]>('/api/v1/products?page_size=200'),
        api.get<{ cells: MatrixCell[] }>('/api/v1/parties/rates/matrix'),
      ]);
      const partyList = Array.isArray(pa.data) ? pa.data : (pa.data as { items: Party[] }).items ?? [];
      const prodList = Array.isArray(pr.data) ? pr.data : (pr.data as { items: Product[] }).items ?? [];
      setParties(partyList);
      setProducts(prodList.filter(p => p.is_active));
      setCells(ma.data.cells ?? []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  useEffect(() => {
    if (!selectedPartyId) { setRows([]); return; }
    const partyCells = cells.filter(c => c.party_id === selectedPartyId);
    setRows(products.map(p => {
      const c = partyCells.find(x => x.product_id === p.id);
      return {
        product_id: p.id,
        product_name: p.name,
        default_rate: Number(p.default_rate),
        override: c ? String(c.rate) : '',
        dirty: false,
      };
    }));
  }, [selectedPartyId, products, cells]);

  const partyWord = mode === 'supplier' ? t('party.supplier') : t('party.customer');

  const typedParties = useMemo(
    () => parties.filter(p =>
      mode === 'supplier'
        ? (p.party_type === 'supplier' || p.party_type === 'both')
        : (p.party_type === 'customer' || p.party_type === 'both')),
    [parties, mode],
  );

  const filteredParties = useMemo(() => {
    const q = partySearch.toLowerCase().trim();
    if (!q) return typedParties;
    return typedParties.filter(p => p.name.toLowerCase().includes(q));
  }, [typedParties, partySearch]);

  const overrideCount = useMemo(() => {
    if (!selectedPartyId) return 0;
    return cells.filter(c => c.party_id === selectedPartyId).length;
  }, [cells, selectedPartyId]);

  const dirtyCount = rows.filter(r => r.dirty).length;

  function setRowOverride(productId: string, value: string) {
    setRows(rs => rs.map(r => r.product_id === productId ? { ...r, override: value, dirty: true } : r));
  }

  async function handleSave() {
    if (!selectedPartyId || dirtyCount === 0) return;
    setSaving(true);
    try {
      const payload = {
        rates: rows.filter(r => r.dirty).map(r => {
          const trimmed = r.override.trim();
          if (trimmed === '') return { product_id: r.product_id, rate: null };
          const num = parseFloat(trimmed);
          if (!Number.isFinite(num) || num < 0) throw new Error(`Invalid rate for ${r.product_name}: "${trimmed}"`);
          return { product_id: r.product_id, rate: num };
        }),
      };
      const res = await api.post<{ saved: number; cleared: number }>(
        `/api/v1/parties/${selectedPartyId}/rates/bulk`, payload,
      );
      toast.success(`Saved ${res.data.saved} rates, cleared ${res.data.cleared} overrides`);
      await loadData();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string };
      toast.error(err.response?.data?.detail ?? err.message ?? 'Save failed');
    } finally {
      setSaving(false);
    }
  }

  async function handleCopyFrom() {
    if (!copyFromParty || !selectedPartyId || copyFromParty === selectedPartyId) { setCopyFromOpen(false); return; }
    const sourceCells = cells.filter(c => c.party_id === copyFromParty);
    setRows(rs => rs.map(r => {
      const c = sourceCells.find(x => x.product_id === r.product_id);
      return c ? { ...r, override: String(c.rate), dirty: true } : r;
    }));
    setCopyFromOpen(false);
    setCopyFromParty('');
    toast.info(`Copied ${sourceCells.length} rates — review and click Save to apply`);
  }

  function handleResetAll() {
    if (!confirm(`Clear all ${partyWord.toLowerCase()}-specific rates for this party? They will use product default rates.`)) return;
    setRows(rs => rs.map(r => ({ ...r, override: '', dirty: true })));
  }

  function switchTab(next: Tab) {
    setTab(next);
    setSelectedPartyId('');
    setCopyFromOpen(false);
    setCopyFromParty('');
    setPartySearch('');
  }

  const selectedParty = parties.find(p => p.id === selectedPartyId);

  const TABS: { value: Tab; label: string }[] = [
    { value: 'default', label: 'Default Rates' },
    { value: 'customer', label: `${t('party.customer')} Rates` },
    { value: 'supplier', label: `${t('party.supplier')} Rates` },
  ];

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Pricing</h1>
        <p className="text-muted-foreground">Set product default rates in bulk, or per-party overrides.</p>
      </div>

      {/* Top tabs */}
      <div className="inline-flex gap-1 rounded-lg border p-0.5">
        {TABS.map(tb => (
          <button
            key={tb.value}
            type="button"
            onClick={() => switchTab(tb.value)}
            className={`px-3 py-1.5 rounded text-xs font-medium transition-colors ${
              tab === tb.value ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'
            }`}
          >
            {tb.label}
          </button>
        ))}
      </div>

      {tab === 'default' ? (
        <>
          <DefaultRatesEditor products={products} onSaved={loadData} />
          <div className="flex items-start gap-2 text-xs text-muted-foreground bg-muted/40 rounded p-3">
            <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
            <p>
              These are the product <b>default rates</b> used on invoices/tokens when no customer-specific
              rate is set. Edit many at once here instead of one product at a time. Use <b>Set all shown</b>
              to apply one rate to every product currently filtered.
            </p>
          </div>
        </>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-[300px_1fr] gap-4">
          {/* Party picker */}
          <Card>
            <CardContent className="p-3 space-y-3">
              <div className="space-y-1">
                <Label className="text-xs">Search {partyWord}</Label>
                <div className="relative">
                  <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
                  <Input className="pl-8 h-8 text-xs" placeholder="Type to filter…"
                    value={partySearch} onChange={e => setPartySearch(e.target.value)} />
                </div>
              </div>
              <div className="max-h-[60vh] overflow-y-auto -mx-1">
                {loading ? (
                  <p className="text-xs text-muted-foreground text-center py-6">Loading…</p>
                ) : filteredParties.length === 0 ? (
                  <p className="text-xs text-muted-foreground text-center py-6">No {partyWord.toLowerCase()}s</p>
                ) : (
                  filteredParties.map(p => {
                    const cellCount = cells.filter(c => c.party_id === p.id).length;
                    return (
                      <button
                        key={p.id}
                        type="button"
                        onClick={() => setSelectedPartyId(p.id)}
                        className={`w-full px-2 py-2 mx-1 rounded text-left text-xs transition-colors flex items-center justify-between gap-2 ${
                          selectedPartyId === p.id ? 'bg-primary/10 border border-primary/40 font-semibold' : 'hover:bg-muted'
                        }`}
                      >
                        <span className="truncate">{p.name}</span>
                        {cellCount > 0 && <Badge variant="secondary" className="shrink-0 text-[10px] h-4">{cellCount}</Badge>}
                      </button>
                    );
                  })
                )}
              </div>
            </CardContent>
          </Card>

          {/* Rate grid */}
          <Card>
            <CardContent className="p-3">
              {!selectedPartyId ? (
                <div className="flex flex-col items-center justify-center py-20 text-muted-foreground">
                  <IndianRupee className="h-10 w-10 mb-3 opacity-40" />
                  <p className="text-sm">{t('pricingMatrix.selectParty')}</p>
                </div>
              ) : (
                <>
                  <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
                    <div>
                      <h2 className="font-semibold">{selectedParty?.name}</h2>
                      <p className="text-xs text-muted-foreground">
                        {overrideCount} custom rate{overrideCount !== 1 ? 's' : ''} set
                        {dirtyCount > 0 && <span className="ml-2 text-amber-600">· {dirtyCount} unsaved change{dirtyCount !== 1 ? 's' : ''}</span>}
                      </p>
                    </div>
                    <div className="flex gap-2 items-center flex-wrap">
                      <Button variant="outline" size="sm" onClick={() => setCopyFromOpen(o => !o)} disabled={typedParties.length < 2}>
                        <Copy className="mr-1 h-3 w-3" /> {t('pricingMatrix.copyFrom')}
                      </Button>
                      {copyFromOpen && (
                        <div className="flex gap-1">
                          <Select value={copyFromParty || undefined} onValueChange={v => setCopyFromParty(v ?? '')}>
                            <SelectTrigger className="h-8 text-xs w-48">
                              <SelectValue placeholder={`Source ${partyWord.toLowerCase()}`} />
                            </SelectTrigger>
                            <SelectContent>
                              {typedParties.filter(p => p.id !== selectedPartyId).map(p => (
                                <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                          <Button size="sm" onClick={handleCopyFrom} disabled={!copyFromParty}>Copy</Button>
                        </div>
                      )}
                      <Button variant="outline" size="sm" onClick={handleResetAll} disabled={overrideCount === 0 && dirtyCount === 0}>
                        <RotateCcw className="mr-1 h-3 w-3" /> {t('pricingMatrix.resetAll')}
                      </Button>
                      <Button size="sm" onClick={handleSave} disabled={dirtyCount === 0 || saving}>
                        <Save className="mr-1 h-3 w-3" />
                        {saving ? t('pricingMatrix.saving') : `${t('pricingMatrix.saveRates')} (${dirtyCount})`}
                      </Button>
                    </div>
                  </div>

                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b bg-muted/50">
                          <th className="text-left p-2 font-medium">{t('pricingMatrix.colProduct')}</th>
                          <th className="text-right p-2 font-medium">{t('pricingMatrix.colDefaultRate')} (₹)</th>
                          <th className="text-right p-2 font-medium">{t('pricingMatrix.colCustomRate')} (₹)</th>
                          <th className="text-center p-2 font-medium">{t('pricingMatrix.colUnit')}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map(r => {
                          const hasOverride = r.override.trim() !== '';
                          return (
                            <tr key={r.product_id} className={`border-b hover:bg-muted/20 ${r.dirty ? 'bg-amber-50/60' : ''}`}>
                              <td className="p-2">{r.product_name}</td>
                              <td className="p-2 text-right text-muted-foreground">{INR(r.default_rate)}</td>
                              <td className="p-2 text-right">
                                <Input type="number" className="h-7 text-xs text-right inline-block w-28"
                                  value={r.override} onChange={e => setRowOverride(r.product_id, e.target.value)}
                                  placeholder="—" min="0" step="0.01" />
                              </td>
                              <td className="p-2 text-center">
                                {hasOverride
                                  ? <Badge className="bg-emerald-100 text-emerald-700 hover:bg-emerald-100">Custom</Badge>
                                  : <Badge variant="secondary">Default</Badge>}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
