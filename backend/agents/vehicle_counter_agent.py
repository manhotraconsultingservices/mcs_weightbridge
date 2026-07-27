"""Weighbridge Gate Vehicle Counter — autonomous truck/car/motorcycle/bus tally.

A standalone service that runs on the gate PC. It grabs a frame from the entry
and exit cameras every second or two, runs a small on-device vehicle-detection
model (YOLOv8n, ONNX, CPU), classifies each vehicle, de-duplicates it, and POSTs
one event (with snapshot) to the cloud. Direction = which camera saw it (entry
camera → IN, exit camera → OUT). No one has to click anything.

The cloud reconciles the camera count against the gate passes the guard creates
manually (Operations → Gate Vehicle Count). This is a paid, opt-in feature gated
by the `vehicle_count` module — the counter only feeds a tenant that has it on.

It is COMPLETELY SEPARATE from the scale/camera agents — it never touches them.
It reads the same gate-camera snapshot URLs and reuses the SAME agent key that is
already in this PC's camera_config.json.

Usage:
    python vehicle_counter_agent.py --setup      # write a starter config
    python vehicle_counter_agent.py --test       # load model + probe cameras + cloud once
    python vehicle_counter_agent.py              # run the counting loop (foreground)
    python vehicle_counter_agent.py --install    # install as a Windows service (NSSM)
    python vehicle_counter_agent.py --uninstall

Deployment: ship as a single frozen EXE (see vehicle_counter_agent.spec +
DPD-VEHICLE-COUNTER.md) — no Python needed on the client PC.
"""
import os
import sys
import json
import copy
import time
import socket
import logging
import threading
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlparse

try:
    import requests
    from requests.auth import HTTPDigestAuth, HTTPBasicAuth
except ImportError:
    print("Missing dependency. Run:  pip install requests")
    sys.exit(1)

AGENT_VERSION = "1.0.0"

# ── Base dir (frozen-EXE safe: read config next to the .exe, not _MEIPASS) ────
if getattr(sys, "frozen", False) or "__compiled__" in globals():
    BASE_DIR = Path(sys.executable).resolve().parent
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR))
else:
    BASE_DIR = Path(__file__).resolve().parent
    BUNDLE_DIR = BASE_DIR

try:
    import certifi as _certifi
    _ca = _certifi.where()
    if _ca and os.path.exists(_ca):
        os.environ.setdefault("SSL_CERT_FILE", _ca)
        os.environ.setdefault("REQUESTS_CA_BUNDLE", _ca)
except Exception:
    pass

CONFIG_FILE = BASE_DIR / "vehicle_counter.json"
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "vehicle_counter_agent.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("vehcount")

PRODUCT_DOMAIN = "weighbridgesetu.com"

# COCO class id → our class name. The model detects ALL of these; which ones are
# actually counted is chosen per-site via the `classes` config — so toggling e.g.
# `person` on/off needs NO rebuild, just an edit to vehicle_counter.json. A
# tipper/dumper reads as 'truck'; auto-rickshaw/tractor aren't COCO classes.
COCO_CLASSES = {0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}

DEFAULT_CONFIG: dict = {
    "cloud_url": f"https://{PRODUCT_DOMAIN}",
    "tenant_slug": "",
    "agent_key": "",
    # The two gate cameras. Same snapshot URLs already used for the gate live feed
    # (camera_config.json → gate_cameras). Leave a url blank to skip that side.
    "cameras": {
        "entry": {"url": "", "username": "admin", "password": ""},
        "exit":  {"url": "", "username": "admin", "password": ""},
    },
    "capture_interval_sec": 1.5,   # how often to grab + analyse a frame per camera
    "min_confidence": 0.45,        # ignore detections below this
    "iou_threshold": 0.45,         # NMS overlap
    "cooldown_sec": 8,             # min gap before the SAME class can count again on a camera
    "min_absent_sec": 3,          # a vehicle must leave frame this long before a new one counts
    "model_path": "yolov8n.onnx",  # external override; falls back to the bundled model
    # Which classes to count. Options: person · bicycle · car · motorcycle · bus · truck.
    # Add "person" to also count people (no rebuild needed). NOTE: counts are
    # presence-based (one count per appearance after the frame clears), so "person"
    # is a people-*activity* signal, not an exact headcount of a crowd.
    "classes": ["truck", "car", "motorcycle", "bus"],
    "send_snapshot": True,         # attach the frame to each event
    "status_port": 9011,           # local diagnostics UI (≠ scale 9002 / camera 9003 / tally 9010 / watchdog 9020)
    "probe_timeout_sec": 6,
}


