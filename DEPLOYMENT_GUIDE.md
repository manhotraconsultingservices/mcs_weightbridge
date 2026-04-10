# Weighbridge ERP — Client Deployment Guide

**Audience:** Junior team member performing first-time installation at a client site
**Goal:** Install and hand over the application in under 2 hours
**Support:** Call senior if any step fails and the error message does not match this guide

---

## Overview — Three Phases

```
PHASE A  →  Developer Office (30 min, done before you travel)
PHASE B  →  Client PC, Automated  (~20 min, script runs itself)
PHASE C  →  Client PC, Manual  (~20 min, you + client do together)
```

---

## Security Features (What Protects the Software)

The application uses **5 layers of security** — all are handled by this guide:

| Layer | What it does | When it happens |
|-------|-------------|-----------------|
| **Hardware fingerprint** | Locks the license to the client's physical PC (CPU, motherboard, disk, Windows ID) — software cannot run on a different machine | Phase A (fingerprint collection + license generation) |
| **Ed25519 license signing** | Cryptographically signed license file — cannot be forged or tampered | Phase A (license generation) |
| **License expiry** | Time-limited license with background re-check every 6 hours | Phase A (set expiry date) |
| **DPAPI encryption** | Database password and encryption keys are locked to the machine using Windows DPAPI — cannot be read on another PC | Phase B (automated by Install-Client.ps1, step 12) |
| **Firewall rules** | PostgreSQL database port blocked from all external access; only app ports open on LAN | Phase B (automated by Install-Client.ps1, step 14) |

---

## PHASE A — Pre-Visit Preparation (Do This at the Office)

### A1. Collect hardware fingerprint from the client

The license is locked to the client's physical hardware. You need to collect a **hardware fingerprint** from their PC before you can generate a license.

**Send these instructions to the client (via WhatsApp/email):**

> "Please do the following on the PC where the weighbridge software will run:
>
> 1. Copy the file `show_fingerprint.py` from the USB we sent earlier (or from the download link)
> 2. Open **Command Prompt** (Start → type `cmd` → press Enter)
> 3. Run this command:
>    ```
>    python show_fingerprint.py
>    ```
> 4. A file called `fingerprint.json` will be created in the same folder
> 5. Send us the `fingerprint.json` file via WhatsApp or email"

**If the client does not have Python installed**, ask them to:
1. Open **Command Prompt** (Start → type `cmd` → press Enter)
2. Type `hostname` and press Enter — **take a screenshot**
3. Send you the screenshot

> We will use hostname-only binding as a fallback, but **hardware fingerprint is strongly preferred** because it prevents the software from being copied to another machine.

### A2. Generate the license key (done by senior developer)

**Option 1 — With hardware fingerprint (RECOMMENDED, most secure):**

```powershell
python tools\license-generator\generate_license.py `
    --customer "CLIENT NAME" `
    --hostname "HOSTNAME_FROM_FINGERPRINT" `
    --expires 2027-12-31 `
    --fingerprint-file "path\to\fingerprint.json" `
    --output dist\clients\CLIENT_NAME\license.key
```

**Example:**
```powershell
python tools\license-generator\generate_license.py `
    --customer "Rajesh Stone Crusher" `
    --hostname "STONE-CRUSHER-PC" `
    --expires 2027-12-31 `
    --fingerprint-file "C:\received\fingerprint.json" `
    --output dist\clients\rajesh-stone\license.key
```

You should see output confirming `HW Bound: YES (2-of-4 factor tolerance)`.

> **What does 2-of-4 tolerance mean?** The license checks 4 hardware components (CPU, motherboard, disk, Windows product ID). If the client replaces up to 2 of these (e.g., new hard drive + new motherboard), the license still works. If 3 or more change, a new license is needed.

**Option 2 — With hostname only (fallback, less secure):**

```powershell
python tools\license-generator\generate_license.py `
    --customer "CLIENT NAME" `
    --hostname "EXACT_HOSTNAME" `
    --expires 2027-12-31 `
    --output dist\clients\CLIENT_NAME\license.key
```

> **IMPORTANT:** The hostname must be **exactly** as shown by the `hostname` command (capital letters, hyphens, everything). One wrong character = license won't work = wasted visit.

