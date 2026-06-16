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

    DESIGN NOTE — gaps are expected and accepted. Unlike token_no (assigned at
    COMPLETED) and invoice_no (assigned at FINALISE), the gate pass is issued at
    gate ENTRY, i.e. the instant a token is created. A token that is later
    cancelled/abandoned (or an accidental double-submit) therefore leaves a hole
    in the GP sequence — that hole corresponds to a real "truck arrived at the
    gate" event, so the number is genuinely consumed and is NOT reclaimed. The
    sequence is gap-FREE at the point of allocation (no two trucks share a
    number); it is not gap-LESS over time. This is intentional.
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


async def next_doc_no(
    db: AsyncSession,
    company_id: uuid.UUID,
    fy_id: uuid.UUID,
    sequence_type: str,
    prefix: str,
    *,
    width: int = 4,
    reset_daily: bool = False,
) -> str:
    """Generic gap-free, row-locked document-number allocator.

    Format: ``{prefix}/{YY-YY}/{NNNN}`` (e.g. ``DC/25-26/0001``). One shared
    implementation for every new document series (delivery challan, credit
    note, debit note, …) so they all get the same FY-scoped, ``WITH FOR
    UPDATE`` row-locked, gap-free behaviour as invoice numbering. Allocated
    inside the caller's transaction — rolls back with it on error.
    """
    result = await db.execute(
        select(NumberSequence)
        .where(
            NumberSequence.company_id == company_id,
            NumberSequence.fy_id == fy_id,
            NumberSequence.sequence_type == sequence_type,
        )
        .with_for_update()
    )
    seq = result.scalar_one_or_none()
    if not seq:
        seq = NumberSequence(
            company_id=company_id, fy_id=fy_id,
            sequence_type=sequence_type, prefix=prefix,
            last_number=0, reset_daily=reset_daily,
        )
        db.add(seq)
    seq.last_number += 1
    await db.flush()
    fy = await db.get(FinancialYear, fy_id)
    short_fy = fy.label[-5:] if fy and fy.label else "25-26"
    return f"{prefix}/{short_fy}/{seq.last_number:0{width}d}"
