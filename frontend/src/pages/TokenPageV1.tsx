/**
 * TokenPageV1 — Operational layout with 3-section split
 *
 * LEFT  30%  : New Token Form + Scale Status
 * RIGHT-TOP  35% (50% of 70%): Live camera feeds (front + top)
 * RIGHT-BOT  35% (50% of 70%): Active token list (OPEN / FIRST_WEIGHT / LOADING / SECOND_WEIGHT)
 */
import { useEffect, useState, useCallback, useRef } from 'react';
import {
  Search, Scale, CheckCircle2, XCircle, Loader2,
  Truck, Package, User, Wifi, WifiOff, ArrowRight,
  AlertCircle, RefreshCw, Camera, Download, Plus,
} from 'lucide-react';
import { PrintButton } from '@/components/PrintButton';
import { downloadCsv } from '@/components/DataTable';
import ResizableSplit from '@/components/ResizableSplit';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter
} from '@/components/ui/dialog';
import {
  Select, SelectContent, SelectItem, SelectTrigger
} from '@/components/ui/select';
import { useWeight } from '@/hooks/useWeight';
import { useAuth } from '@/hooks/useAuth';
import api from '@/services/api';
import type { Token, TokenListResponse, Party, Product, Vehicle, SnapshotResult, TokenSnapshotsResponse } from '@/types';
import { cn } from '@/lib/utils';
import { TokenDetailModal } from '@/components/TokenDetailModal';

// ------------------------------------------------------------------ //
// Helpers (identical to TokenPage)
// ------------------------------------------------------------------ //
const STATUS_CONFIG = {
  OPEN:          { label: 'Awaiting 1st Wt',  color: 'bg-blue-100 text-blue-700 border-blue-200',    dot: 'bg-blue-500'   },
  FIRST_WEIGHT:  { label: '1st Wt Done',       color: 'bg-amber-100 text-amber-700 border-amber-200', dot: 'bg-amber-500'  },
  LOADING:       { label: 'Loading',           color: 'bg-orange-100 text-orange-700 border-orange-200', dot: 'bg-orange-500' },
  SECOND_WEIGHT: { label: 'Awaiting 2nd Wt',  color: 'bg-purple-100 text-purple-700 border-purple-200', dot: 'bg-purple-500' },
  COMPLETED:     { label: 'Completed',         color: 'bg-green-100 text-green-700 border-green-200',  dot: 'bg-green-500'  },
  CANCELLED:     { label: 'Cancelled',         color: 'bg-red-100 text-red-700 border-red-200',        dot: 'bg-red-400'    },
} as const;


// Weight values are stored in kg in the DB. UI displays MT.
function wFmt(v: number | null | undefined) {
  if (v == null) return '—';
  return (Number(v) / 1000).toLocaleString('en-IN', { minimumFractionDigits: 3, maximumFractionDigits: 3 }) + ' MT';
}

function today() {
  return new Date().toISOString().split('T')[0];
}

const canWeigh = (t: Token) =>
  t.status === 'OPEN' || t.status === 'FIRST_WEIGHT' || t.status === 'LOADING' || t.status === 'SECOND_WEIGHT';

