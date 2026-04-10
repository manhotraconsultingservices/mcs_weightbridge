# Weighbridge Invoice Software — Client Site 2 Deployment Guide

**Document:** Step-by-Step Deployment for a New Client Location
**Audience:** Vendor/IT Installer visiting the client site
**Estimated Time:** 2–3 hours (first time), 45 minutes (with experience)

---

## What You Need to Carry to the Client Site

Pack the following before you leave:

| Item | Description |
|------|-------------|
| USB Pendrive 1 (Install Drive) | Contains the release package + all installers |
| USB Pendrive 2 (Guard Drive) | Dedicated pendrive that stays at the client site permanently — used as USB Guard key |
| `license.key` file | Generated for THIS client's PC hostname (see Step 1 below) |
| This guide (printed or on phone) | |
| Vendor support phone number | In case remote help is needed |

---

## BEFORE You Leave Your Office — Pre-Site Preparation

### Step 1 — Get the Client's PC Hostname

**Option A:** Visit the client site first, run `hostname` on their PC, come back and generate the license.
**Option B:** Ask the client to WhatsApp you a photo of the Command Prompt output of:
```
hostname
```
Example result: `WEIGHBRIDGE-PC2`

### Step 2 — Generate a License Key for This Client

On your developer machine (where `vendor_private.key` is stored):

```
cd tools\license-generator

python generate_license.py ^
  --customer "CLIENT COMPANY NAME PVT LTD" ^
  --hostname "WEIGHBRIDGE-PC2" ^
  --expires 2027-04-02 ^
  --features invoicing,private_invoices,tally,gst_reports ^
  --max-users 5 ^
  --output license_client2.key
```

Verify it:
```
python generate_license.py --verify license_client2.key
```

Expected output:
```
VALID LICENSE
  Customer:      CLIENT COMPANY NAME PVT LTD
  Hostname:      WEIGHBRIDGE-PC2
  Serial:        WB-2026-0043
  Expires:       2027-04-02 (365 days remaining)
```

### Step 3 — Prepare the Install USB Pendrive

Copy the following onto **USB Pendrive 1 (Install Drive)**:

```
D:\weighbridge-release\
├── weighbridge.exe           ← compiled backend
├── docker-compose.yml
├── .env.template
├── license.key               ← the file you just generated (rename to license.key)
├── frontend\
│   └── dist\                 ← built React app
├── tools\
│   └── nssm.exe
└── scripts\
    ├── install-service.ps1
    └── manage-service.ps1
```

Also copy onto the USB:
- `Docker Desktop Installer.exe` (download from docker.com — saves time if internet is slow at site)
- This guide as a PDF

---

## AT THE CLIENT SITE — Installation Steps

---

## PHASE 1 — Machine Check (15 minutes)

### Step 4 — Verify the PC Meets Requirements

Open Task Manager (Ctrl+Shift+Esc) and check:

| Requirement | Minimum | Where to Check |
|-------------|---------|---------------|
| Windows version | Windows 10 64-bit or Windows 11 | Start → Settings → System → About |
| RAM | 8 GB | Task Manager → Performance → Memory |
| Free disk space | 5 GB | File Explorer → This PC |
| COM port for scale | COM3 or similar | Device Manager → Ports (COM & LPT) |

### Step 5 — Confirm the Hostname Matches Your License

Open Command Prompt (press Win+R → type `cmd` → Enter):
```
hostname
```

**The output MUST exactly match** the `--hostname` value you used to generate the license.
If they don't match: Stop. You need to regenerate the license (call your office).

---

## PHASE 2 — Install Prerequisites (30–45 minutes)

### Step 6 — Install Docker Desktop

Docker is needed to run the PostgreSQL database.

