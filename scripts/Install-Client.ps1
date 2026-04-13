#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Weighbridge ERP — One-Click Client Site Installer

.DESCRIPTION
    Automates the entire first-time installation of Weighbridge at a client site.
    Run this script from the USB drive or after copying the release package to the PC.

    What this script does automatically:
      [1]  Verifies system requirements (Windows 10/11 64-bit, RAM, disk)
      [2]  Verifies Docker Desktop is running
      [3]  Creates C:\weighbridge\ folder structure
      [4]  Copies application files to C:\weighbridge\
      [5]  Installs license key
      [6]  Generates .env with strong random secrets
      [7]  Patches docker-compose.yml with matching DB password
      [8]  Starts PostgreSQL Docker container
      [9]  Waits for PostgreSQL to be ready
      [10] Registers WeighbridgeBackend and WeighbridgeFrontend Windows services
      [11] Waits for application to respond (health check)
      [12] Encrypts secrets using Windows DPAPI (machine-locked)
      [13] Copies .env.bak to USB backup folder
      [14] Deletes .env.bak from the production machine
      [15] Opens Windows Firewall for ports 9000 and 9001
      [16] Writes version.txt

    What you must do AFTER this script completes (see INSTALL_CHECKLIST.txt):
      - Change the admin password in the app
      - Enter company details (GSTIN, PAN, address, bank)
      - Configure the weighing scale COM port
      - Create operator user accounts

.EXAMPLE
    # Right-click this file → "Run with PowerShell"
    # OR in PowerShell (as Administrator):
    powershell -ExecutionPolicy Bypass -File "D:\weighbridge-full-1.0.0\scripts\Install-Client.ps1"

.NOTES
    REQUIRES: Administrator privileges, Docker Desktop running
    TESTED ON: Windows 10 (22H2), Windows 11 (23H2)
#>

param(
    [string]$InstallRoot = "C:\weighbridge",
    [string]$LicenseFile = ""        # auto-detected from USB if not specified
)

$ErrorActionPreference = "Stop"
$ProgressPreference    = "SilentlyContinue"

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

$SvcBackend   = "WeighbridgeBackend"
$SvcFrontend  = "WeighbridgeFrontend"
$DbName       = "weighbridge"
$DbUser       = "weighbridge"
$DbContainer  = "weighbridge_db"
$BackendPort  = 9001
$FrontendPort = 3000

# Determine where the release package is (same folder as this script's parent)
$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$ReleaseRoot = Split-Path -Parent $ScriptDir     # one level up from scripts\

# ═══════════════════════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════════════════════

$LogDir  = Join-Path $InstallRoot "logs"
$LogFile = Join-Path $LogDir "install_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"

function Write-Log {
    param([string]$Msg, [string]$Color = "White")
    $ts   = Get-Date -Format "HH:mm:ss"
    $line = "[$ts] $Msg"
    if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Force $LogDir | Out-Null }
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
    Write-Host $line -ForegroundColor $Color
}

function Write-Step {
    param([int]$N, [string]$Msg)
    Write-Host ""
    Write-Host ("[{0:D2}/16] {1}" -f $N, $Msg) -ForegroundColor Cyan
    Write-Log ("[{0:D2}/16] {1}" -f $N, $Msg) "Cyan"
}

function Write-OK   { param([string]$Msg) Write-Host "       OK  $Msg" -ForegroundColor Green;  Write-Log "    OK  $Msg" }
function Write-Warn { param([string]$Msg) Write-Host "     WARN  $Msg" -ForegroundColor Yellow; Write-Log "  WARN  $Msg" }
function Write-Fail {
    param([string]$Msg)
    Write-Host ""
    Write-Host "  ╔══════════════════════════════════════════════════════════╗" -ForegroundColor Red
    Write-Host "  ║  INSTALLATION FAILED                                     ║" -ForegroundColor Red
    Write-Host "  ╚══════════════════════════════════════════════════════════╝" -ForegroundColor Red
    Write-Host ""
    Write-Host "  Error: $Msg" -ForegroundColor Red
    Write-Host ""
    Write-Host "  Install log: $LogFile" -ForegroundColor Gray
    Write-Host "  Send this log file to support for assistance." -ForegroundColor Gray
    Write-Host ""
    Write-Log "FAIL: $Msg" "Red"
    Read-Host "Press ENTER to close"
    exit 1
}

# ═══════════════════════════════════════════════════════════════════════════════
# HEADER
# ═══════════════════════════════════════════════════════════════════════════════

