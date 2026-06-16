"""
Camera IP Scanner v3.0 — ROBUST, deterministic camera discovery.

Architecture:
  Phase 1  TCP Port Scan (PRIMARY)   — scans ALL 254 IPs on camera-specific
           ports (37777 Dahua/CPPlus, 554 RTSP, 80 HTTP, 8080, 8000 Hik).
           TCP SYN is a kernel operation — cannot be defeated by auth or
           application-level firewalls. If a port is open, we WILL find it.

  Phase 2  ONVIF WS-Discovery        — multicast probe on EACH local
           interface (not just default). Sends 3 probes with gaps.
           Supplement only — NOT relied upon.

  Phase 3  Config-known IPs + ARP    — check camera_config.json IPs
           directly, plus read ARP table for extras.

  Phase 4  Camera Identification     — authenticated HTTP snapshot test
           ONLY on confirmed-live hosts from Phases 1-3. Fast because
           we test 5-15 hosts, not 254.

Design principles:
  - TCP port scan is PRIMARY. ONVIF is a bonus.
  - Port 37777 = Dahua/CP Plus guaranteed. Port 554 = any RTSP camera.
  - Auth-first ordering: Digest auth tried BEFORE unauthenticated.
  - Longer timeouts (3s) on TCP to handle slow cameras.
  - Per-interface ONVIF binding for multi-homed machines.

Usage:
  python scan_cameras.py                   # auto-detect subnet
  python scan_cameras.py 192.168.0.0/24    # specific subnet
  python scan_cameras.py 192.168.0.101     # test single IP
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

# ══════════════════════════════════════════════════════════════════════════
#  NETWORK HELPERS
# ══════════════════════════════════════════════════════════════════════════

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


def scan_port(ip: str, port: int, timeout: float = 3.0) -> bool:
    """Check if a TCP port is open using connect_ex (kernel SYN)."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((ip, port))
        sock.close()
        return result == 0
    except Exception:
        return False