1. Insert **USB Pendrive 1**
2. Run `Docker Desktop Installer.exe` from the USB drive
3. When asked — select **"Use WSL 2 based engine"**
4. Complete the installation
5. **Restart the PC** when prompted
6. After restart, open Docker Desktop from the Start menu
7. Wait for Docker to show the green "running" whale icon in the system tray (bottom-right corner)
8. Configure auto-start:
   - Docker Desktop → top-right gear icon (Settings)
   - General tab → check **"Start Docker Desktop when you log in"**
   - Click "Apply & Restart"

**Verify Docker is working:**
```
docker --version
docker ps
```
Both should run without errors.

> **If Docker won't start:** Check that WSL2 is installed.
> Open PowerShell as Admin and run: `wsl --install`
> Restart and try Docker again.

---

## PHASE 3 — Copy Files & Configure (20 minutes)

### Step 7 — Create the Application Folder

Open Command Prompt as Administrator:
- Right-click Start → "Windows PowerShell (Admin)" or "Command Prompt (Admin)"

```
mkdir C:\weighbridge
```

### Step 8 — Copy Release Package from USB Pendrive

In File Explorer:
1. Open USB Pendrive 1
2. Select everything inside `weighbridge-release\`
3. Copy and paste into `C:\weighbridge\`

Final structure should be:
```
C:\weighbridge\
├── weighbridge.exe
├── docker-compose.yml
├── .env.template
├── license.key
├── frontend\dist\
├── tools\nssm.exe
└── scripts\
    ├── install-service.ps1
    └── manage-service.ps1
```

### Step 9 — Create the .env Configuration File

In Command Prompt:
```
copy C:\weighbridge\.env.template C:\weighbridge\.env
notepad C:\weighbridge\.env
```

Edit the file and fill in all values:

```env
DATABASE_URL=postgresql+asyncpg://weighbridge:YOURPASSWORD@localhost:5432/weighbridge
DATABASE_URL_SYNC=postgresql+psycopg://weighbridge:YOURPASSWORD@localhost:5432/weighbridge
SECRET_KEY=GENERATE_THIS_SEE_BELOW
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=480
PRIVATE_DATA_KEY=GENERATE_THIS_SEE_BELOW
```

**Generate SECRET_KEY and PRIVATE_DATA_KEY:**

Open a second Command Prompt and run:
```
python -c "import secrets; print(secrets.token_hex(32))"
```

Run this command **twice** — copy the first output as `SECRET_KEY` and the second output as `PRIVATE_DATA_KEY`.

> Write these two keys on a piece of paper and give it to the client to keep in a safe place. These are needed for data recovery.

**Choose a database password** (e.g., `Weighbridge@Site2#2026`) and use the SAME password for both `DATABASE_URL` lines.

Save and close Notepad.

### Step 10 — Update docker-compose.yml with the Same Database Password

Open `C:\weighbridge\docker-compose.yml` in Notepad:
```
notepad C:\weighbridge\docker-compose.yml
```

Find the `POSTGRES_PASSWORD` line and change it to match what you set in `.env`:
```yaml
environment:
  POSTGRES_USER: weighbridge
  POSTGRES_PASSWORD: Weighbridge@Site2#2026   ← same as in .env
  POSTGRES_DB: weighbridge
```

Save and close.

---

## PHASE 4 — Start Database & Install Service (20 minutes)

### Step 11 — Start the PostgreSQL Database

In Command Prompt (as Admin):
```
cd C:\weighbridge
docker compose up -d
```

Expected output:
```
[+] Running 2/2
 ✔ Network weighbridge_default  Created
 ✔ Container weighbridge_db     Started
```

Verify it's running:
```
docker ps
```

You should see `weighbridge_db` with status "Up X seconds".

> **If you see an error here:** Check that Docker Desktop is running (whale icon in system tray). If not, open Docker Desktop from Start menu and wait for it to fully start, then try again.

### Step 12 — Install the Windows Service

In PowerShell as Administrator:
```powershell
cd C:\weighbridge
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\install-service.ps1
```

