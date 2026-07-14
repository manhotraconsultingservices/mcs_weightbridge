"""
Weighbridge Scale Agent v2 — Self-configuring, self-healing serial reader.

Minimal config required: cloud_url + tenant_slug + agent_key.
Port and serial settings (baud, data bits, parity) are AUTO-DETECTED.

Key improvements over v1:
  - Auto-detects correct COM port + serial config at startup
  - Uses ASCII-quality check to reject wrong parity/data-bits (the root cause
    of "2.0 kg" readings — 7E1 data received as 8N1 looks like garbage)
  - Protocol-aware frame parser (prefix → zero-padded → first number, NOT max())
  - After 5 consecutive port failures, clears saved config and re-scans
  - Status server auto-picks an available port (9002 → 9003 → 9004) so Tally
    on 9002 never blocks the status page
  - --detect flag for one-shot auto-detection without starting the agent

Usage:
  python scale_agent.py                   # run agent
  python scale_agent.py --setup           # configure cloud credentials
  python scale_agent.py --detect          # detect port/baud and print, then exit
  python scale_agent.py --install         # install as Windows service (needs NSSM)
  python scale_agent.py --debug           # verbose frame logging
"""
from __future__ import annotations

import copy
import json
import logging
import os
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

# ── Base directory ────────────────────────────────────────────────────────────
# When frozen (PyInstaller/Nuitka .exe), __file__ resolves to the TEMPORARY
# extraction dir (_MEIPASS), NOT the folder the .exe lives in. Anchoring config
# + logs to __file__ then makes the frozen agent read a STALE bundled
# scale_config.json (wrong tenant) and write logs into a temp dir that vanishes.
# Use the executable's own folder when frozen so it reads the scale_config.json
# sitting next to the .exe and writes a visible log there.
# getattr(sys,"frozen") covers PyInstaller; "__compiled__" in globals() covers Nuitka.
if getattr(sys, "frozen", False) or "__compiled__" in globals():
    BASE_DIR = Path(sys.executable).resolve().parent   # folder the .exe lives in
else:
    BASE_DIR = Path(__file__).resolve().parent

# ── TLS CA bundle (frozen-EXE insurance) ──────────────────────────────────────
# A PyInstaller/Nuitka build can lose the OS default CA path, so requests/urllib3
# raise SSLError on the HTTPS push. If certifi is bundled, point the standard env
# vars at its CA bundle — but only when UNSET, so a real system / corporate CA
# bundle configured on the host still wins.
try:
    import certifi as _certifi
    _ca = _certifi.where()
    if _ca and os.path.exists(_ca):
        os.environ.setdefault("SSL_CERT_FILE", _ca)
        os.environ.setdefault("REQUESTS_CA_BUNDLE", _ca)
except Exception:
    pass

# ── Logging ───────────────────────────────────────────────────────────────────

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "scale_agent.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("scale_agent")

# ── Product / tuning constants ────────────────────────────────────────────────
PRODUCT_DOMAIN      = "weighbridgesetu.com"    # apex; per-tenant pushes go to <slug>.<PRODUCT_DOMAIN>
SERVICE_NAME        = "WeighbridgeScaleAgent"  # Windows service name (install/uninstall)
DEFAULT_STATUS_PORT = 9002                     # local status/Discovery UI; auto-increments if busy

MAX_WEIGHT_KG        = 200_000.0   # reject parses above this (implausible for a weighbridge)
ASCII_QUALITY_MIN    = 0.65        # below this = wrong parity/data-bits (garbage) → reject
ASCII_QUALITY_STRONG = 0.80        # clean enough to accept a port even before a weight parses
ASCII_QUALITY_PEEK   = 0.70        # Discovery /peek "looks good" threshold

MAX_JUMP_KG          = 5000.0      # >5 MT change in <JUMP_WINDOW_SEC is physically impossible
JUMP_WINDOW_SEC      = 2.0

SCALE_RETRY_SEC          = 30      # wait after "scale not found" before re-scanning
MAX_CONSECUTIVE_FAILURES = 5       # after N port failures: clear saved config + full re-scan
RECONNECT_BASE_SEC       = 5       # port-error backoff start
RECONNECT_MAX_SEC        = 60      # port-error backoff cap

# ── Config ────────────────────────────────────────────────────────────────────

CONFIG_FILE = BASE_DIR / "scale_config.json"

# Minimal config — serial params are filled in by auto-detection and saved.
DEFAULT_CONFIG: dict = {
    "cloud_url": f"https://{PRODUCT_DOMAIN}",
    "tenant_slug": "",
    "agent_key": "",
    # Serial — leave blank/zero; auto-detected and saved on first run.
    "port": "",
    "baud_rate": 0,
    "data_bits": 0,
    "parity": "",
    "stop_bits": 1,
    # Push rate (ms between cloud posts).
    "push_interval_ms": 500,
    # Calibration offset in kg (applied before push).
    # If indicator shows 12500 but app shows 12550 → set -50.
    "calibration_offset_kg": 0.0,
    # Log raw serial frames at DEBUG level (helps diagnose format issues).
    "log_raw_frames": False,
    # Status API preferred port; auto-increments if busy (Tally uses 9002).
    "status_port": DEFAULT_STATUS_PORT,
}

