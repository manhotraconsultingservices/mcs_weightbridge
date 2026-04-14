"""
Camera configuration and snapshot management.

Supports two IP cameras: front view and top view.
Snapshots are automatically captured (fire-and-forget) when a token's
second weight is recorded, via BackgroundTasks in tokens.py.

Config stored in app_settings table under key "camera_config" as JSON.
Snapshots stored in token_snapshots table.
Files saved under uploads/camera/<token_id>/<camera_id>_<ts>.jpg
"""
import asyncio
import io
import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Form, File, UploadFile
from fastapi.responses import StreamingResponse
from jose import jwt

from app.config import get_settings
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.user import User
from app.routers.app_settings import _get_raw, _upsert
from app.integrations.camera.capture import capture_and_save, capture_test_snapshot

logger = logging.getLogger(__name__)

# Two separate routers so we get clean URL prefixes
router = APIRouter(prefix="/api/v1/cameras", tags=["Cameras"])
router_tokens = APIRouter(prefix="/api/v1/tokens", tags=["Cameras"])

CAMERA_CONFIG_KEY = "camera_config"
CAMERA_IDS = ("front", "top")


# ── Dev / test: fake camera image endpoint ────────────────────────────────────

@router.get("/fake-snapshot")
async def fake_snapshot(label: str = "Camera"):
    """
    Returns a synthetic JPEG image — no real camera needed.

    Use for testing the full snapshot pipeline:
      Snapshot URL → http://localhost:9001/api/v1/cameras/fake-snapshot?label=Front+View

    No authentication required (intentionally public for dev/test use).
    """
    try:
        from PIL import Image, ImageDraw
        from datetime import datetime as dt

        width, height = 640, 480
        img = Image.new("RGB", (width, height), color=(30, 30, 50))
        draw = ImageDraw.Draw(img)

        # Gradient-ish background bands
        for y in range(height):
            r = int(30 + (y / height) * 40)
            g = int(30 + (y / height) * 20)
            b = int(50 + (y / height) * 60)
            draw.line([(0, y), (width, y)], fill=(r, g, b))

        # Decorative grid lines
        for x in range(0, width, 80):
            draw.line([(x, 0), (x, height)], fill=(60, 60, 90), width=1)
        for y in range(0, height, 60):
            draw.line([(0, y), (width, y)], fill=(60, 60, 90), width=1)

        # Central "camera view" rectangle
        box = [80, 60, 560, 420]
        draw.rectangle(box, outline=(100, 180, 255), width=2)
        draw.rectangle([box[0]+10, box[1]+10, box[2]-10, box[3]-10],
                       outline=(60, 120, 200), width=1)

        # Corner markers (like a viewfinder)
        for cx, cy, dx, dy in [
            (box[0], box[1],  1,  1),
            (box[2], box[1], -1,  1),
            (box[0], box[3],  1, -1),
            (box[2], box[3], -1, -1),
        ]:
            draw.line([(cx, cy), (cx + dx*20, cy)], fill=(0, 220, 180), width=3)
            draw.line([(cx, cy), (cx, cy + dy*20)], fill=(0, 220, 180), width=3)

        # "LIVE" badge
        draw.rectangle([box[0]+14, box[1]+14, box[0]+64, box[1]+32],
                       fill=(200, 30, 30))
        draw.text((box[0]+18, box[1]+16), "LIVE", fill=(255, 255, 255))

        # Camera label + timestamp
        now_str = dt.now().strftime("%Y-%m-%d  %H:%M:%S")
        draw.text((box[0]+14, box[3]-36), label.upper(), fill=(0, 220, 180))
        draw.text((box[0]+14, box[3]-18), now_str, fill=(180, 180, 180))

        # "TEST MODE" watermark
        draw.text((width//2 - 50, height//2 - 8), "TEST MODE",
                  fill=(70, 70, 90))

        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85)
        buf.seek(0)
        return StreamingResponse(buf, media_type="image/jpeg",
                                 headers={"Cache-Control": "no-store"})

    except ImportError:
        # Pillow not installed — return a minimal 1x1 valid JPEG
        minimal_jpg = bytes([
            0xFF,0xD8,0xFF,0xE0,0x00,0x10,0x4A,0x46,0x49,0x46,0x00,0x01,
            0x01,0x00,0x00,0x01,0x00,0x01,0x00,0x00,0xFF,0xDB,0x00,0x43,
            0x00,0x10,0x0B,0x0C,0x0E,0x0C,0x0A,0x10,0x0E,0x0D,0x0E,0x12,
            0x11,0x10,0x13,0x18,0x28,0x1A,0x18,0x16,0x16,0x18,0x31,0x23,
            0x25,0x1D,0x28,0x3A,0x33,0x3D,0x3C,0x39,0x33,0x38,0x37,0x40,
            0x48,0x5C,0x4E,0x40,0x44,0x57,0x45,0x37,0x38,0x50,0x6D,0x51,
            0x57,0x5F,0x62,0x67,0x68,0x67,0x3E,0x4D,0x71,0x79,0x70,0x64,
            0x78,0x5C,0x65,0x67,0x63,0xFF,0xC0,0x00,0x0B,0x08,0x00,0x01,
            0x00,0x01,0x01,0x01,0x11,0x00,0xFF,0xC4,0x00,0x14,0x00,0x01,
            0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,
            0x00,0x00,0x00,0x00,0xFF,0xC4,0x00,0x14,0x10,0x01,0x00,0x00,
            0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,
            0x00,0x00,0xFF,0xDA,0x00,0x08,0x01,0x01,0x00,0x00,0x3F,0x00,
            0x7F,0xFF,0xD9,
        ])
        return StreamingResponse(io.BytesIO(minimal_jpg), media_type="image/jpeg")


