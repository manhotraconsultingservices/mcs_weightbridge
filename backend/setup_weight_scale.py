"""
Weight Scale Setup Utility — Client-Side Tool
==============================================
Auto-detects weighbridge indicator on any COM port, determines the correct
baud rate and serial config, writes weight_bridge.json, then validates with
a live read test.

Features:
  - Scans ALL COM ports (PnP + Registry + brute-force COM1-32)
  - Tests 5 baud rates × 4 serial configs = 20 combos per port
  - Uses Win32 API directly (works even when .NET SerialPort fails)
  - Writes weight_bridge.json with detected settings
  - Validates by reading live weight for 5 seconds
  - Shows step-by-step manual verification instructions

Usage:
    python setup_weight_scale.py                # Full auto-detect + setup
    python setup_weight_scale.py --scan-only    # Scan only, don't write config
    python setup_weight_scale.py --validate     # Validate existing config
    python setup_weight_scale.py --port COM7    # Test specific port only

Requirements:
  - Windows 10/11
  - USB-to-RS232 adapter connected to weighbridge indicator
  - Indicator must be powered on and displaying weight
  - No other program should be reading the COM port
    (stop WeighbridgeWeightBridge service first)

Zero dependencies beyond Python 3.x standard library.
"""

import ctypes
import ctypes.wintypes
import json
import os
import re
import subprocess
import sys
import time
import winreg

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

kernel32 = ctypes.windll.kernel32

WEIGHT_PATTERN = re.compile(r"[-+]?\s*(\d{1,7}(?:\.\d{1,4})?)")

# Baud rates and serial configs to test
BAUD_RATES = [9600, 4800, 2400, 1200, 19200]  # 9600 first (most common)
SERIAL_CONFIGS = [
    # (data_bits, parity_char, parity_win32, stop_bits, stop_win32, label)
    (8, "N", NOPARITY,   1, ONESTOPBIT, "8N1"),
    (7, "E", EVENPARITY, 1, ONESTOPBIT, "7E1"),
    (7, "O", ODDPARITY,  1, ONESTOPBIT, "7O1"),
    (8, "E", EVENPARITY, 1, ONESTOPBIT, "8E1"),
]

# Ports to skip (not weight scale adapters)
SKIP_PORTS = {"intel", "amt", "bluetooth", "bt ", "modem"}

# Config file path
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "weight_bridge.json")


# ── Win32 Structures ────────────────────────────────────────────────────── #

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


# ── Helpers ──────────────────────────────────────────────────────────────── #

def color(text, code):
    """ANSI color output."""
    return f"\033[{code}m{text}\033[0m"

def green(text):  return color(text, "32")
def red(text):    return color(text, "31")
def yellow(text): return color(text, "33")
def cyan(text):   return color(text, "36")
def bold(text):   return color(text, "1")
def dim(text):    return color(text, "2")


def parse_weight(text: str) -> float | None:
    """Extract weight value from text."""
    text = text.strip()
    if not text:
        return None
    match = WEIGHT_PATTERN.search(text)
    if match:
        value = float(match.group(1).replace(" ", ""))
        if 0 <= value <= 200000:
            return value
    return None


# ── Port Discovery ──────────────────────────────────────────────────────── #