def get_arp_table() -> dict[str, str]:
    """Parse the OS ARP table."""
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
    """Ping broadcast to populate ARP table."""
    broadcast_ip = f"{subnet}.255"
    try:
        subprocess.run(
            ["ping", "-n", "1", "-w", "500", broadcast_ip],
            capture_output=True, text=True, timeout=3,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except Exception:
        pass
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(0.5)
        sock.sendto(b"\x00", (broadcast_ip, 3702))
        sock.close()
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════
#  PHASE 1: TCP PORT SCAN (PRIMARY DETECTION METHOD)
# ══════════════════════════════════════════════════════════════════════════

# Ports that are DEFINITIVE proof of camera/DVR/NVR:
#   37777 = Dahua/CP Plus binary protocol (ALWAYS open, cannot be disabled)
#   554   = RTSP (open on virtually every IP camera)
#   80    = HTTP web UI
#   8080  = HTTP alt
#   8000  = Hikvision SDK
#   34567 = Chinese DVR command port

CAMERA_PORTS = [
    (37777, "DAHUA/CPPLUS"),    # CP Plus/Dahua binary — most reliable indicator
    (554,   "RTSP"),            # RTSP — universal camera indicator
    (80,    "HTTP"),            # Web interface
    (8080,  "HTTP-ALT"),        # Alternative web
    (8000,  "HIK-SDK"),         # Hikvision SDK
    (34567, "DVR-CMD"),         # Chinese DVR
    (443,   "HTTPS"),           # HTTPS
    (8200,  "HIK-ISAPI"),      # Hikvision ISAPI
    (9000,  "CPPLUS-WEB"),     # CP Plus web alt
    (5000,  "ONVIF"),          # ONVIF service
    (8899,  "DVR-ALT"),        # Alternative DVR
]

# The critical ports — if ANY of these are open, it's almost certainly a camera
CRITICAL_PORTS = [37777, 554, 34567, 8000]


def tcp_scan_subnet(subnet: str, timeout: float = 3.0,
                    max_workers: int = 150) -> dict[str, list[tuple[int, str]]]:
    """Scan ALL 254 IPs on all camera ports using raw TCP SYN.

    This is the PRIMARY discovery method. TCP connect is a kernel
    operation that cannot be blocked by application auth, ONVIF
    settings, or firmware quirks. If a port is listening, we find it.

    Returns: {ip: [(port, label), ...]}
    """
    results = {}
    lock = threading.Lock()

    def _probe(args):
        ip, port, label = args
        if scan_port(ip, port, timeout=timeout):
            with lock:
                if ip not in results:
                    results[ip] = []
                results[ip].append((port, label))

    # Build task list: 254 IPs x N ports
    tasks = []
    for i in range(1, 255):
        ip = f"{subnet}.{i}"
        for port, label in CAMERA_PORTS:
            tasks.append((ip, port, label))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        list(executor.map(_probe, tasks))

    return results


# ══════════════════════════════════════════════════════════════════════════
#  PHASE 2: ONVIF WS-DISCOVERY (SUPPLEMENTARY)
# ══════════════════════════════════════════════════════════════════════════

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


def onvif_ws_discovery(local_ips: list[str], timeout: float = 5.0,
                       retries: int = 3) -> list[dict]:
    """Send ONVIF WS-Discovery probe on EACH local interface with retries.

    Improvements over v2:
      - Binds to each local interface separately via IP_MULTICAST_IF
      - Sends probe 3 times per interface with 0.5s gaps
      - 5-second collection window after all probes sent
    """
    MULTICAST_ADDR = "239.255.255.250"
    MULTICAST_PORT = 3702
    discovered = []
    seen_ips = set()

    # Get real LAN interfaces (skip virtual 172.x)
    real_ips = [ip for ip in local_ips if not ip.startswith("172.")]
    if not real_ips:
        real_ips = local_ips[:1]  # Fallback to first

    for local_ip in real_ips:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.settimeout(timeout)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 4)

            # Bind to specific interface for multicast
            # On Windows, bind to the local IP directly (not "")
            try:
                sock.bind((local_ip, 0))
            except OSError:
                # Fallback: bind to any interface
                sock.bind(("", 0))

            try:
                sock.setsockopt(
                    socket.IPPROTO_IP,
                    socket.IP_MULTICAST_IF,
                    socket.inet_aton(local_ip)
                )
            except OSError:
                pass  # Not critical — multicast will use default route

            # Send probe multiple times with gaps
            for attempt in range(retries):
                msg_id = str(uuid.uuid4())
                probe = ONVIF_DISCOVER_MSG.format(msg_id=msg_id).strip().encode("utf-8")
                sock.sendto(probe, (MULTICAST_ADDR, MULTICAST_PORT))
                if attempt < retries - 1:
                    time.sleep(0.5)

            # Collect responses
            end_time = time.time() + timeout
            while time.time() < end_time:
                try:
                    data, addr = sock.recvfrom(65535)
                    ip = addr[0]
                    if ip in seen_ips or ip in local_ips:
                        continue
                    seen_ips.add(ip)

                    response_text = data.decode("utf-8", errors="ignore")
                    info = {"ip": ip, "source": "ONVIF WS-Discovery"}

                    xaddr_match = re.search(
                        r"<[\w:]*XAddrs>(.*?)</[\w:]*XAddrs>", response_text
                    )
                    if xaddr_match:
                        info["xaddrs"] = xaddr_match.group(1).strip()

                    scope_match = re.search(
                        r"<[\w:]*Scopes>(.*?)</[\w:]*Scopes>", response_text
                    )
                    if scope_match:
                        scopes = scope_match.group(1).strip()
                        info["scopes"] = scopes
                        name_match = re.search(
                            r"onvif://www\.onvif\.org/name/(\S+)", scopes
                        )
                        if name_match:
                            info["name"] = name_match.group(1).replace("%20", " ")
                        hw_match = re.search(
                            r"onvif://www\.onvif\.org/hardware/(\S+)", scopes
                        )
                        if hw_match:
                            info["hardware"] = hw_match.group(1).replace("%20", " ")

                    discovered.append(info)

                except socket.timeout:
                    break
                except Exception:
                    continue

            sock.close()
        except Exception as e:
            print(f"      ONVIF on {local_ip}: {e}")

    return discovered


# ══════════════════════════════════════════════════════════════════════════
#  CAMERA CREDENTIALS & CONFIG
# ══════════════════════════════════════════════════════════════════════════

