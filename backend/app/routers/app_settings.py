"""
Application settings router — generic key/value store for admin-configurable params.

Current keys:
  weighbridge_urgency       JSON: {"green_max": 30, "amber_max": 60, "orange_max": 120}
                            Values are in MINUTES. Used by the Token page for color urgency.
  role_permissions          JSON: {"role": ["/path", ...], ...}
  app_wallpaper_path        Relative path: "uploads/wallpaper/wallpaper_<uuid>.jpg"
  vehicle_types             JSON array: ["truck", "tractor", "trailer", ...]
  invoice_print_settings    JSON: toggleable fields/sections for printed PDF invoices
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
from app.utils.pdf_generator import DEFAULT_INVOICE_PRINT_SETTINGS

router = APIRouter(prefix="/api/v1/app-settings", tags=["App Settings"])

TABLE = "app_settings"


@router.get("/manager-contacts")
async def manager_contacts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Phone-list shown by the Operator Kiosk's "Need Help" SOS button.

    Returns active admin users with a phone number. Zero-config: as soon as
    an admin has a phone in their profile, the operator can reach them.
    """
    rows = (await db.execute(text(
        "SELECT full_name, username, phone FROM users "
        "WHERE role = 'admin' AND is_active = true AND phone IS NOT NULL AND phone <> '' "
        "ORDER BY full_name NULLS LAST, username"
    ))).fetchall()
    return [
        {"name": (r[0] or r[1]), "phone": r[2]}
        for r in rows
    ]

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
    "store_manager": ["/inventory", "/product-inventory", "/production", "/production/dashboard", "/products"],
    "operator": ["/tokens"],
    "gate_guard": ["/gate"],
    "sales_executive": ["/invoices", "/quotations", "/parties", "/vehicles", "/pricing-matrix", "/products"],
    "purchase_executive": ["/purchase-invoices", "/parties", "/products"],
    "accountant": ["/payments", "/ledger", "/gst-reports", "/reports", "/parties", "/pricing-matrix", "/products"],
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


# ── Invoice Action Permissions ────────────────────────────────────────────────

INVOICE_ACTIONS_KEY = "invoice_action_permissions"

# All available invoice actions
INVOICE_ACTIONS = [
    "edit_draft",
    "finalize",
    "cancel_draft",
    "record_payment",
    "tally_sync",
    "einvoice",
    "create_revision",
    "move_to_supplement",
]

# Defaults: which roles get which actions
DEFAULT_INVOICE_ACTION_PERMS: dict[str, list[str]] = {
    "admin":              INVOICE_ACTIONS,  # all actions
    "accountant":         ["edit_draft", "finalize", "cancel_draft", "record_payment", "tally_sync", "einvoice", "create_revision"],
    "sales_executive":    ["edit_draft", "finalize"],
    "purchase_executive": ["edit_draft", "finalize"],
    "store_manager":      [],
    "operator":           [],
    "viewer":             [],
}


@router.get("/invoice-action-permissions")
async def get_invoice_action_permissions(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return role→invoice_actions map. Any user (frontend needs it on load)."""
    raw = await _get_raw(db, INVOICE_ACTIONS_KEY)
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            pass
    return DEFAULT_INVOICE_ACTION_PERMS


@router.put("/invoice-action-permissions")
async def update_invoice_action_permissions(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role("admin")),
):
    """Save role→invoice_actions map. Admin only."""
    await _upsert(db, INVOICE_ACTIONS_KEY, json.dumps(payload))
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


# ── Vehicle Types ─────────────────────────────────────────────────────────────

VEHICLE_TYPES_KEY = "vehicle_types"
VEHICLE_TYPES_DEFAULTS = ["truck", "tractor", "trailer", "tipper", "mini_truck", "tanker", "dumper"]


@router.get("/vehicle-types")
async def get_vehicle_types(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return the list of vehicle types. Any authenticated user."""
    raw = await _get_raw(db, VEHICLE_TYPES_KEY)
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            pass
    return VEHICLE_TYPES_DEFAULTS


@router.put("/vehicle-types")
async def update_vehicle_types(
    payload: list[str],
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role("admin")),
):
    """Save custom vehicle types list. Admin only."""
    if not payload:
        raise HTTPException(400, "At least one vehicle type is required")
    # Deduplicate, lowercase, strip whitespace, remove blanks
    cleaned = list(dict.fromkeys(
        t.strip().lower().replace(" ", "_") for t in payload if t.strip()
    ))
    if not cleaned:
        raise HTTPException(400, "At least one vehicle type is required")
    await _upsert(db, VEHICLE_TYPES_KEY, json.dumps(cleaned))
    return cleaned


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


