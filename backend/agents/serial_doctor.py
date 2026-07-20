#!/usr/bin/env python3
"""
Serial Doctor — diagnose "port opens but no weight" on a weighbridge indicator.

The scale agent logs "Scale connected on COMx" as soon as the port OPENS.
Windows will happily open a serial port with nothing attached, so that message
is NOT evidence that data is arriving. This tool answers the only question that
actually matters:

    Are ANY bytes arriving on this port — and if so, can they be parsed?

That single distinction splits the two very different faults that look identical
from the agent's log:

    NO bytes at all   -> wiring / port fault.  Almost always a missing NULL-MODEM
                         (crossover). A PC COM port and most indicators are both
                         DTE, i.e. both TRANSMIT on pin 3 and LISTEN on pin 2. A
                         straight-through cable joins TX->TX and RX->RX, so the
                         PC listens on a wire nobody talks on: port opens, total
                         silence. Also covers a "phantom" COM port that BIOS
                         exposes but which is not wired to the physical socket.

    Bytes but garbage -> framing mismatch. Right cable, wrong data-bits/parity
                         (e.g. reading a 7E1 indicator as 8N1). You will see
                         bytes, but they will not parse as a weight.

Usage:
    python serial_doctor.py                 # list ports, then sniff each one
    python serial_doctor.py COM1            # sniff one port at common framings
    python serial_doctor.py COM1 --seconds 15
    python serial_doctor.py COM1 --baud 9600 --framing 7E1   # force one combo

Read-only: it never writes to the port and never changes any config.
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys
import time
from pathlib import Path

# Force UTF-8 console. A frozen EXE on a Windows cp1252 console otherwise raises
# UnicodeEncodeError on any non-ASCII character and swallows the line.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    print("pyserial not installed.  Run:  pip install pyserial")
    sys.exit(1)

# When frozen, write the report next to the .exe (NOT _MEIPASS, which is deleted
# on exit) so the field tech can actually find and send it back.
if getattr(sys, "frozen", False) or "__compiled__" in globals():
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent

_REPORT: list[str] = []


def say(msg: str = "") -> None:
    """Print AND capture, so everything ends up in the saved report."""
    print(msg)
    _REPORT.append(msg)


def save_report() -> Path | None:
    try:
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = BASE_DIR / f"serial_doctor_{stamp}.txt"
        path.write_text("\n".join(_REPORT), encoding="utf-8")
        return path
    except Exception:
        return None

# Framings worth trying, most likely first. 8N1 is the general default; 7E1 is
# extremely common on Indian weighbridge indicators (Essae and similar).
FRAMINGS = ["8N1", "7E1", "7O1", "8E1", "8O1", "7N1"]
BAUDS = [9600, 4800, 19200, 2400, 38400]

_PARITY = {"N": serial.PARITY_NONE, "E": serial.PARITY_EVEN, "O": serial.PARITY_ODD}


def parse_framing(f: str):
    f = f.upper().strip()
    if len(f) != 3 or f[0] not in "78" or f[1] not in "NEO" or f[2] not in "12":
        raise ValueError(f"bad framing {f!r} (expect like 8N1 or 7E1)")
    return int(f[0]), _PARITY[f[1]], int(f[2])


def list_all_ports() -> list:
    """Enumerate ports with description + hardware id.

    Worth reading carefully: a native motherboard port shows as something like
    'Communications Port (COM1)' with an ACPI/PNP0501 hwid, while a USB adapter
    shows its chipset (CH340 / FTDI / Prolific) and a USB VID:PID. If the COM
    port you are targeting does not appear here at all, the agent cannot use it
    no matter how the cable is wired.
    """
    ports = sorted(list_ports.comports(), key=lambda p: p.device)
    say(f"\n  {'PORT':<8} {'DESCRIPTION':<42} HARDWARE ID")
    say("  " + "-" * 88)
    if not ports:
        say("  (none found — no serial ports visible to Windows at all)")
    for p in ports:
        say(f"  {p.device:<8} {str(p.description)[:42]:<42} {p.hwid}")
    return ports


def sniff(port: str, baud: int, framing: str, seconds: float,
          dtr: bool = True, rts: bool = True) -> bytes | None:
    """Listen read-only.

    Returns bytes received, or None if the port could not even be OPENED.
    That distinction matters: "opened but silent" is a wiring fault, whereas
    "cannot open" means the port does not exist / is in use / access denied —
    completely different advice. Conflating them sends a technician hunting a
    cable fault on a port that isn't there.
    """
    bits, par, stop = parse_framing(framing)
    got = bytearray()
    try:
        with serial.Serial(port=port, baudrate=baud, bytesize=bits, parity=par,
                           stopbits=stop, timeout=0.3) as sp:
            # Some indicators will not transmit unless the handshake lines are
            # asserted; a USB adapter often asserts them by default while a bare
            # 3-wire connection to a native port does not.
            try:
                sp.dtr = dtr
                sp.rts = rts
            except Exception:
                pass
            sp.reset_input_buffer()
            end = time.time() + seconds
            while time.time() < end:
                chunk = sp.read(256)
                if chunk:
                    got.extend(chunk)
                    if len(got) > 4096:
                        break
    except serial.SerialException as e:
        _LAST_OPEN_ERROR[0] = str(e)
        return None
    except Exception as e:  # noqa: BLE001
        _LAST_OPEN_ERROR[0] = str(e)
        return None
    return bytes(got)


_LAST_OPEN_ERROR = [""]


def looks_like_weight(data: bytes) -> bool:
    """Crude check: does this contain digits in a plausible weight shape?"""
    text = "".join(chr(b) if 32 <= b < 127 else " " for b in data)
    digits = sum(c.isdigit() for c in text)
    return digits >= 4


def show(data: bytes) -> None:
    printable = "".join(chr(b) if 32 <= b < 127 else "." for b in data[:160])
    say(f"    bytes={len(data)}  hex={data[:32].hex(' ')}")
    say(f"    ascii='{printable}'")


def diagnose(port: str, seconds: float, baud: int | None, framing: str | None) -> int:
    combos = ([(baud or 9600, framing)] if framing
              else [(b, f) for b in ([baud] if baud else BAUDS) for f in FRAMINGS])

    say(f"\n  Sniffing {port} — read-only, {seconds:g}s per combination")
    say("  " + "-" * 88)

    any_bytes = False
    opened_ok = False
    for b, f in combos:
        data = sniff(port, b, f, seconds)
        if data is None:
            # Could not OPEN. Bail immediately rather than repeating the same
            # error for all 30 combinations — and never call this a cable fault.
            say(f"    {b:>6} {f}  ->  CANNOT OPEN: {_LAST_OPEN_ERROR[0]}")
            say("")
            say("  ==> VERDICT: the port could not be opened at all.")
            low = _LAST_OPEN_ERROR[0].lower()
            if "cannot find" in low or "filenotfound" in low:
                say(f"      {port} DOES NOT EXIST on this PC. Check the port list above")
                say("      and Device Manager > Ports (COM & LPT) for the real name.")
            elif "access is denied" in low or "permission" in low:
                say(f"      {port} exists but is IN USE by another program.")
                say("      Close the scale agent / terminal / any other serial tool and retry.")
            else:
                say("      Check the port exists and nothing else is holding it.")
            say("      NOTE: this is NOT a cable problem — do not go hunting wiring yet.")
            return 1
        opened_ok = True
        if not data:
            say(f"    {b:>6} {f}  ->  (silence)")
            continue
        any_bytes = True
        say(f"    {b:>6} {f}  ->  {len(data)} bytes"
              f"{'  <-- LOOKS LIKE A WEIGHT' if looks_like_weight(data) else '  (unparseable)'}")
        show(data)
        if looks_like_weight(data):
            say(f"\n  ==> VERDICT: data IS arriving and parses at {b} {f}.")
            say(f"      Set the agent to: port={port} baud={b} framing={f}")
            return 0

    say()
    if not any_bytes and opened_ok:
        say(f"  (the port OPENED fine every time — {port} exists and is usable)")
        say("  ==> VERDICT: ZERO bytes at every baud/framing. This is NOT a settings")
        say("      problem — nothing is reaching the PC's receive pin.")
        say("      Most likely, in order:")
        say("       1. MISSING NULL-MODEM (crossover). PC and indicator are both DTE,")
        say("          so TX must cross to RX (pin 2 <-> 3). A straight-through cable")
        say("          or a plain gender-changer gives exactly this silence.")
        say("          -> Try a null-modem cable/adapter, or a 2-3 swap.")
        say("       2. Wrong COM port — the socket you plugged into may not be the")
        say("          COM number you opened. Check the port list above.")
        say("       3. Phantom port — BIOS exposes COMx but the physical header is")
        say("          not connected. Confirm in Device Manager / BIOS.")
        say("       4. Dead port / disabled in BIOS.")
    else:
        say("  ==> VERDICT: bytes ARE arriving but none parsed as a weight.")
        say("      The cable is fine — this is a FRAMING or protocol mismatch.")
        say("      Compare against the framing used by the setup that works.")
    return 1


def loopback(port: str, baud: int = 9600) -> int:
    """Prove whether the PC's own serial port works, independent of the scale.

    Physically bridge pin 2 to pin 3 on the PC's DB9 (a paperclip works), then
    run this. We transmit a string and see whether it comes straight back.

      echo   -> the PC port, its driver and the UART are all FINE. The fault is
                the CABLE or the indicator side (typically a missing null-modem).
      no echo-> the PC port itself is dead or disabled in BIOS. No cable helps.

    This is the ONE test that separates "my PC is broken" from "my cable is
    wrong", which is otherwise guesswork.
    """
    say("\n  LOOPBACK TEST")
    say("  " + "-" * 88)
    say(f"  1. UNPLUG the indicator cable from {port} (this test WRITES to the port).")
    say("  2. Bridge pin 2 to pin 3 on the PC's DB9 with a paperclip or wire.")
    say("  3. Keep it held there while this runs.")
    say("")
    try:
        input("  Press Enter when the jumper is in place (Ctrl+C to cancel)... ")
    except (EOFError, KeyboardInterrupt):
        say("  cancelled")
        return 2

    probe = b"WBTEST0123456789\r\n"
    try:
        with serial.Serial(port=port, baudrate=baud, timeout=1.0) as sp:
            sp.reset_input_buffer()
            sp.reset_output_buffer()
            sp.write(probe)
            sp.flush()
            time.sleep(0.4)
            back = sp.read(len(probe) + 8)
    except Exception as e:  # noqa: BLE001
        say(f"  !! could not open {port}: {e}")
        say("  ==> VERDICT: cannot even open the port — check it exists and nothing else holds it.")
        return 1

    say(f"  sent {len(probe)} bytes, got {len(back)} back: {back!r}")
    if probe.strip() and probe.strip() in back:
        say("\n  ==> VERDICT: ECHO RECEIVED. The PC serial port is WORKING.")
        say("      So the fault is on the CABLE / INDICATOR side. With the port")
        say("      proven good, a missing NULL-MODEM (pin 2<->3 crossover) is by far")
        say("      the most likely cause of the silence.")
        return 0
    say("\n  ==> VERDICT: NO ECHO. The PC's serial port is NOT working")
    say("      (dead UART, disabled in BIOS, or the jumper was not making contact).")
    say("      Re-seat the jumper and retry; if still nothing, use a USB-RS232 adapter.")
    return 1


def main() -> None:
    ap = argparse.ArgumentParser(description="Diagnose a silent weighbridge serial port")
    ap.add_argument("port", nargs="?", help="e.g. COM1 (omit to sniff every port)")
    ap.add_argument("--seconds", type=float, default=4.0, help="listen time per combo")
    ap.add_argument("--baud", type=int, help="force one baud")
    ap.add_argument("--framing", help="force one framing, e.g. 7E1")
    ap.add_argument("--loopback", action="store_true",
                    help="test the PC port itself with a pin 2-3 jumper (writes to the port)")
    a = ap.parse_args()

    say("=" * 92)
    say("  SERIAL DOCTOR — is the indicator actually sending anything?")
    say("=" * 92)
    ports = list_all_ports()

    if a.port:
        sys.exit(diagnose(a.port.upper(), a.seconds, a.baud, a.framing))

    if not ports:
        sys.exit(1)
    say("\n  No port given — trying each at 9600 8N1 and 9600 7E1 for a quick look.")
    for p in ports:
        for f in ("8N1", "7E1"):
            d = sniff(p.device, 9600, f, 2.0)
            if d is None:
                say(f"    {p.device:<8} 9600 {f}  ->  cannot open ({_LAST_OPEN_ERROR[0][:44]})")
                continue
            tag = "WEIGHT-LIKE" if looks_like_weight(d) else ("bytes" if d else "silence")
            say(f"    {p.device:<8} 9600 {f}  ->  {tag} ({len(d)} bytes)")
    say("\n  Now re-run against the port of interest, e.g.:  python serial_doctor.py COM1")


def _finish(code: int) -> None:
    """Save the report and hold the window open for a double-click launch."""
    p = save_report()
    if p:
        print(f"\n  Report saved: {p}")
        print("  (send this file back for analysis)")
    # A field tech will double-click the .exe; without this the console vanishes
    # instantly and they see nothing at all.
    if sys.stdout.isatty():
        try:
            input("\n  Press Enter to close... ")
        except (EOFError, KeyboardInterrupt):
            pass
    sys.exit(code)


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        _finish(int(e.code) if isinstance(e.code, int) else 0)
    except KeyboardInterrupt:
        _finish(130)
    except Exception as exc:  # noqa: BLE001
        say(f"\n  UNEXPECTED ERROR: {exc}")
        _finish(1)
