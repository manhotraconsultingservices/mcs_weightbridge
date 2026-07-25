import { useEffect, useState, useCallback } from 'react';
import { Truck, Package, User, Scale, Clock, Calendar, Loader2, FileText, CreditCard, UserCheck, Building2, Camera, ImageOff, RefreshCw, ZoomIn, CheckCircle2 } from 'lucide-react';
import { toast } from 'sonner';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import api from '@/services/api';
import { getCurrentUser } from '@/hooks/useAuth';
import type { Token, SnapshotResult, TokenSnapshotsResponse } from '@/types';

const INR = (v: number | string | null | undefined) =>
  '₹' + Number(v ?? 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

// Who may approve a bill (must mirror the cloud require_role on
// /invoices/approve-token). A manager control — operators do NOT approve, online
// OR offline, so the offline outage path can't be used to self-approve a bill.
const APPROVE_ROLES = ['admin', 'accountant', 'store_manager'];

// DB stores kg; UI displays MT (4 decimals).
function wFmt(v: number | null | undefined) {
  if (v == null) return '—';
  return (Number(v) / 1000).toLocaleString('en-IN', { minimumFractionDigits: 4, maximumFractionDigits: 4 }) + ' MT';
}

// Volume in the token's chosen billing unit (canonical storage is CFT) — no MT conversion.
function volFmt(cft: number | null | undefined, unit?: string | null) {
  if (cft == null) return '—';
  const u = (unit || 'CFT').toUpperCase();
  if (u === 'CBM' || u === 'CUM') return (Number(cft) / 35.3147).toFixed(2) + ' CBM';
  if (u === 'BRASS') return (Number(cft) / 100).toFixed(2) + ' Brass';
  return Number(cft).toFixed(2) + ' CFT';
}

const STATUS_COLORS: Record<string, string> = {
  OPEN: 'bg-blue-100 text-blue-700',
  FIRST_WEIGHT: 'bg-amber-100 text-amber-700',
  LOADING: 'bg-orange-100 text-orange-700',
  SECOND_WEIGHT: 'bg-purple-100 text-purple-700',
  COMPLETED: 'bg-green-100 text-green-700',
  CANCELLED: 'bg-red-100 text-red-700',
};

// ── Lightbox ──────────────────────────────────────────────────────────────────
function Lightbox({ src, label, onClose }: { src: string; label: string; onClose: () => void }) {
  return (
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center bg-black/85 backdrop-blur-sm"
      onClick={onClose}
    >
      <div className="relative max-w-4xl w-full mx-4" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-2 px-1">
          <span className="text-white text-sm font-medium flex items-center gap-1.5">
            <Camera className="h-4 w-4" /> {label}
          </span>
          <button
            onClick={onClose}
            className="text-white/60 hover:text-white text-xs border border-white/20 rounded px-2 py-0.5"
          >
            ✕ Close
          </button>
        </div>
        <img
          src={src}
          alt={label}
          className="w-full rounded-lg shadow-2xl"
          style={{ maxHeight: '80vh', objectFit: 'contain' }}
        />
      </div>
    </div>
  );
}

// ── Single camera snapshot card ───────────────────────────────────────────────
function SnapshotCard({
  snap,
  label,
  tokenId,
  onLightbox,
}: {
  snap: SnapshotResult | undefined;
  label: string;
  cameraId: string;
  tokenId: string;
  onLightbox: (src: string, label: string) => void;
}) {
  const displayLabel = snap?.camera_label ?? label;

  if (!snap) {
    // No snapshot record at all (camera disabled / not yet triggered)
    return (
      <div className="rounded-lg border border-dashed bg-muted/20 flex flex-col items-center justify-center gap-1.5 py-6 text-muted-foreground">
        <ImageOff className="h-6 w-6 opacity-40" />
        <p className="text-[11px]">{displayLabel}</p>
        <p className="text-[10px] opacity-60">Not captured</p>
      </div>
    );
  }

  if (snap.capture_status === 'pending') {
    return (
      <div className="rounded-lg border bg-muted/10 flex flex-col items-center justify-center gap-1.5 py-6 text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin opacity-60" />
        <p className="text-[11px] font-medium">{displayLabel}</p>
        <p className="text-[10px] opacity-60">Capturing…</p>
      </div>
    );
  }

  if (snap.capture_status === 'failed') {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 flex flex-col items-center justify-center gap-1 py-6">
        <ImageOff className="h-5 w-5 text-red-400" />
        <p className="text-[11px] font-medium text-red-600">{displayLabel}</p>
        <p className="text-[10px] text-red-400 px-2 text-center line-clamp-2">
          {snap.error_message ?? 'Capture failed'}
        </p>
        <button
          onClick={async () => {
            await api.post(`/api/v1/tokens/${tokenId}/snapshots/retry`).catch(() => {});
          }}
          className="mt-1 flex items-center gap-1 text-[10px] text-red-500 hover:text-red-700 border border-red-200 rounded px-2 py-0.5"
        >
          <RefreshCw className="h-2.5 w-2.5" /> Retry
        </button>
      </div>
    );
  }

  // captured — use relative URL; Vite proxies /uploads → backend:9001
  const src = snap.url ?? '';
  if (!src) return null;

  return (
    <div className="rounded-lg border overflow-hidden group relative cursor-pointer" onClick={() => onLightbox(src, displayLabel)}>
      <img
        src={src}
        alt={displayLabel}
        className="w-full object-cover transition-transform duration-200 group-hover:scale-[1.03]"
        style={{ height: '130px' }}
      />
      {/* overlay */}
      <div className="absolute inset-0 bg-black/0 group-hover:bg-black/30 transition-all flex items-center justify-center">
        <ZoomIn className="h-7 w-7 text-white opacity-0 group-hover:opacity-100 transition-opacity drop-shadow-lg" />
      </div>
      {/* label bar */}
      <div className="absolute bottom-0 inset-x-0 bg-gradient-to-t from-black/70 to-transparent px-2 pt-4 pb-1.5 flex items-end justify-between">
        <span className="text-[10px] text-white font-medium flex items-center gap-1">
          <Camera className="h-2.5 w-2.5" /> {displayLabel}
        </span>
        {snap.captured_at && (
          <span className="text-[9px] text-white/70">
            {new Date(snap.captured_at).toLocaleTimeString('en-IN', { hour12: false })}
          </span>
        )}
      </div>
    </div>
  );
}

