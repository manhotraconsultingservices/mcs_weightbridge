import { useEffect, useState, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { Save, RotateCcw, Info, FileText, Layout } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { useAuth } from '@/hooks/useAuth';
import { DEFAULT_PERMISSIONS } from '@/hooks/useAppSettings';
import type { RoleTabPermissions } from '@/contexts/PermissionsContext';
import api from '@/services/api';

// ── Page catalogue — mirrors the sidebar sections exactly ─────────────────── //
//
// DESIGN: permissions are granted at the HUB level (same names the user sees
// in the sidebar), not at individual leaf pages.  Sidebar.tsx isVisible()
// supports both direct hub paths AND legacy leaf paths via HUB_CHILDREN, so
// old stored permissions continue to work.
//
// Granting a hub gives access to ALL tabs inside it.  More granular control
// is not needed for the current role set.

const PAGE_GROUPS = [
  {
    group: 'General',
    pages: [
      { path: '/',  label: 'Dashboard', hint: 'Exception-first owner overview' },
    ],
  },
  {
    group: 'Operations',  // sidebar section header: OPERATIONS
    pages: [
      {
        path: '/weighbridge',
        label: 'Weighbridge',
        hint: 'Gate Register · Weigh Tickets · Movement Report',
      },
      {
        path: '/cameras-anpr',
        label: 'Cameras & ANPR',
        hint: 'Camera & Scale · Snapshot Search · ANPR Events · Plate Review',
      },
    ],
  },
  {
    group: 'Commercial',  // sidebar section header: COMMERCIAL
    pages: [
      {
        path: '/sales',
        label: 'Sales & CRM',
        hint: 'Bills · Estimates · Challans · Credit/Debit Notes · Customers 360',
      },
      {
        path: '/procurement',
        label: 'Procurement',
        hint: 'Purchase Invoices · Royalty / Transit Passes',
      },
      {
        path: '/products',
        label: 'Item Catalog',
        hint: 'Products master (direct sidebar item)',
      },
    ],
  },
  {
    group: 'Resources',   // sidebar section header: RESOURCES
    pages: [
      {
        path: '/inventory-hub',
        label: 'Inventory',
        hint: 'Finished Goods · Store Inventory · Products Catalog · Pricing',
      },
      {
        path: '/production-hub',
        label: 'Production',
        hint: 'Daily Production Cycles · Production Dashboard · Settings',
      },
    ],
  },
  {
    group: 'Finance & Intelligence',  // sidebar section header: FINANCE & INTELLIGENCE
    pages: [
      {
        path: '/accounts',
        label: 'Accounts',
        hint: 'Payments · Account Statement · Activity Log',
      },
      {
        path: '/gst-compliance',
        label: 'GST & Compliance',
        hint: 'GST Returns (GSTR-1 / 3B / 2B) · Compliance Documents',
      },
      {
        path: '/analytics',
        label: 'Analytics',
        hint: 'P&L · Sales by Status · GST Split · Write-offs Report',
      },
      {
        path: '/fraud-registers',
        label: 'Fraud & Registers',
        hint: 'Anomaly Detection · Gate Pass Register · Token Register',
      },
    ],
  },
];

// ── Tab definitions per hub ──────────────────────────────────────────────── //
// Mirrors the actual TabsTrigger value= strings in each hub page.
// Empty array here = no tab restriction UI for that hub.
const HUB_TABS: Record<string, { value: string; label: string }[]> = {
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
    { value: 'customers', label: 'Customers 360' },
    { value: 'bills',     label: 'Sales Bills' },
    { value: 'estimates', label: 'Estimates' },
    { value: 'challans',  label: 'Delivery Challans' },
    { value: 'notes',     label: 'Credit/Debit Notes' },
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
    { value: 'anomaly',         label: 'Anomaly Detection' },
    { value: 'gate-passes',     label: 'Gate Pass Register' },
    { value: 'token-register',  label: 'Token Register' },
  ],
};

// ── Invoice action catalogue ─────────────────────────────────────────────── //

const INVOICE_ACTION_ITEMS = [
  { key: 'edit_draft',         label: 'Edit Draft Invoice',           icon: '✏️' },
  { key: 'finalize',           label: 'Finalize Invoice',             icon: '✅' },
  { key: 'cancel_draft',       label: 'Cancel Draft Invoice',         icon: '❌' },
  { key: 'record_payment',     label: 'Record Payment',               icon: '💰' },
  { key: 'tally_sync',         label: 'Tally Sync',                   icon: '📤' },
  { key: 'einvoice',           label: 'eInvoice (IRN Generate/Cancel)', icon: '🔐' },
  { key: 'create_revision',    label: 'Create Revision / Amendment',  icon: '🔀' },
  { key: 'move_to_supplement', label: 'Move to Supplement (USB)',      icon: '🔒' },
];

