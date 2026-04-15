import { useState, useEffect, useCallback } from 'react';
import { toast } from 'sonner';
import {
  Building2, Plus, Search, Shield, UserPlus, UserMinus,
  AlertTriangle, CheckCircle, PauseCircle, Calendar, ExternalLink,
  LogOut, Pencil, Loader2, Users, BarChart3, Power, Ban,
  TrendingUp, UserCheck, Eye, EyeOff, KeyRound, Copy, Check,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import platformApi from '@/services/platformApi';
import { usePlatformAuth } from '@/hooks/usePlatformAuth';
import type { TenantOverview, PlatformUser } from '@/types';

// ── Helpers ──────────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  if (status === 'active') return <Badge className="bg-green-100 text-green-700 hover:bg-green-100">Active</Badge>;
  if (status === 'readonly') return <Badge className="bg-amber-100 text-amber-700 hover:bg-amber-100">Read-Only</Badge>;
  if (status === 'suspended') return <Badge className="bg-red-100 text-red-700 hover:bg-red-100">Suspended</Badge>;
  return <Badge variant="secondary">{status}</Badge>;
}

function RoleBadge({ role }: { role: string }) {
  if (role === 'platform_admin') return <Badge className="bg-purple-100 text-purple-700 hover:bg-purple-100">Admin</Badge>;
  if (role === 'sales_rep') return <Badge className="bg-blue-100 text-blue-700 hover:bg-blue-100">Sales</Badge>;
  if (role === 'marketing') return <Badge className="bg-pink-100 text-pink-700 hover:bg-pink-100">Marketing</Badge>;
  if (role === 'cto') return <Badge className="bg-indigo-100 text-indigo-700 hover:bg-indigo-100">CTO</Badge>;
  if (role === 'support') return <Badge className="bg-teal-100 text-teal-700 hover:bg-teal-100">Support</Badge>;
  return <Badge variant="secondary">{role}</Badge>;
}

function AgentKeyCell({ agentKey }: { agentKey: string }) {
  const [copied, setCopied] = useState(false);
  if (!agentKey) return <span className="text-xs text-slate-600">—</span>;
  const short = agentKey.slice(0, 8) + '...';
  function handleCopy() {
    navigator.clipboard.writeText(agentKey);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }
  return (
    <div className="flex items-center gap-1">
      <code className="text-[10px] text-slate-400 font-mono">{short}</code>
      <button onClick={handleCopy} className="text-slate-500 hover:text-blue-400 transition-colors" title={`Copy: ${agentKey}`}>
        {copied ? <Check className="h-3 w-3 text-green-400" /> : <Copy className="h-3 w-3" />}
      </button>
    </div>
  );
}

function fmtDate(iso: string | null) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
}

// ── Onboard Dialog ───────────────────────────────────────────────────────────

function OnboardDialog({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: () => void }) {
  const [slug, setSlug] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [companyName, setCompanyName] = useState('');
  const [adminUser, setAdminUser] = useState('admin');
  const [adminPass, setAdminPass] = useState('');
  const [amcStart, setAmcStart] = useState(new Date().toISOString().split('T')[0]);
  const [amcExpiry, setAmcExpiry] = useState('');
  const [saving, setSaving] = useState(false);

  function autoSlug(name: string) {
    return name.toLowerCase().replace(/[^a-z0-9]/g, '-').replace(/-+/g, '-').replace(/^-|-$/g, '').slice(0, 30);
  }

  async function handleCreate() {
    if (!slug || !displayName || !adminPass || !companyName) {
      toast.error('Fill all required fields');
      return;
    }
    setSaving(true);
    try {
      await platformApi.post('/api/v1/platform/tenants', {
        slug, display_name: displayName, company_name: companyName,
        admin_username: adminUser, admin_password: adminPass,
        amc_start_date: amcStart || null, amc_expiry_date: amcExpiry || null,
      });
      toast.success(`Tenant "${displayName}" created successfully`);
      onCreated(); onClose();
      setSlug(''); setDisplayName(''); setCompanyName(''); setAdminPass(''); setAmcExpiry('');
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || 'Failed to create tenant');
    } finally { setSaving(false); }
  }

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="max-w-lg">
        <DialogHeader><DialogTitle className="flex items-center gap-2"><Plus className="h-5 w-5 text-blue-500" />Onboard New Company</DialogTitle></DialogHeader>
        <div className="space-y-3 py-2">
          <div className="grid grid-cols-2 gap-3">
            <div><Label>Company Name *</Label><Input value={companyName} onChange={e => { setCompanyName(e.target.value); if (!slug || slug === autoSlug(displayName)) { setSlug(autoSlug(e.target.value)); setDisplayName(e.target.value); } }} placeholder="Ziya Ore Minerals Pvt Ltd" /></div>
            <div><Label>Display Name *</Label><Input value={displayName} onChange={e => { setDisplayName(e.target.value); setSlug(autoSlug(e.target.value)); }} placeholder="Ziya Ore Minerals" /></div>
          </div>
          <div><Label>Slug (URL identifier) *</Label><Input value={slug} onChange={e => setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ''))} placeholder="ziya-ore-minerals" className="font-mono text-sm" /><p className="text-[10px] text-muted-foreground mt-0.5">URL: {slug || '...'}.weighbridgesetu.com</p></div>
          <div className="grid grid-cols-2 gap-3">
            <div><Label>Admin Username</Label><Input value={adminUser} onChange={e => setAdminUser(e.target.value)} /></div>
            <div><Label>Admin Password *</Label><Input type="password" value={adminPass} onChange={e => setAdminPass(e.target.value)} placeholder="Strong password" /></div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div><Label>AMC Start Date</Label><Input type="date" value={amcStart} onChange={e => setAmcStart(e.target.value)} /></div>
            <div><Label>AMC Expiry Date</Label><Input type="date" value={amcExpiry} onChange={e => setAmcExpiry(e.target.value)} /></div>
          </div>
        </div>
        <DialogFooter><Button variant="outline" onClick={onClose}>Cancel</Button><Button onClick={handleCreate} disabled={saving}>{saving && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}Create Tenant</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Edit Tenant Dialog ───────────────────────────────────────────────────────