def load_config_credentials() -> list[tuple[str, str]]:
    """Load credentials from camera_config.json + common defaults.
    Auth creds returned FIRST (CP Plus drops unauthenticated connections).
    """
    auth_creds = []
    no_auth = [("", "")]

    # From config file
    try:
        cfg_path = Path(__file__).parent / "camera_config.json"
        if cfg_path.exists():
            cfg = json.loads(cfg_path.read_text())
            for cam in cfg.get("cameras", {}).values():
                u = cam.get("username", "")
                p = cam.get("password", "")
                if u and (u, p) not in auth_creds:
                    auth_creds.append((u, p))
    except Exception:
        pass

    # Common defaults
    for u, p in [("admin", "admin"), ("admin", "admin123"), ("admin", ""),
                 ("admin", "12345"), ("admin", "123456"), ("admin", "password"),
                 ("root", "root"), ("root", "admin")]:
        if (u, p) not in auth_creds:
            auth_creds.append((u, p))

    # Auth-first ordering: cameras drop unauthenticated connections
    return auth_creds + no_auth


def load_config_cameras() -> list[dict]:
    """Load known camera IPs from camera_config.json."""
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


# ══════════════════════════════════════════════════════════════════════════
#  SNAPSHOT DETECTION & CAMERA IDENTIFICATION
# ══════════════════════════════════════════════════════════════════════════

SNAPSHOT_URLS = [
    ("/cgi-bin/snapshot.cgi",                    "CP Plus / Dahua"),
    ("/cgi-bin/snapshot.cgi?channel=1",          "CP Plus / Dahua Ch1"),
    ("/Streaming/channels/1/picture",            "Hikvision"),
    ("/ISAPI/Streaming/channels/101/picture",    "Hikvision (ISAPI)"),
    ("/snap.jpg",                                "Generic ONVIF"),
    ("/snapshot.jpg",                            "Generic"),
    ("/jpg/image.jpg",                           "Axis"),
    ("/cgi-bin/api.cgi?cmd=Snap&channel=0",      "Reolink"),
    ("/capture",                                 "Generic"),
    ("/onvif/snapshot",                          "ONVIF"),
    ("/image/jpeg.cgi",                          "D-Link"),
]

DVR_CHANNEL_PATTERNS = [
    ("/cgi-bin/snapshot.cgi?channel={ch}",             "CP Plus / Dahua"),
    ("/Streaming/channels/{ch}01/picture",             "Hikvision"),
    ("/ISAPI/Streaming/channels/{ch}01/picture",       "Hikvision (ISAPI)"),
    ("/cgi-bin/api.cgi?cmd=Snap&channel={ch}",         "Reolink"),
]


def try_snapshot(ip: str, path: str, creds: list[tuple[str, str]],
                 timeout: float = 8.0, port: int = 80) -> dict | None:
    """Try a snapshot URL with authentication.

    Auth-first: Digest auth tried BEFORE unauthenticated.
    CP Plus cameras DROP unauthenticated connections entirely —
    we MUST try auth first and NOT bail on ConnectionError from
    the no-auth attempt.
    """
    import requests
    from requests.auth import HTTPDigestAuth, HTTPBasicAuth

    url = f"http://{ip}:{port}{path}" if port != 80 else f"http://{ip}{path}"
    got_401 = False
    connection_fails = 0

    for username, password in creds:
        if username:
            auth_methods = [HTTPDigestAuth, HTTPBasicAuth]
        else:
            auth_methods = [None]

        for auth_class in auth_methods:
            try:
                auth = auth_class(username, password) if auth_class else None
                resp = requests.get(url, auth=auth, timeout=timeout,
                                    verify=False, stream=True)
                content_type = resp.headers.get("Content-Type", "")

                if resp.status_code == 200 and (
                    "image" in content_type or len(resp.content) > 1000
                ):
                    auth_label = "none"
                    if auth_class:
                        name = auth_class.__name__.replace("HTTP", "").replace("Auth", "")
                        auth_label = f"{name}({username})"
                    return {
                        "snapshot_url": url,
                        "auth_type": auth_label,
                        "username": username,
                        "password": password,
                        "image_size": len(resp.content),
                        "content_type": content_type,
                    }
                elif resp.status_code == 401:
                    got_401 = True

            except (requests.exceptions.ConnectionError,
                    requests.exceptions.ConnectTimeout):
                connection_fails += 1
                # Only bail after 4+ connection failures
                # (auth creds come first, so we may get several before
                #  no-auth at the end — that's fine)
                if connection_fails >= 4:
                    break
                continue
            except requests.exceptions.ReadTimeout:
                continue
            except Exception:
                continue

        if connection_fails >= 4:
            break

    if got_401:
        return {"snapshot_url": url, "auth_type": "requires_credentials",
                "username": "", "password": "", "image_size": 0,
                "content_type": ""}
    return None


