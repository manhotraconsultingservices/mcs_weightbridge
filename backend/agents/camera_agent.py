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

# ── Logging ──────────────────────────────────────────────────────────────────

LOG_DIR = Path(__file__).parent / "logs"
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

CONFIG_FILE = Path(__file__).parent / "camera_config.json"

DEFAULT_CONFIG = {
    "cloud_url": "https://weighbridgesetu.com",
    "tenant_slug": "",
    "agent_key": "",
    "poll_interval_sec": 5,
    "status_port": 9003,
    "ws_port": 9004,
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
}


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        log.error("Config not found: %s", CONFIG_FILE)
        log.info("Run: python camera_agent.py --setup")
        sys.exit(1)
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)


def save_config(cfg: dict):
    with open(CONFIG_FILE, "w") as f:
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
                body = json.dumps({
                    "service": "camera_agent",
                    "status": "running",
                    "timestamp": datetime.now().isoformat(),
                    "capture_count": capturer.capture_count,
                    "error_count": capturer.error_count,
                    "live_snapshot_urls": {
                        "front": f"http://localhost:{capturer.cfg.get('status_port', 9003)}/snapshot/front",
                        "top": f"http://localhost:{capturer.cfg.get('status_port', 9003)}/snapshot/top",
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

        try:
            async with websockets.serve(handler, "0.0.0.0", self.port):
                log.info("WebSocket live server ready on port %d", self.port)
                await asyncio.Future()  # run forever
        except Exception as e:
            log.error("WebSocket server failed to start on port %d: %s", self.port, e)


# ── Windows Service Install ──────────────────────────────────────────────────

def install_service():
    import shutil
    import subprocess

    nssm = shutil.which("nssm")
    if not nssm:
        print("NSSM not found. Download from https://nssm.cc and add to PATH.")
        sys.exit(1)

    python = sys.executable
    script = str(Path(__file__).resolve())
    name = "WeighbridgeCameraAgent"

    subprocess.run([nssm, "install", name, python, script], check=True)
    subprocess.run([nssm, "set", name, "AppDirectory", str(Path(__file__).parent)], check=True)
    subprocess.run([nssm, "set", name, "AppStdout", str(LOG_DIR / "camera_service_stdout.log")], check=True)
    subprocess.run([nssm, "set", name, "AppStderr", str(LOG_DIR / "camera_service_stderr.log")], check=True)
    subprocess.run([nssm, "set", name, "AppRotateFiles", "1"], check=True)
    subprocess.run([nssm, "set", name, "AppRotateBytes", "10485760"], check=True)
    subprocess.run([nssm, "set", name, "Description", "Weighbridge Camera Agent - captures and uploads snapshots"], check=True)
    subprocess.run([nssm, "start", name], check=True)
    print(f"\n  Service '{name}' installed and started.")
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
    print("=" * 50)
    print("  Weighbridge Camera Agent")
    print(f"  Cloud:  {cfg['cloud_url']}")
    print(f"  Tenant: {cfg['tenant_slug']}")
    cams = cfg.get("cameras", {})
    for cid in ("front", "top"):
        if cid in cams and cams[cid].get("url"):
            print(f"  {cid.capitalize():6s}: {cams[cid]['url']}")
    print("=" * 50)
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

    # Start event listener
    listener = EventListener(cfg, capturer)
    listener.start()

    # Status API (HTTP — for direct browser access & health checks)
    StatusServer(capturer, port=cfg.get("status_port", 9003)).start()

    # WebSocket live server (for HTTPS pages — bypasses mixed-content)
    ws_port = cfg.get("ws_port", 9004)
    WebSocketLiveServer(capturer, port=ws_port).start()

    log.info("Running. Press Ctrl+C to stop.")

    def _shutdown(sig, frame):
        log.info("Shutting down...")
        listener.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _shutdown)

    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