# ── Serial configs tried during auto-detection ────────────────────────────────
# Priority order: most common Indian weighbridge configs first.
# (baud_rate, data_bits, parity, stop_bits)
PROBE_CONFIGS = [
    (9600,  7, "E", 1),   # Essae DS-410 / DS-852, Leo FSD-501, most Indian brands (7E1)
    (9600,  8, "N", 1),   # International / generic (8N1)
    (4800,  7, "E", 1),   # Older Essae / MDS models
    (4800,  8, "N", 1),   # Older generic
    (2400,  7, "E", 1),   # Some older models
    (1200,  7, "E", 1),   # Very old / slow models
    (9600,  8, "E", 1),   # Some Avery/Fairbanks variants
    (19200, 8, "N", 1),   # Some newer DIGI / A&D models
    (9600,  7, "O", 1),   # Odd parity (rare)
]

# ── Frame parser ──────────────────────────────────────────────────────────────

def _ascii_quality(data: bytes) -> float:
    """Fraction of bytes that are printable ASCII (including CR/LF/TAB).

    With correct 7E1 config, bytes are clean ASCII (quality ≈ 0.90+).
    With wrong config (8N1 receiving 7E1), the parity bit is treated as a
    data bit — half the characters get their high bit set, becoming non-ASCII
    garbage.  Quality drops below 0.65, which we use as a rejection signal.
    This is the key test that catches the "2.0 kg" wrong-config bug.
    """
    if not data:
        return 0.0
    ok = sum(1 for b in data if 0x20 <= b <= 0x7E or b in (0x09, 0x0A, 0x0D))
    return ok / len(data)


def parse_weight(text: str) -> float | None:
    """Extract weight (kg) from one decoded indicator frame.

    Protocol hierarchy (most → least specific):
      1. Prefix-based  — "ST 012500", "NT +12500.00", "S 012500.00"
      2. Zero-padded 6-digit — "012500" (Essae, Avery 6-digit display)
      3. First plausible 4+-digit number in the frame

    Deliberately does NOT use max() — multi-field frames (display + tare)
    would cause max() to pick the wrong (larger) value.
    """
    text = text.strip()
    if not text:
        return None

    # 1. Prefix-based: "ST 012500", "NT +12500.50", "S 012500", "UT 12500"
    m = re.search(r'\b(?:ST|NT|UT|GS|G|S|N)\s+([+-]?\d{1,7}(?:\.\d{1,3})?)', text)
    if m:
        try:
            w = abs(float(m.group(1)))
            if 0.0 <= w < MAX_WEIGHT_KG:
                return w
        except ValueError:
            pass

    # 2. Zero-padded 6-or-7 digit block (leading zeros, common on 6-digit displays)
    m = re.search(r'(?<!\d)(0\d{4,6})(?!\d)', text)
    if m:
        try:
            w = float(m.group(1))
            if 0.0 <= w < MAX_WEIGHT_KG:
                return w
        except ValueError:
            pass

    # 3. First plausible standalone number with 4+ digits (avoids "2" noise)
    for match in re.finditer(r'(?<!\d)([+-]?\d{4,6}(?:\.\d{1,3})?)(?!\d)', text):
        try:
            w = abs(float(match.group(1)))
            if 0.0 <= w < MAX_WEIGHT_KG:
                return w
        except ValueError:
            pass

    # 4. Fallback: any 2+-digit number in valid weighbridge range (catches sub-1000 kg
    #    readings). Requires ≥2 digits so a lone stray digit ("2") is NOT read as 2.0 kg.
    for match in re.finditer(r'(?<!\d)(\d{2,6}(?:\.\d{1,3})?)(?!\d)', text):
        try:
            w = float(match.group(1))
            if 0.0 <= w < MAX_WEIGHT_KG:
                return w
        except ValueError:
            pass

    return None


# ── Auto-detection ────────────────────────────────────────────────────────────

def _probe_port(port: str, baud: int, data_bits: int, parity: str, stop_bits: int,
                probe_sec: float = 2.5) -> tuple[bool, float | None]:
    """Open a COM port with specific settings and check for valid weight data.

    Returns (success, weight_or_None).
    Rejects configs where received bytes fail the ASCII quality check
    (indicates wrong data_bits/parity — the most common misconfiguration).
    """
    try:
        import serial
        bsz = {7: serial.SEVENBITS, 8: serial.EIGHTBITS}.get(data_bits, serial.EIGHTBITS)
        par = {"N": serial.PARITY_NONE, "E": serial.PARITY_EVEN,
               "O": serial.PARITY_ODD}.get(parity, serial.PARITY_NONE)

        ser = serial.Serial(port=port, baudrate=baud, bytesize=bsz, parity=par,
                            stopbits={1: serial.STOPBITS_ONE, 2: serial.STOPBITS_TWO}.get(stop_bits, serial.STOPBITS_ONE),
                            timeout=0.3)
        ser.dtr = True
        ser.rts = True
        ser.reset_input_buffer()

        raw = b""
        deadline = time.time() + probe_sec
        while time.time() < deadline:
            chunk = ser.read(128)
            if chunk:
                raw += chunk
            time.sleep(0.05)
        ser.close()

        if len(raw) < 4:
            # Port opened but indicator sent nothing (wrong port or indicator off)
            return False, None

        quality = _ascii_quality(raw)
        if quality < ASCII_QUALITY_MIN:
            # Non-ASCII garbage → wrong serial config
            log.debug("  ✗ %s %d %d%s%d  ASCII=%.0f%% (wrong config)",
                      port, baud, data_bits, parity, stop_bits, quality * 100)
            return False, None

        # Try to parse a weight from any line in the received data
        text = raw.decode("ascii", errors="replace")
        for line in re.split(r'[\r\n]+', text):
            w = parse_weight(line)
            if w is not None:
                log.info("  ✓ %s  %d  %d%s%d  → %.1f kg  (ASCII %.0f%%)",
                         port, baud, data_bits, parity, stop_bits, w, quality * 100)
                return True, w

        # Good ASCII but no weight yet (scale unstable / in error mode) — still valid
        if quality > ASCII_QUALITY_STRONG:
            log.info("  ✓ %s  %d  %d%s%d  → ASCII OK, weight not stable yet",
                     port, baud, data_bits, parity, stop_bits)
            return True, None

        return False, None

    except Exception as e:
        log.debug("  ✗ %s %d %d%s%d  %s", port, baud, data_bits, parity, stop_bits, e)
        return False, None


