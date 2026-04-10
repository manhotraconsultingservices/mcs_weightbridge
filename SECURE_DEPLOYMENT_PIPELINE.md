# Secure Deployment Pipeline — Weighbridge ERP

> Complete guide for building and deploying the Weighbridge application at client sites.
> Written for junior engineers — follow steps in exact order.

**Last updated:** 10-Apr-2026

---

## Table of Contents

0. [Building the Release Package (Office)](#0-building-the-release-package)
1. [Architecture Overview](#1-architecture-overview)
2. [Prerequisites](#2-prerequisites)
3. [Vendor Preparation (Before Client Visit)](#3-vendor-preparation)
4. [Client Site Deployment (On-Site)](#4-client-site-deployment)
5. [Cloudflare Tunnel Setup](#5-cloudflare-tunnel-setup)
6. [Cloud Backup Setup (R2)](#6-cloud-backup-setup)
7. [Post-Deployment Verification](#7-post-deployment-verification)
8. [Security Layers](#8-security-layers)
9. [Backup & Recovery](#9-backup--recovery)
10. [Troubleshooting](#10-troubleshooting)
11. [Cost Summary](#11-cost-summary)
12. [Script Reference](#12-script-reference)
13. [Common Mistakes (Read This First!)](#13-common-mistakes)
14. [Uninstall / Rollback (If Deployment Fails)](#14-uninstall--rollback-if-deployment-fails)

---

## 0. Building the Release Package

> **Who does this?** Senior developer or build engineer, at the office.
> **When?** Before every new client deployment or version update.
> **Time needed:** ~20 minutes (first time ~40 minutes including setup).

### 0.0 Clone the Repository (First Time Only)

```powershell
# Open PowerShell and clone the code from GitHub
cd C:\Projects
git clone https://github.com/manhotraconsultingservices/mcs_weightbridge.git
cd mcs_weightbridge
```

> **All commands below use `$repoDir` as the project root.**
> Set it once at the start of every session:
> ```powershell
> $repoDir = "C:\Projects\mcs_weightbridge"
> ```
> Replace `C:\Projects\mcs_weightbridge` with wherever you cloned the repo.

### 0.1 One-Time Setup (First Time Only)

Install these on the **build machine** (your office development PC).
Run all commands in **PowerShell (Run as Administrator)**.

**Step 1 — Python 3.11** (NOT 3.12+, Nuitka needs 3.11):
1. Download from https://www.python.org/downloads/release/python-3119/
2. Run the installer
3. **IMPORTANT:** Check the box **"Add Python 3.11 to PATH"** before clicking Install
4. Verify: Open new PowerShell window, type `python --version` — should show `Python 3.11.x`

**Step 2 — Node.js 20 LTS:**
1. Download from https://nodejs.org/ (click the LTS button)
2. Run installer with defaults
3. Verify: `node --version` — should show `v20.x.x`

**Step 3 — Git** (for source code):
1. Download from https://git-scm.com/download/win
2. Install with defaults
3. Verify: `git --version`

**Step 4 — MinGW-w64 C Compiler** (needed by Nuitka to compile Python to .exe):
```powershell
# Install MSYS2 (a Unix-tools package manager for Windows)
winget install -e --id MSYS2.MSYS2
```
After MSYS2 installs, it opens a terminal window. In that MSYS2 terminal (NOT PowerShell), type:
```
pacman -S mingw-w64-x86_64-gcc
```
Press Y when asked. Then close the MSYS2 terminal.

Add MinGW to Windows PATH:
```powershell
# Run in PowerShell as Administrator:
$mingwPath = "C:\msys64\mingw64\bin"
$currentPath = [Environment]::GetEnvironmentVariable("PATH", "Machine")
if ($currentPath -notlike "*$mingwPath*") {
    [Environment]::SetEnvironmentVariable("PATH", "$currentPath;$mingwPath", "Machine")
    Write-Host "MinGW added to PATH. Close and reopen PowerShell." -ForegroundColor Green
}
```
Verify: Close and reopen PowerShell, then type `gcc --version` — should show version info.

**Step 5 — Nuitka** (compiles Python to native .exe):
```powershell
pip install nuitka ordered-set zstandard
```

**Step 6 — Frontend dependencies:**
```powershell
cd "$repoDir\frontend"
npm install
```

**Step 7 — Backend dependencies:**
```powershell
cd "$repoDir\backend"
pip install -r requirements.txt
```

**Step 8 — NSSM (Windows Service Manager):**

NSSM is NOT in the git repo (binary files are excluded). Download it once:
```powershell
# Download NSSM and place in scripts folder
$nssmUrl = "https://nssm.cc/release/nssm-2.24.zip"
$zipFile = "$env:TEMP\nssm.zip"
Invoke-WebRequest -Uri $nssmUrl -OutFile $zipFile -UseBasicParsing
Expand-Archive -Path $zipFile -DestinationPath "$env:TEMP\nssm-extract" -Force
Copy-Item "$env:TEMP\nssm-extract\nssm-2.24\win64\nssm.exe" "$repoDir\scripts\nssm.exe" -Force
Remove-Item $zipFile, "$env:TEMP\nssm-extract" -Recurse -Force
Write-Host "NSSM downloaded to scripts\nssm.exe" -ForegroundColor Green
```

**Step 9 — Vendor Keypair for License Generation** (ask senior developer):

The license generator needs a vendor keypair (Ed25519). These are NOT in git for security.
If you're the first person setting up, generate them:
```powershell
cd "$repoDir\tools\license-generator"
python -c "
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
private_key = Ed25519PrivateKey.generate()
with open('vendor_private.key', 'wb') as f:
    f.write(private_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
with open('vendor_public.key', 'wb') as f:
    f.write(private_key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
print('Keypair generated: vendor_private.key + vendor_public.key')
"
```

> **CRITICAL:** The `vendor_private.key` must NEVER be shared or committed to git.
> Store it in a password manager or secure vault. Only the person who generates
> licenses needs this file. The `vendor_public.key` must be embedded in the
> backend source code (`backend/app/services/license.py`).

### 0.2 Build the Frontend

```powershell
cd "$repoDir\frontend"

# IMPORTANT: Before building, verify vite.config.ts proxy points to port 9001
# Open vite.config.ts and check the proxy target is http://localhost:9001 (NOT 9003 or other dev ports)
# If it shows a different port, change it back to 9001 before building:

# Build production bundle (minified, no source maps)
npm run build

# Output: frontend/dist/ folder (~5-10 MB)
# Verify it was created:
dir dist\index.html
# Should show: index.html
```

**What this creates:** A `dist/` folder containing compiled HTML, CSS, and JavaScript files. No TypeScript source code is included.

### 0.3 Build the Backend Binary

```powershell
cd "$repoDir\backend"

# Compile Python to native Windows .exe (takes 5-15 minutes first time)
powershell -File build_dist.ps1

# Output: backend/dist/weighbridge_server.exe (~50-150 MB)
# Verify:
dir dist\weighbridge_server.exe
```

**What this creates:** A single `.exe` file that contains the entire backend (FastAPI, all dependencies). No `.py` source files needed at the client site.

> **If Nuitka build fails:** Check BUILD_GUIDE.md Section 3 for troubleshooting. Common fix: install Visual Studio Build Tools.

### 0.4 Package the Release

Create a release folder with everything the client needs.
Run this in **PowerShell** from the project root (where you cloned the repo):

```powershell
cd $repoDir
```

```powershell
# Set version number (change this for each release)
$version = "1.0.0"
$releaseDir = "C:\releases\weighbridge-full-$version"

# Create folder structure
New-Item -ItemType Directory -Path "$releaseDir\backend" -Force | Out-Null
New-Item -ItemType Directory -Path "$releaseDir\backend\hardening" -Force | Out-Null

# Copy backend binary + utilities
Copy-Item "backend\dist\weighbridge_server.exe" "$releaseDir\backend\" -Force
Copy-Item "backend\setup_dpapi.py"              "$releaseDir\backend\" -Force
Copy-Item "backend\show_fingerprint.py"         "$releaseDir\backend\" -Force
Copy-Item "backend\requirements.txt"            "$releaseDir\backend\" -Force
Copy-Item "backend\hardening\secure_setup.ps1"  "$releaseDir\backend\hardening\" -Force

# Copy PDF/email templates (needed at runtime for invoice generation)
# /E = include subdirectories, /I = assume directory, /Y = no confirm overwrite
xcopy "backend\app\templates" "$releaseDir\backend\app\templates\" /E /I /Y /Q

# Copy compiled frontend (HTML/CSS/JS static files)
xcopy "frontend\dist" "$releaseDir\frontend\dist\" /E /I /Y /Q

# Copy Docker Compose (for PostgreSQL)
Copy-Item "docker-compose.yml" "$releaseDir\" -Force

# Copy all deployment scripts
xcopy "scripts" "$releaseDir\scripts\" /E /I /Y /Q

# Verify NSSM is in scripts (needed for Windows service registration)
if (-not (Test-Path "scripts\nssm.exe")) {
    Write-Host "WARNING: nssm.exe not found in scripts\. Download it:" -ForegroundColor Red
    Write-Host "  https://nssm.cc/release/nssm-2.24.zip" -ForegroundColor Yellow
    Write-Host "  Extract win64\nssm.exe to scripts\nssm.exe" -ForegroundColor Yellow
}

# Create .env template (secrets get auto-generated during install — NOT stored here)
@"
DATABASE_URL=postgresql+asyncpg://weighbridge:REPLACE_ME@localhost:5432/weighbridge
DATABASE_URL_SYNC=postgresql+psycopg://weighbridge:REPLACE_ME@localhost:5432/weighbridge
SECRET_KEY=REPLACE_ME
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=480
PRIVATE_DATA_KEY=REPLACE_ME
"@ | Set-Content "$releaseDir\backend\.env.template" -Encoding UTF8

# Show summary
Write-Host "`nRelease package created at: $releaseDir" -ForegroundColor Green
Get-ChildItem $releaseDir -Recurse | Measure-Object -Property Length -Sum |
    ForEach-Object { Write-Host "Total size: $([math]::Round($_.Sum / 1MB, 1)) MB" -ForegroundColor Cyan }
```

> **Note about `xcopy`:** This is a Windows command that copies folders recursively.
> It works in both PowerShell and Command Prompt. The `/E /I /Y /Q` flags mean:
> `/E` = include empty subdirectories, `/I` = treat destination as directory,
> `/Y` = overwrite without asking, `/Q` = quiet mode (don't list every file).

### 0.5 Verify the Release Package

Check that all required files are present:

```powershell
$releaseDir = "C:\releases\weighbridge-full-1.0.0"

# Must exist:
$required = @(
    "backend\weighbridge_server.exe",
    "backend\setup_dpapi.py",
    "backend\show_fingerprint.py",
    "backend\hardening\secure_setup.ps1",
    "backend\.env.template",
    "frontend\dist\index.html",
    "docker-compose.yml",
    "scripts\Deploy-Full.ps1",
    "scripts\Setup-CloudflareTunnel.ps1",
    "scripts\Setup-CloudBackup.ps1",
    "scripts\Backup-ToCloud.ps1",
    "scripts\Verify-Deployment.ps1",
    "scripts\Install-Client.ps1"
)

$missing = @()
foreach ($f in $required) {
    $path = Join-Path $releaseDir $f
    if (Test-Path $path) {
        Write-Host "  [OK] $f" -ForegroundColor Green
    } else {
        Write-Host "  [MISSING] $f" -ForegroundColor Red
        $missing += $f
    }
}

if ($missing.Count -eq 0) {
    Write-Host "`n  Release package is COMPLETE!" -ForegroundColor Green
} else {
    Write-Host "`n  $($missing.Count) file(s) missing!" -ForegroundColor Red
}
```

---

## 1. Architecture Overview

The Weighbridge ERP uses an **on-premise + Cloudflare** hybrid architecture:

- **Everything runs locally** on the client's Windows PC (backend, database, hardware integrations)
- **Cloudflare Tunnel** provides secure remote access without opening ports
- **Cloudflare R2** stores encrypted database backups in the cloud
- **Cloudflare Zero Trust** adds an email-OTP login gate before the app is reachable

```
CLIENT SITE                                CLOUDFLARE (FREE)
+-------------------------------+          +---------------------------+
|                               |          |                           |
|  Weight Scale (COM port)      |          |  Cloudflare Tunnel        |
|  IP Cameras (HTTP snapshot)   |          |  (encrypted pipe)         |
|  Tally Prime (localhost:9002) |          |                           |
|                               |          |  Zero Trust Access        |
|  FastAPI Backend (:9001)      +--tunnel--+  (email OTP gate)         |
|  PostgreSQL (:5432)           |          |                           |
|  React Frontend (:9000)       |          |  R2 Storage               |
|                               |          |  (encrypted backups)      |
|  BitLocker + DPAPI + License  |          |                           |
+-------------------------------+          |  CDN + SSL + DDoS         |
                                           +---------------------------+
                                                      |
                                           weighbridge-client.domain.com
                                                      |
                                               Users (anywhere)
```

### Why This Architecture?

| Requirement | Why On-Premise Wins |
|-------------|-------------------|
| Weight Scale | Serial port requires local hardware access |
| IP Cameras | Same LAN = instant capture, no cloud latency |
| Tally Prime | Desktop software, only runs on localhost |
| Performance | Local PostgreSQL = 2ms queries vs 100ms+ cloud |
| Theft Protection | BitLocker + DPAPI + hardware-locked license |
| Cost | Only a domain name required (no cloud servers) |

---

## 2. Prerequisites

### Vendor Machine (Your Office)

| Software | Version | Download Link | Purpose |
|----------|---------|--------------|---------|
| Windows 10/11 | 64-bit | — | Operating system |
| Python | 3.11.x (NOT 3.12) | https://www.python.org/downloads/release/python-3119/ | License generation, Nuitka build |
| Node.js | 20 LTS | https://nodejs.org/ | Frontend build |
| Git | Latest | https://git-scm.com/download/win | Source code management |
| MSYS2 + MinGW | Latest | `winget install MSYS2.MSYS2` | C compiler for Nuitka |
| Nuitka | Latest | `pip install nuitka` | Python-to-binary compiler |
| PowerShell | 5.1+ | Built into Windows | Script execution |
| Cloudflare account | Free tier | https://dash.cloudflare.com/sign-up | Tunnel + R2 + Zero Trust |
| Domain name | Any `.com`/`.in` | Any registrar | Public URL for clients |

### Client Machine (On-Site)

| Requirement | Details | How to Check |
|-------------|---------|-------------|
| Windows | 10/11 **Professional or Enterprise** (NOT Home) | Right-click Start > System > "Windows 10 Pro" |
| Architecture | 64-bit | System > "64-bit operating system" |
| RAM | 8 GB minimum | System > "Installed RAM" |
| Free Disk | 5 GB minimum on C: | File Explorer > This PC > C: drive |
| Docker Desktop | Latest | https://www.docker.com/products/docker-desktop/ |
| Internet | Active connection | Open any website in browser |
| Admin Access | Know the admin password | Can you right-click > "Run as administrator"? |
| NSSM | Included in release package | Used to register Windows services |
| Python 3.11 | **Only if deploying from source** (not needed for .exe binary) | `python --version` |

> **Why Docker Desktop?** It runs the PostgreSQL 16 database inside a container.
> This avoids complex PostgreSQL Windows installation. If the client already has
> PostgreSQL 16 installed natively, Docker is NOT needed.

> **Why NOT Windows Home?** BitLocker (full disk encryption) is only available on
> Pro/Enterprise. Without BitLocker, stolen machines expose all data.

> **What is NSSM?** Non-Sucking Service Manager — a small tool (1 MB) that registers
> any .exe as a Windows service with auto-restart. Included in the release package
> under `scripts\nssm.exe`. Download separately if needed: https://nssm.cc/download

### Client Machine — Pre-Visit Checklist

Before you travel to the client site, confirm these over phone/WhatsApp:

- [ ] Windows version is Pro or Enterprise (NOT Home)
- [ ] PC has at least 8 GB RAM
- [ ] PC has at least 5 GB free disk space
- [ ] Client knows the admin password for the PC
- [ ] Internet is available (Wi-Fi or Ethernet)
- [ ] UPS is connected (power cuts during install can corrupt database)
- [ ] Weight scale is connected via USB-to-Serial cable
- [ ] IP cameras are accessible on the local network (if applicable)

### Cloudflare Setup (One-Time, Vendor Side)

Do this ONCE from your Cloudflare dashboard. All future clients reuse the same account.

1. **Add your domain** to Cloudflare (free plan)
   - Go to [dash.cloudflare.com](https://dash.cloudflare.com) > Add a site > Enter domain
   - Update your domain registrar's nameservers to Cloudflare's (shown on screen)
2. **Enable Zero Trust** (free for up to 50 users)
   - Go to [one.dash.cloudflare.com](https://one.dash.cloudflare.com) > Start setup
3. **Create an R2 bucket** named `weighbridge-backups`
   - Go to [dash.cloudflare.com](https://dash.cloudflare.com) > R2 Object Storage > Create bucket
   - Bucket name: `weighbridge-backups`
   - Location: Auto (or Asia Pacific)
4. **Create R2 API token** (Access Key + Secret)
   - Go to R2 > Manage R2 API Tokens > Create API token
   - Permissions: Object Read & Write
   - Specify bucket: `weighbridge-backups`
   - Save the **Access Key ID** and **Secret Access Key** — you'll need these for each client

> **IMPORTANT:** Save the R2 credentials securely (password manager). You cannot
> view the Secret Key again after creation.

---

## 3. Vendor Preparation

### Step 3.1: Create Cloudflare Tunnel

1. Go to [Cloudflare Zero Trust Dashboard](https://one.dash.cloudflare.com)
2. Navigate to **Networks > Tunnels**
3. Click **Create a tunnel**
4. Name it: `weighbridge-<client-id>` (e.g., `weighbridge-shreeram`)
5. Choose **Cloudflared** connector
6. **Copy the tunnel token** (long base64 string starting with `eyJ...`)
7. Add a **Public Hostname**:
   - Subdomain: `weighbridge-shreeram`
   - Domain: `yourdomain.com`
   - Service: `http://localhost:9001`
8. Save

### Step 3.2: Set Up Zero Trust Access Policy

1. Go to **Access > Applications > Add an application**
2. Type: **Self-hosted**
3. Application name: `Weighbridge - <Client Name>`
4. Session duration: **24 hours**
5. Application domain: `weighbridge-shreeram.yourdomain.com`
6. Add a policy:
   - Policy name: `Allow authorized emails`
   - Action: **Allow**
   - Include: **Emails** = `ankushmanhotra@gmail.com, rishumanhotra@gmail.com` (add client emails too)
7. Optionally add **Country** rule: Require = `India`
8. Save

### Step 3.3: Generate License Key

**Option A — You already have the client's fingerprint** (from a previous visit or sent remotely):

```powershell
cd "$repoDir\tools\license-generator"

# Generate license (on YOUR machine — requires vendor_private.key in this folder)
python generate_license.py `
    --customer "Shree Ram Stone Crusher Pvt Ltd" `
    --hostname "CLIENT-PC" `
    --fingerprint fingerprint.json `
    --expires 2027-04-10 `
    --output license.key
```

> **If you get "vendor_private.key not found":** Ask the senior developer for the
> keypair, or generate one (see Section 0.1 Step 9). The private key stays on the
> vendor machine — never give it to clients or commit to git.

**Option B — First deployment, no fingerprint yet:**

Skip this step. At the client site, run `show_fingerprint.py` on their PC first:

```powershell
# ON THE CLIENT PC (during visit):
cd C:\weighbridge\backend
python show_fingerprint.py
# → Creates fingerprint.json
# → Copy this file to USB drive, bring back to office
```

Then generate the license at your office and send it to the client (email/WhatsApp)
or install remotely via Cloudflare Tunnel.

**Option C — Get fingerprint remotely (if client has TeamViewer/AnyDesk):**

Connect to the client PC remotely and run these commands in PowerShell:
```powershell
# These commands collect the hardware fingerprint WITHOUT needing Python
$cpu = (Get-WmiObject Win32_Processor).ProcessorId
$mb  = (Get-WmiObject Win32_BaseBoard).SerialNumber
$disk = (Get-WmiObject Win32_DiskDrive | Select-Object -First 1).SerialNumber
$hostname = $env:COMPUTERNAME

# Display the values — copy these and send to senior developer
Write-Host "Hostname:     $hostname"
Write-Host "CPU ID:       $cpu"
Write-Host "Motherboard:  $mb"
Write-Host "Disk Serial:  $disk"
```
Send the output to the senior developer who will generate `license.key`.

> **License validity:** Set expiry 1 year ahead. You can generate a renewal license
> anytime — just re-run `generate_license.py` with the same fingerprint and new expiry.

### Step 3.4: Generate Deployment Package

```powershell
cd scripts

.\Generate-DeploymentConfig.ps1 `
    -ClientName "Shree Ram Stone Crusher Pvt Ltd" `
    -ClientId "shreeram" `
    -TunnelToken "eyJhIjoiNGY..." `
    -R2AccessKey "abc123def456" `
    -R2SecretKey "xyz789secret" `
    -R2AccountId "1234abcd5678efgh" `
    -LicenseKeyPath ".\licenses\shreeram.key" `
    -Domain "weighbridge.yourdomain.com" `
    -TelegramBotToken "8780469008:AAF3..." `
    -TelegramChatId "6613370540"
```

This creates:
```
deployment-packages/shreeram/
    deploy-config.json    # All client-specific settings
    license.key           # Hardware-locked license
    CHECKLIST.txt         # Step-by-step field guide
    DEPLOY.bat            # Double-click installer
```

### Step 3.5: Prepare USB Drive

Copy these to a USB drive:
```
USB Drive/
    deployment-packages/shreeram/     # Config package (from Step 3.4)
    weighbridge-full-1.0.0/           # Release files (from Section 0.4)
    Docker Desktop Installer.exe      # Download from docker.com (if client needs it)
```

> **Note:** The `scripts/` folder is already inside `weighbridge-full-1.0.0/scripts/`
> (copied during Section 0.4 packaging). No need to copy it separately.

**Verify USB contents before leaving:**
```powershell
# Check USB drive (replace D: with your USB drive letter)
$usb = "D:"

# Must exist:
@(
    "$usb\deployment-packages\shreeram\deploy-config.json",
    "$usb\deployment-packages\shreeram\license.key",
    "$usb\deployment-packages\shreeram\DEPLOY.bat",
    "$usb\weighbridge-full-1.0.0\backend\weighbridge_server.exe",
    "$usb\weighbridge-full-1.0.0\frontend\dist\index.html",
    "$usb\weighbridge-full-1.0.0\scripts\Deploy-Full.ps1",
    "$usb\weighbridge-full-1.0.0\scripts\nssm.exe",
    "$usb\weighbridge-full-1.0.0\docker-compose.yml"
) | ForEach-Object {
    if (Test-Path $_) { Write-Host "[OK] $_" -ForegroundColor Green }
    else { Write-Host "[MISSING] $_" -ForegroundColor Red }
}
```

---

## 4. Client Site Deployment

### FIRST: Enable PowerShell Scripts

On the client PC, open **PowerShell as Administrator** and run:

```powershell
Set-ExecutionPolicy RemoteSigned -Force
```

This allows `.ps1` scripts to run. Without this, every script will fail with _"cannot be loaded because running scripts is disabled"_.

### Option A: One-Click Deployment (Recommended)

1. Insert USB drive
2. Open `deployment-packages/shreeram/` folder
3. Right-click **DEPLOY.bat** > **Run as administrator**
4. Wait for all 6 phases to complete (~10-15 minutes)

### Option B: Step-by-Step Deployment

```powershell
# Run as Administrator
cd D:\scripts  # (USB drive)

.\Deploy-Full.ps1 `
    -ConfigFile "D:\deployment-packages\shreeram\deploy-config.json" `
    -ReleaseDir "D:\weighbridge-full-1.0.0"
```

### Deployment Phases

| Phase | Duration | What Happens |
|-------|----------|-------------|
| **1. System Check** | 5 sec | Verifies Windows version, RAM, disk, Docker |
| **2. Application Install** | 2-5 min | Copies files, starts PostgreSQL, registers services |
| **3. Security Hardening** | 1-2 min | Service account, ACLs, DPAPI, firewall |
| **4. Cloudflare Tunnel** | 1-2 min | Downloads cloudflared, installs as service |
| **5. Cloud Backup** | 2-3 min | Installs rclone, configures R2, runs test backup |
| **6. Verification** | 30 sec | Checks all services, security, connectivity |

### Post-Install Configuration (Manual)

After automated deployment completes, do these steps WITH the client:

**A. Disable PC Sleep** (CRITICAL — otherwise services stop when PC sleeps):
```powershell
# Run in PowerShell as Administrator:
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /change monitor-timeout-ac 0
Write-Host "Sleep and hibernate disabled." -ForegroundColor Green
```
Or manually: Settings > System > Power & Sleep > Set everything to **Never**.

**B. Application Setup** (in the browser at `http://localhost:9000`):

1. **Login**: username `admin`, password `admin123`
2. **Change admin password** immediately (click username bottom-left > Change Password)
3. **Settings > Company**: Enter company name, GSTIN, PAN, address, bank details
4. **Settings > Weight Scale**: Select COM port, baud rate, protocol matching the scale
5. **Settings > Cameras**: Enter front and top camera HTTP snapshot URLs
6. **Settings > Tally**: Enter Tally host (`localhost`) and port (`9002`)
7. **Settings > Notifications > Telegram**: Enter bot token, enable
8. **Notifications > Recipients**: Add owner/staff Telegram chat IDs
9. **Create Financial Year**: e.g., 2025-26 (April 2025 to March 2026)
10. **Create Users**: Operator, accountant, sales executive accounts
11. **Test Transaction**: Create token > weigh > complete > invoice > print PDF > verify Telegram alert

---

## 5. Cloudflare Tunnel Setup

### Standalone Installation

If you need to set up the tunnel separately (not via Deploy-Full.ps1):

```powershell
# Run as Administrator
.\Setup-CloudflareTunnel.ps1 -TunnelToken "eyJhIjoiNGY..."
```

### What It Does

1. Downloads `cloudflared.exe` from GitHub releases
2. Installs it to `C:\weighbridge\cloudflared\`
3. Registers as a Windows service (`cloudflared`)
4. Configures auto-start on boot
5. Establishes outbound-only encrypted tunnel to Cloudflare

### Verify Tunnel

```powershell
# Check service status
Get-Service cloudflared

# Check tunnel connectivity
C:\weighbridge\cloudflared\cloudflared.exe tunnel info
```

### How Users Access

1. User opens `https://weighbridge-shreeram.yourdomain.com`
2. Cloudflare Zero Trust shows email OTP form
3. User enters their email, receives OTP code
4. After verification, user sees the Weighbridge login page
5. User logs in with their Weighbridge credentials (normal JWT auth)

---

## 6. Cloud Backup Setup

### Standalone Installation

```powershell
# Run as Administrator
.\Setup-CloudBackup.ps1 `
    -R2AccessKey "abc123" `
    -R2SecretKey "xyz789" `
    -R2AccountId "1234abcd" `
    -ClientId "shreeram" `
    -TelegramBotToken "8780469008:AAF3..." `
    -TelegramChatId "6613370540"
```

### What Gets Installed

| Component | Location | Purpose |
|-----------|----------|---------|
| rclone.exe | `C:\weighbridge\tools\` | S3-compatible upload tool |
| rclone.conf | `C:\weighbridge\tools\` | R2 credentials (ACL-locked) |
| cloud-backup-config.json | `C:\weighbridge\` | Backup settings (ACL-locked) |
| Scheduled task | Windows Task Scheduler | `WeighbridgeCloudBackup` — daily 2 AM |

### Backup Process (Daily at 2 AM)

```
Step 1: pg_dump database → weighbridge_20260410_020015.sql
Step 2: Compress → .sql.gz (typically 60-80% compression)
Step 3: Encrypt with AES-256 → .sql.gz.enc
Step 4: Upload to R2 → weighbridge-backups/shreeram/weighbridge_20260410_020015.sql.gz.enc
Step 5: Prune local backups older than 7 days
Step 6: Prune R2 backups older than 90 days
Step 7: Write backup-status.json (for dashboard display)
Step 8: Send Telegram notification (success or failure)
```

### Monitoring Backups

**Via Dashboard**: Go to **Backup** page — the cloud backup status card shows:
- Last backup time and size
- Health status (green/red)
- R2 storage location
- Next scheduled backup

**Via Telegram**: Receive automated notifications:
- On success: file name, size, duration
- On failure: error message, log file path

**Manual Trigger**:
```powershell
# Run backup immediately (as Administrator)
powershell -File C:\weighbridge\scripts\Backup-ToCloud.ps1
```

### Backup Retention

| Location | Retention | Encryption |
|----------|-----------|-----------|
| Local disk | 7 days | AES-256 |
| Cloudflare R2 | 90 days | AES-256 + R2 server-side |

---

## 7. Post-Deployment Verification

Run the verification script to confirm everything is working:

```powershell
.\Verify-Deployment.ps1 -PublicUrl "https://weighbridge-shreeram.yourdomain.com"
```

### Verification Checks

**Services:**
- WeighbridgeBackend service running
- WeighbridgeFrontend service running
- cloudflared service running
- PostgreSQL running (Docker or native)

**Security:**
- DPAPI secrets.dpapi exists
- No .env.bak on disk (must be stored offline)
- License key present and valid
- BitLocker enabled on C: drive
- Firewall: PostgreSQL (5432) blocked externally
- Firewall: App ports (9000, 9001) open

**Connectivity:**
- Backend responds on localhost:9001
- Frontend responds on localhost:9000
- Public URL accessible via Cloudflare Tunnel
- Zero Trust gate redirects to email OTP (expected)

**Backup:**
- WeighbridgeCloudBackup scheduled task exists
- rclone installed
- Backup config file present
- Last backup status healthy

**Hardware:**
- Serial ports detected (weight scale)
- System specs logged

### Output

The script generates:
- Color-coded terminal output (PASS/FAIL/WARN)
- JSON report at `C:\weighbridge\deployment-report.json`

---

## 8. Security Layers

The deployment pipeline implements 9 layers of security:

| Layer | Component | What It Protects Against |
|-------|-----------|------------------------|
| 1 | **BitLocker** (full disk encryption) | Physical theft — disk unreadable without PIN |
| 2 | **DPAPI** (machine-locked secrets) | Stolen disk — DB password and API keys unreadable on different PC |
| 3 | **Hardware License** (Ed25519 signed, CPU/MB/Disk fingerprint) | Software cloning — won't run on different hardware |
| 4 | **Cloudflare Zero Trust** (email OTP) | Unauthorized remote access — only whitelisted emails |
| 5 | **Cloudflare Tunnel** (outbound-only) | Network attacks — no open ports, no public IP |
| 6 | **AES-256 Encrypted Backups** | Backup theft — R2 files unreadable without key |
| 7 | **Windows Service Account** (least privilege) | Privilege escalation — app runs as non-admin user |
| 8 | **Firewall Rules** (PostgreSQL blocked) | Database attacks — only localhost can connect |
| 9 | **Nuitka Binary** (compiled .exe, no .py) | Source code theft — native binary, no Python source |

### What Happens If the Machine Is Stolen?

1. Thief **cannot read the disk** (BitLocker requires PIN at boot)
2. Even if disk is mounted elsewhere, **secrets are unreadable** (DPAPI is machine-locked)
3. Even if they bypass encryption, **software won't run** (license bound to original hardware)
4. **You still have all data** — restore from R2 backup onto a new machine in 30 minutes
5. **Remote access is cut** — tunnel token is tied to your Cloudflare account, not the machine

### Recovery After Theft

1. Set up a new Windows machine
2. Run `Deploy-Full.ps1` with the same deployment package
3. Restore database from latest R2 backup
4. Update tunnel to point to new machine's cloudflared
5. Generate new license key for new hardware fingerprint
6. Operations resume within 1-2 hours

---

## 9. Backup & Recovery

### Restore From Cloud Backup

```powershell
# 1. List available R2 backups
C:\weighbridge\tools\rclone.exe ls weighbridge-r2:weighbridge-backups/shreeram/

# 2. Download the backup you want
C:\weighbridge\tools\rclone.exe copy `
    weighbridge-r2:weighbridge-backups/shreeram/weighbridge_20260410_020015.sql.gz.enc `
    C:\weighbridge\backups\

# 3. Decrypt (using PowerShell — same AES key from cloud-backup-config.json)
# Or use the app's built-in Backup > Restore page

# 4. Via the app UI: Upload the .enc file to the Backup page and click Restore
```

### Restore Via Application UI

1. Download the backup `.enc` file from R2
2. Place it in `C:\weighbridge\backups\`
3. Go to **Backup** page in the application
4. Find the file in the list
5. Click the **Restore** button (requires admin role)
6. Confirm the destructive restore operation

---

## 10. Troubleshooting

### Cloudflare Tunnel Not Connecting

```powershell
# Check service status
Get-Service cloudflared

# View recent logs
Get-EventLog -LogName Application -Source cloudflared -Newest 20

# Restart service
Restart-Service cloudflared

# Reinstall if needed
C:\weighbridge\cloudflared\cloudflared.exe service uninstall
.\Setup-CloudflareTunnel.ps1 -TunnelToken "<new-token>"
```

### Backup Failing

```powershell
# Check backup log
Get-Content C:\weighbridge\logs\cloud-backup.log -Tail 50

# Check status file
Get-Content C:\weighbridge\backup-status.json | ConvertFrom-Json

# Test R2 connectivity
C:\weighbridge\tools\rclone.exe lsd weighbridge-r2:weighbridge-backups/

# Run backup manually
.\Backup-ToCloud.ps1 -ConfigFile C:\weighbridge\cloud-backup-config.json
```

### Backend Not Starting

```powershell
# Check service
Get-Service WeighbridgeBackend

# View logs
Get-Content C:\weighbridge\logs\backend_stderr.log -Tail 50

# Test PostgreSQL
docker exec weighbridge_db psql -U weighbridge -c "SELECT 1"

# Restart
Restart-Service WeighbridgeBackend
```

### Public URL Shows Error

1. Check tunnel: `Get-Service cloudflared` — should be Running
2. Check backend: `Invoke-WebRequest http://localhost:9001/api/v1/auth/me` — should return 401
3. Check Cloudflare dashboard: Tunnel status should be "Healthy"
4. Check Zero Trust policy: Ensure your email is in the allowed list

---

## 11. Cost Summary

| Item | Cost | Notes |
|------|------|-------|
| Cloudflare Tunnel | FREE | Unlimited bandwidth |
| Cloudflare Zero Trust | FREE | Up to 50 users |
| Cloudflare R2 | FREE | 10 GB storage, zero egress fees |
| Cloudflare CDN + SSL | FREE | Auto HTTPS + DDoS protection |
| Domain name | ~800/year | .com or .in domain |
| **Total** | **~800/year** | All infrastructure costs |

---

## 12. Script Reference

### `Deploy-Full.ps1` — Master Orchestrator

```powershell
.\Deploy-Full.ps1 `
    -ConfigFile "deploy-config.json" `   # Required: client config
    -ReleaseDir "weighbridge-full-1.0.0" # Optional: release package path
    -SkipPhase @(4,5)                    # Optional: skip specific phases
```

Runs 6 phases: System Check > App Install > Security > Tunnel > Backup > Verify

### `Setup-CloudflareTunnel.ps1` — Tunnel Setup

```powershell
.\Setup-CloudflareTunnel.ps1 `
    -TunnelToken "eyJhIjoiNGY..."        # Required: from Cloudflare dashboard
    -InstallDir "C:\weighbridge\cloudflared"  # Optional: install location
```

Downloads cloudflared, installs as Windows service, configures auto-start.

### `Setup-CloudBackup.ps1` — R2 Backup Configuration

```powershell
.\Setup-CloudBackup.ps1 `
    -R2AccessKey "abc123"                # Required: R2 API key
    -R2SecretKey "xyz789"                # Required: R2 secret
    -R2AccountId "1234abcd"              # Required: Cloudflare account ID
    -ClientId "shreeram"                 # Required: client identifier
    -R2Bucket "weighbridge-backups"      # Optional: bucket name
    -TelegramBotToken "8780..."          # Optional: alert notifications
    -TelegramChatId "661337..."          # Optional: alert chat ID
```

Installs rclone, configures R2 credentials, creates daily 2 AM scheduled task.

### `Backup-ToCloud.ps1` — Daily Backup Script

```powershell
.\Backup-ToCloud.ps1 `
    -ConfigFile "C:\weighbridge\cloud-backup-config.json"
```

Runs as scheduled task. pg_dump > compress > AES-256 encrypt > upload R2 > prune > notify.

### `Verify-Deployment.ps1` — Health Check

```powershell
.\Verify-Deployment.ps1 `
    -PublicUrl "https://weighbridge-shreeram.domain.com"  # Optional: test tunnel
    -OutputFile "C:\weighbridge\deployment-report.json"    # Optional: report path
```

Checks services, security, connectivity, backup status. Outputs color-coded report.

### `Generate-DeploymentConfig.ps1` — Vendor Config Tool

```powershell
.\Generate-DeploymentConfig.ps1 `
    -ClientName "Shree Ram Stone Crusher Pvt Ltd" `
    -ClientId "shreeram" `
    -TunnelToken "eyJhIjoiNGY..." `
    -R2AccessKey "abc123" `
    -R2SecretKey "xyz789" `
    -R2AccountId "1234abcd" `
    -LicenseKeyPath ".\licenses\shreeram.key" `
    -Domain "weighbridge.example.com"
```

Creates deployment package folder with config JSON, license, checklist, and DEPLOY.bat.

---

## Quick Reference Card

```
VENDOR PREPARATION                     CLIENT SITE DEPLOYMENT
========================               ========================

1. Cloudflare Dashboard:               7. Insert USB drive
   - Create tunnel                     8. Run DEPLOY.bat (as Admin)
   - Set Zero Trust policy             9. Wait ~15 minutes
   - Note tunnel token                10. Change admin password

2. Generate license.key               11. Enter company details
   python generate_license.py         12. Configure weight scale
                                      13. Configure cameras
3. Generate deployment config         14. Create financial year
   Generate-DeploymentConfig.ps1      15. Create user accounts
                                      16. Test transaction
4. Copy to USB:
   - deployment-packages/client/      17. Verify deployment
   - weighbridge-full-x.x.x/             Verify-Deployment.ps1
   - scripts/
   - Docker Desktop Installer         18. Hand over to client
```

---

## 13. Common Mistakes (Read This First!)

### Mistake 1: "Scripts cannot be run on this system"

PowerShell blocks scripts by default. Fix:

```powershell
# Run this ONCE as Administrator on the client PC:
Set-ExecutionPolicy RemoteSigned -Force
```

### Mistake 2: Forgetting to Run as Administrator

**Every deployment script must run as Administrator.** If you see "Access denied" errors:

1. Right-click **Command Prompt** or **PowerShell** > **Run as administrator**
2. Then navigate to the script location and run it

### Mistake 3: Docker Desktop Not Running

The deployment needs Docker Desktop running (for PostgreSQL). Signs it's not running:
- Error: "docker: command not found"
- Error: "Cannot connect to Docker daemon"

**Fix:** Open Docker Desktop from Start Menu, wait for it to show "Docker Desktop is running", then retry.

### Mistake 4: Forgetting to Build Frontend Before Packaging

If you skip `npm run build`, the `frontend/dist/` folder will be empty or outdated. Always rebuild before creating a release package.

### Mistake 5: Using Wrong Port in vite.config.ts

- **Development:** proxy target can be any port (9001, 9003, etc.)
- **Production build:** The frontend is served as static files — no proxy is used. The backend runs on port 9001.

Before running `npm run build` for a release, open `frontend/vite.config.ts` and verify ALL proxy targets point to `localhost:9001`:
```typescript
// CORRECT for production build:
proxy: {
    '/api':     { target: 'http://localhost:9001' },
    '/ws':      { target: 'ws://localhost:9001' },
    '/uploads': { target: 'http://localhost:9001' },
}
```
If you see a different port (9003, 9005, etc.), change it to 9001 before building.

### Mistake 6: Not Saving .env.bak to USB

During DPAPI encryption, the `.env` file gets encrypted into `secrets.dpapi` and the original is renamed to `.env.bak`. This `.env.bak` is the ONLY way to recover secrets if you need to reinstall.

**You MUST:**
1. Copy `.env.bak` to the USB drive
2. Delete `.env.bak` from the client machine
3. Store the USB securely at your office

### Mistake 7: Forgetting to Add Client Email to Zero Trust

If the client can't access the public URL, they'll see a "blocked" page. Make sure their email is added to the Zero Trust Access policy in the Cloudflare dashboard.

### Mistake 8: Not Testing the Weighing Scale Before Leaving

Always do a complete test transaction before leaving the client site:
1. Create a token
2. Record first weight (gross)
3. Record second weight (tare)
4. Verify invoice is auto-created
5. Finalize invoice
6. Download and print PDF
7. Check Telegram notification received

### Mistake 9: Client Machine Goes to Sleep

If the client PC goes to sleep, all services stop (backend, tunnel, backups).

**Fix — Set the PC to never sleep:**
1. Settings > System > Power & Sleep
2. Set "When plugged in, turn off screen after" = **Never**
3. Set "When plugged in, PC goes to sleep after" = **Never**

### Mistake 10: R2 Bucket Doesn't Exist

If you get "bucket not found" errors during backup setup, create the bucket first:
1. Go to [Cloudflare Dashboard](https://dash.cloudflare.com)
2. R2 Object Storage > Create bucket
3. Name: `weighbridge-backups`

---

## 14. Uninstall / Rollback (If Deployment Fails)

If the deployment fails midway or you need to start over, follow these steps **in order** to cleanly remove everything. Run all commands in **PowerShell as Administrator**.

### Step 1: Stop and Remove Windows Services

```powershell
# Stop services (ignore errors if they don't exist)
Stop-Service WeighbridgeBackend -ErrorAction SilentlyContinue
Stop-Service WeighbridgeFrontend -ErrorAction SilentlyContinue
Stop-Service cloudflared -ErrorAction SilentlyContinue

# Remove NSSM services
$nssm = "C:\weighbridge\scripts\nssm.exe"
if (Test-Path $nssm) {
    & $nssm remove WeighbridgeBackend confirm
    & $nssm remove WeighbridgeFrontend confirm
}

# Remove cloudflared service
$cloudflared = "C:\weighbridge\cloudflared\cloudflared.exe"
if (Test-Path $cloudflared) {
    & $cloudflared service uninstall
}

Write-Host "Services removed." -ForegroundColor Green
```

### Step 2: Stop and Remove PostgreSQL Docker Container

```powershell
# Stop the database container
docker stop weighbridge_db

# Remove the container (WARNING: this deletes the database data!)
docker rm weighbridge_db

# Remove the Docker volume (WARNING: this permanently deletes ALL database data!)
docker volume rm weighbridge_pgdata

Write-Host "PostgreSQL container and data removed." -ForegroundColor Green
```

> **If you want to KEEP the database data** (e.g., to retry deployment):
> Skip the `docker volume rm` command. The data will persist for the next install.

### Step 3: Remove Scheduled Tasks

```powershell
# Remove backup scheduled task
Unregister-ScheduledTask -TaskName "WeighbridgeCloudBackup" -Confirm:$false -ErrorAction SilentlyContinue
Write-Host "Scheduled tasks removed." -ForegroundColor Green
```

### Step 4: Remove Firewall Rules

```powershell
Remove-NetFirewallRule -DisplayName "Weighbridge Backend" -ErrorAction SilentlyContinue
Remove-NetFirewallRule -DisplayName "Weighbridge Frontend" -ErrorAction SilentlyContinue
Remove-NetFirewallRule -DisplayName "Block External PostgreSQL" -ErrorAction SilentlyContinue
Write-Host "Firewall rules removed." -ForegroundColor Green
```

### Step 5: Remove Service Account (Optional)

```powershell
# Only if secure_setup.ps1 was run:
net user weighbridge_svc /delete 2>$null
Write-Host "Service account removed." -ForegroundColor Green
```

### Step 6: Delete Application Files

```powershell
# Remove the entire weighbridge folder
# WARNING: This deletes ALL application files, logs, and local backups!
Remove-Item -Path "C:\weighbridge" -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "Application files deleted." -ForegroundColor Green
```

### Step 7: Verify Clean State

```powershell
# Verify nothing remains
$checks = @(
    @{ Name = "App folder";    Path = "C:\weighbridge" },
    @{ Name = "Backend svc";   Check = { Get-Service WeighbridgeBackend -EA SilentlyContinue } },
    @{ Name = "Frontend svc";  Check = { Get-Service WeighbridgeFrontend -EA SilentlyContinue } },
    @{ Name = "Tunnel svc";    Check = { Get-Service cloudflared -EA SilentlyContinue } },
    @{ Name = "Backup task";   Check = { Get-ScheduledTask -TaskName WeighbridgeCloudBackup -EA SilentlyContinue } }
)

foreach ($c in $checks) {
    if ($c.Path) {
        $exists = Test-Path $c.Path
    } else {
        $exists = $null -ne (& $c.Check)
    }
    if ($exists) {
        Write-Host "  [STILL EXISTS] $($c.Name)" -ForegroundColor Red
    } else {
        Write-Host "  [CLEAN] $($c.Name)" -ForegroundColor Green
    }
}
```

### Partial Failure Recovery

If the deployment failed at a specific phase, you can **retry just that phase** instead of uninstalling everything:

| Failed At | Recovery Command |
|-----------|-----------------|
| Phase 1 (System Check) | Fix the reported issue (install Docker, free disk space) and re-run `Deploy-Full.ps1` |
| Phase 2 (App Install) | Re-run `Deploy-Full.ps1 -SkipPhase @(1)` |
| Phase 3 (Security) | Re-run `Deploy-Full.ps1 -SkipPhase @(1,2)` |
| Phase 4 (Tunnel) | Run `Setup-CloudflareTunnel.ps1 -TunnelToken "..."` standalone |
| Phase 5 (Backup) | Run `Setup-CloudBackup.ps1 ...` standalone |
| Phase 6 (Verify) | Run `Verify-Deployment.ps1` standalone — this is just a check, nothing to fix |

> **Tip:** The `-SkipPhase` parameter lets you skip phases that already completed
> successfully. For example, if Phase 1-3 passed but Phase 4 failed:
> ```powershell
> .\Deploy-Full.ps1 -ConfigFile "deploy-config.json" -SkipPhase @(1,2,3)
> ```

---

## Appendix A: File Locations on Client Machine

After deployment, these are the important file locations:

```
C:\weighbridge\
    backend\
        weighbridge_server.exe       # Application binary
        secrets.dpapi                # Encrypted secrets (DO NOT DELETE)
        app\templates\pdf\           # Invoice/quotation PDF templates
    frontend\
        dist\                        # React static files (HTML/CSS/JS)
    cloudflared\
        cloudflared.exe              # Tunnel binary
    tools\
        rclone.exe                   # Backup upload tool
        rclone.conf                  # R2 credentials (ACL-locked)
    backups\
        *.sql.enc                    # Local encrypted backups (7-day retention)
    logs\
        backend_stdout.log           # Application logs
        backend_stderr.log           # Application errors
        cloud-backup.log             # Backup job logs
    license.key                      # Hardware-bound license
    cloud-backup-config.json         # R2 backup settings (ACL-locked)
    backup-status.json               # Last backup status (read by dashboard)
    deployment-report.json           # Verification results
    docker-compose.yml               # PostgreSQL container config
```

---

## Appendix B: Updating an Existing Client

To push a new version to an already-deployed client:

```powershell
# Run all commands in PowerShell as Administrator on the CLIENT machine

# 1. Build new release at office (Section 0) and copy to USB drive

# 2. Stop services before replacing files
Stop-Service WeighbridgeBackend -Force
Stop-Service WeighbridgeFrontend -Force

# 3. Replace backend binary (from USB drive, e.g., D:\)
Copy-Item "D:\weighbridge-full-1.1.0\backend\weighbridge_server.exe" "C:\weighbridge\backend\" -Force

# 4. Replace frontend files
xcopy "D:\weighbridge-full-1.1.0\frontend\dist" "C:\weighbridge\frontend\dist\" /E /I /Y /Q

# 5. Replace templates (if changed)
xcopy "D:\weighbridge-full-1.1.0\backend\app\templates" "C:\weighbridge\backend\app\templates\" /E /I /Y /Q

# 6. Restart services
Start-Service WeighbridgeBackend
Start-Service WeighbridgeFrontend

# 7. Wait 10 seconds for backend to start, then verify
Start-Sleep -Seconds 10
.\Verify-Deployment.ps1
```

> **Database migrations run automatically** on backend startup (via main.py).
> No manual SQL migration steps are needed.

---

## Appendix C: Emergency Contacts

| Situation | Action |
|-----------|--------|
| App not loading | Check services: `Get-Service WeighbridgeBackend` |
| Can't access remotely | Check tunnel: `Get-Service cloudflared` |
| Backup failed | Check log: `C:\weighbridge\logs\cloud-backup.log` |
| Machine stolen | Restore from R2 backup to new machine (Section 9) |
| License expired | Generate new license.key and copy to `C:\weighbridge\` |
| Forgot admin password | Reset via PostgreSQL: connect to DB and update users table |
