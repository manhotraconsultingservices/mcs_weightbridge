/**
 * Sidebar — BCG-grouped navigation.
 *
 *   7 items across 4 labelled sections + a single Admin gear-icon dropdown.
 *   All existing routes preserved as direct-URL bookmarks via App.tsx;
 *   sidebar now points to hub pages that render the old pages as tabs.
 *
 *   Sections:
 *     (no header)         Dashboard
 *     OPERATIONS          Weighbridge (gate + trips + cameras + ANPR)
 *     COMMERCIAL          Sales & CRM · Procurement
 *     RESOURCES           Inventory & Production
 *     FINANCE & INTELLIGENCE  Accounts · Analytics
 */
import { NavLink, useNavigate } from 'react-router-dom';
import { useState, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import {
  LayoutDashboard, Scale, FileText, ShoppingCart, Factory,
  BookOpen, TrendingUp, Package,
  LogOut, Usb, Settings,
  Bell, HardDrive, Upload, UserCog, Lock, ImageIcon, Building2,
  Camera, Cog, FileBarChart, ShieldAlert, FileCheck2,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { getTenantModules } from '@/hooks/useAuth';
import LanguageToggle from '@/components/LanguageToggle';
import type { User } from '@/types';

// ── Hub → child paths (for permission expansion + active-link detection) ──────
//
// If a role's stored permissions include ANY child path, the hub link is shown.
// Old permissions (e.g. '/gate', '/purchase-invoices') automatically expand to
// show the hub that wraps them — no permission-store migration needed.
const HUB_CHILDREN: Record<string, string[]> = {
  '/weighbridge':      ['/gate', '/tokens-v1', '/tokens', '/anpr/trips'],
  '/cameras-anpr':     ['/camera-scale', '/snapshot-search', '/anpr/events', '/anpr/live', '/anpr/review', '/anpr/trips'],
  '/sales':            ['/invoices', '/quotations', '/delivery-challans', '/credit-debit-notes', '/customers', '/parties'],
  '/procurement':      ['/purchase-invoices', '/royalty'],
  '/inventory-hub':    ['/products', '/pricing-matrix', '/product-inventory', '/inventory'],
  '/production-hub':   ['/production', '/production/dashboard', '/production/settings'],
  '/accounts':         ['/payments', '/ledger', '/audit'],
  '/gst-compliance':   ['/gst-reports', '/compliance'],
  '/analytics':        ['/reports', '/reports-classic'],
  '/fraud-registers':  ['/reports', '/reports-classic'],
};

// Tenant module gating — if ALL listed modules are disabled, the hub is hidden.
// Note: '/inventory-hub' is intentionally NOT gated — Products/Catalog/Production
// are core features always available. The 'inventory' module gates only the
// Store Inventory API (/api/v1/inventory) at the backend level.
const HUB_MODULES: Record<string, string[]> = {
  '/weighbridge':   ['weighing'],
  '/sales':         ['invoicing', 'quotations'],
  '/procurement':   ['invoicing'],
  '/accounts':      ['payments', 'gst_reports', 'compliance'],
  '/analytics':     ['reports'],
};

interface SidebarProps {
  user: User;
  onLogout: () => void;
  usbAuthorized?: boolean;
  permissions?: string[];   // allowed paths; ["*"] = admin (show all)
  mobileOpen?: boolean;
  onMobileClose?: () => void;
}

type NavItem    = { to: string; icon: React.ElementType; labelKey: string };
type NavSection = { headerKey?: string; items: NavItem[] };

// ── Navigation — 4 sections, 7 hub entries ───────────────────────────────────
const NAV_SECTIONS: NavSection[] = [
  {
    // No section header — Dashboard stands alone at the top
    items: [
      { to: '/', icon: LayoutDashboard, labelKey: 'sidebar.dashboard' },
    ],
  },
  {
    headerKey: 'sidebar.sectionOperations',
    items: [
      { to: '/weighbridge',  icon: Scale,  labelKey: 'sidebar.weighbridge' },
      { to: '/cameras-anpr', icon: Camera, labelKey: 'sidebar.camerasAnpr' },
    ],
  },
  {
    headerKey: 'sidebar.sectionCommercial',
    items: [
      { to: '/sales',       icon: FileText,     labelKey: 'sidebar.salesCrm' },
      { to: '/procurement', icon: ShoppingCart, labelKey: 'sidebar.procurement' },
      { to: '/products',    icon: Package,      labelKey: 'sidebar.catalog' },
    ],
  },
  {
    headerKey: 'sidebar.sectionResources',
    items: [
      { to: '/inventory-hub',  icon: Factory, labelKey: 'sidebar.inventoryProduction' },
      { to: '/production-hub', icon: Cog,     labelKey: 'sidebar.productionHub' },
    ],
  },
  {
    headerKey: 'sidebar.sectionFinance',
    items: [
      { to: '/accounts',        icon: BookOpen,     labelKey: 'sidebar.accounts' },
      { to: '/compliance',      icon: FileCheck2,   labelKey: 'sidebar.compliance' },
      { to: '/gst-compliance',  icon: FileBarChart, labelKey: 'sidebar.gstCompliance' },
      { to: '/analytics',       icon: TrendingUp,   labelKey: 'sidebar.analytics' },
      { to: '/fraud-registers', icon: ShieldAlert,  labelKey: 'sidebar.fraudRegisters' },
    ],
  },
];

// ── Admin items (gear dropdown — unchanged) ───────────────────────────────────
const ADMIN_ITEMS: NavItem[] = [
  { to: '/settings',          icon: Settings,  labelKey: 'sidebar.companySettings' },
  { to: '/admin/branches',    icon: Building2, labelKey: 'sidebar.branches' },
  { to: '/admin/users',       icon: UserCog,   labelKey: 'sidebar.users' },
  { to: '/admin/permissions', icon: Lock,      labelKey: 'sidebar.rolePermissions' },
  { to: '/admin/wallpaper',   icon: ImageIcon, labelKey: 'sidebar.branding' },
  { to: '/notifications',     icon: Bell,      labelKey: 'sidebar.notifications' },
  { to: '/backup',            icon: HardDrive, labelKey: 'sidebar.backup' },
  { to: '/import',            icon: Upload,    labelKey: 'sidebar.dataImport' },
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
    // Dashboard is always visible regardless of stored permissions
    if (item.to === '/') return true;

    // Admins see everything (module-gated items excepted)
    if (isAdmin) {
      const mods = HUB_MODULES[item.to];
      if (mods && modules) {
        const anyEnabled = mods.some(m => modules[m] !== false);
        if (!anyEnabled) return false;
      }
      return true;
    }
    // Direct permission OR any hub-child permission
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

  // Filter admin items by SaaS restrictions
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
          <Scale className="h-5 w-5" />
        </div>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-sidebar-foreground">WeighbridgeSetu</p>
          <p className="truncate text-xs text-sidebar-foreground/50">by Manhotra Consulting</p>
        </div>
      </div>

      {/* Navigation — 4 labelled sections */}
      <nav className="flex-1 overflow-y-auto px-2 py-3">
        <ul className="space-y-2">
          {NAV_SECTIONS.map((section, si) => {
            const visibleItems = section.items.filter(isVisible);
            if (visibleItems.length === 0) return null;
            return (
              <li key={si}>
                {section.headerKey && (
                  <p className="mt-1 mb-0.5 px-3 text-[9px] font-semibold uppercase tracking-widest text-sidebar-foreground/35 select-none">
                    {t(section.headerKey)}
                  </p>
                )}
                <ul className="space-y-0.5">
                  {visibleItems.map(item => (
                    <li key={item.to}>
                      <NavItemLink {...item} end={item.to === '/'} onClick={onMobileClose} />
                    </li>
                  ))}
                </ul>
              </li>
            );
          })}

          {/* USB-gated Supplement entry */}
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
            className="absolute right-3 bottom-16 z-40 w-52 max-w-[calc(100vw-1.5rem)] rounded-lg border border-sidebar-border bg-sidebar shadow-xl overflow-hidden"
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
