"""
Weighbridge Camera Agent — captures snapshots from local IP cameras
and uploads to cloud.

Runs on client PC. Polls the cloud server for pending camera events
(triggered when operator records a weight), captures JPEG snapshots
from local IP cameras, and uploads them to the cloud.

Usage:
  python camera_agent.py                 # run interactively
  python camera_agent.py --setup         # generate config
  python camera_agent.py --install       # install as Windows service
  python camera_agent.py --uninstall     # remove Windows service
  python camera_agent.py --test          # test camera snapshot capture

Config: camera_config.json (same directory)
"""

import copy
import collections
import json
import time
import sys
import os
import logging
from logging.handlers import RotatingFileHandler
import threading
import signal
import asyncio
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    import websockets
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False

# ── Base directory (frozen-EXE safe) ──────────────────────────────────────────
# When frozen (PyInstaller/Nuitka .exe), __file__ resolves to the TEMPORARY
# extraction dir (_MEIPASS), NOT the folder the .exe lives in. Anchor config +
# logs to the executable's own folder when frozen so it reads the
# camera_config.json sitting next to the .exe and writes a visible log there.
if getattr(sys, "frozen", False) or "__compiled__" in globals():
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent

# ── TLS CA bundle (frozen-EXE insurance) ──────────────────────────────────────
# A frozen build can lose the OS default CA path. If certifi is bundled, point
# the standard env vars at its CA bundle — only when UNSET, so a real system CA wins.
try:
    import certifi as _certifi
    _ca = _certifi.where()
    if _ca and os.path.exists(_ca):
        os.environ.setdefault("SSL_CERT_FILE", _ca)
        os.environ.setdefault("REQUESTS_CA_BUNDLE", _ca)
except Exception:
    pass

# ── Logging ──────────────────────────────────────────────────────────────────

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

# Force UTF-8 console output. A frozen EXE on a Windows cp1252 console otherwise
# raises UnicodeEncodeError on any non-ASCII log char (the box-drawing banner,
# arrows, dashes), which prints "--- Logging error ---" and SWALLOWS the real
# message. errors="replace" guarantees the line prints.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # Python 3.7+
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        # Rotating, NOT plain FileHandler: this log is never truncated otherwise,
        # and a dead camera with a browser tab open can append for months.
        # 5 MB x 3 backups = 20 MB ceiling.
        RotatingFileHandler(LOG_DIR / "camera_agent.log", maxBytes=5_000_000,
                            backupCount=3, encoding="utf-8"),
    ],
)
log = logging.getLogger("camera_agent")

# ── Throttled error logging ───────────────────────────────────────────────────
# The poll/push loops run every 3-5s. Logging every failure would flood the log
# (which does not rotate); logging none of them — the previous behaviour — made a
# dead cloud, a wrong agent key or a stale tenant slug COMPLETELY invisible while
# /status still reported "running". Log the first occurrence, then at most once
# per interval, so a persistent fault is always visible but never spams.
_last_err_log: dict[str, float] = {}


def log_throttled(key: str, msg: str, *args, every: float = 60.0) -> None:
    now = time.time()
    if now - _last_err_log.get(key, 0.0) >= every:
        _last_err_log[key] = now
        log.warning(msg, *args)


# ── Local snapshot retention ──────────────────────────────────────────────────

def prune_local_snapshots(cfg: dict) -> None:
    """Delete locally-saved snapshot folders older than `local_retention_days`.

    Snapshot folders are named YYYYMMDD, so a plain string compare is enough —
    no date parsing, and any folder that is not exactly 8 digits is left alone.
    Without this the directory grows ~120 MB/day until the disk fills, after
    which every capture fails on a swallowed write error.
    """
    days = int(cfg.get("local_retention_days", 30) or 0)
    if days <= 0:
        return                                   # 0 = keep forever (opt-out)
    root = Path(cfg.get("local_save_dir", "") or "")
    if not root.is_dir():
        return
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    removed = 0
    for d in sorted(root.iterdir()):
        try:
            if d.is_dir() and len(d.name) == 8 and d.name.isdigit() and d.name < cutoff:
                shutil.rmtree(d, ignore_errors=True)
                removed += 1
        except Exception as e:                   # noqa: BLE001
            log.warning("Prune failed for %s: %s", d, e)
    if removed:
        log.info("Pruned %d snapshot folder(s) older than %d days from %s", removed, days, root)


def warn_if_disk_low(cfg: dict, min_free_mb: int = 500) -> None:
    """Warn loudly when the snapshot volume is nearly full — otherwise a full
    disk just makes captures vanish with no visible cause."""
    root = Path(cfg.get("local_save_dir", "") or "")
    try:
        if root.is_dir():
            free_mb = shutil.disk_usage(root).free // (1024 * 1024)
            if free_mb < min_free_mb:
                log.error("LOW DISK on %s: %d MB free — snapshot saves will start failing",
                          root, free_mb)
    except Exception:                            # noqa: BLE001
        pass


def allowed_origins(cfg: dict) -> set[str]:
    """Origins permitted to read the status/snapshot servers cross-origin.

    Mirrors scale_agent._allowed_origins. A wildcard is deliberately NOT used:
    these servers bind 0.0.0.0 so the camera page can be opened from another PC
    on the plant LAN, which means `*` would let ANY website the operator happens
    to visit read live weighbridge camera frames straight off their machine.

    Derived from cloud_url + tenant_slug so a different domain needs no code
    change; extra origins come from `allowed_origins` in the config file.
    """
    from urllib.parse import urlsplit

    origins: set[str] = set()
    cloud_url = str(cfg.get("cloud_url") or "").strip()
    slug = str(cfg.get("tenant_slug") or "").strip().lower()

    host = ""
    if cloud_url:
        parts = urlsplit(cloud_url if "//" in cloud_url else f"https://{cloud_url}")
        host = (parts.hostname or "").lower()
        if host:
            origins.add(f"https://{host}")

    base = host
    for prefix in ((f"{slug}." if slug else None), "www."):
        if prefix and base.startswith(prefix):
            base = base[len(prefix):]
            break
    if base:
        origins.add(f"https://{base}")
        origins.add(f"https://www.{base}")
        if slug:
            origins.add(f"https://{slug}.{base}")

    for extra in (cfg.get("allowed_origins") or []):
        extra = str(extra).strip().rstrip("/")
        if extra:
            origins.add(extra)
    return {o for o in origins if "://" in o}


def cors_origin_for(origin: str, allow: set[str]) -> str | None:
    """Echo the request Origin only when it is allowlisted (else no CORS header)."""
    o = (origin or "").strip().rstrip("/")
    return o if o and o in allow else None


def start_maintenance_thread(cfg: dict) -> None:
    """Prune + disk-check now, then every 6 hours, on a daemon thread."""
    def _loop():
        while True:
            try:
                prune_local_snapshots(cfg)
                warn_if_disk_low(cfg)
            except Exception as e:               # noqa: BLE001
                log.warning("Maintenance pass failed: %s", e)
            time.sleep(6 * 3600)

    threading.Thread(target=_loop, daemon=True, name="SnapshotMaintenance").start()

# ── Config ───────────────────────────────────────────────────────────────────

CONFIG_FILE = BASE_DIR / "camera_config.json"