const DEFAULT_INVOICE_ACTION_PERMS: Record<string, string[]> = {
  admin:              INVOICE_ACTION_ITEMS.map(a => a.key),
  accountant:         ['edit_draft', 'finalize', 'cancel_draft', 'record_payment', 'tally_sync', 'einvoice', 'create_revision'],
  sales_executive:    ['edit_draft', 'finalize'],
  purchase_executive: ['edit_draft', 'finalize'],
  gate_guard:         [],
  store_manager:      [],
  operator:           [],
  viewer:             [],
};


// ── Role definitions for the tabs ─────────────────────────────────────────── //

const ROLE_TABS = [
  { value: 'gate_guard',         label: 'Gate Guard',         color: 'text-rose-600' },
  { value: 'store_manager',      label: 'Store Manager',      color: 'text-emerald-600' },
  { value: 'operator',           label: 'Operator',           color: 'text-blue-600' },
  { value: 'sales_executive',    label: 'Sales Executive',    color: 'text-green-600' },
  { value: 'purchase_executive', label: 'Purchase Executive', color: 'text-orange-600' },
  { value: 'accountant',         label: 'Accountant',         color: 'text-cyan-600' },
  { value: 'viewer',             label: 'Viewer',             color: 'text-gray-500' },
];

// ── Role Permissions Tab Content ──────────────────────────────────────────── //

interface RoleTabProps {
  allowed: string[];
  onChange: (paths: string[]) => void;
  invoiceActions: string[];
  onInvoiceActionsChange: (actions: string[]) => void;
  hubTabPerms: Record<string, string[]>;    // { hubPath → allowedTabValues[] }
  onHubTabPermsChange: (perms: Record<string, string[]>) => void;
}

