import { useState, useEffect, type FormEvent } from 'react';
import { Eye, EyeOff, Building2, AlertTriangle, ExternalLink, Mail } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import api from '@/services/api';
import type { LoginResponse } from '@/types';

interface LoginPageProps {
  onLogin: (token: string, user: LoginResponse['user'], tenantSlug?: string) => void;
}

interface TenantInfo {
  slug: string;
  display_name: string;
  logo_url: string | null;
  status: string; // active | readonly | suspended
  branding: {
    company_name: string;
    website: string | null;
    email: string | null;
    logo_url: string | null;
  };
}

/** Resolve tenant slug from URL — supports three patterns:
 *  1. ?tenant=alpha          (query param — works anywhere)
 *  2. /login/alpha           (path segment after /login/)
 *  3. alpha.example.com      (subdomain — for production deployments)
 */
function resolveTenantFromUrl(): string | null {
  // 1. Query param: ?tenant=alpha  OR  ?company=alpha
  const params = new URLSearchParams(window.location.search);
  const fromQuery = params.get('tenant') || params.get('company');
  if (fromQuery) return fromQuery.trim().toLowerCase();

  // 2. Path segment: /login/alpha
  const pathMatch = window.location.pathname.match(/\/login\/([a-z][a-z0-9_]{1,30})/i);
  if (pathMatch) return pathMatch[1].toLowerCase();

  // 3. Subdomain: alpha.weighbridge.app  (skip www / localhost)
  const host = window.location.hostname;
  const subdomainMatch = host.match(/^([a-z][a-z0-9_]{1,30})\..+\..+$/i);
  if (subdomainMatch && subdomainMatch[1] !== 'www') {
    return subdomainMatch[1].toLowerCase();
  }

  return null;
}

