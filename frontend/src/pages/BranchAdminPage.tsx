import { useEffect, useState, useCallback } from 'react';
import api from '@/services/api';
import { toast } from 'sonner';
import { Plus, Loader2, Building2, Star, Power } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { DataTable, type ColumnDef } from '@/components/DataTable';

interface Branch {
  id: string; name: string; code: string; gstin: string | null; city: string | null;
  state: string | null; state_code: string | null; phone: string | null;
  is_default: boolean; is_active: boolean;
}

const blank = { name: '', code: '', gstin: '', address_line1: '', city: '', state: '', state_code: '', pincode: '', phone: '', is_default: false };

const BRANCH_COLUMNS: ColumnDef<Branch>[] = [
  {
    key: 'name', label: 'Name', type: 'string',
    accessor: b => b.name,
    format: (_, b) => (
      <span className="font-medium flex items-center gap-1">
        {(b as Branch).name}
        {(b as Branch).is_default && <Star className="inline h-3.5 w-3.5 text-amber-500" />}
      </span>
    ),
  },
  { key: 'code', label: 'Code', type: 'string', accessor: b => b.code, className: 'font-mono' },
  { key: 'gstin', label: 'GSTIN', type: 'string', accessor: b => b.gstin ?? '', format: (v) => v ? <span className="font-mono text-xs">{String(v)}</span> : <span className="text-muted-foreground">—</span> },
  {
    key: 'city_state', label: 'City / State', type: 'string',
    accessor: b => [b.city, b.state].filter(Boolean).join(', '),
    format: (v) => <span className="text-xs">{String(v) || '—'}</span>,
  },
  { key: 'phone', label: 'Phone', type: 'string', accessor: b => b.phone ?? '', format: (v) => <span className="text-xs">{String(v) || '—'}</span> },
  {
    key: 'status', label: 'Status', type: 'enum', enumOptions: ['active', 'inactive'],
    accessor: b => b.is_active ? 'active' : 'inactive',
    format: (v) => (
      <span className={`px-2 py-0.5 rounded-full text-[11px] ${v === 'active' ? 'bg-emerald-100 text-emerald-700' : 'bg-gray-200 text-gray-500'}`}>
        {String(v)}
      </span>
    ),
  },
];

export default function BranchAdminPage() {
  const [rows, setRows] = useState<Branch[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [form, setForm] = useState({ ...blank });
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try { const r = await api.get<Branch[]>('/api/v1/branches', { params: { include_inactive: true } }); setRows(r.data ?? []); }
    catch { /* inline */ } finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  function openNew() { setEditId(null); setForm({ ...blank }); setOpen(true); }
  function openEdit(b: Branch) {
    setEditId(b.id);
    setForm({ name: b.name, code: b.code, gstin: b.gstin ?? '', address_line1: '', city: b.city ?? '', state: b.state ?? '', state_code: b.state_code ?? '', pincode: '', phone: b.phone ?? '', is_default: b.is_default });
    setOpen(true);
  }

  async function save() {
    if (!form.name.trim() || !form.code.trim()) { toast.error('Name and code are required'); return; }
    setBusy(true);
    try {
      if (editId) await api.put(`/api/v1/branches/${editId}`, form);
      else await api.post('/api/v1/branches', form);
      toast.success('Branch saved'); setOpen(false); load();
    } catch (e: unknown) {
      toast.error((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Save failed');
    } finally { setBusy(false); }
  }

  async function toggleActive(b: Branch) {
    try {
      if (b.is_active) { await api.delete(`/api/v1/branches/${b.id}`); }
      else { await api.put(`/api/v1/branches/${b.id}`, { is_active: true }); }
      load();
    } catch { toast.error('Failed'); }
  }

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold flex items-center gap-2"><Building2 className="h-5 w-5" /> Branches / Plants</h1>
          <p className="text-xs text-muted-foreground">Each branch gets its own invoice/token/gate-pass series. Switch the active branch from the header picker.</p>
        </div>
        <Button onClick={openNew} className="gap-1.5"><Plus className="h-4 w-4" /> New Branch</Button>
      </div>

      <DataTable<Branch>
        id="branchadmin.main"
        data={rows}
        loading={loading}
        columns={BRANCH_COLUMNS}
        rowKey={b => b.id}
        exportFilename="branches"
        defaultSort={{ key: 'name', direction: 'asc' }}
        emptyMessage="No branches yet — single-plant mode. Add a branch to enable multi-branch."
        rowActions={b => (
          <div className="flex items-center gap-1 justify-end">
            <Button size="sm" variant="ghost" onClick={() => openEdit(b)}>Edit</Button>
            <button onClick={() => toggleActive(b)} title={b.is_active ? 'Deactivate' : 'Reactivate'} className="inline-flex h-7 w-7 items-center justify-center rounded-md hover:bg-accent">
              <Power className={`h-3.5 w-3.5 ${b.is_active ? 'text-red-500' : 'text-emerald-600'}`} />
            </button>
          </div>
        )}
      />

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader><DialogTitle>{editId ? 'Edit branch' : 'New branch'}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1"><Label className="text-xs">Name *</Label><Input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} /></div>
              <div className="space-y-1"><Label className="text-xs">Code * (short)</Label><Input value={form.code} onChange={e => setForm(f => ({ ...f, code: e.target.value.toUpperCase() }))} maxLength={12} placeholder="HQ / PL2" /></div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1"><Label className="text-xs">GSTIN (optional)</Label><Input value={form.gstin} onChange={e => setForm(f => ({ ...f, gstin: e.target.value.toUpperCase() }))} maxLength={15} /></div>
              <div className="space-y-1"><Label className="text-xs">Phone</Label><Input value={form.phone} onChange={e => setForm(f => ({ ...f, phone: e.target.value }))} /></div>
            </div>
            <div className="grid grid-cols-3 gap-3">
              <div className="space-y-1"><Label className="text-xs">City</Label><Input value={form.city} onChange={e => setForm(f => ({ ...f, city: e.target.value }))} /></div>
              <div className="space-y-1"><Label className="text-xs">State</Label><Input value={form.state} onChange={e => setForm(f => ({ ...f, state: e.target.value }))} /></div>
              <div className="space-y-1"><Label className="text-xs">State code</Label><Input value={form.state_code} onChange={e => setForm(f => ({ ...f, state_code: e.target.value }))} maxLength={2} placeholder="27" /></div>
            </div>
            <div className="flex items-center gap-2"><input type="checkbox" id="bdef" checked={form.is_default} onChange={e => setForm(f => ({ ...f, is_default: e.target.checked }))} /><Label htmlFor="bdef" className="text-xs cursor-pointer">Default branch</Label></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button onClick={save} disabled={busy} className="gap-1.5">{busy && <Loader2 className="h-4 w-4 animate-spin" />} Save</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
