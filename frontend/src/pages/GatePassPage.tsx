/**
 * GatePassPage — Guard's gate register.
 *
 * Entry: Big green "TRUCK IN" button → type plate + driver → tap IN.
 * Edit:  Pencil icon on any pass → update vehicle, driver, material, purpose, notes.
 * Exit:  Find truck in "INSIDE NOW" list → tap big red "TRUCK OUT" button.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ChevronDown, ChevronUp, Eye, FileText, Link2, Loader2, LogIn, LogOut,
  Pencil, RefreshCw, Search, Truck,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import api from '@/services/api';
import { useAuth } from '@/hooks/useAuth';
import { TokenDetailModal } from '@/components/TokenDetailModal';
import type { GatePass, GatePassSummary } from '@/types';

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(dt: string | null) {
  if (!dt) return '—';
  return new Date(dt).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
}

function errMsg(e: unknown) {
  return (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Something went wrong. Try again.';
}

const PURPOSE_LABEL: Record<string, string> = {
  weighbridge: 'Weighbridge', delivery: 'Delivery', pickup: 'Pickup',
  own_use: 'Own Use', other: 'Other',
};

// ── Photo lightbox ────────────────────────────────────────────────────────────
function PhotoThumb({ path, label, fullSize }: { path: string | null; label: string; fullSize?: boolean }) {
  const [open, setOpen] = useState(false);
  if (!path) return null;
  const url = `/${path}`;
  return (
    <>
      <button onClick={() => setOpen(true)} className="block w-full">
        <img
          src={url}
          alt={label}
          className={fullSize
            ? 'w-full max-h-64 object-cover rounded-lg border hover:opacity-90 transition'
            : 'h-14 w-20 object-cover rounded border hover:opacity-80 transition'
          }
        />
      </button>
      {open && (
        <div className="fixed inset-0 z-[60] bg-black/80 flex items-center justify-center" onClick={() => setOpen(false)}>
          <img src={url} alt={label} className="max-h-[90vh] max-w-[90vw] rounded shadow-2xl" />
        </div>
      )}
    </>
  );
}

// ── Gate Pass Detail Modal ────────────────────────────────────────────────────
function GatePassDetailModal({ gp, open, onClose }: {
  gp: GatePass; open: boolean; onClose: () => void;
}) {
  const [tokenModalId, setTokenModalId] = useState<string | null>(null);

  if (!open) return null;

  const fmtDateTime = (dt: string | null) => {
    if (!dt) return '—';
    return new Date(dt).toLocaleString('en-IN', {
      day: '2-digit', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit', hour12: true,
    });
  };

  return (
    <>
      <Dialog open={open} onOpenChange={v => { if (!v) onClose(); }}>
        <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-lg font-bold">
              <Truck className="h-5 w-5 text-primary" />
              Gate Pass — <span className="font-mono text-primary">{gp.gate_pass_no}</span>
            </DialogTitle>
          </DialogHeader>

          <div className="space-y-5">
            {/* Vehicle info */}
            <div className="rounded-lg bg-muted/50 p-4 space-y-1">
              <p className="text-3xl font-extrabold tracking-widest">{gp.vehicle_no ?? '—'}</p>
              {gp.vehicle_type && (
                <p className="text-sm font-medium text-muted-foreground capitalize">{gp.vehicle_type}</p>
              )}
              {gp.vehicle_name && (
                <p className="text-sm text-muted-foreground">{gp.vehicle_name}</p>
              )}
              {gp.driver_name && (
                <p className="text-sm text-muted-foreground">
                  Driver: {gp.driver_name}{gp.driver_phone ? ` · ${gp.driver_phone}` : ''}
                </p>
              )}
              <div className="flex gap-2 flex-wrap pt-1">
                <Badge variant="outline" className="text-xs">{PURPOSE_LABEL[gp.purpose] ?? gp.purpose}</Badge>
                {gp.material && <Badge variant="outline" className="text-xs">{gp.material}</Badge>}
              </div>
            </div>

            {/* Entry */}
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-sm font-semibold text-green-700">
                <LogIn className="h-4 w-4" />
                <span>Entry — {fmtDateTime(gp.entry_time)}</span>
              </div>
              {gp.entry_photo_path ? (
                <PhotoThumb path={gp.entry_photo_path} label="Entry photo" fullSize />
              ) : (
                <div className="h-32 rounded-lg border border-dashed flex items-center justify-center text-muted-foreground text-xs">
                  No entry photo
                </div>
              )}
            </div>

            {/* Exit */}
            <div className="space-y-2">
              <div className={`flex items-center gap-2 text-sm font-semibold ${gp.exit_time ? 'text-blue-700' : 'text-muted-foreground'}`}>
                <LogOut className="h-4 w-4" />
                <span>Exit — {fmtDateTime(gp.exit_time)}</span>
              </div>
              {gp.exit_photo_path ? (
                <PhotoThumb path={gp.exit_photo_path} label="Exit photo" fullSize />
              ) : (
                <div className="h-32 rounded-lg border border-dashed flex items-center justify-center text-muted-foreground text-xs">
                  {gp.exit_time ? 'No exit photo' : 'Truck still inside'}
                </div>
              )}
            </div>

            {/* Token */}
            {gp.token_id && (
              <div className="rounded-lg border p-3 flex items-center justify-between">
                <div className="flex items-center gap-2 text-sm">
                  <FileText className="h-4 w-4 text-muted-foreground" />
                  <span className="text-muted-foreground">Weigh Token:</span>
                  <span className="font-bold">#{gp.token_no ?? gp.token_id.slice(0, 8)}</span>
                  {gp.net_weight != null && (
                    <span className="text-muted-foreground text-xs">
                      · {(Number(gp.net_weight) / 1000).toFixed(3)} MT
                    </span>
                  )}
                </div>
                <button
                  className="flex items-center gap-1 text-xs font-semibold text-primary hover:underline"
                  onClick={() => setTokenModalId(gp.token_id)}
                >
                  <Eye className="h-3.5 w-3.5" /> View
                </button>
              </div>
            )}

            {gp.notes && (
              <p className="text-xs text-muted-foreground border-t pt-3">Notes: {gp.notes}</p>
            )}
          </div>
        </DialogContent>
      </Dialog>

      {tokenModalId && (
        <TokenDetailModal tokenId={tokenModalId} onClose={() => setTokenModalId(null)} />
      )}
    </>
  );
}

