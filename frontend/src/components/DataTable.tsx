/**
 * Generic, reusable data table.
 *
 * Features:
 *   • Click column header to toggle sort (asc → desc → none).
 *   • Per-column filter inputs in a hideable row below the header.
 *   • Column visibility menu (gear icon) — checkbox per column.
 *   • CSV export of the *currently filtered/sorted* view.
 *   • Persists sort, filter, and visible-column state to localStorage
 *     keyed by the `id` prop, so user preferences survive reloads.
 *
 * Usage:
 *   const columns: ColumnDef<MyRow>[] = [
 *     { key: 'date',    label: 'Date',    accessor: r => r.date,    type: 'date' },
 *     { key: 'amount',  label: 'Amount',  accessor: r => r.amount,  type: 'number', align: 'right',
 *       format: v => `₹${(v as number).toFixed(2)}` },
 *     { key: 'status',  label: 'Status',  accessor: r => r.status,  type: 'enum',
 *       enumOptions: ['draft', 'final', 'cancelled'] },
 *   ];
 *   <DataTable id="invoices.main" columns={columns} data={rows} rowKey={r => r.id} />
 */
import { useEffect, useLayoutEffect, useMemo, useState, useRef, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { ArrowUpDown, ArrowUp, ArrowDown, Settings2, Download, Filter, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

// ─── Public types ─────────────────────────────────────────────────────────────

export interface ColumnDef<T> {
  /** Unique key (used as localStorage suffix + column identifier). */
  key: string;
  /** Header text. */
  label: string;
  /** Pull the raw value from a row (used for sort + filter + CSV). */
  accessor: (row: T) => unknown;
  /** Custom React renderer; defaults to the accessor value as-is. */
  format?: (value: unknown, row: T) => ReactNode;
  /** Override CSV export value (defaults to accessor). */
  exportValue?: (row: T) => string | number;
  /** Sort/filter behaviour. `enum` uses a dropdown filter. Default: 'string'. */
  type?: 'string' | 'number' | 'date' | 'enum';
  /** For `type: 'enum'` — the options shown in the filter dropdown. */
  enumOptions?: string[];
  /** Text alignment of the cell content. */
  align?: 'left' | 'right' | 'center';
  /** Show this column by default? Default true. */
  defaultVisible?: boolean;
  /** Disable sort for this column. */
  sortable?: boolean;
  /** Disable filter for this column. */
  filterable?: boolean;
  /** Optional Tailwind class for the body cell. */
  className?: string;
  /** Hide this column entirely from the picker (e.g. action columns). */
  alwaysVisible?: boolean;
}

export interface DataTableProps<T> {
  /** Stable identifier — used as the localStorage namespace. */
  id: string;
  columns: ColumnDef<T>[];
  data: T[];
  loading?: boolean;
  /** Stable React key per row. Defaults to JSON.stringify(row). */
  rowKey?: (row: T, idx: number) => string;
  /** Initial sort. */
  defaultSort?: { key: string; direction: 'asc' | 'desc' };
  emptyMessage?: string;
  /** Last column rendering — typically action buttons (edit, delete, etc.). */
  rowActions?: (row: T) => ReactNode;
  /** Override the CSV filename (without extension). */
  exportFilename?: string;
  /** Optional custom toolbar items rendered to the left of gear/export. */
  toolbarLeft?: ReactNode;
  /** Hide the export button entirely. */
  hideExport?: boolean;
  /** Tailwind class merged into the outer container. */
  className?: string;
  /** Initial column-filter dictionary. Used for caller-driven filtering. */
  initialFilters?: Record<string, string>;
}

// ─── Internal helpers ─────────────────────────────────────────────────────────

type SortState = { key: string; direction: 'asc' | 'desc' } | null;
type FilterState = Record<string, string>;

function lsKey(id: string, suffix: string) {
  return `dt.${id}.${suffix}`;
}

function readLS<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw != null ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function writeLS(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // localStorage full or disabled — fail silently
  }
}

function compareValues(a: unknown, b: unknown, type: ColumnDef<unknown>['type']): number {
  // null/undefined sort to the end
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  if (type === 'number') {
    const an = Number(a);
    const bn = Number(b);
    if (Number.isNaN(an) && Number.isNaN(bn)) return 0;
    if (Number.isNaN(an)) return 1;
    if (Number.isNaN(bn)) return -1;
    return an - bn;
  }
  if (type === 'date') {
    const at = new Date(String(a)).getTime();
    const bt = new Date(String(b)).getTime();
    if (Number.isNaN(at) && Number.isNaN(bt)) return 0;
    if (Number.isNaN(at)) return 1;
    if (Number.isNaN(bt)) return -1;
    return at - bt;
  }
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: 'base' });
}