DEFAULT_CONFIG = {
    "cloud_url": "https://weighbridgesetu.com",
    "tenant_slug": "",
    "agent_key": "",
    "poll_interval_sec": 5,
    "status_port": 9003,
    "ws_port": 9004,
    # ── Local-first snapshot storage (Cloudflare Tunnel) ──────────────────────
    # Set snapshot_serve_url to enable local-first mode.  The agent saves JPEGs
    # to local_save_dir and serves them via file_serve_port.  The Cloudflare
    # Tunnel exposes that port as snapshot_serve_url so the owner can view
    # images from anywhere — no binary upload to the VPS.
    # Leave snapshot_serve_url empty to fall back to the original upload mode.
    "local_save_dir": "D:\\weighbridge\\snapshots",
    "snapshot_serve_url": "",   # e.g. https://cam-acme.weighbridgesetu.com
    "file_serve_port": 9005,
    # Locally-saved snapshots are pruned after this many days. Without it the
    # folder grows ~120 MB/day (~43 GB/yr) until the disk fills, after which
    # every capture fails. 0 disables pruning (keep forever).
    "local_retention_days": 30,
    "cameras": {
        "front": {
            "label": "Front View",
            "url": "http://192.168.0.101/cgi-bin/snapshot.cgi",
            "username": "",
            "password": "",
        },
        "top": {
            "label": "Top View",
            "url": "http://192.168.0.103/cgi-bin/snapshot.cgi",
            "username": "",
            "password": "",
        },
    },
    # Gate pass cameras — captures entry/exit photos for the Gate Register.
    # Leave url empty to reuse the front camera above (default behaviour).
    "gate_cameras": {
        "entry": {
            "label": "Gate Entry",
            "url": "",        # empty = reuse cameras.front
            "username": "",
            "password": "",
        },
        "exit": {
            "label": "Gate Exit",
            "url": "",        # empty = reuse cameras.front
            "username": "",
            "password": "",
        },
    },
}


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        log.error("Config not found: %s", CONFIG_FILE)
        log.info("Run: python camera_agent.py --setup")
        sys.exit(1)
    # utf-8-sig transparently strips an optional BOM. PowerShell's
    # `Out-File -Encoding utf8` on Windows PowerShell 5.1 writes one by
    # default, which Python's plain utf-8 reader rejects. Accept both.
    with open(CONFIG_FILE, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def save_config(cfg: dict):
    # Write plain UTF-8 (no BOM) so the file round-trips cleanly between
    # PowerShell, editors, and Python's json reader.
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    log.info("Config saved to %s", CONFIG_FILE)


def setup_wizard():
    """Interactive setup to generate camera_config.json."""
    print("\n" + "=" * 60)
    print("  Weighbridge Camera Agent — Setup")
    print("=" * 60 + "\n")

    cfg = copy.deepcopy(DEFAULT_CONFIG)

    # Client-agnostic placeholder. This prompt used to name a REAL customer, which
    # is both unprofessional in front of a different client and looks as though the
    # build is tied to that tenant. (scale_agent was fixed for this; this was missed.)
    #
    # Tenant + key are OPTIONAL here on purpose: cameras are commissioned on site,
    # often BEFORE the tenant is provisioned. Leaving them blank produces a valid
    # camera-only config you can test immediately with --test, and the cloud details
    # can be filled in later by re-running --setup.
    cfg["cloud_url"] = input(f"Cloud URL [{cfg['cloud_url']}]: ").strip() or cfg["cloud_url"]
    print("\nTenant + agent key are OPTIONAL — leave blank to configure cameras only")
    print("(you can test cameras now and add the cloud details later).")
    cfg["tenant_slug"] = input("Tenant slug (e.g. your-company-name) [skip]: ").strip()
    cfg["agent_key"] = input("Agent API key (from platform admin)   [skip]: ").strip()

    print("\n--- Camera URLs ---")
    print("Common snapshot URL formats:")
    print("  CP Plus / Dahua:  http://IP/cgi-bin/snapshot.cgi")
    print("  Hikvision:        http://IP/Streaming/channels/1/picture")
    print("  Generic:          http://IP/snap.jpg")
    print()

    cfg["cameras"]["front"]["url"] = input(f"Front camera URL [{cfg['cameras']['front']['url']}]: ").strip() or cfg["cameras"]["front"]["url"]
    cfg["cameras"]["top"]["url"] = input(f"Top camera URL [{cfg['cameras']['top']['url']}]: ").strip() or cfg["cameras"]["top"]["url"]

    cam_user = input("Camera username (leave empty if none): ").strip()
    cam_pass = input("Camera password (leave empty if none): ").strip()
    for cam in ("front", "top"):
        cfg["cameras"][cam]["username"] = cam_user
        cfg["cameras"][cam]["password"] = cam_pass

    print("\n--- Gate Cameras (for Gate Pass entry/exit photos) ---")
    print("Leave URL blank to reuse the front camera above.\n")
    gate_entry_url = input(f"Gate entry camera URL [reuse front]: ").strip()
    gate_exit_url  = input(f"Gate exit camera URL  [reuse front]: ").strip()
    if gate_entry_url:
        cfg["gate_cameras"]["entry"]["url"] = gate_entry_url
        cfg["gate_cameras"]["entry"]["username"] = cam_user
        cfg["gate_cameras"]["entry"]["password"] = cam_pass
    if gate_exit_url:
        cfg["gate_cameras"]["exit"]["url"] = gate_exit_url
        cfg["gate_cameras"]["exit"]["username"] = cam_user
        cfg["gate_cameras"]["exit"]["password"] = cam_pass

    print("\n--- Snapshot Storage Mode ---")
    print("Option 1 (recommended): Local-first via Cloudflare Tunnel")
    print("  Images saved on THIS PC.  Cloudflare Tunnel exposes them remotely.")
    print("  The server only stores the URL — no image data uploaded to VPS.")
    print()
    print("Option 2 (legacy): Upload binary to VPS")
    print("  Leave snapshot_serve_url blank to keep the old upload behaviour.")
    print()

    serve_url = input("Snapshot serve URL (e.g. https://cam-acme.weighbridgesetu.com) [leave blank for upload mode]: ").strip()
    cfg["snapshot_serve_url"] = serve_url

    if serve_url:
        default_dir = cfg["local_save_dir"]
        save_dir = input(f"Local snapshot save directory [{default_dir}]: ").strip() or default_dir
        cfg["local_save_dir"] = save_dir
        file_port = input(f"Local file server port [{cfg['file_serve_port']}]: ").strip()
        if file_port.isdigit():
            cfg["file_serve_port"] = int(file_port)

        print()
        print("  ┌─────────────────────────────────────────────────────────┐")
        print("  │  Cloudflare Tunnel setup (one-time, ~5 min)             │")
        print("  │                                                         │")
        print(f"  │  1. Edit: C:\\cloudflared\\config.yml                     │")
        print(f"  │     Add these lines:                                    │")
        print(f"  │       - hostname: {serve_url.replace('https://',''):<37}│")
        print(f"  │         service: http://localhost:{cfg['file_serve_port']:<24}│")
        print(f"  │                                                         │")
        print(f"  │  2. Restart the Cloudflare Tunnel service:              │")
        print(f"  │       nssm restart cloudflared                          │")
        print(f"  │                                                         │")
        print(f"  │  3. Verify: open {serve_url}/test in a browser  │")
        print(f"  │     (after first snapshot is captured)                  │")
        print(f"  └─────────────────────────────────────────────────────────┘")
        print()
    else:
        print("  Upload mode selected — images will be uploaded to the VPS.")
        print()

    save_config(cfg)
    print(f"\n  Config saved: {CONFIG_FILE}")
    print(f"  Test cameras: python camera_agent.py --test")
    print(f"  Start: python camera_agent.py")
    print(f"  Install as service: python camera_agent.py --install")
    print()


# ── Camera Capturer ──────────────────────────────────────────────────────────

class CameraCapturer:
    """Captures snapshots from local IP cameras and uploads to cloud."""

    def __init__(self, config: dict):
        self.cfg = config
        self.capture_count = 0
        self.error_count = 0

    def _capture_single(self, cam_url: str, cam: dict, camera_id: str) -> bytes | None:
        """Capture a single snapshot with retry and auth fallback."""
        import requests
        from requests.auth import HTTPDigestAuth, HTTPBasicAuth

        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                auth = None
                if cam.get("username"):
                    auth = HTTPDigestAuth(cam["username"], cam.get("password", ""))

                resp = requests.get(cam_url, auth=auth, timeout=10, verify=False)

                # Fallback to Basic auth if Digest fails
                if resp.status_code == 401 and auth:
                    auth = HTTPBasicAuth(cam["username"], cam.get("password", ""))
                    resp = requests.get(cam_url, auth=auth, timeout=10, verify=False)

                if resp.status_code == 200 and len(resp.content) >= 500:
                    return resp.content

                log.warning("Camera %s attempt %d: HTTP %d, %d bytes",
                            camera_id, attempt, resp.status_code, len(resp.content))

            except Exception as e:
                log.warning("Camera %s attempt %d failed: %s", camera_id, attempt, e)

            if attempt < max_retries:
                time.sleep(2)  # wait before retry

        return None

    def capture_once(self, cam_url: str, cam: dict, timeout: float = 5.0) -> bytes | None:
        """Single-attempt capture for LIVE frames — no retries.

        _capture_single retries 3x with a 10s timeout (up to ~60s on a dead
        camera). That is correct for a weighment snapshot, which must not be
        missed, but wrong for a live feed pushed every 3s: a dead ENTRY camera
        stalled the EXIT frames for 34s+ every cycle. Mirrors the fast path
        already used by WebSocketLiveServer._get_frame.
        """
        import requests
        from requests.auth import HTTPDigestAuth, HTTPBasicAuth
        try:
            auth = None
            if cam.get("username"):
                auth = HTTPDigestAuth(cam["username"], cam.get("password", ""))
            resp = requests.get(cam_url, auth=auth, timeout=timeout, verify=False)
            if resp.status_code == 401 and auth:
                auth = HTTPBasicAuth(cam["username"], cam.get("password", ""))
                resp = requests.get(cam_url, auth=auth, timeout=timeout, verify=False)
            if resp.status_code == 200 and len(resp.content) >= 500:
                return resp.content
        except Exception:  # noqa: BLE001
            return None
        return None

    def capture_and_upload(self, token_id: str, weight_stage: str = "second_weight") -> dict:
        """Capture from all cameras and upload to cloud."""
        import requests

        results = {}
        upload_url = f"{self.cfg['cloud_url'].rstrip('/')}/api/v1/cameras/agent-upload"

        for camera_id in ("front", "top"):
            cam = self.cfg.get("cameras", {}).get(camera_id, {})
            cam_url = cam.get("url", "")
            if not cam_url:
                continue

            log.info("Capturing %s: %s", camera_id, cam_url)

            # Step 1: Capture from local camera (with retry)
            image_data = self._capture_single(cam_url, cam, camera_id)
            if image_data is None:
                log.warning("Camera %s FAILED after 3 retries", camera_id)
                results[camera_id] = {"success": False, "error": "Capture failed after retries"}
                self.error_count += 1
                continue

            log.info("Captured %s: %d bytes", camera_id, len(image_data))

            # Step 2: Upload to cloud
            try:
                files = {"file": (f"{camera_id}_{weight_stage}.jpg", image_data, "image/jpeg")}
                data = {
                    "token_id": token_id,
                    "camera_id": camera_id,
                    "weight_stage": weight_stage,
                    "tenant_slug": self.cfg["tenant_slug"],
                    "agent_key": self.cfg["agent_key"],
                }
                resp = requests.post(upload_url, files=files, data=data, timeout=30)
                if resp.status_code == 200:
                    result = resp.json()
                    log.info("Uploaded %s for token %s", camera_id, token_id)
                    results[camera_id] = {"success": True, "url": result.get("url")}
                    self.capture_count += 1
                else:
                    log.warning("Upload %s failed: HTTP %d", camera_id, resp.status_code)
                    results[camera_id] = {"success": False, "error": f"Upload HTTP {resp.status_code}"}
                    self.error_count += 1

            except requests.RequestException as e:
                log.warning("Upload %s failed: %s", camera_id, e)
                results[camera_id] = {"success": False, "error": str(e)}
                self.error_count += 1

            # Small delay between cameras to avoid overwhelming DVR
            time.sleep(1)

        return results

    def _capture_single_for_live(self, camera_id: str) -> bytes | None:
        """Capture a single snapshot for live view (no upload, no retry)."""
        cam = self.cfg.get("cameras", {}).get(camera_id, {})
        cam_url = cam.get("url", "")
        if not cam_url:
            return None
        return self._capture_single(cam_url, cam, camera_id)

    def test_cameras(self) -> dict:
        """Test all cameras — capture snapshot and save locally."""
        import requests

        results = {}
        # BASE_DIR, not __file__: when frozen, __file__ is PyInstaller's _MEIPASS
        # temp dir, which is DELETED when the process exits — so the installer
        # would capture the test images and then destroy them, and the whole
        # point of --test is to eyeball the camera framing afterwards.
        test_dir = BASE_DIR / "test_snapshots"
        test_dir.mkdir(exist_ok=True)

        # Iterate whatever cameras are actually configured, not a hardcoded
        # ("front","top"). Hardcoding silently ignored any other camera id — so
        # cameras passed on the command line, or extra cameras in the config, were
        # reported as "SKIPPED (no URL)" and the run claimed nothing was tested.
        cams = self.cfg.get("cameras", {}) or {}
        for camera_id in (["front", "top"] + [k for k in cams if k not in ("front", "top")]):
            cam = cams.get(camera_id, {})
            cam_url = cam.get("url", "")
            if not cam_url:
                if camera_id in ("front", "top") and camera_id not in cams:
                    continue      # not configured at all — nothing to report
                print(f"  {camera_id}: SKIPPED (no URL)")
                continue

            try:
                auth = None
                if cam.get("username"):
                    from requests.auth import HTTPDigestAuth, HTTPBasicAuth
                    auth = HTTPDigestAuth(cam["username"], cam.get("password", ""))

                resp = requests.get(cam_url, auth=auth, timeout=10, verify=False)

                # Fallback to Basic auth if Digest fails
                if resp.status_code == 401 and auth:
                    auth = HTTPBasicAuth(cam["username"], cam.get("password", ""))
                    resp = requests.get(cam_url, auth=auth, timeout=10, verify=False)

                if resp.status_code == 200 and len(resp.content) > 500:
                    filepath = test_dir / f"test_{camera_id}.jpg"
                    with open(filepath, "wb") as f:
                        f.write(resp.content)
                    print(f"  {camera_id}: OK ({len(resp.content)} bytes) → {filepath}")
                    results[camera_id] = True
                else:
                    print(f"  {camera_id}: FAILED (HTTP {resp.status_code}, {len(resp.content)} bytes)")
                    results[camera_id] = False

            except Exception as e:
                print(f"  {camera_id}: ERROR — {e}")
                results[camera_id] = False

        return results

    def capture_local(self, token_id: str, weight_stage: str = "second_weight") -> dict:
        """Capture from all cameras, save to local disk, notify cloud with URL.

        Local-first mode (Option 1 — Cloudflare Tunnel):
          - JPEG saved to  {local_save_dir}/{YYYYMMDD}/{token_id}/{camera}_{stage}.jpg
          - Local file server (port file_serve_port) serves the file
          - Cloudflare Tunnel exposes the file server as snapshot_serve_url
          - Only the URL is POSTed to the cloud (/cameras/agent-notify) — no binary upload

        Falls back gracefully to capture_and_upload() if snapshot_serve_url is not set.
        """
        import requests

        serve_url = self.cfg.get("snapshot_serve_url", "").rstrip("/")
        if not serve_url:
            return self.capture_and_upload(token_id, weight_stage)

        save_dir_root = Path(self.cfg.get("local_save_dir", "D:\\weighbridge\\snapshots"))
        date_str = datetime.now().strftime("%Y%m%d")
        save_dir = save_dir_root / date_str / token_id
        try:
            save_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            log.error("Cannot create snapshot dir %s: %s — falling back to upload", save_dir, e)
            return self.capture_and_upload(token_id, weight_stage)

        notify_url = f"{self.cfg['cloud_url'].rstrip('/')}/api/v1/cameras/agent-notify"
        results = {}

        for camera_id in ("front", "top"):
            cam = self.cfg.get("cameras", {}).get(camera_id, {})
            cam_url = cam.get("url", "")
            if not cam_url:
                continue

            log.info("Capturing %s: %s", camera_id, cam_url)

            image_data = self._capture_single(cam_url, cam, camera_id)
            if image_data is None:
                log.warning("Camera %s FAILED after 3 retries", camera_id)
                results[camera_id] = {"success": False, "error": "Capture failed after retries"}
                self.error_count += 1
                continue

            # Save to local disk
            ts = datetime.now().strftime("%H%M%S")
            filename = f"{camera_id}_{weight_stage}_{ts}.jpg"
            filepath = save_dir / filename
            try:
                filepath.write_bytes(image_data)
            except Exception as e:
                log.error("Failed to save %s: %s", filepath, e)
                results[camera_id] = {"success": False, "error": str(e)}
                self.error_count += 1
                continue

            log.info("Saved %s: %d bytes → %s", camera_id, len(image_data), filepath)

            # Build the publicly accessible URL (via Cloudflare Tunnel)
            rel_path = f"{date_str}/{token_id}/{filename}"
            file_url = f"{serve_url}/{rel_path}"

            # Notify cloud with URL only (no binary)
            try:
                resp = requests.post(notify_url, data={
                    "token_id": token_id,
                    "camera_id": camera_id,
                    "weight_stage": weight_stage,
                    "file_url": file_url,
                    "tenant_slug": self.cfg["tenant_slug"],
                    "agent_key": self.cfg["agent_key"],
                }, timeout=15)
                if resp.status_code == 200:
                    log.info("Notified cloud: %s → %s", camera_id, file_url)
                    results[camera_id] = {"success": True, "url": file_url}
                    self.capture_count += 1
                else:
                    log.warning("Notify %s failed: HTTP %d", camera_id, resp.status_code)
                    results[camera_id] = {"success": False, "error": f"Notify HTTP {resp.status_code}"}
                    self.error_count += 1
            except requests.RequestException as e:
                log.warning("Notify %s failed: %s — image saved locally at %s", camera_id, e, filepath)
                results[camera_id] = {"success": False, "error": str(e), "local_path": str(filepath)}
                self.error_count += 1

            time.sleep(0.5)

        return results


# ── Event Listener ───────────────────────────────────────────────────────────

class EventListener:
    """Polls cloud API for pending camera capture events."""

    # Sized to the SERVER's contract: /cameras/agent-pending re-offers an event
    # for 5 minutes after the weight is recorded. 60 attempts x 5s poll = ~5 min,
    # so we keep retrying for exactly as long as the job is still on offer and
    # the server's own cutoff bounds us. (A smaller budget would give up early
    # and lose a snapshot the server was still willing to hand us.)
    MAX_CAPTURE_ATTEMPTS = 60

    def __init__(self, config: dict, capturer: CameraCapturer):
        self.cfg = config
        self.capturer = capturer
        self.running = False
        self._thread = None
        self._processed: collections.OrderedDict[str, float] = collections.OrderedDict()
        # key -> failed attempts so far. Only holds ACTIVELY failing events; an
        # entry is removed as soon as it succeeds or we give up, so it stays small.
        self._attempts: dict[str, int] = {}

    def _finish(self, key: str, results: dict, label: str) -> bool:
        """Mark an event done ONLY when the capture actually succeeded.

        Previously the event was marked processed regardless of outcome, so a
        camera that blipped during a weighment lost that snapshot permanently.
        Returns True when the event is finished with (succeeded, or given up on).
        """
        ok = bool(results) and all(r.get("success") for r in results.values())
        if ok or not results:
            # `not results` == no cameras configured for this event: nothing to retry.
            self._processed[key] = time.time()
            self._attempts.pop(key, None)
            return True

        n = self._attempts.get(key, 0) + 1
        self._attempts[key] = n
        if n >= self.MAX_CAPTURE_ATTEMPTS:
            self._processed[key] = time.time()      # stop retrying
            self._attempts.pop(key, None)
            # ERROR, not warning: this is a snapshot that will never exist.
            log.error("Snapshot PERMANENTLY MISSING for token %s (%s) — gave up after %d attempts",
                      label, key, n)
            return True
        # Throttled: with a 60-attempt budget an unthrottled warning would write
        # one line every poll for 5 minutes per failing event.
        log_throttled(f"retry_{key}",
                      "Capture failed for %s (attempt %d/%d) — will retry on next poll",
                      key, n, self.MAX_CAPTURE_ATTEMPTS, every=30.0)
        return False

    def start(self):
        self.running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        poll_sec = self.cfg.get("poll_interval_sec", 5)
        log.info("Event listener started (polling every %ds)", poll_sec)

    def stop(self):
        self.running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _poll_loop(self):
        import requests

        cloud_url = self.cfg["cloud_url"].rstrip("/")
        poll_url = f"{cloud_url}/api/v1/cameras/agent-pending"
        poll_sec = self.cfg.get("poll_interval_sec", 5)

        while self.running:
            try:
                resp = requests.get(poll_url, params={
                    "tenant_slug": self.cfg["tenant_slug"],
                    "agent_key": self.cfg["agent_key"],
                }, timeout=10)

                if resp.status_code == 200:
                    events = resp.json().get("events", [])
                    for evt in events:
                        # Per-event guard: ONE malformed event must not abort the
                        # rest of the batch. Previously a KeyError here skipped
                        # events 2..N and, because the bad event was never marked
                        # processed, it re-blocked the queue on every poll forever.
                        try:
                            key = f"{evt['token_id']}_{evt['weight_stage']}"
                        except (KeyError, TypeError):
                            log.error("Malformed event skipped (no token_id/weight_stage): %r", evt)
                            continue
                        if key in self._processed:
                            continue

                        log.info("Event: token=%s vehicle=%s stage=%s",
                                 evt.get("token_no", "?"), evt.get("vehicle_no", "?"),
                                 evt["weight_stage"])

                        # Local-first (Tunnel) mode when snapshot_serve_url is set;
                        # fall back to binary upload when it's not configured.
                        try:
                            if self.cfg.get("snapshot_serve_url"):
                                res = self.capturer.capture_local(evt["token_id"], evt["weight_stage"])
                            else:
                                res = self.capturer.capture_and_upload(evt["token_id"], evt["weight_stage"])
                        except Exception as e:  # noqa: BLE001
                            log.warning("Capture raised for %s: %s", key, e)
                            res = {}

                        if self._finish(key, res or {}, evt.get("token_no", "?")):
                            while len(self._processed) > 1000:
                                self._processed.popitem(last=False)

                elif resp.status_code != 404:
                    log.warning("Poll HTTP %d", resp.status_code)

            except requests.RequestException as e:
                log_throttled("poll", "Cloud unreachable (token snapshot poll): %s", e)
            except Exception as e:
                log.error("Poll error: %s", e)

            time.sleep(poll_sec)


# ── Gate Pass Listener ───────────────────────────────────────────────────────

class GatePassListener:
    """Polls cloud API for pending gate pass photo events and uploads captures.

    Works exactly like EventListener but targets the Gate Register endpoints:
      GET  /api/v1/gate/agent-pending   → returns gate passes needing entry/exit photos
      POST /api/v1/gate/agent-upload    → uploads captured JPEG

    Camera selection: uses gate_cameras.entry / gate_cameras.exit from config.
    If those URLs are empty, falls back to cameras.front (the token camera).
    """

    # Same reasoning as EventListener: /gate/agent-pending re-offers a pass with
    # no entry/exit photo for 5 minutes, so retry for that whole window.
    # This is the path a PHONE-ONLY gate guard depends on — the guard's phone just
    # creates the pass; this agent (on a plant PC) takes the actual photo.
    MAX_CAPTURE_ATTEMPTS = 60

    def __init__(self, config: dict, capturer: CameraCapturer):
        self.cfg = config
        self.capturer = capturer
        self.running = False
        self._thread = None
        # Dedup: "gate_pass_id_position" → timestamp
        self._processed: collections.OrderedDict[str, float] = collections.OrderedDict()
        # key -> failed attempts (only actively-failing keys; popped on done).
        self._attempts: dict[str, int] = {}

    def _finish(self, key: str, ok: bool, label: str) -> bool:
        """Mark a gate photo event done ONLY when the capture actually succeeded.

        Returns True when the event is finished with (succeeded, or given up on).
        """
        if ok:
            self._processed[key] = time.time()
            self._attempts.pop(key, None)
            return True

        n = self._attempts.get(key, 0) + 1
        self._attempts[key] = n
        if n >= self.MAX_CAPTURE_ATTEMPTS:
            self._processed[key] = time.time()      # stop retrying
            self._attempts.pop(key, None)
            log.error("Gate photo PERMANENTLY MISSING for gate pass %s (%s) — "
                      "gave up after %d attempts", label, key, n)
            return True
        log_throttled(f"gate_retry_{key}",
                      "Gate photo failed for %s (attempt %d/%d) — will retry on next poll",
                      key, n, self.MAX_CAPTURE_ATTEMPTS, every=30.0)
        return False

    def _resolve_gate_cam(self, position: str) -> dict:
        """Return the camera dict to use for this gate position.

        Priority:
          1. gate_cameras.<position>.url if non-empty
          2. cameras.front (fallback / default)
        """
        gate_cams = self.cfg.get("gate_cameras", {})
        cam = gate_cams.get(position, {})
        if cam.get("url"):
            return cam
        # Fallback to token front camera
        return self.cfg.get("cameras", {}).get("front", {})

    def _capture_and_upload(self, gate_pass_id: str, position: str) -> bool:
        """Capture one JPEG for the gate pass and upload to cloud. Returns True on success."""
        import requests

        cam = self._resolve_gate_cam(position)
        cam_url = cam.get("url", "")
        if not cam_url:
            log.warning("Gate camera URL not configured for position '%s' and no front camera fallback", position)
            return False

        log.info("Gate capture: gp=%s position=%s url=%s", gate_pass_id, position, cam_url)

        image_data = self.capturer._capture_single(cam_url, cam, f"gate_{position}")
        if image_data is None:
            log.warning("Gate snapshot capture failed for gp=%s position=%s", gate_pass_id, position)
            self.capturer.error_count += 1
            return False

        log.info("Gate captured %d bytes for gp=%s position=%s", len(image_data), gate_pass_id, position)

        upload_url = f"{self.cfg['cloud_url'].rstrip('/')}/api/v1/gate/agent-upload"
        try:
            files = {"file": (f"gate_{position}.jpg", image_data, "image/jpeg")}
            data = {
                "gate_pass_id": gate_pass_id,
                "position": position,
                "tenant_slug": self.cfg["tenant_slug"],
                "agent_key": self.cfg["agent_key"],
            }
            resp = requests.post(upload_url, files=files, data=data, timeout=30)
            if resp.status_code == 200:
                log.info("Gate photo uploaded: gp=%s position=%s", gate_pass_id, position)
                # Gate paths used to bypass these counters entirely, so /status
                # reported error_count=0 while every gate capture was failing.
                self.capturer.capture_count += 1
                return True
            else:
                log.warning("Gate upload failed: HTTP %d — %s", resp.status_code, resp.text[:200])
                self.capturer.error_count += 1
                return False
        except requests.RequestException as e:
            log.warning("Gate upload error: %s", e)
            self.capturer.error_count += 1
            return False

    def start(self):
        self.running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="GatePassListener")
        self._thread.start()
        poll_sec = self.cfg.get("poll_interval_sec", 5)
        log.info("Gate pass listener started (polling every %ds)", poll_sec)

    def stop(self):
        self.running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _poll_loop(self):
        import requests

        cloud_url = self.cfg["cloud_url"].rstrip("/")
        poll_url = f"{cloud_url}/api/v1/gate/agent-pending"
        poll_sec = self.cfg.get("poll_interval_sec", 5)

        while self.running:
            try:
                resp = requests.get(poll_url, params={
                    "tenant_slug": self.cfg["tenant_slug"],
                    "agent_key": self.cfg["agent_key"],
                }, timeout=10)

                if resp.status_code == 200:
                    events = resp.json().get("events", [])
                    for evt in events:
                        # Per-event guard — one malformed event must not abort the
                        # batch nor re-block the queue forever (see EventListener).
                        try:
                            key = f"{evt['gate_pass_id']}_{evt['position']}"
                        except (KeyError, TypeError):
                            log.error("Malformed gate event skipped (no gate_pass_id/position): %r", evt)
                            continue
                        if key in self._processed:
                            continue

                        log.info("Gate event: gp=%s vehicle=%s position=%s",
                                 evt.get("gate_pass_no", "?"), evt.get("vehicle_no", "?"),
                                 evt["position"])

                        try:
                            ok = self._capture_and_upload(evt["gate_pass_id"], evt["position"])
                        except Exception as e:  # noqa: BLE001
                            log.warning("Gate capture raised for %s: %s", key, e)
                            ok = False

                        if self._finish(key, bool(ok), evt.get("gate_pass_no", "?")):
                            # Trim cache to last 500 entries
                            while len(self._processed) > 500:
                                self._processed.popitem(last=False)

                elif resp.status_code not in (404, 403):
                    log.warning("Gate poll HTTP %d", resp.status_code)

            except requests.RequestException as e:
                log_throttled("gate_poll", "Cloud unreachable (gate photo poll): %s", e)
            except Exception as e:
                log.error("Gate poll error: %s", e)

            time.sleep(poll_sec)


