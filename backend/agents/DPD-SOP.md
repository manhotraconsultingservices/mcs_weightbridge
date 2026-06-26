# Weighbridge Scale Agent — DPD installation SOP

**D**iscovery → **P**repare → **D**eploy. Follow the stages in order. Do **not**
move to the next stage until its **GATE** passes. This removes the on-site
trial-and-error of finding the right COM port + baud + framing (7N1 / 7E1 /
8N1 / 8O1 …) and guarantees the feed reaches the cloud.

> This is the **1-page runbook**. For the full manual — architecture & data
> flow, the Discovery UI, calibration/unit checks, the complete troubleshooting
> matrix, and config/CLI/status appendices — see
> [**`DPD-GUIDE.md`**](./DPD-GUIDE.md).

Server side needs nothing — the agent posts to `POST /api/v1/weight/external-reading`
with `tenant` + `agent_key` in the body; the server validates the key and
broadcasts live weight to the browser. No server change is ever required.

> ## ⚠ SINGLE-OWNER RULE — the #1 gotcha, read this first
>
> **A Windows COM port can be opened by exactly ONE process at a time.** If
> anything else holds the port, the agent gets *"Access to the port 'COMx' is
> denied"* and reports **Scale NOT FOUND** — even though the scale, baud rate
> and wiring are perfectly fine. Things that silently hold the port:
>
> - A **serial terminal** left open (PuTTY, RealTerm, Hercules, Arduino Serial
>   Monitor, even a `terminal.exe` window showing the feed).
> - The **vendor's own weighbridge software**.
> - The **legacy `WeighbridgeWeightBridge` service** (the old `weight_bridge.py`).
>   On any site upgraded from the pre-cloud build, this service is still running
>   and will lock the agent out of the port forever.
>
> **Before Deploy, make sure NOTHING else owns the port.** The installer now
> auto-stops + disables `WeighbridgeWeightBridge` and kills stray
> `weight_bridge.py` — but you must close any terminal / vendor app yourself.
> **The service and a terminal can never read the same COM port at once** — if
> you Peek/sniff a port in the Discovery UI, the agent can't read it during that
> moment, and vice-versa.
>
> **Find what holds a port (when COMx is "denied"):**
> ```powershell
> # any python still on the port?
> Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
>   Where-Object { $_.CommandLine -match 'weight_bridge|scale_agent' } |
>   Select-Object ProcessId,CommandLine
> # legacy service still alive?
> Get-Service WeighbridgeWeightBridge   # must be Stopped + Disabled
> ```

---

## 0. Prerequisites (one-time per machine)

