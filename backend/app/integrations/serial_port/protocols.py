"""
Weight scale protocol parsers.

Supported indicators / brands:
  generic       — Any indicator with continuous ASCII weight output
  essae         — Essae Digitronics (ET-series, T-series)
  avery         — Avery Berkel / Avery Weigh-Tronix
  leo           — Leo Weighing Systems (Leo+, LeoPlus, BW series)
  mettler       — Mettler Toledo (IND series, ID1, ID5, ID7) — SICS protocol
  rice_lake     — Rice Lake (920i, 880, 820, IQ+) — same as Avery/generic
  systec        — Systec & Solutions (common Indian brand)
  tp_loadcell   — TP / Thai-weight / generic loadcell indicators (India)
  a12e          — Adam Equipment / Citizen / CAS A12E format
  rs485_modbus  — Any Modbus RTU indicator on RS485 bus (register-based)
  ci_series     — CAS CI-series indicators (common Indian brands: Transcell, Phoenix)
  digi_sm       — Digi SM-series (label printers with built-in indicator)
  kern          — Kern & Sohn precision balances (GS, DS series)

Each parser receives raw bytes (one line / frame) and returns float (kg) or None.
"""
import re
import struct
from abc import ABC, abstractmethod
from typing import Optional


class WeightProtocol(ABC):
    @abstractmethod
    def parse(self, frame: bytes) -> Optional[float]:
        """Parse a raw frame and return weight in kg, or None if invalid/unstable."""
        ...

    @property
    def brand(self) -> str:
        return self.__class__.__name__


# ─────────────────────────────────────────────────────────────────────────────
# GENERIC — works with most Indian indicator brands out of the box
# ─────────────────────────────────────────────────────────────────────────────

class GenericContinuousProtocol(WeightProtocol):
    """
    Parses continuous ASCII output containing a decimal weight value.

    Handles all common formats:
      "+  012.345 kg\\r\\n"
      "ST,GS,+,  1234.5,kg\\r\\n"   (Shimadzu-style)
      "  001234\\r\\n"               (6-digit raw)
      "12345\\r\\n"
      "W: 12345.0 KG\\r\\n"

    Config keys:
      max_weight_kg   (float, default 200000) — reject above this
      min_weight_kg   (float, default 0)      — reject below this
      decimal_places  (int, default auto)     — if indicator sends integer, divide by 10^N
    """

    def __init__(self, config: dict):
        self.max_weight = float(config.get("max_weight_kg", 200000))
        self.min_weight = float(config.get("min_weight_kg", 0))
        self.decimal_places = int(config.get("decimal_places", 0))
        # Match optional sign, digits, optional decimal
        self._pattern = re.compile(r"[-+]?\s*(\d{1,7}(?:\.\d{1,4})?)")

    def parse(self, frame: bytes) -> Optional[float]:
        try:
            text = frame.decode("ascii", errors="ignore").strip()
            if not text:
                return None
            match = self._pattern.search(text)
            if match:
                value = float(match.group(1).replace(" ", ""))
                if self.decimal_places:
                    value = value / (10 ** self.decimal_places)
                if self.min_weight <= value <= self.max_weight:
                    return value
        except Exception:
            pass
        return None


# ─────────────────────────────────────────────────────────────────────────────
# LEO WEIGHING SYSTEMS
# Leo+, LeoPlus, BW-series, Micro series
# Output: STX + 6-digit weight + status + CR + LF  (same as Essae family)
#
# Baud: 1200 / 2400 / 4800 / 9600 (set via DIP switch or menu)
# Wiring: 9-pin DB9  PIN2=RX  PIN3=TX  PIN5=GND
#
# Status byte:
#   'S' or 0x53 = Stable (NET)
#   'G' or 0x47 = Gross Stable
#   'U' or 0x55 = Unstable / motion
#   'O' or 0x4F = Overload
#   'Z' or 0x5A = Zero / Under-zero
#   'T' or 0x54 = Tare
# ─────────────────────────────────────────────────────────────────────────────

