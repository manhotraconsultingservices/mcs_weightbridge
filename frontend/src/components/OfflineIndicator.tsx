import { useEffect, useState } from 'react';
import { CloudOff, RefreshCw } from 'lucide-react';
import { subscribe, flushQueue } from '@/lib/offlineQueue';

/**
 * Small header pill: shows OFFLINE when the browser is offline, and "N pending
 * sync" when queued tokens are waiting to upload. Hidden entirely when online
 * with an empty queue.
 */
export default function OfflineIndicator() {
  const [online, setOnline] = useState(navigator.onLine);
  const [pending, setPending] = useState(0);

  useEffect(() => {
    const on = () => setOnline(true);
    const off = () => setOnline(false);
    window.addEventListener('online', on);
    window.addEventListener('offline', off);
    const unsub = subscribe(setPending);
    return () => { window.removeEventListener('online', on); window.removeEventListener('offline', off); unsub(); };
  }, []);

  if (online && pending === 0) return null;

  if (!online) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 text-amber-800 px-2.5 py-1 text-xs font-medium" title="No internet — new tokens are saved offline and will sync automatically">
        <CloudOff className="h-3.5 w-3.5" /> Offline{pending > 0 ? ` · ${pending} queued` : ''}
      </span>
    );
  }
  return (
    <button onClick={() => void flushQueue()} title="Click to sync now"
      className="inline-flex items-center gap-1 rounded-full bg-blue-100 text-blue-800 px-2.5 py-1 text-xs font-medium hover:bg-blue-200">
      <RefreshCw className="h-3.5 w-3.5" /> {pending} pending sync
    </button>
  );
}