def discover_ports() -> list[dict]:
    """Find all COM ports using multiple methods."""
    ports = {}

    # Method 1: PnP device query (most reliable for USB-serial)
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             "Get-PnpDevice -Class Ports -Status OK | "
             "Select-Object -Property FriendlyName | "
             "Format-Table -HideTableHeaders"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            for line in result.stdout.strip().splitlines():
                line = line.strip()
                if not line:
                    continue
                m = re.search(r"\(COM(\d+)\)", line)
                if m:
                    port_name = f"COM{m.group(1)}"
                    ports[port_name] = {
                        "port": port_name, "name": line, "source": "PnP"
                    }
    except Exception:
        pass

    # Method 2: Registry
    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM"
        )
        i = 0
        while True:
            try:
                name, port, _ = winreg.EnumValue(key, i)
                if port not in ports:
                    ports[port] = {
                        "port": port, "name": name, "source": "Registry"
                    }
                i += 1
            except OSError:
                break
        winreg.CloseKey(key)
    except Exception:
        pass

    # Method 3: Brute-force COM1-COM32
    for n in range(1, 33):
        port_name = f"COM{n}"
        if port_name not in ports:
            handle = kernel32.CreateFileW(
                f"\\\\.\\{port_name}",
                GENERIC_READ | GENERIC_WRITE,
                0, None, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None,
            )
            if handle != INVALID_HANDLE_VALUE and handle != -1:
                kernel32.CloseHandle(handle)
                ports[port_name] = {
                    "port": port_name,
                    "name": f"COM{n} (detected)",
                    "source": "brute",
                }
            else:
                err = kernel32.GetLastError()
                if err in (5, 31):
                    status = "locked by another process" if err == 5 else "driver error 31"
                    ports[port_name] = {
                        "port": port_name,
                        "name": f"COM{n} ({status})",
                        "source": "brute",
                        "error": err,
                    }

    return sorted(
        ports.values(),
        key=lambda p: int(re.search(r"\d+", p["port"]).group()),
    )


# ── Port Open / Read / Close ────────────────────────────────────────────── #

def open_port(port, baud, data_bits, parity_char, parity_val, stop_bits, stop_val):
    """Open a COM port using Win32 API. Returns handle or raises."""
    # Pre-configure via MODE command (helps CH340)
    p_lower = parity_char.lower()
    try:
        subprocess.run(
            f"mode {port} baud={baud} parity={p_lower} data={data_bits} "
            f"stop={stop_bits} dtr=on rts=on",
            shell=True, capture_output=True, text=True, timeout=5,
        )
    except Exception:
        pass

    handle = kernel32.CreateFileW(
        f"\\\\.\\{port}",
        GENERIC_READ | GENERIC_WRITE,
        0, None, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None,
    )
    if handle == INVALID_HANDLE_VALUE or handle == -1:
        err = kernel32.GetLastError()
        msgs = {
            2: "Port not found",
            5: "Access denied — port locked by another process",
            31: "Device not functioning (Error 31) — unplug/replug USB adapter",
        }
        raise OSError(msgs.get(err, f"Win32 error {err}"))

    # Configure DCB
    dcb = DCB()
    dcb.DCBlength = ctypes.sizeof(DCB)
    kernel32.GetCommState(handle, ctypes.byref(dcb))
    dcb.BaudRate = baud
    dcb.ByteSize = data_bits
    dcb.Parity = parity_val
    dcb.StopBits = stop_val
    dcb.fParity = 1 if parity_char != "N" else 0
    dcb.fBinary = 1
    dcb.fDtrControl = DTR_CONTROL_ENABLE
    dcb.fRtsControl = RTS_CONTROL_ENABLE
    dcb.fOutxCtsFlow = 0
    dcb.fOutxDsrFlow = 0
    dcb.fOutX = 0
    dcb.fInX = 0
    dcb.fAbortOnError = 0
    kernel32.SetCommState(handle, ctypes.byref(dcb))

    # Timeouts
    timeouts = COMMTIMEOUTS()
    timeouts.ReadIntervalTimeout = 50
    timeouts.ReadTotalTimeoutMultiplier = 10
    timeouts.ReadTotalTimeoutConstant = 500
    kernel32.SetCommTimeouts(handle, ctypes.byref(timeouts))

    # Purge + signal
    kernel32.PurgeComm(handle, PURGE_RXCLEAR | PURGE_TXCLEAR)
    kernel32.EscapeCommFunction(handle, SETDTR)
    kernel32.EscapeCommFunction(handle, SETRTS)

    return handle


def read_bytes(handle, max_bytes=512):
    """Read available bytes from serial port."""
    buf = ctypes.create_string_buffer(max_bytes)
    br = ctypes.wintypes.DWORD(0)
    ok = kernel32.ReadFile(handle, buf, max_bytes, ctypes.byref(br), None)
    if ok and br.value > 0:
        return buf.raw[:br.value]
    return b""


def close_port(handle):
    """Close serial port handle."""
    kernel32.CloseHandle(handle)


# ── Probe a Single Port Config ──────────────────────────────────────────── #

