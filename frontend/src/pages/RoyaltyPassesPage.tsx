import { useEffect, useState, useCallback, useRef } from 'react';
import api from '@/services/api';
import { toast } from 'sonner';
import {
  Plus, Loader2, X, MinusCircle, AlertTriangle, FileText,
  ChevronRight, ChevronDown, Download, Upload, Bell, BellOff, CheckCircle2,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger } from '@/components/ui/select';
import { DataTable, type ColumnDef } from '@/components/DataTable';

interface Party { id: string; name: string }
interface Product { id: string; name: string }
interface Pass {
  id: string; pass_no: string; pass_type: string; source_name: string | null;
  party_id: string | null; party_name: string | null; mineral: string | null;
  issue_date: string | null; valid_till: string | null;
  quantity_mt: number | string; rate: number | string; amount: number | string;
  status: string; consumed_mt: number | string; balance_mt: number | string;
  utilization_pct: number; days_to_expiry: number | null;
}
interface Consumption {
  id: string; quantity_mt: number | string;
  authorized_mt: number | string | null; actual_mt: number | string | null;
  variance_mt: number | string | null; vehicle_no: string | null;
  token_id: string | null; token_no: number | null; invoice_id: string | null;
  consumed_date: string; notes: string | null; created_at: string;
}
interface Recon {
  authorised_mt: number; consumed_mt: number; purchase_inbound_mt: number;
  balance_mt: number; unaccounted_mt: number; total_royalty_amount: number;
  pass_count: number; active_count: number; expiring_count: number;
}
interface AlertCfg { enabled: boolean; unaccounted_threshold_mt: number }
interface ImportResult {
  imported: number; previewed: number; skipped: number; error_count: number;
  errors: { row: number; error: string }[];
  total_rows: number; dry_run: boolean;
  columns_detected: Record<string, string>;
  sample: { pass_no: string; pass_type: string; source_name: string | null; mineral: string | null; quantity_mt: string; issue_date: string | null; valid_till: string | null }[];
}

const MT = (v: number | string | null | undefined) => Number(v ?? 0).toFixed(3) + ' MT';
const INR = (v: number | string | null | undefined) => '₹' + Number(v ?? 0).toLocaleString('en-IN', { minimumFractionDigits: 2 });
const today = () => new Date().toISOString().slice(0, 10);
const monthStart = () => { const d = new Date(); d.setDate(1); return d.toISOString().slice(0, 10); };
const PASS_TYPES = ['royalty', 'e_transit', 'mineral_permit'];
const STATUS_PILL: Record<string, string> = {
  active: 'bg-emerald-100 text-emerald-700', exhausted: 'bg-blue-100 text-blue-700',
  expired: 'bg-amber-100 text-amber-700', cancelled: 'bg-gray-200 text-gray-500',
};

// ─── DataTable column definitions ────────────────────────────────────────────

