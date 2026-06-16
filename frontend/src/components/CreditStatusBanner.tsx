import { useEffect, useState } from 'react';
import api from '@/services/api';
import { AlertTriangle, AlertCircle, Clock } from 'lucide-react';

/**
 * Advisory credit-exposure banner. WARN-ONLY by product decision — it never
 * blocks an action; it just surfaces over-limit / overdue / near-limit state
 * for the selected party. Renders nothing when there's no party, while loading,
 * on error, or when the party is in good standing (status === 'ok').
 *
 * Drop it anywhere a party is chosen:  <CreditStatusBanner partyId={form.party_id} />
 */
export interface CreditStatus {
  party_id: string;
  party_name: string;
  credit_limit: number;
  unlimited: boolean;
  outstanding: number;
  available_credit: number | null;
  overdue_amount: number;
  overdue_days: number;
  payment_terms_days: number;
  status: 'ok' | 'near_limit' | 'overdue' | 'over_limit';
  message: string | null;
}

const STYLES: Record<string, { bg: string; border: string; text: string; Icon: typeof AlertTriangle }> = {
  over_limit: { bg: 'bg-red-50',    border: 'border-red-300',    text: 'text-red-800',    Icon: AlertCircle },
  overdue:    { bg: 'bg-amber-50',  border: 'border-amber-300',  text: 'text-amber-900',  Icon: Clock },
  near_limit: { bg: 'bg-yellow-50', border: 'border-yellow-300', text: 'text-yellow-800', Icon: AlertTriangle },
};

const INR = (v: number) => '₹' + Number(v ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 0 });

export function CreditStatusBanner({ partyId, className = '' }: { partyId?: string | null; className?: string }) {
  const [cs, setCs] = useState<CreditStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (!partyId) { setCs(null); return; }
    api.get(`/api/v1/parties/${partyId}/credit-status`)
      .then(r => { if (!cancelled) setCs(r.data); })
      .catch(() => { if (!cancelled) setCs(null); });
    return () => { cancelled = true; };
  }, [partyId]);

  if (!cs || cs.status === 'ok' || !cs.message) return null;
  const s = STYLES[cs.status] ?? STYLES.near_limit;
  const Icon = s.Icon;

  return (
    <div className={`flex items-start gap-2 rounded-md border px-3 py-2 text-xs ${s.bg} ${s.border} ${s.text} ${className}`}>
      <Icon className="h-4 w-4 mt-0.5 shrink-0" />
      <div className="min-w-0">
        <p className="font-semibold">{cs.message}</p>
        <p className="opacity-80">
          Outstanding {INR(cs.outstanding)}
          {!cs.unlimited && <> · Limit {INR(cs.credit_limit)}</>}
          {cs.overdue_amount > 0 && <> · Overdue {INR(cs.overdue_amount)}</>}
        </p>
      </div>
    </div>
  );
}

export default CreditStatusBanner;
