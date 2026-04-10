import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard, Ticket, FileText, ShoppingCart, Package,
  Users, Truck, Settings, BarChart3, BookOpen, CreditCard,
  Receipt, FileBarChart, LogOut, Usb, Bell, Shield, HardDrive,
  Upload, Scale, ShieldCheck, UserCog, ImageIcon, Lock, MonitorPlay, Warehouse,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import type { User } from '@/types';

interface SidebarProps {
  user: User;
  onLogout: () => void;
  usbAuthorized?: boolean;
  permissions?: string[];   // allowed paths; ["*"] = admin (show all)
}

type NavItem = { to: string; icon: React.ElementType; label: string };

const navGroups: { label: string | null; items: NavItem[] }[] = [
  {
    label: null,
    items: [
      { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
    ],
  },
  {
    label: '📦 Daily Work',
    items: [
      { to: '/tokens', icon: Ticket, label: 'Tokens' },
      { to: '/camera-scale', icon: MonitorPlay, label: 'Camera & Scale' },
      { to: '/inventory', icon: Warehouse, label: 'Store Inventory' },
      { to: '/invoices', icon: FileText, label: 'Invoices' },
      { to: '/quotations', icon: Receipt, label: 'Quotations' },
    ],
  },
  {
    label: '💰 Finance',
    items: [
      { to: '/payments', icon: CreditCard, label: 'Payments' },
      { to: '/ledger', icon: BookOpen, label: 'Ledger' },
      { to: '/gst-reports', icon: FileBarChart, label: 'GST Reports' },
      { to: '/reports', icon: BarChart3, label: 'Reports' },
    ],
  },
  {
    label: '🗂 Master Data',
    items: [
      { to: '/parties', icon: Users, label: 'Parties' },
      { to: '/products', icon: Package, label: 'Products' },
      { to: '/vehicles', icon: Truck, label: 'Vehicles' },
    ],
  },
  {
    label: '⚙️ System',
    items: [
      { to: '/compliance', icon: ShieldCheck, label: 'Compliance' },
      { to: '/notifications', icon: Bell, label: 'Notifications' },
      { to: '/audit', icon: Shield, label: 'Audit Trail' },
      { to: '/backup', icon: HardDrive, label: 'Backup' },
      { to: '/import', icon: Upload, label: 'Data Import' },
      { to: '/settings', icon: Settings, label: 'Settings' },
    ],
  },
];

// Admin-only nav group — always shown when permissions === ["*"]
const adminGroup: { label: string; items: NavItem[] } = {
  label: '🔐 Administration',
  items: [
    { to: '/admin/users',       icon: UserCog,   label: 'User Management' },
    { to: '/admin/permissions', icon: Lock,       label: 'Role Permissions' },
    { to: '/admin/wallpaper',   icon: ImageIcon,  label: 'Wallpaper' },
  ],
};

function NavItemLink({ to, icon: Icon, label, end }: NavItem & { end?: boolean }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        `group flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-all ${
          isActive
            ? 'border-l-[3px] border-sidebar-primary bg-sidebar-accent text-sidebar-accent-foreground pl-[9px]'
            : 'border-l-[3px] border-transparent text-sidebar-foreground/60 pl-[9px] hover:bg-sidebar-accent/60 hover:text-sidebar-foreground'
        }`
      }
    >
      <Icon className="h-4 w-4 shrink-0" />
      <span className="truncate">{label}</span>
    </NavLink>
  );
}

export default function Sidebar({ user, onLogout, usbAuthorized = false, permissions = ['*'] }: SidebarProps) {
  const isAdmin = permissions.includes('*');

  // Filter a list of items to only those the current role can see
  function filterItems(items: NavItem[]): NavItem[] {
    if (isAdmin) return items;
    return items.filter(item => permissions.includes(item.to));
  }

  return (
    <aside className="flex h-screen w-60 flex-col bg-sidebar text-sidebar-foreground">
      {/* Logo */}
      <div className="flex h-16 shrink-0 items-center gap-3 border-b border-sidebar-border px-4">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground shadow-sm">
          <Scale className="h-5 w-5" />
        </div>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-sidebar-foreground">Weighbridge</p>
          <p className="truncate text-xs text-sidebar-foreground/50">Stone Crusher ERP</p>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto px-2 py-3 space-y-4">
        {navGroups.map((group, gi) => {
          const visibleItems = filterItems(group.items);
          if (visibleItems.length === 0) return null;

          return (
            <div key={gi}>
              {group.label && (
                <p className="mb-1 px-3 text-[10px] font-semibold uppercase tracking-widest text-sidebar-foreground/35 select-none">
                  {group.label}
                </p>
              )}
              <ul className="space-y-0.5">
                {visibleItems.map((item) => (
                  <li key={item.to}>
                    <NavItemLink {...item} end={item.to === '/'} />
                  </li>
                ))}
                {/* Private Invoices — shown only after USB authorization, inside Operations group */}
                {gi === 1 && usbAuthorized && (
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
                      <span className="truncate">Supplement</span>
                    </NavLink>
                  </li>
                )}
              </ul>
            </div>
          );
        })}

        {/* Administration — admin only */}
        {isAdmin && (
          <div>
            <p className="mb-1 px-3 text-[10px] font-semibold uppercase tracking-widest text-sidebar-foreground/35 select-none">
              {adminGroup.label}
            </p>
            <ul className="space-y-0.5">
              {adminGroup.items.map(item => (
                <li key={item.to}>
                  <NavItemLink {...item} />
                </li>
              ))}
            </ul>
          </div>
        )}
      </nav>

      {/* User / Logout */}
      <div className="shrink-0 border-t border-sidebar-border p-3">
        <div className="flex items-center justify-between rounded-md px-2 py-2">
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-sidebar-foreground">{user.full_name || user.username}</p>
            <p className="truncate text-xs text-sidebar-foreground/50 capitalize">{user.role.replace(/_/g, ' ')}</p>
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={onLogout}
            title="Logout"
            className="h-8 w-8 shrink-0 text-sidebar-foreground/60 hover:bg-sidebar-accent hover:text-sidebar-foreground"
          >
            <LogOut className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </aside>
  );
}
