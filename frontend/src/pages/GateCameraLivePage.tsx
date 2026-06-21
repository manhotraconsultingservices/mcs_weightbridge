/**
 * GateCameraLivePage — Live view of entry and exit gate cameras.
 *
 * Polls POST /api/v1/gate/capture/{position} every 5 s.
 * Each call triggers an HTTP snapshot from the configured CP Plus camera,
 * saves to uploads/gate/, and returns the URL.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertTriangle, Camera, RefreshCw, WifiOff } from 'lucide-react';
import { Button } from '@/components/ui/button';
import api from '@/services/api';

// ── Types ──────────────────────────────────────────────────────────────────────

type CamStatus = 'idle' | 'loading' | 'live' | 'off' | 'error';

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
  refreshInterval?: number; // ms, default 5000
}

function CameraPanel({ position, label, refreshInterval = 5000 }: CameraPanelProps) {
  const [state, setState] = useState<PanelState>({
    status: 'idle', url: null, lastCapture: null, error: null,
  });
  const mountedRef = useRef(true);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const capture = useCallback(async () => {
    if (!mountedRef.current) return;
    setState(s => ({ ...s, status: 'loading' }));
    try {
      const { data } = await api.post<{ url: string }>(`/api/v1/gate/capture/${position}`, {});
      if (!mountedRef.current) return;
      // Bust the browser image cache with a timestamp query param
      setState({ status: 'live', url: `${data.url}?t=${Date.now()}`, lastCapture: new Date(), error: null });
    } catch (e: unknown) {
      if (!mountedRef.current) return;
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? '';
      if (detail.includes('not configured') || detail.includes('disabled')) {
        setState(s => ({ ...s, status: 'off', error: null }));
      } else {
        setState(s => ({ ...s, status: 'error', error: detail || 'Camera offline' }));
      }
    }
  }, [position]);

  useEffect(() => {
    mountedRef.current = true;
    capture();
    intervalRef.current = setInterval(capture, refreshInterval);
    return () => {
      mountedRef.current = false;
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [capture, refreshInterval]);

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
              })}
            </span>
          )}
          <Button
            variant="ghost" size="icon" className="h-7 w-7"
            onClick={() => { capture(); }}
            disabled={state.status === 'loading'}
            title="Capture now"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${state.status === 'loading' ? 'animate-spin' : ''}`} />
          </Button>
        </div>
      </div>

      {/* Camera view area — 16:9 aspect ratio */}
      <div className="relative bg-gray-950 aspect-video flex items-center justify-center">
        {state.url && state.status !== 'off' ? (
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
        ) : state.status === 'off' ? (
          <div className="text-center px-6">
            <WifiOff className="h-12 w-12 mx-auto mb-3 text-gray-600" />
            <p className="text-sm text-gray-400 font-medium">Camera not configured</p>
            <p className="text-xs text-gray-600 mt-1">
              Go to Settings → Gate Cameras to set up the {position} camera URL.
            </p>
          </div>
        ) : state.status === 'error' ? (
          <div className="text-center px-6">
            <AlertTriangle className="h-12 w-12 mx-auto mb-3 text-red-400/70" />
            <p className="text-sm text-gray-300 font-medium">{state.error ?? 'Camera offline'}</p>
            <p className="text-xs text-gray-600 mt-1 mb-3">Check camera power and network connectivity.</p>
            <Button
              variant="outline" size="sm"
              className="border-gray-700 text-gray-300 hover:bg-gray-800"
              onClick={() => { capture(); }}
            >
              <RefreshCw className="h-3 w-3 mr-1.5" /> Retry
            </Button>
          </div>
        ) : (
          <div className="text-center px-6">
            <Camera className="h-12 w-12 mx-auto mb-3 text-gray-600" />
            <p className="text-sm text-gray-500">Connecting to camera…</p>
          </div>
        )}

        {/* Live badge overlay */}
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
            Entry and exit cameras — auto-refreshes every 5 seconds. Snapshots are saved to the gate event log.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <CameraPanel position="entry" label="Entry Gate Camera" />
        <CameraPanel position="exit" label="Exit Gate Camera" />
      </div>

      <p className="text-xs text-center text-muted-foreground">
        Configure cameras in{' '}
        <a href="/settings?tab=gate-cameras" className="underline hover:text-foreground">
          Settings → Gate Cameras
        </a>
        . Each refresh captures a still image from the camera and saves it to the gate log.
      </p>
    </div>
  );
}
