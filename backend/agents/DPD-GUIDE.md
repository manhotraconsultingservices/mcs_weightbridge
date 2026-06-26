# Weighbridge Scale Agent — DPD Field Manual (complete)

**DPD = Discovery → Prepare → Deploy.** This is the complete reference for
installing the local scale agent at a client site so the weighbridge indicator's
live weight reaches the cloud app (`weighbridgesetu.com`) and the operator's
browser. It exists to kill the on-site trial-and-error of finding the right
**COM port + baud + framing** and to guarantee a verifiable end-to-end feed.

- **Audience:** the engineer doing the on-site install / a remote helper on the line.
- **Quick 1-page runbook:** [`DPD-SOP.md`](./DPD-SOP.md). This file is the deep reference.
- **Golden rule:** do not advance to the next phase until its **GATE** passes.

---

## 0. The three things to internalise first

1. **The server needs nothing.** The agent makes an outbound HTTPS `POST` to
   `…/api/v1/weight/external-reading` with `tenant` + `agent_key` in the body.
   The cloud validates the key and broadcasts the weight to the browser over a
   WebSocket. **No server-side change is ever required for a new site.**

2. **A COM port has exactly ONE owner.** On Windows, one process at a time can
   open `COMx`. If a serial terminal, the vendor's weighbridge software, or a
   leftover `weight_bridge.py` / `WeighbridgeWeightBridge` service holds the
   port, the agent gets *"Access to the port 'COMx' is denied"* and reports
   **Scale NOT FOUND** — even though the scale is perfectly healthy. This is the
   single most common failure. See §6.

3. **One agent per machine.** The agent owns the port and pushes to the cloud.
   Do not also run the old local reader. The installer now removes it for you.

### Data flow

```
 ┌──────────────┐   RS-232    ┌───────────────┐   USB    ┌──────────────────────┐
 │  Weighbridge │ ─────────►  │  USB-Serial   │ ──────►  │  Windows PC           │
 │  indicator   │  9600 7E1   │  adapter      │  COMx    │  scale_agent.py       │
 │ (000.320⏎)   │  (example)  │ CH340/FTDI/.. │          │  (Windows service)    │
 └──────────────┘             └───────────────┘          └─────────┬────────────┘
                                                                    │ HTTPS POST
                                                                    │ {weight_kg, tenant, agent_key, raw}
                                                                    ▼
                                              https://weighbridgesetu.com/api/v1/weight/external-reading
                                                                    │ validates agent_key → tenant
                                                                    ▼  WebSocket broadcast
                                                       Operator's browser → live weight on the Weighbridge page
```

The agent also runs a **local diagnostics + Discovery web UI** on
`http://localhost:9002` (auto-bumps to 9003-9006 if 9002 is taken by Tally).

---

## 1. Prerequisites (one-time per machine)

| ✔ | Item | Check / how |
|---|---|---|
| ☐ | Indicator wired to the PC (RS-232 → USB) and powered on | Device Manager → **Ports (COM & LPT)** shows a COMx |
| ☐ | USB-serial **driver** installed | If no COM appears: install CH340 / FTDI / Prolific driver |
| ☐ | **Python 3.11+** | `python --version` |
| ☐ | `pyserial` + `requests` | `pip install pyserial requests` |
| ☐ | **NSSM** on PATH (not downloaded by the installer) | `nssm version` — else `choco install nssm` or get it from nssm.cc |
| ☐ | Agent files in **`C:\weighbridge-agent`** | `scale_agent.py`, `install-scale-service.ps1` |
| ☐ | **Tenant slug** + **Agent key** for this client | Platform admin console → Tenants → client → Agent key. **Keep secret.** |
| ☐ | Outbound **HTTPS (443)** allowed | `Invoke-RestMethod https://weighbridgesetu.com/api/v1/health` returns OK |

---

## 2. Phase D — DISCOVERY

**Goal:** prove the PC can read **clean weight** (not garbage) from the indicator,
and identify the port + framing. Two equivalent ways — use whichever you like.

### 2a. The Discovery UI (recommended — visual, no typing)

If the agent (or even a one-off `python scale_agent.py`) is running, open:

> **http://localhost:9002**

You get a live page showing:

- **Live weight** + **SCALE CONNECTED / CLOUD ONLINE / PUSHED N** badges.
- **Raw frame from the indicator** — you literally see what the port sends
  (e.g. `000.320`), so clean ASCII vs garbage is obvious.
- **COM ports** on the PC, each with a **Peek** button → opens that port across
  all standard baud/framings and dumps the raw bytes (ASCII + hex + a quality
  score + parsed weight), flagging the one that **LOOKS GOOD** — or showing
  *"access denied"* if something else holds the port.
- **Force re-scan** button.

