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
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db, get_tenant_session
from app.dependencies import get_current_user, require_role
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


async def _rebuild_invoice_job_xml(db, job) -> bool:
    """Rebuild a queued invoice/CN/DN job's voucher XML from the CURRENT Tally
    config. Lets a job queued before a config change (e.g. before "Accounting
    vouchers (no inventory)" was switched on) self-heal instead of replaying the
    stale, rejected voucher forever. Returns True if rebuilt. Swallows errors and
    falls back to the stored XML."""
    if job is None or job.entity_type not in ("invoice", "credit_note", "debit_note"):
        return False
    try:
        from sqlalchemy import select as _select
        from app.routers.tally import _get_config, _get_company, _build_invoice_xml
        from app.models.invoice import Invoice
        inv = (await db.execute(
            _select(Invoice).where(Invoice.id == job.entity_id)
        )).scalar_one_or_none()
        if inv is None:
            return False
        cfg = await _get_config(db, job.company_id)
        company = await _get_company(db, job.company_id)
        new_xml, _err = await _build_invoice_xml(inv, company, cfg, db)
        if new_xml and new_xml != job.xml:
            job.xml = new_xml
            job.company_name = (getattr(cfg, "tally_company_name", None)
                                or getattr(company, "name", None) or job.company_name)
            return True
    except Exception as e:
        logging.getLogger(__name__).warning("rebuild job %s failed: %s", getattr(job, "id", "?"), e)
    return False


@router.post("/jobs/{job_id}/result")
async def report_result(job_id: uuid.UUID, payload: dict[str, Any]):
    """Report the outcome of pushing one job's XML to the local Tally."""
    tenant = await _authed_tenant(payload)
    success = bool(payload.get("success"))
    async with await get_tenant_session(tenant) as db:
        result = await relay_queue.report_result(
            db,
            job_id=job_id,
            connector_id=str(payload.get("connector_id") or ""),
            success=success,
            message=payload.get("message") or "",
            tally_response=payload.get("tally_response"),
        )
        # On a retryable failure, rebuild the voucher from CURRENT config so a
        # stale invoice job (queued before a config change) heals on its next try.
        if not success and result.get("status") == "pending":
            from sqlalchemy import select
            from app.models.tally_job import TallySyncJob
            job = (await db.execute(
                select(TallySyncJob).where(TallySyncJob.id == job_id)
            )).scalar_one_or_none()
            if job is not None and await _rebuild_invoice_job_xml(db, job):
                await db.commit()
    if result.get("not_found"):
        raise HTTPException(404, "Job not found")
    # Mirror failures into the server journal so a stuck job is visible from the
    # VPS too (the connector log is on the client's LAN PC).
    if not bool(payload.get("success")):
        logging.getLogger(__name__).warning(
            "Tally relay job %s FAILED (tenant=%s → status=%s): %s",
            job_id, tenant, result.get("status"), (payload.get("message") or "")[:400],
        )
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


@router.get("/jobs")
async def list_jobs(
    status: str = "",
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List relay jobs for the Settings UI (filter by comma-separated status)."""
    clauses = ["company_id = :cid"]
    params = {"cid": str(current_user.company_id), "lim": max(1, min(int(limit), 200))}
    statuses = [s.strip() for s in (status or "").split(",") if s.strip()]
    if statuses:
        clauses.append("status = ANY(:st)")
        params["st"] = statuses
    rows = (await db.execute(text(
        "SELECT id, entity_type, entity_id, status, attempts, max_attempts, priority, "
        "last_error, created_at, completed_at, next_attempt_at "
        f"FROM tally_sync_jobs WHERE {' AND '.join(clauses)} ORDER BY created_at DESC LIMIT :lim"
    ), params)).fetchall()

    def _iso(d):
        return d.isoformat() if d else None
    return {"jobs": [{
        "id": str(r.id), "entity_type": r.entity_type, "entity_id": str(r.entity_id),
        "status": r.status, "attempts": r.attempts, "max_attempts": r.max_attempts,
        "priority": r.priority, "last_error": r.last_error,
        "created_at": _iso(r.created_at), "completed_at": _iso(r.completed_at),
        "next_attempt_at": _iso(r.next_attempt_at),
    } for r in rows]}


@router.post("/jobs/{job_id}/requeue")
async def requeue_job(
    job_id: uuid.UUID,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Re-arm a dead/failed (or stuck-pending) job so the connector retries it.

    For invoice / credit-note / debit-note jobs the voucher XML is **rebuilt from
    the CURRENT Tally config** first — so a job queued before a config change
    (e.g. before "No-GST / accounting-only" was switched on) is regenerated
    correctly instead of replaying the stale, possibly Tally-crashing voucher.
    Falls back to re-arming the stored XML if the rebuild can't run.
    """
    import logging
    from datetime import datetime, timezone
    from sqlalchemy import select
    from app.models.tally_job import TallySyncJob

    job = (await db.execute(
        select(TallySyncJob).where(
            TallySyncJob.id == job_id,
            TallySyncJob.company_id == current_user.company_id,
            TallySyncJob.status.in_(["dead", "failed", "pending"]),
        )
    )).scalar_one_or_none()
    if not job:
        raise HTTPException(404, "Job not found or not re-queueable")

    rebuilt = await _rebuild_invoice_job_xml(db, job)

    job.status = "pending"
    job.attempts = 0
    job.last_error = None
    job.claim_token = None
    job.claimed_until = None
    job.next_attempt_at = datetime.now(timezone.utc)
    await db.commit()
    return {"ok": True, "id": str(job_id), "status": "pending", "rebuilt": rebuilt}
