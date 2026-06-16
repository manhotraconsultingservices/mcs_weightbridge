import { useEffect, useState, useCallback } from 'react';
import { Loader2, LogOut, FileText, IndianRupee, Receipt, KeyRound, Building2, Download } from 'lucide-react';

/**
 * Customer self-service portal — standalone (NOT inside the staff AppLayout).
 * Manages its own customer JWT in sessionStorage('portal_token'). Read-only +
 * change-password + static-UPI pay. Tenant is derived from the subdomain.
 */

const TOKEN_KEY = 'portal_token';
const NAME_KEY = 'portal_party_name';

function tenantSlug(): string {
  const h = window.location.hostname;
  const parts = h.split('.');
  // e.g. manhotra-consulting.weighbridgesetu.com → "manhotra-consulting"
  if (parts.length >= 3 && !['www', 'app', 'platform'].includes(parts[0])) return parts[0];
  return '';
}

async function portalFetch(path: string, opts: RequestInit = {}) {
  const token = sessionStorage.getItem(TOKEN_KEY);
  const res = await fetch(`/api/v1/portal${path}`, {
    ...opts,
    headers: { ...(opts.headers || {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
  if (res.status === 401) { sessionStorage.removeItem(TOKEN_KEY); throw new Error('unauthorized'); }
  return res;
}

const INR = (v: number) => '₹' + Number(v ?? 0).toLocaleString('en-IN', { minimumFractionDigits: 2 });

interface Me { party_name: string; email: string; gstin: string | null; phone: string | null; city: string | null; state: string | null; outstanding: number; credit_limit: number }
interface Inv { id: string; invoice_no: string | null; invoice_type: string; invoice_date: string | null; due_date: string | null; grand_total: number; amount_due: number; payment_status: string; eway_bill_no: string | null }
interface Pay { receipt_no: string; date: string | null; amount: number; mode: string | null }
interface PayInfo { upi_vpa: string; payee_name: string; upi_enabled: boolean; bank_name: string | null; account_no: string | null; ifsc: string | null }

export default function CustomerPortalPage() {
  const [authed, setAuthed] = useState(!!sessionStorage.getItem(TOKEN_KEY));
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  const [tab, setTab] = useState<'invoices' | 'statement' | 'pay' | 'password'>('invoices');
  const [me, setMe] = useState<Me | null>(null);
  const [invoices, setInvoices] = useState<Inv[]>([]);
  const [payments, setPayments] = useState<Pay[]>([]);
  const [payInfo, setPayInfo] = useState<PayInfo | null>(null);

  const loadAll = useCallback(async () => {
    try {
      const [m, i, s, p] = await Promise.all([
        portalFetch('/me'), portalFetch('/invoices'), portalFetch('/statement'), portalFetch('/payment-info'),
      ]);
      setMe(await m.json());
      setInvoices((await i.json()).items ?? []);
      setPayments((await s.json()).payments ?? []);
      setPayInfo(await p.json());
    } catch { setAuthed(false); }
  }, []);

  useEffect(() => { if (authed) loadAll(); }, [authed, loadAll]);

  async function login(e: React.FormEvent) {
    e.preventDefault(); setErr(''); setBusy(true);
    try {
      const body = new URLSearchParams({ email, password, tenant_slug: tenantSlug() });
      const res = await fetch('/api/v1/portal/login', {
        method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body,
      });
      if (!res.ok) { const d = await res.json().catch(() => ({})); throw new Error(d.detail || 'Invalid email or password'); }
      const data = await res.json();
      sessionStorage.setItem(TOKEN_KEY, data.access_token);
      sessionStorage.setItem(NAME_KEY, data.party_name);
      setAuthed(true);
    } catch (e: unknown) { setErr((e as Error).message); } finally { setBusy(false); }
  }

  function logout() {
    sessionStorage.removeItem(TOKEN_KEY); sessionStorage.removeItem(NAME_KEY);
    setAuthed(false); setMe(null);
  }

  async function downloadPdf(inv: Inv) {
    try {
      const res = await portalFetch(`/invoices/${inv.id}/pdf`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      window.open(url, '_blank');
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch { /* ignore */ }
  }

  // ── Login screen ──────────────────────────────────────────────────────────
  if (!authed) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-50 to-slate-200 p-4">
        <form onSubmit={login} className="w-full max-w-sm bg-white rounded-2xl shadow-lg p-6 space-y-4">
          <div className="text-center">
            <Building2 className="h-8 w-8 mx-auto text-emerald-600" />
            <h1 className="text-xl font-bold mt-2">Customer Portal</h1>
            <p className="text-xs text-muted-foreground">View invoices, statement & pay online</p>
          </div>
          <div className="space-y-1">
            <label className="text-xs font-medium">Email</label>
            <input className="w-full h-10 rounded-md border px-3 text-sm" type="email" value={email} onChange={e => setEmail(e.target.value)} autoFocus required />
          </div>
          <div className="space-y-1">
            <label className="text-xs font-medium">Password</label>
            <input className="w-full h-10 rounded-md border px-3 text-sm" type="password" value={password} onChange={e => setPassword(e.target.value)} required />
          </div>
          {err && <p className="text-xs text-red-600">{err}</p>}
          <button type="submit" disabled={busy} className="w-full h-10 rounded-md bg-emerald-600 text-white text-sm font-medium flex items-center justify-center gap-2 disabled:opacity-60">
            {busy && <Loader2 className="h-4 w-4 animate-spin" />} Sign in
          </button>
          <p className="text-[11px] text-center text-muted-foreground">Contact your supplier for portal access credentials.</p>
        </form>
      </div>
    );
  }

  // ── Dashboard ───────────────────────────────────────────────────────────────
  const TABS: { k: typeof tab; label: string; icon: typeof FileText }[] = [
    { k: 'invoices', label: 'Invoices', icon: FileText },
    { k: 'statement', label: 'Payments', icon: Receipt },
    { k: 'pay', label: 'Pay Now', icon: IndianRupee },
    { k: 'password', label: 'Password', icon: KeyRound },
  ];

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="bg-white border-b">
        <div className="max-w-4xl mx-auto px-4 py-3 flex items-center justify-between">
          <div>
            <p className="font-bold">{me?.party_name ?? sessionStorage.getItem(NAME_KEY)}</p>
            <p className="text-xs text-muted-foreground">{me?.email}</p>
          </div>
          <button onClick={logout} className="text-xs flex items-center gap-1 text-muted-foreground hover:text-foreground"><LogOut className="h-4 w-4" /> Sign out</button>
        </div>
      </header>

      <div className="max-w-4xl mx-auto p-4 space-y-4">
        {/* Outstanding card */}
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-xl bg-white border p-4">
            <p className="text-xs text-muted-foreground">Outstanding balance</p>
            <p className={`text-2xl font-bold ${(me?.outstanding ?? 0) > 0 ? 'text-amber-700' : 'text-emerald-700'}`}>{INR(me?.outstanding ?? 0)}</p>
          </div>
          <div className="rounded-xl bg-white border p-4">
            <p className="text-xs text-muted-foreground">Credit limit</p>
            <p className="text-2xl font-bold">{me && me.credit_limit > 0 ? INR(me.credit_limit) : '—'}</p>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 bg-white border rounded-lg p-1 w-fit">
          {TABS.map(t => {
            const Icon = t.icon;
            return (
              <button key={t.k} onClick={() => setTab(t.k)}
                className={`px-3 py-1.5 rounded-md text-xs font-medium flex items-center gap-1.5 ${tab === t.k ? 'bg-emerald-600 text-white' : 'text-muted-foreground hover:bg-slate-100'}`}>
                <Icon className="h-3.5 w-3.5" /> {t.label}
              </button>
            );
          })}
        </div>

        {tab === 'invoices' && (
          <div className="rounded-xl bg-white border overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-xs"><tr className="[&>th]:px-3 [&>th]:py-2 [&>th]:text-left"><th>Invoice</th><th>Date</th><th className="text-right">Total</th><th className="text-right">Due</th><th>Status</th><th></th></tr></thead>
              <tbody>
                {invoices.length === 0 && <tr><td colSpan={6} className="px-3 py-6 text-center text-muted-foreground">No invoices yet.</td></tr>}
                {invoices.map(inv => (
                  <tr key={inv.id} className="border-t [&>td]:px-3 [&>td]:py-2">
                    <td className="font-mono">{inv.invoice_no ?? '—'}{inv.invoice_type !== 'sale' && <span className="ml-1 text-[10px] uppercase text-rose-600">{inv.invoice_type.replace('_note', ' note')}</span>}</td>
                    <td className="text-xs">{inv.invoice_date ? new Date(inv.invoice_date).toLocaleDateString('en-IN') : '—'}</td>
                    <td className="text-right">{INR(inv.grand_total)}</td>
                    <td className="text-right">{INR(inv.amount_due)}</td>
                    <td><span className={`text-[11px] px-2 py-0.5 rounded-full ${inv.payment_status === 'paid' ? 'bg-emerald-100 text-emerald-700' : inv.payment_status === 'partial' ? 'bg-amber-100 text-amber-700' : 'bg-slate-100 text-slate-600'}`}>{inv.payment_status}</span></td>
                    <td className="text-right"><button onClick={() => downloadPdf(inv)} className="inline-flex items-center gap-1 text-xs text-emerald-700 hover:underline"><Download className="h-3.5 w-3.5" /> PDF</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {tab === 'statement' && (
          <div className="rounded-xl bg-white border overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-xs"><tr className="[&>th]:px-3 [&>th]:py-2 [&>th]:text-left"><th>Receipt</th><th>Date</th><th>Mode</th><th className="text-right">Amount</th></tr></thead>
              <tbody>
                {payments.length === 0 && <tr><td colSpan={4} className="px-3 py-6 text-center text-muted-foreground">No payments recorded yet.</td></tr>}
                {payments.map((p, i) => (
                  <tr key={i} className="border-t [&>td]:px-3 [&>td]:py-2">
                    <td className="font-mono text-xs">{p.receipt_no}</td>
                    <td className="text-xs">{p.date ? new Date(p.date).toLocaleDateString('en-IN') : '—'}</td>
                    <td className="text-xs capitalize">{p.mode ?? '—'}</td>
                    <td className="text-right text-emerald-700">{INR(p.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {tab === 'pay' && <PayPanel payInfo={payInfo} outstanding={me?.outstanding ?? 0} />}
        {tab === 'password' && <ChangePasswordPanel />}
      </div>
    </div>
  );
}

function PayPanel({ payInfo, outstanding }: { payInfo: PayInfo | null; outstanding: number }) {
  if (!payInfo) return null;
  const upiLink = payInfo.upi_enabled
    ? `upi://pay?pa=${encodeURIComponent(payInfo.upi_vpa)}&pn=${encodeURIComponent(payInfo.payee_name)}&cu=INR${outstanding > 0 ? `&am=${outstanding.toFixed(2)}` : ''}`
    : '';
  return (
    <div className="rounded-xl bg-white border p-5 space-y-4 max-w-md">
      {payInfo.upi_enabled ? (
        <>
          <div>
            <p className="text-xs text-muted-foreground">Pay via UPI to</p>
            <p className="text-lg font-bold font-mono">{payInfo.upi_vpa}</p>
            <p className="text-xs text-muted-foreground">{payInfo.payee_name}</p>
          </div>
          <a href={upiLink} className="block text-center h-11 leading-[44px] rounded-md bg-emerald-600 text-white text-sm font-medium">
            Open UPI App {outstanding > 0 ? `· ${INR(outstanding)}` : ''}
          </a>
          <p className="text-[11px] text-muted-foreground">On a phone this opens GPay/PhonePe/Paytm. After paying, your supplier will reconcile the receipt against your account.</p>
        </>
      ) : (
        <p className="text-sm text-muted-foreground">Online UPI payment isn't enabled yet. Please use the bank details below.</p>
      )}
      {(payInfo.bank_name || payInfo.account_no) && (
        <div className="border-t pt-3 text-sm space-y-1">
          <p className="text-xs font-semibold text-muted-foreground">Bank transfer</p>
          {payInfo.bank_name && <p>Bank: <b>{payInfo.bank_name}</b></p>}
          {payInfo.account_no && <p>A/C: <b className="font-mono">{payInfo.account_no}</b></p>}
          {payInfo.ifsc && <p>IFSC: <b className="font-mono">{payInfo.ifsc}</b></p>}
        </div>
      )}
    </div>
  );
}

function ChangePasswordPanel() {
  const [cur, setCur] = useState(''); const [nw, setNw] = useState('');
  const [msg, setMsg] = useState(''); const [busy, setBusy] = useState(false);
  async function submit(e: React.FormEvent) {
    e.preventDefault(); setMsg(''); setBusy(true);
    try {
      const res = await portalFetch('/change-password', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ current_password: cur, new_password: nw }),
      });
      if (!res.ok) { const d = await res.json().catch(() => ({})); throw new Error(d.detail || 'Failed'); }
      setMsg('Password updated'); setCur(''); setNw('');
    } catch (e: unknown) { setMsg((e as Error).message); } finally { setBusy(false); }
  }
  return (
    <form onSubmit={submit} className="rounded-xl bg-white border p-5 space-y-3 max-w-sm">
      <div className="space-y-1"><label className="text-xs font-medium">Current password</label><input type="password" className="w-full h-10 rounded-md border px-3 text-sm" value={cur} onChange={e => setCur(e.target.value)} required /></div>
      <div className="space-y-1"><label className="text-xs font-medium">New password</label><input type="password" className="w-full h-10 rounded-md border px-3 text-sm" value={nw} onChange={e => setNw(e.target.value)} required minLength={6} /></div>
      {msg && <p className="text-xs text-muted-foreground">{msg}</p>}
      <button type="submit" disabled={busy} className="h-10 px-4 rounded-md bg-emerald-600 text-white text-sm font-medium disabled:opacity-60">{busy ? 'Saving…' : 'Update password'}</button>
    </form>
  );
}
