"""Background sync loop — mirror-pull + intent-replay, driven on a timer.

One cycle:
  1. Pull the masters snapshot and upsert it into the local mirror. This doubles
     as the reachability probe: if it fails, the link is down, so we do NOT
     attempt replay this cycle (a half-up link would just churn transient
     errors and bump attempt counters).
  2. Drain the intent spool to the cloud in strict order (``replay.replay``),
     which halts at the first unresolved intent — nothing is ever dropped.

The loop is intentionally simple and idempotent: the cloud dedupes replays by
``client_op_id`` and the mirror upsert is ON-CONFLICT, so running a cycle twice
is harmless. A missed cycle is caught by the next one.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from agents.edge import cloud, intents, mirror, replay
from agents.edge.db import get_sessionmaker

log = logging.getLogger("edge.sync")


async def sync_once(cfg: dict[str, Any]) -> dict[str, Any]:
    """Run one mirror+replay cycle. Never raises — returns a status dict."""
    sf = get_sessionmaker()
    out: dict[str, Any] = {"online": False, "mirror": None, "replay": None, "error": None}

    # 1. Mirror pull (also the reachability probe).
    try:
        snapshot = await cloud.fetch_masters(cfg)
        out["mirror"] = await mirror.apply_snapshot(sf, snapshot)
        out["online"] = True
    except Exception as e:                              # offline / half-up — skip replay
        out["error"] = f"masters: {type(e).__name__}: {e}"
        log.info("sync: masters pull failed (offline?) — %s", e)
        return out

    # 2. Replay the spool, in order.
    try:
        summary = await replay.replay(sf, cloud.make_push(cfg))
        out["replay"] = {"synced": summary.synced,
                         "halted_on": summary.halted_on, "reason": summary.reason}
        if summary.synced:
            log.info("sync: replayed %d intent(s)%s", summary.synced,
                     f", halted on {summary.reason}" if summary.halted_on else "")
    except Exception as e:
        out["error"] = f"replay: {type(e).__name__}: {e}"
        log.exception("sync: replay cycle failed")
    return out


async def run_loop(cfg: dict[str, Any], stop: asyncio.Event, *, interval: float = 30.0) -> None:
    """Run ``sync_once`` every ``interval`` seconds until ``stop`` is set."""
    log.info("edge sync loop started (every %ss)", interval)
    while not stop.is_set():
        try:
            await sync_once(cfg)
        except Exception:
            log.exception("sync: unexpected cycle failure")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
    log.info("edge sync loop stopped")


async def pending_summary() -> dict[str, int]:
    """Spool depth by status — for the agent status page."""
    sf = get_sessionmaker()
    async with sf() as db:
        return await intents.counts(db)
