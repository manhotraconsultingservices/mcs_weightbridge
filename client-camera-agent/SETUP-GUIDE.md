# Weighbridge Camera Agent — Client Installation Guide

This guide is written for field engineers installing the Camera Agent on a client's
Windows PC. Follow every step in order. Do not skip steps.

---

## What Is the Camera Agent?

The Camera Agent is a small Python program that runs as a Windows background service
on the client's on-site PC. It does three things:

1. **Weighbridge snapshots** — when an operator records a weight, the agent captures
   a photo from the weighbridge camera and uploads it to the cloud. The photo then
   appears inside the Weighbridge app on the token detail screen.

2. **Gate pass photos** — when a guard opens or closes a gate pass, the agent captures
   an entry or exit photo from the gate camera.

3. **Gate Camera Live Feed** — every 3 seconds the agent pushes a live frame from
   the gate cameras to the cloud so the Operations → Gate Cameras → Live page shows
   a real-time CCTV view.

All three functions run from the **same service** and the **same config file**.

---

## Files in This Package

| File | What it does |
|---|---|
| `camera_agent.py` | The agent program itself |
| `camera_config.example.json` | Example config file — copy this, fill in values, rename to `camera_config.json` |
| `Install-CameraAgent.ps1` | **Fresh install** wizard — use for new clients |
| `Update-CameraAgent.ps1` | **Update** an existing install — use when adding gate cameras or updating the agent |
| `Diagnose-CameraAgent.ps1` | **Diagnose problems** on any installed PC |

---

## Before You Start — Information to Collect

Before visiting the client site (or before calling the client), collect the following.
You will need all of this during installation.

### From the Weighbridge Platform Admin console

Log into the Platform Admin (`https://weighbridgesetu.com` with super-admin login):

1. Click the client tenant name → **Edit**
2. Copy the **Tenant Slug** (e.g. `acme-minerals`)
3. Copy the **Agent API Key** (a long string of letters and numbers)
4. Note the **tenant URL** — it will be `https://<tenant-slug>.weighbridgesetu.com`

### From the client's camera setup

Ask the client or their IT person:

| Information | Example | Where to find it |
|---|---|---|
| Weighbridge camera 1 (Front View) IP address | `192.168.0.101` | Camera sticker or network router admin page |
| Weighbridge camera 2 (Top View) IP address | `192.168.0.103` | Camera sticker or network router admin page |
| Gate Entry camera IP address | `192.168.0.200` | Camera sticker or network router admin page |
| Gate Exit camera IP address | `192.168.0.201` | Camera sticker or network router admin page |
| Camera login username | `admin` | Usually printed on camera or in camera manual |
| Camera login password | `admin123` | Usually printed on camera or in camera manual |

