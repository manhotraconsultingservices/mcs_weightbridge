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
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

# ── Logging ───────────────────────────────────────────────────────────────────

LOG_DIR = Path(__file__).parent / "logs"
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

# ── Config ────────────────────────────────────────────────────────────────────

CONFIG_FILE = Path(__file__).parent / "scale_config.json"

# Minimal config — serial params are filled in by auto-detection and saved.
DEFAULT_CONFIG: dict = {
    "cloud_url": "https://weighbridgesetu.com",
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
    "status_port": 9002,
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
            if 0.0 <= w < 200_000.0:
                return w
        except ValueError:
            pass

    # 2. Zero-padded 6-or-7 digit block (leading zeros, common on 6-digit displays)
    m = re.search(r'(?<!\d)(0\d{4,6})(?!\d)', text)
    if m:
        try:
            w = float(m.group(1))
            if 0.0 <= w < 200_000.0:
                return w
        except ValueError:
            pass

    # 3. First plausible standalone number with 4+ digits (avoids "2" noise)
    for match in re.finditer(r'(?<!\d)([+-]?\d{4,6}(?:\.\d{1,3})?)(?!\d)', text):
        try:
            w = abs(float(match.group(1)))
            if 0.0 <= w < 200_000.0:
                return w
        except ValueError:
            pass

    # 4. Fallback: any number in valid weighbridge range (catches sub-1000 kg readings)
    for match in re.finditer(r'(?<!\d)(\d{1,6}(?:\.\d{1,3})?)(?!\d)', text):
        try:
            w = float(match.group(1))
            if 0.0 <= w < 200_000.0:
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
                            stopbits=serial.STOPBITS_ONE, timeout=0.3)
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
        if quality < 0.65:
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
        if quality > 0.80:
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
            log.info("Using saved serial config: %s @ %d  %d%s%d",
                     port, baud, dbits, par, self.cfg.get("stop_bits", 1))
            return {"port": port, "baud_rate": baud, "data_bits": dbits,
                    "parity": par, "stop_bits": self.cfg.get("stop_bits", 1)}

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

        api_url = f"{self.cfg['cloud_url'].rstrip('/')}/api/v1/weight/external-reading"

        # ── Non-blocking HTTP push queue ───────────────────────────────────
        push_q: _q.Queue = _q.Queue(maxsize=20)

        def _push_worker():
            while self.running or not push_q.empty():
                try:
                    payload = push_q.get(timeout=2)
                except _q.Empty:
                    continue
                try:
                    resp = requests.post(api_url, json=payload, timeout=5)
                    if resp.status_code == 403:
                        self.error_count += 1
                        self.cloud_online = False
                        log.error("AGENT KEY REJECTED (403) — edit agent_key in scale_config.json."
                                  "  Tenant: %s", payload.get("tenant"))
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
        reconnect_delay = 5

        while self.running:
            serial_cfg = self._resolve_serial_cfg()
            if serial_cfg is None:
                log.warning("Scale not found — waiting 30 s before retrying ...")
                time.sleep(30)
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
                    stopbits=serial.STOPBITS_ONE,
                    timeout=2,
                )
                ser.dtr = True
                ser.rts = True
                ser.reset_input_buffer()
                self.connected = True
                consecutive_failures = 0
                reconnect_delay = 5
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
                                abs(weight - self.last_weight) > 5000.0 and
                                now - last_weight_time < 2.0):
                            log.debug("Rejected implausible jump %.1f→%.1f kg", self.last_weight, weight)
                            continue

                        if calibration:
                            weight += calibration

                        if (abs(weight - self.last_weight) >= 1.0 or
                                now - self._last_push_time >= push_interval):
                            self.last_weight    = weight
                            self._last_push_time = now
                            last_weight_time    = now
                            try:
                                push_q.put_nowait({
                                    "weight_kg": weight,
                                    "tenant":    self.cfg["tenant_slug"],
                                    "agent_key": self.cfg["agent_key"],
                                    "raw": raw_str,
                                })
                            except _q.Full:
                                pass  # cloud lagging; drop oldest, keep reading

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
                                try:
                                    push_q.put_nowait({
                                        "weight_kg": weight,
                                        "tenant":    self.cfg["tenant_slug"],
                                        "agent_key": self.cfg["agent_key"],
                                        "raw": raw_str,
                                    })
                                except _q.Full:
                                    pass
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
                        reconnect_delay = 5
                        time.sleep(3)
                        continue

                # After 5 consecutive failures, wipe saved config and re-scan all ports.
                # This handles: port number changed (COM3→COM5 after reconnect),
                # device physically moved to different port, wrong config saved.
                if consecutive_failures >= 5:
                    log.warning("5 consecutive failures on %s — clearing config, re-scanning all ports", port)
                    self._clear_serial_cfg()
                    consecutive_failures = 0
                    reconnect_delay = 5
                else:
                    time.sleep(reconnect_delay)
                    reconnect_delay = min(reconnect_delay * 2, 60)

            finally:
                if ser is not None:
                    try:
                        ser.close()
                    except Exception:
                        pass