### A3. Prepare the USB drive

Insert a USB drive (minimum 2 GB free space). Copy these items to the USB root:

```
USB:\
+-- weighbridge-full-1.0.0\          <-- the built release package
|   +-- backend\
|   |   +-- weighbridge-backend.exe  <-- or Python source if not compiled
|   |   +-- requirements.txt
|   |   +-- setup_dpapi.py
|   |   +-- show_fingerprint.py      <-- for collecting fingerprint on-site
|   +-- frontend\
|   |   +-- dist\                    <-- pre-built frontend (must exist)
|   +-- docker-compose.yml
|   +-- scripts\
|   |   +-- Install-Client.ps1       <-- the automated installer
|   |   +-- install-services.ps1
|   |   +-- manage-services.ps1
|   +-- tools\
|       +-- nssm.exe
+-- license.key                       <-- client-specific (generated in A2)
+-- DockerDesktopInstaller.exe        <-- offline copy (download if not present)
+-- INSTALL_CHECKLIST.txt             <-- printed checklist
```

**How to get DockerDesktopInstaller.exe offline:**
1. Open: https://www.docker.com/products/docker-desktop/
2. Download **Docker Desktop for Windows (AMD64)**
3. The file is named `Docker Desktop Installer.exe` (~600 MB)
4. Copy it to the USB root

### A4. Verify the USB before leaving

Open PowerShell and run these checks:

```powershell
# Check the release package exists
Test-Path "D:\weighbridge-full-1.0.0\scripts\Install-Client.ps1"
# Expected: True

# Check license key exists
Test-Path "D:\license.key"
# Expected: True

# Check Docker installer exists
Test-Path "D:\DockerDesktopInstaller.exe"
# Expected: True
```

