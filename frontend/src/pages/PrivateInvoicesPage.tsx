import { useEffect, useState, useCallback, useMemo } from 'react';
import { Plus, Lock, Usb, Shield, AlertTriangle, LogOut, HardDrive } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import api from '@/services/api';
import { useUsbGuard } from '@/hooks/useUsbGuard';
import { TokenDetailModal } from '@/components/TokenDetailModal';
import { DataTable, type ColumnDef } from '@/components/DataTable';

const INR = (v: number) => '₹' + v.toLocaleString('en-IN', { minimumFractionDigits: 2 });
const PAYMENT_MODES = ['cash', 'cheque', 'upi', 'bank_transfer'];

interface PrivateInvoice {
  id: string;
  invoice_no: string;
  invoice_date: string;
  customer_name: string | null;
  vehicle_no: string | null;
  net_weight: number | null;
  rate: number | null;
  amount: number;
  payment_mode: string;
  notes: string | null;
  created_at: string;
  token_no: string | null;
  token_date: string | null;
  gross_weight: number | null;
  tare_weight: number | null;
  token_id: string | null;
}

// Recovery PIN dialog
function RecoveryDialog({ open, onClose, onSuccess }: { open: boolean; onClose: () => void; onSuccess: () => void }) {
  const [pin, setPin] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  async function handleVerify() {
    if (!pin) return;
    setLoading(true); setError('');
    try {
      await api.post('/api/v1/usb-guard/recovery/verify', { pin });
      onSuccess();
      onClose();
    } catch {
      setError('Invalid or expired recovery PIN. Contact administrator.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={v => !v && onClose()}>
      <DialogContent className="max-w-sm">
        <DialogHeader><DialogTitle className="flex items-center gap-2"><Shield className="h-5 w-5 text-orange-500" /> Recovery Access</DialogTitle></DialogHeader>
        <div className="space-y-4">
          <p className="text-sm text-muted-foreground">USB key not detected. Enter the recovery PIN set by administrator to get temporary access.</p>
          {error && <p className="text-sm text-destructive bg-destructive/10 rounded p-2">{error}</p>}
          <div className="space-y-1">
            <Label>Recovery PIN</Label>
            <Input type="password" value={pin} onChange={e => setPin(e.target.value)} placeholder="Enter PIN" onKeyDown={e => e.key === 'Enter' && handleVerify()} autoFocus />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={handleVerify} disabled={loading || !pin}>Verify PIN</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// New invoice dialog
function NewPrivateInvoiceDialog({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: () => void }) {
  const [form, setForm] = useState({
    invoice_date: new Date().toISOString().slice(0, 10),
    customer_name: '',
    vehicle_no: '',
    net_weight: '',
    rate: '',
    amount: '',
    payment_mode: 'cash',
    notes: '',
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (open) {
      setForm({ invoice_date: new Date().toISOString().slice(0, 10), customer_name: '', vehicle_no: '', net_weight: '', rate: '', amount: '', payment_mode: 'cash', notes: '' });
      setError('');
    }
  }, [open]);

  // Auto-calc amount from net_weight * rate
  useEffect(() => {
    const nw = parseFloat(form.net_weight);
    const rate = parseFloat(form.rate);
    if (nw > 0 && rate > 0) {
      setForm(f => ({ ...f, amount: (nw * rate).toFixed(2) }));
    }
  }, [form.net_weight, form.rate]);

  async function handleSave() {
    if (!form.amount || parseFloat(form.amount) <= 0) { setError('Amount is required'); return; }
    setSaving(true); setError('');
    try {
      await api.post('/api/v1/private-invoices', {
        invoice_date: form.invoice_date,
        customer_name: form.customer_name || null,
        vehicle_no: form.vehicle_no || null,
        net_weight: parseFloat(form.net_weight) || null,
        rate: parseFloat(form.rate) || null,
        amount: parseFloat(form.amount),
        payment_mode: form.payment_mode,
        notes: form.notes || null,
      });
      onCreated();
      onClose();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Failed to save');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={v => !v && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader><DialogTitle>New Supplement Entry</DialogTitle></DialogHeader>
        <div className="space-y-3">
          {error && <p className="text-sm text-destructive bg-destructive/10 rounded p-2">{error}</p>}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>Date *</Label>
              <Input type="date" value={form.invoice_date} onChange={e => setForm(f => ({ ...f, invoice_date: e.target.value }))} />
            </div>
            <div className="space-y-1">
              <Label>Payment Mode</Label>
              <Select value={form.payment_mode} onValueChange={v => setForm(f => ({ ...f, payment_mode: v ?? 'cash' }))}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>{PAYMENT_MODES.map(m => <SelectItem key={m} value={m}>{m.replace('_', ' ').toUpperCase()}</SelectItem>)}</SelectContent>
              </Select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>Customer Name</Label>
              <Input value={form.customer_name} onChange={e => setForm(f => ({ ...f, customer_name: e.target.value }))} placeholder="Name" />
            </div>
            <div className="space-y-1">
              <Label>Vehicle No</Label>
              <Input value={form.vehicle_no} onChange={e => setForm(f => ({ ...f, vehicle_no: e.target.value.toUpperCase() }))} placeholder="MH12AB1234" />
            </div>
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div className="space-y-1">
              <Label>Net Weight (MT)</Label>
              <Input type="number" min="0" step="0.001" value={form.net_weight} onChange={e => setForm(f => ({ ...f, net_weight: e.target.value }))} placeholder="0.000" />
            </div>
            <div className="space-y-1">
              <Label>Rate (₹/MT)</Label>
              <Input type="number" min="0" step="0.01" value={form.rate} onChange={e => setForm(f => ({ ...f, rate: e.target.value }))} placeholder="0.00" />
            </div>
            <div className="space-y-1">
              <Label>Amount (₹) *</Label>
              <Input type="number" min="0" step="0.01" value={form.amount} onChange={e => setForm(f => ({ ...f, amount: e.target.value }))} placeholder="0.00" className="font-semibold" />
            </div>
          </div>
          <div className="space-y-1">
            <Label>Notes</Label>
            <Input value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} placeholder="Optional remarks" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={handleSave} disabled={saving}>Save Invoice</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function PrivateInvoicesPage() {
  const { authorized, method, expires_at, loading: usbLoading, refresh, clientAuth, revokeSession, backupNow, hasBackupDir } = useUsbGuard();
  const [invoices, setInvoices] = useState<PrivateInvoice[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [listLoading, setListLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [recoveryOpen, setRecoveryOpen] = useState(false);
  const [tokenModalId, setTokenModalId] = useState<string | null>(null);
  const [usbError, setUsbError] = useState('');
  const [usbLoading2, setUsbLoading2] = useState(false);

  // Column definitions for the DataTable
  const columns = useMemo<ColumnDef<PrivateInvoice>[]>(() => [
    {
      key: 'invoice_no',
      label: 'Invoice No',
      type: 'string',
      accessor: r => r.invoice_no,
      format: (v) => (
        <span className="font-mono text-xs font-semibold text-purple-700">{String(v)}</span>
      ),
    },
    {
      key: 'invoice_date',
      label: 'Date',
      type: 'date',
      accessor: r => r.invoice_date,
      format: (v) => <span className="text-muted-foreground">{String(v)}</span>,
    },
    {
      key: 'customer_name',
      label: 'Customer',
      type: 'string',
      accessor: r => r.customer_name ?? '',
    },
    {
      key: 'vehicle_no',
      label: 'Vehicle',
      type: 'string',
      accessor: r => r.vehicle_no ?? '',
      format: (v) => v ? <span className="font-mono text-xs">{String(v)}</span> : <span>—</span>,
    },
    {
      key: 'token_no',
      label: 'Token',
      type: 'string',
      accessor: r => r.token_no ?? '',
      sortable: false,
      filterable: false,
      format: (_v, row) => row.token_no ? (
        <span>
          <button
            className="font-mono font-semibold text-primary hover:underline cursor-pointer text-xs"
            onClick={() => row.token_id && setTokenModalId(row.token_id)}
            title="View token details"
          >
            #{row.token_no}
          </button>
          {row.token_date && <span className="block text-[10px] text-muted-foreground">{row.token_date}</span>}
        </span>
      ) : <span>—</span>,
    },
    {
      key: 'net_weight',
      label: 'Net Wt (MT)',
      type: 'number',
      align: 'right',
      accessor: r => r.net_weight,
      format: (v) => v != null ? Number(v).toLocaleString('en-IN', { maximumFractionDigits: 3 }) : '—',
      exportValue: r => r.net_weight != null ? r.net_weight : '',
    },
    {
      key: 'rate',
      label: 'Rate',
      type: 'number',
      align: 'right',
      accessor: r => r.rate,
      format: (v) => v != null ? INR(Number(v)) : '—',
      exportValue: r => r.rate != null ? r.rate : '',
    },
    {
      key: 'amount',
      label: 'Amount',
      type: 'number',
      align: 'right',
      accessor: r => r.amount,
      format: (v) => <span className="font-semibold">{INR(Number(v ?? 0))}</span>,
      exportValue: r => r.amount,
    },
    {
      key: 'payment_mode',
      label: 'Mode',
      type: 'enum',
      enumOptions: PAYMENT_MODES,
      accessor: r => r.payment_mode,
      format: (v) => (
        <span className="text-xs bg-muted px-1.5 py-0.5 rounded">{String(v).toUpperCase()}</span>
      ),
    },
  ], []);

  const load = useCallback(async () => {
    if (!authorized) return;
    setListLoading(true);
    try {
      const { data } = await api.get<{ items: PrivateInvoice[]; total: number }>(`/api/v1/private-invoices?page=${page}&page_size=50`);
      setInvoices(data.items);
      setTotal(data.total);
    } catch {
      // ignore
    } finally { setListLoading(false); }
  }, [authorized, page]);

  useEffect(() => { load(); }, [load]);

  const totalAmount = invoices.reduce((s, i) => s + i.amount, 0);

  if (usbLoading) {
    return <div className="flex items-center justify-center h-64 text-muted-foreground text-sm">Checking USB status...</div>;
  }

  /**
   * Open USB key file via File System Access API (showOpenFilePicker).
   * This gives us a persistent FileSystemFileHandle that can be re-read on
   * every poll — so the moment the pendrive is physically removed, re-read
   * fails and access is immediately revoked.
   *
   * Falls back to <input type="file"> on browsers that don't support the API
   * (Firefox, older Safari) — but without live removal detection.
   */
  async function handleUsbAuth() {
    setUsbError(''); setUsbLoading2(true);
    try {
      if (window.showOpenFilePicker) {
        // Modern path — persistent handle, live pendrive detection
        const [handle] = await window.showOpenFilePicker({
          multiple: false,
          types: [{ description: 'Weighbridge Key File', accept: { '*/*': ['.weighbridge_key'] } }],
          excludeAcceptAllOption: false,
        });
        await clientAuth(handle);
      } else {
        // Fallback for Firefox / older browsers — one-time file read
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = '.weighbridge_key,*';
        input.onchange = async () => {
          const file = input.files?.[0];
          if (!file) { setUsbLoading2(false); return; }
          // Wrap in a minimal FileSystemFileHandle-like object
          const fakeHandle = { name: file.name, getFile: async () => file };
          try {
            await clientAuth(fakeHandle);
          } catch (err: unknown) {
            const msg = err instanceof Error ? err.message : '';
            setUsbError(msg || 'Authentication failed. Contact administrator.');
          } finally {
            setUsbLoading2(false);
          }
        };
        input.click();
        return; // onchange handles setUsbLoading2(false)
      }
    } catch (err: unknown) {
      if ((err as { name?: string }).name === 'AbortError') { /* user cancelled */ }
      else {
        const msg = err instanceof Error ? err.message : '';
        setUsbError(msg || 'Authentication failed. Invalid key or not registered. Contact administrator.');
      }
    } finally {
      setUsbLoading2(false);
    }
  }

  if (!authorized) {
    return (
      <div className="flex flex-col items-center justify-center h-[60vh] gap-6">
        <div className="h-20 w-20 rounded-full bg-red-100 flex items-center justify-center">
          <Lock className="h-10 w-10 text-red-500" />
        </div>
        <div className="text-center">
          <h2 className="text-xl font-semibold">USB Key Required</h2>
          <p className="text-muted-foreground mt-1 text-sm max-w-sm">
            Insert your USB key and click "Authenticate with USB" to select the key file from your drive.
            The server also automatically detects USB keys inserted into the server machine.
          </p>
        </div>
        {usbError && <p className="text-sm text-destructive bg-destructive/10 rounded px-4 py-2 max-w-sm text-center">{usbError}</p>}
        <div className="flex flex-col items-center gap-3">
          <div className="flex gap-3">
            <Button onClick={handleUsbAuth} disabled={usbLoading2}>
              <Usb className="mr-2 h-4 w-4" />
              {usbLoading2 ? 'Authenticating...' : 'Authenticate with USB'}
            </Button>
            <Button variant="outline" onClick={refresh}>Check Again</Button>
          </div>
          <Button variant="ghost" size="sm" onClick={() => setRecoveryOpen(true)}>
            <Shield className="mr-2 h-3 w-3" /> Use Recovery PIN
          </Button>
        </div>
        <RecoveryDialog open={recoveryOpen} onClose={() => setRecoveryOpen(false)} onSuccess={refresh} />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Supplement</h1>
          <div className="flex items-center gap-2 mt-1">
            {(method === 'usb' || method === 'client_usb') ? (
              <span className="flex items-center gap-1 text-xs text-green-700 bg-green-100 px-2 py-0.5 rounded-full">
                <Usb className="h-3 w-3" /> {method === 'client_usb' ? 'Client USB Key Active' : 'USB Key Active'}
                {method === 'client_usb' && expires_at ? ` · Expires ${new Date(expires_at).toLocaleString('en-IN')}` : ''}
              </span>
            ) : (
              <span className="flex items-center gap-1 text-xs text-orange-700 bg-orange-100 px-2 py-0.5 rounded-full">
                <AlertTriangle className="h-3 w-3" /> Recovery Session · Expires {expires_at ? new Date(expires_at).toLocaleString('en-IN') : ''}
              </span>
            )}
            <span className="text-xs text-muted-foreground">{total} invoices</span>
          </div>
        </div>
        <div className="flex gap-2">
          {hasBackupDir ? (
            <Button variant="outline" size="sm" onClick={backupNow} title="Save encrypted backup to USB now">
              <HardDrive className="mr-2 h-4 w-4 text-green-600" /> Backup Now
            </Button>
          ) : (
            <Button variant="ghost" size="sm" title="Re-authenticate USB to enable auto-backup" disabled className="text-muted-foreground">
              <HardDrive className="mr-2 h-4 w-4" /> No backup dir
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={revokeSession} title="Lock — revoke USB session immediately">
            <LogOut className="mr-2 h-4 w-4 text-red-500" /> Lock
          </Button>
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="mr-2 h-4 w-4" /> New Invoice
          </Button>
        </div>
      </div>

      <DataTable<PrivateInvoice>
        id="privateinvoices.main"
        data={invoices}
        columns={columns}
        loading={listLoading}
        rowKey={r => r.id}
        exportFilename="private-invoices"
        defaultSort={{ key: 'invoice_date', direction: 'desc' }}
        emptyMessage="No private invoices yet"
        toolbarLeft={
          invoices.length > 0 ? (
            <span className="text-sm text-muted-foreground">
              Total: <span className="font-bold text-foreground">{INR(totalAmount)}</span>
            </span>
          ) : undefined
        }
      />

      {total > 50 && (
        <div className="flex justify-between items-center py-2 text-sm">
          <span className="text-muted-foreground">Showing {(page - 1) * 50 + 1}–{Math.min(page * 50, total)} of {total}</span>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>Prev</Button>
            <Button variant="outline" size="sm" disabled={page * 50 >= total} onClick={() => setPage(p => p + 1)}>Next</Button>
          </div>
        </div>
      )}

      <NewPrivateInvoiceDialog open={createOpen} onClose={() => setCreateOpen(false)} onCreated={load} />
      <TokenDetailModal tokenId={tokenModalId} onClose={() => setTokenModalId(null)} />
    </div>
  );
}
