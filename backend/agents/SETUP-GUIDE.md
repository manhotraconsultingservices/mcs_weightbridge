# Weighbridge Client Agents — Step-by-Step Setup Guide

**Audience:** a field technician / junior practitioner installing at a client site.
**Assumes:** you can use Windows and copy files. No programming needed.
**Platform:** Windows 10 / 11 (64-bit). **Python on the client PC:** NOT required (all agents are self-contained `.exe`s).

> Read this whole page once before you start. Follow the sections **in order**.
> Every agent has the same 4 steps: **copy → --setup → --test → --install**.

---

## 0. The big picture (read this first)

The Weighbridge app itself is **cloud software** — the operator just opens
`https://<tenant>.weighbridgesetu.com` in Chrome. Nothing about the *app* is installed
on site.

What you install on site are small **bridge agents**. The cloud cannot reach the
client's local hardware (scale, cameras, Tally) across the internet, so these agents
run on the client's PC(s) and connect that hardware to the cloud.

```
        CLIENT SITE (LAN)                                  CLOUD
  ┌───────────────────────────┐                   ┌────────────────────┐
  │  Weighbridge PC            │   agents push →   │  weighbridgesetu   │
  │   • Scale Agent            │ ───────────────►  │  .com  (the app)   │
  │   • Camera Agent           │                   │                    │
  │   • Tally Connector        │ ◄─────────────    │  operator's Chrome │
  │   • Watchdog Agent         │   pulls jobs      │  opens the tenant  │
  ├───────────────────────────┤                   │  subdomain         │
  │  Gate PC (if separate)     │                   └────────────────────┘
  │   • Camera Agent (gate)    │
  │   • Vehicle Counter        │
  │   • Watchdog Agent         │
  └───────────────────────────┘
```

### The agents (install only the ones the client needs)

| Agent | What it does | Install when… | Service type |
|---|---|---|---|
| **Scale Agent** | Reads the weight indicator on a COM port → streams live weight to the cloud + the operator's browser. | There is a weighbridge (almost always). | Scheduled Task |
| **Camera Agent** | Captures IP-camera snapshots at each weighment + pushes the gate live feed. | Cameras are installed. | Scheduled Task |
| **Tally Connector** | Pushes finalised vouchers from the cloud into the client's **local** TallyPrime. | The client uses Tally. | NSSM service |
| **Watchdog Agent** | Watches the scale + cameras and alerts the owner on Telegram if a device goes down. | Recommended everywhere. | NSSM service |
| **Vehicle Counter** | Counts trucks/cars/bikes in & out of the gate (AI on the camera frames) → reconciles vs gate passes. | Paid add-on; the client bought it. | NSSM service |

> **One agent key per tenant** is shared by ALL agents on that client's PCs.

---

## 1. Before you go — gather these values

Get these from the **Platform admin** and from the site. Write them down:

| Value | Example | Where it comes from |
|---|---|---|
| **Tenant slug** | `sss-stone-crusher` | Platform console → the tenant (its subdomain) |
| **Agent key** | `2f0b57…` (one per tenant) | Platform console → tenant → Agent Key |
| **Cloud URL** | `https://weighbridgesetu.com` | Always this (agents auto-route to the tenant subdomain) |
| **Scale COM port + framing** | `COM3`, `9600`, `8N1` (some Indian indicators are `7E1`) | The indicator cable / its manual |
| **Camera snapshot URLs** | `http://192.168.0.101/cgi-bin/snapshot.cgi` | The IP cameras on the LAN |
| **Camera user / password** | `admin` / `admin123` | The camera login |
| **Gate entry/exit camera URLs** | `http://192.168.0.223/…` / `…224/…` | The two gate cameras (for gate live + vehicle counter) |
| **Tally host / port** | `localhost` / `9000` | The PC running TallyPrime (if used) |

**Common camera snapshot URL formats:**
- CP Plus / Dahua: `http://IP/cgi-bin/snapshot.cgi`
- Hikvision: `http://IP/Streaming/channels/1/picture`
- ONVIF generic: `http://IP/onvifsnapshot/media_service/snapshot?channel=1&subtype=0`

> **Tip:** paste each camera URL into a browser first. If it asks for a login and then
> shows a photo, the URL + user/password are correct.

---

## 2. Prepare the PC (one-time)

1. **Copy the bundle** `C:\weighbridge-agent` to the client PC (keep that exact path).
2. **Open PowerShell as Administrator:** Start → type `PowerShell` → right-click
   *Windows PowerShell* → **Run as administrator**.
3. **Allow scripts once** (only needed for the `.ps1` installer):
   ```powershell
   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
   ```
