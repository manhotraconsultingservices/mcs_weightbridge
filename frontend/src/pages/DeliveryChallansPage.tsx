import { useEffect, useState, useCallback } from 'react';
import api from '@/services/api';
import { toast } from 'sonner';
import { Plus, Trash2, FileText, X, Loader2, ArrowRightLeft, FileBadge } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger } from '@/components/ui/select';
import { PrintButton } from '@/components/PrintButton';
import CreditStatusBanner from '@/components/CreditStatusBanner';

interface Party { id: string; name: string; party_type: string; gstin?: string | null }
interface Product { id: string; name: string; hsn_code?: string | null; unit?: string | null; default_rate?: number | string | null; gst_rate?: number | string | null }
interface Challan {
  id: string; challan_no: string | null; challan_date: string; purpose: string;
  party_id: string | null; party_name: string | null; customer_name: string | null;
  vehicle_no: string | null; transporter_name: string | null; total_amount: number | string;
  status: string; invoice_id: string | null; invoice_no: string | null;
  ewb_no: string | null; ewb_status: string;
}

const INR = (v: number | string) => '₹' + Number(v ?? 0).toLocaleString('en-IN', { minimumFractionDigits: 2 });
const today = () => new Date().toISOString().slice(0, 10);

const PURPOSES = ['supply', 'job_work', 'sample', 'line_sales', 'other'];

const STATUS_PILL: Record<string, string> = {
  open: 'bg-blue-100 text-blue-700',
  invoiced: 'bg-emerald-100 text-emerald-700',
  cancelled: 'bg-gray-200 text-gray-500',
};

interface ItemRow { product_id: string; quantity: string; rate: string }

