# WEIGHBRIDGE ERP — CLIENT INSTALLATION GUIDE

**Version:** 1.0 | **Platform:** Windows 10 Pro (64-bit) | **Deployment:** Docker

---

## OVERVIEW

This guide walks you through installing Weighbridge ERP on a client PC from the USB drive provided by your vendor.

**What you will need:**
- The USB drive supplied by your vendor (contains the software)
- A valid `license.key` file (sent by vendor after fingerprint step)
- Internet connection (for downloading Docker Desktop — one time only)
- Administrator access to the PC

**Estimated time:** 45–60 minutes (most of it is automated)

**Who should do this:** IT staff, vendor engineer, or a technically capable operator.

---

## CONTENTS OF THIS GUIDE

1. [System Requirements Check](#step-1--system-requirements-check-5-min)
2. [Enable WSL2](#step-2--enable-wsl2-10-min)
3. [Install Docker Desktop](#step-3--install-docker-desktop-10-min)
4. [Capture Hardware Fingerprint](#step-4--capture-hardware-fingerprint-5-min)
5. [Receive and Copy License Key](#step-5--receive-and-copy-license-key-2-min)
6. [Run the Installer](#step-6--run-the-installer-15-min-automated)
7. [First Login and Company Setup](#step-7--first-login-and-company-setup-5-min)
8. [Configure the Weighing Scale](#step-8--configure-the-weighing-scale-5-min)
9. [Create User Accounts](#step-9--create-user-accounts-5-min)
10. [Verification Checklist](#verification-checklist)
11. [Daily Operations](#daily-operations)
12. [Backup Instructions](#backup-instructions)
13. [Troubleshooting](#troubleshooting)

---

## STEP 1 — SYSTEM REQUIREMENTS CHECK (5 min)

Before you begin, confirm the PC meets these requirements:

| Requirement | Minimum | How to Check |
|---|---|---|
| Operating System | Windows 10 Pro 64-bit (version 20H2 or later) | Start → Settings → System → About |
| RAM | 8 GB (16 GB recommended) | Same page — "Installed RAM" |
| Free disk space on C: | 20 GB | Open File Explorer → This PC |
| Virtualization | Must be enabled in BIOS | See below |
| Internet | Required for Docker download | Any browser |

**Checking Virtualization is Enabled:**
1. Press `Ctrl + Shift + Esc` to open Task Manager
2. Click the **Performance** tab
3. Click **CPU** on the left
4. Look for **Virtualization: Enabled** on the right side

If it shows **Disabled**, restart the PC, enter BIOS (press `Del` or `F2` repeatedly during boot), find **Intel VT-x** or **AMD-V**, enable it, save and exit.

> **Windows 10 Home vs Pro:** Docker Desktop requires **Windows 10 Pro** or Enterprise. If the PC has Windows 10 Home, WSL2 will install but Docker Desktop requires an upgrade to Pro.

---

## STEP 2 — ENABLE WSL2 (10 min)

Docker Desktop on Windows 10 requires WSL2 (Windows Subsystem for Linux 2).

**Steps:**

1. Click **Start** → type `PowerShell` → right-click **Windows PowerShell** → **Run as Administrator**
2. Click **Yes** when prompted
3. In the blue PowerShell window, type this command and press Enter:

```
wsl --install
```

4. Wait for the installation to complete (downloads ~500 MB)
5. When prompted, **restart the computer**
6. After restart, a Ubuntu terminal window may open automatically — close it (you don't need Ubuntu)
7. Verify WSL2 installed correctly:
   - Open PowerShell as Administrator again
   - Type: `wsl --status`
   - You should see **Default Version: 2**

> **If `wsl --install` fails:** Your Windows may need updating first.
> Go to Start → Settings → Update & Security → Windows Update → Check for Updates → Install all available updates → Restart → Try again.

---

## STEP 3 — INSTALL DOCKER DESKTOP (10 min)

**Option A — From USB Drive (Recommended):**
1. Insert the USB drive
2. Open the USB drive in File Explorer
3. Look for a file named `Docker Desktop Installer.exe` in the `tools\` folder
4. Double-click it and follow the installer
5. When asked about WSL2 backend — leave it checked ✓
6. Complete the installation and **restart the PC** when prompted

**Option B — Download from Internet:**
1. Open a browser and go to: **docker.com/products/docker-desktop**
2. Click **Download for Windows**
3. Run the downloaded installer
4. Enable WSL2 backend option
5. Restart the PC

**After restart — Start Docker Desktop:**
1. Click Start → search for **Docker Desktop** → open it
2. Wait for the whale icon (🐳) in the taskbar notification area to turn **green** (ready)
3. This may take 2–3 minutes on first launch
4. Accept the Docker terms of service when prompted

**Verify Docker is working:**
1. Open PowerShell (regular, not Administrator)
2. Type: `docker run hello-world`
3. You should see a "Hello from Docker!" message

> If you see an error like "Docker daemon not running" — Docker Desktop is not fully started yet. Wait for the whale icon to be green, then try again.

---

## STEP 4 — CAPTURE HARDWARE FINGERPRINT (5 min)

> **IMPORTANT:** Complete this step BEFORE calling the vendor to request your license. The vendor needs your fingerprint to generate a license that is locked to YOUR machine.

**Steps:**

1. Insert the USB drive (if not already inserted)
2. Open the USB drive in File Explorer
3. Navigate to the `scripts\` folder
4. Double-click **`Get-Fingerprint.bat`**
5. If Windows asks "Do you want to allow this app to make changes?" — click **Yes**
6. A window will open and collect hardware information — this takes about 30 seconds
7. When done, it shows: **"Fingerprint saved to: C:\Users\...\Desktop\fingerprint.json"**
8. The Desktop folder opens automatically

**Send the file to your vendor:**
- Locate `fingerprint.json` on your Desktop
- Send it to your vendor via **WhatsApp** or **email**
- Tell the vendor the customer name and the expiry period requested

> **The vendor will send back a `license.key` file.** This usually takes a few minutes to a few hours depending on availability.

---

## STEP 5 — RECEIVE AND COPY LICENSE KEY (2 min)

Once the vendor sends you `license.key`:

1. Save the `license.key` file to the root of the USB drive
   - The USB drive root should now contain: `license.key`, `scripts\`, `docker-compose.yml`, etc.

2. Verify the file is there:
   - Open File Explorer → USB drive
   - You should see `license.key` in the main folder (not inside any subfolder)

> **Do not rename or modify** the `license.key` file. Any change will invalidate it.

---

## STEP 6 — RUN THE INSTALLER (15 min, mostly automated)

> **Important:** Docker Desktop must be running (whale icon green in taskbar) before starting.

**Steps:**

1. Insert the USB drive
2. Open the USB drive in File Explorer
3. Navigate to the `scripts\` folder
4. Right-click **`Install-Client.ps1`** → **Run with PowerShell**
5. If Windows asks "Do you want to allow...?" — click **Yes**
6. If PowerShell shows an error about execution policy:
   - Open PowerShell **as Administrator**
   - Run: `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`
   - Type `Y` and press Enter
   - Close and try Step 4 again

**What the installer does automatically (16 steps):**

```
[01/16] Checking system requirements
[02/16] Verifying Docker Desktop is running
[03/16] Creating folder structure at C:\weighbridge\
[04/16] Copying application files
[05/16] Installing license key
[06/16] Generating secure configuration
[07/16] Configuring database password
[08/16] Starting PostgreSQL database (Docker container)
[09/16] Waiting for database to be ready
[10/16] Registering Windows services
[11/16] Waiting for application to start
[12/16] Encrypting secrets (machine-locked)
[13/16] Backing up secrets to USB
[14/16] Configuring Windows Firewall
[15/16] Configuring Docker to auto-start
[16/16] Recording installation version
```

**Expected duration:** 10–20 minutes depending on PC speed.

**Success message:** When complete, you will see:

```
╔══════════════════════════════════════════════════════════╗
║               INSTALLATION COMPLETE ✓                    ║
╚══════════════════════════════════════════════════════════╝

  Application URL  : http://localhost:9000
  Login            : admin  /  admin123
```

> **If the installer fails at any step,** it will show a red "INSTALLATION FAILED" message with an error description. Save the log file path shown and contact your vendor with that log file.

---

## STEP 7 — FIRST LOGIN AND COMPANY SETUP (5 min)

1. Open a web browser (Chrome or Edge recommended)
2. Go to: **http://localhost:9000**
3. Log in with:
   - Username: `admin`
   - Password: `admin123`

4. **IMMEDIATELY change the admin password:**
   - Click the user icon (top right) → **Change Password**
   - Enter a strong password (minimum 8 characters, mix of letters and numbers)
   - Write it down and store securely

5. **Enter company details:**
   - Click **Settings** in the left sidebar → **Company**
   - Fill in:
     - Company Name (exactly as on your GST certificate)
     - Address
     - GSTIN (15-character GST number)
     - PAN number
     - Phone number
     - State (for CGST/SGST vs IGST calculation)
   - Scroll down — fill in **Bank Details** for invoices
   - Click **Save**

6. **Set up invoice numbering:**
   - In Settings → **Financial Year**
   - Verify the current financial year is active (e.g., 2025-26)
   - Go to Settings → **Invoice Settings**
   - Set invoice prefix (e.g., `WB`, `INV`)

---

## STEP 8 — CONFIGURE THE WEIGHING SCALE (5 min)

> Skip this step if you are not connecting a weight indicator/scale via USB/Serial port.

1. Connect the weight indicator to the PC via USB serial adapter
2. In the application, go to **Settings** → **Weight Scale**
3. Click **Scan Ports** — the system will show available COM ports
4. Select your scale's COM port (usually COM3 or COM4)
5. Set the **Baud Rate** (check your weight indicator manual — typically 9600 or 4800)
6. Click **Test Connection**
7. The live weight reading should appear in the top bar of the application

**Common scale protocols:**
- Standard continuous output: most indicators (recommended)
- Stable weight mode: for slow / vibration-prone environments

> **If the COM port is not listed:** The USB serial driver may not be installed. Check Device Manager (Start → right-click This PC → Manage → Device Manager → Ports COM & LPT). If you see a yellow warning on a COM port, install the driver from the adapter's packaging or website.

---

## STEP 9 — CREATE USER ACCOUNTS (5 min)

1. In the application, go to **Settings** → **User Management**
2. Click **Add User** for each person who will use the system:

| Role | Purpose |
|---|---|
| `admin` | Full access — owner/manager only |
| `operator` | Token weighment entry |
| `accountant` | Payments, ledger, GST reports |
| `store_manager` | Store inventory management |
| `sales_executive` | Sales invoices, quotations |
| `viewer` | Read-only reports access |

3. Set a strong password for each user
4. Share each person's username and password individually

---

## VERIFICATION CHECKLIST

Complete these checks before going live:

- [ ] Browser opens `http://localhost:9000` successfully
- [ ] Admin login works with the new password you set
- [ ] Settings → Company shows the correct company name and GSTIN
- [ ] License Status shows **Valid** (check Settings or the green badge in the top bar)
- [ ] Create a test token (Token → New Token) and complete a full weighment cycle
- [ ] Print a test token slip (Thermal and A5)
- [ ] Create a test invoice and generate PDF
- [ ] Weight scale shows live reading (if connected)
- [ ] Other user accounts can log in with their credentials

---

## DAILY OPERATIONS

**The application starts automatically when the PC boots.** No manual action is needed.

**Normal daily workflow:**
1. Turn on the PC — wait ~60 seconds for services to start
2. Open browser → **http://localhost:9000**
3. Login with your user account
4. Begin weighment operations

**Checking if the application is running:**
- Open browser → `http://localhost:9000`
- If it doesn't open, see Troubleshooting below

**The scale reader also starts automatically.** If it shows "disconnected", check that the USB serial adapter is plugged in, then go to Settings → Weight Scale and click Reconnect.

---

## BACKUP INSTRUCTIONS

**Your application data is automatically backed up.**

**USB Backup (created during installation):**
- During installation, a backup folder was created on the USB drive:
  `weighbridge-backup-COMPUTERNAME\`
- This contains the encrypted secrets file (`.env.bak`)
- **Store this USB drive in a safe, separate location from the PC** (not the same room)
- If the PC hard drive fails, you will need this USB drive to recover

**Creating a manual database backup:**
1. Login to the application
2. Go to **Backup** in the left sidebar
3. Click **Create Backup**
4. Click **Download** to save the backup file
5. Copy it to the USB drive or another storage location

**Recommended backup schedule:** Weekly manual backup, stored on USB.

---

## TROUBLESHOOTING

### Problem: Application does not open at `http://localhost:9000`

**Check 1 — Are the Windows Services running?**
1. Press `Win + R` → type `services.msc` → press Enter
2. Scroll down and find **WeighbridgeBackend**
3. If Status is not "Running" → right-click → Start
4. Repeat for **WeighbridgeFrontend** (if present)
5. Try the browser again

**Check 2 — Is Docker running?**
1. Look for the Docker whale icon (🐳) in the taskbar notification area (bottom right)
2. If the icon is not there or shows red/yellow: Open Docker Desktop from Start menu
3. Wait for the whale to turn green (ready)
4. Then restart the WeighbridgeBackend service (see Check 1)

**Check 3 — Is the database container running?**
1. Open Docker Desktop
2. Click **Containers** on the left
3. You should see `weighbridge_db` with a green "Running" status
4. If stopped: click the ▶ Play button next to it

---

### Problem: "License is invalid" or "License expired" message

**Cause:** The license file may be missing, corrupted, or the hardware has changed.

**Fix:**
1. Check if `C:\weighbridge\license.key` exists
2. If missing: find your USB drive and copy `license.key` to `C:\weighbridge\`
3. Restart the WeighbridgeBackend service
4. If the error persists: contact your vendor and re-run `Get-Fingerprint.bat` to get a new fingerprint (hardware may have changed after a repair)

---

### Problem: "Port 9000 already in use" or "Port 9001 already in use"

1. Open Task Manager (`Ctrl + Shift + Esc`)
2. Click the **Services** tab
3. Find **WeighbridgeBackend** → right-click → **Restart**
4. Wait 30 seconds and try the browser again

---

### Problem: Weight scale shows "Disconnected" or no reading

1. Check that the USB serial adapter cable is plugged into the PC
2. Go to application → Settings → Weight Scale → click **Reconnect**
3. If still disconnected: go to Settings → Weight Scale → **Scan Ports** again and reselect the COM port
4. Check Device Manager for driver issues:
   - Right-click Start → Device Manager → Ports (COM & LPT)
   - If there is a yellow warning icon on any port, reinstall the driver

---

### Problem: Services stopped after PC restart

This should not happen normally (services are set to auto-start). If it does:

1. Press `Win + R` → type `services.msc` → Enter
2. Find **WeighbridgeBackend** → double-click it
3. Set **Startup type** to **Automatic**
4. Click **Start** → **OK**
5. Repeat for Docker Desktop: open Docker Desktop → Settings (gear icon) → General → Enable **Start Docker Desktop when you log in**

---

### Problem: "WSL2 is not installed" error from Docker

1. Open PowerShell as Administrator
2. Run: `wsl --install`
3. Restart the PC
4. Open Docker Desktop → it should now work

---

### Problem: "Virtualization is disabled" error

1. Shut down the PC completely (not restart — actually shut down)
2. Turn the PC back on and immediately press `Del` or `F2` repeatedly to enter BIOS
3. Look for settings named: **Intel Virtualization Technology**, **Intel VT-x**, **AMD-V**, or **SVM Mode**
4. Set it to **Enabled**
5. Press `F10` to save and exit
6. Windows will boot normally

---

### Problem: Installer shows red "INSTALLATION FAILED"

1. Note the error message shown in red
2. Note the log file path shown at the bottom (e.g., `C:\weighbridge\logs\install_...log`)
3. Open that log file in Notepad
4. Send the log file and the error message to your vendor for assistance

---

## UNINSTALLATION

To completely remove Weighbridge ERP:

1. Open PowerShell as Administrator
2. Run:
   ```powershell
   # Stop and remove Windows services
   Stop-Service WeighbridgeBackend -ErrorAction SilentlyContinue
   Stop-Service WeighbridgeFrontend -ErrorAction SilentlyContinue
   sc.exe delete WeighbridgeBackend
   sc.exe delete WeighbridgeFrontend

   # Stop and remove Docker container
   cd C:\weighbridge
   docker compose down

   # Remove application files (keeps a backup of logs)
   # WARNING: This deletes all weighbridge data. Export backups first!
   Remove-Item -Recurse -Force C:\weighbridge
   ```

3. To also remove Docker Desktop: Start → Apps → Docker Desktop → Uninstall

> **Important:** Take a backup (Backup → Create Backup → Download) before uninstalling if you want to keep your data.

---

## SUPPORT CONTACT

| | |
|---|---|
| **Vendor Phone / WhatsApp** | *(filled by vendor at delivery)* |
| **Vendor Email** | *(filled by vendor at delivery)* |
| **License Serial** | *(visible in application: Settings → License)* |
| **Installation Log** | `C:\weighbridge\logs\install_*.log` |

**When contacting support, please have ready:**
- The license serial number
- The error message (screenshot or text)
- The install log file (if installation failed)

---

*Document Version: 1.0 — For Weighbridge ERP v1.0*