- [ ] Windows PC wired to the weighbridge indicator (RS‑232 → USB adapter).
- [ ] **Python 3.11+** installed (`python --version`).
- [ ] `pip install pyserial requests` (or `pip install -r requirements.txt`).
- [ ] **NSSM** installed and on PATH (`nssm version`). It is NOT downloaded by
      the installer — install it once (https://nssm.cc) or `choco install nssm`.
- [ ] Agent files in **`C:\weighbridge-agent`**: `scale_agent.py`, `requirements.txt`.
- [ ] **Agent key** + **tenant slug** for this client, from the Platform admin
      console (Tenants → the client → agent key). Keep it handy for stage P.

---

## D — DISCOVERY  (find the right port + framing → clean weight, not garbage)

Power on the indicator, put a known load on the bridge (or note the idle
reading), then:

```powershell
cd C:\weighbridge-agent
python scale_agent.py --detect
```

It scans every COM port against the standard serial configs, rejects any combo
that returns non-ASCII garbage, and prints the first one that yields a valid
weight, e.g.:

```json
{ "port": "COM6", "baud_rate": 2400, "data_bits": 7, "parity": "E", "stop_bits": 1 }
```
> `Scale FOUND: COM6 @ 2400 baud  7E1  weight=12500.0 kg`

**GATE D — PASS when:**
1. It prints a config block (not "Scale NOT FOUND"), **and**
2. the reported `weight` matches (within a few kg) what the **indicator display
   shows**. Add/remove a load and re-run `--detect` — the number must track the
   display.

**If it FAILS:**
| Symptom | Fix |
|---|---|
| `No COM ports found` | USB cable not seated / adapter driver missing — check Device Manager → Ports (COM & LPT). Install CH340 / FTDI / Prolific driver. |
| `Scale NOT FOUND` | **First check the port isn't already owned** (see the Single-owner rule above — close any terminal, stop the legacy `WeighbridgeWeightBridge` service). Then: indicator off, or it only sends on a "print"/"stable" trigger — press the indicator's PRINT key while detecting; confirm it's set to **continuous** output in its menu. |
| Found, but weight is wrong / jumps | Wrong framing matched. Re-run `--detect`; if it keeps mismatching, set the indicator to a standard mode (most common: **9600 8N1** or **2400 7E1**) and retry. Note the indicator's documented protocol. |

---

## P — PREPARE  (write the config: cloud + tenant + key)

```powershell
python scale_agent.py --setup
```
Answer the prompts:
- **Cloud URL** — `https://weighbridgesetu.com` (default; press Enter).
- **Tenant slug** — e.g. `manhotra-consulting`.
- **Agent key** — paste from the Platform console.
- **Calibration offset** (optional) — if the app reads N kg off the display,
  enter `display − app` (e.g. display 12500, app 12550 → `-50`).

This writes `C:\weighbridge-agent\scale_config.json`. Serial port/baud/framing
are auto-detected when the agent starts (and cached back into the JSON for fast
restarts), so you do **not** hand-edit them.

**GATE P — PASS when:** `scale_config.json` exists and a quick foreground run
streams to the cloud:

```powershell
python scale_agent.py        # Ctrl+C after ~10 s
```
Watch the log: it should auto-detect the port, log weights, and show
`Cloud connection restored` / rising push count (no repeated `AGENT KEY
REJECTED (403)`). Then stop it (the service will own the port in stage D).

**If it FAILS:**
| Symptom | Fix |
|---|---|
| `AGENT KEY REJECTED (403)` | Wrong `agent_key` or `tenant_slug`. Re-copy from the Platform console; re-run `--setup`. |
| `Cloud unreachable` | Firewall/proxy blocking outbound 443, or wrong `cloud_url`. Test `Invoke-RestMethod https://weighbridgesetu.com/api/v1/health`. |

---

## D — DEPLOY  (install the service, verify local read + cloud post)

Open **PowerShell as Administrator** and run the installer (from the repo or a
copy alongside the agent):

```powershell
powershell -ExecutionPolicy Bypass -File install-scale-service.ps1
```
It registers `WeighbridgeScaleAgent` (auto-start + restart-on-crash), points it
at `C:\weighbridge-agent`, captures logs to `…\logs\`, and runs a health check.

**GATE D — PASS when ALL are true:**
1. `Get-Service WeighbridgeScaleAgent` → **Running**.
2. Local read works — `last_weight_kg` changes as load changes:
   ```powershell
   Invoke-RestMethod http://localhost:9002/status | ConvertTo-Json -Depth 5
   ```
   (use your `status_port` if not 9002).
3. Cloud post works — in the same `/status`, `cloud_online` is `true` and
   `push_count` keeps rising.
4. **End-to-end** — open the client's app → Weighbridge page; the live weight
   matches the indicator while a truck is on the bridge.

**If it FAILS:**
| Symptom | Fix |
|---|---|
| `Status port … NOT listening` | Agent crashed at init — `Get-Content C:\weighbridge-agent\logs\service_stderr.log -Tail 30`. Usually a missing dependency or the COM port held by another app (close any vendor weighbridge software). |
| `cloud_online=false` after install | Same 403 / firewall checks as stage P; then `Restart-Service WeighbridgeScaleAgent`. |
| Service flaps (restart loop) | The port is busy or detection keeps failing — re-run stage D foreground to confirm a clean read, fix, then `Restart-Service`. |

---

## Day-to-day / handover

```powershell
Get-Service WeighbridgeScaleAgent
Restart-Service WeighbridgeScaleAgent
Get-Content C:\weighbridge-agent\logs\scale_agent.log -Tail 30 -Wait
Invoke-RestMethod http://localhost:9002/status | ConvertTo-Json -Depth 5
```
Uninstall: `install-scale-service.ps1 -Uninstall`.

**Definition of done:** GATE D passed → the truck on the bridge shows the same
weight on the indicator, in `/status`, and on the app's Weighbridge page.