# ── Config ────────────────────────────────────────────────────────────────────
def load_config() -> dict:
    if not CONFIG_FILE.exists():
        log.error("Config not found: %s\nRun: vehicle_counter_agent --setup", CONFIG_FILE)
        sys.exit(1)
    with open(CONFIG_FILE, "r", encoding="utf-8-sig") as fh:
        data = json.load(fh)
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg.update(data)
    # merge nested camera defaults
    cams = copy.deepcopy(DEFAULT_CONFIG["cameras"])
    for pos, c in (data.get("cameras") or {}).items():
        cams.setdefault(pos, {}).update(c or {})
    cfg["cameras"] = cams
    return cfg


def save_config(cfg: dict) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
    log.info("Config saved -> %s", CONFIG_FILE)


def _effective_push_base(cloud_url: str, tenant_slug: str) -> str:
    """Cloud base URL. The apex weighbridgesetu.com 301-redirects to www, and a
    301 turns a POST into a GET that DROPS the body — so route to the tenant's own
    subdomain (no redirect). Custom domains / localhost are left untouched.
    (Same fix as scale_agent.py / tally_connector.py / watchdog_agent.py.)"""
    base = (cloud_url or "").rstrip("/")
    try:
        parts = urlparse(base if "//" in base else f"https://{base}")
        host = (parts.hostname or "").lower()
    except Exception:
        return base
    if tenant_slug and host in (PRODUCT_DOMAIN, f"www.{PRODUCT_DOMAIN}"):
        return f"{parts.scheme or 'https'}://{tenant_slug}.{PRODUCT_DOMAIN}"
    return base


def _cloud_base(cfg: dict) -> str:
    return _effective_push_base(cfg.get("cloud_url", ""), cfg.get("tenant_slug", ""))


def resolve_model_path(cfg: dict) -> Path | None:
    """External model next to the exe wins (lets a client swap the model without a
    rebuild); else the model bundled into the frozen EXE."""
    name = cfg.get("model_path") or "yolov8n.onnx"
    ext = BASE_DIR / name
    if ext.exists():
        return ext
    bundled = BUNDLE_DIR / name
    if bundled.exists():
        return bundled
    return None


# ── Pure geometry: letterbox + NMS (unit-tested; numpy-only) ──────────────────
def letterbox(img, new_size: int = 640):
    """Resize keeping aspect ratio + pad to a square. Returns (chw_float_batch,
    scale, pad_x, pad_y). `img` is an HxWx3 uint8 RGB numpy array."""
    import numpy as np
    h, w = img.shape[:2]
    scale = min(new_size / h, new_size / w)
    nh, nw = int(round(h * scale)), int(round(w * scale))
    # nearest-neighbour resize without cv2 (index remap)
    ys = (np.arange(nh) / scale).astype(np.int32).clip(0, h - 1)
    xs = (np.arange(nw) / scale).astype(np.int32).clip(0, w - 1)
    resized = img[ys][:, xs]
    canvas = np.full((new_size, new_size, 3), 114, dtype=np.uint8)
    pad_y, pad_x = (new_size - nh) // 2, (new_size - nw) // 2
    canvas[pad_y:pad_y + nh, pad_x:pad_x + nw] = resized
    chw = canvas.astype(np.float32).transpose(2, 0, 1) / 255.0
    return chw[None, ...], scale, pad_x, pad_y