class LeoProtocol(WeightProtocol):
    """
    Leo Weighing Systems continuous RS232 output.

    Frame (10 bytes typical):
      [0]     STX  0x02
      [1]     sign '+' or '-'
      [2-7]   6 ASCII digits (e.g. "012345")
      [8]     status ('S','G','U','O','Z','T')
      [9]     CR 0x0D
      [10]    LF 0x0A  (optional)

    Config keys:
      decimal_places  (int, default 1)  — e.g. "001234" with dp=1 → 123.4 kg
      only_stable     (bool, default True) — return None if status not S/G
    """

    STX = 0x02
    STABLE_STATUS = {ord('S'), ord('G')}

    def __init__(self, config: dict):
        self.decimal_places = int(config.get("decimal_places", 1))
        self.only_stable = bool(config.get("only_stable", True))

    def parse(self, frame: bytes) -> Optional[float]:
        try:
            # Find STX in frame (may have garbage before it)
            idx = frame.find(self.STX)
            if idx == -1:
                return None
            frame = frame[idx:]
            if len(frame) < 9:
                return None

            sign = chr(frame[1])
            if sign not in ('+', '-'):
                return None

            digits = frame[2:8].decode("ascii", errors="ignore")
            if not digits.isdigit():
                return None

            status = frame[8]
            if self.only_stable and status not in self.STABLE_STATUS:
                return None

            raw = int(digits)
            value = raw / (10 ** self.decimal_places) if self.decimal_places else float(raw)
            return value if value >= 0 else None
        except Exception:
            return None


# ─────────────────────────────────────────────────────────────────────────────
# ESSAE DIGITRONICS
# ET-600D, ET-600R, T-200, T-300, T-500 (common in stone crushers)
# ─────────────────────────────────────────────────────────────────────────────

class EssaeProtocol(WeightProtocol):
    """
    Essae Digitronics RS232 continuous output.

    Frame (13+ bytes):
      [0]     STX  0x02
      [1]     sign '+' or '-'
      [2-7]   6 ASCII digits
      [8-9]   unit "kg" or "lb" (2 bytes)
      [10]    status 'S'=stable 'U'=unstable 'O'=overload 'Z'=zero
      [11]    CR
      [12]    LF

    Config keys:
      decimal_places  (int, default 0)
      only_stable     (bool, default True)
    """

    STX = 0x02

    def __init__(self, config: dict):
        self.decimal_places = int(config.get("decimal_places", 0))
        self.only_stable = bool(config.get("only_stable", True))

    def parse(self, frame: bytes) -> Optional[float]:
        try:
            idx = frame.find(self.STX)
            if idx == -1:
                return None
            frame = frame[idx:]
            if len(frame) < 11:
                return None

            sign = chr(frame[1])
            if sign not in ('+', '-'):
                return None

            digits = frame[2:8].decode("ascii", errors="ignore")
            if not digits.isdigit():
                return None

            # Status at byte 10 (after 2-byte unit field)
            if len(frame) > 10:
                status = chr(frame[10])
                if self.only_stable and status not in ('S', 'G'):
                    return None

            raw = int(digits)
            value = raw / (10 ** self.decimal_places) if self.decimal_places else float(raw)
            return value if value >= 0 else None
        except Exception:
            return None


# ─────────────────────────────────────────────────────────────────────────────
# AVERY BERKEL / AVERY WEIGH-TRONIX
# Series: L-series, ZM-series, ZK, C3000, 7650
# ─────────────────────────────────────────────────────────────────────────────

class AveryProtocol(WeightProtocol):
    """
    Avery Berkel / Avery Weigh-Tronix continuous output.

    Frame:
      [0]   STX  0x02
      [1]   status 'S'=stable 'U'=unstable 'T'=tare 'O'=over
      [2-7] 6 ASCII digits
      [8]   CR

    Config keys:
      decimal_places  (int, default 1)
      only_stable     (bool, default True)
    """

    STX = 0x02

    def __init__(self, config: dict):
        self.decimal_places = int(config.get("decimal_places", 1))
        self.only_stable = bool(config.get("only_stable", True))

    def parse(self, frame: bytes) -> Optional[float]:
        try:
            idx = frame.find(self.STX)
            if idx == -1:
                return None
            frame = frame[idx:]
            if len(frame) < 8:
                return None

            status = chr(frame[1])
            if self.only_stable and status not in ('S', 'G'):
                return None

            digits = frame[2:8].decode("ascii", errors="ignore")
            if not digits.isdigit():
                return None

            raw = int(digits)
            value = raw / (10 ** self.decimal_places) if self.decimal_places else float(raw)
            return value if value >= 0 else None
        except Exception:
            return None