def probe(port, baud, db, p_char, p_val, sb, sb_val, duration=3.0):
    """
    Read from port for `duration` seconds. Returns dict with results.
    """
    try:
        handle = open_port(port, baud, db, p_char, p_val, sb, sb_val)
    except OSError as e:
        return {"error": str(e), "bytes": 0}

    all_bytes = b""
    start = time.time()
    while time.time() - start < duration:
        chunk = read_bytes(handle, 512)
        if chunk:
            all_bytes += chunk
    close_port(handle)

    if not all_bytes:
        return {"bytes": 0, "error": None}

    total = len(all_bytes)
    printable = sum(1 for b in all_bytes if 0x20 <= b <= 0x7E or b in (0x02, 0x0D, 0x0A))
    pct = int(100 * printable / total)

    # Try to extract weight from the data
    text = all_bytes.decode("ascii", errors="ignore")
    weight = parse_weight(text)

    # Hex + ASCII preview
    sample = all_bytes[:60]
    hex_str = sample.hex(" ").upper()
    ascii_str = "".join(chr(b) if 0x20 <= b <= 0x7E else "." for b in sample)

    return {
        "bytes": total,
        "printable_pct": pct,
        "weight": weight,
        "hex": hex_str,
        "ascii": ascii_str,
        "error": None,
    }


# ── Full Scan ────────────────────────────────────────────────────────────── #

def scan_all(specific_port=None):
    """Scan ports and return best match."""
    print(bold("\n  STEP 1: Discovering COM ports...\n"))

    all_ports = discover_ports()
    if not all_ports:
        print(red("  ERROR: No COM ports found!"))
        print("  Check that the USB-to-RS232 adapter is plugged in.")
        return None

    for p in all_ports:
        err_text = ""
        if p.get("error") == 5:
            err_text = red(" [LOCKED]")
        elif p.get("error") == 31:
            err_text = red(" [ERROR 31 — replug USB]")

        skip = any(s in p["name"].lower() for s in SKIP_PORTS)
        skip_text = dim(" (skipped — not a scale)") if skip else ""
        print(f"    {p['port']:8s}  {p['name']}{err_text}{skip_text}")

    # Filter candidates
    if specific_port:
        candidates = [p for p in all_ports if p["port"].upper() == specific_port.upper()]
        if not candidates:
            print(red(f"\n  Port {specific_port} not found!"))
            return None
    else:
        candidates = [
            p for p in all_ports
            if not any(s in p["name"].lower() for s in SKIP_PORTS)
            and not p.get("error")
        ]

    if not candidates:
        print(red("\n  No available ports to scan."))
        print("  If port shows LOCKED — stop the WeighbridgeWeightBridge service first:")
        print(cyan("    Stop-Service WeighbridgeWeightBridge -Force"))
        print("  If port shows ERROR 31 — unplug and replug the USB adapter.")
        return None

    # Scan
    total = len(candidates) * len(BAUD_RATES) * len(SERIAL_CONFIGS)
    print(bold(f"\n  STEP 2: Scanning {len(candidates)} port(s) "
               f"({total} combinations, ~{total * 3}s max)...\n"))

    matches = []
    n = 0

    for p in candidates:
        port = p["port"]
        port_error = None

        for baud in BAUD_RATES:
            if port_error:
                break
            for db, p_char, p_val, sb, sb_val, label in SERIAL_CONFIGS:
                n += 1
                sys.stdout.write(f"\r    [{n}/{total}] {port} @ {baud} {label}...    ")
                sys.stdout.flush()

                r = probe(port, baud, db, p_char, p_val, sb, sb_val, duration=3.0)

                if r.get("error"):
                    err = r["error"]
                    if "Error 31" in err or "not functioning" in err:
                        print(red(f"\n    {port}: {err}"))
                        port_error = True
                        break
                    elif "locked" in err.lower() or "denied" in err.lower():
                        print(red(f"\n    {port}: {err}"))
                        port_error = True
                        break
                    continue

                if r["bytes"] == 0:
                    continue

                pct = r["printable_pct"]

                if pct >= 70:
                    w_text = f", Weight: {r['weight']:.1f} kg" if r["weight"] is not None else ""
                    print(green(f"\n    MATCH: {port} @ {baud} {label} — "
                                f"{r['bytes']} bytes, {pct}% printable{w_text}"))
                    print(f"    HEX:   {r['hex']}")
                    print(f"    ASCII: {r['ascii']}")

                    matches.append({
                        "port": port,
                        "baud": baud,
                        "data_bits": db,
                        "parity": p_char,
                        "stop_bits": sb,
                        "label": label,
                        "bytes": r["bytes"],
                        "pct": pct,
                        "weight": r["weight"],
                        "hex": r["hex"],
                        "ascii": r["ascii"],
                    })

                elif pct >= 30:
                    print(yellow(f"\n    PARTIAL: {port} @ {baud} {label} — "
                                 f"{r['bytes']} bytes, {pct}% printable (garbled)"))

    print()
    return matches


