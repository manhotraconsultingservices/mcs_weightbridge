"""
Party balance recomputation — single source of truth for Party.current_balance.

`current_balance` is a denormalised convenience field shown on the Parties grid
and Customer 360. Rather than incrementally mutate it on every event (which
drifts — the old code only adjusted it on write-off, never on finalise /
payment / cancel / note), we RECOMPUTE it from source after any event that
changes a party's receivable/payable. Recompute is idempotent, so calling it
repeatedly is always safe and can never double-count.

Signed convention (matches the validated credit-status / Customer-360 logic):
  POSITIVE → the party owes us   (net receivable; typical for customers)
  NEGATIVE → we owe the party    (net payable;    typical for suppliers)

  current_balance =
      opening_balance
    + Σ finalised SALE      (grand_total − amount_paid − write_off_amount)
    − Σ finalised PURCHASE  (grand_total − amount_paid − write_off_amount)
    + Σ finalised DEBIT  notes  grand_total
    − Σ finalised CREDIT notes  grand_total

Using (grand_total − amount_paid − write_off_amount) handles both full and
partial write-offs correctly: a fully written-off invoice nets to 0; a partial
one nets to the still-collectable remainder.
"""
from decimal import Decimal

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice
from app.models.party import Party


async def recompute_party_balance(db: AsyncSession, party_id) -> Decimal | None:
    """Recompute and persist Party.current_balance from source data.

    Returns the new balance, or None if party_id is falsy / the party is gone.
    Does NOT commit — the caller's transaction owns the flush/commit.
    """
    if not party_id:
        return None
    party = await db.get(Party, party_id)
    if party is None:
        return None

    bal = Decimal(str(party.opening_balance or 0))

    # Sale / purchase outstanding, net of payments and write-offs.
    sp_rows = (await db.execute(
        select(
            Invoice.invoice_type,
            func.coalesce(func.sum(
                func.coalesce(Invoice.grand_total, 0)
                - func.coalesce(Invoice.amount_paid, 0)
                - func.coalesce(Invoice.write_off_amount, 0)
            ), 0).label("net"),
        )
        .where(
            Invoice.party_id == party_id,
            Invoice.status == "final",
            Invoice.invoice_type.in_(("sale", "purchase")),
        )
        .group_by(Invoice.invoice_type)
    )).all()
    for r in sp_rows:
        net = Decimal(str(r.net or 0))
        bal += net if r.invoice_type == "sale" else -net

    # Credit / debit notes — full value (a note is not "paid down"): debit +, credit −.
    note_rows = (await db.execute(
        select(
            Invoice.invoice_type,
            func.coalesce(func.sum(func.coalesce(Invoice.grand_total, 0)), 0).label("tot"),
        )
        .where(
            Invoice.party_id == party_id,
            Invoice.status == "final",
            Invoice.invoice_type.in_(("credit_note", "debit_note")),
        )
        .group_by(Invoice.invoice_type)
    )).all()
    for r in note_rows:
        tot = Decimal(str(r.tot or 0))
        bal += tot if r.invoice_type == "debit_note" else -tot

    party.current_balance = bal.quantize(Decimal("0.01"))
    return party.current_balance