4. **Install NSSM** — needed by the Tally, Watchdog, and Vehicle-Counter agents (NOT by
   Scale/Camera). Download from <https://nssm.cc/download>, unzip, and copy the 64-bit
   `nssm.exe` to `C:\Windows\System32\` (or any folder on the PATH). Verify:
   ```powershell
   nssm --version
   ```
   If it prints a version, you're set. (Skip this if you're only installing Scale + Camera.)

---

## 3. Install Scale + Camera (one command)

These two install together via the installer script.

```powershell
cd C:\weighbridge-agent
.\deploy-agents.ps1
```

It will **ask** for the values from §1 (tenant slug, agent key, camera URLs, COM port,
serial framing…), then write the config, register the agents as **auto-start Scheduled
Tasks**, open the firewall, and test the cameras. When it finishes, both agents are
already running (and will restart on every reboot).

**Options:**
- Scale only (no cameras): add `-AgentType scale`
- Camera only: add `-AgentType camera`
- Repeat installs unattended — pass everything on the command line:
  ```powershell
  .\deploy-agents.ps1 -TenantSlug "sss-stone-crusher" -AgentKey "PASTE-KEY" `
      -FrontCameraUrl "http://192.168.0.101/cgi-bin/snapshot.cgi" `
      -TopCameraUrl   "http://192.168.0.103/cgi-bin/snapshot.cgi" `
      -EntryCameraUrl "http://192.168.0.223/onvifsnapshot/media_service/snapshot?channel=1&subtype=0" `
      -ExitCameraUrl  "http://192.168.0.224/onvifsnapshot/media_service/snapshot?channel=1&subtype=0" `
      -CameraUser "admin" -CameraPass "admin123" `
      -ComPort "COM3" -BaudRate 9600
  ```

> **Serial framing matters:** `8N1` is common, but many Indian indicators (Essae etc.)
> use `7E1`. If the weight reads garbage for ~2 minutes then settles, the framing was
> wrong — re-run with `-DataBits 7 -Parity E -StopBits 1`.

**✔ Verify:** open `http://localhost:9002` (scale — shows live weight) and
`http://localhost:9003` (camera — shows running). Then in the web app the live weight
should move in the weighment screen.

---

## 4. Install the Tally Connector (only if the client uses Tally)

Needs NSSM (§2 step 4). Then:

```powershell
cd C:\weighbridge-agent\dist
.\tally_connector.exe --setup      # cloud URL, tenant, agent key, Tally host/port
.\tally_connector.exe --test       # verify cloud auth + local Tally reachable
.\tally_connector.exe --install    # registers auto-start service WeighbridgeTallyConnector
nssm start WeighbridgeTallyConnector
```

> In **TallyPrime**: enable the HTTP gateway (Gateway of Tally → F1 → Settings →
> Connectivity), and in **Import Configuration** set **"Overwrite same-GUID voucher = Yes"**
> so re-syncs update instead of silently skipping.

**✔ Verify:** open `http://localhost:9010` → should show **CLOUD ONLINE / TALLY OK**.

Full details: `docs\DPD-TALLY-CONNECTOR.md`.

---

## 5. Install the Watchdog Agent (recommended)

Alerts the owner on Telegram if the scale or a camera goes down. **Install one per PC**
(the weighbridge PC watches the scale + its cameras; the gate PC watches the gate
cameras). Needs NSSM.

```powershell
cd C:\weighbridge-agent\dist
.\watchdog_agent.exe --setup       # cloud URL, tenant, agent key, this PC's label
```
Then open `C:\weighbridge-agent\dist\watchdog_agent.json` and list this PC's devices
(scale + each camera with its URL). A starter list is written for you — edit the URLs,
remove any device this PC doesn't have.
```powershell
.\watchdog_agent.exe --test        # probes every device + the cloud once
.\watchdog_agent.exe --install
nssm start WeighbridgeWatchdogAgent
```

**✔ Verify:** open `http://localhost:9020`. The owner also picks which alerts to receive
in the app (Notifications → Recipients), and the down-threshold in Settings → Device Health.

---

## 6. Install the Vehicle Counter (paid add-on — only if the client bought it)

Counts trucks/cars/bikes in & out of the gate and reconciles them against the gate
passes the guard creates. **Install on the gate PC** (the one that can see the gate
cameras). Needs NSSM.

> **This is a paid feature.** It only works if the Platform admin has turned the
> **`vehicle_count`** module **ON** for this tenant (Platform → Edit tenant → Feature
> Modules). If it's OFF, the agent's `--test` will say *"module is OFF"* and nothing is
> counted — that's the central on/off control.

```powershell
cd C:\weighbridge-agent\dist
.\vehicle_counter_agent.exe --setup   # tenant, agent key (SAME as camera), entry+exit camera URLs
.\vehicle_counter_agent.exe --test    # expect: model loaded · cameras OK · cloud accepted
.\vehicle_counter_agent.exe --install
nssm start WeighbridgeVehicleCounter
```

The AI model is **built into the exe** — nothing else to download.

**✔ Verify:** open `http://localhost:9011` (shows per-camera counts). In the web app:
**Operations → Gate Vehicle Count** — the IN/OUT counts, per-class breakdown and the
camera-vs-gate-pass reconciliation populate as vehicles pass.

Full details + tuning: `docs\DPD-VEHICLE-COUNTER.md`.

---

## 7. ⚠ If an agent won't start — Smart App Control / SmartScreen

