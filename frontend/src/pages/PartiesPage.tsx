import { useEffect, useState, useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Plus, Search, Pencil, Loader2, ExternalLink } from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { DataTable, type ColumnDef } from '@/components/DataTable';
import api from '@/services/api';
import type { Party } from '@/types';

const STATES = [
  { code: '27', name: 'Maharashtra' }, { code: '24', name: 'Gujarat' },
  { code: '29', name: 'Karnataka' }, { code: '33', name: 'Tamil Nadu' },
  { code: '07', name: 'Delhi' }, { code: '09', name: 'Uttar Pradesh' },
  { code: '20', name: 'Jharkhand' }, { code: '22', name: 'Chhattisgarh' },
  { code: '23', name: 'Madhya Pradesh' }, { code: '08', name: 'Rajasthan' },
  { code: '36', name: 'Telangana' }, { code: '32', name: 'Kerala' },
];

interface PartyForm {
  party_type: string;
  name: string;
  gstin: string;
  pan: string;
  phone: string;
  email: string;
  contact_person: string;
  billing_address: string;
  billing_city: string;
  billing_state: string;
  billing_state_code: string;
  billing_pincode: string;
  credit_limit: number;
  payment_terms_days: number;
  default_payment_mode: 'online' | 'cash';
  tally_ledger_name: string;
}

const EMPTY: PartyForm = {
  party_type: 'customer', name: '', gstin: '', pan: '',
  phone: '', email: '', contact_person: '',
  billing_address: '', billing_city: '', billing_state: '', billing_state_code: '', billing_pincode: '',
  credit_limit: 0, payment_terms_days: 0,
  default_payment_mode: 'cash',     // default: cash (non-GST, Bill of Supply)
  tally_ledger_name: '',
};


interface PartyDialogProps {
  open: boolean;
  editing: Party | null;
  onClose: () => void;
  onSaved: (p: Party) => void;
}

