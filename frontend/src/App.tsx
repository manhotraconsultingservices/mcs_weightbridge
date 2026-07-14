import { useState, useEffect, useRef, useMemo } from 'react';
import { BrowserRouter, Routes, Route, Navigate, useParams, useLocation } from 'react-router-dom';
import { Toaster } from 'sonner';
import { useAuth } from '@/hooks/useAuth';
import { useUsbGuard } from '@/hooks/useUsbGuard';
import { useAppSettings } from '@/hooks/useAppSettings';
import { PermissionsContext, buildPermissionsCtx } from '@/contexts/PermissionsContext';
import { canAccessRoute } from '@/lib/rbac';
import NoAccessPage from '@/pages/NoAccessPage';
import LoginPage from '@/pages/LoginPage';
import LandingPage from '@/pages/LandingPage';
import LicenseExpiredPage from '@/pages/LicenseExpiredPage';
import DashboardPage from '@/pages/DashboardPage';
import TokenPage from '@/pages/TokenPage';
import PartiesPage from '@/pages/PartiesPage';
import CustomerProfilePage from '@/pages/CustomerProfilePage';
import CustomerPickerPage from '@/pages/CustomerPickerPage';
import PartyBalancesPage from '@/pages/PartyBalancesPage';
import AdvancesPage from '@/pages/AdvancesPage';
import AgentsPage from '@/pages/AgentsPage';
import AgentReportPage from '@/pages/AgentReportPage';
import OperatorKioskPage from '@/pages/OperatorKioskPage';
import GatePassPage from '@/pages/GatePassPage';
import ErrorBoundary from '@/components/ErrorBoundary';
import OwnerDashboardPage from '@/pages/OwnerDashboardPage';
// Sprint 3 — hub pages that consolidate the old 28-item sidebar
import SalesHubPage from '@/pages/SalesHubPage';
import CrmHubPage from '@/pages/CrmHubPage';
import MaterialsHubPage from '@/pages/MaterialsHubPage';
import OperationsHubPage from '@/pages/OperationsHubPage';
import ReportsHubPage from '@/pages/ReportsHubPage';
// BCG navigation — 4-section grouped hubs
import WeighbridgeHubPage from '@/pages/WeighbridgeHubPage';
import CamerasAnprHubPage from '@/pages/CamerasAnprHubPage';
import ProcurementHubPage from '@/pages/ProcurementHubPage';
import InventoryProductionHubPage from '@/pages/InventoryProductionHubPage';
import ProductionHubPage from '@/pages/ProductionHubPage';
import AccountsHubPage from '@/pages/AccountsHubPage';
import GstComplianceHubPage from '@/pages/GstComplianceHubPage';
import AnalyticsHubPage from '@/pages/AnalyticsHubPage';
import FraudRegistersHubPage from '@/pages/FraudRegistersHubPage';
import VehiclesPage from '@/pages/VehiclesPage';
import FuelMileagePage from '@/pages/FuelMileagePage';
import InvoicesPage from '@/pages/InvoicesPage';
import QuotationsPage from '@/pages/QuotationsPage';
import DeliveryChallansPage from '@/pages/DeliveryChallansPage';
import CreditDebitNotesPage from '@/pages/CreditDebitNotesPage';
import RoyaltyPassesPage from '@/pages/RoyaltyPassesPage';
import CustomerPortalPage from '@/pages/CustomerPortalPage';
import OfflineIndicator from '@/components/OfflineIndicator';
import BranchAdminPage from '@/pages/BranchAdminPage';
import BranchPicker from '@/components/BranchPicker';
import ProductsPage from '@/pages/ProductsPage';
import PricingMatrixPage from '@/pages/PricingMatrixPage';
import ProductionSettingsPage from '@/pages/ProductionSettingsPage';
import ProductInventoryPage from '@/pages/ProductInventoryPage';
import ProductionPage from '@/pages/ProductionPage';
import ProductionDashboardPage from '@/pages/ProductionDashboardPage';
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
import CustomFieldsPage from '@/pages/CustomFieldsPage';
import WallpaperSettingsPage from '@/pages/WallpaperSettingsPage';
import CameraScalePage from '@/pages/CameraScalePage';
import AnprEventsPage from '@/pages/AnprEventsPage';
import AnprLivePage from '@/pages/AnprLivePage';
import AnprReviewPage from '@/pages/AnprReviewPage';
import AnprTripsPage from '@/pages/AnprTripsPage';
import SnapshotSearchPage from '@/pages/SnapshotSearchPage';
import TokenPageV1 from '@/pages/TokenPageV1';
import PlatformLoginPage from '@/pages/PlatformLoginPage';
import PlatformDashboard from '@/pages/PlatformDashboard';
import Sidebar from '@/components/Sidebar';
import MobileBottomNav from '@/components/MobileBottomNav';
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