def classify_device(ip: str, open_ports: list[tuple[int, str]]) -> str:
    """Classify device type from open ports."""
    port_set = {p for p, _ in open_ports}

    if 37777 in port_set or 34567 in port_set:
        return "DVR/NVR (Dahua/CP Plus)"
    if 8000 in port_set or 8200 in port_set:
        return "Hikvision Camera/NVR"
    if 554 in port_set and 80 in port_set:
        return "IP Camera"
    if 554 in port_set:
        return "RTSP Device"
    if 80 in port_set or 8080 in port_set:
        return "Network Device (HTTP)"
    return "Unknown"


def get_http_title(ip: str, port: int = 80) -> str:
    """Get the HTML title from device web interface."""
    try:
        import requests
        resp = requests.get(f"http://{ip}:{port}/", timeout=4, verify=False)
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


def identify_cameras(ip: str, open_ports: list[tuple[int, str]],
                     creds: list[tuple[str, str]]) -> list[dict]:
    """Identify camera(s) at an IP. Returns list (DVR may have channels)."""
    try:
        import requests
    except ImportError:
        return []

    port_set = {p for p, _ in open_ports}
    http_ports = [p for p in [80, 8080, 9000, 443] if p in port_set]

    if not http_ports:
        # No HTTP port but has RTSP or DVR port — camera exists but no snapshot
        if 554 in port_set:
            return [{
                "brand": "RTSP Camera",
                "snapshot_url": f"rtsp://{ip}:554/cam/realmonitor?channel=1&subtype=0",
                "auth_type": "rtsp_only",
                "username": "", "password": "",
                "image_size": 0, "content_type": "",
                "channel": 0,
            }]
        if 37777 in port_set or 34567 in port_set:
            return [{
                "brand": "DVR/NVR (SDK port only)",
                "snapshot_url": f"http://{ip}/",
                "auth_type": "dvr_detected",
                "username": "", "password": "",
                "image_size": 0, "content_type": "",
                "channel": 0,
            }]
        return []

    cameras_found = []
    port = http_ports[0]

    # Step 1: Try snapshot URLs with auth (10s timeout for cameras)
    for path, brand in SNAPSHOT_URLS:
        result = try_snapshot(ip, path, creds, timeout=10.0, port=port)
        if result and result.get("image_size", 0) > 0:
            result["brand"] = brand
            result["channel"] = 0
            cameras_found.append(result)
            break

    # Step 2: DVR multi-channel detection
    if cameras_found:
        brand = cameras_found[0].get("brand", "")
        working_creds = [(cameras_found[0].get("username", ""),
                          cameras_found[0].get("password", ""))]

        for pattern, pat_brand in DVR_CHANNEL_PATTERNS:
            if pat_brand.split()[0] not in brand.split()[0] and \
               pat_brand.split("/")[0] not in brand:
                continue
            for ch in range(2, 17):
                path = pattern.format(ch=ch)
                result = try_snapshot(ip, path, working_creds, timeout=4.0,
                                     port=port)
                if result and result.get("image_size", 0) > 0:
                    result["brand"] = f"{pat_brand} Ch{ch}"
                    result["channel"] = ch
                    cameras_found.append(result)
                else:
                    break

    # Step 3: 401 fallback — camera exists but needs different credentials
    if not cameras_found:
        for path, brand in SNAPSHOT_URLS[:4]:
            result = try_snapshot(ip, path, creds, timeout=5.0, port=port)
            if result:
                if result["auth_type"] == "requires_credentials":
                    result["brand"] = f"{brand} (auth required)"
                else:
                    result["brand"] = brand
                result["channel"] = 0
                cameras_found.append(result)
                break

    # Step 4: DVR ports but no HTTP snapshot
    if not cameras_found:
        dvr_ports = [p for p in [37777, 34567, 8000, 8899] if p in port_set]
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


# ══════════════════════════════════════════════════════════════════════════
#  FULL SUBNET SCAN
# ══════════════════════════════════════════════════════════════════════════