Replace `D:\` with your actual USB drive letter. If any says `False`, fix it before leaving.

---

## PHASE B — Client PC: Automated Installation

### B1. Before you start — check the client PC

Verify these with your own eyes:

- [ ] Windows 10 or Windows 11 (64-bit)
- [ ] At least **8 GB RAM** (right-click Start → System → check "Installed RAM")
- [ ] At least **5 GB free space on C:** (open File Explorer → This PC → check C: drive)
- [ ] You are logged in as **Administrator** (not a standard user)
- [ ] Internet is not required, but USB must be inserted

### B2. Collect hardware fingerprint on-site (if not done remotely)

If you were unable to collect the fingerprint remotely in Phase A, do it now **before** running the installer:

1. Open **Command Prompt** as Administrator
2. Navigate to the USB:
   ```cmd
   D:
   cd weighbridge-full-1.0.0\backend
   ```
3. Run:
   ```cmd
   python show_fingerprint.py
   ```
4. The file `fingerprint.json` is saved in the current folder
5. Send this file to the office (WhatsApp/email)
6. The senior developer generates the license key and sends it back
7. Save the received `license.key` to the USB root (`D:\license.key`)

> **Do NOT proceed with the installer until you have `license.key` on the USB.**

### B3. Install Docker Desktop (if not already installed)

**Check if Docker is already installed:**
```cmd
docker --version
```
If you see a version number, Docker is installed — skip to B4.

**If not installed:**
1. Copy `DockerDesktopInstaller.exe` from USB to the desktop
2. Right-click the file → **Run as Administrator**
3. Follow the installer (accept all defaults)
4. When asked about WSL 2, click **OK** (it will install WSL automatically)
5. **Restart the PC** when prompted

**After restart:**
1. Docker Desktop will open automatically (look for the whale icon in the taskbar)
2. Wait until the whale icon stops animating and shows green / "Running"
3. This can take **2-3 minutes** on first launch

**Verify Docker is working:**
```cmd
docker ps
```
Expected output: a table with headers (empty rows is fine — no error is what matters)

> If you see `error during connect` — Docker is still starting. Wait 1 more minute and try again.

### B4. Run the automated installer

1. Insert the USB drive
2. Open **File Explorer** → navigate to the USB drive
3. Go into the `weighbridge-full-1.0.0\scripts\` folder
4. Right-click `Install-Client.ps1` → **Run with PowerShell**

   OR if you prefer, open **PowerShell as Administrator** and type:
   ```powershell
   powershell -ExecutionPolicy Bypass -File "D:\weighbridge-full-1.0.0\scripts\Install-Client.ps1"
   ```
   (Replace `D:` with your USB drive letter)

5. The script will start and show a numbered progress display:
   ```
   [01/16] Checking system requirements...
         OK  Windows: Windows 10 Pro (64-bit)
         OK  RAM: 16.0 GB
         OK  Free disk space: 45.2 GB on C:\

   [02/16] Verifying Docker Desktop is running...
         OK  Docker: 27.3.1
   ...
   ```

6. **Do NOT close the window** — wait for it to finish. It takes **15-25 minutes**.

7. When complete, you will see:
   ```
   +----------------------------------------------------------+
   |               INSTALLATION COMPLETE                        |
   +----------------------------------------------------------+

     Application URL  : http://localhost:9000
     Login            : admin  /  admin123
   ```

8. Press **Enter** to close the script window.

### B5. What the installer does automatically (for your understanding)

You do NOT need to do any of these manually — the script handles all of them:

| Step | What it does | Security impact |
|------|-------------|----------------|
| 1-2 | Checks system requirements + Docker | Ensures compatibility |
| 3-4 | Creates folders + copies files to `C:\weighbridge\` | Application installation |
| 5 | Copies `license.key` from USB | **Hardware-bound license activation** |
| 6 | Generates `.env` with random 64-char secrets | **Unique cryptographic keys per client** |
| 7 | Patches `docker-compose.yml` with matching DB password | **Password sync (no manual copy-paste errors)** |
| 8-9 | Starts PostgreSQL database container | Database setup |
| 10-11 | Registers Windows services + health check | Auto-start on boot |
| 12 | Runs `setup_dpapi.py --no-prompt` | **DPAPI machine-locks all secrets** |
| 13-14 | Copies `.env.bak` to USB, deletes from PC | **No plaintext secrets left on disk** |
| 15 | Firewall: opens ports 9000/9001, **blocks 5432** | **Database inaccessible from network** |
| 16 | Records version | Patch management |

### B6. Verify the installation worked

Open a web browser and go to:
```
http://localhost:9000
```

You should see the Weighbridge login page. Login with:
- **Username:** `admin`
- **Password:** `admin123`

If the login page loads and login works → Phase B is complete.

---

## PHASE C — Manual Configuration (Do With Client Present)

> Do these steps with the business owner / senior person from the client side.

### C1. Change the admin password IMMEDIATELY

1. Login to `http://localhost:9000` with `admin / admin123`
2. Click the user icon (top right) → **Change Password**
3. Set a strong password that the owner can remember
4. Write it down and hand it to the owner — **you should not know this password after today**

### C2. Enter company details

1. Go to **Settings** → **Company**
2. Fill in all fields:
   - Company Name (legal name as on GST registration)
   - GSTIN (15-digit number from GST certificate)
   - PAN (10-digit number)
   - Address (as it should appear on invoices)
   - State
   - Phone number
   - Email (for invoices)
3. Go to **Settings** → **Company** → scroll down to **Bank Details**:
   - Bank name
   - Account number
   - IFSC code
   - Account holder name
4. Click **Save**

### C3. Configure the weighing scale

1. Connect the scale's RS-232 cable to the PC's COM port (or USB-to-serial adapter)
2. In the application: **Settings** → **Scale**
3. Select the **COM Port** from the dropdown
   - If you don't know which port: open **Device Manager** (right-click Start → Device Manager → Ports (COM & LPT))
   - The scale will appear as "USB Serial Port (COM3)" or similar
4. Set **Baud Rate** (check the scale manual — commonly 9600 or 2400)
5. Click **Save**, then **Test** — the live weight should appear

### C4. Create financial year

1. Go to **Settings** → **Financial Year**
2. Click **Create New**
3. Set: Start Date = 01 Apr 2025, End Date = 31 Mar 2026
4. Click **Activate**

### C5. Create operator user accounts

1. Go to **Admin** → **Users**
2. Click **Create User**
3. Create accounts for each person who will use the system:
   - Name, username, password
   - Role: `operator` for weighbridge operators, `accountant` for accounts staff
