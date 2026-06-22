/**
 * ANPR Review Queue — operator fixes misreads / unknown plates.
 *
 * Lists every AnprEvent with needs_review=TRUE. For each row the operator
 * sees the snapshot thumbnail, the OCR text, and the top-3 OCR alternates.
 * Three resolution paths:
 *   1. "This is vehicle X" → link the event to an existing Vehicle
 *   2. "Corrected plate is..." → fix the plate text + (optionally) register
 *      the corrected plate as a new Vehicle
 *   3. "Just register it" → auto-create Vehicle from the detected plate
 *
 * Once reviewed, the row drops from the queue.
 */
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Camera, Check, RefreshCw, X, AlertTriangle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent } from '@/components/ui/card';
import api from '@/services/api';
import type { AnprEvent, AnprEventListResponse, Vehicle } from '@/types';

export default function AnprReviewPage() {
  const { t } = useTranslation();
  const [events, setEvents] = useState<AnprEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const { data } = await api.get<AnprEventListResponse>(
        '/api/v1/anpr/unmatched?page=1&page_size=50'
      );
      setEvents(data.items ?? []);
      setTotal(data.total ?? 0);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Failed to load review queue');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-3xl font-bold tracking-tight flex items-center gap-2">
            <AlertTriangle className="h-7 w-7 text-amber-600" /> {t('anpr.reviewTitle')}
          </h1>
          <p className="text-muted-foreground text-sm">
            {t('anpr.reviewHint')}
          </p>
        </div>
        <Button variant="outline" onClick={load} disabled={loading}>
          <RefreshCw className={`h-4 w-4 mr-2 ${loading ? 'animate-spin' : ''}`} /> {t('common.refresh')}
        </Button>
      </div>

      {error && (
        <div className="rounded-md border border-rose-300 bg-rose-50 p-3 text-sm text-rose-800">{error}</div>
      )}

      {events.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            {loading ? t('common.loading') : `🎉 ${t('anpr.allClear')}`}
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          <div className="text-xs text-muted-foreground">{t('anpr.reviewSubtitle', { count: total })}</div>
          {events.map(ev => (
            <ReviewRow key={ev.id} event={ev} onResolved={load} />
          ))}
        </div>
      )}
    </div>
  );
}

