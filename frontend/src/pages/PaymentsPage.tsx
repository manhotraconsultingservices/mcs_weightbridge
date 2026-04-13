import { useEffect, useState, useCallback } from 'react';
import { Plus, Search, CreditCard, ArrowDownCircle, ArrowUpCircle } from 'lucide-react';
import { PrintButton } from '@/components/PrintButton';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import api from '@/services/api';
import type { Party, Invoice } from '@/types';

const PAYMENT_MODES = ['cash', 'cheque', 'upi', 'bank_transfer', 'neft', 'rtgs'];

interface PaymentRecord {
  id: string;
  receipt_no?: string;
  voucher_no?: string;
  receipt_date?: string;
  voucher_date?: string;
  party_id: string;
  party_name: string;
  amount: number;
  payment_mode: string;
  reference_no: string | null;
  bank_name: string | null;
  notes: string | null;
  tally_synced: boolean;
  created_at: string;
}

interface AllocationRow {
  invoice_id: string;
  invoice_no: string | null;
  balance: number;
  amount: string;
}

interface PaymentDialogProps {
  open: boolean;
  type: 'receipt' | 'voucher';
  onClose: () => void;
  onSaved: () => void;
}

function PaymentDialog({ open, type, onClose, onSaved }: PaymentDialogProps) {
  const [parties, setParties] = useState<Party[]>([]);
  const [partyId, setPartyId] = useState('');
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [amount, setAmount] = useState('');
  const [mode, setMode] = useState('cash');
  const [refNo, setRefNo] = useState('');
  const [bankName, setBankName] = useState('');
  const [notes, setNotes] = useState('');
  const [outstandingInvoices, setOutstandingInvoices] = useState<Invoice[]>([]);
  const [allocations, setAllocations] = useState<AllocationRow[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (open) {
      setPartyId(''); setDate(new Date().toISOString().slice(0, 10));
      setAmount(''); setMode('cash'); setRefNo(''); setBankName('');
      setNotes(''); setAllocations([]); setError('');
      api.get<Party[] | { items: Party[] }>('/api/v1/parties').then(r => {
        const d = r.data;
        setParties(Array.isArray(d) ? d : (d.items ?? []));
      }).catch(() => {});
    }
  }, [open]);

  useEffect(() => {
    if (!partyId) { setOutstandingInvoices([]); setAllocations([]); return; }
    const invType = type === 'receipt' ? 'sale' : 'purchase';
    api.get<{ items: Invoice[] }>(`/api/v1/invoices?invoice_type=${invType}&party_id=${partyId}&page=1&page_size=50`)
      .then(r => {
        const unpaid = r.data.items.filter(i => i.payment_status !== 'paid' && i.status === 'final');
        setOutstandingInvoices(unpaid);
        setAllocations(unpaid.map(i => ({
          invoice_id: i.id,
          invoice_no: i.invoice_no,
          balance: i.grand_total - i.amount_paid,
          amount: '',
        })));
      })
      .catch(() => {});
  }, [partyId, type]);

  const totalAllocated = allocations.reduce((s, a) => s + (parseFloat(a.amount) || 0), 0);

  async function handleSave() {
    if (!partyId) { setError('Select a party'); return; }
    if (!amount || parseFloat(amount) <= 0) { setError('Enter a valid amount'); return; }
    setSaving(true); setError('');
    try {
      const allocs = allocations
        .filter(a => parseFloat(a.amount) > 0)
        .map(a => ({ invoice_id: a.invoice_id, amount: parseFloat(a.amount) }));
      const url = type === 'receipt' ? '/api/v1/payments/receipts' : '/api/v1/payments/vouchers';
      const dateKey = type === 'receipt' ? 'receipt_date' : 'voucher_date';
      await api.post(url, {
        [dateKey]: date,
        party_id: partyId,
        amount: parseFloat(amount),
        payment_mode: mode,
        reference_no: refNo || null,
        bank_name: bankName || null,
        notes: notes || null,
        allocations: allocs,
      });
      onSaved();
      onClose();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Failed to save payment');
    } finally {
      setSaving(false);
    }
  }

  const title = type === 'receipt' ? 'New Payment Receipt' : 'New Payment Voucher';

  return (
    <Dialog open={open} onOpenChange={v => !v && onClose()}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          {error && <p className="rounded bg-destructive/10 p-2 text-sm text-destructive">{error}</p>}

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>{type === 'receipt' ? 'Customer' : 'Supplier'} *</Label>
              <Select value={partyId || undefined} onValueChange={v => setPartyId(v ?? '')}>
                <SelectTrigger>
                  <span className="truncate text-left flex-1">
                    {partyId
                      ? (parties.find(p => p.id === partyId)?.name ?? '…')
                      : <span className="text-muted-foreground">Select party</span>}
                  </span>
                </SelectTrigger>
                <SelectContent>
                  {parties
                    .filter(p => type === 'receipt'
                      ? p.party_type === 'customer' || p.party_type === 'both'
                      : p.party_type === 'supplier' || p.party_type === 'both')
                    .map(p => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label>Date *</Label>
              <Input type="date" value={date} onChange={e => setDate(e.target.value)} />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>Amount (₹) *</Label>
              <Input type="number" min="0" value={amount} onChange={e => setAmount(e.target.value)} placeholder="0.00" />
            </div>
            <div className="space-y-1">
              <Label>Payment Mode *</Label>
              <Select value={mode} onValueChange={v => setMode(v ?? 'cash')}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {PAYMENT_MODES.map(m => <SelectItem key={m} value={m}>{m.replace('_', ' ').toUpperCase()}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          </div>

          {(mode === 'cheque' || mode === 'upi' || mode === 'bank_transfer' || mode === 'neft' || mode === 'rtgs') && (
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label>Reference No</Label>
                <Input value={refNo} onChange={e => setRefNo(e.target.value)} placeholder="Cheque no / UTR / TXN" />
              </div>
              <div className="space-y-1">
                <Label>Bank Name</Label>
                <Input value={bankName} onChange={e => setBankName(e.target.value)} placeholder="Bank name" />
              </div>
            </div>
          )}

          <div className="space-y-1">
            <Label>Notes</Label>
            <Input value={notes} onChange={e => setNotes(e.target.value)} placeholder="Optional remarks" />
          </div>

          {/* Invoice allocation */}
          {outstandingInvoices.length > 0 && (
            <div className="border-t pt-3 space-y-2">
              <div className="flex items-center justify-between">
                <p className="text-sm font-medium">Settle Outstanding Invoices</p>
                <p className="text-xs text-muted-foreground">Allocated: ₹{totalAllocated.toLocaleString('en-IN')}</p>
              </div>
              <div className="space-y-2 max-h-48 overflow-y-auto">
                {allocations.map((alloc, i) => (
                  <div key={alloc.invoice_id} className="flex items-center gap-2">
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium">{alloc.invoice_no}</p>
                      <p className="text-xs text-muted-foreground">Balance: ₹{alloc.balance.toLocaleString('en-IN')}</p>
                    </div>
                    <Input
                      type="number" min="0" max={alloc.balance}
                      className="w-32 text-right"
                      placeholder="0"
                      value={alloc.amount}
                      onChange={e => setAllocations(prev => prev.map((a, j) =>
                        j === i ? { ...a, amount: e.target.value } : a
                      ))}
                    />
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={handleSave} disabled={saving}>
            {type === 'receipt' ? 'Record Receipt' : 'Record Payment'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

const PAGE_SIZE = 50;

function PaymentList({ type, refreshKey }: { type: 'receipt' | 'voucher'; refreshKey: number }) {
  const [records, setRecords] = useState<PaymentRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [loading, setLoading] = useState(false);

  const fetchRecords = useCallback(async () => {
    setLoading(true);
    try {
      const url = type === 'receipt' ? '/api/v1/payments/receipts' : '/api/v1/payments/vouchers';
      const params = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) });
      if (search) params.set('search', search);
      if (dateFrom) params.set('date_from', dateFrom);
      if (dateTo) params.set('date_to', dateTo);
      const { data } = await api.get<{ items: PaymentRecord[]; total: number }>(`${url}?${params}`);
      setRecords(data.items ?? []);
      setTotal(data.total ?? 0);
    } catch { } finally { setLoading(false); }
  }, [type, page, search, dateFrom, dateTo]);

  useEffect(() => { fetchRecords(); }, [fetchRecords, refreshKey]);
  useEffect(() => { setPage(1); }, [search, dateFrom, dateTo]);

  const totalAmount = records.reduce((s, r) => s + Number(r.amount), 0);
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input className="pl-9" placeholder="Search party, no…" value={search} onChange={e => setSearch(e.target.value)} />
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-xs text-muted-foreground">Date:</span>
          <input type="date" title="From" className="h-9 rounded-md border border-input bg-background px-2 text-xs"
            value={dateFrom} onChange={e => setDateFrom(e.target.value)} />
          <span className="text-xs text-muted-foreground">–</span>
          <input type="date" title="To" className="h-9 rounded-md border border-input bg-background px-2 text-xs"
            value={dateTo} onChange={e => setDateTo(e.target.value)} />
          {(dateFrom || dateTo) && (
            <button className="text-xs text-muted-foreground hover:text-foreground" onClick={() => { setDateFrom(''); setDateTo(''); }}>×</button>
          )}
        </div>
        {records.length > 0 && (
          <p className="text-sm text-muted-foreground">Page total: <span className="font-semibold">₹{totalAmount.toLocaleString('en-IN')}</span></p>
        )}
      </div>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="py-12 text-center text-muted-foreground text-sm">Loading…</div>
          ) : records.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 px-4 text-center">
              <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-muted">
                <CreditCard className="h-8 w-8 text-muted-foreground/40" />
              </div>
              <h3 className="text-sm font-semibold">No {type === 'receipt' ? 'receipts' : 'vouchers'} found</h3>
              <p className="mt-1 max-w-xs text-xs text-muted-foreground">
                {type === 'receipt'
                  ? 'Record a payment received against an invoice to see it here.'
                  : 'Record a payment made to a supplier to see it here.'}
              </p>
            </div>
          ) : (
            <div className="divide-y">
              {records.map(r => {
                const no = r.receipt_no || r.voucher_no || '—';
                const date = r.receipt_date || r.voucher_date || '';
                return (
                  <div key={r.id} className="flex items-center gap-4 px-4 py-3 hover:bg-muted/30 transition-colors">
                    <div className={`h-9 w-9 rounded-full flex items-center justify-center shrink-0 ${type === 'receipt' ? 'bg-green-100' : 'bg-orange-100'}`}>
                      {type === 'receipt'
                        ? <ArrowDownCircle className="h-5 w-5 text-green-700" />
                        : <ArrowUpCircle className="h-5 w-5 text-orange-700" />}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <p className="font-medium text-sm">{no}</p>
                        <Badge variant="outline" className="text-[10px]">{r.payment_mode.replace('_', ' ').toUpperCase()}</Badge>
                      </div>
                      <p className="text-xs text-muted-foreground">{r.party_name} · {date}</p>
                      {r.reference_no && <p className="text-xs text-muted-foreground">Ref: {r.reference_no}</p>}
                    </div>
                    <p className={`font-semibold text-sm shrink-0 ${type === 'receipt' ? 'text-green-700' : 'text-orange-700'}`}>
                      {type === 'receipt' ? '+' : '−'}₹{Number(r.amount).toLocaleString('en-IN')}
                    </p>
                    <PrintButton
                      url={`/api/v1/payments/${type === 'receipt' ? 'receipts' : 'vouchers'}/${r.id}/pdf`}
                      a4Url={`/api/v1/payments/${type === 'receipt' ? 'receipts' : 'vouchers'}/${r.id}/pdf`}
                      iconOnly
                    />
                  </div>
                );
              })}
            </div>
          )}

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between px-4 py-3 border-t text-sm">
              <span className="text-muted-foreground">
                Showing {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, total)} of {total}
              </span>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>Prev</Button>
                <span className="flex items-center px-2">{page} / {totalPages}</span>
                <Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>Next</Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default function PaymentsPage() {
  const [tab, setTab] = useState('receipts');
  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogType, setDialogType] = useState<'receipt' | 'voucher'>('receipt');
  const [refreshKey, setRefreshKey] = useState(0);

  function openDialog(type: 'receipt' | 'voucher') {
    setDialogType(type);
    setDialogOpen(true);
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Payments</h1>
          <p className="text-muted-foreground">Receipts from customers · Vouchers to suppliers</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => openDialog('voucher')}>
            <ArrowUpCircle className="mr-2 h-4 w-4" /> New Voucher
          </Button>
          <Button onClick={() => openDialog('receipt')}>
            <Plus className="mr-2 h-4 w-4" /> New Receipt
          </Button>
        </div>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="receipts">Receipts (Inbound)</TabsTrigger>
          <TabsTrigger value="vouchers">Vouchers (Outbound)</TabsTrigger>
        </TabsList>
        <TabsContent value="receipts" className="mt-4">
          <PaymentList type="receipt" refreshKey={refreshKey} />
        </TabsContent>
        <TabsContent value="vouchers" className="mt-4">
          <PaymentList type="voucher" refreshKey={refreshKey} />
        </TabsContent>
      </Tabs>

      <PaymentDialog
        open={dialogOpen}
        type={dialogType}
        onClose={() => setDialogOpen(false)}
        onSaved={() => setRefreshKey(k => k + 1)}
      />
    </div>
  );
}
