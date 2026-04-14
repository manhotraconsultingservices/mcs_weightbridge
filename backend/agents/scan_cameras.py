"""
Camera IP Scanner — discovers ALL IP cameras and DVRs on local network.

Uses 6 complementary discovery methods so no camera goes untraced:
  1. ONVIF WS-Discovery multicast (cameras MUST respond per ONVIF spec)
  2. Authenticated HTTP probe (requests.get with Digest/Basic auth — matches camera_agent)
  3. ARP broadcast flood (populate ARP table, then read it)
  4. TCP port probe (raw sockets on camera ports)
  5. Ping sweep (ICMP)
  6. Config-known IPs (from camera_config.json)

Usage:
  python scan_cameras.py                   # auto-detect subnet, full scan
  python scan_cameras.py 192.168.0.0/24    # scan specific subnet
  python scan_cameras.py 192.168.0.101     # test single IP in detail
"""

import socket
import struct
import subprocess
import sys
import re
import time
import threading
import json
import uuid
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
            capture_output=True, text=True, timeout=3,
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
                if mac != "ff:ff:ff:ff:ff:ff" and not ip.endswith(".255"):
                    arp_ips[ip] = mac
    except Exception:
        pass
    return arp_ips


def arp_broadcast_flood(subnet: str):
    """Send ARP broadcast to populate the ARP table with all live hosts.

    Uses `ping -n 1 -w 1 <broadcast>` plus subnet broadcast to trigger
    ARP resolution on all live hosts, then we can read the ARP table.
    """
    broadcast_ip = f"{subnet}.255"
    try:
        # Ping the broadcast address — triggers ARP for all listening hosts
        subprocess.run(
            ["ping", "-n", "1", "-w", "500", broadcast_ip],
            capture_output=True, text=True, timeout=3,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except Exception:
        pass

    # Also try UDP broadcast on port 3702 (WS-Discovery) to wake up ONVIF devices
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(0.5)
        sock.sendto(b"\x00", (broadcast_ip, 3702))
        sock.close()
    except Exception:
        pass


# ── ONVIF WS-Discovery ────────────────────────────────────────────────────

ONVIF_DISCOVER_MSG = """<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
               xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
               xmlns:wsd="http://schemas.xmlsoap.org/ws/2005/04/discovery"
               xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
  <soap:Header>
    <wsa:MessageID>uuid:{msg_id}</wsa:MessageID>
    <wsa:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</wsa:To>
    <wsa:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</wsa:Action>
  </soap:Header>
  <soap:Body>
    <wsd:Probe>
      <wsd:Types>dn:NetworkVideoTransmitter</wsd:Types>
    </wsd:Probe>
  </soap:Body>
</soap:Envelope>"""


def onvif_ws_discovery(timeout: float = 4.0) -> list[dict]:
    """Send ONVIF WS-Discovery multicast probe and collect responses.

    All ONVIF-compliant cameras (CP Plus, Dahua, Hikvision, etc.) MUST
    respond to this multicast. This is the most reliable way to find cameras.
    """
    MULTICAST_ADDR = "239.255.255.250"
    MULTICAST_PORT = 3702
    msg_id = str(uuid.uuid4())
    probe = ONVIF_DISCOVER_MSG.format(msg_id=msg_id).strip().encode("utf-8")

    discovered = []

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(timeout)

        # Set TTL for multicast
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 4)

        # Bind to all interfaces
        sock.bind(("", 0))

        # Send probe to multicast group
        sock.sendto(probe, (MULTICAST_ADDR, MULTICAST_PORT))

        # Also try a second time after a short delay (some cameras are slow)
        time.sleep(0.3)
        sock.sendto(probe, (MULTICAST_ADDR, MULTICAST_PORT))

        # Collect responses
        end_time = time.time() + timeout
        seen_ips = set()

        while time.time() < end_time:
            try:
                data, addr = sock.recvfrom(65535)
                ip = addr[0]

                if ip in seen_ips:
                    continue
                seen_ips.add(ip)

                response_text = data.decode("utf-8", errors="ignore")

                # Extract device info from response
                info = {"ip": ip, "source": "ONVIF WS-Discovery"}

                # Try to get XAddrs (device service URL)
                xaddr_match = re.search(r"<[\w:]*XAddrs>(.*?)</[\w:]*XAddrs>", response_text)
                if xaddr_match:
                    info["xaddrs"] = xaddr_match.group(1).strip()

                # Try to get scopes (may contain hardware/name info)
                scope_match = re.search(r"<[\w:]*Scopes>(.*?)</[\w:]*Scopes>", response_text)
                if scope_match:
                    scopes = scope_match.group(1).strip()
                    info["scopes"] = scopes

                    # Extract brand from scopes
                    name_match = re.search(r"onvif://www\.onvif\.org/name/(\S+)", scopes)
                    if name_match:
                        info["name"] = name_match.group(1).replace("%20", " ")

                    hw_match = re.search(r"onvif://www\.onvif\.org/hardware/(\S+)", scopes)
                    if hw_match:
                        info["hardware"] = hw_match.group(1).replace("%20", " ")

                discovered.append(info)

            except socket.timeout:
                break
            except Exception:
                continue

        sock.close()
    except Exception as e:
        print(f"    ONVIF Discovery error: {e}")

    return discovered


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
    (8899,  "DVR-ALT"),      # Alternative DVR port
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
    for u, p in [("admin", "admin"), ("admin", "admin123"), ("admin", ""),
                 ("admin", "12345"), ("admin", "123456"), ("admin", "password"),
                 ("root", "root"), ("root", "admin")]:
        if (u, p) not in creds:
            creds.append((u, p))

    return creds


