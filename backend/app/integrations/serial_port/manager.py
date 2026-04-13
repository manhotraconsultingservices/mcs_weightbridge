"""
WeightScaleManager — asyncio-based serial port reader with WebSocket broadcast.

Supports:
  - Continuous output protocols  (Leo, Essae, Avery, Generic, etc.)
  - Query-response protocols     (Mettler Toledo SICS — sends "S\\r\\n" request)
  - RS485 Modbus RTU             (sends Modbus read-holding-registers request)
  - Auto-reconnect on disconnect
  - Stability detection
  - WebSocket broadcast to all connected clients
"""
import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, Set

from fastapi import WebSocket

from app.integrations.serial_port.protocols import (
    get_protocol, WeightProtocol, RS485ModbusProtocol, MettlerToledoProtocol
)

log = logging.getLogger(__name__)


# ── CH340 Error 31 auto-recovery ──────────────────────────────────────────── #

def _try_reset_ch340(port: str) -> bool:
    """
    Detect and recover CH340 USB-serial adapter from Error 31
    (Windows driver wedge). Cycles the device via PowerShell PnP commands.
    Returns True if a device was reset, False if no action taken.
    """
    import subprocess
    import re

    try:
        # Find instance ID of the CH340 device on the configured port
        result = subprocess.run(
            ["powershell", "-Command",
             f"Get-PnpDevice | Where-Object {{ $_.FriendlyName -like '*({port})*' }} | Select-Object -ExpandProperty InstanceId"],
            capture_output=True, text=True, timeout=10,
        )
        instance_id = result.stdout.strip()
        if not instance_id:
            log.debug("No PnP device found for port %s", port)
            return False

        # Take only the first line if multiple matches
        instance_id = instance_id.splitlines()[0].strip()
        log.warning("Attempting CH340 device reset for %s (InstanceId: %s)", port, instance_id)

        # Disable the device
        subprocess.run(
            ["powershell", "-Command",
             f"Disable-PnpDevice -InstanceId '{instance_id}' -Confirm:$false"],
            capture_output=True, text=True, timeout=10,
        )

        import time
        time.sleep(3)

        # Re-enable the device
        subprocess.run(
            ["powershell", "-Command",
             f"Enable-PnpDevice -InstanceId '{instance_id}' -Confirm:$false"],
            capture_output=True, text=True, timeout=10,
        )

        time.sleep(2)
        log.info("CH340 device reset complete for %s", port)
        return True

    except Exception as e:
        log.warning("CH340 auto-reset failed: %s", e)
        return False


@dataclass
class WeightReading:
    weight_kg: float
    is_stable: bool
    stable_duration_sec: float
    scale_connected: bool
    raw: str = ""


