import { useState, useCallback, useEffect } from 'react';
import {
  Search, Camera, Calendar, X, ChevronLeft, ChevronRight,
  Image as ImageIcon, Truck, FileText, Eye,
} from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import api from '@/services/api';
import type { SnapshotSearchItem, SnapshotSearchResponse } from '@/types';

const PAGE_SIZE = 24;

function fmtDate(iso: string | null) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
}
function fmtDateTime(iso: string | null) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }) +
    ' ' + d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false });
}

// ── Lightbox ─────────────────────────────────────────────────────────────────

function Lightbox({ url, label, onClose }: { url: string; label: string; onClose: () => void }) {
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-[200] bg-black/85 flex items-center justify-center p-4" onClick={onClose}>
      <div className="relative max-w-4xl max-h-[90vh] w-full" onClick={e => e.stopPropagation()}>
        <button
          onClick={onClose}
          className="absolute -top-3 -right-3 z-10 bg-slate-800 hover:bg-slate-700 rounded-full p-1.5 border border-slate-600"
        >
          <X className="h-4 w-4 text-white" />
        </button>
        <img src={url} alt={label} className="w-full h-auto rounded-lg shadow-2xl object-contain max-h-[85vh]" />
        <p className="text-center text-sm text-slate-300 mt-2">{label}</p>
      </div>
    </div>
  );
}

// ── Grouped results ──────────────────────────────────────────────────────────

interface TokenGroup {
  token_id: string;
  token_no: string | null;
  token_date: string | null;
  vehicle_no: string | null;
  party_name: string | null;
  first_weight: SnapshotSearchItem[];
  second_weight: SnapshotSearchItem[];
}

function groupByToken(items: SnapshotSearchItem[]): TokenGroup[] {
  const map = new Map<string, TokenGroup>();
  for (const item of items) {
    let g = map.get(item.token_id);
    if (!g) {
      g = {
        token_id: item.token_id,
        token_no: item.token_no,
        token_date: item.token_date,
        vehicle_no: item.vehicle_no,
        party_name: item.party_name,
        first_weight: [],
        second_weight: [],
      };
      map.set(item.token_id, g);
    }
    if (item.weight_stage === 'first_weight') g.first_weight.push(item);
    else g.second_weight.push(item);
  }
  return Array.from(map.values());
}

// ── Main Page ────────────────────────────────────────────────────────────────

