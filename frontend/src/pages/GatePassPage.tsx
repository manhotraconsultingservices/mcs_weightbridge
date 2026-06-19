/**
 * GatePassPage — Guard's gate management screen.
 *
 * Guard workflow:
 *   ENTRY: New Gate Pass → fill details → Capture Entry Photo → Create
 *   EXIT : Find GP in "Inside" list → Record Exit → link token (mandatory for
 *          weighbridge purpose) → Capture Exit Photo → Confirm
 *
 * Two tabs: "Inside" (currently on premises) and "All Today" (full log).
 * Summary strip shows entered / exited / still inside at a glance.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { Camera, LogIn, LogOut, Plus, RefreshCw, Search, X, Link2, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import api from '@/services/api';
import { useAuth } from '@/hooks/useAuth';
import type { GatePass, GatePassSummary } from '@/types';

// ── Field helper ───────────────────────────────────────────────────────────────
function Field({ label, value, onChange, placeholder, type = 'text', required = false }: {
  label: string; value: string; onChange: (v: string) => void;
  placeholder?: string; type?: string; required?: boolean;
}) {
  return (
    <div className="space-y-1">
      <label className="text-xs font-medium text-muted-foreground">{label}{required && ' *'}</label>
      <Input type={type} value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder} />
    </div>
  );
}

// ── Photo thumbnail ────────────────────────────────────────────────────────────
function PhotoThumb({ path, label }: { path: string | null; label: string }) {
  const [lightbox, setLightbox] = useState(false);
  if (!path) return <span className="text-xs text-muted-foreground italic">No {label} photo</span>;
  const url = `/${path}`;
  return (
    <>
      <button onClick={() => setLightbox(true)} className="block">
        <img src={url} alt={label} className="h-16 w-24 object-cover rounded border hover:opacity-80 transition" />
      </button>
      {lightbox && (
        <div className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center" onClick={() => setLightbox(false)}>
          <img src={url} alt={label} className="max-h-[90vh] max-w-[90vw] rounded shadow-2xl" />
        </div>
      )}
    </>
  );
}

// ── Status badge ───────────────────────────────────────────────────────────────
const STATUS_STYLE: Record<string, string> = {
  inside: 'bg-amber-100 text-amber-800 border-amber-300',
  exited: 'bg-green-100 text-green-800 border-green-300',
  cancelled: 'bg-slate-100 text-slate-600 border-slate-300',
};
const STATUS_LABEL: Record<string, string> = { inside: 'Inside', exited: 'Exited', cancelled: 'Cancelled' };

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`text-xs font-semibold px-2 py-0.5 rounded border ${STATUS_STYLE[status] ?? ''}`}>
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

// ── Purpose colours ────────────────────────────────────────────────────────────
const PURPOSE_LABEL: Record<string, string> = {
  weighbridge: 'Weighbridge', delivery: 'Delivery', pickup: 'Pickup',
  own_use: 'Own Use', other: 'Other',
};

function fmt(dt: string | null) {
  if (!dt) return '—';
  return new Date(dt).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
}

// ── Capture button ─────────────────────────────────────────────────────────────
function CaptureButton({ position, gatePassId, onCapture, disabled }: {
  position: 'entry' | 'exit';
  gatePassId?: string;
  onCapture: (path: string) => void;
  disabled?: boolean;
}) {
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');

  async function capture() {
    setLoading(true);
    setErr('');
    try {
      const { data } = await api.post<{ photo_path: string }>(`/api/v1/gate/capture/${position}`, {
        gate_pass_id: gatePassId,
      });
      onCapture(data.photo_path);
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setErr(msg ?? 'Camera capture failed');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-1">
      <Button size="sm" variant="outline" onClick={capture} disabled={loading || disabled}>
        {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" /> : <Camera className="h-3.5 w-3.5 mr-1.5" />}
        Capture {position === 'entry' ? 'Entry' : 'Exit'} Photo
      </Button>
      {err && <p className="text-xs text-destructive">{err}</p>}
    </div>
  );
}

// ── New Gate Pass dialog ───────────────────────────────────────────────────────
function NewGatePassDialog({ open, onClose, onCreated }: {
  open: boolean; onClose: () => void; onCreated: (gp: GatePass) => void;
}) {
  const emptyForm = {
    vehicle_no: '', vehicle_name: '', driver_name: '', driver_phone: '',
    material: '', purpose: 'weighbridge' as string, notes: '',
  };
  const [form, setForm] = useState(emptyForm);
  const [capturedPhoto, setCapturedPhoto] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');

  function reset() { setForm(emptyForm); setCapturedPhoto(null); setErr(''); }

  async function create() {
    if (!form.vehicle_no.trim()) { setErr('Vehicle number is required'); return; }
    setSaving(true);
    setErr('');
    try {
      const { data } = await api.post<GatePass>('/api/v1/gate/passes', {
        ...form,
        capture_photo: !capturedPhoto, // if guard already captured, skip background capture
        entry_photo_path: capturedPhoto,
      });
      reset();
      onCreated(data);
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setErr(msg ?? 'Failed to create gate pass');
    } finally {
      setSaving(false);
    }
  }

  const set = (k: string, v: string) => setForm(f => ({ ...f, [k]: v }));

  return (
    <Dialog open={open} onOpenChange={v => { if (!v) { reset(); onClose(); } }}>
      <DialogContent className="max-w-lg">
        <DialogHeader><DialogTitle className="flex items-center gap-2"><LogIn className="h-4 w-4 text-green-600" /> New Gate Pass — Vehicle Entry</DialogTitle></DialogHeader>

        <div className="space-y-3">
          {err && <p className="text-sm text-destructive bg-destructive/10 rounded p-2">{err}</p>}

          <div className="grid grid-cols-2 gap-3">
            <Field label="Vehicle Number" value={form.vehicle_no} onChange={v => set('vehicle_no', v.toUpperCase())} placeholder="MH12AB1234" required />
            <Field label="Vehicle Name" value={form.vehicle_name} onChange={v => set('vehicle_name', v)} placeholder="Tata 407 Tipper" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Driver Name" value={form.driver_name} onChange={v => set('driver_name', v)} placeholder="Ramesh Kumar" />
            <Field label="Driver Phone" value={form.driver_phone} onChange={v => set('driver_phone', v)} placeholder="9876543210" type="tel" />
          </div>
          <Field label="Material / Purpose of Visit" value={form.material} onChange={v => set('material', v)} placeholder="Aggregates 20mm — 5 trips" />
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">Visit Type</label>
            <Select value={form.purpose} onValueChange={v => set('purpose', v ?? 'weighbridge')}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {Object.entries(PURPOSE_LABEL).map(([k, v]) => (
                  <SelectItem key={k} value={k}>{v}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Entry photo */}
          <div className="rounded-md border p-3 space-y-2 bg-muted/30">
            <p className="text-xs font-medium text-muted-foreground">Entry Photo</p>
            {capturedPhoto
              ? <div className="flex items-center gap-3">
                  <PhotoThumb path={capturedPhoto} label="entry" />
                  <Button size="sm" variant="ghost" onClick={() => setCapturedPhoto(null)}>
                    <X className="h-3.5 w-3.5" />
                  </Button>
                </div>
              : <CaptureButton position="entry" onCapture={setCapturedPhoto} />
            }
            <p className="text-xs text-muted-foreground">
              Photo will also auto-capture in the background after creating the gate pass.
            </p>
          </div>

          <Field label="Notes" value={form.notes} onChange={v => set('notes', v)} placeholder="Optional remarks" />
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <Button variant="outline" onClick={() => { reset(); onClose(); }}>Cancel</Button>
          <Button onClick={create} disabled={saving}>
            {saving && <Loader2 className="h-4 w-4 animate-spin mr-1.5" />}
            <LogIn className="h-4 w-4 mr-1.5" /> Create Gate Pass
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ── Exit dialog ────────────────────────────────────────────────────────────────
function ExitDialog({ gp, open, onClose, onExited }: {
  gp: GatePass; open: boolean; onClose: () => void; onExited: () => void;
}) {
  const [tokenSearch, setTokenSearch] = useState('');
  const [tokenId, setTokenId] = useState(gp.token_id ?? '');
  const [capturedPhoto, setCapturedPhoto] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');

  const needsToken = gp.purpose === 'weighbridge' && !gp.token_id;

  async function doExit() {
    if (needsToken && !tokenId.trim()) {
      setErr('Token ID or token number must be linked before closing a weighbridge gate pass.');
      return;
    }
    setSaving(true);
    setErr('');
    try {
      await api.post(`/api/v1/gate/passes/${gp.id}/exit`, {
        token_id: tokenId || undefined,
        capture_photo: !capturedPhoto,
        exit_photo_path: capturedPhoto,
      });
      onExited();
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setErr(msg ?? 'Failed to record exit');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={v => { if (!v) onClose(); }}>
      <DialogContent className="max-w-md">
        <DialogHeader><DialogTitle className="flex items-center gap-2"><LogOut className="h-4 w-4 text-blue-600" /> Record Exit — {gp.gate_pass_no}</DialogTitle></DialogHeader>

        <div className="space-y-4">
          {err && <p className="text-sm text-destructive bg-destructive/10 rounded p-2">{err}</p>}

          <div className="rounded-md border p-3 space-y-1 bg-muted/30 text-sm">
            <p><span className="font-medium">Vehicle:</span> {gp.vehicle_no ?? '—'} {gp.vehicle_name ? `(${gp.vehicle_name})` : ''}</p>
            <p><span className="font-medium">Driver:</span> {gp.driver_name ?? '—'}</p>
            <p><span className="font-medium">Material:</span> {gp.material ?? '—'}</p>
            <p><span className="font-medium">Entered:</span> {new Date(gp.entry_time).toLocaleString('en-IN')}</p>
          </div>

          {/* Token link */}
          {gp.purpose === 'weighbridge' && (
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground flex items-center gap-1">
                <Link2 className="h-3 w-3" /> Linked Token {needsToken && <span className="text-destructive">*</span>}
              </label>
              {gp.token_id
                ? <p className="text-sm text-green-600">✓ Token already linked ({gp.token_no ?? gp.token_id})</p>
                : <Input value={tokenId} onChange={e => setTokenId(e.target.value)}
                    placeholder="Paste token ID from Trips page" />
              }
              {needsToken && <p className="text-xs text-muted-foreground">
                Go to Trips, find this truck's completed token, copy its ID, and paste here.
              </p>}
            </div>
          )}

          {/* Exit photo */}
          <div className="rounded-md border p-3 space-y-2 bg-muted/30">
            <p className="text-xs font-medium text-muted-foreground">Exit Photo</p>
            {capturedPhoto
              ? <div className="flex items-center gap-3">
                  <PhotoThumb path={capturedPhoto} label="exit" />
                  <Button size="sm" variant="ghost" onClick={() => setCapturedPhoto(null)}>
                    <X className="h-3.5 w-3.5" />
                  </Button>
                </div>
              : <CaptureButton position="exit" gatePassId={gp.id} onCapture={setCapturedPhoto} />
            }
          </div>
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={doExit} disabled={saving} className="bg-blue-600 hover:bg-blue-700">
            {saving && <Loader2 className="h-4 w-4 animate-spin mr-1.5" />}
            <LogOut className="h-4 w-4 mr-1.5" /> Confirm Exit
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ── Gate Pass card ─────────────────────────────────────────────────────────────
function GatePassCard({ gp, onRefresh }: { gp: GatePass; onRefresh: () => void }) {
  const [exitOpen, setExitOpen] = useState(false);

  return (
    <Card className="overflow-hidden">
      <CardContent className="p-4">
        <div className="flex items-start justify-between gap-3">
          {/* Left: photos */}
          <div className="flex gap-2 shrink-0">
            <PhotoThumb path={gp.entry_photo_path} label="entry" />
            {gp.status === 'exited' && <PhotoThumb path={gp.exit_photo_path} label="exit" />}
          </div>

          {/* Centre: details */}
          <div className="flex-1 min-w-0 space-y-1.5">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-bold text-sm">{gp.gate_pass_no}</span>
              <StatusBadge status={gp.status} />
              <Badge variant="outline" className="text-xs">{PURPOSE_LABEL[gp.purpose] ?? gp.purpose}</Badge>
            </div>
            <p className="font-semibold text-base leading-tight">{gp.vehicle_no ?? 'Unknown Vehicle'}</p>
            {gp.vehicle_name && <p className="text-xs text-muted-foreground">{gp.vehicle_name}</p>}
            {gp.driver_name && <p className="text-xs text-muted-foreground">Driver: {gp.driver_name}{gp.driver_phone ? ` · ${gp.driver_phone}` : ''}</p>}
            {gp.material && <p className="text-xs text-muted-foreground">Material: {gp.material}</p>}
            <div className="flex gap-4 text-xs text-muted-foreground pt-0.5">
              <span>In: <span className="font-medium text-foreground">{fmt(gp.entry_time)}</span></span>
              {gp.exit_time && <span>Out: <span className="font-medium text-foreground">{fmt(gp.exit_time)}</span></span>}
              {gp.token_no && <span>Token: <span className="font-medium text-foreground">#{gp.token_no}</span></span>}
            </div>
          </div>

          {/* Right: actions */}
          {gp.status === 'inside' && (
            <Button
              size="sm"
              className="bg-blue-600 hover:bg-blue-700 shrink-0"
              onClick={() => setExitOpen(true)}
            >
              <LogOut className="h-3.5 w-3.5 mr-1" /> Exit
            </Button>
          )}
        </div>
      </CardContent>

      {exitOpen && (
        <ExitDialog
          gp={gp}
          open={exitOpen}
          onClose={() => setExitOpen(false)}
          onExited={() => { setExitOpen(false); onRefresh(); }}
        />
      )}
    </Card>
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
    } catch {
      /* leave empty */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Auto-refresh every 60 s
  useEffect(() => {
    const id = setInterval(load, 60_000);
    return () => clearInterval(id);
  }, [load]);

  const filtered = passes.filter(gp => {
    if (tab === 'inside' && gp.status !== 'inside') return false;
    if (search) {
      const q = search.toLowerCase();
      return (
        gp.vehicle_no?.toLowerCase().includes(q) ||
        gp.gate_pass_no.toLowerCase().includes(q) ||
        gp.driver_name?.toLowerCase().includes(q) ||
        gp.material?.toLowerCase().includes(q)
      );
    }
    return true;
  });

  const isGuard = ['gate_guard', 'operator', 'admin'].includes(user?.role ?? '');

  return (
    <div className="space-y-4 max-w-4xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-xl font-bold">Gate Register</h1>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={load} disabled={loading}>
            <RefreshCw className={`h-3.5 w-3.5 mr-1.5 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
          {isGuard && (
            <Button onClick={() => setNewOpen(true)}>
              <Plus className="h-4 w-4 mr-1.5" /> New Gate Pass
            </Button>
          )}
        </div>
      </div>

      {/* Summary strip */}
      {summary && (
        <div className={`rounded-lg border p-4 ${summary.mismatch ? 'border-amber-400 bg-amber-50' : 'border-green-300 bg-green-50'}`}>
          <div className="flex items-center gap-6 flex-wrap text-sm">
            <span className="flex items-center gap-1.5">
              <LogIn className="h-4 w-4 text-green-700" />
              <span className="font-bold text-green-700">{summary.total_entered}</span>
              <span className="text-muted-foreground">Entered</span>
            </span>
            <span className="flex items-center gap-1.5">
              <LogOut className="h-4 w-4 text-blue-700" />
              <span className="font-bold text-blue-700">{summary.total_exited}</span>
              <span className="text-muted-foreground">Exited</span>
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-amber-500 inline-block" />
              <span className="font-bold text-amber-700">{summary.currently_inside}</span>
              <span className="text-muted-foreground">Still Inside</span>
            </span>
            {summary.unlinked_weighbridge > 0 && (
              <span className="text-amber-700 font-medium">
                ⚠ {summary.unlinked_weighbridge} weighbridge {summary.unlinked_weighbridge === 1 ? 'pass' : 'passes'} not linked to token
              </span>
            )}
            {summary.mismatch && summary.currently_inside > 0 && (
              <span className="ml-auto text-amber-700 font-medium">
                ⚠ {summary.currently_inside} vehicle{summary.currently_inside > 1 ? 's' : ''} on premises — exit not recorded
              </span>
            )}
          </div>
        </div>
      )}

      {/* Search */}
      <div className="relative">
        <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
        <input
          className="w-full pl-9 pr-4 py-2 text-sm border rounded-md bg-background focus:outline-none focus:ring-2 focus:ring-ring"
          placeholder="Search by vehicle no, gate pass no, driver, or material…"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
      </div>

      {/* Tabs */}
      <Tabs value={tab} onValueChange={v => setTab(v as 'inside' | 'all')}>
        <TabsList>
          <TabsTrigger value="inside">
            Inside Now
            {summary && summary.currently_inside > 0 && (
              <span className="ml-2 rounded-full bg-amber-500 text-white text-[10px] font-bold px-1.5 py-0.5">
                {summary.currently_inside}
              </span>
            )}
          </TabsTrigger>
          <TabsTrigger value="all">All Today ({passes.length})</TabsTrigger>
        </TabsList>

        <TabsContent value="inside" className="mt-3 space-y-3">
          {loading ? (
            <div className="flex items-center justify-center py-12 text-muted-foreground">
              <Loader2 className="h-5 w-5 animate-spin mr-2" /> Loading…
            </div>
          ) : filtered.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">
              {search ? 'No matching gate passes' : 'No vehicles currently inside.'}
            </div>
          ) : (
            filtered.map(gp => <GatePassCard key={gp.id} gp={gp} onRefresh={load} />)
          )}
        </TabsContent>

        <TabsContent value="all" className="mt-3 space-y-3">
          {loading ? (
            <div className="flex items-center justify-center py-12 text-muted-foreground">
              <Loader2 className="h-5 w-5 animate-spin mr-2" /> Loading…
            </div>
          ) : filtered.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">No gate passes today.</div>
          ) : (
            filtered.map(gp => <GatePassCard key={gp.id} gp={gp} onRefresh={load} />)
          )}
        </TabsContent>
      </Tabs>

      <NewGatePassDialog
        open={newOpen}
        onClose={() => setNewOpen(false)}
        onCreated={() => { setNewOpen(false); load(); }}
      />
    </div>
  );
}