def nms(boxes, scores, iou_threshold: float = 0.45):
    """Standard greedy NMS. boxes are xyxy numpy array (N,4). Returns kept indices."""
    import numpy as np
    if len(boxes) == 0:
        return []
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1).clip(0) * (y2 - y1).clip(0)
    order = scores.argsort()[::-1]
    keep = []
    while order.size > 0:
        i = int(order[0])
        keep.append(i)
        if order.size == 1:
            break
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = (xx2 - xx1).clip(0) * (yy2 - yy1).clip(0)
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-9)
        order = order[1:][iou <= iou_threshold]
    return keep


# ── Detector (lazy: onnxruntime imported only when the loop actually runs) ────
class Detector:
    def __init__(self, model_path: Path, classes: list[str], conf: float, iou: float):
        import onnxruntime as ort  # heavy — kept out of module import so --setup works anywhere
        import numpy as np  # noqa: F401
        self.ort = ort
        self.conf = conf
        self.iou = iou
        self.wanted = set(classes)
        providers = ["CPUExecutionProvider"]
        so = ort.SessionOptions()
        so.intra_op_num_threads = max(1, (os.cpu_count() or 2) - 1)
        so.log_severity_level = 3
        self.sess = ort.InferenceSession(str(model_path), sess_options=so, providers=providers)
        self.input_name = self.sess.get_inputs()[0].name
        self.imgsz = 640

    def infer(self, jpeg_bytes: bytes):
        """Return [(class_name, confidence)] for wanted vehicle classes in the frame."""
        import numpy as np
        from PIL import Image
        import io as _io
        img = np.array(Image.open(_io.BytesIO(jpeg_bytes)).convert("RGB"))
        blob, scale, pad_x, pad_y = letterbox(img, self.imgsz)
        out = self.sess.run(None, {self.input_name: blob})[0]
        # YOLOv8 ONNX head: (1, 4+numClasses, 8400) → transpose to (8400, 4+nc)
        pred = np.squeeze(out, 0)
        if pred.shape[0] < pred.shape[1]:
            pred = pred.T
        boxes_xywh = pred[:, :4]
        scores_all = pred[:, 4:]
        class_ids = scores_all.argmax(1)
        confs = scores_all.max(1)
        keep = confs >= self.conf
        class_ids, confs, boxes_xywh = class_ids[keep], confs[keep], boxes_xywh[keep]
        # only vehicle COCO ids we care about
        results: dict[str, float] = {}
        if len(confs):
            xyxy = np.empty_like(boxes_xywh)
            xyxy[:, 0] = boxes_xywh[:, 0] - boxes_xywh[:, 2] / 2
            xyxy[:, 1] = boxes_xywh[:, 1] - boxes_xywh[:, 3] / 2
            xyxy[:, 2] = boxes_xywh[:, 0] + boxes_xywh[:, 2] / 2
            xyxy[:, 3] = boxes_xywh[:, 1] + boxes_xywh[:, 3] / 2
            kept = nms(xyxy, confs, self.iou)
            for idx in kept:
                cid = int(class_ids[idx])
                name = COCO_CLASSES.get(cid)
                if name and name in self.wanted:
                    results[name] = max(results.get(name, 0.0), float(confs[idx]))
        return results


# ── De-dup counter (pure; unit-tested) ────────────────────────────────────────
class PositionCounter:
    """Rising-edge de-dup per camera position. A vehicle counts once on the
    absent→present transition; a lingering vehicle (present across many frames)
    counts once; a new vehicle after a gap counts again. `cooldown_sec` debounces
    detector flicker; `min_absent_sec` is how long a class must be gone before its
    next appearance is a new vehicle."""
    def __init__(self, classes: list[str], cooldown_sec: float, min_absent_sec: float):
        self.cooldown = cooldown_sec
        self.min_absent = min_absent_sec
        self.tr = {c: {"present": False, "last_seen": 0.0, "last_count": -1e9} for c in classes}
        self.total = {c: 0 for c in classes}

    def update(self, detected: dict, now: float):
        """detected = {class: best_conf}. Returns [(class, conf)] newly counted."""
        counted = []
        for c, s in self.tr.items():
            if c in detected:
                s["last_seen"] = now
                if not s["present"]:
                    s["present"] = True
                    if now - s["last_count"] >= self.cooldown:
                        s["last_count"] = now
                        self.total[c] += 1
                        counted.append((c, detected[c]))
            else:
                if s["present"] and (now - s["last_seen"]) >= self.min_absent:
                    s["present"] = False
        return counted


