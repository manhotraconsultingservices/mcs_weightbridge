"""
Scale Simulator — RS232 weight output emulator for testing.

Writes realistic weighing scale frames to a COM port so you can test
the backend WeightScaleManager without real hardware.

SETUP (one-time):
  1. Install com0com: https://sourceforge.net/projects/com0com/
     Creates a VIRTUAL COM port PAIR, e.g. COM10 <-> COM11
     - Simulator writes to COM10  (acts as the scale)
     - Backend reads from COM11   (configure in Settings → Weight Scale)

  2. Install pyserial if not already:
     pip install pyserial

USAGE:
  python scale_simulator.py --port COM10 --protocol generic
  python scale_simulator.py --port COM10 --protocol leo
  python scale_simulator.py --port COM10 --protocol essae
  python scale_simulator.py --port COM10 --protocol avery
  python scale_simulator.py --port COM10 --protocol mettler

Options:
  --port      COM port to write to (default: COM10)
  --baud      Baud rate (default: 9600)
  --protocol  Protocol format to simulate (default: generic)
  --weight    Starting weight in kg (default: 5000)
  --interval  Seconds between readings (default: 0.5)
  --demo      Run demo mode: simulates truck arriving, loading, leaving
"""
import argparse
import math
import struct
import sys
import time

try:
    import serial
except ImportError:
    print("ERROR: pyserial not installed. Run: pip install pyserial")
    sys.exit(1)


# ─── Frame builders (one per protocol) ──────────────────────────────────────

def frame_generic(weight_kg: float) -> bytes:
    """Generic continuous ASCII: '  +012345.6 kg\\r\\n'"""
    return f"  +{weight_kg:08.2f} kg\r\n".encode("ascii")


def frame_generic_integer(weight_kg: float) -> bytes:
    """Generic integer format (grams): '005000000\\r\\n'  (5000 kg = 5000000 g)"""
    grams = int(weight_kg * 1000)
    return f"{grams:09d}\r\n".encode("ascii")


def frame_leo(weight_kg: float, stable: bool = True) -> bytes:
    """Leo Weighing Systems: 'ST,GS,+,005000.0,kg\\r\\n' or 'US,...' if unstable"""
    status = "ST" if stable else "US"
    return f"{status},GS,+,{weight_kg:08.1f},kg\r\n".encode("ascii")


def frame_essae(weight_kg: float, stable: bool = True) -> bytes:
    """Essae / Avery: STX + status + sign + 7 digit weight + 2 char unit + ETX"""
    STX, ETX = 0x02, 0x03
    status = b"S" if stable else b"D"
    weight_str = f"{weight_kg:07.1f}".encode("ascii")
    unit = b"kg"
    frame = bytes([STX]) + status + b"+" + weight_str + unit + bytes([ETX])
    return frame + b"\r\n"


def frame_avery(weight_kg: float, stable: bool = True) -> bytes:
    """Avery Berkel: same as Essae STX format"""
    return frame_essae(weight_kg, stable)


def frame_mettler(weight_kg: float, stable: bool = True) -> bytes:
    """Mettler Toledo SICS response to 'S\\r\\n' query: 'S S  +001234.56 kg\\r\\n'"""
    status = "S" if stable else "D"
    return f"S {status}  +{weight_kg:09.2f} kg\r\n".encode("ascii")


def frame_systec(weight_kg: float, stable: bool = True) -> bytes:
    """Systec: 'W:005000.0 kg  ST\\r\\n'"""
    status = "ST" if stable else "US"
    return f"W:{weight_kg:08.1f} kg  {status}\r\n".encode("ascii")


def frame_ci_series(weight_kg: float, stable: bool = True) -> bytes:
    """CI-series / Transcell: '00005000.0\\r\\n'"""
    return f"{weight_kg:010.1f}\r\n".encode("ascii")


PROTOCOL_FRAMES = {
    "generic":        frame_generic,
    "generic_int":    frame_generic_integer,
    "leo":            frame_leo,
    "essae":          frame_essae,
    "avery":          frame_avery,
    "mettler":        frame_mettler,
    "systec":         frame_systec,
    "ci_series":      frame_ci_series,
}


# ─── Simulation scenarios ─────────────────────────────────────────────────────

