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
  AlertCircle, RefreshCw, Camera, Download, Plus, Settings2,
} from 'lucide-react';
import { PrintButton } from '@/components/PrintButton';
import { downloadCsv } from '@/components/DataTable';
import ResizableSplit from '@/components/ResizableSplit';
import CreditStatusBanner from '@/components/CreditStatusBanner';
import { toast } from 'sonner';
import { enqueueToken } from '@/lib/offlineQueue';
import { cacheMasters, readCachedMasters } from '@/lib/mastersCache';
import { fmtKg, displayToKg, weightUnitLabel, weightUnit } from '@/lib/weightUnit';
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
import LocalScaleBadge from '@/components/LocalScaleBadge';
import { useAuth, moduleEnabled, getTenantIndustry } from '@/hooks/useAuth';
import { useIsMobile } from '@/hooks/useIsMobile';
import api from '@/services/api';
import type { Token, TokenListResponse, Party, Product, Vehicle, GatePass, SnapshotResult, TokenSnapshotsResponse, CustomFieldDefinition, Agent } from '@/types';
import CustomFieldsInput from '@/components/CustomFieldsInput';
import { cn } from '@/lib/utils';
import { TokenDetailModal } from '@/components/TokenDetailModal';
import { useTranslation } from 'react-i18next';

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

const TOKEN_COL_DEFS = [
  { key: 'token_no', label: '#',           width: '48px',                 alwaysVisible: true  },
  { key: 'vehicle',  label: 'Vehicle',     width: '110px',                alwaysVisible: true  },
  { key: 'party',    label: 'Party',       width: 'minmax(140px, 1.4fr)', alwaysVisible: false },
  { key: 'product',  label: 'Material',    width: 'minmax(110px, 1fr)',   alwaysVisible: false },
  { key: 'gross',    label: 'Gross',       width: '80px',                 alwaysVisible: false },
  { key: 'tare',     label: 'Tare',        width: '80px',                 alwaysVisible: false },
  { key: 'net',      label: 'Net',         width: '160px',                alwaysVisible: true  },
  { key: 'actions',  label: 'Actions',     width: '60px',                 alwaysVisible: true  },
] as const;

type TokenColKey = typeof TOKEN_COL_DEFS[number]['key'];
const DEFAULT_TOKEN_COLS: TokenColKey[] = ['token_no', 'vehicle', 'party', 'product', 'gross', 'tare', 'net', 'actions'];
const TOKEN_COLS_LS = 'dt.tokens-v1.visible';


