"""
Tally dispatch transport — the seam between "build the XML" and "send it".

Two transports, chosen per tenant by ``tally_config.mode`` (NULL → derive from
``MULTI_TENANT``):

  • DirectTransport (on-prem)  — POST the XML straight to the LAN Tally gateway
    (`TallyClient.push_xml`). Synchronous, confirmed.
  • RelayTransport  (SaaS)     — UPSERT a row into ``tally_sync_jobs`` for the
    LAN-side Tally Connector to drain. Returns "queued" (unconfirmed); the
    connector's later report flips the source row's ``tally_synced``.

All callers in ``routers/tally.py`` build the XML once with the existing builders
and dispatch through here, so the ledger map / GST guards / prefix filter /
``tally_synced`` semantics are unchanged.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import get_settings
from app.integrations.tally.client import TallyClient

# Masters before vouchers: a party ledger must exist in Tally before its voucher.
_PRIORITY = {"party": 10, "sales_order": 50, "purchase_order": 50, "invoice": 100}


@dataclass
class TallyDispatchResult:
    synced: bool                       # confirmed in Tally (direct mode only)
    queued: bool                       # accepted into the relay queue (SaaS)
    message: str
    job_id: uuid.UUID | None = None


def effective_mode(cfg) -> str:
    """Resolve the transport mode for a tenant.

    Explicit ``cfg.mode`` ('direct'|'relay') wins; otherwise derive from the
    deployment: cloud/multi-tenant → 'relay', single-tenant/on-prem → 'direct'.
    """
    m = (getattr(cfg, "mode", None) or "").strip().lower()
    if m in ("direct", "relay"):
        return m
    return "relay" if get_settings().MULTI_TENANT else "direct"


class DirectTransport:
    def __init__(self, cfg):
        self.cfg = cfg

    async def dispatch(self, *, entity_type: str, entity_id: uuid.UUID,
                       company_name: str, xml: str, idempotency_key: str,
                       db: AsyncSession) -> TallyDispatchResult:
        client = TallyClient(
            host=self.cfg.host or "localhost",
            port=self.cfg.port or 9002,
            company=company_name or "",
        )
        ok, msg = await client.push_xml(xml)
        return TallyDispatchResult(synced=ok, queued=False, message=msg)


class RelayTransport:
    def __init__(self, cfg):
        self.cfg = cfg

    async def dispatch(self, *, entity_type: str, entity_id: uuid.UUID,
                       company_name: str, xml: str, idempotency_key: str,
                       db: AsyncSession) -> TallyDispatchResult:
        from app.models.tally_job import TallySyncJob

        now = datetime.now(timezone.utc)
        priority = _PRIORITY.get(entity_type, 100)
        # UPSERT on (company_id, idempotency_key): re-dispatching a corrected
        # entity replaces the stale job and re-arms it (no duplicate row, no
        # double-import — the voucher GUID makes Tally ALTER, not duplicate).
        stmt = (
            pg_insert(TallySyncJob)
            .values(
                company_id=self.cfg.company_id,
                entity_type=entity_type,
                entity_id=entity_id,
                idempotency_key=idempotency_key,
                priority=priority,
                company_name=company_name or None,
                xml=xml,
                status="pending",
                attempts=0,
                next_attempt_at=now,
            )
            .on_conflict_do_update(
                index_elements=["company_id", "idempotency_key"],
                set_=dict(
                    status="pending",
                    attempts=0,
                    xml=xml,
                    priority=priority,
                    company_name=company_name or None,
                    next_attempt_at=now,
                    last_error=None,
                    tally_response=None,
                    claim_token=None,
                    claimed_until=None,
                    completed_at=None,
                ),
            )
            .returning(TallySyncJob.id)
        )
        job_id = (await db.execute(stmt)).scalar_one()
        return TallyDispatchResult(
            synced=False, queued=True, job_id=job_id,
            message="Queued for the local Tally connector.",
        )


def get_transport(cfg):
    """Return the transport for this tenant's config."""
    return RelayTransport(cfg) if effective_mode(cfg) == "relay" else DirectTransport(cfg)
