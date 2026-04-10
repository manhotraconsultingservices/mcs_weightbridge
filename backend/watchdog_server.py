#!/usr/bin/env python3
"""
Weighbridge Recovery Watchdog  —  Port 9002
============================================
A completely standalone HTTP server using ONLY Python standard library.
No FastAPI, no SQLAlchemy, no external packages required.

Purpose: Non-IT staff open http://localhost:9002 in a browser and get
a clear traffic-light dashboard showing what is broken and one-click
buttons to restart individual components.

Works even when the main application is completely down.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from pathlib import Path
from urllib.request import urlopen, Request as _Req
from urllib.error import URLError

# ── Configuration ──────────────────────────────────────────────────────────────
PORT            = 9002
BACKEND_PORT    = 9001
FRONTEND_PORT   = 9000
DB_PORT         = 5432
DB_CONTAINER    = "weighbridge_db"
BACKEND_SVC     = "WeighbridgeBackend"
FRONTEND_SVC    = "WeighbridgeFrontend"

# Locate workspace root — watchdog_server.py lives in backend/
WORKSPACE = Path(__file__).resolve().parent.parent   # …/workspace_Weighbridge
LOG_DIR   = WORKSPACE / "logs"

# ── Status helpers ─────────────────────────────────────────────────────────────

def _svc_status(name: str) -> dict:
    """Query a Windows service via sc.exe."""
    try:
        r = subprocess.run(["sc", "query", name],
                           capture_output=True, text=True, timeout=6)
        out = r.stdout
        if "RUNNING"       in out: return {"ok": True,  "label": "Running",    "state": "running"}
        if "STOPPED"       in out: return {"ok": False, "label": "Stopped",    "state": "stopped"}
        if "START_PENDING" in out: return {"ok": True,  "label": "Starting…",  "state": "starting"}
        if "STOP_PENDING"  in out: return {"ok": False, "label": "Stopping…",  "state": "stopping"}
        return                           {"ok": False, "label": "Unknown",     "state": "unknown"}
    except Exception as e:
        return {"ok": False, "label": "Error", "state": "error", "detail": str(e)}


def _port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def _backend_health() -> dict:
    """Hit the real /api/v1/health endpoint."""
    try:
        req = _Req(f"http://localhost:{BACKEND_PORT}/api/v1/health",
                   headers={"Accept": "application/json"})
        with urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            return {"reachable": True, "data": data}
    except URLError as e:
        return {"reachable": False, "error": str(e.reason)}
    except Exception as e:
        return {"reachable": False, "error": str(e)}


def _docker_db_status() -> dict:
    """Check Docker container status for PostgreSQL."""
    try:
        r = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Status}}", DB_CONTAINER],
            capture_output=True, text=True, timeout=6
        )
        state = r.stdout.strip()
        if state == "running": return {"ok": True,  "label": "Running",    "state": "running",  "via": "docker"}
        if state == "exited":  return {"ok": False, "label": "Stopped",    "state": "stopped",  "via": "docker"}
        if state:              return {"ok": False, "label": state.title(),"state": state,      "via": "docker"}
    except FileNotFoundError:
        pass   # Docker not installed — fall back to port check
    except Exception:
        pass
    # Fallback: just check if port 5432 is open
    ok = _port_open("localhost", DB_PORT)
    return {"ok": ok, "label": "Running" if ok else "Unreachable", "state": "running" if ok else "stopped", "via": "port"}


def _disk_info() -> dict:
    try:
        usage = shutil.disk_usage(str(WORKSPACE))
        free_pct = (usage.free / usage.total) * 100
        free_gb  = usage.free  / (1024 ** 3)
        total_gb = usage.total / (1024 ** 3)
        return {
            "ok": free_pct > 10,
            "free_pct": round(free_pct, 1),
            "free_gb":  round(free_gb, 1),
            "total_gb": round(total_gb, 1),
            "warn": free_pct < 20,
        }
    except Exception as e:
        return {"ok": True, "error": str(e), "free_pct": 100}


def _tail_log(service_key: str, lines: int = 60) -> str:
    candidates = {
        "backend":  ["backend_stderr.log",  "backend_stdout.log"],
        "frontend": ["frontend_stderr.log", "frontend_stdout.log"],
    }
    for fname in candidates.get(service_key, []):
        path = LOG_DIR / fname
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    all_lines = f.readlines()
                return "".join(all_lines[-lines:]).strip() or "(log is empty)"
            except Exception as e:
                return f"Error reading {fname}: {e}"
    return f"Log file not found in {LOG_DIR}"


def _collect_status() -> dict:
    backend_svc  = _svc_status(BACKEND_SVC)
    frontend_svc = _svc_status(FRONTEND_SVC)
    db           = _docker_db_status()
    health       = _backend_health()
    disk         = _disk_info()
    backend_port = _port_open("localhost", BACKEND_PORT)

    frontend_port = _port_open("localhost", FRONTEND_PORT)
    # Frontend is OK if the port is reachable (covers both service mode and dev mode)
    frontend_ok   = frontend_svc["ok"] or frontend_port

    overall_ok = backend_svc["ok"] and backend_port and frontend_ok and db["ok"]

    return {
        "ts":       datetime.now().strftime("%H:%M:%S"),
        "date":     datetime.now().strftime("%d %b %Y"),
        "overall":  overall_ok,
        "backend":  {**backend_svc,  "port": backend_port},
        "frontend": {**frontend_svc, "ok": frontend_ok, "port": frontend_port,
                     "label": "Running" if frontend_ok else "Down"},
        "database": db,
        "health":   health,
        "disk":     disk,
    }


# ── Restart helpers ────────────────────────────────────────────────────────────

def _svc_exists(name: str) -> bool:
    """Return True only if the service is registered AND not disabled (i.e. we can start it)."""
    try:
        r = subprocess.run(["sc", "query", name], capture_output=True, text=True, timeout=5)
        if "1060" in r.stdout or "1060" in r.stderr:
            return False   # service not installed at all
        # Check start type — disabled services cannot be started via sc start
        qc = subprocess.run(["sc", "qc", name], capture_output=True, text=True, timeout=5)
        if "DISABLED" in qc.stdout:
            return False   # service exists but is disabled
        return True
    except Exception:
        return False


def _wait_for_svc_state(name: str, desired: str, timeout_s: int = 30) -> bool:
    """Poll sc query until service reaches desired state ('RUNNING' or 'STOPPED')."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            r = subprocess.run(["sc", "query", name], capture_output=True, text=True, timeout=5)
            if desired in r.stdout:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def _restart_frontend_dev(port: int = 9000) -> dict:
    """
    Fallback when WeighbridgeFrontend service is not registered or is disabled.
    Returns a friendly, port-aware message instead of attempting a service restart.
    """
    if _port_open("localhost", port):
        return {
            "ok": False,
            "error": (
                "The Web Interface is running in development mode (npm run dev) "
                "and is not installed as a Windows service — the Restart button "
                "cannot control it automatically.  "
                "It is currently UP and working normally on port 9000."
            )
        }
    # Port is not open — frontend is actually down
    return {
        "ok": False,
        "error": (
            "The Web Interface is DOWN and is not installed as a Windows service.  "
            "Open a Command Prompt in the workspace folder and run:  "
            "cd frontend  &&  npm run dev"
        )
    }


