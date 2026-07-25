"""Weighbridge Watchdog Agent — device-health heartbeat for scale + cameras.

A tiny standalone service that runs on each plant PC. Its ONLY job is to probe
the local devices (the weighing scale via the scale agent's /status, and each IP
camera by fetching a snapshot) and push a per-device health heartbeat to the
cloud. The cloud stores it, shows a Device Health dashboard, and — via a
background loop — fires a Telegram alert to the owner when any device stays down
past a threshold that the owner sets in Settings.

It DOES NOT touch, restart, or reconfigure the scale/camera agents. It only reads
their public /status and pings the cameras — completely non-invasive.

Typical topology (per the two-PC layout):
  • PC1 (weighbridge): scale agent + camera agent  → one watchdog probing the
    scale + the front/top cameras.
  • PC2 (gate):        camera agent (entry/exit)    → one watchdog probing the
    two gate cameras.
Install ONE watchdog per PC, each with its own watchdog_agent.json listing that
PC's devices.

Usage:
    python watchdog_agent.py --setup       # write a starter config
    python watchdog_agent.py --test        # probe every device + cloud once
    python watchdog_agent.py               # run the heartbeat loop (foreground)
    python watchdog_agent.py --install     # install as a Windows service (NSSM)
    python watchdog_agent.py --uninstall

The alert threshold ("down for more than N minutes") is set ON THE SERVER
(Settings → Device Health), NOT here — the agent just reports ok/down every
`push_interval_sec`. Cloud creds (cloud_url + tenant_slug + agent_key) are the
SAME ones already in this PC's scale_config.json / camera_config.json.
"""
import os
import sys
import json
import copy
import time
import socket
import logging
import threading
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse

try:
    import requests
    from requests.auth import HTTPDigestAuth, HTTPBasicAuth
except ImportError:
    print("Missing dependency. Run:  pip install requests")
    sys.exit(1)

AGENT_VERSION = "1.0.0"

# ── Base dir (frozen-EXE safe: read config next to the .exe, not _MEIPASS) ────
if getattr(sys, "frozen", False) or "__compiled__" in globals():
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent

# TLS CA bundle insurance for a frozen build (only set when unset, so a real
# system/corporate CA still wins).
try:
    import certifi as _certifi
    _ca = _certifi.where()
    if _ca and os.path.exists(_ca):
        os.environ.setdefault("SSL_CERT_FILE", _ca)
        os.environ.setdefault("REQUESTS_CA_BUNDLE", _ca)
except Exception:
    pass

CONFIG_FILE = BASE_DIR / "watchdog_agent.json"
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "watchdog_agent.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("watchdog")

PRODUCT_DOMAIN = "weighbridgesetu.com"

DEFAULT_CONFIG: dict = {
    "cloud_url": f"https://{PRODUCT_DOMAIN}",
    "tenant_slug": "",
    "agent_key": "",
    # Free-text label for THIS PC — shown in the dashboard so the owner knows
    # which machine a device sits on.
    "site": "PC1 Weighbridge",
    "push_interval_sec": 30,     # how often to probe + push a heartbeat
    "probe_timeout_sec": 6,      # per-device network timeout
    "status_port": 9020,         # local diagnostics UI (≠ scale 9002 / camera 9003 / tally 9010)
    # Devices to watch. `key` must be stable + unique per tenant (prefix with the
    # PC so PC1's and PC2's devices never collide). Types:
    #   scale  — GET `status_url` (the scale agent's /status); ok when reachable
    #            AND the JSON field `status_field` (default scale_connected) is true.
    #   camera — GET `url` (a snapshot URL, e.g. http://IP/cgi-bin/snapshot.cgi);
    #            ok on HTTP 200 with a non-empty image. Digest→Basic auth fallback.
    #   agent  — GET `status_url`; ok when it responds 200 (liveness of an agent
    #            process, e.g. the camera agent on :9003).
    "devices": [
        {
            "key": "pc1:scale", "type": "scale", "label": "Weighing Scale",
            "status_url": "http://127.0.0.1:9002/status",
            "status_field": "scale_connected",
        },
        {
            "key": "pc1:cam:front", "type": "camera", "label": "Front Camera",
            "url": "http://192.168.0.101/cgi-bin/snapshot.cgi",
            "username": "admin", "password": "",
        },
        {
            "key": "pc1:cam:top", "type": "camera", "label": "Top Camera",
            "url": "http://192.168.0.103/cgi-bin/snapshot.cgi",
            "username": "admin", "password": "",
        },
    ],
}