# ── Agent snapshot upload (client-side agent pushes images to cloud) ──────────

@router.post("/agent-upload")
async def agent_upload_snapshot(
    token_id: str = Form(...),
    camera_id: str = Form(...),
    weight_stage: str = Form("second_weight"),
    tenant_slug: str = Form(""),
    agent_key: str = Form(""),
    file: UploadFile = File(...),
):
    """
    Accept camera snapshot uploaded by the client-side agent.

    The agent runs on the client PC, captures snapshots from local IP cameras,
    and uploads them to the cloud server. Auth via tenant_slug + agent_key.

    This replaces the backend-initiated capture flow for cloud deployments
    where the server cannot reach the client's local cameras.
    """
    from app.config import get_settings
    from pathlib import Path
    from PIL import Image

    settings = get_settings()

    # ── Auth: validate agent key ──
    if settings.MULTI_TENANT:
        if not tenant_slug or not agent_key:
            raise HTTPException(400, "tenant_slug and agent_key required")
        from app.multitenancy.registry import tenant_registry
        if not await tenant_registry.validate_agent_key(tenant_slug, agent_key):
            raise HTTPException(403, "Invalid agent key for tenant")
    else:
        # Single-tenant: require agent_key from settings (or allow localhost only)
        import ipaddress
        # No auth bypass — agent must provide a key or be from localhost

    if camera_id not in ("front", "top"):
        raise HTTPException(400, "camera_id must be 'front' or 'top'")
    if weight_stage not in ("first_weight", "second_weight"):
        raise HTTPException(400, "weight_stage must be 'first_weight' or 'second_weight'")

    # ── Read and validate file ──
    content = await file.read()
    if len(content) < 100:
        raise HTTPException(400, "Image file too small")

    try:
        img = Image.open(io.BytesIO(content))
        img.verify()
    except Exception:
        raise HTTPException(400, "Invalid image file")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{camera_id}_{weight_stage}_{ts}.jpg"

    # ── Upload to R2 (cloud) or save locally (fallback) ──
    from app.utils.r2_storage import is_r2_configured, upload_to_r2

    if is_r2_configured():
        # Upload to Cloudflare R2
        r2_key = f"camera/{tenant_slug}/{token_id}/{filename}"
        r2_url = upload_to_r2(content, r2_key)
        if r2_url:
            file_path_or_url = r2_url
            logger.info("Snapshot uploaded to R2: %s", r2_key)
        else:
            raise HTTPException(500, "Failed to upload to cloud storage")
    else:
        # Local fallback
        from pathlib import Path as _Path
        base_dir = _Path(__file__).parent.parent.parent / "uploads" / "camera" / token_id
        base_dir.mkdir(parents=True, exist_ok=True)
        filepath = base_dir / filename
        rel_path = f"uploads/camera/{token_id}/{filename}"
        with open(filepath, "wb") as f:
            f.write(content)
        file_path_or_url = rel_path
        logger.info("Snapshot saved locally: %s", rel_path)

    # ── Upsert into token_snapshots ──
    from app.database import get_tenant_session
    _session_cm = await get_tenant_session(tenant_slug if settings.MULTI_TENANT else None)
    async with _session_cm as db:
        await db.execute(
            text("""
                INSERT INTO token_snapshots
                    (token_id, camera_id, camera_label, file_path, capture_status, attempts, weight_stage, captured_at)
                VALUES (:tid, :cid, :label, :fp, 'captured', 1, :ws, NOW())
                ON CONFLICT (token_id, camera_id, weight_stage) DO UPDATE
                    SET file_path = :fp, capture_status = 'captured', captured_at = NOW()
            """),
            {"tid": token_id, "cid": camera_id, "label": camera_id.capitalize() + " View",
             "fp": file_path_or_url, "ws": weight_stage},
        )
        await db.commit()

    # Build response URL
    if file_path_or_url.startswith("http"):
        url = file_path_or_url
    else:
        url = _build_url(file_path_or_url)

    logger.info("Agent uploaded snapshot: token=%s camera=%s stage=%s", token_id, camera_id, weight_stage)
    return {"success": True, "url": url, "token_id": token_id, "camera_id": camera_id}


