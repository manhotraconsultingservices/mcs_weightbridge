"""
Weight API Test — verifies the backend weight endpoints and WebSocket.

Tests:
  1. GET /api/v1/weight/ports        — list available COM ports
  2. GET /api/v1/weight/protocols    — list supported protocols
  3. GET /api/v1/weight/status       — current scale status
  4. POST /api/v1/weight/test-port   — raw frame capture (requires a real/virtual port)
  5. WebSocket /ws/weight            — real-time weight stream (10-second listen)

USAGE:
  python test_weight_api.py
  python test_weight_api.py --port COM11       (test raw frame capture on COM11)
  python test_weight_api.py --ws-only          (only listen to WebSocket)

Run AFTER scale_simulator.py is streaming to the partner COM port.
"""
import argparse
import asyncio
import json
import sys
import urllib.request
import urllib.error

try:
    import websockets
except ImportError:
    websockets = None  # type: ignore

BASE = "http://localhost:9001"
WS_URL = "ws://localhost:9001/ws/weight"

# ─── JWT login ────────────────────────────────────────────────────────────────

def get_token(username="admin", password="admin123") -> str:
    """Login and return JWT bearer token."""
    import urllib.parse
    payload = urllib.parse.urlencode({"username": username, "password": password}).encode()
    req = urllib.request.Request(
        f"{BASE}/api/v1/auth/login",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())["access_token"]
    except Exception as e:
        print(f"  [ERROR] Login failed: {e}")
        print("  Make sure the backend is running on port 9001.")
        sys.exit(1)


# ─── REST helpers ─────────────────────────────────────────────────────────────

def api_get(path: str, token: str) -> dict:
    req = urllib.request.Request(
        f"{BASE}{path}",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"error": e.code, "detail": e.read().decode()}
    except Exception as e:
        return {"error": str(e)}


def api_post(path: str, token: str, body: dict) -> dict:
    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"error": e.code, "detail": e.read().decode()}
    except Exception as e:
        return {"error": str(e)}


# ─── WebSocket listener ───────────────────────────────────────────────────────

async def listen_websocket(seconds: int = 10):
    if websockets is None:
        print("  [SKIP] websockets not installed. Run: pip install websockets")
        return

    print(f"\n{'-'*60}")
    print(f"  WebSocket: {WS_URL}")
    print(f"  Listening for {seconds} seconds...")
    print(f"{'-'*60}")

    try:
        async with websockets.connect(WS_URL) as ws:
            deadline = asyncio.get_event_loop().time() + seconds
            count = 0
            while asyncio.get_event_loop().time() < deadline:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    data = json.loads(msg)
                    count += 1
                    connected = "CONNECTED" if data.get("scale_connected") else "DISCONNECTED"
                    stable = " [STABLE]" if data.get("is_stable") else ""
                    print(
                        f"  [{count:03d}] {data['weight_kg']:10.2f} kg  "
                        f"{connected}{stable}  "
                        f"stable_for={data.get('stable_duration_sec', 0):.1f}s"
                    )
                except asyncio.TimeoutError:
                    print("  ... (no data)")

            if count == 0:
                print("\n  [WARN] No WebSocket messages received.")
                print("  Check: is the scale configured? Is scale_simulator.py running?")
            else:
                print(f"\n  [OK] Received {count} weight readings in {seconds}s")
    except Exception as e:
        print(f"  [ERROR] WebSocket connection failed: {e}")


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Weight API Test")
    parser.add_argument("--port",    default=None,  help="COM port to test raw capture (e.g. COM11)")
    parser.add_argument("--baud",    default=9600,  type=int)
    parser.add_argument("--ws-only", action="store_true")
    parser.add_argument("--ws-time", default=10, type=int, help="WebSocket listen seconds")
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"  Weight API Test")
    print(f"  Backend: {BASE}")
    print(f"{'='*60}\n")

    if args.ws_only:
        asyncio.run(listen_websocket(args.ws_time))
        return

    # 1. Login
    print("  [1] Authenticating...")
    token = get_token()
    print("  [OK] Token obtained\n")

    # 2. List ports
    print("  [2] GET /api/v1/weight/ports")
    ports = api_get("/api/v1/weight/ports", token)
    port_list = ports.get("ports", [])
    if port_list:
        for p in port_list:
            print(f"       {p['port']:8s}  {p['description']}")
    else:
        print("       (no COM ports found)")
    print()

    # 3. List protocols
    print("  [3] GET /api/v1/weight/protocols")
    protos = api_get("/api/v1/weight/protocols", token)
    proto_list = protos.get("protocols", [])
    for p in proto_list:
        print(f"       {p['id']:16s}  {p['label']}  (default baud: {p['default_baud']})")
    print()

    # 4. Current status
    print("  [4] GET /api/v1/weight/status")
    status = api_get("/api/v1/weight/status", token)
    if "error" in status:
        print(f"       Error: {status}")
    else:
        connected = "YES" if status.get("scale_connected") else "NO"
        print(f"       scale_connected : {connected}")
        print(f"       weight_kg       : {status.get('weight_kg', 0):.2f}")
        print(f"       is_stable       : {status.get('is_stable', False)}")
        print(f"       stable_duration : {status.get('stable_duration_sec', 0):.1f}s")
    print()

    # 5. Raw port test (optional)
    if args.port:
        print(f"  [5] POST /api/v1/weight/test-port  (port={args.port}, baud={args.baud}, 3s)")
        result = api_post("/api/v1/weight/test-port", token, {
            "port_name": args.port,
            "baud_rate": args.baud,
            "duration_sec": 3,
        })
        if result.get("error") and not result.get("frames"):
            print(f"       Error: {result.get('error')}")
        else:
            captured = result.get("frames_captured", 0)
            print(f"       Frames captured: {captured}")
            if captured > 0:
                print(f"       Sample frames:")
                for i, f in enumerate(result.get("frames", [])[:5]):
                    print(f"         [{i+1}] ASCII: {f['ascii']!r}  HEX: {f['hex'][:30]}")
            elif result.get("error"):
                print(f"       Port error: {result['error']}")
            else:
                print(f"       Port opened OK but no data — is the simulator running on the partner port?")
        print()

    # 6. WebSocket
    print(f"  [6] WebSocket ({args.ws_time}s listen)")
    asyncio.run(listen_websocket(args.ws_time))

    print(f"\n{'='*60}")
    print(f"  Test complete.")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
