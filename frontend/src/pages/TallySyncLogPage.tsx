/**
 * Tally Sync Log — did this record actually reach Tally?
 *
 * Shows Tally's OWN verdict on every record sent, not our intent to send it:
 * Delivered means Tally reported it created or altered the record; Failed carries
 * Tally's exact words (missing ledger, refused company, timeout) so the cause is
 * actionable rather than a shrug. Waiting means it is queued or being retried.
 *
 * Rendered only when Tally is switched on (Settings → Tally).
 */
import { useCallback, useEffect, useState } from 'react';
import { RefreshCw, CheckCircle2, Clock, XCircle } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { DataTable, type ColumnDef } from '@/components/DataTable';
import api from '@/services/api';
import { useTallyEnabled } from '@/hooks/useTallyEnabled';

type Outcome = 'delivered' | 'waiting' | 'failed';

interface LogRow {
  id: string;
  entity_type: string;
  label: string;
  outcome: Outcome;
  status: string;
  attempts: number;
  reason: string | null;
  tally_company: string | null;
  pushed_by: string | null;
  created_at: string | null;
  completed_at: string | null;
  next_attempt_at: string | null;
}

interface LogResponse {
  mode: string;
  total: number;
  summary: { delivered: number; waiting: number; failed: number };
  items: LogRow[];
}

const KIND: Record<string, string> = {
  invoice: 'Invoice',
  credit_note: 'Credit Note',
  debit_note: 'Debit Note',
  party: 'Customer / Supplier',
  product: 'Item',
  ledger: 'Ledgers + Units',
  quotation: 'Sales Order',
  purchase_order: 'Purchase Order',
};

const fmtDT = (v: string | null) =>
  v ? new Date(v).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', dateStyle: 'medium', timeStyle: 'short' }) : '—';

function OutcomeBadge({ outcome }: { outcome: Outcome }) {
  if (outcome === 'delivered')
    return <Badge className="bg-emerald-100 text-emerald-700 gap-1"><CheckCircle2 className="h-3 w-3" />In Tally</Badge>;
  if (outcome === 'failed')
    return <Badge className="bg-rose-100 text-rose-700 gap-1"><XCircle className="h-3 w-3" />Rejected</Badge>;
  return <Badge variant="secondary" className="gap-1"><Clock className="h-3 w-3" />Waiting</Badge>;
}

export default function TallySyncLogPage() {
  const tallyEnabled = useTallyEnabled();
  const [data, setData] = useState<LogResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [outcome, setOutcome] = useState<'' | Outcome>('');
  const [search, setSearch] = useState('');
  const [applied, setApplied] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string | number> = { page_size: 300 };
      if (outcome) params.status = outcome;
      if (applied.trim()) params.search = applied.trim();
      const { data } = await api.get<LogResponse>('/api/v1/tally/sync-log', { params });
      setData(data);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [outcome, applied]);

  useEffect(() => { if (tallyEnabled) void load(); }, [tallyEnabled, load]);

  if (!tallyEnabled) {
    return (
      <Card>
        <CardContent className="pt-6 text-sm text-muted-foreground">
          Tally integration is switched off. Turn it on in <b>Settings → Tally</b> to see the sync log.
        </CardContent>
      </Card>
    );
  }

  const s = data?.summary;
  const columns: ColumnDef<LogRow>[] = [
    {
      key: 'outcome', label: 'Result', type: 'enum', enumOptions: ['In Tally', 'Waiting', 'Rejected'],
      accessor: r => (r.outcome === 'delivered' ? 'In Tally' : r.outcome === 'failed' ? 'Rejected' : 'Waiting'),
      format: (_v, r) => <OutcomeBadge outcome={r.outcome} />,
      exportValue: r => r.outcome,
    },
    {
      key: 'kind', label: 'Type', type: 'enum',
      enumOptions: Array.from(new Set(Object.values(KIND))),
      accessor: r => KIND[r.entity_type] ?? r.entity_type,
    },
    { key: 'label', label: 'Record', accessor: r => r.label ?? '—' },
    {
      key: 'reason', label: 'Tally said', accessor: r => r.reason ?? '',
      format: v => v ? <span className="text-rose-600 text-xs">{String(v)}</span> : <span className="text-muted-foreground">—</span>,
    },
    {
      key: 'pushed_by', label: 'Pushed by', accessor: r => r.pushed_by ?? '',
      format: v => v ? String(v) : <span className="text-muted-foreground">—</span>,
    },
    { key: 'attempts', label: 'Tries', type: 'number', align: 'right', accessor: r => r.attempts },
    {
      key: 'when', label: 'When (IST)', type: 'date',
      accessor: r => r.completed_at ?? r.created_at ?? '',
      format: v => fmtDT(v ? String(v) : null),
    },
    { key: 'company', label: 'Tally company', defaultVisible: false, accessor: r => r.tally_company ?? '—' },
  ];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <div>
          <h1 className="text-xl font-semibold">Tally Sync Log</h1>
          <p className="text-xs text-muted-foreground">
            What Tally itself reported for every record sent.
            {data?.mode === 'direct' && ' This company pushes to Tally directly, so only queued work appears here.'}
          </p>
        </div>
        <Button variant="outline" size="sm" className="ml-auto gap-1.5" onClick={() => void load()} disabled={loading}>
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </Button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {([
          ['In Tally', s?.delivered ?? 0, 'text-emerald-600', 'delivered'],
          ['Waiting', s?.waiting ?? 0, 'text-amber-600', 'waiting'],
          ['Rejected', s?.failed ?? 0, 'text-rose-600', 'failed'],
        ] as const).map(([label, n, cls, key]) => (
          <Card
            key={label}
            className={`cursor-pointer transition ${outcome === key ? 'ring-2 ring-primary' : 'hover:bg-muted/40'}`}
            onClick={() => setOutcome(outcome === key ? '' : key)}
          >
            <CardHeader className="pb-1"><CardTitle className="text-xs text-muted-foreground">{label}</CardTitle></CardHeader>
            <CardContent className={`text-2xl font-semibold ${cls}`}>{n}</CardContent>
          </Card>
        ))}
      </div>

      <div className="flex flex-wrap gap-2">
        <Input
          placeholder="Search invoice no, customer, item…"
          value={search}
          onChange={e => setSearch(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') setApplied(search); }}
          className="max-w-xs"
        />
        <Button variant="outline" size="sm" onClick={() => setApplied(search)}>Search</Button>
        {(outcome || applied) && (
          <Button variant="ghost" size="sm" onClick={() => { setOutcome(''); setSearch(''); setApplied(''); }}>
            Clear
          </Button>
        )}
      </div>

      <DataTable<LogRow>
        id="tally.syncLog"
        data={data?.items ?? []}
        columns={columns}
        rowKey={r => r.id}
        loading={loading}
        exportFilename="tally-sync-log"
        defaultSort={{ key: 'when', direction: 'desc' }}
        emptyMessage={outcome || applied ? 'Nothing matches that filter.' : 'Nothing has been sent to Tally yet.'}
      />
    </div>
  );
}
