# Weighbridge — Windows Service Setup Guide

Run both the backend and frontend as **Windows Services** that start automatically
when the server boots, restart on crash, and write logs to the `logs/` folder.

---

## What Gets Installed

| Service Name | What It Does | Port | Auto-Start |
|---|---|---|---|
| `WeighbridgeBackend` | FastAPI backend (Python/uvicorn) | 9001 | Yes |
| `WeighbridgeFrontend` | Serves built React app (node/serve) | 9000 | Yes |

Both services:
- Start automatically when Windows boots
- Restart automatically if they crash
- Write logs to `<project>\logs\`
- Load all environment variables from `backend\.env`

---

## Prerequisites

Before running the service installer, ensure the following are installed:

| Requirement | Check | Install |
|---|---|---|
| Python 3.11+ | `python --version` | https://python.org |
| Node.js 20+ | `node --version` | https://nodejs.org |
| PostgreSQL 15+ running | `psql --version` | Via Docker: `docker compose up -d` |
| Backend `.env` configured | File exists at `backend\.env` | See step 1 below |

---

## Step 1 — Verify `.env` is Configured

Open `backend\.env` and confirm these values exist:

```env
DATABASE_URL=postgresql+asyncpg://weighbridge:weighbridge_dev_2024@localhost:5432/weighbridge
DATABASE_URL_SYNC=postgresql+psycopg://weighbridge:weighbridge_dev_2024@localhost:5432/weighbridge
SECRET_KEY=<64-char hex string>
ACCESS_TOKEN_EXPIRE_MINUTES=480
PRIVATE_DATA_KEY=<64-char hex string>
```

> **CRITICAL:** `PRIVATE_DATA_KEY` is required for secret invoices.
> If it is missing, run from `backend\` folder:
> ```
> python -c "import secrets; print(secrets.token_hex(32))"
> ```
> Copy the output and add `PRIVATE_DATA_KEY=<output>` to `.env`.

---

## Step 2 — Open PowerShell as Administrator

1. Press `Win + X`
2. Click **"Windows PowerShell (Admin)"** or **"Terminal (Admin)"**
3. You must see **"Administrator"** in the title bar

---

## Step 3 — Navigate to the Project Folder

```powershell
cd "C:\Users\Admin\Documents\workspace_Weighbridge"
```

Adjust the path if your project is in a different location.

---

## Step 4 — Run the Service Installer

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-services.ps1
```

The script will automatically:

1. **Download NSSM** (Non-Sucking Service Manager) if not already present
   - Saved to `tools\nssm.exe`
   - If download fails (no internet): manually download from https://nssm.cc/download,
     extract `nssm.exe` (win64 version) and place it at `tools\nssm.exe`

2. **Install the `serve` npm package** globally (serves React production build)

