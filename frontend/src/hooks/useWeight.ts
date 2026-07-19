import { useEffect, useRef, useState, useCallback } from 'react';
import { getTenantSlug, getAuthToken } from './useAuth';
import { fmtKg } from '@/lib/weightUnit';
import {
  agentStatusToReading, IDLE,
  type AgentStatus, type WeightReading, type WeightSource,
} from '@/lib/agentStatus';

// Re-exported so existing imports from this hook keep working.
export { IDLE, agentStatusToReading };
export type { AgentStatus, WeightReading, WeightSource };

// This is a LIVE weight feed — the operator is watching the number change as a
// truck loads/unloads, so it must recover from a dropped socket in ~1–2 s, never
// the 30 s it used to take. Backoff is deliberately small and capped low.
const BASE_DELAY_MS = 1000;       // first reconnect attempt after a drop
const MAX_DELAY_MS = 4000;        // cap normal backoff at 4 s (was 30 s)
const ABSENT_DELAY_MS = 15000;    // server has no scale manager (1013): don't hammer
const MANAGER_ABSENT_CODE = 1013; // server sends 1013 when weight manager is None

// Half-dead-socket watchdog: the agent pushes a frame every ~500 ms while the
// scale is connected, so if we receive NOTHING for this long the socket is a
// zombie (Cloudflare/nginx dropped it without a close event) — force a reconnect
// instead of waiting for the OS TCP timeout (~30 s of frozen, stale weight).
const SILENCE_LIMIT_MS = 8000;
const WATCHDOG_INTERVAL_MS = 2500;

// ── Local fallback (internet down) ───────────────────────────────────────────
// The scale agent runs on the weighbridge PC and serves the live reading over
// plain HTTP. When the cloud feed goes quiet we read it directly, so a truck can
// still be weighed through an outage.
//
// 127.0.0.1 rather than "localhost" on purpose: the agent binds IPv4 only, and
// "localhost" can resolve to ::1 first, which would fail every time.
//
// The agent scans this port range at startup (Tally's default is 9002, so it
// steps aside when that is taken) — hence discovery rather than a fixed port.
const AGENT_PORTS = [9002, 9003, 9004, 9005, 9006];
const AGENT_PORT_KEY = 'wb.scaleAgentPort';
const AGENT_SERVICE = 'scale_agent_v2';
const LOCAL_TAKEOVER_MS = 3000;    // no cloud frame for this long → read locally
const LOCAL_POLL_MS = 500;         // matches the agent's push cadence
const LOCAL_TIMEOUT_MS = 400;      // < poll interval so hung polls cannot stack
const PROBE_BACKOFF_MS = 10000;    // no agent found → stop hammering all 5 ports

async function fetchAgentStatus(port: number): Promise<AgentStatus | null> {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), LOCAL_TIMEOUT_MS);
  try {
    const r = await fetch(`http://127.0.0.1:${port}/status`, {
      cache: 'no-store',
      signal: ctl.signal,
    });
    if (!r.ok) return null;
    const d: AgentStatus = await r.json();
    return d && d.service === AGENT_SERVICE ? d : null;
  } catch {
    return null;   // agent absent, wrong port, or CORS-blocked
  } finally {
    clearTimeout(t);
  }
}

