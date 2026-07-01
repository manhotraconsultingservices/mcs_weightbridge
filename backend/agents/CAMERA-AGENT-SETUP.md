# Weighbridge Camera Agent — Client Setup Guide

This guide covers everything needed to install, configure, and troubleshoot the
Weighbridge Camera Agent on a client's site PC.

---

## What the Agent Does

The camera agent is a lightweight Python service that runs on the **client's on-site
Windows PC** (the same machine the weighbridge operator uses, or a dedicated PC on the
plant LAN). It does three things:

| Function | How it works |
|---|---|
| **Weighbridge snapshots** | When an operator records a weight, the cloud notifies the agent. The agent captures a JPEG from the weighbridge camera and uploads it — the photo then appears in the token detail view. |
| **Gate pass photos** | When a guard creates or closes a gate pass, the agent captures an entry/exit photo from the gate camera. |
| **Gate Camera Live Feed** | Continuously pushes frames from the gate cameras every 3 s to the cloud so the *Operations → Gate Cameras → Live* page shows a real-time CCTV view. |

All three run from the **same service** (`WeighbridgeCameraAgent`) and the **same
config file** (`camera_config.json`). No second agent or second config file is required.

---

## Package Contents

| File | Purpose |
|---|---|
| `camera_agent.py` | The agent script itself |
| `camera_config.example.json` | Example config (copy, rename, fill in) |
| `Install-CameraAgent.ps1` | Fresh install (new clients) |
| `Update-CameraAgent.ps1` | Update an existing install |
| `Diagnose-CameraAgent.ps1` | Diagnose issues on any PC |
| `CAMERA-AGENT-SETUP.md` | This guide |

---

## Prerequisites

Before starting, confirm the following:

