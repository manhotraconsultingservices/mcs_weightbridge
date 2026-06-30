/**
 * GateCameraLivePage — Live view of entry and exit gate cameras.
 * Same dark CCTV-monitor aesthetic as CameraScalePage.
 * Uses HTTP polling (not WebSocket) — camera_agent.py (GateLiveFeedPusher)
 * pushes snapshots every 3 s; we poll GET /gate/latest-snapshot/{position}.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Activity, AlertTriangle, Camera, Maximize2, Radio, RefreshCw, WifiOff,
} from 'lucide-react';
import api from '@/services/api';

// ── Clock ─────────────────────────────────────────────────────────────────────
function LiveClock() {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  return (
    <span className="font-mono text-sm text-emerald-400/80">
      {now.toLocaleDateString('en-IN')}
      {'  '}
      {now.toLocaleTimeString('en-IN', { hour12: false })}
    </span>
  );
}

// ── Types ──────────────────────────────────────────────────────────────────────
type CamStatus = 'loading' | 'live' | 'stale' | 'off' | 'error';

interface LatestSnapshotResponse {
  configured: boolean;
  url: string | null;
  last_updated_at: string | null;
  is_stale: boolean;
}

interface PanelState {
  status: CamStatus;
  url: string | null;
  lastCapture: Date | null;
  error: string | null;
}

// ── Single camera panel ───────────────────────────────────────────────────────
interface CameraPanelProps {
  position: 'entry' | 'exit';
  label: string;
  refreshInterval?: number;
}

function CameraPanel({ position, label, refreshInterval = 3000 }: CameraPanelProps) {
  const [state, setState] = useState<PanelState>({
    status: 'loading', url: null, lastCapture: null, error: null,
  });
  const [fullscreen, setFullscreen] = useState(false);
  const mountedRef = useRef(true);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const poll = useCallback(async () => {
    if (!mountedRef.current) return;
    try {
      const { data } = await api.get<LatestSnapshotResponse>(
        `/api/v1/gate/latest-snapshot/${position}`,
      );
      if (!mountedRef.current) return;
      if (!data.configured) {
        setState(s => ({ ...s, status: 'off', error: null }));
        return;
      }
      if (data.is_stale) {
        setState(s => ({
          ...s,
          status: 'stale',
          url: data.url ? `${data.url}?t=${Date.now()}` : s.url,
          error: null,
          lastCapture: data.last_updated_at ? new Date(data.last_updated_at) : s.lastCapture,
        }));
        return;
      }
      setState({
        status: 'live',
        url: `${data.url}?t=${Date.now()}`,
        lastCapture: data.last_updated_at ? new Date(data.last_updated_at) : new Date(),
        error: null,
      });
    } catch (e: unknown) {
      if (!mountedRef.current) return;
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? '';
      setState(s => ({ ...s, status: 'error', error: detail || 'Fetch error' }));
    }
  }, [position]);

  useEffect(() => {
    mountedRef.current = true;
    poll();
    intervalRef.current = setInterval(poll, refreshInterval);
    return () => {
      mountedRef.current = false;
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [poll, refreshInterval]);

  const { status, url, lastCapture, error } = state;

  // Position-specific accent (entry = emerald, exit = rose)
  const isEntry = position === 'entry';
  const accentDot    = isEntry ? 'bg-emerald-400'           : 'bg-rose-400';
  const accentText   = isEntry ? 'text-emerald-400'          : 'text-rose-400';
  const accentBorder = isEntry ? 'border-emerald-500/40'     : 'border-rose-500/40';
  const accentBg     = isEntry ? 'bg-emerald-500/10'         : 'bg-rose-500/10';
  const accentCorner = isEntry ? 'border-emerald-500/50'     : 'border-rose-500/50';

  const statusDotCls =
    status === 'live'    ? accentDot    :
    status === 'stale'   ? 'bg-amber-400' :
    status === 'loading' ? 'bg-amber-400' :
    status === 'off'     ? 'bg-slate-600' : 'bg-red-500';

  const statusTextCls =
    status === 'live'    ? accentText   :
    status === 'stale'   ? 'text-amber-400' :
    status === 'loading' ? 'text-amber-400' :
    status === 'off'     ? 'text-slate-500' : 'text-red-400';

  const statusBadgeBorder =
    status === 'live'    ? accentBorder   :
    status === 'stale'   ? 'border-amber-500/40'  :
    status === 'loading' ? 'border-amber-500/40'  :
    status === 'off'     ? 'border-slate-600/40'  : 'border-red-500/40';

  const statusBadgeBg =
    status === 'live'    ? accentBg      :
    status === 'stale'   ? 'bg-amber-500/10'   :
    status === 'loading' ? 'bg-amber-500/10'   :
    status === 'off'     ? 'bg-slate-600/10'   : 'bg-red-500/10';

  const statusBadgeLabel =
    status === 'live'    ? `● ${isEntry ? 'ENTRY' : 'EXIT'} LIVE` :
    status === 'stale'   ? '◑ LAST FRAME' :
    status === 'loading' ? '◌ CONNECTING'  :
    status === 'off'     ? '✕ NOT CONFIGURED' : '✕ OFFLINE';

  return (
    <>
      <div className="relative flex flex-col rounded-xl overflow-hidden border border-slate-700/60 bg-slate-900/80 shadow-2xl shadow-black/40">

        {/* Header bar */}
        <div className="flex items-center justify-between px-4 py-2.5 bg-slate-800/90 border-b border-slate-700/50 shrink-0">
          <div className="flex items-center gap-2.5">
            <span className="relative flex h-2.5 w-2.5 shrink-0">
              {status === 'live' && (
                <span className={`absolute inline-flex h-full w-full rounded-full opacity-75 animate-ping ${accentDot}`} />
              )}
              <span className={`relative inline-flex h-2.5 w-2.5 rounded-full ${statusDotCls}`} />
            </span>
            <Camera className="h-4 w-4 text-slate-400" />
            <div>
              <p className="text-sm font-semibold text-slate-100 leading-none">{label}</p>
              <p className="text-[10px] text-slate-500 mt-0.5">
                {isEntry ? 'Gate Entry · Camera 1' : 'Gate Exit · Camera 2'}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {lastCapture && (
              <span className="text-[10px] text-slate-500 font-mono tabular-nums">
                {lastCapture.toLocaleTimeString('en-IN', {
                  hour: '2-digit', minute: '2-digit', second: '2-digit',
                  hour12: false, timeZone: 'Asia/Kolkata',
                })}
              </span>
            )}
            <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${statusTextCls} ${statusBadgeBorder} ${statusBadgeBg}`}>
              {statusBadgeLabel}
            </span>
            <button
              onClick={() => poll()}
              className="p-1 rounded text-slate-500 hover:text-slate-300 transition-colors"
              title="Refresh"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${status === 'loading' ? 'animate-spin' : ''}`} />
            </button>
            {status === 'live' && url && (
              <button
                onClick={() => setFullscreen(true)}
                className="p-1 rounded text-slate-500 hover:text-slate-300 transition-colors"
                title="Fullscreen"
              >
                <Maximize2 className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        </div>

        {/* Video area */}
        <div className="relative bg-black overflow-hidden" style={{ minHeight: '240px', aspectRatio: '16/9' }}>
          {/* Scan-line overlay */}
          <div
            className="pointer-events-none absolute inset-0 z-10 opacity-[0.03]"
            style={{ backgroundImage: 'repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,0,0,1) 2px, rgba(0,0,0,1) 4px)' }}
          />

          {status === 'off' && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-slate-950">
              <WifiOff className="h-10 w-10 text-slate-600" />
              <p className="text-slate-500 text-sm font-medium">No frames received yet</p>
              <p className="text-slate-600 text-xs text-center max-w-xs leading-relaxed">
                Add{' '}
                <code className="bg-slate-800 px-1 rounded">gate_cameras.{position}</code>{' '}
                URL to <code className="bg-slate-800 px-1 rounded">camera_config.json</code>{' '}
                on the site PC, then restart{' '}
                <code className="bg-slate-800 px-1 rounded">WeighbridgeCameraAgent</code>.
              </p>
            </div>
          )}

          {status === 'error' && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-slate-950">
              <AlertTriangle className="h-10 w-10 text-red-500/50" />
              <p className="text-red-400 text-sm font-medium">{error ?? 'Fetch error'}</p>
              <p className="text-slate-600 text-xs">Check Settings → Gate Cameras</p>
              <button
                onClick={() => poll()}
                className="mt-2 flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md bg-slate-800 text-slate-300 hover:bg-slate-700 border border-slate-600 transition-colors"
              >
                <RefreshCw className="h-3 w-3" /> Retry
              </button>
            </div>
          )}

          {status === 'loading' && !url && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-slate-950">
              <div className="relative">
                <div className="h-12 w-12 rounded-full border-2 border-slate-700 border-t-amber-400 animate-spin" />
                <Camera className="absolute inset-0 m-auto h-5 w-5 text-slate-500" />
              </div>
              <p className="text-amber-400/80 text-sm">Connecting to agent…</p>
            </div>
          )}

          {url && (status === 'live' || status === 'stale') && (
            <img
              key={url}
              src={url}
              alt={label}
              className="w-full h-full object-contain"
              onError={() => {
                if (mountedRef.current)
                  setState(s => ({ ...s, status: 'error', error: 'Failed to load snapshot' }));
              }}
            />
          )}

          {/* Stale overlay */}
          {status === 'stale' && (
            <div className="absolute inset-0 flex items-end justify-center pb-4 bg-black/30 z-20">
              <div className="flex items-center gap-1.5 bg-amber-500/90 text-white rounded px-3 py-1.5 text-xs font-semibold">
                <Radio className="h-3 w-3" />
                Agent offline — showing last frame
              </div>
            </div>
          )}

          {/* Corner markers + bottom bar when live */}
          {status === 'live' && (
            <>
              {[
                'top-2 left-2 border-t-2 border-l-2 rounded-tl',
                'top-2 right-2 border-t-2 border-r-2 rounded-tr',
                'bottom-2 left-2 border-b-2 border-l-2 rounded-bl',
                'bottom-2 right-2 border-b-2 border-r-2 rounded-br',
              ].map((cls, i) => (
                <div key={i} className={`absolute ${cls} ${accentCorner} h-4 w-4 z-20`} />
              ))}
              <div className="absolute bottom-0 inset-x-0 z-20 bg-gradient-to-t from-black/70 to-transparent px-3 pt-6 pb-2 flex items-end justify-between">
                <span className={`text-[10px] font-mono flex items-center gap-1 ${accentText} opacity-80`}>
                  <Activity className="h-2.5 w-2.5" /> AGENT LIVE · 3s poll
                </span>
                <LiveClock />
              </div>
            </>
          )}
        </div>
      </div>

      {/* Fullscreen overlay */}
      {fullscreen && url && (
        <div className="fixed inset-0 z-[300] bg-black flex flex-col" onClick={() => setFullscreen(false)}>
          <div
            className="flex items-center justify-between px-4 py-2 bg-slate-900/90 border-b border-slate-700/50"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-center gap-2">
              <span className="relative flex h-2 w-2">
                <span className={`absolute animate-ping inline-flex h-full w-full rounded-full ${accentDot} opacity-75`} />
                <span className={`relative inline-flex h-2 w-2 rounded-full ${accentDot}`} />
              </span>
              <Camera className="h-4 w-4 text-slate-400" />
              <span className="text-sm font-medium text-slate-200">{label}</span>
              <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${accentText} ${accentBorder} ${accentBg}`}>
                ● LIVE
              </span>
            </div>
            <button
              onClick={() => setFullscreen(false)}
              className="text-slate-400 hover:text-white text-xs border border-slate-600 rounded px-2 py-1"
            >
              ✕ Exit Fullscreen
            </button>
          </div>
          <img src={url} alt={label} className="flex-1 w-full object-contain" />
        </div>
      )}
    </>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────
export default function GateCameraLivePage() {
  return (
    <div
      className="flex flex-col min-h-[calc(100vh-3rem)] -m-6 p-0"
      style={{ background: 'linear-gradient(135deg, #020817 0%, #0a1628 50%, #020817 100%)' }}
    >
      {/* Top header */}
      <div className="shrink-0 flex items-center justify-between px-6 py-3 bg-slate-900/60 border-b border-slate-700/40 backdrop-blur-sm">
        <div className="flex items-center gap-3">
          <div className="relative flex h-8 w-8 items-center justify-center">
            <span
              className="absolute h-8 w-8 rounded-full bg-emerald-500/20 animate-ping"
              style={{ animationDuration: '2s' }}
            />
            <span className="relative flex h-6 w-6 items-center justify-center rounded-full bg-emerald-500/20 border border-emerald-500/40">
              <Activity className="h-3.5 w-3.5 text-emerald-400" />
            </span>
          </div>
          <div>
            <h1 className="text-base font-bold text-slate-100 tracking-wide">Gate Camera Live Feed</h1>
            <p className="text-[10px] text-slate-500 tracking-widest uppercase">
              Entry &amp; Exit Surveillance · Agent Push · 3s Refresh
            </p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-1.5 text-xs">
            <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
            <span className="text-emerald-400 font-semibold">LIVE</span>
          </div>
          <div className="h-4 w-px bg-slate-700" />
          <LiveClock />
        </div>
      </div>

      {/* Camera grid */}
      <div className="flex-1 grid grid-cols-1 md:grid-cols-2 gap-4 p-4 min-h-0">
        <CameraPanel position="entry" label="Entry Gate Camera" />
        <CameraPanel position="exit"  label="Exit Gate Camera"  />
      </div>

      {/* Bottom status bar */}
      <div className="shrink-0 flex items-center justify-between px-6 py-2 bg-slate-900/60 border-t border-slate-700/40 text-[10px] text-slate-600 font-mono">
        <span>GATE SURVEILLANCE SYSTEM · Agent Push Mode</span>
        <span className="flex items-center gap-2">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
          HTTP POLL · 3s INTERVAL
        </span>
        <a href="/settings?tab=gate-cameras" className="underline hover:text-slate-400 transition-colors">
          Settings → Gate Cameras
        </a>
      </div>
    </div>
  );
}
