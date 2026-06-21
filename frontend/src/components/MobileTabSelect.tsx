/**
 * MobileTabSelect — renders a styled native <select> on mobile (< sm) to replace
 * crowded tab strips. Hides automatically on sm+ via sm:hidden.
 *
 * Usage: place above a <TabsList className="hidden sm:inline-flex ..."> so mobile
 * users get an OS picker while desktop users get the full tab strip.
 */

interface MobileTabSelectProps {
  value: string;
  onValueChange: (v: string) => void;
  options: { value: string; label: string }[];
}

export function MobileTabSelect({ value, onValueChange, options }: MobileTabSelectProps) {
  return (
    <select
      value={value}
      onChange={e => onValueChange(e.target.value)}
      className="sm:hidden w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 focus:ring-offset-background"
    >
      {options.map(o => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  );
}