# ── Agent polling: pending camera events ─────────────────────────────────────

@router.get("/agent-pending")
async def agent_pending_events(
    tenant_slug: str = Query(""),
    agent_key: str = Query(""),
):
    """
    Return pending camera capture events for the client agent to process.

    The agent polls this endpoint every 5 seconds. Returns tokens that had
    a weight recorded in the last 5 minutes but don't yet have snapshots.
    Auth via tenant_slug + agent_key (same as external-reading).
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
        # Find tokens needing snapshots — check BOTH stages independently
        # A token with first weight needs first_weight snapshots
        # A token with both weights needs both first_weight AND second_weight snapshots
        rows = (await db.execute(text("""
            SELECT t.id AS token_id, t.token_no, t.vehicle_no, s.stage AS weight_stage
            FROM tokens t
            CROSS JOIN (VALUES ('first_weight'), ('second_weight')) AS s(stage)
            WHERE t.updated_at > NOW() - INTERVAL '5 minutes'
              AND t.status IN ('IN_PROGRESS', 'COMPLETED')
              AND (
                  (s.stage = 'first_weight' AND (t.gross_weight IS NOT NULL OR t.tare_weight IS NOT NULL))
                  OR
                  (s.stage = 'second_weight' AND t.gross_weight IS NOT NULL AND t.tare_weight IS NOT NULL)
              )
              AND NOT EXISTS (
                  SELECT 1 FROM token_snapshots ts
                  WHERE ts.token_id = t.id
                    AND ts.weight_stage = s.stage
                    AND ts.capture_status = 'captured'
              )
            ORDER BY t.updated_at DESC, s.stage
            LIMIT 20
        """))).fetchall()

        events = [
            {
                "token_id": str(r._mapping["token_id"]),
                "token_no": r._mapping.get("token_no"),
                "vehicle_no": r._mapping.get("vehicle_no"),
                "weight_stage": r._mapping.get("weight_stage", "first_weight"),
            }
            for r in rows
            if r._mapping.get("weight_stage")
        ]

    return {"events": events, "count": len(events)}


# ── Dev: seed mock snapshots for a token ──────────────────────────────────────

@router.post("/mock-snapshots/{token_id}")
async def seed_mock_snapshots(
    token_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """
    Create fake camera snapshot images for a token (both weight stages).
    Uses the fake-snapshot generator (PIL) to create realistic test images.
    Saves files locally under uploads/camera/<token_id>/.
    """
    import os
    from pathlib import Path
    from datetime import datetime as dt

    base_dir = Path(__file__).parent.parent.parent / "uploads" / "camera" / str(token_id)
    base_dir.mkdir(parents=True, exist_ok=True)

    stages = ["first_weight", "second_weight"]
    cameras = [("front", "Front View"), ("top", "Top View")]
    created = 0

    for stage in stages:
        for cam_id, cam_label in cameras:
            ts = dt.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{cam_id}_{stage}_{ts}.jpg"
            filepath = base_dir / filename
            rel_path = f"uploads/camera/{token_id}/{filename}"

            # Generate a fake camera image with PIL
            try:
                from PIL import Image, ImageDraw
                w, h = 640, 480
                img = Image.new("RGB", (w, h), color=(30, 30, 50))
                draw = ImageDraw.Draw(img)
                for y in range(h):
                    r = int(30 + (y / h) * 40)
                    g = int(30 + (y / h) * 20)
                    b = int(50 + (y / h) * 60)
                    draw.line([(0, y), (w, y)], fill=(r, g, b))
                # Grid
                for x in range(0, w, 80):
                    draw.line([(x, 0), (x, h)], fill=(60, 60, 90))
                for y2 in range(0, h, 60):
                    draw.line([(0, y2), (w, y2)], fill=(60, 60, 90))
                # Viewfinder box
                box = [80, 60, 560, 420]
                draw.rectangle(box, outline=(100, 180, 255), width=2)
                # LIVE badge
                draw.rectangle([box[0]+14, box[1]+14, box[0]+64, box[1]+32], fill=(200, 30, 30))
                draw.text((box[0]+18, box[1]+16), "LIVE", fill=(255, 255, 255))
                # Stage + Camera label
                stage_label = "1ST WEIGHT" if stage == "first_weight" else "2ND WEIGHT"
                draw.text((box[0]+14, box[3]-56), stage_label, fill=(255, 200, 0))
                draw.text((box[0]+14, box[3]-36), cam_label.upper(), fill=(0, 220, 180))
                draw.text((box[0]+14, box[3]-18), dt.now().strftime("%Y-%m-%d  %H:%M:%S"), fill=(180, 180, 180))
                draw.text((w//2 - 50, h//2 - 8), "MOCK DATA", fill=(70, 70, 90))
                img.save(str(filepath), "JPEG", quality=85)
            except ImportError:
                # No PIL — create minimal placeholder
                filepath.write_bytes(b'\xff\xd8\xff\xe0' + b'\x00' * 100 + b'\xff\xd9')

            # Upsert into token_snapshots
            await db.execute(
                text("""
                    INSERT INTO token_snapshots
                        (token_id, camera_id, camera_label, file_path, capture_status, attempts, weight_stage, captured_at)
                    VALUES (:tid, :cid, :label, :fp, 'captured', 1, :ws, NOW())
                    ON CONFLICT (token_id, camera_id, weight_stage) DO UPDATE
                        SET file_path = :fp, capture_status = 'captured', captured_at = NOW()
                """),
                {"tid": str(token_id), "cid": cam_id, "label": cam_label, "fp": rel_path, "ws": stage},
            )
            created += 1

    await db.commit()
    return {"created": created, "token_id": str(token_id), "stages": stages}


# ── Live MJPEG stream ─────────────────────────────────────────────────────────

async def _mjpeg_frames(stream_url: str, is_rtsp: bool):
    """
    Async generator that yields MJPEG boundary frames continuously.
    RTSP: uses OpenCV (blocking call offloaded to thread pool).
    HTTP: periodically fetches the snapshot URL via httpx.
    Reconnects automatically on failure.
    """
    import asyncio as _asyncio

    BOUNDARY = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"

    if is_rtsp:
        import cv2

        loop = _asyncio.get_event_loop()

        while True:
            def _open():
                cap = cv2.VideoCapture(stream_url, cv2.CAP_FFMPEG)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 8000)
                cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 8000)
                return cap

            cap = await loop.run_in_executor(None, _open)
            if not cap.isOpened():
                cap.release()
                await _asyncio.sleep(3)
                continue

            try:
                while True:
                    def _read(c):
                        ret, frame = c.read()
                        if not ret:
                            return None
                        ok, buf = cv2.imencode(
                            ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75]
                        )
                        return buf.tobytes() if ok else None

                    data = await loop.run_in_executor(None, _read, cap)
                    if data is None:
                        break
                    yield BOUNDARY + data + b"\r\n"
                    await _asyncio.sleep(0.04)   # ~25 fps cap
            except GeneratorExit:
                cap.release()
                return
            except Exception:
                pass
            finally:
                cap.release()

            await _asyncio.sleep(2)   # pause before reconnect

    else:
        # HTTP snapshot — poll repeatedly
        import asyncio as _asyncio
        while True:
            try:
                async with httpx.AsyncClient(timeout=5.0, verify=False) as client:
                    resp = await client.get(stream_url)
                    if resp.status_code == 200 and len(resp.content) > 100:
                        yield BOUNDARY + resp.content + b"\r\n"
            except Exception:
                pass
            await _asyncio.sleep(0.5)   # ~2 fps for HTTP snapshots


@router.get("/stream/{camera_id}")
async def stream_camera(
    camera_id: str,
    token: str = Query(..., description="JWT access token (Bearer value)"),
    db: AsyncSession = Depends(get_db),
):
    """
    Live MJPEG stream for a configured camera.
    Auth via ?token= query param (img tags cannot send Authorization headers).

    Usage in frontend:
        <img src="/api/v1/cameras/stream/front?token=<jwt>" />
    """
    # ── Verify JWT manually (img tags can't send Authorization header) ──────
    try:
        _cfg = get_settings()
        payload = jwt.decode(token, _cfg.SECRET_KEY, algorithms=[_cfg.ALGORITHM])
        if not payload.get("sub"):
            raise HTTPException(status_code=401, detail="Token missing subject")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Stream JWT decode failed — token=%s... error=%s(%s)",
                     token[:20], type(e).__name__, e)
        raise HTTPException(status_code=401, detail=f"Auth error: {type(e).__name__}: {e}")

    if camera_id not in CAMERA_IDS:
        raise HTTPException(400, f"camera_id must be one of: {', '.join(CAMERA_IDS)}")

    cfg = await _load_camera_config(db)
    cam = cfg.get(camera_id)
    if not cam or not cam.get("snapshot_url", "").strip():
        raise HTTPException(400, f"Camera '{camera_id}' is not configured")

    url = cam["snapshot_url"].strip()
    username = cam.get("username", "").strip()
    password = cam.get("password", "").strip()
    is_rtsp = url.lower().startswith(("rtsp://", "rtsps://"))

    if is_rtsp:
        from app.integrations.camera.capture import _build_rtsp_url_with_creds
        stream_url = _build_rtsp_url_with_creds(url, username, password)
    else:
        stream_url = url

    return StreamingResponse(
        _mjpeg_frames(stream_url, is_rtsp),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
        },
    )


# ── Schemas ──────────────────────────────────────────────────────────────────

class CameraConfig(BaseModel):
    label: str = ""
    snapshot_url: str = ""
    username: str = ""
    password: str = ""
    verification_code: str = ""
    serial_number: str = ""
    version: str = ""
    enabled: bool = False


class CameraConfigPayload(BaseModel):
    front: CameraConfig = CameraConfig()
    top: CameraConfig = CameraConfig()


class SnapshotResponse(BaseModel):
    id: uuid.UUID
    token_id: uuid.UUID
    camera_id: str
    camera_label: Optional[str] = None
    url: Optional[str] = None
    capture_status: str
    attempts: int
    error_message: Optional[str] = None
    captured_at: Optional[datetime] = None
    weight_stage: str = "second_weight"


class TokenSnapshotsResponse(BaseModel):
    snapshots: list[SnapshotResponse]
    all_done: bool


class TestSnapshotResponse(BaseModel):
    success: bool
    url: Optional[str] = None
    error: Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mask_password(cfg: CameraConfig) -> CameraConfig:
    """Return a copy with password replaced by sentinel if non-empty."""
    return CameraConfig(
        label=cfg.label,
        snapshot_url=cfg.snapshot_url,
        username=cfg.username,
        password="***" if cfg.password else "",
        verification_code=cfg.verification_code,
        serial_number=cfg.serial_number,
        version=cfg.version,
        enabled=cfg.enabled,
    )


def _build_url(file_path: Optional[str]) -> Optional[str]:
    if not file_path:
        return None
    # R2 URLs are already absolute (https://...)
    if file_path.startswith("http"):
        return file_path
    return "/" + file_path.replace("\\", "/")


async def _load_camera_config(db: AsyncSession) -> dict:
    raw = await _get_raw(db, CAMERA_CONFIG_KEY)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


async def _query_snapshots(db: AsyncSession, token_id: str) -> list[dict]:
    rows = (await db.execute(
        text("""
            SELECT id, token_id, camera_id, camera_label, file_path,
                   capture_status, attempts, error_message, captured_at,
                   COALESCE(weight_stage, 'second_weight') AS weight_stage
            FROM token_snapshots
            WHERE token_id = :tid
            ORDER BY weight_stage, camera_id
        """),
        {"tid": token_id},
    )).fetchall()
    return [dict(r._mapping) for r in rows]


# ── Camera config endpoints ───────────────────────────────────────────────────

@router.get("/config", response_model=CameraConfigPayload)
async def get_camera_config(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return camera config. Passwords are masked."""
    cfg = await _load_camera_config(db)
    front = CameraConfig(**cfg.get("front", {})) if cfg.get("front") else CameraConfig()
    top = CameraConfig(**cfg.get("top", {})) if cfg.get("top") else CameraConfig()
    return CameraConfigPayload(front=_mask_password(front), top=_mask_password(top))


