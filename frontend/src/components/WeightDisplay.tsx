import { useWeight } from '@/hooks/useWeight';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

interface WeightDisplayProps {
  onCapture?: (weight: number) => void;
  className?: string;
}

export default function WeightDisplay({ onCapture, className }: WeightDisplayProps) {
  const { reading, formatted } = useWeight();

  return (
    <div className={cn('rounded-xl border-2 bg-card p-4 text-center', className,
      reading.is_stable ? 'border-green-500' : 'border-muted'
    )}>
      <div className="mb-1 flex items-center justify-center gap-2">
        <span className="text-xs font-medium text-muted-foreground uppercase tracking-widest">Live Weight</span>
        {reading.scale_connected ? (
          <Badge variant="outline" className="border-green-500 text-green-600 text-[10px]">CONNECTED</Badge>
        ) : (
          <Badge variant="outline" className="border-red-400 text-red-500 text-[10px]">OFFLINE</Badge>
        )}
      </div>

      <div className={cn(
        'font-mono text-4xl font-bold tabular-nums transition-colors',
        reading.is_stable ? 'text-green-600' : 'text-foreground'
      )}>
        {reading.scale_connected ? formatted : '—'}
      </div>

      <div className="mt-1 h-4">
        {reading.scale_connected && (
          reading.is_stable ? (
            <p className="text-xs text-green-600 font-medium">
              Stable for {reading.stable_duration_sec.toFixed(1)}s
            </p>
          ) : (
            <p className="text-xs text-muted-foreground animate-pulse">Stabilising…</p>
          )
        )}
      </div>

      {onCapture && (
        <button
          onClick={() => onCapture(reading.weight_kg)}
          disabled={!reading.scale_connected || !reading.is_stable}
          className={cn(
            'mt-3 w-full rounded-md px-4 py-2 text-sm font-semibold transition-colors',
            reading.is_stable && reading.scale_connected
              ? 'bg-green-600 text-white hover:bg-green-700 cursor-pointer'
              : 'bg-muted text-muted-foreground cursor-not-allowed'
          )}
        >
          {reading.is_stable ? 'Capture Weight' : 'Waiting for stability…'}
        </button>
      )}
    </div>
  );
}
