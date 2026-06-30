import { useEffect, useState, useCallback, useMemo } from 'react';
import api from '@/services/api';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';
import { Loader2, AlertTriangle, CheckCircle2, ShieldAlert, Download } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { DataTable, type ColumnDef } from '@/components/DataTable';

const today = () => new Date().toISOString().slice(0, 10);
const daysAgo = (n: number) => {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
};
const monthStart = () => {
  const d = new Date();
  d.setDate(1);
  return d.toISOString().slice(0, 10);
};

const SEV_COLOR: Record<string, string> = {
  high:   'border-red-300 bg-red-50',
  medium: 'border-amber-300 bg-amber-50',
  low:    'border-blue-200 bg-blue-50',
  ok:     'border-emerald-200 bg-emerald-50',
};
const SEV_BADGE: Record<string, string> = {
  high:   'bg-red-100 text-red-700',
  medium: 'bg-amber-100 text-amber-700',
  low:    'bg-blue-100 text-blue-700',
  ok:     'bg-emerald-100 text-emerald-700',
};
const SEV_ICON: Record<string, React.ReactNode> = {
  high:   <ShieldAlert className="h-4 w-4 text-red-600" />,
  medium: <AlertTriangle className="h-4 w-4 text-amber-600" />,
  low:    <AlertTriangle className="h-4 w-4 text-blue-500" />,
  ok:     <CheckCircle2 className="h-4 w-4 text-emerald-600" />,
};

interface DetectorResult {
  title: string;
  description: string;
  severity: string;
  count: number;
  items: Record<string, unknown>[];
  error?: string;
}
interface AnomalyResult {
  overall: string;
  date_from: string;
  date_to: string;
  detectors: Record<string, DetectorResult>;
}

// ─── Per-detector ColumnDef arrays ────────────────────────────────────────────
// Built inside the page component so they can use t() for translated labels.

type AnomalyRow = Record<string, unknown>;

// ─── DetectorCard ─────────────────────────────────────────────────────────────

