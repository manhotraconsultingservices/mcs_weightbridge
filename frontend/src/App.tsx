import { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate, useParams } from 'react-router-dom';
import { Toaster } from 'sonner';
import { useAuth } from '@/hooks/useAuth';
import { useUsbGuard } from '@/hooks/useUsbGuard';
import { useAppSettings } from '@/hooks/useAppSettings';
import LoginPage from '@/pages/LoginPage';
import LandingPage from '@/pages/LandingPage';
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
import SnapshotSearchPage from '@/pages/SnapshotSearchPage';
import TokenPageV1 from '@/pages/TokenPageV1';
import PlatformLoginPage from '@/pages/PlatformLoginPage';
import PlatformDashboard from '@/pages/PlatformDashboard';
import Sidebar from '@/components/Sidebar';
import { usePlatformAuth } from '@/hooks/usePlatformAuth';
import type { User } from '@/types';

/** Check if we're on the platform admin subdomain (e.g. platform.weighbridgesetu.com) */
function isPlatformHost(): boolean {
  const host = window.location.hostname;
  const match = host.match(/^([a-z][a-z0-9-]{1,30})\..+\..+$/i);
  return match ? match[1].toLowerCase() === 'platform' : false;
}

/** Check if we're on a tenant subdomain (e.g. manhotra-consulting.weighbridgesetu.com).
 *  Returns true for ANY subdomain except www and platform.
 *  Used to decide: show LandingPage (marketing) or LoginPage (tenant login).
 */
function isTenantSubdomain(): boolean {
  const host = window.location.hostname;
  const match = host.match(/^([a-z][a-z0-9-]{1,30})\..+\..+$/i);
  if (!match) return false;
  const sub = match[1].toLowerCase();
  return sub !== 'www' && sub !== 'platform';
}

// Redirect to the first page the user has access to
function HomeRedirect({ permissions }: { permissions: string[] }) {
  if (permissions.includes('*') || permissions.includes('/')) return <DashboardPage />;
  const first = permissions[0];
  if (first) return <Navigate to={first} replace />;
  return <DashboardPage />; // absolute fallback
}

// AMC expired banner
function AmcBanner() {
  const status = sessionStorage.getItem('tenant_status');
  const message = sessionStorage.getItem('tenant_status_message');
  if (status !== 'readonly') return null;
  return (
    <div className="bg-amber-50 border-b border-amber-200 px-4 py-2 text-sm text-amber-800 flex items-center gap-2 shrink-0">
      <svg className="h-4 w-4 text-amber-500 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
      </svg>
      {message || 'AMC Expired. Your account is in read-only mode. Contact support to renew.'}
    </div>
  );
}

