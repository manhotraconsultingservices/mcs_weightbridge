import { useState, useEffect, useCallback } from 'react';
import api from '@/services/api';
import type { RoleTabPermissions } from '@/contexts/PermissionsContext';

// ── Default permissions (fallback if API unreachable) ─────────────────────── //

// Permissions use HUB paths (matching the sidebar items the user sees).
// Sidebar.tsx isVisible() grants a hub when permissions includes the hub path
// directly (permissions.includes('/analytics')) OR when it includes any child
// path via HUB_CHILDREN — so old leaf-path DB values continue to work.
export const DEFAULT_PERMISSIONS: Record<string, string[]> = {
  admin: ['*'],

  // Gate guard — gate register only; auto-redirected to /gate on login
  gate_guard: [
    '/weighbridge',  // + DEFAULT_ROLE_TAB_PERMISSIONS pins them to the Gate Register tab
  ],

  // Operator — weighing + camera; auto-redirected to /operator kiosk
  operator: [
    '/weighbridge',   // Gate Register · Weigh Tickets · Movement Report
    '/cameras-anpr',  // Camera & Scale · Snapshots · ANPR Events
  ],

  // Store manager — full inventory and production visibility
  store_manager: [
    '/inventory-hub',  // Finished Goods · Store · Products Catalog · Customer Rates
    '/production-hub', // Daily Cycles · Production Dashboard · Settings
  ],

  // Sales executive — full sales cycle
  sales_executive: [
    '/sales',    // Bills · Estimates · Challans · Notes · Customers 360
    '/products', // Item Catalog (sidebar direct item)
  ],

  // Purchase executive — procurement only
  purchase_executive: [
    '/procurement', // Purchase Invoices · Royalty / Transit Passes
    '/products',    // Item Catalog
  ],

  // Accountant — full financial + reporting access incl. sales for write-offs
  accountant: [
    '/sales',            // Bills (write-offs, revision review)
    '/accounts',         // Payments · Account Statement · Activity Log
    '/gst-compliance',   // GST Returns · Compliance Docs
    '/analytics',        // P&L · Sales Status · GST Split · Write-offs
    '/fraud-registers',  // Anomaly Detection · Gate Pass Register · Token Register
  ],

  // Viewer — read-only reports and compliance
  viewer: [
    '/analytics',       // P&L · Sales Status · Write-offs (read-only)
    '/gst-compliance',  // GST Returns · Compliance Docs
    '/accounts',        // Account Statement (read-only)
  ],
};

export interface AppSettings {
  permissions: string[];   // allowed paths for the current user's role; ["*"] means all
  wallpaperUrl: string | null;
  loading: boolean;
  refresh: () => void;
  roleTabPerms: RoleTabPermissions; // { role → { hubPath → allowedTabValues[] } }
}

// Default TAB grants, applied only when the tenant has never saved any. A gate
// guard must land confined to the Gate Register — granting the Weighbridge hub
// alone would otherwise also hand them Weigh Tickets and the Movement Report.
export const DEFAULT_ROLE_TAB_PERMISSIONS: RoleTabPermissions = {
  gate_guard: { '/weighbridge': ['gate'] },
};

export function useAppSettings(userRole: string): AppSettings {
  // Start from defaults immediately so sidebar renders correctly without flash
  const [permissions, setPermissions] = useState<string[]>(
    userRole === 'admin' ? ['*'] : (DEFAULT_PERMISSIONS[userRole] ?? []),
  );
  const [wallpaperUrl, setWallpaperUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [roleTabPerms, setRoleTabPerms] = useState<RoleTabPermissions>(DEFAULT_ROLE_TAB_PERMISSIONS);

  const fetchSettings = useCallback(async () => {
    try {
      const [permsRes, wallRes, tabRes] = await Promise.all([
        api.get<Record<string, string[]>>('/api/v1/app-settings/role-permissions'),
        api.get<{ url: string | null }>('/api/v1/app-settings/wallpaper/info'),
        api.get<RoleTabPermissions>('/api/v1/app-settings/role-tab-permissions').catch(() => ({ data: {} as RoleTabPermissions })),
      ]);

      const map = permsRes.data ?? {};
      // Admin defaults to full access, but an admin who narrowed their OWN view on
      // /admin/permissions has a stored list — honour it, or the save appears to do
      // nothing. An empty/absent entry still means full access, so a tenant that
      // never touched it is unaffected.
      const stored = map[userRole];
      const rolePerms =
        userRole === 'admin'
          ? (Array.isArray(stored) && stored.length > 0 ? stored : ['*'])
          : (stored ?? DEFAULT_PERMISSIONS[userRole] ?? []);

      setPermissions(rolePerms);
      setWallpaperUrl(wallRes.data?.url ?? null);
      // Stored config wins per ROLE; a role the tenant never configured keeps its
      // default (so upgrading doesn't silently widen an existing gate guard).
      const storedTabs = tabRes.data ?? {};
      setRoleTabPerms({ ...DEFAULT_ROLE_TAB_PERMISSIONS, ...storedTabs });
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

  return { permissions, wallpaperUrl, loading, refresh: fetchSettings, roleTabPerms };
}
