import { useEffect, useState } from 'react';
import api from '@/services/api';
import { toast } from 'sonner';
import { KeyRound, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';

/**
 * Admin control to create / reset / disable a customer's portal login.
 * Self-contained: fetches its own status, no props beyond the party id.
 */
interface AccountStatus { exists: boolean; email?: string; is_active?: boolean; last_login_at?: string | null }

export default function PortalAccessDialog({ partyId, partyName }: { partyId: string; partyName?: string }) {
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<AccountStatus | null>(null);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);

  async function refresh() {
    try { const r = await api.get<AccountStatus>(`/parties/${partyId}/portal-account`); setStatus(r.data); if (r.data.email) setEmail(r.data.email); }
    catch { setStatus({ exists: false }); }
  }
  useEffect(() => { if (open) refresh(); /* eslint-disable-next-line */ }, [open]);

  async function save() {
    if (!email.trim() || password.length < 6) { toast.error('Email + a 6+ char password are required'); return; }
    setBusy(true);
    try {
      await api.post(`/api/v1/parties/${partyId}/portal-account`, { email: email.trim(), password });
      toast.success('Portal access enabled — share /portal + these credentials with the customer');
      setPassword(''); refresh();
    } catch (e: unknown) { toast.error((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed'); }
    finally { setBusy(false); }
  }
  async function resetPw() {
    if (password.length < 6) { toast.error('Enter a 6+ char new password'); return; }
    setBusy(true);
    try { await api.post(`/api/v1/parties/${partyId}/portal-account/reset-password`, { password }); toast.success('Password reset'); setPassword(''); refresh(); }
    catch { toast.error('Failed'); } finally { setBusy(false); }
  }
  async function disable() {
    if (!confirm('Disable this customer’s portal login?')) return;
    try { await api.delete(`/api/v1/parties/${partyId}/portal-account`); toast.success('Portal access disabled'); refresh(); }
    catch { toast.error('Failed'); }
  }

  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)} className="gap-1.5"><KeyRound className="h-4 w-4" /> Portal Access</Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-sm">
          <DialogHeader><DialogTitle>Portal access — {partyName ?? 'customer'}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            {status?.exists && (
              <div className="rounded-md bg-emerald-50 border border-emerald-200 px-3 py-2 text-xs">
                Active: <b>{status.email}</b> · {status.is_active ? 'enabled' : 'disabled'}
                {status.last_login_at && <> · last login {new Date(status.last_login_at).toLocaleDateString('en-IN')}</>}
              </div>
            )}
            <div className="space-y-1"><Label className="text-xs">Customer email (login)</Label><Input type="email" value={email} onChange={e => setEmail(e.target.value)} /></div>
            <div className="space-y-1"><Label className="text-xs">{status?.exists ? 'New password' : 'Password'}</Label><Input type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="min 6 chars" /></div>
            <p className="text-[11px] text-muted-foreground">The customer signs in at <b>/portal</b> to view invoices, statement & pay by UPI.</p>
          </div>
          <DialogFooter className="flex-wrap gap-2">
            {status?.exists && <Button variant="ghost" size="sm" className="text-red-600" onClick={disable}>Disable</Button>}
            {status?.exists
              ? <Button size="sm" onClick={resetPw} disabled={busy} className="gap-1.5">{busy && <Loader2 className="h-4 w-4 animate-spin" />} Reset Password</Button>
              : <Button size="sm" onClick={save} disabled={busy} className="gap-1.5">{busy && <Loader2 className="h-4 w-4 animate-spin" />} Enable Portal Login</Button>}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