function RoleTab({ allowed, onChange, invoiceActions, onInvoiceActionsChange, hubTabPerms, onHubTabPermsChange }: RoleTabProps) {
  function toggle(path: string) {
    onChange(allowed.includes(path) ? allowed.filter(p => p !== path) : [...allowed, path]);
  }

  function toggleAction(key: string) {
    onInvoiceActionsChange(
      invoiceActions.includes(key) ? invoiceActions.filter(a => a !== key) : [...invoiceActions, key]
    );
  }

  function toggleTab(hubPath: string, tabValue: string) {
    const current = hubTabPerms[hubPath] ?? [];
    const next = current.includes(tabValue)
      ? current.filter(v => v !== tabValue)
      : [...current, tabValue];
    onHubTabPermsChange({ ...hubTabPerms, [hubPath]: next });
  }

  function isAllTabsChecked(hubPath: string): boolean {
    const tabs = HUB_TABS[hubPath];
    if (!tabs?.length) return true;
    const allowed = hubTabPerms[hubPath] ?? [];
    // Empty = all allowed (no restriction); full set = all explicitly allowed
    return allowed.length === 0 || tabs.every(t => allowed.includes(t.value));
  }

  function toggleAllTabs(hubPath: string) {
    const tabs = HUB_TABS[hubPath];
    if (!tabs?.length) return;
    const allChecked = isAllTabsChecked(hubPath);
    // If all on → set to empty (no restriction = all allowed)
    // If some off → set to all
    onHubTabPermsChange({
      ...hubTabPerms,
      [hubPath]: allChecked ? [] : tabs.map(t => t.value),
    });
  }

  return (
    <div className="space-y-4 py-4">
      <div className="flex items-center gap-2 rounded-md border border-blue-100 bg-blue-50 px-3 py-2 text-xs text-blue-700">
        <Info className="h-3.5 w-3.5 shrink-0" />
        Admin always has full access regardless of this configuration.
      </div>

      {/* ── Page access ── */}
      {PAGE_GROUPS.map(group => (
        <div key={group.group}>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">{group.group}</p>
          <div className="space-y-2">
            {group.pages.map(page => {
              const isChecked = allowed.includes(page.path);
              const tabs = HUB_TABS[page.path] ?? [];
              const allowedTabs = hubTabPerms[page.path] ?? [];
              return (
                <div key={page.path} className="space-y-1">
                  {/* Hub-level checkbox */}
                  <label
                    className={`flex items-start gap-2 rounded-md border px-3 py-2 text-sm cursor-pointer transition-colors ${
                      isChecked
                        ? 'border-primary/30 bg-primary/5'
                        : 'border-transparent bg-muted/40 hover:bg-muted/70'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={isChecked}
                      onChange={() => toggle(page.path)}
                      className="accent-primary mt-0.5 shrink-0"
                    />
                    <div className="min-w-0 flex-1">
                      <div className="font-medium leading-tight">{page.label}</div>
                      {'hint' in page && page.hint && (
                        <div className="text-[11px] text-muted-foreground mt-0.5 leading-tight">{page.hint}</div>
                      )}
                    </div>
                  </label>
                  {/* Tab-level sub-checkboxes — only shown when hub is enabled and has tabs */}
                  {isChecked && tabs.length > 0 && (
                    <div className="ml-6 rounded-md border border-dashed border-border bg-muted/20 px-3 py-2">
                      <div className="flex items-center gap-1.5 mb-2">
                        <Layout className="h-3 w-3 text-muted-foreground" />
                        <span className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Tab access</span>
                        <button
                          type="button"
                          onClick={() => toggleAllTabs(page.path)}
                          className="ml-auto text-[11px] text-primary hover:underline"
                        >
                          {isAllTabsChecked(page.path) ? 'Restrict some tabs' : 'Allow all tabs'}
                        </button>
                      </div>
                      <div className="grid grid-cols-2 sm:grid-cols-3 gap-1">
                        {tabs.map(tab => {
                          const tabChecked = allowedTabs.length === 0 || allowedTabs.includes(tab.value);
                          return (
                            <label key={tab.value} className="flex items-center gap-1.5 text-xs cursor-pointer">
                              <input
                                type="checkbox"
                                checked={tabChecked}
                                onChange={() => {
                                  // If currently "all allowed" (empty), clicking a tab starts a restriction
                                  if (allowedTabs.length === 0) {
                                    // Enable all except this one
                                    const others = tabs.filter(t => t.value !== tab.value).map(t => t.value);
                                    onHubTabPermsChange({ ...hubTabPerms, [page.path]: others });
                                  } else {
                                    toggleTab(page.path, tab.value);
                                  }
                                }}
                                className="accent-primary"
                              />
                              <span className={tabChecked ? '' : 'text-muted-foreground line-through'}>{tab.label}</span>
                            </label>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      ))}

      {/* ── Invoice action permissions ── */}
      <div className="mt-6 pt-4 border-t">
        <div className="flex items-center gap-2 mb-3">
          <FileText className="h-4 w-4 text-blue-500" />
          <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Invoice Actions</p>
        </div>
        <p className="text-xs text-muted-foreground mb-3">
          Control which invoice action buttons this role can use. Print &amp; Download are always available.
        </p>
        <div className="grid grid-cols-2 gap-2">
          {INVOICE_ACTION_ITEMS.map(action => {
            const isChecked = invoiceActions.includes(action.key);
            return (
              <label
                key={action.key}
                className={`flex items-center gap-2 rounded-md border px-3 py-2 text-sm cursor-pointer transition-colors ${
                  isChecked
                    ? 'border-orange-300/60 bg-orange-50'
                    : 'border-transparent bg-muted/40 hover:bg-muted/70'
                }`}
              >
                <input
                  type="checkbox"
                  checked={isChecked}
                  onChange={() => toggleAction(action.key)}
                  className="accent-orange-500"
                />
                <span className="mr-1">{action.icon}</span>
                <span>{action.label}</span>
              </label>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────── //

export default function PermissionsPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [permissions, setPermissions] = useState<Record<string, string[]>>(() => {
    const result: Record<string, string[]> = {};
    ROLE_TABS.forEach(r => { result[r.value] = DEFAULT_PERMISSIONS[r.value] ?? []; });
    return result;
  });
  const [invoicePerms, setInvoicePerms] = useState<Record<string, string[]>>(() => {
    const result: Record<string, string[]> = {};
    ROLE_TABS.forEach(r => { result[r.value] = DEFAULT_INVOICE_ACTION_PERMS[r.value] ?? []; });
    return result;
  });
  const [roleTabPerms, setRoleTabPerms] = useState<RoleTabPermissions>({});
  const [saving, setSaving] = useState(false);
  const [activeTab, setActiveTab] = useState(ROLE_TABS[0].value);

  // Guard
  useEffect(() => {
    if (user && user.role !== 'admin') navigate('/', { replace: true });
  }, [user, navigate]);

  // Fetch current permissions — each call is independent so one 404 doesn't block the other
  const fetchPerms = useCallback(async () => {
    try {
      const pageRes = await api.get<Record<string, string[]>>('/api/v1/app-settings/role-permissions');
      setPermissions(prev => {
        const updated = { ...prev };
        ROLE_TABS.forEach(r => {
          if (pageRes.data[r.value]) updated[r.value] = pageRes.data[r.value];
        });
        return updated;
      });
    } catch {
      // Network error — fall back to defaults already initialised
    }
    try {
      const actionRes = await api.get<Record<string, string[]>>('/api/v1/app-settings/invoice-action-permissions');
      setInvoicePerms(prev => {
        const updated = { ...prev };
        ROLE_TABS.forEach(r => {
          if (actionRes.data[r.value]) updated[r.value] = actionRes.data[r.value];
        });
        return updated;
      });
    } catch {
      // Endpoint may not exist yet — use defaults (non-fatal)
    }
    try {
      const tabRes = await api.get<RoleTabPermissions>('/api/v1/app-settings/role-tab-permissions');
      setRoleTabPerms(tabRes.data ?? {});
    } catch {
      // Non-fatal — no restrictions configured yet
    }
  }, []);

  useEffect(() => { fetchPerms(); }, [fetchPerms]);

  if (!user || user.role !== 'admin') return null;

  function setRolePerms(role: string, paths: string[]) {
    setPermissions(prev => ({ ...prev, [role]: paths }));
  }

  function setRoleInvoicePerms(role: string, actions: string[]) {
    setInvoicePerms(prev => ({ ...prev, [role]: actions }));
  }

  function setRoleHubTabPerms(role: string, perms: Record<string, string[]>) {
    setRoleTabPerms(prev => ({ ...prev, [role]: perms }));
  }

  function resetToDefault(role: string) {
    setPermissions(prev => ({ ...prev, [role]: DEFAULT_PERMISSIONS[role] ?? [] }));
    setInvoicePerms(prev => ({ ...prev, [role]: DEFAULT_INVOICE_ACTION_PERMS[role] ?? [] }));
    setRoleTabPerms(prev => { const next = { ...prev }; delete next[role]; return next; });
    toast.info(`Reset ${ROLE_TABS.find(r => r.value === role)?.label} to defaults`);
  }

  async function save() {
    setSaving(true);
    try {
      // Page permissions — the critical save
      await api.put('/api/v1/app-settings/role-permissions', { admin: ['*'], ...permissions });

      // Invoice action permissions — best-effort (endpoint may not exist on all deploys)
      try {
        await api.put('/api/v1/app-settings/invoice-action-permissions', {
          admin: INVOICE_ACTION_ITEMS.map(a => a.key),
          ...invoicePerms,
        });
      } catch {
        // Non-fatal — page permissions already saved above
      }

      // Tab permissions — best-effort
      try {
        await api.put('/api/v1/app-settings/role-tab-permissions', roleTabPerms);
      } catch {
        // Non-fatal
      }

      window.dispatchEvent(new CustomEvent('appsettings:updated'));
      toast.success(t('permissions.saved'));
    } catch {
      toast.error(t('permissions.saveFailed'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{t('permissions.title')}</h1>
          <p className="text-sm text-muted-foreground">{t('permissions.subtitle')}</p>
        </div>
        <Button onClick={save} disabled={saving}>
          <Save className="h-4 w-4 mr-1" />
          {saving ? t('permissions.saving') : t('permissions.savePermissions')}
        </Button>
      </div>

      <div className="rounded-lg border bg-card p-4">
        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList className="flex-wrap h-auto mb-4">
            {ROLE_TABS.map(r => (
              <TabsTrigger key={r.value} value={r.value} className={`data-[state=active]:${r.color}`}>
                {r.label}
              </TabsTrigger>
            ))}
          </TabsList>

          {ROLE_TABS.map(r => (
            <TabsContent key={r.value} value={r.value}>
              <div className="flex justify-end mb-2">
                <Button
                  variant="ghost" size="sm"
                  onClick={() => resetToDefault(r.value)}
                >
                  <RotateCcw className="h-3.5 w-3.5 mr-1" />
                  {t('permissions.resetDefaults')}
                </Button>
              </div>
              <RoleTab
                allowed={permissions[r.value] ?? []}
                onChange={paths => setRolePerms(r.value, paths)}
                invoiceActions={invoicePerms[r.value] ?? []}
                onInvoiceActionsChange={actions => setRoleInvoicePerms(r.value, actions)}
                hubTabPerms={roleTabPerms[r.value] ?? {}}
                onHubTabPermsChange={perms => setRoleHubTabPerms(r.value, perms)}
              />
            </TabsContent>
          ))}
        </Tabs>
      </div>
    </div>
  );
}