export default function DeliveryChallansPage() {
  const [rows, setRows] = useState<Challan[]>([]);
  const [parties, setParties] = useState<Party[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  const [form, setForm] = useState({
    challan_date: today(), purpose: 'supply', party_id: '', vehicle_no: '',
    transporter_name: '', driver_name: '', distance_km: '', destination: '', notes: '',
  });
  const [items, setItems] = useState<ItemRow[]>([{ product_id: '', quantity: '', rate: '' }]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get('/delivery-challans', { params: { page_size: 200 } });
      setRows(res.data.items ?? []);
    } catch { /* surfaced inline */ } finally { setLoading(false); }
  }, []);

  useEffect(() => {
    load();
    api.get('/parties').then(r => setParties((Array.isArray(r.data) ? r.data : r.data.items ?? []))).catch(() => {});
    api.get('/products').then(r => setProducts((Array.isArray(r.data) ? r.data : r.data.items ?? []))).catch(() => {});
  }, [load]);

  function resetForm() {
    setForm({ challan_date: today(), purpose: 'supply', party_id: '', vehicle_no: '', transporter_name: '', driver_name: '', distance_km: '', destination: '', notes: '' });
    setItems([{ product_id: '', quantity: '', rate: '' }]);
    setErr('');
  }

  function setItem(i: number, patch: Partial<ItemRow>) {
    setItems(its => its.map((it, idx) => (idx === i ? { ...it, ...patch } : it)));
  }
  function pickProduct(i: number, productId: string) {
    const p = products.find(x => x.id === productId);
    setItem(i, { product_id: productId, rate: p?.default_rate != null ? String(p.default_rate) : '' });
  }

  const challanTotal = items.reduce((s, it) => s + (Number(it.quantity || 0) * Number(it.rate || 0)), 0);

  async function submit() {
    setErr('');
    const validItems = items.filter(it => it.product_id && Number(it.quantity) > 0);
    if (validItems.length === 0) { setErr('Add at least one line item with a quantity.'); return; }
    setBusy(true);
    try {
      await api.post('/delivery-challans', {
        challan_date: form.challan_date,
        purpose: form.purpose,
        party_id: form.party_id || undefined,
        vehicle_no: form.vehicle_no || undefined,
        transporter_name: form.transporter_name || undefined,
        driver_name: form.driver_name || undefined,
        distance_km: form.distance_km ? Number(form.distance_km) : undefined,
        destination: form.destination || undefined,
        notes: form.notes || undefined,
        items: validItems.map((it, idx) => {
          const p = products.find(x => x.id === it.product_id);
          return {
            product_id: it.product_id,
            hsn_code: p?.hsn_code ?? undefined,
            quantity: Number(it.quantity),
            unit: p?.unit ?? 'MT',
            rate: Number(it.rate || 0),
            gst_rate: Number(p?.gst_rate ?? 0),
            sort_order: idx,
          };
        }),
      });
      toast.success('Delivery challan created');
      setOpen(false); resetForm(); load();
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setErr(msg || 'Could not create challan');
    } finally { setBusy(false); }
  }

  async function convert(c: Challan) {
    if (!confirm(`Convert challan ${c.challan_no} to a draft tax invoice?`)) return;
    try {
      await api.post(`/delivery-challans/${c.id}/convert-to-invoice`, {});
      toast.success('Draft invoice created from challan');
      load();
    } catch (e: unknown) {
      toast.error((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Convert failed');
    }
  }

  async function genEwb(c: Challan) {
    const km = prompt('Transport distance in km (0 = let NIC auto-compute):', '0');
    if (km === null) return;
    try {
      await api.post(`/delivery-challans/${c.id}/generate-ewb`, { distance_km: Number(km) || 0 });
      toast.success('E-Way Bill generated');
      load();
    } catch (e: unknown) {
      toast.error((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'EWB generation failed');
    }
  }

  async function cancel(c: Challan) {
    if (!confirm(`Cancel challan ${c.challan_no}? This cannot be undone.`)) return;
    try {
      await api.post(`/delivery-challans/${c.id}/cancel`, {});
      toast.success('Challan cancelled');
      load();
    } catch (e: unknown) {
      toast.error((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Cancel failed');
    }
  }

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">Delivery Challans</h1>
          <p className="text-xs text-muted-foreground">Dispatch goods on a challan now, bill later. Converts to a GST tax invoice.</p>
        </div>
        <Button onClick={() => { resetForm(); setOpen(true); }} className="gap-1.5">
          <Plus className="h-4 w-4" /> New Challan
        </Button>
      </div>

      <div className="rounded-lg border overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-muted/40 text-xs">
            <tr className="[&>th]:px-3 [&>th]:py-2 [&>th]:text-left">
              <th>Challan No</th><th>Date</th><th>Party</th><th>Vehicle</th>
              <th className="text-right">Value</th><th>E-Way Bill</th><th>Status</th><th>Invoice</th><th></th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={9} className="px-3 py-6 text-center text-muted-foreground"><Loader2 className="inline h-4 w-4 animate-spin" /> Loading…</td></tr>}
            {!loading && rows.length === 0 && <tr><td colSpan={9} className="px-3 py-6 text-center text-muted-foreground">No delivery challans yet.</td></tr>}
            {rows.map(c => (
              <tr key={c.id} className="border-t [&>td]:px-3 [&>td]:py-2">
                <td className="font-mono font-semibold">{c.challan_no ?? '—'}</td>
                <td>{new Date(c.challan_date).toLocaleDateString('en-IN')}</td>
                <td className="max-w-[180px] truncate">{c.party_name ?? c.customer_name ?? 'Cash'}</td>
                <td className="font-mono text-xs">{c.vehicle_no ?? '—'}</td>
                <td className="text-right">{INR(c.total_amount)}</td>
                <td>{c.ewb_no ? <span className="font-mono text-xs text-emerald-700">{c.ewb_no}</span> : <span className="text-muted-foreground text-xs">—</span>}</td>
                <td><span className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${STATUS_PILL[c.status] ?? ''}`}>{c.status}</span></td>
                <td className="text-xs">{c.invoice_no ? c.invoice_no : (c.invoice_id ? 'draft' : '—')}</td>
                <td>
                  <div className="flex items-center gap-1 justify-end">
                    <PrintButton a4Url={`/api/v1/delivery-challans/${c.id}/pdf`} url={`/api/v1/delivery-challans/${c.id}/pdf`} iconOnly />
                    {c.status === 'open' && !c.ewb_no && (
                      <button onClick={() => genEwb(c)} title="Generate E-Way Bill"
                        className="inline-flex h-7 w-7 items-center justify-center rounded-md hover:bg-accent text-blue-700">
                        <FileBadge className="h-3.5 w-3.5" />
                      </button>
                    )}
                    {c.status === 'open' && (
                      <>
                        <button onClick={() => convert(c)} title="Convert to tax invoice"
                          className="inline-flex h-7 w-7 items-center justify-center rounded-md hover:bg-accent text-emerald-700">
                          <ArrowRightLeft className="h-3.5 w-3.5" />
                        </button>
                        <button onClick={() => cancel(c)} title="Cancel challan"
                          className="inline-flex h-7 w-7 items-center justify-center rounded-md hover:bg-accent text-red-600">
                          <X className="h-3.5 w-3.5" />
                        </button>
                      </>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Create dialog */}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader><DialogTitle className="flex items-center gap-2"><FileText className="h-4 w-4" /> New Delivery Challan</DialogTitle></DialogHeader>

          <div className="space-y-3">
            <div className="grid grid-cols-3 gap-3">
              <div className="space-y-1">
                <Label className="text-xs">Date</Label>
                <Input type="date" value={form.challan_date} onChange={e => setForm(f => ({ ...f, challan_date: e.target.value }))} />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Purpose</Label>
                <Select value={form.purpose} onValueChange={v => setForm(f => ({ ...f, purpose: v ?? 'supply' }))}>
                  <SelectTrigger><span className="capitalize">{form.purpose.replace('_', ' ')}</span></SelectTrigger>
                  <SelectContent>{PURPOSES.map(p => <SelectItem key={p} value={p}><span className="capitalize">{p.replace('_', ' ')}</span></SelectItem>)}</SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Vehicle No</Label>
                <Input value={form.vehicle_no} onChange={e => setForm(f => ({ ...f, vehicle_no: e.target.value.toUpperCase() }))} placeholder="MH12AB1234" />
              </div>
            </div>

            <div className="space-y-1">
              <Label className="text-xs">Consignee (Party)</Label>
              <Select value={form.party_id || undefined} onValueChange={v => setForm(f => ({ ...f, party_id: v ?? '' }))}>
                <SelectTrigger>
                  <span className="truncate text-left flex-1">
                    {form.party_id ? (parties.find(p => p.id === form.party_id)?.name ?? '…') : <span className="text-muted-foreground">Select party (or leave blank for Cash)…</span>}
                  </span>
                </SelectTrigger>
                <SelectContent>{parties.map(p => <SelectItem key={p.id} value={p.id}>{p.name}{p.gstin && <span className="text-muted-foreground text-xs ml-2">{p.gstin}</span>}</SelectItem>)}</SelectContent>
              </Select>
              {form.party_id && <CreditStatusBanner partyId={form.party_id} className="mt-1.5" />}
            </div>

            <div className="grid grid-cols-3 gap-3">
              <div className="space-y-1"><Label className="text-xs">Transporter</Label><Input value={form.transporter_name} onChange={e => setForm(f => ({ ...f, transporter_name: e.target.value }))} /></div>
              <div className="space-y-1"><Label className="text-xs">Driver</Label><Input value={form.driver_name} onChange={e => setForm(f => ({ ...f, driver_name: e.target.value }))} /></div>
              <div className="space-y-1"><Label className="text-xs">Distance (km)</Label><Input type="number" value={form.distance_km} onChange={e => setForm(f => ({ ...f, distance_km: e.target.value }))} /></div>
            </div>
            <div className="space-y-1"><Label className="text-xs">Destination</Label><Input value={form.destination} onChange={e => setForm(f => ({ ...f, destination: e.target.value }))} /></div>

            {/* Line items */}
            <div className="space-y-1">
              <Label className="text-xs">Items</Label>
              <div className="space-y-1.5">
                {items.map((it, i) => (
                  <div key={i} className="flex gap-1.5 items-center">
                    <Select value={it.product_id || undefined} onValueChange={v => pickProduct(i, v ?? '')}>
                      <SelectTrigger className="flex-1 h-8 text-xs"><span className="truncate text-left flex-1">{it.product_id ? (products.find(p => p.id === it.product_id)?.name ?? '…') : <span className="text-muted-foreground">Material…</span>}</span></SelectTrigger>
                      <SelectContent>{products.map(p => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}</SelectContent>
                    </Select>
                    <Input className="w-24 h-8 text-xs" type="number" step="0.001" placeholder="Qty" value={it.quantity} onChange={e => setItem(i, { quantity: e.target.value })} />
                    <Input className="w-24 h-8 text-xs" type="number" step="0.01" placeholder="Rate" value={it.rate} onChange={e => setItem(i, { rate: e.target.value })} />
                    <span className="w-24 text-right text-xs text-muted-foreground">{INR(Number(it.quantity || 0) * Number(it.rate || 0))}</span>
                    <button onClick={() => setItems(its => its.length > 1 ? its.filter((_, idx) => idx !== i) : its)} className="text-red-500 shrink-0"><Trash2 className="h-3.5 w-3.5" /></button>
                  </div>
                ))}
              </div>
              <Button type="button" size="sm" variant="outline" className="mt-1 h-7 text-xs gap-1" onClick={() => setItems(its => [...its, { product_id: '', quantity: '', rate: '' }])}>
                <Plus className="h-3 w-3" /> Add item
              </Button>
            </div>

            <div className="space-y-1"><Label className="text-xs">Notes</Label><Input value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} /></div>

            <div className="flex justify-between items-center pt-1 border-t">
              <span className="text-xs text-muted-foreground">Tax is applied when converted to an invoice.</span>
              <span className="font-bold">Total Value: {INR(challanTotal)}</span>
            </div>
            {err && <p className="text-xs text-red-600">{err}</p>}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button onClick={submit} disabled={busy} className="gap-1.5">{busy && <Loader2 className="h-4 w-4 animate-spin" />} Create Challan</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
