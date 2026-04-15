"""
Compliance management: Insurance, Certifications, Licenses, Permits.
Stores document paths and expiry dates with configurable alert thresholds.
"""
import json
import uuid
from datetime import date, datetime, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from pydantic import BaseModel
from sqlalchemy import select, and_, or_, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.user import User
from app.models.compliance import ComplianceItem
from app.models.company import Company
from app.utils.r2_storage import upload_to_r2, is_r2_configured

router = APIRouter(prefix="/api/v1/compliance", tags=["compliance"])


# ── Schemas ──────────────────────────────────────────────────────────────── #

class ComplianceItemCreate(BaseModel):
    item_type: str
    name: str
    policy_holder: Optional[str] = None
    issuer: Optional[str] = None
    reference_no: Optional[str] = None
    issue_date: Optional[date] = None
    expiry_date: Optional[date] = None
    file_path: Optional[str] = None
    notes: Optional[str] = None


class ComplianceItemUpdate(BaseModel):
    item_type: Optional[str] = None
    name: Optional[str] = None
    policy_holder: Optional[str] = None
    issuer: Optional[str] = None
    reference_no: Optional[str] = None
    issue_date: Optional[date] = None
    expiry_date: Optional[date] = None
    file_path: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class ComplianceItemResponse(BaseModel):
    id: uuid.UUID
    item_type: str
    name: str
    policy_holder: Optional[str] = None
    issuer: Optional[str]
    reference_no: Optional[str]
    issue_date: Optional[date]
    expiry_date: Optional[date]
    file_path: Optional[str]
    notes: Optional[str]
    is_active: bool
    days_to_expiry: Optional[int]
    alert_level: Optional[str]
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class ComplianceListResponse(BaseModel):
    items: List[ComplianceItemResponse]
    total: int


class ComplianceThresholds(BaseModel):
    warning_days: int = 60
    critical_days: int = 30


# ── Settings keys ─────────────────────────────────────────────────────────── #

_WARNING_KEY  = "compliance.warning_days"
_CRITICAL_KEY = "compliance.critical_days"
_TYPES_KEY    = "compliance.item_types"

DEFAULT_TYPES = ["insurance", "certification", "license", "permit"]


# ── Helpers ──────────────────────────────────────────────────────────────── #

async def _get_thresholds(db: AsyncSession) -> tuple[int, int]:
    """Return (warning_days, critical_days) from app_settings, falling back to defaults."""
    try:
        rows = (await db.execute(
            text("SELECT key, value FROM app_settings WHERE key IN (:w, :c)"),
            {"w": _WARNING_KEY, "c": _CRITICAL_KEY},
        )).fetchall()
        mapping = {r[0]: int(r[1]) for r in rows}
        return mapping.get(_WARNING_KEY, 60), mapping.get(_CRITICAL_KEY, 30)
    except Exception:
        return 60, 30


async def _upsert_setting(db: AsyncSession, key: str, value: str) -> None:
    await db.execute(
        text("""
            INSERT INTO app_settings (key, value)
            VALUES (:key, :value)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """),
        {"key": key, "value": value},
    )


async def _get_types(db: AsyncSession) -> list[str]:
    """Return the configured compliance item types (falls back to defaults)."""
    try:
        row = (await db.execute(
            text("SELECT value FROM app_settings WHERE key = :k"), {"k": _TYPES_KEY}
        )).fetchone()
        if row:
            return json.loads(row[0])
    except Exception:
        pass
    return DEFAULT_TYPES


def _compute_alert(
    expiry_date: Optional[date],
    critical_days: int = 30,
    warning_days: int = 60,
) -> tuple[Optional[int], Optional[str]]:
    """Return (days_to_expiry, alert_level)."""
    if not expiry_date:
        return None, None
    delta = (expiry_date - date.today()).days
    if delta < 0:
        level = "expired"
    elif delta <= critical_days:
        level = "critical"
    elif delta <= warning_days:
        level = "warning"
    else:
        level = "ok"
    return delta, level