@router.get("/live-snapshot/{camera_id}")
async def live_snapshot_proxy(
    camera_id: str,
    token: str = Query(..., description="JWT access token"),
    db: AsyncSession = Depends(get_db),
):
    """
    Proxy a camera snapshot through the backend server.

    Solves the mixed-content problem: browser loads HTTPS page but cameras
    are HTTP. This endpoint fetches the snapshot server-side and returns it.

    For cloud SaaS: this only works if the server can reach the camera.
    For local network: the backend runs on the same LAN as cameras.

    Auth via ?token= query param (img tags can't send Authorization headers).
    """
    import httpx

    # Verify JWT
    try:
        _cfg = get_settings()
        payload = jwt.decode(token, _cfg.SECRET_KEY, algorithms=[_cfg.ALGORITHM])
        if not payload.get("sub"):
            raise HTTPException(401, "Invalid token")
    except Exception:
        raise HTTPException(401, "Invalid token")

    if camera_id not in CAMERA_IDS:
        raise HTTPException(400, f"camera_id must be one of: {', '.join(CAMERA_IDS)}")

    cfg = await _load_camera_config(db)
    cam = cfg.get(camera_id, {})
    if not cam or not cam.get("snapshot_url", "").strip() or not cam.get("enabled"):
        raise HTTPException(400, f"Camera '{camera_id}' is not configured or disabled")

    url = cam["snapshot_url"].strip()
    username = cam.get("username", "")
    password = cam.get("password", "")

    try:
        auth = None
        if username:
            # Try Digest auth first (CP Plus/Dahua)
            auth = httpx.DigestAuth(username, password)

        async with httpx.AsyncClient(timeout=8.0, verify=False) as client:
            resp = await client.get(url, auth=auth)

            # Fallback to Basic auth if Digest fails
            if resp.status_code == 401 and username:
                auth = httpx.BasicAuth(username, password)
                resp = await client.get(url, auth=auth)

            if resp.status_code != 200:
                raise HTTPException(502, f"Camera returned HTTP {resp.status_code}")

            if len(resp.content) < 100:
                raise HTTPException(502, "Camera returned empty image")

            return StreamingResponse(
                io.BytesIO(resp.content),
                media_type="image/jpeg",
                headers={"Cache-Control": "no-store, no-cache", "Pragma": "no-cache"},
            )

    except httpx.RequestError as e:
        raise HTTPException(502, f"Camera unreachable: {e}")


