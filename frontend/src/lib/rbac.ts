/**
 * RBAC catalogue + route-permission resolver — the single source of truth for
 * role-based access control on the frontend.
 *
 * Exposes:
 *  - CATALOGUE_GROUPS — the pages that appear in the Role Permissions grid.
 *    Mirrors the sidebar 1:1. System-config pages (Settings, Users, Permissions,
 *    Backup, Import, Branches, Notifications, Custom Fields, Branding) are
 *    intentionally NOT here — they stay admin-only.
 *  - HUB_CHILDREN — hub → child routes; used by the sidebar (show a hub when any
 *    child perm exists) AND by the route guard (a child inherits its hub's perm).
 *  - HUB_TABS — tab definitions per hub, for tab-level permissions.
 *  - BUILTIN_ROLES — the fixed non-admin roles.
 *  - canAccessRoute() — the guard that blocks URL access to a page the current
 *    role hasn't been granted (so access control is real, not just a hidden menu).
 */

export interface CataloguePage { path: string; label: string; hint?: string }
export interface CatalogueGroup { group: string; pages: CataloguePage[] }

// Operational + reporting pages, mirroring the sidebar sections exactly.
export const CATALOGUE_GROUPS: CatalogueGroup[] = [
  {
    group: 'General',
    pages: [
      { path: '/', label: 'Dashboard', hint: 'Home overview — always visible' },
    ],
  },
  {
    group: 'Operations',
    pages: [
      { path: '/weighbridge',  label: 'Weighbridge',    hint: 'Gate Register · Weigh Tickets · Movement Report' },
      { path: '/cameras-anpr', label: 'Cameras & ANPR', hint: 'Camera & Scale · Snapshots · ANPR · Plate Review' },
      { path: '/device-health', label: 'Device Health',  hint: 'Scale & camera uptime monitor + down-alerts' },
    ],
  },
  {
    group: 'Commercial',
    pages: [
      { path: '/sales',          label: 'Sales Documents',           hint: 'Bills · Estimates · Challans · Credit/Debit Notes' },
      { path: '/crm',            label: 'CRM (Customers & Suppliers)', hint: 'Customer & Supplier 360 · Party master' },
      { path: '/procurement',    label: 'Procurement',               hint: 'Purchase Invoices · Royalty / Transit Passes' },
      { path: '/products',       label: 'Item Catalog',              hint: 'Products master' },
      { path: '/pricing-matrix', label: 'Pricing',                   hint: 'Default + customer/supplier rates by unit' },
      { path: '/agents',         label: 'Sales Partners / Agents',   hint: 'Broker commission dashboards + payouts' },
    ],
  },
  {
    group: 'Resources',
    pages: [
      { path: '/inventory-hub',  label: 'Inventory',      hint: 'Finished Goods · Store · Catalog · Pricing' },
      { path: '/production-hub', label: 'Production',     hint: 'Daily Cycles · Dashboard · Settings' },
      { path: '/vehicles',       label: 'Vehicle Master', hint: 'Vehicles · Drivers · Transporters' },
      { path: '/fuel',           label: 'Fuel & Mileage', hint: 'Diesel log · Mileage vs benchmark · Leakage detection' },
    ],
  },
  {
    group: 'Finance & Intelligence',
    pages: [
      { path: '/accounts',        label: 'Accounts',          hint: 'Payments · Ledger · Balances · Advances · Activity Log' },
      { path: '/workforce',       label: 'Workforce & Payroll', hint: 'Workers · attendance · wages/salary · advances' },
      { path: '/compliance',      label: 'Compliance',        hint: 'Insurance / License / Permit tracker' },
      { path: '/gst-compliance',  label: 'GST & Compliance',  hint: 'GSTR-1 / 3B / 2B · Compliance Docs' },
      { path: '/analytics',       label: 'Analytics',         hint: 'P&L · Sales by Status · GST Split · Write-offs' },
      { path: '/fraud-registers', label: 'Fraud & Registers', hint: 'Anomaly Detection · Gate Pass Register · Token Register' },
    ],
  },
];