def load_config_cameras() -> list[dict]:
    """Load known camera IPs and URLs from camera_config.json."""
    cameras = []
    try:
        cfg_path = Path(__file__).parent / "camera_config.json"
        if cfg_path.exists():
            cfg = json.loads(cfg_path.read_text())
            for cam_id, cam in cfg.get("cameras", {}).items():
                url = cam.get("url", "")
                m = re.search(r"//(\d+\.\d+\.\d+\.\d+)(:\d+)?(/.*)", url)
                if m:
                    cameras.append({
                        "id": cam_id,
                        "ip": m.group(1),
                        "port": int(m.group(2)[1:]) if m.group(2) else 80,
                        "path": m.group(3),
                        "username": cam.get("username", ""),
                        "password": cam.get("password", ""),
                        "label": cam.get("label", cam_id),
                    })
    except Exception:
        pass
    return cameras


def try_snapshot(ip: str, path: str, creds: list[tuple[str, str]],
                 timeout: float = 5.0, port: int = 80) -> dict | None:
    """Try a single snapshot URL with multiple auth methods.

    Uses requests.get() (not HEAD) with Digest auth — matches exactly
    what camera_agent.py does. CP Plus cameras require this.

    IMPORTANT: CP Plus cameras DROP unauthenticated connections entirely.
    We must NOT bail on ConnectionError from no-auth attempt — we still
    need to try authenticated requests (Digest/Basic).
    """
    import requests
    from requests.auth import HTTPDigestAuth, HTTPBasicAuth

    url = f"http://{ip}:{port}{path}" if port != 80 else f"http://{ip}{path}"
    got_401 = False
    connection_failed_count = 0
    total_attempts = 0

    # Try authenticated creds FIRST (cameras often drop unauth connections)
    # Reorder: auth creds first, then no-auth
    ordered_creds = []
    for u, p in creds:
        if u:  # Has username — try first
            ordered_creds.append((u, p))
    for u, p in creds:
        if not u:  # No-auth — try last
            ordered_creds.append((u, p))

    for username, password in ordered_creds:
        auth_methods = [HTTPDigestAuth, HTTPBasicAuth] if username else [None]
        for auth_class in auth_methods:
            total_attempts += 1
            try:
                auth = auth_class(username, password) if auth_class else None
                resp = requests.get(url, auth=auth, timeout=timeout, verify=False,
                                    stream=True)
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
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.ConnectTimeout):
                connection_failed_count += 1
                # Only bail if ALL attempts fail with connection error
                # (not just the first unauth attempt)
                if connection_failed_count >= 3:
                    break  # Likely truly unreachable
                continue  # Try next auth method
            except requests.exceptions.ReadTimeout:
                continue
            except Exception:
                continue

        # If we've had 3+ connection failures, stop trying more creds
        if connection_failed_count >= 3:
            break

    if got_401:
        return {"snapshot_url": url, "auth_type": "requires_credentials",
                "username": "", "password": "", "image_size": 0, "content_type": ""}
    return None