export function useWeight() {
  const [reading, setReading] = useState<WeightReading>(IDLE);
  const wsRef = useRef<WebSocket | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);
  const delayRef = useRef(BASE_DELAY_MS);
  const lastMsgRef = useRef(0);   // timestamp of the last CLOUD frame received

  const agentPortRef = useRef<number | null>(null);
  const nextProbeAtRef = useRef(0);
  const localBusyRef = useRef(false);

  /** True while the cloud feed is delivering frames — it always wins. */
  const cloudIsFresh = () => Date.now() - lastMsgRef.current < LOCAL_TAKEOVER_MS;

  const connect = useCallback(() => {
    if (!mountedRef.current) return;

    // Clean up any prior socket before opening a new one (avoids leaking zombies
    // when the watchdog or a retry fires while one is still half-open).
    if (wsRef.current) {
      try { wsRef.current.onclose = null; wsRef.current.close(); } catch { /* noop */ }
      wsRef.current = null;
    }

    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const host = window.location.host;

    // Multi-tenant: send the tenant slug AND the JWT — the server requires a
    // token whose `tenant` claim matches, so a tenant can only read its own feed.
    const tenant = getTenantSlug();
    const authToken = getAuthToken();
    const qp = new URLSearchParams();
    if (tenant) qp.set('tenant', tenant);
    if (authToken) qp.set('token', authToken);
    const query = qp.toString() ? `?${qp.toString()}` : '';
    const ws = new WebSocket(`${protocol}://${host}/ws/weight${query}`);
    wsRef.current = ws;

    ws.onopen = () => {
      // Reset backoff + arm the watchdog on a successful connection.
      delayRef.current = BASE_DELAY_MS;
      lastMsgRef.current = Date.now();
    };

    ws.onmessage = (event) => {
      lastMsgRef.current = Date.now();
      try {
        const data = JSON.parse(event.data) as Omit<WeightReading, 'source'>;
        setReading({ ...data, source: 'cloud' });   // cloud takes over immediately
      } catch {
        // ignore malformed frames
      }
    };

    ws.onclose = (event) => {
      if (!mountedRef.current) return;
      if (wsRef.current === ws) wsRef.current = null;
      // Mark disconnected but do NOT blank the number here: a 1-second blip
      // would flicker the display. The local poller below decides within
      // LOCAL_TAKEOVER_MS — it either substitutes the local reading or clears
      // it, so a stale number can never sit on screen indefinitely.
      setReading(prev => ({ ...prev, scale_connected: false }));

      // "No scale manager yet" (1013) is the only case that warrants a long
      // backoff — there's literally no scale to stream. Every other close is a
      // transient drop on a live feed, so reconnect fast.
      const absent = event.code === MANAGER_ABSENT_CODE;
      if (absent) delayRef.current = ABSENT_DELAY_MS;
      const cap = absent ? ABSENT_DELAY_MS : MAX_DELAY_MS;

      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(connect, delayRef.current);
      delayRef.current = Math.min(delayRef.current * 2, cap);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    connect();

    // Watchdog: if the socket is "open" but silent for too long, it's a zombie —
    // close it so onclose schedules a fast reconnect. This is what turns a 30 s
    // frozen reading into a ~1–2 s recovery.
    const watchdog = setInterval(() => {
      if (!mountedRef.current) return;
      const ws = wsRef.current;
      if (
        ws && ws.readyState === WebSocket.OPEN &&
        lastMsgRef.current > 0 &&
        Date.now() - lastMsgRef.current > SILENCE_LIMIT_MS
      ) {
        try { ws.close(); } catch { /* onclose reconnects */ }
      }
    }, WATCHDOG_INTERVAL_MS);

    // Local fallback poller. Runs continuously but does nothing while the cloud
    // feed is fresh, so there is exactly one source of truth at any moment and
    // no merging of two feeds.
    const localPoll = setInterval(async () => {
      if (!mountedRef.current || localBusyRef.current) return;
      if (cloudIsFresh()) return;                    // cloud is driving

      localBusyRef.current = true;
      try {
        let port = agentPortRef.current;
        let data = port !== null ? await fetchAgentStatus(port) : null;

        // Cached port failed (or none yet) → rediscover, rate-limited so a
        // machine with no agent isn't probing five ports twice a second.
        if (!data && Date.now() >= nextProbeAtRef.current) {
          for (const p of AGENT_PORTS) {
            if (p === port) continue;
            const d = await fetchAgentStatus(p);
            if (d) {
              port = p;
              data = d;
              agentPortRef.current = p;
              try { localStorage.setItem(AGENT_PORT_KEY, String(p)); } catch { /* noop */ }
              break;
            }
          }
          if (!data) {
            agentPortRef.current = null;
            nextProbeAtRef.current = Date.now() + PROBE_BACKOFF_MS;
          }
        }

        if (!mountedRef.current) return;
        // The cloud may have recovered while we were awaiting — it wins.
        if (cloudIsFresh()) return;

        const next = agentStatusToReading(data);
        // When neither source is live we show a blank rather than the last
        // known value — a frozen number beside a truck on the bridge is worse
        // than an obvious "no reading". Reuse the previous object in that case
        // so an idle poll doesn't re-render twice a second.
        setReading(prev =>
          next.source === 'none' && prev.source === 'none' && prev.weight_kg === 0 ? prev : next);
      } finally {
        localBusyRef.current = false;
      }
    }, LOCAL_POLL_MS);

    return () => {
      mountedRef.current = false;
      clearInterval(watchdog);
      clearInterval(localPoll);
      if (timerRef.current) clearTimeout(timerRef.current);
      const ws = wsRef.current;
      if (ws) { try { ws.onclose = null; ws.close(); } catch { /* noop */ } }
    };
  }, [connect]);

  /** Formatted weight in kg, e.g. "1,234.50 kg" (kept for compat). */
  const formatted = reading.weight_kg.toLocaleString('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }) + ' kg';

  /** Formatted weight in the tenant's display unit, e.g. "1.2350 MT" or
   *  "12.350 Qtl" for maize. (Name kept for backward compat with callers.) */
  const formattedMT = fmtKg(reading.weight_kg, 4);

  /** True when the reading is coming straight off the scale on this PC. */
  const isLocalSource = reading.source === 'local';

  return { reading, formatted, formattedMT, isLocalSource };
}
