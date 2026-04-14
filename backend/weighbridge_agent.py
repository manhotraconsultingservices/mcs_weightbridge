"""
Weighbridge Client Agent — runs on the client PC at the weighbridge site.

Connects to:
  1. Weighbridge scale via serial/COM port → pushes readings to cloud API
  2. Local IP cameras → captures snapshots on demand and uploads to cloud

The agent authenticates with the cloud server using tenant_slug + agent_key.

Usage:
  python weighbridge_agent.py                    # interactive mode
  python weighbridge_agent.py --service           # run as Windows service (NSSM)
  python weighbridge_agent.py --setup             # generate config file

Config: agent_config.json (same directory)
"""

import copy
import json
import time
import sys
import re
import logging
import threading
import signal
import collections
from datetime import datetime
from pathlib import Path

# Suppress InsecureRequestWarning for local camera HTTPS with no cert
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── Logging ──────────────────────────────────────────────────────────────────

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "agent.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("weighbridge_agent")

# ── Config ───────────────────────────────────────────────────────────────────

CONFIG_FILE = Path(__file__).parent / "agent_config.json"

DEFAULT_CONFIG = {
    "cloud_url": "https://weighbridgesetu.com",
    "tenant_slug": "",
    "agent_key": "",

    "scale": {
        "enabled": True,
        "port": "COM3",
        "baud_rate": 9600,
        "data_bits": 8,
        "stop_bits": 1,
        "parity": "N",
        "push_interval_ms": 500,
    },

    "cameras": {
        "enabled": True,
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
        log.error("Config file not found: %s", CONFIG_FILE)
        log.info("Run: python weighbridge_agent.py --setup")
        sys.exit(1)
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)


def save_config(cfg: dict):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)
    log.info("Config saved to %s", CONFIG_FILE)


def setup_wizard():
    """Interactive setup to generate agent_config.json."""
    print("\n" + "=" * 60)
    print("  Weighbridge Agent — Setup Wizard")
    print("=" * 60 + "\n")

    cfg = copy.deepcopy(DEFAULT_CONFIG)  # deep copy to avoid mutating defaults

    cfg["cloud_url"] = input(f"Cloud URL [{cfg['cloud_url']}]: ").strip() or cfg["cloud_url"]
    cfg["tenant_slug"] = input("Tenant slug (e.g. ziya-ore-minerals): ").strip()
    cfg["agent_key"] = input("Agent API key (from platform admin): ").strip()

    print("\n--- Scale Configuration ---")
    cfg["scale"]["enabled"] = input("Enable scale? [Y/n]: ").strip().lower() != "n"
    if cfg["scale"]["enabled"]:
        # List available COM ports
        try:
            import serial.tools.list_ports
            ports = list(serial.tools.list_ports.comports())
            if ports:
                print("  Available COM ports:")
                for p in ports:
                    print(f"    {p.device} — {p.description}")
            else:
                print("  No COM ports found. Connect the USB-Serial cable first.")
        except ImportError:
            print("  (pyserial not installed — install with: pip install pyserial)")

        cfg["scale"]["port"] = input(f"COM port [{cfg['scale']['port']}]: ").strip() or cfg["scale"]["port"]
        baud = input(f"Baud rate [{cfg['scale']['baud_rate']}]: ").strip()
        if baud:
            cfg["scale"]["baud_rate"] = int(baud)

    print("\n--- Camera Configuration ---")
    cfg["cameras"]["enabled"] = input("Enable cameras? [Y/n]: ").strip().lower() != "n"
    if cfg["cameras"]["enabled"]:
        cfg["cameras"]["front"]["url"] = input(f"Front camera URL [{cfg['cameras']['front']['url']}]: ").strip() or cfg["cameras"]["front"]["url"]
        cfg["cameras"]["top"]["url"] = input(f"Top camera URL [{cfg['cameras']['top']['url']}]: ").strip() or cfg["cameras"]["top"]["url"]
        cam_user = input("Camera username (leave empty if none): ").strip()
        cam_pass = input("Camera password (leave empty if none): ").strip()
        for cam in ("front", "top"):
            cfg["cameras"][cam]["username"] = cam_user
            cfg["cameras"][cam]["password"] = cam_pass

    save_config(cfg)
    print(f"\n  Config saved to: {CONFIG_FILE}")
    print(f"  Start agent with: python weighbridge_agent.py")
    print()


