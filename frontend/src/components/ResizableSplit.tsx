/**
 * Reusable two-pane split with a draggable divider.
 *
 *   <ResizableSplit direction="horizontal" defaultSize={30} minSize={15} maxSize={70} storageKey="tokens.formWidth">
 *     <LeftPane />
 *     <RightPane />
 *   </ResizableSplit>
 *
 *   • `direction="horizontal"` — left/right split (drag horizontally)
 *   • `direction="vertical"`   — top/bottom split (drag vertically)
 *   • `defaultSize` is the *first* pane size in percent (0-100)
 *   • Size persists to localStorage under `storageKey`
 *
 * Built on the parent's `display: flex` + a width or height of `${size}%` on the
 * first pane, `flex: 1` on the second. No external dependencies.
 */
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';

interface ResizableSplitProps {
  direction: 'horizontal' | 'vertical';
  defaultSize?: number;            // 0-100, default 50
  minSize?: number;                // 0-100, default 10
  maxSize?: number;                // 0-100, default 90
  storageKey?: string;             // localStorage key for persistence
  className?: string;
  children: [ReactNode, ReactNode];
}

export default function ResizableSplit({
  direction,
  defaultSize = 50,
  minSize = 10,
  maxSize = 90,
  storageKey,
  className,
  children,
}: ResizableSplitProps) {
  const [size, setSize] = useState<number>(() => {
    if (storageKey && typeof window !== 'undefined') {
      const stored = window.localStorage.getItem(storageKey);
      const n = stored ? parseFloat(stored) : NaN;
      if (Number.isFinite(n) && n >= minSize && n <= maxSize) return n;
    }
    return defaultSize;
  });
  const containerRef = useRef<HTMLDivElement | null>(null);
  const draggingRef = useRef(false);
  const [isDragging, setIsDragging] = useState(false);

  // Persist size
  useEffect(() => {
    if (storageKey) window.localStorage.setItem(storageKey, String(size));
  }, [size, storageKey]);

  // Pointer move handler — measures container & updates size in %
  const onPointerMove = useCallback(
    (e: PointerEvent) => {
      if (!draggingRef.current || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const pct =
        direction === 'horizontal'
          ? ((e.clientX - rect.left) / rect.width) * 100
          : ((e.clientY - rect.top) / rect.height) * 100;
      const clamped = Math.max(minSize, Math.min(maxSize, pct));
      setSize(clamped);
    },
    [direction, minSize, maxSize],
  );

  const onPointerUp = useCallback(() => {
    draggingRef.current = false;
    setIsDragging(false);
    document.body.style.userSelect = '';
    document.body.style.cursor = '';
    window.removeEventListener('pointermove', onPointerMove);
    window.removeEventListener('pointerup', onPointerUp);
  }, [onPointerMove]);

  const onPointerDown = useCallback(
    (e: React.PointerEvent) => {
      e.preventDefault();
      draggingRef.current = true;
      setIsDragging(true);
      document.body.style.userSelect = 'none';
      document.body.style.cursor = direction === 'horizontal' ? 'col-resize' : 'row-resize';
      window.addEventListener('pointermove', onPointerMove);
      window.addEventListener('pointerup', onPointerUp);
    },
    [direction, onPointerMove, onPointerUp],
  );

  // Double-click resets to default
  const onDoubleClick = useCallback(() => {
    setSize(defaultSize);
  }, [defaultSize]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      window.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('pointerup', onPointerUp);
      document.body.style.userSelect = '';
      document.body.style.cursor = '';
    };
  }, [onPointerMove, onPointerUp]);

  const containerCls =
    direction === 'horizontal'
      ? 'flex flex-row h-full w-full overflow-hidden'
      : 'flex flex-col h-full w-full overflow-hidden';

  const firstStyle: React.CSSProperties =
    direction === 'horizontal'
      ? { width: `${size}%`, minWidth: 0, height: '100%' }
      : { height: `${size}%`, minHeight: 0, width: '100%' };

  // Divider — wider hit-zone (8px) but visually thin (2px); shows accent on hover/drag
  const dividerCls =
    direction === 'horizontal'
      ? 'group relative shrink-0 w-1.5 cursor-col-resize select-none flex items-center justify-center'
      : 'group relative shrink-0 h-1.5 cursor-row-resize select-none flex items-center justify-center';

  const dividerBarCls =
    direction === 'horizontal'
      ? `h-full w-0.5 transition-colors ${
          isDragging ? 'bg-primary' : 'bg-border group-hover:bg-primary/60'
        }`
      : `w-full h-0.5 transition-colors ${
          isDragging ? 'bg-primary' : 'bg-border group-hover:bg-primary/60'
        }`;

  // Drag handle indicator (3 dots) at midpoint
  const handleCls =
    direction === 'horizontal'
      ? 'absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-3 h-8 rounded bg-muted-foreground/0 group-hover:bg-muted-foreground/15 flex flex-col items-center justify-center gap-0.5'
      : 'absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 h-3 w-8 rounded bg-muted-foreground/0 group-hover:bg-muted-foreground/15 flex flex-row items-center justify-center gap-0.5';

  const dotCls =
    direction === 'horizontal'
      ? `w-0.5 h-0.5 rounded-full transition-colors ${
          isDragging ? 'bg-primary' : 'bg-muted-foreground/40 group-hover:bg-muted-foreground/80'
        }`
      : `h-0.5 w-0.5 rounded-full transition-colors ${
          isDragging ? 'bg-primary' : 'bg-muted-foreground/40 group-hover:bg-muted-foreground/80'
        }`;

  return (
    <div ref={containerRef} className={[containerCls, className].filter(Boolean).join(' ')}>
      <div style={firstStyle} className="overflow-hidden">
        {children[0]}
      </div>
      <div
        role="separator"
        aria-orientation={direction === 'horizontal' ? 'vertical' : 'horizontal'}
        className={dividerCls}
        onPointerDown={onPointerDown}
        onDoubleClick={onDoubleClick}
        title={`Drag to resize${storageKey ? ' · double-click to reset' : ''}`}
      >
        <div className={dividerBarCls} />
        <div className={handleCls}>
          <span className={dotCls} />
          <span className={dotCls} />
          <span className={dotCls} />
        </div>
      </div>
      <div className="flex-1 min-w-0 min-h-0 overflow-hidden">{children[1]}</div>
    </div>
  );
}
