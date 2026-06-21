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

    def _shutdown(sig, frame):
        log.info("Shutting down...")
        agent.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _shutdown)

    log.info("Running. Ctrl+C to stop.")
    agent.run()


if __name__ == "__main__":
    main()
