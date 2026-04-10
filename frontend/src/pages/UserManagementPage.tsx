import { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { Plus, Edit2, KeyRound, UserCheck, UserX, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useAuth } from '@/hooks/useAuth';
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

const ROLES = [
  { value: 'admin',             label: 'Admin' },
  { value: 'store_manager',     label: 'Store Manager' },
  { value: 'operator',          label: 'Operator' },
  { value: 'sales_executive',   label: 'Sales Executive' },
  { value: 'purchase_executive',label: 'Purchase Executive' },
  { value: 'accountant',        label: 'Accountant' },
  { value: 'viewer',            label: 'Viewer' },
];

const ROLE_STYLES: Record<string, string> = {
  admin:              'bg-purple-100 text-purple-700 border-purple-200',
  store_manager:      'bg-emerald-100 text-emerald-700 border-emerald-200',
  operator:           'bg-blue-100 text-blue-700 border-blue-200',
  sales_executive:    'bg-green-100 text-green-700 border-green-200',
  purchase_executive: 'bg-orange-100 text-orange-700 border-orange-200',
  accountant:         'bg-cyan-100 text-cyan-700 border-cyan-200',
  viewer:             'bg-gray-100 text-gray-600 border-gray-200',
};

const ROLE_LABELS: Record<string, string> = {
  admin:              'Admin',
  store_manager:      'Store Manager',
  operator:           'Operator',
  sales_executive:    'Sales Executive',
  purchase_executive: 'Purchase Executive',
  accountant:         'Accountant',
  viewer:             'Viewer',
  private_admin:      'Private Admin',
};

// ── Dialogs ──────────────────────────────────────────────────────────────── //

interface AddEditDialogProps {
  open: boolean;
  user: ManagedUser | null;
  onClose: () => void;
  onSaved: (u: ManagedUser) => void;
}

function AddEditDialog({ open, user, onClose, onSaved }: AddEditDialogProps) {
  const isEdit = !!user;
  const [form, setForm] = useState({
    username: '', full_name: '', email: '', phone: '', role: 'operator', password: '', is_active: true,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

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
    if (!form.username.trim()) { setError('Username is required'); return; }
    if (!isEdit && !form.password) { setError('Password is required for new users'); return; }
    if (!isEdit && form.password.length < 6) { setError('Password must be at least 6 characters'); return; }

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
        toast.success('User updated');
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
        toast.success('User created');
      }
      onClose();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Failed to save user');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={v => !v && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{isEdit ? 'Edit User' : 'Add New User'}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          {error && <p className="rounded bg-destructive/10 p-2 text-sm text-destructive">{error}</p>}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>Username *</Label>
              <Input
                value={form.username}
                onChange={e => setForm(f => ({ ...f, username: e.target.value }))}
                disabled={isEdit}
                placeholder="john.doe"
              />
            </div>
            <div className="space-y-1">
              <Label>Role *</Label>
              <Select value={form.role} onValueChange={v => setForm(f => ({ ...f, role: v ?? 'operator' }))}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {ROLES.map(r => <SelectItem key={r.value} value={r.value}>{r.label}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="space-y-1">
            <Label>Full Name</Label>
            <Input value={form.full_name} onChange={e => setForm(f => ({ ...f, full_name: e.target.value }))} placeholder="John Doe" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>Email</Label>
              <Input type="email" value={form.email} onChange={e => setForm(f => ({ ...f, email: e.target.value }))} placeholder="john@company.com" />
            </div>
            <div className="space-y-1">
              <Label>Phone</Label>
              <Input value={form.phone} onChange={e => setForm(f => ({ ...f, phone: e.target.value }))} placeholder="9876543210" />
            </div>
          </div>
          {!isEdit && (
            <div className="space-y-1">
              <Label>Initial Password *</Label>
              <Input type="password" value={form.password} onChange={e => setForm(f => ({ ...f, password: e.target.value }))} placeholder="Min. 6 characters" />
            </div>
          )}
          {isEdit && (
            <div className="flex items-center gap-3 rounded-md border p-3">
              <span className="text-sm text-muted-foreground flex-1">Account Status</span>
              <Button
                size="sm"
                variant={form.is_active ? 'default' : 'outline'}
                onClick={() => setForm(f => ({ ...f, is_active: !f.is_active }))}
              >
                {form.is_active ? <><UserCheck className="h-3.5 w-3.5 mr-1" />Active</> : <><UserX className="h-3.5 w-3.5 mr-1" />Inactive</>}
              </Button>
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={saving}>Cancel</Button>
          <Button onClick={handleSave} disabled={saving}>{saving ? 'Saving…' : (isEdit ? 'Update' : 'Create User')}</Button>
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
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (open) { setPassword(''); setConfirm(''); setError(''); }
  }, [open]);

  async function handleReset() {
    if (password.length < 6) { setError('Password must be at least 6 characters'); return; }
    if (password !== confirm) { setError('Passwords do not match'); return; }
    setSaving(true); setError('');
    try {
      await api.put(`/api/v1/auth/users/${user!.id}/reset-password`, { new_password: password });
      toast.success(`Password reset for ${user!.username}`);
      onClose();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Failed to reset password');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={v => !v && onClose()}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>Reset Password — {user?.username}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          {error && <p className="rounded bg-destructive/10 p-2 text-sm text-destructive">{error}</p>}
          <div className="space-y-1">
            <Label>New Password</Label>
            <Input type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="Min. 6 characters" />
          </div>
          <div className="space-y-1">
            <Label>Confirm Password</Label>
            <Input type="password" value={confirm} onChange={e => setConfirm(e.target.value)} placeholder="Re-enter new password" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={saving}>Cancel</Button>
          <Button onClick={handleReset} disabled={saving}>{saving ? 'Resetting…' : 'Reset Password'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────── //

export default function UserManagementPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [users, setUsers] = useState<ManagedUser[]>([]);
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
      toast.error('Failed to load users');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchUsers(); }, [fetchUsers]);

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
          <h1 className="text-2xl font-semibold tracking-tight">User Management</h1>
          <p className="text-sm text-muted-foreground">Create and manage user accounts and their roles</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={fetchUsers} disabled={loading}>
            <RefreshCw className={`h-4 w-4 mr-1 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
          <Button size="sm" onClick={() => { setEditTarget(null); setAddEditOpen(true); }}>
            <Plus className="h-4 w-4 mr-1" />
            Add User
          </Button>
        </div>
      </div>

      <div className="rounded-lg border bg-card">
        {loading ? (
          <p className="text-center text-sm text-muted-foreground py-10">Loading users…</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-xs text-muted-foreground">
                  <th className="px-4 py-3 text-left font-medium">Name</th>
                  <th className="px-4 py-3 text-left font-medium">Username</th>
                  <th className="px-4 py-3 text-left font-medium">Role</th>
                  <th className="px-4 py-3 text-left font-medium">Email</th>
                  <th className="px-4 py-3 text-left font-medium">Phone</th>
                  <th className="px-4 py-3 text-left font-medium">Status</th>
                  <th className="px-4 py-3 text-right font-medium">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {users.map(u => (
                  <tr key={u.id} className="hover:bg-muted/30">
                    <td className="px-4 py-3 font-medium">{u.full_name || '—'}</td>
                    <td className="px-4 py-3 font-mono text-xs">{u.username}</td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${ROLE_STYLES[u.role] ?? 'bg-gray-100 text-gray-600'}`}>
                        {ROLE_LABELS[u.role] ?? u.role}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">{u.email || '—'}</td>
                    <td className="px-4 py-3 text-muted-foreground">{u.phone || '—'}</td>
                    <td className="px-4 py-3">
                      {u.is_active
                        ? <span className="inline-flex items-center gap-1 text-xs text-green-600"><span className="h-1.5 w-1.5 rounded-full bg-green-500 inline-block" />Active</span>
                        : <span className="inline-flex items-center gap-1 text-xs text-gray-400"><span className="h-1.5 w-1.5 rounded-full bg-gray-300 inline-block" />Inactive</span>
                      }
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex gap-1 justify-end">
                        <Button size="icon" variant="ghost" className="h-7 w-7" title="Edit user"
                          onClick={() => { setEditTarget(u); setAddEditOpen(true); }}>
                          <Edit2 className="h-3.5 w-3.5" />
                        </Button>
                        <Button size="icon" variant="ghost" className="h-7 w-7" title="Reset password"
                          onClick={() => { setResetTarget(u); setResetOpen(true); }}>
                          <KeyRound className="h-3.5 w-3.5 text-orange-500" />
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
                {users.length === 0 && (
                  <tr><td colSpan={7} className="px-4 py-10 text-center text-sm text-muted-foreground">No users found.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <AddEditDialog
        open={addEditOpen}
        user={editTarget}
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