export default function LoginPage({ onLogin }: LoginPageProps) {
  const [tenantSlug, setTenantSlug] = useState('');
  const [tenantInfo, setTenantInfo] = useState<TenantInfo | null>(null);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [multiTenant, setMultiTenant] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const [resolvedSlug, setResolvedSlug] = useState<string | null>(null);
  const [initDone, setInitDone] = useState(false);

  useEffect(() => {
    api.get('/api/v1/health')
      .then(({ data }) => {
        if (data.multi_tenant) {
          setMultiTenant(true);
          const urlTenant = resolveTenantFromUrl();
          if (urlTenant) {
            setResolvedSlug(urlTenant);
            setTenantSlug(urlTenant);
            // Fetch tenant info + branding from public endpoint
            api.get<TenantInfo>(`/api/v1/tenant-info/${urlTenant}`)
              .then(({ data: info }) => {
                setTenantInfo(info);
                setInitDone(true);
              })
              .catch(() => {
                setNotFound(true);
                setInitDone(true);
              });
          } else {
            setInitDone(true);
          }
        } else {
          setInitDone(true);
        }
      })
      .catch(() => { setInitDone(true); });
  }, []);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError('');

    const slug = (resolvedSlug ?? tenantSlug).trim().toLowerCase();

    if (multiTenant && !slug) {
      setError('Company code is required');
      return;
    }

    setLoading(true);
    try {
      const formData = new URLSearchParams();
      formData.append('username', username);
      formData.append('password', password);
      if (multiTenant && slug) {
        formData.append('tenant_slug', slug);
      }
      const { data } = await api.post<LoginResponse>('/api/v1/auth/login', formData, {
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      });

      // Store tenant status for AMC banner
      if (data.tenant_status) {
        sessionStorage.setItem('tenant_status', data.tenant_status);
        if (data.tenant_status_message) {
          sessionStorage.setItem('tenant_status_message', data.tenant_status_message);
        }
      }

      onLogin(data.access_token, data.user, data.tenant_slug);
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Invalid username or password');
    } finally {
      setLoading(false);
    }
  }

  // Loading state
  if (!initDone) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-muted/30">
        <div className="h-8 w-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  // Company not found page
  if (notFound) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center bg-muted/30 p-4">
        <Card className="w-full max-w-md text-center">
          <CardContent className="pt-8 pb-8 space-y-4">
            <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-destructive/10">
              <AlertTriangle className="h-8 w-8 text-destructive" />
            </div>
            <h2 className="text-xl font-semibold">Company Not Found</h2>
            <p className="text-sm text-muted-foreground">
              The company URL you're looking for doesn't exist or the address is incorrect.
            </p>
            <p className="text-sm text-muted-foreground">
              Please check the URL and try again, or contact support.
            </p>
          </CardContent>
        </Card>
        {/* Powered by footer will show if we have branding (from a fallback fetch) */}
        <p className="mt-6 text-xs text-muted-foreground">
          Powered by Manhotra Consulting
        </p>
      </div>
    );
  }

  const isTenantResolved = multiTenant && !!resolvedSlug && !!tenantInfo;
  const isSuspended = tenantInfo?.status === 'suspended';
  const isReadonly = tenantInfo?.status === 'readonly';
  const branding = tenantInfo?.branding;

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-muted/30 p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          {/* Tenant logo or default icon */}
          {tenantInfo?.logo_url ? (
            <img
              src={tenantInfo.logo_url}
              alt={tenantInfo.display_name}
              className="mx-auto mb-2 h-16 w-auto max-w-[200px] object-contain"
            />
          ) : (
            <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-primary/10">
              <svg className="h-8 w-8 text-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 6l3 1m0 0l-3 9a5.002 5.002 0 006.001 0M6 7l3 9M6 7l6-2m6 2l3-2m6 2l3-1m-3 1l-3 9a5.002 5.002 0 006.001 0M18 7l3 9m-3-9l-6-2m0-2v2m0 16V5m0 16H9m3 0h3" />
              </svg>
            </div>
          )}

          {isTenantResolved ? (
            <>
              <CardTitle className="text-2xl">{tenantInfo.display_name}</CardTitle>
              <CardDescription>Weighbridge Management System</CardDescription>
            </>
          ) : (
            <>
              <CardTitle className="text-2xl">Weighbridge Software</CardTitle>
              <CardDescription>Stone Crusher Invoice Management System</CardDescription>
            </>
          )}
        </CardHeader>

        <CardContent>
          {/* Suspended banner */}
          {isSuspended && (
            <div className="rounded-md bg-destructive/10 border border-destructive/30 p-3 text-sm text-destructive mb-4 flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              This account has been suspended. Contact support.
            </div>
          )}

          {/* Readonly banner */}
          {isReadonly && (
            <div className="rounded-md bg-amber-50 border border-amber-200 p-3 text-sm text-amber-800 mb-4 flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 shrink-0 text-amber-500" />
              AMC expired. Read-only mode. Contact support to renew.
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            {error && (
              <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
                {error}
              </div>
            )}

            {/* Company Code field — only shown in multi-tenant mode WITHOUT a resolved tenant */}
            {multiTenant && !resolvedSlug && (
              <div className="space-y-2">
                <Label htmlFor="tenant_slug">Company Code</Label>
                <div className="relative">
                  <Building2 className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input
                    id="tenant_slug"
                    value={tenantSlug}
                    onChange={(e) => setTenantSlug(e.target.value)}
                    placeholder="Enter company code"
                    className="pl-10"
                    autoFocus
                    required
                  />
                </div>
              </div>
            )}

            <div className="space-y-2">
              <Label htmlFor="username">Username</Label>
              <Input
                id="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="Enter username"
                autoFocus={!multiTenant || !!resolvedSlug}
                required
                disabled={isSuspended}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <div className="relative">
                <Input
                  id="password"
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Enter password"
                  required
                  className="pr-10"
                  disabled={isSuspended}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(v => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
                  tabIndex={-1}
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                >
                  {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>

            <Button type="submit" className="w-full" disabled={loading || isSuspended}>
              {loading ? 'Signing in...' : 'Sign In'}
            </Button>
          </form>
        </CardContent>
      </Card>

      {/* "Powered by" footer — always shown with branding info */}
      {branding && (
        <div className="mt-6 text-center space-y-1">
          <p className="text-xs text-muted-foreground">
            Powered by{' '}
            {branding.website ? (
              <a
                href={branding.website}
                target="_blank"
                rel="noopener noreferrer"
                className="font-medium text-muted-foreground hover:text-foreground inline-flex items-center gap-0.5"
              >
                {branding.company_name}
                <ExternalLink className="h-2.5 w-2.5" />
              </a>
            ) : (
              <span className="font-medium">{branding.company_name}</span>
            )}
          </p>
          {branding.email && (
            <p className="text-[11px] text-muted-foreground/70 flex items-center justify-center gap-1">
              <Mail className="h-2.5 w-2.5" />
              <a href={`mailto:${branding.email}`} className="hover:text-foreground">
                {branding.email}
              </a>
            </p>
          )}
        </div>
      )}
    </div>
  );
}
