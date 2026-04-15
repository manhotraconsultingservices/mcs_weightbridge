import { useEffect, useState, useCallback, useMemo } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  Cell, Legend,
} from 'recharts';
import { Download, RefreshCw, Calendar } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { TokenDetailModal } from '@/components/TokenDetailModal';
import api from '@/services/api';
import type { Token, TokenListResponse } from '@/types';

// ── Helpers ────────────────────────────────────────────────────────────── //

function today() { return new Date().toISOString().split('T')[0]; }

function weekStart(d: Date) {
  const x = new Date(d);
  x.setDate(x.getDate() - x.getDay());
  return x.toISOString().split('T')[0];
}

function monthKey(dateStr: string) {
  return dateStr.slice(0, 7); // YYYY-MM
}

function fmt(d: string) {
  const [y, m, day] = d.split('-');
  return `${day}/${m}/${y.slice(2)}`;
}

function fmtMonth(ym: string) {
  const [y, m] = ym.split('-');
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  return `${months[+m - 1]} ${y.slice(2)}`;
}

function mtFmt(kg: number | null | undefined) {
  if (kg == null) return '—';
  return (kg / 1000).toLocaleString('en-IN', { minimumFractionDigits: 3, maximumFractionDigits: 3 }) + ' MT';
}

function kgFmt(kg: number | null | undefined) {
  if (kg == null) return '—';
  return kg.toLocaleString('en-IN', { minimumFractionDigits: 2 }) + ' kg';
}

const STATUS_CONFIG = {
  OPEN:          { label: 'Open',          color: 'bg-blue-100 text-blue-700 border-blue-200' },
  FIRST_WEIGHT:  { label: '1st Wt Done',   color: 'bg-amber-100 text-amber-700 border-amber-200' },
  LOADING:       { label: 'Loading',       color: 'bg-orange-100 text-orange-700 border-orange-200' },
  SECOND_WEIGHT: { label: '2nd Wt Pending', color: 'bg-purple-100 text-purple-700 border-purple-200' },
  COMPLETED:     { label: 'Completed',     color: 'bg-green-100 text-green-700 border-green-200' },
  CANCELLED:     { label: 'Cancelled',     color: 'bg-red-100 text-red-700 border-red-200' },
} as const;

const CHART_COLORS = ['#3b82f6','#10b981','#f59e0b','#8b5cf6','#ef4444','#06b6d4','#f97316','#84cc16'];

type Granularity = 'daily' | 'weekly' | 'monthly';

// ── Preset date ranges ─────────────────────────────────────────────────── //

function getPreset(preset: string): [string, string] {
  const t = new Date();
  const to = today();
  if (preset === 'today') return [to, to];
  if (preset === 'week') {
    const from = new Date(t);
    from.setDate(t.getDate() - 6);
    return [from.toISOString().split('T')[0], to];
  }
  if (preset === 'month') {
    const from = new Date(t.getFullYear(), t.getMonth(), 1);
    return [from.toISOString().split('T')[0], to];
  }
  if (preset === '3months') {
    const from = new Date(t);
    from.setMonth(t.getMonth() - 3);
    return [from.toISOString().split('T')[0], to];
  }
  return [to, to];
}

// ── CSV export ─────────────────────────────────────────────────────────── //

