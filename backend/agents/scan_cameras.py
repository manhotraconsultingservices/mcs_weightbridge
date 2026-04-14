"""
Camera IP Scanner — discovers IP cameras on local network.

Scans common subnets for devices with camera ports open (HTTP 80, RTSP 554,
ONVIF 8080). Attempts to identify camera brand by testing known snapshot URLs.

Usage:
  python scan_cameras.py                   # auto-detect subnet, scan
  python scan_cameras.py 192.168.0.0/24    # scan specific subnet
  python scan_cameras.py 192.168.1.100     # test single IP
"""

import socket
import sys
import struct
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── Network helpers ─────────────────────────────────────────────────────────

def get_local_ips() -> list[str]:
    """Get all local IP addresses of this machine."""
    ips = []
    try:
        # Connect to a public DNS to find the default route IP
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

        # Also try hostname resolution
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except Exception:
        pass
    return ips


def get_subnets(ips: list[str] | None = None) -> list[str]:
    """Get /24 subnets from local IPs, filtering out virtual adapters."""
    if ips is None:
        ips = get_local_ips()
    subnets = []
    # Skip virtual adapter ranges (WSL, Docker, VPN)
    skip_prefixes = ("172.", "10.0.", "10.255.")
    for ip in ips:
        if any(ip.startswith(p) for p in skip_prefixes):
            continue
        parts = ip.split(".")
        subnet = f"{parts[0]}.{parts[1]}.{parts[2]}"
        if subnet not in subnets:
            subnets.append(subnet)
    # If all were filtered, fall back to the first real IP
    if not subnets and ips:
        parts = ips[0].split(".")
        subnets.append(f"{parts[0]}.{parts[1]}.{parts[2]}")
    return subnets