This script will:
- Check all prerequisites
- Start PostgreSQL if not already running
- Register `WeighbridgeERP` as a Windows auto-start service
- Start the service
- Open a firewall rule for port 9001
- Open the browser to `http://localhost:9001`

Expected final output:
```
============================================================
              INSTALLATION COMPLETE
============================================================

  Application URL  : http://localhost:9001
  LAN access       : http://<this-PC-IP>:9001
  Default login    : admin / admin123
```

### Step 13 — Verify the Application is Running

Open Chrome or Edge and go to:
```
http://localhost:9001
```

You should see the Weighbridge login page.

Login with:
- Username: `admin`
- Password: `admin123`

---

## PHASE 5 — Initial Application Setup (30 minutes)

### Step 14 — Change the Admin Password FIRST

1. Log in as admin
2. Click the user icon (top-right corner)
3. Click "Change Password"
4. Set a strong new password
5. **Give this password to the client owner only** — write it on paper and have them store it safely

### Step 15 — Set Up Company Profile

Go to **Settings → Company**:

- Company name (exact legal name)
- GSTIN (15-digit GST number)
- PAN number
- Full address including PIN code
- State (select from dropdown — important for CGST/SGST vs IGST calculation)
- Phone number
- Bank account details (for invoice printing)
- Upload company logo (optional)

Click **Save**.

### Step 16 — Create Financial Year

Go to **Settings → Financial Years**:

- Click "Add Financial Year"
- Label: `2026-2027`
- Start Date: `2026-04-01`
- End Date: `2027-03-31`
- Click Save
- Click **"Activate"** on the new year

### Step 17 — Set Invoice Prefixes

Go to **Settings → Invoice Prefixes** (or Company settings):

- Sales invoice prefix: e.g., `WB/SALE`
- Purchase invoice prefix: e.g., `WB/PUR`

These appear in invoice numbers like `WB/SALE/26-27/0001`.

### Step 18 — Create User Accounts

Go to **Settings → Users**:

Add accounts for staff:

| Role | Who Gets It | Can Do |
|------|-------------|--------|
| `admin` | Owner / Manager | Everything |
| `operator` | Weighbridge operator | Create tokens, invoices |
| `accountant` | Accountant | Payments, reports, ledger |
| `viewer` | Read-only user | View only |

### Step 19 — Add Products and Categories

Go to **Products**:

1. Add categories first (e.g., Stone Aggregate, Stone Dust, Sand)
2. For each product add:
   - Name
   - HSN code (check the GST HSN master)
   - Unit (MT, CFT, etc.)
   - Default rate (₹ per unit)
   - GST rate (5%, 12%, 18%, etc.)

### Step 20 — Add Parties (Customers & Suppliers)

Go to **Parties**:

For each customer/supplier add:
- Name (exact as on GSTIN certificate)
- GSTIN (for GST-registered parties)
- Phone, address
- Party type: Customer / Supplier / Both

### Step 21 — Add Vehicles

Go to **Vehicles**:

For each truck add:
- Registration number (e.g., `MP19GC1234`)
- Default tare weight (empty truck weight in kg)

### Step 22 — Configure Weighbridge Scale

**Find the COM port:**
1. Open Device Manager (right-click Start → Device Manager)
2. Expand "Ports (COM & LPT)"
3. Note the COM port number (e.g., `COM3`)

**Configure in application:**

Go to **Settings → Scale** (or call the API if not available in UI):
- Port: `COM3` (as found above)
- Baud rate: check scale manual (usually 9600)
- Protocol: `generic` (or scale-specific if shown)

Test: Go to **Tokens** page — you should see a live weight reading in the top bar.

---

## PHASE 6 — USB Guard Pendrive Setup (15 minutes)

The USB Guard protects private/non-GST invoices. This requires a **dedicated USB pendrive** that stays at the weighbridge computer permanently.

### Step 23 — Insert USB Pendrive 2 (Guard Drive)

