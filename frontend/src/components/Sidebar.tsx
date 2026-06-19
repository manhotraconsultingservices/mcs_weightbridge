/**
 * Sidebar — Sprint 3 consolidated layout.
 *
 *   8 top-level items + a single Admin gear-icon dropdown.  Hub URLs render
 *   tabbed pages internally so each child page is still reachable by direct
 *   URL (old bookmarks unaffected).  Vocabulary refreshed to operator-friendly
 *   labels (e.g. "Trips" instead of "Token", "Bills" inside the Sales hub).
 *
 *   Permissions: each sidebar entry maps to a path; if the user's role
 *   permissions include that path OR ["*"], it's shown.  For roles that
 *   stored child URLs (legacy), we expand the permission set to include the
 *   hub URL so the menu still renders.
 */
import { NavLink, useNavigate } from 'react-router-dom';
import { useState, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import {
  LayoutDashboard, Truck, FileText, ShoppingCart, Users,
  Box, Wrench, BarChart3, DoorOpen,
  LogOut, Usb, Settings,
  Bell, HardDrive, Upload, UserCog, Lock, ImageIcon, Building2,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { getTenantModules } from '@/hooks/useAuth';
import LanguageToggle from '@/components/LanguageToggle';
import type { User } from '@/types';

// ── Hub → child paths (for permission expansion + module gating) ───────────
//
// If a role's stored permissions include ANY of the child paths, the hub link
// is shown. Same for tenant `modules` flags: if any child module is enabled,
// the hub is enabled.
const HUB_CHILDREN: Record<string, string[]> = {
  // Customers sidebar entry points to the 360 picker; permissions that
  // referenced /parties still unlock the entry.
  '/customers':   ['/parties', '/customers'],
  '/sales':       ['/invoices', '/quotations'],
  '/materials':   ['/products', '/pricing-matrix', '/product-inventory', '/production', '/production/dashboard', '/production/settings'],
  '/operations':  ['/vehicles', '/inventory', '/camera-scale', '/snapshot-search', '/anpr/events', '/anpr/live', '/anpr/review', '/anpr/trips'],
  '/reports':     ['/payments', '/ledger', '/gst-reports', '/reports', '/reports-classic', '/compliance', '/audit'],
};

// Tenant module gating — module disabled hides the hub entirely.
const HUB_MODULES: Record<string, string[]> = {
  '/tokens-v1':   ['weighing'],
  '/sales':       ['invoicing', 'quotations'],
  '/purchase-invoices': ['invoicing'],
  '/materials':   ['inventory'],
  '/operations':  ['weighing', 'inventory'],
  '/reports':     ['payments', 'gst_reports', 'reports', 'compliance'],
};

interface SidebarProps {
  user: User;
  onLogout: () => void;
  usbAuthorized?: boolean;
  permissions?: string[];   // allowed paths; ["*"] = admin (show all)
  mobileOpen?: boolean;
  onMobileClose?: () => void;
}

type NavItem = { to: string; icon: React.ElementType; labelKey: string };

// ── Main nav (8 items + Gate Register) ────────────────────────────────────
const NAV_ITEMS: NavItem[] = [
  { to: '/',                 icon: LayoutDashboard, labelKey: 'sidebar.dashboard' },
  { to: '/tokens-v1',        icon: Truck,           labelKey: 'sidebar.trips' },
  { to: '/gate',             icon: DoorOpen,        labelKey: 'sidebar.gateRegister' },
  { to: '/sales',            icon: FileText,        labelKey: 'sidebar.sales' },
  { to: '/purchase-invoices', icon: ShoppingCart,   labelKey: 'sidebar.purchases' },
  // Customers points to the Customer 360 picker. Parties master list is
  // reachable from there via the "Master list" link, or directly at /parties.
  { to: '/customers',        icon: Users,           labelKey: 'sidebar.customers' },
  { to: '/materials',        icon: Box,             labelKey: 'sidebar.materials' },
  { to: '/operations',       icon: Wrench,          labelKey: 'sidebar.operations' },
  { to: '/reports',          icon: BarChart3,       labelKey: 'sidebar.reports' },
];

// ── Admin items (gear dropdown) ────────────────────────────────────────────
const ADMIN_ITEMS: NavItem[] = [
  { to: '/settings',          icon: Settings,   labelKey: 'sidebar.companySettings' },
  { to: '/admin/branches',    icon: Building2,  labelKey: 'sidebar.branches' },
  { to: '/admin/users',       icon: UserCog,    labelKey: 'sidebar.users' },
  { to: '/admin/permissions', icon: Lock,       labelKey: 'sidebar.rolePermissions' },
  { to: '/admin/wallpaper',   icon: ImageIcon,  labelKey: 'sidebar.branding' },
  { to: '/notifications',     icon: Bell,       labelKey: 'sidebar.notifications' },
  { to: '/backup',            icon: HardDrive,  labelKey: 'sidebar.backup' },
  { to: '/import',            icon: Upload,     labelKey: 'sidebar.dataImport' },
];

function NavItemLink({ to, icon: Icon, labelKey, end, onClick }: NavItem & { end?: boolean; onClick?: () => void }) {
  const { t } = useTranslation();
  return (
    <NavLink
      to={to}
      end={end}
      onClick={onClick}
      className={({ isActive }) =>
        `group flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-all ${
          isActive
            ? 'border-l-[3px] border-sidebar-primary bg-sidebar-accent text-sidebar-accent-foreground pl-[9px]'
            : 'border-l-[3px] border-transparent text-sidebar-foreground/60 pl-[9px] hover:bg-sidebar-accent/60 hover:text-sidebar-foreground'
        }`
      }
    >
      <Icon className="h-4 w-4 shrink-0" />
      <span className="truncate">{t(labelKey)}</span>
    </NavLink>
  );
}

export default function Sidebar({ user, onLogout, usbAuthorized = false, permissions = ['*'], mobileOpen = false, onMobileClose }: SidebarProps) {
  const { t } = useTranslation();
  const isAdmin = permissions.includes('*');
  const modules = getTenantModules();
  const isSaaS = sessionStorage.getItem('multi_tenant') === '1';
  const nav = useNavigate();

  const [adminOpen, setAdminOpen] = useState(false);
  const adminMenuRef = useRef<HTMLDivElement | null>(null);

  // Close admin dropdown on outside-click
  useEffect(() => {
    if (!adminOpen) return;
    const handler = (e: MouseEvent) => {
      if (adminMenuRef.current && !adminMenuRef.current.contains(e.target as Node)) {
        setAdminOpen(false);
      }
    };
    window.addEventListener('mousedown', handler);
    return () => window.removeEventListener('mousedown', handler);
  }, [adminOpen]);

  // Is this item visible for the current user + tenant?
  function isVisible(item: NavItem): boolean {
    // Admins see everything
    if (isAdmin) {
      // …except module-gated items when the module flag is disabled
      const mods = HUB_MODULES[item.to];
      if (mods && modules) {
        const anyEnabled = mods.some(m => modules[m] !== false);
        if (!anyEnabled) return false;
      }
      return true;
    }
    // Direct permission OR hub-child permission
    const ok =
      permissions.includes(item.to) ||
      (HUB_CHILDREN[item.to] || []).some(child => permissions.includes(child));
    if (!ok) return false;
    // Module gating
    const mods = HUB_MODULES[item.to];
    if (mods && modules) {
      const anyEnabled = mods.some(m => modules[m] !== false);
      if (!anyEnabled) return false;
    }
    return true;
  }

  const visibleNav = NAV_ITEMS.filter(isVisible);
  // Always include the dashboard regardless of role permissions (it's the home)
  if (!visibleNav.some(i => i.to === '/')) visibleNav.unshift(NAV_ITEMS[0]);

  // Filter admin items by SaaS restrictions (no Backup in SaaS mode)
  const visibleAdmin = ADMIN_ITEMS.filter(item => {
    if (isSaaS && item.to === '/backup') return false;
    if (isSaaS && item.to === '/import') return false;
    return true;
  });

  const sidebarContent = (
    <aside className="flex h-full w-60 flex-col bg-sidebar text-sidebar-foreground">
      {/* Logo */}
      <div className="flex h-16 shrink-0 items-center gap-3 border-b border-sidebar-border px-4">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground shadow-sm">
          <Truck className="h-5 w-5" />
        </div>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-sidebar-foreground">WeighbridgeSetu</p>
          <p className="truncate text-xs text-sidebar-foreground/50">by Manhotra Consulting</p>
        </div>
      </div>

      {/* Navigation — 8 top-level items, no group headers */}
      <nav className="flex-1 overflow-y-auto px-2 py-3">
        <ul className="space-y-0.5">
          {visibleNav.map(item => (
            <li key={item.to}>
              <NavItemLink {...item} end={item.to === '/'} onClick={onMobileClose} />
            </li>
          ))}

          {/* USB-gated Supplement entry — shown only after USB authorization */}
          {usbAuthorized && (
            <li>
              <NavLink
                to="/private-invoices"
                className={({ isActive }) =>
                  `flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-all border-l-[3px] ${
                    isActive
                      ? 'border-sidebar-primary bg-sidebar-accent text-sidebar-accent-foreground pl-[9px]'
                      : 'border-transparent text-sidebar-foreground/60 pl-[9px] hover:bg-sidebar-accent/60 hover:text-sidebar-foreground'
                  }`
                }
              >
                <span className="relative flex h-4 w-4 shrink-0 items-center justify-center">
                  <Usb className="h-4 w-4" />
                  <span className="absolute -top-0.5 -right-0.5 h-1.5 w-1.5 rounded-full bg-green-400 animate-pulse" />
                </span>
                <span className="truncate">{t('sidebar.supplement')}</span>
              </NavLink>
            </li>
          )}
        </ul>
      </nav>

      {/* User / Admin gear / Logout */}
      <div className="shrink-0 border-t border-sidebar-border p-3 relative">
        <div className="flex items-center gap-2 rounded-md px-2 py-2">
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-sidebar-foreground">{user.full_name || user.username}</p>
            <p className="truncate text-xs text-sidebar-foreground/50 capitalize">{user.role.replace(/_/g, ' ')}</p>
          </div>
          <LanguageToggle className="h-7 px-2 text-xs font-medium text-sidebar-foreground/70 hover:text-sidebar-foreground border border-sidebar-border hover:bg-sidebar-accent" />
          {/* Admin gear — admins only */}
          {isAdmin && (
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setAdminOpen(o => !o)}
              title="Admin"
              className="h-8 w-8 shrink-0 text-sidebar-foreground/60 hover:bg-sidebar-accent hover:text-sidebar-foreground"
            >
              <Settings className="h-4 w-4" />
            </Button>
          )}
          <Button
            variant="ghost"
            size="icon"
            onClick={onLogout}
            title={t('sidebar.logout')}
            className="h-8 w-8 shrink-0 text-sidebar-foreground/60 hover:bg-sidebar-accent hover:text-sidebar-foreground"
          >
            <LogOut className="h-4 w-4" />
          </Button>
        </div>

        {/* Admin dropup — opens above the user row when gear is clicked */}
        {isAdmin && adminOpen && (
          <div
            ref={adminMenuRef}
            className="absolute right-3 bottom-16 z-40 w-52 rounded-lg border border-sidebar-border bg-sidebar shadow-xl overflow-hidden"
          >
            <div className="px-3 py-2 border-b border-sidebar-border">
              <p className="text-[10px] font-semibold uppercase tracking-widest text-sidebar-foreground/40">{t('sidebar.administration')}</p>
            </div>
            <ul className="py-1 max-h-[60vh] overflow-y-auto">
              {visibleAdmin.map(item => {
                const Icon = item.icon;
                return (
                  <li key={item.to}>
                    <button
                      onClick={() => { nav(item.to); setAdminOpen(false); onMobileClose?.(); }}
                      className="w-full flex items-center gap-2 px-3 py-2 text-sm text-sidebar-foreground/80 hover:bg-sidebar-accent hover:text-sidebar-foreground text-left"
                    >
                      <Icon className="h-4 w-4 shrink-0" />
                      <span className="truncate">{t(item.labelKey)}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </div>
    </aside>
  );

  return (
    <>
      {/* Desktop sidebar — always visible on md+ */}
      <div className="hidden md:flex h-screen w-60 shrink-0">
        {sidebarContent}
      </div>

      {/* Mobile overlay — rendered only when mobileOpen */}
      {mobileOpen && (
        <div className="md:hidden fixed inset-0 z-50 flex">
          {/* Backdrop */}
          <div
            className="fixed inset-0 bg-black/50"
            onClick={onMobileClose}
            aria-hidden="true"
          />
          {/* Sidebar panel */}
          <div className="relative z-10 h-full">
            {sidebarContent}
          </div>
        </div>
      )}
    </>
  );
}