- [ ] Windows 10 / Windows 11 on the site PC
- [ ] Python 3.11 or higher installed ([python.org](https://python.org))
  - Run `python --version` in PowerShell to check
  - On install, tick **"Add Python to PATH"**
- [ ] The site PC is on the same LAN as the IP cameras
- [ ] Camera snapshot URLs are known and accessible from the PC
  (open the URL in a browser on that PC — you should see a JPEG)
- [ ] The cloud URL and credentials from the Platform Admin console

---

## Fresh Install (new client)

Run PowerShell **as Administrator** and execute:

```powershell
cd C:\path\to\WeighbridgeCameraAgent-Package

# Interactive wizard — prompts for all values
.\Install-CameraAgent.ps1

# Or fully automated (no prompts)
.\Install-CameraAgent.ps1 `
    -InstallDir     "C:\weighbridge-agent" `
    -CloudUrl       "https://acme.weighbridgesetu.com" `
    -TenantSlug     "acme-minerals" `
    -AgentKey       "your-agent-api-key" `
    -FrontCameraUrl "http://192.168.0.101/cgi-bin/snapshot.cgi" `
    -TopCameraUrl   "http://192.168.0.103/cgi-bin/snapshot.cgi" `
    -EntryCameraUrl "http://192.168.0.200/cgi-bin/snapshot.cgi" `
    -ExitCameraUrl  "http://192.168.0.201/cgi-bin/snapshot.cgi" `
    -CameraUser     "admin" `
    -CameraPass     "camera123"
```

The script:
1. Checks Python and downloads NSSM if missing
2. Creates the install directory and copies `camera_agent.py`
3. Installs Python packages (`requests`, `Pillow`, `websockets`)
4. Writes `camera_config.json`
5. Tests the camera connections
6. Registers and starts the `WeighbridgeCameraAgent` Windows service

After the install, skip to [Verify It's Working](#verify-its-working).

---

## Manual Setup (step by step)

Use this if the PowerShell script can't run or you prefer full control.

### Step 1 — Create the install directory

```powershell
New-Item -ItemType Directory -Force -Path C:\weighbridge-agent
New-Item -ItemType Directory -Force -Path C:\weighbridge-agent\logs
```

Copy `camera_agent.py` into `C:\weighbridge-agent\`.

### Step 2 — Install Python packages

```powershell
python -m pip install requests urllib3 Pillow "websockets>=13"
```

### Step 3 — Create `camera_config.json`

Copy `camera_config.example.json` to `C:\weighbridge-agent\camera_config.json`
and fill in the values (see [Config Reference](#config-reference) below).

Or run the built-in wizard:

```powershell
cd C:\weighbridge-agent
python camera_agent.py --setup
```

### Step 4 — Test cameras

```powershell
cd C:\weighbridge-agent
python camera_agent.py --test
```

Expected output:
```
  front: OK (87432 bytes) → ...\test_snapshots\test_front.jpg
  top:   OK (91208 bytes) → ...\test_snapshots\test_top.jpg
```

If a camera shows `FAILED`, check the URL and credentials in `camera_config.json`.

### Step 5 — Install as Windows service

Download NSSM from [nssm.cc](https://nssm.cc), place `nssm.exe` in
`C:\weighbridge-agent\` (or anywhere on PATH), then:

```powershell
cd C:\weighbridge-agent
python camera_agent.py --install
```

Check it started:
```powershell
nssm status WeighbridgeCameraAgent
# Expected: SERVICE_RUNNING
```

---

## Updating an Existing Install

Use this on a client who already has the agent running and you need to:
- Update to a newer `camera_agent.py`
- Add gate cameras for the live feed
- Change camera IPs or credentials

```powershell
# From the source package folder:
.\Update-CameraAgent.ps1

# Or specify the client's install directory explicitly:
.\Update-CameraAgent.ps1 -InstallDir "C:\sss-stone-agent"
```

If you run the script **from inside the install directory** (source == destination),
it automatically downloads the latest `camera_agent.py` from GitHub instead.

To add or change only the gate camera URLs without touching anything else:

```powershell
.\Update-CameraAgent.ps1 `
    -InstallDir     "C:\weighbridge-agent" `
    -EntryCameraUrl "http://192.168.0.200/cgi-bin/snapshot.cgi" `
    -ExitCameraUrl  "http://192.168.0.201/cgi-bin/snapshot.cgi" `
    -CameraUser     "admin" `
    -CameraPass     "camera123"
```

---

## Config Reference

`camera_config.json` — all fields explained:

```jsonc
{
  // ── Cloud connection ────────────────────────────────────────────────────────
  "cloud_url":   "https://acme.weighbridgesetu.com",  // tenant subdomain URL
  "tenant_slug": "acme-minerals",                      // tenant identifier
  "agent_key":   "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx", // from Platform Admin

  // ── Polling ─────────────────────────────────────────────────────────────────
  "poll_interval_sec": 5,   // how often to check for pending events (seconds)

  // ── Local ports ─────────────────────────────────────────────────────────────
  "status_port": 9003,  // http://localhost:9003/ → agent status JSON
  "ws_port":     9004,  // ws://localhost:9004/live/{front|top} → live stream

  // ── Weighbridge cameras (snapshot on each weight) ────────────────────────────
  "cameras": {
    "front": {
      "label":    "Front View",
      "url":      "http://192.168.0.101/cgi-bin/snapshot.cgi",
      "username": "admin",
      "password": "camera123"
    },
    "top": {
      "label":    "Top View",
      "url":      "http://192.168.0.103/cgi-bin/snapshot.cgi",
      "username": "admin",
      "password": "camera123"
    }
  },

  // ── Gate cameras (live feed + gate pass entry/exit photos) ───────────────────
  // Leave "url" blank to reuse cameras.front for that position.
  "gate_cameras": {
    "entry": {
      "label":    "Gate Entry",
      "url":      "http://192.168.0.200/cgi-bin/snapshot.cgi",
      "username": "admin",
      "password": "camera123"
    },
    "exit": {
      "label":    "Gate Exit",
      "url":      "http://192.168.0.201/cgi-bin/snapshot.cgi",
      "username": "admin",
      "password": "camera123"
    }
  },

  // ── Snapshot storage mode (leave snapshot_serve_url blank for upload mode) ───
  // Option A — upload to VPS (default, no extra setup needed):
  "snapshot_serve_url": "",

  // Option B — local-first via Cloudflare Tunnel (see DPD-CAMERA-AGENT.md):
  // "snapshot_serve_url": "https://cam-acme.weighbridgesetu.com",
  // "local_save_dir":     "D:\\weighbridge\\snapshots",
  // "file_serve_port":    9005
}
```

### Camera URL formats by brand

| Brand | Snapshot URL format |
|---|---|
| CP Plus / Dahua | `http://IP/cgi-bin/snapshot.cgi` |
| Hikvision | `http://IP/Streaming/channels/1/picture` |
| AXIS | `http://IP/axis-cgi/jpg/image.cgi` |
| Generic ONVIF | `http://IP/onvif/snapshot` |
| Generic | `http://IP/snap.jpg` or `http://IP/snapshot.jpg` |

Test any URL by opening it in a browser on the site PC — you should see a still image.

---

## Finding the Install Directory on an Existing PC

The install directory varies per client (e.g., `C:\weighbridge-agent`,
`C:\sss-stone-agent`, `C:\WEIGHBRIDGE\agent`). To find it:

```powershell
sc.exe qc WeighbridgeCameraAgent
```

Look for the `BINARY_PATH_NAME` line:
```
BINARY_PATH_NAME : C:\sss-stone-agent\nssm.EXE
```

The install directory is the folder containing that `.EXE` — in this case
`C:\sss-stone-agent`.

Or run the diagnostic script — it finds the directory automatically:

```powershell
.\Diagnose-CameraAgent.ps1
```

---

## Verify It's Working

### 1. Service is running

```powershell
Get-Service WeighbridgeCameraAgent
# Status should be: Running
```

### 2. Check the logs

```powershell
Get-Content C:\weighbridge-agent\logs\camera_agent.log -Tail 20
```

A healthy start-up looks like:

```
2026-07-01 10:00:01 [INFO] Cloud: https://acme.weighbridgesetu.com (status: ok)
2026-07-01 10:00:02 [INFO] Event listener started (polling every 5s)
2026-07-01 10:00:02 [INFO] Gate pass listener started (polling every 5s)
2026-07-01 10:00:02 [INFO] Gate live feed (entry): http://192.168.0.200/cgi-bin/snapshot.cgi
2026-07-01 10:00:02 [INFO] Gate live feed (exit): http://192.168.0.201/cgi-bin/snapshot.cgi
2026-07-01 10:00:02 [INFO] Gate live feed pusher started (every 3s per camera)
2026-07-01 10:00:02 [INFO] Status API: http://127.0.0.1:9003
2026-07-01 10:00:02 [INFO] Running. Press Ctrl+C to stop.
```

If **`Gate live feed pusher started`** is present, the live feed is active.

### 3. Verify weighbridge snapshots

Record a weight on any token. The snapshot should appear in the token detail
within 10 seconds.

### 4. Verify the Gate Camera Live Feed

Open the app → **Operations → Gate Cameras → Live**.

You should see `● ENTRY LIVE` and `● EXIT LIVE` within ~5 seconds.
If you see **"No frames received yet"**, the `gate_cameras.entry/exit.url`
values are missing from `camera_config.json` — run `Update-CameraAgent.ps1`
to add them.

---

## Troubleshooting

Run the diagnostic script first — it checks everything automatically:

```powershell
.\Diagnose-CameraAgent.ps1
```

### Common issues

| Symptom | Likely cause | Fix |
|---|---|---|
| Service not found | Not installed | Run `Install-CameraAgent.ps1` |
| Service stopped | Crash at startup | Check logs: `Get-Content ...\logs\camera_agent.log -Tail 30` |
| Snapshots show "pending" forever | Agent not running, or wrong cloud URL / agent key | Check cloud URL in config; check agent_key matches Platform Admin |
| "Camera front: too many consecutive failures" | Camera IP unreachable from the PC | Open camera URL in a browser on that PC; check IP and credentials |
| Gate Camera Live Feed shows "No frames received yet" | `gate_cameras.url` not set | Run `Update-CameraAgent.ps1 -EntryCameraUrl ... -ExitCameraUrl ...` |
| Live feed still offline after URL added | Old code (no `GateLiveFeedPusher`) | Run `Update-CameraAgent.ps1` to download the latest `camera_agent.py` |
| Gate photos not captured | Gate photo capture not enabled | Go to Settings → Gate Cameras → enable "Automatic gate photo capture" |
| HTTP 403 on uploads | Wrong agent key | Get the correct key from Platform Admin → edit tenant → Agent API Key |
| HTTP 405 from cloud | Posting to apex URL (no subdomain) | Set `cloud_url` to the **tenant subdomain** `https://acme.weighbridgesetu.com`, not `https://weighbridgesetu.com` |

### Reading the log

```powershell
# Live log (keep terminal open and watch in real time)
Get-Content C:\weighbridge-agent\logs\camera_agent.log -Wait -Tail 20

# Last 50 lines
Get-Content C:\weighbridge-agent\logs\camera_agent.log -Tail 50
```

Key log lines and what they mean:

| Log line | What it means |
|---|---|
| `Gate live feed pusher started` | Gate cameras are configured and pushing frames |
| `Gate live feed: no gate camera URLs` | `gate_cameras.entry/exit.url` both empty — reusing front camera |
| `Camera front: too many consecutive failures` | Camera unreachable after 3 retries |
| `Poll HTTP 403` | Agent key rejected — update `agent_key` in config |
| `Cloud unreachable` | No internet or wrong `cloud_url` |
| `Gate capture: gp=... position=entry` | Gate pass photo capture triggered |

### Restart the service

```powershell
# With NSSM:
nssm restart WeighbridgeCameraAgent

# Without NSSM (Stop-Service / Start-Service work for NSSM-registered services):
Stop-Service WeighbridgeCameraAgent -Force
Start-Sleep -Seconds 3
Start-Service WeighbridgeCameraAgent
```

### Manually edit the config

Open `camera_config.json` in Notepad, edit, then restart:

```powershell
notepad C:\weighbridge-agent\camera_config.json
# ... make changes, Save ...
Stop-Service WeighbridgeCameraAgent -Force; Start-Sleep 2; Start-Service WeighbridgeCameraAgent
```

> **Important:** `camera_config.json` must be **plain UTF-8 without BOM**.
> If you use Notepad to save on Windows 10 or earlier, choose "UTF-8" (not
> "UTF-8 with BOM") in the Save As encoding dropdown.  PowerShell's `Out-File`
> on PS 5.1 writes a BOM by default — the `Update-CameraAgent.ps1` script
> handles this correctly and always writes BOM-free.

---

## Service Management Reference

| Action | Command |
|---|---|
| Check status | `nssm status WeighbridgeCameraAgent` |
| Start | `nssm start WeighbridgeCameraAgent` |
| Stop | `nssm stop WeighbridgeCameraAgent` |
| Restart | `nssm restart WeighbridgeCameraAgent` |
| Remove service | `nssm remove WeighbridgeCameraAgent confirm` |
| View service config | `sc.exe qc WeighbridgeCameraAgent` |
| View in Services GUI | `services.msc` → find WeighbridgeCameraAgent |

---

## Agent Status API

While the service is running, a lightweight HTTP server listens on port 9003
(configurable via `status_port` in the config):

```
GET http://localhost:9003/
```

Returns a JSON status:
```json
{
  "service": "camera_agent",
  "status": "running",
  "timestamp": "2026-07-01T10:15:30",
  "capture_count": 47,
  "error_count": 2
}
```

Useful for health monitoring or confirming the service is alive without reading
the log file.

---

## Uninstall

```powershell
cd C:\weighbridge-agent
python camera_agent.py --uninstall

# Or manually:
nssm stop WeighbridgeCameraAgent
nssm remove WeighbridgeCameraAgent confirm
Remove-Item -Recurse -Force C:\weighbridge-agent
```

---

## Advanced: Cloudflare Tunnel (local-first snapshot storage)

By default images are uploaded as binary data to the VPS. For high-volume sites
(500+ trucks/day) the upload bandwidth can be significant. The **local-first mode**
stores images on the site PC and serves them via a Cloudflare Tunnel — the VPS
only receives the URL, not the image data.

See [`DPD-CAMERA-AGENT.md`](DPD-CAMERA-AGENT.md) for the full setup guide
(Steps 1–5 cover the Cloudflare Tunnel + local file server configuration).

---

## Getting the Agent API Key

1. Open the Weighbridge Platform Admin console  
   (`https://weighbridgesetu.com` → log in with super-admin credentials)
2. Click the client tenant → **Edit**
3. Copy the **Agent API Key** field
4. Paste it as `agent_key` in `camera_config.json`

Each tenant has a unique key. If you regenerate it (Platform Admin → Rotate Key),
update `camera_config.json` on the site PC and restart the service.