def demo_sequence(base_weight_kg: float):
    """
    Yields (weight_kg, stable, label) tuples simulating a truck:
      1. Empty scale — tare reading ~ base_weight
      2. Truck arrives — weight increases
      3. Gross weight stabilises
      4. Truck leaves — weight drops
    """
    # Phase 1: empty platform (tare), 5 readings
    for _ in range(5):
        yield base_weight_kg + 0.5 * (0.5 - 0.5), False, "EMPTY (tare)"
    for _ in range(10):
        yield base_weight_kg, True, "STABLE tare"

    # Phase 2: truck drives on — weight ramps up
    truck_weight = 18500.0
    for i in range(20):
        w = base_weight_kg + (truck_weight * i / 20) + 50 * math.sin(i)
        yield w, False, "TRUCK ARRIVING"

    # Phase 3: gross weight stable
    for _ in range(15):
        yield base_weight_kg + truck_weight, True, "STABLE gross"

    # Phase 4: truck leaves
    for i in range(15):
        w = base_weight_kg + truck_weight * (1 - i / 15) + 30 * math.sin(i)
        yield w, False, "TRUCK LEAVING"

    # Phase 5: empty again
    for _ in range(10):
        yield base_weight_kg, True, "STABLE tare (again)"


def continuous_sequence(base_weight_kg: float):
    """Yields stable weight with small fluctuation indefinitely."""
    i = 0
    while True:
        fluctuation = 2.5 * math.sin(i * 0.3)
        stable = abs(fluctuation) < 1.5
        yield base_weight_kg + fluctuation, stable, "CONTINUOUS"
        i += 1


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="RS232 Scale Simulator")
    parser.add_argument("--port",     default="COM10",   help="COM port to write to")
    parser.add_argument("--baud",     default=9600, type=int)
    parser.add_argument("--protocol", default="generic", choices=list(PROTOCOL_FRAMES.keys()))
    parser.add_argument("--weight",   default=5000.0, type=float, help="Base weight in kg")
    parser.add_argument("--interval", default=0.5,   type=float, help="Seconds between frames")
    parser.add_argument("--demo",     action="store_true", help="Run truck demo scenario")
    args = parser.parse_args()

    frame_fn = PROTOCOL_FRAMES[args.protocol]

    print(f"\n{'='*60}")
    print(f"  Scale Simulator")
    print(f"  Port:     {args.port} @ {args.baud} baud")
    print(f"  Protocol: {args.protocol}")
    print(f"  Mode:     {'DEMO (truck scenario)' if args.demo else 'CONTINUOUS'}")
    print(f"{'='*60}\n")
    print("  Configure backend:  Settings → Weight Scale")
    print(f"  Backend COM port:   (partner of {args.port}, e.g. COM11)")
    print(f"  Test WebSocket:     ws://localhost:9001/ws/weight")
    print(f"  Test REST:          GET http://localhost:9001/api/v1/weight/status")
    print("\n  Press Ctrl+C to stop.\n")

    try:
        ser = serial.Serial(
            port=args.port,
            baudrate=args.baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=1,
        )
        print(f"  [OK] Opened {args.port}\n")
    except serial.SerialException as e:
        print(f"  [ERROR] Cannot open {args.port}: {e}")
        print("\n  Make sure com0com is installed and the port exists.")
        print("  Download: https://sourceforge.net/projects/com0com/\n")
        sys.exit(1)

    sequence = demo_sequence(args.weight) if args.demo else continuous_sequence(args.weight)
    count = 0

    try:
        for weight, stable, label in sequence:
            try:
                frame = frame_fn(weight, stable) if args.protocol in ("leo", "essae", "avery", "mettler", "systec", "ci_series") else frame_fn(weight)
            except TypeError:
                frame = frame_fn(weight)

            ser.write(frame)
            ser.flush()
            count += 1

            status = "STABLE" if stable else "      "
            print(f"  [{count:04d}] {label:<22} {weight:10.2f} kg  {status}  →  {frame.hex().upper()[:30]}")

            time.sleep(args.interval)

    except KeyboardInterrupt:
        print(f"\n\n  Stopped after {count} frames.")
    finally:
        ser.close()
        print(f"  Port {args.port} closed.\n")


if __name__ == "__main__":
    main()
