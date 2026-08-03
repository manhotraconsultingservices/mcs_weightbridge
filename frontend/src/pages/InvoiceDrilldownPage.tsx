/**
 * Invoice drill-down — full detail page reached by clicking a Sales/Purchase
 * invoice number. A left "tree" of commands drives the right content pane:
 *   • Summary        — header + amounts + settlement
 *   • Line Items     — every billed line
 *   • Where used     — weighment token · payments · revision chain · credit/debit
 *                      notes · source delivery challan · Tally sync · agent commission
 *   • Audit log      — every recorded action on this invoice (who / when / what)
 *
 * Route: /invoices/:id/detail  (guard fails open for detail routes).
 * Powered by GET /api/v1/invoices/:id/drilldown.
 */
import { useEffect, useState, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ArrowLeft, Loader2, FileText, List, Truck, IndianRupee, GitFork,
  FileMinus, Link2, History, Download, ExternalLink, CheckCircle2, XCircle, Clock,
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { DataTable, type ColumnDef } from '@/components/DataTable';
import api from '@/services/api';

const INR = (v: number | null | undefined) =>
  '₹' + Number(v ?? 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtDate = (s: string | null) =>
  s ? new Date(s.length <= 10 ? s + 'T00:00:00' : s).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }) : '—';
const fmtDT = (s: string | null) =>
  s ? new Date(s).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—';

interface DItem { description: string | null; hsn_code: string | null; quantity: number; unit: string | null; rate: number; gst_rate: number; total_amount: number; }
interface DPayment { ref: string; kind: string; amount: number; date: string | null; mode: string; }
interface DRevision { id: string; invoice_no: string; revision_no: number; status: string; grand_total: number; is_current: boolean; }
interface DNote { id: string; invoice_no: string; type: string; reason: string | null; grand_total: number; status: string; }
interface DAudit { action: string; who: string; at: string | null; ip: string | null; details: Record<string, unknown> | null; }
interface Drill {
  summary: {
    id: string; invoice_no: string; invoice_type: string; tax_type: string; status: string; payment_status: string;
    invoice_date: string | null; due_date: string | null;
    party: { id: string; name: string; gstin: string | null; phone: string | null } | null;
    customer_name: string | null; vehicle_no: string | null;
    subtotal: number; discount_amount: number; taxable_amount: number; tax_amount: number; freight: number;
    vehicle_rent: number; royalty_amount: number; round_off: number; grand_total: number; amount_paid: number; amount_due: number;
    revision_no: number; einvoice_status: string | null; irn: string | null; ewb_no: string | null; ewb_status: string | null;
    created_by: string | null; created_at: string | null; updated_at: string | null; items: DItem[];
  };
  audit: DAudit[];
  where_used: {
    token: { id: string; token_no: string | null; token_date: string | null; vehicle_no: string | null } | null;
    payments: DPayment[]; revisions: DRevision[]; notes: DNote[];
    challan: { id: string; challan_no: string; challan_date: string | null } | null;
    tally: { synced: boolean; synced_at: string | null; jobs: { status: string; attempts: number; last_error: string; completed_at: string | null }[] };
    agent: { name: string; commission_amount: number } | null;
    party_balance: number | null;
  };
}

type SectionKey = 'summary' | 'items' | 'token' | 'payments' | 'revisions' | 'notes' | 'related' | 'audit';

const StatusPill = ({ status }: { status: string }) => {
  const map: Record<string, string> = {
    final: 'bg-emerald-100 text-emerald-700 border-emerald-300',
    draft: 'bg-amber-100 text-amber-700 border-amber-300',
    superseded: 'bg-slate-100 text-slate-500 border-slate-300',
    cancelled: 'bg-rose-100 text-rose-700 border-rose-300',
  };
  return <span className={`text-[11px] font-semibold px-2 py-0.5 rounded-full border ${map[status] || 'bg-slate-100 text-slate-600 border-slate-300'}`}>{status.toUpperCase()}</span>;
};