def scan_port(ip: str, port: int, timeout: float = 0.5) -> bool:
    """Check if a TCP port is open."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((ip, port))
        sock.close()
        return result == 0
    except Exception:
        return False


# ── Camera identification ───────────────────────────────────────────────────

CAMERA_PORTS = [
    (80,   "HTTP"),
    (554,  "RTSP"),
    (8080, "HTTP-ALT"),
    (443,  "HTTPS"),
    (8000, "SDK"),       # Hikvision SDK
    (34567, "DVR"),      # Chinese DVR port
    (37777, "DAHUA-SDK"),# Dahua SDK
]

SNAPSHOT_URLS = [
    # CP Plus / Dahua
    ("/cgi-bin/snapshot.cgi",       "CP Plus / Dahua"),
    # Hikvision
    ("/Streaming/channels/1/picture", "Hikvision"),
    ("/ISAPI/Streaming/channels/101/picture", "Hikvision (ISAPI)"),
    # Generic ONVIF
    ("/snap.jpg",                    "Generic ONVIF"),
    ("/snapshot.jpg",                "Generic"),
    ("/jpg/image.jpg",               "Axis"),
    ("/cgi-bin/api.cgi?cmd=Snap",    "Reolink"),
    ("/capture",                     "Generic"),
]


def identify_camera(ip: str, timeout: float = 3.0) -> dict | None:
    """Try known snapshot URLs to identify camera brand and working URL."""
    try:
        import requests
        from requests.auth import HTTPDigestAuth, HTTPBasicAuth
    except ImportError:
        return None

    for path, brand in SNAPSHOT_URLS:
        url = f"http://{ip}{path}"
        for auth_fn in [
            None,
            HTTPDigestAuth("admin", "admin"),
            HTTPDigestAuth("admin", "admin123"),
            HTTPBasicAuth("admin", "admin"),
            HTTPBasicAuth("admin", "admin123"),
        ]:
            try:
                resp = requests.get(url, auth=auth_fn, timeout=timeout, verify=False,
                                    stream=True)
                content_type = resp.headers.get("Content-Type", "")

                if resp.status_code == 200 and (
                    "image" in content_type or len(resp.content) > 1000
                ):
                    auth_type = "none"
                    if auth_fn:
                        auth_type = type(auth_fn).__name__.replace("HTTP", "").replace("Auth", "")
                    return {
                        "brand": brand,
                        "snapshot_url": url,
                        "auth_type": auth_type,
                        "image_size": len(resp.content),
                        "content_type": content_type,
                    }
                elif resp.status_code == 401:
                    # Camera exists, needs different credentials
                    continue
                elif resp.status_code == 200:
                    continue  # Not an image, try next URL
            except Exception:
                pass

        # If we got 401 on any URL, camera exists but needs credentials
        try:
            resp = requests.get(f"http://{ip}{SNAPSHOT_URLS[0][0]}",
                                timeout=timeout, verify=False)
            if resp.status_code == 401:
                return {
                    "brand": "Unknown (auth required)",
                    "snapshot_url": f"http://{ip}{SNAPSHOT_URLS[0][0]}",
                    "auth_type": "requires_credentials",
                    "image_size": 0,
                    "content_type": "",
                }
        except Exception:
            pass

    return None


def get_http_title(ip: str, port: int = 80) -> str:
    """Try to get the HTML title from the device's web interface."""
    try:
        import requests
        resp = requests.get(f"http://{ip}:{port}/", timeout=2, verify=False)
        if resp.status_code == 200:
            import re
            match = re.search(r"<title>(.*?)</title>", resp.text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
    except Exception:
        pass
    return ""


# ── Scanner ─────────────────────────────────────────────────────────────────

def scan_ip(ip: str) -> dict | None:
    """Scan a single IP for camera ports and identify if it's a camera."""
    open_ports = []
    for port, label in CAMERA_PORTS:
        if scan_port(ip, port, timeout=0.5):
            open_ports.append((port, label))

    if not open_ports:
        return None

    result = {
        "ip": ip,
        "open_ports": open_ports,
        "title": "",
        "camera_info": None,
    }

    # Get web title
    if any(p in [80, 8080, 443] for p, _ in open_ports):
        http_port = 80 if (80, "HTTP") in open_ports else 8080
        result["title"] = get_http_title(ip, http_port)

    # Try camera identification
    if (80, "HTTP") in open_ports or (8080, "HTTP-ALT") in open_ports:
        cam_info = identify_camera(ip)
        if cam_info:
            result["camera_info"] = cam_info

    return result


def scan_subnet(subnet: str, start: int = 1, end: int = 254,
                max_workers: int = 50) -> list[dict]:
    """Scan a /24 subnet for cameras using thread pool."""
    results = []
    ips = [f"{subnet}.{i}" for i in range(start, end + 1)]

    # Skip our own IPs
    local_ips = get_local_ips()

    print(f"\n  Scanning {subnet}.{start}-{end} ({len(ips)} hosts, {max_workers} threads)...")

    found_count = 0
    lock = threading.Lock()

    def _scan_and_report(ip):
        nonlocal found_count
        if ip in local_ips:
            return None
        r = scan_ip(ip)
        if r:
            with lock:
                found_count += 1
                port_str = ", ".join(f"{p}({l})" for p, l in r["open_ports"])
                marker = " ★ CAMERA" if r["camera_info"] else ""
                print(f"    Found: {ip:16s} ports: {port_str}{marker}")
        return r

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_scan_and_report, ip): ip for ip in ips}
        for future in as_completed(futures):
            try:
                r = future.result()
                if r:
                    results.append(r)
            except Exception:
                pass

    return sorted(results, key=lambda r: [int(x) for x in r["ip"].split(".")])


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    print()
    print("=" * 60)
    print("  Camera IP Scanner")
    print("  Discovers IP cameras on your local network")
    print("=" * 60)

    # Suppress urllib3 warnings
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass

    # Determine what to scan
    target = sys.argv[1] if len(sys.argv) > 1 else None

    if target and "/" not in target and "." in target:
        # Single IP mode
        print(f"\n  Testing single IP: {target}")
        result = scan_ip(target)
        if result:
            _print_results([result])
        else:
            print(f"\n  No camera ports open on {target}")
            print("  Check: is the camera powered on? Is the Ethernet cable connected?")
        return

    # Discover local subnets
    local_ips = get_local_ips()
    if not local_ips:
        print("\n  ERROR: Could not detect local IP address.")
        print("  Make sure you're connected to the network.")
        return

    print(f"\n  Local IP(s): {', '.join(local_ips)}")

    if target and "/" in target:
        # CIDR notation: 192.168.0.0/24
        subnet = target.rsplit(".", 1)[0]
        subnets = [subnet]
    else:
        # Derive subnets from detected IPs (same list, no second call)
        subnets = get_subnets(local_ips)

    # Also check for camera_config.json — add those subnets too
    try:
        from pathlib import Path
        cfg_path = Path(__file__).parent / "camera_config.json"
        if cfg_path.exists():
            import json
            cfg = json.loads(cfg_path.read_text())
            for cam in cfg.get("cameras", {}).values():
                url = cam.get("url", "")
                # Extract IP from URL like http://192.168.0.101/...
                import re
                m = re.search(r"//(\d+\.\d+\.\d+)\.\d+", url)
                if m:
                    cam_subnet = m.group(1)
                    if cam_subnet not in subnets:
                        subnets.append(cam_subnet)
                        print(f"  (Added {cam_subnet}.0/24 from camera_config.json)")
    except Exception:
        pass

    print(f"  Subnet(s):   {', '.join(s + '.0/24' for s in subnets)}")

    all_results = []
    for subnet in subnets:
        results = scan_subnet(subnet)
        all_results.extend(results)

    _print_results(all_results)


