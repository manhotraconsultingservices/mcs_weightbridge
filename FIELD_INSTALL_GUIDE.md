# MC Weighbridge ERP — Field Installation Guide

**For:** IT Installer with 1 year experience
**Time required:** 2 to 3 hours at client site
**This guide covers:** Installing everything from scratch on a fresh Windows PC

---

## WHAT YOU NEED TO CARRY TO THE CLIENT SITE

Prepare this checklist at your office BEFORE going to the site:

| What | Details |
|------|---------|
| USB Pen Drive 1 (Install Drive) | Copy the full `workspace_Weighbridge` folder + all installers onto this |
| USB Pen Drive 2 (Guard Drive) | A separate pen drive that will be LEFT at the client site permanently as the security key |
| `license.key` file | Generated for this client's PC (see Step 0 below) |
| This document | Printed or on your phone |
| RS232/USB cable | To connect weighbridge scale to PC |
| Scale driver CD or download link | Usually comes with the scale; needed for COM port |
| Your support phone number | Give to client |

---

## STEP 0 — GENERATE LICENSE KEY (DO THIS AT YOUR OFFICE)

You need the client's **computer name** before you can generate the license.

**How to get the computer name remotely:**
Ask the client to open Command Prompt (search "cmd" in Start menu) and type:
```
hostname
```
They will see something like: `WEIGHBRIDGE-PC` or `SACHIN-DESKTOP`

Once you have it, run this on **your own developer machine** (the one with `vendor_private.key`):

```
cd tools\license-generator

python generate_license.py ^
  --customer "ABC STONE CRUSHERS PVT LTD" ^
  --hostname "WEIGHBRIDGE-PC" ^
  --expires 2027-04-02 ^
  --features invoicing,private_invoices,tally,gst_reports ^
  --max-users 5 ^
  --output license_abc.key
```

Replace:
- `"ABC STONE CRUSHERS PVT LTD"` with client's actual company name
- `"WEIGHBRIDGE-PC"` with the hostname you got from client
- `2027-04-02` with the expiry date (1 year or 2 years from today)

Copy the generated `license_abc.key` file onto your Install USB drive.

---

## PART A — AT THE CLIENT SITE

---

## STEP 1 — CHECK THE PC BEFORE YOU START

First check that the client's PC meets minimum requirements.

1. Press **Windows key + R**, type `dxdiag`, press Enter
2. Note the RAM — needs at least **8 GB**
3. Check Windows version — needs **Windows 10 or Windows 11**
4. Check free disk space — right-click C: drive → Properties — needs at least **20 GB free**

Also check:
- The PC is connected to power
- Internet is available (needed only during installation, not after)
- You are logged in as an **Administrator** account (not a limited user)

> **How to check if you are Administrator:** Right-click Start button → Click "Computer Management" — if it opens without asking for a password, you are an Administrator. If it asks for a password, ask the client for the admin password.

---

## STEP 2 — COPY THE APPLICATION FILES

1. Insert your **Install USB** (Pen Drive 1)
2. Open File Explorer
3. Copy the entire **`workspace_Weighbridge`** folder from the USB to:
   ```
   C:\weighbridge
   ```
   (Create the `weighbridge` folder if it does not exist)

After copying, your folder structure should look like:
```
C:\weighbridge\
    backend\
    frontend\
    scripts\
    tools\
    docker-compose.yml
    FIELD_INSTALL_GUIDE.md
```

4. Also copy the `license.key` file you generated to:
   ```
   C:\weighbridge\license.key
   ```

---

## STEP 3 — INSTALL POSTGRESQL (THE DATABASE)

The software stores all data in a database called PostgreSQL. Install it first.

### Option A — Using the installer script (Recommended)

1. Press **Windows key**, search for **PowerShell**
2. Right-click **Windows PowerShell** → **Run as Administrator**
3. A blue window opens. Type exactly:

```powershell
cd C:\weighbridge\scripts
powershell -ExecutionPolicy Bypass -File install.ps1 -RegisterServices
```

4. Press **Enter** and wait. This will:
   - Install Python 3.11 (if not already installed)
   - Install Node.js (if not already installed)
   - Install PostgreSQL (if not already installed)
   - Set up the database
   - Install all required packages
   - Register Windows services
   - Build the frontend

   This takes about **20-30 minutes** on a new PC with a good internet connection.

