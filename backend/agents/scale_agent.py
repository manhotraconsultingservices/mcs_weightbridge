"""
Weighbridge Scale Agent — reads weight from COM port and pushes to cloud.

Runs on client PC. Connects to the weighbridge indicator via RS232/USB
serial port, reads weight continuously, and sends readings to the cloud
server via POST /api/v1/weight/external-reading.

Usage:
  python scale_agent.py                  # run interactively
  python scale_agent.py --setup          # generate config
  python scale_agent.py --install        # install as Windows service
  python scale_agent.py --uninstall      # remove Windows service

Config: scale_config.json (same directory)
"""

import copy
import json
import time
import sys
import re
import logging
import threading
import signal
from datetime import datetime
from pathlib import Path

# ── Logging ──────────────────────────────────────────────────────────────────

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "scale_agent.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("scale_agent")

# ── Config ───────────────────────────────────────────────────────────────────

CONFIG_FILE = Path(__file__).parent / "scale_config.json"

DEFAULT_CONFIG = {
    "cloud_url": "https://weighbridgesetu.com",
    "tenant_slug": "",
    "agent_key": "",
    "port": "COM3",
    "baud_rate": 9600,
    "data_bits": 8,
    "stop_bits": 1,
    "parity": "N",
    "push_interval_ms": 500,
    "status_port": 9002,
}


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        log.error("Config not found: %s", CONFIG_FILE)
        log.info("Run: python scale_agent.py --setup")
        sys.exit(1)
    # utf-8-sig transparently strips an optional BOM. PowerShell's
    # `Out-File -Encoding utf8` on Windows PowerShell 5.1 writes one by
    # default, which Python's plain utf-8 reader rejects. Accept both.
    with open(CONFIG_FILE, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def save_config(cfg: dict):
    # Write plain UTF-8 (no BOM) so the file round-trips cleanly between
    # PowerShell, editors, and Python's json reader.
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    log.info("Config saved to %s", CONFIG_FILE)


def setup_wizard():
    """Interactive setup to generate scale_config.json."""
    print("\n" + "=" * 60)
    print("  Weighbridge Scale Agent — Setup")
    print("=" * 60 + "\n")

    cfg = copy.deepcopy(DEFAULT_CONFIG)

    cfg["cloud_url"] = input(f"Cloud URL [{cfg['cloud_url']}]: ").strip() or cfg["cloud_url"]
    cfg["tenant_slug"] = input("Tenant slug (e.g. ziya-ore-minerals): ").strip()
    cfg["agent_key"] = input("Agent API key (from platform admin): ").strip()

    # List available COM ports
    try:
        import serial.tools.list_ports
        ports = list(serial.tools.list_ports.comports())
        if ports:
            print("\n  Available COM ports:")
            for p in ports:
                print(f"    {p.device} — {p.description}")
        else:
            print("\n  No COM ports found. Connect the USB-Serial cable first.")
    except ImportError:
        print("  (pyserial not installed — pip install pyserial)")

    cfg["port"] = input(f"\nCOM port [{cfg['port']}]: ").strip() or cfg["port"]
    baud = input(f"Baud rate [{cfg['baud_rate']}]: ").strip()
    if baud:
        cfg["baud_rate"] = int(baud)

    print("\nData format (check your indicator manual):")
    print("  Indian brands (Essae/Leo): 7 data bits, Even parity")
    print("  International brands:      8 data bits, No parity")
    db = input(f"Data bits (7 or 8) [{cfg['data_bits']}]: ").strip()
    if db:
        cfg["data_bits"] = int(db)
    par = input(f"Parity (N=None, E=Even, O=Odd) [{cfg['parity']}]: ").strip().upper()
    if par:
        cfg["parity"] = par

    save_config(cfg)
    print(f"\n  Config saved: {CONFIG_FILE}")
    print(f"  Start: python scale_agent.py")
    print(f"  Install as service: python scale_agent.py --install")
    print()


# ── Scale Reader ─────────────────────────────────────────────────────────────

class ScaleReader:
    """Reads weight from serial port and pushes to cloud API."""

    def __init__(self, config: dict):
        self.cfg = config
        self.running = False
        self.last_weight = -1.0   # sentinel: -1 means "never read"
        self.connected = False
        self.push_count = 0
        self.error_count = 0
        # Cloud reachability — live weight is non-transactional, so we don't
        # buffer readings (replaying stale weights would be wrong); we just
        # surface whether the last push reached the cloud so the offline state
        # is observable. Token creation resilience lives in the PWA queue.
        self.cloud_online = True
        self._thread = None
        self._last_push_time = 0.0

    def start(self):
        self.running = True
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        log.info("Scale reader started on %s @ %d baud", self.cfg["port"], self.cfg["baud_rate"])

    def stop(self):
        self.running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _read_loop(self):
        import queue as _queue
        import serial
        import requests

        port = self.cfg["port"]
        baud = self.cfg["baud_rate"]

        # Map to pyserial constants
        bytesize_map = {5: serial.FIVEBITS, 6: serial.SIXBITS, 7: serial.SEVENBITS, 8: serial.EIGHTBITS}
        stopbits_map = {1: serial.STOPBITS_ONE, 1.5: serial.STOPBITS_ONE_POINT_FIVE, 2: serial.STOPBITS_TWO}
        parity_map = {"N": serial.PARITY_NONE, "E": serial.PARITY_EVEN, "O": serial.PARITY_ODD}

        byte_size = bytesize_map.get(self.cfg.get("data_bits", 8), serial.EIGHTBITS)
        stop_bits = stopbits_map.get(self.cfg.get("stop_bits", 1), serial.STOPBITS_ONE)
        parity = parity_map.get(self.cfg.get("parity", "N"), serial.PARITY_NONE)

        push_interval = self.cfg.get("push_interval_ms", 500) / 1000.0
        api_url = f"{self.cfg['cloud_url'].rstrip('/')}/api/v1/weight/external-reading"

        # ── Non-blocking HTTP push via background thread ──────────────────────
        # Posting to the cloud inside the serial-read thread blocks for up to
        # 5 s on each request (network latency / timeout). That stalls serial
        # reads and lets the OS buffer fill with hundreds of unread frames,
        # causing the parser to see jumbled multi-frame chunks. Instead, queue
        # payloads and let a dedicated daemon thread do the HTTP work.
        push_q: _queue.Queue = _queue.Queue(maxsize=20)

        def _push_worker():
            while self.running or not push_q.empty():
                try:
                    payload = push_q.get(timeout=2)
                except _queue.Empty:
                    continue
                try:
                    requests.post(api_url, json=payload, timeout=5)
                    self.push_count += 1
                    if not self.cloud_online:
                        log.info("Cloud reachable again — weight streaming resumed")
                    self.cloud_online = True
                except requests.RequestException as e:
                    self.error_count += 1
                    self.cloud_online = False
                    if self.error_count % 50 == 1:
                        log.warning("Cloud unreachable (count=%d): %s", self.error_count, e)

        push_thread = threading.Thread(target=_push_worker, daemon=True, name="scale-push")
        push_thread.start()

        reconnect_delay = 5
        buffer = b""

        while self.running:
            ser = None
            try:
                log.info("Connecting to scale on %s ...", port)
                ser = serial.Serial(
                    port=port, baudrate=baud, bytesize=byte_size,
                    stopbits=stop_bits, parity=parity, timeout=2,
                )
                # DTR/RTS — many Indian indicators won't transmit without these.
                ser.dtr = True
                ser.rts = True
                ser.reset_input_buffer()
                self.connected = True
                log.info("Scale connected: %s (DTR=on, RTS=on)", port)
                reconnect_delay = 5

                while self.running:
                    # Grab whatever is waiting; if nothing, block up to 2 s.
                    chunk = ser.read(ser.in_waiting or 1)
                    if not chunk:
                        continue

                    buffer += chunk

                    # ── Frame-based parsing (CR/LF delimited) ─────────────
                    # Process every complete line before sleeping.  Most Indian
                    # indicators end frames with CR, LF, or CRLF.  Parsing only
                    # complete frames prevents the regex from matching across two
                    # partial frames when the buffer is flushed in bulk.
                    while True:
                        cr = buffer.find(b'\r')
                        lf = buffer.find(b'\n')
                        # Pick the earliest delimiter.
                        candidates = [p for p in (cr, lf) if p >= 0]
                        if not candidates:
                            break
                        delim = min(candidates)
                        frame = buffer[:delim]
                        # Consume delimiter (and a trailing LF after CR).
                        rest = buffer[delim + 1:]
                        if rest and rest[0:1] == b'\n':
                            rest = rest[1:]
                        buffer = rest

                        # Strip STX (0x02) and other control bytes before parsing.
                        clean = bytes(b for b in frame if b >= 0x20)
                        if not clean:
                            continue

                        weight = self._parse_frame(clean)
                        if weight is None:
                            continue

                        now = time.time()
                        # Push if weight changed by more than 1 kg OR interval elapsed.
                        if (abs(weight - self.last_weight) >= 1.0 or
                                now - self._last_push_time >= push_interval):
                            self.last_weight = weight
                            self._last_push_time = now
                            payload = {
                                "weight_kg": weight,
                                "tenant": self.cfg["tenant_slug"],
                                "agent_key": self.cfg["agent_key"],
                                "raw": clean.decode("ascii", errors="replace"),
                            }
                            try:
                                push_q.put_nowait(payload)
                            except _queue.Full:
                                pass  # drop — queue has 20 slots; cloud is lagging

                    # Delimiter-free fallback: some indicators (Leo FSD 501) emit
                    # continuous repeating blocks without CR/LF.  If the buffer
                    # has accumulated ≥16 bytes without a delimiter, try parsing
                    # the whole thing and keep only the last 16 bytes.
                    if len(buffer) >= 16:
                        clean = bytes(b for b in buffer if b >= 0x20)
                        weight = self._parse_frame(clean)
                        if weight is not None:
                            now = time.time()
                            if (abs(weight - self.last_weight) >= 1.0 or
                                    now - self._last_push_time >= push_interval):
                                self.last_weight = weight
                                self._last_push_time = now
                                try:
                                    push_q.put_nowait({
                                        "weight_kg": weight,
                                        "tenant": self.cfg["tenant_slug"],
                                        "agent_key": self.cfg["agent_key"],
                                        "raw": clean.decode("ascii", errors="replace"),
                                    })
                                except _queue.Full:
                                    pass
                        buffer = buffer[-16:]

                    # Absolute overflow guard.
                    if len(buffer) > 4096:
                        buffer = buffer[-256:]

            except Exception as e:
                self.connected = False
                log.warning("Scale error on %s: %s — reconnecting in %ds", port, e, reconnect_delay)
                time.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 60)
            finally:
                if ser is not None:
                    try:
                        ser.close()
                    except Exception:
                        pass

    def _parse_frame(self, data: bytes) -> float | None:
        """Extract weight from a single complete indicator frame.

        Handles common Indian weighbridge formats:
          NT   12345 kg   (Essae, Leo — no decimal, kg int)
          ST   12345.00   (stable, decimal)
               012345     (bare digits)
          k      0k      0  (Leo FSD 501 continuous, no delimiter)
        Returns the numeric weight as a float (kg), or None if not parseable.
        Zero IS a valid weight (empty scale / truck driven off).
        """
        try:
            text = data.decode("ascii", errors="replace").strip()
            if not text:
                return None
            # Match 1–6 digits optionally followed by up to 3 decimal places.
            # Word-boundary anchors avoid matching partial strings like "31" in "COM31".
            matches = re.findall(r'(?<!\d)(\d{1,6}(?:\.\d{1,3})?)(?!\d)', text)
            if not matches:
                return None
            weights = [float(m) for m in matches]
            weight = max(weights)
            if 0.0 <= weight < 200000.0:
                return weight
        except Exception:
            pass
        return None