export default function InvoiceDrilldownPage() {
  const { id } = useParams<{ id: string }>();
  const nav = useNavigate();
  const [data, setData] = useState<Drill | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [section, setSection] = useState<SectionKey>('summary');

  const load = useCallback(() => {
    if (!id) return;
    setLoading(true);
    api.get<Drill>(`/api/v1/invoices/${id}/drilldown`)
      .then(r => setData(r.data))
      .catch(e => setError((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed to load invoice detail'))
      .finally(() => setLoading(false));
  }, [id]);
  useEffect(() => { load(); }, [load]);
  // Reset to Summary whenever the invoice changes (drill-through to a revision/note)
  useEffect(() => { setSection('summary'); }, [id]);

  const downloadPdf = async () => {
    if (!id) return;
    try {
      const res = await api.get(`/api/v1/invoices/${id}/pdf`, { responseType: 'blob' });
      const url = URL.createObjectURL(res.data as Blob);
      const a = document.createElement('a');
      a.href = url; a.download = `${data?.summary.invoice_no || 'invoice'}.pdf`;
      a.click(); URL.revokeObjectURL(url);
    } catch { /* ignore */ }
  };

  if (loading) return <div className="p-8 text-center text-muted-foreground"><Loader2 className="h-5 w-5 animate-spin inline" /> Loading…</div>;
  if (error || !data) return (
    <div className="p-8 space-y-3">
      <Button variant="ghost" size="sm" onClick={() => nav(-1)} className="gap-1"><ArrowLeft className="h-4 w-4" /> Back</Button>
      <div className="text-rose-600">{error || 'Not found'}</div>
    </div>
  );

  const s = data.summary;
  const w = data.where_used;
  const backTo = s.invoice_type === 'purchase' ? '/purchase-invoices' : '/invoices';

  const NAV: ({ key: SectionKey; label: string; icon: typeof FileText; count?: number } | { group: string })[] = [
    { key: 'summary', label: 'Summary', icon: FileText },
    { key: 'items', label: 'Line Items', icon: List, count: s.items.length },
    { group: 'Where used' },
    { key: 'token', label: 'Weighment Token', icon: Truck, count: w.token ? 1 : 0 },
    { key: 'payments', label: 'Payments', icon: IndianRupee, count: w.payments.length },
    { key: 'revisions', label: 'Revisions', icon: GitFork, count: w.revisions.length },
    { key: 'notes', label: 'Credit / Debit Notes', icon: FileMinus, count: w.notes.length },
    { key: 'related', label: 'Challan · Tally · Agent', icon: Link2 },
    { group: 'History' },
    { key: 'audit', label: 'Audit Log', icon: History, count: data.audit.length },
  ];

  const ITEM_COLS: ColumnDef<DItem>[] = [
    { key: 'description', label: 'Particulars', accessor: r => r.description || '—' },
    { key: 'hsn_code', label: 'HSN', accessor: r => r.hsn_code || '—' },
    { key: 'quantity', label: 'Qty', type: 'number', align: 'right', accessor: r => r.quantity, format: (v, r) => `${Number(v).toLocaleString('en-IN')} ${r.unit || ''}` },
    { key: 'rate', label: 'Rate', type: 'number', align: 'right', accessor: r => r.rate, format: v => INR(v as number) },
    { key: 'gst_rate', label: 'GST %', type: 'number', align: 'right', accessor: r => r.gst_rate, format: v => `${v}%` },
    { key: 'total_amount', label: 'Amount', type: 'number', align: 'right', accessor: r => r.total_amount, format: v => INR(v as number) },
  ];
  const PAY_COLS: ColumnDef<DPayment>[] = [
    { key: 'ref', label: 'Reference', accessor: r => r.ref },
    { key: 'kind', label: 'Type', type: 'enum', enumOptions: ['receipt', 'voucher'], accessor: r => r.kind, format: v => String(v) === 'receipt' ? 'Money In' : 'Money Out' },
    { key: 'date', label: 'Date', type: 'date', accessor: r => r.date, format: v => fmtDate(v as string) },
    { key: 'mode', label: 'Mode', accessor: r => r.mode || '—' },
    { key: 'amount', label: 'Amount', type: 'number', align: 'right', accessor: r => r.amount, format: v => INR(v as number) },
  ];
  const AUDIT_COLS: ColumnDef<DAudit>[] = [
    { key: 'at', label: 'When (IST)', type: 'date', accessor: r => r.at, format: v => fmtDT(v as string) },
    { key: 'action', label: 'Action', type: 'enum', enumOptions: ['create', 'update', 'finalize', 'cancel', 'write_off', 'delete'], accessor: r => r.action,
      format: v => <Badge variant="outline" className="capitalize">{String(v)}</Badge>, exportValue: r => r.action },
    { key: 'who', label: 'By', accessor: r => r.who || 'system' },
    { key: 'details', label: 'Details', accessor: r => r.details ? JSON.stringify(r.details) : '',
      format: (_v, r) => r.details ? <span className="text-[11px] font-mono text-muted-foreground">{Object.entries(r.details).map(([k, val]) => `${k}: ${val}`).join(' · ')}</span> : '—',
      exportValue: r => r.details ? JSON.stringify(r.details) : '' },
  ];

  const Row = ({ label, value, mono }: { label: string; value: React.ReactNode; mono?: boolean }) => (
    <div className="flex justify-between gap-4 py-1.5 border-b border-dashed last:border-0">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className={`text-sm text-right ${mono ? 'font-mono' : 'font-medium'}`}>{value}</span>
    </div>
  );

  return (
    <div className="max-w-6xl mx-auto p-3 md:p-5 space-y-4">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="ghost" size="sm" onClick={() => nav(backTo)} className="gap-1"><ArrowLeft className="h-4 w-4" /> {s.invoice_type === 'purchase' ? 'Purchase Invoices' : 'Sales Invoices'}</Button>
        <div className="flex items-center gap-2 flex-wrap">
          <h1 className="text-lg md:text-xl font-bold font-mono">{s.invoice_no}</h1>
          <StatusPill status={s.status} />
          <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-full border ${s.tax_type === 'non_gst' ? 'bg-amber-100 text-amber-700 border-amber-300' : 'bg-emerald-50 text-emerald-700 border-emerald-200'}`}>
            {s.tax_type === 'non_gst' ? 'Bill of Supply' : 'GST'}
          </span>
          {s.revision_no > 1 && <span className="text-[10px] font-medium px-1.5 py-0.5 rounded-full bg-purple-50 text-purple-600 border border-purple-200">Rv{s.revision_no}</span>}
        </div>
        <div className="ml-auto flex gap-2">
          {s.status === 'final' && <Button size="sm" variant="outline" className="gap-1.5" onClick={downloadPdf}><Download className="h-4 w-4" /> PDF</Button>}
        </div>
      </div>

      <div className="flex flex-col md:flex-row gap-4">
        {/* Left tree */}
        <nav className="md:w-56 shrink-0 flex md:flex-col gap-1 overflow-x-auto md:overflow-visible pb-1">
          {NAV.map((n, i) => 'group' in n ? (
            <div key={`g${i}`} className="hidden md:block px-2 pt-3 pb-1 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">{n.group}</div>
          ) : (
            <button key={n.key} onClick={() => setSection(n.key)}
              className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm whitespace-nowrap transition-colors ${section === n.key ? 'bg-primary text-primary-foreground font-semibold' : 'hover:bg-muted text-foreground'}`}>
              <n.icon className="h-4 w-4 shrink-0" />
              <span>{n.label}</span>
              {n.count !== undefined && n.count > 0 && (
                <span className={`ml-auto text-[10px] px-1.5 py-0.5 rounded-full ${section === n.key ? 'bg-primary-foreground/20' : 'bg-muted-foreground/15'}`}>{n.count}</span>
              )}
            </button>
          ))}
        </nav>

        {/* Right content */}
        <div className="flex-1 min-w-0 space-y-4">
          {section === 'summary' && (
            <div className="grid md:grid-cols-2 gap-4">
              <Card>
                <CardHeader className="pb-2"><CardTitle className="text-sm">Invoice</CardTitle></CardHeader>
                <CardContent className="pt-0">
                  <Row label="Type" value={<span className="capitalize">{s.invoice_type}</span>} />
                  <Row label="Invoice date" value={fmtDate(s.invoice_date)} />
                  <Row label="Due date" value={fmtDate(s.due_date)} />
                  <Row label="Vehicle" value={s.vehicle_no || '—'} mono />
                  <Row label="Created by" value={s.created_by || '—'} />
                  <Row label="Created at" value={fmtDT(s.created_at)} />
                  {s.irn && <Row label="IRN" value={<span className="text-[10px] break-all">{s.irn}</span>} mono />}
                  {s.einvoice_status && s.einvoice_status !== 'none' && <Row label="eInvoice" value={<span className="capitalize">{s.einvoice_status}</span>} />}
                  {s.ewb_no && <Row label="E-Way Bill" value={s.ewb_no} mono />}
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2"><CardTitle className="text-sm">Party</CardTitle></CardHeader>
                <CardContent className="pt-0">
                  <Row label="Name" value={s.party ? (
                    <button className="text-primary hover:underline inline-flex items-center gap-1" onClick={() => nav(`/customers/${s.party!.id}`)}>
                      {s.party.name} <ExternalLink className="h-3 w-3" />
                    </button>
                  ) : (s.customer_name || 'Walk-in')} />
                  {s.party?.gstin && <Row label="GSTIN" value={s.party.gstin} mono />}
                  {s.party?.phone && <Row label="Phone" value={s.party.phone} mono />}
                  {w.party_balance != null && <Row label="Party balance" value={INR(w.party_balance)} mono />}
                </CardContent>
              </Card>
              <Card className="md:col-span-2">
                <CardHeader className="pb-2"><CardTitle className="text-sm">Amounts</CardTitle></CardHeader>
                <CardContent className="pt-0 grid md:grid-cols-2 gap-x-8">
                  <div>
                    <Row label="Taxable" value={INR(s.taxable_amount)} mono />
                    {s.discount_amount > 0 && <Row label="Discount" value={INR(s.discount_amount)} mono />}
                    {s.tax_amount > 0 && <Row label="GST" value={INR(s.tax_amount)} mono />}
                    {s.freight > 0 && <Row label="Freight" value={INR(s.freight)} mono />}
                    {s.vehicle_rent > 0 && <Row label="Vehicle rent" value={INR(s.vehicle_rent)} mono />}
                    {s.royalty_amount > 0 && <Row label="Royalty" value={INR(s.royalty_amount)} mono />}
                    {s.round_off !== 0 && <Row label="Round off" value={INR(s.round_off)} mono />}
                  </div>
                  <div>
                    <Row label="Grand total" value={<span className="font-bold">{INR(s.grand_total)}</span>} mono />
                    <Row label="Paid" value={INR(s.amount_paid)} mono />
                    <Row label="Balance due" value={<span className={s.amount_due > 0 ? 'text-rose-600 font-semibold' : 'text-emerald-600'}>{INR(s.amount_due)}</span>} mono />
                    <Row label="Payment status" value={<span className="capitalize">{s.payment_status}</span>} />
                  </div>
                </CardContent>
              </Card>
            </div>
          )}

          {section === 'items' && (
            <Card><CardContent className="pt-4">
              <DataTable<DItem> id="invoice.drilldown.items" data={s.items} columns={ITEM_COLS}
                rowKey={(_r, i) => String(i)} exportFilename={`${s.invoice_no}-items`} emptyMessage="No line items" />
            </CardContent></Card>
          )}

          {section === 'token' && (
            <Card><CardContent className="pt-4">
              {w.token ? (
                <div className="space-y-2">
                  <Row label="Token no" value={w.token.token_no != null ? `#${w.token.token_no}` : '—'} mono />
                  <Row label="Token date" value={fmtDate(w.token.token_date)} />
                  <Row label="Vehicle" value={w.token.vehicle_no || '—'} mono />
                  <Button size="sm" variant="outline" className="mt-2 gap-1.5" onClick={() => nav(`/tokens-v1?search=${w.token!.token_no ?? ''}`)}>
                    <Truck className="h-4 w-4" /> Open in Weighments
                  </Button>
                </div>
              ) : <div className="text-sm text-muted-foreground py-6 text-center">This invoice was created manually — no linked weighment token.</div>}
            </CardContent></Card>
          )}

          {section === 'payments' && (
            <Card><CardContent className="pt-4">
              <DataTable<DPayment> id="invoice.drilldown.payments" data={w.payments} columns={PAY_COLS}
                rowKey={(r, i) => `${r.ref}-${i}`} exportFilename={`${s.invoice_no}-payments`}
                emptyMessage="No payments recorded against this invoice yet." />
            </CardContent></Card>
          )}

          {section === 'revisions' && (
            <Card><CardContent className="pt-4">
              {w.revisions.length === 0 ? (
                <div className="text-sm text-muted-foreground py-6 text-center">No revisions — this is the original invoice.</div>
              ) : (
                <div className="space-y-1.5">
                  {w.revisions.map(r => (
                    <button key={r.id} onClick={() => !r.is_current && nav(`/invoices/${r.id}/detail`)}
                      className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg border text-left ${r.is_current ? 'bg-primary/5 border-primary/40' : 'hover:bg-muted'}`}>
                      <GitFork className="h-4 w-4 text-muted-foreground shrink-0" />
                      <div className="flex-1 min-w-0">
                        <span className="font-mono text-sm">{r.invoice_no}</span>
                        <span className="ml-2 text-xs text-muted-foreground">Rv{r.revision_no}</span>
                      </div>
                      <StatusPill status={r.status} />
                      <span className="font-mono text-sm">{INR(r.grand_total)}</span>
                      {r.is_current ? <span className="text-[10px] font-semibold text-primary">CURRENT</span> : <ExternalLink className="h-3.5 w-3.5 text-muted-foreground" />}
                    </button>
                  ))}
                </div>
              )}
            </CardContent></Card>
          )}

          {section === 'notes' && (
            <Card><CardContent className="pt-4">
              {w.notes.length === 0 ? (
                <div className="text-sm text-muted-foreground py-6 text-center">No credit or debit notes issued against this invoice.</div>
              ) : (
                <div className="space-y-1.5">
                  {w.notes.map(n => (
                    <button key={n.id} onClick={() => nav(`/invoices/${n.id}/detail`)}
                      className="w-full flex items-center gap-3 px-3 py-2 rounded-lg border hover:bg-muted text-left">
                      <FileMinus className={`h-4 w-4 shrink-0 ${n.type === 'credit_note' ? 'text-rose-500' : 'text-blue-500'}`} />
                      <div className="flex-1 min-w-0">
                        <span className="font-mono text-sm">{n.invoice_no}</span>
                        <span className="ml-2 text-xs capitalize text-muted-foreground">{n.type.replace('_', ' ')}</span>
                        {n.reason && <p className="text-[11px] text-muted-foreground truncate">{n.reason}</p>}
                      </div>
                      <StatusPill status={n.status} />
                      <span className="font-mono text-sm">{INR(n.grand_total)}</span>
                      <ExternalLink className="h-3.5 w-3.5 text-muted-foreground" />
                    </button>
                  ))}
                </div>
              )}
            </CardContent></Card>
          )}

          {section === 'related' && (
            <div className="grid md:grid-cols-2 gap-4">
              <Card>
                <CardHeader className="pb-2"><CardTitle className="text-sm">Source Delivery Challan</CardTitle></CardHeader>
                <CardContent className="pt-0">
                  {w.challan ? (
                    <button className="text-primary hover:underline inline-flex items-center gap-1" onClick={() => nav('/delivery-challans')}>
                      {w.challan.challan_no} · {fmtDate(w.challan.challan_date)} <ExternalLink className="h-3 w-3" />
                    </button>
                  ) : <span className="text-sm text-muted-foreground">Not converted from a challan.</span>}
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2"><CardTitle className="text-sm">Agent Commission</CardTitle></CardHeader>
                <CardContent className="pt-0">
                  {w.agent ? (
                    <>
                      <Row label="Agent" value={w.agent.name} />
                      <Row label="Commission" value={INR(w.agent.commission_amount)} mono />
                    </>
                  ) : <span className="text-sm text-muted-foreground">No sales partner on this invoice.</span>}
                </CardContent>
              </Card>
              <Card className="md:col-span-2">
                <CardHeader className="pb-2"><CardTitle className="text-sm flex items-center gap-2">Tally Sync {w.tally.synced ? <CheckCircle2 className="h-4 w-4 text-emerald-600" /> : <Clock className="h-4 w-4 text-amber-500" />}</CardTitle></CardHeader>
                <CardContent className="pt-0">
                  <Row label="Synced" value={w.tally.synced ? `Yes · ${fmtDT(w.tally.synced_at)}` : 'Not yet'} />
                  {w.tally.jobs.length > 0 && (
                    <div className="mt-2 space-y-1">
                      {w.tally.jobs.map((j, i) => (
                        <div key={i} className="flex items-center gap-2 text-xs">
                          {j.status === 'done' ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" /> : j.status === 'dead' || j.status === 'failed' ? <XCircle className="h-3.5 w-3.5 text-rose-500" /> : <Clock className="h-3.5 w-3.5 text-amber-500" />}
                          <span className="capitalize font-medium">{j.status}</span>
                          <span className="text-muted-foreground">· {j.attempts} attempt(s)</span>
                          {j.last_error && <span className="text-rose-500 truncate">· {j.last_error}</span>}
                        </div>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>
          )}

          {section === 'audit' && (
            <Card><CardContent className="pt-4">
              <DataTable<DAudit> id="invoice.drilldown.audit" data={data.audit} columns={AUDIT_COLS}
                rowKey={(r, i) => `${r.action}-${i}`} exportFilename={`${s.invoice_no}-audit`}
                defaultSort={{ key: 'at', direction: 'desc' }}
                emptyMessage="No audit entries recorded for this invoice." />
            </CardContent></Card>
          )}
        </div>
      </div>
    </div>
  );
}
