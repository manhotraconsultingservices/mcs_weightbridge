/**
 * Customer / Supplier 360 view.
 *
 * One-stop profile page: header + KPIs + outstanding aging + last 20 invoices
 * + last 20 payments + custom rate cards. Renders from a single API call:
 *
 *   GET /api/v1/parties/{id}/360
 *
 * Linked from every party name in the app (Parties table, Invoices,
 * Payments, Ledger).
 */
import { useEffect, useState, useCallback } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import {
  ArrowLeft, Phone, Mail, MapPin, IndianRupee, FileText, Banknote,
  Receipt, Clock, TrendingUp, AlertCircle, Loader2, Truck, Tag,
  Calendar, Edit, CheckCircle2,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import {
  Tabs, TabsList, TabsTrigger, TabsContent,
} from '@/components/ui/tabs';
import api from '@/services/api';
import type { Party360Response } from '@/types';

const INR = (v: number | string | null | undefined) => {
  const n = Number(v ?? 0);
  return '₹' + n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};

const fmtDate = (s: string | null | undefined) =>
  s ? new Date(s).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }) : '—';

const fmtMT = (n: number) => `${n.toFixed(3)} MT`;

// ── Mini stat card ──────────────────────────────────────────────────────────
function KpiCard({
  icon: Icon, label, value, sub, tone = 'default',
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
  sub?: string;
  tone?: 'default' | 'good' | 'warn' | 'bad';
}) {
  const toneClasses = {
    default: 'border-slate-200 bg-white',
    good: 'border-emerald-200 bg-emerald-50',
    warn: 'border-amber-200 bg-amber-50',
    bad: 'border-rose-200 bg-rose-50',
  }[tone];
  const iconColor = {
    default: 'text-slate-500',
    good: 'text-emerald-600',
    warn: 'text-amber-600',
    bad: 'text-rose-600',
  }[tone];
  return (
    <div className={`rounded-lg border p-4 ${toneClasses}`}>
      <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-slate-500">
        <Icon className={`h-3.5 w-3.5 ${iconColor}`} />
        {label}
      </div>
      <div className="mt-1 text-xl font-bold text-slate-900">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-slate-500">{sub}</div>}
    </div>
  );
}