# ── Camera capture ────────────────────────────────────────────────────────────
def capture_frame(cam: dict, timeout: float) -> bytes | None:
    url = cam.get("url")
    if not url:
        return None
    auth = None
    if cam.get("username"):
        auth = HTTPDigestAuth(cam["username"], cam.get("password", ""))
    try:
        r = requests.get(url, auth=auth, timeout=timeout, verify=False)
        if r.status_code == 401 and auth:
            auth = HTTPBasicAuth(cam["username"], cam.get("password", ""))
            r = requests.get(url, auth=auth, timeout=timeout, verify=False)
        if r.status_code == 200 and len(r.content) >= 500:
            return r.content
    except Exception as e:  # noqa: BLE001
        log.debug("capture %s failed: %s", url, type(e).__name__)
    return None


# ── Cloud push ────────────────────────────────────────────────────────────────
def push_event(cfg: dict, session: "requests.Session", position: str,
               vehicle_class: str, confidence: float, frame: bytes | None) -> bool:
    base = _cloud_base(cfg)
    data = {
        "position": position,
        "vehicle_class": vehicle_class,
        "confidence": f"{confidence:.3f}",
        "detected_at": datetime.now(timezone.utc).isoformat(),
        "camera_id": position,
        "tenant_slug": cfg.get("tenant_slug", ""),
    }
    files = {"image": (f"{position}.jpg", frame, "image/jpeg")} if frame else None
    try:
        r = session.post(f"{base}/api/v1/vehicle-count/event",
                         data=data, files=files,
                         headers={"X-Agent-Key": cfg.get("agent_key", "")},
                         timeout=float(cfg.get("probe_timeout_sec", 6)) + 6)
        if r.status_code == 200:
            return True
        if r.status_code == 403:
            log.error("REJECTED (403) — agent key invalid OR the vehicle_count module is OFF for this tenant")
        else:
            log.warning("event HTTP %s: %s", r.status_code, r.text[:180])
    except Exception as e:  # noqa: BLE001
        log.warning("event push failed: %s", e)
    return False


# ── State + status server ─────────────────────────────────────────────────────
class State:
    def __init__(self) -> None:
        self.cloud_online = False
        self.last_event_at: str | None = None
        self.sent = 0
        self.errors = 0
        self.totals: dict[str, dict[str, int]] = {"entry": {}, "exit": {}}


_STATUS_HTML = """<!doctype html><meta charset=utf-8><title>Vehicle Counter</title>
<style>body{font-family:system-ui;background:#0f172a;color:#e2e8f0;margin:0;padding:24px}
h1{font-size:18px}.d{display:flex;justify-content:space-between;padding:8px 12px;border-radius:8px;
background:#1e293b;margin:6px 0}.ok{color:#34d399}.bad{color:#f87171}small{color:#94a3b8}</style>
<h1>Gate Vehicle Counter <small id=v></small></h1><div id=c></div><h3>Today (this run)</h3><div id=t></div>
<script>async function p(){try{const s=await(await fetch('/status')).json();
document.getElementById('v').textContent='v'+s.agent_version;
document.getElementById('c').innerHTML='<div class=d><span>Cloud</span><span class='+
(s.cloud_online?'ok':'bad')+'>'+(s.cloud_online?'ONLINE':'OFFLINE')+'</span></div>'+
'<div class=d><span>Events sent</span><span>'+s.sent+' <small>err '+s.errors+'</small></span></div>'+
'<div class=d><span>Last event</span><span><small>'+(s.last_event_at||'—')+'</small></span></div>';
let h='';for(const pos of ['entry','exit']){const o=s.totals[pos]||{};
h+='<div class=d><span>'+pos.toUpperCase()+'</span><span>'+(Object.keys(o).length?
Object.entries(o).map(([k,v])=>k+' '+v).join(' · '):'<small>—</small>')+'</span></div>';}
document.getElementById('t').innerHTML=h;
}catch(e){}}setInterval(p,3000);p();</script>"""


