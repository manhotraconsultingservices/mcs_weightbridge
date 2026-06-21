"""
Gate Camera Agent — live snapshot push for cloud deployment.

Runs on the on-site Windows PC. Captures JPEG snapshots from local gate
cameras (CP Plus ONVIF, Hikvision, Dahua) every few seconds and POSTs them
to the cloud backend so the live-view page always has a recent frame.

The cloud server cannot reach cameras on a private LAN (192.168.x.x), so
this agent bridges the gap — it runs where the cameras are reachable.

Requirements:
    pip install requests

Usage:
    python gate_camera_agent.py               # run interactively
    python gate_camera_agent.py --setup       # guided config generator
    python gate_camera_agent.py --install     # install as Windows service (NSSM)
    python gate_camera_agent.py --uninstall   # remove Windows service
    python gate_camera_agent.py --test        # test camera connectivity

Config: gate_camera_config.json  (same directory as this script)
Get the agent_key from Settings → Gate Cameras in the web app.
"""

import json
import logging
import signal
import sys
import time
import threading
from datetime import datetime
from pathlib import Path

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    import requests
    from requests.auth import HTTPBasicAuth, HTTPDigestAuth
except ImportError:
    print("ERROR: 'requests' package not found. Run: pip install requests")
    sys.exit(1)

# ── Logging ───────────────────────────────────────────────────────────────────

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "gate_camera_agent.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("gate_camera_agent")

# ── Config ────────────────────────────────────────────────────────────────────

CONFIG_FILE = Path(__file__).parent / "gate_camera_config.json"