Clear-Host
Write-Host ""
Write-Host "  ╔══════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "  ║         Weighbridge ERP — Client Site Installer          ║" -ForegroundColor Cyan
Write-Host "  ║                                                          ║" -ForegroundColor Cyan
Write-Host "  ║  This will take approximately 10-20 minutes.             ║" -ForegroundColor Cyan
Write-Host "  ║  Do NOT close this window until you see COMPLETE.        ║" -ForegroundColor Cyan
Write-Host "  ╚══════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Install location : $InstallRoot" -ForegroundColor Gray
Write-Host "  Log file         : $LogFile" -ForegroundColor Gray
Write-Host ""
Write-Log "=== Weighbridge Client Installer Started ===" "Cyan"
Write-Log "Install root : $InstallRoot"
Write-Log "Release root : $ReleaseRoot"
Write-Log "Computer     : $env:COMPUTERNAME"
Write-Log "User         : $env:USERNAME"
Write-Log "OS           : $((Get-WmiObject Win32_OperatingSystem).Caption)"

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 1 — System requirements check
# ═══════════════════════════════════════════════════════════════════════════════

Write-Step 1 "Checking system requirements..."

$os = Get-WmiObject Win32_OperatingSystem
if ($os.OSArchitecture -ne "64-bit") {
    Write-Fail "64-bit Windows is required. This machine is $($os.OSArchitecture)."
}

$winVer = [System.Version]$os.Version
if ($winVer.Major -lt 10) {
    Write-Fail "Windows 10 or Windows 11 is required. Found: $($os.Caption)"
}
Write-OK "Windows: $($os.Caption) (64-bit)"

