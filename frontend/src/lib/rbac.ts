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
      { path: '/weighbridge',  label: 'Weighbridge',    hint: 'Gate Register · Weigh Tickets · Movement Report. For a gate guard, tick this then untick every tab except Gate Register — the others become unreachable, not just hidden.' },
      { path: '/cameras-anpr', label: 'Cameras & ANPR', hint: 'Camera & Scale · Snapshots · ANPR · Plate Review' },
      { path: '/device-health', label: 'Device Health',  hint: 'Scale & camera uptime monitor + down-alerts' },
      { path: '/vehicle-count', label: 'Gate Vehicle Count', hint: 'Autonomous truck/car/bike tally vs gate passes (paid add-on)' },
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
    group: 'Administration',
    pages: [
      { path: '/settings', label: 'Settings (business tabs)', hint: 'Company · Bank · Prefixes · Financial Years · Units · Print. Pick the exact tabs below — integrations, USB Guard & credentials stay admin-only.' },
    ],
  },
  {
    group: 'Finance & Intelligence',
    pages: [
      { path: '/accounts',        label: 'Accounts',          hint: 'Payments · Ledger · Balances · Advances · Government Dues · Activity Log' },
      { path: '/workforce',       label: 'Workforce & Payroll', hint: 'Workers · attendance · wages/salary · advances' },
      { path: '/compliance',      label: 'Compliance',        hint: 'Insurance / License / Permit tracker' },
      { path: '/gst-compliance',  label: 'GST & Compliance',  hint: 'GSTR-1 / 3B / 2B · Compliance Docs' },
      { path: '/analytics',       label: 'Analytics',         hint: 'P&L · Sales by Status · GST Split · Write-offs' },
      { path: '/fraud-registers', label: 'Fraud & Registers', hint: 'Anomaly Detection · Gate Pass Register · Token Register' },
    ],
  },
];

// Which hub child ROUTES each tab owns. This is what makes a tab grant real: untick
// "Weigh Tickets" for a role and /tokens-v1 stops being reachable, not merely hidden.
// A hub absent from this map keeps the old behaviour (tabs hide, routes stay open),
// so adding a hub here is opt-in and nothing else changes.
export const HUB_TAB_ROUTES: Record<string, Record<string, string[]>> = {
  '/weighbridge': {
    gate:     ['/gate'],
    tickets:  ['/tokens-v1', '/tokens'],
    movement: ['/anpr/trips'],
  },
  // Accounts: untick a tab and its page stops being reachable by URL too, not just
  // hidden — otherwise withholding e.g. Government Dues is only cosmetic.
  '/accounts': {
    payments:  ['/payments'],
    statement: ['/ledger'],
    balances:  ['/party-balances'],
    advances:  ['/advances'],
    statutory: ['/statutory-dues'],
    activity:  ['/audit'],
  },
};

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
  '/accounts':        ['/payments', '/ledger', '/audit', '/party-balances', '/advances', '/statutory-dues'],
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
    { value: 'statutory', label: 'Government Dues' },
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
  // Settings is the ONE delegatable config page, and only these business tabs may
  // ever be granted. Integration/credential tabs (Tally, eInvoice, E-Way, Cameras,
  // Gate Cameras, ANPR, Barrier, Scale, Notifications, UPI, Device Health) and USB
  // Guard are deliberately absent — they can never be handed to a non-admin.
  '/settings': [
    { value: 'company',  label: 'Company Profile' },
    { value: 'bank',     label: 'Bank Details' },
    { value: 'prefixes', label: 'Invoice Prefixes' },
    { value: 'fy',       label: 'Financial Years' },
    { value: 'units',    label: 'Units' },
    { value: 'print',    label: 'Print / Invoice Format' },
  ],
};

/** The only Settings tabs that may be delegated to a non-admin role. */
export const SETTINGS_DELEGATABLE_TABS: ReadonlySet<string> = new Set(
  (HUB_TABS['/settings'] ?? []).map(t => t.value),
);