# ── Gate Live Feed Pusher ────────────────────────────────────────────────────

class GateLiveFeedPusher:
    """Continuously pushes gate camera frames so GateCameraLivePage shows a live view.

    GateCameraLivePage polls GET /api/v1/gate/latest-snapshot/{position} every 3 s.
    This pusher populates that endpoint by POSTing JPEGs to
    POST /api/v1/gate/push-snapshot/{position} every PUSH_INTERVAL seconds.

    Camera source: gate_cameras.entry / gate_cameras.exit from camera_config.json.
    Falls back to cameras.front when a gate_cameras URL is empty.
    Auth: X-Agent-Key header = same agent_key already in camera_config.json.
    No separate gate agent key required.
    """

    PUSH_INTERVAL = 3  # seconds between frame pushes per camera

    def __init__(self, config: dict, capturer: "CameraCapturer"):
        self.cfg = config
        self.capturer = capturer
        self.running = False
        self._thread = None
        self._last_push: dict[str, float] = {"entry": 0.0, "exit": 0.0}

    def _resolve_gate_cam(self, position: str) -> dict:
        gate_cams = self.cfg.get("gate_cameras", {})
        cam = gate_cams.get(position, {})
        if cam.get("url"):
            return cam
        return self.cfg.get("cameras", {}).get("front", {})

    def _has_gate_cameras(self) -> bool:
        for pos in ("entry", "exit"):
            if self._resolve_gate_cam(pos).get("url"):
                return True
        return False

    def _push_one(self, position: str) -> bool:
        import requests

        cam = self._resolve_gate_cam(position)
        cam_url = cam.get("url", "")
        if not cam_url:
            return False

        # Fast single attempt — this loop runs every 3s per position; the 3x10s
        # retry path would let one dead camera stall the other position.
        image_data = self.capturer.capture_once(cam_url, cam)
        if image_data is None:
            log_throttled(f"live_cap_{position}",
                          "Gate live feed (%s): capture failed from %s", position, cam_url)
            return False

        push_url = f"{self.cfg['cloud_url'].rstrip('/')}/api/v1/gate/push-snapshot/{position}"
        try:
            resp = requests.post(
                push_url,
                headers={"X-Agent-Key": self.cfg["agent_key"]},
                files={"image": (f"{position}.jpg", image_data, "image/jpeg")},
                data={"tenant_slug": self.cfg.get("tenant_slug", "")},
                timeout=10,
            )
            if resp.status_code != 200:
                # Was silent: a wrong agent key / stale tenant slug returned 401/403
                # every 3s forever while the Gate Live page showed "Waiting for
                # agent..." and the agent log said nothing at all.
                log_throttled(f"push_{position}",
                              "Gate live feed push failed (%s): HTTP %d %s",
                              position, resp.status_code, (resp.text or "")[:120])
                return False
            return True
        except requests.RequestException as e:
            log_throttled(f"push_{position}", "Gate live feed push failed (%s): %s", position, e)
            return False

    def start(self):
        if not self._has_gate_cameras():
            log.info("Gate live feed: no gate camera URLs — skipping live push")
            return
        self.running = True
        self._thread = threading.Thread(target=self._push_loop, daemon=True, name="GateLiveFeedPusher")
        self._thread.start()
        for pos in ("entry", "exit"):
            cam = self._resolve_gate_cam(pos)
            if cam.get("url"):
                # Say so when this position has no dedicated gate camera and is
                # falling back to cameras.front — otherwise the gate live page
                # shows the WEIGHBRIDGE camera labelled "exit" and the log gives
                # no hint why.
                configured = (self.cfg.get("gate_cameras", {}).get(pos, {}).get("url") or "").strip()
                if configured:
                    log.info("Gate live feed (%s): %s", pos, cam["url"])
                else:
                    log.info("Gate live feed (%s): %s  [FALLBACK - no gate_cameras.%s.url "
                             "configured, using cameras.front]", pos, cam["url"], pos)
        log.info("Gate live feed pusher started (every %ds per camera)", self.PUSH_INTERVAL)

    def stop(self):
        self.running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _push_loop(self):
        while self.running:
            now = time.time()
            for position in ("entry", "exit"):
                if now - self._last_push[position] >= self.PUSH_INTERVAL:
                    self._push_one(position)
                    self._last_push[position] = time.time()
            time.sleep(0.5)


