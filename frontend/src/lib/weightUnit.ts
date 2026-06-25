import { getTenantIndustry } from '@/hooks/useAuth';

// The DB ALWAYS stores weights in kilograms. The *display* unit is per-tenant:
// maize/grain traders weigh in quintals (1 Qtl = 100 kg); everyone else in
// metric tonnes (1 MT = 1000 kg). Driven by the tenant industry so it needs no
// extra config — set the tenant's industry to maize_trader and the whole
// weighbridge UI switches to quintals.

export interface WeightUnitInfo {
  code: 'MT' | 'QUINTAL';
  label: string;   // short label shown next to numbers
  perKg: number;   // how many kg in one display unit
}

export function weightUnit(): WeightUnitInfo {
  return getTenantIndustry() === 'maize_trader'
    ? { code: 'QUINTAL', label: 'Qtl', perKg: 100 }
    : { code: 'MT', label: 'MT', perKg: 1000 };
}

export function weightUnitLabel(): string {
  return weightUnit().label;
}

/** kg → display string, e.g. "9.500 Qtl" / "12.5000 MT". `dp` decimals; pass
 *  withUnit=false for the bare number. Null/undefined → "—". */
export function fmtKg(
  kg: number | string | null | undefined,
  dp = 3,
  withUnit = true,
): string {
  if (kg == null || kg === '') return '—';
  const u = weightUnit();
  const s = (Number(kg) / u.perKg).toLocaleString('en-IN', {
    minimumFractionDigits: dp,
    maximumFractionDigits: dp,
  });
  return withUnit ? `${s} ${u.label}` : s;
}

/** Operator-typed display value (MT/Qtl) → kg, for the API boundary. */
export function displayToKg(v: number | string): number {
  return (Number(v) || 0) * weightUnit().perKg;
}
