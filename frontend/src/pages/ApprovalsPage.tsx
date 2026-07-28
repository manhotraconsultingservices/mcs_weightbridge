import { useCallback, useEffect, useMemo, useState } from 'react';
import api from '../services/api';
import { toast } from 'sonner';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { DataTable, type ColumnDef } from '@/components/DataTable';
import { getCurrentUser } from '@/hooks/useAuth';
import { ShieldCheck, Check, X, RefreshCw, Loader2 } from 'lucide-react';

interface ApprovalRow {
  id: string;
  action_type: string;
  action_label: string;
  title: string;
  amount: number | null;
  status: 'pending' | 'approved' | 'rejected';
  requested_by: string | null;
  requested_by_name: string | null;
  requested_at: string | null;
  decided_by: string | null;
  decided_by_name: string | null;
  decided_at: string | null;
  decision_note: string | null;
}

const INR = (v: number | null | undefined) =>
  v == null ? '—' : '₹' + Number(v).toLocaleString('en-IN', { minimumFractionDigits: 2 });
const fmtDT = (s: string | null) =>
  !s ? '—' : new Date(s).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', dateStyle: 'medium', timeStyle: 'short' });

export default function ApprovalsPage() {
  const me = getCurrentUser();
  const isAdmin = me?.role === 'admin';
  const [rows, setRows] = useState<ApprovalRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [toggling, setToggling] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [list, cfg] = await Promise.all([
        api.get<{ items: ApprovalRow[] }>('/api/v1/approvals'),
        api.get<{ enabled: boolean }>('/api/v1/approvals/config'),
      ]);
      setRows(list.data.items || []);
      setEnabled(!!cfg.data.enabled);
    } catch {
      toast.error('Failed to load approvals');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const pending = useMemo(() => rows.filter(r => r.status === 'pending'), [rows]);
  const history = useMemo(() => rows.filter(r => r.status !== 'pending'), [rows]);

  async function toggle(next: boolean) {
    setToggling(true);
    try {
      await api.put('/api/v1/approvals/config', { enabled: next });
      setEnabled(next);
      toast.success(next ? 'Maker-checker turned ON' : 'Maker-checker turned OFF');
    } catch {
      toast.error('Only an admin can change this');
    } finally {
      setToggling(false);
    }
  }

  async function decide(row: ApprovalRow, action: 'approve' | 'reject') {
    if (action === 'approve' && row.requested_by && row.requested_by === me?.id) {
      toast.error('You submitted this — a different admin must approve it (4-eyes control).');
      return;
    }
    const note = action === 'reject'
      ? (window.prompt(`Reject "${row.title}"?\nOptional reason:`, '') ?? undefined)
      : undefined;
    if (action === 'reject' && note === undefined) return; // cancelled the prompt
    setBusyId(row.id);
    try {
      const res = await api.post<{ ok: boolean }>(`/api/v1/approvals/${row.id}/${action}`, { note });
      if (res.data.ok) {
        toast.success(action === 'approve' ? 'Approved — action applied' : 'Rejected');
        await load();
      }
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(typeof detail === 'string' ? detail : `Failed to ${action}`);
    } finally {
      setBusyId(null);
    }
  }

  const pendingCols: ColumnDef<ApprovalRow>[] = [
    { key: 'action', label: 'Action', accessor: r => r.action_label },
    { key: 'title', label: 'Details', accessor: r => r.title },
    { key: 'amount', label: 'Amount', type: 'number', align: 'right', accessor: r => r.amount ?? 0,
      format: v => INR(Number(v)), exportValue: r => r.amount ?? '' },
    { key: 'by', label: 'Requested by', accessor: r => r.requested_by_name || '—' },
    { key: 'at', label: 'Requested', type: 'date', accessor: r => r.requested_at,
      format: v => fmtDT(String(v ?? '')) },
  ];

  const historyCols: ColumnDef<ApprovalRow>[] = [
    { key: 'status', label: 'Status', type: 'enum', enumOptions: ['approved', 'rejected'], accessor: r => r.status,
      format: v => <Badge variant="outline" className={v === 'approved' ? 'border-emerald-400 text-emerald-600' : 'border-rose-400 text-rose-600'}>{String(v)}</Badge>,
      exportValue: r => r.status },
    { key: 'action', label: 'Action', accessor: r => r.action_label },
    { key: 'title', label: 'Details', accessor: r => r.title },
    { key: 'amount', label: 'Amount', type: 'number', align: 'right', accessor: r => r.amount ?? 0,
      format: v => INR(Number(v)), exportValue: r => r.amount ?? '' },
    { key: 'by', label: 'Maker', accessor: r => r.requested_by_name || '—' },
    { key: 'checker', label: 'Decided by', accessor: r => r.decided_by_name || '—' },
    { key: 'at', label: 'Decided', type: 'date', accessor: r => r.decided_at, format: v => fmtDT(String(v ?? '')) },
    { key: 'note', label: 'Note', defaultVisible: false, accessor: r => r.decision_note || '' },
  ];

  return (
    <div className="space-y-4 p-1">
      <div className="flex items-center gap-2">
        <ShieldCheck className="h-6 w-6 text-indigo-500" />
        <div>
          <h1 className="text-xl font-semibold">Approvals</h1>
          <p className="text-sm text-muted-foreground">
            Maker-checker (4-eyes) — a second admin must approve write-offs, invoice cancels and Day Book opening-balance changes.
          </p>
        </div>
        <Button variant="outline" size="sm" className="ml-auto" onClick={load} disabled={loading}>
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      </div>

      {/* Toggle card */}
      <Card>
        <CardContent className="flex flex-wrap items-center gap-4 py-4">
          <div className="flex-1 min-w-[220px]">
            <div className="font-medium">
              Require a second admin's approval
              {enabled != null && (
                <Badge variant="outline" className={`ml-2 ${enabled ? 'border-emerald-400 text-emerald-600' : 'border-slate-300 text-slate-500'}`}>
                  {enabled ? 'ON' : 'OFF'}
                </Badge>
              )}
            </div>
            <p className="text-xs text-muted-foreground mt-0.5">
              When ON, those sensitive actions are parked here as a pending request instead of taking effect immediately.
              The person who submits a request cannot approve their own.
            </p>
          </div>
          <div className="flex items-center gap-2">
            {toggling && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
            <Switch
              checked={!!enabled}
              onCheckedChange={toggle}
              disabled={!isAdmin || toggling || enabled == null}
            />
          </div>
          {!isAdmin && <p className="w-full text-xs text-amber-600">Only an admin can turn this on or off.</p>}
        </CardContent>
      </Card>

      {/* Pending queue */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base flex items-center gap-2">
            Pending
            {pending.length > 0 && <Badge className="bg-amber-500">{pending.length}</Badge>}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {pending.length === 0 ? (
            <p className="text-sm text-muted-foreground py-6 text-center">No pending approvals.</p>
          ) : (
            <DataTable<ApprovalRow>
              id="approvals.pending"
              data={pending}
              columns={pendingCols}
              rowKey={r => r.id}
              exportFilename="pending-approvals"
              defaultSort={{ key: 'at', direction: 'desc' }}
              rowActions={r => (
                <div className="flex gap-1.5 justify-end">
                  <Button
                    size="sm" variant="outline"
                    className="border-emerald-400 text-emerald-600 hover:bg-emerald-50"
                    disabled={busyId === r.id || !isAdmin || (r.requested_by === me?.id)}
                    title={!isAdmin ? 'Admin only' : (r.requested_by === me?.id ? 'You submitted this — another admin must approve' : 'Approve')}
                    onClick={() => decide(r, 'approve')}
                  >
                    {busyId === r.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
                    <span className="ml-1">Approve</span>
                  </Button>
                  <Button
                    size="sm" variant="outline"
                    className="border-rose-400 text-rose-600 hover:bg-rose-50"
                    disabled={busyId === r.id || !isAdmin}
                    title={!isAdmin ? 'Admin only' : 'Reject'}
                    onClick={() => decide(r, 'reject')}
                  >
                    <X className="h-3.5 w-3.5" /><span className="ml-1">Reject</span>
                  </Button>
                </div>
              )}
            />
          )}
        </CardContent>
      </Card>

      {/* History */}
      <Card>
        <CardHeader className="pb-2"><CardTitle className="text-base">Recent decisions</CardTitle></CardHeader>
        <CardContent>
          {history.length === 0 ? (
            <p className="text-sm text-muted-foreground py-6 text-center">No decisions yet.</p>
          ) : (
            <DataTable<ApprovalRow>
              id="approvals.history"
              data={history}
              columns={historyCols}
              rowKey={r => r.id}
              exportFilename="approval-history"
              defaultSort={{ key: 'at', direction: 'desc' }}
            />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