# ── Status API ───────────────────────────────────────────────────────────────

class StatusServer:
    def __init__(self, reader: ScaleReader, port: int = 9002):
        self.reader = reader
        self.port = port

    def start(self):
        from http.server import HTTPServer, BaseHTTPRequestHandler
        reader = self.reader

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps({
                    "service": "scale_agent",
                    "status": "running",
                    "timestamp": datetime.now().isoformat(),
                    "scale_connected": reader.connected,
                    "cloud_online": reader.cloud_online,
                    "last_weight_kg": reader.last_weight,
                    "push_count": reader.push_count,
                    "error_count": reader.error_count,
                    "port": reader.cfg["port"],
                })
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body.encode())

            def log_message(self, *args):
                pass

        def _serve():
            try:
                HTTPServer(("127.0.0.1", self.port), Handler).serve_forever()
            except OSError as e:
                log.warning("Status server port %d: %s", self.port, e)

        threading.Thread(target=_serve, daemon=True).start()
        log.info("Status API: http://127.0.0.1:%d", self.port)


# ── Windows Service Install ──────────────────────────────────────────────────

def install_service():
    """Install as Windows service using NSSM."""
    import shutil
    import subprocess

    nssm = shutil.which("nssm")
    if not nssm:
        print("NSSM not found. Download from https://nssm.cc and add to PATH.")
        sys.exit(1)

    python = sys.executable
    script = str(Path(__file__).resolve())
    name = "WeighbridgeScaleAgent"

    subprocess.run([nssm, "install", name, python, script], check=True)
    subprocess.run([nssm, "set", name, "AppDirectory", str(Path(__file__).parent)], check=True)
    subprocess.run([nssm, "set", name, "AppStdout", str(LOG_DIR / "scale_service_stdout.log")], check=True)
    subprocess.run([nssm, "set", name, "AppStderr", str(LOG_DIR / "scale_service_stderr.log")], check=True)
    subprocess.run([nssm, "set", name, "AppRotateFiles", "1"], check=True)
    subprocess.run([nssm, "set", name, "AppRotateBytes", "10485760"], check=True)
    subprocess.run([nssm, "set", name, "Description", "Weighbridge Scale Agent - reads weight and pushes to cloud"], check=True)
    subprocess.run([nssm, "start", name], check=True)
    print(f"\n  Service '{name}' installed and started.")
    print(f"  Check: nssm status {name}")
    print(f"  Logs:  {LOG_DIR}")


