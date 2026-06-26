#!/usr/bin/env python3
"""
Weighbridge Tally Connector (SaaS/relay mode).

Runs as a Windows service on the client's LAN (ideally the same PC as Tally).
It makes ONLY outbound HTTPS calls to the cloud — the cloud never connects into
the client's network. Loop:

    claim pending jobs from the cloud  →  POST each job's XML to the LOCAL Tally
    gateway  →  report the result back  →  the cloud flips the source row's
    tally_synced.

Auth = {tenant, agent_key} in the POST body (same as the scale agent); no user
login. Self-contained single file (copy-and-run), mirroring scale_agent.py.

CLI:
    python tally_connector.py --setup       # configure cloud + local Tally
    python tally_connector.py --test        # check cloud auth + local Tally
    python tally_connector.py               # run in foreground
    python tally_connector.py --install     # install as a Windows service (NSSM)
    python tally_connector.py --uninstall
"""
from __future__ import annotations

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
from xml.etree import ElementTree as ET

try:
    import requests
except ImportError:
    print("Missing dependency. Run:  pip install requests")
    sys.exit(1)

CONFIG_FILE = Path(__file__).parent / "tally_connector.json"
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "tally_connector.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("tally-connector")

DEFAULT_CONFIG: dict = {
    "cloud_url": "https://weighbridgesetu.com",
    "tenant_slug": "",
    "agent_key": "",
    # Local Tally gateway (Gateway of Tally → F12 → Advanced → Enable XML/ODBC server)
    "tally_host": "localhost",
    "tally_port": 9000,
    "poll_interval_ms": 5000,
    "max_jobs_per_poll": 10,
    "status_port": 9010,        # local diagnostics (≠ scale agent's 9002)
    "connector_id": "",         # auto-filled per machine if blank
}


# ── Config ────────────────────────────────────────────────────────────────────

def _default_connector_id() -> str:
    return f"tally-{socket.gethostname()}"[:64]


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        log.error("Config not found: %s\nRun: python tally_connector.py --setup", CONFIG_FILE)
        sys.exit(1)
    # utf-8-sig strips the BOM PowerShell 5.1 Out-File adds by default.
    with open(CONFIG_FILE, "r", encoding="utf-8-sig") as fh:
        data = json.load(fh)
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg.update(data)
    if not cfg.get("connector_id"):
        cfg["connector_id"] = _default_connector_id()
    return cfg


def save_config(cfg: dict) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
    log.info("Config saved → %s", CONFIG_FILE)


def _effective_push_base(cloud_url: str, tenant_slug: str) -> str:
    """Cloud base URL. The apex weighbridgesetu.com 301-redirects to www, and a
    301 turns a POST into a GET that DROPS the body — so route to the tenant's
    own subdomain (no redirect). Custom domains / localhost are left untouched.
    (Same fix as scale_agent.py.)"""
    base = (cloud_url or "").rstrip("/")
    try:
        parts = urlparse(base)
        host = (parts.hostname or "").lower()
    except Exception:
        return base
    if tenant_slug and host in ("weighbridgesetu.com", "www.weighbridgesetu.com"):
        return f"{parts.scheme or 'https'}://{tenant_slug}.weighbridgesetu.com"
    return base


# ── Local Tally push ────────────────────────────────────────────────────────────

def _parse_tally_response(xml_text: str) -> tuple[bool, str]:
    """Decode Tally's import reply: LINEERROR → fail, CREATED/ALTERED → ok."""
    try:
        root = ET.fromstring(xml_text)
        errors = [e.text for e in root.findall(".//LINEERROR") if e.text]
        if errors:
            return False, "; ".join(errors)
        created = root.find(".//CREATED")
        altered = root.find(".//ALTERED")
        if created is not None and int(created.text or "0") > 0:
            return True, f"Created in Tally ({created.text})"
        if altered is not None and int(altered.text or "0") > 0:
            return True, f"Updated in Tally ({altered.text})"
        return True, "Sent to Tally"
    except ET.ParseError:
        if "<CREATED>" in xml_text:
            return True, "Created in Tally"
        return True, "Sent to Tally (response: OK)"