/**
 * Which Settings tabs may the current role open?
 *
 *   admin  → null  (no restriction — every tab, including integrations)
 *   others → the EXPLICITLY granted tabs, intersected with the delegatable list.
 *
 * NOTE the inverted semantic vs other hubs: elsewhere an empty/absent tab list
 * means "no restriction, show all". For Settings that would leak integration and
 * credential tabs to anyone granted the page, so here it is a strict ALLOW-LIST —
 * an unconfigured or empty grant shows NOTHING.
 */
export function allowedSettingsTabs(
  role: string | undefined,
  roleTabPerms: Record<string, Record<string, string[]>> | undefined,
): Set<string> | null {
  if (role === 'admin') return null;
  const granted = roleTabPerms?.[role ?? '']?.['/settings'] ?? [];
  return new Set(granted.filter(t => SETTINGS_DELEGATABLE_TABS.has(t)));
}

// `labelKey` is the single i18n key for this role's display name. Both the Role
// Permissions page and User Management resolve through it, so a role can no longer
// show up under two different names (gate_guard read 'Gate Guard' on one screen and
// 'Security Guard' on the other, which is why nobody could find it — 2026-08-15).
// `label` is the fallback: admin-created custom roles have no i18n key, their name
// is whatever the admin typed, so `labelKey` is optional and `label` stands in.
export interface RoleDef { value: string; label: string; labelKey?: string; color: string }

/** The one place a role's display name is resolved. Pass i18next's `t`. */
export function roleLabel(r: RoleDef, t?: (k: string) => string): string {
  return r.labelKey && t ? t(r.labelKey) : r.label;
}

// Built-in non-admin roles (admin is implicit and always has full access).
/** The tenant admin, for screens that let an admin tune their OWN view.
 *  Not part of BUILTIN_ROLES — the user-role pickers already offer admin. */
export const ADMIN_ROLE_DEF: RoleDef = {
  value: 'admin', label: 'Admin / Owner', labelKey: 'users.roles.admin', color: 'text-violet-600',
};

export const BUILTIN_ROLES: RoleDef[] = [
  { value: 'gate_guard',         label: 'Gate Guard', labelKey: 'users.roles.gate_guard',         color: 'text-rose-600' },
  { value: 'store_manager',      label: 'Store Manager', labelKey: 'users.roles.store_manager',      color: 'text-emerald-600' },
  { value: 'operator',           label: 'Weighbridge Operator', labelKey: 'users.roles.operator',           color: 'text-blue-600' },
  { value: 'sales_executive',    label: 'Sales Executive', labelKey: 'users.roles.sales_executive',    color: 'text-green-600' },
  { value: 'purchase_executive', label: 'Purchase Executive', labelKey: 'users.roles.purchase_executive', color: 'text-orange-600' },
  { value: 'accountant',         label: 'Accountant', labelKey: 'users.roles.accountant',         color: 'text-cyan-600' },
  { value: 'viewer',             label: 'Viewer', labelKey: 'users.roles.viewer',             color: 'text-gray-500' },
];

export const BUILTIN_ROLE_VALUES = new Set(
  ['admin', 'private_admin', ...BUILTIN_ROLES.map(r => r.value)],
);

