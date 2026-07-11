/**
 * Pricing — per-unit rates. Three tabs:
 *   • Default Rates   → bulk-edit each product's rate PER UNIT (₹/MT, ₹/CFT,
 *                       ₹/CBM, ₹/Brass) + GST%.
 *   • Customer Rates  → per-customer overrides, per unit.
 *   • Supplier Rates  → per-supplier/farmer overrides, per unit.
 *
 * Rate columns come from GET /app-settings/rate-units (default MT/CFT/CUM/BRASS).
 * Backend:
 *   GET/PUT /api/v1/products/unit-rates          (default per-unit rates)
 *   PUT     /api/v1/products/default-rates        (GST% mirror)
 *   GET     /api/v1/parties/rates/matrix          (customer cells, now with unit)
 *   POST    /api/v1/parties/{party_id}/rates/bulk (per-unit customer overrides)
 */
import { useEffect, useState, useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Search, Save, IndianRupee, Loader2, Download } from 'lucide-react';
import { downloadCsv } from '@/components/DataTable';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import api from '@/services/api';
import type { Party } from '@/types';

interface UnitRow {
  product_id: string;
  name: string;
  hsn_code: string;
  base_unit: string;
  gst_rate: number;
  rates: Record<string, number>;   // { MT: 500, CFT: 42, … }
}
interface Cell { party_id: string; product_id: string; unit: string | null; rate: number; }

