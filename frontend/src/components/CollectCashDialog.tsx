import { useCallback, useEffect, useState } from 'react';
import { Loader2, CreditCard, CheckCircle2 } from 'lucide-react';
import { toast } from 'sonner';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import api from '@/services/api';
import type { Token } from '@/types';

const INR = (v: number | string | null | undefined) =>
  '₹' + Number(v ?? 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/**
 * Compact "collect cash + finalise the bill" dialog, usable straight from the
 * token list. The operator is collecting the cash, so they confirm the qty/rate,
 * finalise the draft invoice (assigns the bill number) and record the cash
 * receipt in ONE step — POST /tokens/{id}/collect-cash. Works for any role the
 * backend allows (operators included; the endpoint has no role guard).
 */
export function CollectCashDialog({
  tokenId, onClose, onDone,
}: { tokenId: string | null; onClose: () => void; onDone: () => void }) {
  const open = !!tokenId;
  const [loading, setLoading] = useState(false);
  const [token, setToken] = useState<Token | null>(null);
  const [qty, setQty] = useState('');
  const [rate, setRate] = useState('');
  const [unit, setUnit] = useState('');
  const [collecting, setCollecting] = useState(false);

  const load = useCallback(() => {
    if (!tokenId) { setToken(null); return; }
    setLoading(true);
    api.get<Token>(`/api/v1/tokens/${tokenId}`)
      .then(async r => {
        setToken(r.data);
        const inv = r.data.linked_invoice;
        if (inv?.id && inv.status === 'draft') {
          try {
            const { data } = await api.get<{ items?: { quantity: number; rate: number; unit: string }[] }>(`/api/v1/invoices/${inv.id}`);
            const it = data.items?.[0];
            setQty(it ? String(it.quantity) : '');
            setRate(it ? String(it.rate) : '');
            setUnit(it?.unit ?? '');
          } catch { /* ignore */ }
        }
      })
      .catch(() => setToken(null))
      .finally(() => setLoading(false));
  }, [tokenId]);

  useEffect(() => { if (open) load(); }, [open, load]);

  const inv = token?.linked_invoice;
  const amount = (parseFloat(qty) || 0) * (parseFloat(rate) || 0);

  async function collect() {
    if (!tokenId) return;
    const q = parseFloat(qty), r = parseFloat(rate);
    if (!q || q <= 0 || isNaN(r) || r < 0) { toast.error('Enter a valid quantity and rate'); return; }
    setCollecting(true);
    try {
      const { data } = await api.post<{ invoice_no: string; grand_total: number; receipt_no: string }>(
        `/api/v1/tokens/${tokenId}/collect-cash`, { quantity: q, rate: r, payment_mode: 'cash' });
      toast.success(`Bill ${data.invoice_no} finalised · ${INR(data.grand_total)} cash collected`);
      onDone();
      onClose();
    } catch (e: unknown) {
      const d = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(typeof d === 'string' ? d : 'Failed to collect cash');
    } finally { setCollecting(false); }
  }

  return (
    <Dialog open={open} onOpenChange={v => !v && onClose()}>
      <DialogContent className="max-w-sm">
        <DialogHeader><DialogTitle>Collect cash &amp; finalise bill</DialogTitle></DialogHeader>
        {loading ? (
          <div className="flex items-center justify-center py-10">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : !inv ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            No bill for this token yet — complete the weighment first.
          </p>
        ) : inv.status !== 'draft' ? (
          <div className="py-6 text-center text-sm space-y-1">
            <CheckCircle2 className="h-6 w-6 text-green-500 mx-auto" />
            <p className="font-medium">Already finalised · {inv.invoice_no ?? ''}</p>
            <p className="text-muted-foreground">
              {inv.grand_total != null ? INR(inv.grand_total) : ''}{inv.payment_status ? ` · ${inv.payment_status}` : ''}
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            <p className="text-xs text-muted-foreground">
              Confirm the quantity &amp; rate, then finalise the bill and record the cash. Rate is from your pricing — adjust here if needed.
            </p>
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1">
                <label className="text-xs font-medium">Quantity{unit ? ` (${unit})` : ''}</label>
                <Input type="number" min="0" step="0.001" value={qty} onChange={e => setQty(e.target.value)} />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-medium">Rate (₹{unit ? `/${unit}` : ''})</label>
                <Input type="number" min="0" step="0.01" value={rate} onChange={e => setRate(e.target.value)} />
              </div>
            </div>
            <div className="flex items-center justify-between rounded-md bg-emerald-50 px-3 py-2">
              <span className="text-sm font-medium">Amount</span>
              <span className="text-lg font-bold text-emerald-700">{INR(amount)}</span>
            </div>
            <p className="text-[11px] text-muted-foreground">GST (if applicable) is added on the bill — the final total is on the invoice.</p>
            <Button onClick={collect} disabled={collecting} className="w-full gap-1.5 bg-emerald-600 hover:bg-emerald-700">
              {collecting ? <Loader2 className="h-4 w-4 animate-spin" /> : <CreditCard className="h-4 w-4" />}
              Finalise bill &amp; collect cash
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
