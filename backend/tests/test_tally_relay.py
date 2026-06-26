"""
Tally SaaS relay path — DB-backed integration test (real Postgres).

Exercises the queue mechanics end-to-end without the FastAPI/auth layer:
  • RelayTransport.dispatch enqueues + UPSERT idempotency (no duplicate)
  • relay_queue.claim_jobs leases in priority (masters-first) then FIFO order
  • relay_queue.report_result: success → done (+ flips source tally_synced),
    failure → pending with backoff, failure at max_attempts → dead

Style matches the existing suite: sync test fn driving one ``asyncio.run`` flow.
Skips cleanly if the dev DB has no `companies` row. Rows are isolated by a
unique per-run tag and deleted at the end.
"""
import asyncio
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

from app.config import get_settings
from app.ddl import get_runtime_ddl, get_column_migrations
from app.integrations.tally import relay_queue
from app.integrations.tally.transport import RelayTransport


async def _ensure_schema(db: AsyncSession) -> None:
    """Create tally_sync_jobs + the mode column if this DB predates them."""
    for stmt in get_runtime_ddl():
        if "tally_sync_jobs" in stmt:
            await db.execute(text(stmt))
    for stmt in get_column_migrations():
        if "tally_config" in stmt and "mode" in stmt:
            await db.execute(text(stmt))
    await db.commit()


async def _run() -> str:
    engine = create_async_engine(get_settings().DATABASE_URL)
    tag = uuid.uuid4().hex[:8]
    party_eid = uuid.uuid4()
    inv_eid = uuid.uuid4()
    dead_eid = uuid.uuid4()
    keys = (f"party:{party_eid}", f"invoice:{inv_eid}", f"purchase_order:{dead_eid}")
    try:
        async with AsyncSession(engine) as db:
            await _ensure_schema(db)
            cid = (await db.execute(text("SELECT id FROM companies LIMIT 1"))).scalar()
            if cid is None:
                return "SKIP: no company row in dev DB"

            cfg = SimpleNamespace(company_id=cid, mode="relay")
            t = RelayTransport(cfg)

            # 1) enqueue a party (priority 10) + an invoice (priority 100)
            await t.dispatch(entity_type="party", entity_id=party_eid, company_name="Relay Test Co",
                             xml="<P/>", idempotency_key=keys[0], db=db)
            await t.dispatch(entity_type="invoice", entity_id=inv_eid, company_name="Relay Test Co",
                             xml="<I/>", idempotency_key=keys[1], db=db)
            await db.commit()
            rows = (await db.execute(text(
                "SELECT entity_type, priority, status FROM tally_sync_jobs "
                "WHERE idempotency_key = ANY(:k) ORDER BY priority"
            ), {"k": list(keys[:2])})).fetchall()
            assert [r.entity_type for r in rows] == ["party", "invoice"], rows
            assert [r.priority for r in rows] == [10, 100], rows
            assert all(r.status == "pending" for r in rows)

            # 2) idempotency — re-dispatch the party (same key) → still ONE row, re-armed
            await t.dispatch(entity_type="party", entity_id=party_eid, company_name="Relay Test Co",
                             xml="<P-v2/>", idempotency_key=keys[0], db=db)
            await db.commit()
            n_party = (await db.execute(text(
                "SELECT count(*), max(xml) FROM tally_sync_jobs WHERE idempotency_key=:k"
            ), {"k": keys[0]})).fetchone()
            assert n_party[0] == 1, "UPSERT must not duplicate"
            assert n_party[1] == "<P-v2/>", "UPSERT must replace the XML"

            # 3) claim — masters first: party (10) before invoice (100)
            claimed = await relay_queue.claim_jobs(db, max_jobs=10, ttl_sec=120, connector_id="c1")
            mine = [j for j in claimed if j["entity_id"] in (str(party_eid), str(inv_eid))]
            assert [j["entity_type"] for j in mine] == ["party", "invoice"], mine
            assert all(j["attempts"] == 1 for j in mine)
            # both now in_progress → a re-claim returns neither
            again = await relay_queue.claim_jobs(db, max_jobs=10, ttl_sec=120, connector_id="c1")
            assert not [j for j in again if j["entity_id"] in (str(party_eid), str(inv_eid))]

            party_job_id = uuid.UUID(next(j["id"] for j in mine if j["entity_type"] == "party"))
            inv_job_id = uuid.UUID(next(j["id"] for j in mine if j["entity_type"] == "invoice"))

            # 4) success → done; failure → pending + future backoff
            r_ok = await relay_queue.report_result(db, job_id=party_job_id, connector_id="c1", success=True)
            assert r_ok["status"] == "done", r_ok
            r_fail = await relay_queue.report_result(db, job_id=inv_job_id, connector_id="c1",
                                                     success=False, message="boom")
            assert r_fail["status"] == "pending", r_fail
            nxt = (await db.execute(text(
                "SELECT next_attempt_at > now() FROM tally_sync_jobs WHERE id=:id"
            ), {"id": str(inv_job_id)})).scalar()
            assert nxt is True, "failed job must back off into the future"

            # 5) dead-letter: a job already at max_attempts + reported failure → dead
            await t.dispatch(entity_type="purchase_order", entity_id=dead_eid, company_name="Relay Test Co",
                             xml="<PO/>", idempotency_key=keys[2], db=db)
            await db.execute(text(
                "UPDATE tally_sync_jobs SET status='in_progress', attempts=max_attempts, claim_token='c1' "
                "WHERE idempotency_key=:k"
            ), {"k": keys[2]})
            await db.commit()
            dead_id = (await db.execute(text(
                "SELECT id FROM tally_sync_jobs WHERE idempotency_key=:k"
            ), {"k": keys[2]})).scalar()

            # 6) stale-claim guard FIRST (lease still held by 'c1') — a report
            # from a different connector is ignored, not applied.
            r_stale = await relay_queue.report_result(db, job_id=dead_id, connector_id="someone-else",
                                                      success=True)
            assert r_stale.get("ignored") is True, r_stale

            # then the real owner reports failure at max_attempts → dead
            r_dead = await relay_queue.report_result(db, job_id=dead_id, connector_id="c1",
                                                     success=False, message="give up")
            assert r_dead["status"] == "dead", r_dead

            return "OK"
        # end session
    finally:
        # cleanup our rows only
        async with AsyncSession(engine) as db2:
            await db2.execute(text("DELETE FROM tally_sync_jobs WHERE idempotency_key = ANY(:k)"),
                              {"k": list(keys)})
            await db2.commit()
        await engine.dispose()


def test_relay_queue_end_to_end():
    result = asyncio.run(_run())
    if isinstance(result, str) and result.startswith("SKIP"):
        pytest.skip(result)
    assert result == "OK"
