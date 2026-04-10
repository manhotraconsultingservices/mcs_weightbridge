"""Excel/CSV data import router — parties, products, vehicles."""
import io
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.company import Company
from app.models.party import Party
from app.models.product import Product, ProductCategory
from app.models.vehicle import Vehicle
from app.models.user import User

router = APIRouter(prefix="/api/v1/import", tags=["Data Import"])


async def _company_id(db: AsyncSession) -> uuid.UUID:
    co = (await db.execute(select(Company).limit(1))).scalar_one_or_none()
    if not co:
        raise HTTPException(404, "Company not found")
    return co.id


def _load_df(file_bytes: bytes, filename: str):
    """Load Excel or CSV into a list of dicts."""
    try:
        import openpyxl  # noqa: F401 (check it's installed)
        import pandas as pd
    except ImportError:
        raise HTTPException(500, "pandas/openpyxl not installed. Run: pip install pandas openpyxl")

    import pandas as pd

    if filename.lower().endswith(".csv"):
        df = pd.read_csv(io.BytesIO(file_bytes))
    else:
        df = pd.read_excel(io.BytesIO(file_bytes))

    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    return df.fillna("").to_dict(orient="records")


# ── Preview ───────────────────────────────────────────────────────────────────

@router.post("/preview/{entity}")
async def preview_import(
    entity: str,
    file: UploadFile = File(...),
    current_user: User = Depends(require_role("admin")),
):
    """Return first 10 rows + detected columns so user can confirm before importing."""
    if entity not in ("parties", "products", "vehicles"):
        raise HTTPException(400, "entity must be parties, products, or vehicles")

    content = await file.read()
    rows = _load_df(content, file.filename or "file.xlsx")

    return {
        "entity": entity,
        "total_rows": len(rows),
        "columns": list(rows[0].keys()) if rows else [],
        "preview": rows[:10],
    }


# ── Parties ───────────────────────────────────────────────────────────────────