def auto_detect_scale() -> dict | None:
    """Scan all COM ports × PROBE_CONFIGS to find the weighbridge indicator.

    Returns a dict with port, baud_rate, data_bits, parity, stop_bits,
    or None if not found.  Result is saved to scale_config.json for fast restart.
    """
    try:
        import serial.tools.list_ports
        ports = sorted(p.device for p in serial.tools.list_ports.comports())
    except ImportError:
        log.error("pyserial not installed — run: pip install pyserial")
        return None

    if not ports:
        log.warning("No COM ports found. Connect the USB-serial cable and retry.")
        return None

    log.info("Scanning %d port(s): %s", len(ports), ", ".join(ports))
    log.info("Will try %d serial configs per port ...", len(PROBE_CONFIGS))

    for port in ports:
        for baud, data_bits, parity, stop_bits in PROBE_CONFIGS:
            ok, weight = _probe_port(port, baud, data_bits, parity, stop_bits)
            if ok:
                cfg = {"port": port, "baud_rate": baud, "data_bits": data_bits,
                       "parity": parity, "stop_bits": stop_bits}
                log.info("Scale FOUND: %s @ %d baud  %d%s%d  weight=%.1f kg",
                         port, baud, data_bits, parity, stop_bits,
                         weight if weight is not None else 0.0)
                return cfg

    log.error("Scale NOT FOUND. Check: (1) USB cable connected, (2) indicator powered on, "
              "(3) USB-serial driver (CH340/FTDI) installed in Device Manager.")
    return None


def _port_exists(port: str) -> bool:
    """True if `port` is currently enumerated. After a USB replug COMx renumbers,
    so a saved port can vanish — used to skip straight to re-detection."""
    try:
        import serial.tools.list_ports
        return any(p.device == port for p in serial.tools.list_ports.comports())
    except Exception:
        return True  # can't tell → assume present, let open() decide


def _peek_port(port: str, probe_sec: float = 1.0) -> dict:
    """Open `port` across the standard serial configs and report exactly what
    bytes arrive — raw ASCII + hex + a quality score — so a technician can SEE
    clean feed vs garbage during Discovery. Stops at the first config that yields
    a parseable weight. Returns {"port", "results":[...]}.
    """
    import serial as _ser
    import time as _t
    results = []
    for baud, dbits, parity, sbits in PROBE_CONFIGS:
        cfg_label = f"{baud} {dbits}{parity}{sbits}"
        try:
            bsz = {7: _ser.SEVENBITS, 8: _ser.EIGHTBITS}.get(dbits, _ser.EIGHTBITS)
            par = {"N": _ser.PARITY_NONE, "E": _ser.PARITY_EVEN,
                   "O": _ser.PARITY_ODD}.get(parity, _ser.PARITY_NONE)
            ser = _ser.Serial(port=port, baudrate=baud, bytesize=bsz, parity=par,
                              stopbits={1: _ser.STOPBITS_ONE, 2: _ser.STOPBITS_TWO}.get(sbits, _ser.STOPBITS_ONE),
                              timeout=0.3)
            ser.dtr = True
            ser.rts = True
            data = b""
            deadline = _t.time() + probe_sec
            while _t.time() < deadline and len(data) < 400:
                chunk = ser.read(256)
                if chunk:
                    data += chunk
            ser.close()
            ascii_preview = data.decode("ascii", errors="replace")[:200]
            q = round(_ascii_quality(data), 2) if data else 0.0
            weight = parse_weight(ascii_preview) if q > ASCII_QUALITY_PEEK else None
            results.append({
                "config": cfg_label, "bytes": len(data), "ascii_quality": q,
                "raw_ascii": ascii_preview, "raw_hex": data[:80].hex(" "),
                "weight": weight, "looks_good": bool(q > ASCII_QUALITY_PEEK and weight is not None),
            })
            if q > ASCII_QUALITY_PEEK and weight is not None:
                break  # clean config found — no need to keep trying
        except Exception as exc:
            msg = str(exc)
            results.append({"config": cfg_label, "error": msg[:140]})
            if "access" in msg.lower() or "denied" in msg.lower():
                break  # port is held by another program — stop probing it
    return {"port": port, "results": results}


# ── CH340 USB-serial auto-recovery ────────────────────────────────────────────

def _try_reset_ch340(port: str) -> bool:
    """Cycle the CH340 device via Windows PnP to recover from Error 31
    ('A device attached to the system is not functioning') — no unplugging needed.
    """
    import subprocess
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             f"Get-PnpDevice | Where-Object {{ $_.FriendlyName -like '*({port})*' }} | "
             "Select-Object -ExpandProperty InstanceId"],
            capture_output=True, text=True, timeout=10,
        )
        lines = result.stdout.strip().splitlines()
        if not lines:
            return False
        iid = lines[0].strip()
        subprocess.run(["powershell", "-Command",
                        f"Disable-PnpDevice -InstanceId '{iid}' -Confirm:$false"],
                       capture_output=True, text=True, timeout=10)
        time.sleep(3)
        subprocess.run(["powershell", "-Command",
                        f"Enable-PnpDevice -InstanceId '{iid}' -Confirm:$false"],
                       capture_output=True, text=True, timeout=10)
        time.sleep(2)
        log.info("CH340 PnP reset complete for %s", port)
        return True
    except Exception as exc:
        log.warning("CH340 reset failed: %s", exc)
        return False


