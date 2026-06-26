"""
Tally Connector API (SaaS/relay mode).

A LAN-side Tally Connector (the agent) talks to these endpoints to drain the
``tally_sync_jobs`` queue and report results. Auth mirrors the scale agent:
``{tenant, agent_key}`` in the POST body, validated against the master DB —
**no user JWT**. Only meaningful in multi-tenant/cloud mode; on-prem uses
DirectTransport and never queues. The claim/report logic lives in
``app.integrations.tally.relay_queue`` (thin router, testable core).

Endpoints:
  POST /api/v1/tally/connector/jobs/claim          — claim N pending jobs (lease)
  POST /api/v1/tally/connector/jobs/{id}/result    — report success/failure
  GET  /api/v1/tally/connector/status              — queue health (user JWT)
"""
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db, get_tenant_session
from app.dependencies import get_current_user
from app.models.user import User
from app.integrations.tally import relay_queue

router = APIRouter(prefix="/api/v1/tally/connector", tags=["Tally Connector"])


async def _authed_tenant(payload: dict[str, Any]) -> str:
    """Validate {tenant, agent_key} (multi-tenant only). Returns the tenant slug."""
    if not get_settings().MULTI_TENANT:
        raise HTTPException(400, "The Tally connector is only used in cloud (multi-tenant) mode.")
    tenant_slug = payload.get("tenant") or payload.get("tenant_slug")
    agent_key = payload.get("agent_key")
    if not tenant_slug or not agent_key:
        raise HTTPException(400, "tenant and agent_key are required")
    from app.multitenancy.registry import tenant_registry
    if not await tenant_registry.validate_agent_key(tenant_slug, agent_key):
        raise HTTPException(403, "Invalid agent key for tenant")
    return tenant_slug


@router.post("/ping")
async def connector_ping(payload: dict[str, Any]):
    """Lightweight auth + queue-depth check for the connector's --test (no jobs consumed)."""
    tenant = await _authed_tenant(payload)
    async with await get_tenant_session(tenant) as db:
        pending = (await db.execute(text(
            "SELECT count(*) FROM tally_sync_jobs WHERE status='pending'"
        ))).scalar()
        dead = (await db.execute(text(
            "SELECT count(*) FROM tally_sync_jobs WHERE status='dead'"
        ))).scalar()
    return {"ok": True, "pending": int(pending or 0), "dead": int(dead or 0)}


@router.post("/jobs/claim")
async def claim_jobs(payload: dict[str, Any]):
    """Atomically lease up to ``max_jobs`` pending jobs (priority then FIFO)."""
    tenant = await _authed_tenant(payload)
    async with await get_tenant_session(tenant) as db:
        jobs = await relay_queue.claim_jobs(
            db,
            max_jobs=int(payload.get("max_jobs", 10)),
            ttl_sec=int(payload.get("claim_ttl_sec", 120)),
            connector_id=str(payload.get("connector_id") or "connector"),
        )
    return {"jobs": jobs}


@router.post("/jobs/{job_id}/result")
async def report_result(job_id: uuid.UUID, payload: dict[str, Any]):
    """Report the outcome of pushing one job's XML to the local Tally."""
    tenant = await _authed_tenant(payload)
    async with await get_tenant_session(tenant) as db:
        result = await relay_queue.report_result(
            db,
            job_id=job_id,
            connector_id=str(payload.get("connector_id") or ""),
            success=bool(payload.get("success")),
            message=payload.get("message") or "",
            tally_response=payload.get("tally_response"),
        )
    if result.get("not_found"):
        raise HTTPException(404, "Job not found")
    return result


@router.get("/status")
async def connector_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Queue health for the Settings → Tally connector card (user JWT)."""
    cid = str(current_user.company_id)
    rows = (await db.execute(text(
        "SELECT status, count(*) AS c FROM tally_sync_jobs WHERE company_id=:cid GROUP BY status"
    ), {"cid": cid})).fetchall()
    counts = {r.status: r.c for r in rows}
    last_done = (await db.execute(text(
        "SELECT max(completed_at) FROM tally_sync_jobs WHERE company_id=:cid AND status='done'"
    ), {"cid": cid})).scalar()
    return {
        "counts": {s: int(counts.get(s, 0)) for s in ("pending", "in_progress", "done", "failed", "dead")},
        "last_done_at": last_done.isoformat() if last_done else None,
    }