# ─────────────────────────────────────────────────────────────────────────────
# METTLER TOLEDO — SICS Protocol
# IND series (IND246, IND560, IND780), ID1, ID3, ID5, ID7, XS, XP balances
#
# Uses MT-SICS (Standard Interface Command Set)
# Query mode: host sends "S\r\n" → scale replies "S S     1234.56 kg\r\n"
# Continuous: scale sends "S S     1234.56 kg\r\n" every ~20ms
#
# Reply format: "<cmd> <status> <sign><value> <unit>\r\n"
#   S = weighing
#   S = Stable (vs D=Dynamic/unstable)
# ─────────────────────────────────────────────────────────────────────────────

class MettlerToledoProtocol(WeightProtocol):
    """
    Mettler Toledo SICS continuous/query protocol.

    Frame examples:
      "S S  +    1234.56 kg\\r\\n"   — stable reading
      "S D  +    1234.56 kg\\r\\n"   — dynamic (unstable)
      "S I"                          — overload
      "S +"                          — underload

    Config keys:
      only_stable  (bool, default True)  — skip 'D' (dynamic) readings
      unit         (str, default 'kg')   — expected unit field
    """

    def __init__(self, config: dict):
        self.only_stable = bool(config.get("only_stable", True))
        self.unit = config.get("unit", "kg")
        # Pattern: S <status> <sign><spaces><digits>.<decimals> kg
        self._pat = re.compile(
            r"^S\s+([SD])\s+([-+])\s*([\d]+\.?[\d]*)\s*(" + re.escape(self.unit) + r")",
            re.IGNORECASE
        )

    def parse(self, frame: bytes) -> Optional[float]:
        try:
            text = frame.decode("ascii", errors="ignore").strip()
            m = self._pat.match(text)
            if not m:
                return None
            status, sign, value_str, _ = m.groups()
            if self.only_stable and status.upper() != 'S':
                return None
            value = float(value_str)
            if sign == '-':
                value = -value
            return value if value >= 0 else None
        except Exception:
            return None

    def query_command(self) -> bytes:
        """Command to send to scale to request current weight (query mode)."""
        return b"S\r\n"


# ─────────────────────────────────────────────────────────────────────────────
# RICE LAKE WEIGHING SYSTEMS
# 920i, 880, 820, IQ+, 380, iRite
# Uses standard ASCII continuous output (similar to generic/Avery)
# ─────────────────────────────────────────────────────────────────────────────

class RiceLakeProtocol(WeightProtocol):
    """
    Rice Lake 920i / 880 / 820 continuous ASCII output.

    Format varies by model but most output:
      "<SP>  12345.0 lb\\r\\n"   or   "  12345.0 kg\\r\\n"
    or command response:
      "GS\\r\\n12345.0\\r\\n"   (gross stable)
      "NT\\r\\n12345.0\\r\\n"   (net stable)

    Config keys:
      decimal_places  (int, default 1)
      unit            (str, default 'kg')
    """

    def __init__(self, config: dict):
        self.decimal_places = int(config.get("decimal_places", 1))
        self._pat = re.compile(r"([\d]+\.?[\d]*)")

    def parse(self, frame: bytes) -> Optional[float]:
        try:
            text = frame.decode("ascii", errors="ignore").strip()
            # Skip status-only lines
            if text in ("GS", "NT", "NL", "SD", "MD", "OL"):
                return None
            m = self._pat.search(text)
            if not m:
                return None
            value = float(m.group(1))
            if self.decimal_places and '.' not in m.group(1):
                value /= (10 ** self.decimal_places)
            return value if value >= 0 else None
        except Exception:
            return None


# ─────────────────────────────────────────────────────────────────────────────
# SYSTEC & SOLUTIONS
# Common Indian brand used in stone crushers, cement plants
# Output is very similar to generic/Essae — uses 6-digit format
# ─────────────────────────────────────────────────────────────────────────────

class SystecProtocol(WeightProtocol):
    """
    Systec continuous RS232 output.

    Frame (8-12 bytes):
      [0]   STX 0x02  (may be absent on some models — fallback to generic)
      [1]   status or sign
      [2-7] 6 ASCII digits
      [8]   ETX 0x03 or CR

    Config keys:
      decimal_places  (int, default 1)
      has_stx         (bool, default True)
      only_stable     (bool, default True)
    """

    def __init__(self, config: dict):
        self.decimal_places = int(config.get("decimal_places", 1))
        self.has_stx = bool(config.get("has_stx", True))
        self.only_stable = bool(config.get("only_stable", True))
        self._fallback = GenericContinuousProtocol(config)

    def parse(self, frame: bytes) -> Optional[float]:
        try:
            if self.has_stx:
                idx = frame.find(0x02)
                if idx == -1:
                    return self._fallback.parse(frame)
                frame = frame[idx:]
                if len(frame) < 8:
                    return None
                status = chr(frame[1])
                if self.only_stable and status not in ('S', '+', 'G'):
                    return None
                digits = frame[2:8].decode("ascii", errors="ignore")
                if not digits.isdigit():
                    return None
                raw = int(digits)
                value = raw / (10 ** self.decimal_places) if self.decimal_places else float(raw)
                return value if value >= 0 else None
            else:
                return self._fallback.parse(frame)
        except Exception:
            return None