// ── Main props ────────────────────────────────────────────────────────────────
interface Props {
  tokenId: string | null;
  onClose: () => void;
}

export function TokenDetailModal({ tokenId, onClose }: Props) {
  const [token, setToken] = useState<Token | null>(null);
  const [loading, setLoading] = useState(false);
  const [snapshots, setSnapshots] = useState<SnapshotResult[]>([]);
  const [lightbox, setLightbox] = useState<{ src: string; label: string } | null>(null);
  const [approving, setApproving] = useState(false);
  const [collectOpen, setCollectOpen] = useState(false);
  const [collectQty, setCollectQty] = useState('');
  const [collectRate, setCollectRate] = useState('');
  const [collectUnit, setCollectUnit] = useState('');
  const [collecting, setCollecting] = useState(false);

  async function openCollect() {
    if (!token?.linked_invoice?.id) return;
    try {
      const { data } = await api.get<{ items?: { quantity: number; rate: number; unit: string }[] }>(`/api/v1/invoices/${token.linked_invoice.id}`);
      const it = data.items?.[0];
      setCollectQty(it ? String(it.quantity) : '');
      setCollectRate(it ? String(it.rate) : '');
      setCollectUnit(it?.unit ?? '');
      setCollectOpen(true);
    } catch { toast.error('Could not load the bill'); }
  }

  async function doCollect() {
    if (!token?.id) return;
    const q = parseFloat(collectQty), r = parseFloat(collectRate);
    if (!q || q <= 0 || isNaN(r) || r < 0) { toast.error('Enter a valid quantity and rate'); return; }
    setCollecting(true);
    try {
      const { data } = await api.post<{ invoice_no: string; grand_total: number; receipt_no: string }>(
        `/api/v1/tokens/${token.id}/collect-cash`, { quantity: q, rate: r });
      toast.success(`Bill ${data.invoice_no} finalised · ${INR(data.grand_total)} cash collected`);
      setCollectOpen(false);
      fetchToken();
    } catch (e: unknown) {
      const d = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(typeof d === 'string' ? d : 'Failed to collect cash');
    } finally { setCollecting(false); }
  }

  // Fetch token details (refetchable — the approve action reloads it)
  const fetchToken = useCallback(() => {
    if (!tokenId) { setToken(null); setSnapshots([]); return; }
    setLoading(true);
    api.get<Token>(`/api/v1/tokens/${tokenId}`)
      .then(r => setToken(r.data))
      .catch(() => setToken(null))
      .finally(() => setLoading(false));
  }, [tokenId]);

  useEffect(() => { fetchToken(); }, [fetchToken]);

  // Approve the bill (P1 #175). Calls the SAME URL online (cloud → finds the
  // token's draft invoice, finalises it, assigns the GST number) and offline
  // (edge → queues an intent that does the same at sync). The base-URL switch
  // picks the target — the frontend calls one endpoint.
  const approve = useCallback(async () => {
    if (!token) return;
    setApproving(true);
    try {
      // Send the approver's identity. Online, the cloud uses the JWT + require_role
      // and ignores this. Offline, the edge stamps it into the intent and the
      // cloud verifies the role + attributes approved_by to this real user at
      // sync (never "system") — closing the offline self-approval gap.
      const me = getCurrentUser();
      await api.post(`/api/v1/invoices/approve-token/${token.id}`, {
        approver_user_id: me?.id ?? null,
        approver_role: me?.role ?? null,
      });
      toast.success(
        navigator.onLine
          ? 'Bill approved — invoice numbered'
          : 'Approved offline — the invoice will be numbered when the link returns',
      );
      fetchToken();
    } catch (e) {
      const err = e as { response?: { status?: number; data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || `Could not approve (HTTP ${err.response?.status ?? '—'})`);
    } finally {
      setApproving(false);
    }
  }, [token, fetchToken]);

  // Only managers approve — consistent online AND offline. Non-managers see the
  // amount (read-only) with an "awaiting manager" note, never the button.
  const canApprove = APPROVE_ROLES.includes(getCurrentUser()?.role ?? '');
  const canCollect = ['operator', 'admin', 'accountant', 'store_manager'].includes(getCurrentUser()?.role ?? '');
  const collectAmount = (parseFloat(collectQty) || 0) * (parseFloat(collectRate) || 0);

  // Fetch snapshots
  const fetchSnapshots = useCallback(() => {
    if (!tokenId) return;
    api.get<TokenSnapshotsResponse>(`/api/v1/tokens/${tokenId}/snapshots`)
      .then(r => setSnapshots(r.data.snapshots))
      .catch(() => {});
  }, [tokenId]);

  useEffect(() => {
    fetchSnapshots();
  }, [fetchSnapshots]);

  // Poll while any snapshot is still pending
  useEffect(() => {
    const hasPending = snapshots.some(s => s.capture_status === 'pending');
    if (!hasPending || !tokenId) return;
    const t = setInterval(fetchSnapshots, 2000);
    return () => clearInterval(t);
  }, [snapshots, tokenId, fetchSnapshots]);

  // Group snapshots by weight stage
  const firstWeightSnaps = snapshots.filter(s => s.weight_stage === 'first_weight');
  const secondWeightSnaps = snapshots.filter(s => s.weight_stage === 'second_weight');
  const hasAnyCamera = snapshots.length > 0 || token?.status === 'COMPLETED' || token?.status === 'FIRST_WEIGHT';

  const open = !!tokenId;

  return (
    <>
      <Dialog open={open} onOpenChange={v => !v && onClose()}>
        <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Scale className="h-4 w-4 text-primary" />
              Token Details
              {token?.token_no != null && (
                <span className="font-mono text-primary">#{token.token_no}</span>
              )}
            </DialogTitle>
          </DialogHeader>

          {loading && (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          )}

          {!loading && !token && (
            <p className="py-8 text-center text-muted-foreground">Token not found.</p>
          )}

          {!loading && token && (
            <div className="space-y-4 text-sm">
              {/* Status + Date */}
              <div className="flex items-center justify-between rounded-lg bg-muted/40 px-4 py-3">
                <div className="flex items-center gap-2">
                  <Calendar className="h-4 w-4 text-muted-foreground" />
                  <span className="font-medium">{token.token_date}</span>
                </div>
                <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_COLORS[token.status] ?? 'bg-muted text-muted-foreground'}`}>
                  {token.status}
                </span>
              </div>

              {/* Vehicle + Type */}
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-lg border p-3">
                  <p className="text-xs text-muted-foreground mb-1 flex items-center gap-1">
                    <Truck className="h-3 w-3" /> Vehicle
                  </p>
                  <p className="font-bold font-mono">{token.vehicle_no}</p>
                  <p className="text-xs text-muted-foreground capitalize mt-0.5">
                    {token.vehicle_type ? `${token.vehicle_type.replace(/_/g, ' ')} · ` : ''}{token.direction} · {token.token_type}
                  </p>
                </div>
                <div className="rounded-lg border p-3">
                  <p className="text-xs text-muted-foreground mb-1 flex items-center gap-1">
                    <Clock className="h-3 w-3" /> Created
                  </p>
                  <p className="font-medium">{new Date(token.created_at).toLocaleString('en-IN', { hour12: false })}</p>
                </div>
              </div>

              {/* Gate Pass + gate movement (when issued / ANPR-tracked) */}
              {(token.gate_pass_no || token.anpr_entry_at || token.anpr_exit_at) && (
                <div className="grid grid-cols-2 gap-3">
                  <div className="rounded-lg border p-3">
                    <p className="text-xs text-muted-foreground mb-1">Gate Pass</p>
                    <p className="font-bold font-mono text-emerald-700">{token.gate_pass_no ?? token.gate_pass ?? '—'}</p>
                    {token.source && token.source !== 'manual' && (
                      <p className="text-[10px] text-muted-foreground mt-0.5 uppercase">via {token.source}</p>
                    )}
                  </div>
                  {(token.anpr_entry_at || token.anpr_exit_at) && (
                    <div className="rounded-lg border p-3">
                      <p className="text-xs text-muted-foreground mb-1 flex items-center gap-1">
                        <Clock className="h-3 w-3" /> Gate Movement
                      </p>
                      <p className="text-xs">In: <b>{token.anpr_entry_at ? new Date(token.anpr_entry_at).toLocaleString('en-IN', { hour12: false }) : '—'}</b></p>
                      <p className="text-xs">Out: <b>{token.anpr_exit_at ? new Date(token.anpr_exit_at).toLocaleString('en-IN', { hour12: false }) : 'still inside'}</b></p>
                    </div>
                  )}
                </div>
              )}

              {/* Party + Product */}
              <div className="grid grid-cols-2 gap-3">
                {token.party && (
                  <div className="rounded-lg border p-3">
                    <p className="text-xs text-muted-foreground mb-1 flex items-center gap-1">
                      <User className="h-3 w-3" /> Party
                    </p>
                    <p className="font-medium">{token.party.name}</p>
                  </div>
                )}
                {token.product && (
                  <div className="rounded-lg border p-3">
                    <p className="text-xs text-muted-foreground mb-1 flex items-center gap-1">
                      <Package className="h-3 w-3" /> Product
                    </p>
                    <p className="font-medium">{token.product.name}</p>
                    <p className="text-xs text-muted-foreground">{token.product.unit}</p>
                  </div>
                )}
              </div>

              {/* Driver + Transporter */}
              {(token.driver || token.transporter) && (
                <div className="grid grid-cols-2 gap-3">
                  {token.driver && (
                    <div className="rounded-lg border p-3">
                      <p className="text-xs text-muted-foreground mb-1 flex items-center gap-1">
                        <UserCheck className="h-3 w-3" /> Driver
                      </p>
                      <p className="font-medium">{token.driver.name}</p>
                      {token.driver.license_no && (
                        <p className="text-xs text-muted-foreground mt-0.5">Lic: {token.driver.license_no}</p>
                      )}
                      {token.driver.phone && (
                        <p className="text-xs text-muted-foreground">{token.driver.phone}</p>
                      )}
                    </div>
                  )}
                  {token.transporter && (
                    <div className="rounded-lg border p-3">
                      <p className="text-xs text-muted-foreground mb-1 flex items-center gap-1">
                        <Building2 className="h-3 w-3" /> Transporter
                      </p>
                      <p className="font-medium">{token.transporter.name}</p>
                      {token.transporter.phone && (
                        <p className="text-xs text-muted-foreground">{token.transporter.phone}</p>
                      )}
                    </div>
                  )}
                </div>
              )}

              {/* Weights */}
              <div className="rounded-lg border overflow-hidden">
                <div className="px-4 py-2 bg-muted/40 border-b">
                  <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">Weighment</p>
                </div>
                <div className="grid grid-cols-3 divide-x">
                  <div className="p-3 text-center">
                    <p className="text-xs text-muted-foreground mb-1">Gross</p>
                    <p className="font-mono font-bold text-sm">{wFmt(token.gross_weight)}</p>
                  </div>
                  <div className="p-3 text-center">
                    <p className="text-xs text-muted-foreground mb-1">Tare</p>
                    <p className="font-mono font-bold text-sm">{wFmt(token.tare_weight)}</p>
                  </div>
                  <div className="p-3 text-center bg-primary/5">
                    <p className="text-xs text-muted-foreground mb-1">{token.weight_method === 'volume' ? 'Volume' : 'Net'}</p>
                    <p className="font-mono font-bold text-sm text-primary">
                      {token.weight_method === 'volume' ? volFmt(token.volume_cft, token.billing_unit) : wFmt(token.net_weight)}
                    </p>
                  </div>
                </div>
              </div>

              {/* ── Camera Snapshots ── */}
              {hasAnyCamera && (
                <div className="rounded-lg border overflow-hidden">
                  <div className="px-4 py-2 bg-muted/40 border-b flex items-center justify-between">
                    <div className="flex items-center gap-1.5">
                      <Camera className="h-3.5 w-3.5 text-muted-foreground" />
                      <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">Camera Snapshots</p>
                    </div>
                    {snapshots.some(s => s.capture_status === 'pending') && (
                      <span className="flex items-center gap-1 text-[10px] text-amber-600">
                        <Loader2 className="h-3 w-3 animate-spin" /> Capturing…
                      </span>
                    )}
                    {snapshots.length > 0 && snapshots.every(s => s.capture_status !== 'pending') && (
                      <button
                        onClick={fetchSnapshots}
                        className="text-[10px] text-muted-foreground hover:text-foreground flex items-center gap-1"
                      >
                        <RefreshCw className="h-3 w-3" /> Refresh
                      </button>
                    )}
                  </div>
                  {/* 1st Weight snapshots */}
                  {(firstWeightSnaps.length > 0 || token.status !== 'OPEN') && (
                    <div className="px-3 pt-3">
                      <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-2">1st Weight</p>
                      <div className="grid grid-cols-2 gap-3">
                        <SnapshotCard
                          snap={firstWeightSnaps.find(s => s.camera_id === 'front')}
                          label="Front View"
                          cameraId="front"
                          tokenId={token.id}
                          onLightbox={(src, lbl) => setLightbox({ src, label: '1st Weight — ' + lbl })}
                        />
                        <SnapshotCard
                          snap={firstWeightSnaps.find(s => s.camera_id === 'top')}
                          label="Top View"
                          cameraId="top"
                          tokenId={token.id}
                          onLightbox={(src, lbl) => setLightbox({ src, label: '1st Weight — ' + lbl })}
                        />
                      </div>
                    </div>
                  )}
                  {/* 2nd Weight snapshots */}
                  {(secondWeightSnaps.length > 0 || token.status === 'COMPLETED') && (
                    <div className="px-3 pt-3 pb-1">
                      <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-2">2nd Weight</p>
                      <div className="grid grid-cols-2 gap-3">
                        <SnapshotCard
                          snap={secondWeightSnaps.find(s => s.camera_id === 'front')}
                          label="Front View"
                          cameraId="front"
                          tokenId={token.id}
                          onLightbox={(src, lbl) => setLightbox({ src, label: '2nd Weight — ' + lbl })}
                        />
                        <SnapshotCard
                          snap={secondWeightSnaps.find(s => s.camera_id === 'top')}
                          label="Top View"
                          cameraId="top"
                          tokenId={token.id}
                          onLightbox={(src, lbl) => setLightbox({ src, label: '2nd Weight — ' + lbl })}
                        />
                      </div>
                    </div>
                  )}
                  <div className="pb-2">
                    {snapshots.some(s => s.capture_status === 'captured') && (
                      <p className="text-[10px] text-muted-foreground text-center">
                        Click image to enlarge
                      </p>
                    )}
                  </div>
                </div>
              )}

              {/* Timestamps */}
              {(token.first_weight_at || token.second_weight_at || token.completed_at) && (
                <div className="rounded-lg border p-3 space-y-1.5 text-xs text-muted-foreground">
                  {token.first_weight_at && (
                    <div className="flex justify-between">
                      <span>1st Weight</span>
                      <span className="font-medium text-foreground">
                        {new Date(token.first_weight_at).toLocaleString('en-IN', { hour12: false })}
                      </span>
                    </div>
                  )}
                  {token.second_weight_at && (
                    <div className="flex justify-between">
                      <span>2nd Weight</span>
                      <span className="font-medium text-foreground">
                        {new Date(token.second_weight_at).toLocaleString('en-IN', { hour12: false })}
                      </span>
                    </div>
                  )}
                  {token.completed_at && (
                    <div className="flex justify-between">
                      <span>Completed</span>
                      <span className="font-medium text-green-600">
                        {new Date(token.completed_at).toLocaleString('en-IN', { hour12: false })}
                      </span>
                    </div>
                  )}
                </div>
              )}

              {token.operator_name && (
                <div className="text-xs text-muted-foreground px-1">
                  Operator: <span className="font-medium text-foreground">{token.operator_name}</span>
                </div>
              )}

              {/* Linked Invoice */}
              {token.linked_invoice && (
                <div className="rounded-lg border overflow-hidden">
                  <div className="px-4 py-2 bg-muted/40 border-b flex items-center gap-1.5">
                    <FileText className="h-3.5 w-3.5 text-muted-foreground" />
                    <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">Invoice</p>
                  </div>
                  <div className="px-4 py-3 flex items-center justify-between gap-2 flex-wrap">
                    <div>
                      <p className="font-mono font-bold text-primary text-sm">
                        {token.linked_invoice.invoice_no ?? <span className="italic text-muted-foreground">Draft</span>}
                      </p>
                      {token.linked_invoice.grand_total != null && (
                        <p className="text-xs text-muted-foreground mt-0.5">
                          ₹{token.linked_invoice.grand_total.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                        </p>
                      )}
                    </div>
                    <div className="flex gap-2">
                      {token.linked_invoice.status && (
                        <span className={`text-[10px] rounded-full px-2 py-0.5 font-medium ${
                          token.linked_invoice.status === 'final' ? 'bg-green-100 text-green-700' :
                          token.linked_invoice.status === 'cancelled' ? 'bg-red-100 text-red-700' :
                          'bg-amber-100 text-amber-700'
                        }`}>{token.linked_invoice.status}</span>
                      )}
                      {token.linked_invoice.payment_status && (
                        <span className={`text-[10px] rounded-full px-2 py-0.5 font-medium ${
                          token.linked_invoice.payment_status === 'paid' ? 'bg-green-100 text-green-700' :
                          token.linked_invoice.payment_status === 'partial' ? 'bg-blue-100 text-blue-700' :
                          'bg-red-100 text-red-700'
                        }`}>
                          <CreditCard className="inline h-2.5 w-2.5 mr-0.5" />
                          {token.linked_invoice.payment_status}
                        </span>
                      )}
                    </div>
                  </div>
                  {/* Approve → server assigns the number (P1 #175). Shown while the
                       invoice is still a draft (pending approval), to managers only. */}
                  {token.linked_invoice.status === 'draft' && (
                    <div className="px-4 pb-3 pt-1 border-t bg-amber-50/40">
                      {canCollect && (
                        <Button size="sm" className="w-full mb-2 gap-1.5 bg-emerald-600 hover:bg-emerald-700" onClick={openCollect}>
                          <CreditCard className="h-3.5 w-3.5" /> Collect Cash — see rate, finalise bill{token.linked_invoice.grand_total != null ? ` · ${INR(token.linked_invoice.grand_total)}` : ''}
                        </Button>
                      )}
                      {canApprove ? (
                        <>
                          <p className="text-[11px] text-muted-foreground mb-2">
                            Review the amount above, then approve — the invoice number is assigned on approval.
                          </p>
                          <Button size="sm" className="w-full" onClick={approve} disabled={approving}>
                            {approving ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" /> : <CheckCircle2 className="h-3.5 w-3.5 mr-1" />}
                            Approve bill{token.linked_invoice.grand_total != null ? ` · ${INR(token.linked_invoice.grand_total)}` : ''}
                          </Button>
                        </>
                      ) : (
                        <p className="text-[11px] text-muted-foreground">
                          Draft — awaiting approval by a manager (admin / accountant / store manager).
                        </p>
                      )}
                    </div>
                  )}
                </div>
              )}

              {/* Offline bill (no cloud invoice yet) — estimate + approve.
                   The edge computes bill_estimate from the mirror; the real amount
                   + GST number are assigned by the server at sync. */}
              {!token.linked_invoice && token.bill_estimate != null &&
                (token.token_type === 'sale' || token.token_type === 'purchase') && (
                <div className="rounded-lg border border-amber-200 overflow-hidden">
                  <div className="px-4 py-2 bg-amber-50 border-b border-amber-200 flex items-center gap-1.5">
                    <FileText className="h-3.5 w-3.5 text-amber-600" />
                    <p className="text-xs font-semibold uppercase tracking-widest text-amber-700">Bill (offline)</p>
                  </div>
                  <div className="px-4 py-3">
                    <div className="flex items-baseline justify-between">
                      <span className="text-xs text-muted-foreground">Estimated amount</span>
                      <span className="font-mono font-bold text-lg">{INR(token.bill_estimate)}</span>
                    </div>
                    <p className="text-[10px] text-muted-foreground mt-1">
                      Estimate from local rates. The final amount + GST invoice number are assigned by the server at sync.
                    </p>
                    {token.approve_queued ? (
                      <div className="mt-2 flex items-center gap-1.5 text-xs text-green-700 bg-green-50 rounded-md px-3 py-2">
                        <CheckCircle2 className="h-4 w-4" /> Approved — will be numbered at sync
                      </div>
                    ) : canApprove ? (
                      <Button size="sm" className="w-full mt-2" onClick={approve} disabled={approving}>
                        {approving ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" /> : <CheckCircle2 className="h-3.5 w-3.5 mr-1" />}
                        Approve bill · {INR(token.bill_estimate)}
                      </Button>
                    ) : (
                      <p className="mt-2 text-[11px] text-muted-foreground">
                        Awaiting approval by a manager (admin / accountant / store manager).
                      </p>
                    )}
                  </div>
                </div>
              )}

              {token.remarks && (
                <div className="rounded-lg bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
                  <span className="font-medium">Remarks: </span>{token.remarks}
                </div>
              )}

              {token.is_manual_weight && (
                <p className="text-[10px] text-amber-600 text-center">⚠ Weight entered manually (scale not used)</p>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Collect Cash — operator confirms qty/rate, finalises the bill + records cash */}
      <Dialog open={collectOpen} onOpenChange={(o) => { if (!o) setCollectOpen(false); }}>
        <DialogContent className="max-w-sm">
          <DialogHeader><DialogTitle>Collect Cash</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <p className="text-xs text-muted-foreground">
              Confirm the quantity &amp; rate, then finalise the bill and collect the cash. The rate is pulled from your pricing — adjust it here if needed.
            </p>
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1">
                <label className="text-xs font-medium">Quantity{collectUnit ? ` (${collectUnit})` : ''}</label>
                <Input type="number" min="0" step="0.001" value={collectQty} onChange={e => setCollectQty(e.target.value)} />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-medium">Rate (₹{collectUnit ? `/${collectUnit}` : ''})</label>
                <Input type="number" min="0" value={collectRate} onChange={e => setCollectRate(e.target.value)} />
              </div>
            </div>
            <div className="flex items-center justify-between rounded-md bg-emerald-50 px-3 py-2">
              <span className="text-sm font-medium">Amount</span>
              <span className="text-lg font-bold text-emerald-700">{INR(collectAmount)}</span>
            </div>
            <p className="text-[11px] text-muted-foreground">GST (if applicable) is added on the bill — the final total is on the invoice.</p>
            <Button onClick={doCollect} disabled={collecting} className="w-full gap-1.5 bg-emerald-600 hover:bg-emerald-700">
              {collecting ? <Loader2 className="h-4 w-4 animate-spin" /> : <CreditCard className="h-4 w-4" />}
              Finalise bill &amp; collect cash
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Full-screen lightbox (outside Dialog so it stacks on top) */}
      {lightbox && (
        <Lightbox
          src={lightbox.src}
          label={lightbox.label}
          onClose={() => setLightbox(null)}
        />
      )}
    </>
  );
}
