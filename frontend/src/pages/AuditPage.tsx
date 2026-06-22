import { useState, useEffect, useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Search, RefreshCw, Activity, Shield } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { DataTable, type ColumnDef } from '@/components/DataTable';
import api from '@/services/api';

interface AuditEntry {
  id: string;
  user_id: string | null;
  username: string | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
  details: string | null;
  ip_address: string | null;
  created_at: string;
}

interface AuditStats {
  by_action: Record<string, number>;
  by_entity: Record<string, number>;
}

interface AuditResponse {
  items: AuditEntry[];
  total: number;
  page: number;
  page_size: number;
}

const ACTION_COLORS: Record<string, string> = {
  create: 'bg-green-100 text-green-800',
  update: 'bg-blue-100 text-blue-800',
  delete: 'bg-red-100 text-red-800',
  cancel: 'bg-orange-100 text-orange-800',
  finalize: 'bg-purple-100 text-purple-800',
  revised: 'bg-indigo-100 text-indigo-800',
  completed: 'bg-emerald-100 text-emerald-800',
  first_weight: 'bg-cyan-100 text-cyan-800',
  second_weight: 'bg-teal-100 text-teal-800',
  login: 'bg-gray-100 text-gray-800',
  payment: 'bg-yellow-100 text-yellow-800',
  approve: 'bg-green-100 text-green-800',
  reject: 'bg-red-100 text-red-800',
  receive: 'bg-sky-100 text-sky-800',
  convert: 'bg-violet-100 text-violet-800',
  send: 'bg-pink-100 text-pink-800',
  sync: 'bg-amber-100 text-amber-800',
};

// Entity → relevant actions mapping (keeps dropdown clean and contextual)
const ENTITY_ACTIONS: Record<string, { value: string; label: string }[]> = {
  invoice: [
    { value: 'create', label: 'Created' },
    { value: 'update', label: 'Updated' },
    { value: 'finalize', label: 'Finalized' },
    { value: 'cancel', label: 'Cancelled' },
    { value: 'revised', label: 'Revised' },
    { value: 'delete', label: 'Deleted' },
    { value: 'sync', label: 'Tally Synced' },
  ],
  token: [
    { value: 'create', label: 'Created' },
    { value: 'first_weight', label: 'First Weight' },
    { value: 'second_weight', label: 'Second Weight' },
    { value: 'completed', label: 'Completed' },
    { value: 'cancel', label: 'Cancelled' },
  ],
  payment: [
    { value: 'create', label: 'Received' },
    { value: 'delete', label: 'Deleted' },
  ],
  party: [
    { value: 'create', label: 'Created' },
    { value: 'update', label: 'Updated' },
    { value: 'delete', label: 'Deleted' },
    { value: 'sync', label: 'Tally Synced' },
  ],
  product: [
    { value: 'create', label: 'Created' },
    { value: 'update', label: 'Updated' },
    { value: 'delete', label: 'Deleted' },
  ],
  vehicle: [
    { value: 'create', label: 'Created' },
    { value: 'update', label: 'Updated' },
    { value: 'delete', label: 'Deleted' },
  ],
  user: [
    { value: 'create', label: 'Created' },
    { value: 'update', label: 'Updated' },
    { value: 'login', label: 'Login' },
  ],
  quotation: [
    { value: 'create', label: 'Created' },
    { value: 'update', label: 'Updated' },
    { value: 'send', label: 'Sent' },
    { value: 'convert', label: 'Converted' },
    { value: 'cancel', label: 'Cancelled' },
  ],
  purchase_order: [
    { value: 'create', label: 'Created' },
    { value: 'approve', label: 'Approved' },
    { value: 'reject', label: 'Rejected' },
    { value: 'receive', label: 'Received' },
  ],
  inventory: [
    { value: 'create', label: 'Created' },
    { value: 'update', label: 'Updated' },
    { value: 'delete', label: 'Deleted' },
  ],
};

// All unique actions (for when no entity is selected)
const ALL_ACTIONS = [
  { value: 'create', label: 'Create' },
  { value: 'update', label: 'Update' },
  { value: 'finalize', label: 'Finalize' },
  { value: 'cancel', label: 'Cancel' },
  { value: 'revised', label: 'Revised' },
  { value: 'completed', label: 'Completed' },
  { value: 'first_weight', label: 'First Weight' },
  { value: 'second_weight', label: 'Second Weight' },
  { value: 'delete', label: 'Delete' },
  { value: 'payment', label: 'Payment' },
  { value: 'approve', label: 'Approve' },
  { value: 'reject', label: 'Reject' },
  { value: 'receive', label: 'Receive' },
  { value: 'convert', label: 'Convert' },
  { value: 'send', label: 'Send' },
  { value: 'sync', label: 'Tally Sync' },
  { value: 'login', label: 'Login' },
];

