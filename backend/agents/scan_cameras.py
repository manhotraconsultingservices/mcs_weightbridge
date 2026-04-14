"""
Camera IP Scanner — discovers IP cameras and DVRs on local network.

Scans common subnets using ping sweep + port scan. Detects individual
IP cameras AND multi-channel DVRs/NVRs. Tests known snapshot URLs with
authentication to identify brand and working capture URL.

Usage:
  python scan_cameras.py                   # auto-detect subnet, full scan
  python scan_cameras.py 192.168.0.0/24    # scan specific subnet
  python scan_cameras.py 192.168.0.101     # test single IP in detail
"""

import socket
import subprocess
import sys
import re
import time
import threading
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── Suppress warnings ──────────────────────────────────────────────────────

try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass

# ── Network helpers ─────────────────────────────────────────────────────────

def get_local_ips() -> list[str]:
    """Get all local IP addresses of this machine."""
    ips = []
    try:
        for target in ["8.8.8.8", "1.1.1.1"]:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.settimeout(1)
                s.connect((target, 80))
                ip = s.getsockname()[0]
                s.close()
                if ip not in ips and not ip.startswith("127."):
                    ips.append(ip)
            except Exception:
                pass

        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except Exception:
        pass
    return ips


def get_subnets(ips: list[str]) -> list[str]:
    """Get /24 subnets from local IPs, filtering out virtual adapters."""
    subnets = []
    skip_prefixes = ("172.", "10.0.", "10.255.")
    for ip in ips:
        if any(ip.startswith(p) for p in skip_prefixes):
            continue
        parts = ip.split(".")
        subnet = f"{parts[0]}.{parts[1]}.{parts[2]}"
        if subnet not in subnets:
            subnets.append(subnet)
    if not subnets and ips:
        parts = ips[0].split(".")
        subnets.append(f"{parts[0]}.{parts[1]}.{parts[2]}")
    return subnets


