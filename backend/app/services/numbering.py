"""Shared gap-free numbering helpers.

Single source of truth for sequence allocation that must be gap-free and
concurrency-safe (row-locked). Used by both the ANPR router (gate pass on
auto entry) and the token router (gate pass on manual entry) so the two
paths can never diverge or hand out a duplicate number.
"""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import FinancialYear
from app.models.settings import NumberSequence


async def next_gate_pass_no(
    db: AsyncSession, company_id: uuid.UUID, fy_id: uuid.UUID
) -> str:
    """Allocate the next gap-free gate-pass number under the current FY.

    Format: ``GP/25-26/0001``. Row-locks the NumberSequence row
    (``WITH FOR UPDATE``) so two concurrent entries — whether from ANPR
    detection or a manual token create — can never get the same number.
    Allocated once at gate ENTRY and reused for the matching EXIT.
    """
    result = await db.execute(
        select(NumberSequence)
        .where(
            NumberSequence.company_id == company_id,
            NumberSequence.fy_id == fy_id,
            NumberSequence.sequence_type == "gate_pass",
        )
        .with_for_update()
    )
    seq = result.scalar_one_or_none()
    if not seq:
        seq = NumberSequence(
            company_id=company_id, fy_id=fy_id,
            sequence_type="gate_pass", prefix="GP",
            last_number=0, reset_daily=False,
        )
        db.add(seq)
    seq.last_number += 1
    await db.flush()
    fy = await db.get(FinancialYear, fy_id)
    short_fy = fy.label[-5:] if fy and fy.label else "25-26"
    return f"GP/{short_fy}/{seq.last_number:04d}"