def auth_http_probe(ip: str, creds: list[tuple[str, str]],
                    timeout: float = 5.0) -> dict | None:
    """Probe a single IP using authenticated HTTP GET on common snapshot URLs.

    This is the KEY method that detects cameras that all other probes miss.
    CP Plus cameras with Digest auth silently drop unauthenticated connections
    but respond properly to authenticated GET requests.
    """
    for path, brand in SNAPSHOT_URLS[:5]:  # Try top 5 most common URLs
        result = try_snapshot(ip, path, creds, timeout=timeout)
        if result is not None:  # Found something (even 401 = camera exists)
            result["brand"] = brand
            return result
    return None


# ── Scanner ─────────────────────────────────────────────────────────────────

def scan_ip(ip: str, creds: list[tuple[str, str]],
            is_onvif: bool = False) -> dict | None:
    """Scan a single IP for camera ports and identify cameras.

    If is_onvif=True, this IP was discovered via ONVIF WS-Discovery,
    so we KNOW it's a camera — use longer timeouts and try harder.
    """
    open_ports = []
    for port, label in CAMERA_PORTS:
        if scan_port(ip, port, timeout=1.5):
            open_ports.append((port, label))

    # Try authenticated HTTP even if no raw socket ports detected
    # CP Plus cameras often block raw sockets but respond to requests.get()
    probe_timeout = 10.0 if is_onvif else 5.0
    if not open_ports or not any(p == 80 for p, _ in open_ports):
        probe = auth_http_probe(ip, creds, timeout=probe_timeout)
        if probe:
            if not any(p == 80 for p, _ in open_ports):
                open_ports.append((80, "HTTP"))

    if not open_ports:
        return None

    result = {
        "ip": ip,
        "open_ports": open_ports,
        "title": "",
        "cameras": [],
    }

    # Get web title
    for port in [80, 8080, 9000]:
        if any(p == port for p, _ in open_ports):
            result["title"] = get_http_title(ip, port)
            if result["title"]:
                break

    # Identify camera(s)
    result["cameras"] = identify_camera(ip, open_ports, creds)

    return result


