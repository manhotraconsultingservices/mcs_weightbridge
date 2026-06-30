import { useEffect, useState, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { MobileTabSelect } from '@/components/MobileTabSelect';
import { Plus, Search, Pencil, Loader2, Truck, Settings2, X, Check } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import api from '@/services/api';
import type { Vehicle } from '@/types';

interface Driver {
  id: string;
  name: string;
  license_no: string | null;
  phone: string | null;
  is_active: boolean;
}

interface Transporter {
  id: string;
  name: string;
  gstin: string | null;
  phone: string | null;
  is_active: boolean;
}


// ------------------------------------------------------------------ //
// Vehicle Type Manager Dialog (Admin only)
// ------------------------------------------------------------------ //
function VehicleTypeManagerDialog({ open, types, onClose, onSaved }: {
  open: boolean; types: string[];
  onClose: () => void; onSaved: (types: string[]) => void;
}) {
  const { t } = useTranslation();
  const [items, setItems] = useState<string[]>([]);
  const [newType, setNewType] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (open) { setItems([...types]); setNewType(''); setError(''); }
  }, [open, types]);

  const addType = () => {
    const val = newType.trim().toLowerCase().replace(/\s+/g, '_');
    if (!val) return;
    if (items.includes(val)) { setError(t('vehicle.typeAlreadyExists', { val })); return; }
    setItems(prev => [...prev, val]);
    setNewType('');
    setError('');
  };

  const removeType = (item: string) => {
    if (items.length <= 1) { setError(t('vehicle.atLeastOneType')); return; }
    setItems(prev => prev.filter(x => x !== item));
  };

  async function handleSave() {
    setSaving(true); setError('');
    try {
      const { data } = await api.put<string[]>('/api/v1/app-settings/vehicle-types', items);
      onSaved(data);
      onClose();
    } catch {
      setError(t('vehicle.failedSaveTypes'));
    } finally { setSaving(false); }
  }

  const fmt = (item: string) => item.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());

  return (
    <Dialog open={open} onOpenChange={v => !v && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader><DialogTitle>{t('vehicle.manageTypes')}</DialogTitle></DialogHeader>
        <div className="space-y-4">
          {error && <p className="rounded bg-destructive/10 p-2 text-sm text-destructive">{error}</p>}
          <div className="flex flex-wrap gap-2">
            {items.map(item => (
              <Badge key={item} variant="secondary" className="gap-1 text-sm py-1 px-3">
                {fmt(item)}
                <button onClick={() => removeType(item)} className="ml-1 hover:text-destructive">
                  <X className="h-3 w-3" />
                </button>
              </Badge>
            ))}
          </div>
          <div className="flex gap-2">
            <Input placeholder={t('vehicle.newTypePlaceholder')} value={newType}
              onChange={e => setNewType(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), addType())} />
            <Button variant="outline" size="icon" onClick={addType} disabled={!newType.trim()}>
              <Plus className="h-4 w-4" />
            </Button>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>{t('common.cancel')}</Button>
          <Button onClick={handleSave} disabled={saving || items.length === 0}>
            {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Check className="mr-2 h-4 w-4" />}
            {t('vehicle.saveTypes')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ------------------------------------------------------------------ //
// Vehicle Dialog
// ------------------------------------------------------------------ //
function VehicleDialog({ open, editing, vehicleTypes, onClose, onSaved }: {
  open: boolean; editing: Vehicle | null; vehicleTypes: string[];
  onClose: () => void; onSaved: (v: Vehicle) => void;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState({
    registration_no: '', vehicle_type: 'truck', owner_name: '', owner_phone: '',
    default_tare_weight: 0,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (open) {
      setForm(editing ? {
        registration_no: editing.registration_no,
        vehicle_type: editing.vehicle_type ?? 'truck',
        owner_name: editing.owner_name ?? '',
        owner_phone: editing.owner_phone ?? '',
        default_tare_weight: editing.default_tare_weight,
      } : { registration_no: '', vehicle_type: 'truck', owner_name: '', owner_phone: '', default_tare_weight: 0 });
      setError('');
    }
  }, [open, editing]);

  const set = (k: string, v: unknown) => setForm(f => ({ ...f, [k]: v }));

  async function handleSubmit() {
    if (!form.registration_no.trim()) { setError(t('vehicle.regRequired')); return; }
    setSaving(true); setError('');
    try {
      const url = editing ? `/api/v1/vehicles/${editing.id}` : '/api/v1/vehicles';
      const method = editing ? 'put' : 'post';
      const { data } = await api[method]<Vehicle>(url, {
        ...form,
        registration_no: form.registration_no.toUpperCase().trim(),
      });
      onSaved(data);
      onClose();
    } catch {
      setError(t('vehicle.failedSaveVehicle'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={v => !v && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader><DialogTitle>{editing ? t('vehicle.editVehicle') : t('vehicle.addVehicle')}</DialogTitle></DialogHeader>
        <div className="space-y-4">
          {error && <p className="rounded bg-destructive/10 p-2 text-sm text-destructive">{error}</p>}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>{t('vehicle.regNoLabel')}</Label>
              <Input value={form.registration_no} onChange={e => set('registration_no', e.target.value.toUpperCase())} placeholder="MH12AB1234" />
            </div>
            <div className="space-y-1">
              <Label>{t('vehicle.type')}</Label>
              <Select value={form.vehicle_type} onValueChange={v => set('vehicle_type', v)}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {vehicleTypes.map(vt => (
                    <SelectItem key={vt} value={vt}>
                      {vt.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>{t('vehicle.ownerName')}</Label>
              <Input value={form.owner_name} onChange={e => set('owner_name', e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label>{t('vehicle.ownerPhone')}</Label>
              <Input value={form.owner_phone} onChange={e => set('owner_phone', e.target.value)} />
            </div>
          </div>
          <div className="space-y-1">
            <Label>{t('vehicle.defaultTareMt')}</Label>
            <Input
              type="number" min="0" step="0.001"
              value={form.default_tare_weight ? (Number(form.default_tare_weight) / 1000).toString() : ''}
              onChange={e => set('default_tare_weight', (parseFloat(e.target.value) || 0) * 1000)}
              placeholder="0.000"
            />
            <p className="text-[10px] text-muted-foreground">
              {t('vehicle.defaultTareHint')}
            </p>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>{t('common.cancel')}</Button>
          <Button onClick={handleSubmit} disabled={saving}>
            {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {editing ? t('vehicle.updateVehicle') : t('vehicle.addVehicle')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ------------------------------------------------------------------ //
// Driver Dialog
// ------------------------------------------------------------------ //
function DriverDialog({ open, editing, onClose, onSaved }: {
  open: boolean; editing: Driver | null;
  onClose: () => void; onSaved: (d: Driver) => void;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState({ name: '', license_no: '', phone: '', aadhaar_no: '' });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) setForm(editing ? { name: editing.name, license_no: editing.license_no ?? '', phone: editing.phone ?? '', aadhaar_no: '' } : { name: '', license_no: '', phone: '', aadhaar_no: '' });
  }, [open, editing]);

  const set = (k: string, v: string) => setForm(f => ({ ...f, [k]: v }));

  async function handleSubmit() {
    if (!form.name.trim()) return;
    setSaving(true);
    try {
      const url = editing ? `/api/v1/drivers/${editing.id}` : '/api/v1/drivers';
      const { data } = await api[editing ? 'put' : 'post']<Driver>(url, form);
      onSaved(data);
      onClose();
    } catch { } finally { setSaving(false); }
  }

  return (
    <Dialog open={open} onOpenChange={v => !v && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader><DialogTitle>{editing ? t('vehicle.editDriver') : t('vehicle.addDriver')}</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1"><Label>{t('vehicle.nameRequired')}</Label><Input value={form.name} onChange={e => set('name', e.target.value)} /></div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="space-y-1"><Label>{t('vehicle.licenseNo')}</Label><Input value={form.license_no} onChange={e => set('license_no', e.target.value.toUpperCase())} /></div>
            <div className="space-y-1"><Label>{t('party.phone')}</Label><Input value={form.phone} onChange={e => set('phone', e.target.value)} /></div>
          </div>
          <div className="space-y-1"><Label>{t('vehicle.aadhaarNo')}</Label><Input value={form.aadhaar_no} onChange={e => set('aadhaar_no', e.target.value)} maxLength={12} /></div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>{t('common.cancel')}</Button>
          <Button onClick={handleSubmit} disabled={saving}>
            {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {editing ? t('vehicle.updateDriver') : t('vehicle.addDriver')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ------------------------------------------------------------------ //
// Transporter Dialog
// ------------------------------------------------------------------ //
function TransporterDialog({ open, editing, onClose, onSaved }: {
  open: boolean; editing: Transporter | null;
  onClose: () => void; onSaved: (tr: Transporter) => void;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState({ name: '', gstin: '', phone: '', address: '' });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) setForm(editing ? { name: editing.name, gstin: editing.gstin ?? '', phone: editing.phone ?? '', address: '' } : { name: '', gstin: '', phone: '', address: '' });
  }, [open, editing]);

  const set = (k: string, v: string) => setForm(f => ({ ...f, [k]: v }));

  async function handleSubmit() {
    if (!form.name.trim()) return;
    setSaving(true);
    try {
      const url = editing ? `/api/v1/transporters/${editing.id}` : '/api/v1/transporters';
      const { data } = await api[editing ? 'put' : 'post']<Transporter>(url, form);
      onSaved(data);
      onClose();
    } catch { } finally { setSaving(false); }
  }

  return (
    <Dialog open={open} onOpenChange={v => !v && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader><DialogTitle>{editing ? t('vehicle.editTransporter') : t('vehicle.addTransporter')}</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1"><Label>{t('vehicle.nameRequired')}</Label><Input value={form.name} onChange={e => set('name', e.target.value)} /></div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="space-y-1"><Label>{t('party.gstin')}</Label><Input value={form.gstin} onChange={e => set('gstin', e.target.value.toUpperCase())} maxLength={15} /></div>
            <div className="space-y-1"><Label>{t('party.phone')}</Label><Input value={form.phone} onChange={e => set('phone', e.target.value)} /></div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>{t('common.cancel')}</Button>
          <Button onClick={handleSubmit} disabled={saving}>
            {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {editing ? t('vehicle.updateTransporter') : t('vehicle.addTransporter')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ------------------------------------------------------------------ //
// Main Page
// ------------------------------------------------------------------ //
const VEH_PAGE_SIZE = 50;

export default function VehiclesPage() {
  const { t } = useTranslation();
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [vehicleTotal, setVehicleTotal] = useState(0);
  const [vehiclePage, setVehiclePage] = useState(1);
  const [drivers, setDrivers] = useState<Driver[]>([]);
  const [driverTotal, setDriverTotal] = useState(0);
  const [driverPage, setDriverPage] = useState(1);
  const [transporters, setTransporters] = useState<Transporter[]>([]);
  const [transporterTotal, setTransporterTotal] = useState(0);
  const [transporterPage, setTransporterPage] = useState(1);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState('vehicles');

  const [vDialog, setVDialog] = useState(false);
  const [dDialog, setDDialog] = useState(false);
  const [tDialog, setTDialog] = useState(false);
  const [editV, setEditV] = useState<Vehicle | null>(null);
  const [editD, setEditD] = useState<Driver | null>(null);
  const [editT, setEditT] = useState<Transporter | null>(null);

  // Vehicle types (admin-configurable)
  const [vehicleTypes, setVehicleTypes] = useState<string[]>([]);
  const [typeDialog, setTypeDialog] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);

  // Fetch vehicle types + admin role on mount
  useEffect(() => {
    api.get<string[]>('/api/v1/app-settings/vehicle-types')
      .then(r => setVehicleTypes(r.data))
      .catch(() => setVehicleTypes(['truck', 'tractor', 'trailer', 'tipper', 'mini_truck', 'tanker', 'dumper']));
    api.get<{ role: string }>('/api/v1/auth/me')
      .then(r => setIsAdmin(r.data.role === 'admin'))
      .catch(() => {});
  }, []);

  const fetch = useCallback(async () => {
    setLoading(true);
    try {
      const vParams = new URLSearchParams({ page: String(vehiclePage), page_size: String(VEH_PAGE_SIZE) });
      if (search) vParams.set('search', search);
      const dParams = new URLSearchParams({ page: String(driverPage), page_size: String(VEH_PAGE_SIZE) });
      if (search) dParams.set('search', search);
      const tParams = new URLSearchParams({ page: String(transporterPage), page_size: String(VEH_PAGE_SIZE) });
      if (search) tParams.set('search', search);
      const [vRes, dRes, tRes] = await Promise.all([
        api.get<{ items: Vehicle[]; total: number } | Vehicle[]>(`/api/v1/vehicles?${vParams}`),
        api.get<{ items: Driver[]; total: number } | Driver[]>(`/api/v1/drivers?${dParams}`),
        api.get<{ items: Transporter[]; total: number } | Transporter[]>(`/api/v1/transporters?${tParams}`),
      ]);
      if (Array.isArray(vRes.data)) { setVehicles(vRes.data); setVehicleTotal(vRes.data.length); }
      else { setVehicles(vRes.data.items ?? []); setVehicleTotal(vRes.data.total ?? 0); }
      if (Array.isArray(dRes.data)) { setDrivers(dRes.data); setDriverTotal(dRes.data.length); }
      else { setDrivers(dRes.data.items ?? []); setDriverTotal(dRes.data.total ?? 0); }
      if (Array.isArray(tRes.data)) { setTransporters(tRes.data); setTransporterTotal(tRes.data.length); }
      else { setTransporters(tRes.data.items ?? []); setTransporterTotal(tRes.data.total ?? 0); }
    } catch { } finally { setLoading(false); }
  }, [search, vehiclePage, driverPage, transporterPage]);

  useEffect(() => { fetch(); }, [fetch]);
  useEffect(() => { setVehiclePage(1); setDriverPage(1); setTransporterPage(1); }, [search]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">{t('vehicle.vehiclesTransport')}</h1>
          <p className="text-muted-foreground">{t('vehicle.subtitle')}</p>
        </div>
        {tab === 'vehicles' && (
          <div className="flex gap-2">
            {isAdmin && (
              <Button variant="outline" size="icon" onClick={() => setTypeDialog(true)} title={t('vehicle.manageTypes')}>
                <Settings2 className="h-4 w-4" />
              </Button>
            )}
            <Button onClick={() => { setEditV(null); setVDialog(true); }}>
              <Plus className="mr-2 h-4 w-4" /> {t('vehicle.addVehicle')}
            </Button>
          </div>
        )}
        {tab === 'drivers' && (
          <Button onClick={() => { setEditD(null); setDDialog(true); }}>
            <Plus className="mr-2 h-4 w-4" /> {t('vehicle.addDriver')}
          </Button>
        )}
        {tab === 'transporters' && (
          <Button onClick={() => { setEditT(null); setTDialog(true); }}>
            <Plus className="mr-2 h-4 w-4" /> {t('vehicle.addTransporter')}
          </Button>
        )}
      </div>

      <div className="relative max-w-xs">
        <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
        <Input className="pl-9" placeholder={t('common.search')} value={search}
          onChange={e => setSearch(e.target.value)} />
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <MobileTabSelect value={tab} onValueChange={setTab} options={[{ value: 'vehicles', label: `${t('vehicle.tabVehicles')} (${vehicleTotal})` }, { value: 'drivers', label: `${t('vehicle.tabDrivers')} (${driverTotal})` }, { value: 'transporters', label: `${t('vehicle.tabTransporters')} (${transporterTotal})` }]} />
        <TabsList className="hidden sm:inline-flex flex-wrap h-auto">
          <TabsTrigger value="vehicles">{t('vehicle.tabVehicles')} ({vehicleTotal})</TabsTrigger>
          <TabsTrigger value="drivers">{t('vehicle.tabDrivers')} ({driverTotal})</TabsTrigger>
          <TabsTrigger value="transporters">{t('vehicle.tabTransporters')} ({transporterTotal})</TabsTrigger>
        </TabsList>

        {/* Vehicles */}
        <TabsContent value="vehicles">
          <Card>
            <CardContent className="p-0">
              {loading ? (
                <div className="flex justify-center py-10"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
              ) : vehicles.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-16 px-4 text-center">
                  <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-muted">
                    <Truck className="h-8 w-8 text-muted-foreground/40" />
                  </div>
                  <h3 className="text-sm font-semibold">{t('vehicle.noVehicles')}</h3>
                  <p className="mt-1 max-w-xs text-xs text-muted-foreground">
                    {t('vehicle.noVehiclesHint')}
                  </p>
                </div>
              ) : (
                <div className="divide-y">
                  {vehicles.map(v => (
                    <div key={v.id} className="flex items-center gap-4 px-4 py-3 hover:bg-muted/30">
                      <Truck className="h-5 w-5 text-muted-foreground shrink-0" />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <p className="font-medium text-sm">{v.registration_no}</p>
                          {v.vehicle_type && (
                            <Badge variant="outline" className="text-[10px] capitalize">
                              {v.vehicle_type.replace(/_/g, ' ')}
                            </Badge>
                          )}
                        </div>
                        <p className="text-xs text-muted-foreground">
                          {v.owner_name ? v.owner_name : ''}
                        </p>
                      </div>
                      <div className="text-right">
                        <p className="text-xs text-muted-foreground">{t('vehicle.tare')}</p>
                        <p className="text-sm font-mono">{(Number(v.default_tare_weight) / 1000).toLocaleString('en-IN', { minimumFractionDigits: 3, maximumFractionDigits: 3 })} MT</p>
                      </div>
                      <Button size="icon" variant="ghost" onClick={() => { setEditV(v); setVDialog(true); }}>
                        <Pencil className="h-4 w-4" />
                      </Button>
                    </div>
                  ))}
                </div>
              )}
              {vehicleTotal > VEH_PAGE_SIZE && (
                <div className="flex items-center justify-between px-4 py-3 border-t text-sm">
                  <span className="text-muted-foreground">
                    {t('vehicle.showing', { from: (vehiclePage - 1) * VEH_PAGE_SIZE + 1, to: Math.min(vehiclePage * VEH_PAGE_SIZE, vehicleTotal), total: vehicleTotal })}
                  </span>
                  <div className="flex gap-2">
                    <Button variant="outline" size="sm" disabled={vehiclePage <= 1} onClick={() => setVehiclePage(prev => prev - 1)}>{t('vehicle.prev')}</Button>
                    <span className="flex items-center px-2">{vehiclePage} / {Math.ceil(vehicleTotal / VEH_PAGE_SIZE)}</span>
                    <Button variant="outline" size="sm" disabled={vehiclePage * VEH_PAGE_SIZE >= vehicleTotal} onClick={() => setVehiclePage(prev => prev + 1)}>{t('vehicle.next')}</Button>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Drivers */}
        <TabsContent value="drivers">
          <Card>
            <CardContent className="p-0">
              {drivers.length === 0 ? (
                <div className="py-16 text-center text-muted-foreground">{t('vehicle.noDrivers')}</div>
              ) : (
                <div className="divide-y">
                  {drivers.map(d => (
                    <div key={d.id} className="flex items-center gap-4 px-4 py-3 hover:bg-muted/30">
                      <div className="flex-1">
                        <p className="font-medium text-sm">{d.name}</p>
                        <p className="text-xs text-muted-foreground">
                          {[d.license_no, d.phone].filter(Boolean).join(' · ')}
                        </p>
                      </div>
                      <Button size="icon" variant="ghost" onClick={() => { setEditD(d); setDDialog(true); }}>
                        <Pencil className="h-4 w-4" />
                      </Button>
                    </div>
                  ))}
                </div>
              )}
              {driverTotal > VEH_PAGE_SIZE && (
                <div className="flex items-center justify-between px-4 py-3 border-t text-sm">
                  <span className="text-muted-foreground">
                    {t('vehicle.showing', { from: (driverPage - 1) * VEH_PAGE_SIZE + 1, to: Math.min(driverPage * VEH_PAGE_SIZE, driverTotal), total: driverTotal })}
                  </span>
                  <div className="flex gap-2">
                    <Button variant="outline" size="sm" disabled={driverPage <= 1} onClick={() => setDriverPage(prev => prev - 1)}>{t('vehicle.prev')}</Button>
                    <span className="flex items-center px-2">{driverPage} / {Math.ceil(driverTotal / VEH_PAGE_SIZE)}</span>
                    <Button variant="outline" size="sm" disabled={driverPage * VEH_PAGE_SIZE >= driverTotal} onClick={() => setDriverPage(prev => prev + 1)}>{t('vehicle.next')}</Button>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Transporters */}
        <TabsContent value="transporters">
          <Card>
            <CardContent className="p-0">
              {transporters.length === 0 ? (
                <div className="py-16 text-center text-muted-foreground">{t('vehicle.noTransporters')}</div>
              ) : (
                <div className="divide-y">
                  {transporters.map(tr => (
                    <div key={tr.id} className="flex items-center gap-4 px-4 py-3 hover:bg-muted/30">
                      <div className="flex-1">
                        <p className="font-medium text-sm">{tr.name}</p>
                        <p className="text-xs text-muted-foreground">
                          {[tr.gstin, tr.phone].filter(Boolean).join(' · ')}
                        </p>
                      </div>
                      <Button size="icon" variant="ghost" onClick={() => { setEditT(tr); setTDialog(true); }}>
                        <Pencil className="h-4 w-4" />
                      </Button>
                    </div>
                  ))}
                </div>
              )}
              {transporterTotal > VEH_PAGE_SIZE && (
                <div className="flex items-center justify-between px-4 py-3 border-t text-sm">
                  <span className="text-muted-foreground">
                    {t('vehicle.showing', { from: (transporterPage - 1) * VEH_PAGE_SIZE + 1, to: Math.min(transporterPage * VEH_PAGE_SIZE, transporterTotal), total: transporterTotal })}
                  </span>
                  <div className="flex gap-2">
                    <Button variant="outline" size="sm" disabled={transporterPage <= 1} onClick={() => setTransporterPage(prev => prev - 1)}>{t('vehicle.prev')}</Button>
                    <span className="flex items-center px-2">{transporterPage} / {Math.ceil(transporterTotal / VEH_PAGE_SIZE)}</span>
                    <Button variant="outline" size="sm" disabled={transporterPage * VEH_PAGE_SIZE >= transporterTotal} onClick={() => setTransporterPage(prev => prev + 1)}>{t('vehicle.next')}</Button>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      <VehicleDialog open={vDialog} editing={editV} vehicleTypes={vehicleTypes}
        onClose={() => setVDialog(false)} onSaved={() => fetch()} />
      <VehicleTypeManagerDialog open={typeDialog} types={vehicleTypes}
        onClose={() => setTypeDialog(false)} onSaved={setVehicleTypes} />
      <DriverDialog open={dDialog} editing={editD} onClose={() => setDDialog(false)}
        onSaved={() => fetch()} />
      <TransporterDialog open={tDialog} editing={editT} onClose={() => setTDialog(false)}
        onSaved={() => fetch()} />
    </div>
  );
}