4. Give each person their login credentials

### C6. Test with a real transaction

1. Go to **Tokens** → **Create Token**
2. Enter a test vehicle and party
3. Record first weight
4. Record second weight
5. Go to **Invoices** — verify the invoice was auto-created
6. Click **Finalise** → **Download PDF**
7. Open the PDF — verify all company details, weights, and GST appear correctly

If the PDF looks correct → the system is working.

### C7. Secure the USB backup

The USB drive now contains a file: `weighbridge-backup-HOSTNAME\.env.bak`

This file contains the database password and encryption keys. If the PC ever needs to be replaced or rebuilt, this file is needed.

**Action required:**
- [ ] Lock this USB drive in a **safe, secure location** (drawer, cabinet)
- [ ] Tell the owner: "This USB is your disaster recovery backup. Keep it locked away. Never share it."
- [ ] Do NOT leave it plugged in after you finish

---

## Security Verification Checklist (Before You Leave)

Run these checks to confirm all security layers are active:

**1. License is hardware-bound:**
Open browser → `http://localhost:9001/api/v1/license/status`
Verify: `"valid": true` in the response

**2. DPAPI secrets are active:**
```powershell
# This file should EXIST:
Test-Path "C:\weighbridge\backend\secrets.dpapi"
# Expected: True

# This file should NOT exist:
Test-Path "C:\weighbridge\backend\.env.bak"
# Expected: False

# This file should NOT exist:
Test-Path "C:\weighbridge\.env.bak"
# Expected: False
```

**3. Firewall is configured:**
```powershell
Get-NetFirewallRule -DisplayName "Weighbridge*" | Select-Object DisplayName, Enabled, Action
```
Expected: Frontend (Allow), Backend API (Allow), Block PostgreSQL External (Block)

**4. Database is not accessible externally:**
From a DIFFERENT computer on the same network, try:
```cmd
telnet CLIENT_PC_IP 5432
```
It should **fail** (connection refused). This confirms PostgreSQL is blocked.

**5. Services auto-start on boot:**
```powershell
Get-Service WeighbridgeBackend, WeighbridgeFrontend | Select-Object Name, Status, StartType
```
Both should show `Status: Running` and `StartType: Automatic`

---

## Troubleshooting Common Problems

### Problem: Script says "Docker Desktop is not running"

**Fix:**
1. Look for the whale icon in the Windows taskbar (bottom-right area, click the `^` to show hidden icons)
2. If the whale is there but not green: wait 2 minutes and try again
3. If no whale: double-click `Docker Desktop` on the desktop or Start menu
4. Wait for the whale to turn green
5. Re-run the installer script

### Problem: Script says "license.key not found"

**Fix:**
1. Check the USB drive is still inserted
2. Open File Explorer → check USB drive root for `license.key` file
3. If not there: call the office to send the correct license key via WhatsApp
4. Copy the received `license.key` to the USB root
5. Re-run the script

### Problem: App says "License expired or invalid" after install

**Fix — Hostname mismatch:**
1. Open CMD on client PC → type `hostname` → note the exact name
2. Call the office — the license was generated with a different hostname
3. Senior regenerates the license with the correct hostname
4. Copy new `license.key` to `C:\weighbridge\license.key`
5. Restart the service: `Restart-Service WeighbridgeBackend`

**Fix — Hardware fingerprint mismatch (rare):**
1. The client may have sent fingerprint from a different PC
2. Run `python show_fingerprint.py` on THIS machine
3. Send the new `fingerprint.json` to the office
4. Senior regenerates the license with correct fingerprint
5. Replace `license.key` and restart service

### Problem: Script says "Backend did not start within 150 seconds"

**Fix:**
1. Open PowerShell as Administrator
2. Run: `Get-Content "C:\weighbridge\logs\backend_stderr.log" -Tail 30`
3. Take a photo / screenshot of the error
4. Call the office and share the error

### Problem: Login page shows "Cannot connect to server"

**Fix:**
1. Open PowerShell as Administrator
2. Run: `Get-Service WeighbridgeBackend`
3. If Status is not `Running`:
   ```powershell
   Start-Service WeighbridgeBackend
   ```
