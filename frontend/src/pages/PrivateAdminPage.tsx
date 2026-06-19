/**
 * Private Admin Console — accessible only at /priv-admin
 * Requires role: private_admin
 * No USB key needed — role-based access only.
 * Not listed in sidebar — navigate directly by URL.
 */
import { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Download, ShieldAlert, LogOut } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import api from '@/services/api';
import { useAuth } from '@/hooks/useAuth';
import { DataTable, type ColumnDef } from '@/components/DataTable';

const INR = (v: number) => '₹' + v.toLocaleString('en-IN', { minimumFractionDigits: 2 });

interface AdminInvoice {
  id: string;
  invoice_no: string;
  invoice_date: string;
  customer_name: string | null;
  vehicle_no: string | null;
  net_weight: number | null;
  rate: number | null;
  amount: number;
  payment_mode: string;
  notes: string | null;
  created_at: string;
  created_by_username: string | null;
}

export default function PrivateAdminPage() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [invoices, setInvoices] = useState<AdminInvoice[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [exporting, setExporting] = useState(false);

  // Enforce private_admin role
  useEffect(() => {
    if (user && user.role !== 'private_admin') {
      navigate('/', { replace: true });
    }
  }, [user, navigate]);

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const { data } = await api.get<{ items: AdminInvoice[]; total: number }>(
        `/api/v1/private-invoices/admin/all?page=${page}&page_size=50`
      );
      setInvoices(data.items);
      setTotal(data.total);
    } catch (e: unknown) {
      const status = (e as { response?: { status?: number } })?.response?.status;
      if (status === 403) {
        setError('Access denied. This console requires the private_admin role.');
      } else {
        setError('Failed to load records.');
      }
    } finally {
      setLoading(false);
    }
  }, [page]);

  useEffect(() => { load(); }, [load]);

  const filtered = search.trim()
    ? invoices.filter(i =>
        (i.customer_name?.toLowerCase().includes(search.toLowerCase())) ||
        (i.vehicle_no?.toLowerCase().includes(search.toLowerCase())) ||
        (i.invoice_no.toLowerCase().includes(search.toLowerCase()))
      )
    : invoices;

  async function handleExport() {
    setExporting(true);
    try {
      const response = await api.get('/api/v1/private-invoices/admin/export-csv', { responseType: 'blob' });
      const url = URL.createObjectURL(new Blob([response.data], { type: 'text/csv' }));
      const a = document.createElement('a');
      a.href = url;
      a.download = 'private_invoices.csv';
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setError('Export failed.');
    } finally {
      setExporting(false);
    }
  }

  const totalAmount = filtered.reduce((s, i) => s + i.amount, 0);

  const ADMIN_COLUMNS: ColumnDef<AdminInvoice>[] = [
    {
      key: 'invoice_no', label: 'Invoice No', type: 'string',
      accessor: r => r.invoice_no,
      format: (_v, r) => <span className="font-mono text-xs font-semibold text-purple-700">{r.invoice_no}</span>,
    },
    {
      key: 'invoice_date', label: 'Date', type: 'date',
      accessor: r => r.invoice_date,
      format: v => <span className="text-muted-foreground whitespace-nowrap">{String(v)}</span>,
    },
    {
      key: 'customer_name', label: 'Customer', type: 'string',
      accessor: r => r.customer_name ?? '',
      format: (_v, r) => r.customer_name ?? '—',
    },
    {
      key: 'vehicle_no', label: 'Vehicle', type: 'string',
      accessor: r => r.vehicle_no ?? '',
      format: (_v, r) => <span className="font-mono text-xs">{r.vehicle_no ?? '—'}</span>,
    },
    {
      key: 'net_weight', label: 'Net Wt (MT)', type: 'number', align: 'right',
      accessor: r => r.net_weight != null ? Number(r.net_weight) / 1000 : 0,
      format: (_v, r) => r.net_weight != null
        ? <span className="font-mono text-xs">{(Number(r.net_weight) / 1000).toLocaleString('en-IN', { minimumFractionDigits: 3, maximumFractionDigits: 3 })}</span>
        : '—',
      exportValue: r => r.net_weight != null ? Number(r.net_weight) / 1000 : '',
    },
    {
      key: 'rate', label: 'Rate', type: 'number', align: 'right',
      accessor: r => r.rate != null ? Number(r.rate) : 0,
      format: (_v, r) => <span className="text-muted-foreground">{r.rate != null ? INR(r.rate) : '—'}</span>,
    },
    {
      key: 'amount', label: 'Amount', type: 'number', align: 'right',
      accessor: r => r.amount,
      format: v => <span className="font-semibold">{INR(v as number)}</span>,
    },
    {
      key: 'payment_mode', label: 'Mode', type: 'string',
      accessor: r => r.payment_mode,
      format: (_v, r) => <span className="text-xs bg-muted px-1.5 py-0.5 rounded">{r.payment_mode.toUpperCase()}</span>,
    },
    {
      key: 'notes', label: 'Notes', type: 'string',
      accessor: r => r.notes ?? '',
      format: (_v, r) => <span className="text-muted-foreground text-xs truncate block max-w-[150px]">{r.notes ?? '—'}</span>,
      defaultVisible: false,
    },
    {
      key: 'created_by_username', label: 'Created By', type: 'string',
      accessor: r => r.created_by_username ?? '',
      format: (_v, r) => <span className="text-xs text-muted-foreground">{r.created_by_username ?? '—'}</span>,
    },
    {
      key: 'created_at', label: 'Created At', type: 'date',
      accessor: r => r.created_at,
      format: (_v, r) => <span className="text-xs text-muted-foreground whitespace-nowrap">{r.created_at.slice(0, 16).replace('T', ' ')}</span>,
      exportValue: r => r.created_at.slice(0, 16).replace('T', ' '),
    },
  ];

  if (user?.role !== 'private_admin') return null;

  return (
    <div className="min-h-screen bg-background">
      {/* Top bar */}
      <div className="border-b bg-card px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="h-8 w-8 rounded-md bg-purple-600 flex items-center justify-center">
            <ShieldAlert className="h-4 w-4 text-white" />
          </div>
          <div>
            <p className="text-sm font-semibold">Private Records Console</p>
            <p className="text-xs text-muted-foreground">Logged in as <span className="font-medium">{user.username}</span></p>
          </div>
        </div>
        <Button variant="ghost" size="sm" onClick={() => { logout(); navigate('/'); }}>
          <LogOut className="mr-2 h-4 w-4" /> Sign Out
        </Button>
      </div>

      <div className="p-6 space-y-4 max-w-7xl mx-auto">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold">Private Invoice Records</h1>
            <p className="text-sm text-muted-foreground">{total} total records — read-only audit view</p>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" onClick={handleExport} disabled={exporting}>
              <Download className="mr-2 h-4 w-4" />
              {exporting ? 'Exporting...' : 'Export CSV'}
            </Button>
          </div>
        </div>

        <div className="max-w-xs">
          <Input
            placeholder="Search customer, vehicle, invoice no..."
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>

        {error && (
          <div className="bg-destructive/10 text-destructive text-sm rounded p-3">{error}</div>
        )}

        {filtered.length > 0 && (
          <div className="text-sm text-right text-muted-foreground pb-1">
            Total ({filtered.length}{search ? ` of ${total}` : ''} records):&nbsp;
            <span className="font-bold text-foreground">{INR(totalAmount)}</span>
          </div>
        )}

        <DataTable<AdminInvoice>
          id="privateadmin.invoices"
          data={filtered}
          loading={loading}
          columns={ADMIN_COLUMNS}
          rowKey={r => r.id}
          exportFilename="private_invoices"
          defaultSort={{ key: 'invoice_date', direction: 'desc' }}
          emptyMessage="No records found"
        />

        {total > 50 && (
          <div className="flex justify-between items-center p-3 border rounded text-sm">
            <span className="text-muted-foreground">{total} total · page {page}</span>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>Prev</Button>
              <Button variant="outline" size="sm" disabled={page * 50 >= total} onClick={() => setPage(p => p + 1)}>Next</Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
