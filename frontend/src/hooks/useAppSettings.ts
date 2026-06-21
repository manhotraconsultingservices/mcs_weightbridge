import { useState, useEffect, useCallback } from 'react';
import api from '@/services/api';

// ── Default permissions (fallback if API unreachable) ─────────────────────── //

export const DEFAULT_PERMISSIONS: Record<string, string[]> = {
  admin: ['*'],

  // Gate guard — gate register only; auto-redirected to /gate on login
  gate_guard: [
    '/gate',
  ],

  // Operator — weighing operations + camera monitoring; auto-redirected to /operator kiosk
  operator: [
    '/gate',            // Weighbridge: Gate Register
    '/tokens-v1',       // Weighbridge: Weigh Tickets
    '/anpr/trips',      // Weighbridge: Movement Report
    '/camera-scale',    // Cameras & ANPR: Camera & Scale
    '/snapshot-search', // Cameras & ANPR: Snapshots
  ],

  // Store manager — all inventory and production; no financial/sales access
  store_manager: [
    '/product-inventory',     // Inventory: Finished Goods
    '/inventory',             // Inventory: Store Inventory
    '/products',              // Inventory: Products Catalog
    '/pricing-matrix',        // Inventory: Customer Rates
    '/production',            // Production: Daily Production
    '/production/dashboard',  // Production: Dashboard
    '/production/settings',   // Production: Settings
  ],

  // Sales executive — full sales cycle (bills, estimates, challans, notes, customers)
  sales_executive: [
    '/invoices',           // Sales: Bills
    '/quotations',         // Sales: Estimates
    '/delivery-challans',  // Sales: Challans
    '/credit-debit-notes', // Sales: Notes
    '/customers',          // Sales: Customers (360 view)
    '/parties',            // Masters: Parties
    '/vehicles',           // Masters: Vehicles
    '/products',           // Masters: Products
    '/pricing-matrix',     // Inventory: Customer Rates
  ],

  // Purchase executive — procurement + royalty passes
  purchase_executive: [
    '/purchase-invoices', // Procurement: Purchase Invoices
    '/royalty',           // Procurement: Royalty Passes
    '/parties',           // Masters: Parties
    '/products',          // Masters: Products
    '/pricing-matrix',    // Inventory: Customer Rates
  ],

  // Accountant — full financial access (accounts, GST, compliance, analytics, reports)
  accountant: [
    '/payments',          // Accounts: Payments
    '/ledger',            // Accounts: Account Statement
    '/audit',             // Accounts: Activity Log
    '/gst-reports',       // GST & Compliance: GST Returns
    '/compliance',        // GST & Compliance: Compliance Docs
    '/reports',           // Analytics: P&L + Fraud & Registers
    '/invoices',          // Sales: Bills (for write-offs, review)
    '/parties',           // Masters: Parties
    '/pricing-matrix',    // Customer Rates
  ],

  // Viewer — read-only dashboards and reports
  viewer: [
    '/reports',     // Analytics + Fraud & Registers (read-only)
    '/gst-reports', // GST & Compliance: GST Returns
    '/ledger',      // Accounts: Account Statement
    '/compliance',  // GST & Compliance: Compliance Docs
  ],
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
