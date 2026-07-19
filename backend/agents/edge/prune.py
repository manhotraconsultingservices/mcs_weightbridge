"""Conditional prune of the edge SQLite store — the safe half of the 04:00 job.

The plan's hard rule: **never wipe the SQLite file.** Three things must never be
deleted — unsynced intents (a truck that physically crossed the bridge), and,
once we keep them, number leases + the master mirror. So this is a CONDITIONAL
prune, not a reset:

  * If ANY intent is not yet 'done' (pending / needs_review / needs_auth) →
    **skip the prune entirely**, log loudly, and (if configured) fire a Telegram
    alert. Better to keep a slightly larger DB than to lose a weighment.
  * Otherwise everything local is already on the cloud (the source of truth), so
    delete synced intents older than `retain_days` **measured from sync time**
    (intents.synced_at, not created_at — an intent created at 23:00 and synced at
    09:00 survives the next 04:00) and local tokens/invoices/gate-passes older
    than `retain_days`, then VACUUM to reclaim space.

Size makes this unnecessary for disk pressure (~500 KB/day worst case) — it just
keeps the file tidy. The permanent audit trail lives server-side in
sync_operations, so short local retention costs nothing.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from agents.edge.db import get_engine, get_sessionmaker

log = logging.getLogger("edge.prune")


@dataclass
class PruneResult:
    pruned: bool = False
    reason: str = ""
    unsynced: int = 0
    intents_deleted: int = 0
    tokens_deleted: int = 0
    detail: dict[str, Any] = field(default_factory=dict)


async def unsynced_count(db) -> int:
    """Intents not yet confirmed applied on the cloud (anything but 'done')."""
    return int((await db.execute(text(
        "SELECT COUNT(*) FROM intents WHERE status != 'done'"
    ))).scalar() or 0)


async def prune(session_factory: async_sessionmaker, db_path: str,
                retain_days: int = 7) -> PruneResult:
    """Run the conditional prune. Never raises for a business reason — returns a
    PruneResult the caller can log / alert on."""
    res = PruneResult()

    async with session_factory() as db:
        res.unsynced = await unsynced_count(db)
        if res.unsynced > 0:
            res.reason = f"skipped — {res.unsynced} unsynced intent(s) still in the spool"
            log.warning("prune %s", res.reason)
            return res

        cutoff = f"-{int(retain_days)} days"
        # 1. synced intents older than retain_days (by SYNC time).
        r = await db.execute(text(
            "DELETE FROM intents WHERE status='done' AND synced_at IS NOT NULL "
            "AND synced_at < datetime('now', :c)"), {"c": cutoff})
        res.intents_deleted = r.rowcount or 0

        # 2. old local tokens + their dependents (all synced — guarded above).
        #    Delete children first (FK: invoice_items → invoices → tokens; gate_passes → tokens).
        old = "token_date < date('now', :c)"
        await db.execute(text(
            f"DELETE FROM invoice_items WHERE invoice_id IN "
            f"(SELECT id FROM invoices WHERE token_id IN (SELECT id FROM tokens WHERE {old}))"), {"c": cutoff})
        await db.execute(text(
            f"DELETE FROM invoices WHERE token_id IN (SELECT id FROM tokens WHERE {old})"), {"c": cutoff})
        await db.execute(text(
            f"DELETE FROM gate_passes WHERE token_id IN (SELECT id FROM tokens WHERE {old})"), {"c": cutoff})
        rt = await db.execute(text(f"DELETE FROM tokens WHERE {old}"), {"c": cutoff})
        res.tokens_deleted = rt.rowcount or 0
        await db.commit()

    # 3. VACUUM — must run OUTSIDE a transaction (AUTOCOMMIT connection).
    try:
        engine = get_engine(db_path)
        vac = await engine.connect()
        vac = await vac.execution_options(isolation_level="AUTOCOMMIT")
        await vac.exec_driver_sql("VACUUM")
        await vac.close()
        res.detail["vacuum"] = "ok"
    except Exception as e:                       # a failed VACUUM is non-fatal
        res.detail["vacuum"] = f"skipped: {type(e).__name__}: {e}"
        log.warning("prune: VACUUM failed — %s", e)

    res.pruned = True
    res.reason = f"pruned {res.intents_deleted} intent(s) + {res.tokens_deleted} token(s) older than {retain_days}d"
    log.info("prune %s", res.reason)
    return res


async def run(cfg: dict[str, Any]) -> PruneResult:
    """Entry point for the scheduled prune (called at/after the 04:00 restart)."""
    from agents.edge.db import init_db
    await init_db(cfg["db_path"])
    sf = get_sessionmaker()
    retain = int(cfg.get("retain_days", 7))
    result = await prune(sf, cfg["db_path"], retain)

    if not result.pruned:
        # Loud + optional Telegram alert so a skipped prune (unsynced work still
        # pending) is never silent.
        await _alert_skip(cfg, result)
    return result


async def _alert_skip(cfg: dict[str, Any], result: PruneResult) -> None:
    token = cfg.get("telegram_bot_token")
    chat = cfg.get("telegram_chat_id")
    if not (token and chat):
        return
    try:
        import httpx
        tag = cfg.get("terminal_tag", "B1")
        msg = (f"⚠️ Weighbridge edge [{tag}]: 04:00 prune SKIPPED — "
               f"{result.unsynced} unsynced weighment(s) still waiting to sync. "
               f"Local data kept. Check the link / review queue.")
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(f"https://api.telegram.org/bot{token}/sendMessage",
                         json={"chat_id": chat, "text": msg})
    except Exception as e:
        log.warning("prune: Telegram skip-alert failed — %s", e)


def main() -> None:  # pragma: no cover — CLI entry for the Scheduled Task
    import asyncio
    from agents.edge.config import load_config
    result = asyncio.run(run(load_config()))
    print(f"[edge-prune] {'PRUNED' if result.pruned else 'SKIPPED'}: {result.reason}")


if __name__ == "__main__":  # pragma: no cover
    main()
