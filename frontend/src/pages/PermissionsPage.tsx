import { useEffect, useState, useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { Save, RotateCcw, Info, FileText, Layout, Plus, Pencil, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { useAuth } from '@/hooks/useAuth';
import { DEFAULT_PERMISSIONS } from '@/hooks/useAppSettings';
import type { RoleTabPermissions } from '@/contexts/PermissionsContext';
import { CATALOGUE_GROUPS, HUB_TABS, BUILTIN_ROLES, BUILTIN_ROLE_VALUES, ADMIN_ROLE_DEF, type RoleDef } from '@/lib/rbac';
import api from '@/services/api';

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
    const allowedT = hubTabPerms[hubPath] ?? [];
    return allowedT.length === 0 || tabs.every(t => allowedT.includes(t.value));
  }

  function toggleAllTabs(hubPath: string) {
    const tabs = HUB_TABS[hubPath];
    if (!tabs?.length) return;
    const allChecked = isAllTabsChecked(hubPath);
    onHubTabPermsChange({
      ...hubTabPerms,
      [hubPath]: allChecked ? [] : tabs.map(t => t.value),
    });
  }

  return (
    <div className="space-y-4 py-4">
      <div className="flex items-center gap-2 rounded-md border border-blue-100 bg-blue-50 px-3 py-2 text-xs text-blue-700">
        <Info className="h-3.5 w-3.5 shrink-0" />
        Admin always has full access. System-config pages (Settings, Users, Backup, Import, Branches) remain admin-only.
      </div>

      {/* ── Page access ── */}
      {CATALOGUE_GROUPS.map(group => (
        <div key={group.group}>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">{group.group}</p>
          <div className="space-y-2">
            {group.pages.map(page => {
              const isChecked = page.path === '/' ? true : allowed.includes(page.path);
              const tabs = HUB_TABS[page.path] ?? [];
              const allowedTabs = hubTabPerms[page.path] ?? [];
              const isDashboard = page.path === '/';
              return (
                <div key={page.path} className="space-y-1">
                  {/* Hub-level checkbox */}
                  <label
                    className={`flex items-start gap-2 rounded-md border px-3 py-2 text-sm transition-colors ${
                      isDashboard ? 'cursor-default opacity-70' : 'cursor-pointer'
                    } ${
                      isChecked
                        ? 'border-primary/30 bg-primary/5'
                        : 'border-transparent bg-muted/40 hover:bg-muted/70'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={isChecked}
                      disabled={isDashboard}
                      onChange={() => !isDashboard && toggle(page.path)}
                      className="accent-primary mt-0.5 shrink-0"
                    />
                    <div className="min-w-0 flex-1">
                      <div className="font-medium leading-tight">{page.label}</div>
                      {page.hint && (
                        <div className="text-[11px] text-muted-foreground mt-0.5 leading-tight">{page.hint}</div>
                      )}
                    </div>
                  </label>
                  {/* Tab-level sub-checkboxes — only when hub is enabled and has tabs */}
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
                                  if (allowedTabs.length === 0) {
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

const CUSTOM_ROLE_COLOR = 'text-violet-600';

export default function PermissionsPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const navigate = useNavigate();

  const [customRoles, setCustomRoles] = useState<RoleDef[]>([]);
  const [permissions, setPermissions] = useState<Record<string, string[]>>({});
  const [invoicePerms, setInvoicePerms] = useState<Record<string, string[]>>({});
  const [roleTabPerms, setRoleTabPerms] = useState<RoleTabPermissions>({});
  const [saving, setSaving] = useState(false);
  const [activeTab, setActiveTab] = useState<string>(BUILTIN_ROLES[0].value);

  // Create / rename role dialog
  const [roleDialog, setRoleDialog] = useState<{ mode: 'create' | 'rename'; value?: string } | null>(null);
  const [roleName, setRoleName] = useState('');

  // Admin first: an owner may want to hide pages they never use from their OWN
  // sidebar. Administration pages stay reachable regardless (see canAccessRoute),
  // so narrowing this can always be undone.
  const roles: RoleDef[] = [ADMIN_ROLE_DEF, ...BUILTIN_ROLES, ...customRoles];

  // Guard
  useEffect(() => {
    if (user && user.role !== 'admin') navigate('/', { replace: true });
  }, [user, navigate]);

  // Fetch everything — each call independent so one 404 doesn't block the rest
  const fetchPerms = useCallback(async () => {
    try {
      const rolesRes = await api.get<RoleDef[]>('/api/v1/app-settings/custom-roles');
      setCustomRoles(Array.isArray(rolesRes.data) ? rolesRes.data : []);
    } catch { /* none yet */ }
    try {
      const pageRes = await api.get<Record<string, string[]>>('/api/v1/app-settings/role-permissions');
      setPermissions(pageRes.data ?? {});
    } catch { /* defaults */ }
    try {
      const actionRes = await api.get<Record<string, string[]>>('/api/v1/app-settings/invoice-action-permissions');
      setInvoicePerms(actionRes.data ?? {});
    } catch { /* defaults */ }
    try {
      const tabRes = await api.get<RoleTabPermissions>('/api/v1/app-settings/role-tab-permissions');
      setRoleTabPerms(tabRes.data ?? {});
    } catch { /* none */ }
  }, []);

  useEffect(() => { fetchPerms(); }, [fetchPerms]);

  if (!user || user.role !== 'admin') return null;

  // Resolve the effective permission list for a role (stored value → default → [])
  // Every grantable page, used to render the admin tab as "all ticked" when the
  // admin is unrestricted ('*' matches no page path, so it would otherwise look
  // like the owner has no access at all).
  const ALL_PAGE_PATHS = useMemo(
    () => CATALOGUE_GROUPS.flatMap(g => g.pages.map(pg => pg.path)), []);

  const permsFor = (role: string) => {
    const stored = permissions[role];
    if (role === 'admin') {
      // Unrestricted (absent or '*') shows everything ticked; unticking then
      // narrows the owner's own view.
      if (!stored || stored.includes('*')) return ALL_PAGE_PATHS;
      return stored;
    }
    return stored ?? DEFAULT_PERMISSIONS[role] ?? [];
  };
  const invoiceFor = (role: string) => invoicePerms[role] ?? DEFAULT_INVOICE_ACTION_PERMS[role] ?? [];

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
    toast.info(`Reset ${roles.find(r => r.value === role)?.label} to defaults`);
  }

  // ── Custom role CRUD ──
  function openCreate() { setRoleName(''); setRoleDialog({ mode: 'create' }); }
  function openRename(value: string) {
    setRoleName(customRoles.find(r => r.value === value)?.label ?? '');
    setRoleDialog({ mode: 'rename', value });
  }

  function submitRoleDialog() {
    const label = roleName.trim();
    if (!label) { toast.error('Enter a role name'); return; }
    if (roleDialog?.mode === 'rename' && roleDialog.value) {
      setCustomRoles(prev => prev.map(r => r.value === roleDialog.value ? { ...r, label } : r));
      setRoleDialog(null);
      return;
    }
    // Create — slugify + uniqueness
    const value = label.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
    if (!value) { toast.error('Invalid role name'); return; }
    if (BUILTIN_ROLE_VALUES.has(value) || customRoles.some(r => r.value === value)) {
      toast.error('A role with that name already exists'); return;
    }
    const def: RoleDef = { value, label, color: CUSTOM_ROLE_COLOR };
    setCustomRoles(prev => [...prev, def]);
    setPermissions(prev => ({ ...prev, [value]: [] }));
    setInvoicePerms(prev => ({ ...prev, [value]: [] }));
    setActiveTab(value);
    setRoleDialog(null);
    toast.success(`Role "${label}" added — set its access, then Save`);
  }

  function deleteRole(value: string) {
    if (!confirm(`Delete the custom role "${customRoles.find(r => r.value === value)?.label}"? Users still assigned to it will lose access until reassigned.`)) return;
    setCustomRoles(prev => prev.filter(r => r.value !== value));
    setPermissions(prev => { const n = { ...prev }; delete n[value]; return n; });
    setInvoicePerms(prev => { const n = { ...prev }; delete n[value]; return n; });
    setRoleTabPerms(prev => { const n = { ...prev }; delete n[value]; return n; });
    if (activeTab === value) setActiveTab(BUILTIN_ROLES[0].value);
  }

  async function save() {
    setSaving(true);
    try {
      // Persist custom roles first so their label/value survive a reload
      try {
        const saved = await api.put<RoleDef[]>('/api/v1/app-settings/custom-roles', customRoles);
        if (Array.isArray(saved.data)) setCustomRoles(saved.data);
      } catch { /* non-fatal */ }

      // Page permissions — the critical save. Only send roles we know about so a
      // deleted role's stale entry doesn't linger.
      const validRoles = new Set(roles.map(r => r.value));
      const pagePayload: Record<string, string[]> = {};
      for (const r of roles) {
        const picked = permsFor(r.value);
        // Store '*' (not an exhaustive list) when the admin has everything ticked.
        // An exhaustive list would freeze today's page set, so a page added in a
        // later release would silently be missing for the owner.
        pagePayload[r.value] =
          r.value === 'admin' && picked.length === ALL_PAGE_PATHS.length ? ['*'] : picked;
      }
      await api.put('/api/v1/app-settings/role-permissions', pagePayload);

      try {
        const actionPayload: Record<string, string[]> = { admin: INVOICE_ACTION_ITEMS.map(a => a.key) };
        for (const r of roles) actionPayload[r.value] = invoiceFor(r.value);
        await api.put('/api/v1/app-settings/invoice-action-permissions', actionPayload);
      } catch { /* non-fatal */ }

      try {
        // Drop tab perms for roles that no longer exist
        const tabPayload: RoleTabPermissions = {};
        for (const [role, v] of Object.entries(roleTabPerms)) {
          if (validRoles.has(role)) tabPayload[role] = v;
        }
        await api.put('/api/v1/app-settings/role-tab-permissions', tabPayload);
      } catch { /* non-fatal */ }

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
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{t('permissions.title')}</h1>
          <p className="text-sm text-muted-foreground">{t('permissions.subtitle')}</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={openCreate}>
            <Plus className="h-4 w-4 mr-1" /> New Role
          </Button>
          <Button onClick={save} disabled={saving}>
            <Save className="h-4 w-4 mr-1" />
            {saving ? t('permissions.saving') : t('permissions.savePermissions')}
          </Button>
        </div>
      </div>

      <div className="rounded-lg border bg-card p-4">
        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList className="flex-wrap h-auto mb-4">
            {roles.map(r => (
              <TabsTrigger key={r.value} value={r.value} className={r.color}>
                {r.label}
                {!BUILTIN_ROLE_VALUES.has(r.value) && (
                  <span className="ml-1.5 rounded bg-violet-100 px-1 py-0.5 text-[9px] font-semibold uppercase text-violet-700">custom</span>
                )}
              </TabsTrigger>
            ))}
          </TabsList>

          {roles.map(r => {
            const isCustom = !BUILTIN_ROLE_VALUES.has(r.value);
            return (
              <TabsContent key={r.value} value={r.value}>
                <div className="flex items-center justify-end gap-1 mb-2">
                  {isCustom && (
                    <>
                      <Button variant="ghost" size="sm" onClick={() => openRename(r.value)}>
                        <Pencil className="h-3.5 w-3.5 mr-1" /> Rename
                      </Button>
                      <Button variant="ghost" size="sm" className="text-destructive hover:text-destructive" onClick={() => deleteRole(r.value)}>
                        <Trash2 className="h-3.5 w-3.5 mr-1" /> Delete
                      </Button>
                    </>
                  )}
                  <Button variant="ghost" size="sm" onClick={() => resetToDefault(r.value)}>
                    <RotateCcw className="h-3.5 w-3.5 mr-1" />
                    {t('permissions.resetDefaults')}
                  </Button>
                </div>
                <RoleTab
                  allowed={permsFor(r.value)}
                  onChange={paths => setRolePerms(r.value, paths)}
                  invoiceActions={invoiceFor(r.value)}
                  onInvoiceActionsChange={actions => setRoleInvoicePerms(r.value, actions)}
                  hubTabPerms={roleTabPerms[r.value] ?? {}}
                  onHubTabPermsChange={perms => setRoleHubTabPerms(r.value, perms)}
                />
              </TabsContent>
            );
          })}
        </Tabs>
      </div>

      {/* Create / rename role dialog */}
      <Dialog open={!!roleDialog} onOpenChange={v => !v && setRoleDialog(null)}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>{roleDialog?.mode === 'rename' ? 'Rename role' : 'New custom role'}</DialogTitle>
          </DialogHeader>
          <div className="space-y-2">
            <Label>Role name</Label>
            <Input
              autoFocus
              value={roleName}
              onChange={e => setRoleName(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') submitRoleDialog(); }}
              placeholder="e.g. Shift Supervisor"
            />
            {roleDialog?.mode === 'create' && (
              <p className="text-xs text-muted-foreground">
                A new role starts with no access. Tick the pages it should see, then Save.
              </p>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRoleDialog(null)}>Cancel</Button>
            <Button onClick={submitRoleDialog}>{roleDialog?.mode === 'rename' ? 'Rename' : 'Add role'}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
