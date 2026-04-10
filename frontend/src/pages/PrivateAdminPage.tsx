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
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import api from '@/services/api';
import { useAuth } from '@/hooks/useAuth';

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

        <Card>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b bg-muted/50">
                    <th className="text-left p-3 font-medium">Invoice No</th>
                    <th className="text-left p-3 font-medium">Date</th>
                    <th className="text-left p-3 font-medium">Customer</th>
                    <th className="text-left p-3 font-medium">Vehicle</th>
                    <th className="text-right p-3 font-medium">Net Wt (kg)</th>
                    <th className="text-right p-3 font-medium">Rate</th>
                    <th className="text-right p-3 font-medium">Amount</th>
                    <th className="text-left p-3 font-medium">Mode</th>
                    <th className="text-left p-3 font-medium">Notes</th>
                    <th className="text-left p-3 font-medium">Created By</th>
                    <th className="text-left p-3 font-medium">Created At</th>
                  </tr>
                </thead>
                <tbody>
                  {loading ? (
                    <tr><td colSpan={11} className="text-center p-8 text-muted-foreground">Loading...</td></tr>
                  ) : filtered.length === 0 ? (
                    <tr><td colSpan={11} className="text-center p-12 text-muted-foreground">No records found</td></tr>
                  ) : filtered.map(inv => (
                    <tr key={inv.id} className="border-b hover:bg-muted/30">
                      <td className="p-3 font-mono text-xs font-semibold text-purple-700">{inv.invoice_no}</td>
                      <td className="p-3 text-muted-foreground whitespace-nowrap">{inv.invoice_date}</td>
                      <td className="p-3">{inv.customer_name ?? '—'}</td>
                      <td className="p-3 font-mono text-xs">{inv.vehicle_no ?? '—'}</td>
                      <td className="p-3 text-right">{inv.net_weight != null ? inv.net_weight.toLocaleString('en-IN', { maximumFractionDigits: 3 }) : '—'}</td>
                      <td className="p-3 text-right text-muted-foreground">{inv.rate != null ? INR(inv.rate) : '—'}</td>
                      <td className="p-3 text-right font-semibold">{INR(inv.amount)}</td>
                      <td className="p-3"><span className="text-xs bg-muted px-1.5 py-0.5 rounded">{inv.payment_mode.toUpperCase()}</span></td>
                      <td className="p-3 text-muted-foreground text-xs max-w-[150px] truncate">{inv.notes ?? '—'}</td>
                      <td className="p-3 text-xs text-muted-foreground">{inv.created_by_username ?? '—'}</td>
                      <td className="p-3 text-xs text-muted-foreground whitespace-nowrap">{inv.created_at.slice(0, 16).replace('T', ' ')}</td>
                    </tr>
                  ))}
                </tbody>
                {filtered.length > 0 && (
                  <tfoot>
                    <tr className="border-t bg-muted/30">
                      <td colSpan={6} className="p-3 text-right text-sm font-medium text-muted-foreground">
                        Total ({filtered.length}{search ? ` of ${total}` : ''} records)
                      </td>
                      <td className="p-3 text-right font-bold">{INR(totalAmount)}</td>
                      <td colSpan={4} />
                    </tr>
                  </tfoot>
                )}
              </table>
            </div>
            {total > 50 && (
              <div className="flex justify-between items-center p-3 border-t text-sm">
                <span className="text-muted-foreground">{total} total · page {page}</span>
                <div className="flex gap-2">
                  <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>Prev</Button>
                  <Button variant="outline" size="sm" disabled={page * 50 >= total} onClick={() => setPage(p => p + 1)}>Next</Button>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