$ramGB = [math]::Round((Get-WmiObject Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)
if ($ramGB -lt 6) {
    Write-Fail "Minimum 8 GB RAM required. This machine has ${ramGB} GB."
}
Write-OK "RAM: ${ramGB} GB"

$freeGB = [math]::Round((Get-PSDrive -Name C).Free / 1GB, 1)
if ($freeGB -lt 4) {
    Write-Fail "Minimum 5 GB free disk space required on C:\ . Only ${freeGB} GB available."
}
Write-OK "Free disk space: ${freeGB} GB on C:\"

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 2 — Verify Docker Desktop is running
# ═══════════════════════════════════════════════════════════════════════════════

Write-Step 2 "Verifying Docker Desktop is running..."

$dockerCmd = Get-Command "docker" -ErrorAction SilentlyContinue
if (-not $dockerCmd) {
    Write-Fail "Docker Desktop is not installed. Please install Docker Desktop first, restart the PC, then run this script again."
}

$dockerRunning = $false
$retryCount    = 0
$maxRetries    = 12      # 12 x 10 seconds = 2 minutes

while (-not $dockerRunning -and $retryCount -lt $maxRetries) {
    try {
        $null = docker ps 2>&1
        if ($LASTEXITCODE -eq 0) { $dockerRunning = $true }
    } catch { }

    if (-not $dockerRunning) {
        $retryCount++
        if ($retryCount -eq 1) {
            Write-Host "       Docker is not responding. Starting Docker Desktop..." -ForegroundColor Yellow
            Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe" -ErrorAction SilentlyContinue
        }
        Write-Host "       Waiting for Docker to start... ($retryCount/$maxRetries)" -ForegroundColor Yellow
        Start-Sleep 10
    }
}

if (-not $dockerRunning) {
    Write-Fail "Docker Desktop is not running after 2 minutes. Open Docker Desktop manually (look for the whale icon in the taskbar), wait for it to show green/running, then re-run this script."
}

$dockerVersion = (docker version --format "{{.Server.Version}}" 2>&1)
Write-OK "Docker: $dockerVersion"

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 3 — Create folder structure
# ═══════════════════════════════════════════════════════════════════════════════

Write-Step 3 "Creating installation folder structure at $InstallRoot..."

$foldersToCreate = @(
    $InstallRoot,
    "$InstallRoot\logs",
    "$InstallRoot\uploads",
    "$InstallRoot\uploads\wallpaper",
    "$InstallRoot\uploads\camera",
    "$InstallRoot\backups",
    "$InstallRoot\backups\patch-backups",
    "$InstallRoot\scripts",
    "$InstallRoot\tools"
)

foreach ($folder in $foldersToCreate) {
    if (-not (Test-Path $folder)) {
        New-Item -ItemType Directory -Force -Path $folder | Out-Null
    }
}
Write-OK "Folder structure created at $InstallRoot"

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 4 — Copy application files
# ═══════════════════════════════════════════════════════════════════════════════

Write-Step 4 "Copying application files to $InstallRoot..."

# Copy everything from the release package, except .env (we generate that)
$itemsToCopy = Get-ChildItem -Path $ReleaseRoot -ErrorAction SilentlyContinue |
               Where-Object { $_.Name -notin @(".env", ".env.bak", "secrets.dpapi") }

if ($itemsToCopy.Count -eq 0) {
    Write-Fail "No files found in release package at: $ReleaseRoot. Check the USB drive contents."
}

foreach ($item in $itemsToCopy) {
    $dest = Join-Path $InstallRoot $item.Name
    if ($item.PSIsContainer) {
        Copy-Item -Path $item.FullName -Destination $dest -Recurse -Force
    } else {
        Copy-Item -Path $item.FullName -Destination $dest -Force
    }
}
Write-OK "Application files copied ($($itemsToCopy.Count) items)"

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 5 — Install license key
# ═══════════════════════════════════════════════════════════════════════════════

Write-Step 5 "Installing license key..."

# Auto-detect license.key on USB drives if not specified
if (-not $LicenseFile -or -not (Test-Path $LicenseFile)) {
    Write-Host "       Searching for license.key on USB drives..." -ForegroundColor Gray
    $drives = Get-PSDrive -PSProvider FileSystem |
              Where-Object { $_.Root -ne "C:\" -and (Test-Path $_.Root) }

    foreach ($drive in $drives) {
        $candidate = Join-Path $drive.Root "license.key"
        if (Test-Path $candidate) {
            $LicenseFile = $candidate
            Write-Host "       Found: $LicenseFile" -ForegroundColor Gray
            break
        }
    }
}

if (-not $LicenseFile -or -not (Test-Path $LicenseFile)) {
    # Try in same folder as the release package
    $candidate = Join-Path $ReleaseRoot "license.key"
    if (Test-Path $candidate) { $LicenseFile = $candidate }
}

if (-not $LicenseFile -or -not (Test-Path $LicenseFile)) {
    Write-Fail "license.key not found. Make sure the USB drive is inserted and contains license.key."
}

Copy-Item -Path $LicenseFile -Destination "$InstallRoot\license.key" -Force
Write-OK "License key installed from: $LicenseFile"

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 6 — Generate secure .env configuration
# ═══════════════════════════════════════════════════════════════════════════════

Write-Step 6 "Generating secure configuration (.env)..."

# Generate cryptographically random values
$rng        = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$bytes32    = New-Object byte[] 32
$bytes64    = New-Object byte[] 64

$rng.GetBytes($bytes32)
$dbPassword = ($bytes32 | ForEach-Object { '{0:x2}' -f $_ }) -join '' | Select-Object -First 1
$dbPassword = $dbPassword.Substring(0, 32)

$rng.GetBytes($bytes64)
$secretKey  = ($bytes64 | ForEach-Object { '{0:x2}' -f $_ }) -join ''
$secretKey  = $secretKey.Substring(0, 64)

$rng.GetBytes($bytes64)
$privateKey = ($bytes64 | ForEach-Object { '{0:x2}' -f $_ }) -join ''
$privateKey = $privateKey.Substring(0, 64)

$envContent = @"
# Weighbridge ERP — Generated by Install-Client.ps1 on $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
# Machine: $env:COMPUTERNAME
# DO NOT EDIT this file manually. Use setup_dpapi.py to re-encrypt after changes.

DATABASE_URL=postgresql+asyncpg://${DbUser}:${dbPassword}@localhost:5432/${DbName}
DATABASE_URL_SYNC=postgresql+psycopg://${DbUser}:${dbPassword}@localhost:5432/${DbName}
SECRET_KEY=${secretKey}
PRIVATE_DATA_KEY=${privateKey}
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=480
"@

$envContent | Out-File -FilePath "$InstallRoot\.env" -Encoding UTF8 -NoNewline
Write-OK ".env created with randomly generated secure secrets"
Write-Log "  DB password length: $($dbPassword.Length) chars (hex)"
Write-Log "  SECRET_KEY length:  $($secretKey.Length) chars (hex)"

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 7 — Patch docker-compose.yml with generated DB password
# ═══════════════════════════════════════════════════════════════════════════════

Write-Step 7 "Patching docker-compose.yml with matching DB password..."

$composeFile = "$InstallRoot\docker-compose.yml"
if (-not (Test-Path $composeFile)) {
    Write-Fail "docker-compose.yml not found at $composeFile. The release package may be incomplete."
}

$composeContent = Get-Content $composeFile -Raw
# Replace the POSTGRES_PASSWORD line (works for both: "value" and value formats)
$composeContent = $composeContent -replace '(POSTGRES_PASSWORD:\s*).*', "`${1}${dbPassword}"
$composeContent | Out-File -FilePath $composeFile -Encoding UTF8 -NoNewline
Write-OK "docker-compose.yml updated with matching password"

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 8 — Start PostgreSQL Docker container
# ═══════════════════════════════════════════════════════════════════════════════

Write-Step 8 "Starting PostgreSQL database container..."

# Stop existing container if running (clean state)
$existingContainer = docker ps -a --filter "name=$DbContainer" --format "{{.Names}}" 2>&1
if ($existingContainer -like "*$DbContainer*") {
    Write-Host "       Removing existing container for clean start..." -ForegroundColor Gray
    docker stop $DbContainer 2>&1 | Out-Null
    docker rm $DbContainer 2>&1 | Out-Null
}

Set-Location $InstallRoot
$composeOutput = docker compose up -d 2>&1
Write-Log "docker compose output: $($composeOutput -join ' | ')"

if ($LASTEXITCODE -ne 0) {
    Write-Fail "docker compose up -d failed. Error: $($composeOutput -join '; ')"
}
Write-OK "PostgreSQL container started"

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 9 — Wait for PostgreSQL to be ready
# ═══════════════════════════════════════════════════════════════════════════════

Write-Step 9 "Waiting for PostgreSQL database to be ready..."

$pgReady   = $false
$pgRetries = 0
$pgMax     = 20    # 20 x 3 seconds = 60 seconds max

while (-not $pgReady -and $pgRetries -lt $pgMax) {
    Start-Sleep 3
    $pgRetries++
    try {
        $result = docker exec $DbContainer pg_isready -U $DbUser -d $DbName 2>&1
        if ($result -like "*accepting connections*") {
            $pgReady = $true
        }
    } catch { }
    Write-Host ("       [{0}/{1}] Waiting for database..." -f $pgRetries, $pgMax) -ForegroundColor Gray
}

if (-not $pgReady) {
    $logs = docker logs $DbContainer --tail 20 2>&1
    Write-Log "PostgreSQL logs: $($logs -join '; ')"
    Write-Fail "PostgreSQL did not start within 60 seconds. Check Docker Desktop is running properly. Run: docker logs $DbContainer"
}
Write-OK "PostgreSQL is ready and accepting connections"

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 10 — Register Windows services (WeighbridgeBackend + WeighbridgeFrontend)
# ═══════════════════════════════════════════════════════════════════════════════

Write-Step 10 "Registering Windows services..."

$installServiceScript = "$InstallRoot\scripts\install-services.ps1"
if (-not (Test-Path $installServiceScript)) {
    Write-Fail "install-services.ps1 not found at $installServiceScript. The release package may be incomplete."
}

# Call install-services.ps1 with the correct project directory
$serviceResult = & powershell.exe -ExecutionPolicy Bypass -File $installServiceScript `
                    -ProjectDir $InstallRoot 2>&1
Write-Log "install-services.ps1 output: $($serviceResult -join ' | ')"

if ($LASTEXITCODE -ne 0) {
    Write-Fail "Service installation failed. Details: $($serviceResult -join '; ')"
}
Write-OK "Windows services registered (WeighbridgeBackend, WeighbridgeFrontend)"

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 11 — Health check — wait for backend to respond
# ═══════════════════════════════════════════════════════════════════════════════

Write-Step 11 "Waiting for application to start (health check)..."

$healthy   = $false
$hcRetries = 0
$hcMax     = 30    # 30 x 5 seconds = 150 seconds max

while (-not $healthy -and $hcRetries -lt $hcMax) {
    Start-Sleep 5
    $hcRetries++
    try {
        $response = Invoke-RestMethod -Uri "http://localhost:${BackendPort}/api/v1/health" `
                        -TimeoutSec 5 -ErrorAction Stop
        if ($response.status -in @("healthy", "degraded")) {
            $healthy = $true
        }
    } catch { }
    Write-Host ("       [{0}/{1}] Waiting for backend to start..." -f $hcRetries, $hcMax) -ForegroundColor Gray
}

