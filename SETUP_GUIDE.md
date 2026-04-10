# Weighbridge Invoice Software — Setup & Deployment Guide

> **Environment:** Windows 10/11 server on a LAN · 2–5 concurrent users · Stone crusher weighbridge with RS232/USB scale

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Quick Install (Script)](#quick-install)
3. [Manual Installation](#manual-installation)
4. [Database Setup](#database-setup)
5. [Environment Variables](#environment-variables)
6. [Running the Application](#running-the-application)
7. [Windows Service (NSSM)](#windows-service)
8. [Recovery Dashboard (System Monitor)](#recovery-dashboard)
9. [LAN Access Setup](#lan-access)
10. [Weight Scale (Serial Port)](#weight-scale)
11. [First-Time Configuration](#first-time-configuration)
12. [USB Guard Setup](#usb-guard-setup)
13. [Backup & Restore](#backup--restore)
14. [Upgrading](#upgrading)
15. [Troubleshooting](#troubleshooting)

---

## Prerequisites

| Software | Version | Download |
|---|---|---|
| Python | 3.11 or 3.12 | https://www.python.org/downloads/ |
| Node.js | 20 LTS | https://nodejs.org/ |
| PostgreSQL | 15 or 16 | https://www.postgresql.org/download/windows/ |
| NSSM (optional, for service) | 2.24 | https://nssm.cc/download |

**Python packages installed via pip:**
`fastapi uvicorn[standard] sqlalchemy[asyncio] asyncpg psycopg alembic pydantic-settings python-jose passlib pyserial weasyprint xhtml2pdf jinja2 pandas openpyxl httpx`

---

## Quick Install

> Run PowerShell **as Administrator**

```powershell
cd C:\path\to\workspace_Weighbridge\scripts
powershell -ExecutionPolicy Bypass -File install.ps1
```

This installs Python, Node.js, PostgreSQL (if not present), creates the database, builds the frontend, and writes the `.env` file.

To also register Windows services:
```powershell
powershell -ExecutionPolicy Bypass -File install.ps1 -RegisterServices
```

---

## Manual Installation

### 1. Clone / Extract project
```
C:\weighbridge\
├── backend\
├── frontend\
└── scripts\
```

### 2. Backend Python setup
```powershell
cd C:\weighbridge\backend
python -m venv venv
.\venv\Scripts\pip install -r requirements.txt
```

### 3. Frontend build
```powershell
cd C:\weighbridge\frontend
npm install
npm run build        # creates dist/ folder for production
# OR for development:
npm run dev          # Vite dev server on port 3000
```

---

## Database Setup

### Create PostgreSQL database and user

```sql
-- Run as postgres superuser (psql -U postgres)
CREATE USER weighbridge WITH PASSWORD 'your_secure_password';
CREATE DATABASE weighbridge OWNER weighbridge;
GRANT ALL PRIVILEGES ON DATABASE weighbridge TO weighbridge;
```

### Run migrations
```powershell
cd C:\weighbridge\backend
.\venv\Scripts\python -m alembic upgrade head
```

---

## Environment Variables

Create `C:\weighbridge\backend\.env`:

```env
# Database
DATABASE_URL=postgresql+asyncpg://weighbridge:YOUR_PASSWORD@localhost:5432/weighbridge
DATABASE_URL_SYNC=postgresql+psycopg://weighbridge:YOUR_PASSWORD@localhost:5432/weighbridge

# JWT Auth (generate a strong random key)
SECRET_KEY=replace-with-64-char-random-string
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=480
```

**Generate a secure SECRET_KEY:**
```python
import secrets; print(secrets.token_hex(32))
```

---

## Running the Application

### Development mode
```powershell
# Terminal 1 — Backend
cd C:\weighbridge\backend
.\venv\Scripts\uvicorn app.main:app --host 0.0.0.0 --port 9001 --reload

# Terminal 2 — Frontend (dev with hot reload)
cd C:\weighbridge\frontend
npm run dev
```

### Production mode (static frontend served separately)
```powershell
# Backend only (no reload)
cd C:\weighbridge\backend
.\venv\Scripts\uvicorn app.main:app --host 0.0.0.0 --port 9001 --workers 2
```

The built frontend (`frontend\dist\`) must be served by IIS, Nginx, or a static server:
```powershell
# Quick static serve (dev only):
cd C:\weighbridge\frontend\dist
npx serve -l 3000
```

---

## Windows Service

Install [NSSM](https://nssm.cc/download) and place `nssm.exe` in `C:\weighbridge\scripts\` or `PATH`.

### Register all services (run once after deployment)

```powershell
# Open PowerShell as Administrator
cd C:\weighbridge\scripts

# 1. Register the backend application service
.\nssm-register.ps1

# 2. Register the frontend static-serve service
.\install-services.ps1       # if separate script, or handled by nssm-register.ps1

# 3. Register the Recovery Watchdog service
.\install-watchdog.ps1
```

> **Important — Enable the Frontend service:**
> After registration, `WeighbridgeFrontend` is set to `DISABLED` by default (to avoid conflicts
> when running `npm run dev` during development). In production you must explicitly enable it:
>
> ```powershell
> sc.exe config WeighbridgeFrontend start= auto
> sc.exe start  WeighbridgeFrontend
> ```
>
> Until this is done, the **"Restart Web Interface"** button in the Recovery Dashboard will show:
> *"The Web Interface is running in development mode and is not installed as a Windows service."*
> That message is expected in dev mode. In production it will not appear once the service is enabled.

### All three production services

| Service Name | Role | Port | Auto-restart |
|---|---|---|---|
| `WeighbridgeBackend` | FastAPI backend API | 9001 | Yes (NSSM) |
| `WeighbridgeFrontend` | Static frontend server | 9000 | Yes (NSSM) |
| `WeighbridgeWatchdog` | Recovery dashboard | 9002 | Yes (NSSM) |

**Logs:** `C:\weighbridge\logs\` (all three services write here)

### Verify all services are running

```powershell
Get-Service WeighbridgeBackend, WeighbridgeFrontend, WeighbridgeWatchdog | Select-Object Name, Status
```

Expected output:
```
Name                    Status
----                    ------
WeighbridgeBackend      Running
WeighbridgeFrontend     Running
WeighbridgeWatchdog     Running
```

### Unregister services

```powershell
.\nssm-register.ps1 -Unregister
nssm remove WeighbridgeWatchdog confirm
nssm remove WeighbridgeFrontend confirm
```

### IIS for frontend (optional)

1. Install IIS with URL Rewrite module
2. Create a new site pointing to `C:\weighbridge\frontend\dist\`
3. Add `web.config` for SPA routing:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<configuration>
  <system.webServer>
    <rewrite>
      <rules>
        <rule name="SPA" stopProcessing="true">
          <match url=".*" />
          <conditions logicalGrouping="MatchAll">
            <add input="{REQUEST_FILENAME}" matchType="IsFile" negate="true" />
          </conditions>
          <action type="Rewrite" url="/index.html" />
        </rule>
      </rules>
    </rewrite>
  </system.webServer>
</configuration>
```

---

## Recovery Dashboard

The **Recovery Dashboard** is a lightweight browser-based monitoring tool at `http://localhost:9002`.
It is designed for **non-IT on-site staff** — they can see what is broken and restart components
without needing to open a command prompt or call IT support.

### What it shows

| Card | What it monitors |
|---|---|
| ⚙️ Application Server | `WeighbridgeBackend` service + port 9001 health check |
| 🗄️ Database | Docker container state + port 5432 |
| 🖥️ Web Interface | `WeighbridgeFrontend` service + port 9000 |
| 💾 Disk Space | Free space % with colour-coded bar |

All cards auto-refresh every 10 seconds. A red banner appears with instructions when anything is down.

### Install the watchdog (production — run once)

```powershell
# Open PowerShell as Administrator
cd C:\weighbridge\scripts
.\install-watchdog.ps1
```

This registers `WeighbridgeWatchdog` as a Windows service that:
- Starts automatically when Windows boots
- Restarts itself if it crashes (NSSM `AppExit Default Restart`)
- Writes logs to `C:\weighbridge\logs\watchdog_stdout.log`

### Open the dashboard

**Option A — Double-click shortcut (recommended for non-IT staff):**
```
workspace_Weighbridge\Open Recovery Dashboard.bat
```
Double-clicking this file starts the watchdog if it isn't running and opens
`http://localhost:9002` in the default browser.

**Option B — Direct URL:**
Open any browser on the server and go to `http://localhost:9002`

**Option C — From a LAN machine:**
`http://SERVER_IP:9002`  (the watchdog binds to `0.0.0.0` — accessible from any machine on the network)

### Restart buttons

| Button | What it does | Requires |
|---|---|---|
| Restart App Server | `sc stop/start WeighbridgeBackend` + polls until RUNNING | Service registered & enabled |
| Restart Database | `docker restart weighbridge_db` + waits for port 5432 | Docker running |
| Restart Web Interface | `sc stop/start WeighbridgeFrontend` + polls until RUNNING | Service registered **and enabled** |

> **If "Restart Web Interface" shows an error:**
> The `WeighbridgeFrontend` service is either not registered or is set to `DISABLED`.
> Enable it first (see [Windows Service](#windows-service) section above):
> ```powershell
> sc.exe config WeighbridgeFrontend start= auto
> sc.exe start  WeighbridgeFrontend
> ```
> The button works correctly once the service is enabled and running.

### Step-by-step guide for on-site staff (printed copy recommended)

1. Open `http://localhost:9002` — or double-click **Open Recovery Dashboard.bat** on the Desktop.
2. Look for any **red card**.
3. Click the **RESTART** button on the red card.
4. Wait **30–40 seconds** — the card should turn green.
5. If the **Database** card is red and won't restart, also restart the App Server.
6. If nothing turns green after 3 minutes — call IT support and read the **Log Messages** at the bottom of the page.

### Troubleshooting the watchdog itself

```powershell
# Check service status
Get-Service WeighbridgeWatchdog

# View logs
Get-Content C:\weighbridge\logs\watchdog_stderr.log -Tail 50

# Start manually (if service not yet registered)
cd C:\weighbridge\backend
.\venv\Scripts\python watchdog_server.py
# Then open http://localhost:9002
```

---

## LAN Access

To allow other machines on the LAN to access the software:

1. **Backend** — Already binds to `0.0.0.0:9001`. Access via `http://SERVER_IP:9001`
2. **Firewall** — Allow port 9001 inbound:
   ```powershell
   New-NetFirewallRule -DisplayName "Weighbridge Backend" -Direction Inbound -Protocol TCP -LocalPort 9001 -Action Allow
   ```
3. **Frontend** — Update `VITE_API_BASE_URL` in `frontend/.env` if backend IP differs from `localhost`:
   ```
   VITE_API_BASE_URL=http://192.168.1.100:9001
   ```
   Then rebuild: `npm run build`

4. **Client access** — Other machines on LAN simply open `http://SERVER_IP:3000` (or IIS port) in their browser.

---

## Weight Scale (Serial Port)

The weighbridge indicator connects via RS232 or USB-to-Serial adapter.

### Setup steps:
1. Connect indicator to server machine
2. Note the COM port (Device Manager → Ports)
3. Login to the software as `admin`
4. Go to **Settings → Weight Scale** (or call `PUT /api/v1/weight/config`)
5. Set port name (e.g., `COM3`), baud rate (typically `9600`), and protocol:
   - `continuous` — indicator streams weight every 200ms
   - `essae` — Essae/CAS indicator protocol
   - `avery` — Avery Weigh-Tronix protocol

### Supported protocols:
| Protocol | Baud | Frame format |
|---|---|---|
| `continuous` | 9600 | Configurable field positions |
| `essae` | 9600 | `+NNNNNN.NNN kg` |
| `avery` | 9600 | Avery standard |

### Testing without a scale:
- Use a USB loopback connector
- Or enable `Manual Entry` mode in the token form (checkbox: "Manual Weight")

---

## First-Time Configuration

1. **Login** with default credentials: `admin` / `admin`
2. **Change password** immediately: top-right → Settings → Change Password
3. **Set up Company** (Settings → Company tab):
   - Company name, GSTIN, PAN, address
   - Bank details for invoice printing
4. **Activate Financial Year** (Settings → Financial Years):
   - Create `2025-26`, set start/end dates, click "Set Active"
5. **Seed products** (optional):
   ```powershell
   cd C:\weighbridge\backend
   .\venv\Scripts\python scripts\seed_data.py
   ```
6. **Create users** (Settings → Users):
   - Add operators with `operator` role
   - Add accountant with `accountant` role

---

## USB Guard Setup

Private invoices (non-GST billing) are protected by USB key authentication.

### Register a USB key:
1. Insert USB drive on the **server machine**
2. Run setup utility:
   ```powershell
   cd C:\weighbridge\backend
   .\venv\Scripts\python setup_usb_key.py
   ```
   This writes `.weighbridge_key` to the USB drive and registers the UUID in the database.
3. Or manually: Settings → USB Guard → paste UUID → Register Key

### Client USB authentication:
1. Copy `.weighbridge_key` from server USB to client USB
2. On any LAN machine, go to Private Invoices → click "Authenticate with USB"
3. Select the `.weighbridge_key` file — grants 8-hour session

### Recovery PIN (if USB is lost):
1. Settings → USB Guard → Recovery → create PIN with expiry hours
2. Share PIN with operator
3. On lock screen: enter PIN to gain temporary access

---

## Backup & Restore

### Create a backup (requires `pg_dump` in PATH):
- **UI:** Go to **Backup** page → Create Backup Now
- **Script:**
  ```powershell
  cd C:\weighbridge\backend
  .\venv\Scripts\python -c "import subprocess; subprocess.run(['pg_dump', '-U', 'weighbridge', '-d', 'weighbridge', '-f', 'backup.sql'])"
  ```

### Schedule daily backups:
```powershell
# Create a scheduled task (runs daily at 2 AM)
$action = New-ScheduledTaskAction -Execute "powershell" -Argument @"
-Command "Invoke-WebRequest -Uri http://localhost:9001/api/v1/backup/create -Method POST -Headers @{Authorization='Bearer YOUR_ADMIN_TOKEN'}"
"@
$trigger = New-ScheduledTaskTrigger -Daily -At "02:00"
Register-ScheduledTask -TaskName "WeighbridgeBackup" -Action $action -Trigger $trigger -RunLevel Highest
```

### Restore:
- **UI:** Backup page → select backup → click Restore (⚠️ destructive)
- **Manual:**
  ```powershell
  psql -U weighbridge -d weighbridge -f C:\weighbridge\backups\weighbridge_backup_YYYYMMDD_HHMMSS.sql
  ```

---

## Upgrading

```powershell
# 1. Stop service
nssm stop WeighbridgeBackend

# 2. Create backup (always backup before upgrade)
# Via UI or manually

# 3. Copy new files
Copy-Item -Path "new_version\backend" -Destination "C:\weighbridge\backend" -Recurse -Force
Copy-Item -Path "new_version\frontend" -Destination "C:\weighbridge\frontend" -Recurse -Force

# 4. Install new dependencies
cd C:\weighbridge\backend
.\venv\Scripts\pip install -r requirements.txt

# 5. Run migrations
.\venv\Scripts\python -m alembic upgrade head

# 6. Rebuild frontend
cd C:\weighbridge\frontend
npm install
npm run build

# 7. Restart service
nssm start WeighbridgeBackend
```

---

## Troubleshooting

### Backend won't start
```powershell
# Check logs
Get-Content C:\weighbridge\logs\backend_stderr.log -Tail 50

# Test manually
cd C:\weighbridge\backend
.\venv\Scripts\uvicorn app.main:app --port 9001
```

### Database connection error
```powershell
# Test PostgreSQL
psql -U weighbridge -d weighbridge -c "SELECT 1"

# Check if service is running
Get-Service postgresql*

# Check .env file
Get-Content C:\weighbridge\backend\.env
```

### Weight scale not reading
1. Check COM port in Device Manager
2. Verify baud rate matches indicator (usually printed on the label)
3. Try different protocols (essae/continuous)
4. Check USB-to-Serial driver is installed
5. Test with a serial terminal (PuTTY) to verify raw data

### Port 9001 already in use
```powershell
netstat -ano | Select-String ":9001"
# Note the PID, then:
Stop-Process -Id PID -Force
```

### "pg_dump not found" for backup
```powershell
# Add PostgreSQL bin to system PATH
$pgBin = "C:\Program Files\PostgreSQL\15\bin"
[Environment]::SetEnvironmentVariable("Path", "$env:Path;$pgBin", "Machine")
# Restart the service after this
```

### Frontend shows "Cannot connect to server"
- Check backend is running: `http://localhost:9001/api/v1/health`
- Check firewall allows port 9001
- If on LAN: verify `VITE_API_BASE_URL` in frontend `.env` points to server IP

### "Restart Web Interface" button in Recovery Dashboard fails

This means the `WeighbridgeFrontend` Windows service is either not registered or is **DISABLED**.

**Check the current state:**
```powershell
sc.exe qc WeighbridgeFrontend
# Look for START_TYPE — if it says DISABLED, run the fix below
```

**Fix — enable and start the service:**
```powershell
sc.exe config WeighbridgeFrontend start= auto
sc.exe start  WeighbridgeFrontend
```

After this the restart button will work end-to-end. Note: in development mode (running `npm run dev`)
the button intentionally reports *"running in development mode"* — this is normal and expected.

### Recovery Dashboard itself is not opening (port 9002)

```powershell
# Check if watchdog service is running
Get-Service WeighbridgeWatchdog

# Start manually if not registered yet
cd C:\weighbridge\backend
.\venv\Scripts\python watchdog_server.py

# Or register the service (once)
cd C:\weighbridge\scripts
.\install-watchdog.ps1
```

---

## Default Ports

| Service | Port | Notes |
|---|---|---|
| Backend (FastAPI) | 9001 | Change in uvicorn startup args |
| Frontend (production static) | 9000 | Served by `WeighbridgeFrontend` NSSM service |
| Frontend dev (Vite) | 9000 | `npm run dev` — dev mode only |
| Recovery Dashboard (Watchdog) | 9002 | `WeighbridgeWatchdog` service · accessible from LAN |
| PostgreSQL | 5432 | Docker container `weighbridge_db` |
| Weight scale WebSocket | ws://…:9001/ws/weight | Same port as backend |

---

## Support & Logs

- **Application logs:** `C:\weighbridge\logs\`
- **Backend API docs:** `http://localhost:9001/docs` (Swagger UI)
- **Health check:** `http://localhost:9001/api/v1/health`
- **Audit trail:** Login → Audit Trail page

---

*Weighbridge Invoice Software — Built for Indian Stone Crusher SMEs*
*Stack: Python 3.11 + FastAPI · React 19 + TypeScript · PostgreSQL 16 · xhtml2pdf*