// hub → child routes. Granting a hub grants every child; a stored legacy child
// path (e.g. '/gate') still unlocks its wrapping hub.
export const HUB_CHILDREN: Record<string, string[]> = {
  '/weighbridge':     ['/gate', '/tokens-v1', '/tokens', '/anpr/trips'],
  '/cameras-anpr':    ['/camera-scale', '/snapshot-search', '/anpr/events', '/anpr/live', '/anpr/review', '/anpr/trips'],
  '/sales':           ['/invoices', '/quotations', '/delivery-challans', '/credit-debit-notes'],
  '/crm':             ['/customers', '/parties', '/suppliers'],
  '/procurement':     ['/purchase-invoices', '/royalty'],
  '/inventory-hub':   ['/products', '/product-inventory', '/inventory'],
  '/production-hub':  ['/production', '/production/dashboard', '/production/settings'],
  '/accounts':        ['/payments', '/ledger', '/audit', '/party-balances', '/advances'],
  '/gst-compliance':  ['/gst-reports', '/compliance'],
  '/analytics':       ['/reports', '/reports-classic'],
  '/fraud-registers': ['/reports', '/reports-classic'],
};

// Tab definitions per hub — mirror the TabsTrigger value= strings on each hub.
export const HUB_TABS: Record<string, { value: string; label: string }[]> = {
  '/weighbridge': [
    { value: 'gate',     label: 'Gate Register' },
    { value: 'tickets',  label: 'Weigh Tickets' },
    { value: 'movement', label: 'Movement Report' },
  ],
  '/cameras-anpr': [
    { value: 'cameras',   label: 'Camera & Scale' },
    { value: 'snapshots', label: 'Snapshot Search' },
    { value: 'gate-live', label: 'Gate Live Feed' },
    { value: 'anpr',      label: 'ANPR Events' },
    { value: 'review',    label: 'Plate Review' },
  ],
  '/sales': [
    { value: 'bills',     label: 'Sales Bills' },
    { value: 'estimates', label: 'Estimates' },
    { value: 'challans',  label: 'Delivery Challans' },
    { value: 'notes',     label: 'Credit/Debit Notes' },
  ],
  '/crm': [
    { value: 'customers', label: 'Customers 360' },
    { value: 'suppliers', label: 'Suppliers 360' },
  ],
  '/procurement': [
    { value: 'purchases', label: 'Purchase Invoices' },
    { value: 'royalty',   label: 'Royalty & Transit' },
  ],
  '/inventory-hub': [
    { value: 'stock',   label: 'Finished Goods Stock' },
    { value: 'store',   label: 'Store Inventory' },
    { value: 'catalog', label: 'Products Catalog' },
    { value: 'rates',   label: 'Pricing' },
  ],
  '/production-hub': [
    { value: 'production', label: 'Daily Cycles' },
    { value: 'dashboard',  label: 'Production Dashboard' },
    { value: 'settings',   label: 'Production Settings' },
  ],
  '/fuel': [
    { value: 'log',     label: 'Fuel Log' },
    { value: 'report',  label: 'Mileage Report' },
    { value: 'trends',  label: 'Trends' },
    { value: 'leakage', label: 'Leakage Alerts' },
  ],
  '/workforce': [
    { value: 'workers',    label: 'Workers' },
    { value: 'attendance', label: 'Attendance' },
    { value: 'payments',   label: 'Payments' },
    { value: 'summary',    label: 'Payroll' },
  ],
  '/accounts': [
    { value: 'payments',  label: 'Payments' },
    { value: 'statement', label: 'Account Statement' },
    { value: 'activity',  label: 'Activity Log' },
  ],
  '/gst-compliance': [
    { value: 'gst',        label: 'GST Returns' },
    { value: 'gstr2b',     label: 'GSTR-2B ITC Recon' },
    { value: 'compliance', label: 'Compliance Docs' },
  ],
  '/analytics': [
    { value: 'pl',           label: 'P&L Report' },
    { value: 'sales-status', label: 'Sales by Status' },
    { value: 'gst-split',    label: 'GST vs Cash Split' },
    { value: 'write-offs',   label: 'Write-offs' },
  ],
  '/fraud-registers': [
    { value: 'anomaly',        label: 'Anomaly Detection' },
    { value: 'gate-passes',    label: 'Gate Pass Register' },
    { value: 'token-register', label: 'Token Register' },
  ],
};

