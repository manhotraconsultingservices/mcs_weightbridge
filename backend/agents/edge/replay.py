"""Replay the edge intent spool to the cloud, in order.

Same safety invariant as the browser offline-queue fix: an intent is NEVER
dropped because the server rejected it. Ordering is load-bearing — the
duplicate-active-token guard and the create→weigh dependency both require strict
order — so any UNRESOLVED outcome HALTS the drain rather than skipping ahead.

`push` is injected (the HTTP transport) so this logic is unit-testable without a
network. It is an async callable(intent: dict) -> PushResult.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy.ext.asyncio import async_sessionmaker

from agents.edge import intents


@dataclass
class PushResult:
    status: Optional[int]          # HTTP status, or None on a network error
    body: Optional[dict[str, Any]] = None
    error: Optional[str] = None


PushFn = Callable[[dict], Awaitable[PushResult]]


@dataclass
class ReplaySummary:
    synced: int = 0
    halted_on: Optional[str] = None     # op_id we stopped at, if any
    reason: Optional[str] = None        # 'needs_review' | 'needs_auth' | 'transient'


async def replay(session_factory: async_sessionmaker, push: PushFn,
                 has_session: bool = True) -> ReplaySummary:
    """Drain pending intents in seq order. Stops at the first unresolved one."""
    summary = ReplaySummary()

    async with session_factory() as db:
        items = await intents.pending_intents(db)

    for item in items:
        # A previously parked item blocks the queue — do not skip ahead to a
        # later pending intent (that would replay a weight out of order).
        if item["status"] == "needs_review":
            summary.halted_on = item["op_id"]
            summary.reason = "needs_review"
            return summary

        result = await push(item)
        status = result.status

        async with session_factory() as db:
            if status is not None and 200 <= status < 300:
                await intents.mark(db, item["op_id"], "done",
                                   assigned=result.body, bump_attempts=True)
                await db.commit()
                summary.synced += 1
                continue

            if status in (401, 403):
                # Session expired / not permitted — pause the whole queue, keep it.
                await intents.mark(db, item["op_id"], "needs_auth",
                                   last_error=result.error or f"HTTP {status}",
                                   bump_attempts=True)
                await db.commit()
                summary.halted_on = item["op_id"]
                summary.reason = "needs_auth"
                return summary

            if status is not None and 400 <= status < 500 and status not in (408, 429):
                # Server refused it (409/422/…). A real weighment — park for a
                # human, never delete; halt to preserve order.
                await intents.mark(db, item["op_id"], "needs_review",
                                   last_error=result.error or f"HTTP {status}",
                                   bump_attempts=True)
                await db.commit()
                summary.halted_on = item["op_id"]
                summary.reason = "needs_review"
                return summary

            # Network error, timeout, 408/429 or 5xx — transient. Leave pending,
            # count the attempt, and stop (retry the whole run later).
            await intents.mark(db, item["op_id"], "pending",
                               last_error=result.error or (f"HTTP {status}" if status else "network"),
                               bump_attempts=True)
            await db.commit()
            summary.halted_on = item["op_id"]
            summary.reason = "transient"
            return summary

    return summary