DEFAULT_CONFIG: dict = {
    "cloud_url": "https://weighbridgesetu.com",
    "tenant_slug": "",
    "agent_key": "",
    "interval_sec": 3,
    "timeout_sec": 8,
    "cameras": {
        "entry": {
            "enabled": True,
            "label": "Gate Entry Camera",
            "url": "http://192.168.1.64/onvif-http/snapshot?Profile_1",
            "username": "admin",
            "password": "",
        },
        "exit": {
            "enabled": False,
            "label": "Gate Exit Camera",
            "url": "",
            "username": "admin",
            "password": "",
        },
    },
}


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        log.error("Config file not found: %s", CONFIG_FILE)
        log.info("Run: python gate_camera_agent.py --setup")
        sys.exit(1)
    # utf-8-sig strips optional BOM written by Windows PowerShell 5.1
    with open(CONFIG_FILE, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def save_config(cfg: dict) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    log.info("Config saved → %s", CONFIG_FILE)


# ── Setup wizard ──────────────────────────────────────────────────────────────

def setup_wizard() -> None:
    import copy

    print("\n" + "=" * 60)
    print("  Weighbridge Gate Camera Agent — Setup")
    print("=" * 60 + "\n")

    cfg = copy.deepcopy(DEFAULT_CONFIG)

    cfg["cloud_url"] = input(f"Cloud URL [{cfg['cloud_url']}]: ").strip() or cfg["cloud_url"]
    cfg["tenant_slug"] = input("Tenant slug (e.g. ziya-ore-minerals, blank = single-tenant): ").strip()
    cfg["agent_key"] = input("Agent key (from Settings → Gate Cameras in the web app): ").strip()

    print("\n--- Common snapshot URL formats ---")
    print("  CP Plus / Dahua ONVIF:  http://<IP>/onvif-http/snapshot?Profile_1")
    print("  Hikvision:              http://<IP>/Streaming/channels/1/picture")
    print("  Generic snapshot:       http://<IP>/cgi-bin/snapshot.cgi")
    print()

    entry_url = input(f"Entry camera URL [{cfg['cameras']['entry']['url']}]: ").strip()
    if entry_url:
        cfg["cameras"]["entry"]["url"] = entry_url
    cfg["cameras"]["entry"]["enabled"] = bool(cfg["cameras"]["entry"]["url"])

    if cfg["cameras"]["entry"]["enabled"]:
        u = input(f"  Entry camera username [{cfg['cameras']['entry']['username']}]: ").strip()
        if u:
            cfg["cameras"]["entry"]["username"] = u
        cfg["cameras"]["entry"]["password"] = input("  Entry camera password: ").strip()

    exit_url = input("\nExit camera URL (leave blank to skip): ").strip()
    if exit_url:
        cfg["cameras"]["exit"]["url"] = exit_url
        cfg["cameras"]["exit"]["enabled"] = True
        u = input(f"  Exit camera username [{cfg['cameras']['exit']['username']}]: ").strip()
        if u:
            cfg["cameras"]["exit"]["username"] = u
        cfg["cameras"]["exit"]["password"] = input("  Exit camera password: ").strip()

    interval = input(f"\nPush interval in seconds [{cfg['interval_sec']}]: ").strip()
    if interval.isdigit() and int(interval) > 0:
        cfg["interval_sec"] = int(interval)

    save_config(cfg)
    print(f"\n  Config written: {CONFIG_FILE}")
    print(f"  Test cameras:   python gate_camera_agent.py --test")
    print(f"  Run now:        python gate_camera_agent.py")
    print(f"  Install as svc: python gate_camera_agent.py --install\n")


# ── Camera capture ────────────────────────────────────────────────────────────

def capture_snapshot(cam: dict, label: str, timeout: int) -> bytes | None:
    """Fetch one JPEG from a camera. Tries Digest auth first, falls back to Basic."""
    url = cam.get("url", "")
    if not url:
        return None

    auth = None
    if cam.get("username"):
        auth = HTTPDigestAuth(cam["username"], cam.get("password", ""))

    for attempt in range(1, 4):
        try:
            resp = requests.get(url, auth=auth, timeout=timeout, verify=False)

            if resp.status_code == 401 and auth:
                auth = HTTPBasicAuth(cam["username"], cam.get("password", ""))
                resp = requests.get(url, auth=auth, timeout=timeout, verify=False)

            ct = resp.headers.get("content-type", "")
            if resp.status_code == 200 and ("image" in ct or len(resp.content) > 500):
                return resp.content

            log.debug("%s attempt %d: HTTP %d (%d bytes)", label, attempt, resp.status_code, len(resp.content))

        except Exception as exc:
            log.debug("%s attempt %d failed: %s", label, attempt, exc)

        if attempt < 3:
            time.sleep(1)

    return None


# ── Push agent ────────────────────────────────────────────────────────────────

class GateCameraAgent:
    """Continuously captures snapshots and POSTs them to the cloud."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.running = False
        self._session = requests.Session()
        self._session.headers["X-Gate-Agent-Key"] = cfg["agent_key"]
        self.push_count = 0
        self.error_count = 0
        self._last_push: dict[str, float] = {}

    def _push_one(self, position: str, cam: dict) -> None:
        timeout = self.cfg.get("timeout_sec", 8)
        image_data = capture_snapshot(cam, position, timeout)
        if image_data is None:
            self.error_count += 1
            return

        cloud = self.cfg["cloud_url"].rstrip("/")
        # Include tenant_slug as query param for multi-tenant deployments
        params = {}
        if self.cfg.get("tenant_slug"):
            params["tenant_slug"] = self.cfg["tenant_slug"]

        try:
            resp = self._session.post(
                f"{cloud}/api/v1/gate/push-snapshot/{position}",
                files={"image": (f"{position}.jpg", image_data, "image/jpeg")},
                params=params,
                timeout=timeout + 5,
            )
            if resp.status_code == 200:
                self.push_count += 1
                self._last_push[position] = time.time()
                log.debug("%s: pushed %d bytes (total %d)", position, len(image_data), self.push_count)
            elif resp.status_code == 403:
                log.error(
                    "%s: agent key rejected — regenerate in Settings → Gate Cameras and update gate_camera_config.json",
                    position,
                )
            else:
                log.warning("%s: push HTTP %d — %s", position, resp.status_code, resp.text[:120])
                self.error_count += 1
        except requests.RequestException as exc:
            log.debug("%s: push error — %s", position, exc)
            self.error_count += 1

    def run(self) -> None:
        self.running = True
        interval = self.cfg.get("interval_sec", 3)
        cameras = {
            pos: cam
            for pos, cam in self.cfg.get("cameras", {}).items()
            if cam.get("enabled") and cam.get("url")
        }

        if not cameras:
            log.warning("No cameras enabled in config. Edit gate_camera_config.json and restart.")
            return

        log.info("Pushing %s every %ds", list(cameras), interval)

        while self.running:
            for position, cam in cameras.items():
                self._push_one(position, cam)
            time.sleep(interval)

    def stop(self) -> None:
        self.running = False


# ── Minimal status HTTP server ────────────────────────────────────────────────

class StatusServer:
    """Serves a JSON status blob on localhost:9005 for health checks."""

    def __init__(self, agent: GateCameraAgent, port: int = 9005):
        self.agent = agent
        self.port = port

    def start(self) -> None:
        from http.server import HTTPServer, BaseHTTPRequestHandler
        agent = self.agent

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps({
                    "service": "gate_camera_agent",
                    "status": "running" if agent.running else "stopped",
                    "timestamp": datetime.now().isoformat(),
                    "push_count": agent.push_count,
                    "error_count": agent.error_count,
                    "last_push": agent._last_push,
                })
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body.encode())

            def log_message(self, *_):
                pass  # suppress per-request console noise

        def _serve():
            try:
                HTTPServer(("0.0.0.0", self.port), Handler).serve_forever()
            except OSError as e:
                log.warning("Status server port %d unavailable: %s", self.port, e)

        threading.Thread(target=_serve, daemon=True, name="StatusServer").start()
        log.info("Status API: http://127.0.0.1:%d", self.port)


# ── Gate pass photo listener ─────────────────────────────────────────────────

class GatePassListener:
    """Polls cloud API for gate passes needing entry/exit photos and uploads captures.

    When a gate pass is created or exited, the backend marks it as needing a photo
    (entry_photo_path / exit_photo_path IS NULL). This listener polls every 5 s,
    captures a fresh JPEG from the correct camera, and uploads it.

    GET  /api/v1/gate/agent-pending  → list of {gate_pass_id, position} needing photos
    POST /api/v1/gate/agent-upload   → multipart upload that sets the photo column

    In single-tenant mode the server skips auth. In multi-tenant mode pass
    tenant_slug + agent_key from the config.
    """

    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg
        self.running = False
        self._thread: threading.Thread | None = None
        self._seen: set[str] = set()   # gate_pass_id:position pairs already handled

    def start(self) -> None:
        self.running = True
        self._thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="GatePassListener"
        )
        self._thread.start()
        log.info("Gate pass listener started (polls every 5 s for pending photos)")

    def stop(self) -> None:
        self.running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _poll_loop(self) -> None:
        cloud = self.cfg["cloud_url"].rstrip("/")
        poll_url = f"{cloud}/api/v1/gate/agent-pending"
        upload_url = f"{cloud}/api/v1/gate/agent-upload"
        timeout_sec = self.cfg.get("timeout_sec", 8)
        tenant_slug = self.cfg.get("tenant_slug", "")
        agent_key = self.cfg.get("agent_key", "")

        while self.running:
            try:
                resp = requests.get(
                    poll_url,
                    params={"tenant_slug": tenant_slug},
                    headers={"X-Gate-Agent-Key": agent_key},
                    timeout=10,
                )
                if resp.status_code == 200:
                    for evt in resp.json().get("events", []):
                        gp_id = evt.get("gate_pass_id")
                        position = evt.get("position")   # "entry" or "exit"
                        if not gp_id or position not in ("entry", "exit"):
                            continue
                        key = f"{gp_id}:{position}"
                        if key in self._seen:
                            continue
                        self._seen.add(key)
                        self._capture_and_upload(
                            gp_id, position, upload_url,
                            agent_key, tenant_slug, timeout_sec,
                        )
                elif resp.status_code not in (403, 404):
                    log.debug("agent-pending HTTP %d", resp.status_code)
            except Exception as exc:
                log.debug("Gate pass poll error: %s", exc)
            time.sleep(5)

    def _capture_and_upload(
        self,
        gate_pass_id: str,
        position: str,
        upload_url: str,
        agent_key: str,
        tenant_slug: str,
        timeout_sec: int,
    ) -> None:
        cam = self.cfg.get("cameras", {}).get(position, {})
        if not cam.get("enabled") or not cam.get("url"):
            log.debug("No %s camera configured — skipping gate pass %s photo", position, gate_pass_id)
            return

        image_data = capture_snapshot(cam, f"gate_{position}", timeout_sec)
        if image_data is None:
            log.warning("Snapshot failed for gate pass %s position=%s", gate_pass_id, position)
            return

        try:
            resp = requests.post(
                upload_url,
                data={
                    "gate_pass_id": gate_pass_id,
                    "position": position,
                    "tenant_slug": tenant_slug,
                },
                headers={"X-Gate-Agent-Key": agent_key},
                files={"file": (f"gate_{position}.jpg", image_data, "image/jpeg")},
                timeout=timeout_sec + 5,
            )
            if resp.status_code == 200:
                log.info(
                    "Gate photo linked: gp=%s pos=%s (%d bytes)",
                    gate_pass_id, position, len(image_data),
                )
            else:
                log.warning("Gate upload HTTP %d: %s", resp.status_code, resp.text[:120])
        except Exception as exc:
            log.warning("Gate upload error gp=%s: %s", gate_pass_id, exc)


# ── Token photo listener (polls cameras/agent-pending) ───────────────────────


class TokenPhotoListener:
    """Polls cloud API for tokens needing camera photos and uploads them.

    Handles issue 1: token images not captured.
    Uses the same cameras as the gate agent (entry=front, exit=top).
    Auth via X-Gate-Agent-Key header — same key as gate agent.
    """

    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg
        self.running = False
        self._thread: threading.Thread | None = None
        self._seen: set[str] = set()

    def start(self) -> None:
        self.running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="TokenPhotoListener")
        self._thread.start()
        log.info("Token photo listener started (polls /cameras/agent-pending every 5 s)")

    def stop(self) -> None:
        self.running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _poll_loop(self) -> None:
        cloud = self.cfg["cloud_url"].rstrip("/")
        poll_url = f"{cloud}/api/v1/cameras/agent-pending"
        upload_url = f"{cloud}/api/v1/cameras/agent-upload"
        timeout_sec = self.cfg.get("timeout_sec", 8)
        tenant_slug = self.cfg.get("tenant_slug", "")
        agent_key = self.cfg.get("agent_key", "")

        cameras_cfg = self.cfg.get("cameras", {})
        # Map gate camera positions to token camera IDs:
        # entry camera captures the "front" view, exit camera captures the "top" view.
        cam_map: dict[str, dict] = {}
        entry = cameras_cfg.get("entry")
        ex = cameras_cfg.get("exit")
        if entry and entry.get("enabled") and entry.get("url"):
            cam_map["front"] = entry
        if ex and ex.get("enabled") and ex.get("url"):
            cam_map["top"] = ex

        if not cam_map:
            log.info("Token photo listener: no cameras configured — skipping")
            return

        while self.running:
            try:
                resp = requests.get(
                    poll_url,
                    params={"tenant_slug": tenant_slug},
                    headers={"X-Gate-Agent-Key": agent_key},
                    timeout=10,
                )
                if resp.status_code == 200:
                    for evt in resp.json().get("events", []):
                        token_id = evt.get("token_id")
                        weight_stage = evt.get("weight_stage", "second_weight")
                        if not token_id:
                            continue
                        key = f"{token_id}:{weight_stage}"
                        if key in self._seen:
                            continue
                        self._seen.add(key)
                        for camera_id, cam in cam_map.items():
                            self._capture_and_upload(
                                token_id, camera_id, weight_stage,
                                cam, upload_url, agent_key, tenant_slug, timeout_sec,
                            )
                elif resp.status_code == 403:
                    log.warning("Token poll: 403 Forbidden — check agent_key in config")
                elif resp.status_code not in (404,):
                    log.debug("token agent-pending HTTP %d", resp.status_code)
            except Exception as exc:
                log.debug("Token photo poll error: %s", exc)
            time.sleep(5)

    def _capture_and_upload(
        self,
        token_id: str,
        camera_id: str,
        weight_stage: str,
        cam: dict,
        upload_url: str,
        agent_key: str,
        tenant_slug: str,
        timeout_sec: int,
    ) -> None:
        image_data = capture_snapshot(cam, f"token_{camera_id}", timeout_sec)
        if image_data is None:
            log.warning("Token snapshot failed: token=%s cam=%s", token_id, camera_id)
            return
        try:
            resp = requests.post(
                upload_url,
                data={
                    "token_id": token_id,
                    "camera_id": camera_id,
                    "weight_stage": weight_stage,
                    "tenant_slug": tenant_slug,
                },
                headers={"X-Gate-Agent-Key": agent_key},
                files={"file": (f"{camera_id}_{weight_stage}.jpg", image_data, "image/jpeg")},
                timeout=timeout_sec + 5,
            )
            if resp.status_code == 200:
                log.info(
                    "Token photo uploaded: token=%s cam=%s stage=%s (%d bytes)",
                    token_id, camera_id, weight_stage, len(image_data),
                )
            else:
                log.warning("Token upload HTTP %d: %s", resp.status_code, resp.text[:120])
        except Exception as exc:
            log.warning("Token upload error token=%s cam=%s: %s", token_id, camera_id, exc)


# ── NSSM service management ───────────────────────────────────────────────────

SERVICE_NAME = "WeighbridgeGateCameraAgent"


def _find_nssm() -> str:
    import shutil
    nssm = shutil.which("nssm")
    if nssm:
        return nssm
    # Common install location from install-scale-service.ps1
    candidate = Path("C:/nssm/nssm.exe")
    if candidate.exists():
        return str(candidate)
    print("NSSM not found.")
    print("  Option 1: Run install-scale-service.ps1 first — it downloads NSSM automatically.")
    print("  Option 2: Download from https://nssm.cc, unzip nssm.exe to C:\\nssm\\")
    sys.exit(1)


def install_service() -> None:
    import subprocess

    nssm = _find_nssm()
    python = sys.executable
    script = str(Path(__file__).resolve())
    log_dir = str(LOG_DIR)

    print(f"\n  Installing '{SERVICE_NAME}' via NSSM...")

    # Idempotent — remove any previous instance first
    subprocess.run([nssm, "stop",   SERVICE_NAME, "confirm"], check=False, capture_output=True)
    subprocess.run([nssm, "remove", SERVICE_NAME, "confirm"], check=False, capture_output=True)

    subprocess.run([nssm, "install",    SERVICE_NAME, python, script], check=True)
    subprocess.run([nssm, "set", SERVICE_NAME, "AppDirectory",   str(Path(__file__).parent)], check=True)
    subprocess.run([nssm, "set", SERVICE_NAME, "DisplayName",    "Weighbridge Gate Camera Agent"], check=True)
    subprocess.run([nssm, "set", SERVICE_NAME, "Description",    "Pushes live gate camera snapshots to the cloud backend."], check=True)
    subprocess.run([nssm, "set", SERVICE_NAME, "Start",          "SERVICE_AUTO_START"], check=True)
    subprocess.run([nssm, "set", SERVICE_NAME, "ObjectName",     "LocalSystem"], check=True)
    subprocess.run([nssm, "set", SERVICE_NAME, "AppExit",        "Default", "Restart"], check=True)
    subprocess.run([nssm, "set", SERVICE_NAME, "AppRestartDelay","2000"], check=True)
    subprocess.run([nssm, "set", SERVICE_NAME, "AppStdout",      str(LOG_DIR / "service_stdout.log")], check=True)
    subprocess.run([nssm, "set", SERVICE_NAME, "AppStderr",      str(LOG_DIR / "service_stderr.log")], check=True)
    subprocess.run([nssm, "set", SERVICE_NAME, "AppRotateFiles", "1"], check=True)
    subprocess.run([nssm, "set", SERVICE_NAME, "AppRotateOnline","1"], check=True)
    subprocess.run([nssm, "set", SERVICE_NAME, "AppRotateBytes", "10485760"], check=True)

    subprocess.run([nssm, "start", SERVICE_NAME], check=True)

    print(f"\n  Service '{SERVICE_NAME}' installed and started.")
    print(f"  Logs:    {log_dir}")
    print(f"  Status:  Invoke-RestMethod http://localhost:9005")
    print(f"  Check:   Get-Service {SERVICE_NAME}")
    print(f"  Restart: Restart-Service {SERVICE_NAME}")
    print(f"  Remove:  python gate_camera_agent.py --uninstall\n")


def uninstall_service() -> None:
    import subprocess

    nssm = _find_nssm()
    subprocess.run([nssm, "stop",   SERVICE_NAME, "confirm"], check=False)
    subprocess.run([nssm, "remove", SERVICE_NAME, "confirm"], check=True)
    print(f"  Service '{SERVICE_NAME}' removed.")


# ── Test mode ─────────────────────────────────────────────────────────────────

def test_cameras(cfg: dict) -> None:
    print("\n  Testing gate cameras...\n")
    test_dir = Path(__file__).parent / "test_snapshots"
    test_dir.mkdir(exist_ok=True)

    cameras = cfg.get("cameras", {})
    any_ok = False

    for position, cam in cameras.items():
        url = cam.get("url", "")
        enabled = cam.get("enabled", False)
        if not url:
            print(f"  {position:8s}: SKIPPED (no URL configured)")
            continue
        if not enabled:
            print(f"  {position:8s}: SKIPPED (enabled: false)")
            continue

        print(f"  {position:8s}: {url} ...", end=" ", flush=True)
        data = capture_snapshot(cam, position, cfg.get("timeout_sec", 8))
        if data:
            path = test_dir / f"test_{position}.jpg"
            path.write_bytes(data)
            print(f"OK  ({len(data):,} bytes) → {path}")
            any_ok = True
        else:
            print("FAILED")

    print()
    if any_ok:
        print(f"  Check test_snapshots/ to confirm the images look correct.")
        print(f"  Then run: python gate_camera_agent.py --install")
    else:
        print("  No cameras responded. Common fixes:")
        print("    1. Ping the camera IP from this PC: ping 192.168.x.x")
        print("    2. Open the URL in a browser to verify it returns an image")
        print("    3. Check username / password in gate_camera_config.json")
        print("    4. CP Plus ONVIF URL: http://<IP>/onvif-http/snapshot?Profile_1")
    print()


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    if "--setup" in sys.argv:
        setup_wizard()
        return
    if "--install" in sys.argv:
        cfg = load_config()   # must exist before install
        install_service()
        return
    if "--uninstall" in sys.argv:
        uninstall_service()
        return

    cfg = load_config()

    if "--test" in sys.argv:
        test_cameras(cfg)
        return

    if not cfg.get("agent_key"):
        log.error("agent_key is empty in gate_camera_config.json")
        log.info("Get the key from Settings → Gate Cameras and run --setup (or edit the JSON)")
        sys.exit(1)

    cloud = cfg["cloud_url"]
    cameras = {p: c for p, c in cfg.get("cameras", {}).items() if c.get("enabled") and c.get("url")}

    print()
    print("=" * 58)
    print("  Weighbridge Gate Camera Agent")
    print(f"  Cloud:    {cloud}")
    for pos, cam in cameras.items():
        print(f"  {pos.capitalize():8s}: {cam['url']}")
    print(f"  Interval: {cfg.get('interval_sec', 3)} s")
    print(f"  Status:   http://127.0.0.1:9005")
    print("=" * 58)
    print()

    # Quick cloud connectivity check
    try:
        r = requests.get(f"{cloud.rstrip('/')}/api/v1/health", timeout=10)
        log.info("Cloud health: %s", r.json().get("status", "ok"))
    except Exception as exc:
        log.warning("Cloud unreachable at startup: %s — will keep retrying", exc)

    agent = GateCameraAgent(cfg)
    StatusServer(agent, port=9005).start()

    # Listen for pending gate pass photo events and upload captures
    gate_listener = GatePassListener(cfg)
    gate_listener.start()

    # Listen for pending token photo events (same cameras, entry=front, exit=top)
    token_listener = TokenPhotoListener(cfg)
    token_listener.start()

    def _shutdown(sig, frame):
        log.info("Shutting down...")
        agent.stop()
        gate_listener.stop()
        token_listener.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _shutdown)

    log.info("Running. Ctrl+C to stop.")
    agent.run()


if __name__ == "__main__":
    main()