def start_status_server(cfg: dict, state: State) -> None:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    def _free_port(start: int) -> int:
        for p in range(start, start + 5):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.bind(("127.0.0.1", p)); s.close()
                return p
            except OSError:
                continue
        return start

    port = _free_port(int(cfg.get("status_port", 9011)))

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._send(200, _STATUS_HTML, "text/html; charset=utf-8")
            elif self.path == "/status":
                self._send(200, json.dumps({
                    "service": "vehicle_counter_agent", "agent_version": AGENT_VERSION,
                    "cloud_online": state.cloud_online, "last_event_at": state.last_event_at,
                    "sent": state.sent, "errors": state.errors, "totals": state.totals,
                }), "application/json")
            else:
                self._send(404, "{}", "application/json")

        def log_message(self, *a):
            pass

    def _serve():
        try:
            ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
        except OSError as exc:
            log.warning("Status server on :%d failed: %s", port, exc)

    threading.Thread(target=_serve, daemon=True, name="status-http").start()
    log.info("Status UI: http://127.0.0.1:%d", port)


# ── Per-camera worker ─────────────────────────────────────────────────────────
def _position_loop(cfg: dict, position: str, detector: "Detector",
                   session: "requests.Session", state: State) -> None:
    cam = (cfg.get("cameras") or {}).get(position) or {}
    if not cam.get("url"):
        return
    interval = max(0.5, float(cfg.get("capture_interval_sec", 1.5)))
    timeout = float(cfg.get("probe_timeout_sec", 6))
    send_snap = bool(cfg.get("send_snapshot", True))
    counter = PositionCounter(cfg.get("classes", ["truck", "car", "motorcycle", "bus"]),
                              float(cfg.get("cooldown_sec", 8)),
                              float(cfg.get("min_absent_sec", 3)))
    log.info("Counting %s camera: %s (every %.1fs)", position, cam.get("url"), interval)
    while True:
        t0 = time.time()
        try:
            frame = capture_frame(cam, timeout)
            if frame:
                detected = detector.infer(frame)
                for cls, conf in counter.update(detected, time.time()):
                    ok = push_event(cfg, session, position, cls, conf, frame if send_snap else None)
                    if ok:
                        state.sent += 1
                        state.cloud_online = True
                        state.last_event_at = datetime.now().isoformat(timespec="seconds")
                        state.totals[position][cls] = state.totals[position].get(cls, 0) + 1
                        log.info("%s: %s (%.0f%%) → counted", position.upper(), cls, conf * 100)
                    else:
                        state.errors += 1
                        state.cloud_online = False
        except Exception as e:  # noqa: BLE001 — a bad frame must never kill the loop
            log.warning("%s cycle error: %s", position, e)
        dt = time.time() - t0
        time.sleep(max(0.0, interval - dt))


