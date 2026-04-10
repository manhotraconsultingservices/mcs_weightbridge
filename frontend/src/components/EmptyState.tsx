import type { ElementType } from 'react';

interface EmptyStateProps {
  icon: ElementType;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}

/**
 * Reusable empty-state block for tables and lists.
 * Shows a large muted icon, heading, optional description, and optional action button.
 *
 * Usage:
 *   <EmptyState
 *     icon={FileText}
 *     title="No invoices yet"
 *     description="Create your first invoice to get started."
 *     action={<Button size="sm" onClick={...}>New Invoice</Button>}
 *   />
 */
export function EmptyState({ icon: Icon, title, description, action, className = '' }: EmptyStateProps) {
  return (
    <div className={`flex flex-col items-center justify-center py-16 px-4 text-center ${className}`}>
      {/* Illustration circle */}
      <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-muted">
        <Icon className="h-8 w-8 text-muted-foreground/40" />
      </div>
      <h3 className="text-sm font-semibold text-foreground">{title}</h3>
      {description && (
        <p className="mt-1 max-w-xs text-xs text-muted-foreground">{description}</p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
