import uuid
from fastapi import Depends, HTTPException, Header, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import get_settings
from app.database import get_db
from app.models.user import User

settings = get_settings()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    # In multi-tenant mode, the ContextVar is already set by TenantMiddleware
    # before this dependency is resolved, so get_db() routes correctly.
    # We validate the tenant claim exists in the JWT for safety.
    if settings.MULTI_TENANT:
        tenant_slug = payload.get("tenant")
        if not tenant_slug:
            raise credentials_exception

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise credentials_exception
    return user


def get_current_branch_id(
    x_branch_id: str | None = Header(default=None),
    current_user: User = Depends(get_current_user),
) -> uuid.UUID | None:
    """Resolve the active branch for a request (Horizon 3 multi-branch).

    - Admins/owners may switch branch via the ``X-Branch-Id`` header (the UI's
      branch picker sends it). Empty/"all" header → None = consolidated/default.
    - Everyone else is pinned to their assigned ``user.branch_id``.
    - None means the default branch (NULL branch_id) — backward-compatible with
      single-plant tenants that have no branches.
    """
    if current_user.role == "admin" and x_branch_id:
        if x_branch_id.lower() in ("all", ""):
            return None
        try:
            return uuid.UUID(x_branch_id)
        except ValueError:
            return None
    return current_user.branch_id


def require_role(*roles: str):
    """Dependency that checks if the current user has one of the required roles."""
    async def role_checker(current_user: User = Depends(get_current_user)):
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{current_user.role}' not authorized. Required: {', '.join(roles)}",
            )
        return current_user
    return role_checker


def require_page_permission(*pages: str, always: tuple[str, ...] = ("admin", "operator")):
    """Authorize a data endpoint by the tenant's admin-configured role→pages grant
    (``app_settings.role_permissions``) instead of a fixed role list.

    Why: a hard ``require_role("admin","operator")`` on a data endpoint blocks a
    role the admin has deliberately granted the matching page — e.g. an accountant
    who has ``/products`` (Item Master) either by default (see
    ``DEFAULT_ROLE_PERMISSIONS``) or by an explicit grant — even though the page
    opens for them in the UI. This dependency honours that grant, so ANY role
    (built-in OR admin-created custom) that holds one of ``pages`` may use the
    endpoint. It upholds the RBAC principle "custom roles are first-class — never
    hard-code the role list".

    - ``always`` roles bypass the map (``admin`` has ``"*"``; ``operator`` is kept
      for parity with the legacy ``require_role("admin","operator")`` guards these
      replace, so weighbridge operators are never regressed).
    - The stored map is layered over ``DEFAULT_ROLE_PERMISSIONS`` so a role the
      admin never touched keeps its defaults, while a role the admin explicitly
      edited uses exactly what they saved (an explicit removal still denies).
    """
    async def perm_checker(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        role = current_user.role
        if role in always:
            return current_user
        # Lazy import avoids a circular import (app_settings imports require_role).
        from app.routers.app_settings import (
            _get_raw, DEFAULT_ROLE_PERMISSIONS, PERMISSIONS_KEY,
        )
        merged = dict(DEFAULT_ROLE_PERMISSIONS)
        raw = await _get_raw(db, PERMISSIONS_KEY)
        if raw:
            try:
                import json
                stored = json.loads(raw)
                if isinstance(stored, dict):
                    merged.update(stored)
            except Exception:
                pass
        perms = merged.get(role, [])
        if "*" in perms or any(p in perms for p in pages):
            return current_user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Role '{role}' not authorized for this action. Ask an admin to "
                f"grant this role access to the relevant page in Settings → Permissions."
            ),
        )
    return perm_checker