function ReviewRow({ event, onResolved }: { event: AnprEvent; onResolved: () => void }) {
  const { t } = useTranslation();
  const [corrected, setCorrected] = useState(event.plate_normalized);
  const [vehicleSearch, setVehicleSearch] = useState('');
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [busy, setBusy] = useState<'register' | 'link' | 'correct' | null>(null);
  const [err, setErr] = useState('');

  // Search vehicles by reg as operator types
  useEffect(() => {
    const q = vehicleSearch.trim();
    if (q.length < 2) { setVehicles([]); return; }
    const id = setTimeout(async () => {
      try {
        const { data } = await api.get<Vehicle[]>(`/api/v1/vehicles/search?reg=${encodeURIComponent(q)}`);
        setVehicles((data ?? []).slice(0, 6));
      } catch { /* ignore */ }
    }, 250);
    return () => clearTimeout(id);
  }, [vehicleSearch]);

  async function doReassign(payload: Record<string, unknown>, kind: 'register' | 'link' | 'correct') {
    setBusy(kind);
    setErr('');
    try {
      await api.post(`/api/v1/anpr/events/${event.id}/reassign`, payload);
      onResolved();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setErr(typeof detail === 'string' ? detail : 'Failed to reassign');
    } finally {
      setBusy(null);
    }
  }

  const alts = event.ocr_alternates ?? [];

  return (
    <Card>
      <CardContent className="pt-4">
        <div className="grid grid-cols-1 md:grid-cols-[200px_1fr] gap-4">
          {/* Snapshot */}
          <div className="rounded-lg overflow-hidden bg-slate-100 aspect-video flex items-center justify-center">
            {event.snapshot_path ? (
              <a href={`/${event.snapshot_path}`} target="_blank" rel="noopener noreferrer">
                <img src={`/${event.snapshot_path}`} alt={event.plate_normalized}
                     className="w-full h-full object-cover" />
              </a>
            ) : (
              <Camera className="h-10 w-10 text-slate-400" />
            )}
          </div>

          {/* Details + actions */}
          <div className="space-y-3">
            <div className="flex items-center gap-3 flex-wrap">
              <span className="font-mono font-bold text-xl text-slate-900">{event.plate_normalized}</span>
              <span className="text-xs text-muted-foreground">
                {new Date(event.detected_at).toLocaleString('en-IN', { hour12: false })} ·
                {' '}{(Number(event.confidence ?? 0) * 100).toFixed(0)}% confidence ·
                {' '}{event.source}
              </span>
            </div>

            {alts.length > 0 && (
              <div className="flex items-center gap-2 flex-wrap text-xs text-muted-foreground">
                <span>Alternates:</span>  {/* No matching key — left in English */}
                {alts.slice(0, 3).map((a, i) => (
                  <button key={i} onClick={() => setCorrected(a.plate.toUpperCase())}
                          className="font-mono px-2 py-0.5 rounded border border-slate-200 hover:bg-slate-50">
                    {a.plate.toUpperCase()} <span className="text-slate-400">({(a.confidence * 100).toFixed(0)}%)</span>
                  </button>
                ))}
              </div>
            )}

            {err && (
              <div className="rounded border border-rose-300 bg-rose-50 px-2 py-1 text-xs text-rose-700">{err}</div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {/* Path 1: link to existing vehicle */}
              <div className="rounded-lg border bg-slate-50 p-3 space-y-2">
                <div className="text-xs font-semibold uppercase tracking-wider text-slate-600">
                  {t('anpr.linkExistingVehicle')}
                </div>
                <Input value={vehicleSearch} onChange={e => setVehicleSearch(e.target.value)}
                       placeholder={t('common.search')} className="h-9 text-sm" />
                {vehicles.length > 0 && (
                  <div className="space-y-1">
                    {vehicles.map(v => (
                      <button key={v.id}
                              onClick={() => doReassign({ vehicle_id: v.id }, 'link')}
                              disabled={busy !== null}
                              className="w-full flex items-center justify-between gap-2 px-2 py-1.5 rounded hover:bg-slate-100 text-left disabled:opacity-50">
                        <span className="font-mono text-sm">{v.registration_no}</span>
                        <Check className="h-3.5 w-3.5 text-emerald-600 opacity-0 group-hover:opacity-100" />
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {/* Path 2/3: correct + register */}
              <div className="rounded-lg border bg-amber-50/50 p-3 space-y-2">
                <div className="text-xs font-semibold uppercase tracking-wider text-amber-800">
                  {t('anpr.correctPlateText')} + {t('anpr.registerNewVehicle')}
                </div>
                <Input value={corrected} onChange={e => setCorrected(e.target.value.toUpperCase())}
                       className="h-9 text-sm font-mono uppercase" />
                <div className="flex gap-2">
                  <Button size="sm" onClick={() => doReassign({
                    plate_corrected: corrected, register_new_vehicle: true,
                  }, 'register')} disabled={busy !== null || !corrected.trim()}>
                    {busy === 'register' ? t('anpr.resolving') : t('anpr.registerNewVehicle')}
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => doReassign({
                    plate_corrected: corrected,
                  }, 'correct')} disabled={busy !== null || !corrected.trim()}>
                    {busy === 'correct' ? t('anpr.resolving') : t('anpr.correctPlateText')}
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => doReassign({ notes: 'dismissed' }, 'link')}
                          disabled={busy !== null} className="ml-auto">
                    <X className="h-3.5 w-3.5 mr-1" /> {t('anpr.skip')}
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
