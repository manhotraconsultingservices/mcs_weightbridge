import { useState, useCallback, useEffect } from 'react';
import type { PlatformUser } from '@/types';
import platformApi from '@/services/platformApi';

export function usePlatformAuth() {
  const [user, setUser] = useState<PlatformUser | null>(() => {
    const raw = sessionStorage.getItem('platform_user');
    return raw ? JSON.parse(raw) : null;
  });

  const [token, setToken] = useState<string | null>(() =>
    sessionStorage.getItem('platform_token')
  );

  const login = useCallback(async (username: string, password: string) => {
    const { data } = await platformApi.post('/api/v1/platform/auth/login', { username, password });
    sessionStorage.setItem('platform_token', data.access_token);
    sessionStorage.setItem('platform_user', JSON.stringify(data.user));
    setToken(data.access_token);
    setUser(data.user);
    return data;
  }, []);

  const logout = useCallback(() => {
    sessionStorage.removeItem('platform_token');
    sessionStorage.removeItem('platform_user');
    setToken(null);
    setUser(null);
  }, []);

  // Listen for 401 events from platformApi interceptor
  useEffect(() => {
    const handler = () => logout();
    window.addEventListener('platform:logout', handler);
    return () => window.removeEventListener('platform:logout', handler);
  }, [logout]);

  return {
    user,
    token,
    isAuthenticated: !!token && !!user,
    isPlatformAdmin: user?.role === 'platform_admin',
    isSalesRep: user?.role === 'sales_rep',
    login,
    logout,
  };
}
