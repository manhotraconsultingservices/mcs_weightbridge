/**
 * Is the Tally integration switched on for this tenant?
 *
 * Every Tally control in the app asks this ONE place, so a tenant that does not
 * use Tally never sees a Tally button, column or panel anywhere — and the answer
 * cannot drift between pages.
 *
 * Two gates, cheapest first:
 *   1. the `tally_sync` FEATURE MODULE (per-tenant, set by the platform admin) —
 *      when off, `/api/v1/tally/*` returns 403, so we never even ask;
 *   2. `tally_config.is_enabled` (per-tenant, set in Settings → Tally).
 *
 * Anything unexpected reads as OFF: never offer an action we cannot perform.
 *
 * The answer is fetched once and shared. It is keyed to the tenant so signing in
 * as a different company in the same tab cannot inherit the previous answer, and
 * it is re-fetched when Settings → Tally is saved (`tally:updated`).
 */
import { useEffect, useState } from 'react';
import api from '../services/api';
import { getTenantSlug, moduleEnabled } from './useAuth';

type Cache = { slug: string | null; enabled: boolean };

let cache: Cache | null = null;
let inflight: Promise<boolean> | null = null;
const listeners = new Set<(v: boolean) => void>();

async function fetchEnabled(): Promise<boolean> {
  // The module gate is a local check — skip the round trip when it is off.
  if (!moduleEnabled('tally_sync')) return false;
  try {
    const { data } = await api.get<{ is_enabled?: boolean }>('/api/v1/tally/config');
    return !!data?.is_enabled;
  } catch {
    return false;
  }
}

function load(): Promise<boolean> {
  const slug = getTenantSlug();
  if (cache && cache.slug === slug) return Promise.resolve(cache.enabled);
  if (!inflight) {
    inflight = fetchEnabled().then(enabled => {
      cache = { slug, enabled };
      inflight = null;
      listeners.forEach(fn => fn(enabled));
      return enabled;
    });
  }
  return inflight;
}

/** Forget the cached answer and re-ask (called after Settings → Tally is saved). */
export function refreshTallyEnabled(): void {
  cache = null;
  inflight = null;
  void load();
}

export function useTallyEnabled(): boolean {
  const [enabled, setEnabled] = useState<boolean>(
    cache && cache.slug === getTenantSlug() ? cache.enabled : false,
  );

  useEffect(() => {
    let alive = true;
    listeners.add(setEnabled);
    void load().then(v => { if (alive) setEnabled(v); });

    const onChange = () => refreshTallyEnabled();
    window.addEventListener('tally:updated', onChange);
    window.addEventListener('appsettings:updated', onChange);
    return () => {
      alive = false;
      listeners.delete(setEnabled);
      window.removeEventListener('tally:updated', onChange);
      window.removeEventListener('appsettings:updated', onChange);
    };
  }, []);

  return enabled;
}