# ── eInvoice Config ──────────────────────────────────────────────────────────

EINVOICE_CONFIG_KEY = "einvoice_config"

_EINVOICE_DEFAULTS = {
    "provider": "nic",
    "base_url": "https://einv-apisandbox.nic.in",
    "client_id": "",
    "client_secret": "",
    "gstin": "",
    "username": "",
    "password": "",
    "is_sandbox": True,
    "is_enabled": False,
    "auto_generate_on_finalize": True,
    "demo_mode": False,
}

_MASK = "***"


def _mask_secrets(cfg: dict) -> dict:
    """Return config with sensitive fields masked for GET responses."""
    out = dict(cfg)
    for key in ("client_secret", "password"):
        if out.get(key):
            out[key] = _MASK
    return out


@router.get("/einvoice-config")
async def get_einvoice_config(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role("admin")),
):
    """Return eInvoice config (passwords masked). Admin only."""
    raw = await _get_raw(db, EINVOICE_CONFIG_KEY)
    if raw:
        try:
            cfg = json.loads(raw)
            return _mask_secrets({**_EINVOICE_DEFAULTS, **cfg})
        except Exception:
            pass
    return _mask_secrets(_EINVOICE_DEFAULTS)


@router.put("/einvoice-config")
async def update_einvoice_config(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role("admin")),
):
    """Save eInvoice config. Admin only. Masked fields preserve existing values."""
    # Load existing to preserve masked secrets
    existing = {}
    raw = await _get_raw(db, EINVOICE_CONFIG_KEY)
    if raw:
        try:
            existing = json.loads(raw)
        except Exception:
            pass

    # Merge — preserve secrets if masked sentinel sent
    merged = {**_EINVOICE_DEFAULTS, **existing}
    for key, val in payload.items():
        if key in ("client_secret", "password") and val == _MASK:
            continue  # keep existing
        if key in _EINVOICE_DEFAULTS:
            merged[key] = val

    # Auto-set base_url from sandbox toggle
    if merged.get("is_sandbox"):
        merged["base_url"] = "https://einv-apisandbox.nic.in"
    else:
        merged["base_url"] = "https://einvoice1.gst.gov.in"

    await _upsert(db, EINVOICE_CONFIG_KEY, json.dumps(merged))
    return _mask_secrets(merged)


@router.post("/einvoice-config/test")
async def test_einvoice_connection(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role("admin")),
):
    """Test NIC eInvoice authentication. Admin only."""
    from app.integrations.einvoice import EInvoiceClient, EInvoiceConfig

    raw = await _get_raw(db, EINVOICE_CONFIG_KEY)
    if not raw:
        raise HTTPException(400, "eInvoice not configured yet")

    try:
        cfg_dict = json.loads(raw)
        config = EInvoiceConfig.from_dict(cfg_dict)
    except Exception as e:
        raise HTTPException(400, f"Invalid config: {e}")

    if not config.client_id or not config.username:
        raise HTTPException(400, "Client ID and Username are required")

    client = EInvoiceClient(config)
    result = await client.test_connection()
    return result


# ── E-Way Bill config ─────────────────────────────────────────────────────────

EWAY_CONFIG_KEY = "eway_config"

_EWAY_DEFAULTS = {
    "provider": "nic",
    "base_url": "https://ewb-apisandbox.nic.in",
    "client_id": "",
    "client_secret": "",
    "gstin": "",
    "username": "",
    "password": "",
    "is_sandbox": True,
    "is_enabled": False,
    "auto_generate_on_finalize": False,
    "default_distance_km": 0,
    "demo_mode": False,
}