# ── Scale Reader ─────────────────────────────────────────────────────────────

class ScaleReader:
    """Reads weight from serial port and pushes to cloud API."""

    def __init__(self, config: dict, cloud_url: str, tenant_slug: str, agent_key: str):
        self.cfg = config
        self.cloud_url = cloud_url
        self.tenant_slug = tenant_slug
        self.agent_key = agent_key
        self.running = False
        self.last_weight = 0.0
        self.connected = False
        self._thread = None

    def start(self):
        self.running = True
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        log.info("Scale reader started on %s @ %d baud",
                 self.cfg["port"], self.cfg["baud_rate"])

    def stop(self):
        self.running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _read_loop(self):
        import serial
        import requests

        port = self.cfg["port"]
        baud = self.cfg["baud_rate"]
        data_bits = self.cfg.get("data_bits", 8)
        stop_bits_val = self.cfg.get("stop_bits", 1)
        parity_map = {"N": serial.PARITY_NONE, "E": serial.PARITY_EVEN, "O": serial.PARITY_ODD}
        parity = parity_map.get(self.cfg.get("parity", "N"), serial.PARITY_NONE)

        # Map stop_bits to pyserial constants
        stopbits_map = {1: serial.STOPBITS_ONE, 1.5: serial.STOPBITS_ONE_POINT_FIVE, 2: serial.STOPBITS_TWO}
        stop_bits = stopbits_map.get(stop_bits_val, serial.STOPBITS_ONE)

        # Map data_bits to pyserial constants
        bytesize_map = {5: serial.FIVEBITS, 6: serial.SIXBITS, 7: serial.SEVENBITS, 8: serial.EIGHTBITS}
        byte_size = bytesize_map.get(data_bits, serial.EIGHTBITS)

        push_interval = self.cfg.get("push_interval_ms", 500) / 1000.0
        api_url = f"{self.cloud_url}/api/v1/weight/external-reading"

        reconnect_delay = 5
        buffer = b""

        while self.running:
            ser = None
            try:
                log.info("Connecting to scale on %s ...", port)
                ser = serial.Serial(
                    port=port,
                    baudrate=baud,
                    bytesize=byte_size,
                    stopbits=stop_bits,
                    parity=parity,
                    timeout=2,
                )
                self.connected = True
                log.info("Scale connected: %s", port)
                reconnect_delay = 5  # reset backoff

                while self.running:
                    chunk = ser.read(ser.in_waiting or 1)
                    if not chunk:
                        continue

                    buffer += chunk

                    # Try to extract weight from buffer (generic parser)
                    weight = self._parse_weight(buffer)
                    if weight is not None:
                        self.last_weight = weight
                        buffer = b""

                        # Push to cloud
                        try:
                            requests.post(api_url, json={
                                "weight_kg": weight,
                                "tenant": self.tenant_slug,
                                "agent_key": self.agent_key,
                                "raw": chunk.decode("ascii", errors="replace"),
                            }, timeout=5)
                        except requests.RequestException as e:
                            log.warning("Failed to push weight: %s", e)

                    # Trim buffer if too large
                    if len(buffer) > 4096:
                        buffer = buffer[-1024:]

                    time.sleep(push_interval)

            except Exception as e:
                self.connected = False
                log.warning("Scale error on %s: %s — reconnecting in %ds", port, e, reconnect_delay)
                time.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 60)
            finally:
                # Always close the serial port to release the handle
                if ser is not None:
                    try:
                        ser.close()
                    except Exception:
                        pass

    def _parse_weight(self, data: bytes) -> float | None:
        """
        Generic weight parser — extracts weight from common indicator formats.

        Common serial formats:
          Essae/Leo:   "ST,GS,+  12345 kg\\r\\n"
          Mettler:     "S S     12345.0 kg\\r\\n"
          Generic:     "   12345\\r\\n"
          CAS:         "ST,GS,  012345 kg"

        Strategy: find the largest number in the frame (likely the weight).
        Ignores numbers < 10 (likely status codes) and timestamps.
        """
        try:
            text = data.decode("ascii", errors="replace")
            # Match numbers that look like weight values (3+ digits, optional decimal)
            matches = re.findall(r"[+-]?\s*(\d{3,6}(?:\.\d{1,3})?)", text)
            if matches:
                # Take the largest number (most likely the weight, not a status code)
                weights = [float(m.replace(" ", "")) for m in matches]
                weight = max(weights)
                if 0 < weight < 200000:  # reasonable range for a truck (kg)
                    return weight
        except Exception:
            pass
        return None