5. When it finishes, it will print a message like:
   ```
   ===== Installation Complete =====
   Backend service: Running
   Frontend service: Running
   Open http://localhost:9000 in browser
   Admin login: admin / [password shown here]
   ```

   **IMPORTANT:** Write down the admin password shown on screen. It is randomly generated and shown only once.

### Option B — Manual install (if Option A fails)

Skip to the "Manual Installation" section at the end of this document.

---

## STEP 4 — VERIFY THE APPLICATION IS RUNNING

1. Open **Google Chrome** or **Microsoft Edge**
2. Type in the address bar: `http://localhost:9000`
3. Press Enter

You should see the **MC Weighbridge ERP login page**.

If you see an error or blank page:
- Wait 30 seconds and refresh (press F5)
- If still not working, go to TROUBLESHOOTING at the end of this document

---

## STEP 5 — FIRST LOGIN AND CHANGE PASSWORD

1. On the login page:
   - **Username:** `admin`
   - **Password:** Use the password shown at the end of Step 3 install script
   - (If you used the script and didn't note the password, see Troubleshooting)

2. After login, immediately change the password:
   - Click the **user icon** at top right
   - Click **Change Password**
   - Set a new strong password (example: `Weighbridge@2026`)
   - Give this password to the client owner (not the operator)

---

## STEP 6 — SETUP COMPANY INFORMATION

1. Click **Settings** in the left sidebar
2. Click the **Company** tab
3. Fill in all fields:

| Field | What to fill |
|-------|-------------|
| Company Name | Full legal name (e.g., ABC Stone Crushers Pvt Ltd) |
| GSTIN | 15-character GST number |
| PAN | 10-character PAN number |
| Address | Full address with PIN code |
| State | Select from dropdown (e.g., Madhya Pradesh) |
| Phone | Contact number |
| Email | Business email |

4. For **Bank Details** (shown on invoices):
   - Bank Name, Branch
   - Account Number
   - IFSC Code

5. Click **Save**

---

## STEP 7 — SETUP FINANCIAL YEAR

1. Still in **Settings**, click **Financial Years** tab
2. Click **Add Financial Year**
3. Fill:
   - Label: `2025-26`
   - Start Date: `01-04-2025`
   - End Date: `31-03-2026`
4. Click **Save**
5. Click **Set Active** next to the year you just created

> **Note:** The financial year must be active before creating any invoices or tokens.

---

## STEP 8 — SETUP INVOICE NUMBERING

1. Still in **Settings**, click **Invoice Prefix** or **Numbering** tab
2. Set prefix for sales invoices (example: `INV` or the company short name)
3. The system will number invoices as `INV/25-26/0001`, `INV/25-26/0002`, etc.

---

## STEP 9 — CREATE USERS

Create accounts for the people who will use the system.

1. Still in **Settings**, click **Users** tab
2. Click **Add User** for each person:

| Role | Who gets it | What they can do |
|------|------------|-----------------|
| `admin` | Business owner / You | Everything — full access |
| `operator` | Weighbridge operator | Create tokens, record weights |
| `accountant` | Accountant / billing staff | Invoices, payments, reports |
| `viewer` | Owner's family member | Read-only — can see everything |

3. Set a simple password for each user and tell them to change it after first login.

---

## STEP 10 — CONNECT THE WEIGHBRIDGE SCALE

This connects the digital weight indicator to the software.

### Find the COM Port number

1. Connect the RS232/USB cable between the weight indicator and the PC
2. Right-click **Start** → **Device Manager**
3. Expand **Ports (COM & LPT)**
4. Look for something like **"USB-SERIAL CH340 (COM8)"** or **"USB Serial Port (COM3)"**
5. **Note the COM number** (e.g., COM8)

> If you don't see any COM port, the scale driver is not installed. Install the driver from the scale's CD or download page, then reconnect the cable.

### Configure in the software

1. In the software, click **Settings**
2. Click **Weight Scale** tab (or go to Settings → Serial Port)
3. Set:
   - **Port:** COM8 (whatever number you saw in Device Manager)
   - **Baud Rate:** 9600 (check the scale's manual if different)
   - **Protocol:** Try `essae` first; if weight doesn't show, try `continuous`
4. Click **Save**
5. Go to the **Tokens** page — you should see the live weight in the top-right corner

> **Common baud rates by brand:**
> - Essae Teraoka: 9600
> - Avery Weigh-Tronix: 9600 or 4800
> - CAS: 9600
> - Phoenix: 9600

---

## STEP 11 — SETUP USB GUARD (SECURITY KEY)

The USB Guard protects the Private Invoice feature (non-GST billing). This requires a dedicated pen drive that stays at the client site permanently.

1. Insert **Pen Drive 2** (the Guard Drive)
2. Open **PowerShell as Administrator**
3. Run:
   ```powershell
   cd C:\weighbridge\backend
   venv\Scripts\python.exe setup_usb_key.py
   ```
4. The script will:
   - Find the pen drive automatically
   - Write a hidden key file (`.weighbridge_key`) to the pen drive
   - Register the key in the database
   - Print: **"USB key registered successfully"**

5. Label the pen drive physically: **"WEIGHBRIDGE KEY - DO NOT REMOVE"**
6. Keep it plugged into the PC at all times

> **If USB Guard is not needed** (client does not use private invoices), you can skip this step. The regular GST invoice system works without USB Guard.

### Setup Recovery PIN (in case pen drive is lost)

1. In the software, go to **Settings → USB Guard**
2. Click **Create Recovery PIN**
3. Set a 6-digit PIN (example: 482916)
4. Set expiry: 720 hours (30 days)
5. Write the PIN on paper and keep it in a sealed envelope with the client owner

---

## STEP 12 — ADD PRODUCTS (MATERIALS)

Add the materials/products the stone crusher sells.

1. Click **Products** in the left sidebar
2. Click **Add Product** for each material:

**Common stone crusher products:**
| Product Name | HSN Code | Unit | GST Rate |
|-------------|----------|------|----------|
| Gitti 20mm | 2517 | MT | 5% |
| Gitti 12mm | 2517 | MT | 5% |
| Gitti 10mm | 2517 | MT | 5% |
| Stone Dust / Murram | 2517 | MT | 5% |
| Boulders | 2517 | MT | 5% |
| Sand | 2505 | MT | 5% |
| GSB (Granular Sub Base) | 2517 | MT | 5% |

3. Set the **Default Rate** in ₹ per MT (this can be changed per invoice)

---

## STEP 13 — ADD CUSTOMERS AND SUPPLIERS (PARTIES)

Add the main customers and suppliers.

1. Click **Parties** in the left sidebar
2. Click **Add Party**
3. For customers: set **Party Type = Customer**
4. For suppliers: set **Party Type = Supplier**
5. Fill in name, GSTIN, phone number

> You don't need to add all parties now. You can add them while creating invoices too.

---

## STEP 14 — ADD VEHICLES

Add the common vehicles that come for weighment.

1. Click **Vehicles** in the left sidebar
2. Click **Add Vehicle**
3. Enter registration number (e.g., MP09AB1234)
4. Enter default tare weight if known (saves time later)

---

## STEP 15 — LAN SETUP (IF OTHER PCs ALSO NEED ACCESS)

If other computers in the office (accountant's PC, owner's laptop) also need to use the software:

### Step 15A — Find the server's IP address

On the server PC (where you installed the software):
1. Open Command Prompt
2. Type: `ipconfig` and press Enter
3. Look for **IPv4 Address** under Ethernet or Wi-Fi
4. Example: `192.168.1.100`
5. Note this IP address

### Step 15B — Open Firewall ports

In PowerShell (as Administrator) on the server PC:
```powershell
New-NetFirewallRule -DisplayName "Weighbridge App" -Direction Inbound -Protocol TCP -LocalPort 9000,9001 -Action Allow
```

### Step 15C — Access from other PCs

On any other PC on the same network, open a browser and type:
```
http://192.168.1.100:9000
```
(Replace `192.168.1.100` with the server's actual IP)

> **Important:** The software server (the PC where you installed) must be ON for other PCs to access it. Make sure it's not set to sleep or hibernate.

---

## STEP 16 — DISABLE SLEEP/HIBERNATE ON SERVER PC

The server PC must never go to sleep, otherwise everyone loses access.

1. Press **Windows key**, search **"Power & sleep settings"**, open it
2. Under **Sleep** → set both options to **"Never"**
3. Under **Screen** → set to 15 minutes or 30 minutes (screen can turn off, PC must not sleep)

Also disable hibernate:
1. Open PowerShell as Administrator
2. Type: `powercfg /hibernate off`
3. Press Enter

---

## STEP 17 — TEST THE FULL WORKFLOW

Before you leave the site, test the complete workflow with the client:

### Test 1: Token and Weighment
1. Go to **Tokens** page
2. Click **New Token**
3. Select a vehicle, party, product
4. Click **Record Gross Weight** (or enter manually if no scale connected)
5. When vehicle returns, click **Record Tare Weight**
6. Token should show **COMPLETED** status and display net weight

### Test 2: Invoice Creation
1. Go to **Invoices** page
2. Click **New Invoice**
3. Select the party, link to the token just created
4. Click **Create Invoice**
5. Click **Finalise** (assigns invoice number)
6. Click **PDF** button — invoice PDF should download

### Test 3: Payment Recording
1. On the invoice row, click the **money icon** (record payment)
2. Enter amount received, mode of payment
3. Invoice should show **Paid** status

### Test 4: Reports
1. Go to **Reports** page
2. Click **Sales Register**
3. Set today's date range
4. Click **Download CSV** — file should download

---

## STEP 18 — SETUP AUTOMATIC BACKUP

Set up daily automatic backup so data is never lost.

1. In the software, go to the **Backup** page
2. Click **Create Backup Now** — verify a backup file appears in the list
3. For automatic daily backup, ask the client to manually click "Create Backup" at end of each week

OR set up Windows Task Scheduler for automatic backup:
1. Open **Task Scheduler** (search in Start menu)
2. Click **Create Basic Task**
3. Name: `Weighbridge Daily Backup`
4. Trigger: Daily at 9:00 PM
5. Action: Start a program
   - Program: `powershell`
   - Arguments: `-Command "Invoke-WebRequest -Uri http://localhost:9001/api/v1/backup/create -Method POST -Headers @{Authorization='Bearer ADMIN_TOKEN'} -UseBasicParsing"`

> Ask your developer to help set up the admin token for the scheduled backup task.

---

## STEP 19 — FINAL CHECKS BEFORE YOU LEAVE

Run through this checklist before leaving the site:

- [ ] Open `http://localhost:9000` in browser — login page appears
- [ ] Login with admin credentials works
- [ ] Company name and GSTIN are correctly set in Settings
- [ ] Financial year is active
- [ ] At least one product is added
- [ ] Weight scale shows live weight in Tokens page (if scale is connected)
- [ ] USB Guard pen drive is registered and inserted
- [ ] Created at least one token and one invoice as a test
- [ ] PDF download works for the test invoice
- [ ] Other PCs on LAN can open the software (if applicable)
- [ ] Admin password has been changed from default
- [ ] Client knows their login username and password
- [ ] Recovery PIN is written and given to client owner in a sealed envelope
- [ ] PC sleep mode is disabled

---

## STEP 20 — HANDOVER TO CLIENT

Tell the client:

1. **Daily use:** Open Chrome, go to `http://localhost:9000` (bookmark this)
2. **The weighbridge PC must always be ON** while operators are working
3. **Do not unplug the USB pen drive** (the Guard Drive)
4. **Weekly backup:** Go to Backup page and click Create Backup once a week
5. **Call you** if software shows an error or doesn't open

Write down and give to client:
- Software URL: `http://localhost:9000`
- Server PC IP for other computers: `http://192.168.1.XXX:9000`
- Admin username: `admin`
- Admin password: `[the password you set]`
- Your contact number

---

---

# TROUBLESHOOTING — COMMON PROBLEMS

---

## Problem: Software page doesn't open in browser

**Check 1:** Is the backend service running?
1. Press Windows + R, type `services.msc`, press Enter
2. Look for `Weighbridge - Backend (FastAPI)` in the list
3. Status should be `Running`
4. If `Stopped`: Right-click → Start

**Check 2:** Is the frontend service running?
1. Same Services window
2. Look for `Weighbridge - Frontend (Static)`
3. If stopped: Right-click → Start

**Check 3:** Check the error log
1. Open PowerShell as Administrator
2. Type:
   ```powershell
   Get-Content C:\weighbridge\logs\backend_stderr.log -Tail 30
   ```
3. The last few lines will show the error message
4. Take a photo and send to your developer for help

---

## Problem: "Admin / admin" login doesn't work

The install script generates a random password. To reset it:

1. Open PowerShell as Administrator
2. Run:
   ```powershell
   cd C:\weighbridge\backend
   venv\Scripts\python.exe -c "
   import asyncio
   from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
   from sqlalchemy.orm import sessionmaker
   from sqlalchemy import select, update, text
   from passlib.context import CryptContext

   pwd = CryptContext(schemes=['bcrypt'])
   new_hash = pwd.hash('Admin@1234')

   async def reset():
       engine = create_async_engine('postgresql+asyncpg://weighbridge:weighbridge_dev_2024@localhost:5432/weighbridge')
       async with engine.begin() as conn:
           await conn.execute(text(\"UPDATE users SET password_hash = '\" + new_hash + \"' WHERE username = 'admin'\"))
       print('Password reset to Admin@1234')
       await engine.dispose()

   asyncio.run(reset())
   "
   ```
3. Login with: `admin` / `Admin@1234`
4. Change password immediately after login

---

## Problem: Weight scale shows "Not Connected"

1. Check the cable is firmly connected at both ends
2. Open **Device Manager** → **Ports (COM & LPT)**
   - If you see a **yellow warning triangle** next to the COM port, the driver is not installed properly
   - Install/reinstall the USB-to-serial driver
3. In the software → Settings → Weight Scale:
   - Try a different COM port number
   - Try a different protocol (essae, continuous, avery)
4. Check the baud rate matches the scale (usually 9600)
5. Restart the backend service:
   ```powershell
   Restart-Service WeighbridgeBackend
   ```

---

## Problem: "USB pen drive not detected" for private invoices

1. Check pen drive is inserted in the server PC (not a different PC)
2. Open File Explorer — the pen drive should appear as a drive letter (D: or E: or F:)
3. Check the key file exists on the pen drive:
   - Open the pen drive in File Explorer
   - Press **View → Show → Hidden Items** (enable)
   - Look for file called `.weighbridge_key`
4. If file is missing, run setup again:
   ```powershell
   cd C:\weighbridge\backend
   venv\Scripts\python.exe setup_usb_key.py
   ```

---

## Problem: Database error on startup

```
sqlalchemy.exc.OperationalError: connection to server failed
```

This means PostgreSQL is not running.

1. Open Services (Windows + R → `services.msc`)
2. Find `postgresql-x64-16` (or similar)
3. Right-click → Start
4. Then restart the Weighbridge backend service too

---

## Problem: "Port 9001 already in use"

1. Open PowerShell as Administrator
2. Run:
   ```powershell
   netstat -ano | Select-String ":9001"
   ```
3. Note the PID number in the last column
4. Run:
   ```powershell
   Stop-Process -Id [PID number] -Force
   ```
5. Restart the backend service

---

## Problem: Frontend service won't start

The frontend static server sometimes has issues with NSSM on Windows. Quick fix:

1. Open PowerShell as Administrator
2. Run:
   ```powershell
   cd C:\weighbridge\backend
   Start-Process -FilePath "venv\Scripts\python.exe" -ArgumentList "-m http.server 9000 --directory C:\weighbridge\frontend\dist" -WindowStyle Hidden
   ```

Or for a permanent fix, start the Vite dev server instead:
```powershell
cd C:\weighbridge\frontend
Start-Process -FilePath "npm.cmd" -ArgumentList "run dev" -WindowStyle Hidden
```

---

## Problem: "pg_dump not found" error during backup

1. Open PowerShell as Administrator
2. Run:
   ```powershell
   $pgPath = "C:\Program Files\PostgreSQL\16\bin"
   [Environment]::SetEnvironmentVariable("Path", $env:Path + ";" + $pgPath, "Machine")
   Restart-Service WeighbridgeBackend
   ```

---

---

# MANUAL INSTALLATION (If the script fails)

If the automated script in Step 3 fails, follow these manual steps.

## Manual Step A — Install Python 3.11

1. Open browser, go to: `https://www.python.org/downloads/`
2. Click **Download Python 3.11.x**
3. Run the installer
4. **IMPORTANT:** On the first screen, check the box **"Add Python to PATH"**
5. Click **Install Now**
6. When done, open Command Prompt and type `python --version` — should show `Python 3.11.x`

## Manual Step B — Install PostgreSQL 16

1. Go to: `https://www.postgresql.org/download/windows/`
2. Click **Download the installer** for Windows
3. Run the installer, click Next for all defaults
4. Set a password for the `postgres` user — write it down
5. Leave port as `5432`
6. Complete installation

## Manual Step C — Create the Database

1. Open **pgAdmin** (installed with PostgreSQL — look in Start menu)
2. Connect with the password you set during install
3. Right-click **Databases** → **Create** → **Database**
4. Name: `weighbridge`
5. Open **Query Tool** and run:
   ```sql
   CREATE USER weighbridge WITH PASSWORD 'weighbridge_prod_2024';
   GRANT ALL PRIVILEGES ON DATABASE weighbridge TO weighbridge;
   ```

## Manual Step D — Setup Backend

1. Open PowerShell as Administrator
2. Run each line one at a time:
   ```powershell
   cd C:\weighbridge\backend
   python -m venv venv
   venv\Scripts\pip install -r requirements.txt
   venv\Scripts\python -m alembic upgrade head
   ```

## Manual Step E — Create the .env file

1. Open Notepad
2. Copy and paste this content:
   ```
   DATABASE_URL=postgresql+asyncpg://weighbridge:weighbridge_prod_2024@localhost:5432/weighbridge
   DATABASE_URL_SYNC=postgresql+psycopg://weighbridge:weighbridge_prod_2024@localhost:5432/weighbridge
   SECRET_KEY=change-this-to-a-random-64-character-string-before-going-live
   ALGORITHM=HS256
   ACCESS_TOKEN_EXPIRE_MINUTES=480
   PRIVATE_DATA_KEY=change-this-to-a-64-char-hex-string-before-going-live
   COMPANY_NAME=Stone Crusher Enterprises
   ```
3. Save as `C:\weighbridge\backend\.env`
   - In Notepad Save dialog, change "Save as type" to **All Files**
   - Type filename as `.env` (with the dot at the start)

> **IMPORTANT:** The SECRET_KEY and PRIVATE_DATA_KEY must be changed to random strings.
> To generate them, open Python and run:
> ```python
> import secrets
> print(secrets.token_hex(32))   # copy this for SECRET_KEY
> print(secrets.token_hex(32))   # copy this for PRIVATE_DATA_KEY
> ```

## Manual Step F — Build Frontend

1. Download and install Node.js from `https://nodejs.org/` (LTS version)
2. Open PowerShell and run:
   ```powershell
   cd C:\weighbridge\frontend
   npm install
   npm run build
   ```

## Manual Step G — Install NSSM Services

1. Download NSSM from `https://nssm.cc/download`
2. Extract `nssm.exe` to `C:\weighbridge\tools\`
3. Open PowerShell as Administrator and run:
   ```powershell
   cd C:\weighbridge\scripts
   powershell -ExecutionPolicy Bypass -File nssm-register.ps1
   ```

## Manual Step H — Start Services

```powershell
Start-Service WeighbridgeBackend
Start-Service WeighbridgeFrontend
```

Then open `http://localhost:9000` in browser.

---

---

# REFERENCE — QUICK FACTS

| Item | Value |
|------|-------|
| Software URL (same PC) | http://localhost:9000 |
| Software URL (other PCs on LAN) | http://[SERVER-IP]:9000 |
| Backend API URL | http://localhost:9001 |
| Default admin username | admin |
| Application folder | C:\weighbridge |
| Log files | C:\weighbridge\logs\ |
| Database backups | C:\weighbridge\backups\ |
| USB key file on pen drive | .weighbridge_key (hidden file) |
| PostgreSQL port | 5432 |

---

# CONTACT AND SUPPORT

If you are stuck at any step, collect the following before calling for support:

1. Screenshot or photo of the error message on screen
2. The last 30 lines of the error log:
   ```powershell
   Get-Content C:\weighbridge\logs\backend_stderr.log -Tail 30
   ```
3. Windows version and RAM of the client PC
4. COM port number of the weight scale

---

*Document version: 2026-04-02*
*MC Weighbridge ERP — Built for Indian Stone Crusher SMEs*
