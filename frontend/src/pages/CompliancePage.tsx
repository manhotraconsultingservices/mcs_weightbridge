import { useEffect, useState, useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import {
  Plus, FolderOpen, Edit2, Trash2, Upload,
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
import { DataTable, type ColumnDef } from '@/components/DataTable';
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

function typeLabel(type: string) {
  return type.charAt(0).toUpperCase() + type.slice(1);
}

// ── Alert helpers ───────────────────────────────────────────────────────── //

function AlertBadge({ level, days }: { level: string | null; days: number | null }) {
  const { t } = useTranslation();
  if (!level || level === 'ok') return null;

  const configs = {
    expired: { color: 'bg-red-100 text-red-700 border-red-200', icon: XCircle, label: t('compliance.alertLevel.expired') },
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

// ── Threshold Settings Panel ─────────────────────────────────────────────── //

interface ThresholdPanelProps {
  open: boolean;
  onClose: () => void;
  thresholds: ComplianceThresholds;
  onSaved: (thresholds: ComplianceThresholds) => void;
}

function ThresholdSettingsPanel({ open, onClose, thresholds, onSaved }: ThresholdPanelProps) {
  const { t } = useTranslation();
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
    if (!w || !c || w < 1 || c < 1) { setError(t('compliance.thresholdValidation')); return; }
    if (c >= w) { setError(t('compliance.thresholdOrderError')); return; }
    setSaving(true); setError('');
    try {
      const { data } = await api.put<ComplianceThresholds>('/api/v1/compliance/settings/thresholds', { warning_days: w, critical_days: c });
      onSaved(data);
      toast.success(t('compliance.thresholdsSaved'));
      onClose();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : t('compliance.thresholdSaveFailed'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Sheet open={open} onOpenChange={prev => !prev && onClose()}>
      <SheetContent side="right" className="w-80">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">
            <Settings2 className="h-4 w-4" />
            {t('compliance.alertThresholds')}
          </SheetTitle>
        </SheetHeader>

        <div className="mt-6 space-y-5">
          <p className="text-sm text-muted-foreground">
            {t('compliance.thresholdDesc')} <span className="text-yellow-600 font-medium">{t('compliance.alertLevel.warning')}</span> {t('compliance.thresholdOr')} <span className="text-orange-600 font-medium">{t('compliance.alertLevel.critical')}</span>.
          </p>

          {error && <p className="rounded bg-destructive/10 p-2 text-sm text-destructive">{error}</p>}

          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label className="text-yellow-700">{t('compliance.warningThresholdLabel')}</Label>
              <Input
                type="number" min={1} max={365}
                value={form.warning_days}
                onChange={e => setForm(prev => ({ ...prev, warning_days: e.target.value }))}
                className="border-yellow-300 focus-visible:ring-yellow-400"
              />
              <p className="text-[11px] text-muted-foreground">{t('compliance.warningThresholdHint')}</p>
            </div>

            <div className="space-y-1.5">
              <Label className="text-orange-700">{t('compliance.criticalThresholdLabel')}</Label>
              <Input
                type="number" min={1} max={365}
                value={form.critical_days}
                onChange={e => setForm(prev => ({ ...prev, critical_days: e.target.value }))}
                className="border-orange-300 focus-visible:ring-orange-400"
              />
              <p className="text-[11px] text-muted-foreground">{t('compliance.criticalThresholdHint')}</p>
            </div>
          </div>

          <div className="rounded-md border bg-muted/40 p-3 text-xs text-muted-foreground space-y-1">
            <p className="font-medium text-foreground">{t('compliance.alertLevelsTitle')}</p>
            <p><span className="text-red-600 font-medium">{t('compliance.alertLevelExpiredLabel')}</span> — {t('compliance.alertLevelExpiredDesc')}</p>
            <p><span className="text-orange-600 font-medium">{t('compliance.alertLevelCriticalLabel')}</span> — {t('compliance.alertLevelCriticalDesc', { days: form.critical_days || '?' })}</p>
            <p><span className="text-yellow-600 font-medium">{t('compliance.alertLevelWarningLabel')}</span> — {t('compliance.alertLevelWarningDesc', { days: form.warning_days || '?' })}</p>
            <p><span className="text-green-600 font-medium">{t('compliance.alertLevelValidLabel')}</span> — {t('compliance.alertLevelValidDesc', { days: form.warning_days || '?' })}</p>
          </div>

          <div className="flex gap-2">
            <Button variant="outline" onClick={onClose} disabled={saving} className="flex-1">{t('compliance.cancel')}</Button>
            <Button onClick={handleSave} disabled={saving} className="flex-1">
              {saving ? t('compliance.saving') : t('compliance.save')}
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
  const { t } = useTranslation();
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
    if (list.includes(val)) { setError(t('compliance.typeAlreadyExists')); return; }
    setList(prev => [...prev, val]);
    setNewType('');
    setError('');
  }

  function removeType(typeVal: string) {
    setList(prev => prev.filter(x => x !== typeVal));
  }

  async function handleSave() {
    if (list.length === 0) { setError(t('compliance.atLeastOneType')); return; }
    setSaving(true); setError('');
    try {
      const { data } = await api.put<string[]>('/api/v1/compliance/settings/types', list);
      onSaved(data);
      toast.success(t('compliance.typesSaved'));
      onClose();
    } catch {
      setError(t('compliance.typesSaveFailed'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Sheet open={open} onOpenChange={prev => !prev && onClose()}>
      <SheetContent side="right" className="w-80">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">
            <Tag className="h-4 w-4" />
            {t('compliance.manageTypes')}
          </SheetTitle>
        </SheetHeader>

        <div className="mt-6 space-y-5">
          <p className="text-sm text-muted-foreground">
            {t('compliance.manageTypesDesc')}
          </p>

          {error && <p className="rounded bg-destructive/10 p-2 text-sm text-destructive">{error}</p>}

          {/* Existing types */}
          <div className="space-y-2">
            {list.map(typeVal => (
              <div key={typeVal} className="flex items-center justify-between rounded-md border bg-muted/30 px-3 py-2">
                <span className="text-sm font-medium capitalize">{typeLabel(typeVal)}</span>
                <button
                  type="button"
                  onClick={() => removeType(typeVal)}
                  className="text-muted-foreground hover:text-destructive transition-colors"
                  title={t('compliance.remove')}
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            ))}
            {list.length === 0 && (
              <p className="text-xs text-muted-foreground text-center py-2">{t('compliance.noTypesYet')}</p>
            )}
          </div>

          {/* Add new type */}
          <div className="space-y-1.5">
            <Label className="text-xs">{t('compliance.addNewType')}</Label>
            <div className="flex gap-2">
              <Input
                className="h-8 text-sm"
                placeholder={t('compliance.addNewTypePlaceholder')}
                value={newType}
                onChange={e => setNewType(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && addType()}
              />
              <Button size="sm" variant="outline" onClick={addType} className="h-8 shrink-0">{t('compliance.add')}</Button>
            </div>
            <p className="text-[11px] text-muted-foreground">{t('compliance.addNewTypeHint')}</p>
          </div>

          <div className="flex gap-2 pt-2">
            <Button variant="outline" onClick={onClose} disabled={saving} className="flex-1">{t('compliance.cancel')}</Button>
            <Button onClick={handleSave} disabled={saving} className="flex-1">
              {saving ? t('compliance.saving') : t('compliance.saveTypes')}
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
  const { t } = useTranslation();
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
    if (!form.name.trim()) { setError(t('compliance.nameRequired')); return; }
    if (!form.policy_holder.trim()) { setError(t('compliance.policyHolderRequired')); return; }
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
          toast.error(typeof detail === 'string' ? detail : t('compliance.fileUploadFailed'));
        } finally {
          setUploading(false);
        }
      }

      onSaved(resp.data);
      onClose();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : t('compliance.saveFailed'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={prev => !prev && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{item ? t('compliance.editDialogTitle') : t('compliance.addDialogTitle')}</DialogTitle>
        </DialogHeader>

        <div className="space-y-3">
          {error && <p className="rounded bg-destructive/10 p-2 text-sm text-destructive">{error}</p>}

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>{t('compliance.typeLabel')} <span className="text-destructive">*</span></Label>
              <Select value={form.item_type} onValueChange={v => setForm(prev => ({ ...prev, item_type: v ?? itemTypes[0] }))}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {itemTypes.map(typeVal => <SelectItem key={typeVal} value={typeVal}>{typeLabel(typeVal)}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label>{t('compliance.name')} <span className="text-destructive">*</span></Label>
              <Input value={form.name} onChange={e => setForm(prev => ({ ...prev, name: e.target.value }))}
                placeholder="e.g. Vehicle Insurance – MH-12-AB-1234" />
            </div>
          </div>

          <div className="space-y-1">
            <Label>{t('compliance.policyHolder')} <span className="text-destructive">*</span></Label>
            <Input value={form.policy_holder} onChange={e => setForm(prev => ({ ...prev, policy_holder: e.target.value }))}
              placeholder={t('compliance.policyHolderPlaceholder')} />
            <p className="text-[11px] text-muted-foreground">{t('compliance.policyHolderHint')}</p>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>{t('compliance.issuingAuthority')}</Label>
              <Input value={form.issuer} onChange={e => setForm(prev => ({ ...prev, issuer: e.target.value }))}
                placeholder={t('compliance.issuingAuthorityPlaceholder')} />
            </div>
            <div className="space-y-1">
              <Label>{t('compliance.policyCertNo')}</Label>
              <Input value={form.reference_no} onChange={e => setForm(prev => ({ ...prev, reference_no: e.target.value }))}
                placeholder={t('compliance.policyCertNoPlaceholder')} />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>{t('compliance.issueDate')}</Label>
              <Input type="date" value={form.issue_date} onChange={e => setForm(prev => ({ ...prev, issue_date: e.target.value }))} />
            </div>
            <div className="space-y-1">
              <Label>{t('compliance.expiryDate')}</Label>
              <Input type="date" value={form.expiry_date} onChange={e => setForm(prev => ({ ...prev, expiry_date: e.target.value }))} />
            </div>
          </div>

          <div className="space-y-1">
            <Label>{t('compliance.uploadDocument')}</Label>
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
                    {t('compliance.uploadCurrent')} <span className="font-medium">{item.file_path.split('/').pop()}</span> — {t('compliance.uploadReplaceHint')}
                  </p>
                ) : (
                  <p className="text-sm text-muted-foreground">{t('compliance.uploadDropHint')}</p>
                )}
              </div>
              <input type="file" className="hidden" accept=".pdf,.jpg,.jpeg,.png,.doc,.docx,.xls,.xlsx,.tif,.tiff"
                onChange={e => { const f = e.target.files?.[0]; if (f) setSelectedFile(f); e.target.value = ''; }} />
            </label>
          </div>

          <div className="space-y-1">
            <Label>{t('compliance.notes')}</Label>
            <Input value={form.notes} onChange={e => setForm(prev => ({ ...prev, notes: e.target.value }))}
              placeholder={t('compliance.notesPlaceholder')} />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={saving || uploading}>{t('compliance.cancel')}</Button>
          <Button onClick={handleSave} disabled={saving || uploading}>
            {uploading ? t('compliance.uploading') : saving ? t('compliance.saving') : (item ? t('compliance.update') : t('compliance.add'))}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Main Page ───────────────────────────────────────────────────────────── //

export default function CompliancePage() {
  const { t } = useTranslation();
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
      toast.error(t('compliance.loadFailed'));
    } finally {
      setLoading(false);
    }
  }, [typeFilter, t]);

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
      toast.error(t('compliance.noFilePath'));
      return;
    }
    setOpeningFile(item.id);
    try {
      const token = sessionStorage.getItem('token');
      const resp = await fetch(`/api/v1/compliance/${item.id}/download`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        toast.error((body as { detail?: string }).detail ?? t('compliance.fileNotFound'));
        return;
      }
      const blob = await resp.blob();
      const blobUrl = URL.createObjectURL(blob);
      window.open(blobUrl, '_blank');
      setTimeout(() => URL.revokeObjectURL(blobUrl), 30_000);
    } catch {
      toast.error(t('compliance.fileOpenFailed'));
    } finally {
      setOpeningFile(null);
    }
  }

  async function deleteFile(item: ComplianceItem) {
    if (!confirm(t('compliance.confirmDeleteFile', { name: item.name }))) return;
    try {
      const resp = await api.delete<ComplianceItem>(`/api/v1/compliance/${item.id}/file`);
      setItems(prev => prev.map(i => i.id === item.id ? resp.data : i));
      toast.success(t('compliance.fileDeleted'));
    } catch {
      toast.error(t('compliance.fileDeleteFailed'));
    }
  }

  async function deleteItem(item: ComplianceItem) {
    if (!confirm(t('compliance.confirmArchive', { name: item.name }))) return;
    try {
      await api.delete(`/api/v1/compliance/${item.id}`);
      setItems(prev => prev.filter(i => i.id !== item.id));
      setTotal(prev => prev - 1);
      toast.success(t('compliance.itemArchived'));
    } catch {
      toast.error(t('compliance.itemArchiveFailed'));
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
    if (!items.find(i => i.id === saved.id)) setTotal(prev => prev + 1);
    toast.success(editItem ? t('compliance.itemUpdated') : t('compliance.itemAdded'));
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
          <h1 className="text-2xl font-semibold tracking-tight">{t('compliance.title')}</h1>
          <p className="text-sm text-muted-foreground">{t('compliance.subtitle')}</p>
        </div>
        <div className="flex gap-2">
          {isAdmin && (
            <>
              <Button variant="outline" size="sm" onClick={() => setManageTypesOpen(true)}>
                <Tag className="h-4 w-4 mr-1" />
                {t('compliance.manageTypes')}
              </Button>
              <Button variant="outline" size="sm" onClick={() => setSettingsOpen(true)}>
                <Settings2 className="h-4 w-4 mr-1" />
                {t('compliance.configureThresholds')}
              </Button>
            </>
          )}
          <Button variant="outline" size="sm" onClick={fetchItems} disabled={loading}>
            <RefreshCw className={`h-4 w-4 mr-1 ${loading ? 'animate-spin' : ''}`} />
            {t('compliance.refresh')}
          </Button>
          <Button size="sm" onClick={() => { setEditItem(null); setDialogOpen(true); }}>
            <Plus className="h-4 w-4 mr-1" />
            {t('compliance.addItem')}
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
              <p className="text-xs font-medium text-red-600">{t('compliance.alertLevel.expired')}</p>
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
              <p className="text-xs font-medium text-orange-600">{t('compliance.criticalBadge', { days: thresholds.critical_days })}</p>
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
              <p className="text-xs font-medium text-yellow-600">{t('compliance.warningBadge', { days: thresholds.warning_days })}</p>
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
              <p className="text-xs font-medium text-green-600">{t('compliance.validItems')}</p>
            </div>
          </button>
        </div>
      )}

      {/* Active filter banner */}
      {alertFilter && (
        <div className="flex items-center gap-2 rounded-md border bg-muted/50 px-3 py-2 text-sm">
          <span className="text-muted-foreground">{t('compliance.showingFilter')}</span>
          <span className="font-medium capitalize">
            {alertFilter === 'ok' ? t('compliance.validLabel') : t(`compliance.alertLevel.${alertFilter}` as Parameters<typeof t>[0])}
          </span>
          <span className="text-muted-foreground">{t('compliance.showingOf', { shown: displayedItems.length, total: items.length })}</span>
          <Button
            variant="ghost" size="icon" className="h-5 w-5 ml-auto"
            onClick={() => setAlertFilter(null)}
            title={t('compliance.clearFilter')}
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
              <TabsTrigger value="all">{t('compliance.allTab', { total })}</TabsTrigger>
              {itemTypes.map(typeVal => (
                <TabsTrigger key={typeVal} value={typeVal}>{typeLabel(typeVal)}</TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
        </div>

        <div className="p-4">
          <ComplianceTable
            items={displayedItems}
            loading={loading}
            itemTypes={itemTypes}
            openingFile={openingFile}
            onOpenFile={openFile}
            onDeleteFile={deleteFile}
            onEdit={item => { setEditItem(item); setDialogOpen(true); }}
            onArchive={deleteItem}
            emptyMessage={alertFilter
              ? t('compliance.noFilteredItems', { level: alertFilter === 'ok' ? t('compliance.validLabel') : alertFilter })
              : t('compliance.noComplianceItems')}
          />
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
        onSaved={saved => { setThresholds(saved); fetchItems(); }}
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

// ------------------------------------------------------------------ //
// Compliance DataTable
// ------------------------------------------------------------------ //
function ComplianceTable({
  items, loading, itemTypes, openingFile, onOpenFile, onDeleteFile, onEdit, onArchive, emptyMessage,
}: {
  items: ComplianceItem[];
  loading: boolean;
  itemTypes: string[];
  openingFile: string | null;
  onOpenFile: (item: ComplianceItem) => void;
  onDeleteFile: (item: ComplianceItem) => void;
  onEdit: (item: ComplianceItem) => void;
  onArchive: (item: ComplianceItem) => void;
  emptyMessage: string;
}) {
  const { t } = useTranslation();
  const columns = useMemo<ColumnDef<ComplianceItem>[]>(() => [
    { key: 'name', label: t('compliance.colName'), accessor: i => i.name, className: 'font-medium' },
    {
      key: 'item_type', label: t('compliance.colType'), type: 'enum',
      enumOptions: itemTypes,
      accessor: i => i.item_type,
      format: v => <Badge variant="outline" className="text-[10px]">{typeLabel(String(v))}</Badge>,
    },
    { key: 'policy_holder', label: t('compliance.colPolicyHolder'), accessor: i => i.policy_holder ?? '', className: 'text-muted-foreground' },
    { key: 'issuer', label: t('compliance.colIssuer'), accessor: i => i.issuer ?? '', className: 'text-muted-foreground' },
    { key: 'reference_no', label: t('compliance.colReferenceNo'), accessor: i => i.reference_no ?? '', className: 'font-mono text-xs' },
    {
      key: 'issue_date', label: t('compliance.colIssueDate'), type: 'date',
      defaultVisible: false,
      accessor: i => i.issue_date ?? '',
      format: v => v ? new Date(String(v)).toLocaleDateString('en-IN') : '—',
      className: 'text-muted-foreground',
    },
    {
      key: 'expiry_date', label: t('compliance.colExpiryDate'), type: 'date',
      accessor: i => i.expiry_date ?? '',
      format: (v, item) => v ? (
        <span className={item.alert_level === 'expired' ? 'text-red-600 font-medium' : item.alert_level === 'critical' ? 'text-orange-600' : ''}>
          {new Date(String(v)).toLocaleDateString('en-IN')}
        </span>
      ) : '—',
    },
    {
      key: 'alert_level', label: t('compliance.colStatus'), type: 'enum',
      enumOptions: ['ok', 'warning', 'critical', 'expired'],
      accessor: i => i.alert_level,
      format: (v, item) => v === 'ok' ? (
        <span className="inline-flex items-center gap-1 text-[10px] text-green-600">
          <CheckCircle className="h-3 w-3" /> {t('compliance.validLabel')}
        </span>
      ) : <AlertBadge level={item.alert_level} days={item.days_to_expiry} />,
    },
    { key: 'notes', label: t('compliance.colNotes'), defaultVisible: false, accessor: i => i.notes ?? '' },
  ], [itemTypes, t]);

  return (
    <DataTable<ComplianceItem>
      id="compliance.items"
      loading={loading}
      data={items}
      columns={columns}
      rowKey={i => i.id}
      exportFilename="compliance-items"
      defaultSort={{ key: 'expiry_date', direction: 'asc' }}
      emptyMessage={emptyMessage}
      rowActions={item => (
        <div className="flex gap-0.5 justify-end">
          {item.file_path && (
            <>
              <Button size="icon" variant="ghost" className="h-7 w-7"
                title={t('compliance.openFile', { filename: item.file_path.split('/').pop() })}
                disabled={openingFile === item.id}
                onClick={() => onOpenFile(item)}>
                <FolderOpen className="h-3.5 w-3.5 text-blue-600" />
              </Button>
              <Button size="icon" variant="ghost" className="h-7 w-7" title={t('compliance.deleteFile')}
                onClick={() => onDeleteFile(item)}>
                <Trash2 className="h-3.5 w-3.5 text-destructive" />
              </Button>
            </>
          )}
          <Button size="icon" variant="ghost" className="h-7 w-7" title={t('compliance.edit')}
            onClick={() => onEdit(item)}>
            <Edit2 className="h-3.5 w-3.5" />
          </Button>
          <Button size="icon" variant="ghost" className="h-7 w-7" title={t('compliance.archive')}
            onClick={() => onArchive(item)}>
            <Trash2 className="h-3.5 w-3.5 text-red-500" />
          </Button>
        </div>
      )}
    />
  );
}
