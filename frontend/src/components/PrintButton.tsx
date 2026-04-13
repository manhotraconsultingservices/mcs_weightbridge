import { useState } from 'react';
import { Printer, Loader2 } from 'lucide-react';
import api from '@/services/api';
import { toast } from 'sonner';

interface PrintButtonProps {
  /** API URL for the print endpoint, e.g. /api/v1/tokens/{id}/print */
  url: string;
  /** Separate URL for A4/PDF if different */
  a4Url?: string;
  label?: string;
  size?: 'sm' | 'default';
  variant?: 'ghost' | 'outline' | 'default';
  iconOnly?: boolean;
}

export function PrintButton({
  url,
  a4Url,
  label,
  size = 'sm',
  variant = 'ghost',
  iconOnly = false,
}: PrintButtonProps) {
  const [loading, setLoading] = useState(false);

  async function doPrint() {
    setLoading(true);
    try {
      const printUrl = a4Url ?? `${url}?format=a5`;
      const res = await api.get(printUrl, { responseType: 'blob' });

      const contentType = res.headers['content-type'] || '';
      const blob = res.data as Blob;

      // If response is HTML (e.g. token weighment slip), open as HTML page
      // which has its own window.print() script embedded
      if (contentType.includes('text/html')) {
        const htmlBlob = new Blob([blob], { type: 'text/html' });
        const blobUrl = URL.createObjectURL(htmlBlob);
        const popup = window.open(blobUrl, '_blank', 'width=620,height=900,scrollbars=yes');
        if (!popup) {
          toast.error('Popup was blocked. Please allow popups for this site.');
          URL.revokeObjectURL(blobUrl);
          return;
        }
        setTimeout(() => URL.revokeObjectURL(blobUrl), 60_000);
        return;
      }

      // Default: treat as PDF
      const pdfBlob = new Blob([blob], { type: 'application/pdf' });
      const blobUrl = URL.createObjectURL(pdfBlob);

      const popup = window.open(blobUrl, '_blank', 'width=620,height=900,scrollbars=yes');
      if (!popup) {
        toast.error('Popup was blocked. Please allow popups for this site.');
        URL.revokeObjectURL(blobUrl);
        return;
      }

      setTimeout(() => URL.revokeObjectURL(blobUrl), 60_000);
    } catch {
      toast.error('Could not open print preview. Please try again.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <button
      onClick={doPrint}
      disabled={loading}
      title="Print"
      className={[
        'inline-flex items-center justify-center rounded-md transition-colors',
        'disabled:pointer-events-none disabled:opacity-50 cursor-pointer',
        size === 'sm' ? 'h-7 w-7' : 'h-9 px-3 gap-1.5 text-sm font-medium',
        variant === 'outline'
          ? 'border border-input bg-background hover:bg-accent hover:text-accent-foreground'
          : variant === 'default'
          ? 'bg-primary text-primary-foreground hover:bg-primary/90'
          : 'hover:bg-accent hover:text-accent-foreground',
      ].join(' ')}
    >
      {loading ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
      ) : (
        <Printer className="h-3.5 w-3.5" />
      )}
      {!iconOnly && label && <span>{label}</span>}
    </button>
  );
}
