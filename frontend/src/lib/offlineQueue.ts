/**
 * Offline token queue (Horizon 2 — offline resilience).
 *
 * When the network is down (or a token POST fails with a network error), the
 * token payload is stored in localStorage and replayed automatically when the
 * browser comes back online.
 *
 * ─────────────────────────────────────────────────────────────────────────────
 * SAFETY INVARIANT — do not weaken:
 *   A queued item is NEVER deleted because the server rejected it.
 *   Every item represents a truck that physically crossed the weighbridge.
 *   A rejection PARKS the item for a human to resolve; it never discards it.
 *   The only automatic removal is a confirmed 2xx. The only manual removal is
 *   discardItem(), which an operator/admin must invoke deliberately.
 * ─────────────────────────────────────────────────────────────────────────────
 *
 * History (why the invariant exists): the original version enqueued the
 * endpoint as '/tokens' while the axios baseURL is '/', so replay POSTed to
 * '/tokens' — a route that does not exist (the router is mounted at
 * '/api/v1/tokens'). The resulting 404 hit a "4xx is permanent, drop it" rule
 * and EVERY offline token was silently destroyed on reconnect, after the
 * operator had been told it was saved. A second path did the same: this queue
 * lives in localStorage but the JWT lives in sessionStorage, so after a browser
 * restart the replay 401'd and was likewise dropped.
 *
 * Both causes are fixed here, and legacy items are migrated forward (endpoint
 * rewritten on read) rather than discarded — items stranded on an operator's
 * machine by the old bug are rescued on the next load.
 */
import api from '@/services/api';

const KEY = 'wb.offlineQueue.v1';

/** Replay must fail fast on a black-holed link rather than hang for ~2 min. */
const REPLAY_TIMEOUT_MS = 10_000;

export type QueueStatus =
  | 'pending'       // waiting for a chance to sync
  | 'needs_auth'    // server said 401/403 — paused until a valid session exists
  | 'needs_review'; // server rejected it (409/422/…) — needs a human decision

export interface QueuedToken {
  id: string;            // client-side temp id
  endpoint: string;      // '/api/v1/tokens' | '/api/v1/tokens/volume'
  payload: unknown;
  created_at: string;
  vehicle_no?: string;
  status?: QueueStatus;  // optional: legacy items load as 'pending'
  attempts?: number;
  last_error?: string;
  last_attempt_at?: string;
}

export interface QueueStats {
  total: number;
  pending: number;
  needsReview: number;
  needsAuth: number;
}

type Listener = (stats: QueueStats) => void;
const listeners = new Set<Listener>();

/**
 * Migrate a legacy endpoint forward. The original queue stored '/tokens' and
 * '/tokens/volume' (no version prefix) which 404 on replay. Anything already
 * carrying '/api/' is left untouched.
 */
function normalizeEndpoint(endpoint: unknown): string {
  const ep = typeof endpoint === 'string' && endpoint.trim() ? endpoint.trim() : '/tokens';
  if (ep.startsWith('/api/')) return ep;
  return `/api/v1${ep.startsWith('/') ? ep : `/${ep}`}`;
}

function read(): QueuedToken[] {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || '[]');
    if (!Array.isArray(raw)) return [];
    return raw.map((i: QueuedToken) => ({
      ...i,
      endpoint: normalizeEndpoint(i?.endpoint),
      status: i?.status ?? 'pending',
      attempts: i?.attempts ?? 0,
    }));
  } catch {
    return [];
  }
}

function write(items: QueuedToken[]) {
  localStorage.setItem(KEY, JSON.stringify(items));
  const stats = statsOf(items);
  listeners.forEach(l => l(stats));
}

function statsOf(items: QueuedToken[]): QueueStats {
  return {
    total: items.length,
    pending: items.filter(i => (i.status ?? 'pending') === 'pending').length,
    needsReview: items.filter(i => i.status === 'needs_review').length,
    needsAuth: items.filter(i => i.status === 'needs_auth').length,
  };
}

export function pendingCount(): number { return read().length; }
export function queueStats(): QueueStats { return statsOf(read()); }
export function listQueue(): QueuedToken[] { return read(); }