const INR = (v: number) => Number(v ?? 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
type Tab = 'default' | 'customer' | 'supplier';

// ── Default per-unit rate editor ──────────────────────────────────────────────
function DefaultRatesEditor({ unitRows, rateUnits, onSaved }: {
  unitRows: UnitRow[]; rateUnits: string[]; onSaved: () => void;
}) {
  const [rows, setRows] = useState<{ product_id: string; name: string; hsn_code: string; base_unit: string; gst: string; rates: Record<string, string> }[]>([]);
  const [dirty, setDirty] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setRows(unitRows.map(r => ({
      product_id: r.product_id, name: r.name, hsn_code: r.hsn_code, base_unit: (r.base_unit || '').toUpperCase(),
      gst: String(Number(r.gst_rate ?? 0)),
      rates: Object.fromEntries(rateUnits.map(u => [u, r.rates[u] != null ? String(r.rates[u]) : ''])),
    })));
    setDirty(new Set());
  }, [unitRows, rateUnits]);

  const filtered = useMemo(() => {
    const q = search.toLowerCase().trim();
    return q ? rows.filter(r => r.name.toLowerCase().includes(q) || r.hsn_code.toLowerCase().includes(q)) : rows;
  }, [rows, search]);

  function setRate(pid: string, unit: string, val: string) {
    setRows(rs => rs.map(r => r.product_id === pid ? { ...r, rates: { ...r.rates, [unit]: val } } : r));
    setDirty(d => new Set(d).add(`${pid}::${unit}`));
  }
  function setGst(pid: string, val: string) {
    setRows(rs => rs.map(r => r.product_id === pid ? { ...r, gst: val } : r));
    setDirty(d => new Set(d).add(`${pid}::__gst__`));
  }

  async function save() {
    if (dirty.size === 0) return;
    setSaving(true);
    try {
      const unitItems: { product_id: string; unit: string; rate: number | null }[] = [];
      const gstItems: { product_id: string; gst_rate: number }[] = [];
      for (const key of dirty) {
        const [pid, unit] = key.split('::');
        const row = rows.find(r => r.product_id === pid);
        if (!row) continue;
        if (unit === '__gst__') {
          gstItems.push({ product_id: pid, gst_rate: parseFloat(row.gst) || 0 });
        } else {
          const v = (row.rates[unit] ?? '').trim();
          unitItems.push({ product_id: pid, unit, rate: v === '' ? null : parseFloat(v) });
        }
      }
      if (unitItems.length) await api.put('/api/v1/products/unit-rates', { items: unitItems });
      if (gstItems.length) await api.put('/api/v1/products/default-rates', { items: gstItems });
      toast.success('Default rates updated');
      onSaved();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string };
      toast.error(err.response?.data?.detail ?? err.message ?? 'Save failed');
    } finally { setSaving(false); }
  }

  return (
    <Card><CardContent className="p-3 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="relative w-full max-w-xs">
          <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
          <Input className="pl-8 h-8 text-xs" placeholder="Search product / HSN…" value={search} onChange={e => setSearch(e.target.value)} />
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" title="Export CSV"
            onClick={() => downloadCsv(`default-rates-${new Date().toISOString().slice(0, 10)}`,
              [['Product', 'HSN', ...rateUnits, 'GST %'], ...rows.map(r => [r.name, r.hsn_code, ...rateUnits.map(u => r.rates[u] ?? ''), r.gst])])}>
            <Download className="mr-1 h-3 w-3" /> CSV
          </Button>
          <Button size="sm" onClick={save} disabled={dirty.size === 0 || saving}>
            <Save className="mr-1 h-3 w-3" />{saving ? 'Saving…' : `Save${dirty.size ? ` (${dirty.size})` : ''}`}
          </Button>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm min-w-max">
          <thead>
            <tr className="border-b bg-muted/50">
              <th className="text-left p-2 font-medium sticky left-0 bg-muted/50">Product</th>
              <th className="text-left p-2 font-medium">HSN</th>
              {rateUnits.map(u => <th key={u} className="text-right p-2 font-medium">₹ / {u}</th>)}
              <th className="text-right p-2 font-medium">GST %</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr><td colSpan={rateUnits.length + 3} className="p-6 text-center text-muted-foreground text-xs">No products</td></tr>
            ) : filtered.map(r => (
              <tr key={r.product_id} className="border-b hover:bg-muted/20">
                <td className="p-2 sticky left-0 bg-background">{r.name}
                  {r.base_unit && <span className="ml-1 text-[10px] text-muted-foreground">({r.base_unit})</span>}</td>
                <td className="p-2 text-muted-foreground text-xs">{r.hsn_code}</td>
                {rateUnits.map(u => (
                  <td key={u} className={`p-2 text-right ${dirty.has(`${r.product_id}::${u}`) ? 'bg-amber-50/60' : ''}`}>
                    <Input type="number" min="0" step="0.01" placeholder="—"
                      className="h-7 text-xs text-right inline-block w-24"
                      value={r.rates[u] ?? ''} onChange={e => setRate(r.product_id, u, e.target.value)} />
                  </td>
                ))}
                <td className={`p-2 text-right ${dirty.has(`${r.product_id}::__gst__`) ? 'bg-amber-50/60' : ''}`}>
                  <Input type="number" min="0" step="0.01" className="h-7 text-xs text-right inline-block w-16"
                    value={r.gst} onChange={e => setGst(r.product_id, e.target.value)} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </CardContent></Card>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────
export default function PricingMatrixPage() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>('default');
  const [parties, setParties] = useState<Party[]>([]);
  const [unitRows, setUnitRows] = useState<UnitRow[]>([]);
  const [rateUnits, setRateUnits] = useState<string[]>(['MT', 'CFT', 'CUM', 'BRASS']);
  const [cells, setCells] = useState<Cell[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedPartyId, setSelectedPartyId] = useState('');
  const [partySearch, setPartySearch] = useState('');
  // customer overrides: { `${product_id}::${unit}`: string }
  const [ov, setOv] = useState<Record<string, string>>({});
  const [ovDirty, setOvDirty] = useState<Set<string>>(new Set());
  const [saving, setSaving] = useState(false);

  const mode: 'customer' | 'supplier' = tab === 'supplier' ? 'supplier' : 'customer';

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [pa, ur, ma, ru] = await Promise.all([
        api.get<{ items: Party[] } | Party[]>('/api/v1/parties?page_size=500'),
        api.get<{ rows: UnitRow[] }>('/api/v1/products/unit-rates'),
        api.get<{ cells: Cell[] }>('/api/v1/parties/rates/matrix'),
        api.get<string[]>('/api/v1/app-settings/rate-units'),
      ]);
      setParties(Array.isArray(pa.data) ? pa.data : (pa.data as { items: Party[] }).items ?? []);
      setUnitRows(ur.data.rows ?? []);
      setCells(ma.data.cells ?? []);
      if (Array.isArray(ru.data) && ru.data.length) setRateUnits(ru.data.map(u => u.toUpperCase()));
    } finally { setLoading(false); }
  }, []);
  useEffect(() => { loadData(); }, [loadData]);

  // Rebuild override map when a party is selected
  useEffect(() => {
    if (!selectedPartyId) { setOv({}); setOvDirty(new Set()); return; }
    const map: Record<string, string> = {};
    for (const c of cells.filter(x => x.party_id === selectedPartyId)) {
      const u = (c.unit || '').toUpperCase();
      // NULL unit = legacy base-unit override → key it under the product base unit
      const row = unitRows.find(r => r.product_id === c.product_id);
      const unit = u || (row?.base_unit || '').toUpperCase();
      if (unit) map[`${c.product_id}::${unit}`] = String(c.rate);
    }
    setOv(map); setOvDirty(new Set());
  }, [selectedPartyId, cells, unitRows]);

  const partyWord = mode === 'supplier' ? t('party.supplier') : t('party.customer');
  const typedParties = useMemo(() => parties.filter(p =>
    mode === 'supplier' ? (p.party_type === 'supplier' || p.party_type === 'both')
                        : (p.party_type === 'customer' || p.party_type === 'both')), [parties, mode]);
  const filteredParties = useMemo(() => {
    const q = partySearch.toLowerCase().trim();
    return q ? typedParties.filter(p => p.name.toLowerCase().includes(q)) : typedParties;
  }, [typedParties, partySearch]);

  function setOverride(pid: string, unit: string, val: string) {
    setOv(o => ({ ...o, [`${pid}::${unit}`]: val }));
    setOvDirty(d => new Set(d).add(`${pid}::${unit}`));
  }

  async function saveOverrides() {
    if (!selectedPartyId || ovDirty.size === 0) return;
    setSaving(true);
    try {
      const rates = [...ovDirty].map(key => {
        const [pid, unit] = key.split('::');
        const v = (ov[key] ?? '').trim();
        return { product_id: pid, unit, rate: v === '' ? null : parseFloat(v) };
      });
      const res = await api.post<{ saved: number; cleared: number }>(`/api/v1/parties/${selectedPartyId}/rates/bulk`, { rates });
      toast.success(`Saved ${res.data.saved} rates, cleared ${res.data.cleared}`);
      await loadData();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string };
      toast.error(err.response?.data?.detail ?? err.message ?? 'Save failed');
    } finally { setSaving(false); }
  }

  const defaultRateFor = (pid: string, unit: string): number | undefined =>
    unitRows.find(r => r.product_id === pid)?.rates[unit];
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
        <p className="text-muted-foreground">Set product rates per unit (₹/MT, ₹/CFT, ₹/CBM, ₹/Brass) — default + per-party.</p>
      </div>

      <div className="inline-flex gap-1 rounded-lg border p-0.5">
        {TABS.map(tb => (
          <button key={tb.value} type="button"
            onClick={() => { setTab(tb.value); setSelectedPartyId(''); setPartySearch(''); }}
            className={`px-3 py-1.5 rounded text-xs font-medium transition-colors ${tab === tb.value ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'}`}>
            {tb.label}
          </button>
        ))}
      </div>

      {tab === 'default' ? (
        loading ? <div className="py-16 text-center text-muted-foreground"><Loader2 className="inline mr-2 h-5 w-5 animate-spin" />Loading…</div>
          : <DefaultRatesEditor unitRows={unitRows} rateUnits={rateUnits} onSaved={loadData} />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-[280px_1fr] gap-4">
          {/* Party picker */}
          <Card><CardContent className="p-3 space-y-3">
            <div className="space-y-1">
              <Label className="text-xs">Search {partyWord}</Label>
              <div className="relative">
                <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
                <Input className="pl-8 h-8 text-xs" placeholder="Type to filter…" value={partySearch} onChange={e => setPartySearch(e.target.value)} />
              </div>
            </div>
            <div className="max-h-[60vh] overflow-y-auto -mx-1">
              {loading ? <p className="text-xs text-muted-foreground text-center py-6">Loading…</p>
                : filteredParties.length === 0 ? <p className="text-xs text-muted-foreground text-center py-6">No {partyWord.toLowerCase()}s</p>
                : filteredParties.map(p => {
                  const n = cells.filter(c => c.party_id === p.id).length;
                  return (
                    <button key={p.id} type="button" onClick={() => setSelectedPartyId(p.id)}
                      className={`w-full px-2 py-2 mx-1 rounded text-left text-xs transition-colors flex items-center justify-between gap-2 ${selectedPartyId === p.id ? 'bg-primary/10 border border-primary/40 font-semibold' : 'hover:bg-muted'}`}>
                      <span className="truncate">{p.name}</span>
                      {n > 0 && <Badge variant="secondary" className="shrink-0 text-[10px] h-4">{n}</Badge>}
                    </button>
                  );
                })}
            </div>
          </CardContent></Card>

          {/* Customer per-unit override grid */}
          <Card><CardContent className="p-3">
            {!selectedPartyId ? (
              <div className="flex flex-col items-center justify-center py-20 text-muted-foreground">
                <IndianRupee className="h-10 w-10 mb-3 opacity-40" /><p className="text-sm">{t('pricingMatrix.selectParty')}</p>
              </div>
            ) : (
              <>
                <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
                  <div>
                    <h2 className="font-semibold">{selectedParty?.name}</h2>
                    <p className="text-xs text-muted-foreground">
                      Per-unit rates · default shown faint
                      {ovDirty.size > 0 && <span className="ml-2 text-amber-600">· {ovDirty.size} unsaved</span>}
                    </p>
                  </div>
                  <Button size="sm" onClick={saveOverrides} disabled={ovDirty.size === 0 || saving}>
                    <Save className="mr-1 h-3 w-3" />{saving ? 'Saving…' : `Save (${ovDirty.size})`}
                  </Button>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm min-w-max">
                    <thead><tr className="border-b bg-muted/50">
                      <th className="text-left p-2 font-medium sticky left-0 bg-muted/50">Product</th>
                      {rateUnits.map(u => <th key={u} className="text-right p-2 font-medium">₹ / {u}</th>)}
                    </tr></thead>
                    <tbody>
                      {unitRows.map(r => (
                        <tr key={r.product_id} className="border-b hover:bg-muted/20">
                          <td className="p-2 sticky left-0 bg-background">{r.name}</td>
                          {rateUnits.map(u => {
                            const key = `${r.product_id}::${u}`;
                            const def = defaultRateFor(r.product_id, u);
                            return (
                              <td key={u} className={`p-2 text-right ${ovDirty.has(key) ? 'bg-amber-50/60' : ''}`}>
                                <Input type="number" min="0" step="0.01"
                                  className="h-7 text-xs text-right inline-block w-24"
                                  placeholder={def != null ? INR(def) : '—'}
                                  value={ov[key] ?? ''} onChange={e => setOverride(r.product_id, u, e.target.value)} />
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </CardContent></Card>
        </div>
      )}

      <div className="flex items-start gap-2 text-xs text-muted-foreground bg-muted/40 rounded p-3">
        <IndianRupee className="h-4 w-4 shrink-0 mt-0.5" />
        <p>
          At weighment the operator picks the <b>billing unit</b>; the system uses that unit's rate here
          ({partyWord.toLowerCase()} rate → default rate). A blank customer cell falls back to the faint
          default. Weighed (bridge) trucks bill in weight units; volume units need a Volume token.
        </p>
      </div>
    </div>
  );
}