# ── Scale Reader ──────────────────────────────────────────────────────────────

class ScaleReader:
    """Reads weight from serial port and pushes to cloud.

    On port failure: CH340 PnP reset → if still failing after 5 attempts,
    clears saved serial config and triggers a full re-scan of all ports.
    """

    def __init__(self, config: dict):
        self.cfg = config
        self.running = False
        self.connected = False
        self.last_weight: float = -1.0          # -1.0 = never read
        self.last_raw_frame: str = ""
        self.detected_port: str = config.get("port", "")
        self.detected_config: dict = {}
        self.cloud_online: bool = True
        self.push_count: int = 0
        self.error_count: int = 0
        self._thread: threading.Thread | None = None
        self._last_push_time: float = 0.0

    def start(self):
        self.running = True
        self._thread = threading.Thread(target=self._read_loop, daemon=True, name="scale-read")
        self._thread.start()

    def stop(self):
        self.running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _resolve_serial_cfg(self) -> dict | None:
        """Return serial config.  If already saved in config file, use it.
        Otherwise auto-detect and save to disk for faster next restart.
        """
        port  = self.cfg.get("port", "")
        baud  = self.cfg.get("baud_rate", 0)
        dbits = self.cfg.get("data_bits", 0)
        par   = self.cfg.get("parity", "")
        if port and baud and dbits and par:
            # USB replug renumbers COMx — if the saved port has vanished, skip it
            # and re-detect instead of looping on a dead port.
            if _port_exists(port):
                log.info("Using saved serial config: %s @ %d  %d%s%d",
                         port, baud, dbits, par, self.cfg.get("stop_bits", 1))
                return {"port": port, "baud_rate": baud, "data_bits": dbits,
                        "parity": par, "stop_bits": self.cfg.get("stop_bits", 1)}
            log.warning("Saved port %s no longer present (USB replug?) — re-detecting", port)

        log.info("No serial config saved — starting auto-detection ...")
        found = auto_detect_scale()
        if found:
            self.cfg.update(found)
            try:
                save_config(self.cfg)
            except Exception:
                pass
        return found

    def _clear_serial_cfg(self):
        """Wipe saved serial config so next iteration triggers a fresh scan."""
        self.cfg["port"] = ""
        self.cfg["baud_rate"] = 0
        self.cfg["data_bits"] = 0
        self.cfg["parity"] = ""

    def _read_loop(self):
        import queue as _q
        import serial
        import requests

        bsz_map = {7: serial.SEVENBITS, 8: serial.EIGHTBITS}
        par_map  = {"N": serial.PARITY_NONE, "E": serial.PARITY_EVEN, "O": serial.PARITY_ODD}
        sbits_map = {1: serial.STOPBITS_ONE, 2: serial.STOPBITS_TWO}

        api_url = f"{_effective_push_base(self.cfg.get('cloud_url', ''), self.cfg.get('tenant_slug', ''))}/api/v1/weight/external-reading"

        # ── Non-blocking HTTP push queue ───────────────────────────────────
        # A live weight gauge only cares about the LATEST value, so the queue is
        # latest-biased: on overflow drop the OLDEST (not the newest), and the
        # sender COALESCES a backlog down to the freshest reading before POSTing.
        # Without this, a slow network makes the worker stream a backlog of stale
        # readings one-by-one and the on-screen weight runs seconds behind.
        push_q: _q.Queue = _q.Queue(maxsize=20)
        _session = requests.Session()   # keep-alive: skip a TLS handshake per POST

        def _enqueue(payload: dict) -> None:
            try:
                push_q.put_nowait(payload)
            except _q.Full:
                try:
                    push_q.get_nowait()        # drop the stalest, keep the freshest
                except _q.Empty:
                    pass
                try:
                    push_q.put_nowait(payload)
                except _q.Full:
                    pass

        def _push_worker():
            while self.running or not push_q.empty():
                try:
                    payload = push_q.get(timeout=2)
                except _q.Empty:
                    continue
                # Coalesce: if readings piled up while a slow POST was in flight,
                # skip straight to the newest and discard the stale backlog. Keeps
                # the on-screen weight ~1 round-trip behind the scale, not seconds.
                try:
                    while True:
                        payload = push_q.get_nowait()
                except _q.Empty:
                    pass
                try:
                    resp = _session.post(api_url, json=payload, timeout=5)
                    if resp.status_code == 403:
                        self.error_count += 1
                        self.cloud_online = False
                        if self.error_count % 20 == 1:   # throttle: don't flood the log on a bad key
                            log.error("AGENT KEY REJECTED (403) — fix agent_key in scale_config.json "
                                      "(tenant: %s)", payload.get("tenant"))
                    elif not resp.ok:
                        self.error_count += 1
                        self.cloud_online = False
                        if self.error_count % 20 == 1:
                            log.warning("Server error %d (push #%d): %s",
                                        resp.status_code, self.error_count, resp.text[:200])
                    else:
                        self.push_count += 1
                        if not self.cloud_online:
                            log.info("Cloud connection restored")
                        self.cloud_online = True
                except requests.RequestException as exc:
                    self.error_count += 1
                    self.cloud_online = False
                    if self.error_count % 50 == 1:
                        log.warning("Cloud unreachable (push #%d): %s", self.error_count, exc)

        threading.Thread(target=_push_worker, daemon=True, name="scale-push").start()

        # ── Main reconnect loop ────────────────────────────────────────────
        consecutive_failures = 0
        reconnect_delay = RECONNECT_BASE_SEC

        while self.running:
            serial_cfg = self._resolve_serial_cfg()
            if serial_cfg is None:
                log.warning("Scale not found — waiting %d s before retrying ...", SCALE_RETRY_SEC)
                time.sleep(SCALE_RETRY_SEC)
                continue

            port   = serial_cfg["port"]
            baud   = serial_cfg["baud_rate"]
            dbits  = serial_cfg["data_bits"]
            parstr = serial_cfg["parity"]
            sbits  = serial_cfg.get("stop_bits", 1)
            self.detected_port   = port
            self.detected_config = serial_cfg

            push_interval = self.cfg.get("push_interval_ms", 500) / 1000.0
            calibration   = float(self.cfg.get("calibration_offset_kg", 0.0))
            log_raw       = bool(self.cfg.get("log_raw_frames", False))

            ser = None
            buffer = b""
            try:
                log.info("Opening %s  %d baud  %d%s%d ...", port, baud, dbits, parstr, sbits)
                ser = serial.Serial(
                    port=port, baudrate=baud,
                    bytesize=bsz_map.get(dbits, serial.EIGHTBITS),
                    parity=par_map.get(parstr, serial.PARITY_NONE),
                    stopbits=sbits_map.get(sbits, serial.STOPBITS_ONE),
                    timeout=2,
                )
                ser.dtr = True
                ser.rts = True
                ser.reset_input_buffer()
                self.connected = True
                consecutive_failures = 0
                reconnect_delay = RECONNECT_BASE_SEC
                last_weight_time = 0.0
                log.info("Scale connected on %s", port)

                while self.running:
                    chunk = ser.read(ser.in_waiting or 1)
                    if not chunk:
                        continue
                    buffer += chunk

                    # ── CR/LF-delimited frames ─────────────────────────────
                    while True:
                        cr = buffer.find(b'\r')
                        lf = buffer.find(b'\n')
                        candidates = [p for p in (cr, lf) if p >= 0]
                        if not candidates:
                            break
                        delim = min(candidates)
                        frame = buffer[:delim]
                        rest  = buffer[delim + 1:]
                        if rest and rest[0:1] == b'\n':
                            rest = rest[1:]
                        buffer = rest

                        # Strip STX and other control bytes
                        clean = bytes(b for b in frame if b >= 0x20)
                        if not clean:
                            continue

                        raw_str = clean.decode("ascii", errors="replace")
                        self.last_raw_frame = raw_str
                        if log_raw:
                            log.debug("RAW: %r", raw_str)

                        weight = parse_weight(raw_str)
                        if weight is None:
                            continue

                        now = time.time()
                        # Plausibility guard: >5 MT jump in <2 s is physically impossible
                        if (self.last_weight >= 0.0 and
                                abs(weight - self.last_weight) > MAX_JUMP_KG and
                                now - last_weight_time < JUMP_WINDOW_SEC):
                            log.debug("Rejected implausible jump %.1f→%.1f kg", self.last_weight, weight)
                            continue

                        if calibration:
                            weight += calibration

                        if (abs(weight - self.last_weight) >= 1.0 or
                                now - self._last_push_time >= push_interval):
                            self.last_weight    = weight
                            self._last_push_time = now
                            last_weight_time    = now
                            _enqueue({
                                "weight_kg": weight,
                                "tenant":    self.cfg["tenant_slug"],
                                "agent_key": self.cfg["agent_key"],
                                "raw": raw_str,
                            })

                    # ── Delimiter-free fallback (Leo FSD-501 continuous) ───
                    if len(buffer) >= 16:
                        clean = bytes(b for b in buffer if b >= 0x20)
                        raw_str = clean.decode("ascii", errors="replace")
                        self.last_raw_frame = raw_str
                        weight = parse_weight(raw_str)
                        if weight is not None:
                            if calibration:
                                weight += calibration
                            now = time.time()
                            if (abs(weight - self.last_weight) >= 1.0 or
                                    now - self._last_push_time >= push_interval):
                                self.last_weight    = weight
                                self._last_push_time = now
                                _enqueue({
                                    "weight_kg": weight,
                                    "tenant":    self.cfg["tenant_slug"],
                                    "agent_key": self.cfg["agent_key"],
                                    "raw": raw_str,
                                })
                        buffer = buffer[-16:]

                    # Overflow guard
                    if len(buffer) > 4096:
                        buffer = buffer[-256:]

            except Exception as exc:
                self.connected = False
                exc_str = str(exc)
                consecutive_failures += 1
                log.warning("Port error on %s (failure #%d): %s", port, consecutive_failures, exc)

                # CH340 Error 31 auto-recovery
                if "31" in exc_str and "functioning" in exc_str.lower():
                    log.warning("CH340 Error 31 on %s — attempting PnP reset", port)
                    if _try_reset_ch340(port):
                        consecutive_failures = 0
                        reconnect_delay = RECONNECT_BASE_SEC
                        time.sleep(3)
                        continue

                # After 5 consecutive failures, wipe saved config and re-scan all ports.
                # This handles: port number changed (COM3→COM5 after reconnect),
                # device physically moved to different port, wrong config saved.
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    log.warning("%d consecutive failures on %s — clearing config, re-scanning all ports",
                                MAX_CONSECUTIVE_FAILURES, port)
                    self._clear_serial_cfg()
                    consecutive_failures = 0
                    reconnect_delay = RECONNECT_BASE_SEC
                else:
                    time.sleep(reconnect_delay)
                    reconnect_delay = min(reconnect_delay * 2, RECONNECT_MAX_SEC)

            finally:
                if ser is not None:
                    try:
                        ser.close()
                    except Exception:
                        pass