# Candidate ports the scale agent may bind (it auto-increments off 9002 when
# Tally holds 9002). A `scale` device with no explicit status_url is probed
# across these on 127.0.0.1.
_SCALE_STATUS_PORTS = [9002, 9003, 9004, 9005, 9006]


# ── Config ────────────────────────────────────────────────────────────────────
def load_config() -> dict:
    if not CONFIG_FILE.exists():
        log.error("Config not found: %s\nRun: python watchdog_agent.py --setup", CONFIG_FILE)
        sys.exit(1)
    with open(CONFIG_FILE, "r", encoding="utf-8-sig") as fh:  # utf-8-sig strips PS BOM
        data = json.load(fh)
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg.update(data)
    return cfg


def save_config(cfg: dict) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
    log.info("Config saved -> %s", CONFIG_FILE)


def _effective_push_base(cloud_url: str, tenant_slug: str) -> str:
    """Cloud base URL. The apex weighbridgesetu.com 301-redirects to www, and a
    301 turns a POST into a GET that DROPS the body — so route to the tenant's own
    subdomain (no redirect). Custom domains / localhost are left untouched.
    (Same fix as scale_agent.py / tally_connector.py.)"""
    base = (cloud_url or "").rstrip("/")
    try:
        parts = urlparse(base if "//" in base else f"https://{base}")
        host = (parts.hostname or "").lower()
    except Exception:
        return base
    if tenant_slug and host in (PRODUCT_DOMAIN, f"www.{PRODUCT_DOMAIN}"):
        return f"{parts.scheme or 'https'}://{tenant_slug}.{PRODUCT_DOMAIN}"
    return base


def _cloud_base(cfg: dict) -> str:
    return _effective_push_base(cfg.get("cloud_url", ""), cfg.get("tenant_slug", ""))


# ── Device probing ──────────────────────────────────────────────────────────────
def _probe_scale(dev: dict, timeout: float) -> tuple[bool, str | None]:
    """Reachable scale agent + scale physically connected → ok."""
    field = dev.get("status_field") or "scale_connected"
    urls = [dev["status_url"]] if dev.get("status_url") else [
        f"http://127.0.0.1:{p}/status" for p in _SCALE_STATUS_PORTS
    ]
    last_err = "scale agent unreachable"
    for url in urls:
        try:
            r = requests.get(url, timeout=timeout)
            if r.status_code != 200:
                last_err = f"scale agent HTTP {r.status_code}"
                continue
            data = r.json()
            if bool(data.get(field)):
                return True, None
            # Agent is up but reports the scale disconnected — the useful signal.
            return False, "scale not connected (serial port down)"
        except Exception as e:  # noqa: BLE001
            last_err = f"scale agent unreachable ({type(e).__name__})"
            continue
    return False, last_err


def _probe_camera(dev: dict, timeout: float) -> tuple[bool, str | None]:
    """Fetch one snapshot from the camera. HTTP 200 + a real image body → ok.
    Tries Digest auth first (CP Plus / Dahua / Hikvision), falls back to Basic."""
    url = dev.get("url")
    if not url:
        return False, "no camera url configured"
    auth = None
    if dev.get("username"):
        auth = HTTPDigestAuth(dev["username"], dev.get("password", ""))
    try:
        r = requests.get(url, auth=auth, timeout=timeout, verify=False)
        if r.status_code == 401 and auth:
            auth = HTTPBasicAuth(dev["username"], dev.get("password", ""))
            r = requests.get(url, auth=auth, timeout=timeout, verify=False)
        if r.status_code == 200 and len(r.content) >= 500:
            return True, None
        if r.status_code == 200:
            return False, f"snapshot too small ({len(r.content)} bytes)"
        return False, f"camera HTTP {r.status_code}"
    except Exception as e:  # noqa: BLE001
        return False, f"camera unreachable ({type(e).__name__})"