def push_to_local_tally(xml: str, host: str, port: int, timeout: float = 20.0):
    """POST one voucher's XML to the local Tally gateway. Returns (ok, msg, raw)."""
    url = f"http://{host}:{port}"
    try:
        resp = requests.post(
            url, data=xml.encode("utf-8"),
            headers={"Content-Type": "text/xml; charset=utf-8"}, timeout=timeout,
        )
        if resp.status_code != 200:
            return False, f"Tally HTTP {resp.status_code}", resp.text[:4000]
        ok, msg = _parse_tally_response(resp.text)
        return ok, msg, resp.text[:4000]
    except requests.ConnectionError:
        return False, f"Cannot reach Tally at {url} — is Tally open with its XML/ODBC server enabled?", None
    except requests.Timeout:
        return False, "Tally connection timed out", None
    except Exception as e:  # noqa: BLE001
        return False, f"Unexpected error: {e}", None


def tally_reachable(host: str, port: int, timeout: float = 5.0) -> tuple[bool, str]:
    """Quick reachability probe (List of Companies) for --test + status."""
    xml = ("<ENVELOPE><HEADER><TALLYREQUEST>Export Data</TALLYREQUEST></HEADER>"
           "<BODY><EXPORTDATA><REQUESTDESC><REPORTNAME>List of Companies</REPORTNAME>"
           "</REQUESTDESC></EXPORTDATA></BODY></ENVELOPE>")
    try:
        resp = requests.post(f"http://{host}:{port}", data=xml,
                             headers={"Content-Type": "text/xml"}, timeout=timeout)
        return resp.status_code == 200, f"HTTP {resp.status_code}"
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:120]


# ── Cloud calls ─────────────────────────────────────────────────────────────────

def _cloud_base(cfg: dict) -> str:
    return _effective_push_base(cfg.get("cloud_url", ""), cfg.get("tenant_slug", ""))


def _auth(cfg: dict) -> dict:
    return {"tenant": cfg["tenant_slug"], "agent_key": cfg["agent_key"],
            "connector_id": cfg.get("connector_id", "")}


# ── Runtime state (for the status server) ───────────────────────────────────────

class State:
    def __init__(self):
        self.cloud_online = False
        self.tally_ok = False
        self.tally_msg = ""
        self.pushed = 0
        self.errors = 0
        self.last_claim_at = None
        self.last_result = ""


def run(cfg: dict, state: State) -> None:
    base = _cloud_base(cfg)
    poll = max(1.0, float(cfg.get("poll_interval_ms", 5000)) / 1000.0)
    n = int(cfg.get("max_jobs_per_poll", 10))
    host = cfg.get("tally_host", "localhost")
    port = int(cfg.get("tally_port", 9000))
    claim_url = f"{base}/api/v1/tally/connector/jobs/claim"
    log.info("Tally Connector starting — cloud=%s tenant=%s local Tally=%s:%s",
             base, cfg["tenant_slug"], host, port)

    while True:
        try:
            r = requests.post(claim_url, json={**_auth(cfg), "max_jobs": n, "claim_ttl_sec": 120}, timeout=20)
            if r.status_code == 403:
                state.cloud_online = False
                log.error("AGENT KEY REJECTED (403) — re-run: python tally_connector.py --setup")
                time.sleep(min(poll * 4, 60))
                continue
            if not r.ok:
                state.cloud_online = (r.status_code == 400)
                log.warning("Claim failed HTTP %s: %s", r.status_code, r.text[:200])
                time.sleep(min(poll * 2, 30))
                continue

            state.cloud_online = True
            state.last_claim_at = datetime.now().isoformat(timespec="seconds")
            jobs = r.json().get("jobs", [])
            if not jobs:
                time.sleep(poll)
                continue

            log.info("Claimed %d job(s)", len(jobs))
            for job in jobs:   # already masters-first ordered by the server
                ok, msg, raw = push_to_local_tally(job["xml"], host, port)
                state.tally_ok, state.tally_msg = ok, msg
                try:
                    requests.post(
                        f"{base}/api/v1/tally/connector/jobs/{job['id']}/result",
                        json={**_auth(cfg), "success": ok, "message": msg, "tally_response": raw},
                        timeout=20,
                    )
                except requests.RequestException as e:
                    log.warning("Could not report result for job %s: %s (will re-lease)", job["id"][:8], e)
                if ok:
                    state.pushed += 1
                    log.info("  job %s (%s) → Tally OK: %s", job["id"][:8], job["entity_type"], msg)
                else:
                    state.errors += 1
                    log.warning("  job %s (%s) → Tally FAILED: %s", job["id"][:8], job["entity_type"], msg)
                state.last_result = f"{job['entity_type']}: {'OK' if ok else 'FAIL'} — {msg}"

            # Drain fast when a full batch came back (more may be waiting).
            time.sleep(0.5 if len(jobs) >= n else poll)
        except requests.RequestException as e:
            state.cloud_online = False
            log.warning("Cloud unreachable: %s", e)
            time.sleep(min(poll * 2, 30))
        except Exception as e:  # noqa: BLE001
            log.error("Loop error: %s", e, exc_info=True)
            time.sleep(poll)


