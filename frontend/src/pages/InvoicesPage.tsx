import { useEffect, useState, useCallback, useMemo } from 'react';
import { toast } from 'sonner';
import { ChevronUp, ChevronDown, ChevronsUpDown } from 'lucide-react';
import { Plus, Search, FileText, Loader2, Download, CheckCircle, XCircle, Banknote, Send, CheckCircle2, Ticket, Lock, Pencil, RefreshCw, ShieldCheck, ShieldAlert, ShieldX, RotateCcw, GitFork, History } from 'lucide-react';
import { TokenDetailModal } from '@/components/TokenDetailModal';
import { PrintButton } from '@/components/PrintButton';
import { InvoiceRevisionDialog } from '@/components/InvoiceRevisionDialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import api from '@/services/api';
import { useUsbGuard } from '@/hooks/useUsbGuard';
import { useAuth } from '@/hooks/useAuth';
import type { Invoice, InvoiceListResponse, Party, Product, Token } from '@/types';

const INR = (v: number) => '₹' + v.toLocaleString('en-IN', { minimumFractionDigits: 2 });

// ── Invoice Pipeline visual (Draft → Final → Paid) ────────────────────────────
function InvoicePipeline({ status, paymentStatus }: { status: string; paymentStatus: string }) {
  if (status === 'cancelled') {
    return (
      <span className="text-[10px] rounded-full px-2 py-0.5 font-medium bg-red-100 text-red-600">
        Cancelled
      </span>
    );
  }
  const isFinal = status === 'final';
  const isPaid = paymentStatus === 'paid';
  const isPartial = paymentStatus === 'partial';

  type Step = { label: string; done: boolean; active: boolean; partial?: boolean };
  const steps: Step[] = [
    { label: 'Draft',  done: isFinal || isPaid,     active: !isFinal && !isPaid },
    { label: 'Final',  done: isFinal && (isPaid || isPartial), active: isFinal && !isPaid && !isPartial },
    { label: 'Paid',   done: isPaid,                active: isFinal && (isPaid || isPartial), partial: isPartial && !isPaid },
  ];

  return (
    <div className="inline-flex items-center gap-0.5">
      {steps.map((step, i) => (
        <div key={step.label} className="inline-flex items-center">
          {i > 0 && (
            <div className={`w-3 h-px mx-0.5 ${step.done || steps[i-1].done ? 'bg-green-400' : 'bg-muted-foreground/25'}`} />
          )}
          <div className="flex flex-col items-center gap-0.5">
            <div className={`h-2 w-2 rounded-full ${
              step.done
                ? 'bg-green-500'
                : step.partial
                  ? 'bg-orange-400'
                  : step.active
                    ? 'bg-blue-500 ring-2 ring-blue-200'
                    : 'bg-muted-foreground/20'
            }`} />
            <span className={`text-[9px] leading-none ${
              step.done ? 'text-green-600 font-medium'
              : step.partial ? 'text-orange-500 font-medium'
              : step.active ? 'text-blue-600 font-semibold'
              : 'text-muted-foreground/50'
            }`}>
              {step.partial ? 'Part' : step.label}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}

// ── eInvoice IRN Status Badge ─────────────────────────────────────────────────
function EInvoiceBadge({ inv }: { inv: Invoice }) {
  if (inv.status !== 'final' || inv.einvoice_status === 'none') return null;
  const s = inv.einvoice_status;
  if (s === 'success') {
    return (
      <span className="inline-flex items-center gap-0.5 text-[9px] font-medium text-green-700 bg-green-50 rounded px-1.5 py-0.5" title={`IRN: ${inv.irn}\nAck: ${inv.irn_ack_no}`}>
        <ShieldCheck className="h-2.5 w-2.5" /> IRN
      </span>
    );
  }
  if (s === 'failed') {
    return (
      <span className="inline-flex items-center gap-0.5 text-[9px] font-medium text-red-700 bg-red-50 rounded px-1.5 py-0.5" title={inv.einvoice_error || 'IRN generation failed'}>
        <ShieldAlert className="h-2.5 w-2.5" /> IRN Failed
      </span>
    );
  }
  if (s === 'cancelled') {
    return (
      <span className="inline-flex items-center gap-0.5 text-[9px] font-medium text-gray-600 bg-gray-100 rounded px-1.5 py-0.5" title="IRN cancelled">
        <ShieldX className="h-2.5 w-2.5" /> IRN Cancelled
      </span>
    );
  }
  return null;
}

// ------------------------------------------------------------------ //
// Line item row in the create form
// ------------------------------------------------------------------ //
interface LineItem {
  product_id: string;
  description: string;
  hsn_code: string;
  quantity: string;
  unit: string;
  rate: string;
  gst_rate: string;
}

const emptyLine = (): LineItem => ({
  product_id: '', description: '', hsn_code: '', quantity: '1', unit: 'MT', rate: '', gst_rate: '5',
});

// ------------------------------------------------------------------ //
// Create Invoice Dialog
// ------------------------------------------------------------------ //
interface CreateProps {
  open: boolean;
  invoiceType: 'sale' | 'purchase';
  onClose: () => void;
  onCreated: (inv: Invoice) => void;
}

function CreateInvoiceDialog({ open, invoiceType, onClose, onCreated }: CreateProps) {
  const { authorized: usbAuthorized } = useUsbGuard();
  const [parties, setParties] = useState<Party[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [completedTokens, setCompletedTokens] = useState<Token[]>([]);
  const [walkIn, setWalkIn] = useState(false);
  const [customerName, setCustomerName] = useState('');
  const [form, setForm] = useState({
    party_id: '', tax_type: 'gst', token_id: '',
    vehicle_no: '', transporter_name: '', eway_bill_no: '',
    discount_type: '', discount_value: '0', freight: '0', tcs_rate: '0',
    payment_mode: '', notes: '', invoice_date: new Date().toISOString().split('T')[0],
  });
  const [lines, setLines] = useState<LineItem[]>([emptyLine()]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open) return;
    const today = new Date().toISOString().split('T')[0];
    setForm(f => ({ ...f, invoice_date: today }));
    setLines([emptyLine()]);
    setWalkIn(false);
    setCustomerName('');
    setError('');
    Promise.all([
      api.get<Party[]>('/api/v1/parties'),
      api.get<Product[]>('/api/v1/products'),
      api.get<{ items: Token[] }>('/api/v1/tokens?status=COMPLETED&page_size=100'),
    ]).then(([p, pr, t]) => {
      const pData = p.data as Party[] | { items: Party[] };
      setParties(Array.isArray(pData) ? pData : (pData.items ?? []));
      const prData = pr.data as Product[] | { items: Product[] };
      setProducts(Array.isArray(prData) ? prData : (prData.items ?? []));
      setCompletedTokens(t.data.items ?? []);
    }).catch(() => {});
  }, [open]);

  // When token is selected, populate line items from it
  function handleTokenSelect(tokenId: string) {
    setForm(f => ({ ...f, token_id: tokenId }));
    if (!tokenId) return;
    const token = completedTokens.find(t => t.id === tokenId);
    if (!token) return;
    if (token.party) setForm(f => ({ ...f, party_id: token.party?.id ?? f.party_id }));
    if (token.product) {
      setLines([{
        product_id: token.product.id,
        description: token.product.name,
        hsn_code: '',
        quantity: token.net_weight != null ? String(token.net_weight) : '1',
        unit: token.product.unit,
        rate: '',
        gst_rate: '5',
      }]);
    }
    setForm(f => ({
      ...f,
      token_id: tokenId,
      vehicle_no: token.vehicle_no,
      party_id: token.party?.id ?? f.party_id,
    }));
  }

  // When product is selected on a line, auto-fill fields
  function handleProductSelect(idx: number, productId: string) {
    const p = products.find(x => x.id === productId);
    if (!p) return;
    updateLine(idx, {
      product_id: productId,
      hsn_code: p.hsn_code,
      unit: p.unit,
      rate: String(p.default_rate),
      gst_rate: String(p.gst_rate),
    });
  }

  function updateLine(idx: number, patch: Partial<LineItem>) {
    setLines(prev => prev.map((l, i) => i === idx ? { ...l, ...patch } : l));
  }

  function lineTotal(l: LineItem) {
    const qty = parseFloat(l.quantity) || 0;
    const rate = parseFloat(l.rate) || 0;
    const gst = parseFloat(l.gst_rate) || 0;
    const amt = qty * rate;
    return amt + (amt * gst / 100);
  }

  const grandEstimate = lines.reduce((s, l) => s + lineTotal(l), 0);

  async function handleSubmit() {
    if (!walkIn && !form.party_id) { setError('Select a party or use Walk-in mode'); return; }
    if (walkIn && !customerName.trim()) { setError('Enter customer name for walk-in invoice'); return; }
    if (lines.some(l => !l.product_id || !l.quantity || !l.rate)) {
      setError('Fill all line item fields'); return;
    }
    setSaving(true); setError('');
    try {
      const { data } = await api.post<Invoice>('/api/v1/invoices', {
        invoice_type: invoiceType,
        tax_type: form.tax_type,
        invoice_date: form.invoice_date,
        party_id: walkIn ? undefined : form.party_id,
        customer_name: walkIn ? customerName.trim() : undefined,
        token_id: form.token_id || undefined,
        vehicle_no: form.vehicle_no || undefined,
        transporter_name: form.transporter_name || undefined,
        eway_bill_no: form.eway_bill_no || undefined,
        discount_type: form.discount_type || undefined,
        discount_value: parseFloat(form.discount_value) || 0,
        freight: parseFloat(form.freight) || 0,
        tcs_rate: parseFloat(form.tcs_rate) || 0,
        payment_mode: form.payment_mode || undefined,
        notes: form.notes || undefined,
        items: lines.map((l, i) => ({
          product_id: l.product_id,
          description: l.description || undefined,
          hsn_code: l.hsn_code || undefined,
          quantity: parseFloat(l.quantity),
          unit: l.unit,
          rate: parseFloat(l.rate),
          gst_rate: parseFloat(l.gst_rate) || 0,
          sort_order: i,
        })),
      });
      onCreated(data);
      onClose();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Failed to create invoice');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={v => !v && onClose()}>
      <DialogContent className="sm:max-w-4xl max-h-[92vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>New {invoiceType === 'sale' ? 'Sales' : 'Purchase'} Invoice</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          {error && <p className="rounded bg-destructive/10 p-2 text-sm text-destructive">{error}</p>}

          <div className="grid grid-cols-3 gap-3">
            <div className="space-y-1">
              <Label>Invoice Date *</Label>
              <Input type="date" value={form.invoice_date}
                onChange={e => setForm(f => ({ ...f, invoice_date: e.target.value }))} />
            </div>
            <div className="space-y-1">
              <Label>Tax Type</Label>
              <Select value={form.tax_type} onValueChange={v => setForm(f => ({ ...f, tax_type: v ?? 'gst' }))}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="gst">GST Invoice</SelectItem>
                  {usbAuthorized && <SelectItem value="non_gst">Non-GST / Bill of Supply</SelectItem>}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label>Link to Token (optional)</Label>
              <Select value={form.token_id || undefined} onValueChange={(v) => handleTokenSelect(v ?? '')}>
                <SelectTrigger>
                  <span className="truncate text-left flex-1">
                    {form.token_id
                      ? (() => { const t = completedTokens.find(x => x.id === form.token_id); return t ? `#${t.token_no} — ${t.vehicle_no}${t.net_weight != null ? ` (${t.net_weight} kg)` : ''}` : 'Token'; })()
                      : <span className="text-muted-foreground">Select completed token…</span>}
                  </span>
                </SelectTrigger>
                <SelectContent>
                  {completedTokens.map(t => (
                    <SelectItem key={t.id} value={t.id}>
                      #{t.token_no} — {t.vehicle_no} {t.net_weight != null ? `(${t.net_weight} kg)` : ''}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <div className="flex items-center justify-between">
                <Label>{walkIn ? 'Customer Name *' : 'Party *'}</Label>
                <button
                  type="button"
                  className="text-xs text-primary underline-offset-2 hover:underline"
                  onClick={() => { setWalkIn(w => !w); setCustomerName(''); setForm(f => ({ ...f, party_id: '' })); }}
                >
                  {walkIn ? '← Select from master' : 'Walk-in / B2C →'}
                </button>
              </div>
              {walkIn ? (
                <Input
                  placeholder="Enter customer name…"
                  value={customerName}
                  onChange={e => setCustomerName(e.target.value)}
                  autoFocus
                />
              ) : (
                <Select value={form.party_id || undefined} onValueChange={v => setForm(f => ({ ...f, party_id: v ?? '' }))}>
                  <SelectTrigger>
                    <span className="truncate text-left flex-1">
                      {form.party_id
                        ? (parties.find(p => p.id === form.party_id)?.name ?? '…')
                        : <span className="text-muted-foreground">Select party…</span>}
                    </span>
                  </SelectTrigger>
                  <SelectContent>
                    {parties.map(p => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}
                  </SelectContent>
                </Select>
              )}
            </div>
            <div className="space-y-1">
              <Label>Vehicle No</Label>
              <Input value={form.vehicle_no}
                onChange={e => setForm(f => ({ ...f, vehicle_no: e.target.value.toUpperCase() }))} />
            </div>
          </div>

          {/* Line Items */}
          <div className="border-t pt-3">
            <div className="flex items-center justify-between mb-2">
              <p className="text-sm font-semibold">Line Items</p>
              <Button size="sm" variant="outline" onClick={() => setLines(l => [...l, emptyLine()])}>
                <Plus className="h-3 w-3 mr-1" /> Add Row
              </Button>
            </div>
            <div className="space-y-2">
              {lines.map((line, idx) => (
                <div key={idx} className="grid gap-2 items-end"
                  style={{ gridTemplateColumns: 'minmax(0,2fr) minmax(80px,1.1fr) minmax(100px,1.4fr) minmax(70px,0.9fr) minmax(90px,1fr) 36px' }}>
                  <div className="space-y-1">
                    {idx === 0 && <Label className="text-sm font-medium">Product</Label>}
                    <Select value={line.product_id || undefined}
                      onValueChange={v => handleProductSelect(idx, v ?? '')}>
                      <SelectTrigger className="h-10 text-sm">
                        <span className="truncate text-left flex-1">
                          {line.product_id
                            ? (products.find(p => p.id === line.product_id)?.name ?? '…')
                            : <span className="text-muted-foreground">Select product…</span>}
                        </span>
                      </SelectTrigger>
                      <SelectContent>
                        {products.map(p => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1 min-w-0">
                    {idx === 0 && <Label className="text-sm font-medium">Qty</Label>}
                    <Input className="h-10 text-sm font-semibold text-center w-full" type="number" min="0" step="0.001"
                      value={line.quantity} onChange={e => updateLine(idx, { quantity: e.target.value })} />
                  </div>
                  <div className="space-y-1 min-w-0">
                    {idx === 0 && <Label className="text-sm font-medium">Rate (₹)</Label>}
                    <Input className="h-10 text-sm font-semibold w-full" type="number" min="0" step="0.01"
                      value={line.rate} onChange={e => updateLine(idx, { rate: e.target.value })} />
                  </div>
                  <div className="space-y-1 min-w-0">
                    {idx === 0 && <Label className="text-sm font-medium">GST%</Label>}
                    <Select value={line.gst_rate} onValueChange={v => updateLine(idx, { gst_rate: v ?? '0' })}>
                      <SelectTrigger className="h-10 text-sm w-full"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {['0', '5', '12', '18', '28'].map(r => <SelectItem key={r} value={r}>{r}%</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="text-right space-y-1">
                    {idx === 0 && <Label className="text-sm font-medium">Total</Label>}
                    <p className="text-sm font-semibold font-mono h-10 flex items-center justify-end pr-1">
                      {INR(lineTotal(line))}
                    </p>
                  </div>
                  <Button size="icon" variant="ghost" className="h-10 w-10 text-muted-foreground"
                    onClick={() => setLines(l => l.filter((_, i) => i !== idx))}
                    disabled={lines.length === 1}>
                    <XCircle className="h-4 w-4" />
                  </Button>
                </div>
              ))}
            </div>
            <div className="text-right mt-2 text-sm font-semibold">
              Est. Total: {INR(grandEstimate)}
            </div>
          </div>

          {/* Other fields */}
          <div className="grid grid-cols-3 gap-3 border-t pt-3">
            <div className="space-y-1">
              <Label>Discount Type</Label>
              <Select value={form.discount_type || 'none'}
                onValueChange={v => setForm(f => ({ ...f, discount_type: (v === 'none' || !v) ? '' : v }))}>
                <SelectTrigger><SelectValue placeholder="No discount" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">None</SelectItem>
                  <SelectItem value="percentage">Percentage (%)</SelectItem>
                  <SelectItem value="flat">Flat Amount (₹)</SelectItem>
                </SelectContent>
              </Select>
            </div>
            {form.discount_type && (
              <div className="space-y-1">
                <Label>Discount Value</Label>
                <Input type="number" min="0" value={form.discount_value}
                  onChange={e => setForm(f => ({ ...f, discount_value: e.target.value }))} />
              </div>
            )}
            <div className="space-y-1">
              <Label>Freight (₹)</Label>
              <Input type="number" min="0" value={form.freight}
                onChange={e => setForm(f => ({ ...f, freight: e.target.value }))} />
            </div>
            <div className="space-y-1">
              <Label>Payment Mode</Label>
              <Select value={form.payment_mode || 'credit'}
                onValueChange={v => setForm(f => ({ ...f, payment_mode: v ?? '' }))}>
                <SelectTrigger><SelectValue placeholder="Select…" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="credit">Credit</SelectItem>
                  <SelectItem value="cash">Cash</SelectItem>
                  <SelectItem value="upi">UPI</SelectItem>
                  <SelectItem value="cheque">Cheque</SelectItem>
                  <SelectItem value="bank_transfer">Bank Transfer</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </div>

        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={handleSubmit} disabled={saving}>
            {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Create Invoice
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ------------------------------------------------------------------ //
// Edit Draft Invoice Dialog
// ------------------------------------------------------------------ //
interface EditProps {
  open: boolean;
  invoice: Invoice | null;
  onClose: () => void;
  onSaved: (inv: Invoice) => void;
}

function EditInvoiceDialog({ open, invoice, onClose, onSaved }: EditProps) {
  const { authorized: usbAuthorized } = useUsbGuard();
  const [parties, setParties] = useState<Party[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [walkIn, setWalkIn] = useState(false);
  const [customerName, setCustomerName] = useState('');
  const [form, setForm] = useState({
    party_id: '', tax_type: 'gst',
    vehicle_no: '', transporter_name: '', eway_bill_no: '',
    discount_type: '', discount_value: '0', freight: '0', tcs_rate: '0',
    payment_mode: '', notes: '', invoice_date: '',
  });
  const [lines, setLines] = useState<LineItem[]>([emptyLine()]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  // Pre-populate from invoice when dialog opens
  useEffect(() => {
    if (!open || !invoice) return;
    setError('');
    const isWalkIn = !invoice.party && !!invoice.customer_name;
    setWalkIn(isWalkIn);
    setCustomerName(invoice.customer_name ?? '');
    setForm({
      party_id: invoice.party?.id ?? '',
      tax_type: invoice.tax_type ?? 'gst',
      vehicle_no: invoice.vehicle_no ?? '',
      transporter_name: invoice.transporter_name ?? '',
      eway_bill_no: invoice.eway_bill_no ?? '',
      discount_type: invoice.discount_type ?? '',
      discount_value: String(invoice.discount_value ?? 0),
      freight: String(invoice.freight ?? 0),
      tcs_rate: String(invoice.tcs_rate ?? 0),
      payment_mode: invoice.payment_mode ?? '',
      notes: invoice.notes ?? '',
      invoice_date: invoice.invoice_date ?? new Date().toISOString().split('T')[0],
    });
    setLines(
      invoice.items.length > 0
        ? invoice.items.map(item => ({
            product_id: item.product_id,
            description: item.description ?? '',
            hsn_code: item.hsn_code ?? '',
            quantity: String(item.quantity),
            unit: item.unit,
            rate: String(item.rate),
            gst_rate: String(item.gst_rate),
          }))
        : [emptyLine()]
    );
    Promise.all([
      api.get<Party[]>('/api/v1/parties'),
      api.get<Product[]>('/api/v1/products'),
    ]).then(([p, pr]) => {
      const pData = p.data as Party[] | { items: Party[] };
      setParties(Array.isArray(pData) ? pData : (pData.items ?? []));
      const prData = pr.data as Product[] | { items: Product[] };
      setProducts(Array.isArray(prData) ? prData : (prData.items ?? []));
    }).catch(() => {});
  }, [open, invoice]);

  function handleProductSelect(idx: number, productId: string) {
    const p = products.find(x => x.id === productId);
    if (!p) return;
    updateLine(idx, { product_id: productId, hsn_code: p.hsn_code, unit: p.unit, rate: String(p.default_rate), gst_rate: String(p.gst_rate) });
  }

  function updateLine(idx: number, patch: Partial<LineItem>) {
    setLines(prev => prev.map((l, i) => i === idx ? { ...l, ...patch } : l));
  }

  function lineTotal(l: LineItem) {
    const qty = parseFloat(l.quantity) || 0;
    const rate = parseFloat(l.rate) || 0;
    const gst = parseFloat(l.gst_rate) || 0;
    const amt = qty * rate;
    return amt + (amt * gst / 100);
  }

  const grandEstimate = lines.reduce((s, l) => s + lineTotal(l), 0);

  async function handleSave() {
    if (!walkIn && !form.party_id) { setError('Select a party or use Walk-in mode'); return; }
    if (walkIn && !customerName.trim()) { setError('Enter customer name for walk-in invoice'); return; }
    if (lines.some(l => !l.product_id || !l.quantity || !l.rate)) {
      setError('Fill all line item fields'); return;
    }
    setSaving(true); setError('');
    try {
      const { data } = await api.put<Invoice>(`/api/v1/invoices/${invoice!.id}`, {
        party_id: walkIn ? null : form.party_id || null,
        customer_name: walkIn ? customerName.trim() : null,
        invoice_date: form.invoice_date,
        tax_type: form.tax_type,
        vehicle_no: form.vehicle_no || null,
        transporter_name: form.transporter_name || null,
        eway_bill_no: form.eway_bill_no || null,
        discount_type: form.discount_type || null,
        discount_value: parseFloat(form.discount_value) || 0,
        freight: parseFloat(form.freight) || 0,
        tcs_rate: parseFloat(form.tcs_rate) || 0,
        payment_mode: form.payment_mode || null,
        notes: form.notes || null,
        items: lines.map((l, i) => ({
          product_id: l.product_id,
          description: l.description || null,
          hsn_code: l.hsn_code || null,
          quantity: parseFloat(l.quantity),
          unit: l.unit,
          rate: parseFloat(l.rate),
          gst_rate: parseFloat(l.gst_rate) || 0,
          sort_order: i,
        })),
      });
      onSaved(data);
      onClose();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Failed to save invoice');
    } finally {
      setSaving(false);
    }
  }

  if (!invoice) return null;

  return (
    <Dialog open={open} onOpenChange={v => !v && onClose()}>
      <DialogContent className="sm:max-w-4xl max-h-[92vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Pencil className="h-4 w-4 text-primary" />
            Edit Draft {invoice.invoice_type === 'sale' ? 'Sales' : 'Purchase'} Invoice
            {invoice.invoice_no && <span className="text-sm font-mono text-muted-foreground ml-1">{invoice.invoice_no}</span>}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          {error && <p className="rounded bg-destructive/10 p-2 text-sm text-destructive">{error}</p>}

          <div className="grid grid-cols-3 gap-3">
            <div className="space-y-1">
              <Label>Invoice Date *</Label>
              <Input type="date" value={form.invoice_date}
                onChange={e => setForm(f => ({ ...f, invoice_date: e.target.value }))} />
            </div>
            <div className="space-y-1">
              <Label>Tax Type</Label>
              <Select value={form.tax_type} onValueChange={v => setForm(f => ({ ...f, tax_type: v ?? 'gst' }))}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="gst">GST Invoice</SelectItem>
                  {usbAuthorized && <SelectItem value="non_gst">Non-GST / Bill of Supply</SelectItem>}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label>Linked Token</Label>
              <Input
                value={invoice.token_no ? `#${invoice.token_no} — ${invoice.vehicle_no ?? ''}` : 'None'}
                readOnly
                className="bg-muted text-muted-foreground"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <div className="flex items-center justify-between">
                <Label>{walkIn ? 'Customer Name *' : 'Party *'}</Label>
                <button
                  type="button"
                  className="text-xs text-primary underline-offset-2 hover:underline"
                  onClick={() => { setWalkIn(w => !w); setCustomerName(''); setForm(f => ({ ...f, party_id: '' })); }}
                >
                  {walkIn ? '← Select from master' : 'Walk-in / B2C →'}
                </button>
              </div>
              {walkIn ? (
                <Input
                  placeholder="Enter customer name…"
                  value={customerName}
                  onChange={e => setCustomerName(e.target.value)}
                  autoFocus
                />
              ) : (
                <Select value={form.party_id || undefined} onValueChange={v => setForm(f => ({ ...f, party_id: v ?? '' }))}>
                  <SelectTrigger>
                    <span className="truncate text-left flex-1">
                      {form.party_id
                        ? (parties.find(p => p.id === form.party_id)?.name ?? '…')
                        : <span className="text-muted-foreground">Select party…</span>}
                    </span>
                  </SelectTrigger>
                  <SelectContent>
                    {parties.map(p => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}
                  </SelectContent>
                </Select>
              )}
            </div>
            <div className="space-y-1">
              <Label>Vehicle No</Label>
              <Input value={form.vehicle_no}
                onChange={e => setForm(f => ({ ...f, vehicle_no: e.target.value.toUpperCase() }))} />
            </div>
          </div>

          {/* Line Items */}
          <div className="border-t pt-3">
            <div className="flex items-center justify-between mb-2">
              <p className="text-sm font-semibold">Line Items</p>
              <Button size="sm" variant="outline" onClick={() => setLines(l => [...l, emptyLine()])}>
                <Plus className="h-3 w-3 mr-1" /> Add Row
              </Button>
            </div>
            <div className="space-y-2">
              {lines.map((line, idx) => (
                <div key={idx} className="grid gap-2 items-end"
                  style={{ gridTemplateColumns: 'minmax(0,2fr) minmax(80px,1.1fr) minmax(100px,1.4fr) minmax(70px,0.9fr) minmax(90px,1fr) 36px' }}>
                  <div className="space-y-1">
                    {idx === 0 && <Label className="text-sm font-medium">Product</Label>}
                    <Select value={line.product_id || undefined}
                      onValueChange={v => handleProductSelect(idx, v ?? '')}>
                      <SelectTrigger className="h-10 text-sm">
                        <span className="truncate text-left flex-1">
                          {line.product_id
                            ? (products.find(p => p.id === line.product_id)?.name ?? '…')
                            : <span className="text-muted-foreground">Select product…</span>}
                        </span>
                      </SelectTrigger>
                      <SelectContent>
                        {products.map(p => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1 min-w-0">
                    {idx === 0 && <Label className="text-sm font-medium">Qty</Label>}
                    <Input className="h-10 text-sm font-semibold text-center w-full" type="number" min="0" step="0.001"
                      value={line.quantity} onChange={e => updateLine(idx, { quantity: e.target.value })} />
                  </div>
                  <div className="space-y-1 min-w-0">
                    {idx === 0 && <Label className="text-sm font-medium">Rate (₹)</Label>}
                    <Input className="h-10 text-sm font-semibold w-full" type="number" min="0" step="0.01"
                      value={line.rate} onChange={e => updateLine(idx, { rate: e.target.value })} />
                  </div>
                  <div className="space-y-1 min-w-0">
                    {idx === 0 && <Label className="text-sm font-medium">GST%</Label>}
                    <Select value={line.gst_rate} onValueChange={v => updateLine(idx, { gst_rate: v ?? '0' })}>
                      <SelectTrigger className="h-10 text-sm w-full"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {['0', '5', '12', '18', '28'].map(r => <SelectItem key={r} value={r}>{r}%</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="text-right space-y-1">
                    {idx === 0 && <Label className="text-sm font-medium">Total</Label>}
                    <p className="text-sm font-semibold font-mono h-10 flex items-center justify-end pr-1">
                      {INR(lineTotal(line))}
                    </p>
                  </div>
                  <Button size="icon" variant="ghost" className="h-10 w-10 text-muted-foreground"
                    onClick={() => setLines(l => l.filter((_, i) => i !== idx))}
                    disabled={lines.length === 1}>
                    <XCircle className="h-4 w-4" />
                  </Button>
                </div>
              ))}
            </div>
            <div className="text-right mt-2 text-sm font-semibold">
              Est. Total: {INR(grandEstimate)}
            </div>
          </div>

          {/* Other fields */}
          <div className="grid grid-cols-3 gap-3 border-t pt-3">
            <div className="space-y-1">
              <Label>Discount Type</Label>
              <Select value={form.discount_type || 'none'}
                onValueChange={v => setForm(f => ({ ...f, discount_type: (v === 'none' || !v) ? '' : v }))}>
                <SelectTrigger><SelectValue placeholder="No discount" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">None</SelectItem>
                  <SelectItem value="percentage">Percentage (%)</SelectItem>
                  <SelectItem value="flat">Flat Amount (₹)</SelectItem>
                </SelectContent>
              </Select>
            </div>
            {form.discount_type && (
              <div className="space-y-1">
                <Label>Discount Value</Label>
                <Input type="number" min="0" value={form.discount_value}
                  onChange={e => setForm(f => ({ ...f, discount_value: e.target.value }))} />
              </div>
            )}
            <div className="space-y-1">
              <Label>Freight (₹)</Label>
              <Input type="number" min="0" value={form.freight}
                onChange={e => setForm(f => ({ ...f, freight: e.target.value }))} />
            </div>
            <div className="space-y-1">
              <Label>Payment Mode</Label>
              <Select value={form.payment_mode || 'credit'}
                onValueChange={v => setForm(f => ({ ...f, payment_mode: v ?? '' }))}>
                <SelectTrigger><SelectValue placeholder="Select…" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="credit">Credit</SelectItem>
                  <SelectItem value="cash">Cash</SelectItem>
                  <SelectItem value="upi">UPI</SelectItem>
                  <SelectItem value="cheque">Cheque</SelectItem>
                  <SelectItem value="bank_transfer">Bank Transfer</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label>Transporter</Label>
              <Input value={form.transporter_name}
                onChange={e => setForm(f => ({ ...f, transporter_name: e.target.value }))}
                placeholder="Transporter name" />
            </div>
            <div className="space-y-1">
              <Label>E-Way Bill No</Label>
              <Input value={form.eway_bill_no}
                onChange={e => setForm(f => ({ ...f, eway_bill_no: e.target.value }))}
                placeholder="EWB number" />
            </div>
            <div className="col-span-3 space-y-1">
              <Label>Notes</Label>
              <Input value={form.notes}
                onChange={e => setForm(f => ({ ...f, notes: e.target.value }))}
                placeholder="Optional remarks…" />
            </div>
          </div>
        </div>

        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={onClose} disabled={saving}>Cancel</Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Save Changes
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ------------------------------------------------------------------ //
// Record Payment Dialog
// ------------------------------------------------------------------ //
const PAYMENT_MODES = ['cash', 'cheque', 'upi', 'bank_transfer', 'neft', 'rtgs'];

interface RecordPaymentDialogProps {
  open: boolean;
  invoice: Invoice | null;
  onClose: () => void;
  onSaved: () => void;
}

function RecordPaymentDialog({ open, invoice, onClose, onSaved }: RecordPaymentDialogProps) {
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [amount, setAmount] = useState('');
  const [mode, setMode] = useState('cash');
  const [refNo, setRefNo] = useState('');
  const [bankName, setBankName] = useState('');
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (open && invoice) {
      setDate(new Date().toISOString().slice(0, 10));
      setAmount(String(Number(invoice.amount_due) || Number(invoice.grand_total)));
      setMode('cash');
      setRefNo('');
      setBankName('');
      setNotes('');
      setError('');
    }
  }, [open, invoice]);

  async function handleSave() {
    if (!amount || parseFloat(amount) <= 0) { setError('Enter a valid amount'); return; }
    if (!invoice?.party) { setError('Cannot record payment for walk-in invoice without a party'); return; }
    setSaving(true); setError('');
    try {
      const url = invoice.invoice_type === 'sale' ? '/api/v1/payments/receipts' : '/api/v1/payments/vouchers';
      const dateKey = invoice.invoice_type === 'sale' ? 'receipt_date' : 'voucher_date';
      await api.post(url, {
        [dateKey]: date,
        party_id: invoice.party.id,
        amount: parseFloat(amount),
        payment_mode: mode,
        reference_no: refNo || null,
        bank_name: bankName || null,
        notes: notes || null,
        allocations: [{ invoice_id: invoice.id, amount: parseFloat(amount) }],
      });
      onSaved();
      onClose();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Failed to record payment');
    } finally {
      setSaving(false);
    }
  }

  const balance = invoice ? Number(invoice.amount_due) || Number(invoice.grand_total) : 0;
  const entered = parseFloat(amount) || 0;
  const isPartial = entered > 0 && entered < balance;

  return (
    <Dialog open={open} onOpenChange={v => !v && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>
            Record {invoice?.invoice_type === 'sale' ? 'Receipt' : 'Payment'}
            {invoice && <span className="ml-2 font-mono text-sm text-muted-foreground">{invoice.invoice_no}</span>}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          {error && <p className="rounded bg-destructive/10 p-2 text-sm text-destructive">{error}</p>}

          <div className="rounded-lg bg-muted/50 p-3 text-sm space-y-1">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Invoice Total</span>
              <span className="font-medium">{INR(invoice?.grand_total ?? 0)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Already Paid</span>
              <span className="text-green-600">{INR(invoice?.amount_paid ?? 0)}</span>
            </div>
            <div className="flex justify-between border-t pt-1 mt-1">
              <span className="font-medium">Balance Due</span>
              <span className="font-semibold text-orange-600">{INR(balance)}</span>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>Payment Date *</Label>
              <Input type="date" value={date} onChange={e => setDate(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label>Amount (₹) *</Label>
              <Input type="number" min="0.01" step="0.01" value={amount}
                onChange={e => setAmount(e.target.value)} placeholder="0.00" />
              {isPartial && (
                <p className="text-[10px] text-orange-600">
                  Partial — ₹{(balance - entered).toLocaleString('en-IN', { minimumFractionDigits: 2 })} will remain
                </p>
              )}
            </div>
          </div>

          <div className="space-y-1">
            <Label>Payment Mode *</Label>
            <Select value={mode} onValueChange={v => setMode(v ?? 'cash')}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {PAYMENT_MODES.map(m => (
                  <SelectItem key={m} value={m}>{m.replace(/_/g, ' ').toUpperCase()}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {mode !== 'cash' && (
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label>Reference No</Label>
                <Input value={refNo} onChange={e => setRefNo(e.target.value)} placeholder="Cheque / UTR / TXN" />
              </div>
              <div className="space-y-1">
                <Label>Bank Name</Label>
                <Input value={bankName} onChange={e => setBankName(e.target.value)} placeholder="Bank name" />
              </div>
            </div>
          )}

          <div className="space-y-1">
            <Label>Notes</Label>
            <Input value={notes} onChange={e => setNotes(e.target.value)} placeholder="Optional remarks" />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Record {invoice?.invoice_type === 'sale' ? 'Receipt' : 'Payment'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ------------------------------------------------------------------ //
// Main Page
// ------------------------------------------------------------------ //
interface InvoicesPageProps {
  defaultType?: 'sale' | 'purchase';
}

type SortCol = 'invoice_no' | 'invoice_date' | 'party' | 'grand_total' | 'net_weight' | 'payment_status' | 'status';

export default function InvoicesPage({ defaultType = 'sale' }: InvoicesPageProps) {
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [invoiceType, setInvoiceType] = useState<'sale' | 'purchase'>(defaultType);
  const [loading, setLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [editInvoice, setEditInvoice] = useState<Invoice | null>(null);
  const [paymentInvoice, setPaymentInvoice] = useState<Invoice | null>(null);
  const [tokenModalId, setTokenModalId] = useState<string | null>(null);
  const [movingToSupp, setMovingToSupp] = useState<string | null>(null);
  const { authorized: usbAuthorized } = useUsbGuard();
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';
  const isSalesExec = user?.role === 'sales_executive';
  const isPurchaseExec = user?.role === 'purchase_executive';

  // ── Role-based action permissions (fetched from API) ──────────────
  const [actionPerms, setActionPerms] = useState<string[]>([]);

  useEffect(() => {
    if (isAdmin) {
      // Admin always has all actions
      setActionPerms(['edit_draft','finalize','cancel_draft','record_payment','tally_sync','einvoice','create_revision','move_to_supplement']);
      return;
    }
    api.get<Record<string, string[]>>('/api/v1/app-settings/invoice-action-permissions')
      .then(({ data }) => {
        const role = user?.role ?? '';
        setActionPerms(data[role] ?? []);
      })
      .catch(() => {
        // Fallback defaults
        const defaults: Record<string, string[]> = {
          accountant: ['edit_draft','finalize','cancel_draft','record_payment','tally_sync','einvoice','create_revision'],
          sales_executive: ['edit_draft','finalize'],
          purchase_executive: ['edit_draft','finalize'],
        };
        setActionPerms(defaults[user?.role ?? ''] ?? []);
      });
  }, [user?.role, isAdmin]);

  const canTallySync = actionPerms.includes('tally_sync');
  const canEInvoice = actionPerms.includes('einvoice');
  const canRecordPayment = actionPerms.includes('record_payment');
  const canRevise = actionPerms.includes('create_revision');
  const canFinalize = actionPerms.includes('finalize');
  const canEditDraft = actionPerms.includes('edit_draft');
  const canCancelDraft = actionPerms.includes('cancel_draft');
  const canMoveToSupplement = actionPerms.includes('move_to_supplement');
  const PAGE_SIZE = 50;

  // Multi-select for bulk Tally sync
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [syncingIds, setSyncingIds] = useState<Set<string>>(new Set());
  const [irnLoadingIds, setIrnLoadingIds] = useState<Set<string>>(new Set());
  const [revisionLoadingIds, setRevisionLoadingIds] = useState<Set<string>>(new Set());
  const [revisionInvoice, setRevisionInvoice] = useState<Invoice | null>(null);

  // Sort state
  const [sortCol, setSortCol] = useState<SortCol>('invoice_date');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');

  // Column filters
  const [cf, setCf] = useState({ invoice_no: '', party: '', vehicle_no: '', payment_status: '', status: '', date_from: '', date_to: '' });

  function toggleSort(col: SortCol) {
    if (sortCol === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    else { setSortCol(col); setSortDir('asc'); }
  }

  function SortIcon({ col }: { col: SortCol }) {
    if (sortCol !== col) return <ChevronsUpDown className="inline h-3 w-3 ml-1 opacity-40" />;
    return sortDir === 'asc'
      ? <ChevronUp className="inline h-3 w-3 ml-1" />
      : <ChevronDown className="inline h-3 w-3 ml-1" />;
  }

  const fetchInvoices = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        page: String(page), page_size: String(PAGE_SIZE),
        invoice_type: invoiceType,
      });
      if (search) params.set('search', search);
      const { data } = await api.get<InvoiceListResponse>(`/api/v1/invoices?${params}`);
      setInvoices(data.items);
      setTotal(data.total);
    } catch { } finally { setLoading(false); }
  }, [page, search, invoiceType]);

  useEffect(() => { fetchInvoices(); }, [fetchInvoices]);
  // Clear selection when navigating pages or switching invoice type
  useEffect(() => { setSelectedIds(new Set()); }, [page, invoiceType]);

  // Client-side filter + sort on fetched page
  const displayed = useMemo(() => {
    let rows = [...invoices];
    if (cf.invoice_no) rows = rows.filter(r => (r.invoice_no ?? '').toLowerCase().includes(cf.invoice_no.toLowerCase()));
    if (cf.party) rows = rows.filter(r => (r.party?.name ?? r.customer_name ?? '').toLowerCase().includes(cf.party.toLowerCase()));
    if (cf.vehicle_no) rows = rows.filter(r => (r.vehicle_no ?? '').toLowerCase().includes(cf.vehicle_no.toLowerCase()));
    if (cf.payment_status) rows = rows.filter(r => r.payment_status === cf.payment_status);
    if (cf.status) rows = rows.filter(r => r.status === cf.status);
    if (cf.date_from) rows = rows.filter(r => r.invoice_date >= cf.date_from);
    if (cf.date_to) rows = rows.filter(r => r.invoice_date <= cf.date_to);
    rows.sort((a, b) => {
      let av: string | number = '', bv: string | number = '';
      if (sortCol === 'invoice_no') { av = a.invoice_no ?? ''; bv = b.invoice_no ?? ''; }
      else if (sortCol === 'invoice_date') { av = a.invoice_date; bv = b.invoice_date; }
      else if (sortCol === 'party') { av = a.party?.name ?? a.customer_name ?? ''; bv = b.party?.name ?? b.customer_name ?? ''; }
      else if (sortCol === 'grand_total') { av = a.grand_total; bv = b.grand_total; }
      else if (sortCol === 'net_weight') { av = a.net_weight ?? 0; bv = b.net_weight ?? 0; }
      else if (sortCol === 'payment_status') { av = a.payment_status; bv = b.payment_status; }
      else if (sortCol === 'status') { av = a.status; bv = b.status; }
      if (av < bv) return sortDir === 'asc' ? -1 : 1;
      if (av > bv) return sortDir === 'asc' ? 1 : -1;
      return 0;
    });
    return rows;
  }, [invoices, cf, sortCol, sortDir]);

  // ── Selection helpers ────────────────────────────────────────────────────
  const syncableFinal = displayed.filter(inv => inv.status === 'final');
  const allSelected = syncableFinal.length > 0 && syncableFinal.every(inv => selectedIds.has(inv.id));
  const someSelected = syncableFinal.some(inv => selectedIds.has(inv.id));
  const selectedNeedingSync = displayed.filter(inv => selectedIds.has(inv.id) && inv.tally_needs_sync && inv.status === 'final');

  function toggleSelect(id: string) {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  function toggleSelectAll() {
    if (allSelected) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(syncableFinal.map(inv => inv.id)));
    }
  }

  async function bulkSyncToTally() {
    if (selectedNeedingSync.length === 0) return;
    let ok = 0, fail = 0;
    for (const inv of selectedNeedingSync) {
      setSyncingIds(prev => new Set([...prev, inv.id]));
      try {
        const { data } = await api.post<{ success: boolean; message: string; tally_sync_at: string }>(
          `/api/v1/tally/sync/invoice/${inv.id}`
        );
        if (data.success) {
          setInvoices(prev => prev.map(i => i.id === inv.id
            ? { ...i, tally_synced: true, tally_sync_at: data.tally_sync_at, tally_needs_sync: false }
            : i));
          ok++;
        } else {
          fail++;
          toast.error(`${inv.invoice_no ?? inv.id}: ${data.message}`, { duration: 6000 });
        }
      } catch (e: unknown) {
        fail++;
        const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Connection failed';
        toast.error(`${inv.invoice_no ?? inv.id}: ${msg}`, { duration: 6000 });
      } finally {
        setSyncingIds(prev => { const n = new Set(prev); n.delete(inv.id); return n; });
      }
    }
    if (ok > 0) toast.success(`${ok} invoice${ok > 1 ? 's' : ''} sent to Tally`);
    if (fail === 0) setSelectedIds(new Set());
  }

  async function finalise(id: string) {
    try {
      const { data } = await api.post<Invoice>(`/api/v1/invoices/${id}/finalise`);
      setInvoices(prev => prev.map(i => i.id === id ? data : i));
      toast.success(`Invoice finalised as ${data.invoice_no}`);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(typeof detail === 'string' ? detail : 'Failed to finalise invoice');
    }
  }

  async function cancel(id: string) {
    try {
      const { data } = await api.post<Invoice>(`/api/v1/invoices/${id}/cancel`);
      setInvoices(prev => prev.map(i => i.id === id ? data : i));
      toast.success('Invoice cancelled');
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(typeof detail === 'string' ? detail : 'Failed to cancel invoice');
    }
  }

  async function moveToSupplement(inv: Invoice) {
    if (!usbAuthorized) {
      toast.error('USB key required to move invoice to Supplement');
      return;
    }
    if (!confirm(`Move invoice to Supplement? This will remove it from the normal invoice list and encrypt it in the Supplement table.`)) return;
    setMovingToSupp(inv.id);
    try {
      const { data } = await api.post<{ entry_no: string; message: string }>(`/api/v1/invoices/${inv.id}/move-to-supplement`);
      toast.success(`Moved to Supplement as ${data.entry_no}`);
      setInvoices(prev => prev.filter(i => i.id !== inv.id));
      setTotal(t => t - 1);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(typeof detail === 'string' ? detail : 'Failed to move to Supplement');
    } finally {
      setMovingToSupp(null);
    }
  }

  async function syncToTally(inv: Invoice) {
    setSyncingIds(prev => new Set([...prev, inv.id]));
    try {
      const { data } = await api.post<{ success: boolean; message: string; tally_sync_at: string }>(
        `/api/v1/tally/sync/invoice/${inv.id}`
      );
      if (data.success) {
        setInvoices(prev => prev.map(i => i.id === inv.id
          ? { ...i, tally_synced: true, tally_sync_at: data.tally_sync_at, tally_needs_sync: false }
          : i));
        toast.success(`${inv.invoice_no} sent to Tally`);
      } else {
        toast.error(`Tally sync failed: ${data.message}`);
      }
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to sync to Tally';
      toast.error(`Tally sync error: ${msg}`);
    } finally {
      setSyncingIds(prev => { const n = new Set(prev); n.delete(inv.id); return n; });
    }
  }

  async function generateIrn(inv: Invoice) {
    setIrnLoadingIds(prev => new Set([...prev, inv.id]));
    try {
      const { data } = await api.post<Invoice>(`/api/v1/invoices/${inv.id}/generate-irn`);
      setInvoices(prev => prev.map(i => i.id === inv.id ? data : i));
      if (data.einvoice_status === 'success') {
        toast.success(`IRN generated for ${inv.invoice_no}`);
      } else {
        toast.error(`IRN failed: ${data.einvoice_error || 'Unknown error'}`);
      }
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to generate IRN';
      toast.error(msg);
    } finally {
      setIrnLoadingIds(prev => { const n = new Set(prev); n.delete(inv.id); return n; });
    }
  }

  async function cancelIrn(inv: Invoice) {
    if (!confirm(`Cancel IRN for ${inv.invoice_no}? This can only be done within 24 hours of generation.`)) return;
    setIrnLoadingIds(prev => new Set([...prev, inv.id]));
    try {
      const { data } = await api.post<Invoice>(`/api/v1/invoices/${inv.id}/cancel-irn`, { reason: '2', remark: 'Cancelled by admin' });
      setInvoices(prev => prev.map(i => i.id === inv.id ? data : i));
      toast.success(`IRN cancelled for ${inv.invoice_no}`);
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to cancel IRN';
      toast.error(msg);
    } finally {
      setIrnLoadingIds(prev => { const n = new Set(prev); n.delete(inv.id); return n; });
    }
  }

  async function createRevision(inv: Invoice) {
    const reason = prompt(`Create revision of ${inv.invoice_no}?\n\nEnter a brief reason for this amendment (optional):`);
    if (reason === null) return; // user cancelled
    setRevisionLoadingIds(prev => new Set([...prev, inv.id]));
    try {
      const { data } = await api.post<Invoice>(
        `/api/v1/invoices/${inv.id}/create-revision`,
        { reason: reason.trim() || null }
      );
      setInvoices(prev => [data, ...prev]);
      toast.success(`Revision Rv${data.revision_no} created as draft — edit and finalize it`);
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to create revision';
      toast.error(msg);
    } finally {
      setRevisionLoadingIds(prev => { const n = new Set(prev); n.delete(inv.id); return n; });
    }
  }

  async function downloadPdf(inv: Invoice) {
    try {
      const res = await api.get(`/api/v1/invoices/${inv.id}/pdf`, { responseType: 'blob' });
      const blob = new Blob([res.data], { type: 'application/pdf' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${inv.invoice_no || 'invoice'}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      toast.error('Could not download PDF. Please try again.');
    }
  }

  const thClass = 'px-3 py-2 text-left text-xs font-medium text-muted-foreground select-none whitespace-nowrap';
  const thSortClass = thClass + ' cursor-pointer hover:text-foreground';

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Invoices</h1>
          <p className="text-muted-foreground">{total} invoices · {displayed.length} shown</p>
        </div>
        <Button onClick={() => setCreateOpen(true)}>
          <Plus className="mr-2 h-4 w-4" /> New Invoice
        </Button>
      </div>

      <div className="flex gap-3 flex-wrap items-center">
        <Tabs value={invoiceType} onValueChange={v => { setInvoiceType(v as 'sale' | 'purchase'); setPage(1); }}>
          <TabsList>
            <TabsTrigger value="sale">Sales</TabsTrigger>
            <TabsTrigger value="purchase">Purchase</TabsTrigger>
          </TabsList>
        </Tabs>
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input className="pl-9 h-9" placeholder="Search invoice no…" value={search}
            onChange={e => { setSearch(e.target.value); setPage(1); }} />
        </div>
        {Object.values(cf).some(Boolean) && (
          <Button variant="ghost" size="sm" className="text-xs text-muted-foreground"
            onClick={() => setCf({ invoice_no: '', party: '', vehicle_no: '', payment_status: '', status: '', date_from: '', date_to: '' })}>
            Clear filters ×
          </Button>
        )}
        {someSelected && (
          <Button
            size="sm"
            className="bg-blue-600 hover:bg-blue-700 text-white gap-1.5 ml-auto"
            onClick={bulkSyncToTally}
            disabled={syncingIds.size > 0 || selectedNeedingSync.length === 0}
            title={selectedNeedingSync.length === 0 ? 'All selected invoices are already up to date in Tally' : `Send ${selectedNeedingSync.length} invoice${selectedNeedingSync.length > 1 ? 's' : ''} to Tally`}
          >
            {syncingIds.size > 0
              ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
              : <Send className="h-3.5 w-3.5" />}
            Send to Tally
            <span className="ml-0.5 rounded-full bg-white/20 px-1.5 py-0.5 text-[10px] font-bold leading-none">
              {selectedIds.size}
            </span>
            {selectedNeedingSync.length < selectedIds.size && (
              <span className="text-[10px] opacity-70">({selectedNeedingSync.length} pending)</span>
            )}
          </Button>
        )}
      </div>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex justify-center py-12"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  {/* Sort row */}
                  <tr className="border-b bg-muted/50">
                    <th className="px-3 py-2 w-8">
                      <input
                        type="checkbox"
                        className="h-3.5 w-3.5 rounded border-gray-300 cursor-pointer accent-blue-600"
                        checked={allSelected}
                        ref={el => { if (el) el.indeterminate = someSelected && !allSelected; }}
                        onChange={toggleSelectAll}
                        title="Select all final invoices on this page"
                      />
                    </th>
                    <th className={thSortClass} onClick={() => toggleSort('invoice_no')}>
                      Invoice No <SortIcon col="invoice_no" />
                    </th>
                    <th className={thSortClass} onClick={() => toggleSort('invoice_date')}>
                      Date <SortIcon col="invoice_date" />
                    </th>
                    <th className={thSortClass} onClick={() => toggleSort('party')}>
                      Party / Customer <SortIcon col="party" />
                    </th>
                    <th className={thClass}>Vehicle</th>
                    <th className={thClass}>Token</th>
                    <th className={thSortClass + ' text-right'} onClick={() => toggleSort('net_weight')}>
                      Net Wt (MT) <SortIcon col="net_weight" />
                    </th>
                    <th className={thSortClass + ' text-right'} onClick={() => toggleSort('grand_total')}>
                      Amount <SortIcon col="grand_total" />
                    </th>
                    <th className={thClass + ' text-center'}>Progress</th>
                    <th className={thClass}></th>
                  </tr>
                  {/* Filter row */}
                  <tr className="border-b bg-muted/20">
                    <td className="px-2 py-1" />
                    <td className="px-2 py-1">
                      <Input className="h-7 text-xs" placeholder="Filter…" value={cf.invoice_no}
                        onChange={e => setCf(f => ({ ...f, invoice_no: e.target.value }))} />
                    </td>
                    <td className="px-2 py-1">
                      <div className="flex flex-col gap-0.5">
                        <input type="date" className="h-6 w-full rounded border border-input bg-background px-1.5 text-[11px]" title="From date"
                          value={cf.date_from} onChange={e => setCf(f => ({ ...f, date_from: e.target.value }))} />
                        <input type="date" className="h-6 w-full rounded border border-input bg-background px-1.5 text-[11px]" title="To date"
                          value={cf.date_to} onChange={e => setCf(f => ({ ...f, date_to: e.target.value }))} />
                      </div>
                    </td>
                    <td className="px-2 py-1">
                      <Input className="h-7 text-xs" placeholder="Filter…" value={cf.party}
                        onChange={e => setCf(f => ({ ...f, party: e.target.value }))} />
                    </td>
                    <td className="px-2 py-1">
                      <Input className="h-7 text-xs" placeholder="Filter…" value={cf.vehicle_no}
                        onChange={e => setCf(f => ({ ...f, vehicle_no: e.target.value }))} />
                    </td>
                    <td className="px-2 py-1" />
                    <td className="px-2 py-1" />
                    <td className="px-2 py-1" />
                    <td className="px-2 py-1">
                      <Select value={cf.payment_status || 'all'} onValueChange={v => setCf(f => ({ ...f, payment_status: (v ?? '') === 'all' ? '' : (v ?? '') }))}>
                        <SelectTrigger className="h-7 text-xs"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="all">All</SelectItem>
                          <SelectItem value="unpaid">Unpaid</SelectItem>
                          <SelectItem value="partial">Partial</SelectItem>
                          <SelectItem value="paid">Paid</SelectItem>
                        </SelectContent>
                      </Select>
                    </td>
                    <td className="px-2 py-1">
                      <Select value={cf.status || 'all'} onValueChange={v => setCf(f => ({ ...f, status: (v ?? '') === 'all' ? '' : (v ?? '') }))}>
                        <SelectTrigger className="h-7 text-xs"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="all">All</SelectItem>
                          <SelectItem value="draft">Draft</SelectItem>
                          <SelectItem value="final">Final</SelectItem>
                          <SelectItem value="cancelled">Cancelled</SelectItem>
                        </SelectContent>
                      </Select>
                    </td>
                    <td className="px-2 py-1" />
                  </tr>
                </thead>
                <tbody>
                  {displayed.length === 0 ? (
                    <tr>
                      <td colSpan={10}>
                        <div className="flex flex-col items-center justify-center py-16 px-4 text-center">
                          <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-muted">
                            <FileText className="h-8 w-8 text-muted-foreground/40" />
                          </div>
                          <h3 className="text-sm font-semibold">No invoices found</h3>
                          <p className="mt-1 max-w-xs text-xs text-muted-foreground">
                            Try adjusting your filters, or create a new invoice to get started.
                          </p>
                        </div>
                      </td>
                    </tr>
                  ) : displayed.map(inv => (
                    <tr key={inv.id} className={`border-b hover:bg-muted/30 transition-colors ${selectedIds.has(inv.id) ? 'bg-blue-50/50' : ''} ${inv.status === 'draft' && inv.invoice_no == null ? 'bg-amber-50/40' : ''}`}>
                      <td className="px-3 py-2">
                        {inv.status === 'final' && (
                          <input
                            type="checkbox"
                            className="h-3.5 w-3.5 rounded border-gray-300 cursor-pointer accent-blue-600"
                            checked={selectedIds.has(inv.id)}
                            onChange={() => toggleSelect(inv.id)}
                          />
                        )}
                      </td>
                      <td className="px-3 py-2 font-mono text-xs font-semibold whitespace-nowrap">
                        <div className="flex items-center gap-1.5">
                          <span>{inv.invoice_no ?? <span className="text-amber-600 italic text-[10px] font-normal">Draft — not assigned</span>}</span>
                          {inv.revision_no > 1 && (
                            <span className="text-[9px] font-bold px-1.5 py-0.5 rounded-full bg-purple-100 text-purple-700 font-mono">
                              Rv{inv.revision_no}
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="px-3 py-2 text-muted-foreground whitespace-nowrap">{inv.invoice_date}</td>
                      <td className="px-3 py-2 max-w-[200px]">
                        <div className="flex items-center gap-1.5 min-w-0">
                          <p className="truncate text-sm">{inv.party?.name ?? inv.customer_name ?? <span className="italic text-muted-foreground">Walk-in</span>}</p>
                          {inv.party?.gstin
                            ? <span className="shrink-0 text-[9px] font-semibold px-1 py-0.5 rounded bg-blue-100 text-blue-700">B2B</span>
                            : <span className="shrink-0 text-[9px] font-semibold px-1 py-0.5 rounded bg-gray-100 text-gray-600">B2C</span>
                          }
                        </div>
                        {inv.party?.gstin && <p className="text-[10px] text-muted-foreground font-mono mt-0.5">{inv.party.gstin}</p>}
                      </td>
                      <td className="px-3 py-2 font-mono text-xs text-muted-foreground">{inv.vehicle_no ?? '—'}</td>
                      <td className="px-3 py-2">
                        {inv.token_id && inv.token_no != null ? (
                          <button
                            className="inline-flex items-center gap-1 rounded-full bg-primary/10 hover:bg-primary/20 px-2 py-0.5 text-[11px] font-semibold text-primary transition-colors"
                            title="View token details"
                            onClick={() => setTokenModalId(inv.token_id)}
                          >
                            <Ticket className="h-2.5 w-2.5" />
                            #{inv.token_no}
                          </button>
                        ) : inv.token_id ? (
                          <button
                            className="inline-flex items-center gap-1 rounded-full bg-muted hover:bg-muted/80 px-2 py-0.5 text-[11px] text-muted-foreground transition-colors"
                            onClick={() => setTokenModalId(inv.token_id)}
                          >
                            <Ticket className="h-2.5 w-2.5" />
                            Token
                          </button>
                        ) : (
                          <span className="text-xs text-muted-foreground">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right text-muted-foreground">
                        {inv.net_weight != null ? Number(inv.net_weight).toLocaleString('en-IN', { maximumFractionDigits: 3 }) : '—'}
                      </td>
                      <td className="px-3 py-2 text-right font-semibold whitespace-nowrap">{INR(inv.grand_total)}</td>
                      <td className="px-3 py-2 text-center">
                        <div className="flex flex-col items-center gap-0.5">
                          <InvoicePipeline status={inv.status} paymentStatus={inv.payment_status} />
                          <EInvoiceBadge inv={inv} />
                        </div>
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex gap-0.5 justify-end">
                          <PrintButton
                            url={`/api/v1/invoices/${inv.id}/print`}
                            a4Url={`/api/v1/invoices/${inv.id}/pdf`}
                            iconOnly
                          />
                          <Button size="icon" variant="ghost" className="h-7 w-7" title="Download PDF" onClick={() => downloadPdf(inv)}>
                            <Download className="h-3.5 w-3.5" />
                          </Button>
                          {/* ── Finalized invoice actions (role-gated) ── */}
                          {inv.status === 'final' && canTallySync && (
                            <Button
                              size="icon" variant="ghost" className="h-7 w-7"
                              disabled={!inv.tally_needs_sync || syncingIds.has(inv.id)}
                              title={
                                syncingIds.has(inv.id) ? 'Sending to Tally…'
                                : !inv.tally_needs_sync
                                  ? `Synced to Tally${inv.tally_sync_at ? ' · ' + new Date(inv.tally_sync_at).toLocaleDateString('en-IN') : ''}`
                                  : inv.tally_synced
                                    ? 'Modified since last sync — click to re-sync'
                                    : 'Send to Tally'
                              }
                              onClick={() => syncToTally(inv)}
                            >
                              {syncingIds.has(inv.id)
                                ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                : !inv.tally_needs_sync
                                  ? <CheckCircle2 className="h-3.5 w-3.5 text-green-600" />
                                  : inv.tally_synced
                                    ? <RefreshCw className="h-3.5 w-3.5 text-amber-500" />
                                    : <Send className="h-3.5 w-3.5 text-orange-500" />}
                            </Button>
                          )}
                          {inv.status === 'final' && canEInvoice && (inv.einvoice_status === 'failed' || inv.einvoice_status === 'none') && inv.party && (inv.party as { gstin?: string | null })?.gstin && (
                            <Button
                              size="icon" variant="ghost" className="h-7 w-7"
                              title={inv.einvoice_status === 'failed' ? 'Retry IRN Generation' : 'Generate IRN'}
                              disabled={irnLoadingIds.has(inv.id)}
                              onClick={() => generateIrn(inv)}
                            >
                              {irnLoadingIds.has(inv.id)
                                ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                : <RotateCcw className="h-3.5 w-3.5 text-amber-600" />}
                            </Button>
                          )}
                          {inv.status === 'final' && canEInvoice && inv.einvoice_status === 'success' && (
                            <Button
                              size="icon" variant="ghost" className="h-7 w-7"
                              title="Cancel IRN"
                              disabled={irnLoadingIds.has(inv.id)}
                              onClick={() => cancelIrn(inv)}
                            >
                              {irnLoadingIds.has(inv.id)
                                ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                : <ShieldX className="h-3.5 w-3.5 text-red-400" />}
                            </Button>
                          )}
                          {inv.status === 'final' && canRecordPayment && inv.payment_status !== 'paid' && inv.party && (
                            <Button size="icon" variant="ghost" className="h-7 w-7" title="Record Payment" onClick={() => setPaymentInvoice(inv)}>
                              <Banknote className="h-3.5 w-3.5 text-blue-600" />
                            </Button>
                          )}
                          {inv.status === 'final' && canRevise && (
                            <Button
                              size="icon" variant="ghost" className="h-7 w-7"
                              title="Create Revision / Amendment"
                              disabled={revisionLoadingIds.has(inv.id)}
                              onClick={() => createRevision(inv)}
                            >
                              {revisionLoadingIds.has(inv.id)
                                ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                : <GitFork className="h-3.5 w-3.5 text-purple-600" />}
                            </Button>
                          )}
                          {(inv.revision_no > 1 || inv.original_invoice_id) && (
                            <Button
                              size="icon" variant="ghost" className="h-7 w-7"
                              title="View Revision History & Compare"
                              onClick={() => setRevisionInvoice(inv)}
                            >
                              <History className="h-3.5 w-3.5 text-indigo-500" />
                            </Button>
                          )}
                          {/* ── Draft invoice actions (role-gated) ── */}
                          {inv.status === 'draft' && (
                            <>
                              {canEditDraft && (!isSalesExec && !isPurchaseExec || (isSalesExec && inv.invoice_type !== 'purchase') || (isPurchaseExec && inv.invoice_type === 'purchase')) && (
                                <Button size="icon" variant="ghost" className="h-7 w-7" title="Edit Draft Invoice" onClick={() => setEditInvoice(inv)}>
                                  <Pencil className="h-3.5 w-3.5 text-blue-500" />
                                </Button>
                              )}
                              {canFinalize && (!isSalesExec && !isPurchaseExec || (isSalesExec && inv.invoice_type !== 'purchase') || (isPurchaseExec && inv.invoice_type === 'purchase')) && (
                                <Button size="icon" variant="ghost" className="h-7 w-7" title="Finalise Invoice" onClick={() => finalise(inv.id)}>
                                  <CheckCircle className="h-3.5 w-3.5 text-green-600" />
                                </Button>
                              )}
                              {canMoveToSupplement && usbAuthorized && (
                                <Button
                                  size="icon" variant="ghost" className="h-7 w-7"
                                  title="Move to Supplement (requires USB)"
                                  disabled={movingToSupp === inv.id}
                                  onClick={() => moveToSupplement(inv)}
                                >
                                  {movingToSupp === inv.id
                                    ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                    : <Lock className="h-3.5 w-3.5 text-purple-600" />}
                                </Button>
                              )}
                              {canCancelDraft && (
                                <Button size="icon" variant="ghost" className="h-7 w-7" title="Cancel" onClick={() => cancel(inv.id)}>
                                  <XCircle className="h-3.5 w-3.5 text-red-500" />
                                </Button>
                              )}
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {total > PAGE_SIZE && (
        <div className="flex items-center justify-between">
          <p className="text-sm text-muted-foreground">
            Showing {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, total)} of {total}
          </p>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" disabled={page === 1} onClick={() => setPage(p => p - 1)}>Previous</Button>
            <Button variant="outline" size="sm" disabled={page * PAGE_SIZE >= total} onClick={() => setPage(p => p + 1)}>Next</Button>
          </div>
        </div>
      )}

      <CreateInvoiceDialog
        open={createOpen}
        invoiceType={invoiceType}
        onClose={() => setCreateOpen(false)}
        onCreated={inv => { setInvoices(p => [inv, ...p]); setTotal(t => t + 1); }}
      />

      <EditInvoiceDialog
        open={!!editInvoice}
        invoice={editInvoice}
        onClose={() => setEditInvoice(null)}
        onSaved={updated => {
          setInvoices(prev => prev.map(i => i.id === updated.id ? updated : i));
          setEditInvoice(null);
        }}
      />

      <RecordPaymentDialog
        open={paymentInvoice !== null}
        invoice={paymentInvoice}
        onClose={() => setPaymentInvoice(null)}
        onSaved={() => { fetchInvoices(); setPaymentInvoice(null); }}
      />

      <TokenDetailModal
        tokenId={tokenModalId}
        onClose={() => setTokenModalId(null)}
      />

      {revisionInvoice && (
        <InvoiceRevisionDialog
          open={!!revisionInvoice}
          invoice={revisionInvoice}
          onClose={() => setRevisionInvoice(null)}
        />
      )}
    </div>
  );
}