function exportCsv(tokens: Token[]) {
  const rows = [
    ['Token No', 'Date', 'Type', 'Status', 'Vehicle', 'Party', 'Product', 'Gross (kg)', 'Tare (kg)', 'Net (kg)', 'Net (MT)'],
    ...tokens.map(t => [
      t.token_no ?? '',
      t.token_date ?? '',
      t.token_type ?? '',
      t.status,
      t.vehicle_no ?? '',
      t.party?.name ?? '',
      t.product?.name ?? '',
      t.gross_weight ?? '',
      t.tare_weight ?? '',
      t.net_weight ?? '',
      t.net_weight ? (t.net_weight / 1000).toFixed(3) : '',
    ]),
  ];
  const csv = rows.map(r => r.map(c => `"${c}"`).join(',')).join('\n');
  const blob = new Blob([csv], { type: 'text/csv' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `tokens_${Date.now()}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// ── Summary card ───────────────────────────────────────────────────────── //

function SummaryCard({ label, value, sub, accent }: { label: string; value: string | number; sub?: string; accent?: string }) {
  return (
    <div className={`rounded-lg border bg-card p-4 ${accent ?? ''}`}>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-2xl font-bold mt-1">{value}</p>
      {sub && <p className="text-xs text-muted-foreground mt-0.5">{sub}</p>}
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────── //

export default function TokenPage() {
  const [tokens, setTokens] = useState<Token[]>([]);
  const [loading, setLoading] = useState(false);
  const [dateFrom, setDateFrom] = useState(today());
  const [dateTo, setDateTo] = useState(today());
  const [activePreset, setActivePreset] = useState<string>('today');
  const [granularity, setGranularity] = useState<Granularity>('daily');
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<Set<string>>(new Set());
  const [detailToken, setDetailToken] = useState<Token | null>(null);

  // ── Fetch all tokens for the period ──────────────────────────────────── //

  const fetchTokens = useCallback(async (from: string, to: string) => {
    setLoading(true);
    try {
      const all: Token[] = [];
      let page = 1;
      while (true) {
        const params = new URLSearchParams({ page: String(page), page_size: '100', date_from: from, date_to: to });
        const { data } = await api.get<TokenListResponse>(`/api/v1/tokens?${params}`);
        all.push(...data.items);
        if (all.length >= data.total || data.items.length < 100) break;
        page++;
        if (page > 10) break; // safety cap at 1000
      }
      setTokens(all);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchTokens(dateFrom, dateTo); }, [fetchTokens, dateFrom, dateTo]);

  function applyPreset(preset: string) {
    setActivePreset(preset);
    const [from, to] = getPreset(preset);
    setDateFrom(from);
    setDateTo(to);
    // Auto-select sensible granularity
    if (preset === 'today') setGranularity('daily');
    else if (preset === 'week') setGranularity('daily');
    else if (preset === 'month') setGranularity('daily');
    else setGranularity('monthly');
  }

  // ── Aggregations ──────────────────────────────────────────────────────── //

  const completed = useMemo(() => tokens.filter(t => t.status === 'COMPLETED'), [tokens]);
  const active = useMemo(() => tokens.filter(t => !['COMPLETED', 'CANCELLED'].includes(t.status)), [tokens]);
  const cancelled = useMemo(() => tokens.filter(t => t.status === 'CANCELLED'), [tokens]);
  const totalNet = useMemo(() => completed.reduce((s, t) => s + (t.net_weight ?? 0), 0), [completed]);

  // Trend data
  const trendData = useMemo(() => {
    const map = new Map<string, number>();
    for (const t of tokens) {
      const d = t.token_date ?? t.created_at?.slice(0, 10) ?? '';
      if (!d) continue;
      let key = d;
      if (granularity === 'weekly') key = weekStart(new Date(d));
      else if (granularity === 'monthly') key = monthKey(d);
      map.set(key, (map.get(key) ?? 0) + 1);
    }
    return Array.from(map.entries())
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([key, count]) => ({
        label: granularity === 'monthly' ? fmtMonth(key) : fmt(key),
        count,
      }));
  }, [tokens, granularity]);

  // Token by Party (top 10)
  const partyData = useMemo(() => {
    const map = new Map<string, { sale: number; purchase: number }>();
    for (const t of tokens) {
      const name = t.party?.name ?? 'Unknown';
      const prev = map.get(name) ?? { sale: 0, purchase: 0 };
      if (t.token_type === 'purchase') prev.purchase++;
      else prev.sale++;
      map.set(name, prev);
    }
    return Array.from(map.entries())
      .map(([name, v]) => ({ name, sale: v.sale, purchase: v.purchase, total: v.sale + v.purchase }))
      .sort((a, b) => b.total - a.total)
      .slice(0, 10);
  }, [tokens]);

  // Token by Product (top 10)
  const productData = useMemo(() => {
    const map = new Map<string, { count: number; netKg: number }>();
    for (const t of tokens) {
      const name = t.product?.name ?? 'Unknown';
      const prev = map.get(name) ?? { count: 0, netKg: 0 };
      prev.count++;
      prev.netKg += t.net_weight ?? 0;
      map.set(name, prev);
    }
    return Array.from(map.entries())
      .map(([name, v]) => ({ name, count: v.count, netMT: +(v.netKg / 1000).toFixed(3) }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 10);
  }, [tokens]);

  // ── Filtered table ────────────────────────────────────────────────────── //

  const filtered = useMemo(() => {
    let list = tokens;
    if (search) {
      const q = search.toLowerCase();
      list = list.filter(t =>
        t.vehicle_no?.toLowerCase().includes(q) ||
        t.party?.name?.toLowerCase().includes(q) ||
        t.product?.name?.toLowerCase().includes(q) ||
        String(t.token_no ?? '').includes(q)
      );
    }
    if (statusFilter.size > 0) {
      list = list.filter(t => statusFilter.has(t.status));
    }
    return list;
  }, [tokens, search, statusFilter]);

  function toggleStatus(s: string) {
    setStatusFilter(prev => {
      const next = new Set(prev);
      if (next.has(s)) next.delete(s); else next.add(s);
      return next;
    });
  }

  // ── Render ────────────────────────────────────────────────────────────── //

  const PRESETS = [
    { key: 'today', label: 'Today' },
    { key: 'week', label: 'Last 7 Days' },
    { key: 'month', label: 'This Month' },
    { key: '3months', label: 'Last 3 Months' },
  ];

  return (
    <div className="space-y-4">
      {/* ── Header ── */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold">Token Dashboard</h1>
          <p className="text-xs text-muted-foreground">{tokens.length} tokens in selected period</p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {/* Preset buttons */}
          {PRESETS.map(p => (
            <Button
              key={p.key}
              size="sm"
              variant={activePreset === p.key ? 'default' : 'outline'}
              onClick={() => applyPreset(p.key)}
            >
              {p.label}
            </Button>
          ))}

          {/* Custom date range */}
          <div className="flex items-center gap-1">
            <Calendar className="h-3.5 w-3.5 text-muted-foreground" />
            <Input type="date" value={dateFrom} onChange={e => { setDateFrom(e.target.value); setActivePreset('custom'); }} className="h-8 w-32 text-xs" />
            <span className="text-muted-foreground text-xs">–</span>
            <Input type="date" value={dateTo} onChange={e => { setDateTo(e.target.value); setActivePreset('custom'); }} className="h-8 w-32 text-xs" />
          </div>

          <Button size="sm" variant="outline" onClick={() => fetchTokens(dateFrom, dateTo)} disabled={loading}>
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
          </Button>
        </div>
      </div>

      {/* ── Summary cards ── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <SummaryCard label="Total Tokens" value={tokens.length} sub={`${active.length} active`} />
        <SummaryCard label="Completed" value={completed.length} sub={`${((completed.length / Math.max(tokens.length, 1)) * 100).toFixed(0)}% of total`} accent="border-green-200" />
        <SummaryCard label="Net Tonnage" value={mtFmt(totalNet)} sub="Completed tokens" accent="border-blue-200" />
        <SummaryCard label="Cancelled" value={cancelled.length} sub={active.length + ' still active'} />
      </div>

      {/* ── Charts row ── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

        {/* Token Trend */}
        <div className="lg:col-span-1 rounded-lg border bg-card p-4">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold">Token Trend</h2>
            <div className="flex gap-1">
              {(['daily', 'weekly', 'monthly'] as Granularity[]).map(g => (
                <button
                  key={g}
                  onClick={() => setGranularity(g)}
                  className={`px-2 py-0.5 rounded text-xs font-medium transition-colors ${granularity === g ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground hover:text-foreground'}`}
                >
                  {g.charAt(0).toUpperCase() + g.slice(1)}
                </button>
              ))}
            </div>
          </div>
          {trendData.length === 0 ? (
            <div className="h-44 flex items-center justify-center text-xs text-muted-foreground">No data</div>
          ) : (
            <ResponsiveContainer width="100%" height={176}>
              <BarChart data={trendData} margin={{ top: 4, right: 4, bottom: 20, left: -20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis dataKey="label" tick={{ fontSize: 10 }} angle={-35} textAnchor="end" interval={0} />
                <YAxis tick={{ fontSize: 10 }} allowDecimals={false} />
                <Tooltip contentStyle={{ fontSize: 12 }} />
                <Bar dataKey="count" fill="#3b82f6" radius={[3, 3, 0, 0]} name="Tokens" />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Token by Party */}
        <div className="rounded-lg border bg-card p-4">
          <h2 className="text-sm font-semibold mb-3">Token by Party <span className="text-xs font-normal text-muted-foreground">(top 10)</span></h2>
          {partyData.length === 0 ? (
            <div className="h-44 flex items-center justify-center text-xs text-muted-foreground">No data</div>
          ) : (
            <ResponsiveContainer width="100%" height={176}>
              <BarChart data={partyData} layout="vertical" margin={{ top: 4, right: 20, bottom: 4, left: 4 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis type="number" tick={{ fontSize: 10 }} allowDecimals={false} />
                <YAxis type="category" dataKey="name" tick={{ fontSize: 9 }} width={80} />
                <Tooltip contentStyle={{ fontSize: 12 }} />
                <Legend iconSize={10} wrapperStyle={{ fontSize: 10 }} />
                <Bar dataKey="sale" stackId="a" fill="#3b82f6" name="Sale" radius={[0, 0, 0, 0]} />
                <Bar dataKey="purchase" stackId="a" fill="#10b981" name="Purchase" radius={[0, 3, 3, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Token by Product */}
        <div className="rounded-lg border bg-card p-4">
          <h2 className="text-sm font-semibold mb-3">Token by Product <span className="text-xs font-normal text-muted-foreground">(top 10)</span></h2>
          {productData.length === 0 ? (
            <div className="h-44 flex items-center justify-center text-xs text-muted-foreground">No data</div>
          ) : (
            <ResponsiveContainer width="100%" height={176}>
              <BarChart data={productData} layout="vertical" margin={{ top: 4, right: 20, bottom: 4, left: 4 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis type="number" tick={{ fontSize: 10 }} allowDecimals={false} />
                <YAxis type="category" dataKey="name" tick={{ fontSize: 9 }} width={80} />
                <Tooltip
                  contentStyle={{ fontSize: 12 }}
                  formatter={(value, name, props) => [
                    `${value} tokens (${props.payload.netMT} MT)`,
                    'Count',
                  ]}
                />
                <Bar dataKey="count" fill="#8b5cf6" radius={[0, 3, 3, 0]} name="Tokens">
                  {productData.map((_, i) => (
                    <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* ── Token Table ── */}
      <div className="rounded-lg border bg-card">
        {/* Table header / controls */}
        <div className="flex flex-wrap items-center justify-between gap-3 p-3 border-b">
          <div className="flex flex-wrap items-center gap-2">
            <Input
              placeholder="Search vehicle, party, product, token…"
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="h-8 w-56 text-xs"
            />
            {/* Status filter pills */}
            <div className="flex flex-wrap gap-1">
              {(Object.keys(STATUS_CONFIG) as Array<keyof typeof STATUS_CONFIG>)
                .filter(s => !['OPEN', 'LOADING', 'SECOND_WEIGHT'].includes(s))
                .map(s => (
                <button
                  key={s}
                  onClick={() => toggleStatus(s)}
                  className={`px-2 py-0.5 rounded-full border text-xs font-medium transition-colors ${
                    statusFilter.has(s)
                      ? STATUS_CONFIG[s].color + ' ring-1 ring-current'
                      : 'border-border text-muted-foreground hover:border-foreground/30'
                  }`}
                >
                  {STATUS_CONFIG[s].label}
                </button>
              ))}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground">{filtered.length} rows</span>
            <Button size="sm" variant="outline" onClick={() => exportCsv(filtered)} disabled={filtered.length === 0}>
              <Download className="h-3.5 w-3.5 mr-1" />
              CSV
            </Button>
          </div>
        </div>

        {/* Table */}
        <div className="overflow-x-auto">
          <div
            className="grid text-xs font-medium text-muted-foreground bg-muted/40 border-b"
            style={{ gridTemplateColumns: '60px 90px 80px 1fr 90px 90px 90px 80px' }}
          >
            {['Token', 'Date', 'Type', 'Vehicle / Party / Product', 'Gross', 'Tare', 'Net', 'Status'].map(h => (
              <div key={h} className="px-3 py-2">{h}</div>
            ))}
          </div>

          {loading && (
            <div className="py-10 text-center text-xs text-muted-foreground">Loading…</div>
          )}
          {!loading && filtered.length === 0 && (
            <div className="py-10 text-center text-xs text-muted-foreground">No tokens found</div>
          )}

          {filtered.map(token => (
            <div
              key={token.id}
              className="grid border-b last:border-0 hover:bg-muted/30 cursor-pointer text-xs items-center"
              style={{ gridTemplateColumns: '60px 90px 80px 1fr 90px 90px 90px 80px' }}
              onClick={() => setDetailToken(token)}
            >
              <div className="px-3 py-2 font-mono font-bold">{token.token_no ?? '—'}</div>
              <div className="px-3 py-2 text-muted-foreground">{token.token_date ?? '—'}</div>
              <div className="px-3 py-2">
                <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${token.token_type === 'purchase' ? 'bg-amber-100 text-amber-700' : 'bg-blue-100 text-blue-700'}`}>
                  {(token.token_type ?? 'sale').toUpperCase()}
                </span>
              </div>
              <div className="px-3 py-2 min-w-0">
                <p className="font-mono font-semibold tracking-wide whitespace-nowrap overflow-hidden text-ellipsis">{token.vehicle_no ?? '—'}</p>
                <p className="text-muted-foreground truncate">{token.party?.name ?? '—'}</p>
                <p className="text-muted-foreground/70 truncate">{token.product?.name ?? '—'}</p>
              </div>
              <div className="px-3 py-2 whitespace-nowrap text-right">{kgFmt(token.gross_weight)}</div>
              <div className="px-3 py-2 whitespace-nowrap text-right">{kgFmt(token.tare_weight)}</div>
              <div className="px-3 py-2 whitespace-nowrap text-right font-semibold">{mtFmt(token.net_weight)}</div>
              <div className="px-3 py-2">
                <Badge
                  variant="outline"
                  className={`text-[10px] px-1.5 py-0 whitespace-nowrap ${STATUS_CONFIG[token.status]?.color ?? ''}`}
                >
                  {STATUS_CONFIG[token.status]?.label ?? token.status}
                </Badge>
              </div>
            </div>
          ))}
        </div>
      </div>

      {detailToken && (
        <TokenDetailModal tokenId={detailToken.id} onClose={() => setDetailToken(null)} />
      )}
    </div>
  );
}
