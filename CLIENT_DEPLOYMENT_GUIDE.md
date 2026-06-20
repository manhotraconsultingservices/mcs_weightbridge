# WeighbridgeSetu - Client Agent Deployment Guide (SaaS Model)

> **Deployment Type:** SaaS - Backend & Frontend are hosted on the cloud
> **What this installs:** Only the local agents (Scale Agent + Camera Agent)
> **Audience:** Junior resource with basic Windows knowledge
> **Time Required:** 30-45 minutes
> **Last Updated:** 2026-04-15

---

## What Are Agents?

The WeighbridgeSetu web app runs in the cloud. But the **weighbridge hardware** (weight indicator + IP cameras) is at the client's site. The agents are small programs that run on a Windows PC at the site and bridge the local hardware to the cloud:

```
CLIENT SITE (This Guide)                         CLOUD (Already Running)
================================                  ==========================
                                                  
[Weight Indicator]                                [WeighbridgeSetu Backend]
    |  RS232/USB serial cable                        |
    v                                                |
[Scale Agent] ---internet--POST weight data-------->  |
    (scale_agent.py)                                 |----> [Web App]
                                                     |      (browser)
[IP Camera Front]                                    |
[IP Camera Top]                                      |
    |  LAN (HTTP snapshot)                           |
    v                                                |
[Camera Agent] ---internet--upload JPEG images----->  |
    (camera_agent.py)                                |
    |                                                
    |---ws://localhost:9004 (live video feed)-------> [Browser on site PC]
```

**You do NOT need to install:** PostgreSQL, Node.js, Frontend build, Backend API, or any server components. Those are all in the cloud.

---

## Table of Contents