@router.get("/eway-config")
async def get_eway_config(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role("admin")),
):
    """Return E-Way Bill config (passwords masked). Admin only."""
    raw = await _get_raw(db, EWAY_CONFIG_KEY)
    if raw:
        try:
            return _mask_secrets({**_EWAY_DEFAULTS, **json.loads(raw)})
        except Exception:
            pass
    return _mask_secrets(_EWAY_DEFAULTS)


@router.put("/eway-config")
async def update_eway_config(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role("admin")),
):
    """Save E-Way Bill config. Admin only. Masked secrets preserve existing values."""
    existing = {}
    raw = await _get_raw(db, EWAY_CONFIG_KEY)
    if raw:
        try:
            existing = json.loads(raw)
        except Exception:
            pass

    merged = {**_EWAY_DEFAULTS, **existing}
    for key, val in payload.items():
        if key in ("client_secret", "password") and val == _MASK:
            continue
        if key in _EWAY_DEFAULTS:
            merged[key] = val

    merged["base_url"] = ("https://ewb-apisandbox.nic.in" if merged.get("is_sandbox")
                          else "https://ewaybillapi.nic.in")
    await _upsert(db, EWAY_CONFIG_KEY, json.dumps(merged))
    return _mask_secrets(merged)


@router.post("/eway-config/test")
async def test_eway_connection(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role("admin")),
):
    """Test NIC E-Way Bill authentication. Admin only."""
    from app.integrations.eway import EWayClient, EWayConfig
    raw = await _get_raw(db, EWAY_CONFIG_KEY)
    if not raw:
        raise HTTPException(400, "E-Way Bill not configured yet")
    try:
        config = EWayConfig.from_dict(json.loads(raw))
    except Exception as e:
        raise HTTPException(400, f"Invalid config: {e}")
    if not config.demo_mode and (not config.client_id or not config.username):
        raise HTTPException(400, "Client ID and Username are required (or enable Demo mode)")
    return await EWayClient(config).test_connection()


# ── UPI collection config (static — no live gateway) ──────────────────────────

UPI_CONFIG_KEY = "upi_config"
_UPI_DEFAULTS = {"vpa": "", "payee_name": "", "enabled": False}


@router.get("/upi-config")
async def get_upi_config(db: AsyncSession = Depends(get_db),
                         current_user=Depends(get_current_user)):
    """UPI VPA + payee name shown to customers on invoices and the portal."""
    raw = await _get_raw(db, UPI_CONFIG_KEY)
    if raw:
        try:
            return {**_UPI_DEFAULTS, **json.loads(raw)}
        except Exception:
            pass
    return dict(_UPI_DEFAULTS)


@router.put("/upi-config")
async def update_upi_config(payload: dict, db: AsyncSession = Depends(get_db),
                            current_user=Depends(require_role("admin"))):
    existing = {}
    raw = await _get_raw(db, UPI_CONFIG_KEY)
    if raw:
        try:
            existing = json.loads(raw)
        except Exception:
            pass
    merged = {**_UPI_DEFAULTS, **existing}
    for k in _UPI_DEFAULTS:
        if k in payload:
            merged[k] = payload[k]
    await _upsert(db, UPI_CONFIG_KEY, json.dumps(merged))
    return merged


# ── Invoice Print Settings ────────────────────────────────────────────────────

INVOICE_PRINT_SETTINGS_KEY = "invoice_print_settings"