function matchFilter(rawValue: unknown, filter: string, type: ColumnDef<unknown>['type']): boolean {
  if (!filter) return true;
  const v = rawValue == null ? '' : String(rawValue);
  if (type === 'enum') {
    return v.toLowerCase() === filter.toLowerCase();
  }
  if (type === 'number') {
    // Support `>10`, `<5`, `10-20`, or plain substring
    const f = filter.trim();
    if (f.startsWith('>=')) return Number(v) >= Number(f.slice(2));
    if (f.startsWith('<=')) return Number(v) <= Number(f.slice(2));
    if (f.startsWith('>')) return Number(v) > Number(f.slice(1));
    if (f.startsWith('<')) return Number(v) < Number(f.slice(1));
    if (/^\d+\s*-\s*\d+$/.test(f)) {
      const [lo, hi] = f.split('-').map(s => Number(s.trim()));
      const n = Number(v);
      return n >= lo && n <= hi;
    }
    return v.includes(f);
  }
  return v.toLowerCase().includes(filter.toLowerCase());
}

export function escapeCsvCell(v: string | number | null | undefined): string {
  if (v == null) return '';
  const s = String(v);
  // Quote if it contains comma, quote, or newline
  if (/[",\n]/.test(s)) {
    return `"${s.replace(/"/g, '""')}"`;
  }
  return s;
}

export function downloadCsv(filename: string, rows: string[][]) {
  const csv = rows.map(r => r.map(escapeCsvCell).join(',')).join('\n');
  const blob = new Blob(['﻿', csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${filename}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

// ─── Component ────────────────────────────────────────────────────────────────

export function DataTable<T>({
  id, columns, data = [], loading,
  rowKey, defaultSort, emptyMessage, rowActions,
  exportFilename, toolbarLeft, hideExport, className,
  initialFilters,
}: DataTableProps<T>) {
  // Never crash on an undefined/non-array `data` (e.g. an unexpected API shape).
  if (!Array.isArray(data)) data = [];
  // Load persisted state on first render
  const initialSort = useMemo<SortState>(
    () => readLS<SortState>(lsKey(id, 'sort'), defaultSort ?? null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [id],
  );
  const initialFilterState = useMemo<FilterState>(
    () => readLS<FilterState>(lsKey(id, 'filters'), initialFilters ?? {}),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [id],
  );
  const initialVisibleKeys = useMemo<string[]>(
    () => readLS<string[]>(
      lsKey(id, 'visible'),
      columns.filter(c => c.defaultVisible !== false).map(c => c.key),
    ),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [id],
  );

  const [sort, setSort] = useState<SortState>(initialSort);
  const [filters, setFilters] = useState<FilterState>(initialFilterState);
  const [visibleKeys, setVisibleKeys] = useState<string[]>(initialVisibleKeys);
  const [showFilters, setShowFilters] = useState<boolean>(
    Object.values(initialFilterState).some(v => v),
  );

  // Persist state changes
  useEffect(() => { writeLS(lsKey(id, 'sort'), sort); }, [id, sort]);
  useEffect(() => { writeLS(lsKey(id, 'filters'), filters); }, [id, filters]);
  useEffect(() => { writeLS(lsKey(id, 'visible'), visibleKeys); }, [id, visibleKeys]);

  const colByKey = useMemo(() => {
    const m: Record<string, ColumnDef<T>> = {};
    columns.forEach(c => { m[c.key] = c; });
    return m;
  }, [columns]);

  // Apply filters
  const filtered = useMemo(() => {
    const activeFilters = Object.entries(filters).filter(([, v]) => v);
    if (activeFilters.length === 0) return data;
    return data.filter(row =>
      activeFilters.every(([key, val]) => {
        const col = colByKey[key];
        if (!col || col.filterable === false) return true;
        const raw = col.accessor(row);
        return matchFilter(raw, val, col.type);
      }),
    );
  }, [data, filters, colByKey]);

  // Apply sort
  const sorted = useMemo(() => {
    if (!sort) return filtered;
    const col = colByKey[sort.key];
    if (!col) return filtered;
    const dir = sort.direction === 'asc' ? 1 : -1;
    return [...filtered].sort((a, b) => dir * compareValues(col.accessor(a), col.accessor(b), col.type));
  }, [filtered, sort, colByKey]);

  // Visible columns in declared order
  const visibleColumns = useMemo(
    () => columns.filter(c => c.alwaysVisible || visibleKeys.includes(c.key)),
    [columns, visibleKeys],
  );

  function toggleSort(key: string) {
    const col = colByKey[key];
    if (!col || col.sortable === false) return;
    setSort(prev => {
      if (!prev || prev.key !== key) return { key, direction: 'asc' };
      if (prev.direction === 'asc') return { key, direction: 'desc' };
      return null;   // third click clears sort
    });
  }

  function setFilter(key: string, value: string) {
    setFilters(prev => {
      const next = { ...prev };
      if (value) next[key] = value;
      else delete next[key];
      return next;
    });
  }

  function clearAllFilters() {
    setFilters({});
  }

  function toggleColumn(key: string) {
    setVisibleKeys(prev =>
      prev.includes(key) ? prev.filter(k => k !== key) : [...prev, key],
    );
  }

  function resetColumns() {
    setVisibleKeys(columns.filter(c => c.defaultVisible !== false).map(c => c.key));
  }

  function handleExport() {
    const headers = visibleColumns.map(c => c.label);
    const rows = sorted.map(row =>
      visibleColumns.map(c => {
        if (c.exportValue) return String(c.exportValue(row));
        const raw = c.accessor(row);
        if (raw == null) return '';
        return String(raw);
      }),
    );
    const fname = `${exportFilename ?? id}-${new Date().toISOString().slice(0, 10)}`;
    downloadCsv(fname, [headers, ...rows]);
  }

  const activeFilterCount = Object.values(filters).filter(v => v).length;
  const ariaSortFor = (key: string): 'ascending' | 'descending' | 'none' => {
    if (!sort || sort.key !== key) return 'none';
    return sort.direction === 'asc' ? 'ascending' : 'descending';
  };

  return (
    <div className={`flex flex-col gap-2 ${className ?? ''}`}>
      {/* Toolbar */}
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-2">
          {toolbarLeft}
          <Button
            type="button"
            size="sm"
            variant={showFilters ? 'default' : 'outline'}
            onClick={() => setShowFilters(s => !s)}
          >
            <Filter className="mr-1 h-3.5 w-3.5" />
            {showFilters ? 'Hide Filters' : 'Filters'}
            {activeFilterCount > 0 && (
              <span className="ml-1.5 rounded-full bg-primary px-1.5 text-[10px] font-bold text-primary-foreground">
                {activeFilterCount}
              </span>
            )}
          </Button>
          {activeFilterCount > 0 && (
            <Button type="button" size="sm" variant="ghost" onClick={clearAllFilters}>
              <X className="mr-1 h-3.5 w-3.5" /> Clear filters
            </Button>
          )}
        </div>
        <div className="flex items-center gap-1">
          <span className="text-xs text-muted-foreground mr-1">
            {sorted.length === data.length
              ? `${data.length} row${data.length === 1 ? '' : 's'}`
              : `${sorted.length} of ${data.length}`}
          </span>
          <ColumnVisibilityMenu
            columns={columns}
            visibleKeys={visibleKeys}
            onToggle={toggleColumn}
            onReset={resetColumns}
          />
          {!hideExport && (
            <Button type="button" size="sm" variant="outline" onClick={handleExport}
                    disabled={sorted.length === 0}>
              <Download className="mr-1 h-3.5 w-3.5" /> CSV
            </Button>
          )}
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto rounded-lg border bg-card">
        <table className="w-full min-w-max text-sm">
          <thead>
            <tr className="border-b bg-muted/50">
              {visibleColumns.map((c, ci) => {
                const sorted_ = sort?.key === c.key;
                return (
                  <th
                    key={c.key}
                    aria-sort={ariaSortFor(c.key)}
                    onClick={() => c.sortable !== false && toggleSort(c.key)}
                    className={`p-2 font-medium whitespace-nowrap text-${c.align ?? 'left'} ${
                      c.sortable !== false ? 'cursor-pointer select-none hover:bg-muted/80' : ''
                    } ${ci === 0 ? 'sticky left-0 z-10 bg-muted/50' : ''}`}
                  >
                    <span className="inline-flex items-center gap-1">
                      {c.label}
                      {c.sortable !== false && (
                        sorted_ ? (
                          sort?.direction === 'asc'
                            ? <ArrowUp className="h-3 w-3 text-foreground" />
                            : <ArrowDown className="h-3 w-3 text-foreground" />
                        ) : (
                          <ArrowUpDown className="h-3 w-3 text-muted-foreground/50" />
                        )
                      )}
                    </span>
                  </th>
                );
              })}
              {rowActions && <th className="p-2 w-12" />}
            </tr>
            {showFilters && (
              <tr className="border-b bg-muted/20">
                {visibleColumns.map(c => (
                  <th key={c.key} className="p-1">
                    {c.filterable === false ? null : c.type === 'enum' ? (
                      <select
                        className="h-7 text-xs px-1 rounded border bg-background w-full"
                        value={filters[c.key] ?? ''}
                        onChange={e => setFilter(c.key, e.target.value)}
                      >
                        <option value="">All</option>
                        {(c.enumOptions ?? []).map(o => (
                          <option key={o} value={o}>{o}</option>
                        ))}
                      </select>
                    ) : c.type === 'date' ? (
                      <Input
                        type="date"
                        className="h-7 text-xs px-2"
                        value={filters[c.key] ?? ''}
                        onChange={e => setFilter(c.key, e.target.value)}
                      />
                    ) : (
                      <Input
                        className="h-7 text-xs px-2"
                        placeholder={c.type === 'number' ? '> 100, 10-20…' : 'Filter…'}
                        value={filters[c.key] ?? ''}
                        onChange={e => setFilter(c.key, e.target.value)}
                      />
                    )}
                  </th>
                ))}
                {rowActions && <th className="p-1" />}
              </tr>
            )}
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={visibleColumns.length + (rowActions ? 1 : 0)} className="text-center p-8 text-muted-foreground">
                  Loading…
                </td>
              </tr>
            ) : sorted.length === 0 ? (
              <tr>
                <td colSpan={visibleColumns.length + (rowActions ? 1 : 0)} className="text-center p-8 text-muted-foreground">
                  {emptyMessage ?? (activeFilterCount > 0 ? 'No rows match your filters.' : 'No data.')}
                </td>
              </tr>
            ) : (
              sorted.map((row, idx) => (
                <tr key={rowKey ? rowKey(row, idx) : idx} className="border-b hover:bg-muted/20 transition-colors">
                  {visibleColumns.map((c, ci) => {
                    const v = c.accessor(row);
                    return (
                      <td key={c.key} className={`p-2 whitespace-nowrap text-${c.align ?? 'left'} ${c.className ?? ''} ${ci === 0 ? 'sticky left-0 z-10 bg-card' : ''}`}>
                        {c.format ? c.format(v, row) : (v == null || v === '' ? '—' : String(v))}
                      </td>
                    );
                  })}
                  {rowActions && (
                    <td className="p-2 text-right whitespace-nowrap">
                      {rowActions(row)}
                    </td>
                  )}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── Column visibility popover (kept private) ─────────────────────────────────

function ColumnVisibilityMenu<T>({
  columns, visibleKeys, onToggle, onReset,
}: {
  columns: ColumnDef<T>[];
  visibleKeys: string[];
  onToggle: (key: string) => void;
  onReset: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const anchorRef = useRef<HTMLSpanElement>(null);   // measured button wrapper
  const menuRef = useRef<HTMLDivElement>(null);      // portaled menu (for click-outside)
  const MENU_W = 256;                                 // w-64

  // Position the PORTALED menu under the button, right-aligned + clamped on-screen.
  // Rendered to document.body so no ancestor overflow (the table's horizontal-scroll
  // wrapper, hub tabs, cards) can clip it — the previous absolute menu got cut off.
  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const b = anchorRef.current?.getBoundingClientRect();
      if (!b) return;
      const left = Math.max(8, Math.min(b.right - MENU_W, window.innerWidth - MENU_W - 8));
      setPos({ top: b.bottom + 4, left });
    };
    place();
    window.addEventListener('scroll', place, true);   // capture: follow scroll in any ancestor
    window.addEventListener('resize', place);
    return () => {
      window.removeEventListener('scroll', place, true);
      window.removeEventListener('resize', place);
    };
  }, [open]);

  // Close on click-outside (button OR portaled menu) + Escape
  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      const t = e.target as Node;
      if (anchorRef.current?.contains(t) || menuRef.current?.contains(t)) return;
      setOpen(false);
    }
    function onKey(e: KeyboardEvent) { if (e.key === 'Escape') setOpen(false); }
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  // Hide alwaysVisible columns from the menu — operator can't toggle them
  const togglable = columns.filter(c => !c.alwaysVisible);

  return (
    <span ref={anchorRef} className="inline-flex">
      <Button type="button" size="sm" variant="outline" onClick={() => setOpen(o => !o)}>
        <Settings2 className="mr-1 h-3.5 w-3.5" /> Columns
      </Button>
      {open && pos && createPortal(
        <div
          ref={menuRef}
          style={{ position: 'fixed', top: pos.top, left: pos.left, width: MENU_W }}
          className="z-[100] rounded-md border bg-popover p-2 shadow-md"
        >
          <div className="flex items-center justify-between mb-2">
            <p className="text-xs font-medium text-muted-foreground">Show columns</p>
            <Button type="button" size="sm" variant="ghost" className="h-6 text-[11px] px-1.5"
                    onClick={onReset}>
              Reset
            </Button>
          </div>
          <div className="max-h-72 overflow-y-auto space-y-1">
            {togglable.map(c => {
              const checked = visibleKeys.includes(c.key);
              return (
                <label key={c.key}
                       className="flex items-center gap-2 rounded px-2 py-1 text-xs hover:bg-muted cursor-pointer">
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => onToggle(c.key)}
                    className="h-3.5 w-3.5"
                  />
                  <span className="flex-1">{c.label}</span>
                </label>
              );
            })}
          </div>
        </div>,
        document.body,
      )}
    </span>
  );
}