Insert the second pendrive (this will be the permanent "key" for the system).

> **Important:** Label this pendrive "WEIGHBRIDGE KEY — DO NOT FORMAT" and explain to the client that this pendrive should:
> - Stay plugged into the PC at all times during business hours
> - Never be formatted or files deleted from it
> - Be stored safely (not left lying around) when the office is closed

### Step 24 — Register the USB Key

Open Command Prompt as Administrator in `C:\weighbridge`:

The USB Guard setup runs via the Python source. Since we are running the exe, use the Settings UI:

1. Go to **Settings → USB Guard** tab
2. The application scans connected drives for `.weighbridge_key` files automatically
3. If no key is found, click **"Register New Key"**
4. The application will write a `.weighbridge_key` file to the inserted USB drive and register its UUID

> **Alternative (if UI option not available):** Generate a UUID and manually write a key file:
> ```
> python -c "import uuid; print(uuid.uuid4())"
> ```
> Copy the output UUID. Create a file named `.weighbridge_key` on the USB drive containing ONLY that UUID.
> Then in Settings → USB Guard → paste the UUID → Register Key.

### Step 25 — Test USB Guard

1. Go to **Private Invoices** (accessible from sidebar after USB is recognized)
2. With USB inserted: the invoice list should appear
3. Eject the USB drive — the page should show a lock screen
4. Re-insert USB — access should be restored

### Step 26 — Set Up USB Recovery PIN

This is the backup in case the USB pendrive is ever lost.

1. Go to **Settings → USB Guard → Recovery**
2. Set a recovery PIN (6–8 digits recommended)
3. Set validity: 48 hours
4. Click **"Save Recovery PIN"**

**Write the recovery PIN on paper and give it to the business owner in a sealed envelope** with instructions to keep it safe.

---

## PHASE 7 — Take First Backup (5 minutes)

### Step 27 — Create Initial Backup

1. Go to **Backup** in the sidebar
2. Click **"Create Backup"**
3. A backup file appears in the list (e.g., `weighbridge_backup_20260402_143000.sql.enc`)
4. Click **"Download"** — save this file to the client's Google Drive or email it to the owner

This backup is AES-256-GCM encrypted — only your system can decrypt it.

---

## PHASE 8 — LAN Access Setup (10 minutes, if multiple PCs needed)

If other computers (accountant's laptop, manager's PC) need to access the software:

### Step 28 — Find the Server PC's IP Address

On the server (weighbridge) PC:
```
ipconfig
```

Look for: `IPv4 Address . . . . . : 192.168.1.xxx`
Note this IP address.

### Step 29 — Firewall Rule (Already Added by Installer)

The install script added the firewall rule. Verify:
```powershell
Get-NetFirewallRule -DisplayName "Weighbridge ERP"
```

If missing, add it:
```powershell
New-NetFirewallRule -DisplayName "Weighbridge ERP" -Direction Inbound -Protocol TCP -LocalPort 9001 -Action Allow
```

### Step 30 — Access from Other PCs

On any other PC on the same network, open Chrome/Edge and go to:
```
http://192.168.1.xxx:9001
```
(Replace with actual IP from Step 28)

The login page should appear.

> **Note:** The IP address may change if the router restarts. To fix this permanently, set a static IP on the server PC (Control Panel → Network → Adapter settings → IPv4 Properties → Use the following IP address).

---

## PHASE 9 — Final Verification & Handover (15 minutes)

### Step 31 — Complete Go-Live Checklist

Walk through each item with the client:

**System**
- [ ] Application opens at `http://localhost:9001`
- [ ] Login works with the new admin password
- [ ] Both services show Running: `.\scripts\manage-service.ps1 status`
- [ ] Docker container running: `docker ps`

**License**
- [ ] License status shows valid: Settings → License (or check `/api/v1/license/status`)
- [ ] Expiry date and customer name are correct

