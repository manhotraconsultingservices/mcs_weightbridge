import { useEffect, useState, useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Plus, Search, Send, XCircle, ArrowRight, Download } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { DataTable, type ColumnDef } from '@/components/DataTable';
import api from '@/services/api';
import type { Quotation, QuotationListResponse, Party, Product } from '@/types';

const INR = (v: number) => '₹' + v.toLocaleString('en-IN', { minimumFractionDigits: 2 });

const STATUS_COLORS: Record<string, string> = {
  draft:     'bg-amber-100 text-amber-700',
  sent:      'bg-blue-100 text-blue-700',
  accepted:  'bg-green-100 text-green-700',
  rejected:  'bg-red-100 text-red-700',
  expired:   'bg-gray-100 text-gray-500',
  converted: 'bg-purple-100 text-purple-700',
};

// ------------------------------------------------------------------ //
// Line items
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
  product_id: '', description: '', hsn_code: '',
  quantity: '1', unit: 'MT', rate: '', gst_rate: '5',
});

// ------------------------------------------------------------------ //
// Create / Edit Quotation Dialog
// ------------------------------------------------------------------ //
interface CreateQuotationDialogProps {
  open: boolean;
  onClose: () => void;
  onCreated: (q: Quotation) => void;
}

function CreateQuotationDialog({ open, onClose, onCreated }: CreateQuotationDialogProps) {
  const { t } = useTranslation();
  const [parties, setParties] = useState<Party[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [form, setForm] = useState({
    party_id: '',
    quotation_date: new Date().toISOString().split('T')[0],
    valid_to: '',
    notes: '',
    terms_and_conditions: '',
  });
  const [lines, setLines] = useState<LineItem[]>([emptyLine()]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open) return;
    setForm(prev => ({ ...prev, quotation_date: new Date().toISOString().split('T')[0], valid_to: '', party_id: '' }));
    setLines([emptyLine()]);
    setError('');
    Promise.all([
      api.get<Party[]>('/api/v1/parties'),
      api.get<Product[]>('/api/v1/products'),
    ]).then(([p, pr]) => {
      const pData = p.data as Party[] | { items: Party[] };
      setParties(Array.isArray(pData) ? pData : (pData.items ?? []));
      const prData = pr.data as Product[] | { items: Product[] };
      setProducts(Array.isArray(prData) ? prData : (prData.items ?? []));
    });
  }, [open]);

  const setForm_ = (k: string, v: string | null) => setForm(prev => ({ ...prev, [k]: v ?? '' }));

  const setLine = (idx: number, k: keyof LineItem, v: string | null) => {
    setLines(prev => {
      const next = [...prev];
      next[idx] = { ...next[idx], [k]: v ?? '' };
      if (k === 'product_id' && v) {
        const prod = products.find(p => p.id === v);
        if (prod) {
          next[idx].hsn_code = prod.hsn_code ?? '';
          next[idx].unit = prod.unit;
          next[idx].rate = String(prod.default_rate);
          next[idx].gst_rate = String(prod.gst_rate);
          next[idx].description = prod.name;
        }
      }
      return next;
    });
  };

  const addLine = () => setLines(prev => [...prev, emptyLine()]);
  const removeLine = (i: number) => setLines(prev => prev.filter((_, idx) => idx !== i));

  const handleSave = async () => {
    if (!form.party_id) { setError(t('quotation.errorSelectParty')); return; }
    if (lines.some(l => !l.product_id || !l.rate)) { setError(t('quotation.errorLineItems')); return; }
    setSaving(true); setError('');
    try {
      const payload = {
        party_id: form.party_id,
        quotation_date: form.quotation_date,
        valid_to: form.valid_to || null,
        notes: form.notes || null,
        terms_and_conditions: form.terms_and_conditions || null,
        items: lines.map((l, i) => ({
          product_id: l.product_id,
          description: l.description || null,
          hsn_code: l.hsn_code || null,
          quantity: parseFloat(l.quantity) || 1,
          unit: l.unit,
          rate: parseFloat(l.rate) || 0,
          gst_rate: parseFloat(l.gst_rate) || 0,
          sort_order: i,
        })),
      };
      const res = await api.post<Quotation>('/api/v1/quotations', payload);
      onCreated(res.data);
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      setError(err.response?.data?.detail ?? t('quotation.errorCreateFailed'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={o => !o && onClose()}>
      <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t('quotation.newQuotation')}</DialogTitle>
        </DialogHeader>

        <div className="grid grid-cols-2 gap-4 py-2">
          {/* Party */}
          <div className="space-y-1">
            <Label>{t('quotation.customer')} *</Label>
            <Select value={form.party_id || undefined} onValueChange={v => setForm_('party_id', v)}>
              <SelectTrigger>
                <span className="truncate text-left flex-1">
                  {form.party_id
                    ? (parties.find(p => p.id === form.party_id)?.name ?? '…')
                    : <span className="text-muted-foreground">{t('quotation.selectCustomer')}</span>}
                </span>
              </SelectTrigger>
              <SelectContent>
                {parties.filter(p => p.party_type === 'customer' || p.party_type === 'both').map(p => (
                  <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1">
            <Label>{t('quotation.quotationDate')} *</Label>
            <Input type="date" value={form.quotation_date} onChange={e => setForm_('quotation_date', e.target.value)} />
          </div>

          <div className="space-y-1">
            <Label>{t('quotation.validUntil')}</Label>
            <Input type="date" value={form.valid_to} onChange={e => setForm_('valid_to', e.target.value)} />
          </div>

          <div className="space-y-1">
            <Label>{t('common.notes')}</Label>
            <Input value={form.notes} onChange={e => setForm_('notes', e.target.value)} placeholder={t('quotation.notesPlaceholder')} />
          </div>

          <div className="col-span-2 space-y-1">
            <Label>{t('quotation.termsAndConditions')}</Label>
            <Input value={form.terms_and_conditions} onChange={e => setForm_('terms_and_conditions', e.target.value)} placeholder={t('quotation.termsPlaceholder')} />
          </div>
        </div>

        {/* Line items */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h3 className="font-medium text-sm">{t('quotation.items')}</h3>
            <Button type="button" variant="outline" size="sm" onClick={addLine}><Plus className="h-3 w-3 mr-1" />{t('quotation.addRow')}</Button>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b bg-muted/50">
                  <th className="text-left p-2">{t('quotation.product')}</th>
                  <th className="text-left p-2 w-20">{t('quotation.hsn')}</th>
                  <th className="text-right p-2 w-20">{t('quotation.quantity')}</th>
                  <th className="text-left p-2 w-16">{t('quotation.unit')}</th>
                  <th className="text-right p-2 w-24">{t('quotation.rate')}</th>
                  <th className="text-right p-2 w-16">{t('quotation.gstPct')}</th>
                  <th className="w-8 p-2"></th>
                </tr>
              </thead>
              <tbody>
                {lines.map((line, i) => (
                  <tr key={i} className="border-b">
                    <td className="p-1">
                      <Select value={line.product_id || undefined} onValueChange={v => setLine(i, 'product_id', v)}>
                        <SelectTrigger className="h-8 text-xs">
                          <span className="truncate text-left flex-1">
                            {line.product_id
                              ? (products.find(p => p.id === line.product_id)?.name ?? '…')
                              : <span className="text-muted-foreground">{t('quotation.selectProduct')}</span>}
                          </span>
                        </SelectTrigger>
                        <SelectContent>
                          {products.map(p => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}
                        </SelectContent>
                      </Select>
                    </td>
                    <td className="p-1"><Input className="h-8 text-xs" value={line.hsn_code} onChange={e => setLine(i, 'hsn_code', e.target.value)} /></td>
                    <td className="p-1"><Input className="h-8 text-xs text-right" type="number" value={line.quantity} onChange={e => setLine(i, 'quantity', e.target.value)} /></td>
                    <td className="p-1">
                      <Select value={line.unit} onValueChange={v => setLine(i, 'unit', v)}>
                        <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          {['MT','KG','CFT','BRASS','CUM','PCS','NOS'].map(u => <SelectItem key={u} value={u}>{u}</SelectItem>)}
                        </SelectContent>
                      </Select>
                    </td>
                    <td className="p-1"><Input className="h-8 text-xs text-right" type="number" value={line.rate} onChange={e => setLine(i, 'rate', e.target.value)} placeholder="0.00" /></td>
                    <td className="p-1">
                      <Select value={line.gst_rate} onValueChange={v => setLine(i, 'gst_rate', v)}>
                        <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          {['0','5','12','18','28'].map(r => <SelectItem key={r} value={r}>{r}%</SelectItem>)}
                        </SelectContent>
                      </Select>
                    </td>
                    <td className="p-1">
                      {lines.length > 1 && (
                        <Button type="button" variant="ghost" size="icon" className="h-8 w-8" onClick={() => removeLine(i)}>
                          <XCircle className="h-4 w-4 text-destructive" />
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>{t('common.cancel')}</Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving ? t('quotation.saving') : t('quotation.createQuotation')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ------------------------------------------------------------------ //
// Quotations Page
// ------------------------------------------------------------------ //
export default function QuotationsPage() {
  const { t } = useTranslation();
  const [quotations, setQuotations] = useState<Quotation[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [createOpen, setCreateOpen] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const PAGE_SIZE = 50;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(PAGE_SIZE),
      });
      if (search) params.set('search', search);
      if (statusFilter !== 'all') params.set('status', statusFilter);

      const res = await api.get<QuotationListResponse>(`/api/v1/quotations?${params}`);
      setQuotations(res.data.items ?? []);
      setTotal(res.data.total ?? 0);
    } finally {
      setLoading(false);
    }
  }, [page, search, statusFilter]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { setPage(1); }, [search, statusFilter]);

  const displayed = quotations.filter(q => {
    if (dateFrom && q.quotation_date < dateFrom) return false;
    if (dateTo && q.quotation_date > dateTo) return false;
    return true;
  });

  const handleAction = async (id: string, action: string) => {
    setActionLoading(id + action);
    try {
      if (action === 'send') await api.post(`/api/v1/quotations/${id}/send`);
      else if (action === 'convert') await api.post(`/api/v1/quotations/${id}/convert`);
      else if (action === 'cancel') await api.post(`/api/v1/quotations/${id}/cancel`);
      await load();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail ?? t('quotation.actionFailed'));
    } finally {
      setActionLoading(null);
    }
  };

  const downloadQuotationPdf = async (q: Quotation) => {
    try {
      const res = await api.get(`/api/v1/quotations/${q.id}/pdf`, { responseType: 'blob' });
      const blob = new Blob([res.data], { type: 'application/pdf' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${q.quotation_no || 'quotation'}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      toast.error(t('quotation.pdfDownloadFailed'));
    }
  };

  const totalPages = Math.ceil(total / PAGE_SIZE);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">{t('quotation.title')}</h1>
          <p className="text-muted-foreground">{t('quotation.subtitle')}</p>
        </div>
        <Button onClick={() => setCreateOpen(true)}>
          <Plus className="mr-2 h-4 w-4" /> {t('quotation.newQuotation')}
        </Button>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 items-center">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            className="pl-9 w-60"
            placeholder={t('quotation.searchPlaceholder')}
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>

        <div className="flex items-center gap-1.5">
          <span className="text-xs text-muted-foreground">{t('common.date')}:</span>
          <input type="date" title={t('common.from')} className="h-9 rounded-md border border-input bg-background px-2 text-xs"
            value={dateFrom} onChange={e => { setDateFrom(e.target.value); setPage(1); }} />
          <span className="text-xs text-muted-foreground">–</span>
          <input type="date" title={t('common.to')} className="h-9 rounded-md border border-input bg-background px-2 text-xs"
            value={dateTo} onChange={e => { setDateTo(e.target.value); setPage(1); }} />
          {(dateFrom || dateTo) && (
            <button className="text-xs text-muted-foreground hover:text-foreground" onClick={() => { setDateFrom(''); setDateTo(''); }}>×</button>
          )}
        </div>

        <Tabs value={statusFilter} onValueChange={setStatusFilter}>
          <TabsList>
            <TabsTrigger value="all">{t('common.all')}</TabsTrigger>
            <TabsTrigger value="draft">{t('quotation.status.draft')}</TabsTrigger>
            <TabsTrigger value="sent">{t('quotation.status.sent')}</TabsTrigger>
            <TabsTrigger value="accepted">{t('quotation.status.accepted')}</TabsTrigger>
            <TabsTrigger value="converted">{t('quotation.status.converted')}</TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      <QuotationsTable
        quotations={displayed}
        loading={loading}
        actionLoading={actionLoading}
        onAction={handleAction}
        onDownload={downloadQuotationPdf}
      />
      {totalPages > 1 && (
        <div className="flex items-center justify-between p-3 border-t text-sm">
          <span className="text-muted-foreground">{t('quotation.quotationCount', { count: total })}</span>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(prev => prev - 1)}>{t('common.back')}</Button>
            <span className="flex items-center px-2">{page} / {totalPages}</span>
            <Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => setPage(prev => prev + 1)}>{t('common.next')}</Button>
          </div>
        </div>
      )}

      <CreateQuotationDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={q => {
          setQuotations(prev => [q, ...prev]);
          setCreateOpen(false);
        }}
      />
    </div>
  );
}

// ------------------------------------------------------------------ //
// Quotations DataTable
// ------------------------------------------------------------------ //
function QuotationsTable({
  quotations, loading, actionLoading, onAction, onDownload,
}: {
  quotations: Quotation[];
  loading: boolean;
  actionLoading: string | null;
  onAction: (id: string, action: 'send' | 'convert') => void;
  onDownload: (q: Quotation) => void;
}) {
  const { t } = useTranslation();

  const columns = useMemo<ColumnDef<Quotation>[]>(() => [
    { key: 'quotation_no', label: t('quotation.quotationNo'), accessor: q => q.quotation_no,
      className: 'font-mono font-medium text-primary' },
    { key: 'quotation_date', label: t('common.date'), type: 'date',
      accessor: q => q.quotation_date,
      format: v => new Date(String(v)).toLocaleDateString('en-IN'),
      className: 'text-muted-foreground' },
    { key: 'valid_to', label: t('quotation.validUntil'), type: 'date',
      accessor: q => q.valid_to,
      format: v => v ? new Date(String(v)).toLocaleDateString('en-IN') : '—',
      className: 'text-muted-foreground' },
    { key: 'party', label: t('quotation.party'), accessor: q => q.party?.name ?? '' },
    { key: 'grand_total', label: t('quotation.grandTotal'), type: 'number', align: 'right',
      accessor: q => q.grand_total,
      format: v => INR(Number(v)),
      className: 'font-medium' },
    {
      key: 'status', label: t('common.status'), type: 'enum', align: 'center',
      enumOptions: ['draft', 'sent', 'accepted', 'rejected', 'converted', 'expired'],
      accessor: q => {
        const isExpired = q.valid_to && new Date(q.valid_to) < new Date() && q.status === 'sent';
        return isExpired ? 'expired' : q.status;
      },
      format: v => (
        <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${STATUS_COLORS[String(v)] ?? ''}`}>
          {t(`quotation.status.${String(v)}`, { defaultValue: String(v).toUpperCase() })}
        </span>
      ),
    },
  // eslint-disable-next-line react-hooks/exhaustive-deps
  ], [t]);

  return (
    <DataTable<Quotation>
      id="quotations.main"
      loading={loading}
      data={quotations}
      columns={columns}
      rowKey={q => q.id}
      exportFilename="quotations"
      defaultSort={{ key: 'quotation_date', direction: 'desc' }}
      emptyMessage={t('quotation.noQuotationsFound')}
      rowActions={q => (
        <div className="flex items-center gap-1 justify-end">
          {q.status === 'draft' && (
            <Button variant="ghost" size="sm"
                    disabled={actionLoading === q.id + 'send'}
                    onClick={() => onAction(q.id, 'send')}
                    title={t('quotation.markAsSent')}>
              <Send className="h-4 w-4" />
            </Button>
          )}
          {(q.status === 'sent' || q.status === 'accepted') && (
            <Button variant="ghost" size="sm"
                    disabled={actionLoading === q.id + 'convert'}
                    onClick={() => onAction(q.id, 'convert')}
                    title={t('quotation.convertToInvoice')}
                    className="text-purple-600">
              <ArrowRight className="h-4 w-4" />
            </Button>
          )}
          <Button variant="ghost" size="sm" title={t('common.download')} onClick={() => onDownload(q)}>
            <Download className="h-4 w-4" />
          </Button>
        </div>
      )}
    />
  );
}
