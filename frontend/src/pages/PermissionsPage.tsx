import { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { Save, RotateCcw, Info, FileText } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { useAuth } from '@/hooks/useAuth';
import { DEFAULT_PERMISSIONS } from '@/hooks/useAppSettings';
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
        hint: 'Finished Goods · Store Inventory · Products Catalog · Customer Rates',
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
}

function RoleTab({ allowed, onChange, invoiceActions, onInvoiceActionsChange }: RoleTabProps) {
  function toggle(path: string) {
    onChange(allowed.includes(path) ? allowed.filter(p => p !== path) : [...allowed, path]);
  }

  function toggleAction(key: string) {
    onInvoiceActionsChange(
      invoiceActions.includes(key) ? invoiceActions.filter(a => a !== key) : [...invoiceActions, key]
    );
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
          <div className="grid grid-cols-2 gap-2">
            {group.pages.map(page => {
              const isChecked = allowed.includes(page.path);
              return (
                <label
                  key={page.path}
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
                  <div className="min-w-0">
                    <div className="font-medium leading-tight">{page.label}</div>
                    {'hint' in page && page.hint && (
                      <div className="text-[11px] text-muted-foreground mt-0.5 leading-tight">{page.hint}</div>
                    )}
                  </div>
                </label>
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
  }, []);

  useEffect(() => { fetchPerms(); }, [fetchPerms]);

  if (!user || user.role !== 'admin') return null;

  function setRolePerms(role: string, paths: string[]) {
    setPermissions(prev => ({ ...prev, [role]: paths }));
  }

  function setRoleInvoicePerms(role: string, actions: string[]) {
    setInvoicePerms(prev => ({ ...prev, [role]: actions }));
  }

  function resetToDefault(role: string) {
    setPermissions(prev => ({ ...prev, [role]: DEFAULT_PERMISSIONS[role] ?? [] }));
    setInvoicePerms(prev => ({ ...prev, [role]: DEFAULT_INVOICE_ACTION_PERMS[role] ?? [] }));
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

      window.dispatchEvent(new CustomEvent('appsettings:updated'));
      toast.success('Role permissions saved');
    } catch {
      toast.error('Failed to save permissions');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Role Permissions</h1>
          <p className="text-sm text-muted-foreground">Configure page access and invoice actions per role</p>
        </div>
        <Button onClick={save} disabled={saving}>
          <Save className="h-4 w-4 mr-1" />
          {saving ? 'Saving…' : 'Save All Changes'}
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
                  Reset to Default
                </Button>
              </div>
              <RoleTab
                allowed={permissions[r.value] ?? []}
                onChange={paths => setRolePerms(r.value, paths)}
                invoiceActions={invoicePerms[r.value] ?? []}
                onInvoiceActionsChange={actions => setRoleInvoicePerms(r.value, actions)}
              />
            </TabsContent>
          ))}
        </Tabs>
      </div>
    </div>
  );
}