// Config/admin routes — admin only, never listed in the permission grid.
// '/settings' is NOT here: it is grantable per-role, but only its business tabs
// (see HUB_TABS['/settings'] + allowedSettingsTabs). Everything else stays admin.
export const ADMIN_ROUTES = new Set([
  '/notifications', '/backup', '/import',
  '/admin/branches', '/admin/users', '/admin/permissions',
  '/admin/custom-fields', '/admin/wallpaper', '/approvals',
  // Owner clean-up of gate passes the guard never closed — rewrites the
  // physical gate record after the fact, so admin-only and not delegatable.
  '/admin/open-gate-passes',
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
/** Roles that always land on one specific page at login, whatever else they hold. */
export const ROLE_HOME: Record<string, string> = {
  operator:   '/operator',   // simplified kiosk
  gate_guard: '/gate',       // Gate Register
};

/**
 * Where a user lands at login. `null` = render the owner dashboard in place.
 *
 * Tab-aware on purpose: a role granted only a hub (e.g. `/weighbridge`) but
 * restricted to one tab must land on THAT tab's page, not the hub's default tab
 * — otherwise a gate guard opens on Weigh Tickets, which they cannot use.
 */
export function resolveHomeRoute(
  role: string | undefined,
  permissions: string[],
  allowedTabsByHub?: Record<string, string[]>,
): string | null {
  if (role && ROLE_HOME[role]) return ROLE_HOME[role];
  if (role === 'admin' || permissions.includes('*') || permissions.includes('/')) return null;
  const first = permissions[0];
  if (!first) return null;
  const tabRoutes = HUB_TAB_ROUTES[first];
  const allowed = allowedTabsByHub?.[first];
  if (tabRoutes && allowed && allowed.length > 0) {
    for (const tab of allowed) {
      const routes = tabRoutes[tab];
      if (routes && routes.length) return routes[0];
    }
  }
  return first;
}

/**
 * Pages the PLATFORM (vendor) has withheld from a tenant.
 *
 * This is the ONLY restriction a tenant admin cannot escape: every other check
 * short-circuits on `role === 'admin'`, and the tenant could otherwise simply grant
 * the page back to itself from Role Permissions. Set per tenant in the platform
 * console and delivered at login, so it is not something the tenant can edit.
 *
 * A restricted hub takes its child routes with it — withholding "/settings" without
 * withholding the pages reachable from it would be decoration.
 */
export function isPlatformRestricted(pathname: string, restrictions?: string[] | null): boolean {
  if (!restrictions || restrictions.length === 0) return false;
  const path = (pathname || '/').toLowerCase();
  return restrictions.some(rawRule => {
    const rule = String(rawRule || '').trim().toLowerCase();
    if (!rule || rule === '/') return false;          // never lock a tenant out entirely
    if (path === rule || path.startsWith(rule + '/')) return true;
    // a restricted hub also withholds the child pages it owns
    const children = HUB_CHILDREN[rule];
    return !!children && children.some(c => path === c || path.startsWith(c + '/'));
  });
}


export function canAccessRoute(
  pathname: string,
  permissions: string[],
  role?: string,
  /** { hubPath → allowed tab values } for THIS role. Empty/absent = no tab
   *  restriction, exactly as isTabAllowed() treats it. */
  allowedTabsByHub?: Record<string, string[]>,
  /** Pages the PLATFORM withheld from this tenant. Checked BEFORE the admin
   *  bypass — this is the one restriction a tenant admin cannot grant back. */
  platformRestrictions?: string[] | null,
): boolean {
  if (isPlatformRestricted(pathname, platformRestrictions)) return false;
  // '*' is full access — the default state for admin, and what every admin has
  // unless they deliberately narrow their own view on /admin/permissions.
  if (permissions.includes('*')) return true;
  if (role === 'admin') {
    // An admin who narrowed their own view keeps the administration pages, so the
    // change is always reversible. Without this a single wrong tick would lock the
    // tenant's only admin out of the screen that undoes it.
    if (pathname.startsWith('/admin/') || pathname === '/settings') return true;
  }
  const req = routeRequirement(pathname);
  if (req.kind === 'allow') return true;
  if (req.kind === 'admin') return role === 'admin';
  if (!hasPagePerm(permissions, req.hub)) return false;

  // The hub is granted — but if the admin restricted this role to certain tabs,
  // a child route belonging to a REMOVED tab must be blocked too, otherwise the
  // restriction is cosmetic and the page is still reachable by URL.
  const tabRoutes = HUB_TAB_ROUTES[req.hub];
  const allowed = allowedTabsByHub?.[req.hub];
  if (tabRoutes && allowed && allowed.length > 0) {
    for (const [tab, routes] of Object.entries(tabRoutes)) {
      if (routes.includes(pathname)) return allowed.includes(tab);
    }
  }
  return true;
}
