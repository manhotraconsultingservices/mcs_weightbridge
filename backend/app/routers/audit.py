"""Audit trail router — view + filter audit log entries."""
import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.settings import AuditLog
from app.models.user import User
from app.models.company import Company

router = APIRouter(prefix="/api/v1/audit", tags=["Audit Trail"])


# ── Helper to get company ─────────────────────────────────────────────────────

async def _company_id(db: AsyncSession) -> uuid.UUID:
    from fastapi import HTTPException
    co = (await db.execute(select(Company).limit(1))).scalar_one_or_none()
    if not co:
        raise HTTPException(404, "Company not found")
    return co.id


# ── Logging utility (called from other routers) ───────────────────────────────

async def log_action(
    db: AsyncSession,
    company_id: uuid.UUID,
    user_id: uuid.UUID | None,
    action: str,           # create | update | delete | finalize | cancel | login
    entity_type: str,      # invoice | token | payment | party | product | user
    entity_id: str | None = None,
    details: dict | None = None,
    ip_address: str | None = None,
) -> None:
    """Insert an audit log entry. Silently ignores errors so it never breaks main flow."""
    try:
        import json as _json
        entry = AuditLog(
            company_id=company_id,
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=_json.dumps(details) if details else None,
            ip_address=ip_address,
        )
        db.add(entry)
        # Note: caller must commit (usually happens as part of main transaction)
    except Exception:
        pass  # audit failure must never break business logic


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("")
async def list_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    action: Optional[str] = Query(None),
    entity_type: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    search: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    company_id = await _company_id(db)

    q = select(AuditLog).where(AuditLog.company_id == company_id)
    if action:
        q = q.where(AuditLog.action == action)
    if entity_type:
        q = q.where(AuditLog.entity_type == entity_type)
    if user_id:
        try:
            q = q.where(AuditLog.user_id == uuid.UUID(user_id))
        except ValueError:
            pass
    if from_date:
        q = q.where(func.date(AuditLog.created_at) >= from_date)
    if to_date:
        q = q.where(func.date(AuditLog.created_at) <= to_date)
    if search:
        q = q.where(AuditLog.entity_id.ilike(f"%{search}%"))

    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar()
    rows = (await db.execute(
        q.order_by(AuditLog.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()

    # Fetch usernames in one shot
    user_ids = list({str(r.user_id) for r in rows if r.user_id})
    usernames: dict[str, str] = {}
    if user_ids:
        from app.models.user import User as UserModel
        users = (await db.execute(
            select(UserModel).where(UserModel.id.in_([uuid.UUID(uid) for uid in user_ids]))
        )).scalars().all()
        usernames = {str(u.id): u.username for u in users}

    return {
        "items": [_out(r, usernames) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def _out(r: AuditLog, usernames: dict) -> dict:
    return {
        "id": str(r.id),
        "action": r.action,
        "entity_type": r.entity_type,
        "entity_id": r.entity_id,
        "user_id": str(r.user_id) if r.user_id else None,
        "username": usernames.get(str(r.user_id), "—") if r.user_id else "system",
        "details": r.details,
        "ip_address": r.ip_address,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.get("/stats")
async def audit_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Quick stats: total entries, breakdown by action and entity_type."""
    company_id = await _company_id(db)

    by_action = (await db.execute(
        select(AuditLog.action, func.count(AuditLog.id).label("cnt"))
        .where(AuditLog.company_id == company_id)
        .group_by(AuditLog.action)
    )).all()

    by_entity = (await db.execute(
        select(AuditLog.entity_type, func.count(AuditLog.id).label("cnt"))
        .where(AuditLog.company_id == company_id)
        .group_by(AuditLog.entity_type)
    )).all()

    total = (await db.execute(
        select(func.count(AuditLog.id)).where(AuditLog.company_id == company_id)
    )).scalar()

    return {
        "total_entries": total,
        "by_action": {r.action: r.cnt for r in by_action},
        "by_entity": {r.entity_type: r.cnt for r in by_entity},
    }
