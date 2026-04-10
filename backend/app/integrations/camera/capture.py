"""
IP Camera snapshot capture utility.

Supports two URL types, auto-detected from the scheme:
  • RTSP  (rtsp:// / rtsps://) — captured via OpenCV + FFmpeg bindings.
  • HTTP  (http:// / https://)  — fetched via httpx, validated with Pillow.

Retries: 3 attempts × timeout each.
Returns: (success: bool, relative_file_path: str | None, error_message: str | None)
"""
import asyncio
import concurrent.futures
import io
import os
import sys
from datetime import datetime, timezone

import httpx
from PIL import Image


# Thread pool for blocking OpenCV calls (keeps the async event loop free)
_thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="cam_rtsp")


# ── Path helper ───────────────────────────────────────────────────────────────

def _uploads_base() -> str:
    """Resolve <project_root>/uploads/ regardless of dev vs PyInstaller."""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(   # project root
            os.path.dirname(          # backend/
                os.path.dirname(          # backend/app/
                    os.path.dirname(          # backend/app/integrations/
                        os.path.dirname(          # backend/app/integrations/camera/
                            os.path.abspath(__file__)
                        )
                    )
                )
            )
        )
    return os.path.join(base, "uploads")


# ── RTSP capture (blocking, run in thread pool) ───────────────────────────────

