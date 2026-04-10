import { useState, useEffect, useCallback } from 'react';
import api from '@/services/api';

// ── Default permissions (fallback if API unreachable) ─────────────────────── //

export const DEFAULT_PERMISSIONS: Record<string, string[]> = {
  admin: ['*'],
  store_manager: ['/inventory'],
  operator: ['/tokens'],
  sales_executive: ['/invoices', '/quotations', '/parties', '/vehicles'],
  purchase_executive: ['/invoices', '/parties', '/products'],
  accountant: ['/payments', '/ledger', '/gst-reports', '/reports', '/parties'],
  viewer: ['/reports', '/gst-reports', '/ledger'],
};

export interface AppSettings {
  permissions: string[];   // allowed paths for the current user's role; ["*"] means all
  wallpaperUrl: string | null;
  loading: boolean;
  refresh: () => void;
}

export function useAppSettings(userRole: string): AppSettings {
  // Start from defaults immediately so sidebar renders correctly without flash
  const [permissions, setPermissions] = useState<string[]>(
    userRole === 'admin' ? ['*'] : (DEFAULT_PERMISSIONS[userRole] ?? []),
  );
  const [wallpaperUrl, setWallpaperUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchSettings = useCallback(async () => {
    try {
      const [permsRes, wallRes] = await Promise.all([
        api.get<Record<string, string[]>>('/api/v1/app-settings/role-permissions'),
        api.get<{ url: string | null }>('/api/v1/app-settings/wallpaper/info'),
      ]);

      const map = permsRes.data ?? {};
      const rolePerms =
        userRole === 'admin'
          ? ['*']
          : (map[userRole] ?? DEFAULT_PERMISSIONS[userRole] ?? []);

      setPermissions(rolePerms);
      setWallpaperUrl(wallRes.data?.url ?? null);
    } catch {
      // Network error or unauthenticated — fall back to defaults silently
      setPermissions(userRole === 'admin' ? ['*'] : (DEFAULT_PERMISSIONS[userRole] ?? []));
    } finally {
      setLoading(false);
    }
  }, [userRole]);

  useEffect(() => {
    fetchSettings();

    // Re-fetch when admin saves new settings (dispatched by PermissionsPage / WallpaperSettingsPage)
    const handler = () => fetchSettings();
    window.addEventListener('appsettings:updated', handler);
    return () => window.removeEventListener('appsettings:updated', handler);
  }, [fetchSettings]);

  return { permissions, wallpaperUrl, loading, refresh: fetchSettings };
}
