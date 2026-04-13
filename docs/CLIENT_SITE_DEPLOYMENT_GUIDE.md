# Weighbridge Client Site Deployment Guide

**Version:** 1.0 | **Last Updated:** April 2026
**Author:** Manhotra Consulting Services
**For:** Field Technicians & Support Engineers

---

## Table of Contents

1. [Pre-Visit Preparation](#1-pre-visit-preparation)
2. [System Requirements](#2-system-requirements)
3. [Phase 1 — Machine Verification (15 min)](#3-phase-1--machine-verification)
4. [Phase 2 — Software Prerequisites (30 min)](#4-phase-2--software-prerequisites)
5. [Phase 3 — Application Installation (20 min)](#5-phase-3--application-installation)
6. [Phase 4 — Weighbridge Scale Setup (30 min)](#6-phase-4--weighbridge-scale-setup)
7. [Phase 5 — IP Camera Setup (20 min)](#7-phase-5--ip-camera-setup)
8. [Phase 6 — Application Configuration (20 min)](#8-phase-6--application-configuration)
9. [Phase 7 — Final Verification Checklist](#9-phase-7--final-verification-checklist)
10. [Troubleshooting Guide](#10-troubleshooting-guide)
11. [Common Scale Brands & Settings](#11-common-scale-brands--settings)
12. [Common Camera Brands & URLs](#12-common-camera-brands--urls)
13. [Support Contact](#13-support-contact)

---

## 1. Pre-Visit Preparation

### Items to Carry

| Item | Purpose | Qty |
|------|---------|-----|
| USB Drive (8GB+) with installer files | Application installation | 1 |
| USB Security Key (with `.weighbridge_key`) | USB Guard authentication | 1 |
| RS232 to USB Converter Cable (CH340/FTDI) | Connect weighbridge indicator to PC | 1 |
| RS232 DB9 Serial Cable (Male-Female) | Connect indicator to converter | 1 |
| Ethernet Cable (CAT6, 5m) | Camera network connection | 2 |
| Network Switch (5-port) | If client needs more LAN ports | 1 |
| Windows 10 Pro USB installer | Emergency OS reinstall | 1 |
| Docker Desktop offline installer | Avoid slow downloads at site | 1 |

### Information to Collect from Client (Before Visit)

| Info | Example | Why Needed |
|------|---------|------------|
| Company Name | Ziya Ore Minerals | For software setup |
| GSTIN | 27AADCZ1234M1Z5 | For GST invoicing |
| PAN | AADCZ1234M | For invoicing |
| Company Address | Village Mahur, Dist Nanded | For invoice header |
| Weighbridge Scale Brand & Model | Essae ET-600 / Leo+ BW-100 | For protocol selection |
| Scale Indicator Baud Rate | Usually 9600 | Serial port config |
| Number of Cameras | Usually 2 (front + top) | Camera config |
| Camera Brand & Model | Hikvision DS-2CD1043 | For snapshot URL format |
| Camera IP Addresses | 192.168.1.13, 192.168.1.14 | Network config |
| Camera Username/Password | admin / admin123 | Authentication |
| Client PC hostname | `WEIGHBRIDGE-PC` | For license generation |
| Internet availability | Yes/No | For cloud sync |
| Tenant slug (from platform admin) | `ziya-ore-minerals` | Pre-created on cloud |

### Pre-Create Tenant on Cloud

Before visiting the client, create their tenant on the cloud platform:

1. Login to **https://weighbridgesetu.com/platform**
2. Click **"Onboard New Company"**
3. Fill in:
   - Slug: `ziya-ore-minerals` (lowercase, hyphens only, no spaces/underscores)
   - Display Name: `Ziya Ore Minerals`
   - Company Name: `Ziya Ore Minerals Pvt Ltd`
   - Admin Username: `admin`
   - Admin Password: (strong password, note it down)
   - AMC Start: today's date
   - AMC Expiry: 1 year from today
4. Note the credentials — you'll give these to the client

---

## 2. System Requirements

### Minimum Hardware

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| OS | Windows 10 Pro 64-bit | Windows 10/11 Pro 64-bit |
| RAM | 4 GB | 8 GB |
| Disk | 5 GB free on C: | 20 GB free |
| CPU | Intel i3 / AMD Ryzen 3 | Intel i5 / AMD Ryzen 5 |
| Display | 1366x768 | 1920x1080 |
| Ports | 1 USB (for scale) | 2 USB |
| Network | LAN (for cameras) | LAN + Internet |

### Network Requirements

| Device | IP Range | Port |
|--------|----------|------|
| PC (this software) | 192.168.1.x | 9000 (web), 9001 (API) |
| Camera 1 (Front) | 192.168.1.13 | 80/554 |
| Camera 2 (Top) | 192.168.1.14 | 80/554 |
| Weighbridge Indicator | COM port (USB) | Serial |

---

## 3. Phase 1 — Machine Verification

**Time: 15 minutes**

Open **PowerShell as Administrator** and run each command:

### Check Windows Version
```powershell
(Get-CimInstance Win32_OperatingSystem).Caption
# Must show: "Microsoft Windows 10 Pro" or "Microsoft Windows 11 Pro"
# Windows Home edition will NOT work (no Hyper-V for Docker)
```

### Check RAM
```powershell
[math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)
# Must show 4.0 or higher
```

### Check Disk Space
```powershell
[math]::Round((Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'").FreeSpace / 1GB, 1)
# Must show 5.0 or higher
```

### Check 64-bit
```powershell
[Environment]::Is64BitOperatingSystem
# Must show: True
```

### Check COM Ports (Weighbridge)
```powershell
Get-CimInstance Win32_PnPEntity | Where-Object { $_.Name -match 'COM\d' } | Select-Object Name, Status
# Should show USB-Serial adapter (e.g., "USB-SERIAL CH340 (COM3)")
# If nothing shows, plug in the RS232-USB converter cable
```

### Get Hostname (for License)
```powershell
hostname
# Note this down — needed for license generation
```

**If any check fails, STOP and resolve before proceeding.**

---

## 4. Phase 2 — Software Prerequisites

**Time: 30 minutes**

### 4.1 Install Docker Desktop

> **CRITICAL:** Docker Desktop requires Windows 10 Pro with Hyper-V or WSL2.

1. Copy `Docker Desktop Installer.exe` from USB drive to Desktop
2. Double-click to install
3. During install, select: **"Use WSL 2 instead of Hyper-V"**
4. Restart PC when prompted
5. After restart, Docker Desktop will start automatically
6. Wait for "Docker Desktop is running" notification (green icon in system tray)

**Verify Docker:**
```powershell
docker --version
# Should show: Docker version 26.x or higher

docker ps
# Should show empty table (no containers yet) — NOT an error
```

> **If Docker won't start:** Check that Virtualization is enabled in BIOS (VT-x/AMD-V). Enter BIOS → Advanced → CPU Configuration → Intel Virtualization Technology → Enabled.

### 4.2 Install CH340 USB Driver (if needed)

Most Windows 10 PCs auto-detect CH340 USB-Serial adapters. If not:
1. Copy `CH341SER.EXE` from USB drive
2. Run as Administrator
3. Click "INSTALL"
4. Plug in the USB-Serial cable
5. Check Device Manager → Ports → should show "USB-SERIAL CH340 (COMx)"

### 4.3 Install Google Chrome (if not present)

The software works best in Chrome. Copy installer from USB and install.

---

## 5. Phase 3 — Application Installation

**Time: 20 minutes**

### 5.1 Create Application Directory

```powershell
# Run as Administrator
New-Item -ItemType Directory -Path "C:\weighbridge" -Force
New-Item -ItemType Directory -Path "C:\weighbridge\logs" -Force
New-Item -ItemType Directory -Path "C:\weighbridge\backups" -Force
New-Item -ItemType Directory -Path "C:\weighbridge\uploads\camera" -Force
New-Item -ItemType Directory -Path "C:\weighbridge\uploads\wallpaper" -Force
```

### 5.2 Copy Application Files

```powershell
# Copy from USB drive (adjust drive letter E: as needed)
Copy-Item -Path "E:\weighbridge-release\*" -Destination "C:\weighbridge\" -Recurse -Force
```

### 5.3 Start PostgreSQL Database

```powershell
cd C:\weighbridge
docker compose up -d db

# Wait for database to be ready (30 seconds)
Start-Sleep -Seconds 30
docker exec weighbridge_db pg_isready -U weighbridge
# Must show: "accepting connections"
```

### 5.4 Configure Environment

Create `C:\weighbridge\backend\.env`:

```powershell
# Generate a random secret key
$secretKey = -join ((48..57) + (97..122) | Get-Random -Count 64 | ForEach-Object { [char]$_ })

@"
DATABASE_URL=postgresql+asyncpg://weighbridge:weighbridge_dev_2024@localhost:5432/weighbridge
DATABASE_URL_SYNC=postgresql+psycopg://weighbridge:weighbridge_dev_2024@localhost:5432/weighbridge
SECRET_KEY=$secretKey
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=480
MULTI_TENANT=false
COMPANY_NAME=Client Company Name
"@ | Out-File -FilePath "C:\weighbridge\backend\.env" -Encoding UTF8

Write-Host "Secret key generated. .env file created."
```

> **NOTE:** For cloud-connected clients (SaaS mode), set `MULTI_TENANT=true` and add master database URLs. For standalone local installs, keep `MULTI_TENANT=false`.

### 5.5 Setup Python Environment

```powershell
cd C:\weighbridge\backend

# Create Python virtual environment (skip if venv already exists in release package)
if (-not (Test-Path "venv\Scripts\python.exe")) {
    python -m venv venv
    .\venv\Scripts\pip.exe install --upgrade pip
    .\venv\Scripts\pip.exe install -r requirements.txt
    Write-Host "Python venv created and packages installed"
} else {
    Write-Host "Python venv already exists"
}
```

### 5.6 Start Backend Service

```powershell
# Test start first (to verify no errors)
cd C:\weighbridge\backend
.\venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 9001
# Wait for "Uvicorn running on http://0.0.0.0:9001"
# Press Ctrl+C to stop

# Download NSSM if not present (requires internet, one-time only)
if (-not (Get-Command nssm -ErrorAction SilentlyContinue)) {
    Write-Host "Downloading NSSM..."
    Invoke-WebRequest -Uri "https://nssm.cc/release/nssm-2.24.zip" -OutFile "$env:TEMP\nssm.zip"
    Expand-Archive "$env:TEMP\nssm.zip" -DestinationPath "$env:TEMP\nssm" -Force
    Copy-Item "$env:TEMP\nssm\nssm-2.24\win64\nssm.exe" "C:\Windows\System32\nssm.exe"
    Write-Host "NSSM installed to C:\Windows\System32\"
}

# Register Backend as Windows Service
nssm install WeighbridgeBackend "C:\weighbridge\backend\venv\Scripts\python.exe" "-m uvicorn app.main:app --host 0.0.0.0 --port 9001"
nssm set WeighbridgeBackend AppDirectory "C:\weighbridge\backend"
nssm set WeighbridgeBackend AppStdout "C:\weighbridge\logs\backend-stdout.log"
nssm set WeighbridgeBackend AppStderr "C:\weighbridge\logs\backend-stderr.log"
nssm set WeighbridgeBackend AppRotateFiles 1
nssm set WeighbridgeBackend AppRotateBytes 10485760
nssm start WeighbridgeBackend
```

### 5.7 Build & Serve Frontend

```powershell
cd C:\weighbridge\frontend

# Install dependencies and build (skip if dist/ already exists in release)
if (-not (Test-Path "dist\index.html")) {
    npm install
    npm run build
    Write-Host "Frontend built successfully"
} else {
    Write-Host "Frontend dist/ already exists"
}

# Register Frontend as Windows Service (serves static files on port 9000)
npm install -g serve
nssm install WeighbridgeFrontend "serve" "-s dist -l 9000"
nssm set WeighbridgeFrontend AppDirectory "C:\weighbridge\frontend"
nssm set WeighbridgeFrontend AppStdout "C:\weighbridge\logs\frontend-stdout.log"
nssm set WeighbridgeFrontend AppStderr "C:\weighbridge\logs\frontend-stderr.log"
nssm start WeighbridgeFrontend
```

### 5.8 Verify Application

```powershell
# Wait 10 seconds for startup
Start-Sleep -Seconds 10

# Health check (backend API)
Invoke-RestMethod http://localhost:9001/api/v1/health | ConvertTo-Json
# Must show: "status": "healthy" or "degraded"

# Verify services running
Get-Service WeighbridgeBackend, WeighbridgeFrontend | Format-Table Name, Status

# Open in browser (port 9000 = frontend, port 9001 = API)
Start-Process "http://localhost:9000"
```

> **Default admin credentials:** Username: `admin` / Password: set during tenant creation on the cloud platform (Section 1, Pre-Create Tenant). For standalone installs, the initial admin user is created by the database seed — default password is `Admin@123` (change immediately after first login).

---

## 6. Phase 4 — Weighbridge Scale Setup

**Time: 30 minutes**

### 6.1 Physical Connection

```
[Weighbridge Indicator] ← RS232 Cable → [RS232-to-USB Converter] ← USB → [PC]
```

1. Turn OFF the weighbridge indicator
2. Connect RS232 cable from indicator's serial port to the USB converter
3. Plug USB converter into PC
4. Turn ON the indicator
5. Wait 10 seconds for Windows to recognize the device

### 6.2 Identify COM Port

```powershell
# Method 1: PowerShell
Get-CimInstance Win32_PnPEntity | Where-Object { $_.Name -match 'COM\d' } | Select-Object Name
# Example output: "USB-SERIAL CH340 (COM3)" → COM port is COM3

# Method 2: Device Manager
# Open Device Manager → Ports (COM & LPT) → Note the COM number
```

### 6.3 Find Scale Settings

Check the weighbridge indicator's manual or settings menu for:
- **Baud Rate** (usually 9600)
- **Data Bits** (7 or 8)
- **Parity** (Even or None)
- **Stop Bits** (1)
- **Continuous Mode** — MUST be enabled (the indicator sends weight data continuously)

> **IMPORTANT:** The indicator MUST be set to "Continuous Send" mode, NOT "Print on Demand" mode. Check indicator settings menu → Communication → Mode → Continuous.

### 6.4 Configure in Software

Login to the application as admin, then use the API to configure:

```powershell
# Login first
$login = Invoke-RestMethod -Uri "http://localhost:9001/api/v1/auth/login" -Method POST `
    -ContentType "application/x-www-form-urlencoded" `
    -Body "username=admin&password=YOUR_PASSWORD"
$token = $login.access_token
$headers = @{ Authorization = "Bearer $token" }

# Option A: Auto-detect scale (recommended — scans all ports, 30 seconds)
Invoke-RestMethod -Uri "http://localhost:9001/api/v1/weight/auto-detect" -Method POST `
    -Headers $headers | ConvertTo-Json -Depth 3
# Returns: detected port, baud rate, protocol, sample reading

# Option B: Manual configuration
$config = @{
    port_name = "COM3"          # From Step 6.2
    baud_rate = 9600            # From indicator settings
    data_bits = 8               # 7 for Indian brands, 8 for international
    stop_bits = 1
    parity = "N"                # "N" (None) or "E" (Even)
    protocol = "generic"        # See Section 11 for brand-specific
    is_enabled = $true
    stability_readings = 5
    stability_tolerance_kg = 20
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:9001/api/v1/weight/config" -Method PUT `
    -Headers $headers -ContentType "application/json" -Body $config
```

### 6.5 Test Scale Connection

```powershell
# Test the configured port
$testBody = @{ port_name = "COM3"; baud_rate = 9600; duration_sec = 10 } | ConvertTo-Json
Invoke-RestMethod -Uri "http://localhost:9001/api/v1/weight/test-port" -Method POST `
    -Headers $headers -ContentType "application/json" -Body $testBody | ConvertTo-Json -Depth 3
# Should return: raw_frames with weight data

# Check real-time status
Invoke-RestMethod -Uri "http://localhost:9001/api/v1/weight/status" -Headers $headers
# Should show: scale_connected: true, weight_kg: <current weight>
```

### 6.6 Verify in Browser

1. Open `http://localhost:9000`
2. Go to **Token Dashboard** or **Camera & Scale** page
3. You should see:
   - Weight display updating in real-time
   - Green "STABLE" indicator when truck is still
   - Weight in KG and MT

> **If weight shows 0 or "Disconnected":** See Troubleshooting Section 10.

---

## 7. Phase 5 — IP Camera Setup

**Time: 20 minutes**

### 7.1 Camera Network Setup

1. Connect cameras to the same network switch as the PC
2. Assign static IPs to cameras (use camera's web interface or SADP Tool for Hikvision)
3. Ensure PC can ping each camera:

```powershell
ping 192.168.1.13   # Front camera
ping 192.168.1.14   # Top camera
# Both must reply successfully
```

### 7.2 Find Camera Snapshot URL

Open the camera's web interface in Chrome and login. Then use the correct snapshot URL format:

| Brand | Snapshot URL Format |
|-------|-------------------|
| Hikvision | `http://IP/Streaming/channels/1/picture` |
| Dahua | `http://IP/cgi-bin/snapshot.cgi` |
| STQC | `http://IP/snap.jpg` |
| Uniview | `http://IP/images/snapshot.jpg` |
| Generic ONVIF | `http://IP/onvif-http/snapshot` |
| RTSP (any brand) | `rtsp://IP:554/ch1/main/av_stream` |

### 7.3 Test Camera Access

```powershell
# Test if camera snapshot URL works (should download a JPEG)
Invoke-WebRequest -Uri "http://admin:password@192.168.1.13/Streaming/channels/1/picture" `
    -OutFile "C:\temp\test_front.jpg"
# Open the file — should show camera view
```

### 7.4 Configure in Software

```powershell
# Login (reuse $headers from step 6.4)

$cameraConfig = @{
    front = @{
        label = "Front View"
        snapshot_url = "http://192.168.1.13/Streaming/channels/1/picture"
        username = "admin"
        password = "camera_password"
        enabled = $true
    }
    top = @{
        label = "Top View"
        snapshot_url = "http://192.168.1.14/Streaming/channels/1/picture"
        username = "admin"
        password = "camera_password"
        enabled = $true
    }
} | ConvertTo-Json -Depth 3

Invoke-RestMethod -Uri "http://localhost:9001/api/v1/cameras/config" -Method PUT `
    -Headers $headers -ContentType "application/json" -Body $cameraConfig
```

### 7.5 Test Camera Capture

```powershell
# Test front camera
Invoke-RestMethod -Uri "http://localhost:9001/api/v1/cameras/test/front" -Method POST `
    -Headers $headers | ConvertTo-Json
# Should return: { "success": true, "url": "/uploads/camera/test/..." }

# Test top camera
Invoke-RestMethod -Uri "http://localhost:9001/api/v1/cameras/test/top" -Method POST `
    -Headers $headers | ConvertTo-Json
```

### 7.6 Verify in Browser

1. Go to **Settings → Cameras** tab
2. Both cameras should show green status
3. Click "Test Snapshot" — preview image should appear
4. Go to **Camera & Scale** page — live MJPEG streams should display

---

## 8. Phase 6 — Application Configuration

**Time: 20 minutes**

### 8.1 Company Setup

1. Login as admin → **Settings → Company**
2. Fill in:
   - Company Name
   - Legal Name
   - GSTIN (15 chars)
   - PAN (10 chars)
   - Full Address (Line 1, City, State, State Code, Pincode)
   - Phone, Email
   - Bank Details (Name, Account No, IFSC, Branch)
   - Invoice Prefix (e.g., `INV`)
3. Click **Save**

### 8.2 Financial Year

1. **Settings → Financial Year**
2. Create: Label `2025-26`, Start `2025-04-01`, End `2026-03-31`
3. Click **Activate**

### 8.3 Create Users

1. Go to **Admin → User Management**
2. Create operator account:
   - Username: `operator1`
   - Password: (set a simple password for the operator)
   - Role: `operator`
   - Full Name: Operator's name
3. Create additional users as needed

### 8.4 Add Products

1. Go to **Products** page
2. Add each product the client sells:
   - Name: `10mm Aggregate`
   - HSN Code: `25171010`
   - Unit: `MT`
   - Default Rate: `850`
   - GST Rate: `5`

### 8.5 Add Parties (Customers/Suppliers)

1. Go to **Parties** page
2. Add key customers and suppliers
3. Include GSTIN for B2B invoicing

---

## 9. Phase 7 — Final Verification Checklist

Run through this checklist before leaving the client site:

### Weight Scale
- [ ] Weight indicator is ON and displaying weight
- [ ] USB-Serial cable is securely connected
- [ ] Software shows real-time weight in KG
- [ ] Weight stabilizes (green "STABLE" indicator)
- [ ] Create a test token → First Weight captures correctly
- [ ] Load/unload truck → Second Weight captures correctly
- [ ] Net weight calculates correctly (Gross - Tare)
- [ ] Token completes successfully

### Camera (if installed)
- [ ] Both cameras accessible via network (ping test)
- [ ] Front camera test snapshot works
- [ ] Top camera test snapshot works
- [ ] Camera images captured automatically on second weight
- [ ] Images visible in Token Detail Modal (camera icon)
- [ ] Snapshot Search page shows captured images

### Application
- [ ] Admin can login
- [ ] Operator can login
- [ ] Dashboard shows today's data
- [ ] Invoice generates correctly (PDF download works)
- [ ] Company name and GSTIN appear on invoice PDF
- [ ] Financial year is set and active

### System
- [ ] Docker container is running: `docker ps`
- [ ] Backend service is running: `Get-Service WeighbridgeBackend`
- [ ] Application auto-starts on PC reboot (test by restarting)
- [ ] Browser bookmarked to `http://localhost:9000`

### Sign-Off
- [ ] Client admin password documented (sealed envelope)
- [ ] Support phone number shared with client
- [ ] USB Security Key left with authorized person
- [ ] Client acknowledges working system (signature)

---

## 10. Troubleshooting Guide

### Weight Scale Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| "Disconnected" in software | USB cable not detected | Unplug and replug USB. Check Device Manager for COM port |
| COM port not visible | Driver not installed | Install CH340 driver from USB |
| Weight shows 0 always | Wrong baud rate or protocol | Try auto-detect: `POST /api/v1/weight/auto-detect` |
| Weight jumps erratically | Wrong data bits/parity | Check indicator manual. Common: 7E1 for Essae, 8N1 for Leo+ |
| "FLUCTUATING" never stabilizes | Tolerance too low | Increase `stability_tolerance_kg` to 50 in config |
| Weight reads but negative | Protocol issue | Try different protocol in config |
| USB-Serial disconnects randomly | CH340 power issue | Use a powered USB hub. Avoid USB 3.0 ports |

### Camera Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| "Camera Offline" | Network unreachable | Check cable, ping IP, verify camera is powered |
| 401 Unauthorized | Wrong credentials | Verify username/password in camera web interface |
| Black image | Wrong snapshot URL | Try different URL format (see Section 12) |
| Slow/timeout | Network congestion | Use wired connection, check for IP conflicts |
| RTSP not working | OpenCV not installed | Use HTTP snapshot URL instead of RTSP |

### Application Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| Page won't load | Backend not running | `Get-Service WeighbridgeBackend` → Start if stopped |
| "502 Bad Gateway" | Backend crashed | Check logs: `C:\weighbridge\logs\backend-stderr.log` |
| Database error | PostgreSQL container stopped | `docker start weighbridge_db` |
| Login fails | Wrong credentials | Reset via API or database |
| Slow performance | Low RAM | Close other applications, check Task Manager |

### Docker Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| Docker won't start | Virtualization disabled in BIOS | Enter BIOS → Advanced → CPU → Enable VT-x/AMD-V → Reboot |
| Docker won't start | Windows Home edition | Upgrade to Windows 10/11 Pro (Home lacks Hyper-V) |
| "Docker daemon not running" | Docker Desktop not started | Start Docker Desktop from Start Menu, wait for green icon |
| Container keeps restarting | Bad PostgreSQL config | `docker logs weighbridge_db --tail 20` to see actual error |
| "Port 5432 already in use" | Another PostgreSQL installed | Stop the other PostgreSQL: `Stop-Service postgresql*` |

### Emergency Recovery

```powershell
# Restart everything (run as Administrator)
docker restart weighbridge_db
Start-Sleep -Seconds 10
Restart-Service WeighbridgeBackend -Force
Restart-Service WeighbridgeFrontend -Force
Start-Sleep -Seconds 10
Invoke-RestMethod http://localhost:9001/api/v1/health

# If services don't exist yet, start manually:
cd C:\weighbridge\backend
.\venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 9001
```

### Verify Database is Running

```powershell
# Check container status
docker ps --filter name=weighbridge_db --format "{{.Status}}"
# Must show: "Up X minutes" (not "Restarting")

# Check database responds
docker exec weighbridge_db pg_isready -U weighbridge
# Must show: "accepting connections"

# Check tables exist
docker exec weighbridge_db psql -U weighbridge -c "\dt" | Select-String "users|tokens|invoices"
```

---

## 11. Common Scale Brands & Settings

| Brand | Model | Baud | Data | Parity | Stop | Protocol |
|-------|-------|------|------|--------|------|----------|
| Essae | ET-600, T-series | 9600 | 7 | Even | 1 | `essae` |
| Leo | Leo+, BW-100/200 | 9600 | 7 | Even | 1 | `leo` |
| Avery | Berkel, Weigh-Tronix | 9600 | 8 | None | 1 | `avery` |
| Mettler Toledo | IND245, IND560 | 9600 | 8 | None | 1 | `mettler` |
| Rice Lake | 920i, 880 | 9600 | 8 | None | 1 | `rice_lake` |
| Systec | IT3000 | 9600 | 8 | None | 1 | `systec` |
| CAS | CI-2001 | 9600 | 8 | None | 1 | `cas` |
| TP/Phoenix/Aczet | Any loadcell | 9600 | 7 | Even | 1 | `tp_loadcell` |
| Generic | Auto-detect | 9600 | 8 | None | 1 | `generic` |

> **Tip:** If unsure, start with `generic` protocol at 9600 baud. The auto-detect feature will try all combinations.

---

## 12. Common Camera Brands & URLs

### Hikvision

```
# HTTP Snapshot (recommended)
http://admin:PASSWORD@192.168.1.13/Streaming/channels/1/picture

# RTSP Stream
rtsp://admin:PASSWORD@192.168.1.13:554/Streaming/Channels/101

# Default credentials: admin / (set during activation)
# Default IP: 192.168.1.64
# Config tool: SADP Tool (download from hikvision.com)
```

### Dahua

```
# HTTP Snapshot
http://admin:PASSWORD@192.168.1.14/cgi-bin/snapshot.cgi

# RTSP Stream
rtsp://admin:PASSWORD@192.168.1.14:554/cam/realmonitor?channel=1&subtype=0

# Default credentials: admin / admin
# Default IP: 192.168.1.108
# Config tool: ConfigTool (download from dahuasecurity.com)
```

### CP Plus

```
# HTTP Snapshot
http://admin:PASSWORD@192.168.1.15/snap.jpg

# RTSP Stream
rtsp://admin:PASSWORD@192.168.1.15:554/cam/realmonitor?channel=1&subtype=0

# Default credentials: admin / admin
# Default IP: 192.168.1.108
```

### Uniview

```
# HTTP Snapshot
http://admin:PASSWORD@192.168.1.16/images/snapshot.jpg

# RTSP Stream
rtsp://admin:PASSWORD@192.168.1.16:554/unicast/c1/s0/live
```

---

## 13. Support Contact

| Channel | Contact | Hours |
|---------|---------|-------|
| Phone | +91-XXXXX-XXXXX | Mon-Sat 9:00-18:00 |
| WhatsApp | +91-XXXXX-XXXXX | Mon-Sat 9:00-21:00 |
| Email | support@manhotraconsulting.com | 24/7 (response within 4 hours) |
| Emergency | +91-XXXXX-XXXXX | 24/7 for critical issues |

**When contacting support, provide:**
1. Client name and site location
2. Error screenshot or exact error message
3. What was being done when the error occurred
4. Scale model and camera model (if hardware issue)

---

*This document is confidential. For internal use by Manhotra Consulting field engineers only.*