@dataclass
class WeightScaleManager:
    port: str = "COM1"
    baud_rate: int = 9600
    data_bits: int = 8
    stop_bits: int = 1
    parity: str = "N"           # N=None, E=Even, O=Odd
    protocol_name: str = "generic"
    protocol_config: dict = field(default_factory=dict)
    stability_readings: int = 5
    stability_tolerance_kg: float = 20.0

    # Internal state — not in __init__
    _clients: Set[WebSocket] = field(default_factory=set, init=False, repr=False)
    _latest: Optional[WeightReading] = field(default=None, init=False)
    _running: bool = field(default=False, init=False)
    _serial_open: bool = field(default=False, init=False)
    _task: Optional[asyncio.Task] = field(default=None, init=False)
    _protocol: Optional[WeightProtocol] = field(default=None, init=False)

    def __post_init__(self):
        self._clients: Set[WebSocket] = set()
        self._protocol = get_protocol(self.protocol_name, self.protocol_config)
        self._recent: deque[float] = deque(maxlen=max(self.stability_readings, 2))
        self._stable_since: Optional[float] = None
        self._retry_delay: float = 5.0  # exponential backoff: 5 → 10 → 20 → 60 max

    # ── Public API ────────────────────────────────────────────────────────── #

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name="weight-scale-reader")
        log.info("WeightScaleManager started: %s @ %d baud [%s]",
                 self.port, self.baud_rate, self.protocol_name)

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._clients.add(ws)
        if self._latest:
            await self._send_one(ws, self._latest)

    async def disconnect(self, ws: WebSocket):
        self._clients.discard(ws)

    @property
    def latest(self) -> Optional[WeightReading]:
        return self._latest

    @property
    def is_connected(self) -> bool:
        return self._running and self._serial_open

    # ── Internal loop ─────────────────────────────────────────────────────── #

    async def _run_loop(self):
        import serial

        is_modbus = isinstance(self._protocol, RS485ModbusProtocol)
        is_query = isinstance(self._protocol, MettlerToledoProtocol)
        loop = asyncio.get_running_loop()

        while self._running:
            ser = None
            try:
                parity_map = {"N": serial.PARITY_NONE, "E": serial.PARITY_EVEN, "O": serial.PARITY_ODD}
                stop_map = {1: serial.STOPBITS_ONE, 2: serial.STOPBITS_TWO}

                def _open_serial():
                    s = serial.Serial(
                        port=self.port,
                        baudrate=self.baud_rate,
                        bytesize=self.data_bits,
                        parity=parity_map.get(self.parity, serial.PARITY_NONE),
                        stopbits=stop_map.get(self.stop_bits, serial.STOPBITS_ONE),
                        timeout=2.0,
                        write_timeout=1.0,
                    )
                    # Enable DTR and RTS — many indicators require these signals
                    # to be HIGH before they transmit. Terminal apps set these by default.
                    s.dtr = True
                    s.rts = True
                    # Flush stale data from OS buffer
                    s.reset_input_buffer()
                    return s

                ser = await loop.run_in_executor(None, _open_serial)
                self._serial_open = True
                self._retry_delay = 5.0  # reset backoff on successful connect
                log.info("Serial port %s opened (protocol=%s, DTR=on, RTS=on)", self.port, self.protocol_name)

                # Accumulator for partial frames (key/print mode sends data sporadically)
                _buffer = b""

                while self._running:
                    if is_modbus:
                        request = self._protocol.build_request()
                        await loop.run_in_executor(None, lambda s=ser: s.write(request))
                        await asyncio.sleep(0.05)
                        raw = await loop.run_in_executor(None, lambda s=ser: s.read(64))
                        await asyncio.sleep(0.15)
                        if not raw:
                            continue
                    elif is_query:
                        cmd = self._protocol.query_command()
                        await loop.run_in_executor(None, lambda s=ser: s.write(cmd))
                        raw = await loop.run_in_executor(None, lambda s=ser: s.readline())
                        await asyncio.sleep(0.05)
                        if not raw:
                            continue
                    else:
                        # Robust read: grab ALL available bytes from the buffer,
                        # then try readline. This handles both continuous mode
                        # (data flows constantly) and key/print mode (data arrives
                        # in bursts when operator presses Print).
                        def _read_any(s=ser):
                            # First check if any bytes are waiting
                            waiting = s.in_waiting
                            if waiting > 0:
                                return s.read(waiting)
                            # Nothing waiting — block up to timeout for a line
                            return s.readline()

                        chunk = await loop.run_in_executor(None, _read_any)
                        if not chunk:
                            continue

                        # Accumulate bytes and split into frames
                        _buffer += chunk

                        # Process frames delimited by STX (0x02), CR/LF, or any combo
                        while True:
                            # Find frame boundaries
                            stx_pos = _buffer.find(b'\x02', 1)  # next STX after pos 0
                            cr_pos = _buffer.find(b'\r')
                            lf_pos = _buffer.find(b'\n')

                            positions = []
                            if stx_pos > 0:
                                positions.append(stx_pos)
                            if cr_pos >= 0:
                                positions.append(cr_pos)
                            if lf_pos >= 0:
                                positions.append(lf_pos)

                            if not positions:
                                break

                            split_at = min(positions)
                            raw = _buffer[:split_at]
                            if split_at == stx_pos:
                                _buffer = _buffer[split_at:]  # keep STX for next frame
                            else:
                                _buffer = _buffer[split_at + 1:]
                                if _buffer and _buffer[0:1] == b'\n':
                                    _buffer = _buffer[1:]

                            # Clean: remove STX control char before parsing
                            clean = raw.replace(b'\x02', b'')
                            if clean.strip():
                                weight = self._protocol.parse(clean)
                                if weight is not None:
                                    reading = self._make_reading(weight, clean, loop)
                                    self._latest = reading
                                    await self._broadcast(reading)

                        # Fallback: delimiter-less continuous output (e.g. Leo FSD 501)
                        # Format: "k      0k      0" — no STX/CR/LF, just repeating.
                        # Try parsing the raw buffer directly if no frames were found.
                        if len(_buffer) >= 8:
                            clean = _buffer.replace(b'\x02', b'')
                            if clean.strip():
                                weight = self._protocol.parse(clean)
                                if weight is not None:
                                    reading = self._make_reading(weight, clean, loop)
                                    self._latest = reading
                                    await self._broadcast(reading)
                                    # Keep only tail to prevent stale data
                                    _buffer = _buffer[-16:]

                        # Prevent buffer from growing forever
                        if len(_buffer) > 512:
                            _buffer = _buffer[-256:]
                        continue

                    weight = self._protocol.parse(raw)
                    if weight is not None:
                        reading = self._make_reading(weight, raw, loop)
                        self._latest = reading
                        await self._broadcast(reading)

            except Exception as exc:
                self._serial_open = False
                exc_str = str(exc)
                log.warning("Serial error: %s — retrying in %.0fs", exc, self._retry_delay)
                disconnected = WeightReading(
                    weight_kg=0.0,
                    is_stable=False,
                    stable_duration_sec=0.0,
                    scale_connected=False,
                )
                self._latest = disconnected
                await self._broadcast(disconnected)

                # CH340 Error 31 auto-recovery: cycle the USB device driver
                if "31" in exc_str and ("not functioning" in exc_str or "PermissionError" in exc_str):
                    log.warning("Detected CH340 Error 31 — attempting automatic device reset")
                    reset_ok = await loop.run_in_executor(None, _try_reset_ch340, self.port)
                    if reset_ok:
                        self._retry_delay = 5.0  # reset backoff after successful device cycle
                        await asyncio.sleep(3)   # short wait after reset
                        continue                 # retry immediately

                await asyncio.sleep(self._retry_delay)
                # Exponential backoff: 5 → 10 → 20 → 40 → 60 (capped)
                self._retry_delay = min(self._retry_delay * 2, 60.0)
            finally:
                self._serial_open = False
                if ser and ser.is_open:
                    try:
                        ser.close()
                        log.info("Serial port %s closed cleanly", self.port)
                    except Exception:
                        pass

    def _make_reading(self, weight: float, raw: bytes, loop=None) -> WeightReading:
        now = (loop or asyncio.get_running_loop()).time()
        self._recent.append(weight)
        is_stable = False
        stable_duration = 0.0

        if len(self._recent) >= 2:
            spread = max(self._recent) - min(self._recent)
            if spread <= self.stability_tolerance_kg:
                if self._stable_since is None:
                    self._stable_since = now
                stable_duration = now - self._stable_since
                is_stable = len(self._recent) >= self._recent.maxlen
            else:
                self._stable_since = None

        return WeightReading(
            weight_kg=round(weight, 2),
            is_stable=is_stable,
            stable_duration_sec=round(stable_duration, 1),
            scale_connected=True,
            raw=raw.decode("ascii", errors="ignore").strip(),
        )

    async def _broadcast(self, reading: WeightReading):
        if not self._clients:
            return
        payload = {
            "weight_kg": reading.weight_kg,
            "is_stable": reading.is_stable,
            "stable_duration_sec": reading.stable_duration_sec,
            "scale_connected": reading.scale_connected,
        }
        dead: Set[WebSocket] = set()
        for ws in list(self._clients):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.add(ws)
        self._clients -= dead

    async def _send_one(self, ws: WebSocket, reading: WeightReading):
        try:
            await ws.send_json({
                "weight_kg": reading.weight_kg,
                "is_stable": reading.is_stable,
                "stable_duration_sec": reading.stable_duration_sec,
                "scale_connected": reading.scale_connected,
            })
        except Exception:
            pass


