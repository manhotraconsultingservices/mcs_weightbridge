#!/usr/bin/env python3
"""
Camera Doctor — diagnose "the URL works in my browser but the agent sees nothing".

That combination is the whole point of this tool. A browser is far more forgiving
than the agent, so "it works in Chrome" does NOT mean the agent can use it:

  * A BROWSER prompts for credentials and remembers them; the agent must be given
    them in the config, and must pick the right SCHEME (Digest vs Basic).
  * A BROWSER happily renders an MJPEG *video stream* that never ends; the agent
    needs a single still JPEG (a snapshot URL). Point it at a stream URL and the
    request just hangs until it times out.
  * A BROWSER shows an HTML error page as a page; the agent sees "HTTP 200" with
    HTML in the body and — because it only checks status + size — can be fooled.
  * A BROWSER may be running as YOU on a machine that can reach the camera VLAN,
    while the agent runs as a SERVICE (Session 0 / SYSTEM), which can have a
    different network view entirely.

The agent's own rule is strict, and worth stating plainly because it explains
most "silent" failures:

        accept ONLY  HTTP 200  AND  body >= 500 bytes  AND  it must be a JPEG

This tool reproduces the agent's exact request path (Digest, then Basic on 401),
reports precisely which of those conditions failed, and — when the URL is wrong
— probes the common snapshot paths for the major CCTV brands.

Usage:
    camera_doctor.exe                                   # read camera_config.json
    camera_doctor.exe http://192.168.0.101/cgi-bin/snapshot.cgi -u admin -p pass
    camera_doctor.exe 192.168.0.101 -u admin -p pass --probe   # try known paths

Read-only: never changes config, never writes to the camera.
"""
from __future__ import annotations

import argparse
import datetime
import json
import socket
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    import requests
    from requests.auth import HTTPBasicAuth, HTTPDigestAuth
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except ImportError:
    print("requests not installed.  Run:  pip install requests")
    sys.exit(1)

# Frozen EXE: anchor beside the .exe, never _MEIPASS (deleted on exit).
if getattr(sys, "frozen", False) or "__compiled__" in globals():
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent

MIN_BYTES = 500          # the agent's own threshold — keep in sync
TIMEOUT = 10             # the agent's own timeout

_REPORT: list[str] = []


def say(msg: str = "") -> None:
    print(msg)
    _REPORT.append(msg)


def save_report():
    try:
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        p = BASE_DIR / f"camera_doctor_{stamp}.txt"
        p.write_text("\n".join(_REPORT), encoding="utf-8")
        return p
    except Exception:
        return None


# Snapshot paths by brand. A *stream* path is deliberately excluded — the agent
# needs a still image, and pointing it at a stream is itself a common mistake.
COMMON_PATHS = [
    ("/cgi-bin/snapshot.cgi", "CP Plus / Dahua"),
    ("/ISAPI/Streaming/channels/101/picture", "Hikvision (ISAPI)"),
    ("/Streaming/channels/1/picture", "Hikvision (older)"),
    ("/snap.jpg", "generic"),
    ("/snapshot.jpg", "generic"),
    ("/image/jpeg.cgi", "Axis-style"),
    ("/axis-cgi/jpg/image.cgi", "Axis"),
    ("/cgi-bin/api.cgi?cmd=Snap&channel=0", "Reolink"),
    ("/tmpfs/auto.jpg", "some Dahua OEM"),
    ("/onvif-http/snapshot", "ONVIF"),
]


def is_jpeg(b: bytes) -> bool:
    return len(b) >= 3 and b[0] == 0xFF and b[1] == 0xD8 and b[2] == 0xFF


def describe_body(b: bytes) -> str:
    if is_jpeg(b):
        return "JPEG image"
    head = b[:200].lower()
    if b"<html" in head or b"<!doctype" in head:
        return "HTML page (NOT an image)"
    if head.startswith(b"--") or b"multipart" in head:
        return "MJPEG STREAM (not a still image)"
    if b"<?xml" in head:
        return "XML (probably an error response)"
    return "unknown/binary"


def tcp_check(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=4):
            return True
    except Exception:
        return False


def try_url(url: str, user: str, pw: str, quiet: bool = False) -> bool:
    """Reproduce the agent's exact request path and explain any failure."""
    if not quiet:
        say(f"\n  Testing: {url}")
        say("  " + "-" * 86)

    schemes = []
    if user:
        schemes = [("Digest", HTTPDigestAuth(user, pw)), ("Basic", HTTPBasicAuth(user, pw))]
    else:
        schemes = [("none", None)]

    for name, auth in schemes:
        t0 = time.time()
        try:
            r = requests.get(url, auth=auth, timeout=TIMEOUT, verify=False, stream=True)
            body = r.raw.read(200_000, decode_content=True) or b""
            ms = int((time.time() - t0) * 1000)
        except requests.Timeout:
            say(f"    auth={name:<7} -> TIMEOUT after {TIMEOUT}s")
            say("       A timeout with a browser-viewable URL almost always means this is a")
            say("       VIDEO STREAM url, not a snapshot: it never ends, so the agent waits.")
            say("       Find the camera's SNAPSHOT/JPEG url instead (try --probe).")
            return False
        except requests.ConnectionError as e:
            say(f"    auth={name:<7} -> CANNOT CONNECT: {str(e)[:110]}")
            return False
        except Exception as e:  # noqa: BLE001
            say(f"    auth={name:<7} -> ERROR: {str(e)[:110]}")
            return False

        ctype = r.headers.get("Content-Type", "?")
        kind = describe_body(body)
        say(f"    auth={name:<7} -> HTTP {r.status_code}  {len(body)} bytes  "
            f"content-type={ctype}  [{kind}]  {ms}ms")

        if r.status_code == 401:
            say(f"       401 Unauthorized with {name} auth — trying next scheme...")
            continue

        # Mirror the agent's acceptance rule exactly, and name what failed.
        if r.status_code != 200:
            say(f"       REJECTED: agent needs HTTP 200, got {r.status_code}.")
            return False
        if len(body) < MIN_BYTES:
            say(f"       REJECTED: only {len(body)} bytes; agent requires >= {MIN_BYTES}.")
            say("       A tiny 200 response is usually an error page or an empty channel.")
            return False
        if not is_jpeg(body):
            say(f"       REJECTED: body is {kind}, not a JPEG.")
            if "HTML" in kind:
                say("       The camera returned a web PAGE. That is what a browser renders")
                say("       and why it 'looks fine' — but it is not an image. Wrong URL.")
            elif "STREAM" in kind:
                say("       This is a live STREAM url. Use the still-snapshot url instead.")
            return False

        say(f"\n  ==> SUCCESS with auth={name}. This URL works for the agent.")
        say(f"      Put in camera_config.json:  url={url}")
        say(f"      username={user or '(none)'}   (auth scheme negotiated automatically)")
        return True

    say("\n  ==> ALL AUTH FAILED (401). The camera rejected these credentials.")
    say("      Note a browser may still work because it caches a session — that does")
    say("      NOT mean the username/password given to the agent are correct.")
    say("      Check for typos, and that this user is allowed API/CGI access (some")
    say("      cameras have a separate 'ONVIF/CGI user' from the web-login user).")
    return False


