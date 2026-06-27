import { useEffect, useRef, useState, useCallback } from 'react';
import { getTenantSlug, getAuthToken } from './useAuth';
import { fmtKg } from '@/lib/weightUnit';

export interface WeightReading {
  weight_kg: number;
  is_stable: boolean;
  stable_duration_sec: number;
  scale_connected: boolean;
}

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

export function useWeight() {
  const [reading, setReading] = useState<WeightReading>({
    weight_kg: 0,
    is_stable: false,
    stable_duration_sec: 0,
    scale_connected: false,
  });
  const wsRef = useRef<WebSocket | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);
  const delayRef = useRef(BASE_DELAY_MS);
  const lastMsgRef = useRef(0);   // timestamp of the last frame received

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
        const data: WeightReading = JSON.parse(event.data);
        setReading(data);
      } catch {
        // ignore malformed frames
      }
    };

    ws.onclose = (event) => {
      if (!mountedRef.current) return;
      if (wsRef.current === ws) wsRef.current = null;
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

    return () => {
      mountedRef.current = false;
      clearInterval(watchdog);
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

  return { reading, formatted, formattedMT };
}