4. Wait 30 seconds, refresh the browser

### Problem: "Execution policy" error when running the script

**Fix:**
Open PowerShell as Administrator and run:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```
Then re-run the installer.

### Problem: Docker says "WSL 2 installation is incomplete"

**Fix:**
Open PowerShell as Administrator and run:
```powershell
wsl --install
```
Restart the PC when prompted. Then start Docker Desktop again.

### Problem: Scale shows no weight / wrong weight

**Fix:**
1. Check the cable is securely connected at both ends
2. Go to **Settings** → **Scale**, try a different COM port
3. Try baud rate 9600, then 2400, then 4800
4. Check if the scale has a "Print" or "Serial" mode that needs to be enabled

---

## After the Visit — What to Leave With the Client

Hand over (verbally and in writing):

| Item | Who keeps it |
|------|-------------|
| Admin username and password | Business owner (they set it themselves in C1) |
| USB backup drive | Business owner — locked in safe |
| Application URL: `http://localhost:9000` | All staff who will use it |
| Your phone number for support | Business owner |

**Before you leave, make the owner confirm:**
- [ ] They can login with their new password
- [ ] They know where the USB backup is stored
- [ ] They know the application URL

---

## Service Management Commands (For Reference)

These commands are run in **PowerShell as Administrator**:

```powershell
# Check if both services are running
Get-Service WeighbridgeBackend, WeighbridgeFrontend

# Restart the application (use this if something seems stuck)
Restart-Service WeighbridgeBackend
Restart-Service WeighbridgeFrontend

# View recent backend errors
Get-Content "C:\weighbridge\logs\backend_stderr.log" -Tail 50

# View recent frontend errors
Get-Content "C:\weighbridge\logs\frontend_stderr.log" -Tail 20

# Check if PostgreSQL database is running
docker ps

# Restart PostgreSQL (use only if instructed by senior)
docker restart weighbridge_db
```

---

## Checklist Summary

### Phase A (Office)
- [ ] Got hardware fingerprint (`fingerprint.json`) from client — OR hostname as fallback
- [ ] License key generated by senior developer (with `--fingerprint-file` for hardware binding)
- [ ] USB prepared: release package + license.key + Docker installer + show_fingerprint.py
- [ ] USB verified with Test-Path commands

### Phase B (Client PC — Automated)
- [ ] Docker Desktop installed and running (green whale)
- [ ] Ran `Install-Client.ps1` as Administrator
- [ ] Saw "INSTALLATION COMPLETE" at the end
- [ ] Logged in to `http://localhost:9000` with `admin / admin123`

### Phase C (Client PC — Manual)
- [ ] Admin password changed (owner chose it themselves)
- [ ] Company name, GSTIN, PAN, address entered in Settings
- [ ] Bank details entered in Settings
- [ ] Weighing scale COM port configured and tested
- [ ] Financial year created and activated
- [ ] Operator user accounts created
- [ ] Test invoice created, PDF verified, PDF printed correctly
- [ ] USB backup locked in secure location
- [ ] Owner can login with new password

### Security Verification (Before Leaving)
- [ ] License status shows `valid: true` at `/api/v1/license/status`
- [ ] `secrets.dpapi` exists at `C:\weighbridge\backend\`
- [ ] `.env.bak` does NOT exist on the machine
- [ ] Firewall rules confirmed (ports 9000/9001 open, 5432 blocked)
- [ ] Both services set to StartType: Automatic

---


### Printer setup

## One-time Windows thermal printer setup
- [ ] Win + R → printui /s /t2 → find your thermal printer → Properties
- [ ] Or: Settings → Bluetooth & devices → Printers & scanners → click your thermal printer → Printer properties → Advanced → Printing Defaults
- [ ] Look for Paper size → if 80mm isn't listed → click New → set:
	-	Width: 80 mm
	-	Height: 200 mm (or whatever your roll length is)
	-	Name: Thermal 80mm
	-	Save → set it as default paper for this printer

- After that, in Chrome's print dialog:
	- Select the thermal printer
	- Paper size → Thermal 80mm
	- Margins → None
	- Scale → 100%
	- Uncheck Headers and footers

*Document maintained by the development team. Last updated: 2026-04-09*
