import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import type { CustomFieldDefinition } from '@/types';

interface Props {
  definitions: CustomFieldDefinition[];
  values: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
  compact?: boolean;   // smaller controls for the dense token form
}

/**
 * Renders owner-defined custom attributes (custom_field_definitions) as a set of
 * inputs, driven entirely by the definitions. Values are kept in a flat object
 * keyed by field_key. Used in the weighment form + detail dialog.
 */
export default function CustomFieldsInput({ definitions, values, onChange, compact }: Props) {
  if (!definitions.length) return null;
  const h = compact ? 'h-8 text-xs' : '';
  const lbl = compact ? 'text-xs' : '';

  return (
    <div className="space-y-2">
      {definitions.map(def => {
        const v = values[def.field_key];
        const label = (
          <Label className={lbl}>
            {def.label}{def.unit ? ` (${def.unit})` : ''}
            {def.required && <span className="text-rose-500"> *</span>}
          </Label>
        );

        if (def.field_type === 'select') {
          return (
            <div key={def.field_key} className="space-y-1">
              {label}
              <Select
                value={(v as string) || ''}
                onValueChange={val => onChange(def.field_key, val === '__none__' ? '' : val)}
              >
                <SelectTrigger className={h}><SelectValue placeholder="Select…" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">—</SelectItem>
                  {(def.options || []).map(opt => (
                    <SelectItem key={opt} value={opt}>{opt}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          );
        }

        if (def.field_type === 'boolean') {
          return (
            <label key={def.field_key} className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                className="h-4 w-4"
                checked={Boolean(v)}
                onChange={e => onChange(def.field_key, e.target.checked)}
              />
              <span className={compact ? 'text-xs' : 'text-sm'}>
                {def.label}{def.required && <span className="text-rose-500"> *</span>}
              </span>
            </label>
          );
        }

        return (
          <div key={def.field_key} className="space-y-1">
            {label}
            <Input
              className={h}
              type={def.field_type === 'number' ? 'number' : def.field_type === 'date' ? 'date' : 'text'}
              step={def.field_type === 'number' ? 'any' : undefined}
              value={(v as string | number | undefined) ?? ''}
              onChange={e => onChange(def.field_key, e.target.value)}
            />
          </div>
        );
      })}
    </div>
  );
}
