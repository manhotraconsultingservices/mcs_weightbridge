#Requires -RunAsAdministrator
<#
.SYNOPSIS
  Weighbridge Invoice Software - Windows Service Installer
  Registers backend (FastAPI) and frontend (static serve) as Windows services using NSSM.

.DESCRIPTION
  Run as Administrator:
    powershell -ExecutionPolicy Bypass -File scripts\install-services.ps1

.PARAMETER ProjectDir
  Root of the project. Defaults to the folder containing this script's parent.

.PARAMETER Unregister
  Stop and remove both services without reinstalling.

.PARAMETER BackendOnly
  Register only the backend service (skip frontend).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\install-services.ps1
  powershell -ExecutionPolicy Bypass -File scripts\install-services.ps1 -Unregister
  powershell -ExecutionPolicy Bypass -File scripts\install-services.ps1 -BackendOnly
#>

param(
    [string]$ProjectDir  = "",
    [switch]$Unregister,
    [switch]$BackendOnly
)

$ErrorActionPreference = "Stop"
$ProgressPreference    = "SilentlyContinue"

# ── Resolve project directory ──────────────────────────────────────────────────
if (-not $ProjectDir) {
    $ProjectDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}
$ProjectDir   = (Resolve-Path $ProjectDir).Path
$BackendDir   = Join-Path $ProjectDir "backend"
$FrontendDir  = Join-Path $ProjectDir "frontend"
$FrontendDist = Join-Path $FrontendDir "dist"
$LogDir       = Join-Path $ProjectDir "logs"
$EnvFile      = Join-Path $BackendDir ".env"
$ToolsDir     = Join-Path $ProjectDir "tools"

$SvcBackend  = "WeighbridgeBackend"
$SvcFrontend = "WeighbridgeFrontend"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "   Weighbridge Invoice Software - Windows Service Installer " -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Project : $ProjectDir"
Write-Host "  Backend : $BackendDir"
Write-Host "  Frontend: $FrontendDir"
Write-Host ""

# ── Locate NSSM ───────────────────────────────────────────────────────────────
function Get-Nssm {
    $candidates = @(
        "nssm",
        "C:\nssm\nssm.exe",
        "C:\tools\nssm\nssm.exe",
        "C:\Program Files\nssm\nssm.exe",
        (Join-Path $ToolsDir "nssm.exe"),
        (Join-Path (Split-Path $MyInvocation.ScriptName -Parent) "nssm.exe")
    )
    foreach ($c in $candidates) {
        $cmd = Get-Command $c -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    return $null
}

$nssm = Get-Nssm

if (-not $nssm) {
    Write-Host "NSSM not found - downloading now..." -ForegroundColor Yellow
    if (-not (Test-Path $ToolsDir)) { New-Item -ItemType Directory -Path $ToolsDir | Out-Null }
    $nssmZip = Join-Path $env:TEMP "nssm.zip"
    $nssmUrl = "https://nssm.cc/release/nssm-2.24.zip"
    try {
        Invoke-WebRequest -Uri $nssmUrl -OutFile $nssmZip -UseBasicParsing -TimeoutSec 60
        Expand-Archive -Path $nssmZip -DestinationPath "$env:TEMP\nssm_extract" -Force
        $nssmExe = Get-ChildItem "$env:TEMP\nssm_extract" -Filter "nssm.exe" -Recurse |
                   Where-Object { $_.FullName -like "*win64*" } |
                   Select-Object -First 1
        if (-not $nssmExe) {
            $nssmExe = Get-ChildItem "$env:TEMP\nssm_extract" -Filter "nssm.exe" -Recurse |
                       Select-Object -First 1
        }
        Copy-Item $nssmExe.FullName (Join-Path $ToolsDir "nssm.exe") -Force
        $nssm = Join-Path $ToolsDir "nssm.exe"
        Write-Host "  NSSM downloaded to: $nssm" -ForegroundColor Green
    } catch {
        Write-Host ""
        Write-Host "  ERROR: Could not download NSSM automatically." -ForegroundColor Red
        Write-Host "  Please download NSSM manually:"
        Write-Host "    1. Go to https://nssm.cc/download"
        Write-Host "    2. Download nssm-2.24.zip"
        Write-Host "    3. Extract nssm.exe (win64 folder) to: $ToolsDir\nssm.exe"
        Write-Host "    4. Re-run this script"
        exit 1
    }
}
Write-Host "  Using NSSM: $nssm" -ForegroundColor Green
Write-Host ""

# ── Find Python executable ────────────────────────────────────────────────────
function Get-PythonExe {
    # Check for venv first
    $venvPy = Join-Path $BackendDir "venv\Scripts\python.exe"
    if (Test-Path $venvPy) { return $venvPy }

    # Fall back to system Python
    foreach ($c in @("python", "python3", "py")) {
        $cmd = Get-Command $c -ErrorAction SilentlyContinue
        if ($cmd) {
            $test = & $cmd.Source -c "import uvicorn" 2>&1
            if ($LASTEXITCODE -eq 0) { return $cmd.Source }
        }
    }
    throw "Python with uvicorn not found. Run: pip install uvicorn"
}

$pythonExe = Get-PythonExe
Write-Host "  Python: $pythonExe" -ForegroundColor Green

# ── Find Node / npm ───────────────────────────────────────────────────────────
$nodeCmd = Get-Command "node" -ErrorAction SilentlyContinue
if (-not $nodeCmd) { throw "Node.js not found. Install from https://nodejs.org" }
$nodeExe = $nodeCmd.Source

$npmCmd = Get-Command "npm" -ErrorAction SilentlyContinue
if (-not $npmCmd) { throw "npm not found. Reinstall Node.js from https://nodejs.org" }
$npmExe = $npmCmd.Source

Write-Host "  Node:   $nodeExe" -ForegroundColor Green
Write-Host "  npm:    $npmExe" -ForegroundColor Green
Write-Host ""

# ── Unregister mode ───────────────────────────────────────────────────────────
if ($Unregister) {
    Write-Host "Removing Windows services..." -ForegroundColor Yellow
    foreach ($svc in @($SvcFrontend, $SvcBackend)) {
        $existing = Get-Service -Name $svc -ErrorAction SilentlyContinue
        if ($existing) {
            Write-Host "  Stopping $svc..."
            & $nssm stop $svc 2>$null
            Start-Sleep 2
            & $nssm remove $svc confirm
            Write-Host "  Removed: $svc" -ForegroundColor Green
        } else {
            Write-Host "  Not found: $svc (skipped)"
        }
    }
    Write-Host ""
    Write-Host "Services removed." -ForegroundColor Green
    exit 0
}

# ── Create log directory ───────────────────────────────────────────────────────
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir | Out-Null
    Write-Host "  Created log directory: $LogDir"
}

