import { useEffect, useState, useCallback } from 'react';
import { toast } from 'sonner';
import {
  Plus, FileText, FolderOpen, Edit2, Trash2, Upload,
  AlertTriangle, CheckCircle, Clock, XCircle, RefreshCw, Settings2, X, Tag,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import api from '@/services/api';

// ── Types ───────────────────────────────────────────────────────────────── //

interface ComplianceItem {
  id: string;
  item_type: string;
  name: string;
  policy_holder: string | null;
  issuer: string | null;
  reference_no: string | null;
  issue_date: string | null;
  expiry_date: string | null;
  file_path: string | null;
  notes: string | null;
  is_active: boolean;
  days_to_expiry: number | null;
  alert_level: 'expired' | 'critical' | 'warning' | 'ok' | null;
  created_at: string;
  updated_at: string;
}

interface ComplianceListResponse {
  items: ComplianceItem[];
  total: number;
}

interface ComplianceThresholds {
  warning_days: number;
  critical_days: number;
}

type AlertFilter = 'expired' | 'critical' | 'warning' | 'ok' | null;

// ── Helpers ─────────────────────────────────────────────────────────────── //

function typeLabel(t: string) {
  return t.charAt(0).toUpperCase() + t.slice(1);
}

// ── Alert helpers ───────────────────────────────────────────────────────── //

function AlertBadge({ level, days }: { level: string | null; days: number | null }) {
  if (!level || level === 'ok') return null;

  const configs = {
    expired: { color: 'bg-red-100 text-red-700 border-red-200', icon: XCircle, label: 'Expired' },
    critical: { color: 'bg-orange-100 text-orange-700 border-orange-200', icon: AlertTriangle, label: `${days}d left` },
    warning: { color: 'bg-yellow-100 text-yellow-700 border-yellow-200', icon: Clock, label: `${days}d left` },
  };

  const cfg = configs[level as keyof typeof configs];
  if (!cfg) return null;
  const Icon = cfg.icon;

  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium ${cfg.color}`}>
      <Icon className="h-3 w-3" />
      {cfg.label}
    </span>
  );
}

function StatusDot({ level }: { level: string | null }) {
  if (!level) return <span className="h-2 w-2 rounded-full bg-gray-300 inline-block" />;
  const colors: Record<string, string> = {
    ok: 'bg-green-500',
    warning: 'bg-yellow-500',
    critical: 'bg-orange-500',
    expired: 'bg-red-500',
  };
  return <span className={`h-2 w-2 rounded-full inline-block ${colors[level] ?? 'bg-gray-300'}`} />;
}

// ── Threshold Settings Panel ─────────────────────────────────────────────── //

interface ThresholdPanelProps {
  open: boolean;
  onClose: () => void;
  thresholds: ComplianceThresholds;
  onSaved: (t: ComplianceThresholds) => void;
}

function ThresholdSettingsPanel({ open, onClose, thresholds, onSaved }: ThresholdPanelProps) {
  const [form, setForm] = useState({ warning_days: String(thresholds.warning_days), critical_days: String(thresholds.critical_days) });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (open) {
      setForm({ warning_days: String(thresholds.warning_days), critical_days: String(thresholds.critical_days) });
      setError('');
    }
  }, [open, thresholds]);

  async function handleSave() {
    const w = parseInt(form.warning_days);
    const c = parseInt(form.critical_days);
    if (!w || !c || w < 1 || c < 1) { setError('Both values must be positive numbers'); return; }
    if (c >= w) { setError('Critical days must be less than Warning days'); return; }
    setSaving(true); setError('');
    try {
      const { data } = await api.put<ComplianceThresholds>('/api/v1/compliance/settings/thresholds', { warning_days: w, critical_days: c });
      onSaved(data);
      toast.success('Alert thresholds saved');
      onClose();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Failed to save');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Sheet open={open} onOpenChange={v => !v && onClose()}>
      <SheetContent side="right" className="w-80">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">
            <Settings2 className="h-4 w-4" />
            Alert Thresholds
          </SheetTitle>
        </SheetHeader>

        <div className="mt-6 space-y-5">
          <p className="text-sm text-muted-foreground">
            Configure how many days before expiry an item is flagged as <span className="text-yellow-600 font-medium">Warning</span> or <span className="text-orange-600 font-medium">Critical</span>.
          </p>

          {error && <p className="rounded bg-destructive/10 p-2 text-sm text-destructive">{error}</p>}

          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label className="text-yellow-700">Warning threshold (days)</Label>
              <Input
                type="number" min={1} max={365}
                value={form.warning_days}
                onChange={e => setForm(f => ({ ...f, warning_days: e.target.value }))}
                className="border-yellow-300 focus-visible:ring-yellow-400"
              />
              <p className="text-[11px] text-muted-foreground">Items expiring within this many days show a yellow warning.</p>
            </div>

            <div className="space-y-1.5">
              <Label className="text-orange-700">Critical threshold (days)</Label>
              <Input
                type="number" min={1} max={365}
                value={form.critical_days}
                onChange={e => setForm(f => ({ ...f, critical_days: e.target.value }))}
                className="border-orange-300 focus-visible:ring-orange-400"
              />
              <p className="text-[11px] text-muted-foreground">Items expiring within this many days show an orange critical alert.</p>
            </div>
          </div>

          <div className="rounded-md border bg-muted/40 p-3 text-xs text-muted-foreground space-y-1">
            <p className="font-medium text-foreground">Alert levels (in order):</p>
            <p><span className="text-red-600 font-medium">Expired</span> — past expiry date</p>
            <p><span className="text-orange-600 font-medium">Critical</span> — within {form.critical_days || '?'} days</p>
            <p><span className="text-yellow-600 font-medium">Warning</span> — within {form.warning_days || '?'} days</p>
            <p><span className="text-green-600 font-medium">Valid</span> — beyond {form.warning_days || '?'} days</p>
          </div>

          <div className="flex gap-2">
            <Button variant="outline" onClick={onClose} disabled={saving} className="flex-1">Cancel</Button>
            <Button onClick={handleSave} disabled={saving} className="flex-1">
              {saving ? 'Saving…' : 'Save'}
            </Button>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}

// ── Manage Types Panel ───────────────────────────────────────────────────── //

interface ManageTypesPanelProps {
  open: boolean;
  onClose: () => void;
  types: string[];
  onSaved: (types: string[]) => void;
}

function ManageTypesPanel({ open, onClose, types, onSaved }: ManageTypesPanelProps) {
  const [list, setList] = useState<string[]>([]);
  const [newType, setNewType] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (open) { setList([...types]); setNewType(''); setError(''); }
  }, [open, types]);

  function addType() {
    const val = newType.trim().toLowerCase();
    if (!val) return;
    if (list.includes(val)) { setError('Type already exists'); return; }
    setList(l => [...l, val]);
    setNewType('');
    setError('');
  }

  function removeType(t: string) {
    setList(l => l.filter(x => x !== t));
  }

  async function handleSave() {
    if (list.length === 0) { setError('At least one type is required'); return; }
    setSaving(true); setError('');
    try {
      const { data } = await api.put<string[]>('/api/v1/compliance/settings/types', list);
      onSaved(data);
      toast.success('Compliance types saved');
      onClose();
    } catch {
      setError('Failed to save types');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Sheet open={open} onOpenChange={v => !v && onClose()}>
      <SheetContent side="right" className="w-80">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">
            <Tag className="h-4 w-4" />
            Manage Types
          </SheetTitle>
        </SheetHeader>

        <div className="mt-6 space-y-5">
          <p className="text-sm text-muted-foreground">
            Configure which item types are available in the compliance form.
          </p>

          {error && <p className="rounded bg-destructive/10 p-2 text-sm text-destructive">{error}</p>}

          {/* Existing types */}
          <div className="space-y-2">
            {list.map(t => (
              <div key={t} className="flex items-center justify-between rounded-md border bg-muted/30 px-3 py-2">
                <span className="text-sm font-medium capitalize">{typeLabel(t)}</span>
                <button
                  type="button"
                  onClick={() => removeType(t)}
                  className="text-muted-foreground hover:text-destructive transition-colors"
                  title="Remove"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            ))}
            {list.length === 0 && (
              <p className="text-xs text-muted-foreground text-center py-2">No types. Add at least one.</p>
            )}
          </div>

          {/* Add new type */}
          <div className="space-y-1.5">
            <Label className="text-xs">Add New Type</Label>
            <div className="flex gap-2">
              <Input
                className="h-8 text-sm"
                placeholder="e.g. vehicle-fitness"
                value={newType}
                onChange={e => setNewType(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && addType()}
              />
              <Button size="sm" variant="outline" onClick={addType} className="h-8 shrink-0">Add</Button>
            </div>
            <p className="text-[11px] text-muted-foreground">Press Enter or click Add. Will be capitalised in the UI.</p>
          </div>

          <div className="flex gap-2 pt-2">
            <Button variant="outline" onClick={onClose} disabled={saving} className="flex-1">Cancel</Button>
            <Button onClick={handleSave} disabled={saving} className="flex-1">
              {saving ? 'Saving…' : 'Save Types'}
            </Button>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}

// ── Add/Edit Dialog ─────────────────────────────────────────────────────── //

interface EditDialogProps {
  open: boolean;
  item: ComplianceItem | null;
  itemTypes: string[];
  onClose: () => void;
  onSaved: (item: ComplianceItem) => void;
}

function EditDialog({ open, item, itemTypes, onClose, onSaved }: EditDialogProps) {
  const [form, setForm] = useState({
    item_type: '',
    name: '',
    policy_holder: '',
    issuer: '',
    reference_no: '',
    issue_date: '',
    expiry_date: '',
    file_path: '',
    notes: '',
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);

  useEffect(() => {
    if (open) {
      const defaultType = itemTypes[0] ?? 'insurance';
      if (item) {
        setForm({
          item_type: item.item_type,
          name: item.name,
          policy_holder: item.policy_holder ?? '',
          issuer: item.issuer ?? '',
          reference_no: item.reference_no ?? '',
          issue_date: item.issue_date ?? '',
          expiry_date: item.expiry_date ?? '',
          file_path: item.file_path ?? '',
          notes: item.notes ?? '',
        });
      } else {
        setForm({ item_type: defaultType, name: '', policy_holder: '', issuer: '', reference_no: '', issue_date: '', expiry_date: '', file_path: '', notes: '' });
      }
      setSelectedFile(null);
      setError('');
    }
  }, [open, item, itemTypes]);

  async function handleSave() {
    if (!form.name.trim()) { setError('Name is required'); return; }
    if (!form.policy_holder.trim()) { setError('Policy Holder is required'); return; }
    setSaving(true); setError('');
    try {
      const payload = {
        item_type: form.item_type,
        name: form.name.trim(),
        policy_holder: form.policy_holder.trim(),
        issuer: form.issuer.trim() || null,
        reference_no: form.reference_no.trim() || null,
        issue_date: form.issue_date || null,
        expiry_date: form.expiry_date || null,
        file_path: (!selectedFile && form.file_path.trim()) ? form.file_path.trim() : (item?.file_path || null),
        notes: form.notes.trim() || null,
      };
      let resp;
      if (item) {
        resp = await api.put<ComplianceItem>(`/api/v1/compliance/${item.id}`, payload);
      } else {
        resp = await api.post<ComplianceItem>('/api/v1/compliance', payload);
      }

      // Upload file if selected
      if (selectedFile) {
        setUploading(true);
        const fd = new FormData();
        fd.append('file', selectedFile);
        try {
          resp = await api.post<ComplianceItem>(`/api/v1/compliance/${resp.data.id}/upload`, fd, {
            headers: { 'Content-Type': 'multipart/form-data' },
          });
        } catch (uploadErr: unknown) {
          const detail = (uploadErr as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
          toast.error(typeof detail === 'string' ? detail : 'File upload failed');
        } finally {
          setUploading(false);
        }
      }

      onSaved(resp.data);
      onClose();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Failed to save');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={v => !v && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{item ? 'Edit' : 'Add'} Compliance Item</DialogTitle>
        </DialogHeader>

        <div className="space-y-3">
          {error && <p className="rounded bg-destructive/10 p-2 text-sm text-destructive">{error}</p>}

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>Type <span className="text-destructive">*</span></Label>
              <Select value={form.item_type} onValueChange={v => setForm(f => ({ ...f, item_type: v ?? itemTypes[0] }))}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {itemTypes.map(t => <SelectItem key={t} value={t}>{typeLabel(t)}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label>Name <span className="text-destructive">*</span></Label>
              <Input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                placeholder="e.g. Vehicle Insurance – MH-12-AB-1234" />
            </div>
          </div>

          <div className="space-y-1">
            <Label>Policy Holder <span className="text-destructive">*</span></Label>
            <Input value={form.policy_holder} onChange={e => setForm(f => ({ ...f, policy_holder: e.target.value }))}
              placeholder="e.g. ABC Stone Crusher Pvt. Ltd." />
            <p className="text-[11px] text-muted-foreground">Name of the individual or company covered by this policy/certificate.</p>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>Issuing Authority / Insurer</Label>
              <Input value={form.issuer} onChange={e => setForm(f => ({ ...f, issuer: e.target.value }))}
                placeholder="e.g. New India Assurance" />
            </div>
            <div className="space-y-1">
              <Label>Policy / Certificate No.</Label>
              <Input value={form.reference_no} onChange={e => setForm(f => ({ ...f, reference_no: e.target.value }))}
                placeholder="e.g. POL/2025/123456" />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>Issue Date</Label>
              <Input type="date" value={form.issue_date} onChange={e => setForm(f => ({ ...f, issue_date: e.target.value }))} />
            </div>
            <div className="space-y-1">
              <Label>Expiry Date</Label>
              <Input type="date" value={form.expiry_date} onChange={e => setForm(f => ({ ...f, expiry_date: e.target.value }))} />
            </div>
          </div>

          <div className="space-y-1">
            <Label>Upload Document</Label>
            <label
              className="flex items-center gap-3 rounded-lg border-2 border-dashed border-muted-foreground/25 p-3 cursor-pointer hover:border-primary/40 hover:bg-primary/5 transition-colors"
              onDragOver={e => { e.preventDefault(); e.currentTarget.classList.add('border-primary/60', 'bg-primary/10'); }}
              onDragLeave={e => { e.currentTarget.classList.remove('border-primary/60', 'bg-primary/10'); }}
              onDrop={e => {
                e.preventDefault();
                e.currentTarget.classList.remove('border-primary/60', 'bg-primary/10');
                const f = e.dataTransfer.files?.[0];
                if (f) setSelectedFile(f);
              }}
            >
              <Upload className="h-5 w-5 text-muted-foreground shrink-0" />
              <div className="flex-1 min-w-0">
                {selectedFile ? (
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium truncate">{selectedFile.name}</span>
                    <span className="text-[11px] text-muted-foreground">({(selectedFile.size / 1024).toFixed(0)} KB)</span>
                    <button type="button" className="text-destructive hover:text-destructive/80" onClick={e => { e.preventDefault(); setSelectedFile(null); }}>
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ) : item?.file_path ? (
                  <p className="text-sm text-muted-foreground">
                    Current: <span className="font-medium">{item.file_path.split('/').pop()}</span> — drop new file to replace
                  </p>
                ) : (
                  <p className="text-sm text-muted-foreground">Click or drag file here (PDF, JPG, PNG, DOCX — max 10 MB)</p>
                )}
              </div>
              <input type="file" className="hidden" accept=".pdf,.jpg,.jpeg,.png,.doc,.docx,.xls,.xlsx,.tif,.tiff"
                onChange={e => { const f = e.target.files?.[0]; if (f) setSelectedFile(f); e.target.value = ''; }} />
            </label>
          </div>

          <div className="space-y-1">
            <Label>Notes</Label>
            <Input value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))}
              placeholder="Any additional details..." />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={saving || uploading}>Cancel</Button>
          <Button onClick={handleSave} disabled={saving || uploading}>
            {uploading ? 'Uploading…' : saving ? 'Saving…' : (item ? 'Update' : 'Add')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Main Page ───────────────────────────────────────────────────────────── //

export default function CompliancePage() {
  const [items, setItems] = useState<ComplianceItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [typeFilter, setTypeFilter] = useState('all');
  const [alertFilter, setAlertFilter] = useState<AlertFilter>(null);
  const [editItem, setEditItem] = useState<ComplianceItem | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [openingFile, setOpeningFile] = useState<string | null>(null);
  const [thresholds, setThresholds] = useState<ComplianceThresholds>({ warning_days: 60, critical_days: 30 });
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [itemTypes, setItemTypes] = useState<string[]>(['insurance', 'certification', 'license', 'permit']);
  const [manageTypesOpen, setManageTypesOpen] = useState(false);

  const ALERT_ORDER: Record<string, number> = { expired: 0, critical: 1, warning: 2, ok: 3 };

  const fetchItems = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ include_inactive: 'false' });
      if (typeFilter !== 'all') params.set('item_type', typeFilter);
      const { data } = await api.get<ComplianceListResponse>(`/api/v1/compliance?${params}`);
      const sorted = [...data.items].sort(
        (a, b) => (ALERT_ORDER[a.alert_level ?? 'ok'] ?? 3) - (ALERT_ORDER[b.alert_level ?? 'ok'] ?? 3)
      );
      setItems(sorted);
      setTotal(data.total);
    } catch {
      toast.error('Failed to load compliance items');
    } finally {
      setLoading(false);
    }
  }, [typeFilter]);

  useEffect(() => { fetchItems(); }, [fetchItems]);

  // Fetch thresholds + types + check role on mount
  useEffect(() => {
    api.get<ComplianceThresholds>('/api/v1/compliance/settings/thresholds')
      .then(r => setThresholds(r.data))
      .catch(() => {});
    api.get<string[]>('/api/v1/compliance/settings/types')
      .then(r => setItemTypes(r.data))
      .catch(() => {});
    api.get<{ role: string }>('/api/v1/auth/me')
      .then(r => setIsAdmin(r.data.role === 'admin'))
      .catch(() => {});
  }, []);

  // Reset alert filter when type tab changes
  useEffect(() => { setAlertFilter(null); }, [typeFilter]);

  async function openFile(item: ComplianceItem) {
    if (!item.file_path) {
      toast.error('No file path configured for this item');
      return;
    }
    // Stream the file via authenticated fetch, then open as a blob URL in a new tab.
    // This avoids Windows Session 0 isolation (the backend service cannot open files
    // on the interactive desktop) and keeps the auth token out of the URL.
    setOpeningFile(item.id);
    try {
      const token = sessionStorage.getItem('token');
      const resp = await fetch(`/api/v1/compliance/${item.id}/download`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        toast.error((body as { detail?: string }).detail ?? 'File not found on server');
        return;
      }
      const blob = await resp.blob();
      const blobUrl = URL.createObjectURL(blob);
      window.open(blobUrl, '_blank');
      // Revoke after a short delay so the new tab has time to load
      setTimeout(() => URL.revokeObjectURL(blobUrl), 30_000);
    } catch {
      toast.error('Failed to open file');
    } finally {
      setOpeningFile(null);
    }
  }

  async function deleteFile(item: ComplianceItem) {
    if (!confirm(`Delete the file attached to "${item.name}"? This cannot be undone.`)) return;
    try {
      const resp = await api.delete<ComplianceItem>(`/api/v1/compliance/${item.id}/file`);
      setItems(prev => prev.map(i => i.id === item.id ? resp.data : i));
      toast.success('File deleted');
    } catch {
      toast.error('Failed to delete file');
    }
  }

  async function deleteItem(item: ComplianceItem) {
    if (!confirm(`Archive "${item.name}"? It will be hidden but not permanently deleted.`)) return;
    try {
      await api.delete(`/api/v1/compliance/${item.id}`);
      setItems(prev => prev.filter(i => i.id !== item.id));
      setTotal(t => t - 1);
      toast.success('Item archived');
    } catch {
      toast.error('Failed to archive item');
    }
  }

  function handleSaved(saved: ComplianceItem) {
    setItems(prev => {
      const idx = prev.findIndex(i => i.id === saved.id);
      if (idx >= 0) {
        const updated = [...prev];
        updated[idx] = saved;
        return updated;
      }
      return [saved, ...prev];
    });
    if (!items.find(i => i.id === saved.id)) setTotal(t => t + 1);
    toast.success(editItem ? 'Item updated' : 'Item added');
  }

  // Summary counts
  const expiredCount = items.filter(i => i.alert_level === 'expired').length;
  const criticalCount = items.filter(i => i.alert_level === 'critical').length;
  const warningCount = items.filter(i => i.alert_level === 'warning').length;
  const okCount = items.filter(i => i.alert_level === 'ok').length;

  // Apply alert drill-down filter
  const displayedItems = alertFilter ? items.filter(i => i.alert_level === alertFilter) : items;

  function toggleAlertFilter(level: AlertFilter) {
    setAlertFilter(prev => prev === level ? null : level);
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Compliance</h1>
          <p className="text-sm text-muted-foreground">Insurance, Certifications, Licenses & Permits</p>
        </div>
        <div className="flex gap-2">
          {isAdmin && (
            <>
              <Button variant="outline" size="sm" onClick={() => setManageTypesOpen(true)}>
                <Tag className="h-4 w-4 mr-1" />
                Manage Types
              </Button>
              <Button variant="outline" size="sm" onClick={() => setSettingsOpen(true)}>
                <Settings2 className="h-4 w-4 mr-1" />
                Alert Settings
              </Button>
            </>
          )}
          <Button variant="outline" size="sm" onClick={fetchItems} disabled={loading}>
            <RefreshCw className={`h-4 w-4 mr-1 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
          <Button size="sm" onClick={() => { setEditItem(null); setDialogOpen(true); }}>
            <Plus className="h-4 w-4 mr-1" />
            Add Item
          </Button>
        </div>
      </div>

      {/* Summary Cards — always show all 4 when there's data */}
      {items.length > 0 && (
        <div className="grid grid-cols-4 gap-4">
          {/* Expired */}
          <button
            onClick={() => toggleAlertFilter('expired')}
            className={`text-left rounded-lg border p-4 flex items-center gap-3 transition-all ${
              expiredCount > 0
                ? `border-red-200 bg-red-50 hover:bg-red-100 hover:shadow-md cursor-pointer ${alertFilter === 'expired' ? 'ring-2 ring-red-400' : ''}`
                : 'border-gray-100 bg-gray-50 opacity-50 cursor-default'
            }`}
            disabled={expiredCount === 0}
          >
            <XCircle className={`h-8 w-8 shrink-0 ${expiredCount > 0 ? 'text-red-500' : 'text-gray-300'}`} />
            <div>
              <p className={`text-2xl font-bold ${expiredCount > 0 ? 'text-red-700' : 'text-gray-400'}`}>{expiredCount}</p>
              <p className="text-xs font-medium text-red-600">Expired</p>
            </div>
          </button>

          {/* Critical */}
          <button
            onClick={() => toggleAlertFilter('critical')}
            className={`text-left rounded-lg border p-4 flex items-center gap-3 transition-all ${
              criticalCount > 0
                ? `border-orange-200 bg-orange-50 hover:bg-orange-100 hover:shadow-md cursor-pointer ${alertFilter === 'critical' ? 'ring-2 ring-orange-400' : ''}`
                : 'border-gray-100 bg-gray-50 opacity-50 cursor-default'
            }`}
            disabled={criticalCount === 0}
          >
            <AlertTriangle className={`h-8 w-8 shrink-0 ${criticalCount > 0 ? 'text-orange-500' : 'text-gray-300'}`} />
            <div>
              <p className={`text-2xl font-bold ${criticalCount > 0 ? 'text-orange-700' : 'text-gray-400'}`}>{criticalCount}</p>
              <p className="text-xs font-medium text-orange-600">≤{thresholds.critical_days}d Critical</p>
            </div>
          </button>

          {/* Warning */}
          <button
            onClick={() => toggleAlertFilter('warning')}
            className={`text-left rounded-lg border p-4 flex items-center gap-3 transition-all ${
              warningCount > 0
                ? `border-yellow-200 bg-yellow-50 hover:bg-yellow-100 hover:shadow-md cursor-pointer ${alertFilter === 'warning' ? 'ring-2 ring-yellow-400' : ''}`
                : 'border-gray-100 bg-gray-50 opacity-50 cursor-default'
            }`}
            disabled={warningCount === 0}
          >
            <Clock className={`h-8 w-8 shrink-0 ${warningCount > 0 ? 'text-yellow-500' : 'text-gray-300'}`} />
            <div>
              <p className={`text-2xl font-bold ${warningCount > 0 ? 'text-yellow-700' : 'text-gray-400'}`}>{warningCount}</p>
              <p className="text-xs font-medium text-yellow-600">≤{thresholds.warning_days}d Warning</p>
            </div>
          </button>

          {/* Valid */}
          <button
            onClick={() => toggleAlertFilter('ok')}
            className={`text-left rounded-lg border p-4 flex items-center gap-3 transition-all border-green-200 bg-green-50 hover:bg-green-100 hover:shadow-md cursor-pointer ${alertFilter === 'ok' ? 'ring-2 ring-green-400' : ''}`}
            disabled={okCount === 0}
          >
            <CheckCircle className="h-8 w-8 shrink-0 text-green-500" />
            <div>
              <p className="text-2xl font-bold text-green-700">{okCount}</p>
              <p className="text-xs font-medium text-green-600">All Valid</p>
            </div>
          </button>
        </div>
      )}

      {/* Active filter banner */}
      {alertFilter && (
        <div className="flex items-center gap-2 rounded-md border bg-muted/50 px-3 py-2 text-sm">
          <span className="text-muted-foreground">Showing:</span>
          <span className="font-medium capitalize">{alertFilter === 'ok' ? 'Valid' : alertFilter} items</span>
          <span className="text-muted-foreground">({displayedItems.length} of {items.length})</span>
          <Button
            variant="ghost" size="icon" className="h-5 w-5 ml-auto"
            onClick={() => setAlertFilter(null)}
            title="Clear filter"
          >
            <X className="h-3 w-3" />
          </Button>
        </div>
      )}

      {/* Filter Tabs + Table */}
      <div className="rounded-lg border bg-card">
        <div className="flex items-center gap-2 border-b px-4 py-3">
          <Tabs value={typeFilter} onValueChange={setTypeFilter}>
            <TabsList>
              <TabsTrigger value="all">All ({total})</TabsTrigger>
              {itemTypes.map(t => (
                <TabsTrigger key={t} value={t}>{typeLabel(t)}</TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
        </div>

        <div className="p-4">
          {loading ? (
            <p className="text-center text-sm text-muted-foreground py-8">Loading…</p>
          ) : displayedItems.length === 0 ? (
            <div className="text-center py-12">
              <FileText className="h-10 w-10 text-muted-foreground mx-auto mb-3 opacity-40" />
              <p className="text-sm text-muted-foreground">
                {alertFilter ? `No ${alertFilter === 'ok' ? 'valid' : alertFilter} items found.` : 'No compliance items found.'}
              </p>
              {!alertFilter && <p className="text-xs text-muted-foreground mt-1">Click "Add Item" to get started.</p>}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-xs text-muted-foreground">
                    <th className="px-3 py-2 text-left font-medium w-4"></th>
                    <th className="px-3 py-2 text-left font-medium">Name</th>
                    <th className="px-3 py-2 text-left font-medium">Type</th>
                    <th className="px-3 py-2 text-left font-medium">Policy Holder</th>
                    <th className="px-3 py-2 text-left font-medium">Issuer</th>
                    <th className="px-3 py-2 text-left font-medium">Reference No.</th>
                    <th className="px-3 py-2 text-left font-medium">Issue Date</th>
                    <th className="px-3 py-2 text-left font-medium">Expiry Date</th>
                    <th className="px-3 py-2 text-left font-medium">Status</th>
                    <th className="px-3 py-2 text-right font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {displayedItems.map(item => (
                    <tr key={item.id} className={`hover:bg-muted/30 ${item.alert_level === 'expired' ? 'bg-red-50/50' : ''}`}>
                      <td className="px-3 py-2.5">
                        <StatusDot level={item.alert_level} />
                      </td>
                      <td className="px-3 py-2.5">
                        <p className="font-medium">{item.name}</p>
                        {item.notes && (
                          <p className="text-[11px] text-muted-foreground truncate max-w-[200px]">{item.notes}</p>
                        )}
                      </td>
                      <td className="px-3 py-2.5">
                        <Badge variant="outline" className="text-[10px]">
                          {typeLabel(item.item_type)}
                        </Badge>
                      </td>
                      <td className="px-3 py-2.5 text-muted-foreground">
                        {item.policy_holder ?? '—'}
                      </td>
                      <td className="px-3 py-2.5 text-muted-foreground">{item.issuer ?? '—'}</td>
                      <td className="px-3 py-2.5 font-mono text-xs">{item.reference_no ?? '—'}</td>
                      <td className="px-3 py-2.5 text-muted-foreground">
                        {item.issue_date ? new Date(item.issue_date).toLocaleDateString('en-IN') : '—'}
                      </td>
                      <td className="px-3 py-2.5">
                        {item.expiry_date ? (
                          <span className={item.alert_level === 'expired' ? 'text-red-600 font-medium' : item.alert_level === 'critical' ? 'text-orange-600' : ''}>
                            {new Date(item.expiry_date).toLocaleDateString('en-IN')}
                          </span>
                        ) : '—'}
                      </td>
                      <td className="px-3 py-2.5">
                        {item.alert_level === 'ok' ? (
                          <span className="inline-flex items-center gap-1 text-[10px] text-green-600">
                            <CheckCircle className="h-3 w-3" /> Valid
                          </span>
                        ) : (
                          <AlertBadge level={item.alert_level} days={item.days_to_expiry} />
                        )}
                      </td>
                      <td className="px-3 py-2.5">
                        <div className="flex gap-0.5 justify-end">
                          {item.file_path && (
                            <>
                              <Button
                                size="icon" variant="ghost" className="h-7 w-7"
                                title={`Open: ${item.file_path.split('/').pop()}`}
                                disabled={openingFile === item.id}
                                onClick={() => openFile(item)}
                              >
                                <FolderOpen className="h-3.5 w-3.5 text-blue-600" />
                              </Button>
                              <Button
                                size="icon" variant="ghost" className="h-7 w-7"
                                title="Delete file"
                                onClick={() => deleteFile(item)}
                              >
                                <Trash2 className="h-3.5 w-3.5 text-destructive" />
                              </Button>
                            </>
                          )}
                          <Button
                            size="icon" variant="ghost" className="h-7 w-7"
                            title="Edit"
                            onClick={() => { setEditItem(item); setDialogOpen(true); }}
                          >
                            <Edit2 className="h-3.5 w-3.5" />
                          </Button>
                          <Button
                            size="icon" variant="ghost" className="h-7 w-7"
                            title="Archive"
                            onClick={() => deleteItem(item)}
                          >
                            <Trash2 className="h-3.5 w-3.5 text-red-500" />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      <EditDialog
        open={dialogOpen}
        item={editItem}
        itemTypes={itemTypes}
        onClose={() => { setDialogOpen(false); setEditItem(null); }}
        onSaved={handleSaved}
      />

      <ThresholdSettingsPanel
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        thresholds={thresholds}
        onSaved={t => { setThresholds(t); fetchItems(); }}
      />

      <ManageTypesPanel
        open={manageTypesOpen}
        onClose={() => setManageTypesOpen(false)}
        types={itemTypes}
        onSaved={newTypes => setItemTypes(newTypes)}
      />
    </div>
  );
}
