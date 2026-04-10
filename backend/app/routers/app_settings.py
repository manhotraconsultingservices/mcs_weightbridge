"""
Application settings router — generic key/value store for admin-configurable params.

Current keys:
  weighbridge_urgency  JSON: {"green_max": 30, "amber_max": 60, "orange_max": 120}
                       Values are in MINUTES. Used by the Token page for color urgency.
  role_permissions     JSON: {"role": ["/path", ...], ...}
  app_wallpaper_path   Relative path: "uploads/wallpaper/wallpaper_<uuid>.jpg"
"""
import json
import os
import sys
import uuid as _uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.user import User

router = APIRouter(prefix="/api/v1/app-settings", tags=["App Settings"])

TABLE = "app_settings"

URGENCY_KEY = "weighbridge_urgency"
URGENCY_DEFAULTS = {"green_max": 30, "amber_max": 60, "orange_max": 120}


# ── Schemas ───────────────────────────────────────────────────────────────────

class UrgencyThresholds(BaseModel):
    green_max: int   # minutes — up to this = green
    amber_max: int   # minutes — up to this = amber
    orange_max: int  # minutes — up to this = orange
                     # anything above orange_max = red


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_raw(db: AsyncSession, key: str) -> str | None:
    row = (await db.execute(
        text(f"SELECT value FROM {TABLE} WHERE key = :k"),
        {"k": key},
    )).fetchone()
    return row[0] if row else None


async def _upsert(db: AsyncSession, key: str, value: str):
    await db.execute(
        text(f"""
            INSERT INTO {TABLE} (key, value, updated_at)
            VALUES (:k, :v, NOW())
            ON CONFLICT (key) DO UPDATE
              SET value = EXCLUDED.value,
                  updated_at = NOW()
        """),
        {"k": key, "v": value},
    )
    await db.commit()


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/weighbridge-urgency", response_model=UrgencyThresholds)
async def get_urgency_thresholds(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return current urgency colour thresholds (minutes). Any authenticated user."""
    raw = await _get_raw(db, URGENCY_KEY)
    if raw:
        try:
            data = json.loads(raw)
            return UrgencyThresholds(**{**URGENCY_DEFAULTS, **data})
        except Exception:
            pass
    return UrgencyThresholds(**URGENCY_DEFAULTS)


@router.put("/weighbridge-urgency", response_model=UrgencyThresholds)
async def update_urgency_thresholds(
    payload: UrgencyThresholds,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Update urgency colour thresholds. Admin only."""
    if not (0 < payload.green_max < payload.amber_max < payload.orange_max):
        raise HTTPException(400, "Thresholds must be in ascending order: green < amber < orange")
    if payload.orange_max > 1440:
        raise HTTPException(400, "orange_max cannot exceed 1440 minutes (24 hours)")

    await _upsert(db, URGENCY_KEY, json.dumps(payload.model_dump()))
    return payload


# ── Role Permissions ──────────────────────────────────────────────────────────

PERMISSIONS_KEY = "role_permissions"

DEFAULT_ROLE_PERMISSIONS: dict[str, list[str]] = {
    "admin": ["*"],
    "operator": ["/tokens"],
    "sales_executive": ["/invoices", "/quotations", "/parties", "/vehicles"],
    "purchase_executive": ["/purchase-invoices", "/parties", "/products"],
    "accountant": ["/payments", "/ledger", "/gst-reports", "/reports", "/parties"],
    "viewer": ["/reports", "/gst-reports", "/ledger"],
}


@router.get("/role-permissions")
async def get_role_permissions(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return the role→pages permissions map. Any authenticated user (needed by sidebar on load)."""
    raw = await _get_raw(db, PERMISSIONS_KEY)
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            pass
    return DEFAULT_ROLE_PERMISSIONS


@router.put("/role-permissions")
async def update_role_permissions(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role("admin")),
):
    """Save role→pages map. Admin only."""
    await _upsert(db, PERMISSIONS_KEY, json.dumps(payload))
    return payload


# ── Wallpaper ─────────────────────────────────────────────────────────────────

WALLPAPER_KEY = "app_wallpaper_path"
_MAX_WALLPAPER_BYTES = 5 * 1024 * 1024  # 5 MB


def _wallpaper_dir() -> str:
    """Resolve uploads/wallpaper directory. Works in both dev and PyInstaller builds."""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    d = os.path.join(base, "uploads", "wallpaper")
    os.makedirs(d, exist_ok=True)
    return d


@router.get("/wallpaper/info")
async def get_wallpaper_info(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return current wallpaper URL or null. Any authenticated user."""
    raw = await _get_raw(db, WALLPAPER_KEY)
    if raw and os.path.exists(os.path.join(_wallpaper_dir(), "..", "..", os.path.basename(raw))):
        url = "/" + raw.replace("\\", "/")
        return {"url": url}
    if raw:
        # Construct the URL regardless (let the browser 404 if file missing)
        url = "/" + raw.replace("\\", "/")
        return {"url": url}
    return {"url": None}


@router.post("/wallpaper")
async def upload_wallpaper(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role("admin")),
):
    """Upload a new wallpaper image. Admin only. Max 5 MB."""
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(400, "Only image files are allowed")

    data = await file.read()
    if len(data) > _MAX_WALLPAPER_BYTES:
        raise HTTPException(413, "Image must be smaller than 5 MB")

    ext = os.path.splitext(file.filename or "wallpaper.jpg")[1] or ".jpg"
    filename = f"wallpaper_{_uuid.uuid4().hex}{ext}"

    wallpaper_dir = _wallpaper_dir()

    # Delete old wallpaper file
    old_raw = await _get_raw(db, WALLPAPER_KEY)
    if old_raw:
        old_path = os.path.join(wallpaper_dir, os.path.basename(old_raw))
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except Exception:
                pass

    # Write new file
    file_path = os.path.join(wallpaper_dir, filename)
    with open(file_path, "wb") as f:
        f.write(data)

    # Store relative path (always forward slashes)
    rel = f"uploads/wallpaper/{filename}"
    await _upsert(db, WALLPAPER_KEY, rel)
    return {"url": f"/{rel}"}


@router.delete("/wallpaper")
async def delete_wallpaper(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role("admin")),
):
    """Remove the current wallpaper. Admin only."""
    old_raw = await _get_raw(db, WALLPAPER_KEY)
    if old_raw:
        wallpaper_dir = _wallpaper_dir()
        old_path = os.path.join(wallpaper_dir, os.path.basename(old_raw))
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except Exception:
                pass
        await db.execute(text(f"DELETE FROM {TABLE} WHERE key = :k"), {"k": WALLPAPER_KEY})
        await db.commit()
    return {"message": "Wallpaper removed"}