# ── Read .env and extract variables ───────────────────────────────────────────
Write-Host "Step 1 - Reading environment variables from .env" -ForegroundColor Cyan

if (-not (Test-Path $EnvFile)) {
    throw ".env not found at $EnvFile. Cannot configure services without it."
}

$envVars = @{}
Get-Content $EnvFile | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith("#")) {
        $idx = $line.IndexOf("=")
        if ($idx -gt 0) {
            $key = $line.Substring(0, $idx).Trim()
            $val = $line.Substring($idx + 1).Trim()
            $envVars[$key] = $val
        }
    }
}

# Build NSSM environment string (newline-separated KEY=VALUE pairs)
$envLines = @()
foreach ($kv in $envVars.GetEnumerator()) {
    $envLines += "$($kv.Key)=$($kv.Value)"
}
$envExtra = $envLines -join "`n"

Write-Host "  Loaded $($envVars.Count) variables" -ForegroundColor Green
if ($envVars.ContainsKey("PRIVATE_DATA_KEY")) {
    Write-Host "  PRIVATE_DATA_KEY: present (encryption enabled)" -ForegroundColor Green
} else {
    Write-Host "  WARNING: PRIVATE_DATA_KEY missing - secret invoices will not work" -ForegroundColor Yellow
}

# ── Build frontend ─────────────────────────────────────────────────────────────
if (-not $BackendOnly) {
    Write-Host ""
    Write-Host "Step 2 - Building frontend for production" -ForegroundColor Cyan

    if (-not (Test-Path (Join-Path $FrontendDir "node_modules"))) {
        Write-Host "  Installing npm dependencies..."
        Push-Location $FrontendDir
        & $npmExe install --silent
        Pop-Location
    }

    Write-Host "  Running npm run build..."
    Push-Location $FrontendDir
    & $npmExe run build
    Pop-Location

    if (-not (Test-Path $FrontendDist)) {
        throw "Frontend build failed - dist folder not found at $FrontendDist"
    }
    Write-Host "  Frontend built: $FrontendDist" -ForegroundColor Green

    # Install 'serve' globally
    Write-Host "  Installing 'serve' package globally..."
    & $npmExe install -g serve 2>&1 | Out-Null

    # Locate serve.cmd
    $serveCmd = Get-Command "serve" -ErrorAction SilentlyContinue
    if ($serveCmd) {
        $servePath = $serveCmd.Source
    } else {
        $servePath = Join-Path $env:APPDATA "npm\serve.cmd"
    }
    Write-Host "  serve: $servePath" -ForegroundColor Green
}

# ── Helper: remove existing service ───────────────────────────────────────────
function Remove-ServiceIfExists([string]$Name) {
    $existing = Get-Service -Name $Name -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host "  Removing existing '$Name'..."
        & $nssm stop $Name 2>$null
        Start-Sleep -Milliseconds 2000
        & $nssm remove $Name confirm | Out-Null
    }
}

# ── Register Backend Service ───────────────────────────────────────────────────
Write-Host ""
Write-Host "Step 3 - Registering backend service ($SvcBackend)" -ForegroundColor Cyan

Remove-ServiceIfExists $SvcBackend