@router.post("/parties")
async def import_parties(
    file: UploadFile = File(...),
    update_existing: bool = Form(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """
    Import parties from Excel/CSV.

    Required columns: name, party_type (customer/supplier/both)
    Optional: gstin, pan, phone, email, contact_person, billing_address,
              billing_city, billing_state, credit_limit, payment_terms_days
    """
    company_id = await _company_id(db)
    content = await file.read()
    rows = _load_df(content, file.filename or "file.xlsx")

    created = updated = skipped = 0
    errors = []

    for i, row in enumerate(rows, start=2):  # row 1 is header
        name = str(row.get("name", "")).strip()
        if not name:
            errors.append(f"Row {i}: name is required")
            skipped += 1
            continue

        party_type = str(row.get("party_type", "customer")).strip().lower()
        if party_type not in ("customer", "supplier", "both"):
            party_type = "customer"

        # Check existing by name
        existing = (await db.execute(
            select(Party).where(Party.company_id == company_id, Party.name == name)
        )).scalar_one_or_none()

        if existing and not update_existing:
            skipped += 1
            continue

        def _s(key, default=""):
            return str(row.get(key, default)).strip() or None

        def _f(key, default=0.0):
            try:
                return float(row.get(key, default) or default)
            except Exception:
                return default

        if existing:
            p = existing
            updated += 1
        else:
            p = Party(company_id=company_id)
            db.add(p)
            created += 1

        p.name = name
        p.party_type = party_type
        p.gstin = _s("gstin")
        p.pan = _s("pan")
        p.phone = _s("phone")
        p.email = _s("email")
        p.contact_person = _s("contact_person")
        p.billing_address = _s("billing_address")
        p.billing_city = _s("billing_city")
        p.billing_state = _s("billing_state")
        p.credit_limit = _f("credit_limit")
        p.payment_terms_days = int(_f("payment_terms_days", 0))

    await db.commit()
    return {
        "entity": "parties",
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "errors": errors[:20],
    }


# ── Products ──────────────────────────────────────────────────────────────────

@router.post("/products")
async def import_products(
    file: UploadFile = File(...),
    update_existing: bool = Form(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """
    Import products from Excel/CSV.

    Required columns: name
    Optional: category, hsn_code, unit, default_rate, gst_rate, code, description
    """
    company_id = await _company_id(db)
    content = await file.read()
    rows = _load_df(content, file.filename or "file.xlsx")

    # Cache category name → id map
    cat_rows = (await db.execute(
        select(ProductCategory).where(ProductCategory.company_id == company_id)
    )).scalars().all()
    cat_map = {c.name.lower(): c.id for c in cat_rows}

    created = updated = skipped = 0
    errors = []

    for i, row in enumerate(rows, start=2):
        name = str(row.get("name", "")).strip()
        if not name:
            errors.append(f"Row {i}: name is required")
            skipped += 1
            continue

        # Resolve or create category
        cat_name = str(row.get("category", "")).strip()
        cat_id = None
        if cat_name:
            cat_key = cat_name.lower()
            if cat_key not in cat_map:
                new_cat = ProductCategory(company_id=company_id, name=cat_name)
                db.add(new_cat)
                await db.flush()
                cat_map[cat_key] = new_cat.id
            cat_id = cat_map[cat_key]

        existing = (await db.execute(
            select(Product).where(Product.company_id == company_id, Product.name == name)
        )).scalar_one_or_none()

        if existing and not update_existing:
            skipped += 1
            continue

        def _s(key, default=""):
            return str(row.get(key, default)).strip() or None

        def _f(key, default=0.0):
            try:
                return float(row.get(key, default) or default)
            except Exception:
                return default

        if existing:
            p = existing
            updated += 1
        else:
            p = Product(company_id=company_id)
            db.add(p)
            created += 1

        p.name = name
        p.category_id = cat_id
        p.hsn_code = _s("hsn_code")
        p.unit = _s("unit") or "MT"
        p.default_rate = _f("default_rate")
        p.gst_rate = _f("gst_rate")
        p.code = _s("code")
        p.description = _s("description")

    await db.commit()
    return {
        "entity": "products",
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "errors": errors[:20],
    }


# ── Vehicles ──────────────────────────────────────────────────────────────────

@router.post("/vehicles")
async def import_vehicles(
    file: UploadFile = File(...),
    update_existing: bool = Form(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """
    Import vehicles from Excel/CSV.

    Required columns: registration_no
    Optional: vehicle_type, owner_name, owner_phone, default_tare_weight
    """
    company_id = await _company_id(db)
    content = await file.read()
    rows = _load_df(content, file.filename or "file.xlsx")

    created = updated = skipped = 0
    errors = []

    for i, row in enumerate(rows, start=2):
        reg = str(row.get("registration_no", "")).strip().upper()
        if not reg:
            errors.append(f"Row {i}: registration_no is required")
            skipped += 1
            continue

        existing = (await db.execute(
            select(Vehicle).where(Vehicle.company_id == company_id, Vehicle.registration_no == reg)
        )).scalar_one_or_none()

        if existing and not update_existing:
            skipped += 1
            continue

        def _s(key, default=""):
            return str(row.get(key, default)).strip() or None

        def _f(key, default=0.0):
            try:
                return float(row.get(key, default) or default)
            except Exception:
                return default

        if existing:
            v = existing
            updated += 1
        else:
            v = Vehicle(company_id=company_id)
            db.add(v)
            created += 1

        v.registration_no = reg
        v.vehicle_type = _s("vehicle_type") or "truck"
        v.owner_name = _s("owner_name")
        v.owner_phone = _s("owner_phone")
        v.default_tare_weight = _f("default_tare_weight")

    await db.commit()
    return {
        "entity": "vehicles",
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "errors": errors[:20],
    }


# ── Template download ─────────────────────────────────────────────────────────

@router.get("/template/{entity}")
async def download_template(
    entity: str,
    current_user: User = Depends(get_current_user),
):
    """Download a blank Excel template for the given entity."""
    try:
        import pandas as pd
    except ImportError:
        raise HTTPException(500, "pandas not installed")

    templates = {
        "parties": ["name", "party_type", "gstin", "pan", "phone", "email",
                    "contact_person", "billing_address", "billing_city",
                    "billing_state", "credit_limit", "payment_terms_days"],
        "products": ["name", "category", "hsn_code", "unit", "default_rate",
                     "gst_rate", "code", "description"],
        "vehicles": ["registration_no", "vehicle_type", "owner_name",
                     "owner_phone", "default_tare_weight"],
    }

    if entity not in templates:
        raise HTTPException(400, "entity must be parties, products, or vehicles")

    df = pd.DataFrame(columns=templates[entity])
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    buf.seek(0)

    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={entity}_template.xlsx"},
    )