function DetectorCard({
  id, d, expanded, onToggle, detectorColumns,
}: {
  id: string;
  d: DetectorResult;
  expanded: boolean;
  onToggle: () => void;
  detectorColumns: Record<string, ColumnDef<AnomalyRow>[]>;
}) {
  const { t } = useTranslation();
  const sev = d.severity ?? 'ok';
  const cols = detectorColumns[id] ?? [];
  return (
    <div className={`rounded-lg border p-4 ${SEV_COLOR[sev] ?? ''}`}>
      <div
        className="flex items-center justify-between cursor-pointer gap-3 flex-wrap"
        onClick={onToggle}
      >
        <div className="flex items-center gap-2 min-w-0">
          {SEV_ICON[sev]}
          <span className="font-semibold text-sm truncate">{d.title}</span>
          <span className={`px-2 py-0.5 rounded-full text-[11px] font-medium whitespace-nowrap ${SEV_BADGE[sev]}`}>
            {sev === 'ok' ? t('anomaly.clean') : sev.toUpperCase()}
          </span>
          {d.count > 0 && (
            <span className="text-xs text-muted-foreground whitespace-nowrap">
              {d.count} {t('anomaly.anomaliesDetected')}
            </span>
          )}
        </div>
        <span className="text-xs text-muted-foreground hidden md:block flex-1 text-right pr-4">
          {d.description}
        </span>
        <span className="text-muted-foreground text-xs">{expanded ? '▲' : '▼'}</span>
      </div>
      <p className="text-xs text-muted-foreground mt-1 md:hidden">{d.description}</p>

      {expanded && d.items.length > 0 && (
        <div className="mt-3">
          <DataTable<AnomalyRow>
            id={`anomaly.${id}`}
            data={d.items}
            columns={cols}
            rowKey={(_, i) => String(i)}
            exportFilename={`anomaly-${id}`}
            emptyMessage={t('anomaly.noIssues')}
            defaultSort={{ key: 'date', direction: 'desc' }}
          />
          {d.items.length >= 50 && (
            <p className="text-[11px] text-muted-foreground mt-1">
              Showing first 50 results. Narrow the date range to see all.
            </p>
          )}
        </div>
      )}

      {expanded && d.items.length === 0 && d.severity === 'ok' && (
        <p className="mt-2 text-xs text-emerald-700">{t('anomaly.noIssues')}</p>
      )}

      {d.error && (
        <p className="text-xs text-red-600 mt-1">Error: {d.error}</p>
      )}
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function AnomalyReportPage() {
  const { t } = useTranslation();
  const [range, setRange] = useState({ from: monthStart(), to: today() });
  const [result, setResult] = useState<AnomalyResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  // ─── Per-detector ColumnDef arrays (built here so t() is in scope) ──────────

  const DETECTOR_COLUMNS = useMemo<Record<string, ColumnDef<AnomalyRow>[]>>(() => ({
    high_frequency: [
      { key: 'date',       label: t('anomaly.colTokenDate'), type: 'date',   accessor: r => r.date,
        format: v => String(v ?? '—') },
      { key: 'vehicle_no', label: t('anomaly.colVehicle'),   type: 'string', accessor: r => r.vehicle_no },
      { key: 'trip_count', label: t('anomaly.colTripsToday'), type: 'number', align: 'right',
        accessor: r => r.trip_count },
    ],
    weight_variance: [
      { key: 'date',          label: t('anomaly.colTokenDate'),  type: 'date',   accessor: r => r.date,
        format: v => String(v ?? '—') },
      { key: 'token_no',      label: t('anomaly.colTokenNo'),    type: 'string', accessor: r => r.token_no },
      { key: 'vehicle_no',    label: t('anomaly.colVehicle'),    type: 'string', accessor: r => r.vehicle_no },
      { key: 'product',       label: t('anomaly.colProduct'),    type: 'string', accessor: r => r.product },
      { key: 'net_weight_mt', label: t('anomaly.colNetWt'),      type: 'number', align: 'right',
        accessor: r => r.net_weight_mt },
      { key: 'mean_mt',       label: t('anomaly.col30DayAvg'),   type: 'number', align: 'right',
        accessor: r => r.mean_mt },
      { key: 'variance_pct',  label: t('anomaly.colVariancePct'), type: 'number', align: 'right',
        accessor: r => r.variance_pct,
        format: v => (
          <span className="text-red-600 font-semibold">{String(v ?? '—')}%</span>
        ) },
    ],
    tare_deviation: [
      { key: 'date',           label: t('anomaly.colTokenDate'),  type: 'date',   accessor: r => r.date,
        format: v => String(v ?? '—') },
      { key: 'token_no',       label: t('anomaly.colTokenNo'),    type: 'string', accessor: r => r.token_no },
      { key: 'vehicle_no',     label: t('anomaly.colVehicle'),    type: 'string', accessor: r => r.vehicle_no },
      { key: 'token_tare_kg',  label: t('anomaly.colTareUsed'),   type: 'number', align: 'right',
        accessor: r => r.token_tare_kg },
      { key: 'master_tare_kg', label: t('anomaly.colMasterTare'), type: 'number', align: 'right',
        accessor: r => r.master_tare_kg },
      { key: 'diff_kg',        label: t('anomaly.colDeviation'),  type: 'number', align: 'right',
        accessor: r => r.diff_kg },
    ],
    invoice_leakage: [
      { key: 'date',        label: t('anomaly.colTokenDate'), type: 'date',   accessor: r => r.date,
        format: v => String(v ?? '—') },
      { key: 'token_no',    label: t('anomaly.colTokenNo'),   type: 'string', accessor: r => r.token_no },
      { key: 'vehicle_no',  label: t('anomaly.colVehicle'),   type: 'string', accessor: r => r.vehicle_no },
      { key: 'net_mt',      label: t('anomaly.colNetWt'),     type: 'number', align: 'right',
        accessor: r => r.net_mt },
      { key: 'hours_since', label: t('anomaly.colHoursGap'), type: 'number', align: 'right',
        accessor: r => r.hours_since },
    ],
    after_hours: [
      { key: 'date',       label: t('anomaly.colTokenDate'), type: 'date',   accessor: r => r.date,
        format: v => String(v ?? '—') },
      { key: 'token_no',   label: t('anomaly.colTokenNo'),   type: 'string', accessor: r => r.token_no },
      { key: 'vehicle_no', label: t('anomaly.colVehicle'),   type: 'string', accessor: r => r.vehicle_no },
      { key: 'hour_ist',   label: t('anomaly.colTime'),      type: 'number', align: 'right',
        accessor: r => r.hour_ist },
      { key: 'net_mt',     label: t('anomaly.colNetWt'),     type: 'number', align: 'right',
        accessor: r => r.net_mt },
    ],
    round_weight: [
      { key: 'date',       label: t('anomaly.colTokenDate'), type: 'date',   accessor: r => r.date,
        format: v => String(v ?? '—') },
      { key: 'token_no',   label: t('anomaly.colTokenNo'),   type: 'string', accessor: r => r.token_no },
      { key: 'vehicle_no', label: t('anomaly.colVehicle'),   type: 'string', accessor: r => r.vehicle_no },
      { key: 'net_mt',     label: t('anomaly.colWeight'),    type: 'number', align: 'right',
        accessor: r => r.net_mt },
    ],
    unlinked_passes: [
      { key: 'date',       label: t('anomaly.colTokenDate'), type: 'date',   accessor: r => r.date,
        format: v => String(v ?? '—') },
      { key: 'token_no',   label: t('anomaly.colTokenNo'),   type: 'string', accessor: r => r.token_no },
      { key: 'vehicle_no', label: t('anomaly.colVehicle'),   type: 'string', accessor: r => r.vehicle_no },
      { key: 'supplier',   label: t('anomaly.colParty'),     type: 'string', accessor: r => r.supplier },
      { key: 'net_mt',     label: t('anomaly.colNetWt'),     type: 'number', align: 'right',
        accessor: r => r.net_mt },
    ],
  }), [t]);

  const load = useCallback(async () => {
    // Skip if either date is empty or incomplete (prevents false errors while typing)
    if (!range.from || !range.to || range.from.length !== 10 || range.to.length !== 10) return;
    setLoading(true);
    try {
      const r = await api.get('/api/v1/reports/anomalies', {
        params: { date_from: range.from, date_to: range.to },
      });
      setResult(r.data);
      // Auto-expand detectors that have findings
      const auto: Record<string, boolean> = {};
      Object.entries(r.data.detectors as Record<string, DetectorResult>).forEach(([k, v]) => {
        if ((v.severity ?? 'ok') !== 'ok') auto[k] = true;
      });
      setExpanded(auto);
    } catch {
      toast.error('Could not load anomaly report');
    } finally {
      setLoading(false);
    }
  }, [range.from, range.to]);

  useEffect(() => { load(); }, [load]);

  function exportCsv() {
    if (!result) return;
    const lines: string[] = ['Detector,Severity,Count,Description'];
    Object.entries(result.detectors).forEach(([, d]) => {
      lines.push(`"${d.title}","${d.severity}","${d.count}","${d.description}"`);
    });
    const url = URL.createObjectURL(new Blob([lines.join('\n')], { type: 'text/csv' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = `anomaly-report_${range.from}_${range.to}.csv`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  }

  const overallColor: Record<string, string> = {
    high:   'border-red-400 bg-red-50 text-red-800',
    medium: 'border-amber-400 bg-amber-50 text-amber-800',
    low:    'border-blue-300 bg-blue-50 text-blue-800',
    ok:     'border-emerald-400 bg-emerald-50 text-emerald-800',
  };

  return (
    <div className="p-4 space-y-4">
      {/* Header row */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold flex items-center gap-2">
            <ShieldAlert className="h-5 w-5" /> {t('anomaly.title')}
          </h1>
          <p className="text-xs text-muted-foreground">
            {t('anomaly.subtitle')}
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {/* Date presets */}
          <div className="flex gap-1">
            <Button
              variant="outline" size="sm" className="h-7 text-xs"
              onClick={() => setRange({ from: monthStart(), to: today() })}
            >
              This month
            </Button>
            <Button
              variant="outline" size="sm" className="h-7 text-xs"
              onClick={() => setRange({ from: daysAgo(7), to: today() })}
            >
              {t('anomaly.last7')}
            </Button>
            <Button
              variant="outline" size="sm" className="h-7 text-xs"
              onClick={() => setRange({ from: daysAgo(30), to: today() })}
            >
              {t('anomaly.last30')}
            </Button>
          </div>
          <Input
            type="date"
            className="h-8 w-36 text-xs"
            value={range.from}
            onChange={e => setRange(r => ({ ...r, from: e.target.value }))}
          />
          <Input
            type="date"
            className="h-8 w-36 text-xs"
            value={range.to}
            onChange={e => setRange(r => ({ ...r, to: e.target.value }))}
          />
          <Button
            variant="outline" size="sm" className="gap-1.5 h-8"
            onClick={exportCsv}
            disabled={!result}
          >
            <Download className="h-3.5 w-3.5" /> {t('anomaly.exportSummary')}
          </Button>
          <Button size="sm" className="h-8" onClick={load} disabled={loading}>
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : t('anomaly.runDetection')}
          </Button>
        </div>
      </div>

      {/* Loading state */}
      {loading && (
        <div className="py-12 text-center text-muted-foreground">
          <Loader2 className="inline h-5 w-5 animate-spin" /> Running detectors…
        </div>
      )}

      {/* Results */}
      {result && !loading && (
        <>
          {/* Overall banner */}
          <div className={`rounded-lg border-2 px-4 py-3 flex items-center gap-3 ${overallColor[result.overall ?? 'ok'] ?? overallColor['ok']}`}>
            {SEV_ICON[result.overall ?? 'ok']}
            <div>
              <p className="font-bold text-sm">
                {t('anomaly.overall')}:{' '}
                {(result.overall ?? 'ok') === 'ok'
                  ? `${t('anomaly.clean')} — ${t('anomaly.noIssues')}`
                  : `${(result.overall ?? 'ok').toUpperCase()} severity anomalies found`}
              </p>
              <p className="text-xs opacity-75">{range.from} to {range.to}</p>
            </div>
          </div>

          {/* Detector cards */}
          <div className="space-y-3">
            {Object.entries(result.detectors).map(([key, d]) => (
              <DetectorCard
                key={key}
                id={key}
                d={d}
                expanded={!!expanded[key]}
                onToggle={() => setExpanded(e => ({ ...e, [key]: !e[key] }))}
                detectorColumns={DETECTOR_COLUMNS}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