# ─────────────────────────────────────────────────────────────────────────────
# TP LOADCELL / GENERIC LOADCELL INDICATORS (India)
# Brands: Phoenix, Transcell, Kanta King, Super Kanta, Aczet
# These typically output a simple 6-digit number + status or just raw digits
# ─────────────────────────────────────────────────────────────────────────────

class TPLoadcellProtocol(WeightProtocol):
    """
    Generic loadcell indicator used widely in India.

    Common output formats:
      "  12345\\r\\n"          — raw 5-6 digit integer
      "12345.0\\r\\n"
      "S 012345\\r\\n"        — S=stable prefix
      "U 012345\\r\\n"        — U=unstable

    Config keys:
      decimal_places  (int, default 1)   — 12345 with dp=1 → 1234.5 kg
      only_stable     (bool, default False) — True to skip 'U' prefix lines
    """

    def __init__(self, config: dict):
        self.decimal_places = int(config.get("decimal_places", 1))
        self.only_stable = bool(config.get("only_stable", False))
        self._pat = re.compile(r"([SU])?\s*([\d]+\.?[\d]*)")

    def parse(self, frame: bytes) -> Optional[float]:
        try:
            text = frame.decode("ascii", errors="ignore").strip()
            m = self._pat.search(text)
            if not m:
                return None
            status_char, value_str = m.groups()
            if self.only_stable and status_char == 'U':
                return None
            value = float(value_str)
            if self.decimal_places and '.' not in value_str:
                value /= (10 ** self.decimal_places)
            return value if value >= 0 else None
        except Exception:
            return None


# ─────────────────────────────────────────────────────────────────────────────
# CI-SERIES / CAS / TRANSCELL FORMAT
# Used by: Transcell India, Phoenix Weighing, Citizen Scales
# ─────────────────────────────────────────────────────────────────────────────

class CISeriesProtocol(WeightProtocol):
    """
    CAS CI-series / Transcell / Phoenix continuous output.

    Frame format:
      STX  ±  7-digit weight  status  CR  LF
      [0]  STX 0x02
      [1]  sign '+' / '-'
      [2-8] 7 ASCII digits (leading zeros)
      [9]  status: 'S'=stable 'U'=unstable 'O'=overload 'E'=error
      [10] CR
      [11] LF

    Config keys:
      decimal_places  (int, default 1)
      only_stable     (bool, default True)
    """

    STX = 0x02

    def __init__(self, config: dict):
        self.decimal_places = int(config.get("decimal_places", 1))
        self.only_stable = bool(config.get("only_stable", True))

    def parse(self, frame: bytes) -> Optional[float]:
        try:
            idx = frame.find(self.STX)
            if idx == -1:
                return None
            frame = frame[idx:]
            if len(frame) < 10:
                return None
            sign = chr(frame[1])
            if sign not in ('+', '-'):
                return None
            digits = frame[2:9].decode("ascii", errors="ignore")
            if not digits.isdigit():
                return None
            status = chr(frame[9])
            if self.only_stable and status not in ('S', 'G'):
                return None
            raw = int(digits)
            value = raw / (10 ** self.decimal_places) if self.decimal_places else float(raw)
            return value if value >= 0 else None
        except Exception:
            return None


# ─────────────────────────────────────────────────────────────────────────────
# KERN & SOHN PRECISION BALANCES
# GS, DS, IDS, EW, EK series
# Uses KERN protocol similar to MT-SICS
# ─────────────────────────────────────────────────────────────────────────────

