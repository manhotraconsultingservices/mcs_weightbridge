import { useEffect, useState, useCallback } from 'react';
import { Save, Loader2, Plus, CheckCircle2, Usb, Shield, Trash2, Mail, Phone, MessageSquare, TestTube, Send, RefreshCw, CheckCircle, XCircle, Server, Scale, ScanLine, Play, RotateCcw, Camera } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import api from '@/services/api';
import { useUsbGuard } from '@/hooks/useUsbGuard';

interface Company {
  id: string;
  name: string;
  legal_name: string | null;
  gstin: string | null;
  pan: string | null;
  phone: string | null;
  email: string | null;
  address: string | null;
  city: string | null;
  state: string | null;
  state_code: string | null;
  pincode: string | null;
  bank_name: string | null;
  bank_account_no: string | null;
  bank_ifsc: string | null;
  bank_branch: string | null;
  sale_invoice_prefix: string | null;
  purchase_invoice_prefix: string | null;
  receipt_prefix: string | null;
  voucher_prefix: string | null;
}

interface FinancialYear {
  id: string;
  label: string;
  start_date: string;
  end_date: string;
  is_active: boolean;
}

interface UsbKey {
  id: string;
  key_uuid: string;
  label: string;
  is_active: boolean;
  created_at: string;
}

function Field({ label, value, onChange, placeholder, type = 'text' }: {
  label: string; value: string; onChange: (v: string) => void; placeholder?: string; type?: string;
}) {
  return (
    <div className="space-y-1">
      <Label>{label}</Label>
      <Input type={type} value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder} />
    </div>
  );
}

