import { useEffect, useState, useCallback, useRef } from 'react';
import {
  Plus, Search, Scale, CheckCircle2, XCircle, Loader2,
  Truck, Package, User, Wifi, WifiOff, ArrowRight,
  AlertCircle, Clock, RefreshCw, Camera,
} from 'lucide-react';
import { PrintButton } from '@/components/PrintButton';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter
} from '@/components/ui/dialog';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue
} from '@/components/ui/select';
import { useWeight } from '@/hooks/useWeight';
import { useAuth } from '@/hooks/useAuth';
import api from '@/services/api';
import type { Token, TokenListResponse, Party, Product, Vehicle, SnapshotResult, TokenSnapshotsResponse } from '@/types';
import { cn } from '@/lib/utils';
import { TokenDetailModal } from '@/components/TokenDetailModal';

// ------------------------------------------------------------------ //
// Helpers
// ------------------------------------------------------------------ //
const STATUS_CONFIG = {
  OPEN:          { label: 'Awaiting 1st Wt',  color: 'bg-blue-100 text-blue-700 border-blue-200',    dot: 'bg-blue-500'   },
  FIRST_WEIGHT:  { label: '1st Wt Done',       color: 'bg-amber-100 text-amber-700 border-amber-200', dot: 'bg-amber-500'  },
  LOADING:       { label: 'Loading',           color: 'bg-orange-100 text-orange-700 border-orange-200', dot: 'bg-orange-500' },
  SECOND_WEIGHT: { label: 'Awaiting 2nd Wt',  color: 'bg-purple-100 text-purple-700 border-purple-200', dot: 'bg-purple-500' },
  COMPLETED:     { label: 'Completed',         color: 'bg-green-100 text-green-700 border-green-200',  dot: 'bg-green-500'  },
  CANCELLED:     { label: 'Cancelled',         color: 'bg-red-100 text-red-700 border-red-200',        dot: 'bg-red-400'    },
} as const;

function StatusBadge({ status }: { status: Token['status'] }) {
  const cfg = STATUS_CONFIG[status] ?? { label: status, color: 'bg-muted text-muted-foreground border-border', dot: 'bg-muted-foreground' };
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap ${cfg.color}`}>
      <span className={`h-1.5 w-1.5 rounded-full shrink-0 ${cfg.dot}`} />
      {cfg.label}
    </span>
  );
}

function wFmt(v: number | null | undefined) {
  if (v == null) return '—';
  return v.toLocaleString('en-IN', { minimumFractionDigits: 2 }) + ' kg';
}

function today() {
  return new Date().toISOString().split('T')[0];
}

function elapsedLabel(secs: number) {
  if (secs < 60) return `${secs}s`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m`;
  return `${Math.floor(secs / 3600)}h ${Math.floor((secs % 3600) / 60)}m`;
}

const canWeigh = (t: Token) =>
  t.status === 'OPEN' || t.status === 'FIRST_WEIGHT' || t.status === 'LOADING' || t.status === 'SECOND_WEIGHT';