# ── Status API ───────────────────────────────────────────────────────────────

class StatusServer:
    """Serves status JSON + live camera snapshot proxy.

    Endpoints:
      GET /                     → agent status JSON
      GET /snapshot/front       → live JPEG from front camera
      GET /snapshot/top         → live JPEG from top camera

    BIND ADDRESS: 0.0.0.0, i.e. reachable from other machines on the plant LAN —
    deliberately, so the Camera & Scale page can be opened from an office PC as
    well as the weighbridge PC. (The docstring used to claim "localhost", which
    was simply wrong and hid the exposure.)

    Because it IS LAN-reachable, CORS echoes an ALLOWLISTED Origin only (derived
    from cloud_url + tenant_slug, see allowed_origins()). It used to send
    `Access-Control-Allow-Origin: *`, which let any website the operator happened
    to visit read live weighbridge frames straight off their machine.

    Note this is origin control, not authentication: a direct non-browser request
    from the LAN can still fetch a frame. Put the agent on a trusted plant LAN.
    """

    def __init__(self, capturer: CameraCapturer, port: int = 9003):
        self.capturer = capturer
        self.port = port

    def start(self):
        # ThreadingHTTPServer, not HTTPServer: a handler here can call
        # _capture_single, which retries 3x with a 10s timeout (up to ~60s when a
        # camera is dead). On the single-threaded HTTPServer that one request
        # blocks EVERY other connection — health checks and the other camera's
        # snapshot all hang until it finishes.
        from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
        capturer = self.capturer
        # StatusServer holds no config of its own — the capturer carries it.
        allow = allowed_origins(getattr(self.capturer, "cfg", {}) or {})
        log.info("Status CORS allowlist: %s", ", ".join(sorted(allow)) or "(none)")

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                # Echo an ALLOWLISTED Origin only. This was "*", which — because
                # the server binds 0.0.0.0 so other PCs on the plant LAN can view
                # the camera page — let any website the operator visited read live
                # weighbridge frames from their machine.
                cors_headers = {
                    "Access-Control-Allow-Methods": "GET",
                    "Cache-Control": "no-store, no-cache",
                    "Pragma": "no-cache",
                }
                _o = cors_origin_for(self.headers.get("Origin", ""), allow)
                if _o:
                    cors_headers["Access-Control-Allow-Origin"] = _o
                    cors_headers["Vary"] = "Origin"
                    cors_headers["Access-Control-Allow-Private-Network"] = "true"

                path = self.path.split("?")[0]  # strip query params

                # Live snapshot proxy
                if path in ("/snapshot/front", "/snapshot/top"):
                    camera_id = path.split("/")[-1]
                    image_data = capturer._capture_single_for_live(camera_id)
                    if image_data:
                        self.send_response(200)
                        self.send_header("Content-Type", "image/jpeg")
                        self.send_header("Content-Length", str(len(image_data)))
                        for k, v in cors_headers.items():
                            self.send_header(k, v)
                        self.end_headers()
                        self.wfile.write(image_data)
                    else:
                        self.send_response(502)
                        self.send_header("Content-Type", "text/plain")
                        for k, v in cors_headers.items():
                            self.send_header(k, v)
                        self.end_headers()
                        self.wfile.write(b"Camera unavailable")
                    return

                # Status JSON
                status_port = capturer.cfg.get('status_port', 9003)
                ws_port = capturer.cfg.get('_actual_ws_port', capturer.cfg.get('ws_port', 9004))
                body = json.dumps({
                    "service": "camera_agent",
                    "status": "running",
                    "timestamp": datetime.now().isoformat(),
                    "capture_count": capturer.capture_count,
                    "error_count": capturer.error_count,
                    "ws_port": ws_port,
                    "live_snapshot_urls": {
                        "front": f"http://localhost:{status_port}/snapshot/front",
                        "top": f"http://localhost:{status_port}/snapshot/top",
                    },
                })
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                for k, v in cors_headers.items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body.encode())

            def do_OPTIONS(self):
                """Handle CORS preflight (allowlisted origins only)."""
                self.send_response(204)
                _o = cors_origin_for(self.headers.get("Origin", ""), allow)
                if _o:
                    self.send_header("Access-Control-Allow-Origin", _o)
                    self.send_header("Vary", "Origin")
                    self.send_header("Access-Control-Allow-Private-Network", "true")
                self.send_header("Access-Control-Allow-Methods", "GET")
                self.send_header("Access-Control-Allow-Headers", "*")
                self.end_headers()

            def log_message(self, *args):
                pass

        def _serve():
            try:
                ThreadingHTTPServer(("0.0.0.0", self.port), Handler).serve_forever()
            except OSError as e:
                log.warning("Status server port %d: %s", self.port, e)

        threading.Thread(target=_serve, daemon=True).start()
        log.info("Status API: http://127.0.0.1:%d  (also reachable on the LAN at "
                 "this PC's IP:%d — CORS allowlisted)", self.port, self.port)