const PASS_COLUMNS: ColumnDef<Pass>[] = [
  {
    key: 'pass_no',
    label: 'Pass No',
    type: 'string',
    accessor: r => r.pass_no,
    format: v => <span className="font-mono font-semibold">{String(v ?? '')}</span>,
  },
  {
    key: 'pass_type',
    label: 'Type',
    type: 'enum',
    enumOptions: ['royalty', 'e_transit', 'mineral_permit'],
    accessor: r => r.pass_type,
    format: v => <span className="text-xs capitalize">{String(v ?? '').replace('_', ' ')}</span>,
  },
  {
    key: 'source_name',
    label: 'Source / Supplier',
    type: 'string',
    accessor: r => r.source_name ?? r.party_name ?? '',
    format: (_v, r) => (
      <span className="max-w-[160px] truncate block">{r.source_name ?? r.party_name ?? '—'}</span>
    ),
  },
  {
    key: 'mineral',
    label: 'Mineral',
    type: 'string',
    accessor: r => r.mineral ?? '',
    format: v => <span className="text-xs">{String(v ?? '') || '—'}</span>,
  },
  {
    key: 'valid_till',
    label: 'Valid Till',
    type: 'date',
    accessor: r => r.valid_till ?? '',
    format: (_v, r) => (
      <span className="text-xs">
        {r.valid_till ? new Date(r.valid_till).toLocaleDateString('en-IN') : '—'}
        {r.days_to_expiry != null && r.days_to_expiry <= 15 && r.status === 'active' && (
          <span className="text-amber-600"> ({r.days_to_expiry}d)</span>
        )}
      </span>
    ),
    exportValue: r => r.valid_till ?? '',
  },
  {
    key: 'utilization',
    label: 'Utilisation',
    type: 'number',
    accessor: r => Number(r.utilization_pct) || 0,
    format: (_v, r) => {
      const pct = Math.min(100, Number(r.utilization_pct) || 0);
      const over = Number(r.balance_mt) < 0;
      return (
        <div className="w-40">
          <div className="h-2 rounded-full bg-muted overflow-hidden">
            <div
              className={`h-full ${over ? 'bg-red-500' : pct > 85 ? 'bg-amber-500' : 'bg-emerald-500'}`}
              style={{ width: `${pct}%` }}
            />
          </div>
          <p className="text-[10px] text-muted-foreground mt-0.5">
            {MT(r.consumed_mt)} / {MT(r.quantity_mt)} · bal {MT(r.balance_mt)}
          </p>
        </div>
      );
    },
    exportValue: r => `${Number(r.consumed_mt).toFixed(3)} / ${Number(r.quantity_mt).toFixed(3)}`,
    sortable: false,
  },
  {
    key: 'status',
    label: 'Status',
    type: 'enum',
    enumOptions: ['active', 'exhausted', 'expired', 'cancelled'],
    accessor: r => r.status,
    format: v => (
      <span className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${STATUS_PILL[String(v ?? '')] ?? ''}`}>
        {String(v ?? '')}
      </span>
    ),
  },
];

export default function RoyaltyPassesPage() {
  const [rows, setRows] = useState<Pass[]>([]);
  const [recon, setRecon] = useState<Recon | null>(null);
  const [parties, setParties] = useState<Party[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(false);
  const [range, setRange] = useState({ from: monthStart(), to: today() });
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [consumeFor, setConsumeFor] = useState<Pass | null>(null);
  const [consumeForm, setConsumeForm] = useState({ quantity_mt: '', notes: '' });

  // P3: expanded consumption sub-table state
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [consumptions, setConsumptions] = useState<Record<string, Consumption[]>>({});
  const [loadingCons, setLoadingCons] = useState<string | null>(null);

  // P2: CSV import state
  const fileRef = useRef<HTMLInputElement>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importBusy, setImportBusy] = useState(false);
  const [importResult, setImportResult] = useState<ImportResult | null>(null);
  const [skipDuplicates, setSkipDuplicates] = useState(true);

  // P2: Alert config state
  const [alertCfg, setAlertCfg] = useState<AlertCfg>({ enabled: true, unaccounted_threshold_mt: 50 });
  const [alertBusy, setAlertBusy] = useState(false);

  const [form, setForm] = useState({
    pass_no: '', pass_type: 'royalty', source_name: '', party_id: '', product_id: '', mineral: '',
    issue_date: today(), valid_till: '', quantity_mt: '', rate: '', amount: '', vehicle_no: '', notes: '',
  });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const p = await api.get('/api/v1/royalty/passes', { params: { page_size: 300 } });
      setRows(p.data.items ?? []);
    } catch {
      toast.error('Could not load royalty passes');
    } finally {
      setLoading(false);
    }
    try {
      const r = await api.get('/api/v1/royalty/reconciliation', { params: { date_from: range.from, date_to: range.to } });
      setRecon(r.data);
    } catch { /* recon optional */ }
  }, [range.from, range.to]);

  useEffect(() => {
    load();
    api.get('/api/v1/parties', { params: { page_size: 500 } }).then(r => setParties(Array.isArray(r.data) ? r.data : r.data.items ?? [])).catch(() => {});
    api.get('/api/v1/products', { params: { page_size: 500 } }).then(r => setProducts(Array.isArray(r.data) ? r.data : r.data.items ?? [])).catch(() => {});
    api.get('/api/v1/royalty/alert-config').then(r => setAlertCfg(r.data)).catch(() => {});
  }, [load]);

  // P2: preview CSV (dry_run=true)
  async function previewImport() {
    if (!importFile) return;
    setImportBusy(true);
    setImportResult(null);
    const fd = new FormData();
    fd.append('file', importFile);
    try {
      const r = await api.post<ImportResult>(
        `/api/v1/royalty/passes/import-csv?skip_duplicates=${skipDuplicates}&dry_run=true`, fd,
        { headers: { 'Content-Type': 'multipart/form-data' } },
      );
      setImportResult(r.data);
    } catch (e: unknown) {
      toast.error((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Preview failed');
    } finally { setImportBusy(false); }
  }

  // P2: actual import (dry_run=false)
  async function doImport() {
    if (!importFile) return;
    setImportBusy(true);
    const fd = new FormData();
    fd.append('file', importFile);
    try {
      const r = await api.post<ImportResult>(
        `/api/v1/royalty/passes/import-csv?skip_duplicates=${skipDuplicates}&dry_run=false`, fd,
        { headers: { 'Content-Type': 'multipart/form-data' } },
      );
      toast.success(`Imported ${r.data.imported} pass(es), skipped ${r.data.skipped} duplicate(s)`);
      setImportOpen(false); setImportFile(null); setImportResult(null);
      load();
    } catch (e: unknown) {
      toast.error((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Import failed');
    } finally { setImportBusy(false); }
  }

  // P2: save alert config
  async function saveAlertCfg() {
    setAlertBusy(true);
    try {
      await api.put('/api/v1/royalty/alert-config', alertCfg);
      toast.success('Alert settings saved');
    } catch { toast.error('Could not save alert settings'); }
    finally { setAlertBusy(false); }
  }

  // P3: toggle consumption history for a pass row
  async function toggleConsumptions(passId: string) {
    if (expandedId === passId) { setExpandedId(null); return; }
    setExpandedId(passId);
    if (consumptions[passId]) return; // already cached
    setLoadingCons(passId);
    try {
      const r = await api.get(`/api/v1/royalty/passes/${passId}/consumptions`);
      setConsumptions(prev => ({ ...prev, [passId]: r.data }));
    } catch {
      toast.error('Could not load consumption history');
    } finally {
      setLoadingCons(null);
    }
  }

  // P3: CSV export for a pass's consumption history
  function exportCsv(passNo: string, passId: string) {
    const csRows = consumptions[passId];
    if (!csRows || csRows.length === 0) { toast.error('Load history first'); return; }
    const hdr = ['Date', 'Token No', 'Vehicle No', 'Authorised MT', 'Actual MT', 'Variance MT', 'Quantity MT', 'Notes'];
    const lines = csRows.map(c => [
      c.consumed_date, c.token_no ?? '', c.vehicle_no ?? '',
      Number(c.authorized_mt ?? 0).toFixed(3), Number(c.actual_mt ?? 0).toFixed(3),
      Number(c.variance_mt ?? 0).toFixed(3), Number(c.quantity_mt).toFixed(3),
      c.notes ?? '',
    ].map(v => `"${String(v).replace(/"/g, '""')}"`).join(','));
    const csv = [hdr.join(','), ...lines].join('\n');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
    a.download = `royalty_${passNo}_consumptions.csv`;
    a.click();
  }

  function resetForm() {
    setForm({
      pass_no: '', pass_type: 'royalty', source_name: '', party_id: '', product_id: '', mineral: '',
      issue_date: today(), valid_till: '', quantity_mt: '', rate: '', amount: '', vehicle_no: '', notes: '',
    });
    setErr('');
  }

  async function submit() {
    setErr('');
    if (!form.pass_no.trim()) { setErr('Pass number is required.'); return; }
    if (!(Number(form.quantity_mt) > 0)) { setErr('Authorised quantity (MT) must be greater than zero.'); return; }
    setBusy(true);
    try {
      await api.post('/api/v1/royalty/passes', {
        pass_no: form.pass_no, pass_type: form.pass_type,
        source_name: form.source_name || undefined,
        party_id: form.party_id || undefined, product_id: form.product_id || undefined,
        mineral: form.mineral || undefined,
        issue_date: form.issue_date || undefined, valid_till: form.valid_till || undefined,
        quantity_mt: Number(form.quantity_mt), rate: Number(form.rate || 0), amount: Number(form.amount || 0),
        vehicle_no: form.vehicle_no || undefined, notes: form.notes || undefined,
      });
      toast.success('Royalty pass added'); setOpen(false); resetForm(); load();
    } catch (e: unknown) {
      setErr((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Could not save pass');
    } finally { setBusy(false); }
  }

  async function doConsume() {
    if (!consumeFor) return;
    if (!(Number(consumeForm.quantity_mt) > 0)) { toast.error('Enter a quantity'); return; }
    try {
      await api.post(`/api/v1/royalty/passes/${consumeFor.id}/consume`, {
        quantity_mt: Number(consumeForm.quantity_mt), notes: consumeForm.notes || undefined,
      });
      toast.success('Consumption recorded');
      // Invalidate cached consumptions so next expand re-fetches
      setConsumptions(prev => { const n = { ...prev }; delete n[consumeFor.id]; return n; });
      setConsumeFor(null); setConsumeForm({ quantity_mt: '', notes: '' }); load();
    } catch (e: unknown) {
      toast.error((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed');
    }
  }

  async function cancel(p: Pass) {
    if (!confirm(`Cancel pass ${p.pass_no}?`)) return;
    try { await api.post(`/api/v1/royalty/passes/${p.id}/cancel`); toast.success('Pass cancelled'); load(); }
    catch { toast.error('Cancel failed'); }
  }

  const expiring = rows.filter(p => p.status === 'active' && p.days_to_expiry != null && p.days_to_expiry <= 15);

  // The currently-expanded pass (for the consumption panel below the table)
  const expandedPass = rows.find(p => p.id === expandedId) ?? null;

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-xl font-bold">Royalty / Transit Passes</h1>
          <p className="text-xs text-muted-foreground">Track mineral royalty & e-transit passes; reconcile authorised qty vs inbound loads.</p>
        </div>
        <div className="flex items-center gap-2">
          <Input type="date" className="h-8 w-36 text-xs" value={range.from} onChange={e => setRange(r => ({ ...r, from: e.target.value }))} />
          <span className="text-xs text-muted-foreground">→</span>
          <Input type="date" className="h-8 w-36 text-xs" value={range.to} onChange={e => setRange(r => ({ ...r, to: e.target.value }))} />
          <Button variant="outline" onClick={() => { setImportFile(null); setImportResult(null); setImportOpen(true); }} className="gap-1.5">
            <Upload className="h-4 w-4" /> Import CSV
          </Button>
          <Button onClick={() => { resetForm(); setOpen(true); }} className="gap-1.5"><Plus className="h-4 w-4" /> New Pass</Button>
        </div>
      </div>

      {/* Reconciliation cards — 6 cards (P3: + Royalty Paid) */}
      {recon && (
        <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
          {[
            { label: 'Authorised', val: MT(recon.authorised_mt), hint: 'on passes issued in range' },
            { label: 'Consumed', val: MT(recon.consumed_mt), hint: 'drawn against passes' },
            { label: 'Purchase inbound', val: MT(recon.purchase_inbound_mt), hint: 'completed purchase tokens' },
            { label: 'Pass balance', val: MT(recon.balance_mt), hint: 'authorised − consumed' },
            { label: 'Unaccounted', val: MT(recon.unaccounted_mt), hint: 'inbound − consumed', warn: recon.unaccounted_mt > 0.5 },
            { label: 'Royalty paid', val: INR(recon.total_royalty_amount), hint: 'sum of pass amounts (₹)', accent: true },
          ].map(c => (
            <div key={c.label} className={`rounded-lg border p-3 ${c.warn ? 'border-amber-300 bg-amber-50' : c.accent ? 'border-blue-200 bg-blue-50' : ''}`}>
              <p className="text-[11px] text-muted-foreground">{c.label}</p>
              <p className={`text-base font-bold ${c.warn ? 'text-amber-700' : c.accent ? 'text-blue-700' : ''}`}>{c.val}</p>
              <p className="text-[10px] text-muted-foreground">{c.hint}</p>
            </div>
          ))}
        </div>
      )}

      {/* P2: Unaccounted MT alert config — compact inline row */}
      <div className="rounded-lg border px-4 py-2.5 flex flex-wrap items-center gap-3 bg-muted/20 text-sm">
        <span className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
          {alertCfg.enabled ? <Bell className="h-3.5 w-3.5 text-amber-500" /> : <BellOff className="h-3.5 w-3.5" />}
          Unaccounted MT alert
        </span>
        <button
          onClick={() => setAlertCfg(c => ({ ...c, enabled: !c.enabled }))}
          className={`relative inline-flex h-5 w-9 shrink-0 rounded-full border-2 border-transparent transition-colors
            ${alertCfg.enabled ? 'bg-amber-500' : 'bg-gray-200'}`}
        >
          <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform
            ${alertCfg.enabled ? 'translate-x-4' : 'translate-x-0'}`} />
        </button>
        {alertCfg.enabled && (
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-muted-foreground">Fire when &gt;</span>
            <Input
              type="number" step="1" min="1"
              className="h-7 w-24 text-xs"
              value={alertCfg.unaccounted_threshold_mt}
              onChange={e => setAlertCfg(c => ({ ...c, unaccounted_threshold_mt: Number(e.target.value) }))}
            />
            <span className="text-xs text-muted-foreground">MT unaccounted</span>
          </div>
        )}
        <Button size="sm" variant="outline" className="h-7 text-xs gap-1 ml-auto" onClick={saveAlertCfg} disabled={alertBusy}>
          {alertBusy ? <Loader2 className="h-3 w-3 animate-spin" /> : <CheckCircle2 className="h-3 w-3" />}
          Save
        </Button>
        <span className="text-[10px] text-muted-foreground hidden sm:block">Telegram fires once/day when inbound purchase MT minus linked passes exceeds threshold.</span>
      </div>

      {expiring.length > 0 && (
        <div className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800 flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          {expiring.length} pass(es) expiring within 15 days: {expiring.map(p => p.pass_no).join(', ')}
        </div>
      )}

      {/* Main passes DataTable */}
      <DataTable<Pass>
        id="royaltypasses.main"
        data={rows}
        columns={PASS_COLUMNS}
        loading={loading}
        rowKey={r => r.id}
        exportFilename="royalty-passes"
        defaultSort={{ key: 'valid_till', direction: 'desc' }}
        emptyMessage="No royalty passes yet."
        rowActions={r => (
          <div className="flex items-center gap-1 justify-end">
            {/* Expand consumption history */}
            <button
              onClick={() => toggleConsumptions(r.id)}
              className="inline-flex items-center justify-center h-7 w-7 rounded-md hover:bg-accent text-muted-foreground"
              title="Show consumption history"
            >
              {loadingCons === r.id
                ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                : expandedId === r.id
                  ? <ChevronDown className="h-3.5 w-3.5" />
                  : <ChevronRight className="h-3.5 w-3.5" />}
            </button>
            {r.status !== 'cancelled' && (
              <button
                onClick={() => { setConsumeFor(r); setConsumeForm({ quantity_mt: '', notes: '' }); }}
                title="Record consumption"
                className="inline-flex h-7 w-7 items-center justify-center rounded-md hover:bg-accent text-blue-700"
              >
                <MinusCircle className="h-3.5 w-3.5" />
              </button>
            )}
            {r.status !== 'cancelled' && (
              <button
                onClick={() => cancel(r)}
                title="Cancel pass"
                className="inline-flex h-7 w-7 items-center justify-center rounded-md hover:bg-accent text-red-600"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        )}
      />

      {/* P3: Expandable consumption sub-table — rendered below the DataTable */}
      {expandedId && expandedPass && (
        <div className="rounded-lg border bg-muted/20 px-4 py-3 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
              Consumption History — {expandedPass.pass_no}
            </span>
            <div className="flex items-center gap-2">
              {consumptions[expandedId]?.length > 0 && (
                <button
                  onClick={() => exportCsv(expandedPass.pass_no, expandedId)}
                  className="inline-flex items-center gap-1 text-[11px] text-blue-600 hover:underline"
                >
                  <Download className="h-3 w-3" /> Export CSV
                </button>
              )}
              <button
                onClick={() => setExpandedId(null)}
                className="inline-flex items-center justify-center h-6 w-6 rounded hover:bg-accent text-muted-foreground"
                title="Close"
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          </div>
          {!consumptions[expandedId] ? (
            <p className="text-xs text-muted-foreground">Loading…</p>
          ) : consumptions[expandedId].length === 0 ? (
            <p className="text-xs text-muted-foreground italic">No consumptions recorded yet.</p>
          ) : (
            <div className="overflow-x-auto rounded border bg-card">
              <table className="w-full text-xs">
                <thead>
                  <tr className="[&>th]:px-2 [&>th]:py-1.5 [&>th]:text-left text-muted-foreground font-medium border-b bg-muted/40">
                    <th>Date</th><th>Token #</th><th>Vehicle</th>
                    <th className="text-right">Authorised MT</th>
                    <th className="text-right">Actual MT</th>
                    <th className="text-right">Variance MT</th>
                    <th className="text-right">Qty MT</th>
                    <th>Notes</th>
                  </tr>
                </thead>
                <tbody>
                  {consumptions[expandedId].map(c => {
                    const variance = Number(c.variance_mt ?? 0);
                    return (
                      <tr key={c.id} className="border-t [&>td]:px-2 [&>td]:py-1.5 align-middle hover:bg-muted/20">
                        <td>{c.consumed_date}</td>
                        <td className="font-mono">{c.token_no ?? '—'}</td>
                        <td>{c.vehicle_no ?? '—'}</td>
                        <td className="text-right">{Number(c.authorized_mt ?? 0).toFixed(3)}</td>
                        <td className="text-right">{Number(c.actual_mt ?? 0).toFixed(3)}</td>
                        <td className={`text-right font-medium ${variance > 0.01 ? 'text-red-600' : variance < -0.01 ? 'text-emerald-600' : 'text-muted-foreground'}`}>
                          {variance > 0 ? '+' : ''}{variance.toFixed(3)}
                        </td>
                        <td className="text-right font-semibold">{Number(c.quantity_mt).toFixed(3)}</td>
                        <td className="text-muted-foreground max-w-[180px] truncate">{c.notes ?? '—'}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* New pass dialog */}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader><DialogTitle className="flex items-center gap-2"><FileText className="h-4 w-4" /> New Royalty / Transit Pass</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div className="grid grid-cols-3 gap-3">
              <div className="space-y-1"><Label className="text-xs">Pass No *</Label><Input value={form.pass_no} onChange={e => setForm(f => ({ ...f, pass_no: e.target.value }))} /></div>
              <div className="space-y-1">
                <Label className="text-xs">Type</Label>
                <Select value={form.pass_type} onValueChange={v => setForm(f => ({ ...f, pass_type: v ?? 'royalty' }))}>
                  <SelectTrigger><span className="capitalize">{form.pass_type.replace('_', ' ')}</span></SelectTrigger>
                  <SelectContent>{PASS_TYPES.map(t => <SelectItem key={t} value={t}><span className="capitalize">{t.replace('_', ' ')}</span></SelectItem>)}</SelectContent>
                </Select>
              </div>
              <div className="space-y-1"><Label className="text-xs">Vehicle No</Label><Input value={form.vehicle_no} onChange={e => setForm(f => ({ ...f, vehicle_no: e.target.value.toUpperCase() }))} /></div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1"><Label className="text-xs">Source (mine/quarry)</Label><Input value={form.source_name} onChange={e => setForm(f => ({ ...f, source_name: e.target.value }))} /></div>
              <div className="space-y-1">
                <Label className="text-xs">Supplier (party)</Label>
                <Select value={form.party_id || '__none__'} onValueChange={v => setForm(f => ({ ...f, party_id: v === '__none__' ? '' : (v ?? '') }))}>
                  <SelectTrigger><span className="truncate text-left flex-1">{form.party_id ? (parties.find(p => p.id === form.party_id)?.name ?? '…') : <span className="text-muted-foreground">Optional…</span>}</span></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__none__"><span className="text-muted-foreground">None</span></SelectItem>
                    {parties.map(p => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label className="text-xs">Mineral / Material</Label>
                <Select value={form.product_id || '__none__'} onValueChange={v => { const pr = products.find(x => x.id === v); setForm(f => ({ ...f, product_id: v === '__none__' ? '' : (v ?? ''), mineral: pr?.name ?? f.mineral })); }}>
                  <SelectTrigger><span className="truncate text-left flex-1">{form.product_id ? (products.find(p => p.id === form.product_id)?.name ?? '…') : (form.mineral || <span className="text-muted-foreground">Select / type below…</span>)}</span></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__none__"><span className="text-muted-foreground">None</span></SelectItem>
                    {products.map(p => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1"><Label className="text-xs">…or free-text mineral</Label><Input value={form.mineral} onChange={e => setForm(f => ({ ...f, mineral: e.target.value }))} placeholder="e.g. Boulder / Gitti" /></div>
            </div>
            <div className="grid grid-cols-3 gap-3">
              <div className="space-y-1"><Label className="text-xs">Authorised Qty (MT) *</Label><Input type="number" step="0.001" value={form.quantity_mt} onChange={e => setForm(f => ({ ...f, quantity_mt: e.target.value }))} /></div>
              <div className="space-y-1"><Label className="text-xs">Rate (₹/MT)</Label><Input type="number" step="0.01" value={form.rate} onChange={e => setForm(f => ({ ...f, rate: e.target.value }))} /></div>
              <div className="space-y-1"><Label className="text-xs">Royalty Amount (₹)</Label><Input type="number" step="0.01" value={form.amount} onChange={e => setForm(f => ({ ...f, amount: e.target.value }))} /></div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1"><Label className="text-xs">Issue Date</Label><Input type="date" value={form.issue_date} onChange={e => setForm(f => ({ ...f, issue_date: e.target.value }))} /></div>
              <div className="space-y-1"><Label className="text-xs">Valid Till</Label><Input type="date" value={form.valid_till} onChange={e => setForm(f => ({ ...f, valid_till: e.target.value }))} /></div>
            </div>
            <div className="space-y-1"><Label className="text-xs">Notes</Label><Input value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} /></div>
            {err && <p className="text-xs text-red-600">{err}</p>}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button onClick={submit} disabled={busy} className="gap-1.5">{busy && <Loader2 className="h-4 w-4 animate-spin" />} Add Pass</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Consume dialog */}
      <Dialog open={!!consumeFor} onOpenChange={o => !o && setConsumeFor(null)}>
        <DialogContent className="max-w-sm">
          <DialogHeader><DialogTitle>Record consumption — {consumeFor?.pass_no}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <p className="text-xs text-muted-foreground">Balance: <b>{consumeFor ? MT(consumeFor.balance_mt) : '—'}</b></p>
            <div className="space-y-1"><Label className="text-xs">Quantity drawn (MT)</Label><Input type="number" step="0.001" value={consumeForm.quantity_mt} onChange={e => setConsumeForm(f => ({ ...f, quantity_mt: e.target.value }))} autoFocus /></div>
            <div className="space-y-1"><Label className="text-xs">Note (e.g. token / vehicle)</Label><Input value={consumeForm.notes} onChange={e => setConsumeForm(f => ({ ...f, notes: e.target.value }))} /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConsumeFor(null)}>Cancel</Button>
            <Button onClick={doConsume}>Record</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* P2: Import CSV dialog */}
      <Dialog open={importOpen} onOpenChange={o => { if (!o) { setImportOpen(false); setImportFile(null); setImportResult(null); } }}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Upload className="h-4 w-4" /> Import Passes from eRavanna / Form-H CSV
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            {/* File picker */}
            <div
              className="border-2 border-dashed rounded-lg p-6 text-center cursor-pointer hover:bg-muted/30 transition-colors"
              onClick={() => fileRef.current?.click()}
              onDragOver={e => e.preventDefault()}
              onDrop={e => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) { setImportFile(f); setImportResult(null); } }}
            >
              <input ref={fileRef} type="file" accept=".csv,.txt" className="hidden"
                onChange={e => { const f = e.target.files?.[0] ?? null; setImportFile(f); setImportResult(null); if (fileRef.current) fileRef.current.value = ''; }} />
              {importFile ? (
                <div className="flex items-center justify-center gap-2 text-sm font-medium">
                  <FileText className="h-5 w-5 text-emerald-600" />
                  {importFile.name}
                  <span className="text-muted-foreground text-xs">({(importFile.size / 1024).toFixed(1)} KB)</span>
                </div>
              ) : (
                <div className="text-muted-foreground text-sm">
                  <Upload className="h-6 w-6 mx-auto mb-1 opacity-40" />
                  Click or drag a CSV file here<br />
                  <span className="text-xs">Supports eRavanna (Karnataka), Form-H (MMDR), HMMS (Telangana)</span>
                </div>
              )}
            </div>

            {/* Options */}
            <div className="flex items-center gap-3 text-sm">
              <label className="flex items-center gap-2 cursor-pointer">
                <input type="checkbox" checked={skipDuplicates} onChange={e => setSkipDuplicates(e.target.checked)} className="rounded" />
                <span>Skip passes already in the system</span>
              </label>
            </div>

            {/* Preview results */}
            {importResult && (
              <div className="space-y-3">
                <div className="grid grid-cols-3 gap-2">
                  {[
                    { label: 'Will import', val: importResult.previewed, color: 'text-emerald-700' },
                    { label: 'Duplicates skipped', val: importResult.skipped, color: 'text-muted-foreground' },
                    { label: 'Rows with errors', val: importResult.error_count, color: importResult.error_count > 0 ? 'text-red-600' : 'text-muted-foreground' },
                  ].map(c => (
                    <div key={c.label} className="rounded border p-2 text-center">
                      <p className={`text-lg font-bold ${c.color}`}>{c.val}</p>
                      <p className="text-[10px] text-muted-foreground">{c.label}</p>
                    </div>
                  ))}
                </div>

                {/* Detected columns */}
                <div>
                  <p className="text-xs font-medium mb-1">Columns detected:</p>
                  <div className="flex flex-wrap gap-1">
                    {Object.entries(importResult.columns_detected).map(([field, col]) => (
                      <span key={field} className="px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700 text-[11px]">
                        {field} ← <span className="font-mono">{col}</span>
                      </span>
                    ))}
                  </div>
                </div>

                {/* Sample rows */}
                {importResult.sample.length > 0 && (
                  <div>
                    <p className="text-xs font-medium mb-1">Preview (first {importResult.sample.length} rows):</p>
                    <div className="rounded border overflow-x-auto">
                      <table className="w-full text-xs">
                        <thead className="bg-muted/40">
                          <tr className="[&>th]:px-2 [&>th]:py-1.5 [&>th]:text-left">
                            <th>Pass No</th><th>Type</th><th>Source</th><th>Mineral</th><th>Qty MT</th><th>Issue Date</th><th>Valid Till</th>
                          </tr>
                        </thead>
                        <tbody>
                          {importResult.sample.map((s, i) => (
                            <tr key={i} className="border-t [&>td]:px-2 [&>td]:py-1">
                              <td className="font-mono font-semibold">{s.pass_no}</td>
                              <td className="capitalize">{s.pass_type.replace('_', ' ')}</td>
                              <td className="max-w-[100px] truncate">{s.source_name ?? '—'}</td>
                              <td>{s.mineral ?? '—'}</td>
                              <td className="text-right">{Number(s.quantity_mt).toFixed(3)}</td>
                              <td>{s.issue_date ?? '—'}</td>
                              <td>{s.valid_till ?? '—'}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}

                {/* Errors */}
                {importResult.errors.length > 0 && (
                  <div>
                    <p className="text-xs font-medium text-red-600 mb-1">Errors ({importResult.error_count}):</p>
                    <div className="max-h-32 overflow-y-auto space-y-0.5">
                      {importResult.errors.map((e, i) => (
                        <p key={i} className="text-xs text-red-600">Row {e.row}: {e.error}</p>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => { setImportOpen(false); setImportFile(null); setImportResult(null); }}>Cancel</Button>
            {!importResult ? (
              <Button onClick={previewImport} disabled={!importFile || importBusy} className="gap-1.5">
                {importBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                Preview
              </Button>
            ) : (
              <Button onClick={doImport} disabled={importBusy || importResult.previewed === 0} className="gap-1.5 bg-emerald-600 hover:bg-emerald-700">
                {importBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                Import {importResult.previewed} pass(es)
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