& $nssm install $SvcBackend $pythonExe
& $nssm set $SvcBackend AppParameters    "-m uvicorn app.main:app --host 0.0.0.0 --port 9001 --workers 2"
& $nssm set $SvcBackend AppDirectory     $BackendDir
& $nssm set $SvcBackend DisplayName      "Weighbridge - Backend (FastAPI)"
& $nssm set $SvcBackend Description      "Weighbridge Invoice Software backend. FastAPI + PostgreSQL."
& $nssm set $SvcBackend Start            SERVICE_AUTO_START
& $nssm set $SvcBackend AppStdout        (Join-Path $LogDir "backend_stdout.log")
& $nssm set $SvcBackend AppStderr        (Join-Path $LogDir "backend_stderr.log")
& $nssm set $SvcBackend AppRotateFiles   1
& $nssm set $SvcBackend AppRotateBytes   10485760
& $nssm set $SvcBackend AppRotateOnline  1
& $nssm set $SvcBackend AppThrottle      5000
& $nssm set $SvcBackend AppExit Default  Restart
& $nssm set $SvcBackend AppEnvironmentExtra $envExtra

Write-Host "  Backend service registered." -ForegroundColor Green

# ── Register Frontend Service ──────────────────────────────────────────────────
if (-not $BackendOnly) {
    Write-Host ""
    Write-Host "Step 4 - Registering frontend service ($SvcFrontend)" -ForegroundColor Cyan

    Remove-ServiceIfExists $SvcFrontend

    # serve.cmd must be launched via cmd.exe since NSSM needs a real .exe
    # cmd.exe /c serve -s "dist" -l 9000 --no-clipboard
    $serveCmd2 = Get-Command "serve" -ErrorAction SilentlyContinue
    if ($serveCmd2) {
        $serveAppPath = $serveCmd2.Source
    } else {
        $serveAppPath = Join-Path $env:APPDATA "npm\serve.cmd"
    }

    & $nssm install $SvcFrontend "cmd.exe"
    & $nssm set $SvcFrontend AppParameters    "/c `"$serveAppPath`" -s `"$FrontendDist`" -l 3000 --no-clipboard"
    & $nssm set $SvcFrontend AppDirectory     $FrontendDir
    & $nssm set $SvcFrontend DisplayName      "Weighbridge - Frontend (Static)"
    & $nssm set $SvcFrontend Description      "Weighbridge Invoice Software frontend. Serves built React app on port 3000."
    & $nssm set $SvcFrontend Start            SERVICE_AUTO_START
    & $nssm set $SvcFrontend AppStdout        (Join-Path $LogDir "frontend_stdout.log")
    & $nssm set $SvcFrontend AppStderr        (Join-Path $LogDir "frontend_stderr.log")
    & $nssm set $SvcFrontend AppRotateFiles   1
    & $nssm set $SvcFrontend AppRotateBytes   5242880
    & $nssm set $SvcFrontend AppThrottle      5000
    & $nssm set $SvcFrontend AppExit Default  Restart
    & $nssm set $SvcFrontend DependOnService  $SvcBackend

    Write-Host "  Frontend service registered." -ForegroundColor Green
}

# ── Start services ─────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "Step 5 - Starting services" -ForegroundColor Cyan

Write-Host "  Starting $SvcBackend..."
& $nssm start $SvcBackend
Start-Sleep -Seconds 6

$backendSvc = Get-Service -Name $SvcBackend -ErrorAction SilentlyContinue
if ($backendSvc -and $backendSvc.Status -eq "Running") {
    Write-Host "  $SvcBackend : Running" -ForegroundColor Green
} else {
    $status = if ($backendSvc) { $backendSvc.Status } else { "Not Found" }
    Write-Host "  $SvcBackend : $status" -ForegroundColor Red
    Write-Host "  Check logs: $LogDir\backend_stderr.log"
}

if (-not $BackendOnly) {
    Write-Host "  Starting $SvcFrontend..."
    & $nssm start $SvcFrontend
    Start-Sleep -Seconds 4

    $frontendSvc = Get-Service -Name $SvcFrontend -ErrorAction SilentlyContinue
    if ($frontendSvc -and $frontendSvc.Status -eq "Running") {
        Write-Host "  $SvcFrontend : Running" -ForegroundColor Green
    } else {
        $status = if ($frontendSvc) { $frontendSvc.Status } else { "Not Found" }
        Write-Host "  $SvcFrontend : $status" -ForegroundColor Red
        Write-Host "  Check logs: $LogDir\frontend_stderr.log"
    }
}

# ── Summary ───────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "                  Services Registered!                      " -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Backend  URL : http://localhost:9001"
Write-Host "  Frontend URL : http://localhost:3000"
Write-Host "  API Docs     : http://localhost:9001/docs"
Write-Host "  Log files    : $LogDir"
Write-Host ""
Write-Host "  Manage services (run as Admin):" -ForegroundColor Cyan
Write-Host "    Status  : powershell -File scripts\manage-services.ps1 status"
Write-Host "    Restart : powershell -File scripts\manage-services.ps1 restart"
Write-Host "    Logs    : powershell -File scripts\manage-services.ps1 logs backend"
Write-Host "    Remove  : powershell -File scripts\install-services.ps1 -Unregister"
Write-Host ""
Write-Host "  Both services auto-start when Windows boots." -ForegroundColor Green
Write-Host ""