# ── Local Snapshot File Server ───────────────────────────────────────────────

class LocalSnapshotServer:
    """Serves locally-saved snapshot JPEGs over HTTP (port 9005 by default).

    The Cloudflare Tunnel exposes this port as the tenant's snapshot hostname
    (e.g. https://cam-acme.weighbridgesetu.com).  Browsers — on-site or
    outside the plant — load images directly from this server via the tunnel
    without any binary data touching the VPS.

    URL pattern:
      http://localhost:9005/{YYYYMMDD}/{token_id}/{camera}_{stage}_{HHmmss}.jpg

    Security:
      - Directory traversal blocked: all requests are resolved against
        save_dir; any path that escapes is rejected with 403.
      - Files are served read-only; no PUT/DELETE accepted.
      - CORS headers allow any origin (the cloud-hosted frontend loads images
        cross-origin; the Tunnel terminates TLS so only it sees this HTTP).
    """

    def __init__(self, save_dir: str, port: int = 9005):
        self.save_dir = Path(save_dir)
        self.port = port

    def start(self):
        # ThreadingHTTPServer, not HTTPServer: a handler here can call
        # _capture_single, which retries 3x with a 10s timeout (up to ~60s when a
        # camera is dead). On the single-threaded HTTPServer that one request
        # blocks EVERY other connection — health checks and the other camera's
        # snapshot all hang until it finishes.
        from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

        save_dir = self.save_dir
        port = self.port

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                url_path = self.path.split("?")[0].lstrip("/")

                # Prevent directory traversal
                try:
                    target = (save_dir / url_path).resolve()
                    target.relative_to(save_dir.resolve())
                except (ValueError, Exception):
                    self.send_response(403)
                    self.end_headers()
                    return

                # Health-check: GET / → 200 OK
                if url_path == "" or url_path == "/":
                    body = b"snapshot server ok"
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain")
                    self.send_header("Content-Length", str(len(body)))
                    self._cors()
                    self.end_headers()
                    self.wfile.write(body)
                    return

                if not target.is_file():
                    self.send_response(404)
                    self.end_headers()
                    return

                data = target.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "public, max-age=86400")
                self._cors()
                self.end_headers()
                self.wfile.write(data)

            def _cors(self):
                self.send_header("Access-Control-Allow-Origin", "*")

            def log_message(self, *args):
                pass  # suppress per-request noise; errors surface elsewhere

        def _serve():
            try:
                ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
            except OSError as e:
                log.warning("Snapshot file server port %d: %s", port, e)

        self.save_dir.mkdir(parents=True, exist_ok=True)
        threading.Thread(target=_serve, daemon=True).start()
        log.info("Snapshot file server: http://0.0.0.0:%d/ (save dir: %s)", port, self.save_dir)