def _probe_agent(dev: dict, timeout: float) -> tuple[bool, str | None]:
    """Liveness of an agent process — its /status answers 200 → ok."""
    url = dev.get("status_url")
    if not url:
        return False, "no status_url configured"
    try:
        r = requests.get(url, timeout=timeout)
        if r.status_code == 200:
            field = dev.get("status_field")
            if field:
                try:
                    if not bool(r.json().get(field)):
                        return False, f"{field} is false"
                except Exception:
                    pass
            return True, None
        return False, f"agent HTTP {r.status_code}"
    except Exception as e:  # noqa: BLE001
        return False, f"agent unreachable ({type(e).__name__})"


_PROBES = {"scale": _probe_scale, "camera": _probe_camera, "agent": _probe_agent}


def probe_all(cfg: dict) -> list[dict]:
    """Probe every configured device, return the heartbeat device list."""
    timeout = float(cfg.get("probe_timeout_sec", 6))
    out: list[dict] = []
    for dev in cfg.get("devices", []):
        key = str(dev.get("key") or "").strip()
        if not key:
            continue
        dtype = (str(dev.get("type") or "camera").strip().lower())
        probe = _PROBES.get(dtype, _probe_camera)
        try:
            ok, err = probe(dev, timeout)
        except Exception as e:  # noqa: BLE001 — a probe crash must not sink the heartbeat
            ok, err = False, f"probe error ({type(e).__name__})"
        out.append({
            "key": key,
            "type": "scale" if dtype == "scale" else ("agent" if dtype == "agent" else "camera"),
            "label": str(dev.get("label") or key),
            "ok": ok,
            "error": err,
        })
    return out


# ── Cloud push ──────────────────────────────────────────────────────────────────
def push_heartbeat(cfg: dict, session: "requests.Session", devices: list[dict]) -> bool:
    base = _cloud_base(cfg)
    payload = {
        "tenant": cfg.get("tenant_slug"),
        "agent_key": cfg.get("agent_key"),
        "site": cfg.get("site"),
        "devices": devices,
    }
    try:
        r = session.post(f"{base}/api/v1/monitor/heartbeat", json=payload,
                         timeout=float(cfg.get("probe_timeout_sec", 6)) + 4)
        if r.status_code == 200:
            return True
        if r.status_code == 403:
            log.error("AGENT KEY REJECTED (403) — check tenant_slug + agent_key (re-run --setup)")
        else:
            log.warning("heartbeat HTTP %s: %s", r.status_code, r.text[:200])
    except Exception as e:  # noqa: BLE001
        log.warning("heartbeat push failed: %s", e)
    return False


# ── State + status server ───────────────────────────────────────────────────────
class State:
    def __init__(self) -> None:
        self.cloud_online = False
        self.last_push_at: str | None = None
        self.devices: list[dict] = []
        self.pushes = 0
        self.errors = 0


_STATUS_HTML = """<!doctype html><meta charset=utf-8><title>Watchdog</title>
<style>body{font-family:system-ui;background:#0f172a;color:#e2e8f0;margin:0;padding:24px}
h1{font-size:18px}.d{display:flex;justify-content:space-between;padding:8px 12px;border-radius:8px;
background:#1e293b;margin:6px 0}.ok{color:#34d399}.bad{color:#f87171}small{color:#94a3b8}</style>
<h1>Weighbridge Watchdog <small id=v></small></h1><div id=c></div><div id=r></div>
<script>async function p(){try{const s=await(await fetch('/status')).json();
document.getElementById('v').textContent='v'+s.agent_version;
document.getElementById('c').innerHTML='<div class=d><span>Cloud</span><span class='+
(s.cloud_online?'ok':'bad')+'>'+(s.cloud_online?'ONLINE':'OFFLINE')+'</span></div>'+
'<div class=d><span>Last push</span><span><small>'+(s.last_push_at||'—')+'</small></span></div>';
document.getElementById('r').innerHTML=(s.devices||[]).map(d=>'<div class=d><span>'+d.label+
' <small>'+d.type+'</small></span><span class='+(d.ok?'ok':'bad')+'>'+(d.ok?'OK':'DOWN')+
(d.error?' <small>'+d.error+'</small>':'')+'</span></div>').join('');
}catch(e){}}setInterval(p,3000);p();</script>"""


