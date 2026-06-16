"""Royalty / Mining Transit-Pass router (Horizon 2).

Tracks government royalty / e-transit passes and reconciles authorised quantity
against inbound purchase loads consumed against each pass.

P2: CSV import from eRavanna / Form-H government portal exports.
    Tolerant column-name mapping handles every variant we've seen in the wild.
    Endpoint: POST /passes/import-csv
    Background: check_royalty_unaccounted() fires after each purchase-token completion.
"""
import csv
import io
import json
import uuid
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import select, func, text as _sql
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.company import Company, FinancialYear
from app.models.party import Party
from app.models.royalty import RoyaltyPass, RoyaltyPassConsumption
from app.models.token import Token
from app.models.user import User
from app.schemas.royalty import (
    RoyaltyPassCreate, RoyaltyPassUpdate, RoyaltyPassResponse, RoyaltyPassListResponse,
    ConsumeRequest, ConsumptionResponse, RoyaltyReconciliation,
)

# ── P2 CSV column aliases ────────────────────────────────────────────────────
# Keys = our field names; values = all column header variants we know from
# eRavanna (Karnataka), Form-H (MMDR), HMMS (Telangana), ARIS (AP), etc.
_CSV_ALIASES: dict[str, list[str]] = {
    "pass_no": [
        "eravanna number", "eravanna no", "e-ravanna no", "e ravanna number",
        "pass no", "pass number", "permit number", "permit no",
        "transit pass no", "transit pass number", "form h no", "form-h no",
        "ravanna number", "pass id", "permit id", "pass_no",
    ],
    "issue_date": [
        "issue date", "date of issue", "issued date", "issue_date",
        "date issued", "permit date", "issued on", "issue on",
        "generated date", "date of generation",
    ],
    "valid_till": [
        "valid till", "validity date", "valid upto", "valid up to",
        "expiry date", "expiry", "validity", "valid_till",
        "validity upto", "expiry till", "permit valid upto",
    ],
    "source_name": [
        "quarry name", "source name", "quarry/source", "mine name",
        "lessor name", "quarry", "lease holder", "source",
        "quarry/mine", "lessee name", "site name", "regd. quarry name",
    ],
    "mineral": [
        "minor mineral", "mineral", "material", "mineral name",
        "minor mineral name", "commodity", "material name",
    ],
    "vehicle_no": [
        "vehicle no", "vehicle number", "veh no", "vehicle_no",
        "veh. no", "vehicle", "vehicle reg no", "veh. reg. no",
    ],
    "quantity_mt": [
        "quantity (mt)", "qty (mt)", "permitted qty", "permitted qty (mt)",
        "quantity mt", "qty mt", "quantity", "qty",
        "weight (mt)", "quantity in mt", "qty. (mt)",
        "volume (mt)", "permitted quantity (mt)", "permitted quantity",
        "dispatched quantity (mt)", "quantity (in mt)",
    ],
    "rate": [
        "rate", "rate (₹/mt)", "royalty rate", "rate per mt",
        "rate/mt", "r/mt", "royalty rate (₹/mt)", "rate (rs./mt)",
    ],
    "amount": [
        "amount", "total amount", "royalty amount", "royalty (₹)",
        "royalty amt", "royalty paid", "amount (₹)", "total",
        "total royalty", "royalty fee", "mineral value",
    ],
    "pass_type": ["pass type", "type", "permit type", "pass_type"],
    "notes": ["notes", "remarks", "remark", "note", "comments", "narration"],
}

_PASS_TYPE_MAP: dict[str, str] = {
    "royalty": "royalty", "e_transit": "e_transit",
    "e-transit": "e_transit", "transit": "e_transit",
    "mineral_permit": "mineral_permit", "permit": "mineral_permit",
    "mineral permit": "mineral_permit", "eravanna": "e_transit",
    "e ravanna": "e_transit", "form h": "royalty",
    "form-h": "royalty",
}

# Alert config defaults (stored in app_settings under key 'royalty_alert_config')
_ROYALTY_ALERT_DEFAULT: dict = {
    "enabled": True,
    "unaccounted_threshold_mt": 50.0,
    "check_on_purchase_complete": True,
}

