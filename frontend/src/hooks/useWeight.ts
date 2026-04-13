import { useEffect, useRef, useState, useCallback } from 'react';
import { getTenantSlug } from './useAuth';

export interface WeightReading {
  weight_kg: number;
  is_stable: boolean;
  stable_duration_sec: number;
  scale_connected: boolean;
}

const BASE_DELAY_MS = 3000;
const MAX_DELAY_MS = 30000;
const MANAGER_ABSENT_CODE = 1013; // server sends 1013 when weight manager is None

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

  const connect = useCallback(() => {
    if (!mountedRef.current) return;

    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const host = window.location.host;

    // Append tenant slug as query param in multi-tenant mode
    const tenant = getTenantSlug();
    const tenantParam = tenant ? `?tenant=${encodeURIComponent(tenant)}` : '';
    const ws = new WebSocket(`${protocol}://${host}/ws/weight${tenantParam}`);
    wsRef.current = ws;

    ws.onopen = () => {
      // Reset backoff on successful connection
      delayRef.current = BASE_DELAY_MS;
    };

    ws.onmessage = (event) => {
      try {
        const data: WeightReading = JSON.parse(event.data);
        setReading(data);
      } catch {
        // ignore malformed frames
      }
    };

    ws.onclose = (event) => {
      if (!mountedRef.current) return;
      setReading(prev => ({ ...prev, scale_connected: false }));

      // If manager is absent (1013), use longer backoff
      if (event.code === MANAGER_ABSENT_CODE) {
        delayRef.current = MAX_DELAY_MS;
      }

      timerRef.current = setTimeout(connect, delayRef.current);
      // Exponential backoff: 3s → 6s → 12s → 24s → 30s (capped)
      delayRef.current = Math.min(delayRef.current * 2, MAX_DELAY_MS);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    connect();
    return () => {
      mountedRef.current = false;
      if (timerRef.current) clearTimeout(timerRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  /** Formatted weight string like "1,234.50 kg" */
  const formatted = reading.weight_kg.toLocaleString('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }) + ' kg';

  return { reading, formatted };
}
