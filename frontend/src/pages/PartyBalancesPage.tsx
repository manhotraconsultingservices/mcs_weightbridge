/**
 * Party Balances — current balance by customer AND supplier.
 *
 * Shows each party's bills outstanding, advance on account (credit), and the
 * net balance (Dr = they owe us, Cr = we owe them). Advance-aware: computed
 * from source so it always matches recompute_party_balance.
 *
 *   GET /api/v1/reports/party-balances?party_type=all|customer|supplier
 */
import { useEffect, useState, useCallback, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { Wallet, IndianRupee, Scale, Loader2, AlertCircle } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { DataTable, type ColumnDef } from '@/components/DataTable';
import api from '@/services/api';

interface BalanceRow {
  id: string;
  name: string;
  party_type: string;
  phone: string | null;
  city: string | null;
  bills_balance: number;   // signed invoice/notes component
  advance: number;         // advance held on account (>= 0)
  net_balance: number;     // signed net (= current_balance)
}
interface BalancesResponse {
  rows: BalanceRow[];
  count: number;
  totals: { bills_balance: number; advance: number; net_balance: number };
}

const INR = (v: number) =>
  '₹' + Number(v ?? 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** Signed money → "₹X Dr" (owed to us) / "₹X Cr" (we owe) / "₹0.00". */
function drcr(v: number): string {
  const n = Number(v ?? 0);
  if (Math.abs(n) < 0.005) return '₹0.00';
  return `${INR(Math.abs(n))} ${n > 0 ? 'Dr' : 'Cr'}`;
}

type Filter = 'all' | 'customer' | 'supplier';

export default function PartyBalancesPage() {
  const [filter, setFilter] = useState<Filter>('all');
  const [data, setData] = useState<BalancesResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const { data } = await api.get<BalancesResponse>('/api/v1/reports/party-balances', {
        params: { party_type: filter },
      });
      setData(data);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Failed to load balances');
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => { load(); }, [load]);

  const rows = data?.rows ?? [];
  const totals = data?.totals ?? { bills_balance: 0, advance: 0, net_balance: 0 };

  const columns = useMemo<ColumnDef<BalanceRow>[]>(() => [
    {
      key: 'name', label: 'Party', accessor: r => r.name,
      format: (_v, r) => (
        <Link to={`/customers/${r.id}`} className="font-medium text-primary hover:underline">
          {r.name}
        </Link>
      ),
      exportValue: r => r.name,
    },
    {
      key: 'party_type', label: 'Type', type: 'enum', enumOptions: ['customer', 'supplier', 'both'],
      accessor: r => r.party_type,
      format: v => <span className="capitalize text-xs text-muted-foreground">{String(v)}</span>,
    },
    {
      key: 'bills_balance', label: 'Bills Outstanding', type: 'number', align: 'right',
      accessor: r => r.bills_balance, format: v => drcr(Number(v)), exportValue: r => r.bills_balance,
    },
    {
      key: 'advance', label: 'Advance (Cr)', type: 'number', align: 'right',
      accessor: r => r.advance,
      format: v => Number(v) > 0
        ? <span className="text-emerald-600 font-medium">{INR(Number(v))}</span>
        : <span className="text-muted-foreground">—</span>,
      exportValue: r => r.advance,
    },
    {
      key: 'net_balance', label: 'Net Balance', type: 'number', align: 'right',
      accessor: r => r.net_balance,
      format: v => {
        const n = Number(v);
        const cls = n > 0.005 ? 'text-rose-600' : n < -0.005 ? 'text-emerald-600' : 'text-muted-foreground';
        return <span className={`font-semibold ${cls}`}>{drcr(n)}</span>;
      },
      exportValue: r => r.net_balance,
    },
    { key: 'phone', label: 'Phone', accessor: r => r.phone ?? '', defaultVisible: false },
    { key: 'city', label: 'City', accessor: r => r.city ?? '', defaultVisible: false },
  ], []);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-bold text-slate-900">Party Balances</h1>
          <p className="text-xs text-muted-foreground">
            Current balance by customer &amp; supplier — bills, advance on account, and net.
          </p>
        </div>
        <div className="flex gap-1 rounded-lg border p-0.5">
          {(['all', 'customer', 'supplier'] as Filter[]).map(f => (
            <Button
              key={f} size="sm"
              variant={filter === f ? 'default' : 'ghost'}
              className="h-7 px-3 text-xs capitalize"
              onClick={() => setFilter(f)}
            >
              {f === 'all' ? 'All' : f + 's'}
            </Button>
          ))}
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
          <AlertCircle className="h-4 w-4" /> {error}
        </div>
      )}

      {/* KPI strip */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Card><CardContent className="flex items-center gap-3 p-4">
          <div className="rounded-lg bg-rose-50 p-2"><IndianRupee className="h-5 w-5 text-rose-600" /></div>
          <div><p className="text-xs text-muted-foreground">Total Bills Outstanding</p>
            <p className="text-lg font-bold">{drcr(totals.bills_balance)}</p></div>
        </CardContent></Card>
        <Card><CardContent className="flex items-center gap-3 p-4">
          <div className="rounded-lg bg-emerald-50 p-2"><Wallet className="h-5 w-5 text-emerald-600" /></div>
          <div><p className="text-xs text-muted-foreground">Total Advances (Cr)</p>
            <p className="text-lg font-bold text-emerald-600">{INR(totals.advance)}</p></div>
        </CardContent></Card>
        <Card><CardContent className="flex items-center gap-3 p-4">
          <div className="rounded-lg bg-slate-100 p-2"><Scale className="h-5 w-5 text-slate-600" /></div>
          <div><p className="text-xs text-muted-foreground">Net Balance</p>
            <p className="text-lg font-bold">{drcr(totals.net_balance)}</p></div>
        </CardContent></Card>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-16 text-muted-foreground">
          <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading…
        </div>
      ) : (
        <DataTable<BalanceRow>
          id="reports.party_balances"
          data={rows}
          columns={columns}
          rowKey={r => r.id}
          exportFilename="party-balances"
          defaultSort={{ key: 'net_balance', direction: 'desc' }}
          emptyMessage="No party balances to show"
        />
      )}
    </div>
  );
}
