import { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Toaster } from 'sonner';
import { useAuth } from '@/hooks/useAuth';
import { useUsbGuard } from '@/hooks/useUsbGuard';
import { useAppSettings } from '@/hooks/useAppSettings';
import LoginPage from '@/pages/LoginPage';
import LicenseExpiredPage from '@/pages/LicenseExpiredPage';
import DashboardPage from '@/pages/DashboardPage';
import TokenPage from '@/pages/TokenPage';
import PartiesPage from '@/pages/PartiesPage';
import VehiclesPage from '@/pages/VehiclesPage';
import InvoicesPage from '@/pages/InvoicesPage';
import QuotationsPage from '@/pages/QuotationsPage';
import ProductsPage from '@/pages/ProductsPage';
import PaymentsPage from '@/pages/PaymentsPage';
import LedgerPage from '@/pages/LedgerPage';
import SettingsPage from '@/pages/SettingsPage';
import ReportsPage from '@/pages/ReportsPage';
import GstReportsPage from '@/pages/GstReportsPage';
import PrivateInvoicesPage from '@/pages/PrivateInvoicesPage';
import PrivateAdminPage from '@/pages/PrivateAdminPage';
import NotificationsPage from '@/pages/NotificationsPage';
import AuditPage from '@/pages/AuditPage';
import BackupPage from '@/pages/BackupPage';
import ImportPage from '@/pages/ImportPage';
import CompliancePage from '@/pages/CompliancePage';
import InventoryPage from '@/pages/InventoryPage';
import UserManagementPage from '@/pages/UserManagementPage';
import PermissionsPage from '@/pages/PermissionsPage';
import WallpaperSettingsPage from '@/pages/WallpaperSettingsPage';
import CameraScalePage from '@/pages/CameraScalePage';
import Sidebar from '@/components/Sidebar';
import type { User } from '@/types';

// Redirect to the first page the user has access to
function HomeRedirect({ permissions }: { permissions: string[] }) {
  if (permissions.includes('*') || permissions.includes('/')) return <DashboardPage />;
  const first = permissions[0];
  if (first) return <Navigate to={first} replace />;
  return <DashboardPage />; // absolute fallback
}

// Inner layout — only rendered when user is authenticated, so hooks are safe here.
function AppLayout({ user, logout }: { user: User; logout: () => void }) {
  const { authorized: usbAuthorized } = useUsbGuard();
  const { permissions, wallpaperUrl } = useAppSettings(user.role);

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar user={user} onLogout={logout} usbAuthorized={usbAuthorized} permissions={permissions} />
      <main
        className="flex-1 overflow-y-auto bg-background p-6"
        style={
          wallpaperUrl
            ? {
                backgroundImage: `url(${wallpaperUrl})`,
                backgroundSize: 'cover',
                backgroundAttachment: 'fixed',
                backgroundPosition: 'center',
              }
            : undefined
        }
      >
        <div className={wallpaperUrl ? 'min-h-full bg-background/80 backdrop-blur-sm rounded-lg p-4' : ''}>
          <Routes>
            <Route path="/" element={<HomeRedirect permissions={permissions} />} />
            <Route path="/tokens" element={<TokenPage />} />
            <Route path="/invoices" element={<InvoicesPage defaultType="sale" />} />
            <Route path="/purchase-invoices" element={<InvoicesPage defaultType="purchase" />} />
            <Route path="/quotations" element={<QuotationsPage />} />
            <Route path="/products" element={<ProductsPage />} />
            <Route path="/parties" element={<PartiesPage />} />
            <Route path="/vehicles" element={<VehiclesPage />} />
            <Route path="/payments" element={<PaymentsPage />} />
            <Route path="/ledger" element={<LedgerPage />} />
            <Route path="/reports" element={<ReportsPage />} />
            <Route path="/gst-reports" element={<GstReportsPage />} />
            <Route path="/private-invoices" element={<PrivateInvoicesPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/notifications" element={<NotificationsPage />} />
            <Route path="/audit" element={<AuditPage />} />
            <Route path="/backup" element={<BackupPage />} />
            <Route path="/import" element={<ImportPage />} />
            <Route path="/compliance" element={<CompliancePage />} />
            <Route path="/inventory" element={<InventoryPage />} />
            <Route path="/camera-scale" element={<CameraScalePage />} />
            {/* Administration — admin only (each page self-guards via role check) */}
            <Route path="/admin/users" element={<UserManagementPage />} />
            <Route path="/admin/permissions" element={<PermissionsPage />} />
            <Route path="/admin/wallpaper" element={<WallpaperSettingsPage />} />
            <Route path="*" element={<HomeRedirect permissions={permissions} />} />
          </Routes>
        </div>
      </main>
    </div>
  );
}

interface LicenseStatus {
  valid: boolean;
  error: string | null;
  serial: string | null;
  customer: string | null;
  expires: string | null;
}

function Root() {
  const { user, isAuthenticated, login, logout } = useAuth();
  const [licenseStatus, setLicenseStatus] = useState<LicenseStatus | null>(null);
  const [licenseChecked, setLicenseChecked] = useState(false);

  // Check license on mount
  useEffect(() => {
    fetch('/api/v1/license/status')
      .then(r => r.json())
      .then((data: LicenseStatus) => {
        setLicenseStatus(data);
        setLicenseChecked(true);
      })
      .catch(() => {
        // If we can't reach the server at all, allow — server will enforce anyway
        setLicenseChecked(true);
      });
  }, []);

  // Show nothing while checking license
  if (!licenseChecked) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="animate-pulse text-muted-foreground text-sm">Checking license...</div>
      </div>
    );
  }

  // Block if license is invalid
  if (licenseStatus && !licenseStatus.valid) {
    return (
      <LicenseExpiredPage
        error={licenseStatus.error}
        serial={licenseStatus.serial}
        customer={licenseStatus.customer}
        expires={licenseStatus.expires}
      />
    );
  }

  // Private admin console — renders outside the main layout (no sidebar)
  if (window.location.pathname === '/priv-admin') {
    if (!isAuthenticated || !user) return <LoginPage onLogin={login} />;
    return <PrivateAdminPage />;
  }

  if (!isAuthenticated || !user) {
    return <LoginPage onLogin={login} />;
  }

  return <AppLayout user={user} logout={logout} />;
}

export default function App() {
  return (
    <BrowserRouter>
      <Root />
      <Toaster richColors position="top-right" closeButton />
    </BrowserRouter>
  );
}
