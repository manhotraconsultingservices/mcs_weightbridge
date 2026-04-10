"""
Security headers middleware — comprehensive hardening.

Headers applied:
  - Content-Security-Policy  : restricts resource loading to same origin
  - X-Content-Type-Options   : prevents MIME-type sniffing
  - X-Frame-Options          : blocks clickjacking via iframe
  - Referrer-Policy          : controls referrer header leakage
  - Permissions-Policy       : disables unused browser features
  - Cache-Control            : prevents sensitive API responses from being cached
  - X-Request-ID             : correlates logs with requests
"""

import secrets
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


# Content Security Policy — tightly scoped for a local ERP SPA
# - default-src 'self'        : only load resources from same origin
# - style-src 'unsafe-inline' : shadcn/Tailwind requires inline styles
# - img-src data: blob:       : camera snapshots and file previews need blob: URLs
# - connect-src 'self' ws:    : WebSocket for weight scale on same host
_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self' data:; "
    "connect-src 'self' ws: wss:; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # Anti-clickjacking
        response.headers["X-Frame-Options"]        = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"

        # XSS mitigations
        response.headers["Content-Security-Policy"] = _CSP
        response.headers["X-XSS-Protection"]        = "0"  # Disabled — CSP supersedes it; old header can cause issues

        # Referrer & permissions
        response.headers["Referrer-Policy"]    = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), "
            "payment=(), usb=(), bluetooth=()"
        )

        # HSTS — enforce HTTPS once TLS is configured (safe even on HTTP — browsers ignore without TLS)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        # Prevent caching of all API responses
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
            response.headers["Pragma"]        = "no-cache"
            response.headers["Expires"]       = "0"

        # Request correlation ID (aids log tracing)
        req_id = request.headers.get("X-Request-ID") or secrets.token_hex(8)
        response.headers["X-Request-ID"] = req_id

        return response