# ── Singleton ─────────────────────────────────────────────────────────────── #

weight_manager: Optional[WeightScaleManager] = None


def get_weight_manager() -> Optional[WeightScaleManager]:
    return weight_manager


async def init_weight_manager(
    port: str,
    baud_rate: int,
    protocol: str,
    protocol_config: dict,
    stability_readings: int,
    stability_tolerance_kg: float,
    data_bits: int = 8,
    stop_bits: int = 1,
    parity: str = "N",
):
    global weight_manager
    if weight_manager and weight_manager._running:
        await weight_manager.stop()
    weight_manager = WeightScaleManager(
        port=port,
        baud_rate=baud_rate,
        data_bits=data_bits,
        stop_bits=stop_bits,
        parity=parity,
        protocol_name=protocol,
        protocol_config=protocol_config,
        stability_readings=stability_readings,
        stability_tolerance_kg=stability_tolerance_kg,
    )
    await weight_manager.start()


# ── Port scanner utility ───────────────────────────────────────────────────── #

def _scan_ports_win32() -> list[dict]:
    """
    Windows-native port scan using PnP and Registry — no pyserial needed.
    Returns [{"port": "COM4", "description": "USB-SERIAL CH340 (COM4)", ...}]
    """
    import re, subprocess, winreg
    ports = []

    # Method 1: PowerShell PnP query — finds USB-serial adapters with friendly names
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             "Get-PnpDevice -Class Ports -Status OK | Select-Object -Property FriendlyName | Format-Table -HideTableHeaders"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().splitlines():
                line = line.strip()
                if not line:
                    continue
                m = re.search(r"\(COM(\d+)\)", line)
                if m:
                    port_name = f"COM{m.group(1)}"
                    ports.append({
                        "port": port_name,
                        "description": line,
                        "hwid": "",
                        "manufacturer": None,
                    })
    except Exception as e:
        log.debug("PnP scan failed: %s", e)

    # Method 2: Registry fallback — works even without PnP access
    if not ports:
        try:
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DEVICEMAP\SERIALCOMM",
            )
            i = 0
            while True:
                try:
                    name, port_val, _ = winreg.EnumValue(key, i)
                    ports.append({
                        "port": port_val,
                        "description": name,
                        "hwid": "",
                        "manufacturer": None,
                    })
                    i += 1
                except OSError:
                    break
            winreg.CloseKey(key)
        except Exception as e:
            log.debug("Registry scan failed: %s", e)

    return sorted(ports, key=lambda x: x["port"])