3. **Build the React frontend** (`npm run build` → creates `frontend\dist\`)

4. **Register `WeighbridgeBackend` service:**
   - Executable: `python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 9001 --workers 2`
   - Working directory: `backend\`
   - All `.env` variables injected automatically
   - Logs: `logs\backend_stdout.log` + `logs\backend_stderr.log`

5. **Register `WeighbridgeFrontend` service:**
   - Executable: `serve -s frontend\dist -l 9000`
   - Depends on: `WeighbridgeBackend` (starts only after backend is running)
   - Logs: `logs\frontend_stdout.log` + `logs\frontend_stderr.log`

6. **Start both services** and report status

### Expected Output

```
╔══════════════════════════════════════════════════════╗
║    Weighbridge Invoice Software — Service Installer   ║
╚══════════════════════════════════════════════════════╝

  Using NSSM: C:\...\tools\nssm.exe
  Python: C:\Users\Admin\AppData\Local\Python\...\python.exe
  Node:   C:\Program Files\nodejs\node.exe

Step 1 — Reading environment variables from .env
  Loaded 7 variables from .env
  PRIVATE_DATA_KEY: present (encryption enabled)

Step 2 — Building frontend for production
  Running npm run build...
  Frontend built at: ...\frontend\dist

Step 3 — Registering backend service (WeighbridgeBackend)
  Backend service registered.

Step 4 — Registering frontend service (WeighbridgeFrontend)
  Frontend service registered.

Step 5 — Starting services
  Starting WeighbridgeBackend... Running
  Starting WeighbridgeFrontend... Running

╔══════════════════════════════════════════════════════╗
║               Services Registered!                   ║
╚══════════════════════════════════════════════════════╝

  Backend  URL : http://localhost:9001
  Frontend URL : http://localhost:9000
```

---

## Step 5 — Verify Services Are Running

Open your browser and check:

| URL | Expected |
|---|---|
| `http://localhost:9000` | Weighbridge login page |
| `http://localhost:9001/docs` | FastAPI Swagger UI |
| `http://localhost:9001/api/v1/dashboard/summary` | Returns JSON (after login) |

Also verify in Windows Services panel:
1. Press `Win + R` → type `services.msc` → press Enter
2. Scroll to **W** — you should see:
   - `Weighbridge — Backend (FastAPI)` → Status: **Running**
   - `Weighbridge — Frontend (Static)` → Status: **Running**

---

## Step 6 — Access from Other Computers on LAN

Other computers on the same network can access the software using the server's IP address:

1. Find the server's IP: Open Command Prompt → type `ipconfig` → look for **IPv4 Address**
   (e.g., `192.168.1.10`)

2. From any LAN machine, open browser:
   ```
   http://192.168.1.10:9000
   ```

3. If it doesn't connect, check Windows Firewall:
   ```powershell
   # Allow port 9000 (frontend) and 9001 (backend)
   New-NetFirewallRule -DisplayName "Weighbridge Frontend" -Direction Inbound -Protocol TCP -LocalPort 9000 -Action Allow
   New-NetFirewallRule -DisplayName "Weighbridge Backend"  -Direction Inbound -Protocol TCP -LocalPort 9001 -Action Allow
   ```

---

## Managing Services

After installation, use the management script for day-to-day operations:

```powershell
# Always run as Administrator
powershell -ExecutionPolicy Bypass -File scripts\manage-services.ps1 <action> [target]
```

### Actions

| Command | Description |
|---|---|
| `.\manage-services.ps1 status` | Show status of both services |
| `.\manage-services.ps1 start` | Start both services |
| `.\manage-services.ps1 stop` | Stop both services |
| `.\manage-services.ps1 restart` | Restart both services |
| `.\manage-services.ps1 restart backend` | Restart backend only (after code update) |
| `.\manage-services.ps1 logs backend` | Live tail of backend log (Ctrl+C to stop) |
| `.\manage-services.ps1 logs frontend` | Live tail of frontend log |

### Quick Commands (without script)

```powershell
# View status in Services panel
Get-Service Weighbridge*

# Start / Stop / Restart using NSSM
nssm start  WeighbridgeBackend
nssm stop   WeighbridgeBackend
nssm restart WeighbridgeBackend

# View live backend log
Get-Content logs\backend_stderr.log -Wait -Tail 50
```

---

## Updating the Application (After Code Changes)

### Backend code changed (Python files):

```powershell
# Run as Administrator
powershell -ExecutionPolicy Bypass -File scripts\manage-services.ps1 restart backend
```

### Frontend code changed (React/TypeScript files):

```powershell
# Rebuild frontend first
cd frontend
npm run build

# Then restart the frontend service
cd ..
powershell -ExecutionPolicy Bypass -File scripts\manage-services.ps1 restart frontend
```

### Database migration needed (after adding new tables/columns):

```powershell
# Stop backend, run migration, restart
powershell -ExecutionPolicy Bypass -File scripts\manage-services.ps1 stop backend
cd backend
python -m alembic upgrade head
cd ..
powershell -ExecutionPolicy Bypass -File scripts\manage-services.ps1 start backend
```

---

## Removing the Services

To completely remove both Windows services:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-services.ps1 -Unregister
```

This stops and deletes both `WeighbridgeBackend` and `WeighbridgeFrontend`.
Your data and code are untouched — only the service registrations are removed.

---

## Log Files

All logs are written to the `logs\` folder in the project root:

| File | Contents |
|---|---|
| `logs\backend_stdout.log` | Backend info/access logs |
| `logs\backend_stderr.log` | Backend errors and startup messages |
| `logs\frontend_stdout.log` | Frontend server access log |
| `logs\frontend_stderr.log` | Frontend errors |

Logs auto-rotate at 10 MB (backend) and 5 MB (frontend).

---

## Troubleshooting

### Service won't start — "Python not found"

The installer couldn't find Python with uvicorn. Fix:
```powershell
# Verify Python is in PATH and uvicorn is installed
python --version
python -m uvicorn --version

# If uvicorn is missing, install it
pip install uvicorn[standard] fastapi sqlalchemy asyncpg
```

### Service won't start — "serve not found"

```powershell
npm install -g serve
# Then re-run: powershell -File scripts\install-services.ps1
```

### Backend starts but frontend shows blank page

The frontend dist is missing or stale. Rebuild:
```powershell
cd frontend
npm install
npm run build
cd ..
powershell -ExecutionPolicy Bypass -File scripts\manage-services.ps1 restart frontend
```

### "Access denied" running the installer

You must run PowerShell **as Administrator**. Right-click PowerShell → "Run as Administrator".

### NSSM download fails (no internet on server)

1. On a machine with internet: download https://nssm.cc/release/nssm-2.24.zip
2. Extract the zip
3. Copy `nssm-2.24\win64\nssm.exe` to `<project>\tools\nssm.exe`
4. Re-run the installer — it will find `tools\nssm.exe` automatically

### Port already in use

```powershell
# Find what is using port 9001
netstat -ano | findstr :9001
# Kill by PID
taskkill /PID <pid> /F
```

### Check service environment variables

```powershell
# Verify PRIVATE_DATA_KEY reached the service
nssm get WeighbridgeBackend AppEnvironmentExtra
```

---

## Architecture After Service Installation

```
Windows Boot
    │
    ├── PostgreSQL Service  (starts automatically, managed by PostgreSQL installer)
    │
    ├── WeighbridgeBackend  (auto-start, depends on nothing)
    │     python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 9001 --workers 2
    │     Reads: backend\.env  (DATABASE_URL, SECRET_KEY, PRIVATE_DATA_KEY)
    │     Logs:  logs\backend_stderr.log
    │
    └── WeighbridgeFrontend  (auto-start, depends on WeighbridgeBackend)
          serve -s frontend\dist -l 9000
          Logs: logs\frontend_stderr.log

LAN Clients → http://<server-ip>:9000  →  WeighbridgeFrontend
                                       →  API calls via Vite proxy → WeighbridgeBackend :9001
```