# ── Status Server ─────────────────────────────────────────────────────────────

# ── Discovery UI (served by StatusServer at /) ────────────────────────────────

DISCOVERY_HTML = r"""<!doctype html><html><head><meta charset="utf-8">
<title>Weighbridge Scale - Discovery</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
 body{font-family:system-ui,'Segoe UI',Arial;margin:0;background:#0f172a;color:#e2e8f0}
 .wrap{max-width:780px;margin:0 auto;padding:16px}
 h1{font-size:18px;margin:6px 0 2px}.sub{color:#94a3b8;font-size:12px;margin-bottom:14px}
 .card{background:#1e293b;border:1px solid #334155;border-radius:12px;padding:16px;margin-bottom:14px}
 .wt{font-size:64px;font-weight:800;font-variant-numeric:tabular-nums;line-height:1}
 .unit{font-size:20px;color:#94a3b8;margin-left:8px}
 .badges{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
 .b{font-size:12px;font-weight:700;padding:4px 10px;border-radius:999px;border:1px solid}
 .ok{background:#064e3b;border-color:#10b981;color:#a7f3d0}
 .bad{background:#450a0a;border-color:#ef4444;color:#fecaca}
 .warn{background:#451a03;border-color:#f59e0b;color:#fde68a}
 .lbl{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:#94a3b8}
 .mono{font-family:Consolas,monospace;font-size:13px;background:#0b1220;border:1px solid #334155;border-radius:8px;padding:10px;white-space:pre-wrap;word-break:break-all;min-height:18px}
 table{width:100%;border-collapse:collapse;font-size:13px}
 td,th{text-align:left;padding:7px 8px;border-bottom:1px solid #334155}
 button{background:#2563eb;color:#fff;border:0;border-radius:8px;padding:7px 12px;font-weight:600;cursor:pointer}
 button.sec{background:#334155}
</style></head><body><div class="wrap">
 <h1>Weighbridge Scale - Discovery</h1>
 <div class="sub">Local agent diagnostics - this page stays on this PC. Use it to confirm the port is reading clean weight before/after install.</div>
 <div class="card"><div class="lbl">Live weight</div>
  <div><span class="wt" id="wt">- . -</span><span class="unit">kg</span></div>
  <div class="badges" id="badges"></div></div>
 <div class="card"><div class="lbl">Raw frame from the indicator (what the port is reading)</div>
  <div class="mono" id="raw">(waiting for data...)</div>
  <div class="sub" id="cfgline" style="margin-top:8px"></div></div>
 <div class="card">
  <div style="display:flex;justify-content:space-between;align-items:center">
   <div class="lbl">COM ports on this PC</div>
   <button class="sec" onclick="rescan()">Force re-scan</button></div>
  <table id="ports"><tbody></tbody></table>
  <div class="mono" id="peekout" style="display:none;margin-top:10px"></div></div>
</div><script>
async function poll(){try{const s=await(await fetch('/status')).json();
 const w=Number(s.last_weight_kg);
 document.getElementById('wt').textContent=(w>=0?w.toLocaleString('en-IN',{maximumFractionDigits:1}):'- . -');
 document.getElementById('raw').textContent=s.last_raw_frame||'(no frame yet)';
 const c=s.detected_config||{};
 document.getElementById('cfgline').textContent=s.detected_port?('Locked on '+s.detected_port+'  '+(c.baud_rate||'')+' baud  '+(c.data_bits||'')+(c.parity||'')+(c.stop_bits||'')):'Not locked on a port yet';
 const b=[];b.push(s.scale_connected?'<span class="b ok">SCALE CONNECTED</span>':'<span class="b bad">SCALE NOT FOUND</span>');
 b.push(s.cloud_online?'<span class="b ok">CLOUD ONLINE</span>':'<span class="b warn">CLOUD OFFLINE</span>');
 b.push('<span class="b '+(s.push_count>0?'ok':'warn')+'">PUSHED '+s.push_count+'</span>');
 document.getElementById('badges').innerHTML=b.join('');
 }catch(e){document.getElementById('badges').innerHTML='<span class="b bad">agent not reachable</span>';}}
async function loadPorts(){try{const d=await(await fetch('/ports')).json();
 const rows=(d.ports||[]).map(p=>'<tr><td><b>'+p.port+'</b></td><td>'+(p.description||'')+'</td><td>'+(p.in_use?'<span class="b warn">in use by agent</span>':'')+'</td><td style="text-align:right"><button onclick="peek(\''+p.port+'\')">Peek</button></td></tr>').join('');
 document.querySelector('#ports tbody').innerHTML=rows||'<tr><td colspan=4>No COM ports found - check the USB cable / driver.</td></tr>';
 }catch(e){}}
async function peek(port){const out=document.getElementById('peekout');out.style.display='block';
 out.textContent='Peeking '+port+' ... (a few seconds; close any terminal using it first)';
 try{const d=await(await fetch('/peek?port='+encodeURIComponent(port))).json();
  if(d.note){out.textContent=port+': '+d.note+'\n'+(d.raw_ascii||'');return;}
  out.textContent=(d.results||[]).map(r=>r.error?(r.config+': ERROR '+r.error):(r.config+': '+r.bytes+' bytes  ascii='+r.ascii_quality+'  weight='+(r.weight==null?'-':r.weight)+(r.looks_good?'   <-- LOOKS GOOD':'')+'\n   '+r.raw_ascii)).join('\n\n')||'(no data on this port)';
 }catch(e){out.textContent='peek failed: '+e;}}
async function rescan(){try{await fetch('/rescan');}catch(e){}}
poll();loadPorts();setInterval(poll,700);setInterval(loadPorts,5000);
</script></body></html>"""


