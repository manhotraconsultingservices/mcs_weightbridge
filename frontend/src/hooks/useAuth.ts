import { useState, useCallback, useEffect } from 'react';
import type { User } from '@/types';

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

  const login = useCallback((accessToken: string, userData: User, tenantSlug?: string, tenantModules?: Record<string, boolean>) => {
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
    setToken(accessToken);
    setUser(userData);
  }, []);

  const logout = useCallback(() => {
    STORE.removeItem('token');
    STORE.removeItem('user');
    STORE.removeItem('tenant_slug');
    STORE.removeItem('tenant_modules');
    setToken(null);
    setUser(null);
  }, []);

  // Listen for 401 events from axios interceptor
  useEffect(() => {
    const handler = () => logout();
    window.addEventListener('auth:logout', handler);
    return () => window.removeEventListener('auth:logout', handler);
  }, [logout]);

  const isAuthenticated = !!token && !!user;

  return { user, token, isAuthenticated, login, logout };
}

/** Get the current tenant slug from session storage (for WebSocket connections). */
export function getTenantSlug(): string | null {
  return sessionStorage.getItem('tenant_slug');
}

/** Get tenant modules from session storage (for sidebar filtering). */
export function getTenantModules(): Record<string, boolean> | null {
  const raw = sessionStorage.getItem('tenant_modules');
  if (!raw) return null;
  try { return JSON.parse(raw); } catch { return null; }
}