def start_status_server(cfg: dict, state: State) -> None:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    def _free_port(start: int) -> int:
        for p in range(start, start + 5):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.bind(("127.0.0.1", p)); s.close()
                return p
            except OSError:
                continue
        return start

    port = _free_port(int(cfg.get("status_port", 9020)))

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._send(200, _STATUS_HTML, "text/html; charset=utf-8")
            elif self.path == "/status":
                self._send(200, json.dumps({
                    "service": "watchdog_agent", "agent_version": AGENT_VERSION,
                    "cloud_online": state.cloud_online, "last_push_at": state.last_push_at,
                    "pushes": state.pushes, "errors": state.errors, "devices": state.devices,
                }), "application/json")
            else:
                self._send(404, "{}", "application/json")

        def log_message(self, *a):
            pass

    def _serve():
        try:
            ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
        except OSError as exc:
            log.warning("Status server on :%d failed: %s", port, exc)

    threading.Thread(target=_serve, daemon=True, name="status-http").start()
    log.info("Status UI: http://127.0.0.1:%d", port)


# ── Run loop ──────────────────────────────────────────────────────────────────
def run(cfg: dict, state: State) -> None:
    interval = max(10, int(cfg.get("push_interval_sec", 30)))
    session = requests.Session()
    log.info("Watchdog v%s — %d device(s), every %ds -> %s",
             AGENT_VERSION, len(cfg.get("devices", [])), interval, _cloud_base(cfg))
    while True:
        try:
            devices = probe_all(cfg)
            state.devices = devices
            down = [d["label"] for d in devices if not d["ok"]]
            if down:
                log.info("DOWN: %s", ", ".join(down))
            ok = push_heartbeat(cfg, session, devices)
            state.cloud_online = ok
            if ok:
                state.pushes += 1
                state.last_push_at = datetime.now().isoformat(timespec="seconds")
            else:
                state.errors += 1
        except Exception as e:  # noqa: BLE001 — the loop must never die
            log.warning("cycle error: %s", e)
            state.errors += 1
        time.sleep(interval)


# ── Setup / test / service ──────────────────────────────────────────────────────
def setup_wizard() -> None:
    print("\n" + "=" * 60)
    print("  Weighbridge Watchdog Agent — Setup")
    print("=" * 60 + "\n")
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        try:
            cfg.update(json.load(open(CONFIG_FILE, "r", encoding="utf-8-sig")))
        except Exception:
            pass
    cfg["cloud_url"]   = input(f"Cloud URL [{cfg['cloud_url']}]: ").strip() or cfg["cloud_url"]
    cfg["tenant_slug"] = input(f"Tenant slug [{cfg.get('tenant_slug','')}]: ").strip() or cfg.get("tenant_slug", "")
    cfg["agent_key"]   = input("Agent API key (same as scale/camera agent): ").strip() or cfg.get("agent_key", "")
    cfg["site"]        = input(f"This PC's label [{cfg['site']}]: ").strip() or cfg["site"]
    print("\nEdit watchdog_agent.json to list this PC's devices (scale + cameras).")
    print("The starter config has example entries — set the real camera URLs +")
    print("credentials, and remove any device this PC does not have.\n")
    save_config(cfg)
    print(f"  Config saved: {CONFIG_FILE}")
    print("  Verify:   python watchdog_agent.py --test")
    print("  Run:      python watchdog_agent.py")