def scan_serial_ports() -> list[dict]:
    """
    Return list of available COM ports.
    Tries pyserial first (cross-platform), falls back to Windows-native methods.
    """
    # Try pyserial first
    try:
        import serial.tools.list_ports
        ports = []
        for p in serial.tools.list_ports.comports():
            ports.append({
                "port": p.device,
                "description": p.description,
                "hwid": p.hwid,
                "manufacturer": getattr(p, "manufacturer", None),
            })
        if ports:
            return sorted(ports, key=lambda x: x["port"])
        log.debug("pyserial found 0 ports, trying Win32 fallback")
    except Exception as e:
        log.debug("pyserial scan failed: %s — trying Win32 fallback", e)

    # Fallback: Windows-native (registry + PnP)
    import sys
    if sys.platform == "win32":
        try:
            return _scan_ports_win32()
        except Exception as e:
            log.warning("Win32 port scan failed: %s", e)

    return []


_SKIP_PORTS = {"intel", "amt", "bluetooth", "bt ", "modem"}
_AUTO_BAUD_RATES = [1200, 2400, 4800, 9600, 19200]


async def auto_detect_scale() -> dict:
    """
    Scan all COM ports at common baud rates + serial configs (8N1, 7E1, 7O1),
    return the one that receives weight data.
    Uses Win32 API directly so it works even when pyserial is unavailable.
    Returns {"port": "COM4", "baud_rate": 9600, "data_bits": 7, "parity": "E",
             "stop_bits": 1, "description": "..."} or {"port": None, ...}
    """
    import sys
    if sys.platform != "win32":
        return {"port": None, "baud_rate": None, "error": "Auto-detect only available on Windows"}

    loop = asyncio.get_running_loop()

    ports = scan_serial_ports()
    # Filter out non-serial devices
    candidates = [
        p for p in ports
        if not any(skip in p["description"].lower() for skip in _SKIP_PORTS)
    ]

    if not candidates:
        return {
            "port": None, "baud_rate": None,
            "candidates_found": len(ports),
            "error": "No USB-serial ports found. Check cable and adapter driver.",
        }

    log.info("Auto-detect: scanning %d port(s): %s",
             len(candidates), ", ".join(p["port"] for p in candidates))

    # Serial configs to try: (data_bits, parity_str, parity_win32, stop_bits)
    _SERIAL_CONFIGS = [
        (8, "N", 0, 1),   # 8N1
        (7, "E", 2, 1),   # 7E1 — Leo, Essae, Avery, most Indian indicators
        (7, "O", 1, 1),   # 7O1 — rare
    ]

    best = None  # (port, baud, bytes_count, printable_pct, description, db, par, sb)

    for p in candidates:
        port = p["port"]
        for baud in _AUTO_BAUD_RATES:
            for db, par_str, par_win, sb in _SERIAL_CONFIGS:
                serial_label = f"{db}{par_str}{sb}"
                log.info("Auto-detect: probing %s @ %d baud %s...", port, baud, serial_label)

                def _probe(port=port, baud=baud, db=db, par_str=par_str, par_win=par_win, sb=sb):
                    """Probe a port for weight data using Win32 API."""
                    try:
                        import ctypes, ctypes.wintypes
                        GENERIC_READ = 0x80000000
                        GENERIC_WRITE = 0x40000000
                        OPEN_EXISTING = 3
                        FILE_ATTRIBUTE_NORMAL = 0x80
                        INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
                        DTR_CONTROL_ENABLE = 0x01
                        RTS_CONTROL_ENABLE = 0x01
                        SETDTR = 5
                        SETRTS = 3
                        PURGE_RXCLEAR = 0x0008
                        PURGE_TXCLEAR = 0x0004

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

                        k32 = ctypes.windll.kernel32
                        # Pre-configure via MODE command
                        import subprocess as _sp
                        p_char = par_str.lower()
                        _sp.run(f"mode {port} baud={baud} parity={p_char} data={db} stop={sb} dtr=on rts=on",
                                shell=True, capture_output=True, timeout=5)

                        handle = k32.CreateFileW(
                            f"\\\\.\\{port}",
                            GENERIC_READ | GENERIC_WRITE,
                            0, None, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None,
                        )
                        if handle == INVALID_HANDLE_VALUE or handle == -1:
                            return (0, 0)

                        # Configure DCB
                        dcb = DCB()
                        dcb.DCBlength = ctypes.sizeof(DCB)
                        k32.GetCommState(handle, ctypes.byref(dcb))
                        dcb.BaudRate = baud
                        dcb.ByteSize = db
                        dcb.Parity = par_win
                        dcb.StopBits = 0 if sb == 1 else 2
                        dcb.fParity = 1 if par_str != "N" else 0
                        dcb.fDtrControl = DTR_CONTROL_ENABLE
                        dcb.fRtsControl = RTS_CONTROL_ENABLE
                        dcb.fAbortOnError = 0
                        k32.SetCommState(handle, ctypes.byref(dcb))

                        timeouts = COMMTIMEOUTS()
                        timeouts.ReadIntervalTimeout = 50
                        timeouts.ReadTotalTimeoutMultiplier = 10
                        timeouts.ReadTotalTimeoutConstant = 500
                        k32.SetCommTimeouts(handle, ctypes.byref(timeouts))
                        k32.PurgeComm(handle, PURGE_RXCLEAR | PURGE_TXCLEAR)
                        k32.EscapeCommFunction(handle, SETDTR)
                        k32.EscapeCommFunction(handle, SETRTS)

                        # Read for 3 seconds
                        import time as _time
                        buf = ctypes.create_string_buffer(256)
                        br = ctypes.wintypes.DWORD(0)
                        all_bytes = b""
                        start = _time.time()
                        while _time.time() - start < 3.0:
                            br.value = 0
                            ok = k32.ReadFile(handle, buf, 256, ctypes.byref(br), None)
                            if ok and br.value > 0:
                                all_bytes += buf.raw[:br.value]
                        k32.CloseHandle(handle)

                        if not all_bytes:
                            return (0, 0)
                        printable = sum(1 for b in all_bytes if 0x20 <= b <= 0x7E)
                        pct = int(100 * printable / len(all_bytes))
                        return (len(all_bytes), pct)

                    except Exception as exc:
                        log.debug("Probe %s @ %d %s failed: %s", port, baud, f"{db}{par_str}{sb}", exc)
                        return (0, 0)

                nbytes, pct = await loop.run_in_executor(None, _probe)
                if nbytes > 0:
                    log.info("  %s @ %d %s: %d bytes, %d%% printable",
                             port, baud, serial_label, nbytes, pct)
                    if best is None or pct > best[3] or (pct == best[3] and nbytes > best[2]):
                        best = (port, baud, nbytes, pct, p["description"], db, par_str, sb)
                    if pct >= 70:
                        return {
                            "port": port,
                            "baud_rate": baud,
                            "data_bits": db,
                            "parity": par_str,
                            "stop_bits": sb,
                            "description": p["description"],
                            "bytes_received": nbytes,
                            "printable_pct": pct,
                            "error": None,
                        }

    if best and best[3] >= 30:
        return {
            "port": best[0],
            "baud_rate": best[1],
            "data_bits": best[5],
            "parity": best[6],
            "stop_bits": best[7],
            "description": best[4],
            "bytes_received": best[2],
            "printable_pct": best[3],
            "error": None,
        }

    return {
        "port": None,
        "baud_rate": None,
        "candidates_scanned": len(candidates),
        "error": "No weight data detected on any port. Check indicator power and cable.",
    }