// ── TRUCK IN dialog ───────────────────────────────────────────────────────────
function TruckInDialog({ open, onClose, onCreated }: {
  open: boolean; onClose: () => void; onCreated: () => void;
}) {
  const [vehicleNo, setVehicleNo] = useState('');
  const [vehicleType, setVehicleType] = useState('');
  const [driverName, setDriverName] = useState('');
  const [driverPhone, setDriverPhone] = useState('');
  const [showMore, setShowMore] = useState(false);
  const [material, setMaterial] = useState('');
  const [purpose, setPurpose] = useState('weighbridge');
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 80);
  }, [open]);

  function reset() {
    setVehicleNo(''); setVehicleType(''); setDriverName(''); setDriverPhone(''); setMaterial('');
    setPurpose('weighbridge'); setNotes(''); setErr(''); setShowMore(false);
  }

  async function create() {
    if (!vehicleNo.trim()) { setErr('Vehicle number is required'); return; }
    setSaving(true); setErr('');
    try {
      await api.post('/api/v1/gate/passes', {
        vehicle_no: vehicleNo.trim().toUpperCase(),
        vehicle_type: vehicleType.trim() || undefined,
        driver_name: driverName.trim() || undefined,
        driver_phone: driverPhone.trim() || undefined,
        material: material.trim() || undefined,
        purpose,
        notes: notes.trim() || undefined,
        capture_photo: true,
      });
      reset(); onCreated();
    } catch (e) {
      setErr(errMsg(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={v => { if (!v) { reset(); onClose(); } }}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="text-xl font-bold flex items-center gap-2">
            <LogIn className="h-5 w-5 text-green-600" />
            TRUCK ARRIVING
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          {err && <p className="text-sm font-medium text-destructive bg-destructive/10 rounded-md p-3">{err}</p>}

          <div className="space-y-1">
            <label className="text-sm font-semibold">VEHICLE NUMBER *</label>
            <Input
              ref={inputRef}
              value={vehicleNo}
              onChange={e => setVehicleNo(e.target.value.toUpperCase())}
              placeholder="e.g. MH12AB1234"
              className="text-2xl font-bold h-14 tracking-widest text-center"
              onKeyDown={e => e.key === 'Enter' && create()}
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Driver Name</label>
              <Input
                value={driverName}
                onChange={e => setDriverName(e.target.value)}
                placeholder="Ramesh Kumar"
                className="h-10"
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Driver Phone</label>
              <Input
                value={driverPhone}
                onChange={e => setDriverPhone(e.target.value)}
                placeholder="9876543210"
                className="h-10"
              />
            </div>
          </div>

          <button
            type="button"
            className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
            onClick={() => setShowMore(v => !v)}
          >
            {showMore ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
            {showMore ? 'Hide extra details' : 'Add vehicle type / material / purpose / notes'}
          </button>

          {showMore && (
            <div className="space-y-3 border-t pt-3">
              <div className="space-y-1">
                <label className="text-xs font-medium text-muted-foreground">Vehicle Type</label>
                <Input value={vehicleType} onChange={e => setVehicleType(e.target.value)} placeholder="Truck / Tipper / Tractor…" />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-medium text-muted-foreground">Material</label>
                <Input value={material} onChange={e => setMaterial(e.target.value)} placeholder="Aggregates 20mm" />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-medium text-muted-foreground">Visit Type</label>
                <Select value={purpose} onValueChange={v => setPurpose(v ?? 'weighbridge')}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {Object.entries(PURPOSE_LABEL).map(([k, v]) => (
                      <SelectItem key={k} value={k}>{v}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <label className="text-xs font-medium text-muted-foreground">Notes</label>
                <Input value={notes} onChange={e => setNotes(e.target.value)} placeholder="Optional remarks" />
              </div>
            </div>
          )}
        </div>

        <div className="flex gap-3 pt-2">
          <Button variant="outline" className="flex-1" onClick={() => { reset(); onClose(); }}>
            Cancel
          </Button>
          <Button
            className="flex-1 h-14 text-lg font-bold bg-green-600 hover:bg-green-700"
            onClick={create}
            disabled={saving}
          >
            {saving ? <Loader2 className="h-5 w-5 animate-spin mr-2" /> : <LogIn className="h-5 w-5 mr-2" />}
            TRUCK IN
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ── Edit dialog ───────────────────────────────────────────────────────────────
function EditDialog({ gp, open, onClose, onSaved }: {
  gp: GatePass; open: boolean; onClose: () => void; onSaved: () => void;
}) {
  const [form, setForm] = useState({
    vehicle_no: gp.vehicle_no ?? '',
    vehicle_name: gp.vehicle_name ?? '',
    driver_name: gp.driver_name ?? '',
    driver_phone: gp.driver_phone ?? '',
    material: gp.material ?? '',
    purpose: gp.purpose ?? 'weighbridge',
    notes: gp.notes ?? '',
  });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');

  // Re-sync form when gp changes (dialog reused for different rows)
  useEffect(() => {
    if (open) {
      setForm({
        vehicle_no: gp.vehicle_no ?? '',
        vehicle_name: gp.vehicle_name ?? '',
        driver_name: gp.driver_name ?? '',
        driver_phone: gp.driver_phone ?? '',
        material: gp.material ?? '',
        purpose: gp.purpose ?? 'weighbridge',
        notes: gp.notes ?? '',
      });
      setErr('');
    }
  }, [open, gp]);

  async function save() {
    if (!form.vehicle_no.trim()) { setErr('Vehicle number is required'); return; }
    setSaving(true); setErr('');
    try {
      await api.put(`/api/v1/gate/passes/${gp.id}`, form);
      onSaved();
    } catch (e) {
      setErr(errMsg(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={v => { if (!v) onClose(); }}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Pencil className="h-4 w-4" />
            Edit Gate Pass — <span className="font-mono text-primary">{gp.gate_pass_no}</span>
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-3">
          {err && <p className="text-sm font-medium text-destructive bg-destructive/10 rounded-md p-2">{err}</p>}

          <div className="space-y-1">
            <label className="text-xs font-semibold">Vehicle Number *</label>
            <Input
              value={form.vehicle_no}
              onChange={e => setForm(f => ({ ...f, vehicle_no: e.target.value.toUpperCase() }))}
              className="font-bold tracking-widest"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Driver Name</label>
              <Input
                value={form.driver_name}
                onChange={e => setForm(f => ({ ...f, driver_name: e.target.value }))}
                placeholder="Ramesh Kumar"
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Driver Phone</label>
              <Input
                value={form.driver_phone}
                onChange={e => setForm(f => ({ ...f, driver_phone: e.target.value }))}
                placeholder="9876543210"
              />
            </div>
          </div>

          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">Material</label>
            <Input
              value={form.material}
              onChange={e => setForm(f => ({ ...f, material: e.target.value }))}
              placeholder="Aggregates 20mm"
            />
          </div>

          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">Visit Type</label>
            <Select value={form.purpose} onValueChange={v => setForm(f => ({ ...f, purpose: v ?? 'weighbridge' }))}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {Object.entries(PURPOSE_LABEL).map(([k, v]) => (
                  <SelectItem key={k} value={k}>{v}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">Notes</label>
            <Input
              value={form.notes}
              onChange={e => setForm(f => ({ ...f, notes: e.target.value }))}
              placeholder="Optional remarks"
            />
          </div>
        </div>

        <div className="flex gap-3 pt-2">
          <Button variant="outline" className="flex-1" onClick={onClose}>Cancel</Button>
          <Button className="flex-1" onClick={save} disabled={saving}>
            {saving && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
            Save Changes
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ── TRUCK OUT dialog ──────────────────────────────────────────────────────────
function TruckOutDialog({ gp, open, onClose, onExited }: {
  gp: GatePass; open: boolean; onClose: () => void; onExited: () => void;
}) {
  const [tokenId, setTokenId] = useState(gp.token_id ?? '');
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');

  const needsToken = gp.purpose === 'weighbridge' && !gp.token_id;

  async function doExit() {
    if (needsToken && !tokenId.trim()) {
      setErr('This truck used the weighbridge. You must link the token ID before exit.');
      return;
    }
    setSaving(true); setErr('');
    try {
      await api.post(`/api/v1/gate/passes/${gp.id}/exit`, {
        token_id: tokenId || undefined,
        capture_photo: true,
      });
      onExited();
    } catch (e) {
      setErr(errMsg(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={v => { if (!v) onClose(); }}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle className="text-xl font-bold flex items-center gap-2">
            <LogOut className="h-5 w-5 text-red-600" />
            TRUCK LEAVING
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          {err && <p className="text-sm font-medium text-destructive bg-destructive/10 rounded-md p-3">{err}</p>}

          <div className="rounded-lg bg-muted/50 p-4 space-y-1">
            <p className="text-2xl font-extrabold tracking-widest">{gp.vehicle_no}</p>
            {gp.vehicle_name && <p className="text-sm text-muted-foreground">{gp.vehicle_name}</p>}
            {gp.driver_name && <p className="text-sm text-muted-foreground">Driver: {gp.driver_name}</p>}
            <p className="text-xs text-muted-foreground">Entered at {new Date(gp.entry_time).toLocaleString('en-IN')}</p>
          </div>

          {gp.purpose === 'weighbridge' && (
            <div className="space-y-1">
              <label className="text-xs font-medium flex items-center gap-1">
                <Link2 className="h-3 w-3" />
                {gp.token_id
                  ? <span className="text-green-600 font-semibold">✓ Token linked ({gp.token_no ?? gp.token_id})</span>
                  : <span className="text-destructive font-semibold">* Paste token ID (from Trips page)</span>
                }
              </label>
              {!gp.token_id && (
                <Input
                  value={tokenId}
                  onChange={e => setTokenId(e.target.value)}
                  placeholder="Paste token ID here"
                  className="h-10"
                />
              )}
            </div>
          )}
        </div>

        <div className="flex gap-3 pt-2">
          <Button variant="outline" className="flex-1" onClick={onClose}>Cancel</Button>
          <Button
            className="flex-1 h-14 text-lg font-bold bg-red-600 hover:bg-red-700"
            onClick={doExit}
            disabled={saving}
          >
            {saving ? <Loader2 className="h-5 w-5 animate-spin mr-2" /> : <LogOut className="h-5 w-5 mr-2" />}
            TRUCK OUT
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ── Inside card — big, visual ─────────────────────────────────────────────────
function InsideCard({ gp, onRefresh, isGuard }: { gp: GatePass; onRefresh: () => void; isGuard: boolean }) {
  const [exitOpen, setExitOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [detailOpen, setDetailOpen] = useState(false);

  return (
    <Card className="border-2 border-amber-300 bg-amber-50/50">
      <CardContent className="p-4">
        <div className="flex items-center justify-between gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap mb-1">
              <span className="text-2xl font-extrabold tracking-widest">{gp.vehicle_no ?? '—'}</span>
              <Badge variant="outline" className="text-xs">{PURPOSE_LABEL[gp.purpose] ?? gp.purpose}</Badge>
              {gp.vehicle_type && (
                <Badge variant="secondary" className="text-xs capitalize">{gp.vehicle_type}</Badge>
              )}
              {gp.token_no && (
                <Badge className="text-xs bg-green-100 text-green-800 border-green-300">Token #{gp.token_no}</Badge>
              )}
            </div>
            {gp.driver_name && (
              <p className="text-sm text-muted-foreground">
                Driver: {gp.driver_name}{gp.driver_phone ? ` · ${gp.driver_phone}` : ''}
              </p>
            )}
            {gp.material && <p className="text-xs text-muted-foreground">{gp.material}</p>}
            <p className="text-xs text-muted-foreground mt-1">
              IN at <span className="font-semibold text-foreground">{fmt(gp.entry_time)}</span>
              {gp.gate_pass_no && <span className="ml-2 text-[10px] font-mono opacity-60">{gp.gate_pass_no}</span>}
            </p>
            {gp.entry_photo_path && (
              <div className="mt-2">
                <PhotoThumb path={gp.entry_photo_path} label="entry" />
              </div>
            )}
          </div>

          <div className="flex flex-col gap-2 shrink-0">
            <Button
              size="icon"
              variant="outline"
              className="h-9 w-9"
              title="View details"
              onClick={() => setDetailOpen(true)}
            >
              <Eye className="h-4 w-4" />
            </Button>
            {isGuard && (
              <Button
                size="icon"
                variant="outline"
                className="h-9 w-9"
                title="Edit gate pass"
                onClick={() => setEditOpen(true)}
              >
                <Pencil className="h-4 w-4" />
              </Button>
            )}
            {isGuard && (
              <Button
                size="lg"
                className="bg-red-600 hover:bg-red-700 text-white font-bold h-16 px-5 text-base flex-col leading-tight"
                onClick={() => setExitOpen(true)}
              >
                <LogOut className="h-5 w-5 mb-0.5" />
                TRUCK<br />OUT
              </Button>
            )}
          </div>
        </div>
      </CardContent>

      {detailOpen && <GatePassDetailModal gp={gp} open={detailOpen} onClose={() => setDetailOpen(false)} />}
      {exitOpen && (
        <TruckOutDialog
          gp={gp}
          open={exitOpen}
          onClose={() => setExitOpen(false)}
          onExited={() => { setExitOpen(false); onRefresh(); }}
        />
      )}
      {editOpen && (
        <EditDialog
          gp={gp}
          open={editOpen}
          onClose={() => setEditOpen(false)}
          onSaved={() => { setEditOpen(false); onRefresh(); }}
        />
      )}
    </Card>
  );
}

// ── History row (all-today compact) ──────────────────────────────────────────
function HistoryRow({ gp, onRefresh, isGuard }: { gp: GatePass; onRefresh: () => void; isGuard: boolean }) {
  const [exitOpen, setExitOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [detailOpen, setDetailOpen] = useState(false);

  const statusStyle: Record<string, string> = {
    inside: 'bg-amber-100 text-amber-800 border-amber-300',
    exited: 'bg-green-100 text-green-800 border-green-300',
    cancelled: 'bg-slate-100 text-slate-500 border-slate-200',
  };
  const statusLabel: Record<string, string> = { inside: 'Inside', exited: 'Exited', cancelled: 'Cancelled' };

  return (
    <>
      <div className="flex items-center gap-3 rounded-lg border bg-card px-4 py-3">
        <div className="flex-1 min-w-0 cursor-pointer" onClick={() => setDetailOpen(true)}>
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-bold text-base">{gp.vehicle_no ?? '—'}</span>
            <span className={`text-[11px] font-semibold px-1.5 py-0.5 rounded border ${statusStyle[gp.status] ?? ''}`}>
              {statusLabel[gp.status] ?? gp.status}
            </span>
            {gp.vehicle_type && (
              <span className="text-[11px] text-muted-foreground capitalize">{gp.vehicle_type}</span>
            )}
            {gp.driver_name && <span className="text-xs text-muted-foreground">{gp.driver_name}</span>}
            {gp.gate_pass_no && (
              <span className="text-[10px] font-mono text-muted-foreground">{gp.gate_pass_no}</span>
            )}
          </div>
          <p className="text-xs text-muted-foreground mt-0.5">
            In: {fmt(gp.entry_time)}
            {gp.exit_time && <> · Out: {fmt(gp.exit_time)}</>}
            {gp.token_no && <> · Token #{gp.token_no}</>}
            {gp.material && <> · {gp.material}</>}
          </p>
        </div>
        <div className="flex gap-2 items-center shrink-0">
          <PhotoThumb path={gp.entry_photo_path} label="entry" />
          {gp.exit_photo_path && <PhotoThumb path={gp.exit_photo_path} label="exit" />}
          <Button
            size="icon"
            variant="outline"
            className="h-8 w-8"
            title="View details"
            onClick={() => setDetailOpen(true)}
          >
            <Eye className="h-3.5 w-3.5" />
          </Button>
          {isGuard && (
            <Button
              size="icon"
              variant="outline"
              className="h-8 w-8"
              title="Edit"
              onClick={() => setEditOpen(true)}
            >
              <Pencil className="h-3.5 w-3.5" />
            </Button>
          )}
          {isGuard && gp.status === 'inside' && (
            <Button size="sm" className="bg-red-600 hover:bg-red-700" onClick={() => setExitOpen(true)}>
              <LogOut className="h-3.5 w-3.5 mr-1" /> OUT
            </Button>
          )}
        </div>
      </div>
      {detailOpen && <GatePassDetailModal gp={gp} open={detailOpen} onClose={() => setDetailOpen(false)} />}
      {exitOpen && (
        <TruckOutDialog
          gp={gp}
          open={exitOpen}
          onClose={() => setExitOpen(false)}
          onExited={() => { setExitOpen(false); onRefresh(); }}
        />
      )}
      {editOpen && (
        <EditDialog
          gp={gp}
          open={editOpen}
          onClose={() => setEditOpen(false)}
          onSaved={() => { setEditOpen(false); onRefresh(); }}
        />
      )}
    </>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function GatePassPage() {
  const { user } = useAuth();
  const [tab, setTab] = useState<'inside' | 'all'>('inside');
  const [passes, setPasses] = useState<GatePass[]>([]);
  const [summary, setSummary] = useState<GatePassSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [newOpen, setNewOpen] = useState(false);

  const todayRef = useRef(new Date().toISOString().split('T')[0]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [passRes, sumRes] = await Promise.all([
        api.get<{ items: GatePass[] }>('/api/v1/gate/passes', {
          params: { pass_date: todayRef.current, page_size: 200 },
        }),
        api.get<GatePassSummary>('/api/v1/gate/passes/summary'),
      ]);
      setPasses(passRes.data.items ?? []);
      setSummary(sumRes.data);
    } catch { /* leave empty */ } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    const id = setInterval(load, 60_000);
    return () => clearInterval(id);
  }, [load]);

  const filtered = (tab === 'inside' ? passes.filter(gp => gp.status === 'inside') : passes).filter(gp => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (
      gp.vehicle_no?.toLowerCase().includes(q) ||
      gp.gate_pass_no?.toLowerCase().includes(q) ||
      gp.driver_name?.toLowerCase().includes(q) ||
      gp.material?.toLowerCase().includes(q)
    );
  });

  const isGuard = ['gate_guard', 'operator', 'admin'].includes(user?.role ?? '');

  return (
    <div className="space-y-4 max-w-3xl mx-auto">

      {/* ── Summary strip ─────────────────────────────────────────── */}
      {summary && (
        <div className={`rounded-xl border-2 p-4 ${summary.mismatch ? 'border-amber-400 bg-amber-50' : 'border-green-400 bg-green-50'}`}>
          <div className="flex items-center gap-8 flex-wrap">
            <div className="text-center">
              <p className="text-3xl font-extrabold text-green-700">{summary.total_entered}</p>
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Entered</p>
            </div>
            <div className="text-center">
              <p className="text-3xl font-extrabold text-blue-700">{summary.total_exited}</p>
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Exited</p>
            </div>
            <div className="text-center">
              <p className="text-3xl font-extrabold text-amber-700">{summary.currently_inside}</p>
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Still Inside</p>
            </div>
            {summary.unlinked_weighbridge > 0 && (
              <p className="text-sm font-semibold text-amber-700">
                ⚠ {summary.unlinked_weighbridge} weighbridge {summary.unlinked_weighbridge === 1 ? 'pass' : 'passes'} not linked to token
              </p>
            )}
          </div>
        </div>
      )}

      {/* ── TRUCK IN button ────────────────────────────────────────── */}
      <div className="flex gap-3">
        {isGuard && (
          <Button
            className="flex-1 h-16 text-xl font-extrabold bg-green-600 hover:bg-green-700"
            onClick={() => setNewOpen(true)}
          >
            <LogIn className="h-6 w-6 mr-2" /> TRUCK IN
          </Button>
        )}
        <Button variant="outline" className="h-16 px-4" onClick={load} disabled={loading}>
          <RefreshCw className={`h-5 w-5 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      </div>

      {/* ── Search ────────────────────────────────────────────────── */}
      <div className="relative">
        <Search className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
        <input
          className="w-full pl-9 pr-4 py-2.5 text-sm border rounded-md bg-background focus:outline-none focus:ring-2 focus:ring-ring"
          placeholder="Search by vehicle, gate pass, driver, material…"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
      </div>

      {/* ── Tabs ──────────────────────────────────────────────────── */}
      <Tabs value={tab} onValueChange={v => setTab(v as 'inside' | 'all')}>
        <TabsList className="w-full">
          <TabsTrigger value="inside" className="flex-1 text-base font-semibold">
            INSIDE NOW
            {summary && summary.currently_inside > 0 && (
              <span className="ml-2 rounded-full bg-amber-500 text-white text-xs font-bold px-2 py-0.5">
                {summary.currently_inside}
              </span>
            )}
          </TabsTrigger>
          <TabsTrigger value="all" className="flex-1 text-base">
            All Today ({passes.length})
          </TabsTrigger>
        </TabsList>

        <TabsContent value="inside" className="mt-4 space-y-3">
          {loading ? (
            <div className="flex items-center justify-center py-16 text-muted-foreground">
              <Loader2 className="h-6 w-6 animate-spin mr-2" /> Loading…
            </div>
          ) : filtered.length === 0 ? (
            <div className="text-center py-16 text-muted-foreground">
              <LogIn className="h-12 w-12 mx-auto mb-3 opacity-20" />
              <p className="text-lg">{search ? 'No matching vehicles' : 'No vehicles currently inside'}</p>
            </div>
          ) : (
            filtered.map(gp => <InsideCard key={gp.id} gp={gp} onRefresh={load} isGuard={isGuard} />)
          )}
        </TabsContent>

        <TabsContent value="all" className="mt-4 space-y-2">
          {loading ? (
            <div className="flex items-center justify-center py-16 text-muted-foreground">
              <Loader2 className="h-6 w-6 animate-spin mr-2" /> Loading…
            </div>
          ) : filtered.length === 0 ? (
            <div className="text-center py-16 text-muted-foreground">No gate passes today.</div>
          ) : (
            filtered.map(gp => <HistoryRow key={gp.id} gp={gp} onRefresh={load} isGuard={isGuard} />)
          )}
        </TabsContent>
      </Tabs>

      <TruckInDialog
        open={newOpen}
        onClose={() => setNewOpen(false)}
        onCreated={() => { setNewOpen(false); load(); }}
      />
    </div>
  );
}
