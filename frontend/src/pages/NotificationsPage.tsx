import { useState, useEffect, useCallback } from 'react';
import { toast } from 'sonner';
import { Bell, Send, Plus, Edit2, Trash2, Mail, MessageSquare, Phone, Users } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import api from '@/services/api';

const EVENT_TYPES = [
  { value: 'invoice_finalized', label: 'Invoice Finalized' },
  { value: 'payment_received', label: 'Payment Received' },
  { value: 'quotation_sent', label: 'Quotation Sent' },
  { value: 'token_completed', label: 'Token / Weighment Completed' },
  { value: 'invoice_overdue', label: 'Invoice Overdue' },
  { value: 'low_balance', label: 'Low Balance Alert' },
];

const CHANNELS = [
  { value: 'email', label: 'Email', icon: Mail },
  { value: 'sms', label: 'SMS', icon: Phone },
  { value: 'whatsapp', label: 'WhatsApp', icon: MessageSquare },
  { value: 'telegram', label: 'Telegram', icon: Send },
];

// Channels that can be used for named recipients (party-contact channels excluded Telegram)
const RECIPIENT_CHANNELS = [
  { value: 'email', label: 'Email' },
  { value: 'sms', label: 'SMS' },
  { value: 'telegram', label: 'Telegram' },
];

interface Template {
  id: string;
  event_type: string;
  channel: string;
  name: string;
  subject: string | null;
  body: string;
  is_enabled: boolean;
  updated_at: string | null;
}

interface Recipient {
  id: string;
  name: string;
  channel: string;
  contact: string;
  event_types: string[];
  is_active: boolean;
  created_at: string | null;
}

interface LogEntry {
  id: string;
  channel: string;
  event_type: string;
  entity_type: string | null;
  entity_id: string | null;
  recipient: string;
  subject: string | null;
  body_preview: string | null;
  status: string;
  error_message: string | null;
  sent_at: string | null;
}

const VARS_HINT: Record<string, string[]> = {
  invoice_finalized: ['party_name', 'party_email', 'party_phone', 'invoice_no', 'invoice_date', 'grand_total', 'company_name'],
  payment_received: ['party_name', 'party_email', 'party_phone', 'receipt_no', 'receipt_date', 'amount', 'company_name'],
  quotation_sent: ['party_name', 'party_email', 'quotation_no', 'valid_to', 'grand_total', 'company_name'],
  token_completed: ['token_no', 'vehicle_no', 'net_weight', 'completed_at', 'party_phone', 'company_name'],
  invoice_overdue: ['party_name', 'party_phone', 'invoice_no', 'amount_due', 'due_date', 'company_name'],
  low_balance: ['party_name', 'party_phone', 'current_balance', 'company_name'],
};

function statusBadge(status: string) {
  if (status === 'sent') return <Badge className="bg-green-100 text-green-800 text-[10px]">Sent</Badge>;
  if (status === 'failed') return <Badge className="bg-red-100 text-red-800 text-[10px]">Failed</Badge>;
  return <Badge className="bg-yellow-100 text-yellow-800 text-[10px]">Pending</Badge>;
}

function channelBadge(channel: string) {
  const colors: Record<string, string> = {
    email: 'bg-blue-100 text-blue-800',
    sms: 'bg-purple-100 text-purple-800',
    whatsapp: 'bg-green-100 text-green-800',
    telegram: 'bg-sky-100 text-sky-800',
  };
  return <Badge className={`${colors[channel] || 'bg-gray-100 text-gray-700'} text-[10px]`}>{channel}</Badge>;
}

function contactPlaceholder(channel: string) {
  if (channel === 'email') return 'admin@example.com';
  if (channel === 'sms') return '9876543210';
  if (channel === 'telegram') return '-1001234567890 (chat ID)';
  return '';
}

