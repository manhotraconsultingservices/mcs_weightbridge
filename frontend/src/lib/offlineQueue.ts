/**
 * Offline token queue (Horizon 2 — offline resilience).
 *
 * When the network is down (or a token POST fails with a network error), the
 * token payload is stored in localStorage and replayed automatically when the
 * browser comes back online. Server-side numbering stays gap-free because the
 * token_no / gate_pass_no are assigned by the server at sync time — the queue
 * only holds the *request*, never a pre-allocated number.
 *
 * Scope: token creation only (the one action that must survive a dropped link
 * at the weighbridge). Validation (4xx) errors drop the item — a malformed
 * token can never succeed on retry.
 */
import api from '@/services/api';

const KEY = 'wb.offlineQueue.v1';

export interface QueuedToken {
  id: string;            // client-side temp id
  endpoint: string;      // '/tokens' | '/tokens/volume'
  payload: unknown;
  created_at: string;
  vehicle_no?: string;
}

type Listener = (count: number) => void;
const listeners = new Set<Listener>();

function read(): QueuedToken[] {
  try { return JSON.parse(localStorage.getItem(KEY) || '[]'); } catch { return []; }
}
function write(items: QueuedToken[]) {
  localStorage.setItem(KEY, JSON.stringify(items));
  listeners.forEach(l => l(items.length));
}

export function pendingCount(): number { return read().length; }

export function subscribe(l: Listener): () => void {
  listeners.add(l);
  l(read().length);
  return () => { listeners.delete(l); };
}

export function enqueueToken(endpoint: string, payload: unknown, vehicle_no?: string): QueuedToken {
  const item: QueuedToken = {
    id: `q_${Date.now()}_${Math.floor(Math.random() * 1e6)}`,
    endpoint, payload, vehicle_no,
    created_at: new Date().toISOString(),
  };
  write([...read(), item]);
  return item;
}

let flushing = false;

/** Try to POST every queued token. Returns {synced, remaining}. */
export async function flushQueue(): Promise<{ synced: number; remaining: number }> {
  if (flushing || !navigator.onLine) return { synced: 0, remaining: read().length };
  flushing = true;
  let synced = 0;
  try {
    let items = read();
    for (const item of items) {
      try {
        await api.post(item.endpoint, item.payload);
        synced++;
        items = read().filter(i => i.id !== item.id);
        write(items);
      } catch (e: unknown) {
        const status = (e as { response?: { status?: number } })?.response?.status;
        if (status && status >= 400 && status < 500) {
          // Permanent failure (validation/auth) — drop it so it can't wedge the queue.
          items = read().filter(i => i.id !== item.id);
          write(items);
          continue;
        }
        // Network / 5xx — stop; retry on next online event.
        break;
      }
    }
  } finally {
    flushing = false;
  }
  return { synced, remaining: read().length };
}

/** Wire auto-flush on reconnect + a periodic safety retry. Call once at startup. */
export function initOfflineQueue() {
  window.addEventListener('online', () => { void flushQueue(); });
  // Safety: retry every 60s while online and non-empty (covers flaky links).
  setInterval(() => { if (navigator.onLine && read().length) void flushQueue(); }, 60_000);
  // Attempt once at boot in case we reloaded with items pending.
  if (navigator.onLine) void flushQueue();
}
