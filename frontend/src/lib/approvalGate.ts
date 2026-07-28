import { toast } from 'sonner';

/**
 * Maker-checker (4-eyes) — client-side response gate.
 *
 * When a tenant has the maker-checker control ON, the protected action
 * endpoints (write-off, bulk write-off, invoice cancel, day-book opening
 * change) do NOT execute — they PARK the request and return HTTP 202
 * `{ status: 'pending_approval', message, approval_id }`. axios treats 202 as
 * success, so each caller must check for it and stop its own success path.
 *
 * Usage:
 *   const res = await api.post(...);
 *   if (wasSubmittedForApproval(res)) return;   // parked — a 2nd admin approves
 *   ...normal success handling...
 *
 * When maker-checker is OFF (default for every tenant) the endpoints return
 * 200 as before, so this is a no-op.
 */
export function wasSubmittedForApproval(
  res: { status?: number; data?: unknown } | undefined | null,
): boolean {
  const data = res?.data as { status?: string; message?: string } | undefined;
  if (res?.status === 202 && data?.status === 'pending_approval') {
    toast.info('Submitted for approval', {
      description: data.message || 'A second admin must approve this before it takes effect.',
    });
    return true;
  }
  return false;
}