// Inner layout — only rendered when user is authenticated, so hooks are safe here.
function AppLayout({ user, logout }: { user: User; logout: () => void }) {
  const { authorized: usbAuthorized } = useUsbGuard();
  const { permissions, wallpaperUrl } = useAppSettings(user.role);

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar user={user} onLogout={logout} usbAuthorized={usbAuthorized} permissions={permissions} />
      <div className="flex-1 flex flex-col overflow-hidden">
        <AmcBanner />
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
            <Route path="/tokens-v1" element={<TokenPageV1 />} />
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
            <Route path="/snapshot-search" element={<SnapshotSearchPage />} />
            {/* Administration — admin only (each page self-guards via role check) */}
            <Route path="/admin/users" element={<UserManagementPage />} />
            <Route path="/admin/permissions" element={<PermissionsPage />} />
            <Route path="/admin/wallpaper" element={<WallpaperSettingsPage />} />
              <Route path="*" element={<HomeRedirect permissions={permissions} />} />
            </Routes>
          </div>
        </main>
      </div>
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

/** Wrapper that injects ?tenant= into the URL so LoginPage picks it up from the path segment */
function TenantLoginRoute({ login }: { login: ReturnType<typeof useAuth>['login'] }) {
  const { tenant } = useParams<{ tenant: string }>();
  // Rewrite the URL to ?tenant=<slug> so resolveTenantFromUrl() works uniformly
  useEffect(() => {
    if (tenant && !window.location.search.includes('tenant=')) {
      const newUrl = `/login?tenant=${encodeURIComponent(tenant)}`;
      window.history.replaceState(null, '', newUrl);
    }
  }, [tenant]);
  return <LoginPage onLogin={login} />;
}

function RootRoutes() {
  const { user, isAuthenticated, login, logout } = useAuth();
  const [licenseStatus, setLicenseStatus] = useState<LicenseStatus | null>(null);
  const [licenseChecked, setLicenseChecked] = useState(false);

  // ── Platform subdomain: render ONLY platform UI ──────────────────────────
  // When on platform.weighbridgesetu.com, the entire app becomes the platform
  // admin portal. No tenant login, no landing page, no sidebar.
  const onPlatformHost = isPlatformHost();

  useEffect(() => {
    if (onPlatformHost) {
      // Platform subdomain — skip health/license checks entirely
      setLicenseChecked(true);
      return;
    }

    // Check health first to detect multi-tenant mode
    fetch('/api/v1/health')
      .then(r => r.json())
      .then((health) => {
        if (health.multi_tenant) {
          // SaaS mode — skip license check entirely
          setLicenseChecked(true);
          return;
        }
        // Single-tenant: check license as before
        return fetch('/api/v1/license/status')
          .then(r => r.json())
          .then((data: LicenseStatus) => {
            setLicenseStatus(data);
            setLicenseChecked(true);
          });
      })
      .catch(() => {
        setLicenseChecked(true);
      });
  }, [onPlatformHost]);

  if (!licenseChecked) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="animate-pulse text-muted-foreground text-sm">Loading...</div>
      </div>
    );
  }

  // ── Platform subdomain: exclusively render platform routes ────────────────
  if (onPlatformHost) {
    return <PlatformRoutes />;
  }

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

  // Tenant subdomain (e.g. manhotra-consulting.weighbridgesetu.com)
  // → show LoginPage directly, NOT the marketing LandingPage.
  const onTenantHost = isTenantSubdomain();

  return (
    <Routes>
      {/* Platform admin portal — separate auth, separate layout */}
      <Route path="/platform/*" element={<PlatformRoutes />} />
      {/* Public landing page — only on main domain, never on tenant subdomains */}
      {(!isAuthenticated || !user) && !onTenantHost && (
        <Route path="/" element={<LandingPage />} />
      )}
      {/* Login page at /login */}
      <Route path="/login" element={
        (isAuthenticated && user)
          ? <Navigate to="/dashboard" replace />
          : <LoginPage onLogin={login} />
      } />
      {/* Dedicated per-tenant login URL: /login/alpha, /login/beta, etc. */}
      <Route path="/login/:tenant" element={<TenantLoginRoute login={login} />} />
      <Route path="/priv-admin" element={
        (!isAuthenticated || !user)
          ? <LoginPage onLogin={login} />
          : <PrivateAdminPage />
      } />
      <Route path="*" element={
        (!isAuthenticated || !user)
          ? (onTenantHost ? <LoginPage onLogin={login} /> : <Navigate to="/" replace />)
          : <AppLayout user={user} logout={logout} />
      } />
    </Routes>
  );
}

/** Platform admin routes — completely separate from tenant auth.
 *  Renders as a self-contained UI: login page when unauthenticated,
 *  dashboard when authenticated.  Works both as a nested route
 *  (path="/platform/*") and standalone (platform subdomain).
 */
function PlatformRoutes() {
  const { isAuthenticated } = usePlatformAuth();
  const [, forceUpdate] = useState(0);

  // Not logged in → platform login page (no tenant UI, no landing page)
  if (!isAuthenticated) {
    return <PlatformLoginPage onLogin={() => forceUpdate(n => n + 1)} />;
  }

  // Authenticated → always show dashboard
  return <PlatformDashboard />;
}

export default function App() {
  return (
    <BrowserRouter>
      <RootRoutes />
      <Toaster richColors position="top-right" closeButton />
    </BrowserRouter>
  );
}
