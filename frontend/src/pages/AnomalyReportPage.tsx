import { useEffect, useState, useCallback } from 'react';
import api from '@/services/api';
import { toast } from 'sonner';
import { Loader2, AlertTriangle, CheckCircle2, ShieldAlert, Download } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

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

// Column definitions per detector key
const COLUMNS: Record<string, string[]> = {
  high_frequency:  ['date', 'vehicle_no', 'trip_count'],
  weight_variance: ['date', 'token_no', 'vehicle_no', 'product', 'net_weight_mt', 'mean_mt', 'variance_pct'],
  tare_deviation:  ['date', 'token_no', 'vehicle_no', 'token_tare_kg', 'master_tare_kg', 'diff_kg'],
  invoice_leakage: ['date', 'token_no', 'vehicle_no', 'net_mt', 'hours_since'],
  after_hours:     ['date', 'token_no', 'vehicle_no', 'hour_ist', 'net_mt'],
  round_weight:    ['date', 'token_no', 'vehicle_no', 'net_mt'],
  unlinked_passes: ['date', 'token_no', 'vehicle_no', 'supplier', 'net_mt'],
};
const COL_LABEL: Record<string, string> = {
  date: 'Date', token_no: 'Token #', vehicle_no: 'Vehicle', trip_count: 'Trips',
  net_weight_mt: 'Net (MT)', net_mt: 'Net (MT)', mean_mt: 'Mean (MT)',
  variance_pct: 'Variance %', product: 'Material',
  token_tare_kg: 'Token Tare (kg)', master_tare_kg: 'Master Tare (kg)', diff_kg: 'Diff (kg)',
  hours_since: 'Hours ago', hour_ist: 'Hour (IST)', supplier: 'Supplier',
};

function DetectorCard({
  id, d, expanded, onToggle,
}: {
  id: string;
  d: DetectorResult;
  expanded: boolean;
  onToggle: () => void;
}) {
  const cols = COLUMNS[id] ?? Object.keys(d.items[0] ?? {});
  return (
    <div className={`rounded-lg border p-4 ${SEV_COLOR[d.severity] ?? ''}`}>
      <div
        className="flex items-center justify-between cursor-pointer gap-3 flex-wrap"
        onClick={onToggle}
      >
        <div className="flex items-center gap-2 min-w-0">
          {SEV_ICON[d.severity]}
          <span className="font-semibold text-sm truncate">{d.title}</span>
          <span className={`px-2 py-0.5 rounded-full text-[11px] font-medium whitespace-nowrap ${SEV_BADGE[d.severity]}`}>
            {d.severity === 'ok' ? 'Clean' : d.severity.toUpperCase()}
          </span>
          {d.count > 0 && (
            <span className="text-xs text-muted-foreground whitespace-nowrap">
              {d.count} flagged
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
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="[&>th]:pr-4 [&>th]:py-1 [&>th]:text-left [&>th]:font-semibold [&>th]:text-muted-foreground border-b">
                {cols.map(c => <th key={c}>{COL_LABEL[c] ?? c}</th>)}
              </tr>
            </thead>
            <tbody>
              {d.items.map((row, i) => (
                <tr key={i} className="border-t border-border/30 [&>td]:pr-4 [&>td]:py-1">
                  {cols.map(c => (
                    <td
                      key={c}
                      className={c === 'variance_pct' ? 'text-red-600 font-semibold' : ''}
                    >
                      {c === 'variance_pct'
                        ? `${row[c]}%`
                        : String(row[c] ?? '—')}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {d.items.length >= 50 && (
            <p className="text-[11px] text-muted-foreground mt-1">
              Showing first 50 results. Narrow the date range to see all.
            </p>
          )}
        </div>
      )}

      {expanded && d.items.length === 0 && d.severity === 'ok' && (
        <p className="mt-2 text-xs text-emerald-700">No anomalies found in this date range.</p>
      )}

      {d.error && (
        <p className="text-xs text-red-600 mt-1">Error: {d.error}</p>
      )}
    </div>
  );
}

export default function AnomalyReportPage() {
  const [range, setRange] = useState({ from: monthStart(), to: today() });
  const [result, setResult] = useState<AnomalyResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.get('/api/v1/reports/anomalies', {
        params: { date_from: range.from, date_to: range.to },
      });
      setResult(r.data);
      // Auto-expand detectors that have findings
      const auto: Record<string, boolean> = {};
      Object.entries(r.data.detectors as Record<string, DetectorResult>).forEach(([k, v]) => {
        if (v.severity !== 'ok') auto[k] = true;
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
            <ShieldAlert className="h-5 w-5" /> Fraud & Anomaly Report
          </h1>
          <p className="text-xs text-muted-foreground">
            7 automated detectors scan for suspicious patterns in your weighbridge data.
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
              7 days
            </Button>
            <Button
              variant="outline" size="sm" className="h-7 text-xs"
              onClick={() => setRange({ from: daysAgo(30), to: today() })}
            >
              30 days
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
            <Download className="h-3.5 w-3.5" /> CSV
          </Button>
          <Button size="sm" className="h-8" onClick={load} disabled={loading}>
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Run'}
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
          <div className={`rounded-lg border-2 px-4 py-3 flex items-center gap-3 ${overallColor[result.overall]}`}>
            {SEV_ICON[result.overall]}
            <div>
              <p className="font-bold text-sm">
                Overall status:{' '}
                {result.overall === 'ok'
                  ? 'Clean — no anomalies detected'
                  : `${result.overall.toUpperCase()} severity anomalies found`}
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
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
