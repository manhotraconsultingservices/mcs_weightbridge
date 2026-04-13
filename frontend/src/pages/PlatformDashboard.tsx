import { useState, useEffect, useCallback } from 'react';
import { toast } from 'sonner';
import {
  Building2, Plus, Search, Shield, UserPlus, UserMinus,
  AlertTriangle, CheckCircle, PauseCircle, Calendar, ExternalLink,
  LogOut, Pencil, Loader2,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import platformApi from '@/services/platformApi';
import { usePlatformAuth } from '@/hooks/usePlatformAuth';
import type { TenantOverview, PlatformUser } from '@/types';

// ── Status helpers ───────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  if (status === 'active') return <Badge className="bg-green-100 text-green-700 hover:bg-green-100">Active</Badge>;
  if (status === 'readonly') return <Badge className="bg-amber-100 text-amber-700 hover:bg-amber-100">Read-Only</Badge>;
  if (status === 'suspended') return <Badge className="bg-red-100 text-red-700 hover:bg-red-100">Suspended</Badge>;
  return <Badge variant="secondary">{status}</Badge>;
}

function fmtDate(iso: string | null) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
}

// ── Onboard Tenant Dialog ────────────────────────────────────────────────────

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
    return name.toLowerCase().replace(/[^a-z0-9]/g, '_').replace(/_+/g, '_').replace(/^_|_$/g, '').slice(0, 30);
  }

  async function handleCreate() {
    if (!slug || !displayName || !adminPass || !companyName) {
      toast.error('Fill all required fields');
      return;
    }
    setSaving(true);
    try {
      await platformApi.post('/api/v1/platform/tenants', {
        slug,
        display_name: displayName,
        company_name: companyName,
        admin_username: adminUser,
        admin_password: adminPass,
        amc_start_date: amcStart || null,
        amc_expiry_date: amcExpiry || null,
      });
      toast.success(`Tenant "${displayName}" created successfully`);
      onCreated();
      onClose();
      // Reset form
      setSlug(''); setDisplayName(''); setCompanyName(''); setAdminPass(''); setAmcExpiry('');
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || 'Failed to create tenant');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Plus className="h-5 w-5 text-blue-500" />
            Onboard New Company
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3 py-2">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>Company Name *</Label>
              <Input value={companyName} onChange={e => { setCompanyName(e.target.value); if (!slug || slug === autoSlug(displayName)) { setSlug(autoSlug(e.target.value)); setDisplayName(e.target.value); } }} placeholder="Alpha Crushers Pvt Ltd" />
            </div>
            <div>
              <Label>Display Name *</Label>
              <Input value={displayName} onChange={e => { setDisplayName(e.target.value); setSlug(autoSlug(e.target.value)); }} placeholder="Alpha Crushers" />
            </div>
          </div>
          <div>
            <Label>Slug (URL identifier) *</Label>
            <Input value={slug} onChange={e => setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, ''))} placeholder="alpha_crushers" className="font-mono text-sm" />
            <p className="text-[10px] text-muted-foreground mt-0.5">URL: {slug || '...'}.weighbridge.app</p>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>Admin Username</Label>
              <Input value={adminUser} onChange={e => setAdminUser(e.target.value)} />
            </div>
            <div>
              <Label>Admin Password *</Label>
              <Input type="password" value={adminPass} onChange={e => setAdminPass(e.target.value)} placeholder="Strong password" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>AMC Start Date</Label>
              <Input type="date" value={amcStart} onChange={e => setAmcStart(e.target.value)} />
            </div>
            <div>
              <Label>AMC Expiry Date</Label>
              <Input type="date" value={amcExpiry} onChange={e => setAmcExpiry(e.target.value)} />
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={handleCreate} disabled={saving}>
            {saving && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}
            Create Tenant
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Edit Tenant Dialog ───────────────────────────────────────────────────────