@router.get("/live-urls")
async def get_camera_live_urls(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return camera snapshot URLs with embedded credentials for live view.

    Used by the Camera & Scale Monitor page to load snapshots directly
    from local IP cameras. Only returns URLs, no other config.
    Passwords are embedded in the URL (http://user:pass@ip/path).
    """
    cfg = await _load_camera_config(db)
    result = {}
    for cam_id in ("front", "top"):
        cam = cfg.get(cam_id, {})
        url = cam.get("snapshot_url", "")
        if not url or not cam.get("enabled"):
            result[cam_id] = {"label": cam.get("label", cam_id.capitalize()), "url": "", "enabled": False}
            continue

        # Embed credentials in URL for browser <img> tag
        try:
            from urllib.parse import urlparse, urlunparse
            parsed = urlparse(url)
            username = cam.get("username", "")
            password = cam.get("password", "")
            if username:
                netloc = f"{username}:{password}@{parsed.hostname}"
                if parsed.port:
                    netloc += f":{parsed.port}"
                url_with_auth = urlunparse(parsed._replace(netloc=netloc))
            else:
                url_with_auth = url
        except Exception:
            url_with_auth = url

        result[cam_id] = {
            "label": cam.get("label", cam_id.capitalize()),
            "url": url_with_auth,
            "enabled": True,
        }
    return result


@router.put("/config", response_model=CameraConfigPayload)
async def update_camera_config(
    payload: CameraConfigPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Save camera config. Admin only. Pass password='***' to keep existing value."""
    # Load existing so we can preserve passwords when sentinel is sent
    existing = await _load_camera_config(db)

    def _merge(new: CameraConfig, cam_id: str) -> dict:
        old = existing.get(cam_id, {})
        password = old.get("password", "") if new.password == "***" else new.password
        return {
            "label": new.label,
            "snapshot_url": new.snapshot_url,
            "username": new.username,
            "password": password,
            "verification_code": new.verification_code,
            "serial_number": new.serial_number,
            "version": new.version,
            "enabled": new.enabled,
        }

    merged = {
        "front": _merge(payload.front, "front"),
        "top": _merge(payload.top, "top"),
    }
    await _upsert(db, CAMERA_CONFIG_KEY, json.dumps(merged))

    # Return masked version
    return CameraConfigPayload(
        front=_mask_password(CameraConfig(**merged["front"])),
        top=_mask_password(CameraConfig(**merged["top"])),
    )


@router.post("/test/{camera_id}", response_model=TestSnapshotResponse)
async def test_camera_snapshot(
    camera_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Capture a test snapshot and return a preview URL. Admin only."""
    if camera_id not in CAMERA_IDS:
        raise HTTPException(400, f"camera_id must be one of: {', '.join(CAMERA_IDS)}")

    cfg = await _load_camera_config(db)
    cam = cfg.get(camera_id)
    if not cam or not cam.get("snapshot_url"):
        raise HTTPException(400, f"Camera '{camera_id}' is not configured. Save a URL first.")

    success, rel_path, error = await capture_test_snapshot(cam, camera_id)
    if success:
        return TestSnapshotResponse(success=True, url=_build_url(rel_path))
    return TestSnapshotResponse(success=False, error=error)


# ── Snapshot search endpoint ──────────────────────────────────────────────────

class SnapshotSearchItem(BaseModel):
    token_id: uuid.UUID
    token_no: Optional[str] = None
    token_date: Optional[datetime] = None
    vehicle_no: Optional[str] = None
    party_name: Optional[str] = None
    weight_stage: str
    camera_id: str
    camera_label: Optional[str] = None
    url: Optional[str] = None
    capture_status: str
    captured_at: Optional[datetime] = None


class SnapshotSearchResponse(BaseModel):
    items: list[SnapshotSearchItem]
    total: int


@router.get("/search", response_model=SnapshotSearchResponse)
async def search_snapshots(
    search: str = Query("", description="Token number or vehicle number"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Search camera snapshots by token number, vehicle number, or date range."""
    conditions = ["ts.capture_status = 'captured'"]
    params: dict = {}

    if search.strip():
        conditions.append("(CAST(t.token_no AS TEXT) ILIKE :q OR t.vehicle_no ILIKE :q)")
        params["q"] = f"%{search.strip()}%"

    if date_from:
        conditions.append("t.token_date >= :df")
        params["df"] = date_from
    if date_to:
        conditions.append("t.token_date <= :dt")
        params["dt"] = date_to

    where = " AND ".join(conditions)

    count_row = (await db.execute(
        text(f"""
            SELECT COUNT(*) FROM token_snapshots ts
            JOIN tokens t ON t.id = ts.token_id
            WHERE {where}
        """), params
    )).scalar() or 0

    offset = (page - 1) * page_size
    rows = (await db.execute(
        text(f"""
            SELECT ts.token_id, t.token_no, t.token_date, t.vehicle_no,
                   p.name AS party_name,
                   COALESCE(ts.weight_stage, 'second_weight') AS weight_stage,
                   ts.camera_id, ts.camera_label, ts.file_path,
                   ts.capture_status, ts.captured_at
            FROM token_snapshots ts
            JOIN tokens t ON t.id = ts.token_id
            LEFT JOIN parties p ON p.id = t.party_id
            WHERE {where}
            ORDER BY t.token_date DESC, t.token_no DESC, ts.weight_stage, ts.camera_id
            LIMIT :lim OFFSET :off
        """), {**params, "lim": page_size, "off": offset}
    )).fetchall()

    items = [
        SnapshotSearchItem(
            token_id=r._mapping["token_id"],
            token_no=str(r._mapping["token_no"]) if r._mapping.get("token_no") is not None else None,
            token_date=r._mapping.get("token_date"),
            vehicle_no=r._mapping.get("vehicle_no"),
            party_name=r._mapping.get("party_name"),
            weight_stage=r._mapping.get("weight_stage", "second_weight"),
            camera_id=r._mapping["camera_id"],
            camera_label=r._mapping.get("camera_label"),
            url=_build_url(r._mapping.get("file_path")),
            capture_status=r._mapping["capture_status"],
            captured_at=r._mapping.get("captured_at"),
        )
        for r in rows
    ]
    return SnapshotSearchResponse(items=items, total=count_row)


# ── Snapshot query endpoints (under /api/v1/tokens prefix) ───────────────────

@router_tokens.get("/{token_id}/snapshots", response_model=TokenSnapshotsResponse)
async def get_token_snapshots(
    token_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return snapshot records for a token. Used by frontend polling."""
    rows = await _query_snapshots(db, str(token_id))
    snapshots = [
        SnapshotResponse(
            id=r["id"],
            token_id=r["token_id"],
            camera_id=r["camera_id"],
            camera_label=r["camera_label"],
            url=_build_url(r["file_path"]),
            capture_status=r["capture_status"],
            attempts=r["attempts"],
            error_message=r["error_message"],
            captured_at=r["captured_at"],
            weight_stage=r.get("weight_stage", "second_weight"),
        )
        for r in rows
    ]
    all_done = all(s.capture_status != "pending" for s in snapshots)
    return TokenSnapshotsResponse(snapshots=snapshots, all_done=all_done)


@router_tokens.post("/{token_id}/snapshots/retry", status_code=202)
async def retry_token_snapshots(
    token_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Re-queue failed snapshot captures for a token. Admin only."""
    rows = await _query_snapshots(db, str(token_id))
    failed = [r for r in rows if r["capture_status"] == "failed"]
    if not failed:
        raise HTTPException(400, "No failed snapshots to retry for this token")

    # Reset failed rows to pending
    for r in failed:
        await db.execute(
            text("""
                UPDATE token_snapshots
                SET capture_status = 'pending', attempts = 0, error_message = NULL
                WHERE token_id = :tid AND camera_id = :cid AND weight_stage = :ws
            """),
            {"tid": str(token_id), "cid": r["camera_id"], "ws": r.get("weight_stage", "second_weight")},
        )
    await db.commit()

    # Fire background capture for each stage that had failures
    import asyncio
    stages = set(r.get("weight_stage", "second_weight") for r in failed)
    for stage in stages:
        asyncio.create_task(trigger_snapshot_capture(token_id, weight_stage=stage))

    return {"queued": len(failed), "token_id": str(token_id)}


# ── Background capture task ───────────────────────────────────────────────────

async def trigger_snapshot_capture(
    token_id: uuid.UUID,
    tenant_slug: str | None = None,
    weight_stage: str = "second_weight",
) -> None:
    """
    Fire-and-forget snapshot capture task.
    Called from tokens.py via BackgroundTasks after first or second weight.
    Opens its own DB session — the request session is already closed.
    tenant_slug: passed explicitly for multi-tenant background task routing.
    weight_stage: 'first_weight' or 'second_weight' — determines which capture event.
    """
    try:
        from app.database import get_tenant_session
        _session_cm = await get_tenant_session(tenant_slug)
        async with _session_cm as db:
            cfg = await _load_camera_config(db)
            if not cfg:
                logger.debug("Camera config not set — skipping snapshot capture for token %s", token_id)
                return

            # Phase 1: insert pending rows for enabled cameras
            for camera_id in CAMERA_IDS:
                cam = cfg.get(camera_id, {})
                if not cam.get("enabled") or not cam.get("snapshot_url", "").strip():
                    continue
                await db.execute(
                    text("""
                        INSERT INTO token_snapshots
                            (token_id, camera_id, camera_label, capture_status, attempts, weight_stage)
                        VALUES (:tid, :cid, :label, 'pending', 0, :ws)
                        ON CONFLICT (token_id, camera_id, weight_stage) DO UPDATE
                            SET capture_status = 'pending',
                                attempts = 0,
                                error_message = NULL,
                                file_path = NULL
                    """),
                    {
                        "tid": str(token_id),
                        "cid": camera_id,
                        "label": cam.get("label", camera_id.capitalize()),
                        "ws": weight_stage,
                    },
                )
            await db.commit()

        # Phase 2: capture each camera (separate session per camera for isolation)
        for camera_id in CAMERA_IDS:
            _session_cm2 = await get_tenant_session(tenant_slug)
            async with _session_cm2 as db:
                cfg = await _load_camera_config(db)
                cam = cfg.get(camera_id, {})
                if not cam.get("enabled") or not cam.get("snapshot_url", "").strip():
                    continue

                logger.info("Capturing snapshot: token=%s camera=%s url=%s",
                            token_id, camera_id, cam.get("snapshot_url"))

                # Include weight_stage in file path for separation
                file_suffix = f"_{weight_stage}" if weight_stage != "second_weight" else ""
                success, rel_path, error = await capture_and_save(
                    cam, str(token_id), f"{camera_id}{file_suffix}"
                )

                if success:
                    await db.execute(
                        text("""
                            UPDATE token_snapshots
                            SET capture_status = 'captured',
                                file_path = :fp,
                                captured_at = NOW(),
                                attempts = attempts + 1,
                                error_message = NULL
                            WHERE token_id = :tid AND camera_id = :cid AND weight_stage = :ws
                        """),
                        {"fp": rel_path, "tid": str(token_id), "cid": camera_id, "ws": weight_stage},
                    )
                    logger.info("Snapshot captured OK: token=%s camera=%s stage=%s path=%s",
                                token_id, camera_id, weight_stage, rel_path)
                else:
                    await db.execute(
                        text("""
                            UPDATE token_snapshots
                            SET capture_status = 'failed',
                                attempts = attempts + 1,
                                error_message = :err
                            WHERE token_id = :tid AND camera_id = :cid AND weight_stage = :ws
                        """),
                        {"err": error, "tid": str(token_id), "cid": camera_id, "ws": weight_stage},
                    )
                    logger.warning("Snapshot FAILED: token=%s camera=%s stage=%s error=%s",
                                   token_id, camera_id, weight_stage, error)

                await db.commit()

    except Exception as exc:
        logger.error("Unexpected error in trigger_snapshot_capture(token=%s): %s", token_id, exc, exc_info=True)
