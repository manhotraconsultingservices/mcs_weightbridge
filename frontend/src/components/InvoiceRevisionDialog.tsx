/**
 * InvoiceRevisionDialog
 *
 * Shows the full revision chain for an invoice and provides:
 *  1. Revision History timeline
 *  2. Side-by-side comparison (diff view) between any two versions
 */

import { useEffect, useState } from 'react';
import { Loader2, GitFork, ArrowRight, Plus, Minus, RefreshCw, ChevronDown, ChevronUp } from 'lucide-react';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import api from '@/services/api';
import type { Invoice, InvoiceRevisionChain, InvoiceCompare, DiffChange, DiffItem } from '@/types';

// ── Helper: render a single field change row ──────────────────────────────────
function ChangeRow({ change }: { change: DiffChange }) {
  return (
    <tr className="border-b border-muted/50 text-xs">
      <td className="py-1.5 pr-3 text-muted-foreground font-medium whitespace-nowrap w-40">{change.label}</td>
      <td className="py-1.5 pr-3 text-red-600 line-through">{change.old_str ?? String(change.old ?? '—')}</td>
      <td className="py-1.5 pl-1 text-muted-foreground"><ArrowRight className="h-3 w-3 inline" /></td>
      <td className="py-1.5 pl-3 text-green-700 font-semibold">{change.new_str ?? String(change.new ?? '—')}</td>
    </tr>
  );
}

// ── Helper: render an item badge (added/removed) ─────────────────────────────
function ItemBadge({ item, type }: { item: DiffItem; type: 'added' | 'removed' }) {
  const color = type === 'added' ? 'bg-green-50 border-green-200 text-green-800' : 'bg-red-50 border-red-200 text-red-700';
  const Icon = type === 'added' ? Plus : Minus;
  return (
    <div className={`flex items-start gap-2 p-2 rounded border text-xs ${color}`}>
      <Icon className="h-3 w-3 mt-0.5 shrink-0" />
      <div>
        <span className="font-medium">{item.description}</span>
        {item.hsn_code && <span className="ml-2 text-[10px] opacity-70">HSN: {item.hsn_code}</span>}
        <div className="mt-0.5 opacity-70">
          Qty: {item.quantity} {item.unit} × ₹{item.rate?.toLocaleString('en-IN')} = ₹{item.total_amount?.toLocaleString('en-IN')}
        </div>
      </div>
    </div>
  );
}

