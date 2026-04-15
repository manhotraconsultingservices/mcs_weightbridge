import { useEffect, useState, useMemo, useCallback } from 'react';
import {
  Scale, IndianRupee, Package, AlertCircle,
  TrendingUp, TrendingDown, Activity, Printer,
  Truck, ArrowUpDown, ArrowUp, ArrowDown, RefreshCw, Search, X, Usb,
  ShieldCheck, ExternalLink,
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import {
  AreaChart, Area, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer,
} from 'recharts';
import { Link } from 'react-router-dom';
import api from '@/services/api';
import { useUsbGuard } from '@/hooks/useUsbGuard';
import { TokenDetailModal } from '@/components/TokenDetailModal';
import { PrintButton } from '@/components/PrintButton';
import type { Token } from '@/types';

// ── Types ─────────────────────────────────────────────────────────────────────

interface DashboardSummary {
  tokens_today: number;
  revenue_today: number;
  tonnage_today: number;
  outstanding: number;
  revenue_month: number;
  tokens_month: number;
  supplement_included: boolean;
  recent_tokens: {
    id: string;
    token_no: number;
    token_date: string;
    status: string;
    token_type: string;
    vehicle_no: string | null;
    party_name: string | null;
    net_weight: number | null;
    is_supplement?: boolean;
  }[];
  top_customers: { name: string; total: number }[];
}

interface ChartsData {
  daily_trend: { date: string; revenue: number; tonnage: number }[];
  product_tonnage: { product: string; tonnage: number }[];
  token_status: Record<string, number>;
  payment_pipeline: { month: string; paid: number; unpaid: number }[];
  supplement_included: boolean;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const INR = (v: number) =>
  '₹' + v.toLocaleString('en-IN', { minimumFractionDigits: 0, maximumFractionDigits: 0 });

const STATUS_COLORS: Record<string, string> = {
  OPEN: 'bg-blue-100 text-blue-800',
  FIRST_WEIGHT: 'bg-yellow-100 text-yellow-800',
  LOADING: 'bg-orange-100 text-orange-800',
  SECOND_WEIGHT: 'bg-purple-100 text-purple-800',
  COMPLETED: 'bg-green-100 text-green-800',
  CANCELLED: 'bg-red-100 text-red-800',
};

const PIE_COLORS = ['#3b82f6', '#f59e0b', '#f97316', '#8b5cf6', '#22c55e', '#ef4444'];

// Tailwind dynamic class safety — keep these hardcoded
const ACCENT_CLASSES: Record<string, { border: string; icon: string }> = {
  blue:   { border: 'border-t-blue-500',   icon: 'text-blue-500' },
  green:  { border: 'border-t-green-500',  icon: 'text-green-500' },
  violet: { border: 'border-t-violet-500', icon: 'text-violet-500' },
  orange: { border: 'border-t-orange-500', icon: 'text-orange-500' },
};

// ── KPI Card ──────────────────────────────────────────────────────────────────

interface KpiCardProps {
  title: string;
  value: string;
  sub: string;
  icon: React.ElementType;
  accent: keyof typeof ACCENT_CLASSES;
  trend?: number | null;
  progress?: number | null;   // 0-100, shows mini progress bar when set
  progressLabel?: string;     // e.g. "42% of month"
}

const PROGRESS_CLASSES: Record<string, string> = {
  blue:   'bg-blue-500',
  green:  'bg-green-500',
  violet: 'bg-violet-500',
  orange: 'bg-orange-500',
};

function KpiCard({ title, value, sub, icon: Icon, accent, trend, progress, progressLabel }: KpiCardProps) {
  const { border, icon: iconCls } = ACCENT_CLASSES[accent];
  const pct = progress != null ? Math.min(100, Math.max(0, progress)) : null;
  return (
    <Card className={`border-t-4 ${border} shadow-sm`}>
      <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
        <CardTitle className="text-sm font-medium text-muted-foreground">{title}</CardTitle>
        <Icon className={`h-4 w-4 ${iconCls}`} />
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-bold">{value}</div>
        <p className="text-xs text-muted-foreground mt-1 flex items-center gap-1">
          {trend != null ? (
            trend >= 0
              ? <TrendingUp className="h-3 w-3 text-green-500" />
              : <TrendingDown className="h-3 w-3 text-red-500" />
          ) : null}
          {sub}
        </p>
        {pct != null && (
          <div className="mt-2">
            <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500 ${PROGRESS_CLASSES[accent]}`}
                style={{ width: `${pct}%` }}
              />
            </div>
            {progressLabel && (
              <p className="text-[10px] text-muted-foreground mt-0.5">{progressLabel}</p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── Skeleton placeholder ───────────────────────────────────────────────────────

function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`bg-muted animate-pulse rounded ${className}`} />;
}

// ── Chart empty state ──────────────────────────────────────────────────────────

function EmptyChart({ message = 'No data yet' }: { message?: string }) {
  return (
    <div className="flex h-40 items-center justify-center text-sm text-muted-foreground">
      <Activity className="h-4 w-4 mr-2 opacity-40" />{message}
    </div>
  );
}

// ── Custom Tooltip ─────────────────────────────────────────────────────────────

function RevenueTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border bg-background p-2 text-xs shadow-md">
      <p className="font-semibold mb-1">{label}</p>
      {payload.map((p: any) => (
        <p key={p.dataKey} style={{ color: p.color }}>
          {p.name}: {p.dataKey === 'revenue' ? INR(p.value) : `${p.value} MT`}
        </p>
      ))}
    </div>
  );
}

function PipelineTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border bg-background p-2 text-xs shadow-md">
      <p className="font-semibold mb-1">{label}</p>
      {payload.map((p: any) => (
        <p key={p.dataKey} style={{ color: p.fill }}>{p.name}: {INR(p.value)}</p>
      ))}
    </div>
  );
}

// ── Active Trucks on Weighbridge ──────────────────────────────────────────────

const ACTIVE_STATUSES = ['OPEN', 'FIRST_WEIGHT', 'LOADING', 'SECOND_WEIGHT'];

type SortCol = 'token_no' | 'status' | 'direction' | 'vehicle_no' | 'party' | 'product' | 'first_weight' | 'time_on_site';

function timeOnSite(created_at: string): string {
  const diff = Math.floor((Date.now() - new Date(created_at).getTime()) / 1000);
  if (diff < 60) return `${diff}s`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m`;
  const h = Math.floor(diff / 3600);
  const m = Math.floor((diff % 3600) / 60);
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}

function timeOnSiteSeconds(created_at: string): number {
  return Math.floor((Date.now() - new Date(created_at).getTime()) / 1000);
}

function SortIcon({ col, sort }: { col: SortCol; sort: { col: SortCol; dir: 'asc' | 'desc' } }) {
  if (sort.col !== col) return <ArrowUpDown className="h-3 w-3 opacity-30 ml-1" />;
  return sort.dir === 'asc'
    ? <ArrowUp className="h-3 w-3 ml-1 text-primary" />
    : <ArrowDown className="h-3 w-3 ml-1 text-primary" />;
}

function ActiveTrucksTable({ onSelectToken }: { onSelectToken: (id: string) => void }) {
  const [trucks, setTrucks] = useState<Token[]>([]);
  const [loadingTrucks, setLoadingTrucks] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('ALL');
  const [dirFilter, setDirFilter] = useState('ALL');
  const [sort, setSort] = useState<{ col: SortCol; dir: 'asc' | 'desc' }>({ col: 'time_on_site', dir: 'desc' });

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<Token[]>('/api/v1/tokens/today');
      setTrucks(data.filter(t => ACTIVE_STATUSES.includes(t.status)));
      setLastRefresh(new Date());
    } catch { /* silent */ }
    finally { setLoadingTrucks(false); }
  }, []);

  useEffect(() => {
    load();
    const interval = setInterval(load, 30_000);
    return () => clearInterval(interval);
  }, [load]);

  function toggleSort(col: SortCol) {
    setSort(s => s.col === col ? { col, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { col, dir: 'asc' });
  }

  const filtered = useMemo(() => {
    let rows = trucks;
    if (statusFilter !== 'ALL') rows = rows.filter(t => t.status === statusFilter);
    if (dirFilter !== 'ALL') rows = rows.filter(t => t.direction === dirFilter);
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      rows = rows.filter(t =>
        t.vehicle_no?.toLowerCase().includes(q) ||
        t.party?.name?.toLowerCase().includes(q) ||
        t.product?.name?.toLowerCase().includes(q) ||
        String(t.token_no ?? '').includes(q)
      );
    }
    return [...rows].sort((a, b) => {
      let av: number | string = 0, bv: number | string = 0;
      switch (sort.col) {
        case 'token_no':    av = a.token_no ?? 0; bv = b.token_no ?? 0; break;
        case 'status':      av = a.status; bv = b.status; break;
        case 'direction':   av = a.direction; bv = b.direction; break;
        case 'vehicle_no':  av = a.vehicle_no ?? ''; bv = b.vehicle_no ?? ''; break;
        case 'party':       av = a.party?.name ?? ''; bv = b.party?.name ?? ''; break;
        case 'product':     av = a.product?.name ?? ''; bv = b.product?.name ?? ''; break;
        case 'first_weight': av = Number(a.first_weight ?? 0); bv = Number(b.first_weight ?? 0); break;
        case 'time_on_site': av = timeOnSiteSeconds(a.created_at); bv = timeOnSiteSeconds(b.created_at); break;
      }
      const cmp = typeof av === 'string' ? av.localeCompare(bv as string) : (av as number) - (bv as number);
      return sort.dir === 'asc' ? cmp : -cmp;
    });
  }, [trucks, statusFilter, dirFilter, search, sort]);

  const Th = ({ col, label }: { col: SortCol; label: string }) => (
    <th
      className="text-left p-3 font-medium cursor-pointer select-none hover:text-foreground whitespace-nowrap"
      onClick={() => toggleSort(col)}
    >
      <span className="inline-flex items-center gap-0.5">
        {label}<SortIcon col={col} sort={sort} />
      </span>
    </th>
  );

  const hasFilters = search || statusFilter !== 'ALL' || dirFilter !== 'ALL';

  return (
    <Card className="border-t-4 border-t-orange-400">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <CardTitle className="text-sm font-semibold flex items-center gap-2">
            <Truck className="h-4 w-4 text-orange-500" />
            Trucks on Weighbridge — Action Required
            {trucks.length > 0 && (
              <span className="ml-1 rounded-full bg-orange-100 text-orange-700 text-xs font-bold px-2 py-0.5">
                {trucks.length}
              </span>
            )}
          </CardTitle>
          <span className="text-[10px] text-muted-foreground">
            Last updated {lastRefresh.toLocaleTimeString('en-IN', { hour12: false })} · auto-refreshes every 30s
          </span>
        </div>

        {/* Filters */}
        <div className="flex items-center gap-2 mt-2 flex-wrap">
          <div className="relative flex-1 min-w-[160px] max-w-xs">
            <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Vehicle, party, product, token…"
              className="pl-8 h-8 text-xs"
            />
          </div>
          <Select value={statusFilter} onValueChange={v => setStatusFilter(v ?? 'ALL')}>
            <SelectTrigger className="h-8 text-xs w-40">
              <SelectValue placeholder="All Statuses" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL">All Statuses</SelectItem>
              <SelectItem value="OPEN">Open</SelectItem>
              <SelectItem value="FIRST_WEIGHT">First Weight</SelectItem>
              <SelectItem value="LOADING">Loading</SelectItem>
              <SelectItem value="SECOND_WEIGHT">Second Weight</SelectItem>
            </SelectContent>
          </Select>
          <Select value={dirFilter} onValueChange={v => setDirFilter(v ?? 'ALL')}>
            <SelectTrigger className="h-8 text-xs w-36">
              <SelectValue placeholder="All Directions" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL">All Directions</SelectItem>
              <SelectItem value="inbound">Inbound</SelectItem>
              <SelectItem value="outbound">Outbound</SelectItem>
            </SelectContent>
          </Select>
          {hasFilters && (
            <Button variant="ghost" size="sm" className="h-8 px-2 text-xs" onClick={() => { setSearch(''); setStatusFilter('ALL'); setDirFilter('ALL'); }}>
              <X className="h-3 w-3 mr-1" /> Clear
            </Button>
          )}
          <Button variant="ghost" size="icon" className="h-8 w-8" onClick={load} title="Refresh now">
            <RefreshCw className="h-3.5 w-3.5" />
          </Button>
        </div>
      </CardHeader>

      <CardContent className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/40 text-xs text-muted-foreground">
                <Th col="token_no"     label="Token #" />
                <Th col="status"       label="Status" />
                <Th col="direction"    label="Direction" />
                <Th col="vehicle_no"   label="Vehicle" />
                <Th col="party"        label="Party" />
                <Th col="product"      label="Product" />
                <Th col="first_weight" label="1st Weight" />
                <Th col="time_on_site" label="Time on Site" />
              </tr>
            </thead>
            <tbody>
              {loadingTrucks ? (
                <tr><td colSpan={8} className="text-center py-8 text-muted-foreground text-sm">Loading…</td></tr>
              ) : filtered.length === 0 ? (
                <tr>
                  <td colSpan={8} className="text-center py-10 text-muted-foreground text-sm">
                    {trucks.length === 0 ? '✅ No trucks currently on the weighbridge.' : 'No results match filters.'}
                  </td>
                </tr>
              ) : filtered.map(t => {
                const secs = timeOnSiteSeconds(t.created_at);
                const urgentColor = secs > 7200 ? 'text-red-600 font-bold' : secs > 3600 ? 'text-orange-500 font-semibold' : 'text-muted-foreground';
                return (
                  <tr
                    key={t.id}
                    className="border-b hover:bg-muted/30 transition-colors cursor-pointer"
                    onClick={() => onSelectToken(t.id)}
                  >
                    <td className="p-3 font-mono font-bold text-primary">
                      {t.token_no != null ? `#${t.token_no}` : <span className="text-muted-foreground text-xs italic">—</span>}
                    </td>
                    <td className="p-3">
                      <span className={`text-xs rounded-full px-2 py-0.5 font-medium ${STATUS_COLORS[t.status] ?? 'bg-muted text-muted-foreground'}`}>
                        {t.status.replace(/_/g, ' ')}
                      </span>
                    </td>
                    <td className="p-3">
                      <span className={`text-xs rounded-full px-2 py-0.5 font-medium ${t.direction === 'inbound' ? 'bg-blue-50 text-blue-700' : 'bg-violet-50 text-violet-700'}`}>
                        {t.direction}
                      </span>
                    </td>
                    <td className="p-3 font-mono text-xs font-semibold">{t.vehicle_no ?? '—'}</td>
                    <td className="p-3 max-w-[140px] truncate">{t.party?.name ?? <span className="text-muted-foreground text-xs">—</span>}</td>
                    <td className="p-3 max-w-[120px] truncate text-muted-foreground">{t.product?.name ?? '—'}</td>
                    <td className="p-3 font-mono text-xs">
                      {t.first_weight != null
                        ? `${Number(t.first_weight).toLocaleString('en-IN', { minimumFractionDigits: 0 })} kg`
                        : <span className="text-muted-foreground">—</span>}
                    </td>
                    <td className={`p-3 font-mono text-xs ${urgentColor}`}>
                      {timeOnSite(t.created_at)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {filtered.length > 0 && (
          <p className="text-[10px] text-muted-foreground px-3 py-2 border-t">
            Showing {filtered.length} of {trucks.length} active trucks · Click row for details · Red = &gt;2h, Orange = &gt;1h
          </p>
        )}
      </CardContent>
    </Card>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

interface ComplianceAlert {
  id: string;
  item_type: string;
  name: string;
  expiry_date: string | null;
  days_to_expiry: number | null;
  alert_level: 'expired' | 'critical' | 'warning' | null;
}

export default function DashboardPage() {
  const { authorized: usbAuthorized } = useUsbGuard();
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [charts, setCharts] = useState<ChartsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [tokenModalId, setTokenModalId] = useState<string | null>(null);
  const [complianceAlerts, setComplianceAlerts] = useState<ComplianceAlert[]>([]);

  // Fetch compliance alerts (items expiring within 60 days or already expired)
  useEffect(() => {
    api.get<{ items: ComplianceAlert[]; total: number }>('/api/v1/compliance/alerts')
      .then(r => setComplianceAlerts(r.data?.items ?? []))
      .catch(() => {});
  }, []);

  const fetchDashboard = useCallback(async (withSupp: boolean) => {
    setLoading(true);
    const qs = withSupp ? '?include_supplement=true' : '';
    try {
      const [s, c] = await Promise.all([
        api.get<DashboardSummary>(`/api/v1/dashboard/summary${qs}`),
        api.get<ChartsData>(`/api/v1/dashboard/charts${qs}`),
      ]);
      setSummary(s.data);
      setCharts(c.data);
    } catch { /* ignore */ }
    finally { setLoading(false); }
  }, []);

  // Re-fetch immediately whenever USB state changes
  useEffect(() => {
    fetchDashboard(usbAuthorized);
  }, [usbAuthorized, fetchDashboard]);

  // ── Loading skeleton ─────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="space-y-6">
        <div><Skeleton className="h-8 w-48" /><Skeleton className="h-4 w-64 mt-1" /></div>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {[...Array(4)].map((_, i) => (
            <Card key={i} className="border-t-4 border-t-muted">
              <CardContent className="pt-6 space-y-2">
                <Skeleton className="h-4 w-28" />
                <Skeleton className="h-8 w-36" />
                <Skeleton className="h-3 w-24" />
              </CardContent>
            </Card>
          ))}
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          {[...Array(4)].map((_, i) => (
            <Card key={i}><CardContent className="pt-6"><Skeleton className="h-48 w-full" /></CardContent></Card>
          ))}
        </div>
      </div>
    );
  }

  const d = summary ?? {
    tokens_today: 0, revenue_today: 0, tonnage_today: 0, outstanding: 0,
    revenue_month: 0, tokens_month: 0, recent_tokens: [], top_customers: [],
  };
  const c = charts ?? {
    daily_trend: [], product_tonnage: [], token_status: {}, payment_pipeline: [],
  };

  // Pie data from token_status
  const pieData = Object.entries(c.token_status).map(([name, value]) => ({ name, value }));

  // Show only every 5th label on daily trend to avoid crowding
  const trendTickFormatter = (_: string, index: number) =>
    index % 5 === 0 ? c.daily_trend[index]?.date ?? '' : '';

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>
          <p className="text-muted-foreground text-sm">Today's activity and 30-day overview</p>
        </div>
        {/* USB data-mode indicator — only shown when USB is active */}
        {usbAuthorized && (
          <div className="flex items-center gap-2 rounded-lg bg-purple-50 border border-purple-200 px-3 py-2 text-xs font-medium text-purple-700">
            <Usb className="h-3.5 w-3.5" />
            USB connected — showing Sales + Supplement data
          </div>
        )}
      </div>

      {/* ── Compliance Alerts Banner ── */}
      {(complianceAlerts ?? []).length > 0 && (
        <div className="rounded-lg border border-orange-200 bg-orange-50 px-4 py-3">
          <div className="flex items-start gap-3">
            <ShieldCheck className="h-5 w-5 text-orange-500 shrink-0 mt-0.5" />
            <div className="flex-1 min-w-0">
              <p className="text-sm font-semibold text-orange-800 mb-1.5">
                Compliance Alerts — {complianceAlerts.length} item{complianceAlerts.length > 1 ? 's' : ''} need attention
              </p>
              <div className="flex flex-wrap gap-2">
                {complianceAlerts.slice(0, 5).map(alert => (
                  <span
                    key={alert.id}
                    className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium ${
                      alert.alert_level === 'expired'
                        ? 'bg-red-100 text-red-700 border-red-200'
                        : alert.alert_level === 'critical'
                        ? 'bg-orange-100 text-orange-700 border-orange-200'
                        : 'bg-yellow-100 text-yellow-700 border-yellow-200'
                    }`}
                  >
                    {alert.name}
                    {alert.alert_level === 'expired'
                      ? ' — EXPIRED'
                      : alert.days_to_expiry != null
                      ? ` — ${alert.days_to_expiry}d left`
                      : ''}
                  </span>
                ))}
                {complianceAlerts.length > 5 && (
                  <span className="text-[11px] text-orange-600">+{complianceAlerts.length - 5} more</span>
                )}
              </div>
            </div>
            <Link to="/compliance" className="shrink-0 text-xs text-orange-700 underline underline-offset-2 flex items-center gap-1 hover:text-orange-900">
              View All <ExternalLink className="h-3 w-3" />
            </Link>
          </div>
        </div>
      )}

      {/* ── KPI Cards ── */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          title="Today's Tokens"
          value={String(d.tokens_today)}
          sub={`${d.tokens_month} this month`}
          icon={Scale}
          accent="blue"
          progress={d.tokens_month > 0 ? Math.round((d.tokens_today / d.tokens_month) * 100) : null}
          progressLabel={d.tokens_month > 0 ? `${Math.round((d.tokens_today / d.tokens_month) * 100)}% of month total` : undefined}
        />
        <KpiCard
          title="Today's Revenue"
          value={INR(d.revenue_today)}
          sub={`${INR(d.revenue_month)} this month`}
          icon={IndianRupee}
          accent="green"
          progress={d.revenue_month > 0 ? Math.round((d.revenue_today / d.revenue_month) * 100) : null}
          progressLabel={d.revenue_month > 0 ? `${Math.round((d.revenue_today / d.revenue_month) * 100)}% of month total` : undefined}
        />
        <KpiCard
          title="Tonnage Today"
          value={`${(d.tonnage_today / 1000).toLocaleString('en-IN', { maximumFractionDigits: 2 })} MT`}
          sub="Net weight completed"
          icon={Package}
          accent="violet"
        />
        <KpiCard
          title="Outstanding"
          value={INR(d.outstanding)}
          sub="Total receivable"
          icon={AlertCircle}
          accent="orange"
        />
      </div>

      {/* ── Trucks on Weighbridge ── */}
      <ActiveTrucksTable onSelectToken={setTokenModalId} />

      {/* ── Charts Row 1: Revenue trend + Tonnage trend ── */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Revenue Trend — Last 30 Days</CardTitle>
          </CardHeader>
          <CardContent>
            {c.daily_trend.length === 0 ? <EmptyChart /> : (
              <ResponsiveContainer width="100%" height={200}>
                <AreaChart data={c.daily_trend} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="revGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.25} />
                      <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                  <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={trendTickFormatter} />
                  <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => `₹${(v / 1000).toFixed(0)}k`} width={48} />
                  <Tooltip content={<RevenueTooltip />} />
                  <Area type="monotone" dataKey="revenue" name="Revenue" stroke="#3b82f6" fill="url(#revGrad)" strokeWidth={2} dot={false} />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Daily Tonnage — Last 30 Days</CardTitle>
          </CardHeader>
          <CardContent>
            {c.daily_trend.length === 0 ? <EmptyChart /> : (
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={c.daily_trend} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                  <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={trendTickFormatter} />
                  <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => `${v}MT`} width={44} />
                  <Tooltip content={<RevenueTooltip />} />
                  <Bar dataKey="tonnage" name="Tonnage" fill="#8b5cf6" radius={[2, 2, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>
      </div>

      {/* ── Charts Row 2: Top products + Token status ── */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Top Products by Tonnage</CardTitle>
          </CardHeader>
          <CardContent>
            {c.product_tonnage.length === 0 ? <EmptyChart /> : (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart
                  data={c.product_tonnage}
                  layout="vertical"
                  margin={{ top: 4, right: 16, left: 8, bottom: 0 }}
                >
                  <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="hsl(var(--border))" />
                  <XAxis type="number" tick={{ fontSize: 10 }} tickFormatter={(v) => `${v}MT`} />
                  <YAxis
                    type="category"
                    dataKey="product"
                    width={90}
                    tick={{ fontSize: 10 }}
                    tickFormatter={(v: string) => v.length > 12 ? v.slice(0, 12) + '…' : v}
                  />
                  <Tooltip formatter={(v: number) => [`${v} MT`, 'Tonnage']} />
                  <Bar dataKey="tonnage" fill="#22c55e" radius={[0, 2, 2, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Token Status — This Month</CardTitle>
          </CardHeader>
          <CardContent className="flex items-center justify-center">
            {pieData.length === 0 ? <EmptyChart message="No tokens this month" /> : (
              <ResponsiveContainer width="100%" height={220}>
                <PieChart>
                  <Pie
                    data={pieData}
                    cx="50%"
                    cy="50%"
                    innerRadius={55}
                    outerRadius={85}
                    paddingAngle={3}
                    dataKey="value"
                  >
                    {pieData.map((_, idx) => (
                      <Cell key={idx} fill={PIE_COLORS[idx % PIE_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip formatter={(v: number, name: string) => [v, name.replace(/_/g, ' ')]} />
                  <Legend
                    iconType="circle"
                    iconSize={8}
                    formatter={(value: string) => (
                      <span style={{ fontSize: 11 }}>{value.replace(/_/g, ' ')}</span>
                    )}
                  />
                </PieChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>
      </div>

      {/* ── Chart Row 3: Payment pipeline (full width) ── */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium">Payment Pipeline — Last 6 Months</CardTitle>
        </CardHeader>
        <CardContent>
          {c.payment_pipeline.length === 0 ? <EmptyChart message="No invoice data yet" /> : (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={c.payment_pipeline} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                <XAxis dataKey="month" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => `₹${(v / 1000).toFixed(0)}k`} width={52} />
                <Tooltip content={<PipelineTooltip />} />
                <Legend iconType="square" iconSize={10} wrapperStyle={{ fontSize: 11 }} />
                <Bar dataKey="paid" name="Paid" stackId="a" fill="#22c55e" radius={[0, 0, 0, 0]} />
                <Bar dataKey="unpaid" name="Unpaid" stackId="a" fill="#f97316" radius={[2, 2, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>

      {/* ── Bottom Row: Recent tokens + Top customers ── */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Recent Tokens</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {d.recent_tokens.length === 0 ? (
              <div className="px-6 pb-6 text-sm text-muted-foreground">No tokens yet.</div>
            ) : (
              <div className="divide-y">
                {d.recent_tokens.map(t => (
                  <div key={t.id} className={`flex items-center gap-2 px-4 py-2.5 ${t.is_supplement ? 'bg-purple-50/50' : ''}`}>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <span className="text-sm font-medium">#{t.token_no}</span>
                        <Badge variant="outline" className={`text-[10px] py-0 ${STATUS_COLORS[t.status] || ''}`}>
                          {t.status}
                        </Badge>
                        {t.is_supplement && (
                          <span className="text-[10px] bg-purple-100 text-purple-700 rounded-full px-1.5 py-0 font-medium">SUPP</span>
                        )}
                        <span className="text-[10px] text-muted-foreground uppercase">{t.token_type}</span>
                      </div>
                      <p className="text-[11px] text-muted-foreground truncate max-w-[200px]">
                        {[t.party_name, t.vehicle_no].filter(Boolean).join(' · ')} · {t.token_date}
                      </p>
                    </div>
                    {t.net_weight != null && (
                      <span className="text-[11px] font-semibold shrink-0 text-muted-foreground">
                        {(t.net_weight / 1000).toLocaleString('en-IN', { maximumFractionDigits: 2 })} MT
                      </span>
                    )}
                    {t.status === 'COMPLETED' && (
                      <PrintButton url={`/api/v1/tokens/${t.id}/print`} iconOnly />
                    )}
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <TrendingUp className="h-4 w-4 text-green-500" /> Top Customers
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {d.top_customers.length === 0 ? (
              <div className="px-6 pb-6 text-sm text-muted-foreground">No invoice data yet.</div>
            ) : (
              <div className="divide-y">
                {d.top_customers.map((c, i) => (
                  <div key={c.name} className="flex items-center gap-3 px-4 py-2.5">
                    <span className="text-base font-bold text-muted-foreground/30 w-5 text-center shrink-0">{i + 1}</span>
                    <p className="flex-1 text-sm font-medium truncate">{c.name}</p>
                    <p className="text-sm font-semibold text-green-700 shrink-0">{INR(c.total)}</p>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <TokenDetailModal tokenId={tokenModalId} onClose={() => setTokenModalId(null)} />
    </div>
  );
}