# ── Write Config ─────────────────────────────────────────────────────────── #

def write_config(match):
    """Write weight_bridge.json with detected settings."""
    # Load existing config or create new
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
    else:
        cfg = {}

    # Update with detected settings
    cfg["com_port"] = match["port"]
    cfg["baud_rate"] = match["baud"]
    cfg["data_bits"] = match["data_bits"]
    cfg["parity"] = match["parity"]
    cfg["stop_bits"] = match["stop_bits"]

    # Ensure other defaults exist
    cfg.setdefault("backend_url", "http://localhost:9001")
    cfg.setdefault("auto_detect", True)
    cfg.setdefault("scan_interval_sec", 30)
    cfg.setdefault("push_interval_ms", 50)
    cfg.setdefault("log_level", "info")

    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

    return cfg


# ── Validate Config ──────────────────────────────────────────────────────── #

def validate_config(cfg=None):
    """Read weight_bridge.json and do a live validation test."""
    print(bold("\n  VALIDATION: Live Read Test\n"))

    if cfg is None:
        if not os.path.exists(CONFIG_FILE):
            print(red(f"  Config not found: {CONFIG_FILE}"))
            return False
        with open(CONFIG_FILE, "r") as f:
            cfg = json.load(f)

    port = cfg.get("com_port")
    baud = cfg.get("baud_rate", 9600)
    db = cfg.get("data_bits", 8)
    par = cfg.get("parity", "N")
    sb = cfg.get("stop_bits", 1)

    par_map = {"N": NOPARITY, "E": EVENPARITY, "O": ODDPARITY}
    sb_map = {1: ONESTOPBIT, 2: TWOSTOPBITS}
    par_val = par_map.get(par, NOPARITY)
    sb_val = sb_map.get(sb, ONESTOPBIT)

    print(f"    Config file: {CONFIG_FILE}")
    print(f"    Port:        {port}")
    print(f"    Baud:        {baud}")
    print(f"    Data bits:   {db}")
    print(f"    Parity:      {par}")
    print(f"    Stop bits:   {sb}")
    print()

    if not port:
        print(red("  ERROR: com_port is not set in config!"))
        return False

    # Open port
    try:
        handle = open_port(port, baud, db, par, par_val, sb, sb_val)
    except OSError as e:
        print(red(f"  ERROR: Cannot open {port}: {e}"))
        return False

    # Read for 5 seconds, show live data
    print(f"    Reading from {port} for 5 seconds...\n")

    weights_seen = []
    all_bytes = b""

    for second in range(5):
        chunk = b""
        start = time.time()
        while time.time() - start < 1.0:
            data = read_bytes(handle, 512)
            if data:
                chunk += data

        if chunk:
            all_bytes += chunk
            text = chunk.decode("ascii", errors="ignore")
            ascii_clean = "".join(c if 0x20 <= ord(c) <= 0x7E else "." for c in text)
            hex_str = chunk[:30].hex(" ").upper()
            w = parse_weight(text)

            w_text = f"  Weight: {green(f'{w:.1f} kg')}" if w is not None else ""
            print(f"    Second {second + 1}: {len(chunk):3d} bytes | "
                  f"HEX: {hex_str[:50]:50s} | "
                  f"ASCII: {ascii_clean[:25]:25s}{w_text}")

            if w is not None:
                weights_seen.append(w)
        else:
            print(f"    Second {second + 1}: {dim('(no data)')}")

    close_port(handle)

    # Summary
    print()
    total_bytes = len(all_bytes)
    if total_bytes == 0:
        print(red("  FAIL: No data received from scale."))
        print("  Check cable wiring and indicator output mode.")
        return False

    printable = sum(1 for b in all_bytes if 0x20 <= b <= 0x7E or b in (0x02, 0x0D, 0x0A))
    pct = int(100 * printable / total_bytes)

    if pct < 70:
        print(yellow(f"  WARNING: Only {pct}% printable data — settings may be wrong."))
        print("  Try running full scan: python setup_weight_scale.py")
        return False

    if weights_seen:
        avg = sum(weights_seen) / len(weights_seen)
        stable = max(weights_seen) - min(weights_seen) < 10
        print(green(f"  PASS: {total_bytes} bytes, {pct}% printable, "
                     f"{len(weights_seen)} weight readings"))
        print(green(f"  Current weight: {avg:.1f} kg"
                     f"{' (STABLE)' if stable else ' (fluctuating)'}"))
    else:
        print(yellow(f"  WARNING: {total_bytes} bytes received ({pct}% printable) "
                      "but no weight value parsed."))
        print("  The data format may need a custom protocol parser.")
        return False

    return True