// ── Diff Section ─────────────────────────────────────────────────────────────
function DiffView({ compare }: { compare: InvoiceCompare }) {
  const { diff, invoice_a, invoice_b } = compare;
  const hasChanges = diff.has_changes;

  return (
    <div className="space-y-4">
      {/* Summary header */}
      <div className={`flex items-center gap-3 p-3 rounded-lg ${hasChanges ? 'bg-amber-50 border border-amber-200' : 'bg-green-50 border border-green-200'}`}>
        <RefreshCw className={`h-4 w-4 ${hasChanges ? 'text-amber-600' : 'text-green-600'}`} />
        <div>
          <p className="text-sm font-medium">{diff.summary_text}</p>
          <p className="text-xs text-muted-foreground mt-0.5">
            {invoice_a.invoice_no} (Rv{invoice_a.revision_no}) → {invoice_b.invoice_no || 'Draft'} (Rv{invoice_b.revision_no})
          </p>
        </div>
      </div>

      {/* Header changes */}
      {diff.header.length > 0 && (
        <section>
          <h4 className="text-xs font-semibold uppercase text-muted-foreground mb-2">Header Changes</h4>
          <table className="w-full">
            <tbody>
              {diff.header.map(c => <ChangeRow key={c.field} change={c} />)}
            </tbody>
          </table>
        </section>
      )}

      {/* Amount changes */}
      {diff.amounts.length > 0 && (
        <section>
          <h4 className="text-xs font-semibold uppercase text-muted-foreground mb-2">Amount Changes</h4>
          <table className="w-full">
            <tbody>
              {diff.amounts.map(c => <ChangeRow key={c.field} change={c} />)}
            </tbody>
          </table>
        </section>
      )}

      {/* Line item changes */}
      {(diff.items.added.length > 0 || diff.items.removed.length > 0 || diff.items.modified.length > 0) && (
        <section>
          <h4 className="text-xs font-semibold uppercase text-muted-foreground mb-2">Line Item Changes</h4>
          <div className="space-y-2">
            {diff.items.added.map((item, i) => (
              <ItemBadge key={i} item={item} type="added" />
            ))}
            {diff.items.removed.map((item, i) => (
              <ItemBadge key={i} item={item} type="removed" />
            ))}
            {diff.items.modified.map((item, i) => (
              <div key={i} className="p-2 rounded border border-amber-200 bg-amber-50 text-xs">
                <div className="flex items-center gap-1 mb-1 font-medium text-amber-800">
                  <RefreshCw className="h-3 w-3" /> {item.description}
                </div>
                <table className="w-full">
                  <tbody>
                    {(item.changes || []).map(c => <ChangeRow key={c.field} change={c} />)}
                  </tbody>
                </table>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* eInvoice changes */}
      {diff.einvoice.length > 0 && (
        <section>
          <h4 className="text-xs font-semibold uppercase text-muted-foreground mb-2">eInvoice Changes</h4>
          <table className="w-full">
            <tbody>
              {diff.einvoice.map(c => <ChangeRow key={c.field} change={c} />)}
            </tbody>
          </table>
        </section>
      )}

      {!hasChanges && (
        <p className="text-sm text-center text-muted-foreground py-4">No changes found between these versions.</p>
      )}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────
interface Props {
  open: boolean;
  invoice: Invoice;
  onClose: () => void;
}

export function InvoiceRevisionDialog({ open, invoice, onClose }: Props) {
  const [chain, setChain] = useState<InvoiceRevisionChain | null>(null);
  const [loading, setLoading] = useState(false);
  const [compareData, setCompareData] = useState<InvoiceCompare | null>(null);
  const [comparing, setComparing] = useState(false);
  const [selectedA, setSelectedA] = useState<string | null>(null);
  const [selectedB, setSelectedB] = useState<string | null>(null);
  const [expandedHistory, setExpandedHistory] = useState(true);

  useEffect(() => {
    if (!open) { setChain(null); setCompareData(null); return; }
    setLoading(true);
    api.get<InvoiceRevisionChain>(`/api/v1/invoices/${invoice.id}/revisions`)
      .then(r => {
        setChain(r.data);
        // Auto-select last two versions for comparison
        const invs = r.data.invoices;
        if (invs.length >= 2) {
          setSelectedA(invs[invs.length - 2].id);
          setSelectedB(invs[invs.length - 1].id);
        }
      })
      .catch(() => setChain(null))
      .finally(() => setLoading(false));
  }, [open, invoice.id]);

  async function loadComparison(aId: string, bId: string) {
    setComparing(true); setCompareData(null);
    try {
      const { data } = await api.get<InvoiceCompare>(`/api/v1/invoices/${aId}/compare/${bId}`);
      setCompareData(data);
    } catch {
      setCompareData(null);
    } finally { setComparing(false); }
  }

  // Trigger comparison when selection changes
  useEffect(() => {
    if (selectedA && selectedB && selectedA !== selectedB) {
      loadComparison(selectedA, selectedB);
    }
  }, [selectedA, selectedB]);

  const revBadge = (inv: Invoice) => (
    <Badge variant={inv.status === 'final' ? 'default' : 'secondary'} className="text-[10px]">
      {inv.status === 'draft' ? `Rv${inv.revision_no} (Draft)` : inv.invoice_no || `Rv${inv.revision_no}`}
    </Badge>
  );

  return (
    <Dialog open={open} onOpenChange={v => !v && onClose()}>
      <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <GitFork className="h-5 w-5 text-muted-foreground" />
            Revision History — {invoice.invoice_no}
          </DialogTitle>
        </DialogHeader>

        {loading && (
          <div className="flex justify-center py-12">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        )}

        {chain && !loading && (
          <div className="space-y-5">
            {/* Revision timeline */}
            <div>
              <button
                className="flex items-center gap-2 text-sm font-semibold mb-3 w-full text-left"
                onClick={() => setExpandedHistory(h => !h)}
              >
                {expandedHistory ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                Revision Timeline ({chain.invoices.length} version{chain.invoices.length !== 1 ? 's' : ''})
              </button>

              {expandedHistory && (
                <div className="space-y-2">
                  {chain.invoices.map((inv, idx) => {
                    const histEntry = chain.history.find(h => h.to_invoice_id === inv.id);
                    return (
                      <div key={inv.id} className="flex gap-3">
                        <div className="flex flex-col items-center">
                          <div className={`h-7 w-7 rounded-full flex items-center justify-center text-xs font-bold shrink-0 ${
                            inv.status === 'final' ? 'bg-green-500 text-white' : 'bg-amber-400 text-white'
                          }`}>
                            {inv.revision_no}
                          </div>
                          {idx < chain.invoices.length - 1 && (
                            <div className="w-0.5 h-8 bg-muted-foreground/20 mt-1" />
                          )}
                        </div>
                        <div className="pb-3 flex-1">
                          <div className="flex items-center gap-2 flex-wrap">
                            {revBadge(inv)}
                            <span className="text-xs text-muted-foreground">
                              {inv.invoice_date} · ₹{Number(inv.grand_total).toLocaleString('en-IN')}
                            </span>
                            {inv.status === 'draft' && (
                              <Badge variant="outline" className="text-[10px] text-amber-600 border-amber-300">Draft</Badge>
                            )}
                          </div>
                          {histEntry && (
                            <p className="text-[11px] text-muted-foreground mt-0.5">
                              {histEntry.change_summary || '—'}
                              {histEntry.revised_by_name && (
                                <span className="ml-2">by <span className="font-medium">{histEntry.revised_by_name}</span></span>
                              )}
                              <span className="ml-2">{new Date(histEntry.created_at).toLocaleDateString('en-IN')}</span>
                            </p>
                          )}
                          {idx === 0 && (
                            <p className="text-[11px] text-muted-foreground mt-0.5">Original invoice</p>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Compare selector */}
            {chain.invoices.length >= 2 && (
              <div>
                <h3 className="text-sm font-semibold mb-3">Compare Versions</h3>
                <div className="flex items-center gap-3 mb-4 flex-wrap">
                  <div className="space-y-1">
                    <label className="text-xs text-muted-foreground">From</label>
                    <select
                      className="text-xs border rounded px-2 py-1.5 bg-background"
                      value={selectedA || ''}
                      onChange={e => setSelectedA(e.target.value)}
                    >
                      {chain.invoices.map(inv => (
                        <option key={inv.id} value={inv.id}>
                          Rv{inv.revision_no} — {inv.invoice_no || 'Draft'} (₹{Number(inv.grand_total).toLocaleString('en-IN')})
                        </option>
                      ))}
                    </select>
                  </div>
                  <ArrowRight className="h-4 w-4 text-muted-foreground mt-4" />
                  <div className="space-y-1">
                    <label className="text-xs text-muted-foreground">To</label>
                    <select
                      className="text-xs border rounded px-2 py-1.5 bg-background"
                      value={selectedB || ''}
                      onChange={e => setSelectedB(e.target.value)}
                    >
                      {chain.invoices.map(inv => (
                        <option key={inv.id} value={inv.id}>
                          Rv{inv.revision_no} — {inv.invoice_no || 'Draft'} (₹{Number(inv.grand_total).toLocaleString('en-IN')})
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                {comparing && (
                  <div className="flex justify-center py-6">
                    <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                  </div>
                )}

                {compareData && !comparing && (
                  <DiffView compare={compareData} />
                )}
              </div>
            )}

            {chain.invoices.length === 1 && (
              <p className="text-sm text-center text-muted-foreground py-4">
                No revisions yet. This is the only version of this invoice.
              </p>
            )}
          </div>
        )}

        {!chain && !loading && (
          <p className="text-sm text-center text-muted-foreground py-8">
            Unable to load revision history.
          </p>
        )}
      </DialogContent>
    </Dialog>
  );
}