**Data Setup**
- [ ] Company name and GSTIN correct
- [ ] Financial year created and active
- [ ] At least 1 product entered
- [ ] At least 1 party entered
- [ ] Weighbridge operator account created

**Hardware**
- [ ] Live weight reading visible on Token page
- [ ] USB Guard pendrive inserted and recognized

**Backup**
- [ ] First backup created and downloaded/saved

### Step 32 — Test a Complete Weighment (Live Demo with Operator)

Do one complete test transaction in front of the operator:

1. Tokens → New Token
2. Enter vehicle, party, product
3. Click "Record First Weight" — enter the live gross weight
4. Click "Record Second Weight" — enter a tare weight
5. Token status changes to COMPLETED
6. Invoice is auto-created (check Invoices → should appear as Draft)
7. Open the invoice → click Finalize
8. Click "Download PDF" — verify PDF opens

### Step 33 — Leave the Client with This Information

Write the following on paper (or email to the owner):

```
WEIGHBRIDGE SOFTWARE — SITE INFORMATION

Application URL    : http://localhost:9001
Admin Username     : admin
Admin Password     : [the password set in Step 14]

Recovery PIN       : [the PIN set in Step 26]
Recovery PIN Hours : 48

Server PC Hostname : [from hostname command]
License Serial     : [from license file]
License Expiry     : [date]

SECRET_KEY         : [copy from .env]
PRIVATE_DATA_KEY   : [copy from .env]

Vendor Support     : [your phone number]
```

> Keep the SECRET_KEY and PRIVATE_DATA_KEY confidential — they are needed to decrypt any backup files.

---

## Troubleshooting at Client Site

### Application not loading after restart

```powershell
# Check service
.\scripts\manage-service.ps1 status

# Start if stopped
.\scripts\manage-service.ps1 start

# Check if Docker is running
docker ps

# If Docker container not running:
cd C:\weighbridge
docker compose up -d
```

### "License Expired" screen after a few months

The license has expired. Contact the vendor with the serial number, get a new `license.key`, copy it to `C:\weighbridge\license.key`, and refresh the browser.

### Scale not showing weight

1. Check that the RS-232 cable is plugged in
2. Open Device Manager → verify COM port number hasn't changed
3. Go to Settings → Scale → update the COM port if needed
4. Restart the weighbridge service:
```powershell
.\scripts\manage-service.ps1 restart
```

### USB Guard not recognizing the pendrive

1. Check the pendrive is inserted
2. Refresh the Private Invoices page
3. If still not working: Settings → USB Guard → the pendrive UUID should appear — click Register

### Cannot find logs for an error

```
C:\weighbridge\logs\weighbridge_stderr.log
```

Open in Notepad and look at the bottom of the file for recent errors. Share this file with vendor support.

---

## Service Management Quick Reference

Run all commands from `C:\weighbridge\` in **PowerShell as Administrator**:

| What you want to do | Command |
|---------------------|---------|
| Check if running | `.\scripts\manage-service.ps1 status` |
| Start | `.\scripts\manage-service.ps1 start` |
| Stop | `.\scripts\manage-service.ps1 stop` |
| Restart | `.\scripts\manage-service.ps1 restart` |
| View logs | `.\scripts\manage-service.ps1 logs` |

---

## Summary — What Was Installed Where

| What | Location on PC |
|------|---------------|
| Application files | `C:\weighbridge\` |
| Database data | Managed by Docker (survives reboots) |
| Backup files | `C:\weighbridge\backups\` |
| Log files | `C:\weighbridge\logs\` |
| License key | `C:\weighbridge\license.key` |
| Configuration | `C:\weighbridge\.env` |
| USB Guard key file | On the dedicated USB pendrive (`.weighbridge_key`) |
| Windows service | `WeighbridgeERP` (visible in Services console) |

---

*Guide version: 1.0 — April 2026*
*For support: contact vendor with license serial number and error screenshot*