def _print_results(results: list[dict]):
    """Print formatted scan results."""
    print()
    print("=" * 60)
    print("  SCAN RESULTS")
    print("=" * 60)

    if not results:
        print("\n  No devices with camera ports found.")
        print("\n  TROUBLESHOOTING:")
        print("    1. Connect the DVR/camera to the same network")
        print("    2. Check Ethernet cable (green LED on DVR port?)")
        print("    3. Try pinging the camera IP manually")
        print("    4. Some cameras use different subnets (e.g., 192.168.1.x)")
        print("       → Run: python scan_cameras.py 192.168.1.0/24")
        return

    cameras = [r for r in results if r.get("camera_info")]
    others = [r for r in results if not r.get("camera_info")]

    if cameras:
        print(f"\n  ★ CAMERAS FOUND ({len(cameras)}):")
        print(f"  {'─' * 56}")
        for r in cameras:
            info = r["camera_info"]
            print(f"\n    IP:           {r['ip']}")
            print(f"    Brand:        {info['brand']}")
            print(f"    Snapshot URL:  {info['snapshot_url']}")
            print(f"    Auth:         {info['auth_type']}")
            if info.get("image_size"):
                print(f"    Image size:   {info['image_size']:,} bytes")
            if r.get("title"):
                print(f"    Web title:    {r['title']}")

        # Print recommended config
        print(f"\n  {'─' * 56}")
        print("  RECOMMENDED camera_config.json cameras section:")
        print()

        cam_ids = ["front", "top", "side"]
        for i, r in enumerate(cameras[:3]):
            info = r["camera_info"]
            cam_id = cam_ids[i] if i < len(cam_ids) else f"cam{i+1}"
            auth_note = ""
            if info["auth_type"] == "requires_credentials":
                auth_note = '  ← UPDATE these'
            print(f'    "{cam_id}": {{')
            print(f'      "label": "{cam_id.capitalize()} View",')
            print(f'      "url": "{info["snapshot_url"]}",')
            print(f'      "username": "admin",{auth_note}')
            print(f'      "password": "admin123"{auth_note}')
            print(f'    }}{"," if i < len(cameras[:3]) - 1 else ""}')

    if others:
        print(f"\n  Other network devices ({len(others)}):")
        for r in others:
            port_str = ", ".join(f"{p}" for p, _ in r["open_ports"])
            title = f" — {r['title']}" if r.get("title") else ""
            print(f"    {r['ip']:16s} ports: {port_str}{title}")

    print(f"\n  Total: {len(cameras)} camera(s), {len(others)} other device(s)")
    print()


if __name__ == "__main__":
    main()