The `.exe`s are **not code-signed**. On a PC with **Smart App Control ON**, Windows may
block them. If an agent won't start:
- Right-click the `.exe` → **Properties** → tick **Unblock** → Apply, then restart it; **or**
- Turn Smart App Control **OFF** (Settings → Privacy & security → Windows Security →
  App & browser control → Smart App Control). *Note: once OFF it stays off until a Windows reinstall.*

---

## 8. Final verification checklist

Tick each on the client PC and in the app:

- [ ] Scale: `http://localhost:9002` shows live weight; weight moves in the app.
- [ ] Camera: `http://localhost:9003` shows running; a snapshot is captured at weighment.
- [ ] Tally (if used): `http://localhost:9010` shows CLOUD ONLINE / TALLY OK.
- [ ] Watchdog: `http://localhost:9020` lists this PC's devices as OK.
- [ ] Vehicle Counter (if bought + module ON): `http://localhost:9011` counts; report populates.
- [ ] Reboot the PC once and re-check — every agent should come back up on its own.

---

## 9. Uninstall

- **Scale + Camera:** `cd C:\weighbridge-agent ; .\deploy-agents.ps1 -Uninstall`
- **Tally / Watchdog / Vehicle Counter:** from `dist\`, run each with `--uninstall`
  (e.g. `.\vehicle_counter_agent.exe --uninstall`).

(Config files + `logs\` are left in place; delete the folder to remove everything.)

---

## 10. Reference — ports, services, configs, logs

| Agent | Service / Task | Port | Config file | Log |
|---|---|---|---|---|
| Scale | `WeighbridgeScaleAgent` (Task) | 9002 | `scale_config.json` | `logs\scale_agent.log` |
| Camera | `WeighbridgeCameraAgent` (Task) | 9003 + 9004 (live WS) | `camera_config.json` | `logs\camera_agent.log` |
| Tally | `WeighbridgeTallyConnector` (NSSM) | 9010 | `tally_connector.json` | `logs\tally_connector.log` |
| Watchdog | `WeighbridgeWatchdogAgent` (NSSM) | 9020 | `watchdog_agent.json` | `logs\watchdog_agent.log` |
| Vehicle Counter | `WeighbridgeVehicleCounter` (NSSM) | 9011 | `vehicle_counter.json` | `logs\vehicle_counter_agent.log` |

Handy commands (PowerShell):
```powershell
Get-ScheduledTask 'Weighbridge*Agent'        # scale + camera
Get-Service Weighbridge*                      # tally + watchdog + vehicle counter (NSSM)
Get-Content C:\weighbridge-agent\dist\logs\vehicle_counter_agent.log -Tail 20
nssm restart WeighbridgeVehicleCounter        # restart an NSSM agent
Stop-ScheduledTask WeighbridgeScaleAgent; Start-ScheduledTask WeighbridgeScaleAgent
```

---

## 11. Troubleshooting

| Symptom | Fix |
|---|---|
| **Live weight not moving** | `http://localhost:9002` — scale connected? Check COM port/baud (Device Manager → Ports). Wrong framing → re-run with `-DataBits 7 -Parity E -StopBits 1` (Essae-type). |
| **"AGENT KEY REJECTED (403)"** | Wrong `tenant_slug` or `agent_key`. Re-run `--setup` with the correct values from the Platform console. |
| **Camera "offline"** | Open the snapshot URL in a browser to confirm it works + the login. Use the right format (§1). |
| **Vehicle counter: "module is OFF"** | Ask the Platform admin to enable the `vehicle_count` module for this tenant. |
| **Vehicle counter: "model load failed"** | The exe wasn't built with the model — get a fresh `vehicle_counter_agent.exe` from the vendor. |
| **Any agent won't start** | Almost always Smart App Control — see §7. |
| **"NSSM not found"** | Install NSSM (§2 step 4) and put `nssm.exe` on the PATH, then re-run `--install`. |
| **Tally: imported 0 / EXCEPTIONS** | TallyPrime → Import Configuration → *Overwrite same-GUID voucher = Yes*; for GST/inventory rejections use the app's **Accounting-vouchers (no inventory)** mode in Settings → Tally. |

---

## 12. What's in this bundle

```
C:\weighbridge-agent\
├── SETUP-GUIDE.md          ← this guide (start here)
├── deploy-agents.ps1       ← installer for Scale + Camera
├── dist\                   ← the agents (self-contained .exe — no Python needed)
│   ├── scale_agent.exe
│   ├── camera_agent.exe
│   ├── tally_connector.exe
│   ├── watchdog_agent.exe
│   ├── vehicle_counter_agent.exe   (AI model bundled inside)
│   ├── serial_doctor.exe   ← scale/COM-port diagnostic
│   └── camera_doctor.exe   ← camera diagnostic
├── config-examples\        ← sample config files (reference only — no real keys)
└── docs\                   ← the detailed per-agent guides (DPD-*.md, etc.)
```

*Vendor note: the source, build recipes and the exe build (PyInstaller) live in the
product repo under `backend/agents/`. The `.exe`s are unsigned — a code-signing
certificate is recommended before a wide rollout (removes the Smart App Control prompt).*
