/**
 * Customer 360 picker — landing page at /customers (no id).
 *
 * Lists every party as a card with a quick balance + last-order summary.
 * Click any card → /customers/:id (the full 360 profile).
 *
 * This exists because the previous flow (Parties → click name) hid the
 * 360 view behind an inline hyperlink that wasn't obvious enough.
 */
import { useEffect, useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import {
  Search, Users, ExternalLink, Loader2, AlertCircle, IndianRupee,
  Phone, Building2, Table as TableIcon, LayoutGrid,
} from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { DataTable, type ColumnDef } from '@/components/DataTable';
import api from '@/services/api';
import type { Party } from '@/types';

const INR_L = (v: number) => {
  // Compact lakh/crore display for big numbers
  const abs = Math.abs(v);
  if (abs >= 10000000) return '₹' + (v / 10000000).toFixed(2) + ' Cr';
  if (abs >= 100000) return '₹' + (v / 100000).toFixed(2) + ' L';
  if (abs >= 1000) return '₹' + (v / 1000).toFixed(0) + 'K';
  return '₹' + Math.abs(v).toFixed(0);
};

export default function CustomerPickerPage(
  { lockType, linkBase = '/customers' }: { lockType?: 'customer' | 'supplier'; linkBase?: string } = {},
) {
  const { t } = useTranslation();
  const [parties, setParties] = useState<Party[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  // When embedded as a CRM tab the type is fixed (and the chips are hidden).
  const [typeFilter, setTypeFilter] = useState<'all' | 'customer' | 'supplier'>(lockType ?? 'all');
  // View mode — default TABLE (per the app's DataTable standard); persisted per list.
  const VIEW_KEY = `crm.pickerView.${lockType ?? 'all'}`;
  const [view, setView] = useState<'table' | 'tiles'>(() => {
    try { return (localStorage.getItem(VIEW_KEY) as 'table' | 'tiles') || 'table'; } catch { return 'table'; }
  });
  useEffect(() => { try { localStorage.setItem(VIEW_KEY, view); } catch { /* ignore */ } }, [view, VIEW_KEY]);

  const typeLabel = (pt: string) =>
    pt === 'both' ? t('party.both') : pt === 'supplier' ? t('party.supplier') : t('party.customer');

  const COLUMNS: ColumnDef<Party>[] = useMemo(() => [
    { key: 'name', label: 'Name', accessor: r => r.name, exportValue: r => r.name,
      format: (v, r) => (
        <Link to={`${linkBase}/${r.id}`}
          className="font-medium text-blue-700 hover:underline inline-flex items-center gap-1">
          {String(v)} <ExternalLink className="h-3 w-3 opacity-40 shrink-0" />
        </Link>
      ) },
    { key: 'type', label: 'Type', type: 'enum', enumOptions: ['customer', 'supplier', 'both'],
      accessor: r => r.party_type, exportValue: r => String(r.party_type ?? ''),
      format: v => <Badge variant="outline" className="text-[10px] uppercase">{typeLabel(String(v))}</Badge> },
    { key: 'phone', label: 'Phone', accessor: r => r.phone ?? '',
      format: v => v ? <span className="font-mono text-xs">{String(v)}</span> : <span className="text-slate-300">—</span> },
    { key: 'city', label: 'City', accessor: r => [r.billing_city, r.billing_state].filter(Boolean).join(', ') },
    { key: 'gstin', label: 'GSTIN', accessor: r => r.gstin ?? '', defaultVisible: false,
      format: v => v ? <span className="font-mono text-xs">{String(v)}</span> : <span className="text-slate-300">—</span> },
    { key: 'balance', label: t('customer360.outstanding'), type: 'number', align: 'right',
      accessor: r => Number(r.current_balance ?? 0), exportValue: r => Number(r.current_balance ?? 0),
      format: v => {
        const b = Number(v ?? 0);
        const cls = b > 0 ? 'text-rose-700' : b < 0 ? 'text-emerald-700' : 'text-slate-500';
        const txt = b > 0 ? INR_L(b) : b < 0 ? `(${INR_L(Math.abs(b))})` : '₹0';
        return <span className={`font-semibold ${cls}`}>{txt}</span>;
      } },
    // eslint-disable-next-line react-hooks/exhaustive-deps
  ], [t, linkBase]);

  useEffect(() => {
    setLoading(true);
    api.get<{ items: Party[] }>('/api/v1/parties?page=1&page_size=500&active_only=true')
      .then(r => setParties(r.data.items ?? []))
      .catch(e => {
        const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
        setError(typeof detail === 'string' ? detail : 'Failed to load customers');
      })
      .finally(() => setLoading(false));
  }, []);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return parties.filter(p => {
      if (typeFilter === 'customer' && p.party_type === 'supplier') return false;
      if (typeFilter === 'supplier' && p.party_type === 'customer') return false;
      if (!q) return true;
      return (
        p.name.toLowerCase().includes(q) ||
        (p.gstin?.toLowerCase().includes(q) ?? false) ||
        (p.phone?.toLowerCase().includes(q) ?? false) ||
        (p.billing_city?.toLowerCase().includes(q) ?? false)
      );
    });
  }, [parties, search, typeFilter]);

  // Bucket counts for the filter chips
  const customerCount = parties.filter(p => p.party_type !== 'supplier').length;
  const supplierCount = parties.filter(p => p.party_type !== 'customer').length;

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-xl font-bold tracking-tight flex items-center gap-2">
            <Users className="h-5 w-5 text-blue-600" />
            {lockType === 'supplier' ? `${t('party.supplier')}s`
              : lockType === 'customer' ? `${t('party.customer')}s`
              : t('customer360.pickerTitle')}
          </h1>
          <p className="text-sm text-muted-foreground">
            {t('customer360.pickerSubtitle')}
          </p>
        </div>
        <Link
          to="/parties"
          className="text-xs text-blue-600 hover:text-blue-800 hover:underline inline-flex items-center gap-1"
        >
          Master list (edit / add new) <ExternalLink className="h-3 w-3" />
        </Link>
      </div>

      {/* Filter bar */}
      <div className="flex items-center gap-2 flex-wrap">
        <div className="relative flex-1 min-w-[240px] max-w-md">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder={t('customer360.searchPlaceholder')}
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="pl-8 h-9"
          />
        </div>
        {!lockType && (
        <div className="flex items-center gap-1">
          {([
            { key: 'all',      label: t('customer360.allTypes'),       count: parties.length      },
            { key: 'customer', label: t('customer360.customersOnly'), count: customerCount       },
            { key: 'supplier', label: t('customer360.suppliersOnly'), count: supplierCount       },
          ] as const).map(chip => (
            <button
              key={chip.key}
              onClick={() => setTypeFilter(chip.key)}
              className={`inline-flex items-center gap-1 px-3 py-1.5 rounded-full text-xs font-medium border transition-all ${
                typeFilter === chip.key
                  ? 'bg-blue-600 border-blue-600 text-white'
                  : 'bg-white border-slate-200 text-slate-600 hover:border-slate-400'
              }`}
            >
              {chip.label}
              <span className={`px-1 rounded text-[10px] ${typeFilter === chip.key ? 'bg-blue-700' : 'bg-slate-100'}`}>{chip.count}</span>
            </button>
          ))}
        </div>
        )}
        {/* Table / Tiles view toggle (default table) */}
        <div className="ml-auto inline-flex rounded-md border border-slate-200 overflow-hidden shrink-0">
          {([['table', TableIcon, 'Table'], ['tiles', LayoutGrid, 'Tiles']] as const).map(([v, Icon, label]) => (
            <button
              key={v}
              onClick={() => setView(v)}
              title={label}
              className={`inline-flex items-center gap-1 px-2.5 py-1.5 text-xs transition-colors ${
                view === v ? 'bg-blue-600 text-white' : 'bg-white text-slate-600 hover:bg-slate-50'
              }`}
            >
              <Icon className="h-3.5 w-3.5" /> <span className="hidden sm:inline">{label}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Error / loading / empty / list */}
      {error && (
        <div className="rounded-lg border-2 border-rose-300 bg-rose-50 px-4 py-3 text-rose-800 flex items-center gap-2 text-sm">
          <AlertCircle className="h-5 w-5 shrink-0" /> {error}
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
        </div>
      ) : view === 'table' ? (
        <DataTable<Party>
          id={`crm.parties.${lockType ?? 'all'}`}
          data={filtered}
          columns={COLUMNS}
          rowKey={r => r.id}
          exportFilename={lockType ? `${lockType}s` : 'parties'}
          defaultSort={{ key: 'name', direction: 'asc' }}
          emptyMessage={t('customer360.noCustomersFound')}
        />
      ) : filtered.length === 0 ? (
        <Card>
          <CardContent className="py-16 text-center">
            <Users className="mx-auto h-10 w-10 text-slate-300 mb-2" />
            <p className="text-sm text-muted-foreground">
              {search ? `${t('customer360.noCustomersFound')}: "${search}"` : t('customer360.noCustomersFound')}
            </p>
            {search && (
              <button onClick={() => setSearch('')} className="mt-3 text-xs text-blue-600 hover:underline">
                Clear search
              </button>
            )}
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
          {filtered.map(p => {
            const balance = Number(p.current_balance ?? 0);
            const owesUs = balance > 0;
            const weOwe = balance < 0;
            return (
              <Link
                key={p.id}
                to={`${linkBase}/${p.id}`}
                className="group block rounded-xl border-2 border-slate-200 hover:border-blue-400 bg-white p-3 transition-all hover:shadow-md"
              >
                <div className="flex items-start gap-2 mb-2">
                  <div className="flex h-10 w-10 items-center justify-center rounded-full bg-blue-100 text-blue-700 text-sm font-bold shrink-0">
                    {p.name.trim().split(/\s+/).slice(0, 2).map(w => w[0]?.toUpperCase() ?? '').join('') || '?'}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="font-semibold text-sm text-slate-900 truncate group-hover:text-blue-700">
                      {p.name}
                    </div>
                    <div className="flex items-center gap-1 mt-0.5">
                      <Badge variant="outline" className="text-[9px] uppercase">
                        {p.party_type === 'both' ? t('party.both')
                          : p.party_type === 'supplier' ? t('party.supplier')
                          : t('party.customer')}
                      </Badge>
                      {p.gstin && (
                        <Badge variant="outline" className="text-[9px] font-mono">GST</Badge>
                      )}
                    </div>
                  </div>
                  <ExternalLink className="h-3.5 w-3.5 text-slate-300 group-hover:text-blue-500 shrink-0" />
                </div>
                <div className="space-y-1 text-xs">
                  {p.phone && (
                    <div className="flex items-center gap-1.5 text-slate-500 font-mono truncate">
                      <Phone className="h-3 w-3 shrink-0" /> {p.phone}
                    </div>
                  )}
                  {(p.billing_city || p.billing_state) && (
                    <div className="flex items-center gap-1.5 text-slate-500 truncate">
                      <Building2 className="h-3 w-3 shrink-0" />
                      {[p.billing_city, p.billing_state].filter(Boolean).join(', ')}
                    </div>
                  )}
                  <div className="flex items-center justify-between pt-1 border-t border-slate-100 mt-1">
                    <span className="text-[10px] uppercase tracking-wide text-slate-400">{t('customer360.outstanding')}</span>
                    <span className={`font-bold inline-flex items-center gap-0.5 ${
                      owesUs ? 'text-rose-700' : weOwe ? 'text-emerald-700' : 'text-slate-500'
                    }`}>
                      <IndianRupee className="h-3 w-3" />
                      {owesUs ? INR_L(balance).replace('₹', '') :
                       weOwe   ? `(${INR_L(Math.abs(balance)).replace('₹', '')})` :
                                 '0'}
                    </span>
                  </div>
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
