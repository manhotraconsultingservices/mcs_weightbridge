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
import { useEffect, useState, useCallback, useMemo } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import {
  ArrowLeft, Phone, Mail, MapPin, IndianRupee, FileText, Banknote,
  Receipt, Clock, TrendingUp, AlertCircle, Loader2, Truck, Tag,
  Calendar, Edit, CheckCircle2, XCircle,
} from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import {
  Tabs, TabsList, TabsTrigger, TabsContent,
} from '@/components/ui/tabs';
import api from '@/services/api';
import { useAuth } from '@/hooks/useAuth';
import PortalAccessDialog from '@/components/PortalAccessDialog';
import { DataTable, type ColumnDef } from '@/components/DataTable';
import type { Party360Response } from '@/types';

const INR = (v: number | string | null | undefined) => {
  const n = Number(v ?? 0);
  return '₹' + n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};

const fmtDate = (s: string | null | undefined) =>
  s ? new Date(s).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }) : '—';

// Backend serialises pydantic Decimal as a STRING in JSON. Always coerce
// with Number(...) before any numeric operation/method like .toFixed().
const fmtMT = (n: number | string | null | undefined) => `${Number(n ?? 0).toFixed(3)} MT`;

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
  const { user } = useAuth();
  const canWriteOff = user?.role === 'admin' || user?.role === 'accountant';
  const [data, setData] = useState<Party360Response | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Mass write-off selection (per-invoice checkbox)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError(null);
    try {
      const { data } = await api.get<Party360Response>(`/api/v1/parties/${id}/360`);
      setData(data);
      setSelectedIds(new Set());   // clear selection after refresh
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Failed to load customer profile');
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  // Invoices eligible for write-off: finalised + has outstanding balance.
  // Defensive ?? [] in case the API response is missing the field (e.g.
  // older backend version on a freshly-onboarded tenant).
  const writeOffEligible = useMemo(() => {
    if (!data) return new Set<string>();
    const invoices = data.recent_invoices ?? [];
    return new Set(
      invoices
        .filter(i => i.status === 'final' && i.payment_status !== 'paid' && Number(i.amount_due ?? 0) > 0)
        .map(i => i.id),
    );
  }, [data]);

  const selectedTotal = useMemo(() => {
    if (!data) return 0;
    const invoices = data.recent_invoices ?? [];
    return invoices
      .filter(i => selectedIds.has(i.id))
      .reduce((s, i) => s + Number(i.amount_due ?? 0), 0);
  }, [selectedIds, data]);

  function toggleSelect(invoiceId: string) {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(invoiceId)) next.delete(invoiceId);
      else next.add(invoiceId);
      return next;
    });
  }

  function toggleSelectAll() {
    if (selectedIds.size === writeOffEligible.size) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(writeOffEligible));
    }
  }

  async function performBulkWriteOff() {
    if (selectedIds.size === 0) return;
    const totalStr = '₹' + selectedTotal.toLocaleString('en-IN', { minimumFractionDigits: 2 });
    const confirmMsg =
      `Write off ${selectedIds.size} invoice${selectedIds.size === 1 ? '' : 's'} totalling ${totalStr}?\n\n` +
      `This is irreversible. The customer's balance will be reduced by ${totalStr} and the amounts ` +
      `will appear as bad-debt expense on your Profit & Loss report.\n\n` +
      `Enter reason for write-off (will be saved on every selected invoice):`;
    const reason = window.prompt(confirmMsg, 'Bad debt — uncollectable');
    if (!reason || !reason.trim()) return;

    setBulkBusy(true);
    try {
      const { data: result } = await api.post<{
        written: number; skipped: number; total_amount: number;
        skipped_details: string[]; parties_affected: number;
      }>('/api/v1/invoices/write-off-bulk', {
        invoice_ids: Array.from(selectedIds),
        reason: reason.trim(),
      });
      if (result.written > 0) {
        toast.success(
          `Wrote off ${result.written} invoice${result.written === 1 ? '' : 's'} (₹${result.total_amount.toLocaleString('en-IN', { minimumFractionDigits: 2 })})`
          + (result.skipped ? ` · ${result.skipped} skipped` : ''),
        );
      } else {
        toast.message('Nothing written off', {
          description: result.skipped_details.join(' · ') || 'All invoices ineligible',
        });
      }
      load();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(typeof detail === 'string' ? detail : 'Bulk write-off failed');
    } finally {
      setBulkBusy(false);
    }
  }

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

  // Defensive defaults — the backend always emits these but we guard anyway
  // so a malformed/old response never white-screens the whole page.
  const party = data.party;
  const stats = data.stats ?? ({
    lifetime_sales: 0, lifetime_paid: 0, lifetime_written_off: 0, write_off_count: 0,
    invoice_count: 0, avg_order_value: 0,
    last_invoice_date: null, days_since_last_order: null,
    last_payment_date: null, days_since_last_payment: null,
    total_outstanding: 0, total_overdue: 0,
    aging: { current: 0, bucket_1_30: 0, bucket_31_60: 0, bucket_61_90: 0, bucket_90_plus: 0 },
    token_count: 0, lifetime_tonnage: 0,
  } as Party360Response['stats']);
  const recent_invoices = data.recent_invoices ?? [];
  const recent_payments = data.recent_payments ?? [];
  const custom_rates = data.custom_rates ?? [];

  if (!party) {
    return (
      <div className="mx-auto max-w-md py-12 text-center">
        <AlertCircle className="mx-auto h-10 w-10 text-rose-400" />
        <p className="mt-2 text-sm text-slate-600">Customer record is malformed.</p>
        <Button variant="outline" className="mt-4" onClick={() => nav('/customers')}>
          <ArrowLeft className="mr-2 h-4 w-4" /> Back to Customers
        </Button>
      </div>
    );
  }

  const outstandingTone: 'good' | 'warn' | 'bad' =
    (stats.total_overdue ?? 0) > 0 ? 'bad' : (stats.total_outstanding ?? 0) > 0 ? 'warn' : 'good';

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
            stats.write_off_count > 0
              ? `${INR(stats.lifetime_written_off)} written off (${stats.write_off_count} inv)`
              : 'no write-offs'
          }
          tone={stats.write_off_count > 0 ? 'warn' : 'default'}
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
          {canWriteOff && writeOffEligible.size > 0 && (
            <div className="mb-2 flex items-center justify-between flex-wrap gap-2 px-3 py-2 rounded-lg bg-amber-50 border border-amber-200">
              <div className="flex items-center gap-2 text-xs">
                <button
                  type="button"
                  onClick={toggleSelectAll}
                  className="font-semibold text-amber-800 hover:underline"
                >
                  {selectedIds.size === writeOffEligible.size && writeOffEligible.size > 0
                    ? 'Deselect all'
                    : `Select all ${writeOffEligible.size} eligible`}
                </button>
                <span className="text-amber-700">
                  {selectedIds.size > 0
                    ? `· ${selectedIds.size} selected · ${INR(selectedTotal)} total`
                    : '· tick rows to write off in bulk'}
                </span>
              </div>
              <Button
                size="sm"
                variant="outline"
                disabled={selectedIds.size === 0 || bulkBusy}
                onClick={performBulkWriteOff}
                className="border-amber-400 bg-white text-amber-800 hover:bg-amber-100 disabled:opacity-40"
              >
                {bulkBusy
                  ? <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                  : <XCircle className="h-3.5 w-3.5 mr-1.5" />}
                Write off {selectedIds.size || ''} invoice{selectedIds.size === 1 ? '' : 's'}
              </Button>
            </div>
          )}
          {(() => {
            type InvRow = Party360Response['recent_invoices'][number];
            const invoiceColumns: ColumnDef<InvRow>[] = [
              ...(canWriteOff ? [{
                key: 'select',
                label: '',
                accessor: (inv: InvRow) => selectedIds.has(inv.id) ? 'checked' : 'unchecked',
                format: (_v: unknown, inv: InvRow) => {
                  const eligible = writeOffEligible.has(inv.id);
                  const checked = selectedIds.has(inv.id);
                  return (
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={!eligible}
                      onChange={() => toggleSelect(inv.id)}
                      title={eligible ? 'Select for bulk write-off' : 'Not eligible (paid, cancelled, or draft)'}
                      className="h-4 w-4 cursor-pointer disabled:cursor-not-allowed disabled:opacity-30"
                    />
                  );
                },
                sortable: false,
                filterable: false,
                alwaysVisible: true,
                align: 'center' as const,
                exportValue: (inv: InvRow) => selectedIds.has(inv.id) ? 'selected' : '',
              }] : []),
              {
                key: 'invoice_no',
                label: 'Invoice #',
                type: 'string',
                accessor: (inv: InvRow) => inv.invoice_no ?? '',
                format: (_v: unknown, inv: InvRow) => (
                  <Link
                    to={`/${inv.invoice_type === 'purchase' ? 'purchase-' : ''}invoices?inv=${inv.id}`}
                    className="font-mono text-xs text-blue-600 hover:underline"
                  >
                    {inv.invoice_no ?? <span className="italic text-slate-400">draft</span>}
                  </Link>
                ),
                exportValue: (inv: InvRow) => inv.invoice_no ?? 'draft',
              },
              {
                key: 'invoice_date',
                label: 'Date',
                type: 'date',
                accessor: (inv: InvRow) => inv.invoice_date ?? '',
                format: (_v: unknown, inv: InvRow) => (
                  <span className="text-xs text-slate-600">{fmtDate(inv.invoice_date)}</span>
                ),
                exportValue: (inv: InvRow) => fmtDate(inv.invoice_date),
              },
              {
                key: 'invoice_type',
                label: 'Type',
                type: 'enum',
                enumOptions: ['sale', 'purchase', 'credit_note', 'debit_note'],
                accessor: (inv: InvRow) => inv.invoice_type,
                format: (_v: unknown, inv: InvRow) => (
                  <Badge variant="outline" className="text-[9px] uppercase">
                    {inv.invoice_type}
                  </Badge>
                ),
              },
              {
                key: 'grand_total',
                label: 'Amount',
                type: 'number',
                align: 'right',
                accessor: (inv: InvRow) => Number(inv.grand_total ?? 0),
                format: (_v: unknown, inv: InvRow) => (
                  <span className="font-medium">{INR(inv.grand_total)}</span>
                ),
                exportValue: (inv: InvRow) => Number(inv.grand_total ?? 0).toFixed(2),
              },
              {
                key: 'amount_paid',
                label: 'Paid',
                type: 'number',
                align: 'right',
                accessor: (inv: InvRow) => Number(inv.amount_paid ?? 0),
                format: (_v: unknown, inv: InvRow) => (
                  <span className="text-emerald-700">{INR(inv.amount_paid)}</span>
                ),
                exportValue: (inv: InvRow) => Number(inv.amount_paid ?? 0).toFixed(2),
              },
              {
                key: 'amount_due',
                label: 'Due',
                type: 'number',
                align: 'right',
                accessor: (inv: InvRow) => Number(inv.amount_due ?? 0),
                format: (_v: unknown, inv: InvRow) => (
                  <span className={`font-medium ${Number(inv.amount_due) > 0 ? 'text-rose-700' : 'text-slate-400'}`}>
                    {INR(inv.amount_due)}
                  </span>
                ),
                exportValue: (inv: InvRow) => Number(inv.amount_due ?? 0).toFixed(2),
              },
              {
                key: 'payment_status',
                label: 'Status',
                type: 'enum',
                enumOptions: ['unpaid', 'partial', 'paid', 'cancelled'],
                align: 'center',
                accessor: (inv: InvRow) => inv.status === 'cancelled' ? 'cancelled' : (inv.payment_status ?? ''),
                format: (_v: unknown, inv: InvRow) => (
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
                ),
                exportValue: (inv: InvRow) => inv.status === 'cancelled' ? 'cancelled' : (inv.payment_status ?? ''),
              },
            ];
            return (
              <DataTable<InvRow>
                id="customer360.invoices"
                data={recent_invoices}
                columns={invoiceColumns}
                rowKey={inv => inv.id}
                exportFilename={`invoices-${party.name.replace(/\s+/g, '-')}`}
                defaultSort={{ key: 'invoice_date', direction: 'desc' }}
                emptyMessage="No invoices yet"
              />
            );
          })()}
        </TabsContent>

        {/* ── Recent payments ─────────────────────────────────────────── */}
        <TabsContent value="payments" className="mt-3">
          {(() => {
            type PayRow = Party360Response['recent_payments'][number];
            const paymentColumns: ColumnDef<PayRow>[] = [
              {
                key: 'voucher_no',
                label: 'Voucher #',
                type: 'string',
                accessor: (p: PayRow) => p.voucher_no ?? '',
                format: (_v: unknown, p: PayRow) => (
                  <span className="font-mono text-xs text-blue-600">{p.voucher_no}</span>
                ),
              },
              {
                key: 'payment_date',
                label: 'Date',
                type: 'date',
                accessor: (p: PayRow) => p.payment_date ?? '',
                format: (_v: unknown, p: PayRow) => (
                  <span className="text-xs text-slate-600">{fmtDate(p.payment_date)}</span>
                ),
                exportValue: (p: PayRow) => fmtDate(p.payment_date),
              },
              {
                key: 'kind',
                label: 'Direction',
                type: 'enum',
                enumOptions: ['receipt', 'voucher'],
                accessor: (p: PayRow) => p.kind,
                format: (_v: unknown, p: PayRow) => (
                  <Badge
                    variant="outline"
                    className={
                      p.kind === 'receipt'
                        ? 'border-emerald-300 bg-emerald-50 text-[9px] uppercase text-emerald-700'
                        : 'border-amber-300 bg-amber-50 text-[9px] uppercase text-amber-700'
                    }
                  >
                    {p.kind === 'receipt' ? 'Received' : 'Paid'}
                  </Badge>
                ),
                exportValue: (p: PayRow) => p.kind === 'receipt' ? 'Received' : 'Paid',
              },
              {
                key: 'payment_mode',
                label: 'Mode',
                type: 'string',
                accessor: (p: PayRow) => p.payment_mode ?? '',
                format: (_v: unknown, p: PayRow) => (
                  <span className="text-xs uppercase text-slate-600">{p.payment_mode}</span>
                ),
              },
              {
                key: 'reference_no',
                label: 'Ref',
                type: 'string',
                accessor: (p: PayRow) => p.reference_no ?? '',
                format: (_v: unknown, p: PayRow) => (
                  <span className="text-xs text-slate-500">{p.reference_no ?? '—'}</span>
                ),
              },
              {
                key: 'amount',
                label: 'Amount',
                type: 'number',
                align: 'right',
                accessor: (p: PayRow) => Number(p.amount ?? 0),
                format: (_v: unknown, p: PayRow) => (
                  <span className={`font-medium ${p.kind === 'receipt' ? 'text-emerald-700' : 'text-amber-700'}`}>
                    {p.kind === 'receipt' ? '+' : '−'} {INR(p.amount)}
                  </span>
                ),
                exportValue: (p: PayRow) => {
                  const sign = p.kind === 'receipt' ? 1 : -1;
                  return (sign * Number(p.amount ?? 0)).toFixed(2);
                },
              },
            ];
            return (
              <DataTable<PayRow>
                id="customer360.payments"
                data={recent_payments}
                columns={paymentColumns}
                rowKey={p => p.id}
                exportFilename={`payments-${party.name.replace(/\s+/g, '-')}`}
                defaultSort={{ key: 'payment_date', direction: 'desc' }}
                emptyMessage="No payments yet"
              />
            );
          })()}
        </TabsContent>

        {/* ── Custom pricing ──────────────────────────────────────────── */}
        <TabsContent value="pricing" className="mt-3">
          {custom_rates.length === 0 ? (
            <Card>
              <CardContent className="px-4 py-8 text-center text-sm text-slate-400">
                No custom rates set — this customer pays product default rates.
                <div className="mt-2">
                  <Link to={`/pricing-matrix?party=${party.id}`}>
                    <Button size="sm" variant="outline">
                      <Tag className="mr-1.5 h-3 w-3" /> Set custom rates
                    </Button>
                  </Link>
                </div>
              </CardContent>
            </Card>
          ) : (() => {
            type RateRow = Party360Response['custom_rates'][number];
            const rateColumns: ColumnDef<RateRow>[] = [
              {
                key: 'product_name',
                label: 'Product',
                type: 'string',
                accessor: (r: RateRow) => r.product_name ?? '',
                format: (_v: unknown, r: RateRow) => (
                  <span className="font-medium">{r.product_name}</span>
                ),
              },
              {
                key: 'product_unit',
                label: 'Unit',
                type: 'string',
                accessor: (r: RateRow) => r.product_unit ?? '',
                format: (_v: unknown, r: RateRow) => (
                  <span className="text-xs uppercase text-slate-500">{r.product_unit}</span>
                ),
              },
              {
                key: 'default_rate',
                label: 'Default Rate',
                type: 'number',
                align: 'right',
                accessor: (r: RateRow) => Number(r.default_rate ?? 0),
                format: (_v: unknown, r: RateRow) => (
                  <span className="text-slate-500">{INR(r.default_rate)}</span>
                ),
                exportValue: (r: RateRow) => Number(r.default_rate ?? 0).toFixed(2),
              },
              {
                key: 'custom_rate',
                label: 'Custom Rate',
                type: 'number',
                align: 'right',
                accessor: (r: RateRow) => Number(r.custom_rate ?? 0),
                format: (_v: unknown, r: RateRow) => (
                  <span className="font-bold text-slate-900">{INR(r.custom_rate)}</span>
                ),
                exportValue: (r: RateRow) => Number(r.custom_rate ?? 0).toFixed(2),
              },
              {
                key: 'rate_diff',
                label: 'Diff',
                type: 'number',
                align: 'right',
                accessor: (r: RateRow) => Number(r.custom_rate ?? 0) - Number(r.default_rate ?? 0),
                format: (_v: unknown, r: RateRow) => {
                  const customRate = Number(r.custom_rate ?? 0);
                  const defaultRate = Number(r.default_rate ?? 0);
                  const diff = customRate - defaultRate;
                  const pct = defaultRate > 0 ? (diff / defaultRate) * 100 : 0;
                  return (
                    <span className={`text-xs ${diff > 0 ? 'text-emerald-700' : diff < 0 ? 'text-rose-700' : 'text-slate-400'}`}>
                      {diff === 0 ? '—' : `${diff > 0 ? '+' : ''}${INR(diff)} (${pct.toFixed(1)}%)`}
                    </span>
                  );
                },
                exportValue: (r: RateRow) => {
                  const diff = Number(r.custom_rate ?? 0) - Number(r.default_rate ?? 0);
                  return diff.toFixed(2);
                },
              },
              {
                key: 'effective_from',
                label: 'Since',
                type: 'date',
                accessor: (r: RateRow) => r.effective_from ?? '',
                format: (_v: unknown, r: RateRow) => (
                  <span className="text-xs text-slate-500">{fmtDate(r.effective_from)}</span>
                ),
                exportValue: (r: RateRow) => fmtDate(r.effective_from),
              },
            ];
            return (
              <DataTable<RateRow>
                id="customer360.rates"
                data={custom_rates}
                columns={rateColumns}
                rowKey={r => r.product_id}
                exportFilename={`rates-${party.name.replace(/\s+/g, '-')}`}
                defaultSort={{ key: 'product_name', direction: 'asc' }}
                emptyMessage="No custom rates"
              />
            );
          })()}
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
        {user?.role === 'admin' && <PortalAccessDialog partyId={party.id} partyName={party.name} />}
      </div>
    </div>
  );
}