def run(cfg: dict, state: State) -> None:
    model_path = resolve_model_path(cfg)
    if not model_path:
        log.error("Model not found (%s). See DPD-VEHICLE-COUNTER.md to obtain yolov8n.onnx.",
                  cfg.get("model_path"))
        sys.exit(1)
    try:
        detector = Detector(model_path,
                            cfg.get("classes", ["truck", "car", "motorcycle", "bus"]),
                            float(cfg.get("min_confidence", 0.45)),
                            float(cfg.get("iou_threshold", 0.45)))
    except Exception as e:  # noqa: BLE001
        log.error("Could not load the detection model (%s): %s", model_path, e)
        log.error("Install the runtime:  pip install onnxruntime   (bundled in the EXE build)")
        sys.exit(1)
    log.info("Vehicle Counter v%s — model %s → %s", AGENT_VERSION, model_path.name, _cloud_base(cfg))
    session = requests.Session()
    threads = []
    for pos in ("entry", "exit"):
        if ((cfg.get("cameras") or {}).get(pos) or {}).get("url"):
            th = threading.Thread(target=_position_loop, args=(cfg, pos, detector, session, state),
                                  daemon=True, name=f"count-{pos}")
            th.start()
            threads.append(th)
    if not threads:
        log.error("No gate camera URLs configured. Run --setup.")
        sys.exit(1)
    while True:
        time.sleep(3600)


# ── Setup / test / service ────────────────────────────────────────────────────
def setup_wizard() -> None:
    print("\n" + "=" * 60)
    print("  Weighbridge Gate Vehicle Counter — Setup")
    print("=" * 60 + "\n")
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        try:
            cfg.update(json.load(open(CONFIG_FILE, "r", encoding="utf-8-sig")))
        except Exception:
            pass
    cfg["cloud_url"]   = input(f"Cloud URL [{cfg['cloud_url']}]: ").strip() or cfg["cloud_url"]
    cfg["tenant_slug"] = input(f"Tenant slug [{cfg.get('tenant_slug','')}]: ").strip() or cfg.get("tenant_slug", "")
    cfg["agent_key"]   = input("Agent API key (same as camera agent): ").strip() or cfg.get("agent_key", "")
    cams = cfg.get("cameras") or copy.deepcopy(DEFAULT_CONFIG["cameras"])
    for pos in ("entry", "exit"):
        c = cams.setdefault(pos, {})
        c["url"] = input(f"{pos.capitalize()} camera snapshot URL [{c.get('url','')}]: ").strip() or c.get("url", "")
        if c.get("url"):
            c["username"] = input(f"  {pos} camera username [{c.get('username','admin')}]: ").strip() or c.get("username", "admin")
            c["password"] = input(f"  {pos} camera password: ").strip() or c.get("password", "")
    cfg["cameras"] = cams
    save_config(cfg)
    print(f"\n  Config saved: {CONFIG_FILE}")
    print("  Place yolov8n.onnx next to this program (or bundle it in the EXE).")
    print("  Verify:   vehicle_counter_agent --test")
    print("  Run:      vehicle_counter_agent")


def run_test() -> None:
    cfg = load_config()
    print(f"\nCloud: {_cloud_base(cfg)}")
    # Model
    mp = resolve_model_path(cfg)
    if not mp:
        print(f"  [ERR] model not found ({cfg.get('model_path')}) — see DPD-VEHICLE-COUNTER.md")
    else:
        try:
            Detector(mp, cfg.get("classes", []), float(cfg.get("min_confidence", 0.45)),
                     float(cfg.get("iou_threshold", 0.45)))
            print(f"  [OK]  model loaded ({mp.name})")
        except Exception as e:  # noqa: BLE001
            print(f"  [ERR] model load failed: {e}  (pip install onnxruntime)")
    # Cameras
    for pos in ("entry", "exit"):
        cam = (cfg.get("cameras") or {}).get(pos) or {}
        if not cam.get("url"):
            print(f"  [--]  {pos} camera: not configured")
            continue
        frame = capture_frame(cam, float(cfg.get("probe_timeout_sec", 6)))
        print(f"  [{'OK ' if frame else 'ERR'}] {pos} camera: " +
              (f"snapshot {len(frame)} bytes" if frame else f"no image from {cam.get('url')}"))
    # Cloud auth
    if not cfg.get("tenant_slug") or not cfg.get("agent_key"):
        print("  [ERR] tenant_slug / agent_key not set — re-run --setup")
        return
    try:
        r = requests.post(f"{_cloud_base(cfg)}/api/v1/vehicle-count/event",
                          data={"position": "entry", "vehicle_class": "car", "confidence": "0.99",
                                "tenant_slug": cfg["tenant_slug"]},
                          headers={"X-Agent-Key": cfg["agent_key"]}, timeout=15)
        if r.status_code == 200:
            print("  [OK]  cloud accepted a test event (auth valid + module ON)")
        elif r.status_code == 403:
            print("  [ERR] 403 — agent key invalid OR the vehicle_count module is OFF for this tenant")
        else:
            print(f"  [ERR] cloud HTTP {r.status_code}: {r.text[:180]}")
    except Exception as e:  # noqa: BLE001
        print(f"  [ERR] cloud unreachable: {e}")


