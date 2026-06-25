import { useEffect, useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { MobileTabSelect } from '@/components/MobileTabSelect';
import { BookOpen, TrendingUp, TrendingDown, AlertCircle, RefreshCw } from 'lucide-react';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { DataTable, type ColumnDef } from '@/components/DataTable';
import api from '@/services/api';
import type { Party } from '@/types';

interface LedgerEntry {
  entry_date: string;
  voucher_type: string;
  voucher_no: string;
  narration: string;
  debit: number;
  credit: number;
  balance: number;
}

interface PartyLedger {
  party_id: string;
  party_name: string;
  opening_balance: number;
  entries: LedgerEntry[];
  closing_balance: number;
  total_debit: number;
  total_credit: number;
}

interface OutstandingItem {
  id: string;
  invoice_no: string;
  invoice_date: string;
  due_date: string | null;
  invoice_type: string;
  party_id: string;
  party_name: string;
  grand_total: number;
  amount_paid: number;
  balance: number;
  days_overdue: number;
  age_bucket: string;
}

interface OutstandingData {
  items: OutstandingItem[];
  total_outstanding: number;
  total_overdue: number;
}

const AGE_COLORS: Record<string, string> = {
  current: 'bg-green-100 text-green-800',
  '1-30': 'bg-yellow-100 text-yellow-800',
  '31-60': 'bg-orange-100 text-orange-800',
  '61-90': 'bg-red-100 text-red-800',
  '90+': 'bg-red-200 text-red-900',
};

const VOUCHER_TYPE_LABELS: Record<string, string> = {
  sale_invoice: 'Sale Invoice',
  purchase_invoice: 'Purchase Invoice',
  receipt: 'Receipt',
  voucher: 'Payment',
  write_off: 'Write-off',
};

// CSS for voucher-type pill (write-off gets an amber tint to stand out)
const VOUCHER_TYPE_CLASSES: Record<string, string> = {
  sale_invoice: 'bg-blue-100 text-blue-800',
  purchase_invoice: 'bg-amber-100 text-amber-800',
  receipt: 'bg-emerald-100 text-emerald-800',
  voucher: 'bg-orange-100 text-orange-800',
  write_off: 'bg-rose-100 text-rose-800 ring-1 ring-rose-300',
};

function fmt(n: number) {
  return '₹' + Math.abs(n).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export default function LedgerPage() {
  const { t } = useTranslation();

  // Respect ?tab=outstanding (linked from Dashboard Outstanding KPI)
  // Respect ?party=<id> (linked from Customer 360 / Parties / Dashboard)
  const initialTab =
    typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('tab') === 'outstanding'
      ? 'outstanding'
      : 'ledger';
  const initialParty =
    typeof window !== 'undefined' ? (new URLSearchParams(window.location.search).get('party') ?? '') : '';
  const todayStr = new Date().toISOString().split('T')[0];
  const fyStart = (() => {
    const m = new Date().getMonth();
    const y = new Date().getFullYear();
    return m >= 3 ? `${y}-04-01` : `${y - 1}-04-01`;
  })();

  const [tab, setTab] = useState(initialTab);
  const [parties, setParties] = useState<Party[]>([]);
  const [partyId, setPartyId] = useState(initialParty);
  const [fromDate, setFromDate] = useState(fyStart);
  const [toDate, setToDate] = useState(todayStr);
  const [ledger, setLedger] = useState<PartyLedger | null>(null);
  const [ledgerError, setLedgerError] = useState<string | null>(null);
  const [outstanding, setOutstanding] = useState<OutstandingData | null>(null);
  const [loadingLedger, setLoadingLedger] = useState(false);
  const [loadingOutstanding, setLoadingOutstanding] = useState(false);
  const [outType, setOutType] = useState('');

  useEffect(() => {
    api.get<{ items: Party[] }>('/api/v1/parties?page=1&page_size=500')
      .then(r => setParties(r.data.items ?? []))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!partyId || tab !== 'ledger') return;
    setLoadingLedger(true);
    setLedgerError(null);
    const params = new URLSearchParams();
    if (fromDate) params.set('from_date', fromDate);
    if (toDate) params.set('to_date', toDate);
    api.get<PartyLedger>(`/api/v1/payments/party-ledger/${partyId}?${params}`)
      .then(r => setLedger(r.data))
      .catch(err => {
        setLedger(null);
        const msg = err?.response?.data?.detail || err?.message || 'Failed to load ledger';
        setLedgerError(String(msg));
      })
      .finally(() => setLoadingLedger(false));
  }, [partyId, tab, fromDate, toDate]);

  useEffect(() => {
    if (tab !== 'outstanding') return;
    setLoadingOutstanding(true);
    const params = new URLSearchParams();
    if (outType) params.set('invoice_type', outType);
    if (partyId) params.set('party_id', partyId);
    api.get<OutstandingData>(`/api/v1/payments/outstanding?${params}`)
      .then(r => setOutstanding(r.data))
      .catch(() => setOutstanding(null))
      .finally(() => setLoadingOutstanding(false));
  }, [tab, outType, partyId]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">{t('ledger.title')}</h1>
          <p className="text-muted-foreground">{t('ledger.subtitle')}</p>
        </div>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <MobileTabSelect value={tab} onValueChange={setTab} options={[{ value: 'ledger', label: t('ledger.partyLedger') }, { value: 'outstanding', label: t('ledger.outstanding') }]} />
        <TabsList className="hidden sm:inline-flex flex-wrap h-auto">
          <TabsTrigger value="ledger">{t('ledger.partyLedger')}</TabsTrigger>
          <TabsTrigger value="outstanding">{t('ledger.outstanding')}</TabsTrigger>
        </TabsList>

        {/* ── Party Ledger ── */}
        <TabsContent value="ledger" className="mt-4 space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <Select value={partyId || 'none'} onValueChange={v => setPartyId(v === 'none' ? '' : (v ?? ''))}>
              <SelectTrigger className="w-72">
                <span className="truncate text-left flex-1">
                  {partyId
                    ? (parties.find(p => p.id === partyId)?.name ?? '…')
                    : <span className="text-muted-foreground">{t('ledger.selectPartyPrompt')}</span>}
                </span>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">{t('ledger.selectPartyOption')}</SelectItem>
                {parties.map(p => (
                  <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <input
              type="date" value={fromDate} onChange={e => setFromDate(e.target.value)}
              className="border rounded px-2 py-1.5 text-sm bg-background"
            />
            <span className="text-muted-foreground text-sm">to</span>
            <input
              type="date" value={toDate} onChange={e => setToDate(e.target.value)}
              className="border rounded px-2 py-1.5 text-sm bg-background"
            />
            {partyId && (
              <Button variant="outline" size="sm" onClick={() => {
                setLedger(null);
                setLedgerError(null);
                setFromDate(fyStart);
                setToDate(todayStr);
              }}>
                <RefreshCw className="h-3.5 w-3.5 mr-1" /> Reset
              </Button>
            )}
            {ledger && (
              <Button variant="outline" size="sm" onClick={() => window.print()}>{t('common.print')}</Button>
            )}
          </div>

          {!partyId && (
            <div className="py-16 text-center">
              <BookOpen className="mx-auto mb-3 h-10 w-10 text-muted-foreground/30" />
              <p className="text-muted-foreground">{t('ledger.selectPartyPrompt')}</p>
            </div>
          )}

          {partyId && loadingLedger && (
            <div className="py-8 text-center text-muted-foreground text-sm">{t('ledger.loadingLedger')}</div>
          )}

          {partyId && !loadingLedger && ledgerError && (
            <div className="rounded-md border border-destructive/30 bg-destructive/10 px-4 py-3 flex items-start gap-3">
              <AlertCircle className="h-4 w-4 text-destructive mt-0.5 shrink-0" />
              <div>
                <p className="text-sm font-medium text-destructive">Could not load ledger</p>
                <p className="text-xs text-destructive/80 mt-0.5">{ledgerError}</p>
              </div>
            </div>
          )}

          {ledger && !loadingLedger && !ledgerError && (
            <>
              {/* Summary cards */}
              <div className="grid grid-cols-3 gap-4">
                <Card>
                  <CardHeader className="pb-1"><CardTitle className="text-sm font-medium text-muted-foreground">{t('ledger.totalDebit')}</CardTitle></CardHeader>
                  <CardContent><p className="text-2xl font-bold text-foreground">{fmt(ledger.total_debit)}</p></CardContent>
                </Card>
                <Card>
                  <CardHeader className="pb-1"><CardTitle className="text-sm font-medium text-muted-foreground">{t('ledger.totalCredit')}</CardTitle></CardHeader>
                  <CardContent><p className="text-2xl font-bold text-foreground">{fmt(ledger.total_credit)}</p></CardContent>
                </Card>
                <Card>
                  <CardHeader className="pb-1"><CardTitle className="text-sm font-medium text-muted-foreground">{t('ledger.closingBalance')}</CardTitle></CardHeader>
                  <CardContent>
                    <p className={`text-2xl font-bold ${ledger.closing_balance > 0 ? 'text-foreground' : 'text-green-600'}`}>
                      {fmt(ledger.closing_balance)} {ledger.closing_balance < 0 ? t('ledger.cr') : t('ledger.dr')}
                    </p>
                  </CardContent>
                </Card>
              </div>

              {/* Ledger table */}
              <Card>
                <CardContent className="p-0">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b bg-muted/50">
                        <th className="px-4 py-2 text-left font-medium text-muted-foreground">{t('common.date')}</th>
                        <th className="px-4 py-2 text-left font-medium text-muted-foreground">{t('ledger.type')}</th>
                        <th className="px-4 py-2 text-left font-medium text-muted-foreground">{t('ledger.voucherNo')}</th>
                        <th className="px-4 py-2 text-left font-medium text-muted-foreground">{t('ledger.narration')}</th>
                        <th className="px-4 py-2 text-right font-medium text-muted-foreground">{t('ledger.debit')}</th>
                        <th className="px-4 py-2 text-right font-medium text-muted-foreground">{t('ledger.credit')}</th>
                        <th className="px-4 py-2 text-right font-medium text-muted-foreground">{t('ledger.balance')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr className="border-b bg-muted/20">
                        <td colSpan={4} className="px-4 py-2 text-muted-foreground italic">{t('ledger.openingBalance')}</td>
                        <td className="px-4 py-2 text-right">—</td>
                        <td className="px-4 py-2 text-right">—</td>
                        <td className="px-4 py-2 text-right font-medium">{fmt(ledger.opening_balance)}</td>
                      </tr>
                      {ledger.entries.map((e, i) => (
                        <tr key={i} className="border-b hover:bg-muted/20 transition-colors">
                          <td className="px-4 py-2 text-muted-foreground whitespace-nowrap">{e.entry_date}</td>
                          <td className="px-4 py-2">
                            <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${VOUCHER_TYPE_CLASSES[e.voucher_type] || 'bg-muted'}`}>
                              {VOUCHER_TYPE_LABELS[e.voucher_type] || e.voucher_type}
                            </span>
                          </td>
                          <td className="px-4 py-2 font-mono text-xs">{e.voucher_no}</td>
                          <td className="px-4 py-2 text-muted-foreground">{e.narration}</td>
                          <td className="px-4 py-2 text-right">
                            {Number(e.debit) > 0 ? <span className="text-foreground">{fmt(Number(e.debit))}</span> : <span className="text-muted-foreground">—</span>}
                          </td>
                          <td className="px-4 py-2 text-right">
                            {Number(e.credit) > 0 ? <span className="text-green-700">{fmt(Number(e.credit))}</span> : <span className="text-muted-foreground">—</span>}
                          </td>
                          <td className="px-4 py-2 text-right font-medium">
                            {fmt(Number(e.balance))} <span className="text-xs text-muted-foreground">{Number(e.balance) >= 0 ? t('ledger.dr') : t('ledger.cr')}</span>
                          </td>
                        </tr>
                      ))}
                      <tr className="bg-muted/30 font-semibold">
                        <td colSpan={4} className="px-4 py-2">{t('ledger.closingBalance')}</td>
                        <td className="px-4 py-2 text-right">{fmt(ledger.total_debit)}</td>
                        <td className="px-4 py-2 text-right text-green-700">{fmt(ledger.total_credit)}</td>
                        <td className="px-4 py-2 text-right">{fmt(ledger.closing_balance)}</td>
                      </tr>
                    </tbody>
                  </table>

                  {ledger.entries.length === 0 && (
                    <div className="py-10 text-center text-muted-foreground text-sm">{t('ledger.noTransactions')}</div>
                  )}
                </CardContent>
              </Card>
            </>
          )}
        </TabsContent>

        {/* ── Outstanding ── */}
        <TabsContent value="outstanding" className="mt-4 space-y-4">
          <div className="flex items-center gap-3">
            <Select value={outType || 'all'} onValueChange={v => setOutType(v === 'all' ? '' : (v ?? ''))}>
              <SelectTrigger className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t('ledger.allInvoices')}</SelectItem>
                <SelectItem value="sale">{t('ledger.sales')}</SelectItem>
                <SelectItem value="purchase">{t('ledger.purchases')}</SelectItem>
              </SelectContent>
            </Select>
            <Select value={partyId || 'all'} onValueChange={v => setPartyId(v === 'all' ? '' : (v ?? ''))}>
              <SelectTrigger className="w-60">
                <span className="truncate text-left flex-1">
                  {partyId
                    ? (parties.find(p => p.id === partyId)?.name ?? '…')
                    : t('ledger.allParties')}
                </span>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t('ledger.allParties')}</SelectItem>
                {parties.map(p => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>

          {outstanding && (
            <div className="grid grid-cols-2 gap-4">
              <Card>
                <CardHeader className="pb-1"><CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2"><TrendingUp className="h-4 w-4" />{t('ledger.totalOutstanding')}</CardTitle></CardHeader>
                <CardContent><p className="text-2xl font-bold">{fmt(Number(outstanding.total_outstanding))}</p></CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-1"><CardTitle className="text-sm font-medium text-destructive flex items-center gap-2"><AlertCircle className="h-4 w-4" />{t('ledger.overdueAmount')}</CardTitle></CardHeader>
                <CardContent><p className="text-2xl font-bold text-destructive">{fmt(Number(outstanding.total_overdue))}</p></CardContent>
              </Card>
            </div>
          )}

          {loadingOutstanding && <div className="py-8 text-center text-muted-foreground text-sm">{t('common.loading')}</div>}

          {outstanding && !loadingOutstanding && (
            outstanding.items.length === 0 ? (
              <Card>
                <CardContent className="py-16 text-center">
                  <TrendingDown className="mx-auto mb-3 h-10 w-10 text-green-500/50" />
                  <p className="text-muted-foreground text-sm">{t('ledger.noOutstanding')}</p>
                </CardContent>
              </Card>
            ) : (
              <OutstandingTable items={outstanding.items} />
            )
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}

// ------------------------------------------------------------------ //
// Outstanding DataTable
// ------------------------------------------------------------------ //
function OutstandingTable({ items }: { items: OutstandingItem[] }) {
  const { t } = useTranslation();

  const columns = useMemo<ColumnDef<OutstandingItem>[]>(() => [
    { key: 'invoice_no', label: t('invoice.invoiceNo'), accessor: i => i.invoice_no, className: 'font-mono text-xs font-medium' },
    { key: 'invoice_date', label: t('common.date'), type: 'date', accessor: i => i.invoice_date, className: 'text-muted-foreground' },
    { key: 'due_date', label: t('ledger.dueDate'), type: 'date', accessor: i => i.due_date ?? '', defaultVisible: false },
    {
      key: 'invoice_type', label: t('ledger.type'), type: 'enum',
      enumOptions: ['sale', 'purchase'],
      accessor: i => i.invoice_type,
      format: v => <span className="capitalize text-xs">{String(v)}</span>,
    },
    {
      key: 'party_name', label: t('invoice.party'), accessor: i => i.party_name,
      format: (_v, row) => (
        <Link to={`/customers/${row.party_id}`} className="text-blue-600 hover:underline" title={t('ledger.viewCustomer360')}>
          {row.party_name}
        </Link>
      ),
    },
    {
      key: 'grand_total', label: t('common.total'), type: 'number', align: 'right',
      accessor: i => i.grand_total, format: v => fmt(Number(v)),
    },
    {
      key: 'amount_paid', label: t('ledger.paid'), type: 'number', align: 'right',
      accessor: i => i.amount_paid,
      format: v => Number(v) > 0 ? <span className="text-green-700">{fmt(Number(v))}</span> : <span className="text-muted-foreground">—</span>,
    },
    {
      key: 'balance', label: t('ledger.balance'), type: 'number', align: 'right',
      accessor: i => i.balance,
      format: v => <span className="font-semibold text-destructive">{fmt(Number(v))}</span>,
    },
    {
      key: 'age_bucket', label: t('ledger.age'), type: 'enum', align: 'center',
      enumOptions: ['current', '1-30', '31-60', '61-90', '90+'],
      accessor: i => i.age_bucket,
      format: v => (
        <Badge className={`text-[10px] ${AGE_COLORS[String(v)] || ''}`}>
          {v === 'current' ? t('ledger.current') : `${v} ${t('ledger.days')}`}
        </Badge>
      ),
    },
  // eslint-disable-next-line react-hooks/exhaustive-deps
  ], [t]);

  return (
    <DataTable<OutstandingItem>
      id="ledger.outstanding"
      data={items}
      columns={columns}
      rowKey={i => i.id}
      exportFilename="outstanding-invoices"
      defaultSort={{ key: 'invoice_date', direction: 'asc' }}
      emptyMessage={t('ledger.noOutstanding')}
    />
  );
}
