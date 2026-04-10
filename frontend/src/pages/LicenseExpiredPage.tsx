import { ShieldX, Phone, Mail, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';

interface LicenseExpiredPageProps {
  error: string | null;
  serial?: string | null;
  customer?: string | null;
  expires?: string | null;
}

export default function LicenseExpiredPage({ error, serial, customer, expires }: LicenseExpiredPageProps) {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-red-50 to-orange-50 p-6">
      <div className="max-w-lg w-full text-center space-y-6">
        {/* Icon */}
        <div className="mx-auto flex h-20 w-20 items-center justify-center rounded-full bg-red-100">
          <ShieldX className="h-10 w-10 text-red-600" />
        </div>

        {/* Title */}
        <div>
          <h1 className="text-3xl font-bold text-gray-900">License Expired</h1>
          <p className="mt-2 text-gray-600">
            This installation of Weighbridge Invoice Software requires a valid license to operate.
          </p>
        </div>

        {/* Error detail */}
        <div className="rounded-lg border border-red-200 bg-white p-4 text-left text-sm">
          <p className="font-medium text-red-700 mb-2">Details:</p>
          <p className="text-gray-700">{error || 'License file is missing, expired, or invalid.'}</p>
          {serial && (
            <p className="mt-2 text-gray-500">
              Serial: <span className="font-mono font-semibold">{serial}</span>
            </p>
          )}
          {customer && (
            <p className="text-gray-500">
              Customer: <span className="font-semibold">{customer}</span>
            </p>
          )}
          {expires && (
            <p className="text-gray-500">
              Expired: <span className="font-semibold">{expires}</span>
            </p>
          )}
        </div>

        {/* Contact info */}
        <div className="rounded-lg border border-gray-200 bg-white p-4 text-sm space-y-2">
          <p className="font-medium text-gray-800">Contact your vendor for renewal:</p>
          <div className="flex items-center justify-center gap-6 text-gray-600">
            <span className="flex items-center gap-1.5">
              <Phone className="h-4 w-4" /> +91-XXXXX-XXXXX
            </span>
            <span className="flex items-center gap-1.5">
              <Mail className="h-4 w-4" /> support@vendor.com
            </span>
          </div>
        </div>

        {/* Retry */}
        <Button
          variant="outline"
          onClick={() => window.location.reload()}
          className="mx-auto"
        >
          <RefreshCw className="mr-2 h-4 w-4" />
          Check Again
        </Button>

        <p className="text-xs text-gray-400">
          After receiving a new license.key file, place it in the application directory and click "Check Again".
        </p>
      </div>
    </div>
  );
}
