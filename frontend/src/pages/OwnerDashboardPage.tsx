/**
 * Owner Dashboard — exception-first, mobile-first.
 *
 * Inverts the old chart-heavy dashboard:
 *   • Traffic-light status line above the fold ("Plant healthy" or "3 things need you")
 *   • One action card per exception type (Overdue / Low Stock / Compliance / Yield)
 *   • Each card has a primary verb (WhatsApp · Raise PO · Renew · View)
 *   • Charts moved 1 tap deeper → "View 30-day trends" link to /dashboard-legacy
 *
 * Persona: business owner on a phone, 60-second glance.  If everything is fine,
 * he sees one green tick and closes the app.
 */
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate } from 'react-router-dom';
import {
  CheckCircle2, AlertTriangle, AlertCircle, Loader2,
  Phone, MessageCircle, ShoppingCart, ShieldAlert, Factory,
  TrendingUp, TrendingDown, IndianRupee, ChevronRight, RefreshCw,
  BarChart3,
} from 'lucide-react';
import { toast } from 'sonner';
import api from '@/services/api';
import AnprStatsCard from '@/components/AnprStatsCard';

// ── Types from /api/v1/dashboard/exceptions ────────────────────────────────

interface OverdueCustomer {
  party_id: string;
  party_name: string;
  phone: string | null;
  balance: number;
  oldest_overdue_days: number;
  aging_bucket: string;
}
interface LowStockProduct {
  product_id: string;
  product_name: string;
  unit: string;
  current_stock: number;
  min_stock_level: number;
  deficit: number;
  is_out: boolean;
}
interface ComplianceExpiring {
  item_id: string;
  name: string;
  type: string;
  expiry_date: string;
  days_to_expiry: number;
  alert_level: 'expired' | 'critical' | 'warning' | 'ok';
}
interface YieldVariance {
  cycle_id: string;
  today_yield_pct: number;
  target_yield_pct: number;
  variance_pct: number;
  is_finalised: boolean;
  status: 'on_track' | 'below' | 'critical';
}
interface ExceptionsResponse {
  status: 'healthy' | 'warning' | 'critical';
  headline: string;
  problem_count: number;
  overdue_customers: { items: OverdueCustomer[]; count: number; total_balance: number };
  low_stock_products: { items: LowStockProduct[]; count: number; out_of_stock_count: number };
  compliance_expiring: { items: ComplianceExpiring[]; count: number };
  yield_variance: YieldVariance | null;
  today_revenue: { today: number; median_30d: number; variance_pct: number };
}

const INR = (v: number) =>
  '₹' + v.toLocaleString('en-IN', { minimumFractionDigits: 0, maximumFractionDigits: 0 });

const INR_L = (v: number) => {
  // Compact lakh/crore display for big numbers
  const abs = Math.abs(v);
  if (abs >= 10000000) return '₹' + (v / 10000000).toFixed(2) + ' Cr';
  if (abs >= 100000) return '₹' + (v / 100000).toFixed(2) + ' L';
  return INR(v);
};

// ── Page ──────────────────────────────────────────────────────────────────

