"""
Gate Management — CP Plus camera + guard-managed gate passes.

Workflow:
  ENTRY: guard opens New Gate Pass → clicks "Capture Entry Photo" (HTTP snapshot)
         → fills vehicle/driver/material → system assigns GP/YYYY-MM-DD/NNN.
  EXIT : guard finds GP → clicks "Record Exit" → captures exit photo →
         links token (mandatory for purpose='weighbridge') → closes.
  EOD  : GET /summary returns entered/exited/inside counts + mismatch list.

CP Plus webhook: POST /webhook/cpplus receives vehicle-detection alarm push
  (configured at camera level to filter vehicle targets only).
  Creates a gate_camera_events row; guard converts it to a gate pass on screen.
"""

import asyncio
import json
import logging
import os
import sys
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, Header, UploadFile
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, require_role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/gate", tags=["Gate Management"])

# ── Allowed roles for guard endpoints ─────────────────────────────────────────
_GUARD_ROLES = {"admin", "gate_guard", "operator"}

GATE_CAM_CFG_KEY = "gate_camera_config"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _uploads_base() -> str:
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), "uploads")
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "uploads",
    )


def _guard_check(user):
    if user.role not in _GUARD_ROLES:
        raise HTTPException(403, "Gate management requires gate_guard, operator, or admin role")


async def _get_gate_cam_cfg(db: AsyncSession) -> dict:
    row = await db.execute(
        text("SELECT value FROM app_settings WHERE key = :k"), {"k": GATE_CAM_CFG_KEY}
    )
    val = row.scalar()
    if not val:
        return {"entry": {"enabled": False}, "exit": {"enabled": False}}
    try:
        return json.loads(val)
    except Exception:
        return {"entry": {"enabled": False}, "exit": {"enabled": False}}


def _is_uuid(value: str) -> bool:
    """Return True if value looks like a UUID (xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)."""
    import re
    return bool(re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", value.lower()))


async def _next_gate_pass_no(db: AsyncSession, company_id: str) -> tuple[str, int]:
    """Atomic daily sequence counter — gap-free, no separate lock needed."""
    today = date.today()
    result = await db.execute(
        text("""
            INSERT INTO gate_pass_daily_seq (company_id, pass_date, last_no)
            VALUES (:cid, :d, 1)
            ON CONFLICT (company_id, pass_date) DO UPDATE
            SET last_no = gate_pass_daily_seq.last_no + 1
            RETURNING last_no
        """),
        {"cid": company_id, "d": today},
    )
    seq_no = result.scalar()
    gate_pass_no = f"GP/{today.strftime('%Y-%m-%d')}/{seq_no:03d}"
    return gate_pass_no, seq_no


async def _capture_snapshot(
    cfg: dict,
    position: str,
    save_dir: str,
    filename: str,
) -> str | None:
    """Capture a JPEG from the configured CP Plus camera URL. Returns relative path or None."""
    cam = cfg.get(position, {})
    if not cam.get("enabled") or not cam.get("snapshot_url"):
        return None

    url = cam["snapshot_url"]
    username = cam.get("username", "")
    password = cam.get("password", "")
    auth = (username, password) if username else None

    try:
        import httpx  # lazy — mirrors cameras.py pattern so module loads without httpx in path
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url, auth=auth)
            resp.raise_for_status()
            if "image" not in resp.headers.get("content-type", ""):
                logger.warning("Gate camera %s returned non-image content-type", position)
                return None
            os.makedirs(save_dir, exist_ok=True)
            full_path = os.path.join(save_dir, filename)
            with open(full_path, "wb") as f:
                f.write(resp.content)
            rel_path = os.path.relpath(full_path, _uploads_base())
            return f"uploads/{rel_path.replace(os.sep, '/')}"
    except Exception as exc:
        logger.warning("Gate snapshot capture failed (%s): %s", position, exc)
        return None


