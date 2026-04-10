import { useEffect, useState, useCallback } from 'react';
import { Plus, Search, Pencil, Loader2, Users } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
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
  tally_ledger_name: string;
}

const EMPTY: PartyForm = {
  party_type: 'customer', name: '', gstin: '', pan: '',
  phone: '', email: '', contact_person: '',
  billing_address: '', billing_city: '', billing_state: '', billing_state_code: '', billing_pincode: '',
  credit_limit: 0, payment_terms_days: 0,
  tally_ledger_name: '',
};


interface PartyDialogProps {
  open: boolean;
  editing: Party | null;
  onClose: () => void;
  onSaved: (p: Party) => void;
}

function PartyDialog({ open, editing, onClose, onSaved }: PartyDialogProps) {
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
          <DialogTitle>{editing ? 'Edit Party' : 'New Party'}</DialogTitle>
        </DialogHeader>

        <div className="space-y-5">
          {error && <p className="rounded bg-destructive/10 p-2 text-sm text-destructive">{error}</p>}

          {/* Basic */}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>Party Type *</Label>
              <Select value={form.party_type} onValueChange={v => set('party_type', v ?? 'customer')}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="customer">Customer</SelectItem>
                  <SelectItem value="supplier">Supplier</SelectItem>
                  <SelectItem value="both">Both</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label>Name *</Label>
              <Input value={form.name ?? ''} onChange={e => set('name', e.target.value)} placeholder="Party / Company name" />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>GSTIN</Label>
              <Input value={form.gstin ?? ''} onChange={e => set('gstin', e.target.value.toUpperCase())} placeholder="27XXXXX" maxLength={15} />
            </div>
            <div className="space-y-1">
              <Label>PAN</Label>
              <Input value={form.pan ?? ''} onChange={e => set('pan', e.target.value.toUpperCase())} placeholder="AAAAA0000A" maxLength={10} />
            </div>
          </div>

          <div className="grid grid-cols-3 gap-3">
            <div className="space-y-1">
              <Label>Phone</Label>
              <Input value={form.phone ?? ''} onChange={e => set('phone', e.target.value)} placeholder="9876543210" />
            </div>
            <div className="space-y-1">
              <Label>Email</Label>
              <Input value={form.email ?? ''} onChange={e => set('email', e.target.value)} type="email" />
            </div>
            <div className="space-y-1">
              <Label>Contact Person</Label>
              <Input value={form.contact_person ?? ''} onChange={e => set('contact_person', e.target.value)} />
            </div>
          </div>

          {/* Address */}
          <div className="border-t pt-4">
            <p className="text-sm font-medium mb-3">Billing Address</p>
            <div className="space-y-3">
              <div className="space-y-1">
                <Label>Address</Label>
                <Input value={form.billing_address} onChange={e => set('billing_address', e.target.value)} placeholder="Street / Plot no" />
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div className="space-y-1">
                  <Label>City</Label>
                  <Input value={form.billing_city} onChange={e => set('billing_city', e.target.value)} />
                </div>
                <div className="space-y-1">
                  <Label>State</Label>
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
                  <Label>Pincode</Label>
                  <Input value={form.billing_pincode} onChange={e => set('billing_pincode', e.target.value)} maxLength={6} />
                </div>
              </div>
            </div>
          </div>

          {/* Financial */}
          <div className="border-t pt-4">
            <p className="text-sm font-medium mb-3">Financial Settings</p>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label>Credit Limit (₹)</Label>
                <Input type="number" min="0" value={form.credit_limit ?? 0} onChange={e => set('credit_limit', parseFloat(e.target.value) || 0)} />
              </div>
              <div className="space-y-1">
                <Label>Payment Terms (days)</Label>
                <Input type="number" min="0" value={form.payment_terms_days ?? 0} onChange={e => set('payment_terms_days', parseInt(e.target.value) || 0)} />
              </div>
            </div>
          </div>

          {/* Tally Integration */}
          <div className="border-t pt-4">
            <p className="text-sm font-medium mb-1">Tally Integration</p>
            <p className="text-xs text-muted-foreground mb-3">
              Override the ledger name used when syncing this party's invoices to Tally.
              Leave blank to use the party name as-is.
            </p>
            <div className="space-y-1">
              <Label>Tally Ledger Name</Label>
              <Input
                value={form.tally_ledger_name}
                onChange={e => set('tally_ledger_name', e.target.value)}
                placeholder={form.name || 'Same as party name if blank'}
              />
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={handleSubmit} disabled={saving}>
            {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {editing ? 'Update' : 'Create'} Party
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

const PARTY_PAGE_SIZE = 50;

export default function PartiesPage() {
  const [parties, setParties] = useState<Party[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [filterType, setFilterType] = useState('');
  const [loading, setLoading] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<Party | null>(null);

  const fetchParties = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page: String(page), page_size: String(PARTY_PAGE_SIZE) });
      if (search) params.set('search', search);
      if (filterType) params.set('party_type', filterType);
      const { data } = await api.get<{ items: Party[]; total: number } | Party[]>(`/api/v1/parties?${params}`);
      if (Array.isArray(data)) {
        setParties(data);
        setTotal(data.length);
      } else {
        setParties(data.items ?? []);
        setTotal(data.total ?? 0);
      }
    } catch { } finally { setLoading(false); }
  }, [search, filterType, page]);

  useEffect(() => { fetchParties(); }, [fetchParties]);
  useEffect(() => { setPage(1); }, [search, filterType]);

  function handleSaved(_p: Party) {
    fetchParties();
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Parties</h1>
          <p className="text-muted-foreground">Customers & Suppliers — {total} records</p>
        </div>
        <Button onClick={() => { setEditing(null); setDialogOpen(true); }}>
          <Plus className="mr-2 h-4 w-4" /> Add Party
        </Button>
      </div>

      <div className="flex gap-3">
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input className="pl-9" placeholder="Name, GSTIN, phone…" value={search}
            onChange={e => { setSearch(e.target.value); }} />
        </div>
        <Select value={filterType || 'all'} onValueChange={v => { setFilterType(v && v !== 'all' ? v : ''); }}>
          <SelectTrigger className="w-36"><SelectValue placeholder="All types" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All</SelectItem>
            <SelectItem value="customer">Customer</SelectItem>
            <SelectItem value="supplier">Supplier</SelectItem>
            <SelectItem value="both">Both</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex justify-center py-12"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>
          ) : parties.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 px-4 text-center">
              <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-muted">
                <Users className="h-8 w-8 text-muted-foreground/40" />
              </div>
              <h3 className="text-sm font-semibold">No parties yet</h3>
              <p className="mt-1 max-w-xs text-xs text-muted-foreground">
                Add your first customer or supplier to get started.
              </p>
            </div>
          ) : (
            <div className="divide-y">
              {parties.map(p => (
                <div key={p.id} className="flex items-center gap-4 px-4 py-3 hover:bg-muted/30 transition-colors">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="font-medium text-sm">{p.name}</p>
                      <Badge variant="outline" className="text-[10px] capitalize">{p.party_type}</Badge>
                    </div>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {[p.gstin, p.phone, p.billing_city].filter(Boolean).join(' · ')}
                    </p>
                  </div>
                  <div className="text-right shrink-0">
                    <p className="text-xs text-muted-foreground">Balance</p>
                    <p className={`text-sm font-semibold ${p.current_balance < 0 ? 'text-red-600' : 'text-foreground'}`}>
                      ₹{Math.abs(p.current_balance).toLocaleString('en-IN')}
                      {p.current_balance < 0 ? ' Cr' : ''}
                    </p>
                  </div>
                  <Button size="icon" variant="ghost" onClick={() => { setEditing(p); setDialogOpen(true); }}>
                    <Pencil className="h-4 w-4" />
                  </Button>
                </div>
              ))}
            </div>
          )}

          {/* Pagination */}
          {total > PARTY_PAGE_SIZE && (
            <div className="flex items-center justify-between px-4 py-3 border-t text-sm">
              <span className="text-muted-foreground">
                Showing {(page - 1) * PARTY_PAGE_SIZE + 1}–{Math.min(page * PARTY_PAGE_SIZE, total)} of {total}
              </span>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>Prev</Button>
                <span className="flex items-center px-2">{page} / {Math.ceil(total / PARTY_PAGE_SIZE)}</span>
                <Button variant="outline" size="sm" disabled={page * PARTY_PAGE_SIZE >= total} onClick={() => setPage(p => p + 1)}>Next</Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>


      <PartyDialog open={dialogOpen} editing={editing} onClose={() => setDialogOpen(false)} onSaved={handleSaved} />
    </div>
  );
}