def ping_sweep(subnet: str, max_workers: int = 40) -> set[str]:
    """ICMP ping sweep in batches to avoid Windows throttling.

    Windows limits concurrent ICMP — running 254 pings at once
    causes silent drops. Batch to 40 at a time for reliability.
    """
    live = set()
    lock = threading.Lock()

    def _ping(ip):
        try:
            result = subprocess.run(
                ["ping", "-n", "1", "-w", "1500", ip],
                capture_output=True, text=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            if result.returncode == 0:
                with lock:
                    live.add(ip)
        except Exception:
            pass

    ips = [f"{subnet}.{i}" for i in range(1, 255)]

    # Batch to avoid Windows ICMP throttling
    batch_size = max_workers
    for batch_start in range(0, len(ips), batch_size):
        batch = ips[batch_start:batch_start + batch_size]
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            list(executor.map(_ping, batch))

    return live


def scan_subnet(subnet: str, local_ips: list[str],
                max_workers: int = 30) -> list[dict]:
    """Full subnet scan — ROBUST multi-phase approach.

    Architecture (designed for 100% reliability):
      Phase 1: Host Discovery (ARP + Ping + Config)
               Find ALL live hosts first. ARP and Ping are OS-level
               operations that always work.
      Phase 2: TCP Port Scan (only on live hosts)
               Scan 5-20 hosts x 11 ports = ~200 connections
               (vs 254 x 11 = 2794 that causes socket exhaustion)
      Phase 3: Safety Net — TCP scan critical ports on FULL subnet
               Catches devices that don't respond to ping/ARP
               but do have camera ports open (37777, 554).
               Uses batched scanning to avoid socket exhaustion.
      Phase 4: ONVIF WS-Discovery (bonus)
      Phase 5: Camera Identification (on confirmed hosts)
    """
    creds = load_config_credentials()
    config_cameras = load_config_cameras()

    all_hosts = {}       # ip -> set of (port, label)
    onvif_info = {}      # ip -> ONVIF device info

    # ── Phase 1: Host Discovery ──────────────────────────────────────
    print(f"\n  Phase 1: Host discovery (ARP + Ping + Config)...")

    # 1a: ARP broadcast + table read
    arp_broadcast_flood(subnet)
    time.sleep(0.5)
    arp = get_arp_table()
    arp_hosts = set()
    for ip, mac in arp.items():
        if ip.startswith(subnet + ".") and ip not in local_ips:
            if not ip.endswith(".255"):
                arp_hosts.add(ip)

    if arp_hosts:
        print(f"    ARP: {len(arp_hosts)} host(s) - "
              f"{', '.join(sorted(arp_hosts, key=lambda x: [int(n) for n in x.split('.')]))}")

    # 1b: Ping sweep (catches hosts not in ARP yet)
    print(f"    Ping sweep {subnet}.1-254...")
    ping_hosts = ping_sweep(subnet, max_workers=40)
    ping_new = ping_hosts - arp_hosts - set(local_ips)

    # Detect "ghost pings" — if > 50% of IPs respond, it's probably a
    # router/firewall proxying pings (very common with managed switches).
    # In that case, ping results are useless — only trust ARP.
    if len(ping_hosts) > 128:
        print(f"    Ping: {len(ping_hosts)} responses (> 50% of subnet)")
        print(f"    WARNING: Router is likely proxying pings (ghost hosts)")
        print(f"    Ignoring ping results - using ARP + TCP only")
        ping_hosts = set()  # Discard — they're ghost responses
        ping_new = set()
    elif ping_new:
        print(f"    Ping: {len(ping_new)} new host(s) - "
              f"{', '.join(sorted(list(ping_new)[:10], key=lambda x: [int(n) for n in x.split('.')]))}"
              f"{'...' if len(ping_new) > 10 else ''}")
    else:
        print(f"    Ping: {len(ping_hosts)} host(s) (all already in ARP)")

    # 1c: Config-known IPs
    config_ips = set()
    for cam in config_cameras:
        ip = cam["ip"]
        if ip.startswith(subnet + ".") and ip not in local_ips:
            config_ips.add(ip)
            print(f"    Config: {ip} ({cam['label']})")

    # Combine all discovered hosts
    discovered_hosts = (arp_hosts | ping_hosts | config_ips) - set(local_ips)
    print(f"    Real hosts found: {len(discovered_hosts)}")

    # ── Phase 2: TCP Port Scan on discovered hosts ───────────────────
    if discovered_hosts:
        print(f"\n  Phase 2: TCP port scan on {len(discovered_hosts)} "
              f"live hosts ({len(CAMERA_PORTS)} ports each)...")

        lock = threading.Lock()

        def _scan_host_ports(ip):
            host_ports = set()
            for port, label in CAMERA_PORTS:
                if scan_port(ip, port, timeout=3.0):
                    host_ports.add((port, label))
            if host_ports:
                with lock:
                    all_hosts[ip] = host_ports

        host_list = sorted(discovered_hosts,
                           key=lambda x: [int(n) for n in x.split(".")])
        with ThreadPoolExecutor(max_workers=min(len(host_list) * 3, 60)) as executor:
            list(executor.map(_scan_host_ports, host_list))

        for ip in sorted(all_hosts.keys(),
                         key=lambda x: [int(n) for n in x.split(".")]):
            ports_str = ", ".join(f"{p}({l})" for p, l in sorted(all_hosts[ip]))
            is_camera = any(p in CRITICAL_PORTS for p, _ in all_hosts[ip])
            marker = " <<< CAMERA" if is_camera else ""
            print(f"    {ip:16s} {ports_str}{marker}")

        print(f"    Hosts with open ports: {len(all_hosts)}")

    # ── Phase 3: Safety net — full subnet scan on critical ports ─────
    #    Catches cameras that don't respond to ping/ARP (some DVRs
    #    disable ICMP) but DO have camera ports open.
    print(f"\n  Phase 3: Safety net - TCP scan {subnet}.1-254 "
          f"on ports 37777 + 554...")

    safety_found = set()
    lock = threading.Lock()

    def _safety_probe(args):
        ip, port, label = args
        if ip in all_hosts or ip in local_ips:
            return
        if scan_port(ip, port, timeout=3.0):
            with lock:
                safety_found.add(ip)
                if ip not in all_hosts:
                    all_hosts[ip] = set()
                all_hosts[ip].add((port, label))

    # Only scan the TWO most critical ports (37777 = Dahua, 554 = RTSP)
    # This is 254 x 2 = 508 connections — very manageable
    safety_tasks = []
    for i in range(1, 255):
        ip = f"{subnet}.{i}"
        if ip not in all_hosts and ip not in local_ips:
            safety_tasks.append((ip, 37777, "DAHUA/CPPLUS"))
            safety_tasks.append((ip, 554, "RTSP"))
            safety_tasks.append((ip, 80, "HTTP"))

    # Process in batches of 60 to avoid socket exhaustion
    batch_size = 60
    for batch_start in range(0, len(safety_tasks), batch_size):
        batch = safety_tasks[batch_start:batch_start + batch_size]
        with ThreadPoolExecutor(max_workers=30) as executor:
            list(executor.map(_safety_probe, batch))

    if safety_found:
        for ip in sorted(safety_found,
                         key=lambda x: [int(n) for n in x.split(".")]):
            ports_str = ", ".join(f"{p}({l})" for p, l in sorted(all_hosts[ip]))
            print(f"    NEW: {ip:16s} {ports_str} (missed by ping/ARP!)")
    else:
        print(f"    No additional hosts found")

    # ── Phase 4: ONVIF WS-Discovery (bonus) ──────────────────────────
    print(f"\n  Phase 4: ONVIF WS-Discovery (per-interface, 3 retries)...")
    onvif_results = onvif_ws_discovery(local_ips, timeout=5.0, retries=3)

    onvif_new_ips = []
    for dev in onvif_results:
        ip = dev["ip"]
        if ip in local_ips or not ip.startswith(subnet + "."):
            continue
        onvif_info[ip] = dev
        name = dev.get("name", dev.get("hardware", ""))
        extra = f" ({name})" if name else ""
        was_new = ip not in all_hosts or not all_hosts.get(ip)
        if ip not in all_hosts:
            all_hosts[ip] = set()
        if was_new:
            onvif_new_ips.append(ip)
        print(f"    ONVIF: {ip}{extra}")

    if not onvif_results:
        print(f"    No ONVIF responses (not critical)")

    # Port-scan ONVIF-discovered hosts that we didn't already scan
    if onvif_new_ips:
        print(f"    Port-scanning {len(onvif_new_ips)} ONVIF host(s)...")
        for ip in onvif_new_ips:
            for port, label in CAMERA_PORTS:
                if scan_port(ip, port, timeout=3.0):
                    all_hosts[ip].add((port, label))
            if all_hosts[ip]:
                ports_str = ", ".join(f"{p}({l})" for p, l in sorted(all_hosts[ip]))
                print(f"    {ip:16s} {ports_str}")
            else:
                print(f"    {ip:16s} (no ports found, will try HTTP probe)")

    # Remove local IPs
    for lip in local_ips:
        all_hosts.pop(lip, None)

    # Ensure ALL hosts with any evidence of being cameras are kept
    total = len(all_hosts)
    hosts_with_ports = {ip for ip, ports in all_hosts.items() if ports}
    hosts_onvif_only = set(onvif_info.keys()) - hosts_with_ports - set(local_ips)
    print(f"\n    Total hosts: {total} "
          f"({len(hosts_with_ports)} with ports, "
          f"{len(hosts_onvif_only)} ONVIF-only)")

    if not all_hosts:
        print("    No hosts found on this subnet.")
        return []

    # ── Phase 5: Camera identification ────────────────────────────────
    print(f"\n  Phase 5: Camera identification...")

    results = []
    lock = threading.Lock()
    scanned = [0]

    def _identify(ip):
        ports = all_hosts.get(ip, set())

        # If no ports found yet (ONVIF-only or config-only), do quick check
        if not ports:
            for port, label in CAMERA_PORTS[:6]:
                if scan_port(ip, port, timeout=3.0):
                    ports.add((port, label))

        port_list = sorted(ports)

        # Get device info
        title = ""
        for p in [80, 8080, 9000]:
            if any(pp == p for pp, _ in port_list):
                title = get_http_title(ip, p)
                if title:
                    break

        # Identify cameras
        cameras = identify_cameras(ip, port_list, creds)

        with lock:
            scanned[0] += 1
            if port_list:
                port_str = ", ".join(f"{p}({l})" for p, l in port_list)
                cam_count = len(cameras)
                if cam_count > 0:
                    print(f"    [*] {ip:16s} {cam_count} camera(s) "
                          f"| {port_str}")
                else:
                    has_cam_port = any(p in CRITICAL_PORTS for p, _ in port_list)
                    if has_cam_port:
                        print(f"    [?] {ip:16s} camera ports open but "
                              f"no snapshot | {port_str}")

            r = {
                "ip": ip,
                "open_ports": port_list,
                "title": title,
                "cameras": cameras,
                "device_type": classify_device(ip, port_list),
                "onvif": onvif_info.get(ip),
            }
            results.append(r)

    # Identify hosts with open ports + ONVIF-found hosts (always scan these)
    onvif_set = set(onvif_info.keys()) - set(local_ips)
    identify_list = sorted(
        [ip for ip in all_hosts if all_hosts[ip] or ip in onvif_set],
        key=lambda x: [int(n) for n in x.split(".")]
    )

    if identify_list:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(_identify, ip) for ip in identify_list]
            for f in as_completed(futures):
                try:
                    f.result()
                except Exception:
                    pass

    print(f"\n    Identified {scanned[0]} hosts")
    return sorted(results, key=lambda r: [int(x) for x in r["ip"].split(".")])


