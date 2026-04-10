# Weighbridge Invoice Software — Build & Deployment Guide

**Version:** 1.0
**Last Updated:** April 2026
**Audience:** Developer (Build) · IT Administrator (Installation)

---

## Table of Contents

1. [Overview](#overview)
2. [Part A — Building the Release (.exe)](#part-a--building-the-release-exe)
   - [A1. Prerequisites on Developer Machine](#a1-prerequisites-on-developer-machine)
   - [A2. Files to Remove Before Building](#a2-files-to-remove-before-building)
   - [A3. Generating a License Key for the Client](#a3-generating-a-license-key-for-the-client)
   - [A4. Running the Build](#a4-running-the-build)
   - [A5. What the Build Produces](#a5-what-the-build-produces)
3. [Part B — Installing at Client Site](#part-b--installing-at-client-site)
   - [B1. Prerequisites on Client Machine](#b1-prerequisites-on-client-machine)
   - [B2. Installing Docker Desktop (for PostgreSQL)](#b2-installing-docker-desktop-for-postgresql)
   - [B3. Copying the Release Package](#b3-copying-the-release-package)
   - [B4. Configuring the .env File](#b4-configuring-the-env-file)
   - [B5. Starting PostgreSQL Database](#b5-starting-postgresql-database)
   - [B6. Running Database Migrations](#b6-running-database-migrations)
   - [B7. Placing the License Key](#b7-placing-the-license-key)
   - [B8. Installing Windows Services](#b8-installing-windows-services)
   - [B9. First Login and Initial Setup](#b9-first-login-and-initial-setup)
   - [B10. Setting Up the USB Guard (Optional)](#b10-setting-up-the-usb-guard-optional)
4. [Part C — Go-Live Checklist](#part-c--go-live-checklist)
5. [Part D — Updating to a New Version](#part-d--updating-to-a-new-version)
6. [Part E — Troubleshooting](#part-e--troubleshooting)

---

## Overview

The deployment architecture uses:

| Component | Technology | Port |
|-----------|-----------|------|
| Backend API | Python (Nuitka .exe) + FastAPI | 9001 |
| Frontend | React (static files via `serve`) | 9000 |
| Database | PostgreSQL 16 (Docker container) | 5432 (localhost only) |
| Service Manager | NSSM (Windows service wrapper) | — |

Users access the software by opening a browser at `http://localhost:9000` or `http://<server-ip>:9000` from any PC on the same LAN.

---

## Part A — Building the Release (.exe)

This part is performed **by the developer** on their own machine, NOT at the client site.

---

### A1. Prerequisites on Developer Machine

Install the following before building:

**1. Python 3.11+**
```
https://www.python.org/downloads/
```
During install, check "Add Python to PATH".

Verify:
```
python --version
```

**2. Nuitka and all backend dependencies**
```
cd backend
pip install -r requirements.txt
pip install nuitka ordered-set zstandard
```

**3. MSVC C Compiler (Visual Studio Build Tools)**

Nuitka requires a C compiler to produce the .exe.

- Download from: https://visualstudio.microsoft.com/downloads/
- Scroll to "Tools for Visual Studio" → "Build Tools for Visual Studio 2022"
- Install with workload: **"Desktop development with C++"**
- This is a ~4 GB download

Verify (run from Developer Command Prompt or PowerShell):
```
cl.exe
```

**4. Node.js 18+ with npm**
```
https://nodejs.org/en/download/
```

Verify:
```
node --version
npm --version
```

---

### A2. Files to Remove Before Building

**CRITICAL: These files must NEVER be included in the build package shipped to clients.**

| File / Folder | Why Remove | Location |
|---|---|---|
| `tools/license-generator/vendor_private.key` | **Contains the private signing key — if leaked, anyone can forge licenses** | `tools/license-generator/` |
| `tools/license-generator/serial_counter.txt` | License serial counter — not needed at client | `tools/license-generator/` |
| `backend/.env` | Contains dev database password and secret keys | `backend/` |
| `backend/alembic/` | Database migration source code | `backend/` |
| `backend/app/` | All Python source code (replaced by compiled .exe) | `backend/` |
| `frontend/src/` | React source code (replaced by built `dist/`) | `frontend/` |
| `frontend/node_modules/` | 500MB+ of dev dependencies — not needed in release | `frontend/` |
| `*.py` (all Python files) | Source code — replaced by .exe | root & subfolders |
| `backend/venv/` | Python virtual environment — not needed | `backend/` |
| `.git/` | Git history — never ship to clients | root |
| `backend/backup/` | Any dev backup .sql files | `backend/backup/` |

**The build script (`scripts/build-release.ps1`) creates a clean release folder automatically** — you do NOT manually delete these. The build output at `dist/weighbridge-vX.X.X/` only contains what is needed.

**Verify the release folder does NOT contain:**
```powershell
# Run after build — these should return nothing
Get-ChildItem dist\weighbridge-v*\ -Recurse -Filter "*.py" | Select-Object FullName
Get-ChildItem dist\weighbridge-v*\ -Recurse -Filter "*.key" -Exclude "license.key" | Select-Object FullName
Get-ChildItem dist\weighbridge-v*\ -Name ".git" -ErrorAction SilentlyContinue
```

---

### A3. Generating a License Key for the Client

Before building, generate a license key bound to the **client's machine hostname**.

**Step 1 — Find the client machine hostname**

On the client's Windows PC, open Command Prompt and run:
```
hostname
```
Example output: `WEIGHBRIDGE-PC`

**Step 2 — Generate the license key**

On your **developer machine** (where `vendor_private.key` is stored):

```
cd tools\license-generator

python generate_license.py ^
  --customer "ABC Stone Crushers Pvt Ltd" ^
  --hostname "WEIGHBRIDGE-PC" ^
  --expires 2027-04-02 ^
  --features invoicing,private_invoices,tally,gst_reports ^
  --max-users 5 ^
  --output license.key
```

Parameters:
| Parameter | Description | Example |
|---|---|---|
| `--customer` | Client company name (for display only) | `"ABC Stone Crushers"` |
| `--hostname` | Exact hostname of client PC (case-insensitive) | `WEIGHBRIDGE-PC` |
| `--expires` | License expiry date in YYYY-MM-DD format | `2027-04-02` |
| `--features` | Comma-separated feature list | `invoicing,private_invoices,tally` |
| `--max-users` | Maximum concurrent users allowed | `5` |
| `--output` | Output file path | `license.key` |

**Step 3 — Verify the generated key**
```
python generate_license.py --verify license.key
```

Expected output:
```
VALID LICENSE
  Customer:      ABC Stone Crushers Pvt Ltd
  Hostname:      WEIGHBRIDGE-PC
  Serial:        WB-2026-0042
  Expires:       2027-04-02 (365 days remaining)
  Features:      invoicing, private_invoices, tally, gst_reports
```

Keep the `license.key` file ready — it goes into the release package.

---

### A4. Running the Build

**Step 1 — Open PowerShell as Administrator**

Right-click the Start menu → "Windows PowerShell (Admin)"

**Step 2 — Navigate to the project root**
```powershell
cd C:\path\to\workspace_Weighbridge
```

**Step 3 — Allow script execution (one-time)**
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

**Step 4 — Run the build script**
```powershell
.\scripts\build-release.ps1 -Version "1.0.0"
```

Replace `1.0.0` with the actual version number.

**What happens during build:**

| Phase | Duration | Action |
|---|---|---|
| Clean | < 1 min | Removes previous `dist/weighbridge-v1.0.0/` if it exists |
| Frontend build | 1–2 min | `npm ci && npm run build` → produces `frontend/dist/` |
| Backend compile | **10–25 min** | Nuitka compiles Python to C then to native .exe |
| Package | < 1 min | Copies all files into release folder |

> **Note:** The first Nuitka build is slow (10–25 minutes) because it downloads and compiles a C runtime. Subsequent builds are faster (5–10 minutes) due to caching.

**Step 5 — Copy the license key into the release**
```powershell
Copy-Item license.key dist\weighbridge-v1.0.0\license.key
```

**Step 6 — Verify build output**
```powershell
Get-ChildItem dist\weighbridge-v1.0.0\
```

---

### A5. What the Build Produces

```
dist/weighbridge-v1.0.0/
├── weighbridge-backend.exe       # Compiled backend (single file, ~80-120 MB)
├── license.key                   # Per-client license file
├── .env.template                 # Configuration template
├── docker-compose.yml            # PostgreSQL-only docker config
├── frontend/
│   └── dist/                     # Built React app (HTML/JS/CSS)
├── tools/
│   └── nssm.exe                  # Windows service manager
└── scripts/
    ├── install-services.ps1      # First-time installation script
    └── manage-services.ps1       # Start/stop/restart/logs utility
```

Zip this folder and deliver to the client via USB drive, Google Drive, WhatsApp, or any file transfer method.

---

## Part B — Installing at Client Site

This part is performed **by the IT installer** at the client's premises.

---

### B1. Prerequisites on Client Machine

| Requirement | Minimum | How to Check |
|---|---|---|
| Windows | Windows 10 Pro/Home (64-bit) or Windows 11 | `winver` in Run dialog |
| RAM | 8 GB | Task Manager → Performance → Memory |
| Disk | 5 GB free space | File Explorer |
| Network | LAN (for multi-user access) | Optional |
| Internet | Required for initial setup only | — |
| Weighbridge Scale | Serial/USB COM port | Device Manager |

> **Windows Home users:** Docker Desktop requires WSL2. Windows Home does NOT support Hyper-V, but WSL2 works on Home since Windows 10 v2004 (May 2020).

---

### B2. Installing Docker Desktop (for PostgreSQL)

PostgreSQL runs in Docker. Only Docker Desktop needs to be installed — the application itself does NOT run in Docker.

**Step 1 — Enable WSL2 (Windows Subsystem for Linux)**

Open PowerShell as Administrator and run:
```powershell
wsl --install
```
Restart the computer when prompted.

**Step 2 — Download and install Docker Desktop**

Go to: https://www.docker.com/products/docker-desktop/

- Download "Docker Desktop for Windows"
- Run the installer, keep all defaults
- Choose "Use WSL 2 based engine" when asked
- Restart if required

**Step 3 — Verify Docker is working**

Open Command Prompt:
```
docker --version
docker ps
```

Both commands should run without errors.

**Step 4 — Configure Docker to start with Windows**

Docker Desktop → Settings → General → Check "Start Docker Desktop when you log in"

---

### B3. Copying the Release Package

**Option 1 — USB Drive**
1. Copy the `weighbridge-v1.0.0.zip` (or folder) from USB to `C:\weighbridge\`
2. Extract if zipped: right-click → "Extract All"

**Option 2 — Network / Google Drive**
1. Download to `C:\weighbridge\`
2. Extract if needed

Final structure should be:
```
C:\weighbridge\
├── weighbridge-backend.exe
├── license.key
├── .env.template
├── docker-compose.yml
├── frontend\dist\
├── tools\nssm.exe
└── scripts\
    ├── install-services.ps1
    └── manage-services.ps1
```

---

### B4. Configuring the .env File

**Step 1 — Copy the template**

In File Explorer or Command Prompt:
```
copy C:\weighbridge\.env.template C:\weighbridge\.env
```

**Step 2 — Open .env in Notepad**
```
notepad C:\weighbridge\.env
```

**Step 3 — Edit the values**

```env
# Database connection — CHANGE THE PASSWORD
DATABASE_URL=postgresql+asyncpg://weighbridge:YOUR_DB_PASSWORD@localhost:5432/weighbridge
DATABASE_URL_SYNC=postgresql+psycopg://weighbridge:YOUR_DB_PASSWORD@localhost:5432/weighbridge

# Secret key for JWT tokens — GENERATE A UNIQUE KEY (see below)
SECRET_KEY=CHANGE_ME

# Encryption key for private invoices — GENERATE A UNIQUE KEY (see below)
PRIVATE_DATA_KEY=CHANGE_ME

# Leave these unchanged
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=480
```

**Step 4 — Generate SECRET_KEY and PRIVATE_DATA_KEY**

If Python is installed on the machine, run:
```
python -c "import secrets; print(secrets.token_hex(32))"
```

Run this **twice** to get two different keys — one for `SECRET_KEY`, one for `PRIVATE_DATA_KEY`.

If Python is not installed, use any 64-character random string from: https://www.random.org/strings/

**Step 5 — Note the database password you chose**

You will use this same password when starting PostgreSQL in the next step.

---

### B5. Starting PostgreSQL Database

**Step 1 — Edit docker-compose.yml to set the database password**

Open `C:\weighbridge\docker-compose.yml` in Notepad and update the password to match what you put in `.env`:

```yaml
environment:
  POSTGRES_USER: weighbridge
  POSTGRES_PASSWORD: YOUR_DB_PASSWORD    # <-- change this
  POSTGRES_DB: weighbridge
```

**Step 2 — Open Command Prompt as Administrator**

Right-click Start → "Command Prompt (Admin)"

**Step 3 — Start the PostgreSQL container**
```
cd C:\weighbridge
docker compose up -d
```

Expected output:
```
[+] Running 2/2
 ✔ Network weighbridge_default   Created
 ✔ Container weighbridge_db      Started
```

**Step 4 — Verify PostgreSQL is running**
```
docker ps
```

You should see:
```
CONTAINER ID   IMAGE               STATUS
abc123def456   postgres:16-alpine  Up 2 minutes
```

**Step 5 — Set Docker to auto-start on boot**

Docker Desktop already auto-starts with Windows (if configured in Step B2). The container has `restart: unless-stopped`, so PostgreSQL will automatically restart with Docker.

---

### B6. Running Database Migrations

This creates all required tables in the database.

**Method: Run migrations using the compiled exe**

Open Command Prompt as Administrator:
```
cd C:\weighbridge

rem Set environment variables for migration
set DATABASE_URL_SYNC=postgresql+psycopg://weighbridge:YOUR_DB_PASSWORD@localhost:5432/weighbridge

rem Run migrations
weighbridge-backend.exe --migrate
```

> **Note:** If the `--migrate` flag is not available in this build, migrations run automatically on first startup. Proceed to Step B8 and check logs for migration status.

**Verify the database was created:**
```
docker exec weighbridge_db psql -U weighbridge -c "\dt" weighbridge
```

You should see a list of tables including `users`, `companies`, `tokens`, `invoices`, etc.

---

### B7. Placing the License Key

The `license.key` file should already be inside `C:\weighbridge\` (it was included in the release package in Step A4 → A5).

**Verify the license key:**

Open Command Prompt:
```
cd C:\weighbridge
weighbridge-backend.exe --check-license
```

Expected output:
```
VALID LICENSE
  Customer:      ABC Stone Crushers Pvt Ltd
  Hostname:      WEIGHBRIDGE-PC
  Serial:        WB-2026-0042
  Expires:       2027-04-02 (365 days remaining)
```

**If the license check fails:**

| Error | Cause | Fix |
|---|---|---|
| "License file not found" | `license.key` missing | Copy file to `C:\weighbridge\` |
| "Bound to hostname X but this machine is Y" | Wrong hostname was used when generating | Get correct hostname (`hostname` command), regenerate license |
| "License expired" | Past expiry date | Contact vendor for renewal |
| "Signature verification FAILED" | File corrupted during transfer | Request a fresh copy of the license file |

---

### B8. Installing Windows Services

This registers the backend and frontend as Windows services that auto-start with the PC.

**Step 1 — Open PowerShell as Administrator**

Right-click Start → "Windows PowerShell (Admin)"

**Step 2 — Allow script execution**
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

**Step 3 — Run the installer**
```powershell
cd C:\weighbridge
.\scripts\install-services.ps1
```

**What this script does:**
1. Locates or downloads NSSM (service manager)
2. Reads variables from `.env`
3. Builds the frontend (`npm run build`)
4. Installs `serve` package globally for static file hosting
5. Registers `WeighbridgeBackend` service on port 9001
6. Registers `WeighbridgeFrontend` service on port 9000
7. Starts both services
8. Shows status

**Expected final output:**
```
============================================================
                  Services Registered!
============================================================

  Backend  URL : http://localhost:9001
  Frontend URL : http://localhost:9000
  API Docs     : http://localhost:9001/docs
  Log files    : C:\weighbridge\logs
```

**Step 4 — Verify services are running**
```powershell
.\scripts\manage-services.ps1 status
```

Output should show both services as "Running":
```
  WeighbridgeBackend           Running
  WeighbridgeFrontend          Running
```

**Step 5 — Test the application in browser**

Open Microsoft Edge or Chrome:
```
http://localhost:9000
```

You should see the Weighbridge login page.

---

### B9. First Login and Initial Setup

**Default admin credentials:**
```
Username:  admin
Password:  admin123
```

> **IMPORTANT: Change the admin password immediately after first login.**
> Settings → (top-right user menu) → Change Password

**Initial configuration steps (do these in order):**

1. **Company Setup**
   - Settings → Company
   - Enter company name, GSTIN, PAN, address, state, phone
   - Upload company logo
   - Set bank account details

2. **Financial Year**
   - Settings → Financial Years
   - Create the current financial year (e.g., April 2026 – March 2027)
   - Click "Activate"

3. **Invoice Prefixes**
   - Settings → Invoice Prefixes
   - Set sales invoice prefix (e.g., `WB-SALE`)
   - Set purchase invoice prefix (e.g., `WB-PUR`)

4. **Add Users**
   - Settings → Users
   - Create operator, accountant accounts with appropriate roles
   - Assign roles: `admin`, `operator`, `accountant`, `viewer`

5. **Products and Categories**
   - Products → Add categories (e.g., Stone, Sand, Gravel)
   - Add products with HSN codes and GST rates

6. **Add Parties**
   - Parties → Add customers and suppliers
   - Enter GSTIN for GST-registered parties

7. **Add Vehicles**
   - Vehicles → Add vehicle registration numbers with default tare weights

8. **Configure Weighbridge Scale**
   - Settings → Scale Configuration (or via API)
   - Set COM port (check Device Manager for correct port, e.g., `COM3`)
   - Set baud rate (default: 9600)

---

### B10. Setting Up the USB Guard (Optional)

The USB Guard protects private/non-GST invoices. Skip if not using private invoices.

**Step 1 — Insert a dedicated USB drive** (use a pen drive exclusively for this purpose)

**Step 2 — Open Command Prompt in the project folder**
```
cd C:\weighbridge
weighbridge-backend.exe --setup-usb
```

Or run the Python setup utility if running from source:
```
python backend\setup_usb_key.py
```

This writes a `.weighbridge_key` file to the USB drive and registers its UUID in the database.

**Step 3 — Test USB Guard**
- Go to Private Invoices in the application
- With USB inserted: should show invoice list
- With USB removed: should show lock screen

**Step 4 — Set Recovery PIN (for when USB is lost)**
- Settings → USB Guard → Recovery
- Set a PIN and validity period (e.g., 48 hours)
- Write the PIN in a secure, physical location

---

## Part C — Go-Live Checklist

Before handing over to the client, verify each item:

### Security
- [ ] Admin password changed from default `admin123`
- [ ] `SECRET_KEY` in `.env` is a unique 64-character random string
- [ ] `PRIVATE_DATA_KEY` in `.env` is a unique 64-character random string
- [ ] Database password in `.env` and `docker-compose.yml` match and are not default
- [ ] License key is valid (`license.key` is in `C:\weighbridge\`)
- [ ] License expires date is correct (verify with client)

### Services
- [ ] `WeighbridgeBackend` service is Running (check Services console or manage-services.ps1 status)
- [ ] `WeighbridgeFrontend` service is Running
- [ ] Docker `weighbridge_db` container is Running (`docker ps`)
- [ ] Both services set to auto-start (should be automatic with NSSM)
- [ ] Application accessible at `http://localhost:9000`

### Data Setup
- [ ] Company details entered correctly (name, GSTIN, PAN, address)
- [ ] Financial year created and activated
- [ ] Invoice number prefixes configured
- [ ] Admin password changed
- [ ] Test user accounts created for operators
- [ ] At least one product/category entered
- [ ] At least one party entered

### Hardware
- [ ] Weighbridge scale COM port configured and weight readings working
- [ ] Test weight reading displayed on Token page (real-time weight ticker)
- [ ] USB Guard configured (if using private invoices)

### Backup
- [ ] Take a first backup: Backup → Create Backup
- [ ] Confirm backup file appears in list
- [ ] Note backup file location: `C:\weighbridge\backend\backup\`

### Training
- [ ] Operator trained on token creation and weighment process
- [ ] Accountant trained on invoice finalization and payments
- [ ] Admin knows how to restart services if needed
- [ ] Emergency contact (vendor phone number) noted

---

## Part D — Updating to a New Version

When a new version is released:

**Step 1 — Receive the new release package from vendor**

The package will be a zip file: `weighbridge-v1.1.0.zip`

**Step 2 — Take a backup FIRST**

Log in to the application → Backup → Create Backup. Download and save the backup file.

**Step 3 — Stop the current services**
```powershell
cd C:\weighbridge
.\scripts\manage-services.ps1 stop
```

**Step 4 — Replace the files**

```powershell
# Backup the current .env and license.key
Copy-Item C:\weighbridge\.env C:\temp\weighbridge_env_backup.txt
Copy-Item C:\weighbridge\license.key C:\temp\license_backup.key

# Extract new version
Expand-Archive C:\Downloads\weighbridge-v1.1.0.zip C:\

# Copy back config files (do NOT overwrite with new template)
Copy-Item C:\temp\weighbridge_env_backup.txt C:\weighbridge-v1.1.0\.env
Copy-Item C:\temp\license_backup.key C:\weighbridge-v1.1.0\license.key
```

**Step 5 — Run service installer for new version**
```powershell
cd C:\weighbridge-v1.1.0
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\install-services.ps1
```

The installer will stop old services, register new ones, and start them.

**Step 6 — Verify**
```
http://localhost:9000
```

Check that the application loads and data is intact.

---

## Part E — Troubleshooting

---

### Problem 1: Application Not Loading in Browser

**Symptoms:** Browser shows "This site can't be reached" or connection refused at `http://localhost:9000`

**Diagnostic steps:**

```powershell
# Check service status
.\scripts\manage-services.ps1 status

# Check if ports are in use
netstat -ano | findstr ":9000"
netstat -ano | findstr ":9001"
```

**Fix A — Services not running:**
```powershell
.\scripts\manage-services.ps1 start
```

**Fix B — Port in use by another application:**
```powershell
# Find what is using port 9000
netstat -ano | findstr ":9000"
# Note the PID (last column), then kill it:
taskkill /F /PID <PID_NUMBER>
# Then restart services
.\scripts\manage-services.ps1 start
```

**Fix C — Services not installed yet:**
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\install-services.ps1
```

---

### Problem 2: Login Fails / "Invalid credentials"

**Check 1 — Is the backend running?**
```
http://localhost:9001/api/v1/health
```
Should return `{"status":"ok"}`. If it doesn't, the backend is down — see Problem 1.

**Check 2 — Is the database running?**
```
docker ps
```
The `weighbridge_db` container should show "Up X minutes". If not:
```
docker compose up -d
```

**Check 3 — Check backend logs for database errors:**
```powershell
.\scripts\manage-services.ps1 logs backend
```

Look for connection errors like `could not connect to server` or `password authentication failed`.

**Check 4 — Database password mismatch:**

Ensure the password in `.env` matches `docker-compose.yml`. If you change the password:
```powershell
# Stop everything
.\scripts\manage-services.ps1 stop
docker compose down -v   # WARNING: This deletes all data!
# Edit .env and docker-compose.yml with matching passwords
docker compose up -d
.\scripts\manage-services.ps1 start
```

---

### Problem 3: License Error / "License Expired" Screen

**The application shows a red screen with "License Expired"**

**Fix A — License key missing:**
```
dir C:\weighbridge\license.key
```
If the file is missing, copy it from the vendor's delivery package.

**Fix B — License expired:**
Contact the vendor with the serial number shown on the screen. The vendor will generate a new license key. Once received:
1. Copy new `license.key` to `C:\weighbridge\`
2. Click "Check Again" on the screen

**Fix C — Wrong hostname:**
The license is bound to a different PC name. This happens if:
- The PC was renamed after the license was generated
- The license was installed on the wrong machine

Contact vendor with the correct hostname:
```
hostname
```

**Fix D — File corrupted during transfer:**
Request the vendor to resend the license file. Transfer via USB drive rather than email/WhatsApp to avoid corruption.

---

### Problem 4: Database Not Starting

**Symptoms:** `docker ps` shows no containers, or container shows "Exited"

**Check 1 — Is Docker Desktop running?**

Look for the Docker whale icon in the system tray (bottom-right). If not visible:
- Start Menu → search "Docker Desktop" → Open

**Check 2 — WSL2 not running:**
```
wsl --status
```
If WSL2 is not installed:
```
wsl --install
```
Restart required.

**Check 3 — Start the container manually:**
```
cd C:\weighbridge
docker compose up -d
docker compose logs db
```

**Check 4 — Port 5432 in use:**
```
netstat -ano | findstr ":5432"
```
If another PostgreSQL instance is running on 5432, stop it or change the port in `docker-compose.yml`.

---

### Problem 5: Weighbridge Scale Not Reading

**Symptoms:** Weight shows "-- kg" or "0 kg" and doesn't update

**Check 1 — Correct COM port:**
- Open Device Manager → Ports (COM & LPT)
- Note the COM port of the weighbridge (e.g., `COM3`)
- Compare with configured port in application settings

**Check 2 — Cable connection:**
- Verify the RS-232 or USB cable between scale and PC is firmly connected
- Try a different USB port if using USB-serial adapter

**Check 3 — Baud rate:**
Check the scale's manual for correct baud rate. Common values: 9600, 19200, 4800.

**Check 4 — Another app is using the port:**
Close any other software that might be communicating with the scale (HyperTerminal, scale manufacturer software, etc.)

**Check 5 — Scale protocol:**
Different scale brands use different data formats. Contact vendor if the scale model has changed.

---

### Problem 6: PDF Download Not Working

**Symptoms:** Clicking "Download PDF" does nothing or shows an error

**Check backend logs:**
```powershell
.\scripts\manage-services.ps1 logs backend
```

Look for `xhtml2pdf` or `WeasyPrint` errors.

**Common fix:** PDF generation requires some Windows fonts. If fonts are missing:
```
pip install xhtml2pdf
```

If using the compiled .exe, restart the backend service:
```powershell
.\scripts\manage-services.ps1 restart backend
```

---

### Problem 7: Services Stop After Windows Restart

**Symptoms:** After rebooting the PC, the application doesn't work — services are stopped.

**Check 1 — Verify services are set to auto-start:**
```powershell
Get-Service WeighbridgeBackend | Select-Object Name, StartType
Get-Service WeighbridgeFrontend | Select-Object Name, StartType
```
Both should show `StartType: Automatic`.

If not, fix:
```powershell
Set-Service -Name WeighbridgeBackend -StartupType Automatic
Set-Service -Name WeighbridgeFrontend -StartupType Automatic
```

**Check 2 — Docker not starting with Windows:**
Docker Desktop → Settings → General → Enable "Start Docker Desktop when you log in"

**Check 3 — Log in is required for Docker:**
Docker requires a user to be logged in on Windows Home (WSL2 dependency). For unattended restarts, configure Windows auto-login or use Windows Server.

---

### Problem 8: "Access Denied" When Running Scripts

**Symptoms:** PowerShell shows "running scripts is disabled on this system"

**Fix:**
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Run this in the same PowerShell window before running any `.ps1` script.

---

### Problem 9: Backup/Restore Fails

**Symptoms:** Creating a backup returns an error

**Check — pg_dump available:**
```
docker exec weighbridge_db pg_dump --version
```

pg_dump runs inside the Docker container. If the container is not running, backup will fail. Start Docker first (see Problem 4).

**Restore note:** Restoring overwrites ALL current data. Always download the backup file before restoring.

---

### Problem 10: Multi-User Access from Other PCs on LAN Not Working

**Symptoms:** Other computers on the same network can't open the application

**Check 1 — Windows Firewall:**

Open PowerShell as Administrator:
```powershell
# Allow port 9000 (frontend)
New-NetFirewallRule -DisplayName "Weighbridge Frontend" -Direction Inbound -Protocol TCP -LocalPort 9000 -Action Allow

# Allow port 9001 (backend API)
New-NetFirewallRule -DisplayName "Weighbridge Backend" -Direction Inbound -Protocol TCP -LocalPort 9001 -Action Allow
```

**Check 2 — Find server IP address:**
```
ipconfig
```
Look for the IPv4 address under "Ethernet adapter" or "Wi-Fi adapter" (e.g., `192.168.1.105`).

**Check 3 — Client PC must use server's IP:**
On other PCs, open browser and navigate to:
```
http://192.168.1.105:9000
```
(Replace with actual server IP)

**Check 4 — Both PCs must be on same network:**
Both the server PC and client PCs must be connected to the same router/switch.

---

### Viewing Logs

Logs are stored in `C:\weighbridge\logs\`

| Log File | Contents |
|---|---|
| `backend_stdout.log` | Normal backend output and request logs |
| `backend_stderr.log` | Backend errors (check this first for problems) |
| `frontend_stdout.log` | Frontend server output |
| `frontend_stderr.log` | Frontend server errors |

**View logs in real time:**
```powershell
.\scripts\manage-services.ps1 logs backend
.\scripts\manage-services.ps1 logs frontend
```

**View in Notepad:**
```
notepad C:\weighbridge\logs\backend_stderr.log
```

---

### Service Management Quick Reference

| Task | Command |
|---|---|
| Check status | `.\scripts\manage-services.ps1 status` |
| Start all | `.\scripts\manage-services.ps1 start` |
| Stop all | `.\scripts\manage-services.ps1 stop` |
| Restart all | `.\scripts\manage-services.ps1 restart` |
| Restart backend only | `.\scripts\manage-services.ps1 restart backend` |
| View backend logs | `.\scripts\manage-services.ps1 logs backend` |
| View frontend logs | `.\scripts\manage-services.ps1 logs frontend` |
| Remove services | `.\scripts\install-services.ps1 -Unregister` |
| Reinstall services | `.\scripts\install-services.ps1` |

All commands must be run from `C:\weighbridge\` in **PowerShell as Administrator**.

---

*For additional support, contact the vendor with the license serial number and a description of the issue.*