# ── Status server (local diagnostics) ───────────────────────────────────────────

_STATUS_HTML = r"""<!doctype html><html><head><meta charset="utf-8">
<title>Tally Connector</title><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
 body{font-family:system-ui,'Segoe UI',Arial;margin:0;background:#0f172a;color:#e2e8f0}
 .wrap{max-width:640px;margin:0 auto;padding:16px}h1{font-size:18px}.sub{color:#94a3b8;font-size:12px;margin-bottom:14px}
 .card{background:#1e293b;border:1px solid #334155;border-radius:12px;padding:16px;margin-bottom:12px}
 .badges{display:flex;gap:8px;flex-wrap:wrap}.b{font-size:12px;font-weight:700;padding:4px 10px;border-radius:999px;border:1px solid}
 .ok{background:#064e3b;border-color:#10b981;color:#a7f3d0}.bad{background:#450a0a;border-color:#ef4444;color:#fecaca}
 .lbl{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:#94a3b8}
 .mono{font-family:Consolas,monospace;font-size:13px;background:#0b1220;border:1px solid #334155;border-radius:8px;padding:10px;white-space:pre-wrap;word-break:break-all}
 .big{font-size:40px;font-weight:800}
</style></head><body><div class="wrap">
 <h1>Tally Connector</h1><div class="sub" id="meta">Local diagnostics — this page stays on this PC.</div>
 <div class="card"><div class="badges" id="badges"></div></div>
 <div class="card"><div class="lbl">Pushed / Errors</div><div class="big"><span id="pushed">0</span> <span style="color:#64748b">/</span> <span id="errors" style="color:#fca5a5">0</span></div>
   <div class="sub" id="cfgline" style="margin-top:6px"></div></div>
 <div class="card"><div class="lbl">Last result</div><div class="mono" id="last">—</div></div>
</div><script>
async function poll(){try{const s=await(await fetch('/status')).json();
 const b=[];b.push(s.cloud_online?'<span class="b ok">CLOUD ONLINE</span>':'<span class="b bad">CLOUD OFFLINE</span>');
 b.push(s.tally_ok?'<span class="b ok">TALLY OK</span>':'<span class="b bad">TALLY '+(s.tally_msg?'ERROR':'IDLE')+'</span>');
 document.getElementById('badges').innerHTML=b.join('');
 document.getElementById('pushed').textContent=s.pushed;document.getElementById('errors').textContent=s.errors;
 document.getElementById('cfgline').textContent='Tally '+s.tally_host+':'+s.tally_port+'   last claim '+(s.last_claim_at||'never');
 document.getElementById('last').textContent=s.last_result||'(no jobs yet)';
 }catch(e){document.getElementById('badges').innerHTML='<span class="b bad">connector not reachable</span>';}}
poll();setInterval(poll,2000);
</script></body></html>"""


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

    port = _free_port(int(cfg.get("status_port", 9010)))

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, body, ctype):
            data = body.encode() if isinstance(body, str) else body
            self.send_response(code); self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data))); self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._send(200, _STATUS_HTML, "text/html; charset=utf-8")
            elif self.path == "/status":
                self._send(200, json.dumps({
                    "service": "tally_connector",
                    "cloud_online": state.cloud_online,
                    "tally_ok": state.tally_ok, "tally_msg": state.tally_msg,
                    "tally_host": cfg.get("tally_host"), "tally_port": cfg.get("tally_port"),
                    "pushed": state.pushed, "errors": state.errors,
                    "last_claim_at": state.last_claim_at, "last_result": state.last_result,
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


# ── Setup / test / service ──────────────────────────────────────────────────────

def setup_wizard() -> None:
    print("\n" + "=" * 60)
    print("  Weighbridge Tally Connector — Setup")
    print("=" * 60 + "\n")
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["cloud_url"]   = input(f"Cloud URL [{cfg['cloud_url']}]: ").strip() or cfg["cloud_url"]
    cfg["tenant_slug"] = input("Tenant slug (e.g. megna-trading): ").strip()
    cfg["agent_key"]   = input("Agent API key (from the Platform console): ").strip()
    cfg["tally_host"]  = input("Local Tally host [localhost]: ").strip() or "localhost"
    try:
        cfg["tally_port"] = int(input("Local Tally port [9000]: ").strip() or "9000")
    except ValueError:
        cfg["tally_port"] = 9000
    cfg["connector_id"] = _default_connector_id()
    save_config(cfg)
    print(f"\n  Config saved: {CONFIG_FILE}")
    print("  Verify:   python tally_connector.py --test")
    print("  Run:      python tally_connector.py")


def run_test() -> None:
    cfg = load_config()
    base = _cloud_base(cfg)
    print(f"\nCloud: {base}")
    try:
        r = requests.post(f"{base}/api/v1/tally/connector/ping", json=_auth(cfg), timeout=15)
        if r.status_code == 200:
            d = r.json()
            print(f"  [OK]  Cloud auth accepted — pending={d.get('pending')} dead={d.get('dead')}")
        elif r.status_code == 403:
            print("  [ERR] AGENT KEY REJECTED — check tenant_slug + agent_key (re-run --setup)")
        elif r.status_code == 400:
            print(f"  [ERR] {r.json().get('detail', r.text[:200])}")
        else:
            print(f"  [ERR] Cloud ping HTTP {r.status_code}: {r.text[:200]}")
    except Exception as e:  # noqa: BLE001
        print(f"  [ERR] Cloud unreachable: {e}")
    ok, msg = tally_reachable(cfg["tally_host"], cfg["tally_port"])
    tag = "OK " if ok else "ERR"
    print(f"  [{tag}] Local Tally {cfg['tally_host']}:{cfg['tally_port']} — {msg}")
    if not ok:
        print("        Open Tally → F12 → Advanced → Enable XML/ODBC server, and confirm the port.")


_SERVICE_NAME = "WeighbridgeTallyConnector"


def install_service() -> None:
    import shutil, subprocess
    nssm = shutil.which("nssm")
    if not nssm:
        print("NSSM not found. Install from https://nssm.cc and add it to PATH.")
        sys.exit(1)
    python = sys.executable
    script = str(Path(__file__).resolve())
    subprocess.run([nssm, "install", _SERVICE_NAME, python, script], check=True)
    subprocess.run([nssm, "set", _SERVICE_NAME, "AppDirectory", str(Path(__file__).parent)], check=True)
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
    p = argparse.ArgumentParser(description="Weighbridge Tally Connector")
    p.add_argument("--setup", action="store_true", help="Interactive config wizard")
    p.add_argument("--test", action="store_true", help="Check cloud auth + local Tally, then exit")
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
        log.error("tenant_slug and agent_key are required.\nRun: python tally_connector.py --setup")
        sys.exit(1)
    state = State()
    start_status_server(cfg, state)
    run(cfg, state)


if __name__ == "__main__":
    main()