def ping_host(ip: str, timeout_ms: int = 500) -> bool:
    """Quick ICMP ping check."""
    try:
        result = subprocess.run(
            ["ping", "-n", "1", "-w", str(timeout_ms), ip],
            capture_output=True, text=True, timeout=2,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        return result.returncode == 0
    except Exception:
        return False


def scan_port(ip: str, port: int, timeout: float = 1.0) -> bool:
    """Check if a TCP port is open."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((ip, port))
        sock.close()
        return result == 0
    except Exception:
        return False


def get_arp_table() -> dict[str, str]:
    """Get ARP table to find devices that responded to broadcasts."""
    arp_ips = {}
    try:
        result = subprocess.run(
            ["arp", "-a"], capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        for line in result.stdout.splitlines():
            m = re.search(r"(\d+\.\d+\.\d+\.\d+)\s+([\w-]+)", line)
            if m:
                ip, mac = m.group(1), m.group(2).replace("-", ":")
                if mac != "ff-ff-ff-ff-ff-ff" and not ip.endswith(".255"):
                    arp_ips[ip] = mac
    except Exception:
        pass
    return arp_ips


# ── Camera identification ───────────────────────────────────────────────────

# Ports that indicate camera/DVR/NVR
CAMERA_PORTS = [
    (80,    "HTTP"),
    (554,   "RTSP"),
    (8080,  "HTTP-ALT"),
    (443,   "HTTPS"),
    (8000,  "HIK-SDK"),       # Hikvision SDK
    (8200,  "HIK-ISAPI"),     # Hikvision ISAPI
    (9000,  "CPPLUS-WEB"),    # CP Plus web
    (5000,  "ONVIF"),         # ONVIF service
    (34567, "DVR-CMD"),       # Chinese DVR command port
    (37777, "DAHUA-SDK"),     # Dahua SDK
    (8899,  "DVR-ALT"),       # Alternative DVR port
]

SNAPSHOT_URLS = [
    # CP Plus / Dahua (most common in India)
    ("/cgi-bin/snapshot.cgi",                    "CP Plus / Dahua"),
    ("/cgi-bin/snapshot.cgi?channel=1",          "CP Plus / Dahua Ch1"),
    # Hikvision
    ("/Streaming/channels/1/picture",            "Hikvision"),
    ("/ISAPI/Streaming/channels/101/picture",    "Hikvision (ISAPI)"),
    # Generic ONVIF / others
    ("/snap.jpg",                                "Generic ONVIF"),
    ("/snapshot.jpg",                            "Generic"),
    ("/jpg/image.jpg",                           "Axis"),
    ("/cgi-bin/api.cgi?cmd=Snap&channel=0",      "Reolink"),
    ("/capture",                                 "Generic"),
    ("/onvif/snapshot",                          "ONVIF"),
    ("/image/jpeg.cgi",                          "D-Link"),
]

# DVR multi-channel snapshot patterns (append channel number)
DVR_CHANNEL_PATTERNS = [
    ("/cgi-bin/snapshot.cgi?channel={ch}",             "CP Plus / Dahua"),
    ("/Streaming/channels/{ch}01/picture",             "Hikvision"),
    ("/ISAPI/Streaming/channels/{ch}01/picture",       "Hikvision (ISAPI)"),
    ("/cgi-bin/api.cgi?cmd=Snap&channel={ch}",         "Reolink"),
]


def load_config_credentials() -> list[tuple[str, str]]:
    """Load camera credentials from camera_config.json if available."""
    creds = [("", "")]  # No auth first
    try:
        cfg_path = Path(__file__).parent / "camera_config.json"
        if cfg_path.exists():
            cfg = json.loads(cfg_path.read_text())
            for cam in cfg.get("cameras", {}).values():
                u = cam.get("username", "")
                p = cam.get("password", "")
                if u and (u, p) not in creds:
                    creds.append((u, p))
    except Exception:
        pass

    # Add common defaults
    for u, p in [("admin", "admin"), ("admin", "admin123"), ("admin", "")]:
        if (u, p) not in creds:
            creds.append((u, p))

    return creds


def try_snapshot(ip: str, path: str, creds: list[tuple[str, str]],
                 timeout: float = 3.0, port: int = 80) -> dict | None:
    """Try a single snapshot URL with multiple auth methods."""
    import requests
    from requests.auth import HTTPDigestAuth, HTTPBasicAuth

    url = f"http://{ip}:{port}{path}" if port != 80 else f"http://{ip}{path}"
    got_401 = False

    for username, password in creds:
        for auth_class in ([None] if not username else [HTTPDigestAuth, HTTPBasicAuth]):
            try:
                auth = auth_class(username, password) if auth_class else None
                resp = requests.get(url, auth=auth, timeout=timeout, verify=False)
                content_type = resp.headers.get("Content-Type", "")

                if resp.status_code == 200 and (
                    "image" in content_type or len(resp.content) > 1000
                ):
                    auth_type = "none"
                    if auth_class:
                        auth_type = f"{auth_class.__name__.replace('HTTP','').replace('Auth','')}({username})"
                    return {
                        "snapshot_url": url,
                        "auth_type": auth_type,
                        "username": username,
                        "password": password,
                        "image_size": len(resp.content),
                        "content_type": content_type,
                    }
                elif resp.status_code == 401:
                    got_401 = True
            except requests.exceptions.ConnectError:
                break  # Port not open on this IP, skip remaining auth
            except Exception:
                pass

    if got_401:
        return {"snapshot_url": url, "auth_type": "requires_credentials",
                "username": "", "password": "", "image_size": 0, "content_type": ""}
    return None


def identify_camera(ip: str, open_ports: list[tuple[int, str]],
                    creds: list[tuple[str, str]]) -> list[dict]:
    """Identify camera(s) at an IP. Returns list (DVR can have multiple channels)."""
    try:
        import requests
    except ImportError:
        return []

    http_ports = [p for p, l in open_ports if p in (80, 8080, 9000, 443)]
    if not http_ports:
        # No HTTP port — but if RTSP is open, it's likely a camera
        if any(p == 554 for p, _ in open_ports):
            return [{
                "brand": "RTSP Camera (no HTTP)",
                "snapshot_url": f"rtsp://{ip}:554/cam/realmonitor?channel=1&subtype=0",
                "auth_type": "rtsp_only",
                "username": "", "password": "",
                "image_size": 0, "content_type": "",
                "channel": 0,
            }]
        return []

    cameras_found = []
    port = http_ports[0]  # Use first available HTTP port

    # Step 1: Try standard snapshot URLs
    for path, brand in SNAPSHOT_URLS:
        result = try_snapshot(ip, path, creds, timeout=3.0, port=port)
        if result and result.get("image_size", 0) > 0:
            result["brand"] = brand
            result["channel"] = 0
            cameras_found.append(result)
            break  # Found working URL, now check for multi-channel

    # Step 2: If we found a camera, check for DVR multi-channel
    if cameras_found:
        brand = cameras_found[0].get("brand", "")
        working_creds = [(cameras_found[0].get("username", ""),
                          cameras_found[0].get("password", ""))]

        for pattern, pat_brand in DVR_CHANNEL_PATTERNS:
            if pat_brand.split()[0] not in brand.split()[0] and pat_brand.split("/")[0] not in brand:
                continue  # Only try patterns matching the detected brand

            for ch in range(2, 17):  # Check channels 2-16
                path = pattern.format(ch=ch)
                result = try_snapshot(ip, path, working_creds, timeout=2.0, port=port)
                if result and result.get("image_size", 0) > 0:
                    result["brand"] = f"{pat_brand} Ch{ch}"
                    result["channel"] = ch
                    cameras_found.append(result)
                else:
                    break  # No more channels

    # Step 3: If nothing worked via snapshot, check if it's a DVR by page title
    if not cameras_found:
        # Check for 401 on common URLs (camera exists but needs auth)
        for path, brand in SNAPSHOT_URLS[:3]:  # Try top 3 most common
            result = try_snapshot(ip, path, creds, timeout=2.0, port=port)
            if result:
                result["brand"] = f"{brand} (auth required)" if result["auth_type"] == "requires_credentials" else brand
                result["channel"] = 0
                cameras_found.append(result)
                break

    # Step 4: If still nothing, but DVR ports are open, mark as potential DVR
    if not cameras_found:
        dvr_ports = [p for p, l in open_ports if p in (34567, 37777, 8000, 8899)]
        if dvr_ports:
            cameras_found.append({
                "brand": "DVR/NVR (SDK port only)",
                "snapshot_url": f"http://{ip}:{port}/",
                "auth_type": "dvr_detected",
                "username": "", "password": "",
                "image_size": 0, "content_type": "",
                "channel": 0,
            })

    return cameras_found


def get_http_title(ip: str, port: int = 80) -> str:
    """Try to get the HTML title from the device's web interface."""
    try:
        import requests
        resp = requests.get(f"http://{ip}:{port}/", timeout=2, verify=False)
        if resp.status_code in (200, 401):
            match = re.search(r"<title>(.*?)</title>", resp.text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
            # Some DVRs return JSON or non-HTML
            server = resp.headers.get("Server", "")
            if server:
                return f"[{server}]"
    except Exception:
        pass
    return ""


# ── Scanner ─────────────────────────────────────────────────────────────────

def scan_ip(ip: str, creds: list[tuple[str, str]]) -> dict | None:
    """Scan a single IP for camera ports and identify cameras."""
    open_ports = []
    for port, label in CAMERA_PORTS:
        if scan_port(ip, port, timeout=1.0):
            open_ports.append((port, label))

    if not open_ports:
        return None

    result = {
        "ip": ip,
        "open_ports": open_ports,
        "title": "",
        "cameras": [],
    }

    # Get web title from any HTTP port
    for port in [80, 8080, 9000]:
        if any(p == port for p, _ in open_ports):
            result["title"] = get_http_title(ip, port)
            if result["title"]:
                break

    # Identify camera(s) at this IP
    result["cameras"] = identify_camera(ip, open_ports, creds)

    return result


def discover_hosts(subnet: str, max_workers: int = 100) -> list[str]:
    """Fast ping sweep to find live hosts on the subnet."""
    live = []
    lock = threading.Lock()

    def _ping(ip):
        if ping_host(ip, timeout_ms=500):
            with lock:
                live.append(ip)

    ips = [f"{subnet}.{i}" for i in range(1, 255)]
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        list(executor.map(_ping, ips))

    return sorted(live, key=lambda ip: [int(x) for x in ip.split(".")])


def tcp_probe_all(subnet: str, ports: list[int],
                  timeout: float = 0.8, max_workers: int = 100) -> set[str]:
    """Fast TCP probe of ALL 254 IPs on key ports. Returns IPs that respond."""
    responsive = set()
    lock = threading.Lock()

    def _probe(ip_port):
        ip, port = ip_port
        if scan_port(ip, port, timeout=timeout):
            with lock:
                responsive.add(ip)

    # Build (ip, port) pairs for all IPs × key ports
    tasks = [(f"{subnet}.{i}", port) for i in range(1, 255) for port in ports]

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        list(executor.map(_probe, tasks))

    return responsive


def scan_subnet(subnet: str, local_ips: list[str],
                max_workers: int = 30) -> list[dict]:
    """Scan a subnet: TCP probe ALL IPs → full port scan → camera identification.

    Many cameras/DVRs disable ICMP ping, so we do NOT rely on ping.
    Instead we TCP-probe ALL 254 IPs on the 3 most common camera ports
    (80, 554, 37777) with a fast timeout, then do full identification
    on every IP that responded.
    """
    creds = load_config_credentials()

    # Phase 1: Fast TCP probe on ALL 254 IPs for key camera ports
    key_ports = [80, 554, 37777]
    print(f"\n  Phase 1: TCP probe {subnet}.1-254 on ports {key_ports}...")
    responsive = tcp_probe_all(subnet, key_ports, timeout=0.8, max_workers=120)

    # Also add: ARP table entries
    arp = get_arp_table()
    for ip, mac in arp.items():
        if ip.startswith(subnet + "."):
            responsive.add(ip)

    # Also add: ping-responsive hosts (catches devices on non-camera ports)
    print(f"    TCP probe: {len(responsive)} hosts responded")
    print(f"  Phase 1b: Quick ping sweep for additional hosts...")
    ping_hosts = discover_hosts(subnet, max_workers=100)
    added_by_ping = 0
    for ip in ping_hosts:
        if ip not in responsive:
            responsive.add(ip)
            added_by_ping += 1
    if added_by_ping:
        print(f"    Ping added {added_by_ping} more host(s)")

    # Also add: known camera IPs from config
    try:
        cfg_path = Path(__file__).parent / "camera_config.json"
        if cfg_path.exists():
            cfg = json.loads(cfg_path.read_text())
            for cam in cfg.get("cameras", {}).values():
                url = cam.get("url", "")
                m = re.search(r"//(\d+\.\d+\.\d+\.\d+)", url)
                if m and m.group(1).startswith(subnet + "."):
                    if m.group(1) not in responsive:
                        responsive.add(m.group(1))
                        print(f"    Added {m.group(1)} from camera_config.json")
    except Exception:
        pass

    print(f"    Total: {len(responsive)} hosts to scan")

    if not responsive:
        print("    No hosts found on this subnet.")
        return []

    # Phase 2: Full port scan + camera identification on responsive hosts
    hosts = sorted(responsive, key=lambda ip: [int(x) for x in ip.split(".")])
    print(f"  Phase 2: Full scan + camera identification on {len(hosts)} hosts...")

    results = []
    lock = threading.Lock()
    scanned = [0]

    def _scan(ip):
        r = scan_ip(ip, creds)
        with lock:
            scanned[0] += 1
            if r:
                port_str = ", ".join(f"{p}({l})" for p, l in r["open_ports"])
                cam_count = len(r["cameras"])
                marker = f" ★ {cam_count} camera(s)" if cam_count > 0 else ""
                is_self = " (this PC)" if ip in local_ips else ""
                print(f"    Found: {ip:16s} ports: {port_str}{marker}{is_self}")
                results.append(r)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_scan, ip) for ip in hosts]
        for f in as_completed(futures):
            try:
                f.result()
            except Exception:
                pass

    print(f"    Scanned {scanned[0]} hosts")
    return sorted(results, key=lambda r: [int(x) for x in r["ip"].split(".")])


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    print()
    print("=" * 64)
    print("  Camera & DVR Scanner")
    print("  Discovers IP cameras, DVRs, and NVRs on your local network")
    print("=" * 64)

    target = sys.argv[1] if len(sys.argv) > 1 else None

    # Single IP mode
    if target and "/" not in target and "." in target:
        print(f"\n  Testing single IP: {target}")
        creds = load_config_credentials()
        result = scan_ip(target, creds)
        if result:
            _print_results([result])
        else:
            print(f"\n  No camera ports open on {target}")
            print("  Check: is the camera powered on? Is the Ethernet cable connected?")
            print(f"  Try: ping {target}")
        return

    # Discover local subnets
    local_ips = get_local_ips()
    if not local_ips:
        print("\n  ERROR: Could not detect local IP address.")
        print("  Make sure you're connected to the network.")
        return

    print(f"\n  Local IP(s): {', '.join(local_ips)}")

    if target and "/" in target:
        subnet = target.rsplit(".", 1)[0]
        subnets = [subnet]
    else:
        subnets = get_subnets(local_ips)

    # Add subnets from camera_config.json
    try:
        cfg_path = Path(__file__).parent / "camera_config.json"
        if cfg_path.exists():
            cfg = json.loads(cfg_path.read_text())
            for cam in cfg.get("cameras", {}).values():
                url = cam.get("url", "")
                m = re.search(r"//(\d+\.\d+\.\d+)\.\d+", url)
                if m and m.group(1) not in subnets:
                    subnets.append(m.group(1))
                    print(f"  (Added {m.group(1)}.0/24 from camera_config.json)")
    except Exception:
        pass

    print(f"  Subnet(s):   {', '.join(s + '.0/24' for s in subnets)}")

    all_results = []
    for subnet in subnets:
        results = scan_subnet(subnet, local_ips)
        all_results.extend(results)

    _print_results(all_results)