def identify_camera(ip: str, open_ports: list[tuple[int, str]],
                    creds: list[tuple[str, str]]) -> list[dict]:
    """Identify camera(s) at an IP. Returns list (DVR can have multiple channels)."""
    try:
        import requests
    except ImportError:
        return []

    http_ports = [p for p, l in open_ports if p in (80, 8080, 9000, 443)]
    if not http_ports:
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
    port = http_ports[0]

    # Step 1: Try standard snapshot URLs with authentication (10s timeout for cameras)
    for path, brand in SNAPSHOT_URLS:
        result = try_snapshot(ip, path, creds, timeout=10.0, port=port)
        if result and result.get("image_size", 0) > 0:
            result["brand"] = brand
            result["channel"] = 0
            cameras_found.append(result)
            break  # Found working URL, check for multi-channel next

    # Step 2: If found a camera, check for DVR multi-channel
    if cameras_found:
        brand = cameras_found[0].get("brand", "")
        working_creds = [(cameras_found[0].get("username", ""),
                          cameras_found[0].get("password", ""))]

        for pattern, pat_brand in DVR_CHANNEL_PATTERNS:
            if pat_brand.split()[0] not in brand.split()[0] and pat_brand.split("/")[0] not in brand:
                continue

            for ch in range(2, 17):
                path = pattern.format(ch=ch)
                result = try_snapshot(ip, path, working_creds, timeout=3.0, port=port)
                if result and result.get("image_size", 0) > 0:
                    result["brand"] = f"{pat_brand} Ch{ch}"
                    result["channel"] = ch
                    cameras_found.append(result)
                else:
                    break  # No more channels

    # Step 3: 401 fallback — camera exists but needs different auth
    if not cameras_found:
        for path, brand in SNAPSHOT_URLS[:3]:
            result = try_snapshot(ip, path, creds, timeout=3.0, port=port)
            if result:
                result["brand"] = f"{brand} (auth required)" if result["auth_type"] == "requires_credentials" else brand
                result["channel"] = 0
                cameras_found.append(result)
                break

    # Step 4: DVR ports open but no HTTP snapshot
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
        resp = requests.get(f"http://{ip}:{port}/", timeout=3, verify=False)
        if resp.status_code in (200, 401, 403):
            match = re.search(r"<title>(.*?)</title>", resp.text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
            server = resp.headers.get("Server", "")
            www_auth = resp.headers.get("WWW-Authenticate", "")
            if server:
                return f"[{server}]"
            if www_auth:
                realm = re.search(r'realm="([^"]*)"', www_auth)
                if realm:
                    return f"[{realm.group(1)}]"
    except Exception:
        pass
    return ""


def tcp_probe_all(subnet: str, ports: list[int],
                  timeout: float = 1.5, max_workers: int = 80) -> set[str]:
    """Fast TCP probe of ALL 254 IPs on key ports."""
    responsive = set()
    lock = threading.Lock()

    def _probe(ip_port):
        ip, port = ip_port
        if scan_port(ip, port, timeout=timeout):
            with lock:
                responsive.add(ip)

    tasks = [(f"{subnet}.{i}", port) for i in range(1, 255) for port in ports]

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        list(executor.map(_probe, tasks))

    return responsive


def auth_http_probe_range(subnet: str, creds: list[tuple[str, str]],
                          timeout: float = 5.0, max_workers: int = 30) -> set[str]:
    """Authenticated HTTP GET probe on ALL 254 IPs using requests.get() with Digest auth.

    This is the CRITICAL method. CP Plus cameras silently drop unauthenticated
    connections but respond to authenticated GET /cgi-bin/snapshot.cgi.
    Uses the same requests.get() + HTTPDigestAuth approach as camera_agent.py.
    """
    import requests
    from requests.auth import HTTPDigestAuth

    responsive = set()
    lock = threading.Lock()

    # Use the first non-empty credential pair for the fast sweep
    auth_creds = [(u, p) for u, p in creds if u]
    if not auth_creds:
        auth_creds = [("admin", "admin123")]

    def _probe(ip):
        # Try GET with Digest auth on the most common snapshot URL
        for path in ["/cgi-bin/snapshot.cgi", "/Streaming/channels/1/picture"]:
            for username, password in auth_creds[:3]:  # Try top 3 creds
                try:
                    url = f"http://{ip}{path}"
                    resp = requests.get(
                        url,
                        auth=HTTPDigestAuth(username, password),
                        timeout=timeout,
                        verify=False,
                        stream=True,
                    )
                    # ANY response means the IP is alive (200, 401, 403, etc.)
                    if resp.status_code > 0:
                        with lock:
                            responsive.add(ip)
                        return
                except (requests.exceptions.ConnectionError,
                        requests.exceptions.ConnectTimeout):
                    break  # Not listening — skip to next path
                except requests.exceptions.ReadTimeout:
                    # Timeout but connected = device exists
                    with lock:
                        responsive.add(ip)
                    return
                except Exception:
                    pass

    ips = [f"{subnet}.{i}" for i in range(1, 255)]

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        list(executor.map(_probe, ips))

    return responsive


def discover_hosts(subnet: str, max_workers: int = 100) -> list[str]:
    """Fast ping sweep to find live hosts."""
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


def scan_subnet(subnet: str, local_ips: list[str],
                max_workers: int = 30) -> list[dict]:
    """Full subnet scan using ALL 6 discovery methods."""
    creds = load_config_credentials()
    config_cameras = load_config_cameras()
    responsive = set()

    # ── Phase 1a: ONVIF WS-Discovery (most reliable for cameras) ──────
    print(f"\n  Phase 1: ONVIF WS-Discovery multicast...")
    onvif_results = onvif_ws_discovery(timeout=4.0)
    onvif_ips = set()
    for dev in onvif_results:
        ip = dev["ip"]
        if ip.startswith(subnet + "."):
            onvif_ips.add(ip)
            responsive.add(ip)
            name = dev.get("name", dev.get("hardware", ""))
            extra = f" ({name})" if name else ""
            print(f"    ONVIF found: {ip}{extra}")
    if not onvif_ips:
        print(f"    No ONVIF responses (cameras may not support WS-Discovery)")

    # ── Phase 1b: Config-known IPs ─────────────────────────────────────
    config_ips = set()
    for cam in config_cameras:
        if cam["ip"].startswith(subnet + "."):
            config_ips.add(cam["ip"])
            responsive.add(cam["ip"])
            print(f"    Config known: {cam['ip']} ({cam['label']})")

    # ── Phase 2: ARP broadcast flood → read ARP table ──────────────────
    print(f"  Phase 2: ARP broadcast + table scan...")
    arp_broadcast_flood(subnet)
    time.sleep(1)  # Wait for ARP responses
    arp = get_arp_table()
    arp_count = 0
    for ip, mac in arp.items():
        if ip.startswith(subnet + ".") and ip not in responsive:
            responsive.add(ip)
            arp_count += 1
    print(f"    ARP table: {len(arp)} entries, {arp_count} new on this subnet")

    # ── Phase 3: Authenticated HTTP probe (THE KEY METHOD) ─────────────
    print(f"  Phase 3: Authenticated HTTP probe {subnet}.1-254 "
          f"(Digest auth on /cgi-bin/snapshot.cgi)...")
    print(f"    This may take 30-60 seconds...")
    auth_hosts = auth_http_probe_range(subnet, creds, timeout=5.0, max_workers=30)
    added_by_auth = len(auth_hosts - responsive)
    responsive |= auth_hosts
    print(f"    Auth HTTP: {len(auth_hosts)} hosts ({added_by_auth} new)")

    # ── Phase 4: TCP port probe ────────────────────────────────────────
    key_ports = [80, 554, 37777, 8000]
    print(f"  Phase 4: TCP probe {subnet}.1-254 on ports {key_ports}...")
    tcp_hosts = tcp_probe_all(subnet, key_ports, timeout=1.5, max_workers=80)
    added_by_tcp = len(tcp_hosts - responsive)
    responsive |= tcp_hosts
    print(f"    TCP: {len(tcp_hosts)} hosts ({added_by_tcp} new)")

    # ── Phase 5: Ping sweep ────────────────────────────────────────────
    print(f"  Phase 5: Ping sweep...")
    ping_hosts = discover_hosts(subnet, max_workers=100)
    added_by_ping = len(set(ping_hosts) - responsive)
    responsive |= set(ping_hosts)
    if added_by_ping:
        print(f"    Ping: {added_by_ping} new host(s)")

    # ── Summary ────────────────────────────────────────────────────────
    # Remove local IPs from scan targets
    for lip in local_ips:
        responsive.discard(lip)

    print(f"\n    Total unique hosts to scan: {len(responsive)}")

    if not responsive:
        print("    No hosts found on this subnet.")
        return []

    # ── Phase 6: Full port scan + camera identification ────────────────
    hosts = sorted(responsive, key=lambda ip: [int(x) for x in ip.split(".")])
    print(f"  Phase 6: Full camera identification on {len(hosts)} hosts...")

    results = []
    lock = threading.Lock()
    scanned = [0]

    # Track which IPs are ONVIF-discovered or config-known (try harder)
    priority_ips = onvif_ips | config_ips

    def _scan(ip):
        r = scan_ip(ip, creds, is_onvif=(ip in priority_ips))
        with lock:
            scanned[0] += 1
            if r:
                port_str = ", ".join(f"{p}({l})" for p, l in r["open_ports"])
                cam_count = len(r["cameras"])
                marker = f" [star] {cam_count} camera(s)" if cam_count > 0 else ""
                print(f"    Found: {ip:16s} ports: {port_str}{marker}")
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
    print("  Camera & DVR Scanner v2.0")
    print("  6-method discovery: ONVIF + Auth HTTP + ARP + TCP + Ping + Config")
    print("  \"No camera should go untraced\"")
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
            print("  Trying authenticated HTTP probe directly...")
            probe = auth_http_probe(target, creds, timeout=8.0)
            if probe:
                print(f"  FOUND via auth probe: {probe.get('brand', 'Unknown')}")
                print(f"  URL: {probe.get('snapshot_url', '')}")
                print(f"  Auth: {probe.get('auth_type', '')}")
            else:
                print(f"\n  Camera NOT reachable at {target}")
                print("  Check: cable connected? Camera powered on?")
                print(f"  Try:   ping {target}")
        return

    # Discover local subnets
    local_ips = get_local_ips()
    if not local_ips:
        print("\n  ERROR: Could not detect local IP address.")
        return

    print(f"\n  Local IP(s): {', '.join(local_ips)}")

    if target and "/" in target:
        subnet = target.rsplit(".", 1)[0]
        subnets = [subnet]
    else:
        subnets = get_subnets(local_ips)

    # Add subnets from camera_config.json
    config_cameras = load_config_cameras()
    for cam in config_cameras:
        parts = cam["ip"].split(".")
        cfg_subnet = f"{parts[0]}.{parts[1]}.{parts[2]}"
        if cfg_subnet not in subnets:
            subnets.append(cfg_subnet)
            print(f"  (Added {cfg_subnet}.0/24 from camera_config.json)")

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
        print("    3. Try single IP: python scan_cameras.py <camera-ip>")
        print("    4. Try specific subnet:")
        print("       python scan_cameras.py 192.168.0.0/24")
        print("       python scan_cameras.py 192.168.1.0/24")
        return

    camera_results = []
    other_results = []

    for r in results:
        if r.get("cameras"):
            camera_results.append(r)
        else:
            other_results.append(r)

    total_channels = sum(len(r["cameras"]) for r in camera_results)

    if camera_results:
        print(f"\n  CAMERAS / DVRs FOUND: {len(camera_results)} device(s), "
              f"{total_channels} channel(s)")
        print(f"  {'-' * 60}")

        all_cameras = []
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
                print(f"      -> Brand:    {cam['brand']}{ch_label}")
                print(f"         URL:      {cam['snapshot_url']}")
                print(f"         Auth:     {cam['auth_type']}")
                if cam.get("image_size"):
                    print(f"         Image:    {cam['image_size']:,} bytes")
                all_cameras.append((ip, cam))

        # Print recommended config
        if all_cameras:
            print(f"\n  {'-' * 60}")
            print("  RECOMMENDED camera_config.json:")
            print()
            print('    "cameras": {')

            cam_ids = ["front", "top", "side", "rear"]
            shown = 0
            for i, (ip, cam) in enumerate(all_cameras):
                if cam.get("auth_type") in ("rtsp_only", "dvr_detected"):
                    continue
                cam_id = cam_ids[shown] if shown < len(cam_ids) else f"cam{shown+1}"
                shown += 1
                is_last = (shown >= len(all_cameras) or shown >= 4)
                auth_note = "  <- UPDATE" if cam["auth_type"] == "requires_credentials" else ""
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
            title = f" - {r['title']}" if r.get("title") else ""
            print(f"    {r['ip']:16s} ports: {port_str}{title}")

    print(f"\n  Summary: {len(camera_results)} camera device(s), "
          f"{total_channels} channel(s), {len(other_results)} other device(s)")
    print()


if __name__ == "__main__":
    main()
