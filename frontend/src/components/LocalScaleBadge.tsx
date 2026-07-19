import { Radio } from 'lucide-react';
import { cn } from '@/lib/utils';

interface Props {
  className?: string;
  /** 'lg' for the kiosk, which is read at arm's length by the bridge operator. */
  size?: 'sm' | 'lg';
  /** Localised label; defaults to English for the desktop UI. */
  label?: string;
}

/**
 * Shown when the weight on screen is being read straight off the scale agent on
 * this PC because the cloud feed is unreachable.
 *
 * Deliberately distinct from the offline-queue pill in the header: "no internet"
 * and "no scale" call for different operator responses, and conflating them is
 * how someone ends up waiting for the wrong thing while a truck sits on the
 * bridge. This one means: the scale is fine, keep weighing, it will sync.
 */
export default function LocalScaleBadge({ className, size = 'sm', label }: Props) {
  const lg = size === 'lg';
  return (
    <span
      title="Internet is down — reading the scale directly on this PC. The weighment is saved and will sync automatically when the connection returns."
      className={cn(
        'inline-flex items-center rounded-full bg-amber-100 text-amber-800 font-semibold uppercase tracking-wide',
        lg ? 'gap-2 px-4 py-2 text-base font-bold' : 'gap-1 px-2 py-0.5 text-[10px]',
        className,
      )}
    >
      <Radio className={lg ? 'h-5 w-5' : 'h-3 w-3'} />
      {label ?? 'Local bridge'}
    </span>
  );
}