// ── Aging bar ───────────────────────────────────────────────────────────────
function AgingChart({ aging }: { aging: Party360Response['stats']['aging'] }) {
  const total =
    aging.current + aging.bucket_1_30 + aging.bucket_31_60 + aging.bucket_61_90 + aging.bucket_90_plus;
  const pct = (v: number) => (total > 0 ? (v / total) * 100 : 0);
  const buckets = [
    { label: 'Current',  value: aging.current,        color: 'bg-emerald-500', textColor: 'text-emerald-700' },
    { label: '1–30 d',   value: aging.bucket_1_30,    color: 'bg-amber-400',   textColor: 'text-amber-700' },
    { label: '31–60 d',  value: aging.bucket_31_60,   color: 'bg-orange-500',  textColor: 'text-orange-700' },
    { label: '61–90 d',  value: aging.bucket_61_90,   color: 'bg-red-500',     textColor: 'text-red-700' },
    { label: '90+ d',    value: aging.bucket_90_plus, color: 'bg-rose-700',    textColor: 'text-rose-800' },
  ];

  if (total <= 0) {
    return (
      <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-6 text-center">
        <CheckCircle2 className="mx-auto h-8 w-8 text-emerald-500" />
        <p className="mt-2 text-sm font-medium text-emerald-700">No outstanding balance</p>
        <p className="text-xs text-emerald-600">This customer is fully settled.</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Stacked bar */}
      <div className="flex h-3 overflow-hidden rounded-full bg-slate-100">
        {buckets.map(b =>
          b.value > 0 ? (
            <div
              key={b.label}
              className={b.color}
              style={{ width: `${pct(b.value)}%` }}
              title={`${b.label}: ${INR(b.value)}`}
            />
          ) : null,
        )}
      </div>
      {/* Legend rows */}
      <div className="grid grid-cols-5 gap-2 text-center text-[11px]">
        {buckets.map(b => (
          <div key={b.label} className="rounded border border-slate-200 p-1.5">
            <div className={`text-xs font-bold ${b.textColor}`}>{INR(b.value)}</div>
            <div className="text-[10px] text-slate-500">{b.label}</div>
            <div className="text-[9px] text-slate-400">{pct(b.value).toFixed(0)}%</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Page component ──────────────────────────────────────────────────────────
export default function CustomerProfilePage() {
  const { id } = useParams<{ id: string }>();
  const nav = useNavigate();
  const [data, setData] = useState<Party360Response | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError(null);
    try {
      const { data } = await api.get<Party360Response>(`/api/v1/parties/${id}/360`);
      setData(data);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Failed to load customer profile');
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="mx-auto max-w-2xl py-12 text-center">
        <AlertCircle className="mx-auto h-10 w-10 text-rose-400" />
        <p className="mt-2 text-sm text-slate-600">{error ?? 'Customer not found'}</p>
        <Button variant="outline" className="mt-4" onClick={() => nav('/parties')}>
          <ArrowLeft className="mr-2 h-4 w-4" /> Back to Parties
        </Button>
      </div>
    );
  }

  const { party, stats, recent_invoices, recent_payments, custom_rates } = data;
  const outstandingTone: 'good' | 'warn' | 'bad' =
    stats.total_overdue > 0 ? 'bad' : stats.total_outstanding > 0 ? 'warn' : 'good';

  return (
    <div className="space-y-4 px-4 py-4">
      {/* ── Header ───────────────────────────────────────────────────── */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <Button variant="ghost" size="icon" onClick={() => nav(-1)} title="Back">
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-xl font-bold text-slate-900">{party.name}</h1>
              <Badge variant="outline" className="text-[10px] uppercase">
                {party.party_type === 'both' ? 'Customer + Supplier' : party.party_type}
              </Badge>
              {!party.is_active && (
                <Badge variant="outline" className="border-slate-300 bg-slate-100 text-[10px] text-slate-600">
                  Inactive
                </Badge>
              )}
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-slate-500">
              {party.gstin && <span>GSTIN: <span className="font-mono">{party.gstin}</span></span>}
              {party.pan && <span>PAN: <span className="font-mono">{party.pan}</span></span>}
              {party.phone && (
                <span className="inline-flex items-center gap-1">
                  <Phone className="h-3 w-3" /> {party.phone}
                </span>
              )}
              {party.email && (
                <span className="inline-flex items-center gap-1">
                  <Mail className="h-3 w-3" /> {party.email}
                </span>
              )}
              {(party.billing_city || party.billing_state) && (
                <span className="inline-flex items-center gap-1">
                  <MapPin className="h-3 w-3" />
                  {[party.billing_city, party.billing_state].filter(Boolean).join(', ')}
                </span>
              )}
            </div>
          </div>
        </div>
        <Link to={`/parties?edit=${party.id}`}>
          <Button variant="outline" size="sm">
            <Edit className="mr-1.5 h-3.5 w-3.5" /> Edit
          </Button>
        </Link>
      </div>

      {/* ── KPI grid ─────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <KpiCard
          icon={IndianRupee}
          label="Outstanding"
          value={INR(stats.total_outstanding)}
          sub={
            stats.total_overdue > 0
              ? `${INR(stats.total_overdue)} overdue`
              : 'No overdue'
          }
          tone={outstandingTone}
        />
        <KpiCard
          icon={TrendingUp}
          label="Lifetime Sales"
          value={INR(stats.lifetime_sales)}
          sub={`${stats.invoice_count} invoice${stats.invoice_count === 1 ? '' : 's'}`}
          tone="default"
        />
        <KpiCard
          icon={Receipt}
          label="Avg Order Value"
          value={INR(stats.avg_order_value)}
          sub={stats.invoice_count > 0 ? `across ${stats.invoice_count} orders` : 'no orders yet'}
          tone="default"
        />
        <KpiCard
          icon={Clock}
          label="Last Order"
          value={
            stats.days_since_last_order === null
              ? '—'
              : stats.days_since_last_order === 0
                ? 'Today'
                : `${stats.days_since_last_order} d ago`
          }
          sub={fmtDate(stats.last_invoice_date)}
          tone={
            stats.days_since_last_order === null
              ? 'default'
              : stats.days_since_last_order > 60
                ? 'warn'
                : 'default'
          }
        />
      </div>

      {/* ── Secondary stats ──────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <KpiCard
          icon={Banknote}
          label="Lifetime Paid"
          value={INR(stats.lifetime_paid)}
          sub={
            stats.lifetime_written_off > 0
              ? `${INR(stats.lifetime_written_off)} written off`
              : 'no write-offs'
          }
        />
        <KpiCard
          icon={Calendar}
          label="Last Payment"
          value={
            stats.days_since_last_payment === null
              ? '—'
              : stats.days_since_last_payment === 0
                ? 'Today'
                : `${stats.days_since_last_payment} d ago`
          }
          sub={fmtDate(stats.last_payment_date)}
        />
        <KpiCard
          icon={Truck}
          label="Tokens"
          value={String(stats.token_count)}
          sub={fmtMT(stats.lifetime_tonnage)}
        />
        <KpiCard
          icon={Tag}
          label="Custom Rates"
          value={String(custom_rates.length)}
          sub={custom_rates.length > 0 ? 'See Pricing tab' : 'Uses defaults'}
        />
      </div>

      {/* ── Outstanding aging ─────────────────────────────────────────── */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-sm">
            <AlertCircle className="h-4 w-4 text-amber-500" />
            Outstanding by Aging Bucket
          </CardTitle>
        </CardHeader>
        <CardContent>
          <AgingChart aging={stats.aging} />
        </CardContent>
      </Card>

      {/* ── Tabs: invoices / payments / pricing ───────────────────────── */}
      <Tabs defaultValue="invoices" className="w-full">
        <TabsList>
          <TabsTrigger value="invoices">
            <FileText className="mr-1.5 h-3.5 w-3.5" /> Invoices ({recent_invoices.length})
          </TabsTrigger>
          <TabsTrigger value="payments">
            <Banknote className="mr-1.5 h-3.5 w-3.5" /> Payments ({recent_payments.length})
          </TabsTrigger>
          <TabsTrigger value="pricing">
            <Tag className="mr-1.5 h-3.5 w-3.5" /> Pricing ({custom_rates.length})
          </TabsTrigger>
        </TabsList>

        {/* ── Recent invoices ─────────────────────────────────────────── */}
        <TabsContent value="invoices" className="mt-3">
          <Card>
            <CardContent className="p-0">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-xs uppercase text-slate-500">
                  <tr>
                    <th className="px-3 py-2 text-left">Invoice #</th>
                    <th className="px-3 py-2 text-left">Date</th>
                    <th className="px-3 py-2 text-left">Type</th>
                    <th className="px-3 py-2 text-right">Amount</th>
                    <th className="px-3 py-2 text-right">Paid</th>
                    <th className="px-3 py-2 text-right">Due</th>
                    <th className="px-3 py-2 text-center">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {recent_invoices.length === 0 && (
                    <tr><td colSpan={7} className="px-3 py-8 text-center text-slate-400">
                      No invoices yet
                    </td></tr>
                  )}
                  {recent_invoices.map(inv => (
                    <tr key={inv.id} className="hover:bg-slate-50">
                      <td className="px-3 py-2 font-mono text-xs">
                        <Link to={`/${inv.invoice_type === 'purchase' ? 'purchase-' : ''}invoices?inv=${inv.id}`}
                              className="text-blue-600 hover:underline">
                          {inv.invoice_no ?? <span className="italic text-slate-400">draft</span>}
                        </Link>
                      </td>
                      <td className="px-3 py-2 text-xs text-slate-600">{fmtDate(inv.invoice_date)}</td>
                      <td className="px-3 py-2 text-xs">
                        <Badge variant="outline" className="text-[9px] uppercase">
                          {inv.invoice_type}
                        </Badge>
                      </td>
                      <td className="px-3 py-2 text-right font-medium">{INR(inv.grand_total)}</td>
                      <td className="px-3 py-2 text-right text-emerald-700">{INR(inv.amount_paid)}</td>
                      <td className={`px-3 py-2 text-right font-medium ${
                        inv.amount_due > 0 ? 'text-rose-700' : 'text-slate-400'
                      }`}>
                        {INR(inv.amount_due)}
                      </td>
                      <td className="px-3 py-2 text-center">
                        <Badge
                          variant="outline"
                          className={
                            inv.status === 'cancelled'
                              ? 'border-slate-300 bg-slate-100 text-slate-600'
                              : inv.payment_status === 'paid'
                                ? 'border-emerald-300 bg-emerald-50 text-emerald-700'
                                : inv.payment_status === 'partial'
                                  ? 'border-amber-300 bg-amber-50 text-amber-700'
                                  : 'border-rose-300 bg-rose-50 text-rose-700'
                          }
                        >
                          {inv.status === 'cancelled' ? 'Cancelled' : inv.payment_status}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>
        </TabsContent>

        {/* ── Recent payments ─────────────────────────────────────────── */}
        <TabsContent value="payments" className="mt-3">
          <Card>
            <CardContent className="p-0">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-xs uppercase text-slate-500">
                  <tr>
                    <th className="px-3 py-2 text-left">Voucher #</th>
                    <th className="px-3 py-2 text-left">Date</th>
                    <th className="px-3 py-2 text-left">Direction</th>
                    <th className="px-3 py-2 text-left">Mode</th>
                    <th className="px-3 py-2 text-left">Ref</th>
                    <th className="px-3 py-2 text-right">Amount</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {recent_payments.length === 0 && (
                    <tr><td colSpan={6} className="px-3 py-8 text-center text-slate-400">
                      No payments yet
                    </td></tr>
                  )}
                  {recent_payments.map(p => (
                    <tr key={p.id} className="hover:bg-slate-50">
                      <td className="px-3 py-2 font-mono text-xs text-blue-600">{p.voucher_no}</td>
                      <td className="px-3 py-2 text-xs text-slate-600">{fmtDate(p.payment_date)}</td>
                      <td className="px-3 py-2 text-xs">
                        <Badge variant="outline" className={
                          p.kind === 'receipt'
                            ? 'border-emerald-300 bg-emerald-50 text-[9px] uppercase text-emerald-700'
                            : 'border-amber-300 bg-amber-50 text-[9px] uppercase text-amber-700'
                        }>
                          {p.kind === 'receipt' ? 'Received' : 'Paid'}
                        </Badge>
                      </td>
                      <td className="px-3 py-2 text-xs uppercase text-slate-600">{p.payment_mode}</td>
                      <td className="px-3 py-2 text-xs text-slate-500">{p.reference_no ?? '—'}</td>
                      <td className={`px-3 py-2 text-right font-medium ${
                        p.kind === 'receipt' ? 'text-emerald-700' : 'text-amber-700'
                      }`}>
                        {p.kind === 'receipt' ? '+' : '−'} {INR(p.amount)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>
        </TabsContent>

        {/* ── Custom pricing ──────────────────────────────────────────── */}
        <TabsContent value="pricing" className="mt-3">
          <Card>
            <CardContent className="p-0">
              {custom_rates.length === 0 ? (
                <div className="px-4 py-8 text-center text-sm text-slate-400">
                  No custom rates set — this customer pays product default rates.
                  <div className="mt-2">
                    <Link to={`/pricing-matrix?party=${party.id}`}>
                      <Button size="sm" variant="outline">
                        <Tag className="mr-1.5 h-3 w-3" /> Set custom rates
                      </Button>
                    </Link>
                  </div>
                </div>
              ) : (
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-xs uppercase text-slate-500">
                    <tr>
                      <th className="px-3 py-2 text-left">Product</th>
                      <th className="px-3 py-2 text-left">Unit</th>
                      <th className="px-3 py-2 text-right">Default Rate</th>
                      <th className="px-3 py-2 text-right">Custom Rate</th>
                      <th className="px-3 py-2 text-right">Diff</th>
                      <th className="px-3 py-2 text-left">Since</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {custom_rates.map(r => {
                      const diff = r.custom_rate - r.default_rate;
                      const pct = r.default_rate > 0 ? (diff / r.default_rate) * 100 : 0;
                      return (
                        <tr key={r.product_id} className="hover:bg-slate-50">
                          <td className="px-3 py-2 font-medium">{r.product_name}</td>
                          <td className="px-3 py-2 text-xs uppercase text-slate-500">{r.product_unit}</td>
                          <td className="px-3 py-2 text-right text-slate-500">{INR(r.default_rate)}</td>
                          <td className="px-3 py-2 text-right font-bold text-slate-900">{INR(r.custom_rate)}</td>
                          <td className={`px-3 py-2 text-right text-xs ${
                            diff > 0 ? 'text-emerald-700' : diff < 0 ? 'text-rose-700' : 'text-slate-400'
                          }`}>
                            {diff === 0 ? '—' : `${diff > 0 ? '+' : ''}${INR(diff)} (${pct.toFixed(1)}%)`}
                          </td>
                          <td className="px-3 py-2 text-xs text-slate-500">{fmtDate(r.effective_from)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* ── Quick action footer ─────────────────────────────────────── */}
      <div className="flex flex-wrap gap-2 border-t border-slate-200 pt-3">
        <Link to={`/ledger?party=${party.id}`}>
          <Button variant="outline" size="sm">
            <FileText className="mr-1.5 h-3.5 w-3.5" /> Full ledger
          </Button>
        </Link>
        <Link to={`/invoices?party=${party.id}`}>
          <Button variant="outline" size="sm">
            <Receipt className="mr-1.5 h-3.5 w-3.5" /> All invoices
          </Button>
        </Link>
        <Link to={`/payments?party=${party.id}`}>
          <Button variant="outline" size="sm">
            <Banknote className="mr-1.5 h-3.5 w-3.5" /> All payments
          </Button>
        </Link>
        <Link to={`/pricing-matrix?party=${party.id}`}>
          <Button variant="outline" size="sm">
            <Tag className="mr-1.5 h-3.5 w-3.5" /> Edit pricing
          </Button>
        </Link>
      </div>
    </div>
  );
}