# ── Print Manual Steps ───────────────────────────────────────────────────── #

def print_manual_steps(cfg):
    """Print manual verification instructions."""
    print(bold("\n" + "=" * 65))
    print(bold("  MANUAL VERIFICATION STEPS"))
    print("=" * 65)

    print(f"""
  1. CHECK weight_bridge.json
     Open {CONFIG_FILE} and verify:

     {{
       "com_port":  "{cfg['com_port']}",
       "baud_rate": {cfg['baud_rate']},
       "data_bits": {cfg['data_bits']},
       "parity":    "{cfg['parity']}",
       "stop_bits": {cfg['stop_bits']}
     }}

  2. COMPARE WITH INDICATOR DISPLAY
     - Look at the weight shown on the FSD 501 / indicator display
     - The weight shown above in the live test should match
     - If they don't match, the decimal_places setting may need adjusting

  3. RESTART THE SERVICE
     Open PowerShell as Administrator and run:

     {cyan('Restart-Service WeighbridgeWeightBridge -Force')}
     {cyan('Restart-Service WeighbridgeBackend -Force')}

  4. VERIFY IN BROWSER
     - Open http://localhost:9001 in your browser
     - The weight widget should show {green('ONLINE')} (not OFFLINE)
     - The weight value should match the indicator display
     - Place/remove weight on the scale to verify it changes

  5. IF WEIGHT SHOWS OFFLINE
     Check the service is running:
     {cyan('Get-Service WeighbridgeWeightBridge | Format-Table Name, Status')}

     Check logs:
     {cyan('Get-Content C:\\weighbridge\\logs\\weight_bridge.log -Tail 20')}

  6. IF COM PORT CHANGES AFTER REBOOT
     The USB adapter may get a different COM number after reboot.
     Re-run this utility to detect the new port:
     {cyan('python setup_weight_scale.py')}
""")


# ── Main ─────────────────────────────────────────────────────────────────── #