def uninstall_service():
    import shutil
    import subprocess
    nssm = shutil.which("nssm")
    if not nssm:
        print("NSSM not found.")
        sys.exit(1)
    name = "WeighbridgeScaleAgent"
    subprocess.run([nssm, "stop", name], check=False)
    subprocess.run([nssm, "remove", name, "confirm"], check=True)
    print(f"  Service '{name}' removed.")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    if "--setup" in sys.argv:
        setup_wizard()
        return
    if "--install" in sys.argv:
        install_service()
        return
    if "--uninstall" in sys.argv:
        uninstall_service()
        return

    cfg = load_config()

    if not cfg.get("tenant_slug") or not cfg.get("agent_key"):
        log.error("tenant_slug and agent_key required in scale_config.json")
        log.info("Run: python scale_agent.py --setup")
        sys.exit(1)

    print()
    print("=" * 50)
    print("  Weighbridge Scale Agent")
    print(f"  Cloud:  {cfg['cloud_url']}")
    print(f"  Tenant: {cfg['tenant_slug']}")
    print(f"  Port:   {cfg['port']} @ {cfg['baud_rate']} baud")
    print("=" * 50)
    print()

    # Verify cloud
    try:
        import requests
        r = requests.get(f"{cfg['cloud_url'].rstrip('/')}/api/v1/health", timeout=10)
        log.info("Cloud: %s (status: %s)", cfg["cloud_url"], r.json().get("status"))
    except Exception as e:
        log.warning("Cloud unreachable: %s — will retry", e)

    reader = ScaleReader(cfg)
    reader.start()

    StatusServer(reader, port=cfg.get("status_port", 9002)).start()

    log.info("Running. Press Ctrl+C to stop.")

    def _shutdown(sig, frame):
        log.info("Shutting down...")
        reader.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _shutdown)

    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