// ------------------------------------------------------------------ //
// Scale Status bar
// ------------------------------------------------------------------ //
function ScaleStatus() {
  const { reading, formattedMT } = useWeight();
  return (
    <div className={cn(
      'flex items-center justify-between rounded-lg border px-3 py-2 text-sm transition-colors',
      reading.scale_connected
        ? reading.is_stable ? 'border-green-400 bg-green-50' : 'border-amber-300 bg-amber-50'
        : 'border-border bg-muted/30'
    )}>
      <div className="flex items-center gap-2">
        <Scale className={cn('h-4 w-4', reading.scale_connected ? 'text-green-600' : 'text-muted-foreground')} />
        <span className="text-xs text-muted-foreground font-medium">Scale</span>
        {reading.scale_connected
          ? <span className="flex items-center gap-1 text-xs text-green-600"><Wifi className="h-3 w-3" />Live</span>
          : <span className="flex items-center gap-1 text-xs text-red-500"><WifiOff className="h-3 w-3" />Offline</span>
        }
      </div>
      <div className="text-right">
        <span className={cn(
          'font-mono font-bold text-base tabular-nums',
          reading.scale_connected
            ? reading.is_stable ? 'text-green-600' : 'text-amber-600'
            : 'text-muted-foreground/50'
        )}>
          {reading.scale_connected ? formattedMT : '—'}
        </span>
        {reading.scale_connected && (
          <p className={cn('text-[10px]', reading.is_stable ? 'text-green-600' : 'text-amber-500 animate-pulse')}>
            {reading.is_stable ? `Stable ${reading.stable_duration_sec.toFixed(1)}s` : 'Stabilising…'}
          </p>
        )}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ //
// Create Token Form (identical to TokenPage)
// ------------------------------------------------------------------ //
interface CreateFormProps {
  onCreated: (token: Token) => void;
}

// Volume → weight conversion: weight_kg = volume_cft × bulk_density(kg/CFT)
// CFT (cubic feet) is the standard unit in the Indian stone-crusher trade.

// Tyre-count → default load volume (CFT). These are industry-standard capacities
// for Indian aggregate trucks (rounded m³ × 35.3147 ft³/m³);
// operators can still override the volume per token.
const TYRE_VOLUME_CFT: Record<number, number> = {
  4: 106,    // Mini-truck / pickup (Tata Ace, Bolero pickup) — ~3 m³
  6: 247,    // Small truck (Eicher Pro 1110) — ~7 m³
  8: 353,    // Medium truck — ~10 m³
  10: 459,   // Heavy truck (Eicher 6028, Ashok Leyland 1616) — ~13 m³
  12: 600,   // Multi-axle — ~17 m³
};
const TYRE_OPTIONS = [4, 6, 8, 10, 12];

function CreateTokenForm({ onCreated }: CreateFormProps) {
  const [form, setForm] = useState({
    vehicle_no: '',
    vehicle_type: '',
    token_type: 'sale',
    direction: 'outbound',
    party_id: '',
    product_id: '',
    vehicle_id: '',
    gate_pass: '',
    remarks: '',
  });
  // Volume-based weighment (skips the bridge) — volume entered in CFT only
  const [weightMethod, setWeightMethod] = useState<'weighbridge' | 'volume'>('weighbridge');
  const [volumeValue, setVolumeValue] = useState('');
  const [tyreCount, setTyreCount] = useState<number | null>(null);   // 4/6/8/10/12 or null

  // Picking a tyre count auto-fills the volume field with the standard capacity
  // for that truck class. Operator can still edit the volume below.
  function pickTyreCount(n: number) {
    setTyreCount(n);
    setVolumeValue(String(TYRE_VOLUME_CFT[n] ?? ''));
  }
  const [parties, setParties] = useState<Party[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [vehicleTypes, setVehicleTypes] = useState<string[]>([]);
  const [vehicleSearch, setVehicleSearch] = useState('');
  const [selectedVehicle, setSelectedVehicle] = useState<Vehicle | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  // Inline party quick-create
  const [partyDialogOpen, setPartyDialogOpen] = useState(false);
  const [quickParty, setQuickParty] = useState({
    name: '', party_type: 'customer' as 'customer' | 'supplier' | 'both', phone: '', gstin: '',
  });
  const [savingParty, setSavingParty] = useState(false);

  async function handleCreateParty() {
    const name = quickParty.name.trim();
    if (!name) { setError('Party name is required'); return; }
    setSavingParty(true);
    try {
      const { data } = await api.post<Party>('/api/v1/parties', {
        name,
        party_type: quickParty.party_type,
        phone: quickParty.phone.trim() || null,
        gstin: quickParty.gstin.trim() || null,
      });
      setParties(prev => [data, ...prev]);                     // prepend so it's at top of list
      setForm(f => ({ ...f, party_id: data.id }));             // auto-select the new one
      setPartyDialogOpen(false);
      setQuickParty({ name: '', party_type: 'customer', phone: '', gstin: '' });
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      setError(err.response?.data?.detail ?? 'Failed to create party');
    } finally {
      setSavingParty(false);
    }
  }

  useEffect(() => {
    Promise.all([
      api.get<{ items: Party[] }>('/api/v1/parties?page_size=200'),
      api.get<Product[]>('/api/v1/products'),
      api.get<{ items: Vehicle[] } | Vehicle[]>('/api/v1/vehicles?page_size=200'),
      api.get<string[]>('/api/v1/app-settings/vehicle-types'),
    ]).then(([p, pr, v, vt]) => {
      setParties(Array.isArray(p.data) ? p.data : (p.data.items ?? []));
      setProducts(Array.isArray(pr.data) ? pr.data : (pr.data as { items: Product[] }).items ?? []);
      const vData = v.data;
      setVehicles(Array.isArray(vData) ? vData : (vData as { items: Vehicle[] }).items ?? []);
      setVehicleTypes(Array.isArray(vt.data) ? vt.data : []);
    }).catch(() => {});
  }, []);

  function resetForm() {
    setForm({ vehicle_no: '', vehicle_type: '', token_type: 'sale', direction: 'outbound', party_id: '', product_id: '', vehicle_id: '', gate_pass: '', remarks: '' });
    setVehicleSearch('');
    setSelectedVehicle(null);
    setVolumeValue('');
    setTyreCount(null);
    setError('');
  }

  // Selected product (used for volume mode). bulk_density is now kg/CFT.
  const selectedProduct = form.product_id ? products.find(p => p.id === form.product_id) ?? null : null;
  const volumeCft = parseFloat(volumeValue || '0');
  const computedWeightKg = selectedProduct?.bulk_density
    ? volumeCft * Number(selectedProduct.bulk_density)
    : 0;

  const handleTypeChange = (type: string) => {
    setForm(f => ({ ...f, token_type: type, direction: type === 'purchase' ? 'inbound' : 'outbound', party_id: '' }));
  };

  const handleVehicleSelect = (vehicle: Vehicle) => {
    setSelectedVehicle(vehicle);
    setForm(f => ({
      ...f,
      vehicle_no: vehicle.registration_no,
      vehicle_id: vehicle.id,
      // Auto-fill vehicle_type from master if available and not already set
      vehicle_type: f.vehicle_type || vehicle.vehicle_type || '',
    }));
    setVehicleSearch('');
  };

  const filteredVehicles = vehicleSearch.length >= 1
    ? vehicles.filter(v => v.registration_no.toLowerCase().includes(vehicleSearch.toLowerCase())).slice(0, 6)
    : [];

  async function handleSubmit() {
    if (!form.vehicle_no.trim()) { setError('Vehicle number is required'); return; }

    // ── Volume mode: skip weighbridge, single POST creates + completes token ──
    if (weightMethod === 'volume') {
      if (!form.party_id) { setError('Party is required for volume-based tokens'); return; }
      if (!form.product_id) { setError('Material is required for volume-based tokens'); return; }
      if (!selectedProduct?.bulk_density) {
        setError(`Bulk density (kg/CFT) not set for "${selectedProduct?.name ?? 'this product'}". Open Products → edit this product → set Bulk Density.`);
        return;
      }
      if (!Number.isFinite(volumeCft) || volumeCft <= 0) {
        setError('Enter a positive volume in CFT (or pick a tyre count to auto-fill)'); return;
      }
      setSaving(true); setError('');
      try {
        const { data } = await api.post<Token>('/api/v1/tokens/volume', {
          token_date: today(),
          vehicle_no: form.vehicle_no.trim().toUpperCase(),
          vehicle_type: form.vehicle_type || undefined,
          token_type: form.token_type,
          direction: form.direction,
          party_id: form.party_id,
          product_id: form.product_id,
          vehicle_id: form.vehicle_id || undefined,
          volume_cft: Number(volumeCft.toFixed(3)),
          gate_pass: form.gate_pass || undefined,
          remarks: form.remarks
            ? `${form.remarks}${tyreCount ? ` | ${tyreCount}-tyre truck` : ''}`
            : (tyreCount ? `${tyreCount}-tyre truck` : undefined),
        });
        onCreated(data);
        resetForm();
      } catch (e: unknown) {
        // Surface the real backend error — handle several axios error shapes
        const err = e as {
          response?: { status?: number; data?: { detail?: string | Array<{ msg: string; loc?: string[] }> } };
          message?: string;
        };
        const detail = err.response?.data?.detail;
        let msg: string;
        if (typeof detail === 'string') {
          msg = detail;
        } else if (Array.isArray(detail)) {
          // FastAPI validation errors: list of { msg, loc }
          msg = detail.map(d => `${(d.loc ?? []).join('.')}: ${d.msg}`).join(' · ');
        } else {
          msg = err.message ?? 'Failed to create volume-based token';
        }
        const status = err.response?.status ?? '?';
        setError(`HTTP ${status}: ${msg}`);
        console.error('Volume token failed:', err);
      } finally {
        setSaving(false);
      }
      return;
    }

    // ── Weighbridge mode (default): two-step weighment workflow ──
    setSaving(true); setError('');
    try {
      const { data } = await api.post<Token>('/api/v1/tokens', {
        token_date: today(),
        vehicle_no: form.vehicle_no.trim().toUpperCase(),
        vehicle_type: form.vehicle_type || undefined,
        token_type: form.token_type,
        direction: form.direction,
        party_id: form.party_id || undefined,
        product_id: form.product_id || undefined,
        vehicle_id: form.vehicle_id || undefined,
        remarks: form.remarks || undefined,
      });
      onCreated(data);
      resetForm();
    } catch {
      setError('Failed to create token. Please try again.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="rounded-xl border bg-card shadow-sm flex flex-col overflow-hidden flex-1 min-h-0">
      {/* Bold colorful header */}
      <div className="relative bg-gradient-to-br from-blue-600 via-blue-700 to-indigo-800 px-4 py-4 overflow-hidden shrink-0">
        <div className="absolute -top-4 -right-4 h-24 w-24 rounded-full bg-white/10" />
        <div className="absolute -bottom-6 -left-4 h-20 w-20 rounded-full bg-white/5" />
        <div className="relative flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-white/20 shadow-inner backdrop-blur-sm">
            <Truck className="h-5 w-5 text-white" />
          </div>
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-widest text-blue-200">Weighbridge</p>
            <p className="text-xl font-black text-white tracking-tight">New Token</p>
          </div>
          <div className="ml-auto">
            <span className="flex h-3 w-3">
              <span className="animate-ping absolute h-3 w-3 rounded-full bg-green-300 opacity-75" />
              <span className="h-3 w-3 rounded-full bg-green-400" />
            </span>
          </div>
        </div>
      </div>

      <div className="p-3 space-y-3 overflow-y-auto flex-1">
        {error && (
          <div className="flex items-center gap-2 rounded-lg bg-destructive/10 p-2.5 text-xs text-destructive">
            <AlertCircle className="h-3.5 w-3.5 shrink-0" />
            {error}
          </div>
        )}

        {/* Token Type */}
        <div className="space-y-1">
          <Label className="text-xs">Token Type</Label>
          <div className="grid grid-cols-2 gap-2">
            {[
              { value: 'sale',     label: 'Sale',     sub: 'Outbound', color: 'border-blue-400 bg-blue-50 text-blue-700' },
              { value: 'purchase', label: 'Purchase', sub: 'Inbound',  color: 'border-green-400 bg-green-50 text-green-700' },
            ].map(opt => (
              <button
                key={opt.value}
                type="button"
                onClick={() => handleTypeChange(opt.value)}
                className={cn(
                  'rounded-lg border-2 p-2 text-left transition-all',
                  form.token_type === opt.value ? opt.color : 'border-border hover:border-primary/40'
                )}
              >
                <p className="font-semibold text-xs">{opt.label}</p>
                <p className="text-[10px] text-muted-foreground">{opt.sub}</p>
              </button>
            ))}
          </div>
        </div>

        {/* Vehicle */}
        <div className="space-y-1">
          <Label className="text-xs">Vehicle Number <span className="text-destructive">*</span></Label>
          {selectedVehicle ? (
            <div className="flex items-center gap-2 rounded-lg border-2 border-green-400 bg-green-50 px-3 py-2">
              <Truck className="h-4 w-4 text-green-600 shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="font-bold text-xs text-green-800">{selectedVehicle.registration_no}</p>
                {selectedVehicle.default_tare_weight > 0 && (
                  <p className="text-[10px] text-green-700">Tare: {wFmt(selectedVehicle.default_tare_weight)}</p>
                )}
              </div>
              <button
                type="button"
                onClick={() => { setSelectedVehicle(null); setForm(f => ({ ...f, vehicle_no: '', vehicle_id: '' })); }}
                className="text-[10px] text-green-700 underline hover:text-green-900 shrink-0"
              >Change</button>
            </div>
          ) : (
            <div className="space-y-1.5">
              <div className="relative">
                <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
                <Input
                  className="pl-8 h-8 text-xs"
                  placeholder="Search registered vehicle…"
                  value={vehicleSearch}
                  onChange={e => setVehicleSearch(e.target.value)}
                />
                {filteredVehicles.length > 0 && (
                  <div className="absolute top-full left-0 right-0 z-50 mt-1 rounded-lg border bg-popover shadow-lg">
                    {filteredVehicles.map(v => (
                      <button
                        key={v.id}
                        type="button"
                        className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-muted transition-colors first:rounded-t-lg last:rounded-b-lg text-xs"
                        onClick={() => handleVehicleSelect(v)}
                      >
                        <Truck className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                        <span className="font-medium">{v.registration_no}</span>
                        {v.default_tare_weight > 0 && (
                          <span className="ml-auto text-[10px] text-muted-foreground">{wFmt(v.default_tare_weight)}</span>
                        )}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <Input
                className="h-8 text-xs uppercase"
                placeholder="Or type: MH12AB1234"
                value={form.vehicle_no}
                onChange={e => setForm(f => ({ ...f, vehicle_no: e.target.value.toUpperCase(), vehicle_id: '' }))}
              />
            </div>
          )}
        </div>

        {/* Vehicle Type */}
        <div className="space-y-1">
          <Label className="text-xs">Vehicle Type</Label>
          <Select value={form.vehicle_type || undefined} onValueChange={v => setForm(f => ({ ...f, vehicle_type: v ?? '' }))}>
            <SelectTrigger className="h-8 text-xs">
              <span className="truncate text-left flex-1">
                {form.vehicle_type
                  ? <span className="capitalize">{form.vehicle_type.replace(/_/g, ' ')}</span>
                  : <span className="text-muted-foreground">Select type…</span>}
              </span>
            </SelectTrigger>
            <SelectContent>
              {vehicleTypes.map(vt => (
                <SelectItem key={vt} value={vt}>
                  <span className="capitalize">{vt.replace(/_/g, ' ')}</span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* Party */}
        <div className="space-y-1">
          <Label className="text-xs">Party</Label>
          <div className="flex gap-1.5">
            <Select value={form.party_id || undefined} onValueChange={v => setForm(f => ({ ...f, party_id: v ?? '' }))}>
              <SelectTrigger className="h-8 text-xs flex-1">
                <span className="truncate text-left flex-1">
                  {form.party_id
                    ? (parties.find(p => p.id === form.party_id)?.name ?? '…')
                    : <span className="text-muted-foreground">Select party…</span>}
                </span>
              </SelectTrigger>
              <SelectContent>
                {parties
                  .filter(p => {
                    if (form.token_type === 'sale') return p.party_type === 'customer' || p.party_type === 'both';
                    if (form.token_type === 'purchase') return p.party_type === 'supplier' || p.party_type === 'both';
                    return true;
                  })
                  .map(p => (
                    <SelectItem key={p.id} value={String(p.id)}>
                      <span className="font-medium">{p.name}</span>
                      {p.gstin && <span className="text-muted-foreground text-xs ml-2">{p.gstin}</span>}
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
            <Button
              type="button" size="sm" variant="outline" className="h-8 px-2 shrink-0"
              onClick={() => {
                // Pre-fill party_type to match the current token type
                setQuickParty({
                  name: '',
                  party_type: form.token_type === 'purchase' ? 'supplier' : 'customer',
                  phone: '', gstin: '',
                });
                setPartyDialogOpen(true);
              }}
              title="Add a new party — appears in the dropdown immediately"
            >
              <Plus className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>

        {/* Material */}
        <div className="space-y-1">
          <Label className="text-xs">Material</Label>
          <Select value={form.product_id || undefined} onValueChange={v => setForm(f => ({ ...f, product_id: v ?? '' }))}>
            <SelectTrigger className="h-8 text-xs">
              <span className="truncate text-left flex-1">
                {form.product_id
                  ? (() => { const p = products.find(x => x.id === form.product_id); return p ? p.name : '…'; })()
                  : <span className="text-muted-foreground">Select material…</span>}
              </span>
            </SelectTrigger>
            <SelectContent>
              {products.map(p => (
                <SelectItem key={p.id} value={p.id}>
                  {p.name} <span className="text-muted-foreground text-xs">({p.unit})</span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* Weighment method */}
        <div className="space-y-1">
          <Label className="text-xs">Measurement Method</Label>
          <div className="grid grid-cols-2 gap-2">
            {[
              { value: 'weighbridge', label: 'Weighbridge', sub: 'Gross + Tare' },
              { value: 'volume',      label: 'Volume',      sub: 'CFT × density' },
            ].map(opt => (
              <button
                key={opt.value}
                type="button"
                onClick={() => setWeightMethod(opt.value as 'weighbridge' | 'volume')}
                className={cn(
                  'rounded-lg border-2 p-2 text-left transition-all',
                  weightMethod === opt.value
                    ? 'border-amber-400 bg-amber-50 text-amber-700'
                    : 'border-border hover:border-primary/40'
                )}
              >
                <p className="font-semibold text-xs">{opt.label}</p>
                <p className="text-[10px] text-muted-foreground">{opt.sub}</p>
              </button>
            ))}
          </div>
        </div>

        {/* Volume input (only in volume mode) */}
        {weightMethod === 'volume' && (
          <div className="space-y-3 rounded-lg border-2 border-amber-200 bg-amber-50/40 p-3">
            {/* Step 1: Pick tyre count → volume auto-fills */}
            <div className="space-y-1.5">
              <Label className="text-xs">Truck size — tyre count</Label>
              <div className="grid grid-cols-5 gap-1.5">
                {TYRE_OPTIONS.map(n => (
                  <button
                    key={n}
                    type="button"
                    onClick={() => pickTyreCount(n)}
                    className={cn(
                      'rounded-lg border-2 px-1 py-2 text-center transition-all',
                      tyreCount === n
                        ? 'border-amber-500 bg-amber-100 text-amber-800'
                        : 'border-border hover:border-amber-300 bg-white',
                    )}
                  >
                    <div className="text-xs font-bold leading-none">{n}</div>
                    <div className="text-[9px] text-muted-foreground leading-tight mt-0.5">
                      tyre<br/>{TYRE_VOLUME_CFT[n]} CFT
                    </div>
                  </button>
                ))}
              </div>
              {tyreCount !== null && (
                <p className="text-[10px] text-amber-700">
                  Defaulted to {TYRE_VOLUME_CFT[tyreCount]} CFT for a {tyreCount}-tyre truck. Adjust below if needed.
                </p>
              )}
            </div>

            {/* Step 2: Editable volume in CFT (auto-filled from tyre count, can override) */}
            <div className="space-y-1">
              <Label className="text-xs">Volume (CFT) <span className="text-destructive">*</span></Label>
              <div className="flex gap-2 items-center">
                <Input
                  type="number"
                  className="h-8 text-xs flex-1"
                  value={volumeValue}
                  onChange={e => { setVolumeValue(e.target.value); setTyreCount(null); }}
                  placeholder="Pick a tyre count above, or type CFT here"
                  min="0"
                  step="0.01"
                />
                <span className="text-xs font-semibold text-muted-foreground px-2">CFT</span>
              </div>
            </div>

            {/* Step 3: Live calculation preview */}
            {!form.product_id ? (
              <p className="text-[10px] text-muted-foreground">Select a material below to compute weight.</p>
            ) : !selectedProduct?.bulk_density ? (
              <p className="text-[10px] text-destructive">
                Bulk density not set for {selectedProduct?.name}. Open Products → edit this product → set Bulk Density in kg/CFT (typical: aggregate 42.5, sand 48.1, GSB 53.8).
              </p>
            ) : volumeCft <= 0 ? (
              <p className="text-[10px] text-muted-foreground">Pick a tyre count or enter a volume to see the computed weight.</p>
            ) : (
              <div className="rounded-md bg-white px-2.5 py-2 text-[10px] border">
                <div className="flex justify-between text-muted-foreground">
                  <span>Volume</span><span>{volumeCft.toFixed(2)} CFT</span>
                </div>
                <div className="flex justify-between text-muted-foreground">
                  <span>× Density ({selectedProduct.name})</span>
                  <span>{Number(selectedProduct.bulk_density).toFixed(2)} kg/CFT</span>
                </div>
                <div className="mt-1 flex justify-between border-t pt-1 text-sm font-bold text-amber-700">
                  <span>= Net weight</span>
                  <span>{(computedWeightKg / 1000).toFixed(3)} MT</span>
                </div>
              </div>
            )}

            <div className="text-[10px] text-muted-foreground bg-white rounded p-2 border">
              <strong>How this works:</strong> No weighbridge needed. One click creates the token,
              auto-completes it, and generates a draft invoice.
            </div>
          </div>
        )}

        {/* Gate Pass */}
        <div className="space-y-1">
          <Label className="text-xs">Gate Pass <span className="text-muted-foreground">(optional)</span></Label>
          <Input
            className="h-8 text-xs"
            value={form.gate_pass}
            onChange={e => setForm(f => ({ ...f, gate_pass: e.target.value }))}
            placeholder="GP-001…"
          />
        </div>

        {/* Remarks */}
        <div className="space-y-1">
          <Label className="text-xs">Remarks <span className="text-muted-foreground">(optional)</span></Label>
          <Input
            className="h-8 text-xs"
            value={form.remarks}
            onChange={e => setForm(f => ({ ...f, remarks: e.target.value }))}
            placeholder="Driver name, challan no…"
          />
        </div>
      </div>

      {/* Submit */}
      <div className="px-3 pb-3 pt-2 border-t shrink-0">
        <Button
          className="w-full"
          size="sm"
          onClick={handleSubmit}
          disabled={saving || !form.vehicle_no.trim()}
        >
          {saving
            ? <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            : <ArrowRight className="mr-2 h-4 w-4" />}
          {weightMethod === 'volume' ? 'Create Token (Volume)' : 'Start Weighment'}
        </Button>
      </div>

      {/* Quick-create Party dialog — opens from the + button next to Party dropdown */}
      <Dialog open={partyDialogOpen} onOpenChange={o => !o && setPartyDialogOpen(false)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Add Party</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1">
              <Label className="text-xs">Party Type</Label>
              <div className="grid grid-cols-3 gap-1.5">
                {(['customer', 'supplier', 'both'] as const).map(t => (
                  <button
                    key={t}
                    type="button"
                    onClick={() => setQuickParty(q => ({ ...q, party_type: t }))}
                    className={cn(
                      'rounded-md border-2 p-2 text-xs font-medium capitalize transition-all',
                      quickParty.party_type === t
                        ? 'border-primary bg-primary/10 text-primary'
                        : 'border-border text-muted-foreground hover:border-primary/40'
                    )}
                  >
                    {t}
                  </button>
                ))}
              </div>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Name <span className="text-destructive">*</span></Label>
              <Input
                autoFocus
                value={quickParty.name}
                onChange={e => setQuickParty(q => ({ ...q, name: e.target.value }))}
                placeholder="e.g. Rajesh Construction Co"
              />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Phone <span className="text-muted-foreground">(optional)</span></Label>
              <Input
                value={quickParty.phone}
                onChange={e => setQuickParty(q => ({ ...q, phone: e.target.value }))}
                placeholder="10-digit mobile"
              />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">GSTIN <span className="text-muted-foreground">(optional)</span></Label>
              <Input
                value={quickParty.gstin}
                onChange={e => setQuickParty(q => ({ ...q, gstin: e.target.value.toUpperCase() }))}
                placeholder="15-character GSTIN"
                maxLength={15}
                className="font-mono"
              />
            </div>
            <p className="text-[10px] text-muted-foreground">
              You can fill in the rest of the party details later from the Parties page.
            </p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPartyDialogOpen(false)}>Cancel</Button>
            <Button onClick={handleCreateParty} disabled={savingParty || !quickParty.name.trim()}>
              {savingParty ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Plus className="mr-2 h-4 w-4" />}
              Add Party
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// ------------------------------------------------------------------ //
// Weight Capture Dialog (identical to TokenPage)
// ------------------------------------------------------------------ //
interface WeightDialogProps {
  token: Token | null;
  weightStage: 'first' | 'second';
  open: boolean;
  onClose: () => void;
  onDone: (updated: Token) => void;
}

// Convert kg → "x.xxx MT" for the live readout
function mtFromKg(kg: number) {
  return (kg / 1000).toLocaleString('en-IN', { minimumFractionDigits: 3, maximumFractionDigits: 3 }) + ' MT';
}

function WeightCaptureDialog({ token, weightStage, open, onClose, onDone }: WeightDialogProps) {
  const { reading, formattedMT } = useWeight();
  const [manualMode, setManualMode] = useState(false);
  const [manualWeight, setManualWeight] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const manualRef = useRef<HTMLInputElement>(null);
  const [capturePhase, setCapturePhase] = useState<'idle' | 'capturing' | 'done'>('idle');
  const [snapshots, setSnapshots] = useState<SnapshotResult[]>([]);
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (open) {
      setManualMode(false);
      setManualWeight('');
      setError('');
      setCapturePhase('idle');
      setSnapshots([]);
    }
    return () => { if (pollTimerRef.current) clearTimeout(pollTimerRef.current); };
  }, [open]);

  useEffect(() => {
    if (manualMode && manualRef.current) manualRef.current.focus();
  }, [manualMode]);

  if (!token) return null;

  const isSale = token.token_type === 'sale';
  const stage1Label = isSale ? 'Tare Weight (Empty Truck)' : 'Gross Weight (Truck + Material)';
  const stage2Label = isSale ? 'Gross Weight (Truck + Material)' : 'Tare Weight (Empty Truck)';
  const currentLabel = weightStage === 'first' ? stage1Label : stage2Label;
  const stageNum = weightStage === 'first' ? 1 : 2;

  // Manual entry is in MT (operator-friendly). Multiply by 1000 to get kg —
  // the unit the backend stores and the bridge streams.
  const manualKg = manualMode ? (parseFloat(manualWeight) || 0) * 1000 : 0;
  const liveWeight = manualMode ? manualKg : reading.weight_kg;
  const stage1Weight = token.first_weight ?? 0;
  const liveNet = weightStage === 'second' && stage1Weight > 0
    ? Math.max(0, isSale ? liveWeight - stage1Weight : stage1Weight - liveWeight)
    : null;

  async function capture(weight: number, isManual = false) {
    if (weight <= 0) { setError('Weight must be greater than 0'); return; }
    setSaving(true); setError('');
    try {
      const endpoint = weightStage === 'first'
        ? `/api/v1/tokens/${token!.id}/first-weight`
        : `/api/v1/tokens/${token!.id}/second-weight`;
      const { data } = await api.post<Token>(endpoint, { weight_kg: weight, is_manual: isManual });

      const isCaptureStage =
        (token!.token_type === 'sale'     && weightStage === 'second') ||
        (token!.token_type === 'purchase' && weightStage === 'first');

      if (isCaptureStage) {
        onDone(data);
        setCapturePhase('capturing');
        const tokenId = token!.id;
        const deadline = Date.now() + 20_000;

        const poll = async () => {
          if (Date.now() > deadline) {
            setCapturePhase('done');
            pollTimerRef.current = setTimeout(onClose, 1000);
            return;
          }
          try {
            const { data: snaps } = await api.get<TokenSnapshotsResponse>(
              `/api/v1/tokens/${tokenId}/snapshots`
            );
            setSnapshots(snaps.snapshots);
            if (snaps.all_done) {
              setCapturePhase('done');
              pollTimerRef.current = setTimeout(onClose, 2500);
            } else {
              pollTimerRef.current = setTimeout(poll, 2000);
            }
          } catch {
            setCapturePhase('done');
            pollTimerRef.current = setTimeout(onClose, 500);
          }
        };
        pollTimerRef.current = setTimeout(poll, 2000);
      } else {
        onDone(data);
        onClose();
      }
    } catch {
      setError('Failed to record weight. Please try again.');
    } finally {
      setSaving(false);
    }
  }

  const canCapture = reading.scale_connected && reading.is_stable && reading.weight_kg > 0;

  // Tare stage = first weight for sale, second weight for purchase
  const isTareStage = (isSale && weightStage === 'first') || (!isSale && weightStage === 'second');
  const storedTare = Number(token.vehicle?.default_tare_weight ?? 0);
  const hasStoredTare = isTareStage && storedTare > 0;

  return (
    <Dialog open={open} onOpenChange={v => !v && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <span className={cn(
              'flex h-7 w-7 items-center justify-center rounded-full text-sm font-bold text-white',
              stageNum === 1 ? 'bg-blue-600' : 'bg-amber-500'
            )}>
              {stageNum}
            </span>
            Stage {stageNum} of 2 — {currentLabel}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          <div className="rounded-lg border bg-muted/30 p-3 space-y-1.5">
            <div className="flex items-center gap-2">
              <Truck className="h-4 w-4 text-primary shrink-0" />
              <span className="font-bold text-sm">{token.vehicle_no}</span>
              {token.vehicle_type && (
                <span className="text-[10px] capitalize rounded px-1.5 py-0.5 bg-muted text-muted-foreground font-medium">
                  {token.vehicle_type.replace(/_/g, ' ')}
                </span>
              )}
            </div>
            {token.party && (
              <div className="flex items-center gap-2">
                <User className="h-4 w-4 text-muted-foreground shrink-0" />
                <span className="text-sm text-muted-foreground">{token.party.name}</span>
              </div>
            )}
            {token.product && (
              <div className="flex items-center gap-2">
                <Package className="h-4 w-4 text-muted-foreground shrink-0" />
                <span className="text-sm text-muted-foreground">{token.product.name}</span>
              </div>
            )}
          </div>

          {weightStage === 'second' && stage1Weight > 0 && (
            <div className="rounded-lg border-2 border-dashed border-muted-foreground/20 p-3">
              <p className="text-xs text-muted-foreground mb-1">{stage1Label} (recorded)</p>
              <p className="font-mono text-xl font-bold">{wFmt(stage1Weight)}</p>
            </div>
          )}

          {error && (
            <div className="flex items-center gap-2 rounded-lg bg-destructive/10 p-2 text-sm text-destructive">
              <AlertCircle className="h-4 w-4 shrink-0" />
              {error}
            </div>
          )}

          {!manualMode ? (
            <div className={cn(
              'rounded-xl border-2 p-4 text-center transition-all',
              reading.scale_connected
                ? canCapture ? 'border-green-500 bg-green-50' : 'border-amber-400 bg-amber-50'
                : 'border-border bg-muted/20'
            )}>
              <div className="flex items-center justify-center gap-2 mb-2">
                <span className="text-xs uppercase tracking-widest text-muted-foreground font-semibold">Scale Reading</span>
                {reading.scale_connected
                  ? <Badge variant="outline" className="border-green-500 text-green-600 text-[10px]">LIVE</Badge>
                  : <Badge variant="outline" className="border-red-400 text-red-500 text-[10px]">OFFLINE</Badge>
                }
              </div>
              <div className={cn(
                'font-mono text-5xl font-black tabular-nums',
                reading.scale_connected
                  ? canCapture ? 'text-green-600' : 'text-amber-600'
                  : 'text-muted-foreground/40'
              )}>
                {reading.scale_connected ? formattedMT : '— . — — —  MT'}
              </div>
              <div className="h-5 mt-1">
                {reading.scale_connected && (
                  canCapture
                    ? <p className="text-xs text-green-600 font-semibold">✓ Stable for {reading.stable_duration_sec.toFixed(1)}s</p>
                    : <p className="text-xs text-amber-600 animate-pulse">Stabilising, please wait…</p>
                )}
              </div>
            </div>
          ) : (
            <div className="space-y-2">
              <Label>Enter Weight Manually (MT)</Label>
              <Input
                ref={manualRef}
                type="number"
                step="0.001"
                min="0"
                value={manualWeight}
                onChange={e => setManualWeight(e.target.value)}
                placeholder="0.000"
                className="text-2xl font-mono h-14 text-center font-bold"
              />
            </div>
          )}

          {liveNet !== null && liveWeight > 0 && (
            <div className="rounded-lg bg-primary/5 border border-primary/20 p-3 flex items-center justify-between">
              <div>
                <p className="text-xs text-muted-foreground">Live Net Weight Preview</p>
                <p className="font-mono text-2xl font-black text-primary">{mtFromKg(liveNet)}</p>
              </div>
              <div className="text-xs text-muted-foreground text-right">
                <p>{wFmt(isSale ? liveWeight : stage1Weight)} (gross)</p>
                <p>− {wFmt(isSale ? stage1Weight : liveWeight)} (tare)</p>
              </div>
            </div>
          )}

          <button
            type="button"
            onClick={() => setManualMode(m => !m)}
            className="text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground"
          >
            {manualMode ? '← Use live scale instead' : 'Enter weight manually →'}
          </button>

          {capturePhase !== 'idle' && (
            <div className="rounded-lg border bg-muted/30 p-3 space-y-2">
              <div className="flex items-center gap-2 text-sm font-medium">
                {capturePhase === 'capturing' ? (
                  <><Loader2 className="h-4 w-4 animate-spin text-primary" /> Capturing camera images…</>
                ) : (
                  <><Camera className="h-4 w-4 text-green-600" /> Camera images captured</>
                )}
              </div>
              {snapshots.map(s => (
                <div key={s.camera_id} className="flex items-center gap-2 text-xs">
                  <Camera className="h-3 w-3 text-muted-foreground shrink-0" />
                  <span className="font-medium capitalize">{s.camera_label || s.camera_id} View</span>
                  {s.capture_status === 'pending' && <span className="text-amber-600 ml-auto">Waiting…</span>}
                  {s.capture_status === 'captured' && <span className="text-green-600 ml-auto">✓ Captured</span>}
                  {s.capture_status === 'failed' && <span className="text-red-500 ml-auto">✗ Failed</span>}
                </div>
              ))}
              {capturePhase === 'done' && snapshots.some(s => s.url) && (
                <div className="grid grid-cols-2 gap-2 pt-1">
                  {snapshots.filter(s => s.url).map(s => (
                    <div key={s.camera_id}>
                      <p className="text-[10px] text-muted-foreground capitalize mb-1">
                        {s.camera_label || s.camera_id} View
                      </p>
                      <img
                        src={s.url!}
                        alt={s.camera_id}
                        className="rounded border w-full h-24 object-cover"
                      />
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        <DialogFooter className="gap-2 flex-wrap">
          <Button variant="outline" onClick={onClose} disabled={saving}>
            {capturePhase !== 'idle' ? 'Close' : 'Cancel'}
          </Button>
          {capturePhase === 'idle' && hasStoredTare && (
            <Button
              variant="secondary"
              onClick={() => capture(storedTare, true)}
              disabled={saving}
              className="min-w-44"
              title={`Use vehicle's registered tare weight: ${(storedTare / 1000).toFixed(3)} MT`}
            >
              {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Truck className="mr-2 h-4 w-4" />}
              Use Reg. Tare ({(storedTare / 1000).toFixed(3)} MT)
            </Button>
          )}
          {capturePhase === 'idle' && (
            !manualMode ? (
              <Button
                onClick={() => capture(reading.weight_kg, false)}
                disabled={saving || !canCapture}
                className="bg-green-600 hover:bg-green-700 text-white min-w-32"
              >
                {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Scale className="mr-2 h-4 w-4" />}
                {canCapture ? 'Capture Weight' : 'Waiting…'}
              </Button>
            ) : (
              <Button
                onClick={() => capture(parseFloat(manualWeight) * 1000, true) /* MT → kg */}
                disabled={saving || !manualWeight || parseFloat(manualWeight) <= 0}
                className="min-w-32"
              >
                {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Save Weight
              </Button>
            )
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ------------------------------------------------------------------ //
// Camera Panel — WebSocket live streaming (same approach as CameraScalePage)
// ------------------------------------------------------------------ //
interface CameraPanelProps {
  cameraId: 'front' | 'top';
  label: string;
}

function CameraPanel({ cameraId, label }: CameraPanelProps) {
  const [status, setStatus] = useState<'connecting' | 'live' | 'error'>('connecting');
  const [imgSrc, setImgSrc] = useState('');
  const wsRef = useRef<WebSocket | null>(null);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);
  const prevBlobRef = useRef('');

  const wsPort = localStorage.getItem('camera_agent_ws_port') || '9004';

  useEffect(() => {
    mountedRef.current = true;
    let reconnectAttempts = 0;

    function connect() {
      if (!mountedRef.current) return;
      if (wsRef.current) {
        try { wsRef.current.close(); } catch (_e) { /* ignore */ }
      }
      setStatus('connecting');

      const ws = new WebSocket(`ws://localhost:${wsPort}/live/${cameraId}`);
      ws.binaryType = 'arraybuffer';
      wsRef.current = ws;

      ws.onopen = () => { if (mountedRef.current) reconnectAttempts = 0; };

      ws.onmessage = (event: MessageEvent) => {
        if (!mountedRef.current) return;
        const data = event.data as ArrayBuffer;
        if (data.byteLength <= 1) return;
        const blob = new Blob([data], { type: 'image/jpeg' });
        const url = URL.createObjectURL(blob);
        if (prevBlobRef.current) URL.revokeObjectURL(prevBlobRef.current);
        prevBlobRef.current = url;
        setImgSrc(url);
        setStatus('live');
      };

      ws.onerror = () => {};
      ws.onclose = () => {
        if (!mountedRef.current) return;
        setStatus('error');
        reconnectAttempts++;
        const delay = Math.min(2000 * reconnectAttempts, 10000);
        retryTimerRef.current = setTimeout(connect, delay);
      };
    }

    connect();

    return () => {
      mountedRef.current = false;
      if (wsRef.current) { try { wsRef.current.close(); } catch (_e) { /* ignore */ } wsRef.current = null; }
      if (retryTimerRef.current) { clearTimeout(retryTimerRef.current); retryTimerRef.current = null; }
      if (prevBlobRef.current) { URL.revokeObjectURL(prevBlobRef.current); prevBlobRef.current = ''; }
    };
  }, [cameraId, wsPort]);

  function retry() {
    if (wsRef.current) { try { wsRef.current.close(); } catch (_e) { /* ignore */ } }
    if (retryTimerRef.current) clearTimeout(retryTimerRef.current);
    setStatus('connecting');
    const ws = new WebSocket(`ws://localhost:${wsPort}/live/${cameraId}`);
    ws.binaryType = 'arraybuffer';
    wsRef.current = ws;
    ws.onopen = () => {};
    ws.onmessage = (event: MessageEvent) => {
      if (!mountedRef.current) return;
      const data = event.data as ArrayBuffer;
      if (data.byteLength <= 1) return;
      const blob = new Blob([data], { type: 'image/jpeg' });
      const url = URL.createObjectURL(blob);
      if (prevBlobRef.current) URL.revokeObjectURL(prevBlobRef.current);
      prevBlobRef.current = url;
      setImgSrc(url);
      setStatus('live');
    };
    ws.onerror = () => {};
    ws.onclose = () => { if (mountedRef.current) setStatus('error'); };
  }

  return (
    <div className="relative flex flex-col rounded-xl overflow-hidden border border-slate-700/60 bg-slate-900/80 shadow-xl h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 bg-slate-800/90 border-b border-slate-700/50 shrink-0">
        <div className="flex items-center gap-2">
          <span className="relative flex h-2 w-2 shrink-0">
            <span className={`absolute inline-flex h-full w-full rounded-full opacity-75 ${
              status === 'live' ? 'animate-ping bg-emerald-400' :
              status === 'connecting' ? 'animate-ping bg-amber-400' : ''
            }`} />
            <span className={`relative inline-flex h-2 w-2 rounded-full ${
              status === 'live' ? 'bg-emerald-400' :
              status === 'connecting' ? 'bg-amber-400' : 'bg-red-500'
            }`} />
          </span>
          <Camera className="h-3.5 w-3.5 text-slate-400" />
          <p className="text-xs font-semibold text-slate-100">{label}</p>
        </div>
        <div className="flex items-center gap-1.5">
          <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full border ${
            status === 'live'
              ? 'text-emerald-400 border-emerald-500/40 bg-emerald-500/10'
              : status === 'connecting'
              ? 'text-amber-400 border-amber-500/40 bg-amber-500/10'
              : 'text-red-400 border-red-500/40 bg-red-500/10'
          }`}>
            {status === 'live' ? '● LIVE' : status === 'connecting' ? '◌ CONN' : '✕ OFF'}
          </span>
          <button
            onClick={retry}
            className="p-1 rounded text-slate-500 hover:text-slate-300 transition-colors"
            title="Reconnect"
          >
            <RefreshCw className="h-3 w-3" />
          </button>
        </div>
      </div>

      {/* Video area */}
      <div className="relative flex-1 bg-black min-h-0 overflow-hidden">
        {status === 'error' && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-slate-950">
            <WifiOff className="h-8 w-8 text-red-500/50" />
            <p className="text-red-400 text-xs font-medium">Camera Offline</p>
            <button
              onClick={retry}
              className="flex items-center gap-1 text-[10px] px-2 py-1 rounded bg-slate-800 text-slate-300 hover:bg-slate-700 border border-slate-600 transition-colors"
            >
              <RefreshCw className="h-2.5 w-2.5" /> Retry
            </button>
          </div>
        )}
        {status === 'connecting' && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-slate-950">
            <div className="relative">
              <div className="h-10 w-10 rounded-full border-2 border-slate-700 border-t-amber-400 animate-spin" />
              <Camera className="absolute inset-0 m-auto h-4 w-4 text-slate-500" />
            </div>
            <p className="text-amber-400/80 text-xs">Connecting…</p>
          </div>
        )}
        {imgSrc && status === 'live' && (
          <img
            src={imgSrc}
            alt={label}
            className="w-full h-full object-cover"
            style={{ minHeight: 0 }}
          />
        )}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ //
// MT + CFT weight formatters
// ------------------------------------------------------------------ //
function mtFmt(v: number | null | undefined) {
  if (v == null) return '—';
  return (v / 1000).toLocaleString('en-IN', { minimumFractionDigits: 3, maximumFractionDigits: 3 }) + ' MT';
}
/** Returns "9.750 MT / 344.34 CFT" when bulk_density(kg/CFT) available, else "9.750 MT" */
function dualFmt(weightKg: number | null | undefined, bulkDensity: number | null | undefined): string {
  if (weightKg == null) return '—';
  const mt = (weightKg / 1000).toLocaleString('en-IN', { minimumFractionDigits: 3, maximumFractionDigits: 3 });
  if (!bulkDensity || bulkDensity <= 0) return `${mt} MT`;
  // bulk_density is kg/CFT, so CFT = kg ÷ kg_per_cft
  const cft = weightKg / Number(bulkDensity);
  return `${mt} MT / ${cft.toFixed(2)} CFT`;
}

// Active statuses (default filter)
// Default visible statuses on the Trip page. Includes COMPLETED so volume tokens
// (which jump straight to COMPLETED on creation) are visible without changing
// the filter. The status filter chips still let the user narrow further.
const DEFAULT_VISIBLE_STATUSES = ['OPEN', 'FIRST_WEIGHT', 'LOADING', 'SECOND_WEIGHT', 'COMPLETED'] as const;
type TokenStatus = keyof typeof STATUS_CONFIG;

// Status multi-select filter pill
function StatusFilterPills({
  selected,
  onChange,
}: {
  selected: Set<TokenStatus>;
  onChange: (s: Set<TokenStatus>) => void;
}) {
  function toggle(s: TokenStatus) {
    const next = new Set(selected);
    if (next.has(s)) next.delete(s); else next.add(s);
    onChange(next);
  }
  const HIDDEN_FILTERS: TokenStatus[] = ['OPEN', 'LOADING', 'SECOND_WEIGHT'];
  const all = (Object.entries(STATUS_CONFIG) as [TokenStatus, typeof STATUS_CONFIG[keyof typeof STATUS_CONFIG]][])
    .filter(([key]) => !HIDDEN_FILTERS.includes(key));
  return (
    <div className="flex flex-wrap gap-1">
      {all.map(([key, cfg]) => (
        <button
          key={key}
          type="button"
          onClick={() => toggle(key)}
          className={cn(
            'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium transition-all',
            selected.has(key)
              ? cfg.color + ' ring-1 ring-offset-0 ring-current'
              : 'border-border bg-muted/30 text-muted-foreground opacity-50'
          )}
        >
          <span className={`h-1.5 w-1.5 rounded-full shrink-0 ${selected.has(key) ? cfg.dot : 'bg-muted-foreground'}`} />
          {cfg.label}
        </button>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ //
// Main Page
// ------------------------------------------------------------------ //
export default function TokenPageV1() {
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';

  const [tokens, setTokens] = useState<Token[]>([]);
  const [loading, setLoading] = useState(false);

  // Search + date + status filter + measurement-method filter
  const [search, setSearch] = useState('');
  const [dateFrom, setDateFrom] = useState(today());
  const [dateTo, setDateTo] = useState(today());
  const [selectedStatuses, setSelectedStatuses] = useState<Set<TokenStatus>>(
    new Set(DEFAULT_VISIBLE_STATUSES)
  );
  // 'all' = show both; 'weighbridge' = bridge-weighed only; 'volume' = volume-computed only
  const [measurementFilter, setMeasurementFilter] = useState<'all' | 'weighbridge' | 'volume'>('all');

  const [weightToken, setWeightToken] = useState<Token | null>(null);
  const [weightStage, setWeightStage] = useState<'first' | 'second'>('first');
  const [weightOpen, setWeightOpen] = useState(false);
  const [tokenModalId, setTokenModalId] = useState<string | null>(null);

  // Fetch tokens for selected date range (all except CANCELLED — status filtered client-side)
  const fetchTokens = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page: '1', page_size: '100' });
      if (dateFrom) params.set('date_from', dateFrom);
      if (dateTo) params.set('date_to', dateTo);
      const { data } = await api.get<TokenListResponse>(`/api/v1/tokens?${params}`);
      setTokens(data.items.filter(t => t.status !== 'CANCELLED'));
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [dateFrom, dateTo]);

  useEffect(() => { fetchTokens(); }, [fetchTokens]);

  // Auto-refresh every 15s
  useEffect(() => {
    const id = setInterval(() => { if (!weightOpen) fetchTokens(); }, 15_000);
    return () => clearInterval(id);
  }, [fetchTokens, weightOpen]);

  // Client-side filter: search + status + measurement method
  const filtered = tokens.filter(t => {
    if (selectedStatuses.size > 0 && !selectedStatuses.has(t.status as TokenStatus)) return false;
    if (measurementFilter !== 'all' && t.weight_method !== measurementFilter) return false;
    if (search.trim()) {
      const q = search.toLowerCase();
      const vehicleMatch = t.vehicle_no.toLowerCase().includes(q);
      const partyMatch = t.party?.name.toLowerCase().includes(q) ?? false;
      const materialMatch = t.product?.name.toLowerCase().includes(q) ?? false;
      if (!vehicleMatch && !partyMatch && !materialMatch) return false;
    }
    return true;
  });

  // Counts for filter chip badges
  const volumeCount = tokens.filter(t => t.weight_method === 'volume').length;
  const bridgeCount = tokens.filter(t => t.weight_method !== 'volume').length;

  function openWeight(token: Token) {
    setWeightToken(token);
    setWeightStage(token.status === 'OPEN' ? 'first' : 'second');
    setWeightOpen(true);
  }

  function handleTokenCreated(token: Token) {
    setTokens(prev => [token, ...prev]);
    // Skip the weight-capture dialog for volume-based tokens — they come back
    // already COMPLETED (single-call workflow). Only weighbridge tokens (status
    // OPEN or FIRST_WEIGHT) need the bridge weighment popup.
    if (token.status === 'COMPLETED' || token.status === 'CANCELLED') {
      return;
    }
    openWeight(token);
  }

  function handleWeightDone(updated: Token) {
    if (updated.status === 'CANCELLED') {
      setTokens(prev => prev.filter(t => t.id !== updated.id));
    } else {
      setTokens(prev => prev.map(t => t.id === updated.id ? updated : t));
    }
  }

  async function cancelToken(id: string) {
    if (!confirm('Cancel this token?')) return;
    try {
      await api.post<Token>(`/api/v1/tokens/${id}/cancel`);
      setTokens(prev => prev.filter(t => t.id !== id));
    } catch { /* ignore */ }
  }

  // # | Vehicle (10-char Indian plates) | Party | Material | Gross | Tare | Net | Action
  // Column widths. Party + Material use minmax(MIN, 1fr) so they never collapse
  // below MIN — without this, when the right pane is squeezed by the resizable
  // split the 1fr columns shrink to zero and `break-words` falls back to
  // character-level wrapping (e.g. "T o u r N o i d a" rendered vertically).
  // Weight columns widened slightly so "10.000 MT / 235 CFT" fits on one line.
  const COLS = '48px 110px minmax(140px, 1.4fr) minmax(110px, 1fr) 80px 80px 160px 60px';

  return (
    <div className="h-[calc(100vh-7rem)] overflow-hidden">
      <ResizableSplit
        direction="horizontal"
        defaultSize={30}
        minSize={20}
        maxSize={60}
        storageKey="tokens.formSplit"
      >
        {/* ==================== LEFT pane ==================== */}
        <div className="h-full flex flex-col gap-2 overflow-hidden pr-1">
          <ScaleStatus />
          <CreateTokenForm onCreated={handleTokenCreated} />
        </div>

        {/* ==================== RIGHT pane ==================== */}
        <div className="h-full flex flex-col overflow-hidden min-w-0 pl-1">
          <ResizableSplit
            direction="vertical"
            defaultSize={45}
            minSize={15}
            maxSize={80}
            storageKey="tokens.camerasSplit"
          >
            {/* ---- TOP — Live Cameras ---- */}
            <div className="h-full grid grid-cols-2 gap-3 min-h-0 pb-1">
              <CameraPanel cameraId="front" label="Front Camera" />
              <CameraPanel cameraId="top" label="Top Camera" />
            </div>

            {/* ---- BOTTOM — Token List ---- */}
            <div className="h-full rounded-xl border bg-card shadow-sm flex flex-col min-h-0 overflow-hidden mt-1">

          {/* Header row */}
          <div className="flex items-center gap-2 px-3 py-2 border-b bg-muted/30 shrink-0 flex-wrap">
            <div className="min-w-0 mr-auto">
              <p className="text-sm font-semibold">
                {dateFrom === today() && dateTo === today() ? "Today's Tokens" : 'Token List'}
              </p>
              <p className="text-[10px] text-muted-foreground">
                {filtered.length} of {tokens.length} · {tokens.filter(canWeigh).length} active
              </p>
            </div>

            {/* Date range */}
            <div className="flex items-center gap-1 shrink-0">
              <input
                type="date"
                className="h-7 rounded-md border border-input bg-background px-2 text-xs"
                value={dateFrom}
                onChange={e => setDateFrom(e.target.value)}
              />
              <span className="text-xs text-muted-foreground">–</span>
              <input
                type="date"
                className="h-7 rounded-md border border-input bg-background px-2 text-xs"
                value={dateTo}
                onChange={e => setDateTo(e.target.value)}
              />
              {(dateFrom !== today() || dateTo !== today()) && (
                <button
                  className="text-[10px] text-muted-foreground hover:text-foreground px-1 underline underline-offset-2"
                  onClick={() => { setDateFrom(today()); setDateTo(today()); }}
                >
                  Today
                </button>
              )}
            </div>

            {/* Search */}
            <div className="relative w-44 shrink-0">
              <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground" />
              <Input
                className="pl-6 h-7 text-xs"
                placeholder="Vehicle / Party / Material…"
                value={search}
                onChange={e => setSearch(e.target.value)}
              />
            </div>

            <Button
              variant="ghost"
              size="sm"
              onClick={fetchTokens}
              className="text-muted-foreground h-7 gap-1 text-xs shrink-0"
            >
              <RefreshCw className={cn('h-3 w-3', loading && 'animate-spin')} />
              Refresh
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="text-muted-foreground h-7 gap-1 text-xs shrink-0"
              disabled={filtered.length === 0}
              onClick={() => {
                const headers = ['Token No', 'Date', 'Vehicle', 'Method', 'Party', 'Material', 'Gross (MT)', 'Tare (MT)', 'Net (MT)', 'Net (CFT)', 'Volume (CFT)', 'Status'];
                const rows = filtered.map(t => {
                  // bulk_density is kg/CFT, so CFT = kg ÷ kg_per_cft
                  const bd = t.product?.bulk_density;
                  const cft = (t.net_weight != null && bd && Number(bd) > 0)
                    ? (Number(t.net_weight) / Number(bd)).toFixed(2)
                    : '';
                  return [
                    t.token_no != null ? String(t.token_no) : '',
                    t.token_date,
                    t.vehicle_no,
                    t.weight_method ?? 'weighbridge',
                    t.party?.name ?? '',
                    t.product?.name ?? '',
                    t.gross_weight != null ? (Number(t.gross_weight) / 1000).toFixed(3) : '',
                    t.tare_weight != null ? (Number(t.tare_weight) / 1000).toFixed(3) : '',
                    t.net_weight != null ? (Number(t.net_weight) / 1000).toFixed(3) : '',
                    cft,
                    t.volume_cft != null ? Number(t.volume_cft).toFixed(2) : '',
                    t.status,
                  ];
                });
                downloadCsv(`tokens-${new Date().toISOString().slice(0,10)}`, [headers, ...rows]);
              }}
              title="Download currently-filtered tokens as CSV"
            >
              <Download className="h-3 w-3" />
              CSV
            </Button>
          </div>

          {/* Status filter pills */}
          <div className="px-3 py-1.5 border-b bg-muted/10 shrink-0 flex flex-wrap items-center gap-x-3 gap-y-1">
            <StatusFilterPills selected={selectedStatuses} onChange={setSelectedStatuses} />
            <span className="text-[9px] text-muted-foreground/60 select-none">|</span>
            <div className="flex gap-1">
              {([
                { key: 'all',         label: 'All Methods', count: tokens.length },
                { key: 'weighbridge', label: 'Weighbridge',  count: bridgeCount  },
                { key: 'volume',      label: 'Volume',       count: volumeCount  },
              ] as const).map(opt => (
                <button
                  key={opt.key}
                  type="button"
                  onClick={() => setMeasurementFilter(opt.key)}
                  className={cn(
                    'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium transition-all',
                    measurementFilter === opt.key
                      ? (opt.key === 'volume'
                          ? 'bg-amber-100 text-amber-800 border-amber-300 ring-1 ring-amber-300'
                          : opt.key === 'weighbridge'
                            ? 'bg-blue-100 text-blue-800 border-blue-300 ring-1 ring-blue-300'
                            : 'bg-muted text-foreground border-border ring-1 ring-foreground/20')
                      : 'border-border bg-muted/30 text-muted-foreground opacity-60 hover:opacity-100'
                  )}
                >
                  {opt.label}
                  <span className={cn(
                    'rounded px-1 text-[9px]',
                    measurementFilter === opt.key ? 'bg-white/60' : 'bg-muted-foreground/10',
                  )}>
                    {opt.count}
                  </span>
                </button>
              ))}
            </div>
          </div>

          {/* Table header */}
          <div
            className="grid gap-x-1 px-3 py-1.5 border-b bg-muted/20 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground shrink-0"
            style={{ gridTemplateColumns: COLS }}
          >
            <div>#</div>
            <div>Vehicle</div>
            <div>Party</div>
            <div>Material</div>
            <div className="text-right">Gross (MT)</div>
            <div className="text-right">Tare (MT)</div>
            <div className="text-right">Net (MT)</div>
            <div className="text-center">Act</div>
          </div>

          {/* Table body */}
          <div className="overflow-y-auto flex-1">
            {loading && tokens.length === 0 ? (
              <div className="flex items-center justify-center py-10">
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              </div>
            ) : filtered.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-10 px-4 text-center">
                <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-muted">
                  <Scale className="h-6 w-6 text-muted-foreground/40" />
                </div>
                <p className="text-xs font-semibold">No tokens match</p>
                <p className="mt-0.5 text-[10px] text-muted-foreground">
                  Adjust the search or status filters above.
                </p>
              </div>
            ) : (
              <div className="divide-y">
                {filtered.map(token => {
                  const active = canWeigh(token);
                  return (
                  <div
                    key={token.id}
                    className={cn(
                      'grid items-center gap-x-1 px-3 py-2 hover:bg-muted/20 transition-colors cursor-pointer',
                      active && 'bg-amber-50/40 border-l-2 border-l-amber-400',
                      token.status === 'COMPLETED' && 'opacity-60'
                    )}
                    style={{ gridTemplateColumns: COLS }}
                    onClick={() => setTokenModalId(token.id)}
                  >
                    {/* Token # */}
                    <div className="min-w-0">
                      <p className="font-bold text-primary text-xs whitespace-nowrap">
                        {token.token_no != null ? `#${token.token_no}` : <span className="text-muted-foreground italic">—</span>}
                      </p>
                      <p className="text-[10px] text-muted-foreground capitalize">{token.token_type}</p>
                    </div>

                    {/* Vehicle — Indian plates: MH12AB1234 (10 chars), no break */}
                    <div className="min-w-0">
                      <div className="flex items-center gap-1">
                        <p className="font-mono font-semibold text-xs tracking-wide whitespace-nowrap overflow-hidden text-ellipsis" title={token.vehicle_no}>
                          {token.vehicle_no}
                        </p>
                        {token.weight_method === 'volume' && (
                          <span
                            title={`Volume-based: ${token.volume_cft != null ? Number(token.volume_cft).toFixed(2) + ' CFT' : '?'}`}
                            className="shrink-0 inline-flex items-center rounded border border-amber-300 bg-amber-100 px-1 text-[8px] font-bold text-amber-800 leading-tight"
                          >
                            VOL
                          </span>
                        )}
                      </div>
                      {token.vehicle_type && (
                        <p className="text-[10px] capitalize text-muted-foreground leading-tight">
                          {token.vehicle_type.replace(/_/g, ' ')}
                        </p>
                      )}
                    </div>

                    {/* Party — single line with ellipsis; full name on hover. */}
                    <div className="min-w-0">
                      {token.party
                        ? <p className="text-xs truncate" title={token.party.name}>{token.party.name}</p>
                        : <p className="text-muted-foreground text-xs">—</p>
                      }
                    </div>

                    {/* Material — single line with ellipsis; full name on hover. */}
                    <div className="min-w-0">
                      {token.product
                        ? <p className="text-xs truncate text-muted-foreground" title={token.product.name}>{token.product.name}</p>
                        : <p className="text-muted-foreground text-xs">—</p>
                      }
                    </div>

                    {/* Weights in MT — never wrap */}
                    <div className="text-right font-mono text-xs text-muted-foreground whitespace-nowrap">{mtFmt(token.gross_weight)}</div>
                    <div className="text-right font-mono text-xs text-muted-foreground whitespace-nowrap">{mtFmt(token.tare_weight)}</div>
                    <div className="text-right font-mono text-xs font-bold whitespace-nowrap" title={dualFmt(token.net_weight, token.product?.bulk_density)}>
                      {token.net_weight != null
                        ? <span className="text-primary">{dualFmt(token.net_weight, token.product?.bulk_density)}</span>
                        : <span className="text-muted-foreground">—</span>
                      }
                    </div>

                    {/* Actions — centered, stop row click */}
                    <div className="flex items-center justify-center gap-0.5 shrink-0" onClick={e => e.stopPropagation()}>
                      {active && (
                        <Button
                          size="icon"
                          variant="ghost"
                          className="h-6 w-6 text-amber-600 hover:text-amber-700 hover:bg-amber-100 shrink-0"
                          title="Record weight"
                          onClick={() => openWeight(token)}
                        >
                          <Scale className="h-3.5 w-3.5" />
                        </Button>
                      )}
                      {token.status === 'COMPLETED' && (
                        <>
                          <CheckCircle2 className="h-4 w-4 text-green-500 shrink-0" />
                          <PrintButton url={`/api/v1/tokens/${token.id}/print`} iconOnly />
                        </>
                      )}
                      {isAdmin && active && (
                        <Button
                          size="icon"
                          variant="ghost"
                          className="h-6 w-6 text-muted-foreground hover:text-destructive shrink-0"
                          title="Cancel token"
                          onClick={() => cancelToken(token.id)}
                        >
                          <XCircle className="h-3.5 w-3.5" />
                        </Button>
                      )}
                    </div>
                  </div>
                  );
                })}
              </div>
            )}
          </div>
            </div>
          </ResizableSplit>
        </div>
      </ResizableSplit>

      {/* ==================== DIALOGS ==================== */}
      <WeightCaptureDialog
        token={weightToken}
        weightStage={weightStage}
        open={weightOpen}
        onClose={() => { setWeightOpen(false); fetchTokens(); }}
        onDone={handleWeightDone}
      />
      <TokenDetailModal
        tokenId={tokenModalId}
        onClose={() => setTokenModalId(null)}
      />
    </div>
  );
}