_SERVICE_NAME = "WeighbridgeVehicleCounter"


def install_service() -> None:
    import shutil, subprocess
    nssm = shutil.which("nssm")
    if not nssm:
        print("NSSM not found. Install from https://nssm.cc and add it to PATH.")
        sys.exit(1)
    if getattr(sys, "frozen", False) or "__compiled__" in globals():
        subprocess.run([nssm, "install", _SERVICE_NAME, str(Path(sys.executable).resolve())], check=True)
    else:
        subprocess.run([nssm, "install", _SERVICE_NAME, sys.executable,
                        str((BASE_DIR / "vehicle_counter_agent.py").resolve())], check=True)
    subprocess.run([nssm, "set", _SERVICE_NAME, "AppDirectory", str(BASE_DIR)], check=True)
    subprocess.run([nssm, "set", _SERVICE_NAME, "Start", "SERVICE_AUTO_START"], check=False)
    subprocess.run([nssm, "set", _SERVICE_NAME, "AppExit", "Default", "Restart"], check=False)
    subprocess.run([nssm, "set", _SERVICE_NAME, "AppStdout", str(LOG_DIR / "service_stdout.log")], check=True)
    subprocess.run([nssm, "set", _SERVICE_NAME, "AppStderr", str(LOG_DIR / "service_stderr.log")], check=True)
    subprocess.run([nssm, "set", _SERVICE_NAME, "AppRotateFiles", "1"], check=False)
    subprocess.run([nssm, "set", _SERVICE_NAME, "AppRotateBytes", "10485760"], check=False)
    print(f"\nService '{_SERVICE_NAME}' installed.  Start:  nssm start {_SERVICE_NAME}")


def uninstall_service() -> None:
    import shutil, subprocess
    nssm = shutil.which("nssm")
    if not nssm:
        print("NSSM not found.")
        sys.exit(1)
    subprocess.run([nssm, "stop", _SERVICE_NAME], check=False)
    subprocess.run([nssm, "remove", _SERVICE_NAME, "confirm"], check=True)
    print("Service removed.")


def main() -> None:
    import argparse
    p = argparse.ArgumentParser(description="Weighbridge Gate Vehicle Counter")
    p.add_argument("--setup", action="store_true", help="Interactive config wizard")
    p.add_argument("--test", action="store_true", help="Load model + probe cameras + cloud once, then exit")
    p.add_argument("--install", action="store_true", help="Install as a Windows service (NSSM)")
    p.add_argument("--uninstall", action="store_true", help="Remove the Windows service")
    p.add_argument("--debug", action="store_true", help="Enable DEBUG logging")
    args = p.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    if args.setup:
        return setup_wizard()
    if args.test:
        return run_test()
    if args.install:
        return install_service()
    if args.uninstall:
        return uninstall_service()

    cfg = load_config()
    if not cfg.get("tenant_slug") or not cfg.get("agent_key"):
        log.error("tenant_slug and agent_key are required.\nRun: vehicle_counter_agent --setup")
        sys.exit(1)
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass
    state = State()
    start_status_server(cfg, state)
    run(cfg, state)


if __name__ == "__main__":
    main()
