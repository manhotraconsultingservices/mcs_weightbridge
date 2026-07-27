# Gate Vehicle Counter — Deploy / Prove / Done runbook

Autonomous truck/car/motorcycle/bus counter for the gate cameras. Runs on the
**gate PC**, detects + classifies each vehicle on the entry/exit camera frames,
and POSTs one event (with snapshot) to the cloud, where it's reconciled against
the gate passes the guard creates (Operations → **Gate Vehicle Count**).

- **Paid, opt-in.** It only feeds a tenant that has the **`vehicle_count`** feature
  module ON (Platform admin → Edit tenant → Feature Modules). If the module is OFF,
  the cloud returns 403 and nothing is counted.
- **Completely separate** from the scale/camera agents — it never touches them. It
  reads the same gate-camera snapshot URLs and reuses the **same agent key** already
  in this PC's `camera_config.json`.
- Ships as a **single frozen EXE** — no Python needed on the client PC.

---

## §0 — What it is / how it decides

- Grabs a JPEG from the **entry** and **exit** cameras every ~1.5 s (configurable).
- Runs **YOLOv8n (ONNX, CPU)** → classifies each vehicle → COCO → `truck / car / motorcycle / bus`.
  (A tipper/dumper reads as *truck*; auto-rickshaw/tractor are not supported in v1.)
- **Direction = which camera fired** (entry camera → IN, exit camera → OUT).
- **De-dup**: a vehicle counts **once** on the absent→present edge; a vehicle sitting
  in frame across many frames counts once; a new vehicle after a gap counts again
  (`cooldown_sec` debounces flicker, `min_absent_sec` = how long a vehicle must leave
  frame before the next one is "new").
- ⚠ It's an **approximate audit tally** from periodic snapshots — not a certified
  turnstile count. Good for "did the guard log every vehicle?", not for billing.

---

## §1 — Build the EXE (once, on a build machine with internet)

You need the model file **`yolov8n.onnx`** and the deps. On any Windows box:

```
pip install -r vehicle_counter_requirements.txt pyinstaller ultralytics

# Export the model to ONNX (one time). This writes yolov8n.onnx (~12 MB):
yolo export model=yolov8n.pt format=onnx imgsz=640
#   (yolov8n.pt auto-downloads from the official Ultralytics release on first run.)
#   Alternatively, drop a yolov8n.onnx you already trust next to the .spec.

# Put yolov8n.onnx next to vehicle_counter_agent.spec, then build:
pyinstaller --noconfirm vehicle_counter_agent.spec
```

Output: **`dist/vehicle_counter_agent.exe`** — self-contained (~74 MB; onnxruntime +
the `yolov8n.onnx` model are bundled inside). This is the ONLY file you ship to a client.

> The model is bundled INTO the exe, but an external `yolov8n.onnx` placed next to
> the exe at runtime still wins — so you can swap/upgrade the model without a rebuild.

The exe is **tenant-agnostic** — nothing is baked in. The same binary works for every
client; `tenant_slug` + `agent_key` come from `vehicle_counter.json` at runtime, and
whether counting is actually accepted is controlled centrally by the platform admin's
**`vehicle_count` feature-module toggle** (module OFF → the cloud returns 403 and the
agent is inert).

---

## §2 — Install on the gate PC (no Python needed)

1. Copy `vehicle_counter_agent.exe` to `C:\weighbridge-agent\`.
2. Configure (interactive):
   ```
   cd C:\weighbridge-agent
   .\vehicle_counter_agent.exe --setup
   ```
   Enter: cloud URL, **tenant slug**, **agent key** (the SAME key as `camera_config.json`),
   and the **entry/exit camera snapshot URLs** (copy from `camera_config.json →
   gate_cameras`). Or copy `vehicle_counter.example.json` → `vehicle_counter.json` and edit.
3. **Prove it** before installing the service:
   ```
   .\vehicle_counter_agent.exe --test
   ```
   Expect: `[OK] model loaded`, `[OK] entry camera: snapshot … bytes`, `[OK] exit camera …`,
   and `[OK] cloud accepted a test event (auth valid + module ON)`.
   - `403` on the cloud line → the agent key is wrong **or** the `vehicle_count` module
     is OFF for this tenant (enable it in the Platform console first).
   - `model load failed` → the exe wasn't built with the model / onnxruntime (rebuild §1).
4. Install as an auto-start Windows service (needs [NSSM](https://nssm.cc) on PATH):
   ```
   .\vehicle_counter_agent.exe --install
   nssm start WeighbridgeVehicleCounter
   ```

---

## §3 — Verify it's counting

- Local status UI: **http://localhost:9011** — Cloud ONLINE, events sent, per-camera
  today's totals.
- Log: `C:\weighbridge-agent\logs\vehicle_counter_agent.log` — one line per counted vehicle.
- In the app (tenant with the module ON): **Operations → Gate Vehicle Count** — the
  IN/OUT counts, per-class breakdown, the camera-vs-gate-pass reconciliation, and
  snapshot thumbnails, all populate as vehicles pass.

---

## §4 — Uninstall

```
.\vehicle_counter_agent.exe --uninstall
```
(Config + logs are left in place.)

---

## Tuning (`vehicle_counter.json`)

| Key | Default | Notes |
|---|---|---|
| `capture_interval_sec` | 1.5 | Lower = catches faster vehicles, more CPU. |
| `min_confidence` | 0.45 | Raise to cut false positives; lower to catch more. |
| `cooldown_sec` | 8 | Min gap before the same class re-counts on a camera. |
| `min_absent_sec` | 3 | How long a vehicle must leave frame before the next is "new". |
| `classes` | truck,car,motorcycle,bus | Which classes to count. Options: `person` · `bicycle` · `car` · `motorcycle` · `bus` · `truck`. **Add `"person"` to also count people — no rebuild needed, just edit this list + restart the agent.** |
| `send_snapshot` | true | Attach the frame to each event (for the report thumbnails). |

> **Counting people:** add `"person"` to `classes`. People are kept **separate** from the
> vehicle totals and the gate-pass reconciliation (they show as a "People detected IN/OUT"
> line in the report). Note: counts are **presence-based** — one count per appearance after
> the frame clears — so `person` is a people-*activity* signal, not an exact crowd headcount.

## Notes / limits

- **Smart App Control / SmartScreen**: the exe is unsigned — Windows may block it on
  a locked-down PC. Right-click → Properties → Unblock, or turn Smart App Control off,
  or run the `.py` with a local Python (`pip install -r vehicle_counter_requirements.txt`).
  A code-signing cert removes this for wide rollout.
- **CPU**: YOLOv8n on CPU is ~50–200 ms/frame — trivial at a 1.5 s cadence on any
  modern PC. If the gate PC is very weak, raise `capture_interval_sec`.
- Ports: status UI **9011** (≠ scale 9002 / camera 9003 / tally 9010 / watchdog 9020).
- One counter per gate PC; it handles both entry + exit cameras in one process.
