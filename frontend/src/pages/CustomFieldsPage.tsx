import { useCallback, useEffect, useState } from 'react';
import { Plus, Pencil, Trash2, Sparkles } from 'lucide-react';
import api from '@/services/api';
import { getTenantIndustry } from '@/hooks/useAuth';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { DataTable, type ColumnDef } from '@/components/DataTable';
import type { CustomFieldDefinition } from '@/types';

const FIELD_TYPES = ['text', 'number', 'select', 'date', 'boolean'] as const;

const EMPTY = {
  id: '', label: '', field_type: 'text', unit: '', options: '',
  required: false, show_on_slip: true, sort_order: 0, is_active: true,
};

export default function CustomFieldsPage() {
  const [rows, setRows] = useState<CustomFieldDefinition[]>([]);
  const [loading, setLoading] = useState(true);
  const [seeded, setSeeded] = useState(false);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ ...EMPTY });
  const [saving, setSaving] = useState(false);
  const industry = getTenantIndustry();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get<CustomFieldDefinition[]>(
        '/api/v1/custom-fields?entity_type=token&include_inactive=true',
      );
      setRows(data);
      return data;
    } finally {
      setLoading(false);
    }
  }, []);

  const seedDefaults = useCallback(async (silent = false) => {
    try {
      const { data } = await api.post<CustomFieldDefinition[]>(
        `/api/v1/custom-fields/seed-defaults?industry=${encodeURIComponent(industry || 'generic')}`,
      );
      if (data.length) {
        toast.success(`Added ${data.length} recommended field${data.length > 1 ? 's' : ''}`);
        await load();
      } else if (!silent) {
        toast.info('No recommended fields for this industry');
      }
    } catch {
      if (!silent) toast.error('Could not add recommended fields');
    }
  }, [industry, load]);

  // First load + one-time auto-seed of industry defaults when the matrix is empty.
  useEffect(() => {
    (async () => {
      const data = await load();
      if (!seeded && data.length === 0 && industry && industry !== 'generic') {
        setSeeded(true);
        await seedDefaults(true);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function openNew() { setForm({ ...EMPTY }); setOpen(true); }
  function openEdit(r: CustomFieldDefinition) {
    setForm({
      id: r.id, label: r.label, field_type: r.field_type, unit: r.unit || '',
      options: (r.options || []).join(', '),
      required: r.required, show_on_slip: r.show_on_slip, sort_order: r.sort_order, is_active: r.is_active,
    });
    setOpen(true);
  }

  async function save() {
    if (!form.label.trim()) { toast.error('Label is required'); return; }
    setSaving(true);
    const body = {
      entity_type: 'token',
      label: form.label.trim(),
      field_type: form.field_type,
      unit: form.unit.trim() || null,
      options: form.field_type === 'select'
        ? form.options.split(',').map(s => s.trim()).filter(Boolean)
        : null,
      required: form.required,
      show_on_slip: form.show_on_slip,
      sort_order: Number(form.sort_order) || 0,
      is_active: form.is_active,
    };
    try {
      if (form.id) await api.put(`/api/v1/custom-fields/${form.id}`, body);
      else await api.post('/api/v1/custom-fields', body);
      toast.success('Saved');
      setOpen(false);
      await load();
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(msg || 'Save failed');
    } finally {
      setSaving(false);
    }
  }

  async function remove(r: CustomFieldDefinition) {
    if (!confirm(`Delete the custom field "${r.label}"? Existing weighment values are kept but stop showing.`)) return;
    try {
      await api.delete(`/api/v1/custom-fields/${r.id}`);
      toast.success('Deleted');
      await load();
    } catch { toast.error('Delete failed'); }
  }

  const COLUMNS: ColumnDef<CustomFieldDefinition>[] = [
    { key: 'label', label: 'Label', accessor: r => r.label },
    { key: 'field_key', label: 'Key', accessor: r => r.field_key },
    { key: 'field_type', label: 'Type', type: 'enum', enumOptions: [...FIELD_TYPES], accessor: r => r.field_type },
    { key: 'unit', label: 'Unit', accessor: r => r.unit || '' },
    { key: 'options', label: 'Choices', accessor: r => (r.options || []).join(', ') },
    { key: 'required', label: 'Required', accessor: r => (r.required ? 'Yes' : ''), exportValue: r => (r.required ? 'Yes' : 'No') },
    { key: 'show_on_slip', label: 'On slip', accessor: r => (r.show_on_slip ? 'Yes' : ''), exportValue: r => (r.show_on_slip ? 'Yes' : 'No') },
    { key: 'sort_order', label: 'Order', type: 'number', align: 'right', accessor: r => r.sort_order },
    { key: 'is_active', label: 'Active', accessor: r => (r.is_active ? 'Yes' : 'No') },
  ];

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Custom Fields</h1>
          <p className="text-sm text-muted-foreground">
            Owner-defined attributes captured on each weighment (e.g. Moisture %, Quality grade).
            Only your tenant sees these. Toggle “On slip” to print a field on the weight slip.
          </p>
        </div>
        <div className="flex gap-2">
          {industry && industry !== 'generic' && (
            <Button variant="outline" onClick={() => seedDefaults(false)}>
              <Sparkles className="mr-2 h-4 w-4" /> Add recommended
            </Button>
          )}
          <Button onClick={openNew}><Plus className="mr-2 h-4 w-4" /> New Field</Button>
        </div>
      </div>

      {loading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : (
        <DataTable<CustomFieldDefinition>
          id="custom-fields.token"
          data={rows}
          columns={COLUMNS}
          rowKey={r => r.id}
          exportFilename="custom-fields"
          defaultSort={{ key: 'sort_order', direction: 'asc' }}
          emptyMessage="No custom fields yet — add one or click “Add recommended”."
          rowActions={r => (
            <div className="flex gap-1">
              <Button size="sm" variant="ghost" onClick={() => openEdit(r)}><Pencil className="h-4 w-4" /></Button>
              <Button size="sm" variant="ghost" onClick={() => remove(r)}><Trash2 className="h-4 w-4 text-rose-600" /></Button>
            </div>
          )}
        />
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>{form.id ? 'Edit' : 'New'} Custom Field</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1">
              <Label>Label *</Label>
              <Input value={form.label} onChange={e => setForm(f => ({ ...f, label: e.target.value }))} placeholder="Moisture %" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label>Type</Label>
                <Select value={form.field_type} onValueChange={v => setForm(f => ({ ...f, field_type: v ?? 'text' }))}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>{FIELD_TYPES.map(t => <SelectItem key={t} value={t}>{t}</SelectItem>)}</SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label>Unit (optional)</Label>
                <Input value={form.unit} onChange={e => setForm(f => ({ ...f, unit: e.target.value }))} placeholder="%, kg…" />
              </div>
            </div>
            {form.field_type === 'select' && (
              <div className="space-y-1">
                <Label>Choices (comma-separated)</Label>
                <Input value={form.options} onChange={e => setForm(f => ({ ...f, options: e.target.value }))} placeholder="A, B, FAQ" />
              </div>
            )}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label>Sort order</Label>
                <Input type="number" value={form.sort_order} onChange={e => setForm(f => ({ ...f, sort_order: Number(e.target.value) }))} />
              </div>
              <div className="flex flex-col justify-end gap-2 pb-1">
                <label className="flex items-center gap-2 text-sm cursor-pointer">
                  <input type="checkbox" className="h-4 w-4" checked={form.show_on_slip} onChange={e => setForm(f => ({ ...f, show_on_slip: e.target.checked }))} />
                  Print on slip
                </label>
                <label className="flex items-center gap-2 text-sm cursor-pointer">
                  <input type="checkbox" className="h-4 w-4" checked={form.required} onChange={e => setForm(f => ({ ...f, required: e.target.checked }))} />
                  Required
                </label>
                <label className="flex items-center gap-2 text-sm cursor-pointer">
                  <input type="checkbox" className="h-4 w-4" checked={form.is_active} onChange={e => setForm(f => ({ ...f, is_active: e.target.checked }))} />
                  Active
                </label>
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Save'}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