// Weight values are stored in kg in the DB. UI displays the tenant's unit
// (MT, or Qtl for maize) via the shared weightUnit helper.
function wFmt(v: number | null | undefined) {
  if (v == null) return '—';
  return fmtKg(v, 4);
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
  const { t } = useTranslation();
  const { reading, formattedMT, isLocalSource } = useWeight();
  return (
    <div className={cn(
      'flex items-center justify-between rounded-lg border px-3 py-2 text-sm transition-colors',
      reading.scale_connected
        ? reading.is_stable ? 'border-green-400 bg-green-50' : 'border-amber-300 bg-amber-50'
        : 'border-border bg-muted/30'
    )}>
      <div className="flex items-center gap-2">
        <Scale className={cn('h-4 w-4', reading.scale_connected ? 'text-green-600' : 'text-muted-foreground')} />
        <span className="text-xs text-muted-foreground font-medium">{t('token.scaleLabel')}</span>
        {reading.scale_connected
          ? <span className="flex items-center gap-1 text-xs text-green-600"><Wifi className="h-3 w-3" />{t('token.scaleLive')}</span>
          : <span className="flex items-center gap-1 text-xs text-red-500"><WifiOff className="h-3 w-3" />{t('token.scaleOffline')}</span>
        }
        {isLocalSource && <LocalScaleBadge />}
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
            {reading.is_stable ? `${t('token.scaleStable')} ${reading.stable_duration_sec.toFixed(1)}s` : t('token.scaleStabilising')}
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

// Tyre-count → default load volume in CFT. Industry-standard capacities for Indian aggregate trucks.
const TYRE_VOLUME_CFT: Record<number, number> = {
  4: 106,   // Mini-truck / pickup (Tata Ace, Bolero pickup)
  6: 247,   // Small truck (Eicher Pro 1110)
  8: 353,   // Medium truck
  10: 459,  // Heavy truck (Eicher 6028, Ashok Leyland 1616)
  12: 600,  // Multi-axle
};
const TYRE_OPTIONS = [4, 6, 8, 10, 12];

// Volume billing units the operator can choose (canonical storage stays CFT).
const CFT_PER_M3 = 35.3147;
const CFT_PER_BRASS = 100;
const VOLUME_UNITS = ['CFT', 'CBM', 'BRASS'] as const;
const VOLUME_UNIT_LABEL: Record<string, string> = { CFT: 'Cubic Feet (CFT)', CBM: 'Cubic Meter (CBM)', BRASS: 'Brass' };
const UNIT_SHORT: Record<string, string> = { CFT: 'CFT', CBM: 'CBM', BRASS: 'Brass' };
// Operator-selectable payment modes → invoice tax type (cash = Bill of Supply, rest = GST)
const PAYMENT_MODE_LABEL: Record<string, string> = { cash: 'Cash', credit: 'Credit', upi: 'UPI', bank_transfer: 'Bank' };
function toCft(qty: number, unit: string): number {
  if (unit === 'CBM') return qty * CFT_PER_M3;
  if (unit === 'BRASS') return qty * CFT_PER_BRASS;
  return qty;
}
function fromCft(cft: number, unit: string): number {
  if (unit === 'CBM') return cft / CFT_PER_M3;
  if (unit === 'BRASS') return cft / CFT_PER_BRASS;
  return cft;
}
const round3 = (n: number) => Number(n.toFixed(3));

function CreateTokenForm({ onCreated }: CreateFormProps) {
  const { t } = useTranslation();
  const [form, setForm] = useState({
    vehicle_no: '',
    vehicle_type: '',
    token_type: 'sale',
    direction: 'outbound',
    party_id: '',
    product_id: '',
    vehicle_id: '',
    gate_pass_id: '',
    remarks: '',
    transit_pass_id: '',   // P1: link purchase token to its royalty/transit pass
    vehicle_rent: '',      // optional payment to truck owner per trip
    agent_id: '',          // broker/dalal — carried to the invoice for commission
    billing_unit: '',      // operator-chosen billing unit ('' = auto = product's unit)
    rate: '',              // ₹ per billing_unit (prefilled from customer-wise/default price, editable)
    payment_mode: '',      // cash | credit | upi | bank_transfer — drives the invoice tax type
  });
  const [rateSource, setRateSource] = useState<'party' | 'default' | 'none'>('none');
  // Volume-based weighment (skips the bridge)
  const [weightMethod, setWeightMethod] = useState<'weighbridge' | 'volume'>('weighbridge');
  const [volumeValue, setVolumeValue] = useState('');
  const [tyreCount, setTyreCount] = useState<number | null>(null);   // 4/6/8/10/12 or null
  // Owner-defined custom attributes (Moisture %, Quality grade…) captured per weighment
  const [customDefs, setCustomDefs] = useState<CustomFieldDefinition[]>([]);
  const [customValues, setCustomValues] = useState<Record<string, unknown>>({});
  useEffect(() => {
    const ind = getTenantIndustry();
    api.get<CustomFieldDefinition[]>('/api/v1/custom-fields?entity_type=token')
      .then(async r => {
        let defs = r.data;
        // First-run: seed the industry's recommended fields (e.g. maize →
        // Moisture % + Quality grade) so they show on the form + slip without a
        // separate setup step. Idempotent; non-admins get a 403 and just skip.
        if (defs.length === 0 && ind && ind !== 'generic') {
          try {
            const seeded = await api.post<CustomFieldDefinition[]>(
              `/api/v1/custom-fields/seed-defaults?industry=${encodeURIComponent(ind)}`,
            );
            if (seeded.data.length) defs = seeded.data;
          } catch { /* not admin or no defaults — ignore */ }
        }
        setCustomDefs(defs);
      })
      .catch(() => setCustomDefs([]));
  }, []);

  // Picking a tyre count auto-fills the volume field with the standard capacity.
  function pickTyreCount(n: number) {
    setTyreCount(n);
    // Auto-fill the quantity in the currently-selected volume unit (operator can still overwrite).
    const u = form.billing_unit || 'CFT';
    setVolumeValue(String(round3(fromCft(TYRE_VOLUME_CFT[n] ?? 0, u))));
  }

  // Weighbridge bills in the tenant's weight unit (MT for crushers, Qtl for
  // maize); Volume defaults to CFT (operator can switch to CBM / Brass). Keeps
  // billing_unit in step with the measurement method.
  const weighUnit = weightUnit().code; // 'MT' | 'QUINTAL'
  useEffect(() => {
    setForm(f => {
      if (weightMethod === 'weighbridge') return f.billing_unit === weighUnit ? f : { ...f, billing_unit: weighUnit };
      return (VOLUME_UNITS as readonly string[]).includes(f.billing_unit) ? f : { ...f, billing_unit: 'CFT' };
    });
  }, [weightMethod, weighUnit]);

  // When the operator switches volume unit, convert the entered quantity so the
  // physical volume stays the same (e.g. 600 CFT ⇄ 6 Brass).
  function changeVolumeUnit(next: string) {
    const cur = form.billing_unit || 'CFT';
    const q = parseFloat(volumeValue || '0');
    if (q > 0 && cur !== next) setVolumeValue(String(round3(fromCft(toCft(q, cur), next))));
    setForm(f => ({ ...f, billing_unit: next }));
  }

  // Today's open gate passes — optional link before token creation
  const [openGatePasses, setOpenGatePasses] = useState<GatePass[]>([]);
  const [gpLoadError, setGpLoadError] = useState<string | null>(null);

  // P1: active transit/royalty passes for purchase tokens
  const [activePasses, setActivePasses] = useState<{ id: string; pass_no: string; balance_mt: number | string }[]>([]);
  const [passWarning, setPassWarning] = useState('');

  const [parties, setParties] = useState<Party[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
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

  const loadGatePasses = useCallback(async () => {
    setGpLoadError(null);
    try {
      const { data } = await api.get<{ items: GatePass[]; total: number }>('/api/v1/gate/passes', {
        params: { unlinked: true, status: 'inside', page_size: 200 },
      });
      setOpenGatePasses(data.items ?? []);
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string }; status?: number }; message?: string };
      const detail = e?.response?.data?.detail ?? e?.message ?? 'Network error';
      setGpLoadError(`[${e?.response?.status ?? 'ERR'}] ${detail}`);
      setOpenGatePasses([]);
    }
  }, []);

  useEffect(() => {
    Promise.all([
      api.get<{ items: Party[] }>('/api/v1/parties?page_size=200'),
      api.get<Product[]>('/api/v1/products'),
      api.get<{ items: Vehicle[] } | Vehicle[]>('/api/v1/vehicles?page_size=200'),
    ]).then(([p, pr, v]) => {
      const partyList = Array.isArray(p.data) ? p.data : (p.data.items ?? []);
      const productList = Array.isArray(pr.data) ? pr.data : (pr.data as { items: Product[] }).items ?? [];
      const vData = v.data;
      const vehicleList = Array.isArray(vData) ? vData : (vData as { items: Vehicle[] }).items ?? [];
      setParties(partyList);
      setProducts(productList);
      setVehicles(vehicleList);
      // Refresh the offline cache so the form stays fillable through an outage.
      cacheMasters('parties', partyList);
      cacheMasters('products', productList);
      cacheMasters('vehicles', vehicleList);
    }).catch(() => {
      // Offline / cloud unreachable → fall back to the last-known-good masters so
      // the operator can still pick a party/product and queue the token.
      setParties(readCachedMasters<Party>('parties'));
      setProducts(readCachedMasters<Product>('products'));
      setVehicles(readCachedMasters<Vehicle>('vehicles'));
    });
    api.get<{ items: Agent[] }>('/api/v1/agents?page_size=500')
      .then(r => setAgents(r.data.items ?? [])).catch(() => setAgents([]));
    loadGatePasses();
  }, [loadGatePasses]);

  function resetForm() {
    setForm({ vehicle_no: '', vehicle_type: '', token_type: 'sale', direction: 'outbound', party_id: '', product_id: '', vehicle_id: '', gate_pass_id: '', remarks: '', transit_pass_id: '', vehicle_rent: '', agent_id: '', billing_unit: weightMethod === 'weighbridge' ? weightUnit().code : 'CFT', rate: '', payment_mode: '' });
    setRateSource('none');
    setCustomValues({});
    setVehicleSearch('');
    setSelectedVehicle(null);
    setVolumeValue('');
    setTyreCount(null);
    setActivePasses([]);
    setPassWarning('');
    setError('');
  }

  // Selected product (used for volume mode). bulk_density is kg/CFT.
  const selectedProduct = form.product_id ? products.find(p => p.id === form.product_id) ?? null : null;
  const volumeInput = parseFloat(volumeValue || '0');
  // The operator enters the quantity in the chosen volume unit; convert to the
  // canonical CFT for storage + weight computation.
  const volUnit = form.billing_unit || 'CFT';
  const volumeCft = weightMethod === 'volume' ? toCft(volumeInput, volUnit) : volumeInput;
  // weight_kg = volume_cft × bulk_density(kg/CFT)
  const computedWeightKg = selectedProduct?.bulk_density && volumeCft > 0
    ? volumeCft * Number(selectedProduct.bulk_density)
    : 0;

  const selectedParty = form.party_id ? parties.find(p => p.id === form.party_id) ?? null : null;

  // Prefill the material price for the current party + product + unit: the
  // customer-wise rate if one is set, otherwise the product default. The operator
  // can override the value; changing party/product/unit re-fetches it.
  useEffect(() => {
    if (!form.product_id) { setRateSource('none'); return; }
    const unit = form.billing_unit || undefined;
    let cancelled = false;
    (async () => {
      try {
        if (form.party_id) {
          const { data } = await api.get<{ rate: number; source: string }>(
            `/api/v1/parties/${form.party_id}/effective-rate/${form.product_id}`,
            { params: { unit } },
          );
          if (cancelled) return;
          setRateSource(data.source === 'party_rate' ? 'party' : (data.rate > 0 ? 'default' : 'none'));
          setForm(f => ({ ...f, rate: data.rate ? String(data.rate) : '' }));
        } else {
          // No party (walk-in) → fall back to the product's base default rate.
          const dr = selectedProduct?.default_rate;
          if (cancelled) return;
          setRateSource(dr ? 'default' : 'none');
          setForm(f => ({ ...f, rate: dr ? String(dr) : '' }));
        }
      } catch { if (!cancelled) setRateSource('none'); }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.party_id, form.product_id, form.billing_unit]);

  // Default the payment mode from the party (cash → Cash / Bill of Supply;
  // online → UPI) whenever the party changes. The operator can override per token;
  // the override persists until a different party is selected.
  useEffect(() => {
    if (!selectedParty) return;
    const def = selectedParty.default_payment_mode === 'online' ? 'upi' : 'cash';
    setForm(f => ({ ...f, payment_mode: def }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.party_id]);

  // The unit the rate is priced in, and its short label, for the Price field.
  const billUnitCode = weightMethod === 'volume' ? (form.billing_unit || 'CFT') : weightUnit().code;
  const billUnitShort = UNIT_SHORT[billUnitCode] ?? billUnitCode;
  const rateNum = parseFloat(form.rate || '0');

  const handleTypeChange = (type: string) => {
    setForm(f => ({ ...f, token_type: type, direction: type === 'purchase' ? 'inbound' : 'outbound', party_id: '', transit_pass_id: '', vehicle_rent: '' }));
    if (type === 'purchase' && moduleEnabled('royalty')) {
      api.get('/api/v1/royalty/passes', { params: { status: 'active', page_size: 100 } })
        .then(r => {
          const passes = (r.data.items ?? []).map((p: { id: string; pass_no: string; balance_mt: number | string }) => ({
            id: p.id, pass_no: p.pass_no, balance_mt: p.balance_mt,
          }));
          setActivePasses(passes);
          setPassWarning(passes.length === 0 ? 'No active transit passes found. Purchase loads may be unaccounted.' : '');
        })
        .catch(() => { setActivePasses([]); });
    } else {
      setActivePasses([]);
      setPassWarning('');
    }
  };

  // Normalize a vehicle number for fuzzy matching: strip spaces, dashes, dots → uppercase.
  // Handles variants like "HP-38-G-1671" vs "HP38G1671" vs "HP 38G1671".
  const normalizeVno = (s: string) => s.toUpperCase().replace(/[\s\-./]/g, '');

  // Auto-select gate pass when vehicle number is set and exactly one open pass matches
  useEffect(() => {
    const vno = normalizeVno(form.vehicle_no.trim());
    if (!vno || form.gate_pass_id) return;
    const matches = openGatePasses.filter(gp => normalizeVno(gp.vehicle_no ?? '') === vno);
    if (matches.length === 1) {
      setForm(f => ({ ...f, gate_pass_id: matches[0].id }));
    }
  }, [form.vehicle_no, openGatePasses]); // eslint-disable-line react-hooks/exhaustive-deps

  // When the operator types a vehicle number, re-fetch gate passes from the server
  // (debounced 600 ms). Without this, passes created by the gate guard AFTER the operator
  // opened this form would only appear after the 30-second polling interval — too late.
  // The existing auto-select effect above fires automatically once openGatePasses updates.
  const _gpRefreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    const vno = form.vehicle_no.trim();
    if (!vno || form.gate_pass_id) return;
    if (_gpRefreshTimer.current) clearTimeout(_gpRefreshTimer.current);
    _gpRefreshTimer.current = setTimeout(loadGatePasses, 600);
    return () => { if (_gpRefreshTimer.current) clearTimeout(_gpRefreshTimer.current); };
  }, [form.vehicle_no, form.gate_pass_id, loadGatePasses]);

  // Poll every 5 s while a vehicle number is entered (no gate pass selected yet), so a pass
  // the guard creates AFTER the operator opens the form appears within seconds. Falls back to
  // 30 s when vehicle_no is empty (the operator is still filling in other fields).
  useEffect(() => {
    if (form.gate_pass_id) return;
    const hasVno = form.vehicle_no.trim().length > 0;
    const id = setInterval(loadGatePasses, hasVno ? 5_000 : 30_000);
    return () => clearInterval(id);
  }, [form.gate_pass_id, form.vehicle_no, loadGatePasses]);

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
      if (!Number.isFinite(volumeInput) || volumeInput <= 0) {
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
          transit_pass_id: form.transit_pass_id || undefined,
          agent_id: form.agent_id || undefined,
          billing_unit: form.billing_unit || undefined,
          rate: form.rate ? Number(form.rate) : undefined,
          payment_mode: form.payment_mode || undefined,
          gate_pass_id: form.gate_pass_id || undefined,
          vehicle_rent: form.vehicle_rent ? Number(form.vehicle_rent) : undefined,
          remarks: form.remarks
            ? `${form.remarks}${tyreCount ? ` | ${tyreCount}-tyre truck` : ''}`
            : (tyreCount ? `${tyreCount}-tyre truck` : undefined),
          custom_fields: Object.keys(customValues).length ? customValues : undefined,
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
    const tokenPayload = {
      token_date: today(),
      vehicle_no: form.vehicle_no.trim().toUpperCase(),
      vehicle_type: form.vehicle_type || undefined,
      token_type: form.token_type,
      direction: form.direction,
      party_id: form.party_id || undefined,
      product_id: form.product_id || undefined,
      vehicle_id: form.vehicle_id || undefined,
      transit_pass_id: form.transit_pass_id || undefined,
      agent_id: form.agent_id || undefined,
      billing_unit: form.billing_unit || undefined,
      rate: form.rate ? Number(form.rate) : undefined,
      payment_mode: form.payment_mode || undefined,
      gate_pass_id: form.gate_pass_id || undefined,
      vehicle_rent: form.vehicle_rent ? Number(form.vehicle_rent) : undefined,
      remarks: form.remarks || undefined,
      custom_fields: Object.keys(customValues).length ? customValues : undefined,
    };
    try {
      if (!navigator.onLine) throw new Error('offline');
      // Short timeout: on a black-holed link (the tenant's real symptom) axios
      // would otherwise hang on the OS default (~2 min) with the spinner stuck
      // before the token could be queued offline.
      const { data } = await api.post<Token>('/api/v1/tokens', tokenPayload, { timeout: 10_000 });
      onCreated(data);
      resetForm();
    } catch (e: unknown) {
      // Offline OR network failure (request never reached the server) → queue it.
      const err = e as {
        response?: { status?: number; data?: { detail?: string | Array<{ msg: string; loc?: string[] }> } };
        message?: string;
      };
      const reached = err.response;
      if (!navigator.onLine || !reached) {
        enqueueToken('/api/v1/tokens', tokenPayload, tokenPayload.vehicle_no);
        toast.success(`Saved offline — ${tokenPayload.vehicle_no} will sync when the connection returns`);
        resetForm();
      } else {
        // Surface the REAL backend error (409 duplicate active token, 422 validation,
        // 500 server) instead of a generic "try again" that hides the cause.
        const detail = err.response?.data?.detail;
        let msg: string;
        if (typeof detail === 'string') {
          msg = detail;
        } else if (Array.isArray(detail)) {
          msg = detail.map(d => `${(d.loc ?? []).join('.')}: ${d.msg}`).join(' · ');
        } else {
          msg = err.message ?? 'Failed to create token';
        }
        const status = err.response?.status ?? '?';
        setError(`HTTP ${status}: ${msg}`);
        console.error('Token create failed:', err);
      }
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
            <p className="text-xl font-black text-white tracking-tight">{t('token.newToken')}</p>
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
          <Label className="text-xs">{t('token.tokenType')}</Label>
          <div className="grid grid-cols-2 gap-2">
            {[
              { value: 'sale',     label: t('token.sale'),     sub: t('token.outbound'), color: 'border-blue-400 bg-blue-50 text-blue-700' },
              { value: 'purchase', label: t('token.purchase'), sub: t('token.inbound'),  color: 'border-green-400 bg-green-50 text-green-700' },
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
          <Label className="text-xs">{t('token.vehicleNo')} <span className="text-destructive">*</span></Label>
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
              >{t('token.changeVehicle')}</button>
            </div>
          ) : (
            <div className="space-y-1.5">
              <div className="relative">
                <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
                <Input
                  className="pl-8 h-8 text-xs"
                  placeholder={t('token.vehicleSearch')}
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

        {/* Material — placed right after the vehicle number for fast entry. */}
        <div className="space-y-1">
          <Label className="text-xs">{t('token.product')}</Label>
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

        {/* Party */}
        <div className="space-y-1">
          <Label className="text-xs">{t('token.party')}</Label>
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
          {form.party_id && <CreditStatusBanner partyId={form.party_id} className="mt-1.5" />}
        </div>

        {/* P1: Transit / Royalty Pass — purchase tokens only, and only when the
            royalty module is on (mining; hidden for maize etc.) */}
        {form.token_type === 'purchase' && moduleEnabled('royalty') && (
          <div className="space-y-1">
            <Label className="text-xs">{t('token.transitPass')}</Label>
            {passWarning && (
              <p className="text-[11px] text-amber-600 flex items-center gap-1">
                <AlertCircle className="h-3 w-3 shrink-0" />{passWarning}
              </p>
            )}
            <Select
              value={form.transit_pass_id || '__none__'}
              onValueChange={v => setForm(f => ({ ...f, transit_pass_id: v === '__none__' ? '' : (v ?? '') }))}
            >
              <SelectTrigger className="h-8 text-xs">
                <span className="truncate text-left flex-1">
                  {form.transit_pass_id
                    ? (() => {
                        const p = activePasses.find(x => x.id === form.transit_pass_id);
                        return p ? `${p.pass_no} (bal ${Number(p.balance_mt).toFixed(2)} MT)` : '…';
                      })()
                    : <span className="text-muted-foreground">None (no auto-draw)</span>}
                </span>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__none__"><span className="text-muted-foreground">None</span></SelectItem>
                {activePasses.map(p => (
                  <SelectItem key={p.id} value={p.id}>
                    {p.pass_no}
                    <span className="text-muted-foreground text-xs ml-2">bal {Number(p.balance_mt).toFixed(2)} MT</span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}

        {/* Weighment method */}
        <div className="space-y-1">
          <Label className="text-xs">{t('token.weightMethod')}</Label>
          <div className="grid grid-cols-2 gap-2">
            {[
              { value: 'weighbridge', label: t('token.weighbridge'), sub: 'Gross + Tare' },
              { value: 'volume',      label: t('token.volume'),      sub: 'CFT × density' },
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

        {/* Units — right after the measurement method. Weighbridge locks to the
            tenant's weight unit; Volume lets the operator pick CFT / CBM / Brass. */}
        <div className="space-y-1">
          <Label className="text-xs">Units</Label>
          {weightMethod === 'weighbridge' ? (
            <div className="flex h-8 items-center rounded-md border bg-muted/40 px-3 text-xs font-medium text-muted-foreground">
              {weightUnitLabel()} <span className="ml-1.5 text-[10px]">(auto — weighbridge)</span>
            </div>
          ) : (
            <Select value={form.billing_unit || 'CFT'} onValueChange={v => changeVolumeUnit(v ?? 'CFT')}>
              <SelectTrigger className="h-8 text-xs">
                <span className="truncate text-left flex-1">{VOLUME_UNIT_LABEL[form.billing_unit] ?? 'Cubic Feet (CFT)'}</span>
              </SelectTrigger>
              <SelectContent>
                {VOLUME_UNITS.map(u => <SelectItem key={u} value={u}>{VOLUME_UNIT_LABEL[u]}</SelectItem>)}
              </SelectContent>
            </Select>
          )}
        </div>

        {/* Volume input (only in volume mode) */}
        {weightMethod === 'volume' && (
          <div className="space-y-3 rounded-lg border-2 border-amber-200 bg-amber-50/40 p-3">
            {/* Step 1: Pick tyre count → volume auto-fills */}
            <div className="space-y-1.5">
              <Label className="text-xs">{t('token.truckSizeTyre')}</Label>
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
                      tyre<br/>
                      {round3(fromCft(TYRE_VOLUME_CFT[n] ?? 0, volUnit))} {UNIT_SHORT[volUnit]}
                    </div>
                  </button>
                ))}
              </div>
              {tyreCount !== null && (
                <p className="text-[10px] text-amber-700">
                  Defaulted to {round3(fromCft(TYRE_VOLUME_CFT[tyreCount] ?? 0, volUnit))} {UNIT_SHORT[volUnit]} for a {tyreCount}-tyre truck. Adjust below if needed.
                </p>
              )}
            </div>

            {/* Step 2: Editable quantity (auto-filled from tyre count, can override) */}
            <div className="space-y-1">
              <Label className="text-xs">Quantity ({UNIT_SHORT[volUnit]}) <span className="text-destructive">*</span></Label>
              <div className="flex gap-2 items-center">
                <Input
                  type="number"
                  className="h-8 text-xs flex-1"
                  value={volumeValue}
                  onChange={e => { setVolumeValue(e.target.value); setTyreCount(null); }}
                  placeholder={`Pick a tyre count above, or type ${UNIT_SHORT[volUnit]} here`}
                  min="0"
                  step="0.1"
                />
                <span className="text-xs font-semibold text-muted-foreground px-2">{UNIT_SHORT[volUnit]}</span>
              </div>
            </div>

            {/* Step 3: Live calculation preview */}
            {!form.product_id ? (
              <p className="text-[10px] text-muted-foreground">Select a material above to compute weight.</p>
            ) : !selectedProduct?.bulk_density ? (
              <p className="text-[10px] text-destructive">
                Bulk density (kg/CFT) not set for {selectedProduct?.name}. Open Products → edit this product → set Bulk Density (typical: aggregate 1.5, sand 1.71, GSB 1.91).
              </p>
            ) : volumeInput <= 0 ? (
              <p className="text-[10px] text-muted-foreground">Pick a tyre count or enter a volume to see the computed weight.</p>
            ) : (
              <div className="rounded-md bg-white px-2.5 py-2 text-[10px] border">
                <div className="flex justify-between text-muted-foreground">
                  <span>Quantity</span>
                  <span>{volumeInput} {UNIT_SHORT[volUnit]}{volUnit !== 'CFT' ? ` = ${volumeCft.toFixed(2)} CFT` : ''}</span>
                </div>
                <div className="flex justify-between text-muted-foreground">
                  <span>× Density ({selectedProduct.name})</span>
                  <span>{Number(selectedProduct.bulk_density).toFixed(2)} kg/CFT</span>
                </div>
                <div className="mt-1 flex justify-between border-t pt-1 text-sm font-bold text-amber-700">
                  <span>= Net weight</span>
                  <span>{fmtKg(computedWeightKg, 3)}</span>
                </div>
              </div>
            )}

            <div className="text-[10px] text-muted-foreground bg-white rounded p-2 border">
              <strong>How this works:</strong> No weighbridge needed. One click creates the token,
              auto-completes it, and generates a draft invoice.
            </div>
          </div>
        )}

        {/* Price & Payment — operator sees/sets the material rate + payment mode.
            Rate is prefilled from the customer-wise price (or the product default);
            the payment mode decides GST Tax Invoice vs Bill of Supply. */}
        <div className="rounded-lg border bg-muted/20 p-3 space-y-2">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <div className="flex items-center justify-between">
                <Label className="text-xs">Rate (₹/{billUnitShort})</Label>
                {form.rate && rateSource !== 'none' && (
                  <span className={cn('text-[9px] px-1.5 py-0.5 rounded-full font-medium',
                    rateSource === 'party' ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-600')}>
                    {rateSource === 'party' ? 'customer rate' : 'default'}
                  </span>
                )}
              </div>
              <Input
                type="number" min="0" step="0.01" className="h-8 text-xs"
                value={form.rate}
                onChange={e => { setForm(f => ({ ...f, rate: e.target.value })); setRateSource('none'); }}
                placeholder="0.00"
              />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Payment mode</Label>
              <Select value={form.payment_mode || 'cash'} onValueChange={v => setForm(f => ({ ...f, payment_mode: v ?? 'cash' }))}>
                <SelectTrigger className="h-8 text-xs">
                  <span className="truncate text-left flex-1">{PAYMENT_MODE_LABEL[form.payment_mode] ?? 'Cash'}</span>
                </SelectTrigger>
                <SelectContent>
                  {Object.entries(PAYMENT_MODE_LABEL).map(([v, lbl]) => (
                    <SelectItem key={v} value={v}>{lbl}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <p className="text-[10px] text-muted-foreground">
            {form.payment_mode === 'cash'
              ? 'Cash → Bill of Supply (no GST).'
              : 'Credit / UPI / Bank → GST Tax Invoice.'}
            {rateNum > 0 && (
              <>
                {' '}
                {weightMethod === 'volume'
                  ? (volumeInput > 0
                      ? `≈ ₹${(rateNum * volumeInput).toLocaleString('en-IN', { maximumFractionDigits: 2 })} (${volumeInput} ${billUnitShort} × ₹${rateNum})`
                      : `₹${rateNum}/${billUnitShort}`)
                  : `₹${rateNum}/${billUnitShort} — amount = weight × rate on the invoice.`}
              </>
            )}
          </p>
        </div>

        {/* Gate Pass — optional, links to a guard-created entry from Gate Register */}
        {(() => {
          const vno = normalizeVno(form.vehicle_no.trim());
          // Passes whose vehicle_no exactly matches the entered number (after normalization)
          const exactMatches = vno
            ? openGatePasses.filter(gp => normalizeVno(gp.vehicle_no ?? '') === vno)
            : openGatePasses;
          const hasExactMatch = exactMatches.length > 0;
          // Always show all open passes in the dropdown — exact matches appear first.
          // This lets the operator manually select a pass even when vehicle numbers
          // differ by a typo (e.g. HP38G1671 vs HP38G1671G).
          const otherPasses = openGatePasses.filter(gp => !exactMatches.includes(gp));
          const allPassesInOrder = [...exactMatches, ...otherPasses];
          return (
            <div className="space-y-1">
              <div className="flex items-center justify-between">
                <Label className="text-xs font-semibold">
                  Gate Pass
                </Label>
                <button
                  type="button"
                  className="text-[11px] text-blue-600 hover:text-blue-800 transition-colors flex items-center gap-1 font-medium"
                  onClick={loadGatePasses}
                  title="Refresh gate passes from server"
                >
                  <RefreshCw className="h-3 w-3" />
                  Refresh
                </button>
              </div>

              {openGatePasses.length === 0 ? (
                // No open passes found — or API error
                <div className={cn(
                  'rounded border px-3 py-2 text-[11px]',
                  gpLoadError
                    ? 'border-red-300 bg-red-50 text-red-800'
                    : vno
                      ? 'border-amber-300 bg-amber-50 text-amber-800'
                      : 'border-dashed border-slate-200 bg-slate-50 text-slate-500'
                )}>
                  {gpLoadError
                    ? <><strong>Error loading gate passes:</strong> {gpLoadError}</>
                    : vno
                      ? <>
                          <strong>No open gate pass found for {form.vehicle_no}.</strong>
                          {' '}Check Gate Register — the pass must be status <em>Inside</em> and not yet linked to a token. Then click Refresh above.
                        </>
                      : 'Enter vehicle number to check for an existing gate pass.'}
                </div>
              ) : (
                <>
                  {vno && !hasExactMatch && !form.gate_pass_id && (
                    <div className="rounded border border-amber-200 bg-amber-50 px-2 py-1 text-[11px] text-amber-700">
                      No exact match for <strong>{vno}</strong> — select the correct pass below.
                    </div>
                  )}
                  {form.gate_pass_id && exactMatches.some(gp => gp.id === form.gate_pass_id) && (
                    <div className="rounded border border-emerald-200 bg-emerald-50 px-2 py-1 text-[11px] text-emerald-700 flex items-center gap-1.5">
                      <CheckCircle2 className="h-3 w-3 shrink-0" />
                      Gate pass auto-linked: <strong className="font-mono">{exactMatches.find(gp => gp.id === form.gate_pass_id)?.gate_pass_no}</strong>
                    </div>
                  )}
                  <Select
                    value={form.gate_pass_id || ''}
                    onValueChange={v => {
                      const gp = openGatePasses.find(g => g.id === v);
                      setForm(f => ({
                        ...f,
                        gate_pass_id: v ?? '',
                        vehicle_no: f.vehicle_no || (gp?.vehicle_no ?? ''),
                      }));
                    }}
                  >
                    <SelectTrigger className="h-8 text-xs">
                      <span className="truncate">
                        {form.gate_pass_id
                          ? (() => {
                              const gp = openGatePasses.find(g => g.id === form.gate_pass_id);
                              return gp ? `${gp.gate_pass_no} — ${gp.vehicle_no}` : 'Select gate pass';
                            })()
                          : hasExactMatch
                            ? `${exactMatches.length} pass${exactMatches.length !== 1 ? 'es' : ''} available — select…`
                            : `${openGatePasses.length} open pass${openGatePasses.length !== 1 ? 'es' : ''} — select…`
                        }
                      </span>
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="" className="text-xs text-muted-foreground">
                        — Skip (no gate pass) —
                      </SelectItem>
                      {allPassesInOrder.map(gp => (
                        <SelectItem key={gp.id} value={gp.id} className="text-xs">
                          <span className="font-mono font-semibold">{gp.gate_pass_no}</span>
                          <span className="ml-2">{gp.vehicle_no}</span>
                          {gp.status === 'exited' && (
                            <span className="ml-1.5 rounded bg-slate-100 px-1 py-0.5 text-[10px] text-slate-500">exited</span>
                          )}
                          {gp.driver_name && <span className="ml-1 text-muted-foreground">· {gp.driver_name}</span>}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </>
              )}
            </div>
          );
        })()}

        {/* Agent (broker/dalal) — after the gate pass; carried to the invoice for
            commission. Only shown when the tenant has agents configured. */}
        {agents.length > 0 && (
          <div className="space-y-1">
            <Label className="text-xs">Agent (broker)</Label>
            <Select
              value={form.agent_id || '__none__'}
              onValueChange={v => setForm(f => ({ ...f, agent_id: v === '__none__' ? '' : (v ?? '') }))}
            >
              <SelectTrigger className="h-8 text-xs">
                <span className="truncate text-left flex-1">
                  {form.agent_id
                    ? (agents.find(a => a.id === form.agent_id)?.name ?? '…')
                    : <span className="text-muted-foreground">None</span>}
                </span>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__none__"><span className="text-muted-foreground">None</span></SelectItem>
                {agents.map(a => <SelectItem key={a.id} value={a.id}>{a.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
        )}

        {/* Vehicle Rent */}
        <div className="space-y-1">
          <Label className="text-xs">Vehicle Rent ₹ <span className="text-muted-foreground">(optional)</span></Label>
          <Input
            className="h-8 text-xs"
            type="number"
            min="0"
            step="0.01"
            value={form.vehicle_rent}
            onChange={e => setForm(f => ({ ...f, vehicle_rent: e.target.value }))}
            placeholder="0.00"
          />
        </div>

        {/* Remarks */}
        <div className="space-y-1">
          <Label className="text-xs">{t('common.remarks')} <span className="text-muted-foreground">(optional)</span></Label>
          <Input
            className="h-8 text-xs"
            value={form.remarks}
            onChange={e => setForm(f => ({ ...f, remarks: e.target.value }))}
            placeholder="Driver name, challan no…"
          />
        </div>

        {/* Owner-defined custom attributes (Moisture %, Quality, …) */}
        {customDefs.length > 0 && (
          <CustomFieldsInput
            definitions={customDefs}
            values={customValues}
            onChange={(k, v) => setCustomValues(s => ({ ...s, [k]: v }))}
            compact
          />
        )}
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
          {weightMethod === 'volume' ? t('token.createTokenVolume') : t('token.startWeighment')}
        </Button>
      </div>

      {/* Quick-create Party dialog — opens from the + button next to Party dropdown */}
      <Dialog open={partyDialogOpen} onOpenChange={o => !o && setPartyDialogOpen(false)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{t('token.addParty')}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1">
              <Label className="text-xs">{t('token.partyType')}</Label>
              <div className="grid grid-cols-3 gap-1.5">
                {(['customer', 'supplier', 'both'] as const).map(pt => (
                  <button
                    key={pt}
                    type="button"
                    onClick={() => setQuickParty(q => ({ ...q, party_type: pt }))}
                    className={cn(
                      'rounded-md border-2 p-2 text-xs font-medium capitalize transition-all',
                      quickParty.party_type === pt
                        ? 'border-primary bg-primary/10 text-primary'
                        : 'border-border text-muted-foreground hover:border-primary/40'
                    )}
                  >
                    {t(`party.${pt}`)}
                  </button>
                ))}
              </div>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">{t('token.partyName')} <span className="text-destructive">*</span></Label>
              <Input
                autoFocus
                value={quickParty.name}
                onChange={e => setQuickParty(q => ({ ...q, name: e.target.value }))}
                placeholder="e.g. Rajesh Construction Co"
              />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">{t('party.phone')} <span className="text-muted-foreground">(optional)</span></Label>
              <Input
                value={quickParty.phone}
                onChange={e => setQuickParty(q => ({ ...q, phone: e.target.value }))}
                placeholder="10-digit mobile"
              />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">{t('party.gstin')} <span className="text-muted-foreground">(optional)</span></Label>
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
            <Button variant="outline" onClick={() => setPartyDialogOpen(false)}>{t('common.cancel')}</Button>
            <Button onClick={handleCreateParty} disabled={savingParty || !quickParty.name.trim()}>
              {savingParty ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Plus className="mr-2 h-4 w-4" />}
              {t('token.addParty')}
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

// Convert kg → display string ("x.xxx MT" / "x.xxx Qtl") for the live readout
function mtFromKg(kg: number) {
  return fmtKg(kg, 3);
}

function WeightCaptureDialog({ token, weightStage, open, onClose, onDone }: WeightDialogProps) {
  const { t } = useTranslation();
  const { reading, formattedMT, isLocalSource } = useWeight();
  const camerasEnabled = moduleEnabled('cameras');
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

  // Manual entry is in the tenant's display unit (MT, or Qtl for maize).
  // displayToKg converts to kg — the unit the backend stores and the bridge streams.
  const manualKg = manualMode ? displayToKg(manualWeight) : 0;
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

      onDone(data);
      // No camera module for this tenant → no snapshot capture; just close.
      if (!camerasEnabled) { onClose(); return; }
      setCapturePhase('capturing');
      const tokenId = token!.id;
      // Filter display to only the current weight stage — avoids duplicate camera
      // rows when both first_weight and second_weight snapshots exist on the token.
      const currentStage: SnapshotResult['weight_stage'] = weightStage === 'first' ? 'first_weight' : 'second_weight';
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
          setSnapshots(snaps.snapshots.filter(s => s.weight_stage === currentStage));
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
            {t('token.stageOf', { stage: stageNum, label: currentLabel })}
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
            {token.gate_pass_no && (
              <div className="flex items-center gap-2 mt-1 pt-1 border-t border-border/30">
                <span className="text-xs font-semibold text-emerald-700 bg-emerald-50 border border-emerald-200 rounded px-2 py-0.5 font-mono">
                  Gate Pass: {token.gate_pass_no}
                </span>
              </div>
            )}
          </div>

          {weightStage === 'second' && stage1Weight > 0 && (
            <div className="rounded-lg border-2 border-dashed border-muted-foreground/20 p-3">
              <p className="text-xs text-muted-foreground mb-1">{stage1Label} ({t('token.recorded')})</p>
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
                <span className="text-xs uppercase tracking-widest text-muted-foreground font-semibold">{t('token.scaleReading')}</span>
                {reading.scale_connected
                  ? <Badge variant="outline" className="border-green-500 text-green-600 text-[10px]">{t('token.liveStatus')}</Badge>
                  : <Badge variant="outline" className="border-red-400 text-red-500 text-[10px]">{t('token.offlineStatus')}</Badge>
                }
                {isLocalSource && <LocalScaleBadge />}
              </div>
              <div className={cn(
                'font-mono text-5xl font-black tabular-nums',
                reading.scale_connected
                  ? canCapture ? 'text-green-600' : 'text-amber-600'
                  : 'text-muted-foreground/40'
              )}>
                {reading.scale_connected ? formattedMT : `— . — — —  ${weightUnitLabel()}`}
              </div>
              <div className="h-5 mt-1">
                {reading.scale_connected && (
                  canCapture
                    ? <p className="text-xs text-green-600 font-semibold">✓ {t('token.scaleStable')} {reading.stable_duration_sec.toFixed(1)}s</p>
                    : <p className="text-xs text-amber-600 animate-pulse">{t('token.scaleStabilising')}</p>
                )}
              </div>
            </div>
          ) : (
            <div className="space-y-2">
              <Label>{t('token.enterWeightManual')} ({weightUnitLabel()})</Label>
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
                <p className="text-xs text-muted-foreground">{t('token.liveNetPreview')}</p>
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
            {manualMode ? t('token.useScaleInstead') : t('token.enterManuallyInstead')}
          </button>

          {capturePhase !== 'idle' && (
            <div className="rounded-lg border bg-muted/30 p-3 space-y-2">
              <div className="flex items-center gap-2 text-sm font-medium">
                {capturePhase === 'capturing' ? (
                  <><Loader2 className="h-4 w-4 animate-spin text-primary" /> {t('token.capturingImages')}</>
                ) : (
                  <><Camera className="h-4 w-4 text-green-600" /> {t('token.imagesCapured')}</>
                )}
              </div>
              {snapshots.map(s => (
                <div key={s.camera_id} className="flex items-center gap-2 text-xs">
                  <Camera className="h-3 w-3 text-muted-foreground shrink-0" />
                  <span className="font-medium capitalize">{s.camera_label || s.camera_id} View</span>
                  {s.capture_status === 'pending' && <span className="text-amber-600 ml-auto">{t('token.waiting')}</span>}
                  {s.capture_status === 'captured' && <span className="text-green-600 ml-auto">{t('token.captured')}</span>}
                  {s.capture_status === 'failed' && <span className="text-red-500 ml-auto">{t('token.failed')}</span>}
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
            {capturePhase !== 'idle' ? t('common.close') : t('common.cancel')}
          </Button>
          {capturePhase === 'idle' && hasStoredTare && (
            <Button
              variant="secondary"
              onClick={() => capture(storedTare, true)}
              disabled={saving}
              className="min-w-44"
              title={`Use vehicle's registered tare weight: ${fmtKg(storedTare)}`}
            >
              {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Truck className="mr-2 h-4 w-4" />}
              {t('token.useRegTare')} ({fmtKg(storedTare)})
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
                {canCapture ? t('token.captureWeight') : t('token.waiting')}
              </Button>
            ) : (
              <Button
                onClick={() => capture(displayToKg(manualWeight), true) /* display unit → kg */}
                disabled={saving || !manualWeight || parseFloat(manualWeight) <= 0}
                className="min-w-32"
              >
                {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {t('token.saveWeight')}
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
  wsPort: string;
}

function CameraPanel({ cameraId, label, wsPort }: CameraPanelProps) {
  const [status, setStatus] = useState<'connecting' | 'live' | 'error'>('connecting');
  const [imgSrc, setImgSrc] = useState('');
  const wsRef = useRef<WebSocket | null>(null);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);
  const prevBlobRef = useRef('');

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
// Weight formatters (tenant unit: MT, or Qtl for maize) + optional CFT
// ------------------------------------------------------------------ //
function mtFmt(v: number | null | undefined) {
  if (v == null) return '—';
  return fmtKg(v, 4);
}
/** Volume in the token's chosen billing unit (canonical storage stays CFT). */
function volFmt(cft: number | null | undefined, unit?: string | null): string {
  if (cft == null) return '—';
  const u = (unit || 'CFT').toUpperCase();
  if (u === 'CBM' || u === 'CUM') return `${(cft / CFT_PER_M3).toFixed(2)} CBM`;
  if (u === 'BRASS') return `${(cft / CFT_PER_BRASS).toFixed(2)} Brass`;
  return `${cft.toFixed(2)} CFT`;
}
/** Net quantity in the unit the token was actually recorded in — no cross-unit
 *  conversion. Volume tokens show their volume unit (CFT/CBM/Brass); weighed
 *  tokens show the tenant weight unit (MT, or Qtl for maize). */
function qtyFmt(token: Token): string {
  if (token.weight_method === 'volume' && token.volume_cft != null) {
    return volFmt(Number(token.volume_cft), token.billing_unit);
  }
  return mtFmt(token.net_weight);
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
  const { t } = useTranslation();
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
          {t(`token.status.${key}`)}
        </button>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ //
// Main Page
// ------------------------------------------------------------------ //
export default function TokenPageV1() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';
  const isMobile = useIsMobile();

  // Camera agent WebSocket port — probe the local status server on mount so we
  // always connect to the actual port (the scale agent can bump its own status
  // onto 9004 via _find_free_port, causing camera_agent's WS bind to fail on
  // 9004 and auto-move to 9005; the status server advertises the real ws_port).
  const [wsPort, setWsPort] = useState(() => localStorage.getItem('camera_agent_ws_port') || '9004');
  useEffect(() => {
    fetch('http://localhost:9003/')
      .then(r => r.json())
      .then((s: { ws_port?: number }) => {
        if (s.ws_port) {
          const port = String(s.ws_port);
          localStorage.setItem('camera_agent_ws_port', port);
          setWsPort(port);
        }
      })
      .catch(() => {}); // camera agent not running is fine
  }, []);

  const [tokens, setTokens] = useState<Token[]>([]);
  const [loading, setLoading] = useState(false);

  // Search + date + status filter + measurement-method filter
  const [search, setSearch] = useState('');
  const [dateFrom, setDateFrom] = useState(today());
  const [dateTo, setDateTo] = useState(today());

  // Column visibility — persisted to localStorage
  const [visibleCols, setVisibleCols] = useState<TokenColKey[]>(() => {
    try {
      const s = localStorage.getItem(TOKEN_COLS_LS);
      if (s) return JSON.parse(s) as TokenColKey[];
    } catch { /* ignore */ }
    return DEFAULT_TOKEN_COLS;
  });
  const [colPickerOpen, setColPickerOpen] = useState(false);
  const colPickerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!colPickerOpen) return;
    function onDown(e: MouseEvent) {
      if (colPickerRef.current && !colPickerRef.current.contains(e.target as Node)) setColPickerOpen(false);
    }
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [colPickerOpen]);

  function toggleCol(key: TokenColKey) {
    setVisibleCols(prev => {
      const next = prev.includes(key) ? prev.filter(k => k !== key) : [...prev, key];
      localStorage.setItem(TOKEN_COLS_LS, JSON.stringify(next));
      return next;
    });
  }
  function resetCols() {
    setVisibleCols(DEFAULT_TOKEN_COLS);
    localStorage.setItem(TOKEN_COLS_LS, JSON.stringify(DEFAULT_TOKEN_COLS));
  }
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
  // Cameras are a per-tenant feature (the `cameras` module). When off (e.g. a
  // client with no camera agent, or a maize tenant), hide the live feeds + skip
  // snapshot capture entirely so the page isn't cluttered with "offline" panels.
  const camerasEnabled = moduleEnabled('cameras');
  const COLS = TOKEN_COL_DEFS.filter(c => visibleCols.includes(c.key)).map(c => c.width).join(' ');

  // ── Mobile layout: stacked sections instead of resizable split ──────── //
  if (isMobile) {
    return (
      <div className="flex flex-col gap-3 pb-20">
        <ScaleStatus />
        <CreateTokenForm onCreated={handleTokenCreated} />
        {camerasEnabled && (
          <div className="grid grid-cols-2 gap-2 h-36">
            <CameraPanel cameraId="front" label={t('token.frontCamera')} wsPort={wsPort} />
            <CameraPanel cameraId="top" label={t('token.topCamera')} wsPort={wsPort} />
          </div>
        )}
        {/* Compact token list */}
        <div className="rounded-xl border bg-card shadow-sm overflow-hidden">
          <div className="px-3 py-2 border-b bg-muted/30 flex items-center justify-between shrink-0">
            <div>
              <p className="text-sm font-semibold">{dateFrom === today() && dateTo === today() ? t('token.todayTokens') : t('token.tokenList')}</p>
              <p className="text-[10px] text-muted-foreground">{filtered.length} tokens · {tokens.filter(canWeigh).length} {t('token.activeCount')}</p>
            </div>
            <Button size="sm" variant="ghost" onClick={fetchTokens} disabled={loading}>
              <RefreshCw className={`h-3 w-3 ${loading ? 'animate-spin' : ''}`} />
            </Button>
          </div>
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : filtered.length === 0 ? (
            <div className="px-3 py-8 text-center text-sm text-muted-foreground">No tokens yet today</div>
          ) : (
            <div className="divide-y">
              {filtered.map(token => {
                const sc = STATUS_CONFIG[token.status as keyof typeof STATUS_CONFIG] ?? STATUS_CONFIG.OPEN;
                return (
                  <div key={token.id} className="px-3 py-2.5 flex items-center justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <span className="text-xs font-mono font-bold text-primary">
                          {token.token_no ? `#${token.token_no}` : `GP/${token.gate_pass_no || '...'}`}
                        </span>
                        <span className={`text-[10px] px-1.5 py-0.5 rounded-full border font-medium ${sc.color}`}>{sc.label}</span>
                      </div>
                      <p className="text-xs text-muted-foreground truncate mt-0.5">
                        {token.vehicle_no} · {token.net_weight ? wFmt(token.net_weight) : token.gross_weight ? wFmt(token.gross_weight) + ' (gross)' : '—'}
                      </p>
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                      {canWeigh(token) && (
                        <Button size="sm" variant="outline" className="h-9 w-9 p-0"
                          onClick={() => { setWeightToken(token); setWeightStage(token.status === 'OPEN' ? 'first' : 'second'); setWeightOpen(true); }}>
                          <Scale className="h-4 w-4" />
                        </Button>
                      )}
                      <Button size="sm" variant="ghost" className="h-9 w-9 p-0"
                        onClick={() => setTokenModalId(token.id)}>
                        <ArrowRight className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
        <WeightCaptureDialog
          token={weightToken}
          weightStage={weightStage}
          open={weightOpen}
          onClose={() => { setWeightOpen(false); fetchTokens(); }}
          onDone={handleWeightDone}
        />
        <TokenDetailModal tokenId={tokenModalId} onClose={() => setTokenModalId(null)} />
      </div>
    );
  }

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
            {/* ---- Live Cameras — only when the camera module is enabled ---- */}
            {camerasEnabled && (
              <div className="grid grid-cols-2 gap-3 h-44 shrink-0 mb-1">
                <CameraPanel cameraId="front" label={t('token.frontCamera')} wsPort={wsPort} />
                <CameraPanel cameraId="top" label={t('token.topCamera')} wsPort={wsPort} />
              </div>
            )}

            {/* ---- Token List (fills remaining height) ---- */}
            <div className="flex-1 rounded-xl border bg-card shadow-sm flex flex-col min-h-0 overflow-hidden">

          {/* Header row */}
          <div className="flex items-center gap-2 px-3 py-2 border-b bg-muted/30 shrink-0 flex-wrap">
            <div className="min-w-0 mr-auto">
              <p className="text-sm font-semibold">
                {dateFrom === today() && dateTo === today() ? t('token.todayTokens') : t('token.tokenList')}
              </p>
              <p className="text-[10px] text-muted-foreground">
                {filtered.length} of {tokens.length} · {tokens.filter(canWeigh).length} {t('token.activeCount')}
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
                  {t('common.today')}
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
              {t('common.refresh')}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="text-muted-foreground h-7 gap-1 text-xs shrink-0"
              disabled={filtered.length === 0}
              onClick={() => {
                const wu = weightUnitLabel();
                const headers = ['Token No', 'Gate Pass', 'Date', 'Vehicle', 'Method', 'Party', 'Material', `Gross (${wu})`, `Tare (${wu})`, `Net (${wu})`, 'Volume (CFT)', 'Status'];
                const rows = filtered.map(t => {
                  return [
                    t.token_no != null ? String(t.token_no) : '',
                    t.gate_pass_no ?? '',
                    t.token_date,
                    t.vehicle_no,
                    t.weight_method ?? 'weighbridge',
                    t.party?.name ?? '',
                    t.product?.name ?? '',
                    t.gross_weight != null ? fmtKg(t.gross_weight, 4, false) : '',
                    t.tare_weight != null ? fmtKg(t.tare_weight, 4, false) : '',
                    t.net_weight != null ? fmtKg(t.net_weight, 4, false) : '',
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

            {/* Column picker */}
            <div className="relative shrink-0" ref={colPickerRef}>
              <Button
                variant="ghost"
                size="sm"
                className="text-muted-foreground h-7 gap-1 text-xs"
                onClick={() => setColPickerOpen(o => !o)}
                title="Show/hide columns"
              >
                <Settings2 className="h-3.5 w-3.5" />
              </Button>
              {colPickerOpen && (
                <div className="absolute right-0 mt-1 z-50 w-52 rounded-md border bg-popover p-2 shadow-md">
                  <div className="flex items-center justify-between mb-2">
                    <p className="text-xs font-medium text-muted-foreground">Show columns</p>
                    <button type="button" className="text-[11px] text-muted-foreground hover:text-foreground px-1 underline underline-offset-2" onClick={resetCols}>
                      Reset
                    </button>
                  </div>
                  <div className="space-y-1">
                    {TOKEN_COL_DEFS.filter(c => !c.alwaysVisible).map(c => (
                      <label key={c.key} className="flex items-center gap-2 rounded px-2 py-1 text-xs hover:bg-muted cursor-pointer">
                        <input
                          type="checkbox"
                          checked={visibleCols.includes(c.key)}
                          onChange={() => toggleCol(c.key)}
                          className="h-3.5 w-3.5"
                        />
                        <span>{c.label}</span>
                      </label>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Status filter pills */}
          <div className="px-3 py-1.5 border-b bg-muted/10 shrink-0 flex flex-wrap items-center gap-x-3 gap-y-1">
            <StatusFilterPills selected={selectedStatuses} onChange={setSelectedStatuses} />
            <span className="text-[9px] text-muted-foreground/60 select-none">|</span>
            <div className="flex gap-1">
              {([
                { key: 'all',         label: t('token.allMethods'),  count: tokens.length },
                { key: 'weighbridge', label: t('token.weighbridge'), count: bridgeCount  },
                { key: 'volume',      label: t('token.volume'),      count: volumeCount  },
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

          {/* Table header + body share ONE overflow-auto container so they scroll together horizontally.
              The header uses sticky top-0 so it stays visible during vertical scroll. */}
          <div className="overflow-auto flex-1 min-h-0">

            {/* Sticky table header */}
            <div
              className="grid gap-x-1 px-3 py-1.5 border-b bg-muted/20 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground sticky top-0 z-10"
              style={{ gridTemplateColumns: COLS }}
            >
              {visibleCols.includes('token_no') && <div>#</div>}
              {visibleCols.includes('vehicle')  && <div>{t('token.vehicle')}</div>}
              {visibleCols.includes('party')    && <div>{t('token.party')}</div>}
              {visibleCols.includes('product')  && <div>{t('token.product')}</div>}
              {visibleCols.includes('gross')    && <div className="text-right">{t('token.grossWeight')} (MT)</div>}
              {visibleCols.includes('tare')     && <div className="text-right">{t('token.tareWeight')} (MT)</div>}
              {visibleCols.includes('net')      && <div className="text-right">{t('token.netWeight')} (MT)</div>}
              {visibleCols.includes('actions')  && <div className="text-center">Act</div>}
            </div>

            {loading && tokens.length === 0 ? (
              <div className="flex items-center justify-center py-10">
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              </div>
            ) : filtered.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-10 px-4 text-center">
                <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-muted">
                  <Scale className="h-6 w-6 text-muted-foreground/40" />
                </div>
                <p className="text-xs font-semibold">{t('token.noTokensMatch')}</p>
                <p className="mt-0.5 text-[10px] text-muted-foreground">
                  {t('token.adjustFilters')}
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
                    {/* Token # + gate pass.
                        overflow-hidden is REQUIRED on the cell wrapper: whitespace-nowrap text
                        (gate pass = "GP/2026-06-20/001", ~18 chars @ 9px mono ≈ 99px) will
                        visually bleed into the VEHICLE column without it. */}
                    {visibleCols.includes('token_no') && (
                    <div className="min-w-0 overflow-hidden">
                      <p className="font-bold text-primary text-xs truncate">
                        {token.token_no != null ? `#${token.token_no}` : <span className="text-muted-foreground italic">—</span>}
                      </p>
                      <p className="text-[10px] text-muted-foreground capitalize truncate">{token.token_type}</p>
                      {token.gate_pass_no && (
                        /* Show compact "GP NNN" so it fits in the 48px column; full value on hover */
                        <p className="text-[9px] font-mono text-emerald-700 truncate leading-tight" title={token.gate_pass_no}>
                          GP {token.gate_pass_no.split('/').pop()}
                        </p>
                      )}
                    </div>
                    )}

                    {/* Vehicle — Indian plates: MH12AB1234 (10 chars) */}
                    {visibleCols.includes('vehicle') && (
                    <div className="min-w-0 overflow-hidden">
                      <div className="flex items-center gap-1">
                        <p className="font-mono font-semibold text-xs tracking-wide truncate" title={token.vehicle_no}>
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
                        <p className="text-[10px] capitalize text-muted-foreground truncate leading-tight">
                          {token.vehicle_type.replace(/_/g, ' ')}
                        </p>
                      )}
                    </div>
                    )}

                    {/* Party — single line with ellipsis; full name on hover. */}
                    {visibleCols.includes('party') && (
                    <div className="min-w-0 overflow-hidden">
                      {token.party
                        ? <p className="text-xs truncate" title={token.party.name}>{token.party.name}</p>
                        : <p className="text-muted-foreground text-xs">—</p>
                      }
                    </div>
                    )}

                    {/* Material — single line with ellipsis; full name on hover. */}
                    {visibleCols.includes('product') && (
                    <div className="min-w-0 overflow-hidden">
                      {token.product
                        ? <p className="text-xs truncate text-muted-foreground" title={token.product.name}>{token.product.name}</p>
                        : <p className="text-muted-foreground text-xs">—</p>
                      }
                    </div>
                    )}

                    {/* Weights in MT — clipped to cell width */}
                    {visibleCols.includes('gross') && (
                    <div className="min-w-0 overflow-hidden text-right font-mono text-xs text-muted-foreground whitespace-nowrap">{mtFmt(token.gross_weight)}</div>
                    )}
                    {visibleCols.includes('tare') && (
                    <div className="min-w-0 overflow-hidden text-right font-mono text-xs text-muted-foreground whitespace-nowrap">{mtFmt(token.tare_weight)}</div>
                    )}
                    {visibleCols.includes('net') && (
                    <div className="min-w-0 overflow-hidden text-right font-mono text-xs font-bold whitespace-nowrap" title={qtyFmt(token)}>
                      {(token.weight_method === 'volume' ? token.volume_cft != null : token.net_weight != null)
                        ? <span className="text-primary">{qtyFmt(token)}</span>
                        : <span className="text-muted-foreground">—</span>
                      }
                    </div>
                    )}

                    {/* Actions — centered, stop row click */}
                    {visibleCols.includes('actions') && (
                    <div className="flex items-center justify-center gap-0.5 shrink-0" onClick={e => e.stopPropagation()}>
                      {active && (
                        <Button
                          size="icon"
                          variant="ghost"
                          className="h-6 w-6 text-amber-600 hover:text-amber-700 hover:bg-amber-100 shrink-0"
                          title={t('token.recordWeight')}
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
                    )}
                  </div>
                  );
                })}
              </div>
            )}
          </div>
            </div>
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