export function subscribe(l: Listener): () => void {
  listeners.add(l);
  l(statsOf(read()));
  return () => { listeners.delete(l); };
}

export function enqueueToken(endpoint: string, payload: unknown, vehicle_no?: string): QueuedToken {
  const item: QueuedToken = {
    id: `q_${Date.now()}_${Math.floor(Math.random() * 1e6)}`,
    endpoint: normalizeEndpoint(endpoint),
    payload,
    vehicle_no,
    created_at: new Date().toISOString(),
    status: 'pending',
    attempts: 0,
  };
  write([...read(), item]);
  return item;
}

/**
 * Deliberate, human-initiated removal of an item the server will never accept
 * (e.g. a duplicate the operator has confirmed was already recorded). This is
 * the ONLY way an unsynced item leaves the queue — never call it automatically.
 */
export function discardItem(id: string): void {
  write(read().filter(i => i.id !== id));
}

function patch(items: QueuedToken[], id: string, fields: Partial<QueuedToken>): QueuedToken[] {
  return items.map(i => (i.id === id ? { ...i, ...fields } : i));
}

let flushing = false;

/**
 * Replay queued tokens in order. Ordering matters: the backend rejects a second
 * OPEN token for the same vehicle (409), so an out-of-order replay would fail
 * spuriously. Any unresolved outcome therefore HALTS the drain rather than
 * skipping ahead.
 */
export async function flushQueue(): Promise<QueueStats> {
  if (flushing || !navigator.onLine) return queueStats();

  // Without a session every replay 401s. Flushing anyway would park the whole
  // queue as needs_auth (and, before this rewrite, delete it) — so wait until a
  // user is actually logged in.
  if (!sessionStorage.getItem('token')) return queueStats();

  flushing = true;
  try {
    let items = read();

    // A session exists now, so previously auth-paused items are retryable.
    if (items.some(i => i.status === 'needs_auth')) {
      items = items.map(i => (i.status === 'needs_auth' ? { ...i, status: 'pending' as const } : i));
      write(items);
    }

    for (const item of items) {
      // A parked item blocks everything behind it until a human resolves it.
      if (item.status === 'needs_review') break;

      try {
        await api.post(item.endpoint, item.payload, { timeout: REPLAY_TIMEOUT_MS });
        items = read().filter(i => i.id !== item.id);   // confirmed 2xx: the only auto-removal
        write(items);
      } catch (e: unknown) {
        const err = e as { response?: { status?: number; data?: { detail?: unknown } }; message?: string };
        const status = err.response?.status;
        const detail = err.response?.data?.detail;
        const message =
          typeof detail === 'string' ? detail
          : Array.isArray(detail) ? detail.map(d => (d as { msg?: string })?.msg ?? '').join(' · ')
          : err.message ?? 'Sync failed';

        const base: Partial<QueuedToken> = {
          attempts: (item.attempts ?? 0) + 1,
          last_error: status ? `HTTP ${status}: ${message}` : message,
          last_attempt_at: new Date().toISOString(),
        };

        if (status === 401 || status === 403) {
          // Session expired / not permitted. Pause — do NOT discard.
          write(patch(read(), item.id, { ...base, status: 'needs_auth' }));
        } else if (status && status >= 400 && status < 500 && status !== 408 && status !== 429) {
          // Server refused it (409 duplicate, 422 validation, 404 …). This is a
          // real weighment, so park it for a human instead of deleting it.
          write(patch(read(), item.id, { ...base, status: 'needs_review' }));
        } else {
          // Network error, timeout, 408/429, or 5xx — transient. Retry later.
          write(patch(read(), item.id, base));
        }
        break;   // halt the drain; preserve ordering
      }
    }
  } finally {
    flushing = false;
  }
  return queueStats();
}

/** Wire auto-flush on reconnect + a periodic safety retry. Call once at startup. */
export function initOfflineQueue() {
  window.addEventListener('online', () => { void flushQueue(); });
  // Safety: retry every 60s while online and non-empty (covers flaky links and
  // picks up items parked as needs_auth once the user logs back in).
  setInterval(() => { if (navigator.onLine && read().length) void flushQueue(); }, 60_000);
  // Attempt once at boot in case we reloaded with items pending.
  if (navigator.onLine) void flushQueue();
}