# ── WebSocket Live Server ────────────────────────────────────────────────────

class WebSocketLiveServer:
    """Streams live camera frames over WebSocket.

    HTTPS pages can connect to ws://localhost (Chrome treats localhost
    as a secure context), so this bypasses mixed-content restrictions
    that block http:// image loads from https:// pages.

    Endpoint:
      ws://localhost:9004/live/front
      ws://localhost:9004/live/top

    Each connected client receives a JPEG frame (binary) every ~1.5s.
    A frame cache avoids hammering the camera when multiple clients
    connect simultaneously.
    """

    def __init__(self, capturer: CameraCapturer, port: int = 9004):
        self.capturer = capturer
        self.port = port
        # Frame cache: camera_id → (timestamp, jpeg_bytes)
        self._frame_cache: dict[str, tuple[float, bytes]] = {}
        self._cache_ttl = 1.0  # seconds

    def _get_frame(self, camera_id: str) -> bytes | None:
        """Return cached frame or capture a fresh one (blocking)."""
        now = time.time()
        cached = self._frame_cache.get(camera_id)
        if cached and (now - cached[0]) < self._cache_ttl:
            return cached[1]

        # Quick single-attempt capture for live view
        cam = self.capturer.cfg.get("cameras", {}).get(camera_id, {})
        cam_url = cam.get("url", "")
        if not cam_url:
            return cached[1] if cached else None

        try:
            import requests
            from requests.auth import HTTPDigestAuth, HTTPBasicAuth

            auth = None
            if cam.get("username"):
                auth = HTTPDigestAuth(cam["username"], cam.get("password", ""))

            resp = requests.get(cam_url, auth=auth, timeout=5, verify=False)

            # Fallback to Basic auth
            if resp.status_code == 401 and auth:
                auth = HTTPBasicAuth(cam["username"], cam.get("password", ""))
                resp = requests.get(cam_url, auth=auth, timeout=5, verify=False)

            if resp.status_code == 200 and len(resp.content) >= 500:
                self._frame_cache[camera_id] = (now, resp.content)
                return resp.content
        except Exception:
            pass

        # Return stale cache if available
        return cached[1] if cached else None

    def start(self):
        if not HAS_WEBSOCKETS:
            log.warning("websockets library not installed — live streaming disabled")
            log.info("Install with: pip install websockets>=13")
            return

        def _run():
            try:
                asyncio.run(self._serve())
            except Exception as e:
                log.error("WebSocket live server crashed: %s", e)

        threading.Thread(target=_run, daemon=True).start()
        log.info("WebSocket live server: ws://0.0.0.0:%d/live/{front|top}", self.port)

    async def _serve(self):
        async def handler(websocket):
            # Extract camera_id from path
            try:
                path = websocket.request.path
            except AttributeError:
                path = getattr(websocket, "path", "/live/front")

            parts = path.strip("/").split("/")
            camera_id = parts[-1] if parts else ""

            if camera_id not in ("front", "top"):
                await websocket.close(1008, "Invalid camera ID. Use /live/front or /live/top")
                return

            log.info("Live stream client connected: %s", camera_id)
            loop = asyncio.get_event_loop()
            consecutive_errors = 0

            try:
                while True:
                    # Capture frame in thread pool (blocking I/O)
                    frame = await loop.run_in_executor(
                        None, self._get_frame, camera_id
                    )
                    if frame:
                        await websocket.send(frame)
                        consecutive_errors = 0
                    else:
                        # Send a 1-byte marker so client knows we're alive
                        await websocket.send(b"\x00")
                        consecutive_errors += 1
                        if consecutive_errors > 20:
                            # Throttled: this used to log EVERY 1.5s, so a dead
                            # camera with a wall-board tab left open wrote ~40
                            # lines/minute into a log that never rotated.
                            log_throttled(f"live_{camera_id}",
                                          "Camera %s: %d consecutive live-frame failures",
                                          camera_id, consecutive_errors)

                    # Once the camera is clearly dead, back off instead of
                    # hammering it (and the log) every 1.5s.
                    await asyncio.sleep(1.5 if consecutive_errors <= 20 else 10)

            except websockets.ConnectionClosed:
                log.info("Live stream client disconnected: %s", camera_id)
            except Exception as e:
                log.warning("Live stream error for %s: %s", camera_id, e)

        # Try the configured port and up to 4 fallbacks in case it's busy
        # (e.g. the scale agent's StatusServer auto-incremented onto this port)
        start_port = self.port
        for candidate in range(start_port, start_port + 5):
            try:
                async with websockets.serve(handler, "0.0.0.0", candidate):
                    if candidate != start_port:
                        log.warning(
                            "WebSocket port %d was busy — using port %d instead",
                            start_port, candidate,
                        )
                    self.port = candidate
                    # Store the actual port so StatusServer can advertise it
                    self.capturer.cfg['_actual_ws_port'] = candidate
                    log.info("WebSocket live server ready on port %d", candidate)
                    await asyncio.Future()  # run forever
                break  # clean exit (never reached, but for clarity)
            except OSError as bind_err:
                in_use = bind_err.errno in (98, 10048) or \
                    'address already in use' in str(bind_err).lower() or \
                    'winerror 10048' in str(bind_err).lower()
                if in_use and candidate < start_port + 4:
                    log.warning("WebSocket port %d in use, trying %d", candidate, candidate + 1)
                    continue
                log.error("WebSocket server failed to start on port %d: %s", candidate, bind_err)
                break
            except Exception as e:
                log.error("WebSocket server failed to start on port %d: %s", candidate, e)
                break
        else:
            log.error(
                "WebSocket server: no free port found in range %d–%d",
                start_port, start_port + 4,
            )


