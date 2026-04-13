"""Thread-safe context variables for current tenant.

Set by TenantMiddleware (from JWT) or manually for agent/background tasks.
Read by database.get_db() to route to the correct tenant engine.
"""

from contextvars import ContextVar

current_tenant_slug: ContextVar[str | None] = ContextVar(
    "current_tenant_slug", default=None
)

# True when tenant status is 'readonly' (AMC expired)
current_tenant_readonly: ContextVar[bool] = ContextVar(
    "current_tenant_readonly", default=False
)