function EditTenantDialog({ tenant, open, onClose, onSaved, salesReps }: {
  tenant: TenantOverview | null; open: boolean; onClose: () => void; onSaved: () => void;
  salesReps: PlatformUser[];
}) {
  const [status, setStatus] = useState('active');
  const [displayName, setDisplayName] = useState('');
  const [amcStart, setAmcStart] = useState('');
  const [amcExpiry, setAmcExpiry] = useState('');
  const [contactEmail, setContactEmail] = useState('');
  const [contactPhone, setContactPhone] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (tenant) {
      setStatus(tenant.status);
      setDisplayName(tenant.display_name);
      setAmcStart(tenant.amc_start_date || '');
      setAmcExpiry(tenant.amc_expiry_date || '');
      setContactEmail(tenant.contact_email || '');
      setContactPhone(tenant.contact_phone || '');
    }
  }, [tenant]);

  async function handleSave() {
    setSaving(true);
    try {
      await platformApi.put(`/api/v1/platform/tenants/${tenant!.slug}`, {
        display_name: displayName,
        status,
        amc_start_date: amcStart || null,
        amc_expiry_date: amcExpiry || null,
        contact_email: contactEmail || null,
        contact_phone: contactPhone || null,
      });
      toast.success('Tenant updated');
      onSaved();
      onClose();
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || 'Update failed');
    } finally {
      setSaving(false);
    }
  }

  if (!tenant) return null;

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Edit: {tenant.display_name}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 py-2">
          <div>
            <Label>Display Name</Label>
            <Input value={displayName} onChange={e => setDisplayName(e.target.value)} />
          </div>
          <div>
            <Label>Status</Label>
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
            <div>
              <Label>AMC Start</Label>
              <Input type="date" value={amcStart} onChange={e => setAmcStart(e.target.value)} />
            </div>
            <div>
              <Label>AMC Expiry</Label>
              <Input type="date" value={amcExpiry} onChange={e => setAmcExpiry(e.target.value)} />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>Contact Email</Label>
              <Input value={contactEmail} onChange={e => setContactEmail(e.target.value)} />
            </div>
            <div>
              <Label>Contact Phone</Label>
              <Input value={contactPhone} onChange={e => setContactPhone(e.target.value)} />
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}
            Save Changes
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Main Page ────────────────────────────────────────────────────────────────