# ── Windows Service Install ──────────────────────────────────────────────────

def install_service():
    import shutil
    import subprocess

    nssm = shutil.which("nssm")
    if not nssm:
        print("NSSM not found. Download from https://nssm.cc and add to PATH.")
        sys.exit(1)

    # A frozen .exe IS the program — register it directly (no python + script).
    frozen = getattr(sys, "frozen", False) or "__compiled__" in globals()
    if frozen:
        app_path = str(Path(sys.executable).resolve())   # the .exe itself
        app_params = ""
    else:
        app_path = sys.executable                         # python.exe
        app_params = str((BASE_DIR / "camera_agent.py").resolve())
    name = "WeighbridgeCameraAgent"

    # Check if service already exists; if so, stop it and update parameters
    status = subprocess.run([nssm, "status", name], capture_output=True, text=True)
    already_exists = status.returncode == 0 or "does not exist" not in status.stdout + status.stderr
    if already_exists:
        print(f"  Service '{name}' already exists — updating parameters...")
        subprocess.run([nssm, "stop", name], check=False)
    elif frozen:
        subprocess.run([nssm, "install", name, app_path], check=True)
    else:
        subprocess.run([nssm, "install", name, app_path, app_params], check=True)

    subprocess.run([nssm, "set", name, "Application", app_path], check=True)
    subprocess.run([nssm, "set", name, "AppParameters", app_params], check=True)
    subprocess.run([nssm, "set", name, "AppDirectory", str(BASE_DIR)], check=True)
    subprocess.run([nssm, "set", name, "AppStdout", str(LOG_DIR / "camera_service_stdout.log")], check=True)
    subprocess.run([nssm, "set", name, "AppStderr", str(LOG_DIR / "camera_service_stderr.log")], check=True)
    subprocess.run([nssm, "set", name, "AppRotateFiles", "1"], check=True)
    subprocess.run([nssm, "set", name, "AppRotateBytes", "10485760"], check=True)
    subprocess.run([nssm, "set", name, "Description", "Weighbridge Camera Agent - captures and uploads snapshots"], check=True)
    subprocess.run([nssm, "start", name], check=True)
    verb = "updated and restarted" if already_exists else "installed and started"
    print(f"\n  Service '{name}' {verb}.")
    print(f"  Check: nssm status {name}")
    print(f"  Logs:  {LOG_DIR}")


