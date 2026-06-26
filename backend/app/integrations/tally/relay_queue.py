"""
Tally relay queue operations (SaaS/relay mode).

The claim + report logic that drains ``tally_sync_jobs``. Kept here (not inline
in the router) so it is DRY and unit-testable against a real Postgres without
the FastAPI/auth layer. The connector router is a thin agent-key-authed wrapper
around these.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tally_job import TallySyncJob

# entity_type → source table whose tally_synced flips on success.
_SOURCE_TABLE = {
    "invoice": "invoices",
    "party": "parties",
    "sales_order": "quotations",
    "purchase_order": "inventory_purchase_orders",
}

_MAX_BACKOFF_SEC = 1800   # 30 min cap


async def claim_jobs(db: AsyncSession, *, max_jobs: int, ttl_sec: int,
                     connector_id: str) -> list[dict]:
    """Atomically lease up to ``max_jobs`` pending jobs (priority then FIFO).

    Re-surfaces jobs whose lease expired, then claims with FOR UPDATE SKIP LOCKED
    so concurrent connectors never grab the same row. Commits and returns the
    claimed jobs' payloads.
    """
    max_jobs = max(1, min(int(max_jobs), 50))
    ttl_sec = max(15, min(int(ttl_sec), 1800))
    connector_id = str(connector_id or "connector")[:64]

    # Expired leases → back to pending (a connector died mid-flight).
    await db.execute(text(
        "UPDATE tally_sync_jobs SET status='pending', claim_token=NULL, claimed_until=NULL "
        "WHERE status='in_progress' AND claimed_until IS NOT NULL AND claimed_until < now()"
    ))
    rows = (await db.execute(text("""
        WITH claimed AS (
            SELECT id FROM tally_sync_jobs
            WHERE status='pending' AND next_attempt_at <= now()
            ORDER BY priority ASC, created_at ASC
            LIMIT :n
            FOR UPDATE SKIP LOCKED
        )
        UPDATE tally_sync_jobs j
        SET status='in_progress', picked_at=now(), attempts=attempts+1,
            claim_token=:ct, claimed_until=now() + make_interval(secs => :ttl)
        FROM claimed
        WHERE j.id = claimed.id
        RETURNING j.id, j.entity_type, j.entity_id, j.company_name, j.xml,
                  j.attempts, j.priority, j.created_at
    """), {"n": max_jobs, "ct": connector_id, "ttl": ttl_sec})).fetchall()
    await db.commit()

    # RETURNING does not preserve the CTE's ORDER BY — re-sort so the connector
    # processes masters (low priority) before vouchers (the masters-first rule).
    rows = sorted(rows, key=lambda r: (r.priority, r.created_at))
    return [
        {
            "id": str(r.id),
            "entity_type": r.entity_type,
            "entity_id": str(r.entity_id),
            "company_name": r.company_name,
            "xml": r.xml,
            "attempts": r.attempts,
            "priority": r.priority,
        }
        for r in rows
    ]


async def report_result(db: AsyncSession, *, job_id: uuid.UUID, connector_id: str,
                        success: bool, message: str = "",
                        tally_response: str | None = None) -> dict:
    """Apply a connector's result. On success: mark done + flip the source row's
    ``tally_synced``. On failure: dead (>= max_attempts) or pending with backoff.
    """
    job = (await db.execute(
        select(TallySyncJob).where(TallySyncJob.id == job_id)
    )).scalar_one_or_none()
    if job is None:
        return {"ok": False, "not_found": True}
    # Ignore a stale report from a job that was already re-leased to someone else.
    if job.claim_token and connector_id and job.claim_token != connector_id:
        return {"ok": False, "ignored": True, "reason": "stale claim", "status": job.status}

    now = datetime.now(timezone.utc)
    if success:
        job.status = "done"
        job.completed_at = now
        job.tally_response = (tally_response or "")[:8000] or None
        job.last_error = None
        job.claim_token = None
        job.claimed_until = None
        table = _SOURCE_TABLE.get(job.entity_type)
        if table:
            await db.execute(
                text(f"UPDATE {table} SET tally_synced=TRUE, tally_sync_at=:ts WHERE id=:id"),
                {"ts": now, "id": str(job.entity_id)},
            )
    else:
        job.last_error = (message or "")[:2000]
        job.tally_response = (tally_response or "")[:8000] or None
        job.claim_token = None
        job.claimed_until = None
        if job.attempts >= job.max_attempts:
            job.status = "dead"
        else:
            job.status = "pending"
            delay = min(2 ** job.attempts * 15, _MAX_BACKOFF_SEC)  # 30s, 60s, … capped 30 min
            job.next_attempt_at = now + timedelta(seconds=delay)
    # Capture before commit — commit may expire ORM attributes, and reading
    # job.status afterwards would trigger an implicit (sync) reload.
    final_status = job.status
    await db.commit()
    return {"ok": True, "status": final_status}