# ── Camera Capturer ──────────────────────────────────────────────────────────

class CameraCapturer:
    """Captures snapshots from local IP cameras and uploads to cloud."""

    def __init__(self, config: dict, cloud_url: str, tenant_slug: str, agent_key: str):
        self.cfg = config
        self.cloud_url = cloud_url
        self.tenant_slug = tenant_slug
        self.agent_key = agent_key

    def capture_and_upload(self, token_id: str, weight_stage: str = "second_weight") -> dict:
        """Capture snapshots from all enabled cameras and upload to cloud."""
        import requests

        results = {}
        upload_url = f"{self.cloud_url}/api/v1/cameras/agent-upload"

        for camera_id in ("front", "top"):
            cam_cfg = self.cfg.get(camera_id, {})
            cam_url = cam_cfg.get("url", "")
            if not cam_url:
                continue

            log.info("Capturing %s camera: %s", camera_id, cam_url)

            # Capture snapshot from local camera
            try:
                auth = None
                if cam_cfg.get("username"):
                    auth = (cam_cfg["username"], cam_cfg.get("password", ""))

                resp = requests.get(cam_url, auth=auth, timeout=10, verify=False)
                if resp.status_code != 200:
                    log.warning("Camera %s returned %d", camera_id, resp.status_code)
                    results[camera_id] = {"success": False, "error": f"HTTP {resp.status_code}"}
                    continue

                image_data = resp.content
                if len(image_data) < 100:
                    log.warning("Camera %s returned too small image (%d bytes)", camera_id, len(image_data))
                    results[camera_id] = {"success": False, "error": "Image too small"}
                    continue

            except requests.RequestException as e:
                log.warning("Camera %s capture failed: %s", camera_id, e)
                results[camera_id] = {"success": False, "error": str(e)}
                continue

            # Upload to cloud
            try:
                files = {"file": (f"{camera_id}_{weight_stage}.jpg", image_data, "image/jpeg")}
                data = {
                    "token_id": token_id,
                    "camera_id": camera_id,
                    "weight_stage": weight_stage,
                    "tenant_slug": self.tenant_slug,
                    "agent_key": self.agent_key,
                }
                resp = requests.post(upload_url, files=files, data=data, timeout=30)
                if resp.status_code == 200:
                    result = resp.json()
                    log.info("Uploaded %s snapshot for token %s: %s",
                             camera_id, token_id, result.get("url"))
                    results[camera_id] = {"success": True, "url": result.get("url")}
                else:
                    log.warning("Upload failed for %s: %d %s",
                                camera_id, resp.status_code, resp.text[:200])
                    results[camera_id] = {"success": False, "error": f"Upload HTTP {resp.status_code}"}

            except requests.RequestException as e:
                log.warning("Upload failed for %s: %s", camera_id, e)
                results[camera_id] = {"success": False, "error": str(e)}

        return results


# ── Token Event Listener ─────────────────────────────────────────────────────

