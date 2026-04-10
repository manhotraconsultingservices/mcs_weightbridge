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

                ser = await loop.run_in_executor(
                    None,
                    lambda: serial.Serial(
                        port=self.port,
                        baudrate=self.baud_rate,
                        bytesize=self.data_bits,
                        parity=parity_map.get(self.parity, serial.PARITY_NONE),
                        stopbits=stop_map.get(self.stop_bits, serial.STOPBITS_ONE),
                        timeout=1.0,
                        write_timeout=1.0,
                    ),
                )
                self._serial_open = True
                self._retry_delay = 5.0  # reset backoff on successful connect
                log.info("Serial port %s opened (protocol=%s)", self.port, self.protocol_name)

                while self._running:
                    # Capture ser in lambda default arg to avoid stale closure
                    if is_modbus:
                        request = self._protocol.build_request()
                        await loop.run_in_executor(None, lambda s=ser: s.write(request))
                        await asyncio.sleep(0.05)
                        raw = await loop.run_in_executor(None, lambda s=ser: s.read(64))
                        await asyncio.sleep(0.15)
                    elif is_query:
                        cmd = self._protocol.query_command()
                        await loop.run_in_executor(None, lambda s=ser: s.write(cmd))
                        raw = await loop.run_in_executor(None, lambda s=ser: s.readline())
                        await asyncio.sleep(0.05)
                    else:
                        raw = await loop.run_in_executor(None, lambda s=ser: s.readline())

                    if not raw:
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

def scan_serial_ports() -> list[dict]:
    """Return list of available COM ports on this machine."""
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
        return sorted(ports, key=lambda x: x["port"])
    except Exception as e:
        log.warning("Port scan failed: %s", e)
        return []


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
            timeout=1.0,
        )
        loop = asyncio.get_event_loop()
        deadline = loop.time() + duration_sec

        while loop.time() < deadline:
            raw = await loop.run_in_executor(None, lambda: ser.readline())
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