# ══════════════════════════════════════════════════════════════════════════
#  SINGLE IP DEEP TEST
# ══════════════════════════════════════════════════════════════════════════

def test_single_ip(ip: str):
    """Deep connectivity test for a single IP."""
    creds = load_config_credentials()

    print(f"\n  Deep test: {ip}")
    print(f"  {'=' * 50}")

    # 1. Ping
    print(f"\n  1. Ping test...")
    try:
        result = subprocess.run(
            ["ping", "-n", "2", "-w", "1000", ip],
            capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        if result.returncode == 0:
            print(f"     PASS - ping replies received")
        else:
            print(f"     FAIL - no ping reply (may still be reachable)")
    except Exception as e:
        print(f"     ERROR - {e}")

    # 2. All ports
    print(f"\n  2. Port scan (all camera ports)...")
    open_ports = []
    for port, label in CAMERA_PORTS:
        is_open = scan_port(ip, port, timeout=3.0)
        status = "OPEN" if is_open else "closed"
        if is_open:
            open_ports.append((port, label))
            print(f"     {port:5d} ({label:12s}) -> {status} <<<")
        else:
            print(f"     {port:5d} ({label:12s}) -> {status}")

    # 3. HTTP title
    if open_ports:
        print(f"\n  3. HTTP title...")
        for p in [80, 8080, 9000]:
            if any(pp == p for pp, _ in open_ports):
                title = get_http_title(ip, p)
                if title:
                    print(f"     Port {p}: {title}")

    # 4. Snapshot test
    print(f"\n  4. Snapshot URL test (auth-first)...")
    for path, brand in SNAPSHOT_URLS:
        result = try_snapshot(ip, path, creds, timeout=10.0)
        if result:
            if result.get("image_size", 0) > 0:
                print(f"     FOUND: {path}")
                print(f"     Brand: {brand}")
                print(f"     Auth:  {result['auth_type']}")
                print(f"     Size:  {result['image_size']:,} bytes")
                return
            elif result["auth_type"] == "requires_credentials":
                print(f"     401:   {path} (needs different credentials)")

    if not open_ports:
        print(f"\n  RESULT: No camera ports open on {ip}")
        print(f"  Check: cable connected? Camera powered on?")
        print(f"  Try:   ping {ip}")
    else:
        print(f"\n  RESULT: Device found but no snapshot URL worked")
        print(f"  Open ports: {', '.join(f'{p}({l})' for p, l in open_ports)}")


# ══════════════════════════════════════════════════════════════════════════
#  OUTPUT
# ══════════════════════════════════════════════════════════════════════════

def _print_results(results: list[dict]):
    """Print formatted scan results."""
    print()
    print("=" * 64)
    print("  SCAN RESULTS")
    print("=" * 64)

    if not results:
        print("\n  No devices found on this subnet.")
        print("\n  TROUBLESHOOTING:")
        print("    1. Is the DVR/camera plugged into the same network?")
        print("    2. Check Ethernet cable (green LED on port?)")
        print("    3. Test single IP: python scan_cameras.py <camera-ip>")
        print("    4. Try other subnets:")
        print("       python scan_cameras.py 192.168.0.0/24")
        print("       python scan_cameras.py 192.168.1.0/24")
        return

    camera_results = [r for r in results if r.get("cameras")]
    other_results = [r for r in results
                     if not r.get("cameras") and r.get("open_ports")]

    total_channels = sum(len(r["cameras"]) for r in camera_results)

    if camera_results:
        print(f"\n  CAMERAS / DVRs FOUND: {len(camera_results)} device(s), "
              f"{total_channels} channel(s)")
        print(f"  {'-' * 58}")

        all_cameras = []
        for r in camera_results:
            ip = r["ip"]
            title = r.get("title", "")
            ports = ", ".join(f"{p}" for p, _ in r["open_ports"])
            dev_type = r.get("device_type", "")
            onvif = r.get("onvif")

            print(f"\n    Device: {ip}")
            if dev_type:
                print(f"    Type:   {dev_type}")
            if title:
                print(f"    Title:  {title}")
            if onvif:
                name = onvif.get("name", onvif.get("hardware", ""))
                if name:
                    print(f"    ONVIF:  {name}")
            print(f"    Ports:  {ports}")

            for cam in r["cameras"]:
                ch = f" (Ch {cam['channel']})" if cam.get("channel", 0) > 0 else ""
                print(f"      -> Brand:    {cam['brand']}{ch}")
                print(f"         URL:      {cam['snapshot_url']}")
                print(f"         Auth:     {cam['auth_type']}")
                if cam.get("image_size"):
                    print(f"         Image:    {cam['image_size']:,} bytes")
                all_cameras.append((ip, cam))

        # Recommended config
        if all_cameras:
            print(f"\n  {'-' * 58}")
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
                needs_cred = cam["auth_type"] == "requires_credentials"
                note = "  <- UPDATE" if needs_cred else ""
                username = cam.get("username", "admin") or "admin"
                password = cam.get("password", "admin123") or "admin123"

                print(f'      "{cam_id}": {{')
                print(f'        "label": "{cam_id.capitalize()} View",')
                print(f'        "url": "{cam["snapshot_url"]}",')
                print(f'        "username": "{username}",{note}')
                print(f'        "password": "{password}"{note}')
                print(f'      }}{" " if is_last else ","}')

                if shown >= 4:
                    break

            print('    }')

    if other_results:
        print(f"\n  Other network devices ({len(other_results)}):")
        for r in other_results:
            port_str = ", ".join(f"{p}" for p, _ in r["open_ports"])
            title = f" - {r['title']}" if r.get("title") else ""
            dev_type = f" [{r['device_type']}]" if r.get("device_type") else ""
            print(f"    {r['ip']:16s} ports: {port_str}{title}{dev_type}")

    print(f"\n  Summary: {len(camera_results)} camera device(s), "
          f"{total_channels} channel(s), {len(other_results)} other device(s)")
    print()


# ══════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════

def main():
    print()
    print("=" * 64)
    print("  Camera & DVR Scanner v3.0 (Robust)")
    print("  PRIMARY: TCP port scan (37777/554/80)")
    print("  SUPPLEMENT: ONVIF + Config + ARP")
    print("  \"No camera should go untraced\"")
    print("=" * 64)

    target = sys.argv[1] if len(sys.argv) > 1 else None

    # Single IP mode
    if target and "/" not in target and "." in target:
        test_single_ip(target)
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


if __name__ == "__main__":
    main()