export default function PlatformDashboard() {
  const { user, isPlatformAdmin, logout } = usePlatformAuth();
  const [tenants, setTenants] = useState<TenantOverview[]>([]);
  const [allUsers, setAllUsers] = useState<PlatformUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [onboardOpen, setOnboardOpen] = useState(false);
  const [editTenant, setEditTenant] = useState<TenantOverview | null>(null);

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
    } catch {
      toast.error('Failed to load tenants');
    } finally {
      setLoading(false);
    }
  }, [isPlatformAdmin]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const filtered = tenants.filter(t =>
    !search || t.display_name.toLowerCase().includes(search.toLowerCase()) || t.slug.includes(search.toLowerCase())
  );

  const activeCt = tenants.filter(t => t.status === 'active').length;
  const readonlyCt = tenants.filter(t => t.status === 'readonly').length;
  const suspendedCt = tenants.filter(t => t.status === 'suspended').length;

  async function assignRep(slug: string, userId: string) {
    try {
      await platformApi.post(`/api/v1/platform/tenants/${slug}/assign-rep`, { platform_user_id: userId });
      toast.success('Sales rep assigned');
      fetchData();
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || 'Assignment failed');
    }
  }

  async function removeRep(slug: string, userId: string) {
    try {
      await platformApi.delete(`/api/v1/platform/tenants/${slug}/reps/${userId}`);
      toast.success('Sales rep removed');
      fetchData();
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || 'Remove failed');
    }
  }

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
          <Button variant="ghost" size="sm" onClick={logout} className="text-slate-400 hover:text-white">
            <LogOut className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <div className="max-w-7xl mx-auto p-6 space-y-6">
        {/* Summary cards */}
        <div className="grid grid-cols-4 gap-4">
          <Card className="bg-slate-800/60 border-slate-700">
            <CardContent className="pt-4 pb-4 flex items-center gap-3">
              <div className="p-2 rounded-lg bg-blue-500/10"><Building2 className="h-5 w-5 text-blue-400" /></div>
              <div><p className="text-2xl font-bold text-white">{tenants.length}</p><p className="text-xs text-slate-400">Total Tenants</p></div>
            </CardContent>
          </Card>
          <Card className="bg-slate-800/60 border-slate-700">
            <CardContent className="pt-4 pb-4 flex items-center gap-3">
              <div className="p-2 rounded-lg bg-green-500/10"><CheckCircle className="h-5 w-5 text-green-400" /></div>
              <div><p className="text-2xl font-bold text-green-400">{activeCt}</p><p className="text-xs text-slate-400">Active</p></div>
            </CardContent>
          </Card>
          <Card className="bg-slate-800/60 border-slate-700">
            <CardContent className="pt-4 pb-4 flex items-center gap-3">
              <div className="p-2 rounded-lg bg-amber-500/10"><AlertTriangle className="h-5 w-5 text-amber-400" /></div>
              <div><p className="text-2xl font-bold text-amber-400">{readonlyCt}</p><p className="text-xs text-slate-400">Read-Only</p></div>
            </CardContent>
          </Card>
          <Card className="bg-slate-800/60 border-slate-700">
            <CardContent className="pt-4 pb-4 flex items-center gap-3">
              <div className="p-2 rounded-lg bg-red-500/10"><PauseCircle className="h-5 w-5 text-red-400" /></div>
              <div><p className="text-2xl font-bold text-red-400">{suspendedCt}</p><p className="text-xs text-slate-400">Suspended</p></div>
            </CardContent>
          </Card>
        </div>

        {/* Toolbar */}
        <div className="flex items-center justify-between">
          <div className="relative w-72">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-slate-500" />
            <Input
              placeholder="Search tenants..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="pl-9 bg-slate-800 border-slate-700 text-white placeholder:text-slate-500"
            />
          </div>
          {isPlatformAdmin && (
            <Button onClick={() => setOnboardOpen(true)} className="bg-blue-600 hover:bg-blue-700">
              <Plus className="h-4 w-4 mr-1" /> Onboard New Company
            </Button>
          )}
        </div>

        {/* Tenant table */}
        {loading ? (
          <div className="flex justify-center py-12"><Loader2 className="h-8 w-8 animate-spin text-blue-400" /></div>
        ) : (
          <Card className="bg-slate-800/60 border-slate-700">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-700 text-slate-400">
                    <th className="text-left px-4 py-3 font-medium">Company</th>
                    <th className="text-left px-4 py-3 font-medium">Slug</th>
                    <th className="text-center px-4 py-3 font-medium">Status</th>
                    <th className="text-left px-4 py-3 font-medium">AMC Expiry</th>
                    <th className="text-left px-4 py-3 font-medium">Sales Rep</th>
                    <th className="text-right px-4 py-3 font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map(t => (
                    <tr key={t.id} className="border-b border-slate-700/50 hover:bg-slate-700/30">
                      <td className="px-4 py-3 text-white font-medium">{t.display_name}</td>
                      <td className="px-4 py-3 font-mono text-xs text-slate-400">{t.slug}</td>
                      <td className="px-4 py-3 text-center"><StatusBadge status={t.status} /></td>
                      <td className="px-4 py-3 text-slate-300">
                        <div className="flex items-center gap-1">
                          <Calendar className="h-3.5 w-3.5 text-slate-500" />
                          {fmtDate(t.amc_expiry_date)}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap gap-1">
                          {t.sales_reps.map(r => (
                            <Badge key={r.id} variant="outline" className="text-xs text-slate-300 border-slate-600 gap-1">
                              {r.full_name || r.username}
                              {isPlatformAdmin && (
                                <button onClick={() => removeRep(t.slug, r.id)} className="text-red-400 hover:text-red-300 ml-0.5" title="Remove">
                                  <UserMinus className="h-3 w-3" />
                                </button>
                              )}
                            </Badge>
                          ))}
                          {isPlatformAdmin && (
                            <Select onValueChange={(v: string | null) => { if (v) assignRep(t.slug, v); }}>
                              <SelectTrigger className="h-6 w-6 p-0 border-0 bg-transparent text-slate-500 hover:text-blue-400">
                                <UserPlus className="h-3.5 w-3.5" />
                              </SelectTrigger>
                              <SelectContent>
                                {allUsers.filter(u => u.role === 'sales_rep' && !t.sales_reps.some(r => r.id === u.id)).map(u => (
                                  <SelectItem key={u.id} value={u.id}>{u.full_name || u.username}</SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          )}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex gap-1 justify-end">
                          {isPlatformAdmin && (
                            <Button size="icon" variant="ghost" className="h-7 w-7 text-slate-400 hover:text-white" onClick={() => setEditTenant(t)}>
                              <Pencil className="h-3.5 w-3.5" />
                            </Button>
                          )}
                          <Button size="icon" variant="ghost" className="h-7 w-7 text-slate-400 hover:text-blue-400" title="View Dashboard"
                            onClick={() => window.open(`//${t.slug}.${window.location.host.replace(/^[^.]+\./, '')}`, '_blank')}>
                            <ExternalLink className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                  {filtered.length === 0 && (
                    <tr><td colSpan={6} className="text-center py-8 text-slate-500">No tenants found</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </Card>
        )}
      </div>

      {/* Dialogs */}
      <OnboardDialog open={onboardOpen} onClose={() => setOnboardOpen(false)} onCreated={fetchData} />
      <EditTenantDialog
        tenant={editTenant}
        open={!!editTenant}
        onClose={() => setEditTenant(null)}
        onSaved={fetchData}
        salesReps={allUsers.filter(u => u.role === 'sales_rep')}
      />
    </div>
  );
}
