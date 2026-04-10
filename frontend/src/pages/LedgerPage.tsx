import { useEffect, useState } from 'react';
import { BookOpen, TrendingUp, TrendingDown, AlertCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
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
};

function fmt(n: number) {
  return '₹' + Math.abs(n).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export default function LedgerPage() {
  const [tab, setTab] = useState('ledger');
  const [parties, setParties] = useState<Party[]>([]);
  const [partyId, setPartyId] = useState('');
  const [ledger, setLedger] = useState<PartyLedger | null>(null);
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
    api.get<PartyLedger>(`/api/v1/payments/party-ledger/${partyId}`)
      .then(r => setLedger(r.data))
      .catch(() => setLedger(null))
      .finally(() => setLoadingLedger(false));
  }, [partyId, tab]);

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
          <h1 className="text-3xl font-bold tracking-tight">Ledger & Accounts</h1>
          <p className="text-muted-foreground">Party ledger, outstanding invoices, ageing analysis</p>
        </div>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="ledger">Party Ledger</TabsTrigger>
          <TabsTrigger value="outstanding">Outstanding</TabsTrigger>
        </TabsList>

        {/* ── Party Ledger ── */}
        <TabsContent value="ledger" className="mt-4 space-y-4">
          <div className="flex items-center gap-3">
            <Select value={partyId || 'none'} onValueChange={v => setPartyId(v === 'none' ? '' : (v ?? ''))}>
              <SelectTrigger className="w-72">
                <span className="truncate text-left flex-1">
                  {partyId
                    ? (parties.find(p => p.id === partyId)?.name ?? '…')
                    : <span className="text-muted-foreground">Select a party to view ledger</span>}
                </span>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">— Select party —</SelectItem>
                {parties.map(p => (
                  <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            {ledger && (
              <Button variant="outline" size="sm" onClick={() => window.print()}>Print</Button>
            )}
          </div>

          {!partyId && (
            <div className="py-16 text-center">
              <BookOpen className="mx-auto mb-3 h-10 w-10 text-muted-foreground/30" />
              <p className="text-muted-foreground">Select a party to view their ledger</p>
            </div>
          )}

          {partyId && loadingLedger && (
            <div className="py-8 text-center text-muted-foreground text-sm">Loading ledger…</div>
          )}

          {ledger && !loadingLedger && (
            <>
              {/* Summary cards */}
              <div className="grid grid-cols-3 gap-4">
                <Card>
                  <CardHeader className="pb-1"><CardTitle className="text-sm font-medium text-muted-foreground">Total Debit</CardTitle></CardHeader>
                  <CardContent><p className="text-2xl font-bold text-foreground">{fmt(ledger.total_debit)}</p></CardContent>
                </Card>
                <Card>
                  <CardHeader className="pb-1"><CardTitle className="text-sm font-medium text-muted-foreground">Total Credit</CardTitle></CardHeader>
                  <CardContent><p className="text-2xl font-bold text-foreground">{fmt(ledger.total_credit)}</p></CardContent>
                </Card>
                <Card>
                  <CardHeader className="pb-1"><CardTitle className="text-sm font-medium text-muted-foreground">Closing Balance</CardTitle></CardHeader>
                  <CardContent>
                    <p className={`text-2xl font-bold ${ledger.closing_balance > 0 ? 'text-foreground' : 'text-green-600'}`}>
                      {fmt(ledger.closing_balance)} {ledger.closing_balance < 0 ? 'Cr' : 'Dr'}
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
                        <th className="px-4 py-2 text-left font-medium text-muted-foreground">Date</th>
                        <th className="px-4 py-2 text-left font-medium text-muted-foreground">Type</th>
                        <th className="px-4 py-2 text-left font-medium text-muted-foreground">Voucher No</th>
                        <th className="px-4 py-2 text-left font-medium text-muted-foreground">Narration</th>
                        <th className="px-4 py-2 text-right font-medium text-muted-foreground">Debit</th>
                        <th className="px-4 py-2 text-right font-medium text-muted-foreground">Credit</th>
                        <th className="px-4 py-2 text-right font-medium text-muted-foreground">Balance</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr className="border-b bg-muted/20">
                        <td colSpan={4} className="px-4 py-2 text-muted-foreground italic">Opening Balance</td>
                        <td className="px-4 py-2 text-right">—</td>
                        <td className="px-4 py-2 text-right">—</td>
                        <td className="px-4 py-2 text-right font-medium">{fmt(ledger.opening_balance)}</td>
                      </tr>
                      {ledger.entries.map((e, i) => (
                        <tr key={i} className="border-b hover:bg-muted/20 transition-colors">
                          <td className="px-4 py-2 text-muted-foreground whitespace-nowrap">{e.entry_date}</td>
                          <td className="px-4 py-2">
                            <span className="text-xs bg-muted px-1.5 py-0.5 rounded">
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
                            {fmt(Number(e.balance))} <span className="text-xs text-muted-foreground">{Number(e.balance) >= 0 ? 'Dr' : 'Cr'}</span>
                          </td>
                        </tr>
                      ))}
                      <tr className="bg-muted/30 font-semibold">
                        <td colSpan={4} className="px-4 py-2">Closing Balance</td>
                        <td className="px-4 py-2 text-right">{fmt(ledger.total_debit)}</td>
                        <td className="px-4 py-2 text-right text-green-700">{fmt(ledger.total_credit)}</td>
                        <td className="px-4 py-2 text-right">{fmt(ledger.closing_balance)}</td>
                      </tr>
                    </tbody>
                  </table>

                  {ledger.entries.length === 0 && (
                    <div className="py-10 text-center text-muted-foreground text-sm">No transactions in current financial year</div>
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
                <SelectItem value="all">All Invoices</SelectItem>
                <SelectItem value="sale">Sales</SelectItem>
                <SelectItem value="purchase">Purchases</SelectItem>
              </SelectContent>
            </Select>
            <Select value={partyId || 'all'} onValueChange={v => setPartyId(v === 'all' ? '' : (v ?? ''))}>
              <SelectTrigger className="w-60">
                <span className="truncate text-left flex-1">
                  {partyId
                    ? (parties.find(p => p.id === partyId)?.name ?? '…')
                    : 'All Parties'}
                </span>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Parties</SelectItem>
                {parties.map(p => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>

          {outstanding && (
            <div className="grid grid-cols-2 gap-4">
              <Card>
                <CardHeader className="pb-1"><CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2"><TrendingUp className="h-4 w-4" />Total Outstanding</CardTitle></CardHeader>
                <CardContent><p className="text-2xl font-bold">{fmt(Number(outstanding.total_outstanding))}</p></CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-1"><CardTitle className="text-sm font-medium text-destructive flex items-center gap-2"><AlertCircle className="h-4 w-4" />Overdue Amount</CardTitle></CardHeader>
                <CardContent><p className="text-2xl font-bold text-destructive">{fmt(Number(outstanding.total_overdue))}</p></CardContent>
              </Card>
            </div>
          )}

          {loadingOutstanding && <div className="py-8 text-center text-muted-foreground text-sm">Loading…</div>}

          {outstanding && !loadingOutstanding && (
            <Card>
              <CardContent className="p-0">
                {outstanding.items.length === 0 ? (
                  <div className="py-16 text-center">
                    <TrendingDown className="mx-auto mb-3 h-10 w-10 text-green-500/50" />
                    <p className="text-muted-foreground text-sm">No outstanding invoices</p>
                  </div>
                ) : (
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b bg-muted/50">
                        <th className="px-4 py-2 text-left font-medium text-muted-foreground">Invoice</th>
                        <th className="px-4 py-2 text-left font-medium text-muted-foreground">Party</th>
                        <th className="px-4 py-2 text-right font-medium text-muted-foreground">Total</th>
                        <th className="px-4 py-2 text-right font-medium text-muted-foreground">Paid</th>
                        <th className="px-4 py-2 text-right font-medium text-muted-foreground">Balance</th>
                        <th className="px-4 py-2 text-center font-medium text-muted-foreground">Age</th>
                      </tr>
                    </thead>
                    <tbody>
                      {outstanding.items.map(item => (
                        <tr key={item.id} className="border-b hover:bg-muted/20 transition-colors">
                          <td className="px-4 py-2">
                            <p className="font-medium font-mono text-xs">{item.invoice_no}</p>
                            <p className="text-xs text-muted-foreground">{item.invoice_date}{item.due_date ? ` · Due: ${item.due_date}` : ''}</p>
                          </td>
                          <td className="px-4 py-2 text-muted-foreground">{item.party_name}</td>
                          <td className="px-4 py-2 text-right">{fmt(Number(item.grand_total))}</td>
                          <td className="px-4 py-2 text-right text-green-700">{Number(item.amount_paid) > 0 ? fmt(Number(item.amount_paid)) : '—'}</td>
                          <td className="px-4 py-2 text-right font-semibold text-destructive">{fmt(Number(item.balance))}</td>
                          <td className="px-4 py-2 text-center">
                            <Badge className={`text-[10px] ${AGE_COLORS[item.age_bucket] || ''}`}>
                              {item.age_bucket === 'current' ? 'Current' : `${item.age_bucket} days`}
                            </Badge>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </CardContent>
            </Card>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
