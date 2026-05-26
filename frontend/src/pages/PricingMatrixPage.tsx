/**
 * Customer-specific Pricing Matrix.
 *
 * Most businesses negotiate per-customer rates. This page lets admin/accountant
 * pick a party and bulk-set rates for every product. Empty rate cells fall
 * back to the product's default_rate at invoice time.
 *
 * Backend:
 *   GET  /api/v1/parties/rates/matrix          → all active (party, product, rate) cells
 *   POST /api/v1/parties/{party_id}/rates/bulk → bulk save for one party
 *   DELETE /api/v1/parties/{party_id}/rates/{product_id} → clear one cell
 */
import { useEffect, useState, useCallback, useMemo } from 'react';
import { Search, Save, IndianRupee, Copy, AlertCircle, RotateCcw } from 'lucide-react';
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

// One row in the editable grid for the currently selected party
interface Row {
  product_id: string;
  product_name: string;
  default_rate: number;
  override: string;       // empty = no override (use default), else parsed as number
  dirty: boolean;         // user has changed this cell since load
}

const INR = (v: number) =>
  v.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export default function PricingMatrixPage() {
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

  // Load parties, products, and current matrix in parallel
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
      // Customers only — pricing matrix is irrelevant for suppliers
      setParties(partyList.filter(p => p.party_type === 'customer' || p.party_type === 'both'));
      setProducts(prodList.filter(p => p.is_active));
      setCells(ma.data.cells ?? []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  // Rebuild the editable rows whenever party or matrix changes
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

  const filteredParties = useMemo(() => {
    const q = partySearch.toLowerCase().trim();
    if (!q) return parties;
    return parties.filter(p => p.name.toLowerCase().includes(q));
  }, [parties, partySearch]);

  const overrideCount = useMemo(() => {
    if (!selectedPartyId) return 0;
    return cells.filter(c => c.party_id === selectedPartyId).length;
  }, [cells, selectedPartyId]);

  const dirtyCount = rows.filter(r => r.dirty).length;

  function setRowOverride(productId: string, value: string) {
    setRows(rs => rs.map(r =>
      r.product_id === productId ? { ...r, override: value, dirty: true } : r
    ));
  }

  async function handleSave() {
    if (!selectedPartyId || dirtyCount === 0) return;
    setSaving(true);
    try {
      // Build payload: dirty rows only. Empty string → null (clear); valid number → set rate.
      const payload = {
        rates: rows.filter(r => r.dirty).map(r => {
          const trimmed = r.override.trim();
          if (trimmed === '') return { product_id: r.product_id, rate: null };
          const num = parseFloat(trimmed);
          if (!Number.isFinite(num) || num < 0) {
            throw new Error(`Invalid rate for ${r.product_name}: "${trimmed}"`);
          }
          return { product_id: r.product_id, rate: num };
        }),
      };
      const res = await api.post<{ saved: number; cleared: number }>(
        `/api/v1/parties/${selectedPartyId}/rates/bulk`,
        payload,
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
    if (!copyFromParty || !selectedPartyId || copyFromParty === selectedPartyId) {
      setCopyFromOpen(false);
      return;
    }
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
    if (!confirm('Clear all customer-specific rates for this party? They will use product default rates.')) return;
    setRows(rs => rs.map(r => ({ ...r, override: '', dirty: true })));
  }

  const selectedParty = parties.find(p => p.id === selectedPartyId);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Customer Pricing Matrix</h1>
          <p className="text-muted-foreground">
            Set negotiated rates per customer per product. Empty cells fall back to product default rates.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-[300px_1fr] gap-4">
        {/* Party picker */}
        <Card>
          <CardContent className="p-3 space-y-3">
            <div className="space-y-1">
              <Label className="text-xs">Search Customer</Label>
              <div className="relative">
                <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
                <Input
                  className="pl-8 h-8 text-xs"
                  placeholder="Type to filter…"
                  value={partySearch}
                  onChange={e => setPartySearch(e.target.value)}
                />
              </div>
            </div>
            <div className="max-h-[60vh] overflow-y-auto -mx-1">
              {loading ? (
                <p className="text-xs text-muted-foreground text-center py-6">Loading…</p>
              ) : filteredParties.length === 0 ? (
                <p className="text-xs text-muted-foreground text-center py-6">No customers</p>
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
                      {cellCount > 0 && (
                        <Badge variant="secondary" className="shrink-0 text-[10px] h-4">{cellCount}</Badge>
                      )}
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
                <p className="text-sm">Pick a customer from the left to edit their rates</p>
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
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setCopyFromOpen(o => !o)}
                      disabled={parties.length < 2}
                    >
                      <Copy className="mr-1 h-3 w-3" /> Copy from…
                    </Button>
                    {copyFromOpen && (
                      <div className="flex gap-1">
                        <Select value={copyFromParty || undefined} onValueChange={v => setCopyFromParty(v ?? '')}>
                          <SelectTrigger className="h-8 text-xs w-48">
                            <SelectValue placeholder="Source customer" />
                          </SelectTrigger>
                          <SelectContent>
                            {parties.filter(p => p.id !== selectedPartyId).map(p => (
                              <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        <Button size="sm" onClick={handleCopyFrom} disabled={!copyFromParty}>Copy</Button>
                      </div>
                    )}
                    <Button variant="outline" size="sm" onClick={handleResetAll} disabled={overrideCount === 0 && dirtyCount === 0}>
                      <RotateCcw className="mr-1 h-3 w-3" /> Reset all
                    </Button>
                    <Button size="sm" onClick={handleSave} disabled={dirtyCount === 0 || saving}>
                      <Save className="mr-1 h-3 w-3" />
                      {saving ? 'Saving…' : `Save (${dirtyCount})`}
                    </Button>
                  </div>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b bg-muted/50">
                        <th className="text-left p-2 font-medium">Product</th>
                        <th className="text-right p-2 font-medium">Default Rate (₹)</th>
                        <th className="text-right p-2 font-medium">Customer Rate (₹)</th>
                        <th className="text-center p-2 font-medium">Source</th>
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
                              <Input
                                type="number"
                                className="h-7 text-xs text-right inline-block w-28"
                                value={r.override}
                                onChange={e => setRowOverride(r.product_id, e.target.value)}
                                placeholder="—"
                                min="0"
                                step="0.01"
                              />
                            </td>
                            <td className="p-2 text-center">
                              {hasOverride ? (
                                <Badge className="bg-emerald-100 text-emerald-700 hover:bg-emerald-100">Custom</Badge>
                              ) : (
                                <Badge variant="secondary">Default</Badge>
                              )}
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

      {/* Help footer */}
      <div className="flex items-start gap-2 text-xs text-muted-foreground bg-muted/40 rounded p-3">
        <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
        <div>
          <p className="font-medium">How rates are applied at invoice time</p>
          <p>
            Customer-specific rate → product default rate → ₹0. Token auto-invoices and the New Invoice
            dialog both honour customer rates as long as the rate field is left at zero (the server fills it in).
            Operators can still type a one-off rate to override either default.
          </p>
        </div>
      </div>
    </div>
  );
}
