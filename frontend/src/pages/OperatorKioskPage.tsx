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
import { useNavigate } from 'react-router-dom';
import {
  Truck, ArrowRight, ArrowDownToLine, ArrowUpFromLine, Scale,
  CheckCircle2, Printer, MessageCircle, RefreshCw, X, LogOut,
  PhoneCall, AlertTriangle, Loader2, Search, Sparkles, ChevronLeft,
} from 'lucide-react';
import api from '@/services/api';
import { useWeight } from '@/hooks/useWeight';
import type { User, Party, Product, Token } from '@/types';

// ── Constants ──────────────────────────────────────────────────────────────

// Default volume per tyre-class in CFT (cubic feet — the standard unit in
// the Indian stone-crusher trade). Operator can still override per token.
const TYRE_VOLUME_CFT: Record<number, number> = {
  4: 106, 6: 247, 8: 353, 10: 459, 12: 600,
};
const TYRE_OPTIONS = [4, 6, 8, 10, 12];

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
}

// ── Main page ──────────────────────────────────────────────────────────────

interface OperatorKioskPageProps {
  user: User;
  onLogout: () => void;
}

export default function OperatorKioskPage({ user, onLogout }: OperatorKioskPageProps) {
  const nav = useNavigate();
  const [stage, setStage] = useState<Stage>('arrival');
  const [draft, setDraft] = useState<ArrivalDraft>({
    vehicle_no: '', token_type: 'sale', party: null, product: null, tyre_count: null,
  });
  const [activeToken, setActiveToken] = useState<Token | null>(null);
  const [sosOpen, setSosOpen] = useState(false);

  // Reset to start a brand-new token
  const reset = useCallback(() => {
    setDraft({ vehicle_no: '', token_type: 'sale', party: null, product: null, tyre_count: null });
    setActiveToken(null);
    setStage('arrival');
  }, []);

  return (
    <div className="fixed inset-0 bg-slate-50 overflow-hidden flex flex-col">
      {/* ── Top bar: logo + minimal context ── */}
      <header className="bg-white border-b border-slate-200 px-6 py-3 flex items-center gap-4 shrink-0">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-600 text-white shadow-sm">
          <Scale className="h-5 w-5" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-base font-bold text-slate-900">Truck Counter</div>
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
          <span className="hidden sm:inline">Logout</span>
        </button>
      </header>

      {/* ── Body ── */}
      <main className="flex-1 overflow-auto">
        {stage === 'arrival' && (
          <ArrivalScreen
            draft={draft}
            setDraft={setDraft}
            onProceed={tok => { setActiveToken(tok); setStage('weighing'); }}
          />
        )}
        {stage === 'weighing' && activeToken && (
          <WeighingScreen
            token={activeToken}
            onUpdated={t => setActiveToken(t)}
            onDone={t => { setActiveToken(t); setStage('done'); }}
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
        Need Help
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
  onProceed: (token: Token) => void;
}

function ArrivalScreen({ draft, setDraft, onProceed }: ArrivalScreenProps) {
  const [parties, setParties] = useState<Party[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [partySearch, setPartySearch] = useState('');
  const [lastSeen, setLastSeen] = useState<LastSeen | null>(null);
  const [lookupBusy, setLookupBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const lookupTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Load master data once
  useEffect(() => {
    Promise.all([
      api.get<{ items: Party[] }>('/api/v1/parties?page_size=500'),
      api.get<Product[] | { items: Product[] }>('/api/v1/products?page_size=200'),
    ]).then(([p, pr]) => {
      setParties(p.data.items ?? []);
      const prodData = pr.data;
      setProducts(Array.isArray(prodData) ? prodData : (prodData as { items: Product[] }).items ?? []);
    }).catch(() => { /* keep empty */ });
  }, []);

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

  // Filter party list by search
  const partyMatches = useMemo(() => {
    const q = partySearch.trim().toLowerCase();
    if (!q) return parties.slice(0, 12);  // initial: top 12
    return parties.filter(p => p.name.toLowerCase().includes(q)).slice(0, 24);
  }, [parties, partySearch]);

  // Apply last-seen suggestion in one click
  function applyLastSeen() {
    if (!lastSeen) return;
    setDraft(d => ({
      ...d,
      token_type: (lastSeen.token_type === 'purchase' ? 'purchase' : 'sale') as 'sale' | 'purchase',
      party: lastSeen.party
        ? ({ id: lastSeen.party.id, name: lastSeen.party.name } as unknown as Party)
        : null,
      product: lastSeen.product
        ? ({
            id: lastSeen.product.id,
            name: lastSeen.product.name,
            unit: lastSeen.product.unit,
            bulk_density: lastSeen.product.bulk_density,
          } as unknown as Product)
        : null,
    }));
  }

  const canProceed =
    draft.vehicle_no.trim().length >= 4 && draft.party && draft.product;

  // Create the token (either /tokens or /tokens/volume)
  async function handleStart() {
    if (!canProceed || !draft.party || !draft.product) return;
    setError('');
    setSaving(true);
    try {
      const today = new Date().toISOString().split('T')[0];
      // Volume path: tyre_count selected → one-shot create+complete+invoice
      if (draft.tyre_count != null) {
        const cft = TYRE_VOLUME_CFT[draft.tyre_count] ?? 0;
        const { data } = await api.post<Token>('/api/v1/tokens/volume', {
          token_date: today,
          vehicle_no: draft.vehicle_no.trim().toUpperCase(),
          token_type: draft.token_type,
          direction: draft.token_type === 'sale' ? 'outbound' : 'inbound',
          party_id: draft.party.id,
          product_id: draft.product.id,
          volume_cft: cft,
          tyre_count: draft.tyre_count,
        });
        speak(
          `Volume token created. ${draft.product.name}, ${cft} cubic feet, for ${draft.party.name}. Bill will print.`,
        );
        onProceed(data);
        return;
      }
      // Weighbridge path
      const { data } = await api.post<Token>('/api/v1/tokens', {
        token_date: today,
        vehicle_no: draft.vehicle_no.trim().toUpperCase(),
        token_type: draft.token_type,
        direction: draft.token_type === 'sale' ? 'outbound' : 'inbound',
        party_id: draft.party.id,
        product_id: draft.product.id,
        tyre_count: draft.tyre_count,    // null when "Weigh" is chosen — that's fine
      });
      speak(`Truck in. ${draft.product.name} for ${draft.party.name}. Drive onto the bridge.`);
      onProceed(data);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Could not start. Try again.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="max-w-5xl mx-auto p-6 space-y-6">
      {/* Vehicle number — biggest input on the screen */}
      <section>
        <label className="block text-sm font-semibold uppercase tracking-widest text-slate-500 mb-2">
          1.  Vehicle Number
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

      {/* Smart suggest — only when we found a last visit */}
      {lookupBusy && (
        <div className="text-center text-sm text-slate-500 flex items-center justify-center gap-2">
          <Loader2 className="h-4 w-4 animate-spin" /> Checking history…
        </div>
      )}
      {lastSeen && lastSeen.party && lastSeen.product && (
        <button
          onClick={applyLastSeen}
          className="w-full rounded-2xl border-2 border-emerald-300 bg-emerald-50 hover:bg-emerald-100 p-5 flex items-center gap-4 text-left transition-colors"
        >
          <Sparkles className="h-8 w-8 text-emerald-600 shrink-0" />
          <div className="flex-1 min-w-0">
            <div className="text-xs uppercase tracking-widest text-emerald-700 font-semibold">Same as last time?</div>
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
          2.  Truck Going
        </label>
        <div className="grid grid-cols-2 gap-3">
          <DirectionTile
            active={draft.token_type === 'sale'}
            label="OUT"
            sub="Loaded → leaving"
            icon={ArrowUpFromLine}
            color="blue"
            onClick={() => setDraft(d => ({ ...d, token_type: 'sale' }))}
          />
          <DirectionTile
            active={draft.token_type === 'purchase'}
            label="IN"
            sub="Empty → buying"
            icon={ArrowDownToLine}
            color="amber"
            onClick={() => setDraft(d => ({ ...d, token_type: 'purchase' }))}
          />
        </div>
      </section>

      {/* Product picker — grid of big tiles */}
      <section>
        <label className="block text-sm font-semibold uppercase tracking-widest text-slate-500 mb-2">
          3.  Material
        </label>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
          {products.length === 0 && (
            <div className="col-span-full text-center text-sm text-slate-400 py-6">
              No products configured. Ask the manager to add some.
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

      {/* Party picker — search + recent tiles */}
      <section>
        <label className="block text-sm font-semibold uppercase tracking-widest text-slate-500 mb-2">
          4.  {draft.token_type === 'sale' ? 'Customer' : 'Supplier'}
        </label>
        <div className="relative mb-3">
          <Search className="absolute left-4 top-1/2 -translate-y-1/2 h-5 w-5 text-slate-400" />
          <input
            type="text"
            value={partySearch}
            onChange={e => setPartySearch(e.target.value)}
            placeholder={`Search ${draft.token_type === 'sale' ? 'customer' : 'supplier'}…`}
            className="w-full h-14 pl-12 pr-4 text-base rounded-xl border-2 border-slate-300 focus:border-blue-500 focus:outline-none focus:ring-4 focus:ring-blue-100 bg-white"
          />
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">
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
              No match. Ask the manager to add this customer.
            </div>
          )}
        </div>
      </section>

      {/* Optional: tyre count → volume mode (skip the bridge) */}
      <section>
        <label className="block text-sm font-semibold uppercase tracking-widest text-slate-500 mb-2">
          5.  Skip Weighbridge? <span className="text-slate-400 normal-case font-normal">(optional)</span>
        </label>
        <div className="grid grid-cols-6 gap-2">
          <button
            onClick={() => setDraft(d => ({ ...d, tyre_count: null }))}
            className={`h-16 rounded-xl border-2 font-bold transition-all ${
              draft.tyre_count == null
                ? 'border-blue-500 bg-blue-50 text-blue-900 ring-2 ring-blue-100'
                : 'border-slate-200 bg-white text-slate-700 hover:border-slate-300'
            }`}
          >
            <div className="text-sm uppercase">Weigh</div>
          </button>
          {TYRE_OPTIONS.map(n => {
            const selected = draft.tyre_count === n;
            return (
              <button
                key={n}
                onClick={() => setDraft(d => ({ ...d, tyre_count: n }))}
                className={`h-16 rounded-xl border-2 font-bold transition-all ${
                  selected
                    ? 'border-amber-500 bg-amber-50 text-amber-900 ring-2 ring-amber-100'
                    : 'border-slate-200 bg-white text-slate-700 hover:border-slate-300'
                }`}
              >
                <div className="text-xl">{n} 🛞</div>
                <div className="text-[10px] text-slate-500 mt-0.5">{TYRE_VOLUME_CFT[n]} CFT</div>
              </button>
            );
          })}
        </div>
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
          <><Loader2 className="h-7 w-7 animate-spin" /> Creating…</>
        ) : draft.tyre_count != null ? (
          <><Truck className="h-7 w-7" /> CREATE TRIP (NO WEIGHING) <ArrowRight className="h-7 w-7" /></>
        ) : (
          <><Truck className="h-7 w-7" /> START WEIGHING <ArrowRight className="h-7 w-7" /></>
        )}
      </button>
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
  onUpdated: (t: Token) => void;
  onDone: (t: Token) => void;
  onCancel: () => void;
}

function WeighingScreen({ token, onUpdated, onDone, onCancel }: WeighingScreenProps) {
  const { reading } = useWeight();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  // Volume tokens (skip-the-bridge) come in already COMPLETED — jump straight to Done.
  useEffect(() => {
    if (token.status === 'COMPLETED' || token.status === 'CANCELLED') {
      onDone(token);
    }
  }, [token, onDone]);

  // Which weighment are we on? OPEN/LOADING → first;  FIRST_WEIGHT/SECOND_WEIGHT → second.
  const isFirst = token.status === 'OPEN' || token.status === 'LOADING';
  const stageLabel = isFirst ? 'FIRST WEIGHT' : 'SECOND WEIGHT';

  // For sale (outbound): 1st = empty (tare), 2nd = loaded (gross)
  // For purchase (inbound): 1st = loaded (gross), 2nd = empty (tare)
  const isSale = token.token_type === 'sale';
  const tareNow = (isSale && isFirst) || (!isSale && !isFirst);
  const tareOrGrossLabel = tareNow ? '(EMPTY truck)' : '(LOADED truck)';

  const weightKg = reading.weight_kg;
  const formattedMT = (weightKg / 1000).toLocaleString('en-IN', { minimumFractionDigits: 3, maximumFractionDigits: 3 });
  const canCapture = reading.scale_connected && reading.is_stable && weightKg > 0;

  async function handleCapture() {
    if (!canCapture) return;
    setError('');
    setSaving(true);
    try {
      const endpoint = isFirst
        ? `/api/v1/tokens/${token.id}/first-weight`
        : `/api/v1/tokens/${token.id}/second-weight`;
      const { data } = await api.post<Token>(endpoint, { weight_kg: weightKg, is_manual: false });
      const mt = (weightKg / 1000).toFixed(2);
      // Voice confirm — short + memorable
      if (isFirst) {
        speak(`${mt} tonne captured. Truck can move.`);
        onUpdated(data);
      } else {
        const netMt = data.net_weight ? (data.net_weight / 1000).toFixed(2) : mt;
        speak(`Done. Net weight ${netMt} tonne. Print bill.`);
        onDone(data);
      }
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Could not capture. Try again.');
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
          <ChevronLeft className="h-4 w-4" /> Cancel
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
              {isSale ? 'OUT (loaded → leaving)' : 'IN (empty → buying)'}
            </div>
          </div>
        </div>
      </div>

      {/* Stage marker */}
      <div className="text-center">
        <div className="text-xs uppercase tracking-widest text-slate-500 font-semibold">{stageLabel}</div>
        <div className="text-base text-slate-700 mt-1 font-medium">{tareOrGrossLabel}</div>
      </div>

      {/* THE READOUT — the focal point */}
      <div className={`rounded-3xl border-4 p-8 text-center shadow-md ${
        reading.scale_connected
          ? canCapture ? 'border-emerald-500 bg-emerald-50' : 'border-amber-400 bg-amber-50'
          : 'border-slate-300 bg-slate-100'
      }`}>
        {!reading.scale_connected ? (
          <div className="py-8">
            <div className="text-3xl font-bold text-rose-600 mb-2">SCALE OFFLINE</div>
            <div className="text-sm text-slate-500">Check the bridge connection or call the manager.</div>
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
            <div className="text-3xl font-bold text-slate-500 mt-2">MT</div>
            <div className="mt-4 text-base font-semibold">
              {canCapture ? (
                <span className="text-emerald-700">✓ STABLE — READY TO CAPTURE</span>
              ) : (
                <span className="text-amber-700 animate-pulse">⏳ Wait for truck to stop moving…</span>
              )}
            </div>
          </>
        )}
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
          <><Loader2 className="h-9 w-9 animate-spin" /> Saving…</>
        ) : (
          <><CheckCircle2 className="h-9 w-9" /> CAPTURE THIS WEIGHT</>
        )}
      </button>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// SCREEN 3 — DONE
// ──────────────────────────────────────────────────────────────────────────

function DoneScreen({ token, onNew }: { token: Token; onNew: () => void }) {
  const grossMt = token.gross_weight ? (token.gross_weight / 1000).toFixed(3) : '—';
  const tareMt = token.tare_weight ? (token.tare_weight / 1000).toFixed(3) : '—';
  const netMt = token.net_weight ? (token.net_weight / 1000).toFixed(3) : '—';
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
      `${token.product?.name ?? ''}  ·  ${netMt} MT\n\n` +
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
        <div className="text-3xl font-black text-slate-900">DONE</div>
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
            <div className="text-xs uppercase tracking-widest text-slate-500">Gross</div>
            <div className="text-xl font-mono font-bold text-slate-900 mt-1">{grossMt}</div>
            <div className="text-[10px] text-slate-400">MT</div>
          </div>
          <div>
            <div className="text-xs uppercase tracking-widest text-slate-500">Tare</div>
            <div className="text-xl font-mono font-bold text-slate-900 mt-1">{tareMt}</div>
            <div className="text-[10px] text-slate-400">MT</div>
          </div>
          <div className="rounded-lg bg-blue-50 -m-1 p-1">
            <div className="text-xs uppercase tracking-widest text-blue-700 font-semibold">NET</div>
            <div className="text-2xl font-mono font-black text-blue-900 mt-1">{netMt}</div>
            <div className="text-[10px] text-blue-600 font-semibold">MT</div>
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
          Print Bill
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
          New Truck
        </button>
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// SOS Modal
// ──────────────────────────────────────────────────────────────────────────

function SosModal({ onClose }: { onClose: () => void }) {
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
          <div className="text-2xl font-black text-slate-900">Call Manager</div>
          <div className="text-sm text-slate-500 mt-1">Tap a name to call.</div>
        </div>

        <div className="space-y-2">
          {admins.length === 0 ? (
            <div className="text-center text-sm text-slate-500 py-4">
              No manager contacts configured. Ask the admin to set them in Settings.
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
          Cancel
        </button>
      </div>
    </div>
  );
}
