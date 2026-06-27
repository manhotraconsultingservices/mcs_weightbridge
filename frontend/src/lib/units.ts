import api from '@/services/api';

// Admin-managed units of measure (Settings → Units). These are the fallback
// defaults used before the list loads or if the request fails.
export const DEFAULT_UNITS = ['MT', 'QUINTAL', 'KG', 'CFT', 'BRASS', 'CUM', 'PCS', 'NOS'];

/** Fetch the configured units of measure; always resolves (falls back to defaults). */
export async function fetchUnits(): Promise<string[]> {
  try {
    const r = await api.get<string[]>('/api/v1/app-settings/units');
    return Array.isArray(r.data) && r.data.length ? r.data : DEFAULT_UNITS;
  } catch {
    return DEFAULT_UNITS;
  }
}

/** Save the units list (admin only). Returns the cleaned list the server stored. */
export async function saveUnits(units: string[]): Promise<string[]> {
  const r = await api.put<string[]>('/api/v1/app-settings/units', units);
  return Array.isArray(r.data) ? r.data : units;
}

/** Ensure `unit` is present in the option list so a Select can render it even
 *  if it was removed from the managed list after an invoice used it. */
export function withUnit(units: string[], unit?: string | null): string[] {
  const u = (unit || '').trim();
  if (u && !units.some(x => x.toLowerCase() === u.toLowerCase())) return [u, ...units];
  return units;
}