def _print_results(results: list[dict]):
    """Print formatted scan results."""
    print()
    print("=" * 64)
    print("  SCAN RESULTS")
    print("=" * 64)

    if not results:
        print("\n  No devices with camera ports found.")
        print("\n  TROUBLESHOOTING:")
        print("    1. Connect the DVR/camera to the same network")
        print("    2. Check Ethernet cable (green LED on port?)")
        print("    3. Try: python scan_cameras.py <camera-ip>")
        print("    4. Try other subnets:")
        print("       python scan_cameras.py 192.168.0.0/24")
        print("       python scan_cameras.py 192.168.1.0/24")
        print("       python scan_cameras.py 10.0.0.0/24")
        return

    # Separate cameras from non-camera devices
    camera_results = []
    other_results = []

    for r in results:
        if r.get("cameras"):
            camera_results.append(r)
        else:
            other_results.append(r)

    total_channels = sum(len(r["cameras"]) for r in camera_results)

    if camera_results:
        print(f"\n  ★ CAMERAS / DVRs FOUND: {len(camera_results)} device(s), {total_channels} channel(s)")
        print(f"  {'─' * 60}")

        all_cameras = []  # Flat list of (ip, camera_info)
        for r in camera_results:
            ip = r["ip"]
            title = r.get("title", "")
            ports = ", ".join(f"{p}" for p, _ in r["open_ports"])

            print(f"\n    Device: {ip}")
            if title:
                print(f"    Title:  {title}")
            print(f"    Ports:  {ports}")

            for cam in r["cameras"]:
                ch_label = f" (Ch {cam['channel']})" if cam.get("channel", 0) > 0 else ""
                print(f"      → Brand:    {cam['brand']}{ch_label}")
                print(f"        URL:      {cam['snapshot_url']}")
                print(f"        Auth:     {cam['auth_type']}")
                if cam.get("image_size"):
                    print(f"        Image:    {cam['image_size']:,} bytes")
                all_cameras.append((ip, cam))

        # Print recommended config
        if all_cameras:
            print(f"\n  {'─' * 60}")
            print("  RECOMMENDED camera_config.json:")
            print()
            print('    "cameras": {')

            cam_ids = ["front", "top", "side", "rear"]
            shown = 0
            for i, (ip, cam) in enumerate(all_cameras):
                if cam.get("auth_type") in ("rtsp_only", "dvr_detected"):
                    continue  # Skip non-HTTP cameras in config
                cam_id = cam_ids[shown] if shown < len(cam_ids) else f"cam{shown+1}"
                shown += 1
                is_last = (shown >= len(all_cameras) or shown >= 4)
                auth_note = "  ← UPDATE" if cam["auth_type"] == "requires_credentials" else ""
                username = cam.get("username", "admin") or "admin"
                password = cam.get("password", "admin123") or "admin123"

                print(f'      "{cam_id}": {{')
                print(f'        "label": "{cam_id.capitalize()} View",')
                print(f'        "url": "{cam["snapshot_url"]}",')
                print(f'        "username": "{username}",{auth_note}')
                print(f'        "password": "{password}"{auth_note}')
                print(f'      }}{" " if is_last else ","}')

                if shown >= 4:
                    break

            print('    }')

    if other_results:
        print(f"\n  Other network devices ({len(other_results)}):")
        for r in other_results:
            port_str = ", ".join(f"{p}" for p, _ in r["open_ports"])
            title = f" — {r['title']}" if r.get("title") else ""
            print(f"    {r['ip']:16s} ports: {port_str}{title}")

    print(f"\n  Summary: {len(camera_results)} camera device(s), "
          f"{total_channels} channel(s), {len(other_results)} other device(s)")
    print()


if __name__ == "__main__":
    main()