def uninstall_service():
    import shutil
    import subprocess
    nssm = shutil.which("nssm")
    if not nssm:
        print("NSSM not found.")
        sys.exit(1)
    name = "WeighbridgeCameraAgent"
    subprocess.run([nssm, "stop", name], check=False)
    subprocess.run([nssm, "remove", name, "confirm"], check=True)
    print(f"  Service '{name}' removed.")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    if "--setup" in sys.argv:
        setup_wizard()
        return
    if "--install" in sys.argv:
        install_service()
        return
    if "--uninstall" in sys.argv:
        uninstall_service()
        return
    if "--test" in sys.argv:
        # Camera commissioning happens on site, often before the tenant exists and
        # before any config file has been written. Allow the cameras to be given
        # straight on the command line so this binary is a usable camera tester
        # with NO config and NO tenant:
        #   camera_agent.exe --test --camera http://IP/cgi-bin/snapshot.cgi \
        #                    --user admin --pass secret
        # Repeat --camera for more than one. Falls back to camera_config.json.
        cli_cams = [sys.argv[i + 1] for i, a in enumerate(sys.argv)
                    if a == "--camera" and i + 1 < len(sys.argv)]
        if cli_cams:
            def _opt(flag: str) -> str:
                return next((sys.argv[i + 1] for i, a in enumerate(sys.argv)
                             if a == flag and i + 1 < len(sys.argv)), "")
            user, pw = _opt("--user"), _opt("--pass")
            cfg = {
                "cameras": {f"cam{n}": {"label": f"Camera {n}", "url": u,
                                        "username": user, "password": pw}
                            for n, u in enumerate(cli_cams, 1)},
                "gate_cameras": {},
            }
            print(f"\n  Testing {len(cli_cams)} camera(s) from the command line "
                  f"(no config / no tenant needed)...\n")
        else:
            cfg = load_config()
            print("\n  Testing camera snapshots...\n")
        capturer = CameraCapturer(cfg)
        results = capturer.test_cameras()
        # all({}) is True. Without this guard a config with NO camera URLs prints
        # "ALL OK" and the technician signs off an install that tested nothing.
        if not results:
            print("\n  Result: NO CAMERAS TESTED — no camera URLs are configured.")
            print("  Run 'camera_agent.exe --setup' to set the camera URLs.")
        else:
            ok = all(results.values())
            print(f"\n  Result: {'ALL OK' if ok else 'SOME FAILED'}")
        print(f"  Test images saved to: {BASE_DIR / 'test_snapshots'}")
        return

    cfg = load_config()

    if not cfg.get("tenant_slug") or not cfg.get("agent_key"):
        # Only RUNNING the agent needs cloud credentials (it has to authenticate to
        # upload). Camera commissioning does not — point that out rather than just
        # refusing, so a tech on site is not blocked waiting for tenant provisioning.
        log.error("tenant_slug and agent_key are required to RUN the agent "
                  "(they authenticate the upload to the cloud).")
        log.info("To configure them:      camera_agent.exe --setup")
        log.info("To test cameras WITHOUT a tenant, no config needed:")
        log.info("  camera_agent.exe --test --camera http://<ip>/cgi-bin/snapshot.cgi "
                 "--user <user> --pass <pass>")
        sys.exit(1)

    print()
    print("=" * 56)
    print("  Weighbridge Camera Agent")
    print(f"  Cloud:  {cfg['cloud_url']}")
    print(f"  Tenant: {cfg['tenant_slug']}")
    cams = cfg.get("cameras", {})
    for cid in ("front", "top"):
        if cid in cams and cams[cid].get("url"):
            print(f"  {cid.capitalize():6s}: {cams[cid]['url']}")
    gate_cams = cfg.get("gate_cameras", {})
    for gid in ("entry", "exit"):
        if gid in gate_cams and gate_cams[gid].get("url"):
            print(f"  Gate {gid.capitalize():5s}: {gate_cams[gid]['url']} (live feed)")
    if cfg.get("snapshot_serve_url"):
        _save_dir = cfg.get("local_save_dir", "D:\\weighbridge\\snapshots")
        _file_port = cfg.get("file_serve_port", 9005)
        print("  Mode:   Local-first (Cloudflare Tunnel)")
        print(f"  SaveTo: {_save_dir}")
        print(f"  Serve:  http://localhost:{_file_port}/")
        print(f"  Public: {cfg['snapshot_serve_url']}")
    else:
        print("  Mode:   Upload to VPS (legacy)")
    print("=" * 56)
    print()

    # Verify cloud
    try:
        import requests
        r = requests.get(f"{cfg['cloud_url'].rstrip('/')}/api/v1/health", timeout=10)
        log.info("Cloud: %s (status: %s)", cfg["cloud_url"], r.json().get("status"))
    except Exception as e:
        log.warning("Cloud unreachable: %s — will retry", e)

    # Test cameras once. NEVER fatal — this is a diagnostic self-test, and an
    # exception here (e.g. a mkdir PermissionError when installed under
    # Program Files with a restricted service account) would kill the process
    # BEFORE any listener starts, so NSSM would crash-loop the service forever.
    print("  Testing cameras...")
    capturer = CameraCapturer(cfg)
    try:
        capturer.test_cameras()
    except Exception as e:  # noqa: BLE001
        log.warning("Startup camera self-test failed (starting anyway): %s", e)
    print()

    # Prune old local snapshots + warn on low disk (now, then every 6h)
    start_maintenance_thread(cfg)

    # Start token snapshot listener
    listener = EventListener(cfg, capturer)
    listener.start()

    # Start gate pass photo listener (triggered capture on gate pass create/exit)
    gate_listener = GatePassListener(cfg, capturer)
    gate_listener.start()

    # Start gate live feed pusher (continuous frames → GateCameraLivePage)
    gate_live_pusher = GateLiveFeedPusher(cfg, capturer)
    gate_live_pusher.start()

    # Local snapshot file server (Cloudflare Tunnel mode only)
    if cfg.get("snapshot_serve_url"):
        LocalSnapshotServer(
            save_dir=cfg.get("local_save_dir", "D:\\weighbridge\\snapshots"),
            port=cfg.get("file_serve_port", 9005),
        ).start()

    # Status API (HTTP — for direct browser access & health checks)
    StatusServer(capturer, port=cfg.get("status_port", 9003)).start()

    # WebSocket live server (for HTTPS pages — bypasses mixed-content)
    ws_port = cfg.get("ws_port", 9004)
    WebSocketLiveServer(capturer, port=ws_port).start()

    log.info("Running. Press Ctrl+C to stop.")

    def _shutdown(sig, frame):
        log.info("Shutting down...")
        listener.stop()
        gate_listener.stop()
        gate_live_pusher.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _shutdown)

    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
