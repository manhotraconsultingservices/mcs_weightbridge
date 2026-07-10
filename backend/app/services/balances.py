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

Advances / prepayments:
  A payment recorded with no (or partial) invoice allocation leaves an
  *unallocated remainder* = receipt.amount − Σ its InvoicePayment.amount. That
  remainder is an advance the party has paid us (customer) or we've prepaid the
  party (supplier). It reduces the net balance:
      − Σ unallocated RECEIPT remainder   (customer advance → they owe us less / credit)
      + Σ unallocated VOUCHER remainder   (supplier prepayment → we owe them less)
  This nets to zero double-counting: once an advance is later allocated to an
  invoice, that amount moves into Invoice.amount_paid (raising the invoice's paid
  portion) while the receipt remainder drops by the same amount — the balance is
  invariant under allocation.
"""
from decimal import Decimal

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice
from app.models.party import Party
from app.models.payment import PaymentReceipt, PaymentVoucher, InvoicePayment


async def party_advance_remaining(db: AsyncSession, party_id) -> dict:
    """Return a party's unallocated advance remainders.

    {"receipt_adv": <customer advance ₹>, "voucher_adv": <supplier prepayment ₹>}

    receipt_adv = Σ receipts.amount − Σ InvoicePayment.amount(receipt side).
    voucher_adv = Σ vouchers.amount − Σ InvoicePayment.amount(voucher side).
    Both clamped ≥ 0 (allocations can never exceed the payment amount — enforced
    by _validate_allocations — so a negative here would be a data error).
    """
    if not party_id:
        return {"receipt_adv": Decimal("0"), "voucher_adv": Decimal("0")}

    rec_total = (await db.execute(
        select(func.coalesce(func.sum(PaymentReceipt.amount), 0))
        .where(PaymentReceipt.party_id == party_id)
    )).scalar() or 0
    rec_alloc = (await db.execute(
        select(func.coalesce(func.sum(InvoicePayment.amount), 0))
        .join(PaymentReceipt, InvoicePayment.receipt_id == PaymentReceipt.id)
        .where(PaymentReceipt.party_id == party_id)
    )).scalar() or 0
    receipt_adv = Decimal(str(rec_total)) - Decimal(str(rec_alloc))

    vou_total = (await db.execute(
        select(func.coalesce(func.sum(PaymentVoucher.amount), 0))
        .where(PaymentVoucher.party_id == party_id)
    )).scalar() or 0
    vou_alloc = (await db.execute(
        select(func.coalesce(func.sum(InvoicePayment.amount), 0))
        .join(PaymentVoucher, InvoicePayment.voucher_id == PaymentVoucher.id)
        .where(PaymentVoucher.party_id == party_id)
    )).scalar() or 0
    voucher_adv = Decimal(str(vou_total)) - Decimal(str(vou_alloc))

    return {
        "receipt_adv": max(Decimal("0"), receipt_adv).quantize(Decimal("0.01")),
        "voucher_adv": max(Decimal("0"), voucher_adv).quantize(Decimal("0.01")),
    }


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

    # Advances / prepayments — the unallocated remainder of receipts/vouchers.
    #   customer receipt advance → they owe us less (credit): subtract
    #   supplier voucher prepayment → we owe them less: add
    adv = await party_advance_remaining(db, party_id)
    bal -= adv["receipt_adv"]
    bal += adv["voucher_adv"]

    party.current_balance = bal.quantize(Decimal("0.01"))
    return party.current_balance
