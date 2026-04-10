import { useEffect, useRef, useState } from 'react';
import {
  Camera, Scale, Wifi, WifiOff, Activity, RefreshCw,
  Maximize2, Clock, Gauge, TrendingUp,
} from 'lucide-react';
import { useWeight } from '@/hooks/useWeight';

// ── JWT helper ────────────────────────────────────────────────────────────────
function getToken(): string {
  return sessionStorage.getItem('token') ?? '';
}

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

// ── Camera panel ──────────────────────────────────────────────────────────────
interface CameraPanelProps {
  cameraId: 'front' | 'top';
  label: string;
  subtitle?: string;
}

function CameraPanel({ cameraId, label, subtitle }: CameraPanelProps) {
  const [status, setStatus] = useState<'connecting' | 'live' | 'error'>('connecting');
  const [retryKey, setRetryKey] = useState(0);
  const [fullscreen, setFullscreen] = useState(false);
  const imgRef = useRef<HTMLImageElement>(null);
  const token = getToken();

  const streamUrl = `/api/v1/cameras/stream/${cameraId}?token=${encodeURIComponent(token)}`;

  function handleLoad() { setStatus('live'); }
  function handleError() { setStatus('error'); }
  function retry() { setStatus('connecting'); setRetryKey(k => k + 1); }

  useEffect(() => {
    setStatus('connecting');
  }, [retryKey]);

  return (
    <>
      <div className="relative flex flex-col rounded-xl overflow-hidden border border-slate-700/60 bg-slate-900/80 shadow-2xl shadow-black/40 group">

        {/* ── Header bar ── */}
        <div className="flex items-center justify-between px-4 py-2.5 bg-slate-800/90 border-b border-slate-700/50 shrink-0">
          <div className="flex items-center gap-2.5">
            {/* Status dot */}
            <span className={`relative flex h-2.5 w-2.5 shrink-0 ${
              status === 'live'        ? 'text-emerald-400' :
              status === 'connecting'  ? 'text-amber-400'   : 'text-red-500'
            }`}>
              <span className={`absolute inline-flex h-full w-full rounded-full opacity-75 ${
                status === 'live' ? 'animate-ping bg-emerald-400' :
                status === 'connecting' ? 'animate-ping bg-amber-400' : ''
              }`} />
              <span className={`relative inline-flex h-2.5 w-2.5 rounded-full ${
                status === 'live' ? 'bg-emerald-400' :
                status === 'connecting' ? 'bg-amber-400' : 'bg-red-500'
              }`} />
            </span>
            <Camera className="h-4 w-4 text-slate-400" />
            <div>
              <p className="text-sm font-semibold text-slate-100 leading-none">{label}</p>
              {subtitle && <p className="text-[10px] text-slate-500 mt-0.5">{subtitle}</p>}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${
              status === 'live'
                ? 'text-emerald-400 border-emerald-500/40 bg-emerald-500/10'
                : status === 'connecting'
                ? 'text-amber-400 border-amber-500/40 bg-amber-500/10'
                : 'text-red-400 border-red-500/40 bg-red-500/10'
            }`}>
              {status === 'live' ? '● LIVE' : status === 'connecting' ? '◌ CONNECTING' : '✕ OFFLINE'}
            </span>
            <button
              onClick={retry}
              className="p-1 rounded text-slate-500 hover:text-slate-300 transition-colors"
              title="Reconnect"
            >
              <RefreshCw className="h-3.5 w-3.5" />
            </button>
            <button
              onClick={() => setFullscreen(true)}
              className="p-1 rounded text-slate-500 hover:text-slate-300 transition-colors"
              title="Fullscreen"
            >
              <Maximize2 className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>

        {/* ── Video area ── */}
        <div className="relative flex-1 bg-black min-h-0 overflow-hidden">
          {/* Scan-line overlay for CRT effect */}
          <div
            className="pointer-events-none absolute inset-0 z-10 opacity-[0.03]"
            style={{
              backgroundImage: 'repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,0,0,1) 2px, rgba(0,0,0,1) 4px)',
            }}
          />

          {status === 'error' && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-slate-950">
              <WifiOff className="h-10 w-10 text-red-500/50" />
              <p className="text-red-400 text-sm font-medium">Camera Offline</p>
              <p className="text-slate-600 text-xs">Check RTSP URL in Settings → Cameras</p>
              <button
                onClick={retry}
                className="mt-2 flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md bg-slate-800 text-slate-300 hover:bg-slate-700 border border-slate-600 transition-colors"
              >
                <RefreshCw className="h-3 w-3" /> Retry
              </button>
            </div>
          )}

          {status === 'connecting' && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-slate-950">
              <div className="relative">
                <div className="h-12 w-12 rounded-full border-2 border-slate-700 border-t-amber-400 animate-spin" />
                <Camera className="absolute inset-0 m-auto h-5 w-5 text-slate-500" />
              </div>
              <p className="text-amber-400/80 text-sm">Connecting to camera…</p>
            </div>
          )}

          <img
            key={retryKey}
            ref={imgRef}
            src={streamUrl}
            alt={label}
            onLoad={handleLoad}
            onError={handleError}
            className={`w-full h-full object-cover transition-opacity duration-500 ${
              status === 'live' ? 'opacity-100' : 'opacity-0 absolute inset-0'
            }`}
          />

          {/* Corner crosshair markers */}
          {status === 'live' && (
            <>
              {[
                'top-2 left-2 border-t-2 border-l-2 rounded-tl',
                'top-2 right-2 border-t-2 border-r-2 rounded-tr',
                'bottom-2 left-2 border-b-2 border-l-2 rounded-bl',
                'bottom-2 right-2 border-b-2 border-r-2 rounded-br',
              ].map((cls, i) => (
                <div key={i} className={`absolute ${cls} border-emerald-500/50 h-4 w-4 z-20`} />
              ))}
              {/* Bottom label */}
              <div className="absolute bottom-0 inset-x-0 z-20 bg-gradient-to-t from-black/70 to-transparent px-3 pt-6 pb-2 flex items-end justify-between">
                <span className="text-[10px] text-emerald-400/80 font-mono flex items-center gap-1">
                  <Activity className="h-2.5 w-2.5" /> MJPEG · 25fps
                </span>
                <LiveClock />
              </div>
            </>
          )}
        </div>
      </div>

      {/* Fullscreen overlay */}
      {fullscreen && (
        <div
          className="fixed inset-0 z-[300] bg-black flex flex-col"
          onClick={() => setFullscreen(false)}
        >
          <div className="flex items-center justify-between px-4 py-2 bg-slate-900/90 border-b border-slate-700/50" onClick={e => e.stopPropagation()}>
            <div className="flex items-center gap-2">
              <span className="relative flex h-2 w-2">
                <span className="absolute animate-ping inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400" />
              </span>
              <Camera className="h-4 w-4 text-slate-400" />
              <span className="text-sm font-medium text-slate-200">{label}</span>
              <span className="text-[10px] text-emerald-400 font-bold px-2 py-0.5 rounded-full border border-emerald-500/40 bg-emerald-500/10">● LIVE</span>
            </div>
            <button onClick={() => setFullscreen(false)} className="text-slate-400 hover:text-white text-xs border border-slate-600 rounded px-2 py-1">
              ✕ Exit Fullscreen
            </button>
          </div>
          <img
            src={`${streamUrl}&fs=1`}
            alt={label}
            className="flex-1 w-full object-contain"
          />
        </div>
      )}
    </>
  );
}

// ── Weight display ─────────────────────────────────────────────────────────────
function WeightPanel() {
  const { reading } = useWeight();
  const { weight_kg, is_stable, scale_connected } = reading;
  const weightMT = weight_kg / 1000;

  const weightStr = weight_kg.toLocaleString('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  const mtStr = weightMT.toLocaleString('en-IN', {
    minimumFractionDigits: 3,
    maximumFractionDigits: 3,
  });

  return (
    <div className="flex flex-col gap-3 h-full">

      {/* Main weight card */}
      <div className={`flex-1 rounded-xl border bg-slate-900/80 shadow-2xl shadow-black/40 overflow-hidden flex flex-col transition-all duration-700 ${
        !scale_connected
          ? 'border-slate-700/50'
          : is_stable
          ? 'border-emerald-600/50 shadow-emerald-900/20'
          : 'border-amber-600/50 shadow-amber-900/20'
      }`}>

        {/* Header */}
        <div className="px-4 py-3 bg-slate-800/90 border-b border-slate-700/50 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-2">
            <Scale className="h-4 w-4 text-slate-400" />
            <span className="text-sm font-semibold text-slate-200">Weighing Scale</span>
          </div>
          <div className="flex items-center gap-1.5">
            {scale_connected
              ? <Wifi className="h-3.5 w-3.5 text-emerald-400" />
              : <WifiOff className="h-3.5 w-3.5 text-red-500" />
            }
            <span className={`text-[10px] font-bold ${scale_connected ? 'text-emerald-400' : 'text-red-400'}`}>
              {scale_connected ? 'CONNECTED' : 'OFFLINE'}
            </span>
          </div>
        </div>

        {/* Weight display */}
        <div className="flex-1 flex flex-col items-center justify-center px-4 py-6 gap-4">

          {/* Stability badge */}
          <div className={`flex items-center gap-1.5 text-xs font-bold px-3 py-1 rounded-full border transition-all ${
            !scale_connected
              ? 'text-slate-500 border-slate-700 bg-slate-800/50'
              : is_stable
              ? 'text-emerald-400 border-emerald-500/50 bg-emerald-500/10'
              : 'text-amber-400 border-amber-500/50 bg-amber-500/10'
          }`}>
            <span className={`h-1.5 w-1.5 rounded-full ${
              !scale_connected ? 'bg-slate-600' :
              is_stable ? 'bg-emerald-400 animate-pulse' : 'bg-amber-400 animate-pulse'
            }`} />
            {!scale_connected ? 'NO SIGNAL' : is_stable ? 'STABLE' : 'FLUCTUATING'}
          </div>

          {/* Big weight number — segmented display style */}
          <div className="text-center">
            <div className={`font-mono font-black leading-none tracking-tight transition-colors duration-500 ${
              !scale_connected
                ? 'text-slate-600'
                : is_stable
                ? 'text-emerald-400'
                : 'text-amber-400'
            }`} style={{ fontSize: 'clamp(2.4rem, 4vw, 3.5rem)' }}>
              {scale_connected ? weightStr : '——.——'}
            </div>
            <div className={`text-lg font-semibold mt-1 ${
              scale_connected ? 'text-slate-400' : 'text-slate-600'
            }`}>
              kg
            </div>
          </div>

          {/* Divider */}
          <div className="w-full border-t border-slate-700/60" />

          {/* MT conversion */}
          <div className="text-center">
            <p className="text-[10px] text-slate-500 uppercase tracking-widest mb-1">Metric Tons</p>
            <p className={`font-mono font-bold text-2xl ${
              scale_connected ? 'text-slate-300' : 'text-slate-600'
            }`}>
              {scale_connected ? mtStr : '—.———'}
            </p>
            <p className="text-sm text-slate-500 mt-0.5">MT</p>
          </div>

          {/* Gauge bar */}
          <div className="w-full space-y-1">
            <div className="flex justify-between text-[9px] text-slate-600 font-mono">
              <span>0 kg</span>
              <span>50,000 kg</span>
            </div>
            <div className="h-2 rounded-full bg-slate-800 border border-slate-700/50 overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500 ${
                  !scale_connected ? 'bg-slate-700' :
                  is_stable ? 'bg-emerald-500' : 'bg-amber-500'
                }`}
                style={{
                  width: scale_connected
                    ? `${Math.min((weight_kg / 50000) * 100, 100)}%`
                    : '0%'
                }}
              />
            </div>
          </div>
        </div>
      </div>

      {/* Stats strip */}
      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-lg bg-slate-900/80 border border-slate-700/50 px-3 py-2.5">
          <p className="text-[9px] text-slate-500 uppercase tracking-widest flex items-center gap-1 mb-1">
            <TrendingUp className="h-2.5 w-2.5" /> In Tons
          </p>
          <p className={`font-mono font-bold text-base ${scale_connected ? 'text-slate-200' : 'text-slate-600'}`}>
            {scale_connected ? mtStr : '—.———'}
          </p>
          <p className="text-[9px] text-slate-600 mt-0.5">MT</p>
        </div>
        <div className="rounded-lg bg-slate-900/80 border border-slate-700/50 px-3 py-2.5">
          <p className="text-[9px] text-slate-500 uppercase tracking-widest flex items-center gap-1 mb-1">
            <Gauge className="h-2.5 w-2.5" /> Status
          </p>
          <p className={`font-bold text-sm ${
            !scale_connected ? 'text-red-400' :
            is_stable ? 'text-emerald-400' : 'text-amber-400'
          }`}>
            {!scale_connected ? 'Offline' : is_stable ? 'Stable' : 'Moving'}
          </p>
          <p className="text-[9px] text-slate-600 mt-0.5">
            {scale_connected && reading.stable_duration_sec > 0
              ? `${reading.stable_duration_sec.toFixed(1)}s stable`
              : scale_connected ? 'measuring' : 'no signal'}
          </p>
        </div>
      </div>

      {/* Scale info card */}
      <div className="rounded-lg bg-slate-900/80 border border-slate-700/50 px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <Clock className="h-3.5 w-3.5" />
          <LiveClock />
        </div>
        <div className={`flex items-center gap-1.5 text-xs font-medium ${
          scale_connected ? 'text-emerald-400' : 'text-red-400'
        }`}>
          <span className={`h-1.5 w-1.5 rounded-full ${
            scale_connected ? 'bg-emerald-400 animate-pulse' : 'bg-red-400'
          }`} />
          {scale_connected ? 'Live feed' : 'Disconnected'}
        </div>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────
export default function CameraScalePage() {
  return (
    <div
      className="flex flex-col min-h-[calc(100vh-3rem)] -m-6 p-0"
      style={{
        background: 'linear-gradient(135deg, #020817 0%, #0a1628 50%, #020817 100%)',
      }}
    >
      {/* ── Top header bar ── */}
      <div className="shrink-0 flex items-center justify-between px-6 py-3 bg-slate-900/60 border-b border-slate-700/40 backdrop-blur-sm">
        <div className="flex items-center gap-3">
          {/* Animated pulse ring */}
          <div className="relative flex h-8 w-8 items-center justify-center">
            <span className="absolute h-8 w-8 rounded-full bg-emerald-500/20 animate-ping" style={{ animationDuration: '2s' }} />
            <span className="relative flex h-6 w-6 items-center justify-center rounded-full bg-emerald-500/20 border border-emerald-500/40">
              <Activity className="h-3.5 w-3.5 text-emerald-400" />
            </span>
          </div>
          <div>
            <h1 className="text-base font-bold text-slate-100 tracking-wide">
              Camera &amp; Weighing Scale Monitor
            </h1>
            <p className="text-[10px] text-slate-500 tracking-widest uppercase">Live Surveillance &amp; Weight Feed</p>
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

      {/* ── Main grid ── */}
      <div className="flex-1 grid p-4 gap-4 min-h-0" style={{ gridTemplateColumns: '1fr 1fr 280px' }}>

        {/* Camera 1 — Front View */}
        <CameraPanel
          cameraId="front"
          label="Front View"
          subtitle="Camera 1 · Entry"
        />

        {/* Camera 2 — Top View */}
        <CameraPanel
          cameraId="top"
          label="Top View"
          subtitle="Camera 2 · Overhead"
        />

        {/* Weight panel */}
        <WeightPanel />
      </div>

      {/* ── Bottom status bar ── */}
      <div className="shrink-0 flex items-center justify-between px-6 py-2 bg-slate-900/60 border-t border-slate-700/40 text-[10px] text-slate-600 font-mono">
        <span>WEIGHBRIDGE MONITORING SYSTEM · v1.0</span>
        <span className="flex items-center gap-2">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
          ALL SYSTEMS OPERATIONAL
        </span>
        <span>RTSP · MJPEG STREAM · WebSocket</span>
      </div>
    </div>
  );
}