def _rtsp_grab_frame(rtsp_url: str, full_path: str, timeout_sec: float = 10.0) -> None:
    """
    Open an RTSP stream with OpenCV, grab one frame, and save it as JPEG.
    Raises on any failure so the caller can catch and retry.
    """
    import cv2  # local import — not needed if camera is HTTP-only

    cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)             # minimal buffer — get latest frame
    cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, timeout_sec * 1000)
    cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, timeout_sec * 1000)

    try:
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open RTSP stream: {rtsp_url}")

        # Discard a couple of buffered frames to get a fresh one
        for _ in range(3):
            cap.grab()

        ret, frame = cap.read()
        if not ret or frame is None:
            raise RuntimeError("RTSP read() returned no frame")

        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        ok = cv2.imwrite(full_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            raise RuntimeError(f"cv2.imwrite failed writing to {full_path}")
    finally:
        cap.release()


def _build_rtsp_url_with_creds(url: str, username: str, password: str) -> str:
    """
    Embed credentials into the RTSP URL if they are not already present.
    rtsp://admin:JLGMKG@192.168.1.13:554/ch1/main  ← already embedded
    rtsp://192.168.1.13:554/ch1/main               ← add admin:JLGMKG@
    """
    if not username:
        return url
    # Check if credentials are already embedded
    scheme_end = url.index("://") + 3
    rest = url[scheme_end:]
    if "@" in rest.split("/")[0]:
        return url  # already has creds
    return f"{url[:scheme_end]}{username}:{password}@{rest}"


# ── Public API ────────────────────────────────────────────────────────────────

def _is_rtsp(url: str) -> bool:
    return url.lower().startswith(("rtsp://", "rtsps://"))


async def capture_and_save(
    camera_cfg: dict,
    token_id: str,
    camera_id: str,
) -> tuple[bool, str | None, str | None]:
    """
    Fetch a snapshot from the camera and save it to disk.

    Supports both:
      • HTTP  snapshot_url  → httpx GET + Pillow validation
      • RTSP  stream URL    → OpenCV/FFmpeg frame grab (run in thread pool)

    Returns (success, relative_file_path, error_message)
    """
    url = camera_cfg.get("snapshot_url", "").strip()
    if not url:
        return False, None, "No snapshot_url configured"

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    filename = f"{camera_id}_{ts}.jpg"
    dir_path = os.path.join(_uploads_base(), "camera", token_id)
    os.makedirs(dir_path, exist_ok=True)
    full_path = os.path.join(dir_path, filename)
    rel_path = f"uploads/camera/{token_id}/{filename}"

    username = camera_cfg.get("username", "").strip()
    password = camera_cfg.get("password", "").strip()

    last_err = "Unknown error"

    # ── RTSP path ──────────────────────────────────────────────────────────────
    if _is_rtsp(url):
        rtsp_url = _build_rtsp_url_with_creds(url, username, password)
        loop = asyncio.get_event_loop()
        for attempt in range(3):
            try:
                await loop.run_in_executor(
                    _thread_pool,
                    _rtsp_grab_frame,
                    rtsp_url,
                    full_path,
                    8.0,           # 8-second timeout per attempt
                )
                return True, rel_path, None
            except Exception as exc:
                last_err = str(exc)
                if attempt < 2:
                    await asyncio.sleep(2)
        return False, None, last_err

    # ── HTTP path ─────────────────────────────────────────────────────────────
    auth = (username, password) if username else None
    extra_params: dict = {}
    if camera_cfg.get("verification_code", "").strip():
        extra_params["auth_code"] = camera_cfg["verification_code"].strip()
    if camera_cfg.get("serial_number", "").strip():
        extra_params["serial"] = camera_cfg["serial_number"].strip()
    if camera_cfg.get("version", "").strip():
        extra_params["ver"] = camera_cfg["version"].strip()

    for attempt in range(3):
        try:
            async with httpx.AsyncClient(
                timeout=5.0,
                verify=False,        # many IP cameras use self-signed certs
                follow_redirects=True,
            ) as client:
                resp = await client.get(url, auth=auth,
                                        params=extra_params if extra_params else None)
                resp.raise_for_status()

                if len(resp.content) < 100:
                    raise ValueError(f"Response too small ({len(resp.content)} bytes)")

                img = Image.open(io.BytesIO(resp.content))
                img.load()  # force full decode — catches truncated images

                if img.mode not in ("RGB", "L"):
                    img = img.convert("RGB")
                img.save(full_path, "JPEG", quality=85, optimize=True)

                return True, rel_path, None

        except Exception as exc:
            last_err = str(exc)
            if attempt < 2:
                await asyncio.sleep(1)

    return False, None, last_err


async def capture_test_snapshot(
    camera_cfg: dict,
    camera_id: str,
) -> tuple[bool, str | None, str | None]:
    """
    Capture a test snapshot (not linked to any token).
    Saves to uploads/camera/test/<camera_id>.jpg — overwrites each time.
    """
    url = camera_cfg.get("snapshot_url", "").strip()
    if not url:
        return False, None, "No snapshot_url configured"

    username = camera_cfg.get("username", "").strip()
    password = camera_cfg.get("password", "").strip()

    test_dir = os.path.join(_uploads_base(), "camera", "test")
    os.makedirs(test_dir, exist_ok=True)
    full_path = os.path.join(test_dir, f"{camera_id}.jpg")
    rel_path = f"uploads/camera/test/{camera_id}.jpg"

    # ── RTSP test ──────────────────────────────────────────────────────────────
    if _is_rtsp(url):
        rtsp_url = _build_rtsp_url_with_creds(url, username, password)
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                _thread_pool, _rtsp_grab_frame, rtsp_url, full_path, 8.0
            )
            return True, rel_path, None
        except Exception as exc:
            return False, None, str(exc)

    # ── HTTP test ─────────────────────────────────────────────────────────────
    auth = (username, password) if username else None
    extra_params: dict = {}
    if camera_cfg.get("verification_code", "").strip():
        extra_params["auth_code"] = camera_cfg["verification_code"].strip()
    if camera_cfg.get("serial_number", "").strip():
        extra_params["serial"] = camera_cfg["serial_number"].strip()
    if camera_cfg.get("version", "").strip():
        extra_params["ver"] = camera_cfg["version"].strip()

    try:
        async with httpx.AsyncClient(
            timeout=5.0, verify=False, follow_redirects=True
        ) as client:
            resp = await client.get(url, auth=auth,
                                    params=extra_params if extra_params else None)
            resp.raise_for_status()

            img = Image.open(io.BytesIO(resp.content))
            img.load()
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img.save(full_path, "JPEG", quality=85)
            return True, rel_path, None

    except Exception as exc:
        return False, None, str(exc)
