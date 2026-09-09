/**
 * Tally hub — everything a user does with Tally, in one place.
 *
 * Three questions: what has NOT gone to Tally yet (Pending), what happened to
 * everything sent (Sync Log), and how it is wired up (Setup & Mapping). Setup was
 * moved out of Settings so nothing Tally lives in two places — it stays admin-only,
 * and stays reachable with the integration off, because it is the switch.
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { ClipboardList, Clock, RefreshCw, Settings2 } from 'lucide-react';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { MobileTabSelect } from '@/components/MobileTabSelect';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { DataTable, type ColumnDef } from '@/components/DataTable';
import { usePermissions } from '@/contexts/PermissionsContext';
import { useTallyEnabled } from '@/hooks/useTallyEnabled';
import api from '@/services/api';
import TallySyncLogPage from './TallySyncLogPage';
import { TallyTab as TallySetup } from './SettingsPage';
import { getCurrentUser } from '@/hooks/useAuth';

type Tab = 'log' | 'pending' | 'setup';

interface PendingRow {
  id: string;
  invoice_no: string;
  invoice_type: string;
  invoice_date: string;
  grand_total: number;
}

const INR = (v: number) => '₹' + Number(v ?? 0).toLocaleString('en-IN', { minimumFractionDigits: 2 });

function PendingTab() {
  const [rows, setRows] = useState<PendingRow[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get<{ items: PendingRow[] }>('/api/v1/tally/pending');
      setRows(data.items ?? []);
    } catch {
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const columns: ColumnDef<PendingRow>[] = [
    { key: 'invoice_no', label: 'Invoice', accessor: r => r.invoice_no },
    {
      key: 'invoice_type', label: 'Type', type: 'enum', enumOptions: ['sale', 'purchase', 'credit_note', 'debit_note'],
      accessor: r => r.invoice_type,
      format: v => <Badge variant="secondary" className="capitalize">{String(v).replace('_', ' ')}</Badge>,
    },
    { key: 'invoice_date', label: 'Date', type: 'date', accessor: r => r.invoice_date },
    {
      key: 'grand_total', label: 'Amount', type: 'number', align: 'right',
      accessor: r => r.grand_total, format: v => INR(Number(v)), exportValue: r => r.grand_total,
    },
  ];

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <p className="text-xs text-muted-foreground">
          Finalised invoices Tally has not confirmed yet. They go automatically if auto-sync is on;
          otherwise push them from the Invoices page.
        </p>
        <Button variant="outline" size="sm" className="ml-auto gap-1.5" onClick={() => void load()} disabled={loading}>
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </Button>
      </div>
      <DataTable<PendingRow>
        id="tally.pending"
        data={rows}
        columns={columns}
        rowKey={r => r.id}
        loading={loading}
        exportFilename="tally-pending"
        defaultSort={{ key: 'invoice_date', direction: 'desc' }}
        emptyMessage="Nothing is waiting — everything finalised has reached Tally."
      />
    </div>
  );
}

export default function TallyHubPage() {
  const tallyEnabled = useTallyEnabled();
  const { isTabAllowed } = usePermissions();
  const nav = useNavigate();
  const loc = useLocation();

  // Setup carries connection + ledger mapping, so it stays admin-only exactly as
  // it was under Settings — moving it here must not widen who can change it.
  const isAdmin = getCurrentUser()?.role === 'admin';
  const TABS: { value: Tab; label: string; icon: React.ElementType }[] = [
    { value: 'log', label: 'Sync Log', icon: ClipboardList },
    { value: 'pending', label: 'Pending', icon: Clock },
    ...(isAdmin ? [{ value: 'setup' as Tab, label: 'Setup & Mapping', icon: Settings2 }] : []),
  ];
  const visibleTabs = TABS.filter(tb => isTabAllowed('/tally', tb.value));
  const initialRaw = (new URLSearchParams(loc.search).get('tab') as Tab)
    || (!tallyEnabled && isAdmin ? 'setup' : 'log');
  const initial = (visibleTabs.find(tb => tb.value === initialRaw)?.value ?? visibleTabs[0]?.value ?? 'log') as Tab;
  const [tab, setTab] = useState<Tab>(initial);

  useEffect(() => {
    const params = new URLSearchParams(loc.search);
    if (params.get('tab') !== tab) {
      params.set('tab', tab);
      nav({ search: params.toString() }, { replace: true });
    }
  }, [tab, loc.search, nav]);

  // With Tally off there is nothing to log — but an admin still needs Setup here,
  // since this page is now the only place to switch it on.
  if (!tallyEnabled && !isAdmin) {
    return (
      <Card>
        <CardContent className="pt-6 text-sm text-muted-foreground">
          Tally integration is switched off. An administrator can turn it on under <b>Tally → Setup &amp; Mapping</b>.
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-3">
      <Tabs value={tab} onValueChange={(v) => setTab(v as Tab)}>
        <MobileTabSelect
          value={tab}
          onValueChange={(v) => setTab(v as Tab)}
          options={visibleTabs.map(tb => ({ value: tb.value, label: tb.label }))}
        />
        <TabsList className="hidden sm:flex">
          {visibleTabs.map(tb => (
            <TabsTrigger key={tb.value} value={tb.value} className="gap-1.5">
              <tb.icon className="h-4 w-4" />{tb.label}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="log" className="mt-4"><TallySyncLogPage /></TabsContent>
        <TabsContent value="pending" className="mt-4"><PendingTab /></TabsContent>
        {isAdmin && <TabsContent value="setup" className="mt-4"><TallySetup /></TabsContent>}
      </Tabs>
    </div>
  );
}