def probe(host: str, user: str, pw: str) -> int:
    say(f"\n  PROBING common snapshot paths on {host}")
    say("  " + "-" * 86)
    if not tcp_check(host, 80):
        say(f"  !! cannot even open TCP :80 on {host} — check IP, cable, VLAN, firewall.")
        return 1
    say(f"  TCP :80 reachable on {host}\n")
    for path, brand in COMMON_PATHS:
        url = f"http://{host}{path}"
        try:
            auth = HTTPDigestAuth(user, pw) if user else None
            r = requests.get(url, auth=auth, timeout=6, verify=False, stream=True)
            if r.status_code == 401 and user:
                r = requests.get(url, auth=HTTPBasicAuth(user, pw), timeout=6,
                                 verify=False, stream=True)
            body = r.raw.read(200_000, decode_content=True) or b""
            ok = r.status_code == 200 and len(body) >= MIN_BYTES and is_jpeg(body)
            flag = "  <== USE THIS ONE" if ok else ""
            say(f"    {r.status_code}  {len(body):>7}b  {describe_body(body):<28} "
                f"{path}  ({brand}){flag}")
            if ok:
                say(f"\n  ==> WORKING SNAPSHOT URL: {url}")
                return 0
        except Exception as e:  # noqa: BLE001
            say(f"    ---  {'timeout/err':>7}  {str(e)[:28]:<28} {path}  ({brand})")
    say("\n  ==> No standard snapshot path worked.")
    say("      Look in the camera's web UI for its snapshot/JPEG URL, or check the")
    say("      model's manual. Also confirm the user has CGI/API permission.")
    return 1


def from_config() -> int:
    cfg_path = BASE_DIR / "camera_config.json"
    if not cfg_path.exists():
        say(f"  No camera_config.json beside this program ({BASE_DIR}).")
        say("  Pass a URL instead:  camera_doctor.exe <url> -u <user> -p <pass>")
        return 2
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
    except Exception as e:  # noqa: BLE001
        say(f"  camera_config.json is not valid JSON: {e}")
        return 2

    say(f"  Using {cfg_path}")
    groups = [("cameras", cfg.get("cameras", {})), ("gate_cameras", cfg.get("gate_cameras", {}))]
    tested = failed = 0
    for gname, group in groups:
        for cam_id, cam in (group or {}).items():
            url = (cam or {}).get("url", "")
            if not url:
                say(f"\n  {gname}.{cam_id}: (no url configured — skipped)")
                continue
            tested += 1
            if not try_url(url, (cam or {}).get("username", ""), (cam or {}).get("password", "")):
                failed += 1
    if tested == 0:
        say("\n  No camera URLs configured at all.")
        return 2
    say(f"\n  {tested - failed}/{tested} camera URL(s) usable by the agent.")
    return 1 if failed else 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Diagnose camera snapshot problems")
    ap.add_argument("target", nargs="?", help="full snapshot URL, or just an IP with --probe")
    ap.add_argument("-u", "--user", default="", help="camera username")
    ap.add_argument("-p", "--password", default="", help="camera password")
    ap.add_argument("--probe", action="store_true", help="try common snapshot paths for an IP")
    a = ap.parse_args()

    say("=" * 92)
    say("  CAMERA DOCTOR — can the AGENT actually fetch a snapshot?")
    say("  (a URL that works in a browser is NOT proof that the agent can use it)")
    say("=" * 92)

    if not a.target:
        sys.exit(from_config())

    if a.probe or "://" not in a.target:
        host = a.target.replace("http://", "").replace("https://", "").split("/")[0]
        sys.exit(probe(host, a.user, a.password))

    u = urlparse(a.target)
    if u.hostname:
        port = u.port or (443 if u.scheme == "https" else 80)
        say(f"\n  TCP {u.hostname}:{port} ... "
            f"{'reachable' if tcp_check(u.hostname, port) else 'NOT REACHABLE'}")
    sys.exit(0 if try_url(a.target, a.user, a.password) else 1)


def _finish(code: int) -> None:
    p = save_report()
    if p:
        print(f"\n  Report saved: {p}")
        print("  (send this file back for analysis)")
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