// ------------------------------------------------------------------ //
// Compact Scale Status
// ------------------------------------------------------------------ //
function ScaleStatus() {
  const { reading, formatted } = useWeight();
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
          {reading.scale_connected ? formatted : '—'}
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
// Inline Create Token Form
// ------------------------------------------------------------------ //
interface CreateFormProps {
  onCreated: (token: Token) => void;
}

function CreateTokenForm({ onCreated }: CreateFormProps) {
  const [form, setForm] = useState({
    vehicle_no: '',
    token_type: 'sale',
    direction: 'outbound',
    party_id: '',
    product_id: '',
    vehicle_id: '',
    remarks: '',
  });
  const [parties, setParties] = useState<Party[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [vehicleSearch, setVehicleSearch] = useState('');
  const [selectedVehicle, setSelectedVehicle] = useState<Vehicle | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    Promise.all([
      api.get<{ items: Party[] }>('/api/v1/parties?page_size=200'),
      api.get<Product[]>('/api/v1/products'),
      api.get<{ items: Vehicle[] } | Vehicle[]>('/api/v1/vehicles?page_size=200'),
    ]).then(([p, pr, v]) => {
      setParties(Array.isArray(p.data) ? p.data : (p.data.items ?? []));
      setProducts(Array.isArray(pr.data) ? pr.data : (pr.data as { items: Product[] }).items ?? []);
      const vData = v.data;
      setVehicles(Array.isArray(vData) ? vData : (vData as { items: Vehicle[] }).items ?? []);
    }).catch(() => {});
  }, []);

  function resetForm() {
    setForm({ vehicle_no: '', token_type: 'sale', direction: 'outbound', party_id: '', product_id: '', vehicle_id: '', remarks: '' });
    setVehicleSearch('');
    setSelectedVehicle(null);
    setError('');
  }

  const handleTypeChange = (type: string) => {
    setForm(f => ({ ...f, token_type: type, direction: type === 'purchase' ? 'inbound' : 'outbound' }));
  };

  const handleVehicleSelect = (vehicle: Vehicle) => {
    setSelectedVehicle(vehicle);
    setForm(f => ({ ...f, vehicle_no: vehicle.registration_no, vehicle_id: vehicle.id }));
    setVehicleSearch('');
  };

  const filteredVehicles = vehicleSearch.length >= 1
    ? vehicles.filter(v => v.registration_no.toLowerCase().includes(vehicleSearch.toLowerCase())).slice(0, 6)
    : [];

  async function handleSubmit() {
    if (!form.vehicle_no.trim()) { setError('Vehicle number is required'); return; }
    setSaving(true); setError('');
    try {
      const { data } = await api.post<Token>('/api/v1/tokens', {
        token_date: today(),
        vehicle_no: form.vehicle_no.trim().toUpperCase(),
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
    <div className="rounded-xl border bg-card shadow-sm flex flex-col overflow-hidden">
      {/* Bold colorful header */}
      <div className="relative bg-gradient-to-br from-blue-600 via-blue-700 to-indigo-800 px-5 py-5 overflow-hidden">
        {/* decorative circles */}
        <div className="absolute -top-4 -right-4 h-24 w-24 rounded-full bg-white/10" />
        <div className="absolute -bottom-6 -left-4 h-20 w-20 rounded-full bg-white/5" />
        <div className="relative flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-white/20 shadow-inner backdrop-blur-sm">
            <Truck className="h-6 w-6 text-white" />
          </div>
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-widest text-blue-200">Weighbridge</p>
            <p className="text-2xl font-black text-white tracking-tight">New Token</p>
          </div>
          <div className="ml-auto">
            <span className="flex h-3 w-3">
              <span className="animate-ping absolute h-3 w-3 rounded-full bg-green-300 opacity-75" />
              <span className="h-3 w-3 rounded-full bg-green-400" />
            </span>
          </div>
        </div>
        <p className="relative mt-2 text-xs text-blue-200">Fill in details and record the first weight</p>
      </div>

      <div className="p-4 space-y-4 overflow-y-auto flex-1">
        {error && (
          <div className="flex items-center gap-2 rounded-lg bg-destructive/10 p-2.5 text-xs text-destructive">
            <AlertCircle className="h-3.5 w-3.5 shrink-0" />
            {error}
          </div>
        )}

        {/* Step indicator */}
        {(() => {
          const currentStep = form.vehicle_no.trim() ? (form.party_id ? 3 : 2) : 1;
          return (
            <div className="flex items-center gap-0 mb-5">
              {[
                { n: 1, icon: '🚛', label: 'Vehicle' },
                { n: 2, icon: '📋', label: 'Details' },
                { n: 3, icon: '⚖️', label: 'Weigh' },
              ].map((step, i) => (
                <div key={step.n} className="flex items-center flex-1">
                  <div className="flex flex-col items-center flex-1">
                    <div className={`flex h-8 w-8 items-center justify-center rounded-full text-sm font-bold transition-colors ${
                      currentStep >= step.n ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground'
                    }`}>
                      {currentStep > step.n ? '✓' : step.icon}
                    </div>
                    <span className={`text-[10px] mt-1 font-medium ${currentStep >= step.n ? 'text-primary' : 'text-muted-foreground'}`}>
                      {step.label}
                    </span>
                  </div>
                  {i < 2 && <div className={`h-0.5 flex-1 mx-1 ${currentStep > step.n ? 'bg-primary' : 'bg-muted'}`} />}
                </div>
              ))}
            </div>
          );
        })()}

        {/* Token Type */}
        <div className="space-y-1.5">
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
                  'rounded-lg border-2 p-2.5 text-left transition-all',
                  form.token_type === opt.value ? opt.color : 'border-border hover:border-primary/40'
                )}
              >
                <p className="font-semibold text-sm">{opt.label}</p>
                <p className="text-xs text-muted-foreground">{opt.sub}</p>
              </button>
            ))}
          </div>
        </div>

        {/* Vehicle */}
        <div className="space-y-1.5">
          <Label className="text-xs">Vehicle Number <span className="text-destructive">*</span></Label>
          {selectedVehicle ? (
            <div className="flex items-center gap-2 rounded-lg border-2 border-green-400 bg-green-50 px-3 py-2">
              <Truck className="h-4 w-4 text-green-600 shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="font-bold text-sm text-green-800">{selectedVehicle.registration_no}</p>
                {selectedVehicle.default_tare_weight > 0 && (
                  <p className="text-xs text-green-700">Tare: {wFmt(selectedVehicle.default_tare_weight)}</p>
                )}
              </div>
              <button
                type="button"
                onClick={() => { setSelectedVehicle(null); setForm(f => ({ ...f, vehicle_no: '', vehicle_id: '' })); }}
                className="text-xs text-green-700 underline hover:text-green-900 shrink-0"
              >Change</button>
            </div>
          ) : (
            <div className="space-y-2">
              <div className="relative">
                <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
                <Input
                  className="pl-8 h-9 text-sm"
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
                        className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-muted transition-colors first:rounded-t-lg last:rounded-b-lg text-sm"
                        onClick={() => handleVehicleSelect(v)}
                      >
                        <Truck className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                        <span className="font-medium">{v.registration_no}</span>
                        {v.default_tare_weight > 0 && (
                          <span className="ml-auto text-xs text-muted-foreground">{wFmt(v.default_tare_weight)}</span>
                        )}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <Input
                className="h-9 text-sm uppercase"
                placeholder="Or type: MH12AB1234"
                value={form.vehicle_no}
                onChange={e => setForm(f => ({ ...f, vehicle_no: e.target.value.toUpperCase(), vehicle_id: '' }))}
              />
            </div>
          )}
        </div>

        {/* Party */}
        <div className="space-y-1.5">
          <Label className="text-xs">Party <span className="text-destructive">*</span></Label>
          <Select value={form.party_id || undefined} onValueChange={v => setForm(f => ({ ...f, party_id: v ?? '' }))}>
            <SelectTrigger className="h-9 text-sm">
              <span className="truncate text-left flex-1">
                {form.party_id
                  ? (parties.find(p => p.id === form.party_id)?.name ?? '…')
                  : <span className="text-muted-foreground">Select party…</span>}
              </span>
            </SelectTrigger>
            <SelectContent>
              {parties.map(p => (
                <SelectItem key={p.id} value={String(p.id)} textValue={p.name}>
                  <span className="font-medium">{p.name}</span>
                  {p.gstin && <span className="text-muted-foreground text-xs ml-2">{p.gstin}</span>}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* Material */}
        <div className="space-y-1.5">
          <Label className="text-xs">Material</Label>
          <Select value={form.product_id || undefined} onValueChange={v => setForm(f => ({ ...f, product_id: v ?? '' }))}>
            <SelectTrigger className="h-9 text-sm">
              <span className="truncate text-left flex-1">
                {form.product_id
                  ? (() => { const p = products.find(x => x.id === form.product_id); return p ? p.name : '…'; })()
                  : <span className="text-muted-foreground">Select material…</span>}
              </span>
            </SelectTrigger>
            <SelectContent>
              {products.map(p => (
                <SelectItem key={p.id} value={p.id} textValue={p.name}>
                  {p.name} <span className="text-muted-foreground text-xs">({p.unit})</span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* Remarks */}
        <div className="space-y-1.5">
          <Label className="text-xs">Remarks <span className="text-muted-foreground">(optional)</span></Label>
          <Input
            className="h-9 text-sm"
            value={form.remarks}
            onChange={e => setForm(f => ({ ...f, remarks: e.target.value }))}
            placeholder="Driver name, challan no…"
          />
        </div>
      </div>

      {/* Submit */}
      <div className="px-4 pb-4 pt-2 border-t mt-auto">
        <Button
          className="w-full"
          onClick={handleSubmit}
          disabled={saving || !form.vehicle_no.trim()}
        >
          {saving
            ? <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            : <ArrowRight className="mr-2 h-4 w-4" />}
          Start Weighment
        </Button>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ //
// Weight Capture Dialog
// ------------------------------------------------------------------ //
interface WeightDialogProps {
  token: Token | null;
  weightStage: 'first' | 'second';
  open: boolean;
  onClose: () => void;
  onDone: (updated: Token) => void;
}

function WeightCaptureDialog({ token, weightStage, open, onClose, onDone }: WeightDialogProps) {
  const { reading, formatted } = useWeight();
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
    // Cleanup poll timer when dialog closes
    return () => { if (pollTimerRef.current) clearTimeout(pollTimerRef.current); };
  }, [open]);

  useEffect(() => {
    if (manualMode && manualRef.current) manualRef.current.focus();
  }, [manualMode]);

  if (!token) return null;

  const isOutbound = token.direction === 'outbound';
  const stage1Label = isOutbound ? 'Gross Weight (Truck + Material)' : 'Tare Weight (Empty Truck)';
  const stage2Label = isOutbound ? 'Tare Weight (Empty Truck)'       : 'Gross Weight (Truck + Material)';
  const currentLabel = weightStage === 'first' ? stage1Label : stage2Label;
  const stageNum = weightStage === 'first' ? 1 : 2;

  const liveWeight = manualMode ? (parseFloat(manualWeight) || 0) : reading.weight_kg;
  const stage1Weight = token.first_weight ?? 0;
  const liveNet = weightStage === 'second' && stage1Weight > 0
    ? Math.max(0, isOutbound ? stage1Weight - liveWeight : liveWeight - stage1Weight)
    : null;

  async function capture(weight: number, isManual = false) {
    if (weight <= 0) { setError('Weight must be greater than 0'); return; }
    setSaving(true); setError('');
    try {
      const endpoint = weightStage === 'first'
        ? `/api/v1/tokens/${token!.id}/first-weight`
        : `/api/v1/tokens/${token!.id}/second-weight`;
      const { data } = await api.post<Token>(endpoint, { weight_kg: weight, is_manual: isManual });

      // Camera snapshot timing:
      //   Sale token    → capture at 2nd weight (loaded truck departing)
      //   Purchase token → capture at 1st weight (loaded truck arriving)
      const isCaptureStage =
        (token!.token_type === 'sale'     && weightStage === 'second') ||
        (token!.token_type === 'purchase' && weightStage === 'first');

      if (isCaptureStage) {
        // Weight saved — update parent immediately, then poll for camera snapshots
        onDone(data);
        setCapturePhase('capturing');
        const tokenId = token!.id;
        const deadline = Date.now() + 20_000; // 20s max poll window

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
              // Auto-close after 2.5s so operator can see thumbnails
              pollTimerRef.current = setTimeout(onClose, 2500);
            } else {
              pollTimerRef.current = setTimeout(poll, 2000);
            }
          } catch {
            // If poll fails, just close
            setCapturePhase('done');
            pollTimerRef.current = setTimeout(onClose, 500);
          }
        };
        // Start first poll after 2s (give backend time to start capture)
        pollTimerRef.current = setTimeout(poll, 2000);
      } else {
        // Non-capture weight stage — just update and close
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
          {/* Token context */}
          <div className="rounded-lg border bg-muted/30 p-3 space-y-1.5">
            <div className="flex items-center gap-2">
              <Truck className="h-4 w-4 text-primary shrink-0" />
              <span className="font-bold text-sm">{token.vehicle_no}</span>
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

          {/* Stage 1 reference */}
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

          {/* Weight display */}
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
                {reading.scale_connected ? formatted : '— . — —  kg'}
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
              <Label>Enter Weight Manually (kg)</Label>
              <Input
                ref={manualRef}
                type="number"
                step="0.01"
                min="0"
                value={manualWeight}
                onChange={e => setManualWeight(e.target.value)}
                placeholder="0.00"
                className="text-2xl font-mono h-14 text-center font-bold"
              />
            </div>
          )}

          {/* Live net preview */}
          {liveNet !== null && liveWeight > 0 && (
            <div className="rounded-lg bg-primary/5 border border-primary/20 p-3 flex items-center justify-between">
              <div>
                <p className="text-xs text-muted-foreground">Live Net Weight Preview</p>
                <p className="font-mono text-2xl font-black text-primary">{wFmt(liveNet)}</p>
              </div>
              <div className="text-xs text-muted-foreground text-right">
                <p>{wFmt(isOutbound ? stage1Weight : liveWeight)} (gross)</p>
                <p>− {wFmt(isOutbound ? liveWeight : stage1Weight)} (tare)</p>
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

          {/* Camera snapshot status — shown after second weight is submitted */}
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

        <DialogFooter className="gap-2">
          <Button
            variant="outline"
            onClick={onClose}
            disabled={saving}
          >
            {capturePhase !== 'idle' ? 'Close' : 'Cancel'}
          </Button>
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
                onClick={() => capture(parseFloat(manualWeight), true)}
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
// Snapshot Lightbox
// ------------------------------------------------------------------ //
function SnapshotLightboxModal({
  tokenId,
  onClose,
}: {
  tokenId: string | null;
  onClose: () => void;
}) {
  const [snapshots, setSnapshots] = useState<SnapshotResult[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!tokenId) return;
    setLoading(true);
    api.get<TokenSnapshotsResponse>(`/api/v1/tokens/${tokenId}/snapshots`)
      .then(r => setSnapshots(r.data.snapshots))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [tokenId]);

  const captured = snapshots.filter(s => s.capture_status === 'captured' && s.url);

  return (
    <Dialog open={!!tokenId} onOpenChange={v => !v && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Camera className="h-4 w-4 text-primary" />
            Token Camera Snapshots
          </DialogTitle>
        </DialogHeader>
        {loading ? (
          <div className="flex justify-center py-10">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : captured.length === 0 ? (
          <div className="text-center py-10 space-y-2">
            <Camera className="h-10 w-10 text-muted-foreground/30 mx-auto" />
            <p className="text-sm text-muted-foreground">
              {snapshots.length === 0
                ? 'No camera snapshots recorded for this token.'
                : 'Camera capture failed for this token.'}
            </p>
            {snapshots.some(s => s.capture_status === 'failed') && (
              <p className="text-xs text-muted-foreground">
                An admin can retry failed captures from the token snapshots API.
              </p>
            )}
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-4">
            {captured.map(s => (
              <div key={s.camera_id} className="space-y-2">
                <p className="text-sm font-medium capitalize flex items-center gap-1.5">
                  <Camera className="h-3.5 w-3.5 text-muted-foreground" />
                  {s.camera_label || s.camera_id} View
                </p>
                <a href={s.url!} target="_blank" rel="noopener noreferrer">
                  <img
                    src={s.url!}
                    alt={`${s.camera_id} view`}
                    className="rounded-lg border w-full object-cover cursor-zoom-in hover:opacity-90 transition-opacity"
                    style={{ maxHeight: '280px' }}
                  />
                </a>
                <p className="text-[10px] text-muted-foreground text-right">
                  Click image to open full size ↗
                  {s.captured_at && (
                    <> · {new Date(s.captured_at).toLocaleTimeString('en-IN')}</>
                  )}
                </p>
              </div>
            ))}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

// ------------------------------------------------------------------ //
// Main Page
// ------------------------------------------------------------------ //
export default function TokenPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';

  const [tokens, setTokens] = useState<Token[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [filterStatus, setFilterStatus] = useState('');
  const [dateFrom, setDateFrom] = useState(today());
  const [dateTo, setDateTo] = useState(today());
  const [loading, setLoading] = useState(false);

  const [weightToken, setWeightToken] = useState<Token | null>(null);
  const [weightStage, setWeightStage] = useState<'first' | 'second'>('first');
  const [weightOpen, setWeightOpen] = useState(false);
  const [tokenModalId, setTokenModalId] = useState<string | null>(null);
  const [snapshotTokenId, setSnapshotTokenId] = useState<string | null>(null);

  // Elapsed timer tick
  const [, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick(t => t + 1), 30_000);
    return () => clearInterval(id);
  }, []);

  const PAGE_SIZE = 50;

  const fetchTokens = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) });
      if (search) params.set('search', search);
      if (filterStatus) params.set('status', filterStatus);
      if (dateFrom) params.set('date_from', dateFrom);
      if (dateTo) params.set('date_to', dateTo);
      const { data } = await api.get<TokenListResponse>(`/api/v1/tokens?${params}`);
      setTokens(data.items);
      setTotal(data.total);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [page, search, filterStatus, dateFrom, dateTo]);

  useEffect(() => { fetchTokens(); }, [fetchTokens]);

  // Auto-refresh every 30s when no dialog open
  useEffect(() => {
    const id = setInterval(() => {
      if (!weightOpen) fetchTokens();
    }, 30_000);
    return () => clearInterval(id);
  }, [fetchTokens, weightOpen]);

  function openWeight(token: Token) {
    setWeightToken(token);
    setWeightStage(token.status === 'OPEN' ? 'first' : 'second');
    setWeightOpen(true);
  }

  function handleTokenCreated(token: Token) {
    setTokens(prev => [token, ...prev]);
    setTotal(t => t + 1);
    openWeight(token);
  }

  function handleWeightDone(updated: Token) {
    setTokens(prev => prev.map(t => t.id === updated.id ? updated : t));
  }

  async function cancelToken(id: string) {
    if (!confirm('Cancel this token?')) return;
    try {
      const { data } = await api.post<Token>(`/api/v1/tokens/${id}/cancel`);
      setTokens(prev => prev.map(t => t.id === id ? data : t));
    } catch {
      // ignore
    }
  }

  const activeCount = tokens.filter(t => canWeigh(t)).length;

  // Elapsed time helper
  function elapsed(iso: string) {
    const secs = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
    return elapsedLabel(secs);
  }

  const isToday = dateFrom === today() && dateTo === today();

  return (
    <div className="flex gap-4 h-[calc(100vh-7rem)] overflow-hidden">

      {/* ==================== LEFT PANEL (45%) ==================== */}
      <div className="w-[45%] shrink-0 flex flex-col gap-3 overflow-y-auto">
        <ScaleStatus />
        <CreateTokenForm onCreated={handleTokenCreated} />
      </div>

      {/* ==================== RIGHT PANEL (55%) ==================== */}
      <div className="w-[55%] flex flex-col gap-3 overflow-hidden">

        {/* Header + filter bar */}
        <div className="flex flex-col gap-2 shrink-0">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-base font-semibold text-muted-foreground tracking-tight">
                {isToday ? "Today's Tokens" : "Token List"}
              </h1>
              <p className="text-xs text-muted-foreground">
                {total} token{total !== 1 ? 's' : ''}
                {activeCount > 0 && (
                  <span className="ml-2 text-amber-600 font-medium">
                    · {activeCount} active
                  </span>
                )}
              </p>
            </div>
            <Button
              variant="ghost"
              size="sm"
              onClick={fetchTokens}
              className="text-muted-foreground h-8 gap-1.5"
            >
              <RefreshCw className={cn('h-3.5 w-3.5', loading && 'animate-spin')} />
              Refresh
            </Button>
          </div>

          {/* Filters */}
          <div className="flex flex-wrap gap-2 items-center">
            {/* Search */}
            <div className="relative min-w-40 flex-1 max-w-xs">
              <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
              <Input
                className="pl-8 h-8 text-sm"
                placeholder="Search vehicle or customer…"
                value={search}
                onChange={e => { setSearch(e.target.value); setPage(1); }}
              />
            </div>

            {/* Date range */}
            <div className="flex items-center gap-1.5">
              <input
                type="date"
                title="From"
                className="h-8 rounded-md border border-input bg-background px-2 text-xs"
                value={dateFrom}
                onChange={e => { setDateFrom(e.target.value); setPage(1); }}
              />
              <span className="text-xs text-muted-foreground">–</span>
              <input
                type="date"
                title="To"
                className="h-8 rounded-md border border-input bg-background px-2 text-xs"
                value={dateTo}
                onChange={e => { setDateTo(e.target.value); setPage(1); }}
              />
              {!isToday && (
                <button
                  className="text-xs text-muted-foreground hover:text-foreground px-1"
                  onClick={() => { setDateFrom(today()); setDateTo(today()); setPage(1); }}
                >
                  Today
                </button>
              )}
            </div>

            {/* Status filter */}
            <Select
              value={filterStatus || 'all'}
              onValueChange={v => { setFilterStatus(v !== 'all' ? v : ''); setPage(1); }}
            >
              <SelectTrigger className="h-8 w-40 text-xs">
                <SelectValue placeholder="All statuses" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All statuses</SelectItem>
                {Object.entries(STATUS_CONFIG).map(([k, v]) => (
                  <SelectItem key={k} value={k}>{v.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        {/* Token table */}
        <div className="flex-1 rounded-xl border bg-card shadow-sm overflow-hidden flex flex-col min-h-0">

          {/* Table header */}
          <div className="grid grid-cols-12 px-3 py-2 border-b bg-muted/30 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground shrink-0">
            <div className="col-span-1">#</div>
            <div className="col-span-2">Truck</div>
            <div className="col-span-2">Party</div>
            <div className="col-span-2">Material</div>
            <div className="col-span-1 text-right">Gross</div>
            <div className="col-span-1 text-right">Tare</div>
            <div className="col-span-1 text-right">Net</div>
            <div className="col-span-1 text-center">Time</div>
            <div className="col-span-1 text-center">Status</div>
          </div>

          {/* Table body */}
          <div className="overflow-y-auto flex-1">
            {loading && tokens.length === 0 ? (
              <div className="flex items-center justify-center py-20">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            ) : tokens.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-20 px-4 text-center">
                <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-muted">
                  <Scale className="h-8 w-8 text-muted-foreground/40" />
                </div>
                <h3 className="text-sm font-semibold">No tokens found</h3>
                <p className="mt-1 max-w-xs text-xs text-muted-foreground">
                  {isToday ? 'Create a new token using the form on the left.' : 'Try adjusting the date or search filters.'}
                </p>
              </div>
            ) : (
              <div className="divide-y">
                {tokens.map(token => {
                  const active = canWeigh(token);
                  return (
                    <div
                      key={token.id}
                      className={cn(
                        'grid grid-cols-12 items-center gap-1 px-3 py-2.5 hover:bg-muted/20 transition-colors text-sm cursor-pointer',
                        active && 'bg-amber-50/60 border-l-2 border-l-amber-400'
                      )}
                      onClick={() => setTokenModalId(token.id)}
                    >
                      {/* Token # */}
                      <div className="col-span-1">
                        <p className="font-bold text-primary text-xs">
                          {token.token_no != null ? `#${token.token_no}` : <span className="text-muted-foreground italic">—</span>}
                        </p>
                        <p className="text-[10px] text-muted-foreground">{token.token_date}</p>
                      </div>

                      {/* Truck */}
                      <div className="col-span-2 min-w-0">
                        <p className="font-semibold text-xs flex items-center gap-1 truncate">
                          <Truck className="h-3 w-3 text-muted-foreground shrink-0" />
                          {token.vehicle_no}
                        </p>
                        <p className="text-[10px] text-muted-foreground capitalize">{token.token_type}</p>
                      </div>

                      {/* Party */}
                      <div className="col-span-2 min-w-0">
                        {token.party
                          ? <p className="text-xs truncate" title={token.party.name}>{token.party.name}</p>
                          : <p className="text-muted-foreground text-xs">—</p>
                        }
                      </div>

                      {/* Material */}
                      <div className="col-span-2 min-w-0">
                        {token.product
                          ? <p className="text-xs truncate text-muted-foreground" title={token.product.name}>{token.product.name}</p>
                          : <p className="text-muted-foreground text-xs">—</p>
                        }
                      </div>

                      {/* Weights */}
                      <div className="col-span-1 text-right font-mono text-xs text-muted-foreground">{wFmt(token.gross_weight)}</div>
                      <div className="col-span-1 text-right font-mono text-xs text-muted-foreground">{wFmt(token.tare_weight)}</div>
                      <div className="col-span-1 text-right font-mono text-xs font-bold">
                        {token.net_weight != null
                          ? <span className="text-primary">{wFmt(token.net_weight)}</span>
                          : <span className="text-muted-foreground">—</span>
                        }
                      </div>

                      {/* Elapsed time */}
                      <div className="col-span-1 text-center">
                        {active && (
                          <span className="flex items-center justify-center gap-0.5 text-[10px] text-amber-600 font-medium">
                            <Clock className="h-3 w-3" />
                            {elapsed(token.created_at)}
                          </span>
                        )}
                      </div>

                      {/* Status + actions */}
                      <div className="col-span-1 flex items-center justify-center gap-1" onClick={e => e.stopPropagation()}>
                        <StatusBadge status={token.status} />
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
                        {isAdmin && token.status !== 'COMPLETED' && token.status !== 'CANCELLED' && (
                          <Button
                            size="icon"
                            variant="ghost"
                            className="h-6 w-6 text-muted-foreground hover:text-destructive shrink-0"
                            title="Cancel token (Admin only)"
                            onClick={() => cancelToken(token.id)}
                          >
                            <XCircle className="h-3.5 w-3.5" />
                          </Button>
                        )}
                        {token.status === 'COMPLETED' && (
                          <>
                            <CheckCircle2 className="h-4 w-4 text-green-500 shrink-0" />
                            <PrintButton
                              url={`/api/v1/tokens/${token.id}/print`}
                              iconOnly
                            />
                            <Button
                              size="icon"
                              variant="ghost"
                              className="h-6 w-6 text-blue-500 hover:text-blue-700 hover:bg-blue-50 shrink-0"
                              title="View camera snapshots"
                              onClick={() => setSnapshotTokenId(token.id)}
                            >
                              <Camera className="h-3.5 w-3.5" />
                            </Button>
                          </>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Pagination */}
          {total > PAGE_SIZE && (
            <div className="flex items-center justify-between px-3 py-2 border-t bg-muted/20 text-xs text-muted-foreground shrink-0">
              <span>
                {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, total)} of {total}
              </span>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" className="h-7 text-xs" disabled={page === 1} onClick={() => setPage(p => p - 1)}>Prev</Button>
                <Button variant="outline" size="sm" className="h-7 text-xs" disabled={page * PAGE_SIZE >= total} onClick={() => setPage(p => p + 1)}>Next</Button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ==================== DIALOGS ==================== */}
      <WeightCaptureDialog
        token={weightToken}
        weightStage={weightStage}
        open={weightOpen}
        onClose={() => setWeightOpen(false)}
        onDone={handleWeightDone}
      />
      <TokenDetailModal
        tokenId={tokenModalId}
        onClose={() => setTokenModalId(null)}
      />
      <SnapshotLightboxModal
        tokenId={snapshotTokenId}
        onClose={() => setSnapshotTokenId(null)}
      />
    </div>
  );
}