class KernProtocol(WeightProtocol):
    """
    Kern & Sohn precision balance output.

    Frame:
      "     1234.56 g \\r\\n"   (fixed-width, right-justified)
    or
      "ES\\r\\n"               (error/overload)

    Config keys:
      unit            (str, default 'kg')
      decimal_places  (int, default 2)
    """

    def __init__(self, config: dict):
        self.unit = config.get("unit", "kg")
        self._pat = re.compile(r"([-+]?\s*[\d]+\.?[\d]*)\s*" + re.escape(self.unit), re.IGNORECASE)
        self._fallback = GenericContinuousProtocol(config)

    def parse(self, frame: bytes) -> Optional[float]:
        try:
            text = frame.decode("ascii", errors="ignore").strip()
            if text in ("ES", "OL", "UL", "ERR"):
                return None
            m = self._pat.search(text)
            if m:
                value = float(m.group(1).replace(" ", ""))
                return value if value >= 0 else None
            return self._fallback.parse(frame)
        except Exception:
            return None


# ─────────────────────────────────────────────────────────────────────────────
# RS485 MODBUS RTU
# For indicators that use Modbus RTU over RS485 bus.
# Common brands: Anyload, Flintec, HBM, Utilcell, some Leo/Essae models
#
# NOTE: This parser expects the response bytes from a Modbus read holding
# registers response (function code 0x03). The manager must send the request
# command before reading.
# ─────────────────────────────────────────────────────────────────────────────

class RS485ModbusProtocol(WeightProtocol):
    """
    Modbus RTU RS485 weight reading.

    The manager sends: device_addr 0x03 reg_high reg_low 0x00 0x02 CRC_L CRC_H
    Scale replies:     device_addr 0x03 byte_count data_H data_L [data2_H data2_L] CRC_L CRC_H

    Weight is stored in 1 or 2 holding registers as a 16-bit or 32-bit integer.

    Config keys:
      device_address    (int, default 1)     — Modbus slave address
      register          (int, default 0)     — Starting register address (0-indexed)
      num_registers     (int, default 2)     — 1=16bit, 2=32bit
      decimal_places    (int, default 1)     — raw / 10^N = kg
      signed            (bool, default False)— treat value as signed integer
      byte_order        (str, default 'big') — 'big' or 'little'
    """

    def __init__(self, config: dict):
        self.device_address = int(config.get("device_address", 1))
        self.register = int(config.get("register", 0))
        self.num_registers = int(config.get("num_registers", 2))
        self.decimal_places = int(config.get("decimal_places", 1))
        self.signed = bool(config.get("signed", False))
        self.byte_order = config.get("byte_order", "big")

    def build_request(self) -> bytes:
        """Build Modbus RTU read holding registers request with CRC."""
        msg = bytes([
            self.device_address,
            0x03,                           # function code: read holding registers
            (self.register >> 8) & 0xFF,
            self.register & 0xFF,
            0x00,
            self.num_registers,
        ])
        crc = self._crc16(msg)
        return msg + bytes([crc & 0xFF, (crc >> 8) & 0xFF])

    def parse(self, frame: bytes) -> Optional[float]:
        """Parse Modbus RTU response frame."""
        try:
            # Minimum: addr(1) + fc(1) + bytecount(1) + data(2*N) + crc(2)
            min_len = 5 + (self.num_registers * 2)
            if len(frame) < min_len:
                return None
            if frame[0] != self.device_address:
                return None
            if frame[1] != 0x03:
                return None
            byte_count = frame[2]
            data = frame[3: 3 + byte_count]

            if self.num_registers == 1:
                fmt = ">h" if self.signed else ">H"
                raw = struct.unpack(fmt, data[:2])[0]
            else:
                # 2 registers = 32-bit
                if self.byte_order == "big":
                    fmt = ">i" if self.signed else ">I"
                    raw = struct.unpack(fmt, data[:4])[0]
                else:
                    fmt = "<i" if self.signed else "<I"
                    raw = struct.unpack(fmt, data[:4])[0]

            value = raw / (10 ** self.decimal_places) if self.decimal_places else float(raw)
            return value if value >= 0 else None
        except Exception:
            return None

    @staticmethod
    def _crc16(data: bytes) -> int:
        crc = 0xFFFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 0x0001:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return crc


# ─────────────────────────────────────────────────────────────────────────────
# DIGI SM-SERIES (label printers with built-in indicator)
# SM-90, SM-100, SM-110, SM-300
# ─────────────────────────────────────────────────────────────────────────────