async def test_port_connection(
    port: str,
    baud_rate: int,
    duration_sec: int = 3,
    data_bits: int = 8,
    stop_bits: int = 1,
    parity: str = "N",
) -> dict:
    """
    Open a COM port for `duration_sec`, capture raw frames, return them.
    Used for hardware diagnostics without starting the full manager.
    """
    import serial

    parity_map = {"N": serial.PARITY_NONE, "E": serial.PARITY_EVEN, "O": serial.PARITY_ODD}
    stop_map = {1: serial.STOPBITS_ONE, 2: serial.STOPBITS_TWO}

    frames: list[dict] = []
    error = None

    try:
        ser = serial.Serial(
            port=port,
            baudrate=baud_rate,
            bytesize=data_bits,
            parity=parity_map.get(parity, serial.PARITY_NONE),
            stopbits=stop_map.get(stop_bits, serial.STOPBITS_ONE),
            timeout=2.0,
        )
        # Enable DTR and RTS — required by many indicators to start transmitting
        ser.dtr = True
        ser.rts = True
        ser.reset_input_buffer()

        loop = asyncio.get_event_loop()
        deadline = loop.time() + duration_sec

        while loop.time() < deadline:
            # Robust read: check for any waiting bytes first, then try readline
            def _read_data(s=ser):
                waiting = s.in_waiting
                if waiting > 0:
                    return s.read(waiting)
                return s.readline()

            raw = await loop.run_in_executor(None, _read_data)
            if raw:
                frames.append({
                    "hex": raw.hex(" ").upper(),
                    "ascii": raw.decode("ascii", errors="replace").strip(),
                    "bytes": len(raw),
                })
            if len(frames) >= 20:
                break

        ser.close()
    except Exception as exc:
        error = str(exc)

    return {
        "port": port,
        "baud_rate": baud_rate,
        "frames_captured": len(frames),
        "frames": frames,
        "error": error,
    }