// Redirect to the first page the user has access to.
// Operators get the simplified kiosk; everyone else gets the exception-first
// owner dashboard. Legacy chart-heavy dashboard still reachable at /dashboard-legacy.
function HomeRedirect({ permissions, role }: { permissions: string[]; role?: string }) {
  if (role === 'operator') return <Navigate to="/operator" replace />;
  if (role === 'gate_guard') return <Navigate to="/gate" replace />;
  if (permissions.includes('*') || permissions.includes('/')) return <OwnerDashboardPage />;
  const first = permissions[0];
  if (first) return <Navigate to={first} replace />;
  return <OwnerDashboardPage />; // absolute fallback
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
  const { permissions, wallpaperUrl, roleTabPerms } = useAppSettings(user.role);
  const location = useLocation();
  const permissionsCtx = useMemo(
    () => buildPermissionsCtx(user.role, permissions, roleTabPerms),
    [user.role, permissions, roleTabPerms],
  );
  // Route guard — block direct URL access to a page this role wasn't granted.
  // Admin bypasses; detail/utility routes fail open (see rbac.ts).
  const routeAllowed = canAccessRoute(location.pathname, permissions, user.role);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);

  // PWA install prompt (Android Chrome "Add to Home Screen")
  const deferredInstallPrompt = useRef<Event & { prompt: () => void } | null>(null);
  const [showInstallBanner, setShowInstallBanner] = useState(false);
  useEffect(() => {
    if (localStorage.getItem('pwa_install_dismissed')) return;
    const handler = (e: Event) => {
      e.preventDefault();
      deferredInstallPrompt.current = e as Event & { prompt: () => void };
      setShowInstallBanner(true);
    };
    window.addEventListener('beforeinstallprompt', handler);
    return () => window.removeEventListener('beforeinstallprompt', handler);
  }, []);

  function handleInstall() {
    deferredInstallPrompt.current?.prompt();
    setShowInstallBanner(false);
    localStorage.setItem('pwa_install_dismissed', '1');
  }

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar
        user={user}
        onLogout={logout}
        usbAuthorized={usbAuthorized}
        permissions={permissions}
        mobileOpen={mobileSidebarOpen}
        onMobileClose={() => setMobileSidebarOpen(false)}
      />
      <div className="flex-1 flex flex-col overflow-hidden min-w-0">
        <AmcBanner />
        {/* Top-right: branch picker + offline indicator + PWA install chip */}
        <div className="fixed top-2 right-3 z-50 flex items-center gap-2">
          {showInstallBanner && (
            <div className="flex items-center gap-1.5 rounded-full bg-primary/10 border border-primary/20 px-3 py-1 text-xs font-medium text-primary">
              <span>Install App</span>
              <button onClick={handleInstall} className="underline hover:no-underline">Install</button>
              <button onClick={() => { setShowInstallBanner(false); localStorage.setItem('pwa_install_dismissed', '1'); }} className="ml-1 text-muted-foreground hover:text-foreground">✕</button>
            </div>
          )}
          <BranchPicker role={user.role} />
          <OfflineIndicator />
        </div>
        {/* Mobile hamburger — only visible below md, larger tap target (44px) */}
        <button
          onClick={() => setMobileSidebarOpen(true)}
          className="md:hidden fixed top-3 left-3 z-40 flex h-10 w-10 items-center justify-center rounded-md bg-background border border-border shadow-sm text-foreground"
          style={{ marginTop: 'env(safe-area-inset-top)' }}
          aria-label="Open navigation"
        >
          <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>
        <main
          className="flex-1 overflow-y-auto bg-background px-3 py-3 pt-14 md:p-6 md:pt-6 pb-16 md:pb-6"
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
            <PermissionsContext.Provider value={permissionsCtx}>
            <ErrorBoundary>
            {!routeAllowed ? <NoAccessPage /> : (
            <Routes>
            <Route path="/" element={<HomeRedirect permissions={permissions} role={user.role} />} />
            {/* Legacy chart-heavy dashboard kept reachable for "View 30-day trends" link */}
            <Route path="/dashboard-legacy" element={<DashboardPage />} />
            <Route path="/tokens" element={<TokenPage />} />
            <Route path="/tokens-v1" element={<TokenPageV1 />} />
            <Route path="/invoices" element={<InvoicesPage defaultType="sale" />} />
            <Route path="/purchase-invoices" element={<InvoicesPage defaultType="purchase" />} />
            <Route path="/quotations" element={<QuotationsPage />} />
            <Route path="/delivery-challans" element={<DeliveryChallansPage />} />
            <Route path="/credit-debit-notes" element={<CreditDebitNotesPage />} />
            <Route path="/royalty" element={<RoyaltyPassesPage />} />
            <Route path="/admin/branches" element={<BranchAdminPage />} />
            {/* Sprint 3 hubs — consolidate sub-pages into tabbed views */}
            <Route path="/sales" element={<SalesHubPage />} />
            <Route path="/crm" element={<CrmHubPage />} />
            <Route path="/materials" element={<MaterialsHubPage />} />
            <Route path="/operations" element={<OperationsHubPage />} />
            {/* BCG navigation — 4-section grouped hubs */}
            <Route path="/weighbridge"    element={<WeighbridgeHubPage />} />
            <Route path="/cameras-anpr"   element={<CamerasAnprHubPage />} />
            <Route path="/procurement"    element={<ProcurementHubPage />} />
            <Route path="/inventory-hub"  element={<InventoryProductionHubPage />} />
            <Route path="/production-hub" element={<ProductionHubPage />} />
            <Route path="/accounts"       element={<AccountsHubPage />} />
            <Route path="/gst-compliance" element={<GstComplianceHubPage />} />
            <Route path="/analytics"      element={<AnalyticsHubPage />} />
            <Route path="/fraud-registers" element={<FraudRegistersHubPage />} />
            <Route path="/products" element={<ProductsPage />} />
            <Route path="/pricing-matrix" element={<PricingMatrixPage />} />
            <Route path="/parties" element={<PartiesPage />} />
            {/* Customer 360 — picker landing at /customers, full profile at /customers/:id */}
            <Route path="/customers" element={<CustomerPickerPage />} />
            <Route path="/customers/:id" element={<CustomerProfilePage />} />
            {/* Supplier 360 — dedicated namespace (reuses the type-aware picker + profile) */}
            <Route path="/suppliers" element={<CustomerPickerPage lockType="supplier" linkBase="/suppliers" />} />
            <Route path="/suppliers/:id" element={<CustomerProfilePage />} />
            <Route path="/vehicles" element={<VehiclesPage />} />
            <Route path="/fuel" element={<FuelMileagePage />} />
            <Route path="/payments" element={<PaymentsPage />} />
            <Route path="/ledger" element={<LedgerPage />} />
            <Route path="/party-balances" element={<PartyBalancesPage />} />
            <Route path="/advances" element={<AdvancesPage />} />
            <Route path="/agents" element={<AgentsPage />} />
            <Route path="/agents/:id" element={<AgentReportPage />} />
            {/* /reports now serves the hub (with old ReportsPage as a tab). */}
            <Route path="/reports" element={<ReportsHubPage />} />
            <Route path="/reports-classic" element={<ReportsPage />} />
            <Route path="/gst-reports" element={<GstReportsPage />} />
            <Route path="/private-invoices" element={<PrivateInvoicesPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/notifications" element={<NotificationsPage />} />
            <Route path="/audit" element={<AuditPage />} />
            <Route path="/backup" element={<BackupPage />} />
            <Route path="/import" element={<ImportPage />} />
            <Route path="/compliance" element={<CompliancePage />} />
            <Route path="/inventory" element={<InventoryPage />} />
            <Route path="/product-inventory" element={<ProductInventoryPage />} />
            <Route path="/production" element={<ProductionPage />} />
            <Route path="/production/dashboard" element={<ProductionDashboardPage />} />
            <Route path="/production/settings" element={<ProductionSettingsPage />} />
            <Route path="/camera-scale" element={<CameraScalePage />} />
            <Route path="/snapshot-search" element={<SnapshotSearchPage />} />
            <Route path="/anpr/events" element={<AnprEventsPage />} />
            <Route path="/anpr/live" element={<AnprLivePage />} />
            <Route path="/anpr/review" element={<AnprReviewPage />} />
            <Route path="/anpr/trips" element={<AnprTripsPage />} />
            {/* Gate management — guard registers every vehicle entry + exit */}
            <Route path="/gate" element={<GatePassPage />} />
            {/* Administration — admin only (each page self-guards via role check) */}
            <Route path="/admin/users" element={<UserManagementPage />} />
            <Route path="/admin/permissions" element={<PermissionsPage />} />
            <Route path="/admin/custom-fields" element={<CustomFieldsPage />} />
            <Route path="/admin/wallpaper" element={<WallpaperSettingsPage />} />
              <Route path="*" element={<HomeRedirect permissions={permissions} role={user.role} />} />
            </Routes>
            )}
            </ErrorBoundary>
            </PermissionsContext.Provider>
          </div>
        </main>
        {/* Mobile bottom navigation bar — hidden on md+ */}
        <MobileBottomNav onOpenSidebar={() => setMobileSidebarOpen(true)} />
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
          // SaaS mode — store flag and skip license check
          sessionStorage.setItem('multi_tenant', '1');
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
      {/* Customer self-service portal — separate (customer) auth + layout */}
      <Route path="/portal/*" element={<CustomerPortalPage />} />
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
      {/* Operator kiosk — full-bleed, no sidebar/header chrome. Operators
          land here by default; admins can also visit /operator directly. */}
      <Route path="/operator" element={
        (!isAuthenticated || !user)
          ? <LoginPage onLogin={login} />
          : <OperatorKioskPage user={user} onLogout={logout} />
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
