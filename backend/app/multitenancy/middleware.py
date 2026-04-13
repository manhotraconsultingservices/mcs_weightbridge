"""Tenant middleware — extracts tenant slug from JWT and sets ContextVar.

Must run BEFORE FastAPI dependency resolution so that get_db() sees
the correct tenant when Depends(get_db) is resolved.
"""

import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from jose import jwt, JWTError

from app.multitenancy.context import current_tenant_slug

logger = logging.getLogger(__name__)


class TenantMiddleware(BaseHTTPMiddleware):
    """Extract tenant slug from JWT Bearer token and set ContextVar."""

    async def dispatch(self, request: Request, call_next) -> Response:
        from app.config import get_settings
        settings = get_settings()

        # Only process if multi-tenant is enabled
        if not settings.MULTI_TENANT:
            return await call_next(request)

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
                tenant_slug = payload.get("tenant")
                if tenant_slug:
                    current_tenant_slug.set(tenant_slug)
            except JWTError:
                # Let the auth dependency handle invalid tokens
                pass

        # Also check X-Tenant header (used by agents)
        if not current_tenant_slug.get(None):
            x_tenant = request.headers.get("X-Tenant")
            if x_tenant:
                current_tenant_slug.set(x_tenant)

        response = await call_next(request)

        # Reset context var after request
        current_tenant_slug.set(None)

        return response
