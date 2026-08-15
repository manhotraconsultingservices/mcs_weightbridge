import { useEffect, useState, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';
import { Plus, Edit2, KeyRound, UserCheck, UserX, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { DataTable, type ColumnDef } from '@/components/DataTable';
import { useAuth } from '@/hooks/useAuth';
import { BUILTIN_ROLES, roleLabel, type RoleDef } from '@/lib/rbac';
import api from '@/services/api';

// ── Types ────────────────────────────────────────────────────────────────── //

interface ManagedUser {
  id: string;
  username: string;
  full_name: string | null;
  email: string | null;
  phone: string | null;
  role: string;
  is_active: boolean;
}

// ── Constants ─────────────────────────────────────────────────────────────── //

const ROLE_STYLES: Record<string, string> = {
  admin:              'bg-purple-100 text-purple-700 border-purple-200',
  store_manager:      'bg-emerald-100 text-emerald-700 border-emerald-200',
  operator:           'bg-blue-100 text-blue-700 border-blue-200',
  sales_executive:    'bg-green-100 text-green-700 border-green-200',
  purchase_executive: 'bg-orange-100 text-orange-700 border-orange-200',
  accountant:         'bg-cyan-100 text-cyan-700 border-cyan-200',
  viewer:             'bg-gray-100 text-gray-600 border-gray-200',
};

// ── Dialogs ──────────────────────────────────────────────────────────────── //

interface AddEditDialogProps {
  open: boolean;
  user: ManagedUser | null;
  customRoles: RoleDef[];
  onClose: () => void;
  onSaved: (u: ManagedUser) => void;
}

function AddEditDialog({ open, user, customRoles, onClose, onSaved }: AddEditDialogProps) {
  const { t } = useTranslation();
  const isEdit = !!user;
  const [form, setForm] = useState({
    username: '', full_name: '', email: '', phone: '', role: 'operator', password: '', is_active: true,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  // Built from the SAME list the Role Permissions page uses (lib/rbac.ts), resolved
  // through each role's single i18n key. This used to be a second hand-written list,
  // which is how gate_guard came to read "Security Guard" here and "Gate Guard" there
  // — the option was in the dropdown, just under a name nobody was looking for.
  const ROLES = useMemo(() => [
    { value: 'admin', label: t('users.roles.admin') },
    ...BUILTIN_ROLES.map(r => ({ value: r.value, label: roleLabel(r, t) })),
    // Admin-defined custom roles (from /admin/permissions → New Role)
    ...customRoles.map(r => ({ value: r.value, label: r.label })),
  ], [t, customRoles]);

  useEffect(() => {
    if (open) {
      if (user) {
        setForm({ username: user.username, full_name: user.full_name ?? '', email: user.email ?? '', phone: user.phone ?? '', role: user.role, password: '', is_active: user.is_active });
      } else {
        setForm({ username: '', full_name: '', email: '', phone: '', role: 'operator', password: '', is_active: true });
      }
      setError('');
    }
  }, [open, user]);

  async function handleSave() {
    if (!form.username.trim()) { setError(t('users.errors.usernameRequired')); return; }
    if (!isEdit && !form.password) { setError(t('users.errors.passwordRequired')); return; }
    if (!isEdit && form.password.length < 6) { setError(t('users.errors.passwordMinLength')); return; }

    setSaving(true); setError('');
    try {
      if (isEdit) {
        const { data } = await api.put<ManagedUser>(`/api/v1/auth/users/${user!.id}`, {
          full_name: form.full_name || null,
          email: form.email || null,
          phone: form.phone || null,
          role: form.role,
          is_active: form.is_active,
        });
        onSaved(data);
        toast.success(t('users.toasts.updated'));
      } else {
        const { data } = await api.post<ManagedUser>('/api/v1/auth/users', {
          username: form.username.trim(),
          password: form.password,
          full_name: form.full_name || null,
          email: form.email || null,
          phone: form.phone || null,
          role: form.role,
        });
        onSaved(data);
        toast.success(t('users.toasts.created'));
      }
      onClose();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : t('users.errors.saveFailed'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={v => !v && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{isEdit ? t('users.editUser') : t('users.addUser')}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          {error && <p className="rounded bg-destructive/10 p-2 text-sm text-destructive">{error}</p>}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>{t('users.username')} *</Label>
              <Input
                value={form.username}
                onChange={e => setForm(prev => ({ ...prev, username: e.target.value }))}
                disabled={isEdit}
                placeholder="john.doe"
              />
            </div>
            <div className="space-y-1">
              <Label>{t('users.role')} *</Label>
              <Select value={form.role} onValueChange={v => setForm(prev => ({ ...prev, role: v ?? 'operator' }))}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {ROLES.map(r => <SelectItem key={r.value} value={r.value}>{r.label}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="space-y-1">
            <Label>{t('users.fullName')}</Label>
            <Input value={form.full_name} onChange={e => setForm(prev => ({ ...prev, full_name: e.target.value }))} placeholder="John Doe" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>{t('users.email')}</Label>
              <Input type="email" value={form.email} onChange={e => setForm(prev => ({ ...prev, email: e.target.value }))} placeholder="john@company.com" />
            </div>
            <div className="space-y-1">
              <Label>{t('users.phone')}</Label>
              <Input value={form.phone} onChange={e => setForm(prev => ({ ...prev, phone: e.target.value }))} placeholder="9876543210" />
            </div>
          </div>
          {!isEdit && (
            <div className="space-y-1">
              <Label>{t('users.initialPassword')} *</Label>
              <Input type="password" value={form.password} onChange={e => setForm(prev => ({ ...prev, password: e.target.value }))} placeholder={t('users.passwordPlaceholder')} />
            </div>
          )}
          {isEdit && (
            <div className="flex items-center gap-3 rounded-md border p-3">
              <span className="text-sm text-muted-foreground flex-1">{t('users.accountStatus')}</span>
              <Button
                size="sm"
                variant={form.is_active ? 'default' : 'outline'}
                onClick={() => setForm(prev => ({ ...prev, is_active: !prev.is_active }))}
              >
                {form.is_active ? <><UserCheck className="h-3.5 w-3.5 mr-1" />{t('users.active')}</> : <><UserX className="h-3.5 w-3.5 mr-1" />{t('users.inactive')}</>}
              </Button>
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={saving}>{t('common.cancel')}</Button>
          <Button onClick={handleSave} disabled={saving}>{saving ? t('users.saving') : (isEdit ? t('common.update') : t('users.createUser'))}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

interface ResetPasswordDialogProps {
  open: boolean;
  user: ManagedUser | null;
  onClose: () => void;
}

function ResetPasswordDialog({ open, user, onClose }: ResetPasswordDialogProps) {
  const { t } = useTranslation();
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (open) { setPassword(''); setConfirm(''); setError(''); }
  }, [open]);

  async function handleReset() {
    if (password.length < 6) { setError(t('users.errors.passwordMinLength')); return; }
    if (password !== confirm) { setError(t('users.errors.passwordMismatch')); return; }
    setSaving(true); setError('');
    try {
      await api.put(`/api/v1/auth/users/${user!.id}/reset-password`, { new_password: password });
      toast.success(t('users.toasts.passwordReset', { username: user!.username }));
      onClose();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : t('users.errors.resetFailed'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={v => !v && onClose()}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>{t('users.resetPassword')} — {user?.username}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          {error && <p className="rounded bg-destructive/10 p-2 text-sm text-destructive">{error}</p>}
          <div className="space-y-1">
            <Label>{t('users.newPassword')}</Label>
            <Input type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder={t('users.passwordPlaceholder')} />
          </div>
          <div className="space-y-1">
            <Label>{t('users.confirmPassword')}</Label>
            <Input type="password" value={confirm} onChange={e => setConfirm(e.target.value)} placeholder={t('users.confirmPasswordPlaceholder')} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={saving}>{t('common.cancel')}</Button>
          <Button onClick={handleReset} disabled={saving}>{saving ? t('users.resetting') : t('users.resetPassword')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────── //

export default function UserManagementPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [customRoles, setCustomRoles] = useState<RoleDef[]>([]);
  const [loading, setLoading] = useState(false);
  const [addEditOpen, setAddEditOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<ManagedUser | null>(null);
  const [resetTarget, setResetTarget] = useState<ManagedUser | null>(null);
  const [resetOpen, setResetOpen] = useState(false);

  // Guard — admin only
  useEffect(() => {
    if (user && user.role !== 'admin') navigate('/', { replace: true });
  }, [user, navigate]);

  const fetchUsers = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get<ManagedUser[]>('/api/v1/auth/users');
      setUsers(data);
    } catch {
      toast.error(t('users.toasts.loadFailed'));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { fetchUsers(); }, [fetchUsers]);
  useEffect(() => {
    api.get<RoleDef[]>('/api/v1/app-settings/custom-roles')
      .then(r => setCustomRoles(Array.isArray(r.data) ? r.data : []))
      .catch(() => setCustomRoles([]));
  }, []);

  if (!user || user.role !== 'admin') return null;

  function handleSaved(saved: ManagedUser) {
    setUsers(prev => {
      const idx = prev.findIndex(u => u.id === saved.id);
      if (idx >= 0) { const a = [...prev]; a[idx] = saved; return a; }
      return [...prev, saved];
    });
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{t('users.title')}</h1>
          <p className="text-sm text-muted-foreground">{t('users.subtitle')}</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={fetchUsers} disabled={loading}>
            <RefreshCw className={`h-4 w-4 mr-1 ${loading ? 'animate-spin' : ''}`} />
            {t('common.refresh')}
          </Button>
          <Button size="sm" onClick={() => { setEditTarget(null); setAddEditOpen(true); }}>
            <Plus className="h-4 w-4 mr-1" />
            {t('users.addUser')}
          </Button>
        </div>
      </div>

      <UsersTable
        users={users}
        loading={loading}
        customRoles={customRoles}
        onEdit={u => { setEditTarget(u); setAddEditOpen(true); }}
        onResetPassword={u => { setResetTarget(u); setResetOpen(true); }}
      />

      <AddEditDialog
        open={addEditOpen}
        user={editTarget}
        customRoles={customRoles}
        onClose={() => { setAddEditOpen(false); setEditTarget(null); }}
        onSaved={handleSaved}
      />
      <ResetPasswordDialog
        open={resetOpen}
        user={resetTarget}
        onClose={() => { setResetOpen(false); setResetTarget(null); }}
      />
    </div>
  );
}

// ------------------------------------------------------------------ //
// Users DataTable
// ------------------------------------------------------------------ //
function UsersTable({
  users, loading, customRoles, onEdit, onResetPassword,
}: {
  users: ManagedUser[];
  loading: boolean;
  customRoles: RoleDef[];
  onEdit: (u: ManagedUser) => void;
  onResetPassword: (u: ManagedUser) => void;
}) {
  const { t } = useTranslation();

  const ROLE_LABELS: Record<string, string> = useMemo(() => ({
    admin:              t('users.roles.admin'),
    store_manager:      t('users.roles.store_manager'),
    operator:           t('users.roles.operator'),
    sales_executive:    t('users.roles.sales_executive'),
    private_admin:      t('users.roles.private_admin'),
    // same single source as the picker above, so the badge can't drift from it
    ...Object.fromEntries(BUILTIN_ROLES.map(r => [r.value, roleLabel(r, t)])),
    ...Object.fromEntries(customRoles.map(r => [r.value, r.label])),
  }), [t, customRoles]);

  const columns = useMemo<ColumnDef<ManagedUser>[]>(() => [
    { key: 'full_name', label: t('users.colName'), accessor: u => u.full_name ?? '', className: 'font-medium' },
    { key: 'username', label: t('users.colUsername'), accessor: u => u.username, className: 'font-mono text-xs' },
    {
      key: 'role', label: t('users.colRole'), type: 'enum',
      enumOptions: Object.keys(ROLE_LABELS),
      accessor: u => u.role,
      format: (_, u) => (
        <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${ROLE_STYLES[u.role] ?? 'bg-gray-100 text-gray-600'}`}>
          {ROLE_LABELS[u.role] ?? u.role}
        </span>
      ),
    },
    { key: 'email', label: t('users.colEmail'), accessor: u => u.email ?? '', className: 'text-muted-foreground' },
    { key: 'phone', label: t('users.colPhone'), accessor: u => u.phone ?? '', className: 'text-muted-foreground' },
    {
      key: 'is_active', label: t('users.colStatus'), type: 'enum',
      enumOptions: [t('users.active'), t('users.inactive')],
      accessor: u => u.is_active ? t('users.active') : t('users.inactive'),
      format: v => v === t('users.active')
        ? <span className="inline-flex items-center gap-1 text-xs text-green-600"><span className="h-1.5 w-1.5 rounded-full bg-green-500 inline-block" />{t('users.active')}</span>
        : <span className="inline-flex items-center gap-1 text-xs text-gray-400"><span className="h-1.5 w-1.5 rounded-full bg-gray-300 inline-block" />{t('users.inactive')}</span>,
    },
  ], [t, ROLE_LABELS]);

  return (
    <DataTable<ManagedUser>
      id="users.main"
      loading={loading}
      data={users}
      columns={columns}
      rowKey={u => u.id}
      exportFilename="users"
      defaultSort={{ key: 'username', direction: 'asc' }}
      emptyMessage={t('users.noUsersFound')}
      rowActions={u => (
        <div className="flex gap-1 justify-end">
          <Button size="icon" variant="ghost" className="h-7 w-7" title={t('users.editUserTitle')} onClick={() => onEdit(u)}>
            <Edit2 className="h-3.5 w-3.5" />
          </Button>
          <Button size="icon" variant="ghost" className="h-7 w-7" title={t('users.resetPasswordTitle')} onClick={() => onResetPassword(u)}>
            <KeyRound className="h-3.5 w-3.5 text-orange-500" />
          </Button>
        </div>
      )}
    />
  );
}
