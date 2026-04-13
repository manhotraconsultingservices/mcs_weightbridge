import { useState, useEffect, type FormEvent } from 'react';
import { Eye, EyeOff, Building2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import api from '@/services/api';
import type { LoginResponse } from '@/types';

interface LoginPageProps {
  onLogin: (token: string, user: LoginResponse['user'], tenantSlug?: string) => void;
}

/** Resolve tenant slug from URL — supports three patterns:
 *  1. ?tenant=alpha          (query param — works anywhere)
 *  2. /login/alpha           (path segment after /login/)
 *  3. alpha.example.com      (subdomain — for production deployments)
 *
 * Returns null if not found (generic login).
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
  const [lockedTenant, setLockedTenant] = useState<string | null>(null); // pre-filled from URL
  const [tenantDisplayName, setTenantDisplayName] = useState<string | null>(null);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [multiTenant, setMultiTenant] = useState(false);

  useEffect(() => {
    api.get('/api/v1/health')
      .then(({ data }) => {
        if (data.multi_tenant) {
          setMultiTenant(true);

          // Check if URL already specifies a tenant
          const urlTenant = resolveTenantFromUrl();
          if (urlTenant) {
            setLockedTenant(urlTenant);
            setTenantSlug(urlTenant);
            // Fetch tenant display name to show on the card
            api.get(`/api/v1/admin/tenants/${urlTenant}`, {
              headers: { 'X-Super-Admin': 'skip' }, // read-only public info fallback
            }).then(({ data: t }) => {
              setTenantDisplayName(t.display_name);
            }).catch(() => {
              // Not critical — just won't show display name
            });
          }
        }
      })
      .catch(() => {});
  }, []);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError('');

    const slug = (lockedTenant ?? tenantSlug).trim().toLowerCase();

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
      onLogin(data.access_token, data.user, data.tenant_slug);
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Invalid username or password');
    } finally {
      setLoading(false);
    }
  }

  // When a tenant is locked from URL, show a dedicated branded header
  const isLockedTenant = multiTenant && !!lockedTenant;

  return (
    <div className="min-h-screen flex items-center justify-center bg-muted/30 p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-primary/10">
            <svg className="h-8 w-8 text-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 6l3 1m0 0l-3 9a5.002 5.002 0 006.001 0M6 7l3 9M6 7l6-2m6 2l3-2m6 2l3-1m-3 1l-3 9a5.002 5.002 0 006.001 0M18 7l3 9m-3-9l-6-2m0-2v2m0 16V5m0 16H9m3 0h3" />
            </svg>
          </div>
          {isLockedTenant ? (
            <>
              <CardTitle className="text-2xl">
                {tenantDisplayName ?? lockedTenant!.charAt(0).toUpperCase() + lockedTenant!.slice(1)}
              </CardTitle>
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
          <form onSubmit={handleSubmit} className="space-y-4">
            {error && (
              <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
                {error}
              </div>
            )}

            {/* Company Code field — shown only in multi-tenant mode WITHOUT a locked tenant */}
            {multiTenant && !lockedTenant && (
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

            {/* Locked tenant badge — shown when tenant comes from URL */}
            {isLockedTenant && (
              <div className="flex items-center gap-2 rounded-md bg-primary/5 border border-primary/20 px-3 py-2">
                <Building2 className="h-4 w-4 text-primary shrink-0" />
                <span className="text-sm text-muted-foreground">
                  Company: <span className="font-medium text-foreground">{tenantDisplayName ?? lockedTenant}</span>
                </span>
              </div>
            )}

            <div className="space-y-2">
              <Label htmlFor="username">Username</Label>
              <Input
                id="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="Enter username"
                autoFocus={!multiTenant || !!lockedTenant}
                required
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

            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? 'Signing in...' : 'Sign In'}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
