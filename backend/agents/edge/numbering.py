"""Offline number allocation for the edge agent.

Two numbers are minted offline; INVOICE numbers are NOT (the client chose
approve-offline / number-at-sync, so the server mints the GST number when the
intent replays — nothing here touches invoices).

- token_no: the server picks a RANDOM 4-digit number, so it needs no shared
  counter. Offline terminals draw from the reserved 9000–9999 band while the
  server draws 1000–8999, making a cross-source collision structurally
  impossible. The server re-checks the band at sync as a backstop.

- gate_pass_no: a per-terminal LOCAL daily sequence, e.g. GP/2026-07-19/B1-007.
  The terminal tag (B1) keeps two terminals' numbers disjoint. Kept as-issued at
  sync — gate passes already tolerate gaps, so no lease/rewind is needed.
"""
from __future__ import annotations

import random
from datetime import date

from sqlalchemy import and_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Token

OFFLINE_TOKEN_MIN = 9000
OFFLINE_TOKEN_MAX = 9999


async def next_token_no(db: AsyncSession, company_id, token_date: date) -> int:
    """A free token number in the offline band for this company + day."""
    for _ in range(200):
        candidate = random.randint(OFFLINE_TOKEN_MIN, OFFLINE_TOKEN_MAX)
        exists = await db.execute(
            select(Token.id).where(and_(
                Token.company_id == company_id,
                Token.token_date == token_date,
                Token.token_no == candidate,
            ))
        )
        if exists.scalar_one_or_none() is None:
            return candidate
    # Band exhausted for the day (>1000 offline tokens) — extremely unlikely.
    # Fall back to a deterministic scan so we never loop forever.
    for candidate in range(OFFLINE_TOKEN_MIN, OFFLINE_TOKEN_MAX + 1):
        exists = await db.execute(
            select(Token.id).where(and_(
                Token.company_id == company_id,
                Token.token_date == token_date,
                Token.token_no == candidate,
            ))
        )
        if exists.scalar_one_or_none() is None:
            return candidate
    raise RuntimeError("offline token band 9000–9999 exhausted for the day")


async def next_gate_pass_no(db: AsyncSession, company_id, terminal_tag: str,
                            pass_date: date) -> str:
    """Allocate the next local gate-pass number for this terminal + day.

    Single-writer on SQLite, so a plain read-modify-write inside the caller's
    transaction is already serialised — no row lock needed. Uses the existing
    gate_pass_daily_seq table (composite PK company_id + pass_date), namespacing
    the terminal via the printed tag rather than a separate counter.
    """
    row = await db.execute(text(
        "SELECT last_no FROM gate_pass_daily_seq "
        "WHERE company_id = :cid AND pass_date = :d"
    ), {"cid": str(company_id), "d": pass_date.isoformat()})
    last = row.scalar_one_or_none()
    if last is None:
        await db.execute(text(
            "INSERT INTO gate_pass_daily_seq (company_id, pass_date, last_no) "
            "VALUES (:cid, :d, 1)"
        ), {"cid": str(company_id), "d": pass_date.isoformat()})
        seq = 1
    else:
        seq = int(last) + 1
        await db.execute(text(
            "UPDATE gate_pass_daily_seq SET last_no = :n "
            "WHERE company_id = :cid AND pass_date = :d"
        ), {"n": seq, "cid": str(company_id), "d": pass_date.isoformat()})
    tag = (terminal_tag or "B1").strip() or "B1"
    return f"GP/{pass_date.isoformat()}/{tag}-{seq:03d}"