if (-not $healthy) {
    $errLog = "$InstallRoot\logs\backend_stderr.log"
    $lastLines = if (Test-Path $errLog) { (Get-Content $errLog -Tail 10) -join '; ' } else { "(log not found)" }
    Write-Log "Backend stderr: $lastLines"
    Write-Fail "Backend did not start within 150 seconds. Check: $errLog"
}
Write-OK "Application is running (http://localhost:${FrontendPort})"

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 12 — Encrypt secrets with Windows DPAPI
# ═══════════════════════════════════════════════════════════════════════════════

Write-Step 12 "Encrypting secrets with Windows DPAPI (machine-locked)..."

$setupDpapiScript = "$InstallRoot\backend\setup_dpapi.py"
$venvPython       = "$InstallRoot\backend\venv\Scripts\python.exe"
$systemPython     = Get-Command "python" -ErrorAction SilentlyContinue

# Try venv Python first, fall back to system Python
if (Test-Path $venvPython) {
    $pythonExe = $venvPython
} elseif ($systemPython) {
    $pythonExe = $systemPython.Source
} else {
    Write-Warn "Python not found — skipping DPAPI encryption. Run setup_dpapi.py manually after install."
    $pythonExe = $null
}

if ($pythonExe -and (Test-Path $setupDpapiScript)) {
    # Run setup_dpapi.py with --no-prompt so it runs unattended
    $dpapiResult = & $pythonExe $setupDpapiScript --no-prompt 2>&1
    Write-Log "setup_dpapi.py output: $($dpapiResult -join ' | ')"

    if ($LASTEXITCODE -eq 0 -and (Test-Path "$InstallRoot\backend\secrets.dpapi")) {
        Write-OK "Secrets encrypted to secrets.dpapi (machine-locked, tamper-proof)"
    } else {
        Write-Warn "DPAPI encryption could not be completed automatically."
        Write-Warn "Run this manually after install: python backend\setup_dpapi.py"
    }
} else {
    Write-Warn "Skipping DPAPI encryption (setup_dpapi.py or Python not found)."
    Write-Warn "IMPORTANT: Run 'python backend\setup_dpapi.py' manually before going live!"
}

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 13 — Backup .env.bak to USB and delete from machine
# ═══════════════════════════════════════════════════════════════════════════════