1. [Pre-Requisites](#1-pre-requisites)
2. [Step 1 - Install Python](#step-1---install-python)
3. [Step 2 - Create Agent Folder & Copy Files](#step-2---create-agent-folder--copy-files)
4. [Step 3 - Install Python Dependencies](#step-3---install-python-dependencies)
5. [Step 4 - Get Tenant Credentials](#step-4---get-tenant-credentials)
6. [Step 5 - Find the Weighbridge COM Port](#step-5---find-the-weighbridge-com-port)
7. [Step 6 - Find Camera IP Addresses](#step-6---find-camera-ip-addresses)
8. [Step 7 - Configure Scale Agent](#step-7---configure-scale-agent)
9. [Step 8 - Configure Camera Agent](#step-8---configure-camera-agent)
10. [Step 9 - Test Scale Agent](#step-9---test-scale-agent)
11. [Step 10 - Test Camera Agent](#step-10---test-camera-agent)
12. [Step 11 - Download NSSM](#step-11---download-nssm)
13. [Step 12 - Install Scale Agent as Windows Service](#step-12---install-scale-agent-as-windows-service)
14. [Step 13 - Install Camera Agent as Windows Service](#step-13---install-camera-agent-as-windows-service)
15. [Step 14 - Configure Firewall](#step-14---configure-firewall)
16. [Step 15 - Final Verification](#step-15---final-verification)
17. [Troubleshooting](#troubleshooting)
18. [Service Management Commands](#service-management-commands)
19. [Quick Reference Card](#quick-reference-card)

---

## 1. Pre-Requisites

### What You Need

| Item | Details |
|------|---------|
| **Windows** | Windows 10/11 (64-bit) |
| **RAM** | 4 GB minimum |
| **Internet** | Required (agents communicate with cloud) |
| **Admin Access** | Must run PowerShell as Administrator |
| **USB/Network** | Deployment files from vendor |

### What You Need From the Client Site

| Item | How to Get It |
|------|---------------|
| **Weighbridge indicator cable** | RS232 serial cable or USB-to-serial adapter already plugged into the PC |
| **Camera IP addresses** | Ask the CCTV technician or check the camera's sticker/manual |
| **Camera login** | Username & password for the IP cameras (ask CCTV person) |
| **Tenant Slug** | Provided by vendor (e.g., `sharma-crushers`) |
| **Agent API Key** | Provided by vendor (UUID like `09911e73-120f-...`) |

### What You Need From the Vendor (Before Going to Site)

Ask the senior developer for these 2 values:
1. **Tenant Slug** - the client's identifier in the system
2. **Agent API Key** - the authentication key for the agents

### Important Notes
- **ALWAYS run PowerShell as Administrator** (right-click > "Run as Administrator")
- **Copy-paste** commands exactly as shown
- If you see **red error text**, STOP and take a screenshot
- The agents need internet to work - verify the PC has internet before starting

---

## Step 1 - Install Python

### 1.1 Check if Python is Already Installed

Open **PowerShell as Administrator** and run:

```powershell
python --version
```

If you see `Python 3.11.x` or `Python 3.12.x`, **skip to Step 2**. If you see an error, continue below.

### 1.2 Download Python

1. Open browser: **https://www.python.org/downloads/release/python-3119/**
2. Scroll to **"Files"** section
3. Click **"Windows installer (64-bit)"**

### 1.3 Install Python

1. Double-click the downloaded file
2. **CHECK BOTH BOXES:**
   - [x] **"Install launcher for all users"**
   - [x] **"Add python.exe to PATH"** <-- CRITICAL!
3. Click **"Install Now"** (default settings are fine)
4. Wait for installation
5. Click **Close**

### 1.4 Verify

**Close PowerShell and open a new one as Administrator:**

```powershell
python --version
```

**Expected:** `Python 3.11.9`

```powershell
pip --version
```

**Expected:** `pip 24.x.x ...`

> **If "python not found":** Restart the computer, then try again.

---

## Step 2 - Create Agent Folder & Copy Files

### 2.1 Create the Folder

```powershell
New-Item -ItemType Directory -Path "C:\weighbridge-agent" -Force
New-Item -ItemType Directory -Path "C:\weighbridge-agent\logs" -Force
```

### 2.2 Copy Agent Files from Deployment Package

```powershell
# Replace E:\agents\ with the actual path on USB/network share
Copy-Item "E:\agents\scale_agent.py" "C:\weighbridge-agent\" -Force
Copy-Item "E:\agents\camera_agent.py" "C:\weighbridge-agent\" -Force
Copy-Item "E:\agents\scan_cameras.py" "C:\weighbridge-agent\" -Force
Copy-Item "E:\agents\requirements.txt" "C:\weighbridge-agent\" -Force
Copy-Item "E:\agents\scale_config.example.json" "C:\weighbridge-agent\" -Force
Copy-Item "E:\agents\camera_config.example.json" "C:\weighbridge-agent\" -Force
```

### 2.3 Verify Files

```powershell
Get-ChildItem "C:\weighbridge-agent\*.py" | Select-Object Name
```

**Expected output:**
```
Name
----
camera_agent.py
scale_agent.py
scan_cameras.py
```

---

## Step 3 - Install Python Dependencies

```powershell
pip install -r C:\weighbridge-agent\requirements.txt
```

**Expected output (last line):** `Successfully installed pyserial-3.5 requests-... urllib3-... websockets-...`

### Verify:

```powershell
python -c "import serial; print('pyserial OK')"
python -c "import requests; print('requests OK')"
python -c "import websockets; print('websockets OK')"
```

All three should print "OK".

> **If running as SYSTEM user later fails to find packages**, install to system-wide location:
> ```powershell
> python -m pip install -r C:\weighbridge-agent\requirements.txt --target "C:\Program Files\Python311\Lib\site-packages"
> ```

---

## Step 4 - Get Tenant Credentials

You need **two values** from the vendor/senior developer:

| Value | Example | Where to Get |
|-------|---------|-------------|
| **Tenant Slug** | `sharma-crushers` | Vendor provides this |
| **Agent API Key** | `09911e73-120f-4ab9-9ef3-47f52604864f` | Vendor provides this |

**Write these down.** You'll enter them during configuration in Steps 7 and 8.

> The vendor generates the Agent API Key from the admin panel:
> Cloud Admin > Tenants > Select Tenant > Copy "Agent API Key"

---

## Step 5 - Find the Weighbridge COM Port

The weight indicator connects to the PC via a serial cable (RS232 or USB-to-serial adapter).

### 5.1 Check Which COM Port is Connected

```powershell
# List all COM ports on this PC
[System.IO.Ports.SerialPort]::GetPortNames()
```

**Example output:**
```
COM3
COM7
```

### 5.2 Identify the Correct Port

If multiple ports appear, check **Device Manager:**

1. Right-click **Start** button > **Device Manager**
2. Expand **"Ports (COM & LPT)"**
3. Look for something like:
   - "USB-SERIAL CH340 (COM3)" -- this is the weighbridge
   - "Communications Port (COM1)" -- this is usually built-in, ignore it
4. Note the COM port number (e.g., **COM3**)

> **If no COM ports appear:**
> - Check if the serial cable is plugged in
> - If using USB-to-serial adapter, install the driver (usually CH340 or PL2303)
> - After installing driver, re-run the command

### 5.3 Find the Baud Rate

Ask the weighbridge technician for the baud rate. Common values:

| Indicator Brand | Typical Baud Rate |
|----------------|-------------------|
| Essae / Eagle | 9600 |
| Avery Weigh-Tronix | 9600 |
| Contech | 9600 or 2400 |
| Sansui | 9600 |
| Vibra / Shinko | 9600 or 4800 |

**If not sure, try 9600** (most common).

---

## Step 6 - Find Camera IP Addresses

### 6.1 Option A: Ask the CCTV Technician

The easiest way. Ask for:
- Front camera IP address (e.g., `192.168.1.101`)
- Top camera IP address (e.g., `192.168.1.103`)
- Camera login username and password

### 6.2 Option B: Use the Camera Scanner

```powershell
cd C:\weighbridge-agent
python scan_cameras.py
```

This scans the local network for IP cameras. Look for entries showing ports 80 or 554 open.

### 6.3 Camera Snapshot URL Formats

Once you have the IP address, the snapshot URL depends on the camera brand:

| Camera Brand | Snapshot URL |
|-------------|-------------|
| **CP Plus / Dahua** | `http://<IP>/cgi-bin/snapshot.cgi` |
| **Hikvision** | `http://<IP>/Streaming/channels/1/picture` |
| **Generic** | `http://<IP>/snap.jpg` |

**Example:** If front camera IP is `192.168.1.101` and it's CP Plus:
- Snapshot URL: `http://192.168.1.101/cgi-bin/snapshot.cgi`

### 6.4 Test Camera URL in Browser

Open browser and type the snapshot URL. If it asks for username/password, enter the camera credentials. If you see a JPEG image, the URL is correct.

---

## Step 7 - Configure Scale Agent

### 7.1 Option A: Interactive Setup (Recommended)

```powershell
cd C:\weighbridge-agent
python scale_agent.py --setup
```

The wizard will ask you for:
- Cloud URL: press Enter for default (`https://weighbridgesetu.com`)
- Tenant Slug: enter the value from Step 4 (e.g., `sharma-crushers`)
- Agent API Key: enter the value from Step 4
- COM Port: enter from Step 5 (e.g., `COM3`)
- Baud Rate: enter from Step 5 (e.g., `9600`)
- Other settings: press Enter for defaults

### 7.2 Option B: Manual Config File

```powershell
Copy-Item "C:\weighbridge-agent\scale_config.example.json" "C:\weighbridge-agent\scale_config.json"
notepad C:\weighbridge-agent\scale_config.json
```

Edit the file with your values:

```json
{
  "cloud_url": "https://weighbridgesetu.com",
  "tenant_slug": "YOUR-TENANT-SLUG",
  "agent_key": "YOUR-AGENT-API-KEY",
  "port": "COM3",
  "baud_rate": 9600,
  "data_bits": 8,
  "stop_bits": 1,
  "parity": "N",
  "push_interval_ms": 500,
  "status_port": 9002
}
```

Replace:
- `YOUR-TENANT-SLUG` with the tenant slug from Step 4
- `YOUR-AGENT-API-KEY` with the API key from Step 4
- `COM3` with the actual COM port from Step 5
- `9600` with the actual baud rate from Step 5

Save (**Ctrl+S**) and close Notepad.

---

## Step 8 - Configure Camera Agent

### 8.1 Option A: Interactive Setup (Recommended)

```powershell
cd C:\weighbridge-agent
python camera_agent.py --setup
```

The wizard will ask you for:
- Cloud URL: press Enter for default
- Tenant Slug: enter from Step 4
- Agent API Key: enter from Step 4
- Front camera URL: enter from Step 6 (e.g., `http://192.168.1.101/cgi-bin/snapshot.cgi`)
- Front camera username: enter camera login (e.g., `admin`)
- Front camera password: enter camera password
- Top camera URL: enter from Step 6
- Top camera username/password: same as front (usually)
- Other settings: press Enter for defaults

### 8.2 Option B: Manual Config File

```powershell
Copy-Item "C:\weighbridge-agent\camera_config.example.json" "C:\weighbridge-agent\camera_config.json"
notepad C:\weighbridge-agent\camera_config.json
```

Edit with your values:

```json
{
  "cloud_url": "https://weighbridgesetu.com",
  "tenant_slug": "YOUR-TENANT-SLUG",
  "agent_key": "YOUR-AGENT-API-KEY",
  "poll_interval_sec": 5,
  "status_port": 9003,
  "ws_port": 9004,
  "cameras": {
    "front": {
      "label": "Front View",
      "url": "http://192.168.1.101/cgi-bin/snapshot.cgi",
      "username": "admin",
      "password": "CAMERA-PASSWORD"
    },
    "top": {
      "label": "Top View",
      "url": "http://192.168.1.103/cgi-bin/snapshot.cgi",
      "username": "admin",
      "password": "CAMERA-PASSWORD"
    }
  }
}
```

Replace all placeholder values. Save and close.

---

## Step 9 - Test Scale Agent

```powershell
cd C:\weighbridge-agent
python scale_agent.py
```

**What to look for:**

```
2026-04-15 10:30:01 [INFO] Scale Agent v1.0 starting...
2026-04-15 10:30:01 [INFO] Connecting to COM3 at 9600 baud...
2026-04-15 10:30:02 [INFO] Serial port connected
2026-04-15 10:30:02 [INFO] Weight reading: 0.00 t
2026-04-15 10:30:03 [INFO] Pushed to cloud: 200 OK
```

- If you see **"Serial port connected"** and weight readings, it's working
- If the indicator shows a weight, you should see it in the agent output
- Press **Ctrl+C** to stop

> **Common errors:**
> - `"Could not open COM3"` -- wrong COM port or cable not connected
> - `"Connection refused"` -- no internet or wrong cloud URL
> - `"401 Unauthorized"` -- wrong tenant_slug or agent_key

---

## Step 10 - Test Camera Agent

### 10.1 Test Snapshot Capture

```powershell
cd C:\weighbridge-agent
python camera_agent.py --test
```

**What to look for:**

```
Testing camera: front (http://192.168.1.101/cgi-bin/snapshot.cgi)
  Captured 45231 bytes (JPEG OK)
  Saved to: test_snapshots/front_20260415_103015.jpg

Testing camera: top (http://192.168.1.103/cgi-bin/snapshot.cgi)
  Captured 38102 bytes (JPEG OK)
  Saved to: test_snapshots/top_20260415_103016.jpg

All cameras OK!
```

- Check the `test_snapshots` folder - you should see JPEG images
- Open them to verify they show the correct view (front/top of weighbridge)

### 10.2 Test Full Agent

```powershell
python camera_agent.py
```

**What to look for:**

```
2026-04-15 10:31:01 [INFO] Camera Agent v1.0 starting...
2026-04-15 10:31:01 [INFO] Status API on port 9003
2026-04-15 10:31:01 [INFO] WebSocket live feed on port 9004
2026-04-15 10:31:02 [INFO] Polling cloud for pending events...
2026-04-15 10:31:02 [INFO] No pending events
```

Press **Ctrl+C** to stop.

> **Common errors:**
> - `"401 Unauthorized"` on camera -- wrong camera username/password
> - `"Connection timed out"` on camera -- wrong camera IP or camera is off
> - `"Connection refused"` to cloud -- no internet connection

---

## Step 11 - Download NSSM

NSSM makes the agents run as Windows services that start automatically when the PC boots.

### 11.1 Download

1. Open browser: **https://nssm.cc/download**
2. Click **"nssm 2.24 (2014-08-31)"** to download the zip
3. If site is slow: **https://nssm.cc/release/nssm-2.24.zip**

### 11.2 Extract

1. Go to **Downloads** folder
2. Right-click `nssm-2.24.zip` > **Extract All** > **Extract**
3. Open: `nssm-2.24` > `win64`
4. **Copy** `nssm.exe`
5. **Paste** into `C:\weighbridge-agent\`

### 11.3 Verify

```powershell
C:\weighbridge-agent\nssm.exe version
```

**Expected:** `NSSM 64-bit 2.24`

### 11.4 Add to PATH

```powershell
$p = "C:\weighbridge-agent"
$cur = [Environment]::GetEnvironmentVariable("PATH", "Machine")
if ($cur -notlike "*$p*") {
    [Environment]::SetEnvironmentVariable("PATH", "$cur;$p", "Machine")
    Write-Host "Added to PATH. Restart PowerShell." -ForegroundColor Green
}
```

**Close and reopen PowerShell as Administrator.**

```powershell
nssm version
```

**Expected:** `NSSM 64-bit 2.24`

---

## Step 12 - Install Scale Agent as Windows Service

Run each command one by one:

```powershell
# 12.1 - Find Python path
$pythonPath = (Get-Command python).Source
Write-Host "Python at: $pythonPath" -ForegroundColor Cyan
```

Note the path shown (e.g., `C:\Program Files\Python311\python.exe`).

```powershell
# 12.2 - Install service
nssm install WeighbridgeScaleAgent "$pythonPath"
```

```powershell
# 12.3 - Set the script to run
nssm set WeighbridgeScaleAgent AppParameters "C:\weighbridge-agent\scale_agent.py"
```

```powershell
# 12.4 - Set working directory
nssm set WeighbridgeScaleAgent AppDirectory "C:\weighbridge-agent"
```

```powershell
# 12.5 - Display name & description
nssm set WeighbridgeScaleAgent DisplayName "WeighbridgeSetu Scale Agent"
nssm set WeighbridgeScaleAgent Description "Reads weight from serial port and pushes to cloud"
```

```powershell
# 12.6 - Auto-start on boot
nssm set WeighbridgeScaleAgent Start SERVICE_AUTO_START
```

```powershell
# 12.7 - Auto-restart on crash (wait 5 seconds)
nssm set WeighbridgeScaleAgent AppExit Default Restart
nssm set WeighbridgeScaleAgent AppRestartDelay 5000
```

```powershell
# 12.8 - Log files with rotation
nssm set WeighbridgeScaleAgent AppStdout "C:\weighbridge-agent\logs\scale_service_stdout.log"
nssm set WeighbridgeScaleAgent AppStderr "C:\weighbridge-agent\logs\scale_service_stderr.log"
nssm set WeighbridgeScaleAgent AppRotateFiles 1
nssm set WeighbridgeScaleAgent AppRotateBytes 10485760
```

```powershell
# 12.9 - Start the service
nssm start WeighbridgeScaleAgent
```

**Expected:** `WeighbridgeScaleAgent: START: The operation completed successfully.`

### 12.10 - Verify

```powershell
nssm status WeighbridgeScaleAgent
```

**Expected:** `SERVICE_RUNNING`

```powershell
# Check status API
Invoke-RestMethod http://localhost:9002 | ConvertTo-Json
```

Should show JSON with `scale_connected`, `last_weight_kg`, etc.

---

## Step 13 - Install Camera Agent as Windows Service

```powershell
# 13.1 - Find Python path (if not already set)
$pythonPath = (Get-Command python).Source
```

```powershell
# 13.2 - Install service
nssm install WeighbridgeCameraAgent "$pythonPath"
```

```powershell
# 13.3 - Set the script to run
nssm set WeighbridgeCameraAgent AppParameters "C:\weighbridge-agent\camera_agent.py"
```

```powershell
# 13.4 - Set working directory
nssm set WeighbridgeCameraAgent AppDirectory "C:\weighbridge-agent"
```

```powershell
# 13.5 - Display name & description
nssm set WeighbridgeCameraAgent DisplayName "WeighbridgeSetu Camera Agent"
nssm set WeighbridgeCameraAgent Description "Captures camera snapshots and uploads to cloud"
```

```powershell
# 13.6 - Auto-start on boot
nssm set WeighbridgeCameraAgent Start SERVICE_AUTO_START
```

```powershell
# 13.7 - Auto-restart on crash (wait 5 seconds)
nssm set WeighbridgeCameraAgent AppExit Default Restart
nssm set WeighbridgeCameraAgent AppRestartDelay 5000
```

```powershell
# 13.8 - Log files with rotation
nssm set WeighbridgeCameraAgent AppStdout "C:\weighbridge-agent\logs\camera_service_stdout.log"
nssm set WeighbridgeCameraAgent AppStderr "C:\weighbridge-agent\logs\camera_service_stderr.log"
nssm set WeighbridgeCameraAgent AppRotateFiles 1
nssm set WeighbridgeCameraAgent AppRotateBytes 10485760
```

```powershell
# 13.9 - Start the service
nssm start WeighbridgeCameraAgent
```

**Expected:** `WeighbridgeCameraAgent: START: The operation completed successfully.`

### 13.10 - Verify

```powershell
nssm status WeighbridgeCameraAgent
```

**Expected:** `SERVICE_RUNNING`

```powershell
# Check status API
Invoke-RestMethod http://localhost:9003 | ConvertTo-Json
```

Should show JSON with camera status information.

---

## Step 14 - Configure Firewall

Open the agent ports for local access (needed for live camera feed in browser):

```powershell
# Scale Agent status port
New-NetFirewallRule -DisplayName "WeighbridgeSetu Scale Agent (9002)" `
    -Direction Inbound -Protocol TCP -LocalPort 9002 `
    -Action Allow -Profile Domain,Private `
    -Description "Scale Agent status API"

# Camera Agent status + snapshot proxy
New-NetFirewallRule -DisplayName "WeighbridgeSetu Camera Agent (9003)" `
    -Direction Inbound -Protocol TCP -LocalPort 9003 `
    -Action Allow -Profile Domain,Private `
    -Description "Camera Agent status and snapshot proxy"

# Camera Agent live WebSocket feed
New-NetFirewallRule -DisplayName "WeighbridgeSetu Camera Live Feed (9004)" `
    -Direction Inbound -Protocol TCP -LocalPort 9004 `
    -Action Allow -Profile Domain,Private `
    -Description "Camera Agent live video WebSocket"
```

---

## Step 15 - Final Verification

### 15.1 Check Both Services

```powershell
Write-Host "`n=== Agent Services ===" -ForegroundColor Cyan
Write-Host "Scale Agent:  " -NoNewline; nssm status WeighbridgeScaleAgent
Write-Host "Camera Agent: " -NoNewline; nssm status WeighbridgeCameraAgent
```

Both should show `SERVICE_RUNNING`.

### 15.2 Check All Ports

```powershell
Write-Host "`n=== Port Check ===" -ForegroundColor Cyan
@(9002, 9003, 9004) | ForEach-Object {
    $result = Test-NetConnection localhost -Port $_ -WarningAction SilentlyContinue
    Write-Host "Port $_`: $(if($result.TcpTestSucceeded){'OPEN (OK)'}else{'CLOSED (PROBLEM)'})"
}
```

All three should show **OPEN (OK)**.

### 15.3 Test in the Web App

1. Open browser on the same PC
2. Go to the WeighbridgeSetu web app (e.g., `https://weighbridgesetu.com`)
3. Login with the client's credentials
4. Go to **Tokens** page
5. The weight reading should show in real-time (if indicator has a weight)
6. Create a test token with a weighment - camera snapshots should appear

### 15.4 Check Agent Logs

```powershell
# Scale Agent logs
Write-Host "`n=== Scale Agent Log (last 10 lines) ===" -ForegroundColor Cyan
Get-Content "C:\weighbridge-agent\logs\scale_agent.log" -Tail 10

# Camera Agent logs
Write-Host "`n=== Camera Agent Log (last 10 lines) ===" -ForegroundColor Cyan
Get-Content "C:\weighbridge-agent\logs\camera_agent.log" -Tail 10
```

---

## Troubleshooting

### Scale Agent Issues

| Problem | Fix |
|---------|-----|
| `"Could not open COM3"` | Wrong port number. Run `[System.IO.Ports.SerialPort]::GetPortNames()` to find correct port. Update `scale_config.json`. |
| `"No data from serial port"` | Wrong baud rate. Try 9600, 2400, 4800. Ask weighbridge technician. |
| `"Connection refused"` to cloud | PC has no internet. Check with `ping google.com`. |
| `"401 Unauthorized"` from cloud | Wrong `tenant_slug` or `agent_key`. Get correct values from vendor. |
| Weight shows 0.00 | Indicator may be off or in standby. Turn on the weighbridge indicator. |
| Service stops after PC restart | Check `nssm status WeighbridgeScaleAgent`. If not running: `nssm start WeighbridgeScaleAgent` |

### Camera Agent Issues

| Problem | Fix |
|---------|-----|
| `"401 Unauthorized"` on camera | Wrong camera username/password. Update `camera_config.json`. |
| `"Connection timed out"` on camera | Camera is off or wrong IP. Ping the camera: `ping 192.168.1.101` |
| `"Connection refused"` on camera | Camera is on different network or firewall blocking. Check with CCTV technician. |
| Live feed not showing in browser | Check port 9004 is open: `Test-NetConnection localhost -Port 9004` |
| Snapshots blurry or dark | Camera issue, not agent issue. Adjust camera settings via camera's web interface. |
| `"websockets not installed"` | Run: `pip install websockets` |

### General Issues

**Check service logs:**
```powershell
# Scale service logs
Get-Content "C:\weighbridge-agent\logs\scale_service_stderr.log" -Tail 30

# Camera service logs
Get-Content "C:\weighbridge-agent\logs\camera_service_stderr.log" -Tail 30

# Application logs
Get-Content "C:\weighbridge-agent\logs\scale_agent.log" -Tail 30
Get-Content "C:\weighbridge-agent\logs\camera_agent.log" -Tail 30
```

**Restart services:**
```powershell
nssm restart WeighbridgeScaleAgent
nssm restart WeighbridgeCameraAgent
```

**Run agent manually to see errors:**
```powershell
# Stop the service first
nssm stop WeighbridgeScaleAgent

# Run manually to see full error output
cd C:\weighbridge-agent
python scale_agent.py

# After debugging, start service again
nssm start WeighbridgeScaleAgent
```

---

## Service Management Commands

```powershell
# ============ STATUS ============
nssm status WeighbridgeScaleAgent
nssm status WeighbridgeCameraAgent

# ============ START ============
nssm start WeighbridgeScaleAgent
nssm start WeighbridgeCameraAgent

# ============ STOP ============
nssm stop WeighbridgeScaleAgent
nssm stop WeighbridgeCameraAgent

# ============ RESTART ============
nssm restart WeighbridgeScaleAgent
nssm restart WeighbridgeCameraAgent

# ============ VIEW LOGS ============
Get-Content "C:\weighbridge-agent\logs\scale_agent.log" -Tail 30
Get-Content "C:\weighbridge-agent\logs\camera_agent.log" -Tail 30

# ============ EDIT SERVICE (opens GUI) ============
nssm edit WeighbridgeScaleAgent
nssm edit WeighbridgeCameraAgent

# ============ REMOVE SERVICE ============
nssm stop WeighbridgeScaleAgent
nssm remove WeighbridgeScaleAgent confirm

nssm stop WeighbridgeCameraAgent
nssm remove WeighbridgeCameraAgent confirm

# ============ CHECK ALL SERVICES ============
Get-Service "Weighbridge*" | Format-Table Name, Status, StartType
```

### Updating Agents (When Vendor Sends New Version)

```powershell
# 1. Stop services
nssm stop WeighbridgeScaleAgent
nssm stop WeighbridgeCameraAgent

# 2. Copy new files (DO NOT overwrite config files!)
Copy-Item "E:\update\scale_agent.py" "C:\weighbridge-agent\" -Force
Copy-Item "E:\update\camera_agent.py" "C:\weighbridge-agent\" -Force

# 3. Update dependencies (if requirements changed)
pip install -r C:\weighbridge-agent\requirements.txt

# 4. Restart services
nssm start WeighbridgeScaleAgent
nssm start WeighbridgeCameraAgent

# 5. Verify
nssm status WeighbridgeScaleAgent
nssm status WeighbridgeCameraAgent
```

> **IMPORTANT:** Do NOT copy `scale_config.json` or `camera_config.json` during updates. Those contain this client's specific settings and should never be overwritten.

---

## Quick Reference Card

Print this and keep it at the client site.

```
+--------------------------------------------------------------+
|        WeighbridgeSetu Agents - Quick Reference               |
+--------------------------------------------------------------+
|                                                               |
|  Web App:  https://weighbridgesetu.com                        |
|  (Open in browser - no local install needed)                  |
|                                                               |
|  Agent Files:   C:\weighbridge-agent\                         |
|  Agent Logs:    C:\weighbridge-agent\logs\                    |
|  NSSM:          C:\weighbridge-agent\nssm.exe                 |
|                                                               |
|  Services:                                                    |
|    WeighbridgeScaleAgent   (port 9002)                        |
|    WeighbridgeCameraAgent  (port 9003 + 9004)                 |
|                                                               |
|  Commands (PowerShell as Admin):                              |
|    nssm status WeighbridgeScaleAgent                          |
|    nssm status WeighbridgeCameraAgent                         |
|    nssm restart WeighbridgeScaleAgent                         |
|    nssm restart WeighbridgeCameraAgent                        |
|                                                               |
|  View Logs:                                                   |
|    Get-Content C:\weighbridge-agent\logs\scale_agent.log      |
|          -Tail 20                                             |
|    Get-Content C:\weighbridge-agent\logs\camera_agent.log     |
|          -Tail 20                                             |
|                                                               |
|  Tenant:     ___________________________                      |
|  COM Port:   ___________________________                      |
|  Front Cam:  ___________________________                      |
|  Top Cam:    ___________________________                      |
|  Vendor:     ___________________________                      |
|  Install Date: _________________________                      |
|                                                               |
+--------------------------------------------------------------+
```

---

## Installation Checklist

```
[ ] Step 1  - Python installed (python --version works)
[ ] Step 2  - Agent files copied to C:\weighbridge-agent\
[ ] Step 3  - pip dependencies installed (pyserial, requests, websockets)
[ ] Step 4  - Got tenant_slug and agent_key from vendor
[ ] Step 5  - Identified COM port (e.g., COM3) and baud rate
[ ] Step 6  - Got camera IPs, URLs, and login credentials
[ ] Step 7  - scale_config.json created with correct values
[ ] Step 8  - camera_config.json created with correct values
[ ] Step 9  - Scale agent tested manually (shows weight readings)
[ ] Step 10 - Camera agent tested (--test shows captured JPEGs)
[ ] Step 11 - NSSM downloaded to C:\weighbridge-agent\nssm.exe
[ ] Step 12 - WeighbridgeScaleAgent service created (SERVICE_RUNNING)
[ ] Step 13 - WeighbridgeCameraAgent service created (SERVICE_RUNNING)
[ ] Step 14 - Firewall rules created (ports 9002, 9003, 9004)
[ ] Step 15 - Weight shows in web app
[ ] Step 15 - Camera snapshots appear after weighment

Deployment Date: _______________
Deployed By:     _______________
Client Name:     _______________
PC Name/IP:      _______________
COM Port:        _______________
Front Camera IP: _______________
Top Camera IP:   _______________
```

---

*Document Version: 2.0 | Created: 2026-04-15 | WeighbridgeSetu by Manhotra Consulting Services*