// USB Guard settings tab component
function UsbGuardTab() {
  const { authorized, method, expires_at, loading, refresh } = useUsbGuard();
  const [usbKeys, setUsbKeys] = useState<UsbKey[]>([]);
  const [keysLoading, setKeysLoading] = useState(false);

  // Register key form
  const [regKeyUuid, setRegKeyUuid] = useState('');
  const [regLabel, setRegLabel] = useState('Primary Key');
  const [regError, setRegError] = useState('');
  const [regSaving, setRegSaving] = useState(false);
  const [regMsg, setRegMsg] = useState('');

  // Recovery form
  const [recPin, setRecPin] = useState('');
  const [recHours, setRecHours] = useState('24');
  const [recReason, setRecReason] = useState('');
  const [recError, setRecError] = useState('');
  const [recSaving, setRecSaving] = useState(false);
  const [recMsg, setRecMsg] = useState('');

  // Deactivate key dialog
  const [deactivateKey, setDeactivateKey] = useState<UsbKey | null>(null);

  async function loadKeys() {
    setKeysLoading(true);
    try {
      const { data } = await api.get<UsbKey[]>('/api/v1/usb-guard/keys');
      setUsbKeys(data);
    } catch {
      // ignore — may not be admin
    } finally {
      setKeysLoading(false);
    }
  }

  useEffect(() => { loadKeys(); }, []);

  async function handleRegisterKey() {
    if (!regKeyUuid.trim()) { setRegError('Key UUID is required'); return; }
    setRegSaving(true); setRegError(''); setRegMsg('');
    try {
      await api.post('/api/v1/usb-guard/register-key', { key_uuid: regKeyUuid.trim(), label: regLabel });
      setRegMsg('Key registered successfully');
      setRegKeyUuid('');
      loadKeys();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setRegError(typeof detail === 'string' ? detail : 'Failed to register key');
    } finally {
      setRegSaving(false);
    }
  }

  async function handleCreateRecovery() {
    if (!recPin || recPin.length < 6) { setRecError('PIN must be at least 6 characters'); return; }
    setRecSaving(true); setRecError(''); setRecMsg('');
    try {
      const { data } = await api.post<{ message: string; expires_at: string }>('/api/v1/usb-guard/recovery/create', {
        pin: recPin,
        hours: parseInt(recHours),
        reason: recReason,
      });
      setRecMsg(data.message);
      setRecPin('');
      setRecReason('');
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setRecError(typeof detail === 'string' ? detail : 'Failed to create recovery session');
    } finally {
      setRecSaving(false);
    }
  }

  async function handleDeactivateKey(key: UsbKey) {
    try {
      await api.post('/api/v1/usb-guard/register-key', { key_uuid: key.key_uuid, label: key.label + ' (deactivated)' });
      // The register-key endpoint sets is_active=TRUE on conflict; to deactivate we need a direct update.
      // For now, re-load — admin can manage via DB or future endpoint.
      setDeactivateKey(null);
      loadKeys();
    } catch {
      setDeactivateKey(null);
    }
  }

  return (
    <div className="space-y-6">
      {/* Current Status */}
      <Card>
        <CardHeader><CardTitle className="text-base flex items-center gap-2"><Usb className="h-4 w-4" /> Current USB Status</CardTitle></CardHeader>
        <CardContent>
          {loading ? (
            <p className="text-sm text-muted-foreground">Checking...</p>
          ) : authorized ? (
            <div className="flex items-center gap-2">
              {method === 'usb' ? (
                <span className="flex items-center gap-2 text-sm text-green-700 bg-green-100 px-3 py-1.5 rounded-md">
                  <span className="h-2 w-2 rounded-full bg-green-500 animate-pulse" />
                  USB Key Active
                </span>
              ) : (
                <span className="flex items-center gap-2 text-sm text-orange-700 bg-orange-100 px-3 py-1.5 rounded-md">
                  <span className="h-2 w-2 rounded-full bg-orange-500" />
                  Recovery Session · Expires {expires_at ? new Date(expires_at).toLocaleString('en-IN') : ''}
                </span>
              )}
              <Button variant="ghost" size="sm" onClick={refresh}>Refresh</Button>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <span className="flex items-center gap-2 text-sm text-red-700 bg-red-100 px-3 py-1.5 rounded-md">
                <span className="h-2 w-2 rounded-full bg-red-500" />
                No USB key detected
              </span>
              <Button variant="ghost" size="sm" onClick={refresh}>Refresh</Button>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Register Key */}
      <Card>
        <CardHeader><CardTitle className="text-base">Register USB Key</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">
            Insert the USB drive on the server machine, then enter the UUID from the <code className="text-xs bg-muted px-1 rounded">.weighbridge_key</code> file on the drive.
            Alternatively, run <code className="text-xs bg-muted px-1 rounded">python setup_usb_key.py</code> to generate and register a key automatically.
          </p>
          {regError && <p className="text-sm text-destructive bg-destructive/10 rounded p-2">{regError}</p>}
          {regMsg && <p className="text-sm text-green-700 bg-green-100 rounded p-2">{regMsg}</p>}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>Key UUID</Label>
              <Input value={regKeyUuid} onChange={e => setRegKeyUuid(e.target.value)} placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" className="font-mono text-xs" />
            </div>
            <div className="space-y-1">
              <Label>Label</Label>
              <Input value={regLabel} onChange={e => setRegLabel(e.target.value)} placeholder="Primary Key" />
            </div>
          </div>
          <Button onClick={handleRegisterKey} disabled={regSaving || !regKeyUuid.trim()}>
            {regSaving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Register Key
          </Button>
        </CardContent>
      </Card>

      {/* Registered Keys */}
      <Card>
        <CardHeader><CardTitle className="text-base">Registered Keys</CardTitle></CardHeader>
        <CardContent className="p-0">
          {keysLoading ? (
            <div className="py-6 text-center text-sm text-muted-foreground">Loading...</div>
          ) : usbKeys.length === 0 ? (
            <div className="py-8 text-center text-sm text-muted-foreground">No USB keys registered.</div>
          ) : (
            <div className="divide-y">
              {usbKeys.map(key => (
                <div key={key.id} className="flex items-center gap-4 px-4 py-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="font-medium text-sm">{key.label}</p>
                      {key.is_active
                        ? <Badge className="bg-green-100 text-green-800 text-[10px]">Active</Badge>
                        : <Badge variant="secondary" className="text-[10px]">Inactive</Badge>
                      }
                    </div>
                    <p className="text-xs text-muted-foreground font-mono truncate">{key.key_uuid}</p>
                    <p className="text-xs text-muted-foreground">Registered {new Date(key.created_at).toLocaleDateString('en-IN')}</p>
                  </div>
                  {key.is_active && (
                    <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground hover:text-destructive" onClick={() => setDeactivateKey(key)}>
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Create Recovery Session */}
      <Card>
        <CardHeader><CardTitle className="text-base flex items-center gap-2"><Shield className="h-4 w-4 text-orange-500" /> Create Recovery Session</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">
            If the USB key is lost or unavailable, create a time-limited recovery PIN. Share the PIN with the operator to grant temporary access.
          </p>
          {recError && <p className="text-sm text-destructive bg-destructive/10 rounded p-2">{recError}</p>}
          {recMsg && <p className="text-sm text-green-700 bg-green-100 rounded p-2">{recMsg}</p>}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>Recovery PIN (min 6 chars)</Label>
              <Input type="password" value={recPin} onChange={e => setRecPin(e.target.value)} placeholder="Enter a secure PIN" />
            </div>
            <div className="space-y-1">
              <Label>Valid For</Label>
              <Select value={recHours} onValueChange={v => setRecHours(v ?? '24')}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="1">1 hour</SelectItem>
                  <SelectItem value="4">4 hours</SelectItem>
                  <SelectItem value="8">8 hours</SelectItem>
                  <SelectItem value="24">24 hours</SelectItem>
                  <SelectItem value="48">48 hours</SelectItem>
                  <SelectItem value="72">72 hours</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="space-y-1">
            <Label>Reason (optional)</Label>
            <Input value={recReason} onChange={e => setRecReason(e.target.value)} placeholder="USB lost, maintenance, etc." />
          </div>
          <Button onClick={handleCreateRecovery} disabled={recSaving || recPin.length < 6}>
            {recSaving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Create Recovery Session
          </Button>
        </CardContent>
      </Card>

      {/* Deactivate confirm dialog */}
      <Dialog open={!!deactivateKey} onOpenChange={v => !v && setDeactivateKey(null)}>
        <DialogContent className="max-w-sm">
          <DialogHeader><DialogTitle>Deactivate USB Key</DialogTitle></DialogHeader>
          <p className="text-sm text-muted-foreground">
            Are you sure you want to deactivate <strong>{deactivateKey?.label}</strong>? Private invoices will no longer be accessible with this key.
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeactivateKey(null)}>Cancel</Button>
            <Button variant="destructive" onClick={() => deactivateKey && handleDeactivateKey(deactivateKey)}>Deactivate</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// ── Notifications Config Tab ─────────────────────────────────────────────────

interface NotifConfig {
  channel: string;
  is_enabled: boolean;
  smtp_host: string | null;
  smtp_port: number | null;
  smtp_user: string | null;
  smtp_password: string | null;
  from_email: string | null;
  from_name: string | null;
  use_tls: boolean;
  sms_api_key: string | null;
  sms_sender_id: string | null;
  sms_route: string | null;
  wa_api_url: string | null;
  wa_api_key: string | null;
  wa_phone_number_id: string | null;
  tg_bot_token: string | null;
}

function NotificationsConfigTab() {
  const [configs, setConfigs] = useState<Record<string, NotifConfig>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);
  const [msgs, setMsgs] = useState<Record<string, string>>({});
  const [testRecipient, setTestRecipient] = useState('');
  const [testChannel, setTestChannel] = useState('');
  const [testSending, setTestSending] = useState(false);
  const [testMsg, setTestMsg] = useState('');

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<NotifConfig[]>('/api/v1/notifications/config');
      const map: Record<string, NotifConfig> = {};
      data.forEach(c => { map[c.channel] = c; });
      setConfigs(map);
    } catch { /* ignore */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  function setField(channel: string, key: keyof NotifConfig, val: string | boolean | number | null) {
    setConfigs(prev => ({ ...prev, [channel]: { ...prev[channel], [key]: val } }));
  }

  async function saveChannel(channel: string) {
    setSaving(channel); setMsgs(m => ({ ...m, [channel]: '' }));
    try {
      await api.put(`/api/v1/notifications/config/${channel}`, configs[channel]);
      setMsgs(m => ({ ...m, [channel]: 'Saved ✓' }));
      setTimeout(() => setMsgs(m => ({ ...m, [channel]: '' })), 3000);
    } catch {
      setMsgs(m => ({ ...m, [channel]: 'Failed to save' }));
    } finally { setSaving(null); }
  }

  async function sendTest() {
    if (!testChannel || !testRecipient) return;
    setTestSending(true); setTestMsg('');
    try {
      await api.post(`/api/v1/notifications/config/${testChannel}/test`, { channel: testChannel, recipient: testRecipient });
      setTestMsg('Test message sent successfully!');
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setTestMsg(typeof detail === 'string' ? detail : 'Send failed');
    } finally { setTestSending(false); }
  }

  if (loading) return <div className="py-8 text-center text-sm text-muted-foreground">Loading...</div>;

  const cfg = (ch: string): NotifConfig => configs[ch] || {
    channel: ch, is_enabled: false, smtp_host: null, smtp_port: 587, smtp_user: null,
    smtp_password: null, from_email: null, from_name: null, use_tls: true,
    sms_api_key: null, sms_sender_id: null, sms_route: '4',
    wa_api_url: null, wa_api_key: null, wa_phone_number_id: null,
    tg_bot_token: null,
  };

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const channelIcons: Record<string, any> = {
    email: Mail, sms: Phone, whatsapp: MessageSquare, telegram: Send,
  };

  return (
    <div className="space-y-4">
      {(['email', 'sms', 'whatsapp', 'telegram'] as const).map(ch => {
        const c = cfg(ch);
        const Icon = channelIcons[ch];
        const label = ch === 'email' ? 'Email (SMTP)' : ch === 'sms' ? 'SMS (MSG91)' : ch === 'whatsapp' ? 'WhatsApp (WATI)' : 'Telegram Bot';
        return (
          <Card key={ch}>
            <CardHeader>
              <CardTitle className="text-base flex items-center justify-between">
                <span className="flex items-center gap-2"><Icon className="h-4 w-4" /> {label}</span>
                <div className="flex items-center gap-2">
                  {c.is_enabled
                    ? <Badge className="bg-green-100 text-green-800">Enabled</Badge>
                    : <Badge variant="secondary">Disabled</Badge>}
                  <Button size="sm" variant="outline"
                    onClick={() => setField(ch, 'is_enabled', !c.is_enabled)}>
                    {c.is_enabled ? 'Disable' : 'Enable'}
                  </Button>
                </div>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {ch === 'email' && (
                <>
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1">
                      <Label>SMTP Host</Label>
                      <Input value={c.smtp_host ?? ''} onChange={e => setField(ch, 'smtp_host', e.target.value)} placeholder="smtp.gmail.com" />
                    </div>
                    <div className="space-y-1">
                      <Label>Port</Label>
                      <Input type="number" value={c.smtp_port ?? 587} onChange={e => setField(ch, 'smtp_port', parseInt(e.target.value))} />
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1">
                      <Label>Username</Label>
                      <Input value={c.smtp_user ?? ''} onChange={e => setField(ch, 'smtp_user', e.target.value)} placeholder="user@gmail.com" />
                    </div>
                    <div className="space-y-1">
                      <Label>Password / App Password</Label>
                      <Input type="password" value={c.smtp_password ?? ''} onChange={e => setField(ch, 'smtp_password', e.target.value)} placeholder="••••••••" />
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1">
                      <Label>From Email</Label>
                      <Input value={c.from_email ?? ''} onChange={e => setField(ch, 'from_email', e.target.value)} placeholder="invoices@yourcompany.com" />
                    </div>
                    <div className="space-y-1">
                      <Label>From Name</Label>
                      <Input value={c.from_name ?? ''} onChange={e => setField(ch, 'from_name', e.target.value)} placeholder="Weighbridge System" />
                    </div>
                  </div>
                </>
              )}
              {ch === 'sms' && (
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1">
                    <Label>MSG91 API Key</Label>
                    <Input type="password" value={c.sms_api_key ?? ''} onChange={e => setField(ch, 'sms_api_key', e.target.value)} placeholder="MSG91 API key" />
                  </div>
                  <div className="space-y-1">
                    <Label>Sender ID</Label>
                    <Input value={c.sms_sender_id ?? ''} onChange={e => setField(ch, 'sms_sender_id', e.target.value)} placeholder="WGHBRG" maxLength={6} />
                  </div>
                </div>
              )}
              {ch === 'whatsapp' && (
                <>
                  <div className="space-y-1">
                    <Label>WATI API URL</Label>
                    <Input value={c.wa_api_url ?? ''} onChange={e => setField(ch, 'wa_api_url', e.target.value)} placeholder="https://live-server-XXXX.wati.io" />
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1">
                      <Label>API Key</Label>
                      <Input type="password" value={c.wa_api_key ?? ''} onChange={e => setField(ch, 'wa_api_key', e.target.value)} placeholder="••••••••" />
                    </div>
                    <div className="space-y-1">
                      <Label>Phone Number ID</Label>
                      <Input value={c.wa_phone_number_id ?? ''} onChange={e => setField(ch, 'wa_phone_number_id', e.target.value)} placeholder="918XXXXXXXXXX" />
                    </div>
                  </div>
                </>
              )}
              {ch === 'telegram' && (
                <>
                  <div className="space-y-1">
                    <Label>Bot Token</Label>
                    <Input type="password" value={c.tg_bot_token ?? ''} onChange={e => setField(ch, 'tg_bot_token', e.target.value)} placeholder="1234567890:AAF..." />
                    <p className="text-xs text-muted-foreground mt-1">
                      Create a bot via <code>@BotFather</code> on Telegram. Add recipient chat IDs in <strong>Notifications → Recipients</strong>.
                    </p>
                  </div>
                </>
              )}
              <div className="flex items-center gap-3 pt-1">
                <Button size="sm" onClick={() => saveChannel(ch)} disabled={saving === ch}>
                  {saving === ch && <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />}
                  <Save className="mr-1 h-3.5 w-3.5" /> Save
                </Button>
                <Button size="sm" variant="outline" onClick={() => { setTestChannel(ch); setTestRecipient(''); setTestMsg(''); }}>
                  <TestTube className="mr-1 h-3.5 w-3.5" /> Test
                </Button>
                {msgs[ch] && <span className="text-sm text-muted-foreground">{msgs[ch]}</span>}
              </div>
            </CardContent>
          </Card>
        );
      })}

      {/* Test Send Dialog */}
      {testChannel && (
        <Card className="border-dashed border-blue-300 bg-blue-50/30">
          <CardHeader><CardTitle className="text-sm flex items-center gap-2">
            <TestTube className="h-4 w-4 text-blue-600" />
            Test {testChannel === 'email' ? 'Email' : testChannel === 'sms' ? 'SMS' : testChannel === 'whatsapp' ? 'WhatsApp' : 'Telegram'} Channel
          </CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <p className="text-xs text-muted-foreground">
              {testChannel === 'email' ? 'Enter recipient email address' : testChannel === 'telegram' ? 'Enter Telegram chat ID (numeric, e.g. -1001234567890)' : 'Enter recipient phone number (10-digit Indian mobile)'}
            </p>
            <div className="flex items-center gap-2">
              <Input
                value={testRecipient}
                onChange={e => setTestRecipient(e.target.value)}
                placeholder={testChannel === 'email' ? 'test@example.com' : testChannel === 'telegram' ? '-1001234567890' : '9876543210'}
                className="flex-1"
              />
              <Button size="sm" onClick={sendTest} disabled={testSending || !testRecipient}>
                {testSending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => { setTestChannel(''); setTestMsg(''); }}>✕</Button>
            </div>
            {testMsg && <p className={`text-sm ${testMsg.includes('success') ? 'text-green-700' : 'text-destructive'}`}>{testMsg}</p>}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Weight Scale Settings Tab
// ─────────────────────────────────────────────────────────────────────────────
interface PortInfo { port: string; description: string; hwid: string; manufacturer: string | null; }
interface ProtocolInfo { id: string; label: string; default_baud: number; default_config: Record<string, unknown>; }
interface WeightConfig {
  port_name: string;
  baud_rate: number;
  protocol: string;
  stability_readings: number;
  stability_tolerance_kg: number;
  protocol_config: Record<string, unknown>;
}
interface TestFrame { hex: string; ascii: string; bytes: number; }
interface TestResult { port: string; baud_rate: number; frames_captured: number; frames: TestFrame[]; error: string | null; }

function WeightScaleTab() {
  const [ports, setPorts] = useState<PortInfo[]>([]);
  const [protocols, setProtocols] = useState<ProtocolInfo[]>([]);
  const [cfg, setCfg] = useState<WeightConfig>({
    port_name: '', baud_rate: 9600, protocol: 'generic',
    stability_readings: 5, stability_tolerance_kg: 20,
    protocol_config: {},
  });
  const [scanningPorts, setScanningPorts] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestResult | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState('');
  const [testDuration, setTestDuration] = useState(3);

  const loadConfig = useCallback(async () => {
    try {
      const { data } = await api.get<WeightConfig>('/api/v1/weight/config');
      if (data && data.port_name) setCfg(c => ({ ...c, ...data, protocol_config: (data as WeightConfig & { protocol_config?: Record<string, unknown> }).protocol_config || {} }));
    } catch { /* not configured yet */ }
  }, []);

  const loadProtocols = useCallback(async () => {
    try {
      const { data } = await api.get<{ protocols: ProtocolInfo[] }>('/api/v1/weight/protocols');
      setProtocols(data.protocols);
    } catch { /* ignore */ }
  }, []);

  const scanPorts = useCallback(async () => {
    setScanningPorts(true);
    try {
      const { data } = await api.get<{ ports: PortInfo[] }>('/api/v1/weight/ports');
      setPorts(data.ports);
    } catch { setPorts([]); }
    finally { setScanningPorts(false); }
  }, []);

  useEffect(() => {
    loadConfig();
    loadProtocols();
    scanPorts();
  }, [loadConfig, loadProtocols, scanPorts]);

  // When protocol changes, apply its default baud if no custom baud was set
  function handleProtocolChange(protocolId: string | null) {
    if (!protocolId) return;
    const proto = protocols.find(p => p.id === protocolId);
    setCfg(c => ({
      ...c,
      protocol: protocolId,
      baud_rate: proto?.default_baud ?? c.baud_rate,
      protocol_config: proto?.default_config ? { ...proto.default_config } : {},
    }));
    setTestResult(null);
  }

  async function runTest() {
    if (!cfg.port_name) return;
    setTesting(true); setTestResult(null);
    try {
      const { data } = await api.post<TestResult>('/api/v1/weight/test-port', {
        port_name: cfg.port_name,
        baud_rate: cfg.baud_rate,
        duration_sec: testDuration,
        data_bits: 8, stop_bits: 1, parity: 'N',
      });
      setTestResult(data);
    } catch { setTestResult({ port: cfg.port_name, baud_rate: cfg.baud_rate, frames_captured: 0, frames: [], error: 'Request failed — backend error' }); }
    finally { setTesting(false); }
  }

  async function save() {
    setSaving(true); setSaveMsg('');
    try {
      await api.put('/api/v1/weight/config', cfg);
      setSaveMsg('Scale config saved and restarted');
      setTimeout(() => setSaveMsg(''), 4000);
    } catch { setSaveMsg('Failed to save config'); }
    finally { setSaving(false); }
  }

  const selectedProto = protocols.find(p => p.id === cfg.protocol);

  return (
    <div className="space-y-5 max-w-2xl">
      {/* Info banner */}
      <Card className="border-blue-200 bg-blue-50">
        <CardContent className="pt-4 pb-3">
          <div className="flex gap-3 items-start">
            <Scale className="h-5 w-5 text-blue-600 mt-0.5 shrink-0" />
            <div className="text-sm text-blue-800">
              <p className="font-semibold mb-1">Weighbridge Scale Integration</p>
              <p>Connects to your weighbridge indicator via RS232 / RS485. Select the COM port, protocol for your indicator brand, and test before saving.</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Port + Protocol */}
      <Card>
        <CardHeader><CardTitle className="text-base flex items-center gap-2"><Scale className="h-4 w-4" /> Port &amp; Protocol</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          {/* COM Port */}
          <div className="space-y-1">
            <Label>COM Port</Label>
            <div className="flex gap-2">
              <Select value={cfg.port_name} onValueChange={v => setCfg(c => ({ ...c, port_name: v ?? '' }))}>
                <SelectTrigger className="flex-1">
                  <SelectValue placeholder="Select COM port..." />
                </SelectTrigger>
                <SelectContent>
                  {ports.map(p => (
                    <SelectItem key={p.port} value={p.port}>
                      <div className="flex flex-col">
                        <span className="font-medium">{p.port}</span>
                        <span className="text-xs text-muted-foreground">{p.description}</span>
                      </div>
                    </SelectItem>
                  ))}
                  {ports.length === 0 && (
                    <SelectItem value="_none" disabled>No ports found — click Scan</SelectItem>
                  )}
                </SelectContent>
              </Select>
              <Button variant="outline" size="sm" onClick={scanPorts} disabled={scanningPorts} className="shrink-0">
                {scanningPorts ? <Loader2 className="h-4 w-4 animate-spin" /> : <ScanLine className="h-4 w-4" />}
                <span className="ml-1 hidden sm:inline">Scan</span>
              </Button>
            </div>
            {ports.length > 0 && (
              <p className="text-xs text-muted-foreground">{ports.length} port{ports.length > 1 ? 's' : ''} found</p>
            )}
          </div>

          {/* Protocol */}
          <div className="space-y-1">
            <Label>Scale Protocol / Brand</Label>
            <Select value={cfg.protocol} onValueChange={handleProtocolChange}>
              <SelectTrigger>
                <SelectValue placeholder="Select protocol..." />
              </SelectTrigger>
              <SelectContent>
                {protocols.map(p => (
                  <SelectItem key={p.id} value={p.id}>
                    {p.label}
                    {p.default_baud !== 9600 && (
                      <span className="ml-2 text-xs text-muted-foreground">({p.default_baud} baud)</span>
                    )}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Baud rate */}
          <div className="grid grid-cols-3 gap-3">
            <div className="space-y-1">
              <Label>Baud Rate</Label>
              <Select value={String(cfg.baud_rate)} onValueChange={v => setCfg(c => ({ ...c, baud_rate: Number(v) }))}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {[1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200].map(b => (
                    <SelectItem key={b} value={String(b)}>{b}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label>Data Bits</Label>
              <Select value="8" onValueChange={() => {}}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="7">7</SelectItem>
                  <SelectItem value="8">8</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label>Parity</Label>
              <Select value="N" onValueChange={() => {}}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="N">None</SelectItem>
                  <SelectItem value="E">Even</SelectItem>
                  <SelectItem value="O">Odd</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          {/* Protocol-specific config */}
          {selectedProto && Object.keys(selectedProto.default_config).length > 0 && (
            <div className="space-y-3 pt-2 border-t">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Protocol-specific Settings</p>
              {Object.entries(selectedProto.default_config).map(([key, defVal]) => {
                const val = (cfg.protocol_config[key] ?? defVal);
                const isBoolean = typeof defVal === 'boolean';
                const label = key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
                if (isBoolean) {
                  return (
                    <div key={key} className="flex items-center gap-2">
                      <input type="checkbox" id={`pcfg_${key}`}
                        checked={Boolean(val)}
                        onChange={e => setCfg(c => ({ ...c, protocol_config: { ...c.protocol_config, [key]: e.target.checked } }))}
                        className="h-4 w-4 rounded border-gray-300" />
                      <label htmlFor={`pcfg_${key}`} className="text-sm">{label}</label>
                    </div>
                  );
                }
                return (
                  <div key={key} className="space-y-1">
                    <Label className="text-xs">{label}</Label>
                    <Input
                      type="number"
                      value={String(val)}
                      onChange={e => setCfg(c => ({ ...c, protocol_config: { ...c.protocol_config, [key]: Number(e.target.value) } }))}
                      className="h-8 text-sm"
                    />
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Stability Settings */}
      <Card>
        <CardHeader><CardTitle className="text-base">Stability Detection</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <p className="text-xs text-muted-foreground">
            A weight reading is considered <strong>stable</strong> when it varies by less than the tolerance over N consecutive readings.
          </p>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1">
              <Label>Stable Readings (N)</Label>
              <Input
                type="number" min={2} max={20}
                value={cfg.stability_readings}
                onChange={e => setCfg(c => ({ ...c, stability_readings: Number(e.target.value) }))}
              />
              <p className="text-xs text-muted-foreground">Typically 5 readings (~3s)</p>
            </div>
            <div className="space-y-1">
              <Label>Tolerance (kg)</Label>
              <Input
                type="number" min={0.1} step={0.5}
                value={cfg.stability_tolerance_kg}
                onChange={e => setCfg(c => ({ ...c, stability_tolerance_kg: Number(e.target.value) }))}
              />
              <p className="text-xs text-muted-foreground">Max spread across N readings</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Test Connection */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <Play className="h-4 w-4" /> Test Connection
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-xs text-muted-foreground">
            Opens the selected port for a few seconds and captures raw frames. Use this to verify wiring and baud rate before saving.
          </p>
          <div className="flex items-end gap-3">
            <div className="space-y-1 w-32">
              <Label>Duration (sec)</Label>
              <Select value={String(testDuration)} onValueChange={v => setTestDuration(Number(v))}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {[2, 3, 5, 8, 10].map(d => (
                    <SelectItem key={d} value={String(d)}>{d}s</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Button onClick={runTest} disabled={testing || !cfg.port_name} variant="outline">
              {testing ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4" />}
              {testing ? `Reading ${testDuration}s...` : 'Test Port'}
            </Button>
          </div>

          {testResult && (
            <div className="mt-3">
              {testResult.error ? (
                <div className="flex items-center gap-2 p-3 rounded-md text-sm bg-red-50 text-red-800 border border-red-200">
                  <XCircle className="h-4 w-4 shrink-0" />
                  <span>{testResult.error}</span>
                </div>
              ) : testResult.frames_captured === 0 ? (
                <div className="flex items-center gap-2 p-3 rounded-md text-sm bg-amber-50 text-amber-800 border border-amber-200">
                  <CheckCircle className="h-4 w-4 shrink-0" />
                  <span>Port opened successfully but no data received. Check cable connection and indicator power.</span>
                </div>
              ) : (
                <div>
                  <div className="flex items-center gap-2 p-2 rounded-t-md text-sm bg-green-50 text-green-800 border border-green-200 border-b-0">
                    <CheckCircle className="h-4 w-4 shrink-0" />
                    <span>{testResult.frames_captured} frame{testResult.frames_captured > 1 ? 's' : ''} captured — scale is transmitting data</span>
                  </div>
                  <div className="rounded-b-md border border-green-200 bg-gray-950 text-gray-100 font-mono text-xs p-3 max-h-52 overflow-y-auto space-y-1">
                    {testResult.frames.map((f, i) => (
                      <div key={i} className="flex gap-3">
                        <span className="text-gray-500 select-none w-5 text-right shrink-0">{i + 1}</span>
                        <span className="text-green-400">{f.ascii || '(non-printable)'}</span>
                        <span className="text-gray-500 ml-auto shrink-0">{f.bytes}B</span>
                      </div>
                    ))}
                  </div>
                  {testResult.frames.length > 0 && (
                    <div className="mt-2 p-2 rounded-md bg-gray-50 border text-xs font-mono text-gray-600">
                      <span className="text-muted-foreground mr-2">HEX:</span>
                      {testResult.frames[0].hex}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Save */}
      <div className="flex items-center gap-3">
        <Button onClick={save} disabled={saving || !cfg.port_name || !cfg.protocol}>
          {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RotateCcw className="mr-2 h-4 w-4" />}
          Save &amp; Restart Scale
        </Button>
        {saveMsg && (
          <p className={`text-sm ${saveMsg.includes('Failed') ? 'text-destructive' : 'text-green-700'}`}>{saveMsg}</p>
        )}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Tally Integration Tab
// ─────────────────────────────────────────────────────────────────────────────
interface TallyConfig {
  id?: string;
  host: string;
  port: number;
  tally_company_name: string;
  auto_sync: boolean;
  is_enabled: boolean;
  // Ledger name mappings
  ledger_sales: string;
  ledger_purchase: string;
  ledger_cgst: string;
  ledger_sgst: string;
  ledger_igst: string;
  ledger_freight: string;
  ledger_discount: string;
  ledger_tcs: string;
  ledger_roundoff: string;
  // Narration options
  narration_vehicle: boolean;
  narration_token: boolean;
  narration_weight: boolean;
}

// ── Weighbridge / Urgency Settings Tab ───────────────────────────────────────
function WeighbridgeTab() {
  const [form, setForm] = useState({ green_max: 30, amber_max: 60, orange_max: 120 });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    api.get<{ green_max: number; amber_max: number; orange_max: number }>('/api/v1/app-settings/weighbridge-urgency')
      .then(r => setForm(r.data))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  async function save() {
    setMsg(''); setError('');
    if (form.green_max <= 0 || form.amber_max <= form.green_max || form.orange_max <= form.amber_max) {
      setError('Thresholds must be in ascending order: Green < Amber < Orange (all > 0)');
      return;
    }
    setSaving(true);
    try {
      await api.put('/api/v1/app-settings/weighbridge-urgency', form);
      setMsg('Thresholds saved.');
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Failed to save');
    } finally { setSaving(false); }
  }

  if (loading) return <div className="py-8 text-center text-sm text-muted-foreground">Loading…</div>;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base flex items-center gap-2">
          <Scale className="h-4 w-4" /> Token Urgency Colour Thresholds
        </CardTitle>
        <p className="text-sm text-muted-foreground mt-1">
          Control the colour-coding of active token cards and the Command Center on the Token page.
          Times are in <strong>minutes</strong>.
        </p>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Threshold table */}
        <div className="rounded-lg border overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-muted/50 text-xs text-muted-foreground border-b">
                <th className="text-left px-4 py-2.5 font-medium">Colour</th>
                <th className="text-left px-4 py-2.5 font-medium">Condition</th>
                <th className="text-left px-4 py-2.5 font-medium w-36">Threshold (min)</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              <tr>
                <td className="px-4 py-3">
                  <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-green-700">
                    <span className="h-3 w-3 rounded-full bg-green-500 inline-block" /> 🟢 Green
                  </span>
                </td>
                <td className="px-4 py-3 text-muted-foreground text-xs">Elapsed &lt; green_max</td>
                <td className="px-4 py-3">
                  <Input
                    type="number" min={1} max={1439}
                    value={form.green_max}
                    onChange={e => setForm(f => ({ ...f, green_max: Number(e.target.value) }))}
                    className="h-8 w-24 text-sm"
                  />
                </td>
              </tr>
              <tr>
                <td className="px-4 py-3">
                  <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-amber-700">
                    <span className="h-3 w-3 rounded-full bg-amber-400 inline-block" /> 🟡 Amber
                  </span>
                </td>
                <td className="px-4 py-3 text-muted-foreground text-xs">green_max ≤ elapsed &lt; amber_max</td>
                <td className="px-4 py-3">
                  <Input
                    type="number" min={1} max={1439}
                    value={form.amber_max}
                    onChange={e => setForm(f => ({ ...f, amber_max: Number(e.target.value) }))}
                    className="h-8 w-24 text-sm"
                  />
                </td>
              </tr>
              <tr>
                <td className="px-4 py-3">
                  <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-orange-700">
                    <span className="h-3 w-3 rounded-full bg-orange-500 inline-block" /> 🟠 Orange
                  </span>
                </td>
                <td className="px-4 py-3 text-muted-foreground text-xs">amber_max ≤ elapsed &lt; orange_max</td>
                <td className="px-4 py-3">
                  <Input
                    type="number" min={1} max={1440}
                    value={form.orange_max}
                    onChange={e => setForm(f => ({ ...f, orange_max: Number(e.target.value) }))}
                    className="h-8 w-24 text-sm"
                  />
                </td>
              </tr>
              <tr className="bg-red-50/40">
                <td className="px-4 py-3">
                  <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-red-700">
                    <span className="h-3 w-3 rounded-full bg-red-500 inline-block" /> 🔴 Red
                  </span>
                </td>
                <td className="px-4 py-3 text-muted-foreground text-xs">elapsed ≥ orange_max</td>
                <td className="px-4 py-3 text-xs text-muted-foreground italic">Always (no limit)</td>
              </tr>
            </tbody>
          </table>
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}

        <div className="flex items-center gap-3">
          <Button onClick={save} disabled={saving}>
            {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            <Save className="mr-2 h-4 w-4" /> Save Thresholds
          </Button>
          {msg && <p className="text-sm text-muted-foreground">{msg}</p>}
        </div>
      </CardContent>
    </Card>
  );
}

const DEFAULT_TALLY_CFG: TallyConfig = {
  host: 'localhost', port: 9002, tally_company_name: '', auto_sync: false, is_enabled: false,
  ledger_sales: 'Sales', ledger_purchase: 'Purchase',
  ledger_cgst: 'CGST', ledger_sgst: 'SGST', ledger_igst: 'IGST',
  ledger_freight: 'Freight Outward', ledger_discount: 'Trade Discount',
  ledger_tcs: 'TCS Payable', ledger_roundoff: 'Round Off',
  narration_vehicle: true, narration_token: true, narration_weight: true,
};

function TallyTab() {
  const [cfg, setCfg] = useState<TallyConfig>({ ...DEFAULT_TALLY_CFG });
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);
  const [companies, setCompanies] = useState<string[]>([]);
  const [saveMsg, setSaveMsg] = useState('');

  useEffect(() => {
    api.get<TallyConfig>('/api/v1/tally/config')
      .then(r => setCfg({ ...DEFAULT_TALLY_CFG, ...r.data, tally_company_name: r.data.tally_company_name || '' }))
      .catch(() => {});
  }, []);

  async function save() {
    setSaving(true); setSaveMsg('');
    try {
      const { data } = await api.put<TallyConfig>('/api/v1/tally/config', cfg);
      setCfg({ ...data, tally_company_name: data.tally_company_name || '' });
      setSaveMsg('Saved successfully');
      setTimeout(() => setSaveMsg(''), 3000);
    } catch { setSaveMsg('Failed to save'); }
    finally { setSaving(false); }
  }

  async function testConnection() {
    setTesting(true); setTestResult(null); setCompanies([]);
    try {
      const { data } = await api.post<{ success: boolean; message: string }>('/api/v1/tally/test-connection');
      setTestResult(data);
      if (data.success) {
        const comp = await api.get<{ companies: string[] }>('/api/v1/tally/companies');
        setCompanies(comp.data.companies || []);
      }
    } catch { setTestResult({ success: false, message: 'Request failed — backend error' }); }
    finally { setTesting(false); }
  }

  return (
    <div className="space-y-5 max-w-2xl">
      {/* Header info */}
      <Card className="border-blue-200 bg-blue-50">
        <CardContent className="pt-4 pb-3">
          <div className="flex gap-3 items-start">
            <Server className="h-5 w-5 text-blue-600 mt-0.5 shrink-0" />
            <div className="text-sm text-blue-800">
              <p className="font-semibold mb-1">Tally Prime Integration</p>
              <p>Sends finalised Sales & Purchase invoices to Tally as vouchers. Tally must be running with its HTTP server enabled.</p>
              <p className="mt-1 text-xs text-blue-600">Gateway of Tally → F12 Config → Advanced → Enable ODBC Server (set port to match below)</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Enable toggle */}
      <Card>
        <CardContent className="pt-4 space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="font-medium">Enable Tally Integration</p>
              <p className="text-xs text-muted-foreground">Allow invoices to be pushed to Tally</p>
            </div>
            <button
              onClick={() => setCfg(c => ({ ...c, is_enabled: !c.is_enabled }))}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${cfg.is_enabled ? 'bg-green-500' : 'bg-gray-300'}`}
            >
              <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${cfg.is_enabled ? 'translate-x-6' : 'translate-x-1'}`} />
            </button>
          </div>

          {/* Connection settings */}
          <div className="grid grid-cols-3 gap-3">
            <div className="col-span-2 space-y-1">
              <Label>Tally Server Host</Label>
              <Input value={cfg.host} onChange={e => setCfg(c => ({ ...c, host: e.target.value }))} placeholder="localhost" />
            </div>
            <div className="space-y-1">
              <Label>Port</Label>
              <Input type="number" value={cfg.port} onChange={e => setCfg(c => ({ ...c, port: Number(e.target.value) }))} placeholder="9002" />
            </div>
          </div>

          <div className="space-y-1">
            <Label>Tally Company Name</Label>
            <Input
              value={cfg.tally_company_name}
              onChange={e => setCfg(c => ({ ...c, tally_company_name: e.target.value }))}
              placeholder="As it appears in Tally (leave blank to use current company)"
            />
            {companies.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-1">
                <span className="text-xs text-muted-foreground">Open companies:</span>
                {companies.map(c => (
                  <button key={c} onClick={() => setCfg(f => ({ ...f, tally_company_name: c }))}
                    className="text-xs px-2 py-0.5 rounded bg-blue-100 text-blue-700 hover:bg-blue-200">
                    {c}
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="flex items-center gap-2">
            <input type="checkbox" id="auto_sync" checked={cfg.auto_sync}
              onChange={e => setCfg(c => ({ ...c, auto_sync: e.target.checked }))}
              className="h-4 w-4 rounded border-gray-300" />
            <label htmlFor="auto_sync" className="text-sm">Auto-sync when invoice is finalised</label>
          </div>
        </CardContent>
      </Card>

      {/* Ledger Name Mapping */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-semibold">Ledger Name Mapping</CardTitle>
          <p className="text-xs text-muted-foreground">These names must match the ledger names in your Tally company exactly (case-sensitive).</p>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label className="text-xs">Sales Ledger</Label>
              <Input className="h-8 text-sm" value={cfg.ledger_sales} onChange={e => setCfg(c => ({ ...c, ledger_sales: e.target.value }))} placeholder="Sales" />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Purchase Ledger</Label>
              <Input className="h-8 text-sm" value={cfg.ledger_purchase} onChange={e => setCfg(c => ({ ...c, ledger_purchase: e.target.value }))} placeholder="Purchase" />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">CGST Ledger</Label>
              <Input className="h-8 text-sm" value={cfg.ledger_cgst} onChange={e => setCfg(c => ({ ...c, ledger_cgst: e.target.value }))} placeholder="CGST" />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">SGST Ledger</Label>
              <Input className="h-8 text-sm" value={cfg.ledger_sgst} onChange={e => setCfg(c => ({ ...c, ledger_sgst: e.target.value }))} placeholder="SGST" />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">IGST Ledger</Label>
              <Input className="h-8 text-sm" value={cfg.ledger_igst} onChange={e => setCfg(c => ({ ...c, ledger_igst: e.target.value }))} placeholder="IGST" />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Freight Ledger</Label>
              <Input className="h-8 text-sm" value={cfg.ledger_freight} onChange={e => setCfg(c => ({ ...c, ledger_freight: e.target.value }))} placeholder="Freight Outward" />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Discount Ledger</Label>
              <Input className="h-8 text-sm" value={cfg.ledger_discount} onChange={e => setCfg(c => ({ ...c, ledger_discount: e.target.value }))} placeholder="Trade Discount" />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">TCS Ledger</Label>
              <Input className="h-8 text-sm" value={cfg.ledger_tcs} onChange={e => setCfg(c => ({ ...c, ledger_tcs: e.target.value }))} placeholder="TCS Payable" />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Round-off Ledger</Label>
              <Input className="h-8 text-sm" value={cfg.ledger_roundoff} onChange={e => setCfg(c => ({ ...c, ledger_roundoff: e.target.value }))} placeholder="Round Off" />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Narration Options */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-semibold">Narration Options</CardTitle>
          <p className="text-xs text-muted-foreground">Choose what information appears in the Tally voucher narration field.</p>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <input type="checkbox" checked={cfg.narration_vehicle}
                onChange={e => setCfg(c => ({ ...c, narration_vehicle: e.target.checked }))}
                className="h-4 w-4 rounded border-gray-300" />
              Include Vehicle Number (e.g. <span className="font-mono text-xs bg-muted px-1 rounded">Vehicle: MH12AB1234</span>)
            </label>
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <input type="checkbox" checked={cfg.narration_token}
                onChange={e => setCfg(c => ({ ...c, narration_token: e.target.checked }))}
                className="h-4 w-4 rounded border-gray-300" />
              Include Token Number (e.g. <span className="font-mono text-xs bg-muted px-1 rounded">Token #4872</span>)
            </label>
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <input type="checkbox" checked={cfg.narration_weight}
                onChange={e => setCfg(c => ({ ...c, narration_weight: e.target.checked }))}
                className="h-4 w-4 rounded border-gray-300" />
              Include Net Weight (e.g. <span className="font-mono text-xs bg-muted px-1 rounded">Net Wt: 15.760 MT</span>)
            </label>
          </div>
        </CardContent>
      </Card>

      {/* Test + Save */}
      <div className="flex gap-2 flex-wrap">
        <Button variant="outline" onClick={testConnection} disabled={testing}>
          {testing ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
          Test Connection
        </Button>
        <Button onClick={save} disabled={saving}>
          {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}
          Save Tally Settings
        </Button>
        {saveMsg && <p className="text-sm text-muted-foreground self-center">{saveMsg}</p>}
      </div>

      {testResult && (
        <div className={`flex items-start gap-2 p-3 rounded-md text-sm ${testResult.success ? 'bg-green-50 text-green-800 border border-green-200' : 'bg-red-50 text-red-800 border border-red-200'}`}>
          {testResult.success
            ? <CheckCircle className="h-4 w-4 mt-0.5 shrink-0" />
            : <XCircle className="h-4 w-4 mt-0.5 shrink-0" />}
          <span>{testResult.message}</span>
        </div>
      )}
    </div>
  );
}

// ── Camera Settings Tab ───────────────────────────────────────────────────── //

interface CameraCfg {
  label: string;
  snapshot_url: string;
  username: string;
  password: string;
  verification_code: string;
  serial_number: string;
  version: string;
  enabled: boolean;
}

const DEFAULT_CAM: CameraCfg = {
  label: '', snapshot_url: '', username: '', password: '',
  verification_code: '', serial_number: '', version: '', enabled: false,
};

function CameraSettingsTab() {
  const [front, setFront] = useState<CameraCfg>({ ...DEFAULT_CAM, label: 'Front View' });
  const [top, setTop] = useState<CameraCfg>({ ...DEFAULT_CAM, label: 'Top View' });
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState('');
  const [testingFront, setTestingFront] = useState(false);
  const [testingTop, setTestingTop] = useState(false);
  const [frontPreview, setFrontPreview] = useState<string | null>(null);
  const [topPreview, setTopPreview] = useState<string | null>(null);
  const [frontError, setFrontError] = useState('');
  const [topError, setTopError] = useState('');

  useEffect(() => {
    api.get<{ front: CameraCfg; top: CameraCfg }>('/api/v1/cameras/config')
      .then(r => {
        if (r.data.front) setFront(r.data.front);
        if (r.data.top) setTop(r.data.top);
      })
      .catch(() => {});
  }, []);

  async function save() {
    setSaving(true); setSaveMsg('');
    try {
      await api.put('/api/v1/cameras/config', { front, top });
      setSaveMsg('Camera settings saved');
      setTimeout(() => setSaveMsg(''), 3000);
    } catch {
      setSaveMsg('Failed to save');
    } finally {
      setSaving(false);
    }
  }

  async function testCamera(cameraId: 'front' | 'top') {
    const setTesting = cameraId === 'front' ? setTestingFront : setTestingTop;
    const setPreview = cameraId === 'front' ? setFrontPreview : setTopPreview;
    const setErr = cameraId === 'front' ? setFrontError : setTopError;
    setTesting(true); setPreview(null); setErr('');
    try {
      const { data } = await api.post<{ success: boolean; url?: string; error?: string }>(
        `/api/v1/cameras/test/${cameraId}`
      );
      if (data.success && data.url) {
        setPreview(data.url + '?t=' + Date.now()); // cache-bust
      } else {
        setErr(data.error || 'Test failed');
      }
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setErr(typeof detail === 'string' ? detail : 'Test failed — check URL and credentials');
    } finally {
      setTesting(false);
    }
  }

  function CameraForm({
    title,
    value,
    onChange,
    testing,
    preview,
    error,
    onTest,
  }: {
    title: string;
    value: CameraCfg;
    onChange: (v: CameraCfg) => void;
    testing: boolean;
    preview: string | null;
    error: string;
    onTest: () => void;
  }) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <span className="flex h-6 w-6 items-center justify-center rounded-full bg-primary/10 text-primary text-xs font-bold">
              {title[0]}
            </span>
            {title}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center gap-3">
            <Label className="w-20 shrink-0 text-xs">Enabled</Label>
            <input
              type="checkbox"
              checked={value.enabled}
              onChange={e => onChange({ ...value, enabled: e.target.checked })}
              className="accent-primary h-4 w-4"
            />
            <span className="text-xs text-muted-foreground">
              {value.enabled ? 'Capture enabled' : 'Capture disabled'}
            </span>
          </div>
          <div className="space-y-1">
            <Label className="text-xs">Camera Label</Label>
            <Input
              value={value.label}
              onChange={e => onChange({ ...value, label: e.target.value })}
              placeholder="e.g. Front View"
              className="h-8 text-sm"
            />
          </div>
          <div className="space-y-1">
            <Label className="text-xs">Snapshot URL</Label>
            <Input
              value={value.snapshot_url}
              onChange={e => onChange({ ...value, snapshot_url: e.target.value })}
              placeholder="rtsp://admin:password@192.168.1.13:554/ch1/main"
              className="h-8 text-sm font-mono"
            />
            <div className="rounded bg-muted/60 px-2 py-1.5 space-y-0.5">
              <p className="text-[10px] font-medium text-muted-foreground">Supported formats:</p>
              <p className="text-[10px] text-muted-foreground font-mono">rtsp://user:pass@192.168.1.x:554/ch1/main</p>
              <p className="text-[10px] text-muted-foreground font-mono">http://192.168.1.x/snapshot.jpg</p>
              <p className="text-[10px] text-muted-foreground">RTSP streams use OpenCV/FFmpeg — no extra setup needed.</p>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1">
              <Label className="text-xs">Username</Label>
              <Input
                value={value.username}
                onChange={e => onChange({ ...value, username: e.target.value })}
                placeholder="admin"
                className="h-8 text-sm"
              />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Password</Label>
              <Input
                type="password"
                value={value.password}
                onChange={e => onChange({ ...value, password: e.target.value })}
                placeholder={value.password === '***' ? '(saved)' : ''}
                className="h-8 text-sm"
              />
            </div>
          </div>
          <div className="rounded-md border border-dashed px-3 py-2 space-y-2">
            <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide">
              STQC Credentials (optional)
            </p>
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1">
                <Label className="text-xs">Verification Code</Label>
                <Input
                  value={value.verification_code}
                  onChange={e => onChange({ ...value, verification_code: e.target.value })}
                  placeholder="e.g. VC-12345"
                  className="h-8 text-sm font-mono"
                />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Serial Number</Label>
                <Input
                  value={value.serial_number}
                  onChange={e => onChange({ ...value, serial_number: e.target.value })}
                  placeholder="e.g. SN-ABCDE"
                  className="h-8 text-sm font-mono"
                />
              </div>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Version</Label>
              <Input
                value={value.version}
                onChange={e => onChange({ ...value, version: e.target.value })}
                placeholder="e.g. 1.0"
                className="h-8 text-sm font-mono"
              />
            </div>
            <p className="text-[10px] text-muted-foreground">
              Sent as query parameters: <code className="bg-muted px-1 rounded">?auth_code=…&amp;serial=…&amp;ver=…</code>
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            className="w-full"
            disabled={testing || !value.snapshot_url}
            onClick={onTest}
          >
            {testing
              ? <><Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" /> Testing…</>
              : <><TestTube className="h-3.5 w-3.5 mr-1.5" /> Test Snapshot</>}
          </Button>
          {error && <p className="text-xs text-destructive rounded bg-destructive/10 px-2 py-1">{error}</p>}
          {preview && (
            <div className="space-y-1">
              <p className="text-xs text-green-600 font-medium">✓ Connection successful</p>
              <img
                src={preview}
                alt="test snapshot"
                className="rounded-lg border w-full object-cover"
                style={{ maxHeight: '160px' }}
              />
            </div>
          )}
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <div>
        <p className="text-sm text-muted-foreground">
          Configure IP camera URLs for automatic snapshot capture when second weight is recorded.
          Snapshots are taken in the background — camera failures never block weight recording.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <CameraForm
          title="Front View Camera"
          value={front}
          onChange={setFront}
          testing={testingFront}
          preview={frontPreview}
          error={frontError}
          onTest={() => testCamera('front')}
        />
        <CameraForm
          title="Top View Camera"
          value={top}
          onChange={setTop}
          testing={testingTop}
          preview={topPreview}
          error={topError}
          onTest={() => testCamera('top')}
        />
      </div>

      <div className="flex items-center gap-3">
        <Button onClick={save} disabled={saving}>
          {saving ? <Loader2 className="h-4 w-4 mr-1.5 animate-spin" /> : <Save className="h-4 w-4 mr-1.5" />}
          Save Camera Settings
        </Button>
        {saveMsg && (
          <p className={`text-sm ${saveMsg.includes('Failed') ? 'text-destructive' : 'text-muted-foreground'}`}>
            {saveMsg}
          </p>
        )}
      </div>
    </div>
  );
}

export default function SettingsPage() {
  const [tab, setTab] = useState('company');
  const [company, setCompany] = useState<Company | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState('');

  // Financial years
  const [fyears, setFyears] = useState<FinancialYear[]>([]);
  const [fyDialog, setFyDialog] = useState(false);
  const [fyForm, setFyForm] = useState({ label: '', start_date: '', end_date: '' });
  const [fyError, setFyError] = useState('');
  const [fySaving, setFySaving] = useState(false);

  useEffect(() => {
    api.get<Company>('/api/v1/company').then(r => setCompany(r.data)).catch(() => {});
    api.get<FinancialYear[]>('/api/v1/company/financial-years').then(r => setFyears(r.data)).catch(() => {});
  }, []);

  function set(k: keyof Company, v: string) {
    setCompany(c => c ? { ...c, [k]: v } : c);
  }

  async function saveCompany() {
    if (!company) return;
    setSaving(true); setSaveMsg('');
    try {
      await api.put('/api/v1/company', company);
      setSaveMsg('Saved successfully');
      setTimeout(() => setSaveMsg(''), 3000);
    } catch { setSaveMsg('Failed to save'); }
    finally { setSaving(false); }
  }

  async function createFY() {
    if (!fyForm.label || !fyForm.start_date || !fyForm.end_date) {
      setFyError('All fields required'); return;
    }
    setFySaving(true); setFyError('');
    try {
      const { data } = await api.post<FinancialYear>('/api/v1/company/financial-years', fyForm);
      setFyears(p => [...p, data]);
      setFyDialog(false);
      setFyForm({ label: '', start_date: '', end_date: '' });
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setFyError(typeof detail === 'string' ? detail : 'Failed to create');
    } finally { setFySaving(false); }
  }

  async function activateFY(id: string) {
    await api.put(`/api/v1/company/financial-years/${id}/activate`).catch(() => {});
    setFyears(p => p.map(f => ({ ...f, is_active: f.id === id })));
  }

  if (!company) return <div className="py-12 text-center text-muted-foreground text-sm">Loading...</div>;

  return (

    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Settings</h1>
        <p className="text-muted-foreground">Company setup, financial years, invoice prefixes</p>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="flex flex-wrap h-auto gap-1 p-1">
          <TabsTrigger value="company">Company</TabsTrigger>
          <TabsTrigger value="bank">Bank Details</TabsTrigger>
          <TabsTrigger value="prefixes">Invoice Prefixes</TabsTrigger>
          <TabsTrigger value="fy">Financial Years</TabsTrigger>
          <TabsTrigger value="usb">USB Guard</TabsTrigger>
          <TabsTrigger value="scale">Weight Scale</TabsTrigger>
          <TabsTrigger value="tally">Tally</TabsTrigger>
          <TabsTrigger value="weighbridge">Weighbridge</TabsTrigger>
          <TabsTrigger value="notifications">Notifications</TabsTrigger>
          <TabsTrigger value="cameras" className="flex items-center gap-1">
            <Camera className="h-3.5 w-3.5" />Cameras
          </TabsTrigger>
        </TabsList>

        {/* Company Info */}
        <TabsContent value="company" className="mt-4">
          <Card>
            <CardHeader><CardTitle className="text-base">Company Information</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <Field label="Company Name *" value={company.name ?? ''} onChange={v => set('name', v)} placeholder="As on GST certificate" />
                <Field label="Legal Name" value={company.legal_name ?? ''} onChange={v => set('legal_name', v)} />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <Field label="GSTIN" value={company.gstin ?? ''} onChange={v => set('gstin', v.toUpperCase())} placeholder="27AAAAA0000A1Z5" />
                <Field label="PAN" value={company.pan ?? ''} onChange={v => set('pan', v.toUpperCase())} placeholder="AAAAA0000A" />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Phone" value={company.phone ?? ''} onChange={v => set('phone', v)} placeholder="9876543210" />
                <Field label="Email" value={company.email ?? ''} onChange={v => set('email', v)} type="email" />
              </div>
              <Field label="Address" value={company.address ?? ''} onChange={v => set('address', v)} placeholder="Street, Plot no" />
              <div className="grid grid-cols-3 gap-3">
                <Field label="City" value={company.city ?? ''} onChange={v => set('city', v)} />
                <Field label="State" value={company.state ?? ''} onChange={v => set('state', v)} />
                <Field label="Pincode" value={company.pincode ?? ''} onChange={v => set('pincode', v)} />
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Bank Details */}
        <TabsContent value="bank" className="mt-4">
          <Card>
            <CardHeader><CardTitle className="text-base">Bank Details</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <Field label="Bank Name" value={company.bank_name ?? ''} onChange={v => set('bank_name', v)} placeholder="State Bank of India" />
                <Field label="Account Number" value={company.bank_account_no ?? ''} onChange={v => set('bank_account_no', v)} />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <Field label="IFSC Code" value={company.bank_ifsc ?? ''} onChange={v => set('bank_ifsc', v.toUpperCase())} placeholder="SBIN0001234" />
                <Field label="Branch" value={company.bank_branch ?? ''} onChange={v => set('bank_branch', v)} />
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Prefixes */}
        <TabsContent value="prefixes" className="mt-4">
          <Card>
            <CardHeader><CardTitle className="text-base">Invoice & Voucher Prefixes</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              <p className="text-sm text-muted-foreground">
                Prefixes are used when generating document numbers (e.g. INV/25-26/0001). Changes apply to new documents only.
              </p>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Sale Invoice Prefix" value={company.sale_invoice_prefix ?? ''} onChange={v => set('sale_invoice_prefix', v)} placeholder="INV" />
                <Field label="Purchase Invoice Prefix" value={company.purchase_invoice_prefix ?? ''} onChange={v => set('purchase_invoice_prefix', v)} placeholder="PINV" />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Receipt Prefix" value={company.receipt_prefix ?? ''} onChange={v => set('receipt_prefix', v)} placeholder="REC" />
                <Field label="Voucher Prefix" value={company.voucher_prefix ?? ''} onChange={v => set('voucher_prefix', v)} placeholder="PMT" />
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Financial Years */}
        <TabsContent value="fy" className="mt-4 space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-sm text-muted-foreground">Active financial year determines number sequences and period filtering.</p>
            <Button size="sm" onClick={() => { setFyDialog(true); setFyError(''); }}>
              <Plus className="mr-2 h-4 w-4" /> New FY
            </Button>
          </div>
          <Card>
            <CardContent className="p-0">
              {fyears.length === 0 ? (
                <div className="py-10 text-center text-sm text-muted-foreground">No financial years configured.</div>
              ) : (
                <div className="divide-y">
                  {fyears.map(fy => (
                    <div key={fy.id} className="flex items-center gap-4 px-4 py-3">
                      <div className="flex-1">
                        <div className="flex items-center gap-2">
                          <p className="font-medium text-sm">{fy.label}</p>
                          {fy.is_active && <Badge className="bg-green-100 text-green-800 text-[10px]">Active</Badge>}
                        </div>
                        <p className="text-xs text-muted-foreground">{fy.start_date} → {fy.end_date}</p>
                      </div>
                      {!fy.is_active && (
                        <Button size="sm" variant="outline" onClick={() => activateFY(fy.id)}>
                          <CheckCircle2 className="mr-1 h-3.5 w-3.5" /> Set Active
                        </Button>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* USB Guard */}
        <TabsContent value="usb" className="mt-4">
          <UsbGuardTab />
        </TabsContent>

        {/* Weight Scale */}
        <TabsContent value="scale" className="mt-4">
          <WeightScaleTab />
        </TabsContent>

        {/* Tally Integration */}
        <TabsContent value="tally" className="mt-4">
          <TallyTab />
        </TabsContent>

        {/* Weighbridge urgency thresholds */}
        <TabsContent value="weighbridge" className="mt-4">
          <WeighbridgeTab />
        </TabsContent>

        {/* Notifications Config */}
        <TabsContent value="notifications" className="mt-4">
          <NotificationsConfigTab />
        </TabsContent>

        {/* Cameras */}
        <TabsContent value="cameras" className="mt-4">
          <CameraSettingsTab />
        </TabsContent>
      </Tabs>

      {/* Save button (not on FY, USB Guard, Scale, Tally, Weighbridge, or Notifications tabs) */}
      {tab !== 'fy' && tab !== 'usb' && tab !== 'scale' && tab !== 'tally' && tab !== 'weighbridge' && tab !== 'notifications' && tab !== 'cameras' && (
        <div className="flex items-center gap-3">
          <Button onClick={saveCompany} disabled={saving}>
            {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            <Save className="mr-2 h-4 w-4" /> Save Changes
          </Button>
          {saveMsg && <p className="text-sm text-muted-foreground">{saveMsg}</p>}
        </div>
      )}

      {/* New FY Dialog */}
      <Dialog open={fyDialog} onOpenChange={v => !v && setFyDialog(false)}>
        <DialogContent>
          <DialogHeader><DialogTitle>New Financial Year</DialogTitle></DialogHeader>
          <div className="space-y-3">
            {fyError && <p className="text-sm text-destructive">{fyError}</p>}
            <Field label="Label (e.g. 2025-26)" value={fyForm.label} onChange={v => setFyForm(f => ({ ...f, label: v }))} />
            <div className="grid grid-cols-2 gap-3">
              <Field label="Start Date" value={fyForm.start_date} onChange={v => setFyForm(f => ({ ...f, start_date: v }))} type="date" />
              <Field label="End Date" value={fyForm.end_date} onChange={v => setFyForm(f => ({ ...f, end_date: v }))} type="date" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setFyDialog(false)}>Cancel</Button>
            <Button onClick={createFY} disabled={fySaving}>
              {fySaving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Create
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