@router.get("/invoice-print-settings")
async def get_invoice_print_settings(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return invoice PDF print settings. Any authenticated user."""
    raw = await _get_raw(db, INVOICE_PRINT_SETTINGS_KEY)
    if raw:
        try:
            stored = json.loads(raw)
            # Deep merge with defaults so new keys are always present
            merged = {**DEFAULT_INVOICE_PRINT_SETTINGS}
            for section, defaults in DEFAULT_INVOICE_PRINT_SETTINGS.items():
                if isinstance(defaults, dict) and section in stored and isinstance(stored[section], dict):
                    merged[section] = {**defaults, **stored[section]}
                elif section in stored:
                    merged[section] = stored[section]
            return merged
        except Exception:
            pass
    return DEFAULT_INVOICE_PRINT_SETTINGS


@router.put("/invoice-print-settings")
async def save_invoice_print_settings(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role("admin")),
):
    """Save invoice PDF print settings. Admin only."""
    await _upsert(db, INVOICE_PRINT_SETTINGS_KEY, json.dumps(payload))
    return payload


# ── Barrier / Gate-relay Config (H3-D) ───────────────────────────────────────

BARRIER_CONFIG_KEY = "barrier_config"
_BARRIER_MASK = "***"


@router.get("/barrier-config")
async def get_barrier_config(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return barrier relay config (password masked). Any authenticated user."""
    from app.services.barrier import DEFAULT_CONFIG as BARRIER_DEFAULTS
    raw = await _get_raw(db, BARRIER_CONFIG_KEY)
    stored: dict = {}
    if raw:
        try:
            stored = json.loads(raw)
        except Exception:
            pass
    cfg = {**BARRIER_DEFAULTS, **stored}
    if cfg.get("http_auth_pass"):
        cfg["http_auth_pass"] = _BARRIER_MASK
    return cfg


@router.put("/barrier-config")
async def update_barrier_config(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Save barrier relay config. Admin only. Password sentinel preserves existing."""
    from app.services.barrier import DEFAULT_CONFIG as BARRIER_DEFAULTS
    existing: dict = {}
    raw = await _get_raw(db, BARRIER_CONFIG_KEY)
    if raw:
        try:
            existing = json.loads(raw)
        except Exception:
            pass
    merged = {**BARRIER_DEFAULTS, **existing, **payload}
    # preserve password if sentinel was sent
    if payload.get("http_auth_pass") == _BARRIER_MASK:
        merged["http_auth_pass"] = existing.get("http_auth_pass", "")
    await _upsert(db, BARRIER_CONFIG_KEY, json.dumps(merged))
    # mask before returning
    if merged.get("http_auth_pass"):
        merged["http_auth_pass"] = _BARRIER_MASK
    return merged


@router.post("/barrier-config/test")
async def test_barrier_config(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Fire one test trigger and return success/error. Admin only."""
    from app.services.barrier import trigger_barrier
    try:
        await trigger_barrier(db, "entry", "TEST-PLATE", "TEST-GP")
        return {"ok": True, "message": "Test trigger sent — check your relay device"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ── Volume Unit Setting ────────────────────────────────────────────────────────
# Per-tenant preference: "m3" (SI default, stored canonical unit) or "cft"
# (cubic feet — traditional unit in Indian stone-crusher trade).
# When "cft" is selected, the frontend converts CFT→m³ before API calls
# and converts m³→CFT for display. The DB always stores m³.

VOLUME_UNIT_KEY = "volume_unit"


@router.get("/volume-unit")
async def get_volume_unit(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return current volume display unit preference (m3 | cft)."""
    val = await _get_raw(db, VOLUME_UNIT_KEY)
    return {"volume_unit": val or "m3"}


@router.put("/volume-unit")
async def update_volume_unit(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role("admin")),
):
    """Save volume display unit preference. Only 'm3' or 'cft' are valid."""
    unit = payload.get("volume_unit", "m3")
    if unit not in ("m3", "cft"):
        from fastapi import HTTPException as _HTTPException
        raise _HTTPException(400, "volume_unit must be 'm3' or 'cft'")
    await _upsert(db, VOLUME_UNIT_KEY, unit)
    return {"volume_unit": unit}


# ── Gate Camera Config ─────────────────────────────────────────────────────────

GATE_CAM_CFG_KEY = "gate_camera_config"

_GATE_CAM_DEFAULT: dict = {
    "entry": {"enabled": False, "label": "Entry Gate Camera", "snapshot_url": "", "username": "admin", "password": ""},
    "exit":  {"enabled": False, "label": "Exit Gate Camera",  "snapshot_url": "", "username": "admin", "password": ""},
    "webhook_secret": "",
    "eod_alert_time": "20:00",
    "eod_alert_enabled": True,
}


def _mask_gate_cam(cfg: dict) -> dict:
    import copy
    out = copy.deepcopy(cfg)
    for pos in ("entry", "exit"):
        if out.get(pos, {}).get("password"):
            out[pos]["password"] = "***"
    if out.get("webhook_secret"):
        out["webhook_secret"] = "***"
    return out


@router.get("/gate-camera-config")
async def get_gate_camera_config(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role("admin")),
):
    raw = await _get_raw(db, GATE_CAM_CFG_KEY)
    cfg = json.loads(raw) if raw else _GATE_CAM_DEFAULT
    return _mask_gate_cam(cfg)


@router.put("/gate-camera-config")
async def update_gate_camera_config(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role("admin")),
):
    raw = await _get_raw(db, GATE_CAM_CFG_KEY)
    stored = json.loads(raw) if raw else _GATE_CAM_DEFAULT
    merged: dict = {**_GATE_CAM_DEFAULT, **stored}
    for pos in ("entry", "exit"):
        if pos in payload:
            incoming = dict(payload[pos])
            existing = merged.get(pos, {})
            if incoming.get("password") == "***":
                incoming["password"] = existing.get("password", "")
            merged[pos] = {**existing, **incoming}
    if "webhook_secret" in payload and payload["webhook_secret"] != "***":
        merged["webhook_secret"] = payload["webhook_secret"]
    for k in ("eod_alert_time", "eod_alert_enabled"):
        if k in payload:
            merged[k] = payload[k]
    await _upsert(db, GATE_CAM_CFG_KEY, json.dumps(merged))
    return _mask_gate_cam(merged)


@router.post("/gate-camera-config/test/{position}")
async def test_gate_camera(
    position: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role("admin")),
):
    """Capture a test snapshot from the entry or exit gate camera."""
    if position not in ("entry", "exit"):
        raise HTTPException(400, "position must be 'entry' or 'exit'")
    raw = await _get_raw(db, GATE_CAM_CFG_KEY)
    cfg = json.loads(raw) if raw else {}
    cam = cfg.get(position, {})
    if not cam.get("snapshot_url"):
        raise HTTPException(400, f"{position} camera URL is not configured")
    import httpx as _httpx
    url = cam["snapshot_url"]
    username = cam.get("username", "")
    password = cam.get("password", "")
    auth = (username, password) if username else None
    try:
        async with _httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url, auth=auth)
            resp.raise_for_status()
            if "image" not in resp.headers.get("content-type", ""):
                return {"ok": False, "error": "Camera returned non-image content. Check URL."}
            return {"ok": True, "message": f"{position.title()} camera responded ({len(resp.content)} bytes)", "size": len(resp.content)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ── Volume Unit Preference ────────────────────────────────────────────────────
# Controls how operators enter volumes on the Token page and Kiosk.
# 'm3' = cubic metres (input directly); 'cft' = cubic feet (frontend converts
# CFT → m³ before posting volume_m3 to the API). Density is always MT/m³.

VOLUME_UNIT_KEY = "volume_unit"


class VolumeUnitConfig(BaseModel):
    volume_unit: str = "m3"   # "m3" or "cft"


@router.get("/volume-unit", response_model=VolumeUnitConfig)
async def get_volume_unit(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    raw = await _get_raw(db, VOLUME_UNIT_KEY)
    unit = (raw or "m3").strip('"')
    if unit not in ("m3", "cft"):
        unit = "m3"
    return VolumeUnitConfig(volume_unit=unit)


@router.put("/volume-unit", response_model=VolumeUnitConfig)
async def update_volume_unit(
    payload: VolumeUnitConfig,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    if payload.volume_unit not in ("m3", "cft"):
        raise HTTPException(400, "volume_unit must be 'm3' or 'cft'")
    await _upsert(db, VOLUME_UNIT_KEY, payload.volume_unit)
    return payload