async def _do_capture_and_store(
    db: AsyncSession,
    company_id: str,
    gate_pass_id: str | None,
    position: str,
    source: str,
    webhook_payload: dict | None,
) -> str | None:
    cfg = await _get_gate_cam_cfg(db)
    today_str = date.today().strftime("%Y%m%d")
    save_dir = os.path.join(_uploads_base(), "gate", today_str)
    ts = datetime.now(timezone.utc).strftime("%H%M%S")
    filename = f"{position}_{gate_pass_id or 'pending'}_{ts}.jpg"
    photo_path = await _capture_snapshot(cfg, position, save_dir, filename)

    await db.execute(
        text("""
            INSERT INTO gate_camera_events
                (company_id, camera_position, camera_id, gate_pass_id,
                 snapshot_path, source, webhook_payload, detected_at, linked_at)
            VALUES (:cid, :pos, :cam, :gpid,
                    :path, :src, :payload, NOW(),
                    CASE WHEN :gpid IS NOT NULL THEN NOW() ELSE NULL END)
        """),
        {
            "cid": company_id,
            "pos": position,
            "cam": cfg.get(position, {}).get("label", position),
            "gpid": gate_pass_id,
            "path": photo_path,
            "src": source,
            "payload": json.dumps(webhook_payload) if webhook_payload else None,
        },
    )
    return photo_path


# ── Gate Pass CRUD ────────────────────────────────────────────────────────────