> **Peek and the running agent can't read the same port at once** (single-owner
> rule). That's expected — Peek is for a port the agent hasn't locked onto.

### 2b. The `--detect` CLI

```powershell
cd C:\weighbridge-agent
python scale_agent.py --detect
```

It scans **every COM port × 9 standard serial configs** (§Appendix E), rejects
any combo that returns non-ASCII garbage (ASCII quality < 65 %), and prints the
first config that yields a valid weight:

```json
{ "port": "COM6", "baud_rate": 9600, "data_bits": 7, "parity": "E", "stop_bits": 1 }
```
> `Scale FOUND: COM6 @ 9600 baud  7E1  weight=0.3 kg`

### ✅ GATE D — pass when BOTH are true
1. It locks onto a port (UI shows **SCALE CONNECTED** / `--detect` prints a config block, **not** "Scale NOT FOUND").
2. The number **tracks the indicator display**: add/remove a load (or watch the idle reading) and confirm the value on the page/CLI matches what the indicator shows. *(Magnitude check — see §4 if it's off by ~1000×.)*

If it fails → **§6 troubleshooting**, starting with the single-owner rule.

---

## 3. Phase P — PREPARE

**Goal:** write the cloud credentials so the agent knows which tenant to feed.
Serial port/baud/framing are **not** entered here — they're auto-detected at
start and cached.

```powershell
python scale_agent.py --setup
```

Prompts (writes `C:\weighbridge-agent\scale_config.json`):

| Prompt | Enter |
|---|---|
| **Cloud URL** `[https://weighbridgesetu.com]` | press Enter (default) |
| **Tenant slug** | e.g. `manhotra-consulting` |
| **Agent API key** | paste from the Platform console (**secret**) |
| **Calibration offset (kg)** | usually blank; see §4. `offset = display − app_reading` |
| **Log raw serial frames? (y/N)** | `N` (turn on only when diagnosing a format issue) |

### ✅ GATE P — pass when a quick foreground run streams to the cloud

```powershell
python scale_agent.py        # watch ~10 s, then Ctrl+C
```
The log should: auto-detect the port → log weights → show rising **push count**
and `Cloud connection restored` (no repeated `AGENT KEY REJECTED (403)`).
Then **stop it** (Ctrl+C) — the service will own the port in Phase Deploy.

If it fails → **§6** (403 = wrong key/slug; *Cloud unreachable* = firewall/443).

---

## 4. Calibration & unit verification (do this once, with a known load)

The indicator sends a number; the agent treats it as **kg** and applies
`calibration_offset_kg` before pushing. Two things to confirm:

1. **Magnitude / unit.** Put a **known weight** on the bridge. Compare the app
   value to the indicator display:
   - **They match** → done.
   - **App is ~1000× smaller** (indicator `12500`, app `12.5`) → the indicator
     transmits **tonnes**, not kg. Fix at the indicator (set output to kg) **or**
     tell the developer to set a unit multiplier — do **not** fake it with a
     calibration offset (offset is additive, not a scale factor).
2. **Fine offset.** If the app is consistently off by a fixed amount
   (display `12500`, app `12550`), set `calibration_offset_kg = display − app`
   → `-50`. Re-run `--setup` or edit the JSON, then `Restart-Service`.

> The idle reading on this build's reference site was `000.320` → the agent
> shows `0.32`. With a real load it must move to the loaded weight; that's the
> GATE-D magnitude check.

---

## 5. Phase D — DEPLOY

**Goal:** install the agent as an auto-starting, self-restarting Windows service
and verify the **full chain** (local read **and** cloud post).

Open **PowerShell as Administrator**:

```powershell
powershell -ExecutionPolicy Bypass -File C:\weighbridge-agent\install-scale-service.ps1
```

What the installer does:
- Kills any foreground `scale_agent.py`.
- **Stops + disables the legacy `WeighbridgeWeightBridge` service and kills any
  `weight_bridge.py`** (they fight the agent for the COM port — §6).
- Registers **`WeighbridgeScaleAgent`** (auto-start, restart-on-crash) pointed at
  `C:\weighbridge-agent`, with stdout/stderr captured to `…\logs\`.
- Starts it and runs a health check.

Uninstall: `…\install-scale-service.ps1 -Uninstall`.

### ✅ GATE D — pass when ALL are true
1. `Get-Service WeighbridgeScaleAgent` → **Running**.
2. **Local read** — in `/status`, `scale_connected=true` and `last_weight_kg`
   tracks the load:
   ```powershell
   Invoke-RestMethod http://localhost:9002/status | ConvertTo-Json -Depth 5
   ```
3. **Cloud post** — same `/status`: `cloud_online=true` and `push_count` keeps
   rising.
4. **End-to-end** — open the client's app → **Weighbridge** page; the live weight
   matches the indicator while a truck is on the bridge.

**Definition of done:** the truck on the bridge shows the **same** weight on the
indicator, in `/status`, and on the app's Weighbridge page.

---

## 6. Troubleshooting matrix

Work top-down — the first rows are the most common.

| Symptom | Likely cause | Fix |
|---|---|---|
| **Scale NOT FOUND**, but a terminal/vendor app *can* read the scale | **Port already owned** (single-owner rule) | Close the terminal/vendor app. Stop + remove the legacy service: `Stop-Service WeighbridgeWeightBridge; & nssm remove WeighbridgeWeightBridge confirm`. Then `Restart-Service WeighbridgeScaleAgent`. See the holder-finder below. |
| **Scale NOT FOUND**, nothing else open | Indicator off / cable loose, **or** indicator only sends on a "Print"/"Stable" trigger | Re-seat cable; power-cycle indicator; set indicator to **continuous** output in its menu (or press PRINT while detecting) |
| `No COM ports found` | USB adapter driver missing | Device Manager → Ports; install CH340 / FTDI / Prolific driver |
| Found, but value is **garbage / jumps** | Wrong framing matched | Re-run Discovery; if it keeps mismatching, set the indicator to a documented standard (commonly **9600 8N1** or **2400 7E1**) |
| Value is **~1000× off** | Indicator transmits **tonnes** | §4 — fix unit at the indicator (or add a multiplier); don't use the offset |
| `AGENT KEY REJECTED (403)` | Wrong `agent_key` / `tenant_slug` | Re-copy from Platform console; `--setup` again |
| `Cloud unreachable` | Firewall/proxy blocking outbound 443, or wrong `cloud_url` | `Invoke-RestMethod https://weighbridgesetu.com/api/v1/health`; fix firewall/URL |
| `Status port … NOT listening` after install | Agent crashed at init | `Get-Content C:\weighbridge-agent\logs\service_stderr.log -Tail 30` — usually a missing dep or the COM port held by another app |
| Service **flaps** (restart loop) | Port busy or detection keeps failing | Re-run Phase D foreground to get a clean read; fix; `Restart-Service` |
| Worked, then **stopped after re-plugging USB** | COM number changed (e.g. COM6→COM7) | The agent auto-re-detects within one loop — wait ~30 s. If not, `Restart-Service WeighbridgeScaleAgent` |

**Find what holds a port** (when COMx is "denied"):
```powershell
# any python still on a serial port?
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -match 'weight_bridge|scale_agent' } |
  Select-Object ProcessId,CommandLine
# legacy service still alive? (should not exist / be Disabled)
Get-Service WeighbridgeWeightBridge -ErrorAction SilentlyContinue
```

---

## 7. How the agent self-heals (so you don't have to babysit it)

- **Auto-detect:** on start with no saved serial config, it scans every COM port
  × 9 configs (§Appendix E), rejecting non-ASCII garbage, and caches the winning
  config back into `scale_config.json` for fast restarts.
- **USB re-plug recovery:** before reusing a saved port it checks the port still
  exists. A re-plug renumbers `COMx`; if the saved port is gone it **re-detects
  on the next loop** instead of looping on a dead port.
- **Read self-heal:** after 5 consecutive read failures it clears the cached
  serial config and re-detects from scratch.
- **Cloud resilience:** transient cloud errors don't stop reading; it keeps
  retrying and logs `Cloud connection restored` when back. Live weight is
  non-transactional (not buffered) — replaying stale weights would be wrong.
- **Service restart-on-crash:** NSSM restarts the process on any non-zero exit.

---

## 8. Day-to-day / handover

```powershell
Get-Service WeighbridgeScaleAgent
Restart-Service WeighbridgeScaleAgent
Get-Content C:\weighbridge-agent\logs\scale_agent.log -Tail 30 -Wait
Invoke-RestMethod http://localhost:9002/status | ConvertTo-Json -Depth 5
```
- **Live diagnostics page:** `http://localhost:9002` (the Discovery UI doubles as
  a day-2 health board).
- **Logs:** `C:\weighbridge-agent\logs\` — `scale_agent.log` (app),
  `service_stdout.log` / `service_stderr.log` (NSSM-captured).
- **Uninstall:** `install-scale-service.ps1 -Uninstall`.

---

## 9. Multi-site / fleet notes

- Each site is **one tenant + one agent key**. The same `scale_agent.py` binary
  serves every site; only `scale_config.json` differs (`tenant_slug` + `agent_key`).
- To roll out to another PC: copy `C:\weighbridge-agent\` there, run Phases P + D.
  Serial discovery happens automatically per machine.
- **Never reuse an agent key across tenants** — the key *is* the tenant routing.
- Rotating a key: Platform console → Tenants → Rotate agent key → update that
  site's `scale_config.json` → `Restart-Service`.

---

## Appendix A — `scale_config.json` reference

| Key | Default | Meaning |
|---|---|---|
| `cloud_url` | `https://weighbridgesetu.com` | Base URL the agent POSTs to |
| `tenant_slug` | `""` (**required**) | Which tenant this feed belongs to |
| `agent_key` | `""` (**required, secret**) | Validates the feed to the tenant |
| `port` | `""` | Serial port — **leave blank**, auto-detected + cached |
| `baud_rate` | `0` | Auto-detected + cached |
| `data_bits` | `0` | Auto-detected + cached |
| `parity` | `""` | Auto-detected + cached (`N`/`E`/`O`) |
| `stop_bits` | `1` | Usually 1 |
| `push_interval_ms` | `500` | ms between cloud posts (2 Hz) |
| `calibration_offset_kg` | `0.0` | Added before push: `display − app` (§4) |
| `log_raw_frames` | `false` | Log raw serial frames at DEBUG (diagnostics) |
| `status_port` | `9002` | Local diagnostics/Discovery UI port (auto-bumps 9002→9006 if busy) |

> **Secret handling:** `agent_key` is a credential — don't paste it into chats,
> screenshots, or tickets. Mask it (`…last4`) when sharing logs.

## Appendix B — `/status` field reference

`GET http://localhost:9002/status` →

| Field | Meaning |
|---|---|
| `scale_connected` | Agent currently owns a port and is reading frames |
| `detected_port` / `detected_config` | The locked port + serial config |
| `cloud_online` | Last cloud POST succeeded (key valid + 443 reachable) |
| `last_weight_kg` | Latest parsed weight (after calibration); `-1.0` = none yet |
| `last_raw_frame` | The most recent raw line from the indicator |
| `push_count` | Cloud posts sent since start (should rise continuously) |
| `error_count` | Read/parse/push errors since start |
| `calibration_offset_kg` | Active offset |

Other local endpoints (used by the Discovery UI): `/` (HTML page), `/ports`
(COM list), `/peek?port=COMx` (raw probe of one port), `/rescan` (clear cached
serial config → re-detect).

## Appendix C — agent CLI reference

| Command | Purpose |
|---|---|
| `python scale_agent.py` | Run in foreground (auto-detect → read → push). Ctrl+C to stop. |
| `python scale_agent.py --setup` | Interactive config wizard (Phase P) |
| `python scale_agent.py --detect` | One-shot port/baud detection, print, exit (Phase D) |
| `python scale_agent.py --debug` | Same as run, with DEBUG logging (raw frames, probe attempts) |
| `python scale_agent.py --install` / `--uninstall` | Service register/remove (the `.ps1` installer is preferred — it also retires the legacy service) |

## Appendix D — serial framing primer (why ASCII quality matters)

Indian indicators are almost always **7E1** (7 data bits, even parity) or **8N1**.
If the agent opens a 7E1 stream as 8N1, the parity bit is read as a data bit, so
~half the characters get a high bit set → non-ASCII garbage. The agent measures
**ASCII quality** (fraction of printable bytes); < 65 % ⇒ wrong config, rejected.
A correct config reads clean digits like `000.320` at ~100 % quality. This is
exactly why Discovery probes multiple configs and rejects garbage instead of
billing a bogus "2.0 kg".

## Appendix E — the 9 probe configs (in order)

`9600 7E1` · `9600 8N1` · `4800 7E1` · `4800 8N1` · `2400 7E1` · `1200 7E1` ·
`9600 8E1` · `19200 8N1` · `9600 7O1`

(Plain-digit frames like `000.320` read identically at 7E1 / 8N1 / 7N1 because
they contain no high-bit characters; the agent locks onto the first match.)

---

## Appendix F — one-screen checklist (print this)

```
PRE-FLIGHT  □ COM appears in Device Manager   □ NO terminal/vendor app on the port
            □ NO legacy WeighbridgeWeightBridge service   □ HTTPS 443 reachable
DISCOVERY   □ http://localhost:9002 shows clean raw frame  OR  --detect prints a config
   GATE D   □ value tracks the indicator display (and magnitude sane — not 1000× off)
PREPARE     □ --setup: cloud_url + tenant_slug + agent_key (+ calibration if needed)
   GATE P   □ foreground run: rising push_count, no 403, cloud restored
DEPLOY      □ install-scale-service.ps1 (as Admin)
   GATE D   □ service Running  □ scale_connected=true  □ cloud_online=true + push_count↑
            □ END-TO-END: bridge load = indicator = /status = app Weighbridge page
```
