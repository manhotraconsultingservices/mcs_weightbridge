"""Tenant middleware — extracts tenant slug from JWT and sets ContextVar.

Must run BEFORE FastAPI dependency resolution so that get_db() sees
the correct tenant when Depends(get_db) is resolved.

Also enforces tenant status:
- suspended → 403 on all requests
- readonly  → 403 on write operations (POST/PUT/PATCH/DELETE)
"""

import logging
import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from jose import jwt, JWTError

from app.multitenancy.context import current_tenant_slug, current_tenant_readonly

logger = logging.getLogger(__name__)

# ── Tenant status cache (process-local, 5-min TTL) ───────────────────────────
_status_cache: dict[str, tuple[str, float]] = {}  # slug → (status, timestamp)
_CACHE_TTL = 300  # 5 minutes


async def _get_tenant_status(slug: str) -> str:
    """Look up tenant status with caching to avoid hitting master DB on every request."""
    now = time.time()
    cached = _status_cache.get(slug)
    if cached and (now - cached[1]) < _CACHE_TTL:
        return cached[0]

    try:
        from app.multitenancy.master_db import get_master_session_factory
        factory = get_master_session_factory()
        from sqlalchemy import text
        async with factory() as db:
            row = (await db.execute(
                text("SELECT status FROM tenants WHERE slug = :s"),
                {"s": slug},
            )).fetchone()
            status = row[0] if row else "active"
            _status_cache[slug] = (status, now)
            return status
    except Exception as e:
        logger.warning("Failed to check tenant status for %s: %s", slug, e)
        return cached[0] if cached else "active"


def invalidate_tenant_status_cache(slug: str | None = None):
    """Clear status cache for a tenant (or all tenants)."""
    if slug:
        _status_cache.pop(slug, None)
    else:
        _status_cache.clear()


# ── Paths exempt from readonly enforcement ────────────────────────────────────
_READONLY_EXEMPT_PATHS = {
    "/api/v1/auth/login",
    "/api/v1/auth/change-password",
    "/api/v1/health",
}


class TenantMiddleware(BaseHTTPMiddleware):
    """Extract tenant slug from JWT Bearer token, set ContextVar, enforce status."""

    async def dispatch(self, request: Request, call_next) -> Response:
        from app.config import get_settings
        settings = get_settings()

        # Only process if multi-tenant is enabled
        if not settings.MULTI_TENANT:
            return await call_next(request)

        tenant_slug_value = None

        # Try to extract tenant from JWT
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            try:
                payload = jwt.decode(
                    token,
                    settings.SECRET_KEY,
                    algorithms=[settings.ALGORITHM],
                )
                # Skip platform tokens (they don't target a tenant DB)
                if payload.get("platform"):
                    return await call_next(request)

                tenant_slug_value = payload.get("tenant")
                if tenant_slug_value:
                    current_tenant_slug.set(tenant_slug_value)
            except JWTError:
                # Let the auth dependency handle invalid tokens
                pass

        # Also check X-Tenant header (used by agents)
        if not tenant_slug_value:
            x_tenant = request.headers.get("X-Tenant")
            if x_tenant:
                tenant_slug_value = x_tenant
                current_tenant_slug.set(x_tenant)

        # ── Enforce tenant status ─────────────────────────────────────
        if tenant_slug_value:
            status = await _get_tenant_status(tenant_slug_value)

            if status == "suspended":
                current_tenant_slug.set(None)
                return JSONResponse(
                    status_code=403,
                    content={"detail": "This account has been suspended. Contact support."},
                )

            if status == "readonly":
                current_tenant_readonly.set(True)
                # Block write operations (POST/PUT/PATCH/DELETE) except exempt paths
                method = request.method.upper()
                path = request.url.path
                if method in ("POST", "PUT", "PATCH", "DELETE"):
                    if path not in _READONLY_EXEMPT_PATHS:
                        current_tenant_slug.set(None)
                        current_tenant_readonly.set(False)
                        return JSONResponse(
                            status_code=403,
                            content={
                                "detail": "AMC expired. Your account is in read-only mode. Contact support to renew.",
                                "readonly": True,
                            },
                        )
            else:
                current_tenant_readonly.set(False)

        try:
            response = await call_next(request)
        finally:
            # Reset context vars after request
            current_tenant_slug.set(None)
            current_tenant_readonly.set(False)

        return response