# ── Status Server ─────────────────────────────────────────────────────────────

class StatusServer:
    """Local HTTP diagnostic API at http://127.0.0.1:{port}.
    Auto-picks the first available port starting from preferred_port,
    so Tally on 9002 never blocks this service.
    """

    def __init__(self, reader: ScaleReader, preferred_port: int = 9002):
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
        from http.server import BaseHTTPRequestHandler, HTTPServer
        reader = self.reader
        port   = self.port

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                r = reader
                body = json.dumps({
                    "service":               "scale_agent_v2",
                    "status":                "running",
                    "timestamp":             datetime.now().isoformat(),
                    "scale_connected":       r.connected,
                    "detected_port":         r.detected_port,
                    "detected_config":       r.detected_config,
                    "cloud_online":          r.cloud_online,
                    "last_weight_kg":        r.last_weight,
                    "last_raw_frame":        r.last_raw_frame,
                    "calibration_offset_kg": r.cfg.get("calibration_offset_kg", 0.0),
                    "push_count":            r.push_count,
                    "error_count":           r.error_count,
                }, indent=2)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body.encode())

            def log_message(self, *args):
                pass  # suppress HTTP access log noise

        def _serve():
            try:
                HTTPServer(("127.0.0.1", port), Handler).serve_forever()
            except OSError as exc:
                log.warning("Status server on :%d failed to bind: %s", port, exc)

        threading.Thread(target=_serve, daemon=True, name="status-http").start()
        log.info("Status API: http://127.0.0.1:%d", self.port)


# ── Config helpers ────────────────────────────────────────────────────────────

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
    python = sys.executable
    script = str(Path(__file__).resolve())
    name   = "WeighbridgeScaleAgent"
    subprocess.run([nssm, "install",        name, python, script],                        check=True)
    subprocess.run([nssm, "set", name, "AppDirectory",   str(Path(__file__).parent)],     check=True)
    subprocess.run([nssm, "set", name, "AppStdout",      str(LOG_DIR / "stdout.log")],    check=True)
    subprocess.run([nssm, "set", name, "AppStderr",      str(LOG_DIR / "stderr.log")],    check=True)
    subprocess.run([nssm, "set", name, "AppRotateFiles", "1"],                            check=True)
    subprocess.run([nssm, "set", name, "AppRotateOnline","1"],                            check=True)
    subprocess.run([nssm, "set", name, "AppRotateBytes", "10485760"],                     check=True)
    print(f"\nService '{name}' installed.")
    print(f"Start:     nssm start {name}")
    print(f"Status:    nssm status {name}")
    print(f"Logs:      {LOG_DIR}")


def uninstall_service():
    import shutil, subprocess
    nssm = shutil.which("nssm")
    if not nssm:
        print("NSSM not found.")
        sys.exit(1)
    subprocess.run([nssm, "stop",   "WeighbridgeScaleAgent"], check=False)
    subprocess.run([nssm, "remove", "WeighbridgeScaleAgent", "confirm"], check=True)
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
    status = StatusServer(reader, preferred_port=cfg.get("status_port", 9002))
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