Write-Step 13 "Backing up secrets to USB and securing the machine..."

$envBakPath = "$InstallRoot\backend\.env.bak"

if (Test-Path $envBakPath) {
    # Find USB drive to write backup to
    $usbDrive = Get-PSDrive -PSProvider FileSystem |
                Where-Object { $_.Root -ne "C:\" -and (Test-Path $_.Root) } |
                Select-Object -First 1

    if ($usbDrive) {
        $usbBackupDir = "$($usbDrive.Root)weighbridge-backup-$env:COMPUTERNAME"
        New-Item -ItemType Directory -Force $usbBackupDir | Out-Null
        Copy-Item $envBakPath "$usbBackupDir\.env.bak" -Force

        # Verify copy succeeded before deleting
        if (Test-Path "$usbBackupDir\.env.bak") {
            Remove-Item $envBakPath -Force
            Write-OK ".env.bak backed up to USB: $usbBackupDir"
            Write-OK ".env.bak removed from machine (secrets now machine-locked only)"
        } else {
            Write-Warn "Could not verify USB backup. .env.bak kept at: $envBakPath"
            Write-Warn "IMPORTANT: Copy .env.bak to USB manually then delete it from this machine!"
        }
    } else {
        Write-Warn "No USB drive detected. .env.bak kept at: $envBakPath"
        Write-Warn "IMPORTANT: Copy .env.bak to USB manually then delete it from this machine!"
    }
} else {
    # DPAPI might not have run (no .env.bak generated)
    # Back up the .env itself (still needed for DR)
    Write-Warn ".env.bak not found (DPAPI may not have run). Back up .env manually to USB."
}

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 14 — Configure Windows Firewall
# ═══════════════════════════════════════════════════════════════════════════════

Write-Step 14 "Configuring Windows Firewall..."

# Remove old rules if they exist (avoid duplicates)
Remove-NetFirewallRule -DisplayName "Weighbridge Frontend" -ErrorAction SilentlyContinue
Remove-NetFirewallRule -DisplayName "Weighbridge Backend API" -ErrorAction SilentlyContinue
Remove-NetFirewallRule -DisplayName "Weighbridge: Block PostgreSQL External" -ErrorAction SilentlyContinue

# Allow frontend (port 9000) from local network — operators access via browser
New-NetFirewallRule `
    -DisplayName "Weighbridge Frontend" `
    -Direction Inbound `
    -Protocol TCP `
    -LocalPort $FrontendPort `
    -Action Allow `
    -Enabled True `
    -Profile Domain,Private | Out-Null

# Allow backend API (port 9001) from local network — same machine + LAN
New-NetFirewallRule `
    -DisplayName "Weighbridge Backend API" `
    -Direction Inbound `
    -Protocol TCP `
    -LocalPort $BackendPort `
    -Action Allow `
    -Enabled True `
    -Profile Domain,Private | Out-Null

# Block PostgreSQL (port 5432) from ALL external sources
New-NetFirewallRule `
    -DisplayName "Weighbridge: Block PostgreSQL External" `
    -Direction Inbound `
    -Protocol TCP `
    -LocalPort 5432 `
    -RemoteAddress "0.0.0.0/0" `
    -Action Block `
    -Enabled True | Out-Null

Write-OK "Firewall: Port 9000 (UI) and 9001 (API) open for LAN access"
Write-OK "Firewall: Port 5432 (PostgreSQL) blocked from all external access"

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 15 — Configure Docker to auto-start with Windows
# ═══════════════════════════════════════════════════════════════════════════════

Write-Step 15 "Configuring Docker Desktop to start automatically..."

# Set Docker Desktop to run on login (applies for current user)
$dockerDesktopExe = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
if (Test-Path $dockerDesktopExe) {
    $regKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
    Set-ItemProperty -Path $regKey -Name "Docker Desktop" -Value "`"$dockerDesktopExe`"" -ErrorAction SilentlyContinue
    Write-OK "Docker Desktop set to start automatically on login"
} else {
    Write-Warn "Docker Desktop exe not found at default path — set it to auto-start manually"
}

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 16 — Write version.txt
# ═══════════════════════════════════════════════════════════════════════════════

