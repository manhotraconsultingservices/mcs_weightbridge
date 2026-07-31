import { useEffect, useState, useCallback, useMemo, Fragment } from 'react';
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
  party_id: string | null;
  party_name: string | null;
  expense_category?: string | null;
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
  // Gross open-invoice balance on the OPPOSITE side (purchases for a receipt,
  // sales for a voucher). A party that's both customer AND supplier can have an
  // open receivable and an open payable that net to zero in current_balance —
  // this lets the "Outstanding" label show both instead of masking to "Settled".
  const [oppositeDue, setOppositeDue] = useState(0);
  const [allocations, setAllocations] = useState<AllocationRow[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  // Direct-expense (overhead) mode — vouchers only. No party/allocation required.
  const [isExpense, setIsExpense] = useState(false);
  const [expenseCategory, setExpenseCategory] = useState('');
  const [expenseCats, setExpenseCats] = useState<string[]>([]);
  // Operator who physically COLLECTED the cash (receipts) — drives the Operator Cash EOD.
  const [collectedBy, setCollectedBy] = useState('');
  const [opUsers, setOpUsers] = useState<{ id: string; name: string; role: string }[]>([]);

  useEffect(() => {
    if (open) {
      setPartyId(''); setDate(new Date().toISOString().slice(0, 10));
      setAmount(''); setMode('cash'); setRefNo(''); setBankName('');
      setNotes(''); setAllocations([]); setError(''); setCollectedBy('');
      setIsExpense(false); setExpenseCategory('');
      api.get<Party[] | { items: Party[] }>('/api/v1/parties').then(r => {
        const d = r.data;
        setParties(Array.isArray(d) ? d : (d.items ?? []));
      }).catch(() => {});
      if (type === 'receipt') {
        api.get<{ id: string; name: string; role: string }[]>('/api/v1/auth/users-lite')
          .then(r => setOpUsers(Array.isArray(r.data) ? r.data : []))
          .catch(() => setOpUsers([]));
      }
      if (type === 'voucher') {
        api.get<string[]>('/api/v1/app-settings/expense-categories')
          .then(r => setExpenseCats(Array.isArray(r.data) ? r.data : []))
          .catch(() => setExpenseCats([]));
      }
    }
  }, [open, type]);

  // Auto-offset outstanding invoices by FIFO (oldest bill first) as the amount is entered.
  const [autoFifo, setAutoFifo] = useState(true);

  // Oldest-first ordering (FIFO): invoice_date asc, tie-break created_at asc.
  const invTime = (i: Invoice) => new Date((i.invoice_date || (i as { created_at?: string }).created_at || '') as string).getTime() || 0;

  useEffect(() => {
    if (!partyId) { setOutstandingInvoices([]); setAllocations([]); setOppositeDue(0); return; }
    const invType = type === 'receipt' ? 'sale' : 'purchase';
    const oppType = type === 'receipt' ? 'purchase' : 'sale';
    // Opposite-side open-invoice gross — only used to enrich the "Outstanding" label.
    setOppositeDue(0);
    api.get<{ items: Invoice[] }>(`/api/v1/invoices?invoice_type=${oppType}&party_id=${partyId}&page=1&page_size=50`)
      .then(r => setOppositeDue(r.data.items
        .filter(i => i.payment_status !== 'paid' && i.status === 'final')
        .reduce((s, i) => s + Math.max(0, Number(i.grand_total ?? 0) - Number(i.amount_paid ?? 0)), 0)))
      .catch(() => setOppositeDue(0));
    api.get<{ items: Invoice[] }>(`/api/v1/invoices?invoice_type=${invType}&party_id=${partyId}&page=1&page_size=50`)
      .then(r => {
        // FIFO: sort unpaid finalised invoices oldest-first so allocation clears the oldest bills first.
        const unpaid = r.data.items
          .filter(i => i.payment_status !== 'paid' && i.status === 'final')
          .sort((a, b) => invTime(a) - invTime(b));
        setOutstandingInvoices(unpaid);
        setAllocations(unpaid.map(i => ({
          invoice_id: i.id,
          invoice_no: i.invoice_no,
          balance: i.grand_total - i.amount_paid,
          amount: '',
        })));
      })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [partyId, type]);

  // FIFO auto-fill: distribute `amount` across outstanding invoices oldest-first,
  // filling each bill's balance until the payment is exhausted. Recomputes whenever
  // the amount (or the invoice list) changes while auto-offset is ON. Computed purely
  // from outstandingInvoices balances (not from `allocations`) so there's no update loop.
  useEffect(() => {
    if (isExpense || !autoFifo || outstandingInvoices.length === 0) return;
    let rem = Math.max(0, parseFloat(amount) || 0);
    setAllocations(outstandingInvoices.map(i => {
      const bal = i.grand_total - i.amount_paid;
      let use = 0;
      if (rem > 0.005) { use = Math.min(rem, bal); rem = Number((rem - use).toFixed(2)); }
      return {
        invoice_id: i.id, invoice_no: i.invoice_no, balance: bal,
        amount: use > 0.005 ? String(Number(use.toFixed(2))) : '',
      };
    }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [amount, autoFifo, outstandingInvoices]);

  const totalAllocated = allocations.reduce((s, a) => s + (parseFloat(a.amount) || 0), 0);

  async function handleSave() {
    const expense = type === 'voucher' && isExpense;
    const expenseCat = expenseCategory.trim();
    if (expense) {
      if (!expenseCat) { setError('Enter an expense category'); return; }
    } else if (!partyId) {
      setError('Select a party'); return;
    }
    if (!amount || parseFloat(amount) <= 0) { setError('Enter a valid amount'); return; }
    setSaving(true); setError('');
    try {
      const allocs = expense ? [] : allocations
        .filter(a => parseFloat(a.amount) > 0)
        .map(a => ({ invoice_id: a.invoice_id, amount: parseFloat(a.amount) }));
      const url = type === 'receipt' ? '/api/v1/payments/receipts' : '/api/v1/payments/vouchers';
      const dateKey = type === 'receipt' ? 'receipt_date' : 'voucher_date';
      await api.post(url, {
        [dateKey]: date,
        party_id: partyId || null,
        expense_category: expense ? expenseCat : null,
        amount: parseFloat(amount),
        payment_mode: mode,
        reference_no: refNo || null,
        bank_name: bankName || null,
        notes: notes || null,
        ...(type === 'receipt' && collectedBy ? { collected_by: collectedBy } : {}),
        allocations: allocs,
      });
      // Remember a newly-typed category so it appears in the picker next time.
      // Best-effort + admin-only server-side (403 for non-admins is ignored).
      if (expense && expenseCat && !expenseCats.some(c => c.toLowerCase() === expenseCat.toLowerCase())) {
        api.put('/api/v1/app-settings/expense-categories', [...expenseCats, expenseCat]).catch(() => {});
      }
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

          {/* Voucher-only: record a direct overhead expense (electricity, rent…) */}
          {type === 'voucher' && (
            <label className="flex items-center gap-2 rounded-md border border-amber-200 bg-amber-50/60 px-3 py-2 text-sm cursor-pointer">
              <input type="checkbox" className="h-4 w-4" checked={isExpense}
                onChange={e => setIsExpense(e.target.checked)} />
              <span className="font-medium">Direct expense (overhead)</span>
              <span className="text-xs text-muted-foreground">— electricity, rent, repairs… (no supplier invoice)</span>
            </label>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="space-y-1">
              {isExpense ? (
                <>
                  <Label>Expense category *</Label>
                  <Input list="expense-cats-dl" value={expenseCategory}
                    placeholder="e.g. EMI, Rent, Electricity…"
                    onChange={e => setExpenseCategory(e.target.value)} />
                  <datalist id="expense-cats-dl">
                    {expenseCats.map(c => <option key={c} value={c} />)}
                  </datalist>
                  <p className="text-[11px] text-muted-foreground">Pick a saved category or type a new one (e.g. EMI, Loan interest, Admin charges).</p>
                </>
              ) : (<>
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
              {partyId && (() => {
                const bal = Number(parties.find(p => p.id === partyId)?.current_balance ?? 0);
                const fmt = (v: number) => '₹' + Math.abs(v).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
                const Money = ({ v }: { v: number }) => <span className="font-semibold">{fmt(v)}</span>;
                // Gross open-invoice balances per side (NOT netted). When a party is both a
                // customer and a supplier, an open receivable and an open payable can cancel in
                // current_balance — so show both explicitly instead of a misleading "Settled".
                const settlingDue = outstandingInvoices
                  .reduce((s, i) => s + Math.max(0, Number(i.grand_total ?? 0) - Number(i.amount_paid ?? 0)), 0);
                const receivable = type === 'receipt' ? settlingDue : oppositeDue;  // party owes us (open sales)
                const payable    = type === 'receipt' ? oppositeDue : settlingDue;  // we owe party (open purchases)
                const owesUs = bal > 0.005;   // net: party owes us
                const weOwe = bal < -0.005;   // net: we owe them / advance held
                const clauses: React.ReactNode[] = [];
                if (receivable > 0.005) clauses.push(<><Money v={receivable} /> to collect (customer owes)</>);
                if (payable > 0.005)    clauses.push(<><Money v={payable} /> payable to them</>);
                let txt: React.ReactNode; let cls: string;
                if (clauses.length > 0) {
                  // Both sides open → amber (there's still something to settle either way).
                  txt = clauses.map((c, i) => <Fragment key={i}>{i > 0 && ' · '}{c}</Fragment>);
                  cls = (receivable > 0.005 && payable > 0.005) ? 'text-amber-700'
                      : type === 'receipt' ? (receivable > 0.005 ? 'text-amber-700' : 'text-emerald-700')
                      : (payable > 0.005 ? 'text-amber-700' : 'text-emerald-700');
                } else if (weOwe || owesUs) {
                  // No open invoices on either side, but a net advance is on account.
                  if (type === 'receipt') {
                    txt = weOwe ? <><Money v={bal} /> advance already with us</>
                        : <><Money v={bal} /> to collect (customer owes)</>;
                    cls = weOwe ? 'text-emerald-700' : 'text-amber-700';
                  } else {
                    txt = owesUs ? <><Money v={bal} /> advance already paid</>
                        : <><Money v={bal} /> payable (we owe supplier)</>;
                    cls = owesUs ? 'text-emerald-700' : 'text-amber-700';
                  }
                } else {
                  txt = 'Settled — no outstanding';
                  cls = 'text-muted-foreground';
                }
                return <p className={`text-xs mt-1 ${cls}`}>Outstanding: {txt}</p>;
              })()}
              </>)}
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

          {/* Receipt only: which operator physically collected the cash (drives Operator Cash EOD) */}
          {type === 'receipt' && opUsers.length > 0 && (
            <div className="space-y-1">
              <Label>Collected by (operator)</Label>
              <Select value={collectedBy || undefined} onValueChange={v => setCollectedBy(v ?? '')}>
                <SelectTrigger>
                  <span className="truncate text-left flex-1">
                    {collectedBy ? (opUsers.find(u => u.id === collectedBy)?.name ?? '…')
                      : <span className="text-muted-foreground">Me (defaults to whoever records it)</span>}
                  </span>
                </SelectTrigger>
                <SelectContent>
                  {opUsers.map(u => <SelectItem key={u.id} value={u.id}>{u.name}{u.role ? ` · ${u.role}` : ''}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          )}

          <div className="space-y-1">
            <Label>{t('common.notes')}</Label>
            <Input value={notes} onChange={e => setNotes(e.target.value)} placeholder={t('payment.optionalRemarks')} />
          </div>

          {/* Invoice allocation (not applicable to a direct expense) */}
          {!isExpense && outstandingInvoices.length > 0 && (
            <div className="border-t pt-3 space-y-2">
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <p className="text-sm font-medium">{t('payment.settleInvoices')}</p>
                <div className="flex items-center gap-3">
                  <label className="flex items-center gap-1.5 text-xs cursor-pointer" title="Automatically settle the oldest bills first as you type the amount">
                    <input type="checkbox" className="h-3.5 w-3.5" checked={autoFifo} onChange={e => setAutoFifo(e.target.checked)} />
                    <span>Auto-offset (FIFO — oldest first)</span>
                  </label>
                  <p className="text-xs text-muted-foreground">{t('payment.allocated')}: ₹{totalAllocated.toLocaleString('en-IN')}</p>
                </div>
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
                      onChange={e => {
                        setAutoFifo(false);   // manual edit → stop auto-offset clobbering it
                        setAllocations(prev => prev.map((a, j) =>
                          j === i ? { ...a, amount: e.target.value } : a
                        ));
                      }}
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
    { key: 'party_name', label: t('payment.party'),
      accessor: r => r.party_name || (r.expense_category ? `${r.expense_category} (expense)` : '—') },
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
