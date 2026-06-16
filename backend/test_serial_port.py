"""Diagnose serial port issues — run with venv Python."""
import sys
import time

print("=" * 50)
print("Serial Port Diagnostic Tool")
print("=" * 50)

try:
    import serial
    import serial.tools.list_ports
    print(f"PySerial version: {serial.__version__}")
except ImportError:
    print("ERROR: pyserial not installed. Run: pip install pyserial")
    sys.exit(1)

# Step 1: List all ports
print("\n--- Step 1: Available Ports ---")
ports = serial.tools.list_ports.comports()
if not ports:
    print("  No COM ports found!")
    sys.exit(1)

for p in ports:
    print(f"  {p.device:8s} | {p.description} | hwid={p.hwid}")

# Step 2: Try to open the port
port = input("\nEnter port to test (e.g. COM9): ").strip().upper()
if not port:
    print("No port entered.")
    sys.exit(1)

baud = input("Baud rate (default 9600): ").strip()
baud = int(baud) if baud else 9600

print(f"\n--- Step 2: Opening {port} at {baud} baud ---")

# Method A: Standard open
print("\n  Method A: serial.Serial() standard open...")
try:
    ser = serial.Serial(
        port=port,
        baudrate=baud,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=2.0,
    )
    print(f"  SUCCESS: Port opened. is_open={ser.is_open}")

    print("\n--- Step 3: Reading data (5 seconds) ---")
    start = time.time()
    data_received = False
    while time.time() - start < 5:
        raw = ser.readline()
        if raw:
            data_received = True
            print(f"  DATA: {raw!r}")
            try:
                text = raw.decode('ascii', errors='replace').strip()
                print(f"  TEXT: {text}")
            except:
                pass

    if not data_received:
        print("  No data received in 5 seconds.")
        print("  Possible causes:")
        print("    - Scale output mode is 'on demand' (not continuous)")
        print("    - Wrong baud rate")
        print("    - TX/RX pins swapped (need null-modem adapter)")

    ser.close()
    print(f"\n  Port closed cleanly.")

except serial.SerialException as e:
    print(f"  FAILED: {e}")

    # Method B: Try with exclusive=False
    print("\n  Method B: Trying with exclusive=False...")
    try:
        ser = serial.Serial()
        ser.port = port
        ser.baudrate = baud
        ser.bytesize = serial.EIGHTBITS
        ser.parity = serial.PARITY_NONE
        ser.stopbits = serial.STOPBITS_ONE
        ser.timeout = 2.0
        ser.exclusive = False
        ser.open()
        print(f"  SUCCESS with exclusive=False! is_open={ser.is_open}")

        print("  Reading for 3 seconds...")
        start = time.time()
        while time.time() - start < 3:
            raw = ser.readline()
            if raw:
                print(f"  DATA: {raw!r}")

        ser.close()
        print("\n  FIX: The app needs exclusive=False on this port.")
    except Exception as e2:
        print(f"  FAILED: {e2}")

        # Method C: Try Windows CreateFile directly
        print("\n  Method C: Testing raw Windows file handle...")
        try:
            import ctypes
            handle = ctypes.windll.kernel32.CreateFileW(
                f"\\\\.\\{port}",
                0x80000000 | 0x40000000,  # GENERIC_READ | GENERIC_WRITE
                0,  # no sharing
                None,
                3,  # OPEN_EXISTING
                0,
                None,
            )
            if handle == -1:
                err = ctypes.windll.kernel32.GetLastError()
                print(f"  FAILED: Windows error code {err}")
                if err == 5:
                    print("  → Access Denied. Port is locked by another process.")
                    print("  → Close terminal.exe or any other serial app, then retry.")
                elif err == 31:
                    print("  → Device not functioning. USB-Serial adapter driver issue.")
                    print("  → Unplug USB cable, wait 5 sec, replug.")
                elif err == 2:
                    print(f"  → Port {port} does not exist.")
            else:
                print(f"  SUCCESS: Raw handle opened (handle={handle})")
                ctypes.windll.kernel32.CloseHandle(handle)
                print("  The port works at OS level. PySerial may need exclusive=False.")
        except Exception as e3:
            print(f"  FAILED: {e3}")

print("\n" + "=" * 50)
print("Diagnostic complete.")
