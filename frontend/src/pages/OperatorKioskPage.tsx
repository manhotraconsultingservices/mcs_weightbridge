/**
 * Operator Kiosk — the 60-second token.
 *
 * A kiosk-mode, full-bleed flow built for the bridge-side operator. No sidebar,
 * no jargon, no keyboard chases. Three screens:
 *
 *   ① Arrival   — plate in, "Same as last time?" smart suggest, big photo-grid
 *                  product picker, recent-customer carousel, one START button.
 *   ② Weighing  — giant MT readout, single "✓ Capture Weight" button enabled
 *                  only when stable; voice confirmation when captured.
 *   ③ Done      — token summary + 3 big actions (Print · WhatsApp · New Truck).
 *
 * Persistent floating SOS button on all screens calls the manager.
 *
 * Persona: low-literacy operator on a tablet. Every primary control ≥ 64px,
 * vocabulary is action-oriented ("Truck In" not "Token Type · Inbound"), and
 * mistakes are recoverable in one tap.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import {
  Truck, ArrowRight, ArrowDownToLine, ArrowUpFromLine, Scale,
  CheckCircle2, Printer, MessageCircle, RefreshCw, X, LogOut,
  PhoneCall, AlertTriangle, Loader2, Search, Sparkles, ChevronLeft,
  Pencil,
} from 'lucide-react';
import api from '@/services/api';
import { useWeight } from '@/hooks/useWeight';
import LocalScaleBadge from '@/components/LocalScaleBadge';
import { fmtKg, displayToKg, weightUnitLabel, weightUnit } from '@/lib/weightUnit';
import { cacheMasters, readCachedMasters } from '@/lib/mastersCache';
import type { User, Party, Product, Token, TokenListResponse } from '@/types';

// ── Constants ──────────────────────────────────────────────────────────────

// Default volume per tyre-class in CFT (canonical DB unit; weight_kg = volume_cft × bulk_density_kg_per_cft).
const TYRE_VOLUME_CFT: Record<number, number> = {
  4: 106, 6: 247, 8: 353, 10: 459, 12: 600,
};
const TYRE_OPTIONS = [4, 6, 8, 10, 12];

// Volume billing units the operator can pick (canonical storage stays CFT).
// Mirrors the New Trip form so kiosk volume tokens bill by the chosen unit's rate.
const CFT_PER_M3 = 35.3147;
const CFT_PER_BRASS = 100;
const VOLUME_UNITS = ['CFT', 'CBM', 'BRASS'] as const;
const VOLUME_UNIT_LABEL: Record<string, string> = { CFT: 'Cubic Feet', CBM: 'Cubic Meter', BRASS: 'Brass' };
const UNIT_SHORT: Record<string, string> = { CFT: 'CFT', CBM: 'CBM', BRASS: 'Brass' };
const VOLUME_UNIT_SPOKEN: Record<string, string> = { CFT: 'cubic feet', CBM: 'cubic meter', BRASS: 'brass' };
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

// Colors for the avatar circles (consistent per name via hash)
const AVATAR_COLORS = [
  'bg-blue-500', 'bg-emerald-500', 'bg-amber-500', 'bg-rose-500',
  'bg-violet-500', 'bg-cyan-500', 'bg-orange-500', 'bg-pink-500',
  'bg-teal-500', 'bg-indigo-500',
];

function colorFor(name: string): string {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  return AVATAR_COLORS[h % AVATAR_COLORS.length];
}

function initials(name: string): string {
  const words = name.trim().split(/\s+/).slice(0, 2);
  return words.map(w => w[0]?.toUpperCase() ?? '').join('') || '?';
}

// ── Voice confirmation (Web Speech API) ────────────────────────────────────

function speak(text: string) {
  if (typeof window === 'undefined' || !window.speechSynthesis) return;
  try {
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.rate = 0.95;
    u.pitch = 1.0;
    u.volume = 1.0;
    // Prefer Hindi/Indian English voice if available; falls back to default.
    const voices = window.speechSynthesis.getVoices();
    const preferred =
      voices.find(v => /hi[-_]IN/i.test(v.lang)) ||
      voices.find(v => /en[-_]IN/i.test(v.lang)) ||
      voices.find(v => /en/i.test(v.lang));
    if (preferred) u.voice = preferred;
    window.speechSynthesis.speak(u);
  } catch {
    /* speech synthesis is best-effort; never throw */
  }
}

// ── Avatar pill ────────────────────────────────────────────────────────────

function Avatar({ name, size = 'md' }: { name: string; size?: 'md' | 'lg' | 'xl' }) {
  const cls = {
    md: 'h-12 w-12 text-base',
    lg: 'h-16 w-16 text-xl',
    xl: 'h-20 w-20 text-2xl',
  }[size];
  return (
    <div className={`${cls} ${colorFor(name)} rounded-full flex items-center justify-center text-white font-bold shrink-0 shadow-sm`}>
      {initials(name)}
    </div>
  );
}

// ── Smart-suggest payload from /tokens/last-by-vehicle/{plate} ─────────────

interface LastSeen {
  token_type: 'sale' | 'purchase' | 'general';
  vehicle_type: string | null;
  tare_weight: number | null;
  party: { id: string; name: string } | null;
  product: { id: string; name: string; unit: string; bulk_density: number | null } | null;
  last_seen_date: string;
}

// ── Kiosk state machine ────────────────────────────────────────────────────

type Stage = 'arrival' | 'weighing' | 'done';

interface ArrivalDraft {
  vehicle_no: string;
  token_type: 'sale' | 'purchase';
  party: Party | null;
  product: Product | null;
  tyre_count: number | null;     // null → weighbridge mode; number → volume mode
  volume_unit: string;           // volume billing unit (CFT/CBM/BRASS) — volume mode only
  volume_qty: string;            // operator-entered quantity in volume_unit (editable)
  gate_pass_id: string | null;   // required before token creation
  gate_pass_no: string | null;   // display only
}

// ── Main page ──────────────────────────────────────────────────────────────

interface OperatorKioskPageProps {
  user: User;
  onLogout: () => void;
}