> **Tip — How to verify a camera URL works:**
> On the client PC, open any web browser (Chrome, Edge, etc.) and type this in the
> address bar (replace IP with the actual camera IP):
> ```
> http://192.168.0.101/cgi-bin/snapshot.cgi
> ```
> If you see a photo appear in the browser, the camera URL is correct.
> If you see an error or a login prompt, try the formats in the
> [Camera URL Formats](#camera-url-formats-by-brand) section at the bottom.

---

## Part 1 — Fresh Install (New Client)

Use this section when the client has never had the Camera Agent installed before.

### Step 1 — Transfer the package to the client PC

Copy the entire `client-camera-agent` folder to the client PC. You can use:
- USB drive
- Remote desktop file transfer
- WhatsApp/email (zip the folder first)

Place it somewhere easy to find, for example: `C:\WeighbridgeSetup\`

After copying, the client PC should have these files at `C:\WeighbridgeSetup\`:
```
camera_agent.py
camera_config.example.json
Install-CameraAgent.ps1
Update-CameraAgent.ps1
Diagnose-CameraAgent.ps1
SETUP-GUIDE.md
```

### Step 2 — Check Python is installed

The agent requires Python 3.11 or higher.

1. Press **Windows key + R** on the client PC
2. Type `powershell` and press Enter
3. In the PowerShell window that opens, type:
   ```
   python --version
   ```
4. Press Enter

**What you should see:**
```
Python 3.11.9
```
(The number after 3.11 can be anything — 3.11, 3.12, 3.13 all work.)

**If you see an error** ("python is not recognized" or "command not found"):

Python is not installed. Install it:
1. Open a web browser on the client PC and go to: `https://www.python.org/downloads/`
2. Click the big yellow **"Download Python 3.x.x"** button
3. Run the downloaded installer
4. **IMPORTANT:** On the first screen of the installer, tick the checkbox that says
   **"Add Python to PATH"** — this is at the bottom of the window. If you miss this,
   Python will not work from PowerShell.
5. Click **Install Now**
6. After installation, close PowerShell and open a new one, then run `python --version` again

### Step 3 — Open PowerShell as Administrator

The installation must run as Administrator. This is important — it will fail without it.

1. Press the **Windows key** (the key with the Windows logo)
2. Type: `powershell`
3. You will see **Windows PowerShell** appear in the search results
4. **Right-click** on Windows PowerShell
5. Click **"Run as administrator"**
6. A window will appear asking "Do you want to allow this app to make changes to your
   device?" — click **Yes**

A blue PowerShell window will open. The title bar should say
**"Administrator: Windows PowerShell"**. If it does not say "Administrator", close it
and try again.

### Step 4 — Navigate to the setup folder

In the Administrator PowerShell window, type the following and press Enter:
```powershell
cd C:\WeighbridgeSetup
```

(If you saved the files to a different folder, use that path instead.)

Confirm you are in the right folder by typing:
```powershell
dir
```

You should see the files listed:
```
camera_agent.py
Install-CameraAgent.ps1
Update-CameraAgent.ps1
...
```

### Step 5 — Allow the script to run

Windows blocks PowerShell scripts by default. Run this command to allow them:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

When asked "Do you want to change the execution policy?", type `Y` and press Enter.

### Step 6 — Run the Install script

Type the following and press Enter:
```powershell
.\Install-CameraAgent.ps1
```

The script will now run and ask you a series of questions. Here is exactly what it asks
and what to type for each:

---

**Question 1: Install directory**

```
Enter install directory [C:\weighbridge-agent]:
```

This is where the agent files will be stored permanently on the client PC.
Press **Enter** to accept the default `C:\weighbridge-agent`.
(Or type a different path if the client prefers, then press Enter.)

---

**Question 2: Cloud URL**

```
Enter cloud URL (e.g. https://acme.weighbridgesetu.com):
```

Type the tenant URL you collected from Platform Admin. Example:
```
https://acme-minerals.weighbridgesetu.com
```

> **Important:** Use the **subdomain URL** (with the tenant name before
> `.weighbridgesetu.com`), NOT `https://weighbridgesetu.com` by itself.

---

**Question 3: Tenant Slug**

```
Enter tenant slug:
```

Type the Tenant Slug from Platform Admin. Example:
```
acme-minerals
```

---

**Question 4: Agent API Key**

```
Enter agent API key:
```

Paste the Agent API Key from Platform Admin. It is a long string like:
```
a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

---

**Question 5: Front camera URL**

```
Enter front camera URL (e.g. http://192.168.0.101/cgi-bin/snapshot.cgi):
```

Type the snapshot URL for the weighbridge front camera. Example:
```
http://192.168.0.101/cgi-bin/snapshot.cgi
```

See [Camera URL Formats](#camera-url-formats-by-brand) if unsure of the format.

---

**Question 6: Top camera URL (optional)**

```
Enter top camera URL (blank to skip):
```

If there is a second weighbridge camera (top view), type its URL.
If there is only one weighbridge camera, press **Enter** to skip.

---

**Question 7: Gate Entry camera URL (optional)**

```
Enter gate entry camera URL (blank to reuse front camera):
```

Type the URL for the gate entry camera. Example:
```
http://192.168.0.200/cgi-bin/snapshot.cgi
```

If the gate entry camera is the same as the front weighbridge camera, press **Enter**
to reuse it.

---

**Question 8: Gate Exit camera URL (optional)**

```
Enter gate exit camera URL (blank to reuse front camera):
```

Type the URL for the gate exit camera. Example:
```
http://192.168.0.201/cgi-bin/snapshot.cgi
```

If there is no separate exit camera, press **Enter** to reuse the front camera.

---

**Question 9: Camera username**

```
Enter camera username (used for all cameras) [admin]:
```

Type the camera login username. Usually it is `admin`. Press **Enter** to accept.

---

**Question 10: Camera password**

```
Enter camera password:
```

Type the camera login password. Nothing will appear on screen as you type — this is
normal for passwords. Press **Enter** when done.

---

After you answer all questions, the script will:

1. Download NSSM (a tool to run Python as a Windows service) if not already present
2. Create the install folder
3. Copy `camera_agent.py` to the install folder
4. Install required Python packages (`requests`, `Pillow`, `websockets`)
5. Write the config file (`camera_config.json`)
6. Test the camera connections
7. Register the agent as a Windows service
8. Start the service

This takes about 1–3 minutes.

### Step 7 — Confirm the service is running

After the script finishes, confirm the service started successfully:

```powershell
Get-Service WeighbridgeCameraAgent
```

You should see:
```
Status   Name                       DisplayName
------   ----                       -----------
Running  WeighbridgeCameraAgent     Weighbridge Camera Agent
```

**If the status says `Stopped`**, check the log (Step 8 below).

### Step 8 — Check the log

```powershell
Get-Content C:\weighbridge-agent\logs\camera_agent.log -Tail 20
```

(Replace `C:\weighbridge-agent` with the install directory if you changed it.)

A successful startup looks like this:
```
[INFO] Cloud: https://acme-minerals.weighbridgesetu.com (status: ok)
[INFO] Event listener started (polling every 5s)
[INFO] Gate pass listener started (polling every 5s)
[INFO] Gate live feed (entry): http://192.168.0.200/cgi-bin/snapshot.cgi
[INFO] Gate live feed (exit): http://192.168.0.201/cgi-bin/snapshot.cgi
[INFO] Gate live feed pusher started (every 3s per camera)
[INFO] Status API: http://127.0.0.1:9003
[INFO] Running. Press Ctrl+C to stop.
```

If you see `[ERROR]` lines, go to the [Troubleshooting](#troubleshooting) section.

### Step 9 — Test camera snapshots

Run the built-in camera test:
```powershell
cd C:\weighbridge-agent
python camera_agent.py --test
```

Expected output:
```
Testing cameras...
  front: OK (87432 bytes) -> C:\weighbridge-agent\test_snapshots\test_front.jpg
  top:   OK (91208 bytes) -> C:\weighbridge-agent\test_snapshots\test_top.jpg
```

`OK` means the camera is reachable and returning images.
`FAILED` means the camera URL or credentials are wrong — check the config file.

> **Note:** The `--test` command only tests weighbridge cameras (front and top). It
> does NOT test gate cameras. To verify gate cameras, check the log file after the
> service starts — if gate camera URLs are configured correctly you will see
> `[INFO] Gate live feed pusher started`.

### Step 10 — Verify in the app

Open the Weighbridge app in a browser and check:

1. Go to **Operations → Gate Cameras → Live**
   - You should see live video from the entry and exit cameras within 5 seconds
   - The status indicator should show **● LIVE**

2. Record a test weight on a token
   - After the second weight is saved, go to the token detail
   - Within 10 seconds, camera snapshots should appear

Installation is complete.

---

## Part 2 — Adding Gate Cameras to an Existing Install

Use this when the client already has the Camera Agent installed (for weighbridge
snapshots) but the gate cameras haven't been configured yet.

### Step 1 — Open PowerShell as Administrator

See [Step 3 in Part 1](#step-3--open-powershell-as-administrator) for the exact steps.

### Step 2 — Navigate to the package folder

```powershell
cd C:\WeighbridgeSetup
```

### Step 3 — Find the existing install directory

Run this command to find where the agent is installed:
```powershell
sc.exe qc WeighbridgeCameraAgent
```

Look for the line that says `BINARY_PATH_NAME`. Example:
```
BINARY_PATH_NAME : C:\weighbridge-agent\nssm.EXE
```

The install directory is the folder in that path — in this example `C:\weighbridge-agent`.

### Step 4 — Run the Update script

```powershell
.\Update-CameraAgent.ps1 -InstallDir "C:\weighbridge-agent"
```

Replace `C:\weighbridge-agent` with the actual install directory found in Step 3.

The script will ask:

```
Enter gate entry camera URL (blank to keep existing):
```
Type the gate entry camera URL, then press Enter.

```
Enter gate exit camera URL (blank to keep existing):
```
Type the gate exit camera URL, then press Enter.

```
Enter camera username [admin]:
```
Type the camera username (usually `admin`), then press Enter.

```
Enter camera password:
```
Type the camera password, then press Enter.

The script will:
1. Stop the service
2. Update `camera_agent.py` with the latest version
3. Add the gate camera URLs to `camera_config.json`
4. Restart the service

### Step 5 — Verify gate cameras are working

```powershell
Get-Content C:\weighbridge-agent\logs\camera_agent.log -Tail 15
```

Look for this line — it confirms gate cameras are pushing live frames:
```
[INFO] Gate live feed pusher started (every 3s per camera)
```

Then check the app → Operations → Gate Cameras → Live.

---

## Part 3 — Troubleshooting

### Run the Diagnostic Script First

The `Diagnose-CameraAgent.ps1` script checks everything automatically. Run it first
before trying to fix anything manually:

```powershell
cd C:\WeighbridgeSetup
.\Diagnose-CameraAgent.ps1
```

It will check and report on:
- Whether the service is installed and running
- Whether `camera_agent.py` is the latest version
- The current configuration (cloud URL, tenant, camera URLs)
- Whether required Python packages are installed
- Whether the cloud server is reachable
- Live camera test results
- Last 25 lines of the agent log

Read the output carefully — it will tell you exactly what is wrong.

### Common Problems and Fixes

| Symptom | What to check | Fix |
|---|---|---|
| Service not found | Agent not installed | Run `Install-CameraAgent.ps1` |
| Service status: Stopped | Error at startup | Check log: `Get-Content C:\weighbridge-agent\logs\camera_agent.log -Tail 30` |
| Log shows: `Poll HTTP 403` | Wrong agent key | Get correct key from Platform Admin → edit tenant → Agent API Key. Update config (see below) |
| Log shows: `Cloud unreachable` | Wrong cloud URL, or no internet | Check `cloud_url` in config. Make sure PC has internet. Use tenant subdomain URL, NOT the main site URL |
| Log shows: `Camera front: FAILED` | Wrong camera URL or credentials | Open camera URL in browser on client PC to verify it works |
| Snapshots show "pending" in app | Agent not running, or wrong cloud URL | Check service status and log |
| Gate Camera Live shows "No Signal" | Gate camera URLs not set in config | Run `Update-CameraAgent.ps1` to add gate camera URLs |
| `--test` says FAILED for a camera | Camera URL wrong, or camera offline | Open the camera URL in a browser on the same PC |

### How to Manually Edit the Config File

If you need to correct a wrong URL or password after installation:

1. Find the install directory (see [Part 2 Step 3](#step-3--find-the-existing-install-directory))
2. Open Notepad:
   ```powershell
   notepad C:\weighbridge-agent\camera_config.json
   ```
3. Make your changes
4. Click **File → Save**
   - **Important:** When saving, make sure the encoding is **UTF-8** (not "UTF-8 with BOM").
     In Notepad, go to File → Save As → check the Encoding dropdown at the bottom.
5. Restart the service:
   ```powershell
   nssm restart WeighbridgeCameraAgent
   ```

### How to Restart the Service

```powershell
nssm restart WeighbridgeCameraAgent
```

If NSSM is not on PATH:
```powershell
Stop-Service WeighbridgeCameraAgent -Force
Start-Sleep -Seconds 3
Start-Service WeighbridgeCameraAgent
```

### How to Watch the Log in Real Time

Open a PowerShell window and run:
```powershell
Get-Content C:\weighbridge-agent\logs\camera_agent.log -Wait -Tail 20
```

Leave this window open. New log lines will appear as they happen. Press **Ctrl+C** to stop.

### Check the Agent Status API

While the service is running, open a browser on the client PC and go to:
```
http://localhost:9003/
```

You will see a JSON response like:
```json
{
  "service": "camera_agent",
  "status": "running",
  "timestamp": "2026-07-01T10:15:30",
  "capture_count": 47,
  "error_count": 2,
  "ws_port": 9004,
  "live_snapshot_urls": {
    "front": "http://localhost:9003/snapshot/front",
    "top": "http://localhost:9003/snapshot/top"
  }
}
```

You can also view a live snapshot from the weighbridge camera at:
```
http://localhost:9003/snapshot/front
http://localhost:9003/snapshot/top
```

---

## Part 4 — Service Management Reference

These commands are run in a **PowerShell** window (does not need to be Administrator
for status checks, but does for start/stop/restart).

| Action | Command |
|---|---|
| Check if service is running | `Get-Service WeighbridgeCameraAgent` |
| Start the service | `nssm start WeighbridgeCameraAgent` |
| Stop the service | `nssm stop WeighbridgeCameraAgent` |
| Restart the service | `nssm restart WeighbridgeCameraAgent` |
| Remove the service | `nssm remove WeighbridgeCameraAgent confirm` |
| View last 30 log lines | `Get-Content C:\weighbridge-agent\logs\camera_agent.log -Tail 30` |
| Watch log live | `Get-Content C:\weighbridge-agent\logs\camera_agent.log -Wait -Tail 20` |
| Find install directory | `sc.exe qc WeighbridgeCameraAgent` |
| Open config in Notepad | `notepad C:\weighbridge-agent\camera_config.json` |

---

## Part 5 — Config File Reference

The config file is at `<install-dir>\camera_config.json`.
Here is every field explained:

```json
{
  "cloud_url": "https://acme-minerals.weighbridgesetu.com",
  "tenant_slug": "acme-minerals",
  "agent_key": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",

  "poll_interval_sec": 5,
  "status_port": 9003,
  "ws_port": 9004,

  "cameras": {
    "front": {
      "label": "Front View",
      "url": "http://192.168.0.101/cgi-bin/snapshot.cgi",
      "username": "admin",
      "password": "camera123"
    },
    "top": {
      "label": "Top View",
      "url": "http://192.168.0.103/cgi-bin/snapshot.cgi",
      "username": "admin",
      "password": "camera123"
    }
  },

  "gate_cameras": {
    "entry": {
      "url": "http://192.168.0.200/cgi-bin/snapshot.cgi",
      "username": "admin",
      "password": "camera123"
    },
    "exit": {
      "url": "http://192.168.0.201/cgi-bin/snapshot.cgi",
      "username": "admin",
      "password": "camera123"
    }
  }
}
```

| Field | What it does |
|---|---|
| `cloud_url` | The tenant's cloud URL. **Must be the subdomain URL** e.g. `https://acme-minerals.weighbridgesetu.com` — NOT `https://weighbridgesetu.com` |
| `tenant_slug` | The tenant identifier from Platform Admin |
| `agent_key` | The API key from Platform Admin. Keep this secret. |
| `poll_interval_sec` | How often (in seconds) the agent checks for new weighbridge events. Default: 5 |
| `status_port` | Port for the local status API at `http://localhost:9003`. Default: 9003 |
| `ws_port` | Port for the live WebSocket stream. Default: 9004 |
| `cameras.front.url` | Snapshot URL for weighbridge front-view camera |
| `cameras.top.url` | Snapshot URL for weighbridge top-view camera (leave URL blank if no top camera) |
| `gate_cameras.entry.url` | Snapshot URL for gate entry camera. Leave blank to reuse `cameras.front` |
| `gate_cameras.exit.url` | Snapshot URL for gate exit camera. Leave blank to reuse `cameras.front` |

---

## Camera URL Formats by Brand

Test the URL in a browser on the client PC — you should see a still image.

| Camera Brand | Snapshot URL |
|---|---|
| CP Plus / Dahua | `http://IP/cgi-bin/snapshot.cgi` |
| Hikvision | `http://IP/Streaming/channels/1/picture` |
| AXIS | `http://IP/axis-cgi/jpg/image.cgi` |
| Generic ONVIF | `http://IP/onvif/snapshot` |
| Generic | `http://IP/snap.jpg` or `http://IP/snapshot.jpg` |

If the camera requires a username and password in the URL:
```
http://admin:password@192.168.0.101/cgi-bin/snapshot.cgi
```

---

## Getting the Agent API Key

If you need to get or re-copy the Agent API Key:

1. Open a browser and go to `https://weighbridgesetu.com`
2. Log in with the super-admin username and password
3. You will see the list of all clients
4. Click the client you are installing for
5. Click **Edit**
6. Find the **Agent API Key** field and copy it
7. Paste it into `camera_config.json` as the `agent_key` value

If the key has been regenerated (rotated), you must also update the config file on the
client PC and restart the service.

---

## Uninstall

To completely remove the agent from a client PC:

```powershell
cd C:\weighbridge-agent
python camera_agent.py --uninstall
```

Then delete the install folder:
```powershell
Remove-Item -Recurse -Force C:\weighbridge-agent
```
