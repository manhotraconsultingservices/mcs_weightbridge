import api from '@/services/api';

// Per-tenant tyre-class → default load volume (Settings → Tyre Volumes).
// The admin sets the default in CUM (cubic metre); the token form converts to the
// canonical CFT (× CFT_PER_CUM) for storage. These are the fallback defaults used
// before the list loads or if the request fails.
export const CFT_PER_CUM = 35.3147;

export interface TyreVolume {
  tyre: number;   // tyre count (e.g. 4, 6, 8, 10, 12)
  cum: number;    // default load volume in CUM (cubic metre)
}

export const DEFAULT_TYRE_VOLUMES: TyreVolume[] = [
  { tyre: 4, cum: 3.0 },
  { tyre: 6, cum: 7.0 },
  { tyre: 8, cum: 10.0 },
  { tyre: 10, cum: 13.0 },
  { tyre: 12, cum: 17.0 },
];

/** Fetch the configured tyre→volume (CUM) map; always resolves (falls back to defaults). */
export async function fetchTyreVolumes(): Promise<TyreVolume[]> {
  try {
    const r = await api.get<TyreVolume[]>('/api/v1/app-settings/tyre-volumes');
    if (Array.isArray(r.data) && r.data.length) {
      return r.data
        .map(x => ({ tyre: Number(x.tyre), cum: Number(x.cum) }))
        .filter(x => x.tyre > 0 && x.cum > 0)
        .sort((a, b) => a.tyre - b.tyre);
    }
  } catch { /* fall through to defaults */ }
  return DEFAULT_TYRE_VOLUMES;
}

/** Save the tyre→volume (CUM) list (admin only). Returns the cleaned list the server stored. */
export async function saveTyreVolumes(rows: TyreVolume[]): Promise<TyreVolume[]> {
  const r = await api.put<TyreVolume[]>('/api/v1/app-settings/tyre-volumes', rows);
  return Array.isArray(r.data) ? r.data : rows;
}

/** Tyre count → default volume in **CFT** (canonical storage unit). */
export function tyreCftMap(rows: TyreVolume[]): Record<number, number> {
  const m: Record<number, number> = {};
  for (const r of rows) m[r.tyre] = r.cum * CFT_PER_CUM;
  return m;
}

/** Tyre count → default volume in **CUM** (as entered by the admin). */
export function tyreCumMap(rows: TyreVolume[]): Record<number, number> {
  const m: Record<number, number> = {};
  for (const r of rows) m[r.tyre] = r.cum;
  return m;
}

/** Sorted list of tyre counts to render as options. */
export function tyreOptions(rows: TyreVolume[]): number[] {
  return rows.map(r => r.tyre).sort((a, b) => a - b);
}