class TokenEventListener:
    """Polls the cloud API for token events that need camera snapshots."""

    def __init__(self, cloud_url: str, tenant_slug: str, agent_key: str, camera: CameraCapturer):
        self.cloud_url = cloud_url
        self.tenant_slug = tenant_slug
        self.agent_key = agent_key
        self.camera = camera
        self.running = False
        self._thread = None
        # OrderedDict preserves insertion order — prune oldest entries first
        self._processed_events: collections.OrderedDict[str, float] = collections.OrderedDict()

    def start(self):
        self.running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        log.info("Token event listener started (polling every 5s)")

    def stop(self):
        self.running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _poll_loop(self):
        import requests

        poll_url = f"{self.cloud_url}/api/v1/cameras/agent-pending"

        while self.running:
            try:
                resp = requests.get(poll_url, params={
                    "tenant_slug": self.tenant_slug,
                    "agent_key": self.agent_key,
                }, timeout=10)

                if resp.status_code == 200:
                    events = resp.json().get("events", [])
                    for evt in events:
                        event_key = f"{evt['token_id']}_{evt['weight_stage']}"
                        if event_key in self._processed_events:
                            continue

                        log.info("Camera event: token=%s stage=%s",
                                 evt["token_id"], evt["weight_stage"])

                        self.camera.capture_and_upload(
                            evt["token_id"], evt["weight_stage"]
                        )
                        self._processed_events[event_key] = time.time()

                        # Prune oldest entries when set grows too large
                        while len(self._processed_events) > 1000:
                            self._processed_events.popitem(last=False)

                elif resp.status_code != 404:
                    log.warning("Poll returned %d", resp.status_code)

            except requests.RequestException:
                pass  # network blip, retry next cycle
            except Exception as e:
                log.error("Poll error: %s", e)

            time.sleep(5)


# ── Agent Status API (local web server for health checks) ────────────────────

class AgentStatusServer:
    """Simple HTTP server on localhost for agent health checks."""

    def __init__(self, scale: ScaleReader | None, port: int = 9002):
        self.scale = scale
        self.port = port
        self._thread = None

    def start(self):
        from http.server import HTTPServer, BaseHTTPRequestHandler

        scale = self.scale

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                status = {
                    "agent": "running",
                    "timestamp": datetime.now().isoformat(),
                    "scale_connected": scale.connected if scale else False,
                    "last_weight_kg": scale.last_weight if scale else 0,
                }
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(status).encode())

            def log_message(self, format, *args):
                pass  # suppress access logs

        def _serve():
            try:
                server = HTTPServer(("127.0.0.1", self.port), Handler)
                server.serve_forever()
            except OSError as e:
                log.warning("Status server failed to start on port %d: %s", self.port, e)

        self._thread = threading.Thread(target=_serve, daemon=True)
        self._thread.start()
        log.info("Agent status API running on http://127.0.0.1:%d", self.port)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    if "--setup" in sys.argv:
        setup_wizard()
        return

    cfg = load_config()

    if not cfg.get("tenant_slug") or not cfg.get("agent_key"):
        log.error("tenant_slug and agent_key must be set in agent_config.json")
        log.info("Run: python weighbridge_agent.py --setup")
        sys.exit(1)

    cloud_url = cfg["cloud_url"].rstrip("/")
    tenant_slug = cfg["tenant_slug"]
    agent_key = cfg["agent_key"]

    print()
    print("=" * 60)
    print("  Weighbridge Agent")
    print(f"  Cloud:  {cloud_url}")
    print(f"  Tenant: {tenant_slug}")
    print("=" * 60)
    print()

    # Verify cloud connectivity
    try:
        import requests
        r = requests.get(f"{cloud_url}/api/v1/health", timeout=10)
        health = r.json()
        log.info("Cloud server: %s (status: %s)", cloud_url, health.get("status"))
    except Exception as e:
        log.warning("Cannot reach cloud server: %s — will retry in background", e)

    # Start scale reader
    scale = None
    if cfg.get("scale", {}).get("enabled"):
        scale = ScaleReader(cfg["scale"], cloud_url, tenant_slug, agent_key)
        scale.start()

    # Start camera capturer + event listener
    camera = None
    event_listener = None
    if cfg.get("cameras", {}).get("enabled"):
        camera = CameraCapturer(cfg["cameras"], cloud_url, tenant_slug, agent_key)
        event_listener = TokenEventListener(cloud_url, tenant_slug, agent_key, camera)
        event_listener.start()

    # Start local status API
    status_server = AgentStatusServer(scale, port=9002)
    status_server.start()

    # Keep running
    log.info("Agent is running. Press Ctrl+C to stop.")

    def _shutdown(sig, frame):
        log.info("Shutting down...")
        if scale:
            scale.stop()
        if event_listener:
            event_listener.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    # SIGTERM is not available on Windows — only register if supported
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _shutdown)

    # Keep main thread alive
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