function PartyDialog({ open, editing, onClose, onSaved }: PartyDialogProps) {
  const { t } = useTranslation();
  const [form, setForm] = useState<PartyForm>({ ...EMPTY });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (open) {
      if (editing) {
        setForm({
          party_type: editing.party_type,
          name: editing.name,
          gstin: editing.gstin ?? '',
          pan: editing.pan ?? '',
          phone: editing.phone ?? '',
          email: editing.email ?? '',
          contact_person: editing.contact_person ?? '',
          billing_address: '',
          billing_city: editing.billing_city ?? '',
          billing_state: editing.billing_state ?? '',
          billing_state_code: editing.billing_state_code ?? '',
          billing_pincode: '',
          credit_limit: editing.credit_limit,
          payment_terms_days: editing.payment_terms_days,
          default_payment_mode: (editing.default_payment_mode === 'online' ? 'online' : 'cash'),
          tally_ledger_name: editing.tally_ledger_name ?? '',
        });
      } else {
        setForm({ ...EMPTY });
      }
    }
    setError('');
  }, [open, editing]);

  const set = (k: keyof PartyForm, v: string | number) => setForm(f => ({ ...f, [k]: v }));

  async function handleSubmit() {
    if (!form.name?.trim()) { setError('Name is required'); return; }
    setSaving(true); setError('');
    try {
      const url = editing ? `/api/v1/parties/${editing.id}` : '/api/v1/parties';
      const method = editing ? 'put' : 'post';
      const { data } = await api[method]<Party>(url, form);
      onSaved(data);
      onClose();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Failed to save party');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={v => !v && onClose()}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{editing ? t('party.editParty') : t('party.newParty')}</DialogTitle>
        </DialogHeader>

        <div className="space-y-5">
          {error && <p className="rounded bg-destructive/10 p-2 text-sm text-destructive">{error}</p>}

          {/* Basic */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>{t('party.type')} *</Label>
              <Select value={form.party_type} onValueChange={v => set('party_type', v ?? 'customer')}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="customer">{t('party.customer')}</SelectItem>
                  <SelectItem value="supplier">{t('party.supplier')}</SelectItem>
                  <SelectItem value="both">{t('party.both')}</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label>{t('party.name')} *</Label>
              <Input value={form.name ?? ''} onChange={e => set('name', e.target.value)} placeholder="Party / Company name" />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>{t('party.gstin')}</Label>
              <Input value={form.gstin ?? ''} onChange={e => set('gstin', e.target.value.toUpperCase())} placeholder="27XXXXX" maxLength={15} />
            </div>
            <div className="space-y-1">
              <Label>{t('party.pan')}</Label>
              <Input value={form.pan ?? ''} onChange={e => set('pan', e.target.value.toUpperCase())} placeholder="AAAAA0000A" maxLength={10} />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div className="space-y-1">
              <Label>{t('party.phone')}</Label>
              <Input value={form.phone ?? ''} onChange={e => set('phone', e.target.value)} placeholder="9876543210" />
            </div>
            <div className="space-y-1">
              <Label>{t('party.email')}</Label>
              <Input value={form.email ?? ''} onChange={e => set('email', e.target.value)} type="email" />
            </div>
            <div className="space-y-1">
              <Label>{t('party.contactPerson')}</Label>
              <Input value={form.contact_person ?? ''} onChange={e => set('contact_person', e.target.value)} />
            </div>
          </div>

          {/* Address */}
          <div className="border-t pt-4">
            <p className="text-sm font-medium mb-3">{t('party.billingAddress')}</p>
            <div className="space-y-3">
              <div className="space-y-1">
                <Label>{t('party.address')}</Label>
                <Input value={form.billing_address} onChange={e => set('billing_address', e.target.value)} placeholder="Street / Plot no" />
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div className="space-y-1">
                  <Label>{t('party.city')}</Label>
                  <Input value={form.billing_city} onChange={e => set('billing_city', e.target.value)} />
                </div>
                <div className="space-y-1">
                  <Label>{t('party.state')}</Label>
                  <Select value={form.billing_state_code} onValueChange={v => {
                    const s = STATES.find(s => s.code === v);
                    set('billing_state_code', v ?? '');
                    if (s) set('billing_state', s.name);
                  }}>
                    <SelectTrigger><SelectValue placeholder="State" /></SelectTrigger>
                    <SelectContent>
                      {STATES.map(s => <SelectItem key={s.code} value={s.code}>{s.name}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1">
                  <Label>{t('party.pincode')}</Label>
                  <Input value={form.billing_pincode} onChange={e => set('billing_pincode', e.target.value)} maxLength={6} />
                </div>
              </div>
            </div>
          </div>

          {/* Financial */}
          <div className="border-t pt-4">
            <p className="text-sm font-medium mb-3">{t('party.financialSettings')}</p>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <div className="space-y-1">
                <Label>{t('party.creditLimit')} (₹)</Label>
                <Input type="number" min="0" value={form.credit_limit ?? 0} onChange={e => set('credit_limit', parseFloat(e.target.value) || 0)} />
              </div>
              <div className="space-y-1">
                <Label>{t('party.paymentTerms')}</Label>
                <Input type="number" min="0" value={form.payment_terms_days ?? 0} onChange={e => set('payment_terms_days', parseInt(e.target.value) || 0)} />
              </div>
              <div className="space-y-1">
                <Label>{t('party.paymentMode')}</Label>
                <Select
                  value={form.default_payment_mode}
                  onValueChange={v => set('default_payment_mode', (v === 'online' ? 'online' : 'cash'))}
                >
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="cash">{t('party.cashDesc')}</SelectItem>
                    <SelectItem value="online">{t('party.onlineDesc')}</SelectItem>
                  </SelectContent>
                </Select>
                <p className="text-[10px] text-muted-foreground">
                  {t('party.paymentModeHint')}
                </p>
              </div>
            </div>
          </div>

          {/* Tally Integration */}
          <div className="border-t pt-4">
            <p className="text-sm font-medium mb-1">{t('party.tallyIntegration')}</p>
            <p className="text-xs text-muted-foreground mb-3">
              Override the ledger name used when syncing this party's invoices to Tally.
              Leave blank to use the party name as-is.
            </p>
            <div className="space-y-1">
              <Label>{t('party.tallyLedger')}</Label>
              <Input
                value={form.tally_ledger_name}
                onChange={e => set('tally_ledger_name', e.target.value)}
                placeholder={form.name || 'Same as party name if blank'}
              />
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>{t('common.cancel')}</Button>
          <Button onClick={handleSubmit} disabled={saving}>
            {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {editing ? t('party.updateParty') : t('party.createParty')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// DataTable filters in-memory; API max page_size=500.
const PARTY_FETCH_SIZE = 500;

export default function PartiesPage() {
  const { t } = useTranslation();
  const [parties, setParties] = useState<Party[]>([]);
  const [search, setSearch] = useState('');
  const [filterType, setFilterType] = useState('');
  const [loading, setLoading] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<Party | null>(null);

  const fetchParties = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page: '1', page_size: String(PARTY_FETCH_SIZE) });
      if (search) params.set('search', search);
      if (filterType) params.set('party_type', filterType);
      const { data } = await api.get<{ items: Party[]; total: number } | Party[]>(`/api/v1/parties?${params}`);
      if (Array.isArray(data)) setParties(data);
      else setParties(data.items ?? []);
    } catch { } finally { setLoading(false); }
  }, [search, filterType]);

  useEffect(() => { fetchParties(); }, [fetchParties]);

  function handleSaved(_p: Party) {
    fetchParties();
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">{t('party.title')}</h1>
          <p className="text-muted-foreground">{t('party.subtitle', { count: parties.length })}</p>
        </div>
        <Button onClick={() => { setEditing(null); setDialogOpen(true); }}>
          <Plus className="mr-2 h-4 w-4" /> {t('party.addParty')}
        </Button>
      </div>

      {/* Pointer to the Customer 360 view */}
      <div className="rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 flex items-start gap-3 text-sm">
        <ExternalLink className="h-4 w-4 text-blue-600 shrink-0 mt-0.5" />
        <div className="flex-1">
          <span className="font-semibold text-blue-900">Looking for Customer 360?</span>
          <span className="text-blue-700"> Click a party name (blue link) or the 🔗 icon in the row to open
            their full profile — outstanding · aging · last 20 invoices · last 20 payments · custom rates.
          </span>
          <Link to="/customers" className="ml-1 text-blue-700 hover:text-blue-900 underline underline-offset-2 font-medium">
            Or open the 360 picker
          </Link>
          <span className="text-blue-700">.</span>
        </div>
      </div>

      <div className="flex gap-3">
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input className="pl-9" placeholder="Name, GSTIN, phone…" value={search}
            onChange={e => { setSearch(e.target.value); }} />
        </div>
        <Select value={filterType || 'all'} onValueChange={v => { setFilterType(v && v !== 'all' ? v : ''); }}>
          <SelectTrigger className="w-36"><SelectValue placeholder={t('common.all')} /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t('common.all')}</SelectItem>
            <SelectItem value="customer">{t('party.customer')}</SelectItem>
            <SelectItem value="supplier">{t('party.supplier')}</SelectItem>
            <SelectItem value="both">{t('party.both')}</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <PartiesTable
        parties={parties}
        loading={loading}
        onEdit={p => { setEditing(p); setDialogOpen(true); }}
      />

      <PartyDialog open={dialogOpen} editing={editing} onClose={() => setDialogOpen(false)} onSaved={handleSaved} />
    </div>
  );
}

// ------------------------------------------------------------------ //
// Parties DataTable
// ------------------------------------------------------------------ //
function PartiesTable({
  parties, loading, onEdit,
}: {
  parties: Party[];
  loading: boolean;
  onEdit: (p: Party) => void;
}) {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const columns = useMemo<ColumnDef<Party>[]>(() => [
    {
      key: 'name', label: t('party.name'), accessor: p => p.name, className: 'font-medium',
      format: (_v, row) => (
        <Link
          to={`/customers/${row.id}`}
          className="inline-flex items-center gap-1 text-blue-600 hover:text-blue-800 hover:underline cursor-pointer"
          title="View 360 profile"
        >
          {row.name}
          <ExternalLink className="h-3 w-3 opacity-60" />
        </Link>
      ),
    },
    {
      key: 'party_type', label: t('party.type'), type: 'enum',
      enumOptions: ['customer', 'supplier', 'both'],
      accessor: p => p.party_type,
      format: v => <Badge variant="outline" className="text-[10px] capitalize">{String(v)}</Badge>,
    },
    { key: 'gstin', label: t('party.gstin'), accessor: p => p.gstin ?? '', className: 'font-mono text-xs' },
    { key: 'phone', label: t('party.phone'), accessor: p => p.phone ?? '', className: 'font-mono text-xs' },
    { key: 'email', label: t('party.email'), accessor: p => p.email ?? '', defaultVisible: false },
    { key: 'contact_person', label: t('party.contact'), accessor: p => p.contact_person ?? '', defaultVisible: false },
    { key: 'billing_city', label: t('party.city'), accessor: p => p.billing_city ?? '' },
    { key: 'billing_state', label: t('party.state'), accessor: p => p.billing_state ?? '', defaultVisible: false },
    {
      key: 'current_balance', label: `${t('party.balance')} (₹)`, type: 'number', align: 'right',
      accessor: p => p.current_balance,
      format: (v, row) => {
        const n = Number(v);
        return (
          <span className={`font-mono ${n < 0 ? 'text-red-600' : 'text-foreground'}`}>
            ₹{Math.abs(n).toLocaleString('en-IN')}
            {n < 0 ? ' Cr' : row.current_balance > 0 ? ' Dr' : ''}
          </span>
        );
      },
    },
    {
      key: 'credit_limit', label: t('party.creditLimit'), type: 'number', align: 'right',
      defaultVisible: false,
      accessor: p => p.credit_limit,
      format: v => `₹${Number(v).toLocaleString('en-IN')}`,
    },
    {
      key: 'payment_terms_days', label: t('party.termsD'), type: 'number', align: 'right',
      defaultVisible: false,
      accessor: p => p.payment_terms_days,
    },
    {
      key: 'default_payment_mode', label: t('party.mode'), type: 'enum', align: 'center',
      enumOptions: ['cash', 'online'],   // cash listed first to match default
      accessor: p => p.default_payment_mode ?? 'cash',
      format: v => v === 'online'
        ? <Badge className="bg-emerald-100 text-emerald-700 hover:bg-emerald-100 text-[10px]">ONLINE · GST</Badge>
        : <Badge className="bg-amber-100 text-amber-700 hover:bg-amber-100 text-[10px]">CASH · BoS</Badge>,
    },
    {
      key: 'is_active', label: t('common.status'), type: 'enum', align: 'center',
      enumOptions: ['Active', 'Inactive'],
      accessor: p => p.is_active ? 'Active' : 'Inactive',
      format: v => v === 'Active'
        ? <Badge className="bg-green-100 text-green-700 hover:bg-green-100">Active</Badge>
        : <Badge variant="secondary">Inactive</Badge>,
    },
  ], [t]);

  return (
    <DataTable<Party>
      id="parties.main"
      loading={loading}
      data={parties}
      columns={columns}
      rowKey={p => p.id}
      exportFilename="parties"
      defaultSort={{ key: 'name', direction: 'asc' }}
      emptyMessage="No parties yet. Add your first customer or supplier to get started."
      rowActions={p => (
        <div className="flex items-center gap-1 justify-end">
          <Button
            size="icon" variant="ghost"
            onClick={() => navigate(`/customers/${p.id}`)}
            title="View 360 profile"
          >
            <ExternalLink className="h-4 w-4 text-blue-600" />
          </Button>
          <Button size="icon" variant="ghost" onClick={() => onEdit(p)} title="Edit party">
            <Pencil className="h-4 w-4" />
          </Button>
        </div>
      )}
    />
  );
}