export default function SnapshotSearchPage() {
  const [search, setSearch] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [items, setItems] = useState<SnapshotSearchItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [lightbox, setLightbox] = useState<{ url: string; label: string } | null>(null);
  const [searched, setSearched] = useState(false);

  const fetchResults = useCallback(async (p = 1) => {
    setLoading(true);
    try {
      const params: Record<string, string | number> = { page: p, page_size: PAGE_SIZE };
      if (search.trim()) params.search = search.trim();
      if (dateFrom) params.date_from = dateFrom;
      if (dateTo) params.date_to = dateTo;
      const { data } = await api.get<SnapshotSearchResponse>('/api/v1/cameras/search', { params });
      setItems(data.items);
      setTotal(data.total);
      setPage(p);
      setSearched(true);
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, [search, dateFrom, dateTo]);

  // Load on first mount — show recent snapshots
  useEffect(() => { fetchResults(1); }, []);

  const totalPages = Math.ceil(total / PAGE_SIZE);
  const groups = groupByToken(items);

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    fetchResults(1);
  }

  function clearFilters() {
    setSearch('');
    setDateFrom('');
    setDateTo('');
    setTimeout(() => fetchResults(1), 0);
  }

  // Quick date presets
  function setToday() {
    const t = new Date().toISOString().split('T')[0];
    setDateFrom(t);
    setDateTo(t);
  }
  function setLast7() {
    const to = new Date();
    const from = new Date();
    from.setDate(from.getDate() - 7);
    setDateFrom(from.toISOString().split('T')[0]);
    setDateTo(to.toISOString().split('T')[0]);
  }
  function setLast30() {
    const to = new Date();
    const from = new Date();
    from.setDate(from.getDate() - 30);
    setDateFrom(from.toISOString().split('T')[0]);
    setDateTo(to.toISOString().split('T')[0]);
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Camera className="h-6 w-6 text-blue-500" />
            Snapshot Search
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Search camera images by token number, vehicle number, or date
          </p>
        </div>
        {total > 0 && (
          <Badge variant="secondary" className="text-sm px-3 py-1">
            {total} image{total !== 1 ? 's' : ''} found
          </Badge>
        )}
      </div>

      {/* Search bar */}
      <Card>
        <CardContent className="pt-4 pb-4">
          <form onSubmit={handleSearch} className="flex flex-wrap items-end gap-3">
            <div className="flex-1 min-w-[200px]">
              <label className="text-xs font-medium text-muted-foreground mb-1 block">
                Token No. or Vehicle No.
              </label>
              <div className="relative">
                <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input
                  placeholder="e.g. 1234 or MH-12-AB-1234"
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  className="pl-9"
                />
              </div>
            </div>

            <div className="w-[150px]">
              <label className="text-xs font-medium text-muted-foreground mb-1 block">From Date</label>
              <Input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} />
            </div>

            <div className="w-[150px]">
              <label className="text-xs font-medium text-muted-foreground mb-1 block">To Date</label>
              <Input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} />
            </div>

            <div className="flex gap-1.5">
              <Button type="submit" size="sm" disabled={loading}>
                <Search className="h-3.5 w-3.5 mr-1" /> Search
              </Button>
              <Button type="button" variant="outline" size="sm" onClick={clearFilters}>
                <X className="h-3.5 w-3.5 mr-1" /> Clear
              </Button>
            </div>

            {/* Date presets */}
            <div className="flex gap-1 ml-auto">
              <Button type="button" variant="ghost" size="sm" className="text-xs h-7" onClick={setToday}>Today</Button>
              <Button type="button" variant="ghost" size="sm" className="text-xs h-7" onClick={setLast7}>7 Days</Button>
              <Button type="button" variant="ghost" size="sm" className="text-xs h-7" onClick={setLast30}>30 Days</Button>
            </div>
          </form>
        </CardContent>
      </Card>

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center py-12">
          <div className="h-8 w-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
        </div>
      )}

      {/* No results */}
      {!loading && searched && items.length === 0 && (
        <Card>
          <CardContent className="py-12 text-center">
            <ImageIcon className="h-12 w-12 text-muted-foreground/30 mx-auto mb-3" />
            <p className="text-lg font-medium text-muted-foreground">No snapshots found</p>
            <p className="text-sm text-muted-foreground/70 mt-1">Try a different search term or date range</p>
          </CardContent>
        </Card>
      )}

      {/* Results grouped by token */}
      {!loading && groups.length > 0 && (
        <div className="space-y-4">
          {groups.map(g => (
            <Card key={g.token_id} className="overflow-hidden">
              {/* Token header */}
              <div className="bg-muted/40 px-4 py-2.5 border-b flex items-center gap-4 flex-wrap">
                <div className="flex items-center gap-2">
                  <FileText className="h-4 w-4 text-blue-500" />
                  <span className="font-semibold text-sm">
                    Token #{g.token_no ?? '—'}
                  </span>
                </div>
                <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
                  <Calendar className="h-3.5 w-3.5" />
                  {fmtDate(g.token_date)}
                </div>
                <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
                  <Truck className="h-3.5 w-3.5" />
                  {g.vehicle_no ?? '—'}
                </div>
                {g.party_name && (
                  <span className="text-sm text-muted-foreground">
                    {g.party_name}
                  </span>
                )}
              </div>

              <CardContent className="py-3 px-4">
                <div className="grid md:grid-cols-2 gap-4">
                  {/* 1st Weight */}
                  <div>
                    <p className="text-xs font-semibold text-amber-600 mb-2 flex items-center gap-1">
                      <span className="h-2 w-2 rounded-full bg-amber-500" />
                      1st Weight
                    </p>
                    {g.first_weight.length === 0 ? (
                      <p className="text-xs text-muted-foreground italic">No snapshots</p>
                    ) : (
                      <div className="grid grid-cols-2 gap-2">
                        {g.first_weight.map(snap => (
                          <div
                            key={`${snap.camera_id}-fw`}
                            className="relative group rounded-lg overflow-hidden border bg-black cursor-pointer"
                            onClick={() => snap.url && setLightbox({ url: snap.url, label: `${snap.camera_label ?? snap.camera_id} - 1st Weight` })}
                          >
                            {snap.url ? (
                              <img
                                src={snap.url}
                                alt={snap.camera_label ?? snap.camera_id}
                                className="w-full h-32 object-cover"
                              />
                            ) : (
                              <div className="w-full h-32 flex items-center justify-center bg-muted">
                                <ImageIcon className="h-8 w-8 text-muted-foreground/30" />
                              </div>
                            )}
                            <div className="absolute inset-0 bg-black/0 group-hover:bg-black/40 transition-colors flex items-center justify-center">
                              <Eye className="h-6 w-6 text-white opacity-0 group-hover:opacity-100 transition-opacity" />
                            </div>
                            <div className="absolute bottom-0 inset-x-0 bg-gradient-to-t from-black/70 to-transparent px-2 py-1">
                              <p className="text-[10px] text-white font-medium">{snap.camera_label ?? snap.camera_id}</p>
                              <p className="text-[9px] text-white/60">{fmtDateTime(snap.captured_at)}</p>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* 2nd Weight */}
                  <div>
                    <p className="text-xs font-semibold text-emerald-600 mb-2 flex items-center gap-1">
                      <span className="h-2 w-2 rounded-full bg-emerald-500" />
                      2nd Weight
                    </p>
                    {g.second_weight.length === 0 ? (
                      <p className="text-xs text-muted-foreground italic">No snapshots</p>
                    ) : (
                      <div className="grid grid-cols-2 gap-2">
                        {g.second_weight.map(snap => (
                          <div
                            key={`${snap.camera_id}-sw`}
                            className="relative group rounded-lg overflow-hidden border bg-black cursor-pointer"
                            onClick={() => snap.url && setLightbox({ url: snap.url, label: `${snap.camera_label ?? snap.camera_id} - 2nd Weight` })}
                          >
                            {snap.url ? (
                              <img
                                src={snap.url}
                                alt={snap.camera_label ?? snap.camera_id}
                                className="w-full h-32 object-cover"
                              />
                            ) : (
                              <div className="w-full h-32 flex items-center justify-center bg-muted">
                                <ImageIcon className="h-8 w-8 text-muted-foreground/30" />
                              </div>
                            )}
                            <div className="absolute inset-0 bg-black/0 group-hover:bg-black/40 transition-colors flex items-center justify-center">
                              <Eye className="h-6 w-6 text-white opacity-0 group-hover:opacity-100 transition-opacity" />
                            </div>
                            <div className="absolute bottom-0 inset-x-0 bg-gradient-to-t from-black/70 to-transparent px-2 py-1">
                              <p className="text-[10px] text-white font-medium">{snap.camera_label ?? snap.camera_id}</p>
                              <p className="text-[9px] text-white/60">{fmtDateTime(snap.captured_at)}</p>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Pagination */}
      {!loading && totalPages > 1 && (
        <div className="flex items-center justify-between pt-2">
          <p className="text-sm text-muted-foreground">
            Page {page} of {totalPages} ({total} images)
          </p>
          <div className="flex gap-1">
            <Button
              variant="outline" size="sm"
              disabled={page <= 1}
              onClick={() => fetchResults(page - 1)}
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <Button
              variant="outline" size="sm"
              disabled={page >= totalPages}
              onClick={() => fetchResults(page + 1)}
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </div>
      )}

      {/* Lightbox */}
      {lightbox && <Lightbox url={lightbox.url} label={lightbox.label} onClose={() => setLightbox(null)} />}
    </div>
  );
}
