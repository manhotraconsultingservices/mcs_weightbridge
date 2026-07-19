import { useState, useCallback, useEffect } from 'react';
import type { User } from '@/types';
import { applyIndustryTerminology } from '@/i18n';
import api from '@/services/api';

// How often an active session silently re-mints its token while online (P1 #174).
// Well inside the 8 h token life, so a shift punctuated by 30–40 min outages
// keeps a valid token the whole time — the operator is never logged out
// mid-shift and, crucially, never needs the network to re-login during an outage.
const REFRESH_INTERVAL_MS = 20 * 60 * 1000;

// Use sessionStorage — tokens are cleared when the browser tab/window closes.
// This prevents tokens persisting on disk (localStorage survives browser close
// and is readable from the file system by anyone with physical PC access).
const STORE = sessionStorage;

export function useAuth() {
  const [user, setUser] = useState<User | null>(() => {
    const stored = STORE.getItem('user');
    return stored ? JSON.parse(stored) : null;
  });

  const [token, setToken] = useState<string | null>(() => STORE.getItem('token'));

  const login = useCallback((accessToken: string, userData: User, tenantSlug?: string, tenantModules?: Record<string, boolean>, tenantIndustry?: string) => {
    STORE.setItem('token', accessToken);
    STORE.setItem('user', JSON.stringify(userData));
    if (tenantSlug) {
      STORE.setItem('tenant_slug', tenantSlug);
    } else {
      STORE.removeItem('tenant_slug');
    }
    if (tenantModules) {
      STORE.setItem('tenant_modules', JSON.stringify(tenantModules));
    } else {
      STORE.removeItem('tenant_modules');
    }
    if (tenantIndustry) {
      STORE.setItem('tenant_industry', tenantIndustry);
    } else {
      STORE.removeItem('tenant_industry');
    }
    // Swap in (or clear) the industry terminology overlay for this tenant.
    applyIndustryTerminology(tenantIndustry || null);
    setToken(accessToken);
    setUser(userData);
  }, []);

  const logout = useCallback(() => {
    STORE.removeItem('token');
    STORE.removeItem('user');
    STORE.removeItem('tenant_slug');
    STORE.removeItem('tenant_modules');
    STORE.removeItem('tenant_industry');
    applyIndustryTerminology(null);   // reset labels to base
    setToken(null);
    setUser(null);
  }, []);

  // Listen for 401 events from axios interceptor
  useEffect(() => {
    const handler = () => logout();
    window.addEventListener('auth:logout', handler);
    return () => window.removeEventListener('auth:logout', handler);
  }, [logout]);

  // Refresh-on-use (P1 #174): while a session is active, silently re-mint the
  // token periodically and on focus so it never expires mid-shift. A failure is
  // swallowed — during an outage the POST just fails (network error, NOT a 401),
  // so the still-valid token is kept; the next online tick refreshes it. Only a
  // genuine 401 (already expired while online) logs out, via the interceptor.
  const refresh = useCallback(async () => {
    if (!STORE.getItem('token')) return;
    try {
      const { data } = await api.post('/api/v1/auth/refresh');
      if (data?.access_token) {
        STORE.setItem('token', data.access_token);
        setToken(data.access_token);
      }
    } catch {
      /* offline / transient — keep the existing token */
    }
  }, []);

  useEffect(() => {
    if (!token) return;
    const id = window.setInterval(refresh, REFRESH_INTERVAL_MS);
    const onVisible = () => { if (document.visibilityState === 'visible') refresh(); };
    window.addEventListener('focus', refresh);
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      window.clearInterval(id);
      window.removeEventListener('focus', refresh);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [token, refresh]);

  const isAuthenticated = !!token && !!user;

  return { user, token, isAuthenticated, login, logout };
}

/** Get the current tenant slug from session storage (for WebSocket connections). */
export function getTenantSlug(): string | null {
  return sessionStorage.getItem('tenant_slug');
}

/** Get the current JWT (for WebSocket query-param auth — the /ws/weight endpoint
 *  requires it in multi-tenant mode so one tenant can't read another's feed). */
export function getAuthToken(): string | null {
  return sessionStorage.getItem('token');
}

/** Get tenant modules from session storage (for sidebar filtering). */
export function getTenantModules(): Record<string, boolean> | null {
  const raw = sessionStorage.getItem('tenant_modules');
  if (!raw) return null;
  try { return JSON.parse(raw); } catch { return null; }
}

/** Get the tenant's industry profile (e.g. 'maize_trader'); null = generic. */
export function getTenantIndustry(): string | null {
  return sessionStorage.getItem('tenant_industry');
}

/**
 * Is a feature module enabled for this tenant? Defaults to TRUE when modules
 * are unset (single-tenant / no config) or the key is absent — so gating is
 * purely additive and never hides anything for tenants without a profile.
 */
export function moduleEnabled(name: string): boolean {
  const mods = getTenantModules();
  if (!mods) return true;
  return mods[name] !== false;
}