function EditTenantDialog({ tenant, open, onClose, onSaved }: {
  tenant: TenantOverview | null; open: boolean; onClose: () => void; onSaved: () => void;
}) {
  const [status, setStatus] = useState('active');
  const [displayName, setDisplayName] = useState('');
  const [amcStart, setAmcStart] = useState('');
  const [amcExpiry, setAmcExpiry] = useState('');
  const [contactEmail, setContactEmail] = useState('');
  const [contactPhone, setContactPhone] = useState('');
  const [saving, setSaving] = useState(false);
  const [modules, setModules] = useState<Record<string, boolean>>({});
  const [modulesLoading, setModulesLoading] = useState(false);

  useEffect(() => {
    if (tenant) {
      setStatus(tenant.status); setDisplayName(tenant.display_name);
      setAmcStart(tenant.amc_start_date || ''); setAmcExpiry(tenant.amc_expiry_date || '');
      setContactEmail(tenant.contact_email || ''); setContactPhone(tenant.contact_phone || '');
      // Load modules
      setModulesLoading(true);
      platformApi.get(`/api/v1/platform/tenants/${tenant.slug}/modules`)
        .then(r => setModules(r.data.modules))
        .catch(() => {})
        .finally(() => setModulesLoading(false));
    }
  }, [tenant]);

  async function handleSave() {
    setSaving(true);
    try {
      await platformApi.put(`/api/v1/platform/tenants/${tenant!.slug}`, {
        display_name: displayName, status, amc_start_date: amcStart || null,
        amc_expiry_date: amcExpiry || null, contact_email: contactEmail || null, contact_phone: contactPhone || null,
      });
      // Save modules separately
      await platformApi.put(`/api/v1/platform/tenants/${tenant!.slug}/modules`, modules);
      toast.success('Tenant updated'); onSaved(); onClose();
    } catch (err: any) { toast.error(err?.response?.data?.detail || 'Update failed'); }
    finally { setSaving(false); }
  }

  const MODULE_META: { key: string; label: string; description: string }[] = [
    { key: 'weighing',      label: 'Weighing & Tokens',   description: 'Token creation, weighment, camera, snapshot search' },
    { key: 'invoicing',     label: 'Invoicing',           description: 'Sales & purchase invoices with GST' },
    { key: 'quotations',    label: 'Quotations',          description: 'Create and convert quotations to invoices' },
    { key: 'payments',      label: 'Payments & Ledger',   description: 'Payment receipts, vouchers, party ledger' },
    { key: 'gst_reports',   label: 'GST Reports',         description: 'GSTR-1, GSTR-3B, HSN summary, JSON export' },
    { key: 'reports',       label: 'Reports & Analytics', description: 'Sales register, weight register, P&L, stock summary' },
    { key: 'inventory',     label: 'Store Inventory',     description: 'Stock items, purchase orders, daily reports' },
    { key: 'compliance',    label: 'Compliance Tracker',  description: 'Insurance, licenses, permits with expiry alerts' },
    { key: 'notifications', label: 'Notifications',       description: 'Email, SMS, WhatsApp, Telegram alerts' },
    { key: 'tally_sync',    label: 'Tally Integration',   description: 'Push invoices and masters to Tally Prime' },
    { key: 'einvoice',      label: 'eInvoice (IRN)',      description: 'NIC eInvoice generation for B2B invoices' },
    { key: 'data_import',   label: 'Data Import',         description: 'Bulk import parties, products, vehicles from Excel' },
  ];

  if (!tenant) return null;
  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="max-w-lg">
        <DialogHeader><DialogTitle>Edit: {tenant.display_name}</DialogTitle></DialogHeader>
        <div className="space-y-3 py-2">
          <div><Label>Display Name</Label><Input value={displayName} onChange={e => setDisplayName(e.target.value)} /></div>
          <div><Label>Status</Label>
            <Select value={status} onValueChange={v => setStatus(v ?? 'active')}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="active">Active</SelectItem>
                <SelectItem value="readonly">Read-Only (AMC Expired)</SelectItem>
                <SelectItem value="suspended">Suspended</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div><Label>AMC Start</Label><Input type="date" value={amcStart} onChange={e => setAmcStart(e.target.value)} /></div>
            <div><Label>AMC Expiry</Label><Input type="date" value={amcExpiry} onChange={e => setAmcExpiry(e.target.value)} /></div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div><Label>Contact Email</Label><Input value={contactEmail} onChange={e => setContactEmail(e.target.value)} /></div>
            <div><Label>Contact Phone</Label><Input value={contactPhone} onChange={e => setContactPhone(e.target.value)} /></div>
          </div>

          {/* ── Module Toggles ── */}
          <div className="pt-2 border-t">
            <div className="flex items-center justify-between mb-2">
              <Label className="text-sm font-semibold">Feature Modules</Label>
              <span className="text-[11px] text-muted-foreground">
                {Object.values(modules).filter(Boolean).length}/{MODULE_META.length} enabled
              </span>
            </div>
            {modulesLoading ? (
              <div className="flex items-center gap-2 py-4 justify-center text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />Loading modules...</div>
            ) : (
              <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 max-h-[240px] overflow-y-auto">
                {MODULE_META.map(m => (
                  <label key={m.key} className="flex items-start gap-2 cursor-pointer group py-1 px-1.5 rounded hover:bg-muted/50">
                    <input
                      type="checkbox"
                      checked={modules[m.key] ?? false}
                      onChange={e => setModules(prev => ({ ...prev, [m.key]: e.target.checked }))}
                      className="mt-0.5 h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary shrink-0"
                    />
                    <div className="min-w-0">
                      <p className="text-xs font-medium leading-tight">{m.label}</p>
                      <p className="text-[10px] text-muted-foreground leading-tight">{m.description}</p>
                    </div>
                  </label>
                ))}
              </div>
            )}
          </div>
        </div>
        <DialogFooter><Button variant="outline" onClick={onClose}>Cancel</Button><Button onClick={handleSave} disabled={saving}>{saving && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}Save Changes</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Internal User Dialog ─────────────────────────────────────────────────────

function UserDialog({ open, onClose, onSaved, editUser }: {
  open: boolean; onClose: () => void; onSaved: () => void; editUser: PlatformUser | null;
}) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [role, setRole] = useState('sales_rep');
  const [saving, setSaving] = useState(false);
  const [showPass, setShowPass] = useState(false);
  const isEdit = !!editUser;

  useEffect(() => {
    if (editUser) {
      setUsername(editUser.username); setFullName(editUser.full_name || '');
      setEmail(editUser.email || ''); setPhone(editUser.phone || '');
      setRole(editUser.role); setPassword('');
    } else {
      setUsername(''); setFullName(''); setEmail(''); setPhone(''); setRole('sales_rep'); setPassword('');
    }
  }, [editUser, open]);

  async function handleSave() {
    if (!isEdit && (!username || !password)) { toast.error('Username and password required'); return; }
    setSaving(true);
    try {
      if (isEdit) {
        await platformApi.put(`/api/v1/platform/users/${editUser!.id}`, {
          full_name: fullName || null, email: email || null, phone: phone || null, role,
        });
        toast.success('User updated');
      } else {
        await platformApi.post('/api/v1/platform/users', {
          username, password, full_name: fullName || null, email: email || null, phone: phone || null, role,
        });
        toast.success('User created');
      }
      onSaved(); onClose();
    } catch (err: any) { toast.error(err?.response?.data?.detail || 'Failed'); }
    finally { setSaving(false); }
  }

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="max-w-md">
        <DialogHeader><DialogTitle>{isEdit ? `Edit: ${editUser?.full_name || editUser?.username}` : 'Create Internal User'}</DialogTitle></DialogHeader>
        <div className="space-y-3 py-2">
          <div><Label>Username {!isEdit && '*'}</Label><Input value={username} onChange={e => setUsername(e.target.value)} disabled={isEdit} placeholder="ankush.sharma" /></div>
          {!isEdit && (
            <div><Label>Password *</Label>
              <div className="relative">
                <Input type={showPass ? 'text' : 'password'} value={password} onChange={e => setPassword(e.target.value)} placeholder="Strong password" className="pr-10" />
                <button type="button" onClick={() => setShowPass(v => !v)} className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground">
                  {showPass ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>
          )}
          <div><Label>Full Name</Label><Input value={fullName} onChange={e => setFullName(e.target.value)} placeholder="Ankush Sharma" /></div>
          <div className="grid grid-cols-2 gap-3">
            <div><Label>Email</Label><Input value={email} onChange={e => setEmail(e.target.value)} placeholder="ankush@manhotra.com" /></div>
            <div><Label>Phone</Label><Input value={phone} onChange={e => setPhone(e.target.value)} placeholder="+91-98765-43210" /></div>
          </div>
          <div><Label>Role</Label>
            <Select value={role} onValueChange={v => setRole(v ?? 'sales_rep')}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="platform_admin">Platform Admin</SelectItem>
                <SelectItem value="sales_rep">Sales Representative</SelectItem>
                <SelectItem value="marketing">Marketing</SelectItem>
                <SelectItem value="cto">CTO / Technical</SelectItem>
                <SelectItem value="support">Support</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
        <DialogFooter><Button variant="outline" onClick={onClose}>Cancel</Button><Button onClick={handleSave} disabled={saving}>{saving && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}{isEdit ? 'Update' : 'Create User'}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Reset Password Dialog ────────────────────────────────────────────────────

function ResetPasswordDialog({ user, open, onClose }: { user: PlatformUser | null; open: boolean; onClose: () => void }) {
  const [pw, setPw] = useState('');
  const [saving, setSaving] = useState(false);

  async function handleReset() {
    if (!pw || pw.length < 6) { toast.error('Password must be at least 6 characters'); return; }
    setSaving(true);
    try {
      await platformApi.put(`/api/v1/platform/users/${user!.id}/reset-password`, { new_password: pw });
      toast.success('Password reset'); setPw(''); onClose();
    } catch (err: any) { toast.error(err?.response?.data?.detail || 'Failed'); }
    finally { setSaving(false); }
  }

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="max-w-sm">
        <DialogHeader><DialogTitle>Reset Password: {user?.username}</DialogTitle></DialogHeader>
        <div className="py-2"><Label>New Password</Label><Input type="password" value={pw} onChange={e => setPw(e.target.value)} placeholder="New password (min 6 chars)" /></div>
        <DialogFooter><Button variant="outline" onClick={onClose}>Cancel</Button><Button onClick={handleReset} disabled={saving}>{saving && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}Reset</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// MAIN PAGE
// ════════════════════════════════════════════════════════════════════════════

export default function PlatformDashboard() {
  const { user, isPlatformAdmin, logout } = usePlatformAuth();
  const [tenants, setTenants] = useState<TenantOverview[]>([]);
  const [allUsers, setAllUsers] = useState<PlatformUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [activeTab, setActiveTab] = useState('tenants');

  // Dialogs
  const [onboardOpen, setOnboardOpen] = useState(false);
  const [editTenant, setEditTenant] = useState<TenantOverview | null>(null);
  const [userDialogOpen, setUserDialogOpen] = useState(false);
  const [editingUser, setEditingUser] = useState<PlatformUser | null>(null);
  const [resetPwUser, setResetPwUser] = useState<PlatformUser | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const endpoint = isPlatformAdmin ? '/api/v1/platform/tenants' : '/api/v1/platform/my-tenants';
      const { data } = await platformApi.get(endpoint);
      setTenants(data.tenants);
      if (isPlatformAdmin) {
        const { data: users } = await platformApi.get<PlatformUser[]>('/api/v1/platform/users');
        setAllUsers(users);
      }
    } catch { toast.error('Failed to load data'); }
    finally { setLoading(false); }
  }, [isPlatformAdmin]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const filtered = tenants.filter(t =>
    !search || t.display_name.toLowerCase().includes(search.toLowerCase()) || t.slug.includes(search.toLowerCase())
  );

  const activeCt = tenants.filter(t => t.status === 'active').length;
  const readonlyCt = tenants.filter(t => t.status === 'readonly').length;
  const suspendedCt = tenants.filter(t => t.status === 'suspended').length;
  const salesReps = allUsers.filter(u => u.role === 'sales_rep');

  async function toggleTenantStatus(t: TenantOverview, newStatus: string) {
    try {
      await platformApi.put(`/api/v1/platform/tenants/${t.slug}`, { status: newStatus });
      toast.success(`${t.display_name} → ${newStatus}`);
      fetchData();
    } catch (err: any) { toast.error(err?.response?.data?.detail || 'Failed'); }
  }

  async function assignRep(slug: string, userId: string) {
    try {
      await platformApi.post(`/api/v1/platform/tenants/${slug}/assign-rep`, { platform_user_id: userId });
      toast.success('Sales rep assigned'); fetchData();
    } catch (err: any) { toast.error(err?.response?.data?.detail || 'Failed'); }
  }

  async function removeRep(slug: string, userId: string) {
    try {
      await platformApi.delete(`/api/v1/platform/tenants/${slug}/reps/${userId}`);
      toast.success('Sales rep removed'); fetchData();
    } catch (err: any) { toast.error(err?.response?.data?.detail || 'Failed'); }
  }

  async function toggleUserActive(u: PlatformUser) {
    try {
      await platformApi.put(`/api/v1/platform/users/${u.id}`, { is_active: !u.is_active });
      toast.success(`${u.username} ${u.is_active ? 'deactivated' : 'activated'}`); fetchData();
    } catch (err: any) { toast.error(err?.response?.data?.detail || 'Failed'); }
  }

  // ── Analytics Data ─────────────────────────────────────────────────────
  // Group tenants by month + sales rep for onboarding trends
  const monthlyOnboarding = (() => {
    const months: Record<string, { month: string; total: number; byRep: Record<string, number> }> = {};
    tenants.forEach(t => {
      const d = new Date(t.created_at);
      const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
      const label = d.toLocaleDateString('en-IN', { month: 'short', year: 'numeric' });
      if (!months[key]) months[key] = { month: label, total: 0, byRep: {} };
      months[key].total++;
      t.sales_reps.forEach(r => {
        const name = r.full_name || r.username;
        months[key].byRep[name] = (months[key].byRep[name] || 0) + 1;
      });
    });
    return Object.entries(months).sort(([a], [b]) => a.localeCompare(b)).map(([, v]) => v);
  })();

  const weeklyOnboarding = (() => {
    const now = new Date();
    const weeks: { label: string; count: number }[] = [];
    for (let i = 3; i >= 0; i--) {
      const start = new Date(now); start.setDate(now.getDate() - (i + 1) * 7);
      const end = new Date(now); end.setDate(now.getDate() - i * 7);
      const count = tenants.filter(t => { const d = new Date(t.created_at); return d >= start && d < end; }).length;
      weeks.push({ label: `Week ${4 - i}`, count });
    }
    return weeks;
  })();

  const repPerformance = (() => {
    const reps: Record<string, { name: string; total: number; active: number; readonly: number; suspended: number }> = {};
    tenants.forEach(t => {
      t.sales_reps.forEach(r => {
        const name = r.full_name || r.username;
        if (!reps[name]) reps[name] = { name, total: 0, active: 0, readonly: 0, suspended: 0 };
        reps[name].total++;
        if (t.status === 'active') reps[name].active++;
        else if (t.status === 'readonly') reps[name].readonly++;
        else if (t.status === 'suspended') reps[name].suspended++;
      });
    });
    return Object.values(reps).sort((a, b) => b.total - a.total);
  })();

  return (
    <div className="min-h-screen bg-slate-950">
      {/* Top nav */}
      <div className="bg-slate-900 border-b border-slate-700 px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Shield className="h-6 w-6 text-blue-400" />
          <div>
            <h1 className="text-base font-semibold text-white">Platform Admin</h1>
            <p className="text-xs text-slate-400">Manhotra Consulting</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm text-slate-400">{user?.full_name || user?.username}</span>
          <Badge variant="outline" className="text-blue-400 border-blue-500/30">{user?.role}</Badge>
          <Button variant="ghost" size="sm" onClick={logout} className="text-slate-400 hover:text-white"><LogOut className="h-4 w-4" /></Button>
        </div>
      </div>

      <div className="max-w-7xl mx-auto p-6 space-y-6">
        {/* Summary cards */}
        <div className="grid grid-cols-4 gap-4">
          <Card className="bg-slate-800/60 border-slate-700"><CardContent className="pt-4 pb-4 flex items-center gap-3"><div className="p-2 rounded-lg bg-blue-500/10"><Building2 className="h-5 w-5 text-blue-400" /></div><div><p className="text-2xl font-bold text-white">{tenants.length}</p><p className="text-xs text-slate-400">Total Tenants</p></div></CardContent></Card>
          <Card className="bg-slate-800/60 border-slate-700"><CardContent className="pt-4 pb-4 flex items-center gap-3"><div className="p-2 rounded-lg bg-green-500/10"><CheckCircle className="h-5 w-5 text-green-400" /></div><div><p className="text-2xl font-bold text-green-400">{activeCt}</p><p className="text-xs text-slate-400">Active</p></div></CardContent></Card>
          <Card className="bg-slate-800/60 border-slate-700"><CardContent className="pt-4 pb-4 flex items-center gap-3"><div className="p-2 rounded-lg bg-amber-500/10"><AlertTriangle className="h-5 w-5 text-amber-400" /></div><div><p className="text-2xl font-bold text-amber-400">{readonlyCt}</p><p className="text-xs text-slate-400">Read-Only</p></div></CardContent></Card>
          <Card className="bg-slate-800/60 border-slate-700"><CardContent className="pt-4 pb-4 flex items-center gap-3"><div className="p-2 rounded-lg bg-red-500/10"><PauseCircle className="h-5 w-5 text-red-400" /></div><div><p className="text-2xl font-bold text-red-400">{suspendedCt}</p><p className="text-xs text-slate-400">Suspended</p></div></CardContent></Card>
        </div>

        {/* Tabs: Tenants | Users | Analytics */}
        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList className="bg-slate-800 border border-slate-700">
            <TabsTrigger value="tenants" className="data-[state=active]:bg-slate-700 text-slate-300"><Building2 className="h-3.5 w-3.5 mr-1" />Tenants</TabsTrigger>
            {isPlatformAdmin && <TabsTrigger value="users" className="data-[state=active]:bg-slate-700 text-slate-300"><Users className="h-3.5 w-3.5 mr-1" />Internal Users</TabsTrigger>}
            <TabsTrigger value="analytics" className="data-[state=active]:bg-slate-700 text-slate-300"><BarChart3 className="h-3.5 w-3.5 mr-1" />Analytics</TabsTrigger>
          </TabsList>

          {/* ── TENANTS TAB ── */}
          <TabsContent value="tenants" className="mt-4 space-y-4">
            <div className="flex items-center justify-between">
              <div className="relative w-72">
                <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-slate-500" />
                <Input placeholder="Search tenants..." value={search} onChange={e => setSearch(e.target.value)} className="pl-9 bg-slate-800 border-slate-700 text-white placeholder:text-slate-500" />
              </div>
              {isPlatformAdmin && <Button onClick={() => setOnboardOpen(true)} className="bg-blue-600 hover:bg-blue-700"><Plus className="h-4 w-4 mr-1" />Onboard New Company</Button>}
            </div>

            {loading ? (
              <div className="flex justify-center py-12"><Loader2 className="h-8 w-8 animate-spin text-blue-400" /></div>
            ) : (
              <Card className="bg-slate-800/60 border-slate-700">
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead><tr className="border-b border-slate-700 text-slate-400">
                      <th className="text-left px-4 py-3 font-medium">Company</th>
                      <th className="text-left px-4 py-3 font-medium">Slug</th>
                      <th className="text-center px-4 py-3 font-medium">Status</th>
                      <th className="text-left px-4 py-3 font-medium">AMC Expiry</th>
                      <th className="text-left px-4 py-3 font-medium">Agent Key</th>
                      <th className="text-left px-4 py-3 font-medium">Sales Rep</th>
                      <th className="text-right px-4 py-3 font-medium">Actions</th>
                    </tr></thead>
                    <tbody>
                      {filtered.map(t => (
                        <tr key={t.id} className="border-b border-slate-700/50 hover:bg-slate-700/30">
                          <td className="px-4 py-3 text-white font-medium">{t.display_name}</td>
                          <td className="px-4 py-3 font-mono text-xs text-slate-400">{t.slug}</td>
                          <td className="px-4 py-3 text-center"><StatusBadge status={t.status} /></td>
                          <td className="px-4 py-3 text-slate-300"><div className="flex items-center gap-1"><Calendar className="h-3.5 w-3.5 text-slate-500" />{fmtDate(t.amc_expiry_date)}</div></td>
                          <td className="px-4 py-3">
                            <AgentKeyCell agentKey={t.agent_api_key} />
                          </td>
                          <td className="px-4 py-3">
                            <div className="flex flex-wrap gap-1">
                              {t.sales_reps.map(r => (
                                <Badge key={r.id} variant="outline" className="text-xs text-slate-300 border-slate-600 gap-1">
                                  {r.full_name || r.username}
                                  {isPlatformAdmin && <button onClick={() => removeRep(t.slug, r.id)} className="text-red-400 hover:text-red-300 ml-0.5" title="Remove"><UserMinus className="h-3 w-3" /></button>}
                                </Badge>
                              ))}
                              {isPlatformAdmin && (
                                <Select onValueChange={(v: string | null) => { if (v) assignRep(t.slug, v); }}>
                                  <SelectTrigger className="h-6 w-6 p-0 border-0 bg-transparent text-slate-500 hover:text-blue-400"><UserPlus className="h-3.5 w-3.5" /></SelectTrigger>
                                  <SelectContent>{salesReps.filter(u => !t.sales_reps.some(r => r.id === u.id)).map(u => (
                                    <SelectItem key={u.id} value={u.id}>{u.full_name || u.username}</SelectItem>
                                  ))}</SelectContent>
                                </Select>
                              )}
                            </div>
                          </td>
                          <td className="px-4 py-3 text-right">
                            <div className="flex gap-1 justify-end">
                              {isPlatformAdmin && (
                                <>
                                  <Button size="icon" variant="ghost" className="h-7 w-7 text-slate-400 hover:text-white" title="Edit" onClick={() => setEditTenant(t)}><Pencil className="h-3.5 w-3.5" /></Button>
                                  {t.status === 'active' && (
                                    <Button size="icon" variant="ghost" className="h-7 w-7 text-slate-400 hover:text-red-400" title="Suspend" onClick={() => toggleTenantStatus(t, 'suspended')}><Ban className="h-3.5 w-3.5" /></Button>
                                  )}
                                  {t.status === 'suspended' && (
                                    <Button size="icon" variant="ghost" className="h-7 w-7 text-slate-400 hover:text-green-400" title="Reactivate" onClick={() => toggleTenantStatus(t, 'active')}><Power className="h-3.5 w-3.5" /></Button>
                                  )}
                                  {t.status === 'readonly' && (
                                    <Button size="icon" variant="ghost" className="h-7 w-7 text-slate-400 hover:text-green-400" title="Reactivate" onClick={() => toggleTenantStatus(t, 'active')}><Power className="h-3.5 w-3.5" /></Button>
                                  )}
                                </>
                              )}
                              <Button size="icon" variant="ghost" className="h-7 w-7 text-slate-400 hover:text-blue-400" title="Open Client Portal" onClick={() => window.open(`//${t.slug}.${window.location.host.replace(/^[^.]+\./, '')}`, '_blank')}><ExternalLink className="h-3.5 w-3.5" /></Button>
                            </div>
                          </td>
                        </tr>
                      ))}
                      {filtered.length === 0 && <tr><td colSpan={7} className="text-center py-8 text-slate-500">No tenants found</td></tr>}
                    </tbody>
                  </table>
                </div>
              </Card>
            )}
          </TabsContent>

          {/* ── INTERNAL USERS TAB ── */}
          {isPlatformAdmin && (
            <TabsContent value="users" className="mt-4 space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold text-white">Internal Users</h2>
                <Button onClick={() => { setEditingUser(null); setUserDialogOpen(true); }} className="bg-blue-600 hover:bg-blue-700"><Plus className="h-4 w-4 mr-1" />Add User</Button>
              </div>

              <Card className="bg-slate-800/60 border-slate-700">
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead><tr className="border-b border-slate-700 text-slate-400">
                      <th className="text-left px-4 py-3 font-medium">Name</th>
                      <th className="text-left px-4 py-3 font-medium">Username</th>
                      <th className="text-center px-4 py-3 font-medium">Role</th>
                      <th className="text-left px-4 py-3 font-medium">Email</th>
                      <th className="text-left px-4 py-3 font-medium">Phone</th>
                      <th className="text-left px-4 py-3 font-medium">Assigned Clients</th>
                      <th className="text-center px-4 py-3 font-medium">Status</th>
                      <th className="text-right px-4 py-3 font-medium">Actions</th>
                    </tr></thead>
                    <tbody>
                      {allUsers.map(u => {
                        const assignedTenants = tenants.filter(t => t.sales_reps.some(r => r.id === u.id));
                        return (
                          <tr key={u.id} className={`border-b border-slate-700/50 hover:bg-slate-700/30 ${!u.is_active ? 'opacity-50' : ''}`}>
                            <td className="px-4 py-3 text-white font-medium">{u.full_name || '—'}</td>
                            <td className="px-4 py-3 font-mono text-xs text-slate-400">{u.username}</td>
                            <td className="px-4 py-3 text-center"><RoleBadge role={u.role} /></td>
                            <td className="px-4 py-3 text-slate-300 text-xs">{u.email || '—'}</td>
                            <td className="px-4 py-3 text-slate-300 text-xs">{u.phone || '—'}</td>
                            <td className="px-4 py-3">
                              <div className="flex flex-wrap gap-1">
                                {assignedTenants.length === 0 ? <span className="text-xs text-slate-500">None</span> : assignedTenants.map(t => (
                                  <Badge key={t.id} variant="outline" className="text-[10px] text-slate-400 border-slate-600">{t.display_name}</Badge>
                                ))}
                              </div>
                            </td>
                            <td className="px-4 py-3 text-center">{u.is_active ? <Badge className="bg-green-100 text-green-700 hover:bg-green-100 text-[10px]">Active</Badge> : <Badge className="bg-red-100 text-red-700 hover:bg-red-100 text-[10px]">Inactive</Badge>}</td>
                            <td className="px-4 py-3 text-right">
                              <div className="flex gap-1 justify-end">
                                <Button size="icon" variant="ghost" className="h-7 w-7 text-slate-400 hover:text-white" title="Edit" onClick={() => { setEditingUser(u); setUserDialogOpen(true); }}><Pencil className="h-3.5 w-3.5" /></Button>
                                <Button size="icon" variant="ghost" className="h-7 w-7 text-slate-400 hover:text-amber-400" title="Reset Password" onClick={() => setResetPwUser(u)}><KeyRound className="h-3.5 w-3.5" /></Button>
                                <Button size="icon" variant="ghost" className={`h-7 w-7 ${u.is_active ? 'text-slate-400 hover:text-red-400' : 'text-slate-400 hover:text-green-400'}`} title={u.is_active ? 'Deactivate' : 'Activate'} onClick={() => toggleUserActive(u)}>
                                  {u.is_active ? <Ban className="h-3.5 w-3.5" /> : <UserCheck className="h-3.5 w-3.5" />}
                                </Button>
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                      {allUsers.length === 0 && <tr><td colSpan={8} className="text-center py-8 text-slate-500">No internal users</td></tr>}
                    </tbody>
                  </table>
                </div>
              </Card>
            </TabsContent>
          )}

          {/* ── ANALYTICS TAB ── */}
          <TabsContent value="analytics" className="mt-4 space-y-6">
            <div className="grid grid-cols-3 gap-4">
              {/* Weekly Onboarding */}
              <Card className="bg-slate-800/60 border-slate-700 col-span-1">
                <CardContent className="pt-4 pb-4">
                  <h3 className="text-sm font-semibold text-slate-300 mb-3 flex items-center gap-1.5"><TrendingUp className="h-4 w-4 text-blue-400" />Weekly Trend (Last 4 Weeks)</h3>
                  <div className="space-y-2">
                    {weeklyOnboarding.map((w, i) => (
                      <div key={i} className="flex items-center gap-2">
                        <span className="text-xs text-slate-500 w-16">{w.label}</span>
                        <div className="flex-1 bg-slate-700 rounded-full h-4 overflow-hidden">
                          <div className="bg-blue-500 h-full rounded-full transition-all" style={{ width: `${Math.max(w.count * 25, w.count > 0 ? 10 : 0)}%` }} />
                        </div>
                        <span className="text-sm font-bold text-white w-6 text-right">{w.count}</span>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>

              {/* Monthly Onboarding */}
              <Card className="bg-slate-800/60 border-slate-700 col-span-2">
                <CardContent className="pt-4 pb-4">
                  <h3 className="text-sm font-semibold text-slate-300 mb-3 flex items-center gap-1.5"><BarChart3 className="h-4 w-4 text-green-400" />Monthly Onboarding</h3>
                  {monthlyOnboarding.length === 0 ? (
                    <p className="text-sm text-slate-500 py-4 text-center">No data yet</p>
                  ) : (
                    <div className="space-y-2">
                      {monthlyOnboarding.map((m, i) => (
                        <div key={i} className="flex items-center gap-3">
                          <span className="text-xs text-slate-400 w-20 shrink-0">{m.month}</span>
                          <div className="flex-1 bg-slate-700 rounded-full h-6 overflow-hidden relative">
                            <div className="bg-green-500/80 h-full rounded-full transition-all flex items-center px-2" style={{ width: `${Math.max(m.total * 15, m.total > 0 ? 15 : 0)}%` }}>
                              <span className="text-[10px] text-white font-bold">{m.total}</span>
                            </div>
                          </div>
                          <div className="flex gap-1 shrink-0">
                            {Object.entries(m.byRep).map(([name, count]) => (
                              <Badge key={name} variant="outline" className="text-[10px] text-slate-400 border-slate-600">{name}: {count}</Badge>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>

            {/* Sales Rep Performance */}
            <Card className="bg-slate-800/60 border-slate-700">
              <CardContent className="pt-4 pb-4">
                <h3 className="text-sm font-semibold text-slate-300 mb-3 flex items-center gap-1.5"><UserCheck className="h-4 w-4 text-purple-400" />Sales Rep Performance</h3>
                {repPerformance.length === 0 ? (
                  <p className="text-sm text-slate-500 py-4 text-center">No sales rep assignments yet. Assign reps to tenants to see performance data.</p>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead><tr className="border-b border-slate-700 text-slate-400">
                        <th className="text-left px-4 py-2 font-medium">Sales Rep</th>
                        <th className="text-center px-4 py-2 font-medium">Total Clients</th>
                        <th className="text-center px-4 py-2 font-medium">Active</th>
                        <th className="text-center px-4 py-2 font-medium">Read-Only</th>
                        <th className="text-center px-4 py-2 font-medium">Suspended</th>
                        <th className="text-center px-4 py-2 font-medium">Retention %</th>
                      </tr></thead>
                      <tbody>
                        {repPerformance.map(r => {
                          const retention = r.total > 0 ? Math.round((r.active / r.total) * 100) : 0;
                          return (
                            <tr key={r.name} className="border-b border-slate-700/50">
                              <td className="px-4 py-2 text-white font-medium">{r.name}</td>
                              <td className="px-4 py-2 text-center text-white font-bold">{r.total}</td>
                              <td className="px-4 py-2 text-center text-green-400">{r.active}</td>
                              <td className="px-4 py-2 text-center text-amber-400">{r.readonly}</td>
                              <td className="px-4 py-2 text-center text-red-400">{r.suspended}</td>
                              <td className="px-4 py-2 text-center">
                                <span className={`font-bold ${retention >= 80 ? 'text-green-400' : retention >= 50 ? 'text-amber-400' : 'text-red-400'}`}>{retention}%</span>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </div>

      {/* Dialogs */}
      <OnboardDialog open={onboardOpen} onClose={() => setOnboardOpen(false)} onCreated={fetchData} />
      <EditTenantDialog tenant={editTenant} open={!!editTenant} onClose={() => setEditTenant(null)} onSaved={fetchData} />
      <UserDialog open={userDialogOpen} onClose={() => { setUserDialogOpen(false); setEditingUser(null); }} onSaved={fetchData} editUser={editingUser} />
      <ResetPasswordDialog user={resetPwUser} open={!!resetPwUser} onClose={() => setResetPwUser(null)} />
    </div>
  );
}
