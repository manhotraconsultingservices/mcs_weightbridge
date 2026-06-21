/**
 * GateCameraLivePage — Live view of entry and exit gate cameras.
 *
 * Cloud deployment: polls GET /api/v1/gate/latest-snapshot/{position} every 3 s.
 * Snapshots are pushed by gate_camera_agent.py running on-site.
 * Shows "Agent offline" when no push received in the last 30 seconds.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertTriangle, Camera, RefreshCw, WifiOff, Radio } from 'lucide-react';
import { Button } from '@/components/ui/button';
import api from '@/services/api';

// ── Types ──────────────────────────────────────────────────────────────────────

type CamStatus = 'idle' | 'loading' | 'live' | 'stale' | 'off' | 'error';

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
  refreshInterval?: number; // ms, default 3000
}

function CameraPanel({ position, label, refreshInterval = 3000 }: CameraPanelProps) {
  const [state, setState] = useState<PanelState>({
    status: 'idle', url: null, lastCapture: null, error: null,
  });
  const mountedRef = useRef(true);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const poll = useCallback(async () => {
    if (!mountedRef.current) return;
    setState(s => ({ ...s, status: s.url ? s.status : 'loading' }));
    try {
      const { data } = await api.get<LatestSnapshotResponse>(
        `/api/v1/gate/latest-snapshot/${position}`
      );
      if (!mountedRef.current) return;
      if (!data.configured) {
        setState(s => ({ ...s, status: 'off', error: null }));
        return;
      }
      if (data.is_stale) {
        // Show last frame (if any) but mark as stale
        setState(s => ({
          ...s,
          status: 'stale',
          url: data.url ? `${data.url}?t=${Date.now()}` : s.url,
          error: null,
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

  const bgColor = position === 'entry' ? 'bg-emerald-500' : 'bg-rose-500';
  const labelColor = position === 'entry' ? 'text-emerald-700 bg-emerald-50 border-emerald-200' : 'text-rose-700 bg-rose-50 border-rose-200';

  return (
    <div className="rounded-xl border bg-card overflow-hidden shadow-sm">
      {/* Header bar */}
      <div className="flex items-center justify-between px-4 py-2 border-b bg-muted/30">
        <div className="flex items-center gap-2">
          <span className={`px-2 py-0.5 rounded-full text-xs font-semibold border ${labelColor}`}>
            {position === 'entry' ? 'ENTRY' : 'EXIT'}
          </span>
          <span className="font-medium text-sm truncate">{label}</span>
          {state.status === 'live' && (
            <span className="flex h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
          )}
          {state.status === 'stale' && (
            <span className="flex h-2 w-2 rounded-full bg-amber-400" title="Agent offline — showing last frame" />
          )}
          {state.status === 'error' && (
            <span className="flex h-2 w-2 rounded-full bg-red-500" />
          )}
          {state.status === 'loading' && (
            <RefreshCw className="h-3 w-3 text-muted-foreground animate-spin" />
          )}
        </div>
        <div className="flex items-center gap-2">
          {state.lastCapture && (
            <span className="text-[11px] text-muted-foreground tabular-nums">
              {state.lastCapture.toLocaleTimeString('en-IN', {
                hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
                timeZone: 'Asia/Kolkata',
              })}
            </span>
          )}
          <Button
            variant="ghost" size="icon" className="h-7 w-7"
            onClick={() => { poll(); }}
            disabled={state.status === 'loading'}
            title="Refresh"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${state.status === 'loading' ? 'animate-spin' : ''}`} />
          </Button>
        </div>
      </div>

      {/* Camera view area — 16:9 aspect ratio */}
      <div className="relative bg-gray-950 aspect-video flex items-center justify-center">
        {state.url ? (
          <>
            <img
              key={state.url}
              src={state.url}
              alt={label}
              className="w-full h-full object-contain"
              onError={() => {
                if (mountedRef.current) {
                  setState(s => ({ ...s, status: 'error', error: 'Failed to load snapshot' }));
                }
              }}
            />
            {/* Stale overlay — keep showing last frame but warn */}
            {state.status === 'stale' && (
              <div className="absolute inset-0 flex items-end justify-center pb-4 bg-black/30">
                <div className="flex items-center gap-1.5 bg-amber-500/90 text-white rounded px-3 py-1.5 text-xs font-semibold">
                  <Radio className="h-3 w-3" />
                  Agent offline — showing last frame
                </div>
              </div>
            )}
          </>
        ) : state.status === 'off' ? (
          <div className="text-center px-6">
            <WifiOff className="h-12 w-12 mx-auto mb-3 text-gray-600" />
            <p className="text-sm text-gray-400 font-medium">Agent not started</p>
            <p className="text-xs text-gray-500 mt-1 max-w-xs">
              Run <code className="bg-gray-800 px-1 rounded">gate_camera_agent.py</code> on
              the on-site PC to start pushing snapshots.
            </p>
            <p className="text-xs text-gray-600 mt-2">
              Get the agent key from Settings → Gate Cameras.
            </p>
          </div>
        ) : state.status === 'error' ? (
          <div className="text-center px-6">
            <AlertTriangle className="h-12 w-12 mx-auto mb-3 text-red-400/70" />
            <p className="text-sm text-gray-300 font-medium">{state.error ?? 'Fetch error'}</p>
            <Button
              variant="outline" size="sm"
              className="mt-3 border-gray-700 text-gray-300 hover:bg-gray-800"
              onClick={() => { poll(); }}
            >
              <RefreshCw className="h-3 w-3 mr-1.5" /> Retry
            </Button>
          </div>
        ) : (
          <div className="text-center px-6">
            <Camera className="h-12 w-12 mx-auto mb-3 text-gray-600" />
            <p className="text-sm text-gray-500">Waiting for agent…</p>
          </div>
        )}

        {/* Live badge */}
        {state.status === 'live' && (
          <div className="absolute top-2 left-2 flex items-center gap-1 bg-black/60 rounded px-2 py-0.5">
            <span className={`h-1.5 w-1.5 rounded-full ${bgColor} animate-pulse`} />
            <span className="text-[10px] text-white font-bold tracking-wider">LIVE</span>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function GateCameraLivePage() {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Gate Camera Live Feed</h2>
          <p className="text-sm text-muted-foreground">
            Snapshots pushed by the on-site camera agent every 3 seconds.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <CameraPanel position="entry" label="Entry Gate Camera" />
        <CameraPanel position="exit" label="Exit Gate Camera" />
      </div>

      <p className="text-xs text-center text-muted-foreground">
        Run <code className="bg-muted px-1 rounded">gate_camera_agent.py</code> on the on-site PC.
        Get setup instructions and agent key in{' '}
        <a href="/settings?tab=gate-cameras" className="underline hover:text-foreground">
          Settings → Gate Cameras
        </a>
        .
      </p>
    </div>
  );
}
