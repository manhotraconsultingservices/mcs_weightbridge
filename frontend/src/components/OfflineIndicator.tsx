import { useCallback, useEffect, useRef, useState } from 'react';
import { CloudOff, RefreshCw, AlertTriangle } from 'lucide-react';
import { subscribe, flushQueue, type QueueStats } from '@/lib/offlineQueue';

/**
 * Header pill for connectivity + offline-queue state.
 *
 * Reachability is probed against the health endpoint rather than trusting
 * navigator.onLine. navigator.onLine only reports whether a network interface
 * is up — on a rural weighbridge behind a 4G dongle the interface stays up
 * while the uplink is dead, so it reports "online" through the entire outage
 * and the operator gets no warning at all.
 */
const HEALTH_URL = '/api/v1/health';
const PROBE_OK_MS = 15_000;   // steady-state re-check
const PROBE_DOWN_MS = 5_000;  // probe harder while down, to resume quickly
const PROBE_TIMEOUT_MS = 4_000;

async function probeReachable(): Promise<boolean> {
  if (!navigator.onLine) return false;   // cheap negative; never a positive
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), PROBE_TIMEOUT_MS);
  try {
    const res = await fetch(HEALTH_URL, { method: 'GET', cache: 'no-store', signal: ctl.signal });
    return res.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(t);
  }
}

export default function OfflineIndicator() {
  const [reachable, setReachable] = useState(true);
  const [stats, setStats] = useState<QueueStats>({ total: 0, pending: 0, needsReview: 0, needsAuth: 0 });
  const reachableRef = useRef(true);

  const runProbe = useCallback(async () => {
    const ok = await probeReachable();
    const was = reachableRef.current;
    reachableRef.current = ok;
    setReachable(ok);
    // Recovered: drain immediately. The 'online' event does NOT fire here when
    // the interface never went down (dead-uplink case), so this is the only
    // prompt trigger we get.
    if (ok && !was) void flushQueue();
  }, []);

  useEffect(() => {
    const unsub = subscribe(setStats);
    void runProbe();

    let timer: ReturnType<typeof setTimeout>;
    const schedule = () => {
      timer = setTimeout(async () => {
        await runProbe();
        schedule();
      }, reachableRef.current ? PROBE_OK_MS : PROBE_DOWN_MS);
    };
    schedule();

    const onOnline = () => { void runProbe(); };
    const onOffline = () => { reachableRef.current = false; setReachable(false); };
    window.addEventListener('online', onOnline);
    window.addEventListener('offline', onOffline);

    return () => {
      clearTimeout(timer);
      window.removeEventListener('online', onOnline);
      window.removeEventListener('offline', onOffline);
      unsub();
    };
  }, [runProbe]);

  // Items the server refused are never auto-discarded, so they must stay
  // visible until a human deals with them — highest priority.
  if (stats.needsReview > 0) {
    return (
      <span
        className="inline-flex items-center gap-1 rounded-full bg-red-100 text-red-800 px-2.5 py-1 text-xs font-medium"
        title={`${stats.needsReview} saved weighment(s) were refused by the server and need attention. They have NOT been discarded.`}
      >
        <AlertTriangle className="h-3.5 w-3.5" /> {stats.needsReview} need attention
      </span>
    );
  }

  if (!reachable) {
    return (
      <span
        className="inline-flex items-center gap-1 rounded-full bg-amber-100 text-amber-800 px-2.5 py-1 text-xs font-medium"
        title="No connection to the server — new tokens are saved offline and will sync automatically"
      >
        <CloudOff className="h-3.5 w-3.5" /> Offline{stats.total > 0 ? ` · ${stats.total} queued` : ''}
      </span>
    );
  }

  if (stats.total === 0) return null;

  return (
    <button
      onClick={() => void flushQueue()}
      title="Click to sync now"
      className="inline-flex items-center gap-1 rounded-full bg-blue-100 text-blue-800 px-2.5 py-1 text-xs font-medium hover:bg-blue-200"
    >
      <RefreshCw className="h-3.5 w-3.5" /> {stats.total} pending sync
    </button>
  );
}