export interface RoleDef { value: string; label: string; color: string }

// Built-in non-admin roles (admin is implicit and always has full access).
export const BUILTIN_ROLES: RoleDef[] = [
  { value: 'gate_guard',         label: 'Gate Guard',         color: 'text-rose-600' },
  { value: 'store_manager',      label: 'Store Manager',      color: 'text-emerald-600' },
  { value: 'operator',           label: 'Operator',           color: 'text-blue-600' },
  { value: 'sales_executive',    label: 'Sales Executive',    color: 'text-green-600' },
  { value: 'purchase_executive', label: 'Purchase Executive', color: 'text-orange-600' },
  { value: 'accountant',         label: 'Accountant',         color: 'text-cyan-600' },
  { value: 'viewer',             label: 'Viewer',             color: 'text-gray-500' },
];

export const BUILTIN_ROLE_VALUES = new Set(
  ['admin', 'private_admin', ...BUILTIN_ROLES.map(r => r.value)],
);

// Config/admin routes — admin only, never listed in the permission grid.
export const ADMIN_ROUTES = new Set([
  '/settings', '/notifications', '/backup', '/import',
  '/admin/branches', '/admin/users', '/admin/permissions',
  '/admin/custom-fields', '/admin/wallpaper',
]);

// Routes that must never be blocked by the guard: the home redirect, detail
// pages reached from allowed parents, and legacy hubs. NOTE: the reports hub
// (/reports) is deliberately NOT here — it exposes financial reports, so it
// requires Analytics access (mapped below).
const ALWAYS_ALLOW = new Set([
  '/', '/materials', '/operations', '/dashboard-legacy', '/private-invoices', '/operator',
]);
const DETAIL_RE = /^\/(customers|suppliers|agents)\/[^/]+$/;

// path → hub permission it requires. HUB_CHILDREN is applied first, then the
// direct catalogue paths override (a catalogue item requires itself).
const ROUTE_TO_HUB: Record<string, string> = {};
for (const [hub, kids] of Object.entries(HUB_CHILDREN)) {
  for (const kid of kids) ROUTE_TO_HUB[kid] = hub;
}
for (const g of CATALOGUE_GROUPS) {
  for (const p of g.pages) ROUTE_TO_HUB[p.path] = p.path;
}
// The multi-hub reports pages resolve to Analytics for the guard (they're not in
// the sidebar directly; only reachable by URL/bookmark).
ROUTE_TO_HUB['/reports'] = '/analytics';
ROUTE_TO_HUB['/reports-classic'] = '/analytics';

/** Does this permission set grant `hubPath`? Mirrors the sidebar's isVisible(). */
export function hasPagePerm(permissions: string[], hubPath: string): boolean {
  if (permissions.includes('*')) return true;
  if (permissions.includes(hubPath)) return true;
  return (HUB_CHILDREN[hubPath] || []).some(c => permissions.includes(c));
}

type RouteReq = { kind: 'allow' } | { kind: 'admin' } | { kind: 'page'; hub: string };

/** Classify a concrete pathname into what it requires. */
export function routeRequirement(pathname: string): RouteReq {
  const path = pathname !== '/' && pathname.endsWith('/') ? pathname.slice(0, -1) : pathname;
  if (ALWAYS_ALLOW.has(path)) return { kind: 'allow' };
  if (ADMIN_ROUTES.has(path)) return { kind: 'admin' };
  if (DETAIL_RE.test(path)) return { kind: 'allow' };
  const hub = ROUTE_TO_HUB[path];
  if (hub) return { kind: 'page', hub };
  return { kind: 'allow' }; // fail-open for unknown/utility routes — never lock out
}

/**
 * Can the current role open this route directly?
 * Admin → always. Config routes → admin only. Catalogue pages → require the
 * granting perm. Everything else (details, unknowns) → allowed.
 */
export function canAccessRoute(pathname: string, permissions: string[], role?: string): boolean {
  if (role === 'admin' || permissions.includes('*')) return true;
  const req = routeRequirement(pathname);
  if (req.kind === 'allow') return true;
  if (req.kind === 'admin') return false;
  return hasPagePerm(permissions, req.hub);
}
