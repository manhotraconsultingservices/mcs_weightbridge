#!/usr/bin/env python3
"""
Gate Camera Agent — CP Plus ONVIF snapshot push for cloud deployment.

Runs on the on-site Windows PC. Captures JPEG snapshots from local CP Plus
cameras using the ONVIF HTTP snapshot URL and pushes them to the cloud backend.

The cloud server cannot reach cameras on a private LAN (192.168.x.x), so this
agent bridges the gap: it runs where the cameras are reachable, then POSTs
snapshots to the cloud under X-Gate-Agent-Key authentication.

Requirements:
    pip install requests

Configuration:
    Copy gate_camera_agent.ini.template to gate_camera_agent.ini and edit it.
    Get the agent_key from Settings → Gate Cameras in the web app.

Usage:
    python gate_camera_agent.py

Auto-start (Windows):
    - Task Scheduler: run at logon, repeat every 1 min if it stops
    - Or install as a service with NSSM: nssm install GateCameraAgent python gate_camera_agent.py
"""

import configparser
import logging
import pathlib
import sys
import time

try:
    import requests
except ImportError:
    print("ERROR: 'requests' package not found. Run: pip install requests")
    sys.exit(1)

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("gate_camera_agent")

# ── Load config ───────────────────────────────────────────────────────────────

CFG_PATH = pathlib.Path(__file__).parent / "gate_camera_agent.ini"
if not CFG_PATH.exists():
    log.error("Config file not found: %s", CFG_PATH)
    log.error("Copy gate_camera_agent.ini.template → gate_camera_agent.ini and edit it.")
    sys.exit(1)

cfg = configparser.ConfigParser()
cfg.read(CFG_PATH, encoding="utf-8")

CLOUD_URL = cfg.get("server", "url", fallback="").rstrip("/")
AGENT_KEY = cfg.get("server", "agent_key", fallback="")
INTERVAL  = cfg.getint("server", "interval_seconds", fallback=3)
TIMEOUT   = cfg.getint("server", "timeout_seconds", fallback=5)

if not CLOUD_URL:
    log.error("[server] url is missing in config")
    sys.exit(1)
if not AGENT_KEY or AGENT_KEY == "PASTE_AGENT_KEY_HERE":
    log.error("[server] agent_key is missing. Copy the key from Settings → Gate Cameras.")
    sys.exit(1)

# ── Build camera list ─────────────────────────────────────────────────────────

CAMERAS: dict[str, dict] = {}
for pos in ("entry", "exit"):
    if cfg.has_section(pos) and cfg.getboolean(pos, "enabled", fallback=False):
        snap_url = cfg.get(pos, "snapshot_url", fallback="")
        if not snap_url:
            log.warning("[%s] enabled but snapshot_url is empty — skipping", pos)
            continue
        CAMERAS[pos] = {
            "snapshot_url": snap_url,
            "username": cfg.get(pos, "username", fallback=""),
            "password": cfg.get(pos, "password", fallback=""),
        }

if not CAMERAS:
    log.warning("No cameras enabled in config. Enable [entry] and/or [exit] sections.")

log.info("Gate Camera Agent starting")
log.info("  Cloud server : %s", CLOUD_URL)
log.info("  Cameras      : %s", list(CAMERAS.keys()) or "none")
log.info("  Interval     : %d s", INTERVAL)

# ── Session (reuse TCP connection) ────────────────────────────────────────────

push_session = requests.Session()
push_session.headers.update({"X-Gate-Agent-Key": AGENT_KEY})

# ── Main loop ─────────────────────────────────────────────────────────────────

def capture_and_push(position: str, cam: dict) -> None:
    """Fetch one JPEG from the local camera and POST it to the cloud."""
    try:
        # 1. Capture snapshot from local CP Plus camera (ONVIF URL)
        auth = (cam["username"], cam["password"]) if cam["username"] else None
        snap = requests.get(cam["snapshot_url"], auth=auth, timeout=TIMEOUT, stream=True)
        snap.raise_for_status()
        content_type = snap.headers.get("content-type", "")
        if "image" not in content_type:
            log.warning("%s: unexpected content-type '%s' from camera", position, content_type)
            return
        image_bytes = snap.content

        # 2. Push to cloud backend
        resp = push_session.post(
            f"{CLOUD_URL}/api/v1/gate/push-snapshot/{position}",
            files={"image": ("snapshot.jpg", image_bytes, "image/jpeg")},
            timeout=TIMEOUT + 5,
        )
        if resp.status_code == 403:
            log.error("%s: agent key rejected — regenerate key in Settings → Gate Cameras", position)
        elif not resp.ok:
            log.warning("%s: push failed %d — %s", position, resp.status_code, resp.text[:100])

    except requests.exceptions.ConnectTimeout:
        log.debug("%s: camera connection timeout", position)
    except requests.exceptions.ConnectionError as exc:
        log.debug("%s: connection error — %s", position, exc)
    except Exception as exc:
        log.warning("%s: unexpected error — %s", position, exc)


log.info("Starting push loop (Ctrl+C to stop)")
while True:
    for pos, cam in CAMERAS.items():
        capture_and_push(pos, cam)
    time.sleep(INTERVAL)