def _restart_svc(name: str) -> dict:
    """Stop a Windows service, wait until fully stopped, then start and wait until running."""
    try:
        # ── Pre-check: service must be registered ─────────────────────────────
        if not _svc_exists(name):
            return {
                "ok": False,
                "error": (
                    f"'{name}' is not registered as a Windows service. "
                    f"Run  scripts\\nssm-register.ps1  (as Administrator) to register it, "
                    f"then retry. If you are in development mode, restart the component manually."
                )
            }

        # ── Step 1: Stop ──────────────────────────────────────────────────────
        subprocess.run(["sc", "stop", name], capture_output=True, timeout=15)
        stopped = _wait_for_svc_state(name, "STOPPED", timeout_s=25)
        if not stopped:
            # Service may already have been stopped — that's fine, continue
            pass

        # ── Step 2: Start ─────────────────────────────────────────────────────
        r = subprocess.run(["sc", "start", name], capture_output=True, text=True, timeout=15)
        if r.returncode not in (0, 1056):   # 1056 = already running (fine)
            return {"ok": False, "error": f"sc start failed (code {r.returncode}): {r.stderr.strip()}"}

        # ── Step 3: Wait until RUNNING (up to 40 s) ───────────────────────────
        running = _wait_for_svc_state(name, "RUNNING", timeout_s=40)
        if running:
            return {"ok": True, "message": f"{name} restarted successfully"}
        else:
            # Check what state it ended up in
            check = subprocess.run(["sc", "query", name], capture_output=True, text=True, timeout=5)
            state_line = next((l.strip() for l in check.stdout.splitlines() if "STATE" in l), "unknown")
            return {"ok": False, "error": f"Service did not reach RUNNING within 40 s. Current: {state_line}"}

    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "sc command timed out — service may be hung"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _restart_db() -> dict:
    """Restart the PostgreSQL Docker container and wait for port 5432 to come back."""
    try:
        r = subprocess.run(
            ["docker", "restart", DB_CONTAINER],
            capture_output=True, text=True, timeout=40
        )
        if r.returncode != 0:
            return {"ok": False, "error": (r.stdout + r.stderr)[:400]}

        # Wait for port 5432 to be reachable (up to 30 s)
        deadline = time.time() + 30
        while time.time() < deadline:
            if _port_open("localhost", DB_PORT):
                return {"ok": True, "message": "Database restarted successfully"}
            time.sleep(1)

        return {"ok": False, "error": "Database container started but port 5432 not reachable within 30 s"}

    except FileNotFoundError:
        return {"ok": False, "error": "Docker not found — cannot restart database automatically"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Embedded HTML dashboard ────────────────────────────────────────────────────

_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Weighbridge — System Monitor</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f1f5f9;color:#1e293b;min-height:100vh}
  header{background:#0f172a;color:#fff;padding:16px 24px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px}
  header h1{font-size:1.2rem;font-weight:700;display:flex;align-items:center;gap:10px}
  header h1 span{font-size:1.6rem}
  .ts{font-size:.85rem;color:#94a3b8;text-align:right}
  .ts b{color:#e2e8f0;font-size:1rem}
  .container{max-width:1100px;margin:0 auto;padding:20px 16px;display:flex;flex-direction:column;gap:20px}

  /* Banner */
  .banner{padding:18px 24px;border-radius:14px;font-size:1.15rem;font-weight:700;display:flex;align-items:center;gap:12px;transition:all .4s}
  .banner.ok{background:#dcfce7;color:#15803d;border:2px solid #86efac}
  .banner.bad{background:#fee2e2;color:#b91c1c;border:2px solid #fca5a5;animation:pulse 2s infinite}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.7}}

  /* Cards */
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px}
  .card{background:#fff;border-radius:14px;padding:20px;box-shadow:0 1px 3px rgba(0,0,0,.08);border-top:5px solid #e2e8f0;transition:border-color .3s}
  .card.ok{border-top-color:#22c55e}
  .card.warn{border-top-color:#f59e0b}
  .card.bad{border-top-color:#ef4444}
  .card-title{font-size:.75rem;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:#64748b;margin-bottom:6px}
  .card-status{font-size:1.5rem;font-weight:800;margin-bottom:4px}
  .card-status.ok{color:#16a34a}
  .card-status.warn{color:#d97706}
  .card-status.bad{color:#dc2626}
  .card-sub{font-size:.82rem;color:#94a3b8;margin-bottom:16px}
  .btn{display:inline-flex;align-items:center;gap:6px;padding:10px 18px;border-radius:8px;border:none;font-size:.9rem;font-weight:600;cursor:pointer;transition:background .2s,transform .1s;width:100%;justify-content:center}
  .btn:active{transform:scale(.97)}
  .btn-restart{background:#3b82f6;color:#fff}
  .btn-restart:hover{background:#2563eb}
  .btn-restart:disabled{background:#94a3b8;cursor:not-allowed}

  /* Disk bar */
  .disk-bar-bg{background:#e2e8f0;border-radius:99px;height:14px;overflow:hidden;margin:10px 0 6px}
  .disk-bar{height:100%;border-radius:99px;transition:width .5s}
  .disk-bar.ok{background:#22c55e}
  .disk-bar.warn{background:#f59e0b}
  .disk-bar.bad{background:#ef4444}

  /* Guide */
  .guide{background:#fff;border-radius:14px;padding:20px 24px;box-shadow:0 1px 3px rgba(0,0,0,.08)}
  .guide h2{font-size:1rem;font-weight:700;margin-bottom:12px;color:#1e293b}
  .steps{list-style:none;counter-reset:steps;display:flex;flex-direction:column;gap:10px}
  .steps li{counter-increment:steps;display:flex;align-items:flex-start;gap:12px;font-size:.9rem;color:#475569}
  .steps li::before{content:counter(steps);background:#3b82f6;color:#fff;font-weight:700;font-size:.8rem;border-radius:50%;width:22px;height:22px;display:flex;align-items:center;justify-content:center;flex-shrink:0;margin-top:1px}

  /* Logs */
  .logs-section{background:#fff;border-radius:14px;box-shadow:0 1px 3px rgba(0,0,0,.08);overflow:hidden}
  .logs-header{padding:14px 20px;border-bottom:1px solid #f1f5f9;display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap}
  .logs-header h2{font-size:.95rem;font-weight:700}
  .log-tabs{display:flex;gap:6px}
  .log-tab{padding:5px 14px;border-radius:6px;border:1px solid #e2e8f0;background:#f8fafc;font-size:.82rem;cursor:pointer;font-weight:500}
  .log-tab.active{background:#3b82f6;color:#fff;border-color:#3b82f6}
  pre.log-output{background:#0f172a;color:#e2e8f0;font-size:.78rem;line-height:1.55;padding:16px 20px;max-height:300px;overflow-y:auto;white-space:pre-wrap;word-break:break-all}

  /* Countdown */
  .countdown{font-size:.8rem;color:#94a3b8}
  .spinner{display:inline-block;width:10px;height:10px;border:2px solid #94a3b8;border-top-color:#3b82f6;border-radius:50%;animation:spin .7s linear infinite;margin-right:4px;vertical-align:middle}
  @keyframes spin{to{transform:rotate(360deg)}}

  /* Toast */
  .toast{position:fixed;bottom:24px;right:24px;background:#1e293b;color:#f8fafc;padding:12px 20px;border-radius:10px;font-size:.88rem;font-weight:500;max-width:320px;z-index:999;opacity:0;transform:translateY(10px);transition:all .3s}
  .toast.show{opacity:1;transform:translateY(0)}
  .toast.success{border-left:4px solid #22c55e}
  .toast.error{border-left:4px solid #ef4444}

  footer{text-align:center;padding:20px;font-size:.78rem;color:#94a3b8}
</style>
</head>
<body>
<header>
  <h1><span>🏭</span> Weighbridge System Monitor</h1>
  <div class="ts"><div class="countdown" id="cd">Refreshing…</div><b id="ts">--:--:--</b><br><span id="dt"></span></div>
</header>

<div class="container">
  <!-- Overall Banner -->
  <div class="banner ok" id="banner">
    <span id="banner-icon">⏳</span>
    <span id="banner-text">Checking system status…</span>
  </div>

  <!-- Component Cards -->
  <div class="cards" id="cards">
    <div class="card" id="card-backend">
      <div class="card-title">⚙️ Application Server</div>
      <div class="card-status" id="st-backend">Checking…</div>
      <div class="card-sub" id="sub-backend">Backend API</div>
      <button class="btn btn-restart" id="btn-backend" onclick="restart('backend')">↺ Restart App Server</button>
    </div>
    <div class="card" id="card-database">
      <div class="card-title">🗄️ Database</div>
      <div class="card-status" id="st-database">Checking…</div>
      <div class="card-sub" id="sub-database">PostgreSQL</div>
      <button class="btn btn-restart" id="btn-database" onclick="restart('database')">↺ Restart Database</button>
    </div>
    <div class="card" id="card-frontend">
      <div class="card-title">🖥️ Web Interface</div>
      <div class="card-status" id="st-frontend">Checking…</div>
      <div class="card-sub" id="sub-frontend">User Portal</div>
      <button class="btn btn-restart" id="btn-frontend" onclick="restart('frontend')">↺ Restart Web Interface</button>
    </div>
    <div class="card" id="card-disk">
      <div class="card-title">💾 Disk Space</div>
      <div class="card-status" id="st-disk">Checking…</div>
      <div class="disk-bar-bg"><div class="disk-bar ok" id="disk-bar" style="width:0%"></div></div>
      <div class="card-sub" id="sub-disk">Loading…</div>
    </div>
  </div>

  <!-- Step-by-step Guide -->
  <div class="guide">
    <h2>🆘 What to do when something shows RED</h2>
    <ol class="steps">
      <li><strong>Wait 60 seconds</strong> — the system tries to fix itself automatically.</li>
      <li><strong>Click the RESTART button</strong> on the red component above.</li>
      <li><strong>Wait 30 seconds</strong>, then check if it turned green.</li>
      <li>If the <em>Database</em> is red and won't restart, try restarting the App Server too.</li>
      <li>If nothing works after 3 minutes — <strong>call IT support</strong> and read the log below.</li>
    </ol>
  </div>

  <!-- Recent Logs -->
  <div class="logs-section">
    <div class="logs-header">
      <h2>📋 Recent Log Messages</h2>
      <div style="display:flex;align-items:center;gap:10px">
        <div class="log-tabs">
          <button class="log-tab active" id="tab-backend"  onclick="switchLog('backend')">App Server</button>
          <button class="log-tab"        id="tab-frontend" onclick="switchLog('frontend')">Web Portal</button>
        </div>
        <button class="btn btn-restart" style="width:auto;padding:5px 12px;font-size:.8rem" onclick="loadLog(currentLog)">⟳ Refresh</button>
      </div>
    </div>
    <pre class="log-output" id="log-output">Loading…</pre>
  </div>
</div>

<div class="toast" id="toast"></div>

<footer>Weighbridge Recovery Watchdog · Port 9002 · Auto-refreshes every 10 s</footer>

<script>
var currentLog = 'backend';
var countdown  = 10;
var timer;

function setCard(id, ok, warn, statusText, subText) {
  var card = document.getElementById('card-' + id);
  var st   = document.getElementById('st-'   + id);
  var sub  = document.getElementById('sub-'  + id);
  card.className = 'card ' + (ok ? (warn ? 'warn' : 'ok') : 'bad');
  st.className   = 'card-status ' + (ok ? (warn ? 'warn' : 'ok') : 'bad');
  st.textContent = statusText;
  if (sub && subText) sub.textContent = subText;
}

function updateStatus(d) {
  document.getElementById('ts').textContent = d.ts;
  document.getElementById('dt').textContent = d.date;

  // Backend
  var bOk  = d.backend.ok && d.backend.port;
  setCard('backend', bOk, false,
    bOk ? '✅ Running' : '❌ Down',
    bOk ? 'App API responding on port 9001' : 'Service stopped or port not responding');

  // Database
  var dbOk = d.database.ok;
  setCard('database', dbOk, false,
    dbOk ? '✅ Running' : '❌ Down',
    'PostgreSQL · Port 5432 · ' + (d.database.via || 'docker'));

  // Frontend
  var fOk = d.frontend.ok && d.frontend.port;
  setCard('frontend', fOk, false,
    fOk ? '✅ Running' : '❌ Down',
    fOk ? 'Web portal on port 9000' : 'Service stopped or port not responding');

  // Disk
  var disk  = d.disk;
  var dpct  = disk.free_pct || 0;
  var dOk   = dpct > 20;
  var dWarn = dpct > 10 && dpct <= 20;
  setCard('disk', dOk || dWarn, dWarn,
    dpct + '% free',
    (disk.free_gb || '?') + ' GB free of ' + (disk.total_gb || '?') + ' GB');
  var bar = document.getElementById('disk-bar');
  bar.style.width = dpct + '%';
  bar.className   = 'disk-bar ' + (dOk ? 'ok' : dWarn ? 'warn' : 'bad');

  // Health detail from API
  if (d.health && d.health.data) {
    var checks = d.health.data.checks || {};
    if (checks.database && checks.database.status !== 'ok') {
      document.getElementById('sub-backend').textContent = '⚠ DB: ' + checks.database.detail;
    }
  }

  // Banner
  var allOk = d.overall;
  var banner = document.getElementById('banner');
  banner.className = 'banner ' + (allOk ? 'ok' : 'bad');
  document.getElementById('banner-icon').textContent = allOk ? '✅' : '🚨';
  document.getElementById('banner-text').textContent = allOk
    ? 'All systems running — everything looks good!'
    : 'Something is down. Follow the steps below or click RESTART on the red card.';
}

function fetchStatus() {
  fetch('/api/status')
    .then(function(r){ return r.json(); })
    .then(updateStatus)
    .catch(function(e){ console.warn('Status fetch failed:', e); });
}

function startCountdown() {
  clearInterval(timer);
  countdown = 10;
  timer = setInterval(function() {
    countdown--;
    document.getElementById('cd').innerHTML = '<span class="spinner"></span>Refreshing in ' + countdown + ' s';
    if (countdown <= 0) {
      fetchStatus();
      countdown = 10;
    }
  }, 1000);
}

function toast(msg, type) {
  var el = document.getElementById('toast');
  el.textContent = msg;
  el.className = 'toast show ' + (type || 'success');
  setTimeout(function(){ el.className = 'toast'; }, 4000);
}

function restart(svc) {
  var btn = document.getElementById('btn-' + svc);
  btn.disabled = true;
  btn.textContent = '⏳ Restarting…';
  fetch('/api/restart/' + svc, { method: 'POST' })
    .then(function(r){ return r.json(); })
    .then(function(d){
      if (d.ok) {
        toast('✅ ' + svc + ' restart command sent. Wait 20–30 s…', 'success');
      } else {
        toast('❌ Restart failed: ' + (d.error || 'Unknown error'), 'error');
      }
      setTimeout(function(){
        btn.disabled = false;
        btn.textContent = '↺ Restart ' + ({backend:'App Server',database:'Database',frontend:'Web Interface'}[svc]||svc);
        fetchStatus();
      }, 8000);
    })
    .catch(function(e){
      toast('❌ Could not reach watchdog: ' + e, 'error');
      btn.disabled = false;
    });
}

function switchLog(svc) {
  currentLog = svc;
  document.querySelectorAll('.log-tab').forEach(function(t){ t.classList.remove('active'); });
  document.getElementById('tab-' + svc).classList.add('active');
  loadLog(svc);
}

function loadLog(svc) {
  fetch('/api/logs/' + svc)
    .then(function(r){ return r.text(); })
    .then(function(t){
      var el = document.getElementById('log-output');
      el.textContent = t;
      el.scrollTop = el.scrollHeight;
    })
    .catch(function(){ document.getElementById('log-output').textContent = 'Could not load log.'; });
}

// Init
fetchStatus();
loadLog('backend');
startCountdown();
</script>
</body>
</html>"""


# ── HTTP request handler ────────────────────────────────────────────────────────

class WatchdogHandler(BaseHTTPRequestHandler):
    # Force HTTP/1.1 so browsers render inline instead of downloading
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass   # suppress default access log noise

    def _send(self, code, content_type, body):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache, no-store")
        # Prevent browsers/Windows from misidentifying the content type
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):
        # Support HEAD so browser preflight checks don't fail
        path = self.path.split("?")[0]
        ct = "text/html; charset=utf-8" if path in ("/", "/index.html") else "application/json"
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]

        if path == "/" or path == "/index.html":
            self._send(200, "text/html; charset=utf-8", _HTML)

        elif path == "/api/status":
            try:
                data = _collect_status()
                self._send(200, "application/json", json.dumps(data))
            except Exception as e:
                self._send(500, "application/json", json.dumps({"error": str(e)}))

        elif path.startswith("/api/logs/"):
            key = path.split("/api/logs/")[-1].split("/")[0]
            text = _tail_log(key)
            self._send(200, "text/plain; charset=utf-8", text)

        else:
            self._send(404, "text/plain", "Not found")

    def do_POST(self):
        path = self.path.split("?")[0]

        if path.startswith("/api/restart/"):
            key = path.split("/api/restart/")[-1].split("/")[0]
            if key == "backend":
                result = _restart_svc(BACKEND_SVC)
            elif key == "frontend":
                if _svc_exists(FRONTEND_SVC):
                    result = _restart_svc(FRONTEND_SVC)
                else:
                    result = _restart_frontend_dev(FRONTEND_PORT)
            elif key == "database":
                result = _restart_db()
            else:
                self._send(400, "application/json", json.dumps({"ok": False, "error": "Unknown service"}))
                return
            self._send(200, "application/json", json.dumps(result))
        else:
            self._send(404, "text/plain", "Not found")

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()


# ── Entry point ────────────────────────────────────────────────────────────────

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Handle each request in a separate thread — prevents one slow check blocking others."""
    daemon_threads = True


def main():
    host = "0.0.0.0"   # bind to all interfaces so LAN access works
    server = ThreadedHTTPServer((host, PORT), WatchdogHandler)
    print(f"[Watchdog] Weighbridge Recovery Dashboard running on http://0.0.0.0:{PORT}")
    print(f"[Watchdog] Open  http://localhost:{PORT}  in a browser to monitor the system")
    print(f"[Watchdog] Workspace: {WORKSPACE}")
    print(f"[Watchdog] Log dir  : {LOG_DIR}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[Watchdog] Shutting down")
        server.shutdown()


if __name__ == "__main__":
    main()