def main():
    print("\n" + "=" * 65)
    print(bold("  WEIGHT SCALE SETUP UTILITY"))
    print("  Auto-detect weighbridge indicator and configure connection")
    print("=" * 65)

    # Parse args
    args = sys.argv[1:]
    scan_only = "--scan-only" in args
    validate_only = "--validate" in args
    specific_port = None
    for a in args:
        if a.startswith("--port"):
            idx = args.index(a)
            if idx + 1 < len(args):
                specific_port = args[idx + 1].upper()
            elif "=" in a:
                specific_port = a.split("=", 1)[1].upper()

    # Validate-only mode
    if validate_only:
        success = validate_config()
        if success:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, "r") as f:
                    cfg = json.load(f)
                print_manual_steps(cfg)
        sys.exit(0 if success else 1)

    # Check for processes that might lock the port
    print(dim("\n  Checking for processes that might lock the COM port..."))
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             "Get-Process | Where-Object { $_.ProcessName -match 'python' } | "
             "Select-Object Id, ProcessName, Path | Format-Table -AutoSize"],
            capture_output=True, text=True, timeout=10,
        )
        python_procs = result.stdout.strip()
        if python_procs and "python" in python_procs.lower():
            # Filter out our own process
            our_pid = os.getpid()
            lines = python_procs.strip().splitlines()
            others = [l for l in lines if str(our_pid) not in l and "Id" not in l and "---" not in l]
            if others:
                print(yellow("\n  WARNING: Other Python processes are running:"))
                for line in others:
                    print(f"    {line.strip()}")
                print(yellow("  These may be locking the COM port."))
                print(f"  To stop them: {cyan('Stop-Service WeighbridgeWeightBridge -Force')}")
                resp = input("\n  Continue anyway? (Y/n): ").strip().lower()
                if resp == "n":
                    print("  Aborted. Stop the services first, then re-run.")
                    sys.exit(0)
    except Exception:
        pass

    # Run scan
    matches = scan_all(specific_port)

    if not matches:
        print(red(bold("\n  No weight indicator detected.")))
        print("""
  Possible causes:

  1. PORT LOCKED — Another process has the COM port open.
     Fix: Stop-Service WeighbridgeWeightBridge -Force

  2. ERROR 31 — CH340 USB adapter driver stuck.
     Fix: Unplug USB cable, wait 5 seconds, plug back in.

  3. NO DATA — Indicator not transmitting.
     Fix: Check indicator menu → set Output Mode to CONTINUOUS.
     Some indicators only send data when PRINT key is pressed.

  4. CABLE WIRING — RS232 TX/RX may be swapped.
     Fix: Try a null-modem adapter or swap pins 2 and 3.

  5. INDICATOR OFF — Check power cable and display.
""")
        sys.exit(1)

    # Show results
    print(bold("\n  STEP 3: Results\n"))

    if len(matches) > 1:
        # Multiple matches — pick the one with most bytes at simplest config
        print(f"  Found {len(matches)} working configurations:")
        for i, m in enumerate(matches):
            w_text = f", {m['weight']:.1f} kg" if m.get("weight") is not None else ""
            print(f"    {i + 1}. {m['port']} @ {m['baud']} {m['label']} "
                  f"({m['bytes']} bytes, {m['pct']}% printable{w_text})")

        # Prefer 8N1 > 7E1 > others, then highest byte count
        priority = {"8N1": 0, "7E1": 1, "7O1": 2, "8E1": 3}
        matches.sort(key=lambda m: (priority.get(m["label"], 9), -m["bytes"]))

    best = matches[0]
    w_text = f"{best['weight']:.1f} kg" if best.get("weight") is not None else "detected"

    print(green(f"\n  DETECTED: {best['port']} @ {best['baud']} baud {best['label']} "
                f"— Weight: {w_text}"))

    if scan_only:
        print(f"\n  To save this config, re-run without --scan-only")
        print(f"\n  Config to use:")
        print(f"    com_port:  {best['port']}")
        print(f"    baud_rate: {best['baud']}")
        print(f"    data_bits: {best['data_bits']}")
        print(f"    parity:    {best['parity']}")
        print(f"    stop_bits: {best['stop_bits']}")
        sys.exit(0)

    # Write config
    print(bold("\n  STEP 4: Writing configuration...\n"))

    cfg = write_config(best)
    print(green(f"  Saved to: {CONFIG_FILE}"))
    print(f"\n  Configuration written:")
    print(f"    {{")
    print(f'      "com_port":  "{cfg["com_port"]}",')
    print(f'      "baud_rate": {cfg["baud_rate"]},')
    print(f'      "data_bits": {cfg["data_bits"]},')
    print(f'      "parity":    "{cfg["parity"]}",')
    print(f'      "stop_bits": {cfg["stop_bits"]}')
    print(f"    }}")

    # Validate
    print(bold("\n  STEP 5: Validating with live read...\n"))
    success = validate_config(cfg)

    # Manual steps
    print_manual_steps(cfg)

    if success:
        print(green(bold("  Setup complete! Restart the services to apply.\n")))
    else:
        print(yellow(bold("  Setup saved but validation had warnings. "
                          "Check the manual steps above.\n")))

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
