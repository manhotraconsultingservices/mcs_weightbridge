import { useState } from 'react';
import { Printer, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import api from '@/services/api';
import { toast } from 'sonner';

interface PrintButtonProps {
  /** API URL for the print endpoint, e.g. /api/v1/tokens/{id}/print */
  url: string;
  /** Separate URL for A4 if different (e.g. /api/v1/invoices/{id}/pdf → downloads as PDF blob) */
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
  const [loading, setLoading] = useState<'a4' | 'thermal' | null>(null);

  async function doPrint(format: 'a4' | 'thermal') {
    setLoading(format);
    try {
      const printUrl =
        format === 'a4' && a4Url ? a4Url : `${url}?format=${format}`;
      const mimeType =
        format === 'a4' && a4Url ? 'application/pdf' : 'text/html';

      const res = await api.get(printUrl, { responseType: 'blob' });
      const blob = new Blob([res.data], { type: mimeType });
      const blobUrl = URL.createObjectURL(blob);

      const popup = window.open(
        blobUrl,
        '_blank',
        format === 'thermal'
          ? 'width=320,height=650,scrollbars=yes,resizable=no'
          : 'width=900,height=750,scrollbars=yes',
      );

      if (!popup) {
        toast.error('Popup was blocked. Please allow popups for this site.');
        URL.revokeObjectURL(blobUrl);
        return;
      }

      // Revoke the blob URL after 60 seconds to free memory
      setTimeout(() => URL.revokeObjectURL(blobUrl), 60_000);
    } catch {
      toast.error('Could not open print preview. Please try again.');
    } finally {
      setLoading(null);
    }
  }

  const isLoading = loading !== null;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          size={size === 'sm' ? 'icon' : 'default'}
          variant={variant}
          className={size === 'sm' ? 'h-7 w-7' : ''}
          disabled={isLoading}
          title="Print"
        >
          {isLoading ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Printer className="h-3.5 w-3.5" />
          )}
          {!iconOnly && label && <span className="ml-1">{label}</span>}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onClick={() => doPrint('a4')} disabled={isLoading}>
          <span className="mr-2">📄</span> A4 Print
        </DropdownMenuItem>
        <DropdownMenuItem
          onClick={() => doPrint('thermal')}
          disabled={isLoading}
        >
          <span className="mr-2">🧾</span> Thermal Print (80mm)
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
