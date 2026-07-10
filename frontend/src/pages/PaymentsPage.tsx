import { useEffect, useState, useCallback, useMemo } from 'react';
import { Plus, Search, ArrowUpCircle } from 'lucide-react';
import { MobileTabSelect } from '@/components/MobileTabSelect';
import { useTranslation } from 'react-i18next';
import { PrintButton } from '@/components/PrintButton';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { DataTable, type ColumnDef } from '@/components/DataTable';
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
  const { t } = useTranslation();
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

  const title = type === 'receipt' ? t('payment.newReceipt') : t('payment.newVoucher');

  return (
    <Dialog open={open} onOpenChange={v => !v && onClose()}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          {error && <p className="rounded bg-destructive/10 p-2 text-sm text-destructive">{error}</p>}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>{type === 'receipt' ? t('payment.customer') : t('payment.supplier')} *</Label>
              <Select value={partyId || undefined} onValueChange={v => setPartyId(v ?? '')}>
                <SelectTrigger>
                  <span className="truncate text-left flex-1">
                    {partyId
                      ? (parties.find(p => p.id === partyId)?.name ?? '…')
                      : <span className="text-muted-foreground">{t('payment.selectParty')}</span>}
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
              <Label>{t('common.date')} *</Label>
              <Input type="date" value={date} onChange={e => setDate(e.target.value)} />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>{t('payment.amount')} (₹) *</Label>
              <Input type="number" min="0" value={amount} onChange={e => setAmount(e.target.value)} placeholder="0.00" />
            </div>
            <div className="space-y-1">
              <Label>{t('payment.paymentMode')} *</Label>
              <Select value={mode} onValueChange={v => setMode(v ?? 'cash')}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {PAYMENT_MODES.map(m => <SelectItem key={m} value={m}>{m.replace('_', ' ').toUpperCase()}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          </div>

          {(mode === 'cheque' || mode === 'upi' || mode === 'bank_transfer' || mode === 'neft' || mode === 'rtgs') && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label>{t('payment.reference')}</Label>
                <Input value={refNo} onChange={e => setRefNo(e.target.value)} placeholder={t('payment.chequeUtr')} />
              </div>
              <div className="space-y-1">
                <Label>{t('invoice.bankName')}</Label>
                <Input value={bankName} onChange={e => setBankName(e.target.value)} placeholder={t('payment.bankCol')} />
              </div>
            </div>
          )}

          <div className="space-y-1">
            <Label>{t('common.notes')}</Label>
            <Input value={notes} onChange={e => setNotes(e.target.value)} placeholder={t('payment.optionalRemarks')} />
          </div>

          {/* Invoice allocation */}
          {outstandingInvoices.length > 0 && (
            <div className="border-t pt-3 space-y-2">
              <div className="flex items-center justify-between">
                <p className="text-sm font-medium">{t('payment.settleInvoices')}</p>
                <p className="text-xs text-muted-foreground">{t('payment.allocated')}: ₹{totalAllocated.toLocaleString('en-IN')}</p>
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

          {/* Unallocated → advance / on-account credit */}
          {(parseFloat(amount) || 0) - totalAllocated > 0.05 && (
            <div className="rounded-lg border border-emerald-200 bg-emerald-50/60 p-2.5 text-xs">
              <span className="font-semibold text-emerald-700">
                ₹{((parseFloat(amount) || 0) - totalAllocated).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
              </span>{' '}
              <span className="text-emerald-800">
                will be recorded as an {type === 'receipt' ? 'advance from this customer' : 'advance to this supplier'} (on account)
                — auto-applied to their next {type === 'receipt' ? 'sale' : 'purchase'} bills.
              </span>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>{t('common.cancel')}</Button>
          <Button onClick={handleSave} disabled={saving}>
            {type === 'receipt' ? t('payment.recordReceipt') : t('payment.recordVoucher')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

const PAGE_SIZE = 50;

function PaymentList({ type, refreshKey }: { type: 'receipt' | 'voucher'; refreshKey: number }) {
  const { t } = useTranslation();
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
          <span className="text-xs text-muted-foreground">{t('common.date')}:</span>
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
          <p className="text-sm text-muted-foreground">{t('payment.pageTotal')}: <span className="font-semibold">₹{totalAmount.toLocaleString('en-IN')}</span></p>
        )}
      </div>

      <PaymentsTable type={type} records={records} loading={loading} />
      {totalPages > 1 && (
        <div className="flex items-center justify-between px-1 py-2 text-sm">
          <span className="text-muted-foreground">
            {t('payment.showingOf', { from: (page - 1) * PAGE_SIZE + 1, to: Math.min(page * PAGE_SIZE, total), total })}
          </span>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>{t('invoice.previous')}</Button>
            <span className="flex items-center px-2">{page} / {totalPages}</span>
            <Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>{t('common.next')}</Button>
          </div>
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ //
// Payments DataTable (shared between receipts + vouchers)
// ------------------------------------------------------------------ //
function PaymentsTable({
  type, records, loading,
}: {
  type: 'receipt' | 'voucher';
  records: PaymentRecord[];
  loading: boolean;
}) {
  const { t } = useTranslation();

  const columns = useMemo<ColumnDef<PaymentRecord>[]>(() => [
    {
      key: 'no', label: type === 'receipt' ? t('payment.receiptNo') : t('payment.voucherNo'),
      accessor: r => r.receipt_no || r.voucher_no || '',
      className: 'font-mono text-xs font-medium',
    },
    {
      key: 'date', label: t('common.date'), type: 'date',
      accessor: r => r.receipt_date || r.voucher_date || '',
      format: v => v ? new Date(String(v)).toLocaleDateString('en-IN') : '—',
      className: 'text-muted-foreground',
    },
    { key: 'party_name', label: t('payment.party'), accessor: r => r.party_name },
    {
      key: 'payment_mode', label: t('payment.modeCol'), type: 'enum',
      enumOptions: PAYMENT_MODES,
      accessor: r => r.payment_mode,
      format: v => <Badge variant="outline" className="text-[10px]">{String(v).replace('_', ' ').toUpperCase()}</Badge>,
    },
    {
      key: 'amount', label: t('payment.amount'), type: 'number', align: 'right',
      accessor: r => r.amount,
      format: v => (
        <span className={`font-semibold ${type === 'receipt' ? 'text-green-700' : 'text-orange-700'}`}>
          {type === 'receipt' ? '+' : '−'}₹{Number(v).toLocaleString('en-IN')}
        </span>
      ),
    },
    { key: 'reference_no', label: t('payment.reference'), accessor: r => r.reference_no ?? '', className: 'text-xs text-muted-foreground' },
    { key: 'bank_name', label: t('payment.bankCol'), defaultVisible: false, accessor: r => r.bank_name ?? '', className: 'text-xs' },
    { key: 'notes', label: t('common.notes'), defaultVisible: false, accessor: r => r.notes ?? '' },
    {
      key: 'tally_synced', label: t('payment.tallyCol'), type: 'enum', align: 'center', defaultVisible: false,
      enumOptions: [t('payment.synced'), t('payment.pendingSync')],
      accessor: r => r.tally_synced ? t('payment.synced') : t('payment.pendingSync'),
      format: v => v === t('payment.synced')
        ? <Badge className="bg-green-100 text-green-700 text-[10px]">{t('payment.synced')}</Badge>
        : <Badge variant="secondary" className="text-[10px]">{t('payment.pendingSync')}</Badge>,
    },
  ], [type, t]);

  return (
    <DataTable<PaymentRecord>
      id={`payments.${type}`}
      loading={loading}
      data={records}
      columns={columns}
      rowKey={r => r.id}
      exportFilename={type === 'receipt' ? 'payment-receipts' : 'payment-vouchers'}
      defaultSort={{ key: 'date', direction: 'desc' }}
      emptyMessage={type === 'receipt' ? t('payment.noReceipts') : t('payment.noVouchers')}
      rowActions={r => (
        <PrintButton
          url={`/api/v1/payments/${type === 'receipt' ? 'receipts' : 'vouchers'}/${r.id}/pdf`}
          a4Url={`/api/v1/payments/${type === 'receipt' ? 'receipts' : 'vouchers'}/${r.id}/pdf`}
          iconOnly
        />
      )}
    />
  );
}

export default function PaymentsPage() {
  const { t } = useTranslation();
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
          <h1 className="text-3xl font-bold tracking-tight">{t('payment.title')}</h1>
          <p className="text-muted-foreground">{t('payment.subtitle')}</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => openDialog('voucher')}>
            <ArrowUpCircle className="mr-2 h-4 w-4" /> {t('payment.newVoucher')}
          </Button>
          <Button onClick={() => openDialog('receipt')}>
            <Plus className="mr-2 h-4 w-4" /> {t('payment.newReceipt')}
          </Button>
        </div>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <MobileTabSelect value={tab} onValueChange={setTab} options={[{ value: 'receipts', label: t('payment.receiptsTab') }, { value: 'vouchers', label: t('payment.vouchersTab') }]} />
        <TabsList className="hidden sm:inline-flex flex-wrap h-auto">
          <TabsTrigger value="receipts">{t('payment.receiptsTab')}</TabsTrigger>
          <TabsTrigger value="vouchers">{t('payment.vouchersTab')}</TabsTrigger>
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