export default function NotificationsPage() {
  const [tab, setTab] = useState('templates');
  const [templates, setTemplates] = useState<Template[]>([]);
  const [recipients, setRecipients] = useState<Recipient[]>([]);
  const [logItems, setLogItems] = useState<LogEntry[]>([]);
  const [logTotal, setLogTotal] = useState(0);
  const [logPage, setLogPage] = useState(1);
  const [logFilter, setLogFilter] = useState({ channel: '', status: '', event_type: '' });
  const [loading, setLoading] = useState(false);

  // Template dialog
  const [tmplDialog, setTmplDialog] = useState(false);
  const [editing, setEditing] = useState<Template | null>(null);
  const [tmplForm, setTmplForm] = useState({ event_type: 'invoice_finalized', channel: 'email', name: '', subject: '', body: '', is_enabled: true });

  // Recipient dialog
  const [recipDialog, setRecipDialog] = useState(false);
  const [editingRecip, setEditingRecip] = useState<Recipient | null>(null);
  const [recipForm, setRecipForm] = useState({
    name: '',
    channel: 'telegram',
    contact: '',
    event_types: ['*'] as string[],
    is_active: true,
  });

  // Test send
  const [testDialog, setTestDialog] = useState(false);
  const [testChannel, setTestChannel] = useState('');
  const [testRecipient, setTestRecipient] = useState('');
  const [testMsg, setTestMsg] = useState('');
  const [testLoading, setTestLoading] = useState(false);

  const loadTemplates = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.get('/api/v1/notifications/templates');
      setTemplates(r.data);
    } catch {
      setTemplates([]);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadRecipients = useCallback(async () => {
    try {
      const r = await api.get('/api/v1/notifications/recipients');
      setRecipients(Array.isArray(r.data) ? r.data : []);
    } catch {
      setRecipients([]);
    }
  }, []);

  const loadLog = useCallback(async () => {
    const p = new URLSearchParams({ page: String(logPage), page_size: '50' });
    if (logFilter.channel) p.set('channel', logFilter.channel);
    if (logFilter.status) p.set('status', logFilter.status);
    if (logFilter.event_type) p.set('event_type', logFilter.event_type);
    try {
      const r = await api.get(`/api/v1/notifications/log?${p}`);
      setLogItems(r.data.items);
      setLogTotal(r.data.total);
    } catch {
      setLogItems([]);
    }
  }, [logPage, logFilter]);

  useEffect(() => { loadTemplates(); }, [loadTemplates]);
  useEffect(() => { if (tab === 'recipients') loadRecipients(); }, [tab, loadRecipients]);
  useEffect(() => { if (tab === 'log') loadLog(); }, [tab, loadLog]);

  // ── Template CRUD ───────────────────────────────────────────────────────────
  function openNew() {
    setEditing(null);
    setTmplForm({ event_type: 'invoice_finalized', channel: 'email', name: '', subject: '', body: '', is_enabled: true });
    setTmplDialog(true);
  }

  function openEdit(t: Template) {
    setEditing(t);
    setTmplForm({ event_type: t.event_type, channel: t.channel, name: t.name, subject: t.subject || '', body: t.body, is_enabled: t.is_enabled });
    setTmplDialog(true);
  }

  async function saveTmpl() {
    try {
      if (editing) {
        await api.put(`/api/v1/notifications/templates/${editing.id}`, tmplForm);
      } else {
        await api.post('/api/v1/notifications/templates', tmplForm);
      }
      setTmplDialog(false);
      loadTemplates();
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || 'Save failed');
    }
  }

  async function deleteTmpl(id: string) {
    if (!confirm('Delete this template?')) return;
    await api.delete(`/api/v1/notifications/templates/${id}`);
    loadTemplates();
  }

  // ── Recipient CRUD ──────────────────────────────────────────────────────────
  function openNewRecip() {
    setEditingRecip(null);
    setRecipForm({ name: '', channel: 'telegram', contact: '', event_types: ['*'], is_active: true });
    setRecipDialog(true);
  }

  function openEditRecip(r: Recipient) {
    setEditingRecip(r);
    setRecipForm({ name: r.name, channel: r.channel, contact: r.contact, event_types: r.event_types, is_active: r.is_active });
    setRecipDialog(true);
  }

  async function saveRecip() {
    try {
      const payload = { ...recipForm };
      if (editingRecip) {
        await api.put(`/api/v1/notifications/recipients/${editingRecip.id}`, payload);
        toast.success('Recipient updated');
      } else {
        await api.post('/api/v1/notifications/recipients', payload);
        toast.success('Recipient added');
      }
      setRecipDialog(false);
      loadRecipients();
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || 'Save failed');
    }
  }

  async function deleteRecip(id: string) {
    if (!confirm('Remove this recipient?')) return;
    await api.delete(`/api/v1/notifications/recipients/${id}`);
    loadRecipients();
    toast.success('Recipient removed');
  }

  function toggleEventType(evt: string) {
    setRecipForm(f => {
      if (evt === '*') return { ...f, event_types: ['*'] };
      const without = f.event_types.filter(e => e !== '*' && e !== evt);
      const included = f.event_types.includes(evt);
      return { ...f, event_types: included ? without : [...without, evt] };
    });
  }

  // ── Test send ───────────────────────────────────────────────────────────────
  async function sendTest() {
    setTestLoading(true);
    setTestMsg('');
    try {
      const r = await api.post(`/api/v1/notifications/config/${testChannel}/test`, { channel: testChannel, recipient: testRecipient });
      setTestMsg('✅ ' + r.data.message);
    } catch (e: any) {
      setTestMsg('❌ ' + (e?.response?.data?.detail || 'Send failed'));
    } finally {
      setTestLoading(false);
    }
  }

  // Group templates by event_type
  const byEvent: Record<string, Template[]> = {};
  for (const t of templates) {
    (byEvent[t.event_type] = byEvent[t.event_type] || []).push(t);
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Notifications</h1>
          <p className="text-muted-foreground">Email · SMS · WhatsApp · Telegram — templates, recipients, and delivery log</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => { setTestChannel('email'); setTestRecipient(''); setTestMsg(''); setTestDialog(true); }}>
            <Send className="mr-2 h-4 w-4" /> Test Send
          </Button>
          {tab === 'templates' && (
            <Button onClick={openNew}><Plus className="mr-2 h-4 w-4" /> New Template</Button>
          )}
          {tab === 'recipients' && (
            <Button onClick={openNewRecip}><Plus className="mr-2 h-4 w-4" /> Add Recipient</Button>
          )}
        </div>
      </div>

      <Tabs value={tab} onValueChange={v => setTab(v ?? 'templates')}>
        <TabsList>
          <TabsTrigger value="templates">Templates</TabsTrigger>
          <TabsTrigger value="recipients"><Users className="mr-1 h-3.5 w-3.5" />Recipients</TabsTrigger>
          <TabsTrigger value="log">Delivery Log</TabsTrigger>
        </TabsList>

        {/* ── Templates ── */}
        <TabsContent value="templates" className="mt-4 space-y-4">
          {loading ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : (
            Object.entries(byEvent).map(([evt, tmpls]) => {
              const evtLabel = EVENT_TYPES.find(e => e.value === evt)?.label || evt;
              return (
                <Card key={evt}>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm flex items-center gap-2">
                      <Bell className="h-4 w-4 text-primary" />
                      {evtLabel}
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="p-0">
                    <table className="w-full text-sm">
                      <thead><tr className="border-b bg-muted/30">
                        <th className="px-4 py-2 text-left font-medium text-muted-foreground">Channel</th>
                        <th className="px-4 py-2 text-left font-medium text-muted-foreground">Name</th>
                        <th className="px-4 py-2 text-left font-medium text-muted-foreground">Subject</th>
                        <th className="px-4 py-2 text-center font-medium text-muted-foreground">Status</th>
                        <th className="px-4 py-2 text-right font-medium text-muted-foreground">Actions</th>
                      </tr></thead>
                      <tbody>
                        {tmpls.map(t => (
                          <tr key={t.id} className="border-b hover:bg-muted/10">
                            <td className="px-4 py-2">{channelBadge(t.channel)}</td>
                            <td className="px-4 py-2 font-medium text-sm">{t.name}</td>
                            <td className="px-4 py-2 text-xs text-muted-foreground truncate max-w-[200px]">{t.subject || '—'}</td>
                            <td className="px-4 py-2 text-center">
                              <Badge className={t.is_enabled ? 'bg-green-100 text-green-800 text-[10px]' : 'bg-gray-100 text-gray-600 text-[10px]'}>
                                {t.is_enabled ? 'Active' : 'Disabled'}
                              </Badge>
                            </td>
                            <td className="px-4 py-2 text-right">
                              <Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => openEdit(t)}><Edit2 className="h-3.5 w-3.5" /></Button>
                              <Button size="icon" variant="ghost" className="h-7 w-7 text-destructive" onClick={() => deleteTmpl(t.id)}><Trash2 className="h-3.5 w-3.5" /></Button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </CardContent>
                </Card>
              );
            })
          )}
          {templates.length === 0 && !loading && (
            <div className="py-12 text-center text-muted-foreground text-sm">No templates yet. Click "New Template" to create one.</div>
          )}
        </TabsContent>

        {/* ── Recipients ── */}
        <TabsContent value="recipients" className="mt-4 space-y-4">
          <div className="rounded-md border bg-sky-50 text-sky-800 px-4 py-3 text-sm">
            <strong>Named recipients</strong> are internal contacts (staff, owners) notified for every matching event — separate from party/customer notifications.
            Use <strong>Telegram chat IDs</strong> for instant alerts. Get your chat ID from <code>@userinfobot</code> on Telegram.
          </div>

          <Card><CardContent className="p-0">
            <table className="w-full text-sm">
              <thead><tr className="border-b bg-muted/50">
                <th className="px-4 py-2 text-left font-medium text-muted-foreground">Name</th>
                <th className="px-4 py-2 text-left font-medium text-muted-foreground">Channel</th>
                <th className="px-4 py-2 text-left font-medium text-muted-foreground">Contact</th>
                <th className="px-4 py-2 text-left font-medium text-muted-foreground">Events</th>
                <th className="px-4 py-2 text-center font-medium text-muted-foreground">Active</th>
                <th className="px-4 py-2 text-right font-medium text-muted-foreground">Actions</th>
              </tr></thead>
              <tbody>
                {recipients.map(r => (
                  <tr key={r.id} className="border-b hover:bg-muted/20">
                    <td className="px-4 py-2 font-medium">{r.name}</td>
                    <td className="px-4 py-2">{channelBadge(r.channel)}</td>
                    <td className="px-4 py-2 text-xs font-mono text-muted-foreground">{r.contact}</td>
                    <td className="px-4 py-2 text-xs text-muted-foreground">
                      {r.event_types.includes('*')
                        ? <Badge className="bg-gray-100 text-gray-700 text-[10px]">All events</Badge>
                        : r.event_types.map(e => (
                            <Badge key={e} className="bg-muted text-muted-foreground text-[10px] mr-1">
                              {EVENT_TYPES.find(et => et.value === e)?.label || e}
                            </Badge>
                          ))}
                    </td>
                    <td className="px-4 py-2 text-center">
                      <Badge className={r.is_active ? 'bg-green-100 text-green-800 text-[10px]' : 'bg-gray-100 text-gray-600 text-[10px]'}>
                        {r.is_active ? 'Active' : 'Inactive'}
                      </Badge>
                    </td>
                    <td className="px-4 py-2 text-right">
                      <Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => openEditRecip(r)}><Edit2 className="h-3.5 w-3.5" /></Button>
                      <Button size="icon" variant="ghost" className="h-7 w-7 text-destructive" onClick={() => deleteRecip(r.id)}><Trash2 className="h-3.5 w-3.5" /></Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {recipients.length === 0 && (
              <div className="py-12 text-center text-muted-foreground text-sm">
                No recipients configured. Click "Add Recipient" to add staff/owner contacts.
              </div>
            )}
          </CardContent></Card>
        </TabsContent>

        {/* ── Delivery Log ── */}
        <TabsContent value="log" className="mt-4 space-y-4">
          <div className="flex flex-wrap gap-2">
            <Select value={logFilter.channel || 'all'} onValueChange={v => setLogFilter(f => ({ ...f, channel: v === 'all' || !v ? '' : v }))}>
              <SelectTrigger className="w-32"><SelectValue placeholder="Channel" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Channels</SelectItem>
                {CHANNELS.map(c => <SelectItem key={c.value} value={c.value}>{c.label}</SelectItem>)}
              </SelectContent>
            </Select>
            <Select value={logFilter.status || 'all'} onValueChange={v => setLogFilter(f => ({ ...f, status: v === 'all' || !v ? '' : v }))}>
              <SelectTrigger className="w-32"><SelectValue placeholder="Status" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Statuses</SelectItem>
                <SelectItem value="sent">Sent</SelectItem>
                <SelectItem value="failed">Failed</SelectItem>
                <SelectItem value="pending">Pending</SelectItem>
              </SelectContent>
            </Select>
            <Select value={logFilter.event_type || 'all'} onValueChange={v => setLogFilter(f => ({ ...f, event_type: v === 'all' || !v ? '' : v }))}>
              <SelectTrigger className="w-48"><SelectValue placeholder="Event" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Events</SelectItem>
                {EVENT_TYPES.map(e => <SelectItem key={e.value} value={e.value}>{e.label}</SelectItem>)}
              </SelectContent>
            </Select>
            <Button onClick={loadLog}>Refresh</Button>
          </div>

          <Card><CardContent className="p-0">
            <table className="w-full text-sm">
              <thead><tr className="border-b bg-muted/50">
                <th className="px-3 py-2 text-left font-medium text-muted-foreground">Time</th>
                <th className="px-3 py-2 text-left font-medium text-muted-foreground">Channel</th>
                <th className="px-3 py-2 text-left font-medium text-muted-foreground">Event</th>
                <th className="px-3 py-2 text-left font-medium text-muted-foreground">Recipient</th>
                <th className="px-3 py-2 text-left font-medium text-muted-foreground">Subject / Preview</th>
                <th className="px-3 py-2 text-center font-medium text-muted-foreground">Status</th>
              </tr></thead>
              <tbody>
                {logItems.map(r => (
                  <tr key={r.id} className="border-b hover:bg-muted/20">
                    <td className="px-3 py-2 text-xs text-muted-foreground whitespace-nowrap">
                      {r.sent_at ? new Date(r.sent_at).toLocaleString('en-IN') : '—'}
                    </td>
                    <td className="px-3 py-2">{channelBadge(r.channel)}</td>
                    <td className="px-3 py-2 text-xs">{EVENT_TYPES.find(e => e.value === r.event_type)?.label || r.event_type}</td>
                    <td className="px-3 py-2 text-xs font-mono">{r.recipient}</td>
                    <td className="px-3 py-2 text-xs text-muted-foreground truncate max-w-[200px]">
                      {r.subject || r.body_preview || '—'}
                      {r.error_message && <p className="text-red-600 mt-0.5 truncate">{r.error_message}</p>}
                    </td>
                    <td className="px-3 py-2 text-center">{statusBadge(r.status)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {logItems.length === 0 && <div className="py-12 text-center text-muted-foreground text-sm">No delivery log entries.</div>}
          </CardContent></Card>

          {logTotal > 50 && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Button size="sm" variant="outline" disabled={logPage === 1} onClick={() => setLogPage(p => p - 1)}>Prev</Button>
              <span>Page {logPage} · {logTotal} total</span>
              <Button size="sm" variant="outline" disabled={logPage * 50 >= logTotal} onClick={() => setLogPage(p => p + 1)}>Next</Button>
            </div>
          )}
        </TabsContent>
      </Tabs>

      {/* ── Template Editor Dialog ── */}
      <Dialog open={tmplDialog} onOpenChange={setTmplDialog}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader><DialogTitle>{editing ? 'Edit Template' : 'New Template'}</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1">
                <Label className="text-xs">Event Type</Label>
                <Select value={tmplForm.event_type} onValueChange={v => setTmplForm(f => ({ ...f, event_type: v ?? '' }))}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>{EVENT_TYPES.map(e => <SelectItem key={e.value} value={e.value}>{e.label}</SelectItem>)}</SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Channel</Label>
                <Select value={tmplForm.channel} onValueChange={v => setTmplForm(f => ({ ...f, channel: v ?? '' }))}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>{CHANNELS.map(c => <SelectItem key={c.value} value={c.value}>{c.label}</SelectItem>)}</SelectContent>
                </Select>
              </div>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Template Name</Label>
              <Input value={tmplForm.name} onChange={e => setTmplForm(f => ({ ...f, name: e.target.value }))} placeholder="e.g. Invoice Finalized Email" />
            </div>
            {tmplForm.channel === 'email' && (
              <div className="space-y-1">
                <Label className="text-xs">Subject</Label>
                <Input value={tmplForm.subject} onChange={e => setTmplForm(f => ({ ...f, subject: e.target.value }))} placeholder="Invoice {{ invoice_no }} from {{ company_name }}" />
              </div>
            )}
            <div className="space-y-1">
              <Label className="text-xs">
                Body (Jinja2 template)
                {tmplForm.channel === 'telegram' && (
                  <span className="ml-2 text-[10px] text-muted-foreground">— HTML tags supported: &lt;b&gt;, &lt;i&gt;, &lt;code&gt;</span>
                )}
              </Label>
              <Textarea
                value={tmplForm.body}
                onChange={e => setTmplForm(f => ({ ...f, body: e.target.value }))}
                className="font-mono text-xs min-h-[160px]"
                placeholder="Dear {{ party_name }}, ..."
              />
            </div>
            {/* Variable hints */}
            <div className="rounded bg-muted/40 px-3 py-2">
              <p className="text-xs font-medium text-muted-foreground mb-1">Available variables:</p>
              <div className="flex flex-wrap gap-1">
                {(VARS_HINT[tmplForm.event_type] || []).map(v => (
                  <code key={v} className="text-[10px] bg-background border rounded px-1">{'{{ ' + v + ' }}'}</code>
                ))}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <input type="checkbox" id="tpl-enabled" checked={tmplForm.is_enabled} onChange={e => setTmplForm(f => ({ ...f, is_enabled: e.target.checked }))} />
              <Label htmlFor="tpl-enabled" className="text-xs cursor-pointer">Enabled</Label>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setTmplDialog(false)}>Cancel</Button>
            <Button onClick={saveTmpl}>Save Template</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Recipient Dialog ── */}
      <Dialog open={recipDialog} onOpenChange={setRecipDialog}>
        <DialogContent className="max-w-lg">
          <DialogHeader><DialogTitle>{editingRecip ? 'Edit Recipient' : 'Add Recipient'}</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <div className="space-y-1">
              <Label className="text-xs">Display Name</Label>
              <Input value={recipForm.name} onChange={e => setRecipForm(f => ({ ...f, name: e.target.value }))} placeholder="e.g. Owner Telegram, Manager Email" />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1">
                <Label className="text-xs">Channel</Label>
                <Select value={recipForm.channel} onValueChange={v => setRecipForm(f => ({ ...f, channel: v ?? 'telegram' }))}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>{RECIPIENT_CHANNELS.map(c => <SelectItem key={c.value} value={c.value}>{c.label}</SelectItem>)}</SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label className="text-xs">
                  {recipForm.channel === 'email' ? 'Email Address' : recipForm.channel === 'sms' ? 'Phone Number' : 'Telegram Chat ID'}
                </Label>
                <Input
                  value={recipForm.contact}
                  onChange={e => setRecipForm(f => ({ ...f, contact: e.target.value }))}
                  placeholder={contactPlaceholder(recipForm.channel)}
                />
              </div>
            </div>

            {recipForm.channel === 'telegram' && (
              <p className="text-xs text-muted-foreground">
                💡 Get your chat ID: message <code>@userinfobot</code> on Telegram, it will reply with your numeric ID.
                For groups/channels, forward a message to <code>@getidsbot</code>.
              </p>
            )}

            <div className="space-y-2">
              <Label className="text-xs">Notify for events</Label>
              <div className="flex flex-wrap gap-2">
                <label className="flex items-center gap-1.5 cursor-pointer text-xs">
                  <input
                    type="checkbox"
                    checked={recipForm.event_types.includes('*')}
                    onChange={() => toggleEventType('*')}
                  />
                  All events
                </label>
                {!recipForm.event_types.includes('*') && EVENT_TYPES.map(evt => (
                  <label key={evt.value} className="flex items-center gap-1.5 cursor-pointer text-xs">
                    <input
                      type="checkbox"
                      checked={recipForm.event_types.includes(evt.value)}
                      onChange={() => toggleEventType(evt.value)}
                    />
                    {evt.label}
                  </label>
                ))}
              </div>
            </div>

            <div className="flex items-center gap-2">
              <input type="checkbox" id="recip-active" checked={recipForm.is_active} onChange={e => setRecipForm(f => ({ ...f, is_active: e.target.checked }))} />
              <Label htmlFor="recip-active" className="text-xs cursor-pointer">Active</Label>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRecipDialog(false)}>Cancel</Button>
            <Button onClick={saveRecip}>Save</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Test Send Dialog ── */}
      <Dialog open={testDialog} onOpenChange={setTestDialog}>
        <DialogContent>
          <DialogHeader><DialogTitle>Test Notification Send</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <div className="space-y-1">
              <Label className="text-xs">Channel</Label>
              <Select value={testChannel} onValueChange={v => { setTestChannel(v ?? 'email'); setTestRecipient(''); }}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>{CHANNELS.map(c => <SelectItem key={c.value} value={c.value}>{c.label}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">
                {testChannel === 'email' ? 'Email Address' : testChannel === 'telegram' ? 'Telegram Chat ID' : 'Phone Number'}
              </Label>
              <Input
                value={testRecipient}
                onChange={e => setTestRecipient(e.target.value)}
                placeholder={contactPlaceholder(testChannel)}
              />
            </div>
            {testMsg && <p className={`text-sm ${testMsg.startsWith('✅') ? 'text-green-700' : 'text-red-600'}`}>{testMsg}</p>}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setTestDialog(false)}>Close</Button>
            <Button onClick={sendTest} disabled={testLoading || !testRecipient}>
              <Send className="mr-2 h-4 w-4" />{testLoading ? 'Sending…' : 'Send Test'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