export default function OperatorKioskPage({ user, onLogout }: OperatorKioskPageProps) {
  const { t } = useTranslation();
  const nav = useNavigate();
  const [stage, setStage] = useState<Stage>('arrival');
  const [draft, setDraft] = useState<ArrivalDraft>({
    vehicle_no: '', token_type: 'sale', party: null, product: null, tyre_count: null,
    volume_unit: 'CFT', volume_qty: '',
    gate_pass_id: null, gate_pass_no: null,
  });
  const [activeToken, setActiveToken] = useState<Token | null>(null);
  const [sosOpen, setSosOpen] = useState(false);
  const [pendingTokens, setPendingTokens] = useState<Token[]>([]);

  // Fetch in-progress tokens (FIRST_WEIGHT or LOADING) so the operator can
  // pick a truck up where they left it for the 2nd weighing. Refreshed every
  // 15s and after every transition.
  const fetchPending = useCallback(async () => {
    try {
      const today = new Date().toISOString().split('T')[0];
      const { data } = await api.get<TokenListResponse>(
        `/api/v1/tokens?page=1&page_size=50&date_from=${today}`
      );
      setPendingTokens(
        (data.items ?? []).filter(t => t.status === 'FIRST_WEIGHT' || t.status === 'LOADING')
      );
    } catch {
      /* offline / network — leave list as-is so we don't blank the strip on a hiccup */
    }
  }, []);

  useEffect(() => { fetchPending(); }, [fetchPending]);
  useEffect(() => {
    const id = setInterval(fetchPending, 15_000);
    return () => clearInterval(id);
  }, [fetchPending]);

  // Reset to start a brand-new token (also refreshes pending strip)
  const reset = useCallback(() => {
    setDraft({ vehicle_no: '', token_type: 'sale', party: null, product: null, tyre_count: null, volume_unit: 'CFT', volume_qty: '', gate_pass_id: null, gate_pass_no: null });
    setActiveToken(null);
    setStage('arrival');
    fetchPending();
  }, [fetchPending]);

  // Resume a pending truck for its 2nd weighing — jump straight to weighing screen
  const resumeToken = useCallback((tok: Token) => {
    setActiveToken(tok);
    setStage('weighing');
  }, []);

  return (
    <div className="fixed inset-0 bg-slate-50 overflow-hidden flex flex-col">
      {/* ── Top bar: logo + minimal context ── */}
      <header className="bg-white border-b border-slate-200 px-6 py-3 flex items-center gap-4 shrink-0">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-600 text-white shadow-sm">
          <Scale className="h-5 w-5" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-base font-bold text-slate-900">{t('kiosk.truckCounter')}</div>
          <div className="text-xs text-slate-500">Operator: {user.full_name || user.username}</div>
        </div>
        <button
          onClick={() => nav('/tokens-v1')}
          className="text-xs text-slate-500 hover:text-slate-900 underline underline-offset-2 px-3 py-1"
        >
          Advanced view
        </button>
        <button
          onClick={onLogout}
          className="flex items-center gap-1.5 text-sm text-slate-600 hover:text-slate-900 px-2 py-1.5 rounded hover:bg-slate-100"
          title="Logout"
        >
          <LogOut className="h-4 w-4" />
          <span className="hidden sm:inline">{t('sidebar.logout')}</span>
        </button>
      </header>

      {/* ── Body ── */}
      <main className="flex-1 overflow-auto">
        {stage === 'arrival' && (
          <ArrivalScreen
            draft={draft}
            setDraft={setDraft}
            pendingTokens={pendingTokens}
            onResume={resumeToken}
            onProceed={tok => {
              setActiveToken(tok);
              setStage('weighing');
              fetchPending();
            }}
          />
        )}
        {stage === 'weighing' && activeToken && (
          <WeighingScreen
            token={activeToken}
            onParked={() => {
              // After 1st weight: return to arrival so operator can either
              // start a new truck or come back to this one later.
              setActiveToken(null);
              setStage('arrival');
              fetchPending();
            }}
            onDone={t => { setActiveToken(t); setStage('done'); fetchPending(); }}
            onCancel={reset}
          />
        )}
        {stage === 'done' && activeToken && (
          <DoneScreen token={activeToken} onNew={reset} />
        )}
      </main>

      {/* ── Floating SOS ── */}
      <button
        onClick={() => setSosOpen(true)}
        className="fixed bottom-5 right-5 h-14 px-5 rounded-full bg-red-600 hover:bg-red-700 text-white font-bold shadow-lg flex items-center gap-2 text-base z-50"
        title="Call manager"
      >
        <AlertTriangle className="h-5 w-5" />
        {t('kiosk.needHelp')}
      </button>
      {sosOpen && <SosModal onClose={() => setSosOpen(false)} />}
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// SCREEN 1 — ARRIVAL
// ──────────────────────────────────────────────────────────────────────────

interface ArrivalScreenProps {
  draft: ArrivalDraft;
  setDraft: React.Dispatch<React.SetStateAction<ArrivalDraft>>;
  pendingTokens: Token[];
  onResume: (token: Token) => void;
  onProceed: (token: Token) => void;
}

function ArrivalScreen({ draft, setDraft, pendingTokens, onResume, onProceed }: ArrivalScreenProps) {
  const { t } = useTranslation();
  const [parties, setParties] = useState<Party[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [partySearch, setPartySearch] = useState('');
  const [lastSeen, setLastSeen] = useState<LastSeen | null>(null);
  const [lookupBusy, setLookupBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const lookupTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Load master data once. Parties API may return either an array OR a paged
  // {items, total} object depending on the route version — handle both shapes.
  useEffect(() => {
    Promise.all([
      api.get<Party[] | { items: Party[] }>('/api/v1/parties?page_size=500'),
      api.get<Product[] | { items: Product[] }>('/api/v1/products?page_size=200'),
    ]).then(([p, pr]) => {
      const pData = p.data;
      const partyList = Array.isArray(pData) ? pData : (pData as { items: Party[] }).items ?? [];
      const prodData = pr.data;
      const productList = Array.isArray(prodData) ? prodData : (prodData as { items: Product[] }).items ?? [];
      setParties(partyList);
      setProducts(productList);
      // Refresh the offline cache so the kiosk's pickers stay usable in an outage.
      cacheMasters('parties', partyList);
      cacheMasters('products', productList);
    }).catch(() => {
      // Offline → last-known-good so the operator can still pick a buyer/material.
      setParties(readCachedMasters<Party>('parties'));
      setProducts(readCachedMasters<Product>('products'));
    });
  }, []);

  // ── Plate match against in-progress tokens ─────────────────────────────
  // If operator types a plate that already has an OPEN / FIRST_WEIGHT / LOADING
  // token today, surface a HUGE banner offering to resume — this is how a
  // truck comes back for its 2nd weighing without the operator having to
  // hunt through Advanced view. Match is case- and whitespace-insensitive.
  const plateNorm = draft.vehicle_no.trim().toUpperCase().replace(/\s+/g, '');
  const matchingPending = useMemo(() => {
    if (plateNorm.length < 4) return null;
    return pendingTokens.find(t => t.vehicle_no.replace(/\s+/g, '').toUpperCase() === plateNorm) ?? null;
  }, [pendingTokens, plateNorm]);

  // ── Smart suggest: when vehicle plate ≥ 4 chars, look up last seen ────
  useEffect(() => {
    if (lookupTimer.current) clearTimeout(lookupTimer.current);
    const plate = draft.vehicle_no.trim().toUpperCase();
    if (plate.length < 4) {
      setLastSeen(null);
      return;
    }
    lookupTimer.current = setTimeout(async () => {
      setLookupBusy(true);
      try {
        const { data } = await api.get<LastSeen | null>(`/api/v1/tokens/last-by-vehicle/${encodeURIComponent(plate)}`);
        setLastSeen(data);
      } catch {
        setLastSeen(null);
      } finally {
        setLookupBusy(false);
      }
    }, 350);
    return () => { if (lookupTimer.current) clearTimeout(lookupTimer.current); };
  }, [draft.vehicle_no]);

  // ── Gate pass lookup: auto-find the guard's open gate pass for this truck ──
  useEffect(() => {
    const plate = draft.vehicle_no.trim().toUpperCase();
    if (plate.length < 4) {
      setDraft(d => ({ ...d, gate_pass_id: null, gate_pass_no: null }));
      return;
    }
    const t = setTimeout(async () => {
      try {
        const { data } = await api.get<{ items: { id: string; gate_pass_no: string; vehicle_no: string; status: string }[] }>(
          '/api/v1/gate/passes',
          { params: { unlinked: true, status: 'inside', page_size: 50 } }
        );
        const matches = (data.items ?? []).filter(
          gp => gp.vehicle_no?.toUpperCase().replace(/\s+/g, '') === plate.replace(/\s+/g, '')
        );
        if (matches.length === 1) {
          setDraft(d => ({ ...d, gate_pass_id: matches[0].id, gate_pass_no: matches[0].gate_pass_no }));
        } else {
          setDraft(d => ({ ...d, gate_pass_id: null, gate_pass_no: null }));
        }
      } catch {
        setDraft(d => ({ ...d, gate_pass_id: null, gate_pass_no: null }));
      }
    }, 400);
    return () => clearTimeout(t);
  }, [draft.vehicle_no]); // eslint-disable-line react-hooks/exhaustive-deps

  // Filter party list by search. NO cap — show everything in a scrollable
  // grid so the operator can find their customer without typing if literacy
  // is a barrier. Filtering on city as well as name.
  const partyMatches = useMemo(() => {
    const q = partySearch.trim().toLowerCase();
    if (!q) return parties;
    return parties.filter(p =>
      p.name.toLowerCase().includes(q) ||
      (p.billing_city ?? '').toLowerCase().includes(q) ||
      (p.phone ?? '').includes(q)
    );
  }, [parties, partySearch]);

  // Apply last-seen suggestion in one click. Look up the REAL party + product
  // objects from the loaded lists by id (the API smart-suggest endpoint
  // returns only id+name, but the kiosk needs full objects for invoice flow).
  function applyLastSeen() {
    if (!lastSeen) return;
    const realParty = lastSeen.party
      ? parties.find(p => p.id === lastSeen.party!.id) ?? null
      : null;
    const realProduct = lastSeen.product
      ? products.find(p => p.id === lastSeen.product!.id) ?? null
      : null;
    setDraft(d => ({
      ...d,
      token_type: (lastSeen.token_type === 'purchase' ? 'purchase' : 'sale') as 'sale' | 'purchase',
      party: realParty,
      product: realProduct,
    }));
  }

  // ── Volume mode helpers (skip-the-bridge) ─────────────────────────────────
  // Picking a tyre class switches to volume mode and auto-fills the quantity in
  // the current unit; the operator can still overwrite it below.
  function pickTyre(n: number) {
    setDraft(d => ({ ...d, tyre_count: n, volume_qty: String(round3(fromCft(TYRE_VOLUME_CFT[n] ?? 0, d.volume_unit))) }));
  }
  function pickWeigh() {
    setDraft(d => ({ ...d, tyre_count: null, volume_qty: '' }));
  }
  // Switching unit converts the entered quantity so the physical volume is kept
  // (e.g. 600 CFT ⇄ 6 Brass).
  function changeVolumeUnit(next: string) {
    setDraft(d => {
      const q = parseFloat(d.volume_qty || '0');
      const nextQty = q > 0 && d.volume_unit !== next ? String(round3(fromCft(toCft(q, d.volume_unit), next))) : d.volume_qty;
      return { ...d, volume_unit: next, volume_qty: nextQty };
    });
  }
  const isVolume = draft.tyre_count != null;
  const volQty = parseFloat(draft.volume_qty || '0');
  const volCft = isVolume ? toCft(volQty, draft.volume_unit) : 0;
  // Live weight preview: volume_cft × bulk_density(kg/CFT)
  const volWeightKg = draft.product?.bulk_density && volCft > 0 ? volCft * Number(draft.product.bulk_density) : 0;

  // Gate pass is informational — shown when found, but NOT a blocker.
  // The backend auto-creates a gate pass at token creation for any truck
  // that doesn't already have one, so we never need to block on this.
  const canProceed =
    draft.vehicle_no.trim().length >= 4 && !!draft.party && !!draft.product && (!isVolume || volQty > 0);

  // What's missing? Shown below the START button so operator knows why
  // it's disabled. Order: vehicle → product → party → quantity.
  const missingItems: string[] = [];
  if (draft.vehicle_no.trim().length < 4) missingItems.push('Vehicle number');
  if (!draft.product) missingItems.push('Material');
  if (!draft.party) missingItems.push('Customer');
  if (isVolume && volQty <= 0) missingItems.push('Quantity');

  // Create the token (either /tokens or /tokens/volume)
  async function handleStart() {
    if (!canProceed || !draft.party || !draft.product) return;
    setError('');
    setSaving(true);
    try {
      const today = new Date().toISOString().split('T')[0];
      // Volume path: tyre_count selected → one-shot create+complete+invoice.
      // The operator's chosen unit + quantity drive billing; we convert to the
      // canonical CFT for storage and send billing_unit so the per-unit rate applies.
      if (draft.tyre_count != null) {
        const cft = round3(toCft(parseFloat(draft.volume_qty || '0'), draft.volume_unit));
        const { data } = await api.post<Token>('/api/v1/tokens/volume', {
          token_date: today,
          vehicle_no: draft.vehicle_no.trim().toUpperCase(),
          token_type: draft.token_type,
          direction: draft.token_type === 'sale' ? 'outbound' : 'inbound',
          party_id: draft.party.id,
          product_id: draft.product.id,
          volume_cft: cft,
          billing_unit: draft.volume_unit,
          tyre_count: draft.tyre_count,
          gate_pass_id: draft.gate_pass_id,
        });
        speak(
          `Volume token created. ${draft.product.name}, ${draft.volume_qty} ${VOLUME_UNIT_SPOKEN[draft.volume_unit] ?? ''}, for ${draft.party.name}. Bill will print.`,
        );
        onProceed(data);
        return;
      }
      // Weighbridge path — bill in the tenant weight unit (MT, or Qtl for maize).
      const { data } = await api.post<Token>('/api/v1/tokens', {
        token_date: today,
        vehicle_no: draft.vehicle_no.trim().toUpperCase(),
        token_type: draft.token_type,
        direction: draft.token_type === 'sale' ? 'outbound' : 'inbound',
        party_id: draft.party.id,
        product_id: draft.product.id,
        billing_unit: weightUnit().code,
        tyre_count: draft.tyre_count,    // null when "Weigh" is chosen — that's fine
        gate_pass_id: draft.gate_pass_id,
      });
      speak(`Truck in. ${draft.product.name} for ${draft.party.name}. Drive onto the bridge.`);
      onProceed(data);
    } catch (e: unknown) {
      // Handle every error shape: string, Pydantic validation array, plain
      // network error. Operators with no developer to call need the actual
      // backend reason, not a generic "try again".
      const err = e as {
        response?: { status?: number; data?: { detail?: string | Array<{ msg: string; loc?: string[] }> } };
        message?: string;
      };
      const detail = err.response?.data?.detail;
      let msg: string;
      if (typeof detail === 'string') {
        msg = detail;
      } else if (Array.isArray(detail)) {
        msg = detail.map(d => d.msg).join(' · ');
      } else {
        msg = err.message ?? 'Could not start. Check connection or call manager.';
      }
      const code = err.response?.status;
      setError(code ? `[${code}] ${msg}` : msg);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="max-w-5xl mx-auto p-6 space-y-6">
      {/* ── PENDING TRUCKS strip — only shown when there are in-progress tokens ── */}
      {pendingTokens.length > 0 && (
        <section>
          <label className="flex items-center gap-2 text-sm font-semibold uppercase tracking-widest text-amber-700 mb-2">
            <Truck className="h-4 w-4" />
            {t('kiosk.pendingCount')} ({pendingTokens.length})
          </label>
          <div className="flex gap-3 overflow-x-auto pb-2 -mx-1 px-1 snap-x">
            {pendingTokens.map(tok => (
              <button
                key={tok.id}
                onClick={() => onResume(tok)}
                className="snap-start shrink-0 w-56 p-4 rounded-2xl border-2 border-amber-300 bg-amber-50 hover:bg-amber-100 transition-colors text-left shadow-sm"
                title={`Tap to capture 2nd weight for token #${tok.token_no ?? '—'}`}
              >
                <div className="flex items-center gap-2 mb-1">
                  <Truck className="h-4 w-4 text-amber-700 shrink-0" />
                  <span className="font-mono font-bold text-lg text-amber-900 tracking-wide truncate">{tok.vehicle_no}</span>
                </div>
                <div className="text-sm font-semibold text-slate-800 truncate">{tok.party?.name ?? '—'}</div>
                <div className="text-xs text-slate-600 truncate mt-0.5">{tok.product?.name ?? '—'}</div>
                <div className="mt-2 inline-flex items-center gap-1.5 rounded-full bg-amber-200 text-amber-900 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide">
                  <ArrowRight className="h-3 w-3" /> {t('kiosk.waitingForWeight')}
                </div>
              </button>
            ))}
          </div>
          <div className="text-center text-xs text-slate-400 mt-1 uppercase tracking-widest">— {t('kiosk.orStartNew')} —</div>
        </section>
      )}

      {/* Vehicle number — biggest input on the screen */}
      <section>
        <label className="block text-sm font-semibold uppercase tracking-widest text-slate-500 mb-2">
          1.  {t('kiosk.vehicleNumber')}
        </label>
        <div className="flex gap-3">
          <input
            type="text"
            autoFocus
            value={draft.vehicle_no}
            onChange={e => setDraft(d => ({ ...d, vehicle_no: e.target.value.toUpperCase() }))}
            placeholder="MH 12 AB 1234"
            className="flex-1 h-20 text-3xl font-mono font-bold tracking-widest text-center rounded-xl border-2 border-slate-300 focus:border-blue-500 focus:outline-none focus:ring-4 focus:ring-blue-100 bg-white px-4 uppercase"
          />
          {draft.vehicle_no && (
            <button
              onClick={() => setDraft(d => ({ ...d, vehicle_no: '' }))}
              className="h-20 w-20 rounded-xl border-2 border-slate-200 bg-white hover:bg-slate-50 flex items-center justify-center text-slate-400 hover:text-slate-700"
              title="Clear"
            >
              <X className="h-6 w-6" />
            </button>
          )}
        </div>
      </section>

      {/* ── Gate pass status ── */}
      {draft.vehicle_no.trim().length >= 4 && (
        draft.gate_pass_id ? (
          <div className="flex items-center gap-3 rounded-xl border-2 border-emerald-400 bg-emerald-50 px-4 py-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-emerald-600 text-white shrink-0">
              <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
            </div>
            <div>
              <div className="text-xs font-bold uppercase tracking-widest text-emerald-700">Gate Pass Found</div>
              <div className="font-mono font-bold text-emerald-900">{draft.gate_pass_no}</div>
            </div>
          </div>
        ) : (
          <div className="flex items-center gap-3 rounded-xl border border-amber-300 bg-amber-50 px-4 py-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-amber-500 text-white shrink-0">
              <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
            </div>
            <div>
              <div className="text-xs font-bold uppercase tracking-widest text-amber-700">No Gate Pass Yet</div>
              <div className="text-sm text-amber-800">One will be auto-created. Gate guard can register separately.</div>
            </div>
          </div>
        )
      )}

      {/* ── URGENT: plate matches a pending token → big "tap for 2nd weight" banner ── */}
      {matchingPending && (
        <button
          onClick={() => onResume(matchingPending)}
          className="w-full rounded-2xl border-2 border-amber-500 bg-amber-100 hover:bg-amber-200 p-5 flex items-center gap-4 text-left transition-colors shadow-md animate-pulse"
        >
          <div className="flex h-14 w-14 items-center justify-center rounded-full bg-amber-600 text-white shrink-0">
            <Scale className="h-7 w-7" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-xs uppercase tracking-widest text-amber-800 font-bold">{t('kiosk.backFor2ndWeight')}</div>
            <div className="text-lg font-bold text-amber-900 mt-0.5 truncate">
              Token #{matchingPending.token_no ?? '—'} · {matchingPending.party?.name ?? 'Walk-in'}
            </div>
            <div className="text-sm text-amber-800 mt-0.5 truncate">
              {matchingPending.product?.name ?? '—'} · tap to weigh now
            </div>
          </div>
          <ArrowRight className="h-8 w-8 text-amber-800 shrink-0" />
        </button>
      )}

      {/* Smart suggest — only when no pending match AND we found history */}
      {!matchingPending && lookupBusy && (
        <div className="text-center text-sm text-slate-500 flex items-center justify-center gap-2">
          <Loader2 className="h-4 w-4 animate-spin" /> Checking history…
        </div>
      )}
      {!matchingPending && lastSeen && lastSeen.party && lastSeen.product && (
        <button
          onClick={applyLastSeen}
          className="w-full rounded-2xl border-2 border-emerald-300 bg-emerald-50 hover:bg-emerald-100 p-5 flex items-center gap-4 text-left transition-colors"
        >
          <Sparkles className="h-8 w-8 text-emerald-600 shrink-0" />
          <div className="flex-1 min-w-0">
            <div className="text-xs uppercase tracking-widest text-emerald-700 font-semibold">{t('kiosk.sameAsLast')}</div>
            <div className="text-lg font-bold text-emerald-900 mt-0.5">
              {lastSeen.product.name} {lastSeen.token_type === 'sale' ? 'OUT to' : 'IN from'} {lastSeen.party.name}
            </div>
            <div className="text-xs text-emerald-700 mt-0.5">
              Last seen {new Date(lastSeen.last_seen_date).toLocaleDateString('en-IN')}. Tap to use these.
            </div>
          </div>
          <ArrowRight className="h-7 w-7 text-emerald-600 shrink-0" />
        </button>
      )}

      {/* Direction toggle */}
      <section>
        <label className="block text-sm font-semibold uppercase tracking-widest text-slate-500 mb-2">
          2.  {t('kiosk.truckGoing')}
        </label>
        <div className="grid grid-cols-2 gap-3">
          <DirectionTile
            active={draft.token_type === 'sale'}
            label={t('kiosk.truckOut')}
            sub={t('kiosk.truckOutSub')}
            icon={ArrowUpFromLine}
            color="blue"
            onClick={() => setDraft(d => ({ ...d, token_type: 'sale' }))}
          />
          <DirectionTile
            active={draft.token_type === 'purchase'}
            label={t('kiosk.truckIn')}
            sub={t('kiosk.truckInSub')}
            icon={ArrowDownToLine}
            color="amber"
            onClick={() => setDraft(d => ({ ...d, token_type: 'purchase' }))}
          />
        </div>
      </section>

      {/* Product picker — grid of big tiles */}
      <section>
        <label className="block text-sm font-semibold uppercase tracking-widest text-slate-500 mb-2">
          3.  {t('kiosk.material')}
        </label>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
          {products.length === 0 && (
            <div className="col-span-full text-center text-sm text-slate-400 py-6">
              {t('kiosk.noProducts')}
            </div>
          )}
          {products.map(p => {
            const selected = draft.product?.id === p.id;
            return (
              <button
                key={p.id}
                onClick={() => setDraft(d => ({ ...d, product: p }))}
                className={`p-4 rounded-2xl border-2 transition-all flex flex-col items-center gap-2 ${
                  selected
                    ? 'border-blue-500 bg-blue-50 ring-4 ring-blue-100 shadow-sm'
                    : 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50'
                }`}
              >
                <Avatar name={p.name} size="lg" />
                <div className={`text-base font-bold text-center leading-tight ${selected ? 'text-blue-900' : 'text-slate-900'}`}>
                  {p.name}
                </div>
                {selected && <CheckCircle2 className="h-5 w-5 text-blue-600" />}
              </button>
            );
          })}
        </div>
      </section>

      {/* Party picker — search + scrollable grid showing ALL parties */}
      <section>
        <div className="flex items-center justify-between mb-2">
          <label className="block text-sm font-semibold uppercase tracking-widest text-slate-500">
            4.  {draft.token_type === 'sale' ? t('kiosk.customer') : t('kiosk.supplier')}
          </label>
          <span className="text-xs text-slate-400">
            Showing {partyMatches.length} of {parties.length}
          </span>
        </div>
        <div className="relative mb-3">
          <Search className="absolute left-4 top-1/2 -translate-y-1/2 h-5 w-5 text-slate-400" />
          <input
            type="text"
            value={partySearch}
            onChange={e => setPartySearch(e.target.value)}
            placeholder={`Search ${draft.token_type === 'sale' ? t('kiosk.customer') : t('kiosk.supplier')} by name, city, or phone…`}
            className="w-full h-14 pl-12 pr-4 text-base rounded-xl border-2 border-slate-300 focus:border-blue-500 focus:outline-none focus:ring-4 focus:ring-blue-100 bg-white"
          />
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2 max-h-80 overflow-y-auto p-1 rounded-lg border border-slate-200 bg-slate-50/40">
          {partyMatches.map(p => {
            const selected = draft.party?.id === p.id;
            return (
              <button
                key={p.id}
                onClick={() => setDraft(d => ({ ...d, party: p }))}
                className={`p-3 rounded-xl border-2 transition-all flex items-center gap-2 text-left ${
                  selected
                    ? 'border-blue-500 bg-blue-50 ring-2 ring-blue-100'
                    : 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50'
                }`}
              >
                <Avatar name={p.name} size="md" />
                <div className="min-w-0 flex-1">
                  <div className={`text-sm font-bold truncate ${selected ? 'text-blue-900' : 'text-slate-900'}`}>
                    {p.name}
                  </div>
                  {p.billing_city && <div className="text-xs text-slate-500 truncate">{p.billing_city}</div>}
                </div>
              </button>
            );
          })}
          {partyMatches.length === 0 && (
            <div className="col-span-full text-center text-sm text-slate-400 py-4">
              {t('kiosk.noMatch')}
            </div>
          )}
        </div>
      </section>

      {/* Optional: tyre count → volume mode (skip the bridge) */}
      <section>
        <label className="block text-sm font-semibold uppercase tracking-widest text-slate-500 mb-2">
          5.  {t('kiosk.skipWeighbridge')} <span className="text-slate-400 normal-case font-normal">({t('common.optional')})</span>
        </label>
        <div className="grid grid-cols-6 gap-2">
          <button
            onClick={pickWeigh}
            className={`h-16 rounded-xl border-2 font-bold transition-all ${
              draft.tyre_count == null
                ? 'border-blue-500 bg-blue-50 text-blue-900 ring-2 ring-blue-100'
                : 'border-slate-200 bg-white text-slate-700 hover:border-slate-300'
            }`}
          >
            <div className="text-sm uppercase">{t('kiosk.weigh')}</div>
          </button>
          {TYRE_OPTIONS.map(n => {
            const selected = draft.tyre_count === n;
            return (
              <button
                key={n}
                onClick={() => pickTyre(n)}
                className={`h-16 rounded-xl border-2 font-bold transition-all ${
                  selected
                    ? 'border-amber-500 bg-amber-50 text-amber-900 ring-2 ring-amber-100'
                    : 'border-slate-200 bg-white text-slate-700 hover:border-slate-300'
                }`}
              >
                <div className="text-xl">{n} 🛞</div>
                <div className="text-[10px] text-slate-500 mt-0.5">{round3(fromCft(TYRE_VOLUME_CFT[n] ?? 0, draft.volume_unit))} {UNIT_SHORT[draft.volume_unit]}</div>
              </button>
            );
          })}
        </div>

        {/* Volume mode → unit toggle + editable quantity + live weight preview */}
        {isVolume && (
          <div className="mt-3 rounded-2xl border-2 border-amber-200 bg-amber-50/50 p-4 space-y-3">
            {/* Unit toggle */}
            <div>
              <div className="text-xs font-semibold uppercase tracking-widest text-slate-500 mb-1.5">Unit</div>
              <div className="grid grid-cols-3 gap-2">
                {VOLUME_UNITS.map(u => (
                  <button
                    key={u}
                    onClick={() => changeVolumeUnit(u)}
                    className={`h-12 rounded-xl border-2 text-sm font-bold transition-all ${
                      draft.volume_unit === u
                        ? 'border-amber-500 bg-amber-100 text-amber-900 ring-2 ring-amber-100'
                        : 'border-slate-200 bg-white text-slate-700 hover:border-amber-300'
                    }`}
                  >
                    {VOLUME_UNIT_LABEL[u]}
                  </button>
                ))}
              </div>
            </div>
            {/* Editable quantity — auto-filled from the tyre class, overwritable */}
            <div>
              <div className="text-xs font-semibold uppercase tracking-widest text-slate-500 mb-1.5">Quantity</div>
              <div className="flex items-center gap-3">
                <input
                  type="number"
                  min="0"
                  step="0.1"
                  value={draft.volume_qty}
                  onChange={e => setDraft(d => ({ ...d, volume_qty: e.target.value }))}
                  placeholder="0"
                  className="flex-1 h-16 text-3xl font-mono font-bold text-center rounded-xl border-2 border-slate-300 focus:border-amber-500 focus:outline-none focus:ring-4 focus:ring-amber-100 bg-white"
                />
                <span className="w-24 text-center text-xl font-bold text-slate-500">{UNIT_SHORT[draft.volume_unit]}</span>
              </div>
            </div>
            {/* Live weight preview */}
            {!draft.product ? (
              <div className="text-xs text-slate-500">Pick a material above to see the weight.</div>
            ) : !draft.product.bulk_density ? (
              <div className="text-xs text-rose-600">Set bulk density for {draft.product.name} in Products to compute weight.</div>
            ) : volWeightKg > 0 ? (
              <div className="flex items-center justify-between rounded-xl border bg-white px-4 py-2.5">
                <span className="text-sm text-slate-600">
                  {draft.volume_qty} {UNIT_SHORT[draft.volume_unit]} × {Number(draft.product.bulk_density).toFixed(2)} kg/CFT
                </span>
                <span className="text-xl font-mono font-black text-amber-700">≈ {fmtKg(volWeightKg, 3)}</span>
              </div>
            ) : null}
          </div>
        )}
      </section>

      {/* Error banner */}
      {error && (
        <div className="rounded-xl border-2 border-rose-300 bg-rose-50 px-4 py-3 text-rose-800 font-medium flex items-center gap-2">
          <AlertTriangle className="h-5 w-5 shrink-0" /> {error}
        </div>
      )}

      {/* CTA */}
      <button
        onClick={handleStart}
        disabled={!canProceed || saving}
        className={`w-full h-24 rounded-2xl text-2xl font-bold flex items-center justify-center gap-3 shadow-lg transition-all ${
          canProceed && !saving
            ? 'bg-blue-600 hover:bg-blue-700 text-white'
            : 'bg-slate-200 text-slate-400 cursor-not-allowed'
        }`}
      >
        {saving ? (
          <><Loader2 className="h-7 w-7 animate-spin" /> {t('kiosk.creating')}</>
        ) : draft.tyre_count != null ? (
          <><Truck className="h-7 w-7" /> {t('kiosk.createTripNoWeigh')} <ArrowRight className="h-7 w-7" /></>
        ) : (
          <><Truck className="h-7 w-7" /> {t('kiosk.startWeighing')} <ArrowRight className="h-7 w-7" /></>
        )}
      </button>

      {/* Validation hint — explains why the button is disabled */}
      {!canProceed && !saving && missingItems.length > 0 && (
        <div className="text-center text-sm text-slate-600 -mt-3">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1">
            ☝️ Still missing: <strong>{missingItems.join(', ')}</strong>
          </span>
        </div>
      )}
    </div>
  );
}

// Direction tile (OUT / IN)
function DirectionTile({
  active, label, sub, icon: Icon, color, onClick,
}: {
  active: boolean;
  label: string;
  sub: string;
  icon: React.ElementType;
  color: 'blue' | 'amber';
  onClick: () => void;
}) {
  const palette =
    color === 'blue'
      ? active
        ? 'border-blue-500 bg-blue-50 text-blue-900 ring-4 ring-blue-100'
        : 'border-slate-200 bg-white text-slate-700 hover:bg-slate-50'
      : active
        ? 'border-amber-500 bg-amber-50 text-amber-900 ring-4 ring-amber-100'
        : 'border-slate-200 bg-white text-slate-700 hover:bg-slate-50';
  return (
    <button
      onClick={onClick}
      className={`p-6 rounded-2xl border-2 transition-all flex items-center gap-4 ${palette}`}
    >
      <Icon className={`h-12 w-12 ${active ? '' : 'opacity-50'}`} />
      <div className="text-left">
        <div className="text-3xl font-bold tracking-tight">{label}</div>
        <div className="text-xs text-slate-500 mt-0.5">{sub}</div>
      </div>
    </button>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// SCREEN 2 — WEIGHING
// ──────────────────────────────────────────────────────────────────────────

interface WeighingScreenProps {
  token: Token;
  onParked: () => void;       // 1st weight captured → back to arrival, token now in Pending strip
  onDone: (t: Token) => void; // 2nd weight captured → Done screen with summary
  onCancel: () => void;       // explicit cancel — returns to arrival without changing token
}

function WeighingScreen({ token, onParked, onDone, onCancel }: WeighingScreenProps) {
  const { t } = useTranslation();
  const { reading, isLocalSource } = useWeight();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  // Manual entry fallback — critical when the bridge is offline. Operator
  // types weight in MT (the natural unit); we multiply by 1000 at the API.
  const [manualMode, setManualMode] = useState(false);
  const [manualMt, setManualMt] = useState('');

  // Volume tokens (skip-the-bridge) come in already COMPLETED — jump straight to Done.
  useEffect(() => {
    if (token.status === 'COMPLETED' || token.status === 'CANCELLED') {
      onDone(token);
    }
  }, [token, onDone]);

  // Which weighment are we on? OPEN/LOADING → first;  FIRST_WEIGHT/SECOND_WEIGHT → second.
  const isFirst = token.status === 'OPEN' || token.status === 'LOADING';
  const stageLabel = isFirst ? t('kiosk.firstWeight') : t('kiosk.secondWeight');

  // For sale (outbound): 1st = empty (tare), 2nd = loaded (gross)
  // For purchase (inbound): 1st = loaded (gross), 2nd = empty (tare)
  const isSale = token.token_type === 'sale';
  const tareNow = (isSale && isFirst) || (!isSale && !isFirst);
  const tareOrGrossLabel = tareNow ? t('kiosk.emptyTruck') : t('kiosk.loadedTruck');

  // Effective weight: live scale OR manual display-unit value → kg
  const manualKg = displayToKg(manualMt);
  const weightKg = manualMode ? manualKg : reading.weight_kg;
  const formattedMT = fmtKg(weightKg, 4, false);
  const canCapture = manualMode
    ? weightKg > 0
    : reading.scale_connected && reading.is_stable && weightKg > 0;

  async function handleCapture() {
    if (!canCapture) return;
    setError('');
    setSaving(true);
    try {
      const endpoint = isFirst
        ? `/api/v1/tokens/${token.id}/first-weight`
        : `/api/v1/tokens/${token.id}/second-weight`;
      const { data } = await api.post<Token>(endpoint, {
        weight_kg: weightKg, is_manual: manualMode,
      });
      const dispVal = fmtKg(weightKg, 2, false);
      const unitWord = weightUnit().code === 'QUINTAL' ? 'quintal' : 'tonne';
      // Voice confirm — short + memorable
      if (isFirst) {
        speak(`${dispVal} ${unitWord} captured. Truck can load. Bring back for second weight.`);
        onParked();
      } else {
        const netDisp = data.net_weight ? fmtKg(data.net_weight, 2, false) : dispVal;
        speak(`Done. Net weight ${netDisp} ${unitWord}. Print bill.`);
        onDone(data);
      }
    } catch (e: unknown) {
      const err = e as {
        response?: { status?: number; data?: { detail?: string | Array<{ msg: string; loc?: string[] }> } };
        message?: string;
      };
      const detail = err.response?.data?.detail;
      let msg: string;
      if (typeof detail === 'string') msg = detail;
      else if (Array.isArray(detail)) msg = detail.map(d => d.msg).join(' · ');
      else msg = err.message ?? 'Could not capture. Try again.';
      const code = err.response?.status;
      setError(code ? `[${code}] ${msg}` : msg);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="max-w-5xl mx-auto p-6 space-y-6">
      {/* Back / cancel ribbon */}
      <div className="flex items-center justify-between">
        <button
          onClick={onCancel}
          className="flex items-center gap-2 text-sm text-slate-600 hover:text-slate-900 px-3 py-1.5 rounded hover:bg-slate-100"
        >
          <ChevronLeft className="h-4 w-4" /> {t('common.cancel')}
        </button>
        <div className="text-xs uppercase tracking-widest font-semibold text-slate-500">
          Token #{token.token_no ?? '—'}  ·  {token.vehicle_no}
        </div>
      </div>

      {/* Context card */}
      <div className="rounded-2xl border-2 border-slate-200 bg-white p-5">
        <div className="flex items-center gap-4">
          <Avatar name={token.party?.name ?? '—'} size="xl" />
          <div className="flex-1 min-w-0">
            <div className="text-2xl font-bold text-slate-900 truncate">{token.party?.name ?? 'Walk-in'}</div>
            <div className="text-lg text-slate-600 truncate mt-0.5">{token.product?.name ?? '—'}</div>
            <div className="text-sm text-slate-400 mt-0.5">
              {isSale ? t('kiosk.outDesc') : t('kiosk.inDesc')}
            </div>
          </div>
        </div>
      </div>

      {/* Stage marker */}
      <div className="text-center">
        <div className="text-xs uppercase tracking-widest text-slate-500 font-semibold">{stageLabel}</div>
        <div className="text-base text-slate-700 mt-1 font-medium">{tareOrGrossLabel}</div>
      </div>

      {/* THE READOUT — the focal point. Manual mode shows an input; live mode shows scale. */}
      <div className={`rounded-3xl border-4 p-8 text-center shadow-md ${
        manualMode
          ? canCapture ? 'border-blue-500 bg-blue-50' : 'border-slate-300 bg-slate-50'
          : reading.scale_connected
            ? canCapture ? 'border-emerald-500 bg-emerald-50' : 'border-amber-400 bg-amber-50'
            : 'border-rose-300 bg-rose-50'
      }`}>
        {manualMode ? (
          <>
            <div className="text-xs uppercase tracking-widest text-blue-700 font-bold mb-2">
              {t('kiosk.typeWeightByHand')}
            </div>
            <input
              type="number"
              autoFocus
              min="0"
              step="0.001"
              value={manualMt}
              onChange={e => setManualMt(e.target.value)}
              placeholder="0.000"
              className="w-full font-mono font-black tabular-nums leading-none text-blue-700 bg-transparent border-none focus:outline-none text-center"
              style={{ fontSize: 'clamp(60px, 14vw, 140px)' }}
            />
            <div className="text-3xl font-bold text-slate-500 mt-2">{weightUnitLabel()}</div>
            <div className="mt-4 text-base text-slate-600">
              {t('kiosk.enterMtHint')}
            </div>
          </>
        ) : !reading.scale_connected ? (
          <div className="py-4">
            <div className="text-3xl font-bold text-rose-600 mb-2">{t('kiosk.scaleOffline')}</div>
            <div className="text-sm text-slate-600 mb-4">{t('kiosk.scaleOfflineDesc')}</div>
            <button
              onClick={() => setManualMode(true)}
              className="inline-flex items-center gap-2 h-12 px-5 rounded-xl bg-blue-600 hover:bg-blue-700 text-white font-bold shadow"
            >
              <Pencil className="h-5 w-5" /> {t('kiosk.typeWeightByHandBtn')}
            </button>
          </div>
        ) : (
          <>
            <div className={`font-mono font-black tabular-nums leading-none ${
              canCapture ? 'text-emerald-600' : 'text-amber-600'
            }`}
              style={{ fontSize: 'clamp(80px, 18vw, 200px)' }}
            >
              {formattedMT}
            </div>
            <div className="text-3xl font-bold text-slate-500 mt-2">{weightUnitLabel()}</div>
            <div className="mt-4 text-base font-semibold">
              {canCapture ? (
                <span className="text-emerald-700">{t('kiosk.stable')}</span>
              ) : (
                <span className="text-amber-700 animate-pulse">{t('kiosk.waitStable')}</span>
              )}
            </div>
            {isLocalSource && (
              <div className="mt-4">
                <LocalScaleBadge size="lg" label={t('kiosk.localBridge')} />
              </div>
            )}
          </>
        )}
      </div>

      {/* Mode toggle — operator can always switch between live scale and manual */}
      <div className="text-center">
        <button
          onClick={() => { setManualMode(m => !m); setManualMt(''); }}
          className="inline-flex items-center gap-2 text-sm text-slate-600 hover:text-slate-900 underline underline-offset-4 px-3 py-1.5"
        >
          {manualMode
            ? <><Scale className="h-4 w-4" /> {t('kiosk.useLiveScale')}</>
            : <><Pencil className="h-4 w-4" /> {t('kiosk.typeInstead')}</>
          }
        </button>
      </div>

      {error && (
        <div className="rounded-xl border-2 border-rose-300 bg-rose-50 px-4 py-3 text-rose-800 font-medium flex items-center gap-2">
          <AlertTriangle className="h-5 w-5 shrink-0" /> {error}
        </div>
      )}

      {/* THE CAPTURE BUTTON — only one */}
      <button
        onClick={handleCapture}
        disabled={!canCapture || saving}
        className={`w-full h-28 rounded-3xl text-3xl font-black flex items-center justify-center gap-3 shadow-lg transition-all ${
          canCapture && !saving
            ? 'bg-emerald-600 hover:bg-emerald-700 text-white'
            : 'bg-slate-200 text-slate-400 cursor-not-allowed'
        }`}
      >
        {saving ? (
          <><Loader2 className="h-9 w-9 animate-spin" /> {t('kiosk.saving')}</>
        ) : (
          <><CheckCircle2 className="h-9 w-9" /> {t('kiosk.captureThisWeight')}</>
        )}
      </button>

      {/* Helper note: after 1st weight, the truck goes off to load. The token
          now sits in the Pending strip on the home screen for when it comes back. */}
      {isFirst && (
        <div className="text-center text-xs text-slate-500">
          {t('kiosk.after1stWeightNote')}
        </div>
      )}
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// SCREEN 3 — DONE
// ──────────────────────────────────────────────────────────────────────────

function DoneScreen({ token, onNew }: { token: Token; onNew: () => void }) {
  const { t } = useTranslation();
  const grossMt = fmtKg(token.gross_weight, 3, false);
  const tareMt = fmtKg(token.tare_weight, 3, false);
  const netMt = fmtKg(token.net_weight, 3, false);
  const wu = weightUnitLabel();
  const printUrl = `/api/v1/tokens/${token.id}/print`;

  // Open the print PDF in a new tab — leverages browser print
  function doPrint() {
    window.open(printUrl, '_blank', 'noopener');
  }

  // WhatsApp deep-link with party phone, if present
  function doWhatsApp() {
    const partyName = token.party?.name ?? 'Customer';
    const billUrl = `${window.location.origin}${printUrl}`;
    const msg = encodeURIComponent(
      `${partyName},\n\n` +
      `Trip slip #${token.token_no} — ${token.vehicle_no}\n` +
      `${token.product?.name ?? ''}  ·  ${netMt} ${wu}\n\n` +
      `Bill: ${billUrl}`
    );
    window.open(`https://wa.me/?text=${msg}`, '_blank', 'noopener');
  }

  return (
    <div className="max-w-3xl mx-auto p-6 space-y-6">
      {/* Big success */}
      <div className="text-center py-6">
        <div className="inline-flex h-24 w-24 items-center justify-center rounded-full bg-emerald-100 mb-4">
          <CheckCircle2 className="h-14 w-14 text-emerald-600" />
        </div>
        <div className="text-3xl font-black text-slate-900">{t('kiosk.done')}</div>
        <div className="text-sm text-slate-500 mt-1">Token #{token.token_no ?? '—'}  ·  {token.vehicle_no}</div>
      </div>

      {/* Summary card */}
      <div className="rounded-2xl border-2 border-slate-200 bg-white p-5">
        <div className="flex items-center gap-4 pb-4 border-b border-slate-100">
          <Avatar name={token.party?.name ?? '—'} size="xl" />
          <div className="flex-1 min-w-0">
            <div className="text-xl font-bold text-slate-900 truncate">{token.party?.name ?? 'Walk-in'}</div>
            <div className="text-base text-slate-600 truncate mt-0.5">{token.product?.name ?? '—'}</div>
          </div>
        </div>
        <div className="grid grid-cols-3 gap-3 mt-4 text-center">
          <div>
            <div className="text-xs uppercase tracking-widest text-slate-500">{t('kiosk.gross')}</div>
            <div className="text-xl font-mono font-bold text-slate-900 mt-1">{grossMt}</div>
            <div className="text-[10px] text-slate-400">{wu}</div>
          </div>
          <div>
            <div className="text-xs uppercase tracking-widest text-slate-500">{t('kiosk.tare')}</div>
            <div className="text-xl font-mono font-bold text-slate-900 mt-1">{tareMt}</div>
            <div className="text-[10px] text-slate-400">{wu}</div>
          </div>
          <div className="rounded-lg bg-blue-50 -m-1 p-1">
            <div className="text-xs uppercase tracking-widest text-blue-700 font-semibold">{t('kiosk.net')}</div>
            <div className="text-2xl font-mono font-black text-blue-900 mt-1">{netMt}</div>
            <div className="text-[10px] text-blue-600 font-semibold">{wu}</div>
          </div>
        </div>
      </div>

      {/* Actions: 3 big buttons */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <button
          onClick={doPrint}
          className="h-24 rounded-2xl bg-slate-900 hover:bg-slate-800 text-white text-lg font-bold flex flex-col items-center justify-center gap-1 shadow-md transition-colors"
        >
          <Printer className="h-7 w-7" />
          {t('kiosk.printBill')}
        </button>
        <button
          onClick={doWhatsApp}
          className="h-24 rounded-2xl bg-emerald-600 hover:bg-emerald-700 text-white text-lg font-bold flex flex-col items-center justify-center gap-1 shadow-md transition-colors"
        >
          <MessageCircle className="h-7 w-7" />
          WhatsApp
        </button>
        <button
          onClick={onNew}
          className="h-24 rounded-2xl bg-blue-600 hover:bg-blue-700 text-white text-lg font-bold flex flex-col items-center justify-center gap-1 shadow-md transition-colors"
        >
          <RefreshCw className="h-7 w-7" />
          {t('kiosk.newTruck')}
        </button>
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// SOS Modal
// ──────────────────────────────────────────────────────────────────────────

function SosModal({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  // Pull admin contact numbers from app-settings if present — fall back to a generic prompt
  const [admins, setAdmins] = useState<{ name: string; phone: string }[]>([]);

  useEffect(() => {
    api.get<{ name: string; phone: string }[]>('/api/v1/app-settings/manager-contacts')
      .then(r => setAdmins(r.data ?? []))
      .catch(() => setAdmins([]));   // endpoint may not exist yet
  }, []);

  return (
    <div className="fixed inset-0 bg-black/50 z-[60] flex items-center justify-center p-4" onClick={onClose}>
      <div
        className="bg-white rounded-3xl shadow-2xl max-w-md w-full p-6 space-y-4"
        onClick={e => e.stopPropagation()}
      >
        <div className="text-center">
          <div className="inline-flex h-16 w-16 items-center justify-center rounded-full bg-red-100 mb-3">
            <PhoneCall className="h-8 w-8 text-red-600" />
          </div>
          <div className="text-2xl font-black text-slate-900">{t('kiosk.callManager')}</div>
          <div className="text-sm text-slate-500 mt-1">{t('kiosk.tapCallToTap')}</div>
        </div>

        <div className="space-y-2">
          {admins.length === 0 ? (
            <div className="text-center text-sm text-slate-500 py-4">
              {t('kiosk.noManagerContacts')}
            </div>
          ) : (
            admins.map(a => (
              <a
                key={a.phone}
                href={`tel:${a.phone}`}
                className="flex items-center gap-3 p-4 rounded-xl border-2 border-emerald-200 bg-emerald-50 hover:bg-emerald-100 transition-colors"
              >
                <Avatar name={a.name} size="md" />
                <div className="flex-1 min-w-0">
                  <div className="font-bold text-slate-900 truncate">{a.name}</div>
                  <div className="text-sm text-slate-600 font-mono">{a.phone}</div>
                </div>
                <PhoneCall className="h-6 w-6 text-emerald-600" />
              </a>
            ))
          )}
        </div>

        <button
          onClick={onClose}
          className="w-full h-14 rounded-xl border-2 border-slate-200 bg-white hover:bg-slate-50 font-bold text-slate-700"
        >
          {t('common.cancel')}
        </button>
      </div>
    </div>
  );
}