def run_test() -> None:
    cfg = load_config()
    print(f"\nSite: {cfg.get('site')}")
    print("Probing devices:")
    for d in probe_all(cfg):
        tag = "OK " if d["ok"] else "DOWN"
        print(f"  [{tag}] {d['label']:24s} ({d['type']})" + (f"  — {d['error']}" if d["error"] else ""))
    base = _cloud_base(cfg)
    print(f"\nCloud: {base}")
    if not cfg.get("tenant_slug") or not cfg.get("agent_key"):
        print("  [ERR] tenant_slug / agent_key not set — re-run --setup")
        return
    try:
        r = requests.post(f"{base}/api/v1/monitor/heartbeat",
                          json={"tenant": cfg["tenant_slug"], "agent_key": cfg["agent_key"],
                                "site": cfg.get("site"), "devices": []},
                          timeout=15)
        if r.status_code == 200:
            print("  [OK]  Cloud accepted the heartbeat (auth valid)")
        elif r.status_code == 403:
            print("  [ERR] AGENT KEY REJECTED — check tenant_slug + agent_key")
        else:
            print(f"  [ERR] Cloud HTTP {r.status_code}: {r.text[:200]}")
    except Exception as e:  # noqa: BLE001
        print(f"  [ERR] Cloud unreachable: {e}")


_SERVICE_NAME = "WeighbridgeWatchdogAgent"


def install_service() -> None:
    import shutil, subprocess
    nssm = shutil.which("nssm")
    if not nssm:
        print("NSSM not found. Install from https://nssm.cc and add it to PATH.")
        sys.exit(1)
    if getattr(sys, "frozen", False) or "__compiled__" in globals():
        subprocess.run([nssm, "install", _SERVICE_NAME, str(Path(sys.executable).resolve())], check=True)
    else:
        subprocess.run([nssm, "install", _SERVICE_NAME, sys.executable,
                        str((BASE_DIR / "watchdog_agent.py").resolve())], check=True)
    subprocess.run([nssm, "set", _SERVICE_NAME, "AppDirectory", str(BASE_DIR)], check=True)
    subprocess.run([nssm, "set", _SERVICE_NAME, "Start", "SERVICE_AUTO_START"], check=False)
    subprocess.run([nssm, "set", _SERVICE_NAME, "AppExit", "Default", "Restart"], check=False)
    subprocess.run([nssm, "set", _SERVICE_NAME, "AppStdout", str(LOG_DIR / "service_stdout.log")], check=True)
    subprocess.run([nssm, "set", _SERVICE_NAME, "AppStderr", str(LOG_DIR / "service_stderr.log")], check=True)
    subprocess.run([nssm, "set", _SERVICE_NAME, "AppRotateFiles", "1"], check=False)
    subprocess.run([nssm, "set", _SERVICE_NAME, "AppRotateBytes", "10485760"], check=False)
    print(f"\nService '{_SERVICE_NAME}' installed.  Start:  nssm start {_SERVICE_NAME}")


def uninstall_service() -> None:
    import shutil, subprocess
    nssm = shutil.which("nssm")
    if not nssm:
        print("NSSM not found.")
        sys.exit(1)
    subprocess.run([nssm, "stop", _SERVICE_NAME], check=False)
    subprocess.run([nssm, "remove", _SERVICE_NAME, "confirm"], check=True)
    print("Service removed.")


def main() -> None:
    import argparse
    p = argparse.ArgumentParser(description="Weighbridge Watchdog Agent")
    p.add_argument("--setup", action="store_true", help="Interactive config wizard")
    p.add_argument("--test", action="store_true", help="Probe every device + cloud once, then exit")
    p.add_argument("--install", action="store_true", help="Install as a Windows service (NSSM)")
    p.add_argument("--uninstall", action="store_true", help="Remove the Windows service")
    p.add_argument("--debug", action="store_true", help="Enable DEBUG logging")
    args = p.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    if args.setup:
        return setup_wizard()
    if args.test:
        return run_test()
    if args.install:
        return install_service()
    if args.uninstall:
        return uninstall_service()

    cfg = load_config()
    if not cfg.get("tenant_slug") or not cfg.get("agent_key"):
        log.error("tenant_slug and agent_key are required.\nRun: python watchdog_agent.py --setup")
        sys.exit(1)
    # Silence noisy urllib3 InsecureRequestWarning (self-signed camera TLS).
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass
    state = State()
    start_status_server(cfg, state)
    run(cfg, state)


if __name__ == "__main__":
    main()
