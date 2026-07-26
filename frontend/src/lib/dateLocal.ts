// Local (wall-clock) ISO date helpers — fix the toISOString() UTC bug.
//
// `new Date().toISOString().split('T')[0]` returns the UTC calendar day, which in
// IST (+5:30) is the PREVIOUS day between 00:00 and 05:30 IST, and makes
// `new Date(y, m, 1).toISOString()` land on the prior month's last day. These
// helpers build the YYYY-MM-DD string from the browser's LOCAL date parts instead,
// so "today"/"this month"/date presets match the user's wall clock.

/** YYYY-MM-DD for a Date using its LOCAL parts (default: now). */
export function localISO(d: Date = new Date()): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

/** Today (local wall clock) as YYYY-MM-DD. */
export function todayISO(): string {
  return localISO(new Date());
}

/** `n` days from today (local), YYYY-MM-DD. Negative = past. */
export function shiftISO(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() + n);
  return localISO(d);
}

/** First day of the current month (local), YYYY-MM-DD. */
export function monthStartISO(): string {
  const d = new Date();
  return localISO(new Date(d.getFullYear(), d.getMonth(), 1));
}
