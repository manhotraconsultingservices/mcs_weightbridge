# Weighbridge ERP — Complete Build & Deployment Guide

> **Audience:** Any team member responsible for building, packaging, or deploying the software.
> No prior DevOps experience required. Follow every step in order.

---

## Table of Contents

1. [Overview — What gets built](#1-overview)
2. [One-Time Developer Machine Setup](#2-one-time-developer-machine-setup)
3. [Project Structure Quick Reference](#3-project-structure)
4. [Building the Frontend (React)](#4-building-the-frontend)
5. [Building the Backend (Python → Native .exe)](#5-building-the-backend)
6. [Packaging the Complete Release](#6-packaging-the-complete-release)
7. [Installing on a Client Machine](#7-installing-on-a-client-machine)
8. [Security Hardening After Install](#8-security-hardening-after-install)
9. [Generating a Hardware-Locked License](#9-generating-a-hardware-locked-license)
10. [Updating an Existing Installation](#10-updating-an-existing-installation)
11. [Troubleshooting](#11-troubleshooting)
12. [Quick Reference Cheatsheet](#12-quick-reference-cheatsheet)

---

## 1. Overview

The software has two parts:

| Part | Technology | Build Output |
|---|---|---|
| **Backend** | Python 3.11 + FastAPI | `weighbridge_server.exe` (native binary, no Python needed) |
| **Frontend** | React 19 + TypeScript | `dist/` folder (static HTML/CSS/JS files) |

The backend serves both the API and the frontend files from a single process on port **9001**.

---

## 2. One-Time Developer Machine Setup

Do this **once** on your build computer. You do not need to do this on client machines.

### 2.1 Install Python 3.11

1. Download from https://www.python.org/downloads/release/python-3119/
2. Run installer → check **"Add Python to PATH"** → click **Install Now**
3. Open a new Command Prompt and verify:
   ```
   python --version
   ```
   Expected output: `Python 3.11.x`

### 2.2 Install Node.js 20 LTS

1. Download from https://nodejs.org/en/download (choose **Windows Installer, LTS**)
2. Run installer with all defaults
3. Verify:
   ```
   node --version
   npm --version
   ```
   Expected: `v20.x.x` and `10.x.x`

### 2.3 Install PostgreSQL 16 (development only)

> Skip this if you only need to build — not run — the software.

1. Download from https://www.postgresql.org/download/windows/
2. Run installer, set password for `postgres` superuser to something you'll remember
3. During installation, make sure **pgAdmin** and **Command Line Tools** are selected
4. After install, open pgAdmin and create:
   - User: `weighbridge` with password `weighbridge_dev_2024`
   - Database: `weighbridge` owned by `weighbridge`

### 2.4 Install Git

1. Download from https://git-scm.com/download/win
2. Install with all defaults

### 2.5 Clone the Repository

```cmd
cd C:\Users\Admin\Documents
git clone <your-repo-url> workspace_Weighbridge
cd workspace_Weighbridge
```

### 2.6 Set Up Python Virtual Environment

```cmd
cd C:\Users\Admin\Documents\workspace_Weighbridge\backend
python -m venv venv
venv\Scripts\pip install --upgrade pip
venv\Scripts\pip install -r requirements.txt
```

**This takes 2-5 minutes.** You will see many packages installing.

### 2.7 Install Node.js Dependencies

```cmd
cd C:\Users\Admin\Documents\workspace_Weighbridge\frontend
npm install
```

**This takes 1-3 minutes.**

### 2.8 Install Nuitka (for production builds)

Nuitka compiles Python to native machine code so the source cannot be read.

```cmd
cd C:\Users\Admin\Documents\workspace_Weighbridge\backend
venv\Scripts\pip install nuitka ordered-set zstandard
```

Verify Nuitka is installed:
```cmd
venv\Scripts\python -m nuitka --version
```
Expected output: `2.x.x` (any recent version is fine)

### 2.9 Install a C Compiler (required by Nuitka)

Nuitka compiles Python to C first, then calls a C compiler. You need one of:

**Option A (Recommended): MinGW-w64**
1. Download from https://github.com/niXman/mingw-builds-binaries/releases
   - Choose `x86_64-XX.X.X-release-win32-seh-ucrt-rt_v12-rev0.7z`
2. Extract to `C:\mingw64`
3. Add `C:\mingw64\bin` to your Windows PATH:
   - Press `Win + R` → type `sysdm.cpl` → Advanced → Environment Variables
   - Under System variables → find `Path` → Edit → New → type `C:\mingw64\bin`
4. Verify: open new Command Prompt → `gcc --version`

**Option B: Visual Studio Build Tools**
1. Download from https://visualstudio.microsoft.com/visual-cpp-build-tools/
2. Install **Desktop development with C++** workload
3. Nuitka will find it automatically

---

## 3. Project Structure

```
workspace_Weighbridge/
├── backend/
│   ├── app/                    ← Python source code (NOT deployed to clients)
│   ├── venv/                   ← Python virtual environment (NOT deployed)
│   ├── requirements.txt        ← Python dependencies list
│   ├── run.py                  ← Entry point (what Nuitka compiles)
│   ├── .env                    ← Secrets file (NEVER commit to git)
│   ├── build_dist.ps1          ← Build script (run this to build)
│   ├── setup_dpapi.py          ← Encrypts secrets on client machine
│   ├── show_fingerprint.py     ← Gets hardware ID for license generation
│   └── hardening/
│       └── secure_setup.ps1   ← OS hardening script (run on client)
├── frontend/
│   ├── src/                    ← TypeScript source (NOT deployed)
│   ├── dist/                   ← Built frontend files (deployed)
│   └── package.json
├── license.key                 ← License file (client-specific, from vendor)
└── BUILD_GUIDE.md              ← This file
```

---

## 4. Building the Frontend

The frontend must be built **before** packaging. This converts TypeScript source into
optimised, minified JavaScript files.

### Step 1: Open a terminal in the frontend folder

```cmd
cd C:\Users\Admin\Documents\workspace_Weighbridge\frontend
```

### Step 2: Run the build

```cmd
npm run build
```

**What you will see:**
```
vite v8.x.x building for production...
✓ 847 modules transformed.
dist/index.html                   0.46 kB │ gzip:  0.30 kB
dist/assets/a1b2c3d4.js         423.18 kB │ gzip: 132.51 kB
dist/assets/e5f6a7b8.js          89.24 kB │ gzip:  28.10 kB
✓ built in 12.34s
```

### Step 3: Verify the output

```cmd
dir dist
```

You should see:
- `index.html` (main page)
- `assets/` folder containing `.js` and `.css` files

> ✅ **Security note:** Source maps are disabled in the build config, so the
> original TypeScript source code is **not** included in the output.

### Common Frontend Build Errors

| Error | Fix |
|---|---|
| `npm: command not found` | Node.js not installed or not in PATH — see Section 2.2 |
| `Cannot find module '@/...'` | Run `npm install` first |
| TypeScript errors (red lines) | Run `npx tsc --noEmit` to see all errors, fix them first |
| `ENOSPC: no space left` | Free up disk space |

---

## 5. Building the Backend

This compiles the Python source into a single `.exe` file. The source code is
compiled to machine code — it cannot be read or modified on client machines.

### Step 1: Open a terminal in the backend folder

```cmd
cd C:\Users\Admin\Documents\workspace_Weighbridge\backend
```

### Step 2: Make sure your .env file is correct

The `.env` file must have valid values before building:

```cmd
type .env
```

You should see something like:
```
DATABASE_URL=postgresql+asyncpg://weighbridge:PASSWORD@localhost:5432/weighbridge
SECRET_KEY=<64-char hex string>
PRIVATE_DATA_KEY=<64-char hex string>
```

If `SECRET_KEY` still says `dev-secret-key-change-in-production`, **stop and fix it first**:
```cmd
python -c "import secrets; print(secrets.token_hex(32))"
```
Copy the output and update `SECRET_KEY` in `.env`.

### Step 3: Run the build script

```cmd
powershell -ExecutionPolicy Bypass -File build_dist.ps1
```

**What you will see:**
```
========================================================
  Weighbridge ERP - Nuitka Production Build
========================================================
  Nuitka version : 2.x.x
  Compiling backend to native binary (this takes 3-10 minutes)...
  ...
  (many lines of compilation output)
  ...
========================================================
  BUILD SUCCESSFUL
  Output : C:\...\backend\dist\weighbridge_server.exe
  Size   : 87.3 MB
========================================================
```

> ⏱️ **The first build takes 5-15 minutes.** Subsequent builds are faster because
> Nuitka caches compiled C code.

### Step 4: Verify the binary

```cmd
dir dist\weighbridge_server.exe
```

The file size should be between **50 MB and 150 MB**.

Test that it starts correctly (it will begin listening — press Ctrl+C to stop):
```cmd
dist\weighbridge_server.exe
```

Expected output:
```
INFO:     Started server process [XXXX]
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:9001 (Press CTRL+C to quit)
```
If you see `Application startup complete`, the binary is working. Press `Ctrl+C` to stop.

### Common Backend Build Errors

| Error | Fix |
|---|---|
| `gcc not found` or `no C compiler` | Install MinGW-w64 and add to PATH (Section 2.9) |
| `ModuleNotFoundError: No module named 'nuitka'` | Run: `venv\Scripts\pip install nuitka` |
| `Import Error` for any module | Add `--include-package=<modulename>` to `build_dist.ps1` Nuitka args |
| Out of memory during build | Close other applications, need at least 4 GB free RAM |
| Build output missing some files | Ensure `--include-data-dir` covers templates folder |

---

## 6. Packaging the Complete Release

After building both parts, assemble the deployment package.

### Step 1: Create a release folder

```cmd
mkdir C:\Releases\WeighbridgeERP_v1.0
```

### Step 2: Copy all required files

```cmd
set RELEASE=C:\Releases\WeighbridgeERP_v1.0

REM Backend binary
mkdir %RELEASE%\backend
copy backend\dist\weighbridge_server.exe %RELEASE%\backend\

REM Secrets setup and hardening tools
copy backend\setup_dpapi.py %RELEASE%\backend\
copy backend\show_fingerprint.py %RELEASE%\backend\
mkdir %RELEASE%\backend\hardening
copy backend\hardening\secure_setup.ps1 %RELEASE%\backend\hardening\

REM Frontend (built files only — NOT src/)
mkdir %RELEASE%\frontend
xcopy frontend\dist %RELEASE%\frontend\dist\ /E /I

REM NSSM service registration scripts (if you have them)
copy nssm-register.ps1 %RELEASE%\ 2>nul

REM Build guide and setup guide
copy BUILD_GUIDE.md %RELEASE%\
```

### Step 3: Create a template .env file

Create `%RELEASE%\backend\.env.template` with placeholder values:

```
DATABASE_URL=postgresql+asyncpg://weighbridge:CHANGE_ME@localhost:5432/weighbridge
DATABASE_URL_SYNC=postgresql+psycopg://weighbridge:CHANGE_ME@localhost:5432/weighbridge
SECRET_KEY=GENERATE_WITH_PYTHON_SECRETS_TOKEN_HEX_32
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=480
PRIVATE_DATA_KEY=GENERATE_WITH_PYTHON_SECRETS_TOKEN_HEX_32
COMPANY_NAME=<CLIENT_COMPANY_NAME>
```

> ⚠️ **Do NOT include a real `.env` file in the release package.**
> Each client machine must have its own secrets.

### Step 4: What your release folder should look like

```
WeighbridgeERP_v1.0/
├── backend/
│   ├── weighbridge_server.exe  ← The compiled backend
│   ├── setup_dpapi.py          ← Run after install to encrypt secrets
│   ├── show_fingerprint.py     ← Run to get hardware ID for licensing
│   ├── .env.template           ← Template — fill in and rename to .env
│   └── hardening/
│       └── secure_setup.ps1   ← OS hardening
├── frontend/
│   └── dist/                   ← Static web files served by the backend
├── BUILD_GUIDE.md
└── (license.key added per-client by vendor)
```

---

## 7. Installing on a Client Machine

### Prerequisites on client machine:
- Windows 10/11 64-bit
- PostgreSQL 16 installed
- **Python 3.11** installed (needed for `setup_dpapi.py` and `show_fingerprint.py` — see Section 2.1)
- NSSM (Non-Sucking Service Manager) installed — download from https://nssm.cc/download
- At least 4 GB RAM and 20 GB free disk space

> 📝 Python is only needed during initial setup. After `setup_dpapi.py` encrypts the secrets,
> Python is no longer required to run the software day-to-day.

---

### Step 1: Install PostgreSQL on client machine

1. Download PostgreSQL 16 installer from https://www.postgresql.org/download/windows/
2. Install to `C:\Program Files\PostgreSQL\16`
3. During install, note the password you set for the `postgres` superuser
4. After install, open **SQL Shell (psql)** and run:

```sql
CREATE USER weighbridge WITH PASSWORD 'choose-a-strong-password-here';
CREATE DATABASE weighbridge OWNER weighbridge;
GRANT ALL PRIVILEGES ON DATABASE weighbridge TO weighbridge;
\q
```

> 📝 Note the password you chose — you'll need it in Step 3.

---

### Step 2: Copy release files to client machine

Copy the entire release package to the client machine.
Recommended install path: `C:\weighbridge\`

```
C:\weighbridge\
├── backend\
│   ├── weighbridge_server.exe
│   ├── setup_dpapi.py
│   ├── show_fingerprint.py
│   └── hardening\
│       └── secure_setup.ps1
├── frontend\
│   └── dist\
└── license.key   (← add this before starting — see Section 9)
```

---

### Step 3: Create the .env secrets file

On the client machine, create `C:\weighbridge\backend\.env`:

```
DATABASE_URL=postgresql+asyncpg://weighbridge:YOUR_DB_PASSWORD@localhost:5432/weighbridge
DATABASE_URL_SYNC=postgresql+psycopg://weighbridge:YOUR_DB_PASSWORD@localhost:5432/weighbridge
SECRET_KEY=<run: python -c "import secrets; print(secrets.token_hex(32))">
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=480
PRIVATE_DATA_KEY=<run: python -c "import secrets; print(secrets.token_hex(32))">
COMPANY_NAME=Client Company Name Here
```

Generate the two random keys from Command Prompt (Python must be installed):
```cmd
python -c "import secrets; print(secrets.token_hex(32))"
```
Run this **twice** — once for `SECRET_KEY`, once for `PRIVATE_DATA_KEY`. Copy each output to the `.env` file.

> ⚠️ **CRITICAL: Write down PRIVATE_DATA_KEY and store it offline.**
> If this key is lost, all encrypted private invoice data is permanently unrecoverable.

---

### Step 4: Start the server manually (first-time test)

Before registering as a service, verify the server starts:

```cmd
cd C:\weighbridge\backend
weighbridge_server.exe
```

You should see:
```
INFO:     Started server process [XXXX]
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:9001
```

Open a browser and go to `http://localhost:9001` — you should see the login page.

Press `Ctrl+C` to stop.

If you see a **license error**, go to Section 9 first.

---

### Step 5: Register as a Windows Service

Using NSSM, register the server to start automatically:

```cmd
nssm install WeighbridgeERP "C:\weighbridge\backend\weighbridge_server.exe"
nssm set WeighbridgeERP AppDirectory "C:\weighbridge\backend"
nssm set WeighbridgeERP AppStdout "C:\weighbridge\logs\weighbridge.log"
nssm set WeighbridgeERP AppStderr "C:\weighbridge\logs\weighbridge_error.log"
nssm set WeighbridgeERP AppRotateFiles 1
nssm set WeighbridgeERP AppRotateBytes 10485760
nssm set WeighbridgeERP Start SERVICE_AUTO_START
nssm start WeighbridgeERP
```

Verify service is running:
```cmd
sc query WeighbridgeERP
```

Expected output includes: `STATE: 4 RUNNING`

---

### Step 6: Create log directory

```cmd
mkdir C:\weighbridge\logs
```

---

## 8. Security Hardening After Install

**Do this on every client machine, without exception.**

### Step 1: Encrypt secrets with DPAPI

This locks the .env secrets to this specific machine so they cannot be read on another computer.

Open **Command Prompt as Administrator** and run:

```cmd
cd C:\weighbridge\backend
python setup_dpapi.py
```

Follow the prompts. At the end:
- `secrets.dpapi` is created — this file is machine-locked
- `.env` is renamed to `.env.bak`

**Immediately after this:**
1. Copy `.env.bak` to a secure USB drive or password manager
2. Delete `.env.bak` from the machine:
   ```cmd
   del C:\weighbridge\backend\.env.bak
   ```

> 🔐 If the machine needs to be rebuilt, you'll use .env.bak to recreate secrets.dpapi.

---

### Step 2: Run OS Hardening Script

Open **Command Prompt as Administrator** and run:

```cmd
powershell -ExecutionPolicy Bypass -File "C:\weighbridge\backend\hardening\secure_setup.ps1" -InstallDir "C:\weighbridge"
```

This script automatically:
- Creates a least-privilege Windows service account
- Locks file permissions so only the service account can read app files
- Restricts PostgreSQL to localhost-only (blocks LAN access to database)
- Changes the PostgreSQL password to a random 32-character value
- Adds Windows Firewall rules blocking external database access
- Checks BitLocker status and offers to enable it

Follow the on-screen prompts. **Write down the new database password shown** and update `secrets.dpapi` by re-running `setup_dpapi.py` with the updated `.env`.

---

### Step 3: Enable BitLocker (if prompted)

If the script says BitLocker is not enabled:

1. Press `Win + R` → type `manage-bde` → Enter
2. Or: Control Panel → System and Security → BitLocker Drive Encryption
3. Click **Turn on BitLocker** for the C: drive
4. Choose **Save to a file** for the recovery key → save to a USB drive
5. Choose **Encrypt entire drive**
6. Click **Start encrypting** (takes 1-4 hours depending on disk size)

> ⚠️ **Without BitLocker, anyone who steals the hard drive can read all business data.**

---

### Step 4: Restart the service

After all hardening steps:

```cmd
net stop WeighbridgeERP
net start WeighbridgeERP
```

---

## 9. Generating a Hardware-Locked License

Every client machine needs a license file. The license is cryptographically signed
and bound to the specific hardware — it cannot be copied to another machine.

### Step 1: Get the client's hardware fingerprint

On the **client machine**, run:

```cmd
cd C:\weighbridge\backend
python show_fingerprint.py
```

Output example:
```
Hostname        : CRUSHER-PC-01

Hardware Factors (RAW):
  cpu       : BFEBFBFF000906ED
  mb        : To be filled by O.E.M.
  disk      : S3YUNX0M123456
  winprod   : 00330-80000-00000-AA001

Full Fingerprint (SHA-256):
  a7f3b2c9d1e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0

Factor Hashes (for 2-of-4 tolerance):
  cpu       : 3f7a9b2c...
  mb        : 1a2b3c4d...
  disk      : 9e8f7a6b...
  winprod   : 5c4d3e2f...

Paste the following into generate_license.py:
{
    "hostname": "CRUSHER-PC-01",
    "hardware_fingerprint": "a7f3b2c9d1e4f5...",
    "factor_hashes": { ... }
}
```

Copy the entire JSON block at the bottom. Send it to the license generator.

---

### Step 2: Generate the license (vendor side only)

On the **vendor machine** (not the client), run `generate_license.py` with:
- Customer name
- Expiry date
- Hardware fingerprint JSON from Step 1

The script outputs a `license.key` file.

---

### Step 3: Deploy the license file

Copy `license.key` to the **root** of the installation:
```
C:\weighbridge\license.key
```

Restart the service:
```cmd
net stop WeighbridgeERP
net start WeighbridgeERP
```

Check the license is accepted by opening the app in a browser.

---

## 10. Updating an Existing Installation

When releasing a new version:

### Step 1: Build new binaries (developer machine)

```cmd
REM Frontend
cd frontend
npm run build

REM Backend
cd ..\backend
powershell -ExecutionPolicy Bypass -File build_dist.ps1
```

### Step 2: Stop the service on client

```cmd
net stop WeighbridgeERP
```

### Step 3: Replace the files

```cmd
REM Replace backend binary
copy dist\weighbridge_server.exe C:\weighbridge\backend\weighbridge_server.exe

REM Replace frontend files
rd /s /q C:\weighbridge\frontend\dist
xcopy frontend\dist C:\weighbridge\frontend\dist\ /E /I
```

### Step 4: Restart the service

```cmd
net start WeighbridgeERP
```

> 📌 **You do NOT need to re-run security hardening or re-encrypt secrets**
> unless the .env values have changed.

---

## 11. Troubleshooting

### "License file not found"
- Check `C:\weighbridge\license.key` exists
- Check file is not corrupted (should start with `-----BEGIN WEIGHBRIDGE LICENSE-----`)

### "License hardware fingerprint does not match"
- The software was copied to a different machine without a new license
- Run `show_fingerprint.py` and request a new license from the vendor

### "Could not validate credentials" (login)
- Username or password is wrong
- After 5 failed attempts from the same IP, the system locks for 15 minutes
- Admin can check `login_audit` table in the database for details

### Server won't start — port already in use
```cmd
netstat -ano | findstr :9001
taskkill /PID <pid-number> /F
net start WeighbridgeERP
```

### Server won't start — database connection error
- Verify PostgreSQL is running: `sc query postgresql-x64-16`
- Verify credentials in `.env` (or `secrets.dpapi`) are correct
- Test connection: `psql -U weighbridge -d weighbridge -h localhost`

### "DPAPI decryption failed"
- `secrets.dpapi` was created on a different machine
- Restore `.env.bak` from your secure backup, re-run `setup_dpapi.py`

### Frontend shows blank page after update
- Clear browser cache: `Ctrl + Shift + Delete` in browser
- Or open in incognito/private mode

### Nuitka build fails with memory error
- Close all other applications
- Restart the build machine
- Minimum 8 GB RAM recommended for Nuitka builds

---

## 12. Quick Reference Cheatsheet

```
╔═══════════════════════════════════════════════════════════════════════╗
║            WEIGHBRIDGE ERP — BUILD QUICK REFERENCE                   ║
╠═══════════════════════════════════════════════════════════════════════╣
║  DEVELOPER MACHINE  (run from Command Prompt)                         ║
║  ────────────────────────────────────────────                         ║
║  Build frontend:                                                       ║
║    cd frontend                                                         ║
║    npm run build                                                       ║
║                                                                        ║
║  Build backend (Nuitka — takes 5-15 min):                             ║
║    cd backend                                                          ║
║    powershell -ExecutionPolicy Bypass -File build_dist.ps1            ║
║                                                                        ║
║  Start dev server:                                                     ║
║    cd backend                                                          ║
║    venv\Scripts\uvicorn app.main:app --reload --port 9001             ║
║                                                                        ║
╠═══════════════════════════════════════════════════════════════════════╣
║  CLIENT MACHINE SETUP  (run from Command Prompt as Administrator)     ║
║  ────────────────────────────────────────────────────────────────     ║
║  Encrypt secrets (one-time):                                           ║
║    cd C:\weighbridge\backend                                           ║
║    python setup_dpapi.py                                               ║
║                                                                        ║
║  Get hardware ID for license:                                          ║
║    python show_fingerprint.py                                          ║
║                                                                        ║
║  Run OS hardening (one-time):                                          ║
║    powershell -ExecutionPolicy Bypass -File                            ║
║      C:\weighbridge\backend\hardening\secure_setup.ps1                ║
║      -InstallDir C:\weighbridge                                        ║
║                                                                        ║
╠═══════════════════════════════════════════════════════════════════════╣
║  SERVICE MANAGEMENT  (Command Prompt)                                 ║
║  ───────────────────────────────────                                   ║
║  Start service:   net start WeighbridgeERP                            ║
║  Stop service:    net stop WeighbridgeERP                             ║
║  Check status:    sc query WeighbridgeERP                             ║
║  View log:        type C:\weighbridge\logs\weighbridge.log            ║
║  Check port:      netstat -ano | findstr :9001                        ║
║                                                                        ║
╠═══════════════════════════════════════════════════════════════════════╣
║  PORTS                                                                ║
║  ──────                                                               ║
║  Backend API + Frontend : 9001                                        ║
║  PostgreSQL (local only) : 5432                                       ║
║  Weight Scale WebSocket  : ws://localhost:9001/ws/weight              ║
╚═══════════════════════════════════════════════════════════════════════╝
```

---

*Last updated: April 2026 | For support contact the development team*