class DigiSMProtocol(WeightProtocol):
    """
    Digi SM-series continuous output.

    Frame:
      STX  WW  6-digit  status  ETX
      [0]  STX 0x02
      [1-2] "WW" or "WT"
      [3-8] 6 ASCII digits
      [9]  status 'S'/'U'/'O'
      [10] ETX 0x03

    Config keys:
      decimal_places (int, default 1)
      only_stable    (bool, default True)
    """

    def __init__(self, config: dict):
        self.decimal_places = int(config.get("decimal_places", 1))
        self.only_stable = bool(config.get("only_stable", True))

    def parse(self, frame: bytes) -> Optional[float]:
        try:
            idx = frame.find(0x02)
            if idx == -1:
                return None
            frame = frame[idx:]
            if len(frame) < 10:
                return None
            prefix = frame[1:3].decode("ascii", errors="ignore")
            if prefix not in ("WW", "WT", "WN"):
                return None
            digits = frame[3:9].decode("ascii", errors="ignore")
            if not digits.isdigit():
                return None
            status = chr(frame[9])
            if self.only_stable and status not in ('S', 'G'):
                return None
            raw = int(digits)
            value = raw / (10 ** self.decimal_places) if self.decimal_places else float(raw)
            return value if value >= 0 else None
        except Exception:
            return None


# ─────────────────────────────────────────────────────────────────────────────
# PROTOCOL REGISTRY
# ─────────────────────────────────────────────────────────────────────────────

PROTOCOL_MAP: dict[str, type[WeightProtocol]] = {
    "generic":      GenericContinuousProtocol,
    "leo":          LeoProtocol,
    "essae":        EssaeProtocol,
    "avery":        AveryProtocol,
    "mettler":      MettlerToledoProtocol,
    "rice_lake":    RiceLakeProtocol,
    "systec":       SystecProtocol,
    "tp_loadcell":  TPLoadcellProtocol,
    "ci_series":    CISeriesProtocol,
    "kern":         KernProtocol,
    "rs485_modbus": RS485ModbusProtocol,
    "digi_sm":      DigiSMProtocol,
}

# Human-readable labels for UI dropdowns
PROTOCOL_LABELS: dict[str, str] = {
    "generic":      "Generic / Auto-detect (most indicators)",
    "leo":          "Leo Weighing Systems (Leo+, BW-series)",
    "essae":        "Essae Digitronics (ET-600, T-200, T-300, T-500)",
    "avery":        "Avery Berkel / Avery Weigh-Tronix",
    "mettler":      "Mettler Toledo (IND-series, ID1/ID5/ID7) — SICS",
    "rice_lake":    "Rice Lake (920i, 880, 820, IQ+)",
    "systec":       "Systec & Solutions",
    "tp_loadcell":  "TP / Phoenix / Transcell / Aczet (India loadcell)",
    "ci_series":    "CAS CI-series / Transcell / Citizen / Kanta King",
    "kern":         "Kern & Sohn precision balances",
    "rs485_modbus": "RS485 Modbus RTU (Anyload, Flintec, HBM, custom)",
    "digi_sm":      "Digi SM-series label printers",
}

# Default baud rates per brand
PROTOCOL_DEFAULT_BAUD: dict[str, int] = {
    "generic":      9600,
    "leo":          9600,
    "essae":        9600,
    "avery":        9600,
    "mettler":      9600,
    "rice_lake":    9600,
    "systec":       9600,
    "tp_loadcell":  9600,
    "ci_series":    9600,
    "kern":         9600,
    "rs485_modbus": 9600,
    "digi_sm":      9600,
}

# Default config per protocol
PROTOCOL_DEFAULT_CONFIG: dict[str, dict] = {
    "generic":      {"decimal_places": 0, "max_weight_kg": 200000},
    "leo":          {"decimal_places": 1, "only_stable": True},
    "essae":        {"decimal_places": 0, "only_stable": True},
    "avery":        {"decimal_places": 1, "only_stable": True},
    "mettler":      {"only_stable": True, "unit": "kg"},
    "rice_lake":    {"decimal_places": 1},
    "systec":       {"decimal_places": 1, "has_stx": True, "only_stable": True},
    "tp_loadcell":  {"decimal_places": 1, "only_stable": False},
    "ci_series":    {"decimal_places": 1, "only_stable": True},
    "kern":         {"unit": "kg", "decimal_places": 2},
    "rs485_modbus": {"device_address": 1, "register": 0, "num_registers": 2, "decimal_places": 1},
    "digi_sm":      {"decimal_places": 1, "only_stable": True},
}


def get_protocol(name: str, config: dict) -> WeightProtocol:
    cls = PROTOCOL_MAP.get(name.lower(), GenericContinuousProtocol)
    merged = {**PROTOCOL_DEFAULT_CONFIG.get(name.lower(), {}), **config}
    return cls(merged)