@router.post("/passes")
async def create_gate_pass(
    body: dict,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Create a gate pass. Triggers entry photo capture as a background task."""
    _guard_check(current_user)
    company_id = str(current_user.company_id)

    gate_pass_no, seq_no = await _next_gate_pass_no(db, company_id)

    row = await db.execute(
        text("""
            INSERT INTO gate_passes
                (company_id, gate_pass_no, pass_date, seq_no,
                 vehicle_no, vehicle_name, vehicle_id, vehicle_type,
                 driver_name, driver_phone, driver_id,
                 material, product_id, purpose,
                 token_id, entry_time, status, notes,
                 created_by, updated_by)
            VALUES
                (:cid, :gpno, CURRENT_DATE, :seq,
                 :vno, :vname, :vid, :vtype,
                 :dname, :dphone, :did,
                 :mat, :pid, :purpose,
                 :tid, COALESCE(CAST(:etime AS TIMESTAMPTZ), NOW()), 'inside', :notes,
                 :uid, :uid)
            RETURNING id, gate_pass_no, seq_no, entry_time
        """),
        {
            "cid": company_id,
            "gpno": gate_pass_no,
            "seq": seq_no,
            "vno": body.get("vehicle_no"),
            "vname": body.get("vehicle_name"),
            "vid": body.get("vehicle_id"),
            "vtype": body.get("vehicle_type"),
            "dname": body.get("driver_name"),
            "dphone": body.get("driver_phone"),
            "did": body.get("driver_id"),
            "mat": body.get("material"),
            "pid": body.get("product_id"),
            "purpose": body.get("purpose", "weighbridge"),
            "tid": body.get("token_id"),
            "etime": body.get("entry_time"),
            "notes": body.get("notes"),
            "uid": str(current_user.id),
        },
    )
    await db.commit()
    created = row.fetchone()

    gp_id = str(created.id)

    # Fire-and-forget entry photo capture
    if body.get("capture_photo", True):
        background_tasks.add_task(
            _bg_capture_entry_photo, company_id, gp_id
        )

    return {
        "id": gp_id,
        "gate_pass_no": created.gate_pass_no,
        "seq_no": created.seq_no,
        "entry_time": created.entry_time.isoformat(),
        "status": "inside",
    }


async def _bg_capture_entry_photo(company_id: str, gate_pass_id: str):
    """Background task: capture entry photo and update the gate pass row."""
    from app.database import async_session_factory
    async with async_session_factory() as db:
        try:
            photo_path = await _do_capture_and_store(
                db, company_id, gate_pass_id, "entry", "manual", None
            )
            if photo_path:
                await db.execute(
                    text("UPDATE gate_passes SET entry_photo_path = :p, updated_at = NOW() WHERE id = :id"),
                    {"p": photo_path, "id": gate_pass_id},
                )
            await db.commit()
        except Exception as exc:
            logger.warning("Background entry photo capture failed: %s", exc)


@router.get("/passes")
async def list_gate_passes(
    pass_date: str | None = None,
    status: str | None = None,
    vehicle_no: str | None = None,
    unlinked: bool = False,
    page: int = 1,
    page_size: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    company_id = str(current_user.company_id)
    target_date_str = pass_date or date.today().isoformat()
    target_date = date.fromisoformat(target_date_str)  # asyncpg needs date obj, not str

    filters = "AND pass_date = :d"
    params: dict = {"cid": company_id, "d": target_date, "lim": page_size, "off": (page - 1) * page_size}
    if status:
        filters += " AND status = :status"
        params["status"] = status
    if vehicle_no:
        filters += " AND vehicle_no ILIKE :vno"
        params["vno"] = f"%{vehicle_no}%"
    if unlinked:
        filters += " AND gp.token_id IS NULL"

    rows = await db.execute(
        text(f"""
            SELECT gp.*,
                   t.token_no, t.net_weight
            FROM gate_passes gp
            LEFT JOIN tokens t ON t.id = gp.token_id
            WHERE gp.company_id = :cid {filters}
            ORDER BY gp.entry_time DESC
            LIMIT :lim OFFSET :off
        """),
        params,
    )
    items = [dict(r._mapping) for r in rows.fetchall()]

    total_row = await db.execute(
        text(f"SELECT COUNT(*) FROM gate_passes gp WHERE gp.company_id = :cid {filters}"),
        {k: v for k, v in params.items() if k not in ("lim", "off")},
    )
    total = total_row.scalar() or 0

    return {"items": _serialize(items), "total": total, "page": page, "page_size": page_size, "date": target_date_str}


@router.get("/passes/summary")
async def daily_summary(
    pass_date: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Daily entry/exit counts + mismatch list (vehicles still inside).
    Used by the OwnerDashboard gate summary card and EOD Telegram digest.
    """
    _guard_check(current_user)
    company_id = str(current_user.company_id)
    target_date_str = pass_date or date.today().isoformat()
    target_date = date.fromisoformat(target_date_str)  # asyncpg needs date obj, not str

    counts = await db.execute(
        text("""
            SELECT
                COUNT(*) FILTER (WHERE TRUE)                        AS total_entered,
                COUNT(*) FILTER (WHERE status = 'exited')           AS total_exited,
                COUNT(*) FILTER (WHERE status = 'inside')           AS currently_inside,
                COUNT(*) FILTER (WHERE status = 'cancelled')        AS cancelled,
                COUNT(*) FILTER (WHERE purpose = 'weighbridge'
                                   AND token_id IS NULL
                                   AND status != 'cancelled')       AS unlinked_weighbridge
            FROM gate_passes
            WHERE company_id = :cid AND pass_date = :d
        """),
        {"cid": company_id, "d": target_date},
    )
    c = counts.fetchone()

    inside_rows = await db.execute(
        text("""
            SELECT id, gate_pass_no, vehicle_no, vehicle_name, driver_name,
                   material, purpose, entry_time, token_id
            FROM gate_passes
            WHERE company_id = :cid AND pass_date = :d AND status = 'inside'
            ORDER BY entry_time
        """),
        {"cid": company_id, "d": target_date},
    )
    inside = _serialize([dict(r._mapping) for r in inside_rows.fetchall()])

    return {
        "date": target_date_str,
        "total_entered": c.total_entered or 0,
        "total_exited": c.total_exited or 0,
        "currently_inside": c.currently_inside or 0,
        "cancelled": c.cancelled or 0,
        "unlinked_weighbridge": c.unlinked_weighbridge or 0,
        "mismatch": (c.currently_inside or 0) > 0,
        "inside_list": inside,
    }


@router.get("/passes/{gp_id}")
async def get_gate_pass(
    gp_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    row = await db.execute(
        text("""
            SELECT gp.*,
                   v.registration_no AS vehicle_registration,
                   t.token_no, t.net_weight,
                   COALESCE(gp.vehicle_type, t.vehicle_type) AS vehicle_type,
                   u.full_name AS created_by_name
            FROM gate_passes gp
            LEFT JOIN vehicles v ON v.id = gp.vehicle_id
            LEFT JOIN tokens t ON t.id = gp.token_id
            LEFT JOIN users u ON u.id = gp.created_by
            WHERE gp.id = :id AND gp.company_id = :cid
        """),
        {"id": gp_id, "cid": str(current_user.company_id)},
    )
    gp = row.fetchone()
    if not gp:
        raise HTTPException(404, "Gate pass not found")
    return _serialize_one(dict(gp._mapping))


@router.put("/passes/{gp_id}")
async def update_gate_pass(
    gp_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Guard updates vehicle/driver/material details."""
    _guard_check(current_user)
    company_id = str(current_user.company_id)

    await db.execute(
        text("""
            UPDATE gate_passes SET
                vehicle_no   = COALESCE(:vno,   vehicle_no),
                vehicle_name = COALESCE(:vname, vehicle_name),
                vehicle_id   = COALESCE(:vid,   vehicle_id),
                vehicle_type = COALESCE(:vtype, vehicle_type),
                driver_name  = COALESCE(:dname, driver_name),
                driver_phone = COALESCE(:dphone,driver_phone),
                material     = COALESCE(:mat,   material),
                product_id   = COALESCE(:pid,   product_id),
                purpose      = COALESCE(:purpose, purpose),
                token_id     = COALESCE(:tid,   token_id),
                notes        = COALESCE(:notes, notes),
                updated_by   = :uid,
                updated_at   = NOW()
            WHERE id = :id AND company_id = :cid
        """),
        {
            "vno": body.get("vehicle_no"),
            "vname": body.get("vehicle_name"),
            "vid": body.get("vehicle_id"),
            "vtype": body.get("vehicle_type"),
            "dname": body.get("driver_name"),
            "dphone": body.get("driver_phone"),
            "mat": body.get("material"),
            "pid": body.get("product_id"),
            "purpose": body.get("purpose"),
            "tid": body.get("token_id"),
            "notes": body.get("notes"),
            "uid": str(current_user.id),
            "id": gp_id,
            "cid": company_id,
        },
    )
    await db.commit()
    return await get_gate_pass(gp_id, db, current_user)


@router.post("/passes/{gp_id}/exit")
async def record_exit(
    gp_id: str,
    body: dict,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Record vehicle exit. Mandatory token link for purpose='weighbridge'.
    Triggers exit photo capture.
    """
    _guard_check(current_user)
    company_id = str(current_user.company_id)

    # Fetch current state
    existing = await db.execute(
        text("SELECT purpose, token_id, status FROM gate_passes WHERE id = :id AND company_id = :cid"),
        {"id": gp_id, "cid": company_id},
    )
    gp = existing.fetchone()
    if not gp:
        raise HTTPException(404, "Gate pass not found")
    if gp.status == "exited":
        raise HTTPException(400, "Gate pass already closed")
    if gp.status == "cancelled":
        raise HTTPException(400, "Cannot exit a cancelled gate pass")

    # Mandatory token link for weighbridge purpose
    token_id = body.get("token_id") or gp.token_id

    # Accept token_no (e.g. "8686") in addition to a UUID
    if token_id and not _is_uuid(str(token_id)):
        try:
            token_no_int = int(str(token_id).strip())
        except ValueError:
            raise HTTPException(400, f"'{token_id}' is not a valid token number.")
        resolved = await db.execute(
            text("SELECT id FROM tokens WHERE token_no = :no AND company_id = :cid"),
            {"no": token_no_int, "cid": company_id},
        )
        resolved_id = resolved.scalar()
        if not resolved_id:
            raise HTTPException(400, f"Token #{token_no_int} not found. Check the weighbridge slip.")
        token_id = str(resolved_id)

    if gp.purpose == "weighbridge" and not token_id:
        raise HTTPException(
            400,
            "Token must be linked before closing a weighbridge gate pass. "
            "Enter the token number from the weighbridge slip.",
        )

    await db.execute(
        text("""
            UPDATE gate_passes SET
                exit_time  = COALESCE(CAST(:etime AS TIMESTAMPTZ), NOW()),
                token_id   = COALESCE(:tid, token_id),
                status     = 'exited',
                updated_by = :uid,
                updated_at = NOW()
            WHERE id = :id AND company_id = :cid
        """),
        {
            "etime": body.get("exit_time"),
            "tid": token_id,
            "uid": str(current_user.id),
            "id": gp_id,
            "cid": company_id,
        },
    )
    await db.commit()

    if body.get("capture_photo", True):
        background_tasks.add_task(_bg_capture_exit_photo, company_id, gp_id)

    return {"ok": True, "status": "exited"}


async def _bg_capture_exit_photo(company_id: str, gate_pass_id: str):
    from app.database import async_session_factory
    async with async_session_factory() as db:
        try:
            photo_path = await _do_capture_and_store(
                db, company_id, gate_pass_id, "exit", "manual", None
            )
            if photo_path:
                await db.execute(
                    text("UPDATE gate_passes SET exit_photo_path = :p, updated_at = NOW() WHERE id = :id"),
                    {"p": photo_path, "id": gate_pass_id},
                )
            await db.commit()
        except Exception as exc:
            logger.warning("Background exit photo capture failed: %s", exc)


@router.post("/passes/{gp_id}/cancel")
async def cancel_gate_pass(
    gp_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    _guard_check(current_user)
    await db.execute(
        text("""
            UPDATE gate_passes SET
                status = 'cancelled', notes = COALESCE(:reason, notes),
                updated_by = :uid, updated_at = NOW()
            WHERE id = :id AND company_id = :cid AND status = 'inside'
        """),
        {
            "reason": body.get("reason"),
            "uid": str(current_user.id),
            "id": gp_id,
            "cid": str(current_user.company_id),
        },
    )
    await db.commit()
    return {"ok": True}


# ── Manual photo capture (on-demand from guard screen) ───────────────────────

@router.post("/capture/{position}")
async def capture_photo(
    position: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Guard clicks 'Capture Photo' button. Immediately fires HTTP snapshot from
    the configured entry or exit camera and returns the saved path.
    Optionally attaches the photo to an existing gate pass (gate_pass_id in body).
    """
    _guard_check(current_user)
    if position not in ("entry", "exit"):
        raise HTTPException(400, "position must be 'entry' or 'exit'")

    company_id = str(current_user.company_id)
    gate_pass_id = body.get("gate_pass_id")

    cfg = await _get_gate_cam_cfg(db)
    cam = cfg.get(position, {})
    if not cam.get("enabled") or not cam.get("snapshot_url"):
        raise HTTPException(400, f"{position} camera is not configured or disabled")

    today_str = date.today().strftime("%Y%m%d")
    save_dir = os.path.join(_uploads_base(), "gate", today_str)
    ts = datetime.now(timezone.utc).strftime("%H%M%S%f")[:12]
    filename = f"{position}_{gate_pass_id or 'preview'}_{ts}.jpg"

    photo_path = await _capture_snapshot(cfg, position, save_dir, filename)
    if not photo_path:
        raise HTTPException(502, "Failed to capture photo from camera. Check camera URL and connectivity.")

    # Log the camera event
    await db.execute(
        text("""
            INSERT INTO gate_camera_events
                (company_id, camera_position, camera_id, gate_pass_id,
                 snapshot_path, source, detected_at, linked_at)
            VALUES (:cid, :pos, :cam, :gpid, :path, 'manual', NOW(),
                    CASE WHEN :gpid IS NOT NULL THEN NOW() ELSE NULL END)
        """),
        {
            "cid": company_id,
            "pos": position,
            "cam": cam.get("label", position),
            "gpid": gate_pass_id,
            "path": photo_path,
        },
    )

    # Update gate pass photo column if gp_id given
    if gate_pass_id:
        col = "entry_photo_path" if position == "entry" else "exit_photo_path"
        await db.execute(
            text(f"UPDATE gate_passes SET {col} = :p, updated_at = NOW() WHERE id = :id AND company_id = :cid"),
            {"p": photo_path, "id": gate_pass_id, "cid": company_id},
        )

    await db.commit()
    return {"photo_path": photo_path, "url": f"/{photo_path}"}


# ── CP Plus vehicle-detection webhook ─────────────────────────────────────────

@router.post("/webhook/cpplus")
async def cpplus_webhook(
    request: Request,
    x_gate_secret: str | None = Header(None, alias="X-Gate-Secret"),
    db: AsyncSession = Depends(get_db),
):
    """
    Receives alarm push from CP Plus AI cameras configured with Vehicle Detection.
    Configure in camera: Smart Event → Vehicle Detection → HTTP Notification → URL.
    Set X-Gate-Secret header in camera config to match gate_camera_config.webhook_secret.

    The system ONLY captures a snapshot and creates a pending gate_camera_event.
    Guard reviews it on screen and creates a gate pass from it.
    """
    cfg = await _get_gate_cam_cfg(db)
    stored_secret = cfg.get("webhook_secret")
    if stored_secret and x_gate_secret != stored_secret:
        raise HTTPException(403, "Invalid webhook secret")

    # Parse payload — CP Plus sends JSON, form-data, or XML depending on model
    content_type = request.headers.get("content-type", "")
    payload: dict[str, Any] = {}
    try:
        if "json" in content_type:
            payload = await request.json()
        elif "form" in content_type or "urlencoded" in content_type:
            form = await request.form()
            payload = dict(form)
        else:
            body_bytes = await request.body()
            try:
                payload = json.loads(body_bytes)
            except Exception:
                payload = {"raw": body_bytes.decode(errors="replace")}
    except Exception:
        payload = {}

    # Determine camera position from payload or camera ID
    cam_id = str(payload.get("LocalID") or payload.get("CameraID") or payload.get("channel") or "")
    position = _infer_position(cfg, cam_id, payload)

    # Infer company from camera config (single-tenant) or header
    # For multi-tenant, tenant middleware already set the DB session
    company_row = await db.execute(text("SELECT id FROM companies LIMIT 1"))
    company_id = str(company_row.scalar())

    # Capture snapshot and create event
    asyncio.create_task(
        _async_webhook_event(company_id, position, cam_id, payload)
    )

    return {"ok": True}


def _infer_position(cfg: dict, cam_id: str, payload: dict) -> str:
    """Best-effort: map camera ID to entry/exit based on configured camera labels."""
    entry_label = cfg.get("entry", {}).get("label", "entry").lower()
    exit_label = cfg.get("exit", {}).get("label", "exit").lower()
    cam_lower = cam_id.lower()
    alarm_lower = str(payload.get("AlarmType", "")).lower()

    if "exit" in cam_lower or "out" in cam_lower or "exit" in alarm_lower:
        return "exit"
    if exit_label and exit_label in cam_lower:
        return "exit"
    return "entry"  # default to entry for ambiguous


async def _async_webhook_event(company_id: str, position: str, cam_id: str, payload: dict):
    """Create camera event from webhook (run as asyncio task, no response latency)."""
    from app.database import async_session_factory
    async with async_session_factory() as db:
        try:
            cfg = await _get_gate_cam_cfg(db)
            today_str = date.today().strftime("%Y%m%d")
            save_dir = os.path.join(_uploads_base(), "gate", today_str)
            ts = datetime.now(timezone.utc).strftime("%H%M%S%f")[:12]
            filename = f"{position}_webhook_{ts}.jpg"
            photo_path = await _capture_snapshot(cfg, position, save_dir, filename)

            await db.execute(
                text("""
                    INSERT INTO gate_camera_events
                        (company_id, camera_position, camera_id, snapshot_path,
                         source, webhook_payload, detected_at)
                    VALUES (:cid, :pos, :cam, :path, 'webhook', :payload, NOW())
                """),
                {
                    "cid": company_id,
                    "pos": position,
                    "cam": cam_id,
                    "path": photo_path,
                    "payload": json.dumps(payload),
                },
            )
            await db.commit()
        except Exception as exc:
            logger.warning("Webhook gate camera event failed: %s", exc)


# ── Recent camera events (unlinked webhook shots for guard to action) ─────────

@router.get("/camera-events")
async def list_camera_events(
    position: str | None = None,
    unlinked_only: bool = False,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return recent camera events so guard can create gate passes from webhook shots."""
    _guard_check(current_user)
    filters = ""
    params: dict = {"cid": str(current_user.company_id), "lim": limit}
    if position:
        filters += " AND camera_position = :pos"
        params["pos"] = position
    if unlinked_only:
        filters += " AND gate_pass_id IS NULL"

    rows = await db.execute(
        text(f"""
            SELECT * FROM gate_camera_events
            WHERE company_id = :cid {filters}
              AND detected_at >= NOW() - INTERVAL '24 hours'
            ORDER BY detected_at DESC
            LIMIT :lim
        """),
        params,
    )
    return _serialize([dict(r._mapping) for r in rows.fetchall()])


# ── Client-side agent endpoints (gate pass photo upload) ─────────────────────

@router.get("/agent-pending")
async def gate_agent_pending(
    tenant_slug: str = Query(""),
    agent_key: str = Query(""),
):
    """
    Return gate passes needing entry or exit photos for the client-side agent to capture.

    The agent polls this endpoint every 5 seconds. Returns:
    - status='inside' passes with no entry_photo_path, created in the last 5 minutes
    - status='exited' passes with no exit_photo_path, exited in the last 5 minutes

    Auth via tenant_slug + agent_key (same pattern as /api/v1/cameras/agent-pending).
    """
    from app.config import get_settings
    settings = get_settings()

    if settings.MULTI_TENANT:
        if not tenant_slug or not agent_key:
            raise HTTPException(400, "tenant_slug and agent_key required")
        from app.multitenancy.registry import tenant_registry
        if not await tenant_registry.validate_agent_key(tenant_slug, agent_key):
            raise HTTPException(403, "Invalid agent key")

    from app.database import get_tenant_session
    _session_cm = await get_tenant_session(tenant_slug if settings.MULTI_TENANT else None)
    async with _session_cm as db:
        rows = (await db.execute(text("""
            SELECT id, gate_pass_no, vehicle_no,
                   CASE
                       WHEN status = 'inside' AND entry_photo_path IS NULL THEN 'entry'
                       WHEN status = 'exited' AND exit_photo_path IS NULL  THEN 'exit'
                   END AS position
            FROM gate_passes
            WHERE (
                (status = 'inside' AND entry_photo_path IS NULL
                    AND entry_time > NOW() - INTERVAL '5 minutes')
                OR
                (status = 'exited' AND exit_photo_path IS NULL
                    AND exit_time > NOW() - INTERVAL '5 minutes')
            )
            ORDER BY entry_time DESC
            LIMIT 20
        """))).fetchall()

        events = [
            {
                "gate_pass_id": str(r._mapping["id"]),
                "gate_pass_no": r._mapping["gate_pass_no"],
                "vehicle_no": r._mapping.get("vehicle_no"),
                "position": r._mapping["position"],
            }
            for r in rows
            if r._mapping.get("position")
        ]

    return {"events": events, "count": len(events)}


@router.post("/agent-upload")
async def gate_agent_upload(
    gate_pass_id: str = Form(...),
    position: str = Form(...),
    tenant_slug: str = Form(""),
    agent_key: str = Form(""),
    file: UploadFile = File(...),
):
    """
    Accept a gate pass photo uploaded by the client-side camera agent.
    Updates entry_photo_path or exit_photo_path on the gate_passes row.

    position: 'entry' or 'exit'
    Auth via tenant_slug + agent_key (same as /api/v1/cameras/agent-upload).
    """
    import io
    from PIL import Image
    from app.config import get_settings
    settings = get_settings()

    if settings.MULTI_TENANT:
        if not tenant_slug or not agent_key:
            raise HTTPException(400, "tenant_slug and agent_key required")
        from app.multitenancy.registry import tenant_registry
        if not await tenant_registry.validate_agent_key(tenant_slug, agent_key):
            raise HTTPException(403, "Invalid agent key for tenant")

    if position not in ("entry", "exit"):
        raise HTTPException(400, "position must be 'entry' or 'exit'")

    content = await file.read()
    if len(content) < 100:
        raise HTTPException(400, "Image file too small")

    try:
        img = Image.open(io.BytesIO(content))
        img.verify()
    except Exception:
        raise HTTPException(400, "Invalid image file")

    today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    ts = datetime.now(timezone.utc).strftime("%H%M%S")
    filename = f"{position}_{gate_pass_id}_{ts}.jpg"
    save_dir = os.path.join(_uploads_base(), "gate", today_str)
    os.makedirs(save_dir, exist_ok=True)
    full_path = os.path.join(save_dir, filename)
    with open(full_path, "wb") as f:
        f.write(content)
    rel_path = f"uploads/gate/{today_str}/{filename}"

    photo_col = "entry_photo_path" if position == "entry" else "exit_photo_path"

    from app.database import get_tenant_session
    _session_cm = await get_tenant_session(tenant_slug if settings.MULTI_TENANT else None)
    async with _session_cm as db:
        await db.execute(
            text(f"UPDATE gate_passes SET {photo_col} = :p, updated_at = NOW() WHERE id = :gid"),  # noqa: S608
            {"p": rel_path, "gid": gate_pass_id},
        )
        await db.commit()

    logger.info("Agent gate photo: gp=%s position=%s path=%s", gate_pass_id, position, rel_path)
    return {"success": True, "gate_pass_id": gate_pass_id, "position": position, "path": rel_path}


# ── Serialisation helpers ─────────────────────────────────────────────────────

def _serialize_one(row: dict) -> dict:
    out = {}
    for k, v in row.items():
        if isinstance(v, UUID):
            out[k] = str(v)
        elif isinstance(v, (datetime, date)):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


def _serialize(rows: list[dict]) -> list[dict]:
    return [_serialize_one(r) for r in rows]