def _to_response(item: ComplianceItem, critical_days: int = 30, warning_days: int = 60) -> ComplianceItemResponse:
    days, level = _compute_alert(item.expiry_date, critical_days, warning_days)
    return ComplianceItemResponse(
        id=item.id,
        item_type=item.item_type,
        name=item.name,
        policy_holder=getattr(item, "policy_holder", None),
        issuer=item.issuer,
        reference_no=item.reference_no,
        issue_date=item.issue_date,
        expiry_date=item.expiry_date,
        file_path=item.file_path,
        notes=item.notes,
        is_active=item.is_active,
        days_to_expiry=days,
        alert_level=level,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


async def _get_company(db: AsyncSession) -> Company:
    co = (await db.execute(select(Company).limit(1))).scalar_one_or_none()
    if not co:
        raise HTTPException(500, "Company not configured")
    return co


# ── Threshold endpoints (must be before /{item_id}) ───────────────────────── #

@router.get("/settings/thresholds", response_model=ComplianceThresholds)
async def get_thresholds(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    warning_days, critical_days = await _get_thresholds(db)
    return ComplianceThresholds(warning_days=warning_days, critical_days=critical_days)


@router.put("/settings/thresholds", response_model=ComplianceThresholds)
async def update_thresholds(
    payload: ComplianceThresholds,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    if payload.critical_days < 1 or payload.warning_days < 1:
        raise HTTPException(400, "Days must be at least 1")
    if payload.critical_days >= payload.warning_days:
        raise HTTPException(400, "Critical days must be less than warning days")

    # Ensure app_settings table exists
    await db.execute(text("""
        CREATE TABLE IF NOT EXISTS app_settings (
            key VARCHAR(100) PRIMARY KEY,
            value TEXT NOT NULL
        )
    """))
    await _upsert_setting(db, _WARNING_KEY, str(payload.warning_days))
    await _upsert_setting(db, _CRITICAL_KEY, str(payload.critical_days))
    await db.commit()
    return payload


# ── Item Types endpoints ───────────────────────────────────────────────────── #

@router.get("/settings/types")
async def get_item_types(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the list of compliance item type strings."""
    return await _get_types(db)


@router.put("/settings/types")
async def update_item_types(
    payload: List[str],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Replace the compliance item types list (admin only)."""
    cleaned = [t.strip().lower() for t in payload if t.strip()]
    if not cleaned:
        raise HTTPException(400, "At least one type is required")
    await _upsert_setting(db, _TYPES_KEY, json.dumps(cleaned))
    await db.commit()
    return cleaned


# ── Endpoints ─────────────────────────────────────────────────────────────── #

@router.get("", response_model=ComplianceListResponse)
async def list_compliance(
    item_type: Optional[str] = None,
    alert_only: bool = False,
    include_inactive: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    co = await _get_company(db)
    warning_days, critical_days = await _get_thresholds(db)

    filters = [ComplianceItem.company_id == co.id]
    if not include_inactive:
        filters.append(ComplianceItem.is_active == True)
    if item_type:
        filters.append(ComplianceItem.item_type == item_type)
    if alert_only:
        threshold = date.today() + timedelta(days=warning_days)
        filters.append(
            or_(
                ComplianceItem.expiry_date <= threshold,
                ComplianceItem.expiry_date < date.today(),
            )
        )

    rows = (await db.execute(
        select(ComplianceItem)
        .where(and_(*filters))
        .order_by(ComplianceItem.expiry_date.asc().nulls_last(), ComplianceItem.name.asc())
    )).scalars().all()

    return ComplianceListResponse(
        items=[_to_response(r, critical_days, warning_days) for r in rows],
        total=len(rows),
    )


@router.post("", response_model=ComplianceItemResponse, status_code=201)
async def create_compliance(
    payload: ComplianceItemCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    co = await _get_company(db)
    warning_days, critical_days = await _get_thresholds(db)
    item = ComplianceItem(
        company_id=co.id,
        item_type=payload.item_type,
        name=payload.name,
        policy_holder=payload.policy_holder,
        issuer=payload.issuer,
        reference_no=payload.reference_no,
        issue_date=payload.issue_date,
        expiry_date=payload.expiry_date,
        file_path=payload.file_path,
        notes=payload.notes,
        is_active=True,
        created_by=current_user.id,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return _to_response(item, critical_days, warning_days)


@router.get("/alerts", response_model=ComplianceListResponse)
async def get_alerts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return items that are expired or expiring within warning_days. Used by dashboard."""
    co = await _get_company(db)
    warning_days, critical_days = await _get_thresholds(db)
    threshold = date.today() + timedelta(days=warning_days)
    rows = (await db.execute(
        select(ComplianceItem)
        .where(
            and_(
                ComplianceItem.company_id == co.id,
                ComplianceItem.is_active == True,
                ComplianceItem.expiry_date.isnot(None),
                ComplianceItem.expiry_date <= threshold,
            )
        )
        .order_by(ComplianceItem.expiry_date.asc())
    )).scalars().all()
    return ComplianceListResponse(
        items=[_to_response(r, critical_days, warning_days) for r in rows],
        total=len(rows),
    )


@router.get("/{item_id}", response_model=ComplianceItemResponse)
async def get_compliance(
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    warning_days, critical_days = await _get_thresholds(db)
    item = (await db.execute(select(ComplianceItem).where(ComplianceItem.id == item_id))).scalar_one_or_none()
    if not item:
        raise HTTPException(404, "Item not found")
    return _to_response(item, critical_days, warning_days)


@router.put("/{item_id}", response_model=ComplianceItemResponse)
async def update_compliance(
    item_id: uuid.UUID,
    payload: ComplianceItemUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    warning_days, critical_days = await _get_thresholds(db)
    item = (await db.execute(select(ComplianceItem).where(ComplianceItem.id == item_id))).scalar_one_or_none()
    if not item:
        raise HTTPException(404, "Item not found")
    for field, val in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, val)
    await db.commit()
    await db.refresh(item)
    return _to_response(item, critical_days, warning_days)


@router.delete("/{item_id}", status_code=204)
async def delete_compliance(
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    item = (await db.execute(select(ComplianceItem).where(ComplianceItem.id == item_id))).scalar_one_or_none()
    if not item:
        raise HTTPException(404, "Item not found")
    item.is_active = False
    await db.commit()


@router.get("/{item_id}/download")
async def download_file(
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Stream the file at item.file_path over HTTP so the browser can open it.
    This avoids Windows Session 0 isolation (services can't open files on the
    interactive desktop directly).
    """
    import os
    import mimetypes
    from fastapi.responses import FileResponse

    item = (await db.execute(select(ComplianceItem).where(ComplianceItem.id == item_id))).scalar_one_or_none()
    if not item:
        raise HTTPException(404, "Item not found")
    if not item.file_path:
        raise HTTPException(400, "No file path configured for this item")

    path = item.file_path.strip()

    # ── R2 URL — proxy download from cloud storage ──
    if path.startswith("http://") or path.startswith("https://"):
        import httpx
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(path)
                resp.raise_for_status()
        except Exception as e:
            raise HTTPException(502, f"Failed to fetch file from cloud storage: {e}")

        filename = path.rsplit("/", 1)[-1] if "/" in path else "document"
        mime, _ = mimetypes.guess_type(filename)
        from fastapi.responses import Response
        return Response(
            content=resp.content,
            media_type=mime or "application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # ── Local file path — stream from disk ──
    if not os.path.exists(path):
        raise HTTPException(400, f"File not found: {path}")

    mime, _ = mimetypes.guess_type(path)
    filename = os.path.basename(path)
    return FileResponse(
        path=path,
        media_type=mime or "application/octet-stream",
        filename=filename,
    )


# ── File Upload (R2 or local fallback) ─────────────────────────────────── #

ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".doc", ".docx", ".xls", ".xlsx", ".tif", ".tiff"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


@router.post("/{item_id}/upload", response_model=ComplianceItemResponse)
async def upload_compliance_file(
    item_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Upload a document file for a compliance item.
    Stores in Cloudflare R2 under compliance/{company_id}/{item_id}/ prefix.
    Falls back to local uploads/compliance/ if R2 is not configured.
    """
    import os
    import mimetypes
    from pathlib import Path

    # Validate item exists
    item = (await db.execute(select(ComplianceItem).where(ComplianceItem.id == item_id))).scalar_one_or_none()
    if not item:
        raise HTTPException(404, "Item not found")

    # Validate file extension
    original_name = file.filename or "document"
    ext = os.path.splitext(original_name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"File type '{ext}' not allowed. Accepted: {', '.join(sorted(ALLOWED_EXTENSIONS))}")

    # Read and validate size
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(400, f"File too large ({len(content) // (1024*1024)} MB). Maximum: {MAX_FILE_SIZE // (1024*1024)} MB")
    if len(content) == 0:
        raise HTTPException(400, "File is empty")

    # Determine content type
    content_type = file.content_type or mimetypes.guess_type(original_name)[0] or "application/octet-stream"

    # Build a safe filename
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    safe_name = f"{timestamp}_{original_name.replace(' ', '_')}"

    co = await _get_company(db)
    warning_days, critical_days = await _get_thresholds(db)

    if is_r2_configured():
        # Upload to R2 under compliance/ prefix (separate from camera/ images)
        r2_key = f"compliance/{co.id}/{item_id}/{safe_name}"
        url = upload_to_r2(content, r2_key, content_type)
        if not url:
            raise HTTPException(502, "Failed to upload file to cloud storage")
        item.file_path = url
    else:
        # Fallback: save to local uploads/compliance/ directory
        upload_dir = Path(__file__).parent.parent.parent / "uploads" / "compliance" / str(item_id)
        upload_dir.mkdir(parents=True, exist_ok=True)
        local_path = upload_dir / safe_name
        local_path.write_bytes(content)
        item.file_path = f"uploads/compliance/{item_id}/{safe_name}"

    await db.commit()
    await db.refresh(item)
    return _to_response(item, critical_days, warning_days)


@router.delete("/{item_id}/file", response_model=ComplianceItemResponse)
async def delete_compliance_file(
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete the uploaded file for a compliance item (from R2 or local disk)."""
    import os
    from app.utils.r2_storage import delete_from_r2

    item = (await db.execute(select(ComplianceItem).where(ComplianceItem.id == item_id))).scalar_one_or_none()
    if not item:
        raise HTTPException(404, "Item not found")
    if not item.file_path:
        raise HTTPException(400, "No file attached to this item")

    path = item.file_path.strip()

    if path.startswith("http://") or path.startswith("https://"):
        # R2 URL — extract key and delete from cloud
        from app.config import get_settings
        settings = get_settings()
        public_base = getattr(settings, "R2_PUBLIC_URL", "")
        if public_base and path.startswith(public_base):
            r2_key = path[len(public_base.rstrip("/")) + 1:]
            delete_from_r2(r2_key)
    elif os.path.exists(path):
        os.remove(path)
    elif path.startswith("uploads/"):
        from pathlib import Path
        full = Path(__file__).parent.parent.parent / path
        if full.exists():
            full.unlink()

    co = await _get_company(db)
    warning_days, critical_days = await _get_thresholds(db)
    item.file_path = None
    await db.commit()
    await db.refresh(item)
    return _to_response(item, critical_days, warning_days)
