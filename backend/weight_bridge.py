"""
Weight Bridge — Auto-detecting serial port reader using Win32 API.

Reads weight data from any weighbridge indicator via direct Windows
CreateFile/ReadFile (bypasses pyserial) and pushes readings to the
Weighbridge backend via HTTP.

Features:
  - Auto-detects COM port and baud rate (scans all ports + bauds)
  - Saves settings to weight_bridge.json (no CLI args needed)
  - Auto-reconnects if USB adapter is unplugged/replugged
  - Works with any indicator brand (Leo, Essae, generic, etc.)
  - Zero dependencies beyond Python 3.x standard library

Usage:
    python weight_bridge.py                  # Auto-detect (reads config)
    python weight_bridge.py --scan           # Force rescan
    python weight_bridge.py COM4 1200        # Manual override
    python weight_bridge.py --backend http://host:9001
"""

import ctypes
import ctypes.wintypes
import http.client
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import winreg

# ── Logging ──────────────────────────────────────────────────────────────── #

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("weight_bridge")

# ── Config ───────────────────────────────────────────────────────────────── #

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "weight_bridge.json")

DEFAULT_CONFIG = {
    "com_port": None,
    "baud_rate": None,
    "data_bits": 8,
    "parity": "N",
    "stop_bits": 1,
    "backend_url": "http://localhost:9001",
    "auto_detect": True,
    "scan_interval_sec": 30,
    "push_interval_ms": 50,
    "log_level": "info",
}


