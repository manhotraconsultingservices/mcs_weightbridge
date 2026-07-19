/**
 * Last-known-good masters cache (offline resilience).
 *
 * The token form's party / product / vehicle dropdowns are fetched fresh from the
 * cloud. During an outage those fetches fail and — without this — the dropdowns
 * are EMPTY, so an operator can queue a token offline but can't actually fill in
 * who/what it's for. Caching the last successful fetch in localStorage lets the
 * form stay usable through an outage; it is refreshed on every successful load,
 * so it never goes more stale than the last time the operator was online.
 *
 * This is a plain read cache — no writes, no sync — so it's safe to keep across
 * sessions and can never corrupt anything.
 */
const PREFIX = 'wb.masters.';

export function cacheMasters<T>(key: string, data: T[]): void {
  try {
    localStorage.setItem(PREFIX + key, JSON.stringify(data ?? []));
  } catch {
    /* quota / private mode — the online path is unaffected */
  }
}

export function readCachedMasters<T>(key: string): T[] {
  try {
    const raw = localStorage.getItem(PREFIX + key);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? (parsed as T[]) : [];
  } catch {
    return [];
  }
}
