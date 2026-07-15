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
import threading
import signal
import asyncio
from datetime import datetime
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "camera_agent.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("camera_agent")

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

    cfg["cloud_url"] = input(f"Cloud URL [{cfg['cloud_url']}]: ").strip() or cfg["cloud_url"]
    cfg["tenant_slug"] = input("Tenant slug (e.g. ziya-ore-minerals): ").strip()
    cfg["agent_key"] = input("Agent API key (from platform admin): ").strip()

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
        test_dir = Path(__file__).parent / "test_snapshots"
        test_dir.mkdir(exist_ok=True)

        for camera_id in ("front", "top"):
            cam = self.cfg.get("cameras", {}).get(camera_id, {})
            cam_url = cam.get("url", "")
            if not cam_url:
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

    def __init__(self, config: dict, capturer: CameraCapturer):
        self.cfg = config
        self.capturer = capturer
        self.running = False
        self._thread = None
        self._processed: collections.OrderedDict[str, float] = collections.OrderedDict()

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
                        key = f"{evt['token_id']}_{evt['weight_stage']}"
                        if key in self._processed:
                            continue

                        log.info("Event: token=%s vehicle=%s stage=%s",
                                 evt.get("token_no", "?"), evt.get("vehicle_no", "?"),
                                 evt["weight_stage"])

                        # Local-first (Tunnel) mode when snapshot_serve_url is set;
                        # fall back to binary upload when it's not configured.
                        if self.cfg.get("snapshot_serve_url"):
                            self.capturer.capture_local(evt["token_id"], evt["weight_stage"])
                        else:
                            self.capturer.capture_and_upload(evt["token_id"], evt["weight_stage"])
                        self._processed[key] = time.time()

                        while len(self._processed) > 1000:
                            self._processed.popitem(last=False)

                elif resp.status_code != 404:
                    log.warning("Poll HTTP %d", resp.status_code)

            except requests.RequestException:
                pass
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

    def __init__(self, config: dict, capturer: CameraCapturer):
        self.cfg = config
        self.capturer = capturer
        self.running = False
        self._thread = None
        # Dedup: "gate_pass_id_position" → timestamp
        self._processed: collections.OrderedDict[str, float] = collections.OrderedDict()

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
                return True
            else:
                log.warning("Gate upload failed: HTTP %d — %s", resp.status_code, resp.text[:200])
                return False
        except requests.RequestException as e:
            log.warning("Gate upload error: %s", e)
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
                        key = f"{evt['gate_pass_id']}_{evt['position']}"
                        if key in self._processed:
                            continue

                        log.info("Gate event: gp=%s vehicle=%s position=%s",
                                 evt.get("gate_pass_no", "?"), evt.get("vehicle_no", "?"),
                                 evt["position"])

                        self._capture_and_upload(evt["gate_pass_id"], evt["position"])
                        self._processed[key] = time.time()

                        # Trim cache to last 500 entries
                        while len(self._processed) > 500:
                            self._processed.popitem(last=False)

                elif resp.status_code not in (404, 403):
                    log.warning("Gate poll HTTP %d", resp.status_code)

            except requests.RequestException:
                pass
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

        image_data = self.capturer._capture_single(cam_url, cam, f"gate_live_{position}")
        if image_data is None:
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
            return resp.status_code == 200
        except requests.RequestException:
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
                log.info("Gate live feed (%s): %s", pos, cam["url"])
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
    """Serves status JSON + live camera snapshot proxy on localhost.

    Endpoints:
      GET /                     → agent status JSON
      GET /snapshot/front       → live JPEG from front camera
      GET /snapshot/top         → live JPEG from top camera

    The snapshot proxy allows the browser to load camera images via
    http://localhost:9003/snapshot/front — no mixed-content issues.
    CORS headers allow any origin (the cloud-hosted frontend).
    """

    def __init__(self, capturer: CameraCapturer, port: int = 9003):
        self.capturer = capturer
        self.port = port

    def start(self):
        from http.server import HTTPServer, BaseHTTPRequestHandler
        capturer = self.capturer

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                # CORS headers for cross-origin access from cloud frontend
                cors_headers = {
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET",
                    "Cache-Control": "no-store, no-cache",
                    "Pragma": "no-cache",
                }

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
                """Handle CORS preflight."""
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET")
                self.send_header("Access-Control-Allow-Headers", "*")
                self.end_headers()

            def log_message(self, *args):
                pass

        def _serve():
            try:
                HTTPServer(("0.0.0.0", self.port), Handler).serve_forever()
            except OSError as e:
                log.warning("Status server port %d: %s", self.port, e)

        threading.Thread(target=_serve, daemon=True).start()
        log.info("Status API: http://127.0.0.1:%d", self.port)


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
        from http.server import HTTPServer, BaseHTTPRequestHandler

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
                HTTPServer(("0.0.0.0", port), Handler).serve_forever()
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
                            log.warning("Camera %s: too many consecutive failures", camera_id)

                    await asyncio.sleep(1.5)

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
        cfg = load_config()
        print("\n  Testing camera snapshots...\n")
        capturer = CameraCapturer(cfg)
        results = capturer.test_cameras()
        ok = all(results.values())
        print(f"\n  Result: {'ALL OK' if ok else 'SOME FAILED'}")
        print(f"  Test images saved to: {Path(__file__).parent / 'test_snapshots'}")
        return

    cfg = load_config()

    if not cfg.get("tenant_slug") or not cfg.get("agent_key"):
        log.error("tenant_slug and agent_key required in camera_config.json")
        log.info("Run: python camera_agent.py --setup")
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

    # Test cameras once
    print("  Testing cameras...")
    capturer = CameraCapturer(cfg)
    capturer.test_cameras()
    print()

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