# In-memory de-dup: prevents repeated alerts within the same calendar day
_last_royalty_alert: dict[str, date] = {}


def _resolve_csv_cols(fieldnames: list[str]) -> dict[str, str | None]:
    """Map our field names → actual CSV header strings using the alias table."""
    lowered = {h.strip().lower(): h for h in fieldnames}
    result: dict[str, str | None] = {k: None for k in _CSV_ALIASES}
    for field, aliases in _CSV_ALIASES.items():
        for alias in aliases:
            if alias in lowered:
                result[field] = lowered[alias]
                break
    return result


def _parse_indian_date(s: str) -> date | None:
    """Parse Indian date strings: DD/MM/YYYY, DD-MM-YYYY, YYYY-MM-DD, etc."""
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d.%m.%Y",
                "%d/%m/%y", "%d-%m-%y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def _parse_csv_decimal(s: str) -> Decimal:
    """Tolerant decimal parser: handles commas, ₹ prefix, spaces."""
    s = (s or "").strip().replace(",", "").replace("₹", "").replace(" ", "")
    try:
        return Decimal(s) if s else Decimal("0")
    except Exception:
        return Decimal("0")

router = APIRouter(prefix="/api/v1/royalty", tags=["Royalty / Transit Pass"])


async def _company_fy(db: AsyncSession):
    co = (await db.execute(select(Company).limit(1))).scalar_one_or_none()
    fy = (await db.execute(
        select(FinancialYear).where(FinancialYear.is_active == True).limit(1)
    )).scalar_one_or_none()
    return co, fy


async def _load(db: AsyncSession, pass_id: uuid.UUID) -> RoyaltyPass:
    p = (await db.execute(
        select(RoyaltyPass).options(selectinload(RoyaltyPass.consumptions))
        .where(RoyaltyPass.id == pass_id)
    )).scalar_one_or_none()
    if not p:
        raise HTTPException(404, "Royalty pass not found")
    return p


async def _to_response(db: AsyncSession, p: RoyaltyPass) -> RoyaltyPassResponse:
    resp = RoyaltyPassResponse.model_validate(p)
    consumed = sum((c.quantity_mt or Decimal("0")) for c in p.consumptions)
    qty = p.quantity_mt or Decimal("0")
    resp.consumed_mt = consumed
    resp.balance_mt = qty - consumed
    resp.utilization_pct = float(round((consumed / qty * 100), 1)) if qty > 0 else 0.0
    if p.valid_till:
        resp.days_to_expiry = (p.valid_till - date.today()).days
    # Reflect derived status without persisting on read
    if p.status == "active" and p.valid_till and p.valid_till < date.today():
        resp.status = "expired"
    if p.party_id:
        resp.party_name = (await db.execute(select(Party.name).where(Party.id == p.party_id))).scalar_one_or_none()
    return resp