def load_config() -> dict:
    """Load config from weight_bridge.json, create with defaults if missing."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                cfg = json.load(f)
            # Merge with defaults for any missing keys
            for k, v in DEFAULT_CONFIG.items():
                if k not in cfg:
                    cfg[k] = v
            return cfg
        except Exception as e:
            log.warning("Failed to read config: %s — using defaults", e)
    return dict(DEFAULT_CONFIG)


def save_config(cfg: dict):
    """Save config to weight_bridge.json."""
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
        log.info("Config saved to %s", CONFIG_FILE)
    except Exception as e:
        log.warning("Failed to save config: %s", e)


# ── Win32 Constants ──────────────────────────────────────────────────────── #

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x80
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
DTR_CONTROL_ENABLE = 0x01
RTS_CONTROL_ENABLE = 0x01
NOPARITY = 0
ODDPARITY = 1
EVENPARITY = 2
ONESTOPBIT = 0
TWOSTOPBITS = 2
SETDTR = 5
SETRTS = 3
PURGE_RXCLEAR = 0x0008
PURGE_TXCLEAR = 0x0004

PARITY_MAP = {"N": NOPARITY, "O": ODDPARITY, "E": EVENPARITY}
STOPBITS_MAP = {1: ONESTOPBIT, 2: TWOSTOPBITS}

# Serial configs to try during auto-detect: (data_bits, parity, stop_bits)
SERIAL_CONFIGS = [
    (8, "N", 1),  # 8N1 — most common generic
    (7, "E", 1),  # 7E1 — Leo, Essae, Avery, most Indian indicators
    (7, "O", 1),  # 7O1 — rare, some older indicators
]

kernel32 = ctypes.windll.kernel32


class DCB(ctypes.Structure):
    _fields_ = [
        ("DCBlength", ctypes.wintypes.DWORD),
        ("BaudRate", ctypes.wintypes.DWORD),
        ("fBinary", ctypes.wintypes.DWORD, 1),
        ("fParity", ctypes.wintypes.DWORD, 1),
        ("fOutxCtsFlow", ctypes.wintypes.DWORD, 1),
        ("fOutxDsrFlow", ctypes.wintypes.DWORD, 1),
        ("fDtrControl", ctypes.wintypes.DWORD, 2),
        ("fDsrSensitivity", ctypes.wintypes.DWORD, 1),
        ("fTXContinueOnXoff", ctypes.wintypes.DWORD, 1),
        ("fOutX", ctypes.wintypes.DWORD, 1),
        ("fInX", ctypes.wintypes.DWORD, 1),
        ("fErrorChar", ctypes.wintypes.DWORD, 1),
        ("fNull", ctypes.wintypes.DWORD, 1),
        ("fRtsControl", ctypes.wintypes.DWORD, 2),
        ("fAbortOnError", ctypes.wintypes.DWORD, 1),
        ("fDummy2", ctypes.wintypes.DWORD, 17),
        ("wReserved", ctypes.wintypes.WORD),
        ("XonLim", ctypes.wintypes.WORD),
        ("XoffLim", ctypes.wintypes.WORD),
        ("ByteSize", ctypes.wintypes.BYTE),
        ("Parity", ctypes.wintypes.BYTE),
        ("StopBits", ctypes.wintypes.BYTE),
        ("XonChar", ctypes.c_char),
        ("XoffChar", ctypes.c_char),
        ("ErrorChar", ctypes.c_char),
        ("EofChar", ctypes.c_char),
        ("EvtChar", ctypes.c_char),
        ("wReserved1", ctypes.wintypes.WORD),
    ]


class COMMTIMEOUTS(ctypes.Structure):
    _fields_ = [
        ("ReadIntervalTimeout", ctypes.wintypes.DWORD),
        ("ReadTotalTimeoutMultiplier", ctypes.wintypes.DWORD),
        ("ReadTotalTimeoutConstant", ctypes.wintypes.DWORD),
        ("WriteTotalTimeoutMultiplier", ctypes.wintypes.DWORD),
        ("WriteTotalTimeoutConstant", ctypes.wintypes.DWORD),
    ]


# ── COM Port Discovery ──────────────────────────────────────────────────── #

# Port name substrings to skip (not weight scale adapters)
SKIP_PORTS = {"intel", "amt", "bluetooth", "bt ", "modem"}


def list_serial_ports() -> list[dict]:
    """
    List all COM ports from Windows registry with friendly names.
    Returns [{"port": "COM4", "name": "USB-SERIAL CH340 (COM4)"}, ...]
    """
    ports = []

    # Method 1: PnP device query (most reliable for USB-serial)
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             "Get-PnpDevice -Class Ports -Status OK | Select-Object -Property FriendlyName | Format-Table -HideTableHeaders"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            for line in result.stdout.strip().splitlines():
                line = line.strip()
                if not line:
                    continue
                # Extract COM port from "USB-SERIAL CH340 (COM4)"
                m = re.search(r"\(COM(\d+)\)", line)
                if m:
                    port_name = f"COM{m.group(1)}"
                    ports.append({"port": port_name, "name": line})
    except Exception:
        pass

    # Method 2: Registry fallback
    if not ports:
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM")
            i = 0
            while True:
                try:
                    name, port, _ = winreg.EnumValue(key, i)
                    ports.append({"port": port, "name": name})
                    i += 1
                except OSError:
                    break
            winreg.CloseKey(key)
        except Exception:
            pass

    return ports


def filter_candidate_ports(ports: list[dict]) -> list[dict]:
    """Filter out non-USB-serial ports (Intel AMT, Bluetooth, etc.)."""
    candidates = []
    for p in ports:
        name_lower = p["name"].lower()
        if any(skip in name_lower for skip in SKIP_PORTS):
            log.debug("Skipping port %s (%s)", p["port"], p["name"])
            continue
        candidates.append(p)
    return candidates


# ── Serial Port I/O ──────────────────────────────────────────────────────── #

def _preconfigure_port(port: str, baud_rate: int, data_bits: int = 8,
                       parity: str = "N", stop_bits: int = 1):
    """Use Windows MODE command to pre-configure port (helps CH340)."""
    try:
        p_char = parity[0].lower() if parity else "n"
        cmd = f"mode {port} baud={baud_rate} parity={p_char} data={data_bits} stop={stop_bits} dtr=on rts=on"
        subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
    except Exception:
        pass


def open_serial_port(port: str, baud_rate: int = 9600, data_bits: int = 8,
                     parity: str = "N", stop_bits: int = 1, quiet: bool = False) -> int:
    """Open a COM port using Win32 CreateFileW. Returns handle."""
    _preconfigure_port(port, baud_rate, data_bits, parity, stop_bits)

    handle = kernel32.CreateFileW(
        f"\\\\.\\{port}",
        GENERIC_READ | GENERIC_WRITE,
        0, None, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None,
    )

    if handle == INVALID_HANDLE_VALUE or handle == -1:
        err = kernel32.GetLastError()
        if err == 5:
            raise PermissionError(f"Access denied on {port}")
        elif err == 2:
            raise FileNotFoundError(f"Port {port} not found")
        elif err == 31:
            raise OSError(f"Device on {port} not functioning (Error 31)")
        else:
            raise OSError(f"Cannot open {port}: error {err}")

    # Try multiple methods to configure DCB (CH340 compatibility)
    dcb = DCB()
    dcb.DCBlength = ctypes.sizeof(DCB)
    configured = False

    win_parity = PARITY_MAP.get(parity.upper(), NOPARITY)
    win_stopbits = STOPBITS_MAP.get(stop_bits, ONESTOPBIT)
    use_parity = parity.upper() != "N"
    p_char = parity[0].upper() if parity else "N"

    # Method 1: BuildCommDCBW
    mode_str = f"baud={baud_rate} parity={p_char} data={data_bits} stop={stop_bits}"
    if kernel32.BuildCommDCBW(mode_str, ctypes.byref(dcb)):
        dcb.fBinary = 1
        dcb.fParity = 1 if use_parity else 0
        dcb.fDtrControl = DTR_CONTROL_ENABLE
        dcb.fRtsControl = RTS_CONTROL_ENABLE
        dcb.fOutxCtsFlow = 0
        dcb.fOutxDsrFlow = 0
        dcb.fOutX = 0
        dcb.fInX = 0
        dcb.fAbortOnError = 0
        if kernel32.SetCommState(handle, ctypes.byref(dcb)):
            configured = True

    # Method 2: GetCommState + modify
    if not configured:
        dcb2 = DCB()
        dcb2.DCBlength = ctypes.sizeof(DCB)
        if kernel32.GetCommState(handle, ctypes.byref(dcb2)):
            dcb2.BaudRate = baud_rate
            dcb2.ByteSize = data_bits
            dcb2.Parity = win_parity
            dcb2.StopBits = win_stopbits
            dcb2.fParity = 1 if use_parity else 0
            dcb2.fDtrControl = DTR_CONTROL_ENABLE
            dcb2.fRtsControl = RTS_CONTROL_ENABLE
            dcb2.fAbortOnError = 0
            if kernel32.SetCommState(handle, ctypes.byref(dcb2)):
                configured = True

    # Method 3: Minimal — just baud rate + serial params
    if not configured:
        dcb3 = DCB()
        dcb3.DCBlength = ctypes.sizeof(DCB)
        if kernel32.GetCommState(handle, ctypes.byref(dcb3)):
            dcb3.BaudRate = baud_rate
            dcb3.ByteSize = data_bits
            dcb3.Parity = win_parity
            dcb3.StopBits = win_stopbits
            kernel32.SetCommState(handle, ctypes.byref(dcb3))
        # Fall through — MODE command may have configured it

    # Set timeouts
    timeouts = COMMTIMEOUTS()
    timeouts.ReadIntervalTimeout = 50
    timeouts.ReadTotalTimeoutMultiplier = 10
    timeouts.ReadTotalTimeoutConstant = 500
    timeouts.WriteTotalTimeoutMultiplier = 10
    timeouts.WriteTotalTimeoutConstant = 1000
    kernel32.SetCommTimeouts(handle, ctypes.byref(timeouts))

    # Purge buffers + set DTR/RTS HIGH
    kernel32.PurgeComm(handle, PURGE_RXCLEAR | PURGE_TXCLEAR)
    kernel32.EscapeCommFunction(handle, SETDTR)
    kernel32.EscapeCommFunction(handle, SETRTS)

    return handle


def read_serial(handle: int, max_bytes: int = 256) -> bytes:
    """Read up to max_bytes from the serial port. Returns b'' on timeout."""
    buf = ctypes.create_string_buffer(max_bytes)
    bytes_read = ctypes.wintypes.DWORD(0)
    ok = kernel32.ReadFile(handle, buf, max_bytes, ctypes.byref(bytes_read), None)
    if ok and bytes_read.value > 0:
        return buf.raw[:bytes_read.value]
    return b""


def close_serial(handle: int):
    """Close the serial port handle."""
    kernel32.CloseHandle(handle)


# ── Weight Parsing ────────────────────────────────────────────────────────── #

WEIGHT_PATTERN = re.compile(r"[-+]?\s*(\d{1,7}(?:\.\d{1,4})?)")


def parse_weight(text: str) -> float | None:
    """Extract weight value from text. Returns None if no valid weight."""
    text = text.strip()
    if not text:
        return None
    match = WEIGHT_PATTERN.search(text)
    if match:
        value = float(match.group(1).replace(" ", ""))
        if 0 <= value <= 200000:
            return value
    return None


# ── Auto-Detection ────────────────────────────────────────────────────────── #

BAUD_RATES = [1200, 2400, 4800, 9600, 19200]


def probe_port(port: str, baud: int, data_bits: int = 8, parity: str = "N",
               stop_bits: int = 1, duration: float = 3.0) -> tuple[int, int]:
    """
    Open port at baud rate, read for duration seconds.
    Returns (total_bytes, printable_percent).
    """
    try:
        handle = open_serial_port(port, baud, data_bits, parity, stop_bits, quiet=True)
    except Exception:
        return (0, 0)

    all_bytes = b""
    start = time.time()
    while time.time() - start < duration:
        chunk = read_serial(handle, 256)
        if chunk:
            all_bytes += chunk

    close_serial(handle)

    if not all_bytes:
        return (0, 0)

    printable = sum(1 for b in all_bytes if 0x20 <= b <= 0x7E)
    pct = int(100 * printable / len(all_bytes))
    return (len(all_bytes), pct)


def auto_detect_port() -> tuple[str, int, int, str, int] | None:
    """
    Scan all candidate COM ports at all common baud rates and serial configs.
    Returns (port, baud_rate, data_bits, parity, stop_bits) for the best match, or None.
    """
    all_ports = list_serial_ports()
    candidates = filter_candidate_ports(all_ports)

    if not candidates:
        log.warning("No USB-serial ports found")
        if all_ports:
            log.info("Available ports (skipped): %s",
                     ", ".join(f"{p['port']} ({p['name']})" for p in all_ports))
        return None

    log.info("Scanning %d port(s): %s",
             len(candidates),
             ", ".join(f"{p['port']} ({p['name']})" for p in candidates))

    best = None  # (port, baud, bytes, pct, db, par, sb)

    for p in candidates:
        port = p["port"]
        for baud in BAUD_RATES:
            for db, par, sb in SERIAL_CONFIGS:
                label = f"{db}{par}{sb}"
                log.info("  Probing %s @ %d baud %s...", port, baud, label)
                nbytes, pct = probe_port(port, baud, db, par, sb, duration=3.0)

                if nbytes > 0:
                    log.info("    -> %d bytes, %d%% printable ASCII", nbytes, pct)
                    if best is None or pct > best[3] or (pct == best[3] and nbytes > best[2]):
                        best = (port, baud, nbytes, pct, db, par, sb)

                    # If we found >70% printable data, this is almost certainly correct
                    if pct >= 70:
                        log.info("  Found weight data on %s @ %d baud %s (%d%% printable)",
                                 port, baud, label, pct)
                        return (port, baud, db, par, sb)

    if best and best[3] >= 30:
        log.info("Best match: %s @ %d baud %d%s%d (%d bytes, %d%% printable)",
                 best[0], best[1], best[4], best[5], best[6], best[2], best[3])
        return (best[0], best[1], best[4], best[5], best[6])

    log.warning("No weight indicator detected on any port")
    return None


# ── HTTP Push (persistent connection) ─────────────────────────────────────── #

_http_conn = None


def push_weight(backend_url: str, weight_kg: float, raw: str) -> bool:
    """POST weight reading using a persistent HTTP connection."""
    global _http_conn

    data = json.dumps({"weight_kg": weight_kg, "raw": raw}).encode("utf-8")
    host_port = backend_url.replace("http://", "").replace("https://", "")

    try:
        if _http_conn is None:
            _http_conn = http.client.HTTPConnection(host_port, timeout=2)
        _http_conn.request(
            "POST", "/api/v1/weight/external-reading",
            body=data,
            headers={"Content-Type": "application/json", "Connection": "keep-alive"},
        )
        resp = _http_conn.getresponse()
        resp.read()
        return resp.status == 200
    except Exception:
        try:
            _http_conn.close()
        except Exception:
            pass
        _http_conn = None
        return False


# ── Frame Parser ──────────────────────────────────────────────────────────── #

def parse_frames(buffer: bytes) -> tuple[float | None, str, bytes]:
    """
    Parse all weight frames from buffer.
    Handles STX-delimited (0x02), CR/LF-delimited, and delimiter-less formats.
    Returns (latest_weight, latest_raw, remaining_buffer).
    """
    latest_weight = None
    latest_raw = ""

    # Process STX-delimited frames
    while True:
        stx_pos = buffer.find(b'\x02')
        if stx_pos < 0:
            break

        # Discard bytes before first STX
        if stx_pos > 0:
            buffer = buffer[stx_pos:]

        # Need at least 10 bytes for a complete frame (STX + 8 data + trailing)
        if len(buffer) < 10:
            break

        frame_data = buffer[1:9]
        buffer = buffer[10:]
        text = frame_data.decode("ascii", errors="ignore").strip()
        if text:
            w = parse_weight(text)
            if w is not None:
                latest_weight = w
                latest_raw = text

    # Also process CR/LF-delimited lines (for indicators that use line endings)
    while b'\n' in buffer or b'\r' in buffer:
        for sep in (b'\r\n', b'\n', b'\r'):
            if sep in buffer:
                line, buffer = buffer.split(sep, 1)
                break
        else:
            break
        text = line.decode("ascii", errors="ignore").replace('\x02', '').strip()
        if text:
            w = parse_weight(text)
            if w is not None:
                latest_weight = w
                latest_raw = text

    # Fallback: delimiter-less continuous output (e.g. Leo FSD 501)
    # Format: "k      0k      0" — no STX/CR/LF, just repeating frames.
    # Try regex directly on the buffer to extract weight.
    if latest_weight is None and len(buffer) >= 8:
        text = buffer.decode("ascii", errors="ignore")
        if text.strip():
            w = parse_weight(text)
            if w is not None:
                latest_weight = w
                latest_raw = text.strip()[-20:]
        # Prevent buffer from growing forever — keep only the tail
        if len(buffer) > 64:
            buffer = buffer[-16:]

    return (latest_weight, latest_raw, buffer)


# ── Read Loop ─────────────────────────────────────────────────────────────── #

def run_read_loop(handle: int, backend_url: str, push_interval_ms: int = 50) -> str:
    """
    Read weight data from serial handle and push to backend.
    Returns reason for stopping: "no_data", "error", or "interrupted".
    """
    # Background push thread
    current_weight = {"kg": None, "raw": "", "dirty": False}
    weight_lock = threading.Lock()
    push_count = 0
    error_count = 0
    push_running = True
    interval = push_interval_ms / 1000.0

    def push_loop():
        nonlocal push_count, error_count
        while push_running:
            with weight_lock:
                if current_weight["dirty"]:
                    w = current_weight["kg"]
                    r = current_weight["raw"]
                    current_weight["dirty"] = False
                else:
                    w = None
            if w is not None:
                ok = push_weight(backend_url, w, r)
                if ok:
                    push_count += 1
                else:
                    error_count += 1
            time.sleep(interval)

    push_thread = threading.Thread(target=push_loop, daemon=True)
    push_thread.start()

    buffer = b""
    last_weight = None
    last_data_time = time.time()
    NO_DATA_TIMEOUT = 10  # seconds without data → reconnect

    try:
        while True:
            chunk = read_serial(handle, 256)

            if not chunk:
                if time.time() - last_data_time > NO_DATA_TIMEOUT:
                    log.warning("No data for %ds — will reconnect", NO_DATA_TIMEOUT)
                    return "no_data"
                continue

            last_data_time = time.time()
            buffer += chunk

            latest_weight, latest_raw, buffer = parse_frames(buffer)

            if latest_weight is not None:
                if latest_weight != last_weight:
                    log.info("WEIGHT: %10.2f kg", latest_weight)
                    last_weight = latest_weight

                with weight_lock:
                    current_weight["kg"] = latest_weight
                    current_weight["raw"] = latest_raw
                    current_weight["dirty"] = True
            else:
                # Keep pushing last known weight
                with weight_lock:
                    if current_weight["kg"] is not None:
                        current_weight["dirty"] = True

            # Prevent buffer overflow
            if len(buffer) > 1024:
                buffer = buffer[-256:]

    except KeyboardInterrupt:
        log.info("Stopped by user. Pushed: %d, Errors: %d", push_count, error_count)
        return "interrupted"
    except Exception as e:
        log.error("Read loop error: %s", e)
        return "error"
    finally:
        push_running = False


# ── Main ──────────────────────────────────────────────────────────────────── #

def main():
    print("=" * 60)
    print("  Weight Bridge — Auto-Detecting Serial Reader")
    print("  Zero-config weight scale integration")
    print("=" * 60)

    # ── Parse CLI args (override config) ────────────────────────────────── #
    positional = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    cli_port = positional[0].upper() if len(positional) > 0 else None
    cli_baud = int(positional[1]) if len(positional) > 1 else None
    force_scan = "--scan" in flags

    cli_backend = None
    for i, arg in enumerate(sys.argv):
        if arg == "--backend" and i + 1 < len(sys.argv):
            cli_backend = sys.argv[i + 1]

    # ── Load config ─────────────────────────────────────────────────────── #
    cfg = load_config()

    # CLI overrides config
    if cli_port:
        cfg["com_port"] = cli_port
    if cli_baud:
        cfg["baud_rate"] = cli_baud
    if cli_backend:
        cfg["backend_url"] = cli_backend
    if force_scan:
        cfg["com_port"] = None
        cfg["baud_rate"] = None

    backend_url = cfg["backend_url"]
    auto_detect = cfg.get("auto_detect", True)
    scan_interval = cfg.get("scan_interval_sec", 30)
    push_interval = cfg.get("push_interval_ms", 50)

    # Set log level
    log_level = cfg.get("log_level", "info").upper()
    logging.getLogger().setLevel(getattr(logging, log_level, logging.INFO))

    log.info("Config: %s", CONFIG_FILE)
    log.info("Backend: %s", backend_url)

    # ── Main reconnection loop ──────────────────────────────────────────── #
    while True:
        port = cfg.get("com_port")
        baud = cfg.get("baud_rate")
        data_bits = int(cfg.get("data_bits", 8))
        par = cfg.get("parity", "N")
        stop = int(cfg.get("stop_bits", 1))

        # Auto-detect if port or baud unknown
        if not port or not baud:
            if auto_detect or force_scan:
                log.info("Auto-detecting weight indicator...")
                result = auto_detect_port()
                if result:
                    port, baud, data_bits, par, stop = result
                    cfg["com_port"] = port
                    cfg["baud_rate"] = baud
                    cfg["data_bits"] = data_bits
                    cfg["parity"] = par
                    cfg["stop_bits"] = stop
                    save_config(cfg)
                    force_scan = False
                else:
                    log.warning("No indicator found. Retrying in %ds...", scan_interval)
                    time.sleep(scan_interval)
                    continue
            else:
                log.error("No COM port configured and auto_detect is disabled")
                log.error("Set com_port and baud_rate in %s", CONFIG_FILE)
                time.sleep(scan_interval)
                continue

        serial_label = f"{data_bits}{par}{stop}"

        # Open port
        log.info("Opening %s @ %d baud %s...", port, baud, serial_label)
        try:
            handle = open_serial_port(port, baud, data_bits, par, stop)
        except Exception as e:
            log.error("Failed to open %s: %s", port, e)
            if auto_detect:
                log.info("Will re-scan for indicator in %ds...", scan_interval)
                cfg["com_port"] = None
                cfg["baud_rate"] = None
                time.sleep(scan_interval)
                continue
            else:
                log.info("Retrying in %ds...", scan_interval)
                time.sleep(scan_interval)
                continue

        log.info("Connected to %s @ %d baud (DTR=ON, RTS=ON, %s)", port, baud, serial_label)

        # Run read loop until disconnect
        reason = run_read_loop(handle, backend_url, push_interval)
        close_serial(handle)
        log.info("Disconnected from %s (reason: %s)", port, reason)

        if reason == "interrupted":
            break

        # Reconnection strategy
        if reason == "no_data" and auto_detect:
            log.info("Re-scanning for indicator (may have moved to different port)...")
            cfg["com_port"] = None
            cfg["baud_rate"] = None
            time.sleep(2)  # brief pause before rescan
        elif reason == "error":
            log.info("Retrying same port in 5s...")
            time.sleep(5)
        else:
            time.sleep(5)

    log.info("Weight Bridge stopped.")


if __name__ == "__main__":
    main()