def _list_ports(reader) -> dict:
    try:
        import serial.tools.list_ports
        held = reader.detected_port if getattr(reader, "connected", False) else None
        return {"ports": [
            {"port": p.device, "description": (p.description or ""), "in_use": (p.device == held)}
            for p in serial.tools.list_ports.comports()
        ]}
    except Exception as exc:
        return {"ports": [], "error": str(exc)}


def _peek_for_ui(reader, port: str) -> dict:
    if not port:
        return {"note": "no port specified"}
    # Can't double-open a port the agent is actively reading — show its frame.
    if getattr(reader, "connected", False) and reader.detected_port == port:
        return {"note": "this port is live in the agent - showing its current frame",
                "raw_ascii": reader.last_raw_frame or ""}
    return _peek_port(port)


class StatusServer:
    """Local HTTP diagnostic API + Discovery UI at http://127.0.0.1:{port}.
    Auto-picks the first available port starting from preferred_port,
    so Tally on 9002 never blocks this service.
    """

    def __init__(self, reader: ScaleReader, preferred_port: int = DEFAULT_STATUS_PORT):
        self.reader = reader
        self.port   = self._find_free_port(preferred_port)

    @staticmethod
    def _find_free_port(start: int) -> int:
        import socket
        for p in range(start, start + 5):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.bind(("127.0.0.1", p))
                s.close()
                return p
            except OSError:
                continue
        log.warning("Ports %d–%d all busy; status server may fail to bind", start, start + 4)
        return start

    def start(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from urllib.parse import urlparse, parse_qs
        reader = self.reader
        port   = self.port

        def _status_dict():
            r = reader
            return {
                "service": "scale_agent_v2", "status": "running",
                "timestamp": datetime.now().isoformat(),
                "scale_connected": r.connected, "detected_port": r.detected_port,
                "detected_config": r.detected_config, "cloud_online": r.cloud_online,
                "last_weight_kg": r.last_weight, "last_raw_frame": r.last_raw_frame,
                "calibration_offset_kg": r.cfg.get("calibration_offset_kg", 0.0),
                "push_count": r.push_count, "error_count": r.error_count,
            }

        class Handler(BaseHTTPRequestHandler):
            def _send(self, code, body, ctype):
                data = body.encode() if isinstance(body, str) else body
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                u = urlparse(self.path)
                p = u.path
                if p in ("/", "/index.html", "/discover"):
                    self._send(200, DISCOVERY_HTML, "text/html; charset=utf-8")
                elif p == "/status":
                    self._send(200, json.dumps(_status_dict(), indent=2), "application/json")
                elif p == "/ports":
                    self._send(200, json.dumps(_list_ports(reader)), "application/json")
                elif p == "/rescan":
                    try:
                        reader._clear_serial_cfg()
                    except Exception:
                        pass
                    self._send(200, json.dumps({"ok": True}), "application/json")
                elif p == "/peek":
                    cp = (parse_qs(u.query).get("port", [""])[0]).strip()
                    self._send(200, json.dumps(_peek_for_ui(reader, cp)), "application/json")
                else:
                    self._send(404, json.dumps({"error": "not found"}), "application/json")

            def log_message(self, *args):
                pass  # suppress HTTP access log noise

        def _serve():
            try:
                ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
            except OSError as exc:
                log.warning("Status server on :%d failed to bind: %s", port, exc)

        threading.Thread(target=_serve, daemon=True, name="status-http").start()
        log.info("Status + Discovery UI: http://127.0.0.1:%d", self.port)


# ── Config helpers ────────────────────────────────────────────────────────────

def _effective_push_base(cloud_url: str, tenant_slug: str) -> str:
    """Base URL the agent POSTs weight readings to.

    The apex weighbridgesetu.com 301-redirects to www, and a 301 turns the POST
    into a GET that DROPS the body — so the reading silently never reaches the
    backend (the agent still sees a 2xx for the redirect and thinks it pushed,
    while the server's /weight/ping stays scale_connected=false). Route to the
    tenant's own subdomain (which does NOT redirect) instead. Custom domains /
    localhost / already-subdomained hosts are left untouched.
    """
    from urllib.parse import urlparse
    base = (cloud_url or "").rstrip("/")
    if base and "://" not in base:
        base = "https://" + base          # tolerate a scheme-less host typed at the wizard
    try:
        parts = urlparse(base)
        host = (parts.hostname or "").lower()
    except Exception:
        return base
    if tenant_slug and host in (PRODUCT_DOMAIN, f"www.{PRODUCT_DOMAIN}"):
        return f"{parts.scheme or 'https'}://{tenant_slug}.{PRODUCT_DOMAIN}"
    return base


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        log.error("Config not found: %s\nRun: python scale_agent.py --setup", CONFIG_FILE)
        sys.exit(1)
    # utf-8-sig strips the BOM that PowerShell 5.1 Out-File adds by default.
    with open(CONFIG_FILE, "r", encoding="utf-8-sig") as fh:
        data = json.load(fh)
    merged = copy.deepcopy(DEFAULT_CONFIG)
    merged.update(data)
    return merged


def save_config(cfg: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
    log.info("Config saved → %s", CONFIG_FILE)


# ── Setup wizard ──────────────────────────────────────────────────────────────

def setup_wizard():
    print("\n" + "=" * 64)
    print("  Weighbridge Scale Agent v2 — Setup")
    print("=" * 64)
    print()
    print("Serial port and baud rate are AUTO-DETECTED at startup.")
    print("You only need to supply the cloud connection details below.")
    print()

    cfg = copy.deepcopy(DEFAULT_CONFIG)

    cfg["cloud_url"]    = input(f"Cloud URL [{cfg['cloud_url']}]: ").strip() or cfg["cloud_url"]
    cfg["tenant_slug"]  = input("Tenant slug (e.g. sss-stone-crusher): ").strip()
    cfg["agent_key"]    = input("Agent API key (from platform admin panel): ").strip()

    print()
    print("Calibration (press Enter to skip):")
    print("  If the indicator display shows a different value than what the")
    print("  app receives, set the difference here:  offset = display − app_reading")
    print("  Example: display shows 12500, app shows 12550 → enter -50")
    cal = input("Calibration offset in kg (+ or −, default 0): ").strip()
    if cal:
        try:
            cfg["calibration_offset_kg"] = float(cal)
        except ValueError:
            print("  Invalid number — keeping 0.")

    raw_log = input("Log raw serial frames for debugging? (y/N): ").strip().lower()
    cfg["log_raw_frames"] = raw_log in ("y", "yes")

    save_config(cfg)
    print(f"\n  Config saved: {CONFIG_FILE}")
    print("  Port + baud will be auto-detected when the agent starts.")
    print(f"\n  Start agent:   python scale_agent.py")
    print(f"  Test detect:   python scale_agent.py --detect")


# ── Windows service ───────────────────────────────────────────────────────────

def install_service():
    import shutil, subprocess
    nssm = shutil.which("nssm")
    if not nssm:
        print("NSSM not found.  Download from https://nssm.cc and add to PATH.")
        sys.exit(1)
    # A frozen .exe IS the program — register it directly (no python + script).
    # Anchor everything to BASE_DIR (the .exe's own folder when frozen) so the
    # service never points at PyInstaller/Nuitka's transient _MEIPASS dir, which
    # is deleted when the installer process exits.
    if getattr(sys, "frozen", False) or "__compiled__" in globals():
        install_cmd = [nssm, "install", SERVICE_NAME, str(Path(sys.executable).resolve())]
    else:
        install_cmd = [nssm, "install", SERVICE_NAME,
                       sys.executable, str((BASE_DIR / "scale_agent.py").resolve())]
    subprocess.run(install_cmd,                                                                    check=True)
    subprocess.run([nssm, "set", SERVICE_NAME, "AppDirectory",   str(BASE_DIR)],                   check=True)
    subprocess.run([nssm, "set", SERVICE_NAME, "AppStdout",      str(LOG_DIR / "stdout.log")],     check=True)
    subprocess.run([nssm, "set", SERVICE_NAME, "AppStderr",      str(LOG_DIR / "stderr.log")],     check=True)
    subprocess.run([nssm, "set", SERVICE_NAME, "AppRotateFiles", "1"],                             check=True)
    subprocess.run([nssm, "set", SERVICE_NAME, "AppRotateOnline","1"],                             check=True)
    subprocess.run([nssm, "set", SERVICE_NAME, "AppRotateBytes", "10485760"],                      check=True)
    print(f"\nService '{SERVICE_NAME}' installed.")
    print(f"Start:     nssm start {SERVICE_NAME}")
    print(f"Status:    nssm status {SERVICE_NAME}")
    print(f"Logs:      {LOG_DIR}")


def uninstall_service():
    import shutil, subprocess
    nssm = shutil.which("nssm")
    if not nssm:
        print("NSSM not found.")
        sys.exit(1)
    subprocess.run([nssm, "stop",   SERVICE_NAME], check=False)
    subprocess.run([nssm, "remove", SERVICE_NAME, "confirm"], check=True)
    print("Service removed.")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    import argparse
    p = argparse.ArgumentParser(description="Weighbridge Scale Agent v2")
    p.add_argument("--setup",     action="store_true", help="Interactive config wizard")
    p.add_argument("--detect",    action="store_true", help="Auto-detect port/baud and exit")
    p.add_argument("--install",   action="store_true", help="Install as Windows service")
    p.add_argument("--uninstall", action="store_true", help="Remove Windows service")
    p.add_argument("--debug",     action="store_true", help="Enable DEBUG log level")
    args = p.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.setup:
        setup_wizard()
        return

    if args.detect:
        result = auto_detect_scale()
        if result:
            print(json.dumps(result, indent=2))
        else:
            print("No scale detected.")
            sys.exit(1)
        return

    if args.install:
        install_service()
        return

    if args.uninstall:
        uninstall_service()
        return

    cfg = load_config()
    if not cfg.get("tenant_slug") or not cfg.get("agent_key"):
        log.error("tenant_slug and agent_key are required.\nRun: python scale_agent.py --setup")
        sys.exit(1)

    log.info("Weighbridge Scale Agent v2 starting ...")
    log.info("  Cloud:  %s", cfg["cloud_url"])
    log.info("  Tenant: %s", cfg["tenant_slug"])
    if cfg.get("port"):
        log.info("  Saved port: %s  (will verify on connect)", cfg["port"])
    else:
        log.info("  Port: auto-detect (first run or after port change)")

    reader = ScaleReader(cfg)
    status = StatusServer(reader, preferred_port=cfg.get("status_port", DEFAULT_STATUS_PORT))
    status.start()
    reader.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("Shutting down ...")
        reader.stop()


if __name__ == "__main__":
    main()