@router.post("/passes", response_model=RoyaltyPassResponse, status_code=201)
async def create_pass(
    payload: RoyaltyPassCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    co, fy = await _company_fy(db)
    if not co:
        raise HTTPException(500, "Company not configured")
    p = RoyaltyPass(
        company_id=co.id, fy_id=fy.id if fy else None,
        pass_no=payload.pass_no.strip(),
        pass_type=payload.pass_type or "royalty",
        source_name=payload.source_name,
        party_id=payload.party_id,
        mineral=payload.mineral,
        product_id=payload.product_id,
        issue_date=payload.issue_date,
        valid_till=payload.valid_till,
        quantity_mt=Decimal(str(payload.quantity_mt or 0)),
        rate=Decimal(str(payload.rate or 0)),
        amount=Decimal(str(payload.amount or 0)),
        vehicle_no=(payload.vehicle_no or "").upper().strip() or None,
        notes=payload.notes,
        status="active",
        created_by=current_user.id,
    )
    db.add(p)
    await db.commit()
    p = await _load(db, p.id)
    return await _to_response(db, p)


@router.get("/passes", response_model=RoyaltyPassListResponse)
async def list_passes(
    status: str | None = None,
    pass_type: str | None = None,
    party_id: uuid.UUID | None = None,
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(RoyaltyPass).where(RoyaltyPass.company_id == current_user.company_id)
    if status:
        stmt = stmt.where(RoyaltyPass.status == status)
    if pass_type:
        stmt = stmt.where(RoyaltyPass.pass_type == pass_type)
    if party_id:
        stmt = stmt.where(RoyaltyPass.party_id == party_id)
    if search:
        like = f"%{search.upper()}%"
        stmt = stmt.where(
            func.upper(RoyaltyPass.pass_no).like(like)
            | func.upper(func.coalesce(RoyaltyPass.source_name, "")).like(like)
        )
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    rows = (await db.execute(
        stmt.options(selectinload(RoyaltyPass.consumptions))
        .order_by(RoyaltyPass.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()
    items = [await _to_response(db, p) for p in rows]
    return RoyaltyPassListResponse(items=items, total=int(total))


@router.get("/passes/{pass_id}", response_model=RoyaltyPassResponse)
async def get_pass(pass_id: uuid.UUID, db: AsyncSession = Depends(get_db),
                   current_user: User = Depends(get_current_user)):
    return await _to_response(db, await _load(db, pass_id))


@router.put("/passes/{pass_id}", response_model=RoyaltyPassResponse)
async def update_pass(
    pass_id: uuid.UUID, payload: RoyaltyPassUpdate,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user),
):
    p = await _load(db, pass_id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    await db.commit()
    return await _to_response(db, await _load(db, pass_id))


@router.post("/passes/{pass_id}/cancel", response_model=RoyaltyPassResponse)
async def cancel_pass(pass_id: uuid.UUID, db: AsyncSession = Depends(get_db),
                      current_user: User = Depends(get_current_user)):
    p = await _load(db, pass_id)
    p.status = "cancelled"
    await db.commit()
    return await _to_response(db, await _load(db, pass_id))


@router.post("/passes/{pass_id}/consume", response_model=RoyaltyPassResponse)
async def consume(
    pass_id: uuid.UUID, payload: ConsumeRequest,
    db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user),
):
    """Record a consumption against a pass (an inbound load drawn from it)."""
    p = await _load(db, pass_id)
    if p.status == "cancelled":
        raise HTTPException(400, "Cannot consume against a cancelled pass")
    qty = Decimal(str(payload.quantity_mt or 0))
    if qty <= 0:
        raise HTTPException(400, "quantity_mt must be greater than zero")

    # Compute current balance for variance tracking
    consumed_so_far = sum((c.quantity_mt or Decimal("0")) for c in p.consumptions)
    balance = (p.quantity_mt or Decimal("0")) - consumed_so_far

    # authorized_mt = what the pass could cover; actual_mt = what the truck actually brought
    auth_mt = payload.authorized_mt if payload.authorized_mt is not None else (min(qty, balance) if balance > 0 else qty)
    actual_mt = payload.actual_mt if payload.actual_mt is not None else qty
    variance_mt = actual_mt - auth_mt  # >0 = overrun (truck brought more than pass allowed)

    db.add(RoyaltyPassConsumption(
        pass_id=p.id, company_id=p.company_id,
        token_id=payload.token_id, invoice_id=payload.invoice_id,
        quantity_mt=qty,
        authorized_mt=auth_mt,
        actual_mt=actual_mt,
        variance_mt=variance_mt,
        vehicle_no=payload.vehicle_no,
        consumed_date=payload.consumed_date or date.today(),
        notes=payload.notes, created_by=current_user.id,
    ))
    await db.flush()
    # Auto-exhaust when balance hits zero (overrun still allowed but flagged)
    new_consumed = consumed_so_far + qty
    if p.quantity_mt and new_consumed >= p.quantity_mt and p.status == "active":
        p.status = "exhausted"
    await db.commit()
    return await _to_response(db, await _load(db, pass_id))


@router.get("/passes/{pass_id}/consumptions", response_model=list[ConsumptionResponse])
async def get_consumptions(
    pass_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Full consumption history for a pass, with token_no joined from tokens."""
    rows = (await db.execute(
        select(RoyaltyPassConsumption)
        .where(RoyaltyPassConsumption.pass_id == pass_id)
        .order_by(RoyaltyPassConsumption.consumed_date.desc(), RoyaltyPassConsumption.created_at.desc())
    )).scalars().all()

    # Batch-fetch token_no for any token_id references
    token_ids = [c.token_id for c in rows if c.token_id]
    token_no_map: dict[uuid.UUID, int | None] = {}
    if token_ids:
        t_rows = (await db.execute(
            select(Token.id, Token.token_no).where(Token.id.in_(token_ids))
        )).all()
        token_no_map = {r.id: r.token_no for r in t_rows}

    result = []
    for c in rows:
        r = ConsumptionResponse.model_validate(c)
        r.token_no = token_no_map.get(c.token_id) if c.token_id else None
        result.append(r)
    return result


@router.get("/reconciliation", response_model=RoyaltyReconciliation)
async def reconciliation(
    date_from: date = Query(...),
    date_to: date = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = current_user.company_id
    agg = (await db.execute(
        select(
            func.coalesce(func.sum(RoyaltyPass.quantity_mt), 0),
            func.coalesce(func.sum(RoyaltyPass.amount), 0),
        ).where(
            RoyaltyPass.company_id == cid,
            RoyaltyPass.status != "cancelled",
            RoyaltyPass.issue_date >= date_from, RoyaltyPass.issue_date <= date_to,
        )
    )).first()
    authorised = agg[0] if agg else 0
    total_royalty_amount = float(agg[1]) if agg else 0.0

    consumed = (await db.execute(
        select(func.coalesce(func.sum(RoyaltyPassConsumption.quantity_mt), 0)).where(
            RoyaltyPassConsumption.company_id == cid,
            RoyaltyPassConsumption.consumed_date >= date_from,
            RoyaltyPassConsumption.consumed_date <= date_to,
        )
    )).scalar() or 0
    # Purchase inbound = completed purchase tokens' net weight (kg → MT)
    inbound_kg = (await db.execute(
        select(func.coalesce(func.sum(Token.net_weight), 0)).where(
            Token.company_id == cid,
            Token.token_type == "purchase",
            Token.status == "COMPLETED",
            Token.token_date >= date_from, Token.token_date <= date_to,
        )
    )).scalar() or 0
    inbound_mt = float(inbound_kg) / 1000.0

    from datetime import timedelta
    soon = date.today() + timedelta(days=30)
    counts = (await db.execute(
        select(
            func.count(),
            func.count().filter(RoyaltyPass.status == "active"),
            func.count().filter(
                (RoyaltyPass.valid_till != None)  # noqa: E711
                & (RoyaltyPass.valid_till >= date.today())
                & (RoyaltyPass.valid_till <= soon)
            ),
        ).where(RoyaltyPass.company_id == cid, RoyaltyPass.status != "cancelled")
    )).first()

    return RoyaltyReconciliation(
        date_from=date_from, date_to=date_to,
        authorised_mt=float(authorised), consumed_mt=float(consumed),
        purchase_inbound_mt=round(inbound_mt, 3),
        balance_mt=float(authorised) - float(consumed),
        unaccounted_mt=round(inbound_mt - float(consumed), 3),
        total_royalty_amount=round(total_royalty_amount, 2),
        pass_count=int(counts[0] or 0),
        active_count=int(counts[1] or 0),
        expiring_count=int(counts[2] or 0),
    )


@router.get("/alerts", response_model=RoyaltyPassListResponse)
async def alerts(
    within_days: int = Query(15, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Passes expiring within N days (or already expired) and not cancelled/exhausted."""
    from datetime import timedelta
    horizon = date.today() + timedelta(days=within_days)
    rows = (await db.execute(
        select(RoyaltyPass).options(selectinload(RoyaltyPass.consumptions))
        .where(
            RoyaltyPass.company_id == current_user.company_id,
            RoyaltyPass.status == "active",
            RoyaltyPass.valid_till != None,  # noqa: E711
            RoyaltyPass.valid_till <= horizon,
        )
        .order_by(RoyaltyPass.valid_till.asc())
    )).scalars().all()
    items = [await _to_response(db, p) for p in rows]
    return RoyaltyPassListResponse(items=items, total=len(items))


# ── P2: eRavanna / Form-H CSV import ─────────────────────────────────────────

@router.post("/passes/import-csv")
async def import_passes_csv(
    file: UploadFile = File(...),
    skip_duplicates: bool = Query(True, description="Skip rows whose pass_no already exists"),
    dry_run: bool = Query(False, description="Parse + validate only; do not write to DB"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Import royalty/transit passes from an eRavanna or Form-H portal CSV export.

    Tolerant column-name mapping covers Karnataka DMG (eRavanna), HMMS
    (Telangana), ARIS (Andhra Pradesh), and generic Form-H formats.
    Returns {imported, skipped, errors, columns_detected, sample}.
    """
    try:
        raw = await file.read()
        text_content = raw.decode("utf-8-sig")  # strips Excel BOM
    except Exception:
        raise HTTPException(400, "Could not read the uploaded file. Please upload a UTF-8 or Excel CSV.")

    try:
        reader = csv.DictReader(io.StringIO(text_content))
        if not reader.fieldnames:
            raise HTTPException(400, "CSV file appears to be empty or has no header row.")
        cols = _resolve_csv_cols(list(reader.fieldnames))
        all_rows = list(reader)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"Could not parse CSV: {e}")

    if not cols["pass_no"]:
        found = ", ".join(list(reader.fieldnames or [])[:10])
        raise HTTPException(
            400,
            f"Could not detect the pass-number column. Columns found: {found}. "
            "Expected: 'eRavanna Number', 'Pass No', 'Permit Number', or similar."
        )

    co, fy = await _company_fy(db)
    if not co:
        raise HTTPException(500, "Company not configured")

    # Pre-load existing pass numbers for O(1) duplicate check
    existing_nos: set[str] = set(
        r[0] for r in (await db.execute(
            select(RoyaltyPass.pass_no).where(RoyaltyPass.company_id == co.id)
        )).all()
    )

    imported, skipped = 0, 0
    errors: list[dict] = []
    new_passes: list[RoyaltyPass] = []

    for row_num, row in enumerate(all_rows, start=2):  # row 1 = header
        def _cell(field: str) -> str:
            col = cols.get(field)
            return (row.get(col, "") or "").strip() if col else ""

        pass_no = _cell("pass_no")
        if not pass_no:
            errors.append({"row": row_num, "error": "Empty pass number — row skipped."})
            continue

        if skip_duplicates and pass_no in existing_nos:
            skipped += 1
            continue

        pt_raw = _cell("pass_type").lower().strip()
        pass_type = _PASS_TYPE_MAP.get(pt_raw, "royalty")

        qty = _parse_csv_decimal(_cell("quantity_mt"))

        p = RoyaltyPass(
            company_id=co.id,
            fy_id=fy.id if fy else None,
            pass_no=pass_no,
            pass_type=pass_type,
            source_name=_cell("source_name") or None,
            mineral=_cell("mineral") or None,
            vehicle_no=(_cell("vehicle_no").upper().replace(" ", "") or None),
            issue_date=_parse_indian_date(_cell("issue_date")),
            valid_till=_parse_indian_date(_cell("valid_till")),
            quantity_mt=qty,
            rate=_parse_csv_decimal(_cell("rate")),
            amount=_parse_csv_decimal(_cell("amount")),
            notes=_cell("notes") or None,
            status="active",
            created_by=current_user.id,
        )
        new_passes.append(p)
        existing_nos.add(pass_no)   # prevent intra-batch duplicates
        imported += 1

    if not dry_run and new_passes:
        for p in new_passes:
            db.add(p)
        await db.commit()

    return {
        "imported": imported if not dry_run else 0,
        "previewed": imported if dry_run else 0,
        "skipped": skipped,
        "error_count": len(errors),
        "errors": errors[:20],  # cap to keep response small
        "total_rows": len(all_rows),
        "columns_detected": {k: v for k, v in cols.items() if v},
        "dry_run": dry_run,
        "sample": [
            {
                "pass_no": p.pass_no,
                "pass_type": p.pass_type,
                "source_name": p.source_name,
                "mineral": p.mineral,
                "vehicle_no": p.vehicle_no,
                "quantity_mt": str(p.quantity_mt),
                "issue_date": p.issue_date.isoformat() if p.issue_date else None,
                "valid_till": p.valid_till.isoformat() if p.valid_till else None,
            }
            for p in new_passes[:10]
        ],
    }


# ── P2: Reconciliation alert config ──────────────────────────────────────────

_ALERT_KEY = "royalty_alert_config"


@router.get("/alert-config")
async def get_alert_config(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return current unaccounted-MT alert config (merged with defaults)."""
    row = (await db.execute(_sql(
        "SELECT value FROM app_settings WHERE key = :k"
    ), {"k": _ALERT_KEY})).fetchone()
    cfg = dict(_ROYALTY_ALERT_DEFAULT)
    if row:
        try:
            cfg.update(json.loads(row[0]))
        except Exception:
            pass
    return cfg


@router.put("/alert-config")
async def update_alert_config(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Save unaccounted-MT alert threshold. Admin only."""
    await db.execute(_sql("""
        INSERT INTO app_settings (key, value, updated_at)
        VALUES (:k, :v, NOW())
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
    """), {"k": _ALERT_KEY, "v": json.dumps(payload)})
    await db.commit()
    return {**_ROYALTY_ALERT_DEFAULT, **payload}


# ── P2: Background unaccounted-MT check ──────────────────────────────────────

async def check_royalty_unaccounted(
    db: AsyncSession,
    company_id: uuid.UUID,
    token_date: date,
) -> None:
    """Compute today's unaccounted MT and send Telegram if threshold is crossed.

    Called as a BackgroundTask after every purchase token completion.
    In-memory de-dup fires at most once per company per calendar day.
    """
    cid_str = str(company_id)
    today = date.today()

    # Daily de-dup
    if _last_royalty_alert.get(cid_str) == today:
        return

    # Load config
    row = (await db.execute(_sql(
        "SELECT value FROM app_settings WHERE key = :k"
    ), {"k": _ALERT_KEY})).fetchone()
    cfg = dict(_ROYALTY_ALERT_DEFAULT)
    if row:
        try:
            cfg.update(json.loads(row[0]))
        except Exception:
            pass

    if not cfg.get("enabled", True):
        return

    threshold = float(cfg.get("unaccounted_threshold_mt", 50.0))

    # Consumed MT today across all passes
    consumed = (await db.execute(
        select(func.coalesce(func.sum(RoyaltyPassConsumption.quantity_mt), 0)).where(
            RoyaltyPassConsumption.company_id == company_id,
            RoyaltyPassConsumption.consumed_date == today,
        )
    )).scalar() or 0

    # Inbound purchase MT today (kg → MT)
    inbound_kg = (await db.execute(
        select(func.coalesce(func.sum(Token.net_weight), 0)).where(
            Token.company_id == company_id,
            Token.token_type == "purchase",
            Token.status == "COMPLETED",
            Token.token_date == today,
        )
    )).scalar() or 0

    inbound_mt = float(inbound_kg) / 1000.0
    unaccounted_mt = round(inbound_mt - float(consumed), 3)

    if unaccounted_mt < threshold:
        return

    co = (await db.execute(
        select(Company).where(Company.id == company_id).limit(1)
    )).scalar_one_or_none()

    # Mark de-dup BEFORE sending so a send error doesn't re-trigger immediately
    _last_royalty_alert[cid_str] = today

    try:
        from app.integrations.notifications.service import send_notification
        ctx = {
            "date": today.strftime("%d-%m-%Y"),
            "inbound_mt": f"{inbound_mt:.3f}",
            "consumed_mt": f"{float(consumed):.3f}",
            "unaccounted_mt": f"{unaccounted_mt:.3f}",
            "threshold_mt": f"{threshold:.1f}",
            "company_name": co.name if co else "—",
        }
        await send_notification(db, company_id, "royalty_unaccounted_alert", ctx,
                                entity_type="company", entity_id=str(company_id))
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Royalty unaccounted alert send failed: %s", exc)