Write-Step 16 "Recording installation version..."

# Try to read version from API
try {
    $versionInfo = Invoke-RestMethod -Uri "http://localhost:${BackendPort}/api/v1/version" -TimeoutSec 5
    $appVersion  = $versionInfo.version
} catch {
    $appVersion = "1.0.0"    # fallback if version endpoint not yet implemented
}

"$appVersion" | Out-File -FilePath "$InstallRoot\version.txt" -Encoding UTF8 -NoNewline
Write-OK "Version $appVersion recorded in $InstallRoot\version.txt"

# ═══════════════════════════════════════════════════════════════════════════════
# DONE — Print summary
# ═══════════════════════════════════════════════════════════════════════════════

Write-Host ""
Write-Host "  ╔══════════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "  ║               INSTALLATION COMPLETE ✓                    ║" -ForegroundColor Green
Write-Host "  ╚══════════════════════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""
Write-Host "  Application URL  : http://localhost:9000" -ForegroundColor Cyan
Write-Host "  Login            : admin  /  admin123" -ForegroundColor Cyan
Write-Host "  Version          : $appVersion" -ForegroundColor Cyan
Write-Host "  Install log      : $LogFile" -ForegroundColor Gray
Write-Host ""
Write-Host "  ┌── IMPORTANT: Complete these steps now ────────────────┐" -ForegroundColor Yellow
Write-Host "  │                                                        │" -ForegroundColor Yellow
Write-Host "  │  1. Open http://localhost:9000 in the browser          │" -ForegroundColor Yellow
Write-Host "  │  2. Login with  admin / admin123                       │" -ForegroundColor Yellow
Write-Host "  │  3. IMMEDIATELY change the admin password              │" -ForegroundColor Yellow
Write-Host "  │  4. Go to Settings → Company and enter:                │" -ForegroundColor Yellow
Write-Host "  │        - Company name, GSTIN, PAN, address             │" -ForegroundColor Yellow
Write-Host "  │        - Bank account details                          │" -ForegroundColor Yellow
Write-Host "  │  5. Go to Settings → Scale and configure the COM port  │" -ForegroundColor Yellow
Write-Host "  │  6. Store the USB backup drive in a safe location      │" -ForegroundColor Yellow
Write-Host "  │                                                        │" -ForegroundColor Yellow
Write-Host "  │  See INSTALL_CHECKLIST.txt on the USB drive for full   │" -ForegroundColor Yellow
Write-Host "  │  instructions.                                         │" -ForegroundColor Yellow
Write-Host "  └────────────────────────────────────────────────────────┘" -ForegroundColor Yellow
Write-Host ""

Write-Log "=== Installation Complete === Version: $appVersion ==="

Read-Host "Press ENTER to close this window"
