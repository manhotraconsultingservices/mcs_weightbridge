"""
License guard middleware.

Intercepts all API requests and returns HTTP 503 when the license is
invalid or expired. Exempts health-check and license-status endpoints
so the frontend can display the expired-license page.
"""

import json
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Paths that bypass the license check
EXEMPT_PATHS = frozenset({
    "/api/v1/health",
    "/api/v1/license/status",
})


class LicenseGuardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Skip license check entirely in multi-tenant SaaS mode
        from app.config import get_settings
        if get_settings().MULTI_TENANT:
            return await call_next(request)

        # Only gate API paths
        path = request.url.path

        # Don't gate non-API paths (frontend static files, etc.)
        if not path.startswith("/api/"):
            return await call_next(request)

        # Exempt paths
        if path in EXEMPT_PATHS:
            return await call_next(request)

        # Check license state (set by lifespan in main.py)
        if not getattr(request.app.state, "license_valid", False):
            error = getattr(request.app.state, "license_error", "License invalid")
            return Response(
                content=json.dumps({
                    "detail": "License expired or invalid",
                    "error": error,
                }),
                status_code=503,
                media_type="application/json",
            )

        return await call_next(request)