const ENTITY_LABELS: Record<string, string> = {
  invoice: 'Invoice',
  token: 'Token',
  payment: 'Payment',
  party: 'Party',
  product: 'Product',
  vehicle: 'Vehicle',
  user: 'User',
  quotation: 'Quotation',
  purchase_order: 'Purchase Order',
  inventory: 'Inventory',
};

function actionBadgeClass(action: string) {
  return ACTION_COLORS[action] ?? 'bg-gray-100 text-gray-600';
}

function formatDt(iso: string) {
  return new Date(iso).toLocaleString('en-IN', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

function parseDetails(raw: string | null): string {
  if (!raw) return '';
  try {
    const obj = JSON.parse(raw);
    return Object.entries(obj).map(([k, v]) => `${k}: ${v}`).join(' · ');
  } catch {
    return raw;
  }
}

export default function AuditPage() {
  const { t } = useTranslation();
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState<AuditStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 50;

  // Filters
  const [action, setAction] = useState('');
  const [entityType, setEntityType] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [search, setSearch] = useState('');

  // Get available actions based on selected entity
  const availableActions = entityType
    ? (ENTITY_ACTIONS[entityType] ?? ALL_ACTIONS)
    : ALL_ACTIONS;

  // Reset action when entity changes and current action is not valid for new entity
  function handleEntityChange(newEntity: string) {
    setEntityType(newEntity);
    if (newEntity && action) {
      const validActions = ENTITY_ACTIONS[newEntity];
      if (validActions && !validActions.some(a => a.value === action)) {
        setAction('');
      }
    }
  }

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string | number> = { page, page_size: PAGE_SIZE };
      if (action) params.action = action;
      if (entityType) params.entity_type = entityType;
      if (dateFrom) params.date_from = dateFrom;
      if (dateTo) params.date_to = dateTo;
      if (search) params.search = search;

      const [auditRes, statsRes] = await Promise.all([
        api.get<AuditResponse>('/api/v1/audit', { params }),
        api.get<AuditStats>('/api/v1/audit/stats'),
      ]);
      setEntries(auditRes.data.items);
      setTotal(auditRes.data.total);
      setStats(statsRes.data);
    } catch { /* ignore */ }
    finally { setLoading(false); }
  }, [page, action, entityType, dateFrom, dateTo, search]);

  useEffect(() => { load(); }, [load]);

  function applyFilters() { setPage(1); load(); }

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight flex items-center gap-2">
          <Shield className="h-8 w-8 text-primary" /> {t('auditTrail.title')}
        </h1>
        <p className="text-muted-foreground">{t('auditTrail.subtitle')}</p>
      </div>

      {/* Stats cards */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {Object.entries(stats.by_action).slice(0, 4).map(([act, count]) => (
            <Card key={act}>
              <CardContent className="pt-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-xs text-muted-foreground capitalize">{act.replace(/_/g, ' ')}</p>
                    <p className="text-2xl font-bold">{count}</p>
                  </div>
                  <Activity className="h-8 w-8 text-muted-foreground/30" />
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Filters */}
      <Card>
        <CardContent className="pt-4">
          <div className="flex flex-wrap gap-3 items-end">
            <div className="flex-1 min-w-[180px] space-y-1">
              <p className="text-xs font-medium text-muted-foreground">Search</p>
              <div className="relative">
                <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input
                  className="pl-8"
                  placeholder="Invoice no, entity ID..."
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && applyFilters()}
                />
              </div>
            </div>

            <div className="w-44 space-y-1">
              <p className="text-xs font-medium text-muted-foreground">Entity</p>
              <Select value={entityType || 'all'} onValueChange={v => handleEntityChange(v === 'all' ? '' : (v ?? ''))}>
                <SelectTrigger><SelectValue placeholder={t('auditTrail.allTypes')} /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">{t('auditTrail.allTypes')}</SelectItem>
                  {Object.entries(ENTITY_LABELS).map(([key, label]) => (
                    <SelectItem key={key} value={key}>{label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="w-40 space-y-1">
              <p className="text-xs font-medium text-muted-foreground">Action</p>
              <Select value={action || 'all'} onValueChange={v => setAction(v === 'all' ? '' : (v ?? ''))}>
                <SelectTrigger><SelectValue placeholder={t('auditTrail.allActions')} /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">{t('auditTrail.allActions')}</SelectItem>
                  {availableActions.map(a => (
                    <SelectItem key={a.value} value={a.value}>{a.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1">
              <p className="text-xs font-medium text-muted-foreground">From</p>
              <Input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} className="w-36" />
            </div>
            <div className="space-y-1">
              <p className="text-xs font-medium text-muted-foreground">To</p>
              <Input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} className="w-36" />
            </div>

            <Button onClick={applyFilters} disabled={loading}>
              {loading ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Audit Log Table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center justify-between">
            <span>Audit Log — {total.toLocaleString()} entries</span>
            <Button variant="ghost" size="sm" onClick={load} disabled={loading}>
              <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            </Button>
          </CardTitle>
        </CardHeader>
        <CardContent className="p-3">
          <AuditTable entries={entries} loading={loading && entries.length === 0} />
          {totalPages > 1 && (
            <div className="flex items-center justify-between px-1 py-3 border-t mt-2">
              <p className="text-sm text-muted-foreground">Page {page} of {totalPages}</p>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>Previous</Button>
                <Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>Next</Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Entity breakdown */}
      {stats && Object.keys(stats.by_entity).length > 0 && (
        <Card>
          <CardHeader><CardTitle className="text-sm">Events by Entity Type</CardTitle></CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {Object.entries(stats.by_entity).sort((a, b) => b[1] - a[1]).map(([ent, cnt]) => (
                <Badge key={ent} variant="secondary" className="text-sm px-3 py-1 capitalize">
                  {(ENTITY_LABELS[ent] ?? ent).replace(/_/g, ' ')}: <span className="font-bold ml-1">{cnt}</span>
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ //
// Audit DataTable
// ------------------------------------------------------------------ //
function AuditTable({ entries, loading }: { entries: AuditEntry[]; loading: boolean }) {
  const { t } = useTranslation();
  const columns = useMemo<ColumnDef<AuditEntry>[]>(() => [
    {
      key: 'created_at', label: t('auditTrail.colTimestamp'), type: 'date',
      accessor: e => e.created_at,
      format: v => formatDt(String(v)),
      className: 'font-mono text-xs',
    },
    {
      key: 'action', label: t('auditTrail.colAction'), type: 'enum',
      enumOptions: ['create', 'update', 'delete', 'finalize', 'cancel', 'first_weight', 'completed', 'login', 'logout'],
      accessor: e => e.action,
      format: v => <Badge className={`text-xs px-2 py-0 ${actionBadgeClass(String(v))}`}>{String(v).replace(/_/g, ' ')}</Badge>,
    },
    {
      key: 'entity_type', label: t('auditTrail.colEntity'), type: 'enum',
      enumOptions: ['token', 'invoice', 'payment', 'party', 'product', 'vehicle', 'user', 'production_cycle'],
      accessor: e => e.entity_type,
      format: v => <span className="capitalize">{(ENTITY_LABELS[String(v)] ?? String(v)).replace(/_/g, ' ')}</span>,
    },
    {
      key: 'entity_id', label: 'ID', defaultVisible: false,
      accessor: e => e.entity_id ?? '',
      format: v => v ? <span className="font-mono text-xs text-muted-foreground">#{String(v).slice(0, 8)}</span> : '—',
    },
    { key: 'username', label: t('auditTrail.colUser'), accessor: e => e.username ?? 'System' },
    {
      key: 'details', label: 'Details',
      accessor: e => e.details ? parseDetails(e.details) : '',
      className: 'text-xs text-muted-foreground max-w-md truncate',
    },
    { key: 'ip_address', label: 'IP', defaultVisible: false, accessor: e => e.ip_address ?? '', className: 'font-mono text-xs' },
  ], [t]);

  return (
    <DataTable<AuditEntry>
      id="audit.log"
      loading={loading}
      data={entries}
      columns={columns}
      rowKey={e => e.id}
      exportFilename="audit-log"
      defaultSort={{ key: 'created_at', direction: 'desc' }}
      emptyMessage={t('auditTrail.noEvents')}
    />
  );
}