export default function OwnerDashboardPage() {
  const { t } = useTranslation();
  const [data, setData] = useState<ExceptionsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const nav = useNavigate();

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    setRefreshing(true);
    setError(null);
    try {
      const { data } = await api.get<ExceptionsResponse>('/api/v1/dashboard/exceptions');
      setData(data);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Failed to load dashboard');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);
  // Auto-refresh every 60 s for live updates
  useEffect(() => {
    const t = setInterval(() => load(true), 60000);
    return () => clearInterval(t);
  }, [load]);

  // ── Loading / error states ─────────────────────────────────────────────
  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
      </div>
    );
  }
  if (error || !data) {
    return (
      <div className="mx-auto max-w-xl py-12 text-center space-y-3">
        <AlertCircle className="mx-auto h-10 w-10 text-rose-400" />
        <p className="text-sm font-semibold text-slate-800">{t('ownerDash.couldNotLoadDashboard')}</p>
        {error && (
          <pre className="text-xs text-rose-700 bg-rose-50 border border-rose-200 rounded-lg p-3 whitespace-pre-wrap break-all text-left max-w-md mx-auto">
            {error}
          </pre>
        )}
        <p className="text-xs text-slate-500">
          You can keep using the rest of the app — try the sidebar links above.
        </p>
        <div className="flex justify-center gap-2 pt-2">
          <button
            className="px-4 py-2 rounded border border-slate-300 hover:bg-slate-50 text-sm"
            onClick={() => load()}
          >{t('ownerDash.retry')}</button>
          <Link
            to="/dashboard-legacy"
            className="px-4 py-2 rounded border border-slate-300 hover:bg-slate-50 text-sm"
          >
            {t('ownerDash.openOldDashboard')}
          </Link>
        </div>
      </div>
    );
  }

  // ── Traffic-light header ────────────────────────────────────────────────
  const headerPalette = {
    healthy:  { bg: 'bg-emerald-50',  border: 'border-emerald-300', text: 'text-emerald-900', icon: CheckCircle2,  iconColor: 'text-emerald-600' },
    warning:  { bg: 'bg-amber-50',    border: 'border-amber-300',   text: 'text-amber-900',   icon: AlertTriangle, iconColor: 'text-amber-600' },
    critical: { bg: 'bg-rose-50',     border: 'border-rose-300',    text: 'text-rose-900',    icon: AlertCircle,   iconColor: 'text-rose-600' },
  }[data.status];
  const HeaderIcon = headerPalette.icon;

  return (
    <div className="space-y-4 max-w-4xl mx-auto pb-6">
      {/* ── Status line ──────────────────────────────────────────────── */}
      <div className={`rounded-2xl border-2 ${headerPalette.bg} ${headerPalette.border} p-4 sm:p-5 flex items-start gap-3`}>
        <HeaderIcon className={`h-8 w-8 sm:h-10 sm:w-10 ${headerPalette.iconColor} shrink-0`} />
        <div className="flex-1 min-w-0">
          <div className={`text-base sm:text-lg font-bold ${headerPalette.text}`}>
            {data.status === 'healthy' ? t('ownerDash.allClear') : (data.problem_count === 1 ? t('ownerDash.thingsNeedYou', { count: data.problem_count }) : t('ownerDash.thingsNeedYouPlural', { count: data.problem_count }))}
          </div>
          <div className={`text-xs sm:text-sm ${headerPalette.text} opacity-80 mt-0.5`}>
            {data.headline}
          </div>
        </div>
        <button
          onClick={() => load(true)}
          className="shrink-0 h-9 w-9 rounded-full hover:bg-white/60 flex items-center justify-center"
          title="Refresh"
        >
          <RefreshCw className={`h-4 w-4 ${headerPalette.text} ${refreshing ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* ── Today's revenue strip ───────────────────────────────────── */}
      <RevenueStrip rev={data.today_revenue} />

      {/* ── ANPR gate-camera widget (hidden when ANPR off or no traffic) ── */}
      <AnprStatsCard />

      {/* ── Action cards ─────────────────────────────────────────────── */}
      <div className="space-y-3">
        <OverdueCard overdue={data.overdue_customers} onSent={() => load(true)} />
        <LowStockCard low={data.low_stock_products} onAction={() => nav('/product-inventory')} />
        <ComplianceCard comp={data.compliance_expiring} onAction={(id) => nav(`/compliance?id=${id}`)} />
        {data.yield_variance && (
          <YieldCard yv={data.yield_variance} onAction={() => nav('/production/dashboard')} />
        )}
      </div>

      {/* ── Footer: trends + advanced view ─────────────────────────── */}
      <div className="pt-3 border-t border-slate-200 flex flex-wrap gap-2">
        <Link to="/dashboard-legacy" className="inline-flex items-center gap-1.5 text-sm text-slate-600 hover:text-slate-900 px-3 py-2 rounded hover:bg-slate-100">
          <BarChart3 className="h-4 w-4" />
          {t('ownerDash.view30DayTrends')}
        </Link>
        <Link to="/ledger?tab=outstanding" className="inline-flex items-center gap-1.5 text-sm text-slate-600 hover:text-slate-900 px-3 py-2 rounded hover:bg-slate-100">
          <IndianRupee className="h-4 w-4" />
          {t('ownerDash.fullOutstanding')}
        </Link>
      </div>
    </div>
  );
}

// ── Revenue strip ───────────────────────────────────────────────────────────

function RevenueStrip({ rev }: { rev: { today: number; median_30d: number; variance_pct: number } }) {
  const { t } = useTranslation();
  const tone =
    rev.today === 0 && rev.median_30d > 0  ? 'amber' :
    rev.variance_pct < -50                  ? 'amber' :
    rev.variance_pct > 0                    ? 'good'  : 'default';
  const bg = { good: 'bg-emerald-50 border-emerald-200', amber: 'bg-amber-50 border-amber-200', default: 'bg-white border-slate-200' }[tone];
  const TrendIcon = rev.variance_pct >= 0 ? TrendingUp : TrendingDown;
  const trendColor = rev.variance_pct >= 0 ? 'text-emerald-600' : 'text-amber-600';

  return (
    <div className={`rounded-xl border ${bg} p-3 sm:p-4 flex items-center gap-3`}>
      <div className="flex h-10 w-10 sm:h-12 sm:w-12 items-center justify-center rounded-lg bg-blue-100 text-blue-700 shrink-0">
        <IndianRupee className="h-5 w-5 sm:h-6 sm:w-6" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-xs uppercase tracking-widest text-slate-500 font-semibold">{t('ownerDash.todayRevenue')}</div>
        <div className="text-xl sm:text-2xl font-bold text-slate-900">{INR_L(rev.today)}</div>
        <div className="text-xs text-slate-500 mt-0.5 flex items-center gap-1">
          <TrendIcon className={`h-3 w-3 ${trendColor}`} />
          <span className={trendColor}>
            {rev.variance_pct >= 0 ? '+' : ''}{rev.variance_pct}%
          </span>
          <span>{t('ownerDash.vs30DayMedian')} {INR_L(rev.median_30d)}</span>
        </div>
      </div>
    </div>
  );
}

// ── Action card shell ───────────────────────────────────────────────────────

function ActionCard({
  icon: Icon, color, title, sub, primary, secondary, expanded = false, children,
}: {
  icon: React.ElementType;
  color: 'rose' | 'amber' | 'orange' | 'emerald';
  title: string;
  sub: string;
  primary?: { label: string; onClick: () => void; busy?: boolean; icon?: React.ElementType };
  secondary?: { label: string; onClick: () => void };
  expanded?: boolean;
  children?: React.ReactNode;
}) {
  const palette = {
    rose:    { ring: 'border-rose-300',    bg: 'bg-rose-50',    iconBg: 'bg-rose-100 text-rose-700',       primary: 'bg-rose-600 hover:bg-rose-700' },
    amber:   { ring: 'border-amber-300',   bg: 'bg-amber-50',   iconBg: 'bg-amber-100 text-amber-700',     primary: 'bg-amber-600 hover:bg-amber-700' },
    orange:  { ring: 'border-orange-300',  bg: 'bg-orange-50',  iconBg: 'bg-orange-100 text-orange-700',   primary: 'bg-orange-600 hover:bg-orange-700' },
    emerald: { ring: 'border-emerald-300', bg: 'bg-emerald-50', iconBg: 'bg-emerald-100 text-emerald-700', primary: 'bg-emerald-600 hover:bg-emerald-700' },
  }[color];
  const PrimaryIcon = primary?.icon;

  return (
    <div className={`rounded-xl border-2 ${palette.ring} ${palette.bg} overflow-hidden`}>
      <div className="p-3 sm:p-4 flex items-start gap-3">
        <div className={`h-10 w-10 sm:h-12 sm:w-12 rounded-lg ${palette.iconBg} flex items-center justify-center shrink-0`}>
          <Icon className="h-5 w-5 sm:h-6 sm:w-6" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-sm sm:text-base font-bold text-slate-900">{title}</div>
          <div className="text-xs sm:text-sm text-slate-600 mt-0.5">{sub}</div>
        </div>
      </div>

      {/* Expanded list (when there is room / items to show) */}
      {expanded && children && (
        <div className="px-3 sm:px-4 pb-3 sm:pb-4 space-y-2">
          {children}
        </div>
      )}

      {/* Actions */}
      {(primary || secondary) && (
        <div className="px-3 sm:px-4 pb-3 sm:pb-4 flex flex-wrap gap-2">
          {primary && (
            <button
              onClick={primary.onClick}
              disabled={primary.busy}
              className={`flex-1 min-w-[200px] h-11 rounded-lg ${palette.primary} text-white font-semibold text-sm flex items-center justify-center gap-2 disabled:opacity-50`}
            >
              {primary.busy
                ? <Loader2 className="h-4 w-4 animate-spin" />
                : PrimaryIcon && <PrimaryIcon className="h-4 w-4" />}
              {primary.label}
            </button>
          )}
          {secondary && (
            <button
              onClick={secondary.onClick}
              className="h-11 px-4 rounded-lg border border-slate-300 bg-white hover:bg-slate-50 text-sm font-semibold text-slate-700"
            >
              {secondary.label}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ── Overdue customers card ─────────────────────────────────────────────────

function OverdueCard({ overdue, onSent }: { overdue: ExceptionsResponse['overdue_customers']; onSent: () => void }) {
  const { t } = useTranslation();
  const [sending, setSending] = useState(false);
  if (overdue.count === 0) {
    return (
      <ActionCard
        icon={CheckCircle2} color="emerald"
        title={t('ownerDash.allCustomersPaid')}
        sub={t('ownerDash.noOverdueBalances')}
      />
    );
  }

  async function sendBatch() {
    setSending(true);
    try {
      const { data } = await api.post<{ sent: number; skipped: number; failed: number }>(
        '/api/v1/dashboard/whatsapp-overdue',
        { party_ids: overdue.items.map(i => i.party_id) },
      );
      if (data.sent > 0) {
        toast.success(`Reminders sent to ${data.sent} customer${data.sent === 1 ? '' : 's'}` + (data.skipped ? ` · ${data.skipped} skipped (no phone)` : ''));
      } else {
        toast.message('No reminders sent', { description: 'No customers had a phone number set, or WhatsApp integration is not configured.' });
      }
      onSent();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(typeof detail === 'string' ? detail : 'Failed to send reminders');
    } finally {
      setSending(false);
    }
  }

  const tone = overdue.items.some(i => i.oldest_overdue_days > 60) ? 'rose' : 'amber';
  return (
    <ActionCard
      icon={IndianRupee} color={tone}
      title={`${INR_L(overdue.total_balance)} overdue from ${overdue.count} customer${overdue.count === 1 ? '' : 's'}`}
      sub={`Oldest: ${Math.max(...overdue.items.map(i => i.oldest_overdue_days))} days past due`}
      expanded
      primary={{ label: sending ? t('ownerDash.sending') : t('ownerDash.sendWhatsappReminders'), onClick: sendBatch, busy: sending, icon: MessageCircle }}
    >
      <div className="space-y-1.5">
        {overdue.items.slice(0, 5).map(c => (
          <Link
            key={c.party_id}
            to={`/customers/${c.party_id}`}
            className="flex items-center gap-2 px-3 py-2 rounded-lg bg-white border border-slate-200 hover:border-slate-400 transition-colors"
          >
            <div className="flex-1 min-w-0">
              <div className="text-sm font-semibold text-slate-900 truncate">{c.party_name}</div>
              <div className="text-xs text-slate-500 flex items-center gap-1.5">
                {c.phone ? <><Phone className="h-3 w-3" /> {c.phone}</> : <span className="italic text-slate-400">No phone</span>}
                <span className="text-slate-400">·</span>
                <span className={c.oldest_overdue_days > 60 ? 'text-rose-600 font-semibold' : 'text-amber-700'}>
                  {c.oldest_overdue_days} {t('ownerDash.daysOverdue')}
                </span>
              </div>
            </div>
            <div className="text-sm font-bold text-slate-900 shrink-0">{INR_L(c.balance)}</div>
            <ChevronRight className="h-4 w-4 text-slate-300 shrink-0" />
          </Link>
        ))}
        {overdue.items.length > 5 && (
          <div className="text-center text-xs text-slate-500 py-1">
            +{overdue.items.length - 5} {t('ownerDash.more')} · <Link to="/ledger?tab=outstanding" className="underline">{t('ownerDash.viewAll')}</Link>
          </div>
        )}
      </div>
    </ActionCard>
  );
}

// ── Low stock card ─────────────────────────────────────────────────────────

function LowStockCard({ low, onAction }: { low: ExceptionsResponse['low_stock_products']; onAction: () => void }) {
  const { t } = useTranslation();
  if (low.count === 0) {
    return (
      <ActionCard
        icon={CheckCircle2} color="emerald"
        title={t('ownerDash.allStockOk')}
        sub={t('ownerDash.noLowStockItems')}
      />
    );
  }
  const tone = low.out_of_stock_count > 0 ? 'rose' : 'amber';
  return (
    <ActionCard
      icon={ShoppingCart} color={tone}
      title={low.out_of_stock_count > 0
        ? `${low.out_of_stock_count} product${low.out_of_stock_count === 1 ? '' : 's'} out of stock`
        : `${low.count} product${low.count === 1 ? '' : 's'} below minimum`}
      sub="Tap below to raise a Purchase Order"
      expanded
      primary={{ label: t('ownerDash.viewPurchaseOrders'), onClick: onAction, icon: ShoppingCart }}
    >
      <div className="space-y-1.5">
        {low.items.slice(0, 5).map(p => (
          <div key={p.product_id} className="flex items-center gap-2 px-3 py-2 rounded-lg bg-white border border-slate-200">
            <div className="flex-1 min-w-0">
              <div className="text-sm font-semibold text-slate-900 truncate">{p.product_name}</div>
              <div className="text-xs text-slate-500">
                Current: {p.current_stock.toFixed(2)} {p.unit}  ·  Min: {p.min_stock_level.toFixed(2)} {p.unit}
              </div>
            </div>
            {p.is_out ? (
              <span className="text-[10px] font-bold uppercase bg-rose-100 text-rose-700 px-2 py-0.5 rounded-full border border-rose-200 shrink-0">
                OUT
              </span>
            ) : (
              <span className="text-[10px] font-bold uppercase bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full border border-amber-200 shrink-0">
                LOW
              </span>
            )}
          </div>
        ))}
        {low.items.length > 5 && (
          <div className="text-center text-xs text-slate-500 py-1">
            +{low.items.length - 5} more
          </div>
        )}
      </div>
    </ActionCard>
  );
}

// ── Compliance card ────────────────────────────────────────────────────────

function ComplianceCard({ comp, onAction }: { comp: ExceptionsResponse['compliance_expiring']; onAction: (id: string) => void }) {
  const { t } = useTranslation();
  if (comp.count === 0) {
    return (
      <ActionCard
        icon={CheckCircle2} color="emerald"
        title={t('ownerDash.allComplianceValid')}
        sub={t('ownerDash.noExpiringDocs')}
      />
    );
  }
  const hasExpired = comp.items.some(c => c.alert_level === 'expired');
  const tone = hasExpired ? 'rose' : 'amber';
  return (
    <ActionCard
      icon={ShieldAlert} color={tone}
      title={hasExpired
        ? `${comp.items.filter(c => c.alert_level === 'expired').length} document${comp.items.filter(c => c.alert_level === 'expired').length === 1 ? '' : 's'} EXPIRED`
        : `${comp.count} compliance document${comp.count === 1 ? '' : 's'} expiring soon`}
      sub="Tap an item to review and renew"
      expanded
    >
      <div className="space-y-1.5">
        {comp.items.slice(0, 5).map(c => (
          <button
            key={c.item_id}
            onClick={() => onAction(c.item_id)}
            className="w-full flex items-center gap-2 px-3 py-2 rounded-lg bg-white border border-slate-200 hover:border-slate-400 transition-colors text-left"
          >
            <div className="flex-1 min-w-0">
              <div className="text-sm font-semibold text-slate-900 truncate">{c.name}</div>
              <div className="text-xs text-slate-500 capitalize">{c.type}</div>
            </div>
            <div className="text-right shrink-0">
              {c.alert_level === 'expired' ? (
                <div className="text-xs font-bold text-rose-700 uppercase">EXPIRED {Math.abs(c.days_to_expiry)}d ago</div>
              ) : (
                <div className={`text-xs font-bold uppercase ${c.alert_level === 'critical' ? 'text-rose-700' : 'text-amber-700'}`}>
                  {c.days_to_expiry} days left
                </div>
              )}
              <div className="text-[10px] text-slate-500">{c.expiry_date}</div>
            </div>
            <ChevronRight className="h-4 w-4 text-slate-300 shrink-0" />
          </button>
        ))}
      </div>
    </ActionCard>
  );
}

// ── Yield variance card ────────────────────────────────────────────────────

function YieldCard({ yv, onAction }: { yv: YieldVariance; onAction: () => void }) {
  const { t } = useTranslation();
  const palette = yv.status === 'on_track' ? 'emerald' : yv.status === 'below' ? 'amber' : 'rose';
  const Icon = yv.status === 'on_track' ? CheckCircle2 : Factory;
  return (
    <ActionCard
      icon={Icon} color={palette}
      title={`Today's yield: ${yv.today_yield_pct.toFixed(1)}%`}
      sub={
        yv.status === 'on_track'
          ? `${t('ownerDash.yieldOnTarget')} (${yv.target_yield_pct.toFixed(1)}%)`
          : `${yv.variance_pct.toFixed(1)}% ${yv.variance_pct < 0 ? 'below' : 'above'} target (${yv.target_yield_pct.toFixed(1)}%)`
      }
      primary={yv.status !== 'on_track'
        ? { label: t('ownerDash.viewProduction'), onClick: onAction, icon: BarChart3 }
        : undefined}
      secondary={yv.status === 'on_track' ? { label: t('ownerDash.viewProduction'), onClick: onAction } : undefined}
    />
  );
}
