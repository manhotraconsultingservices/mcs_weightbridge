#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Install the Weighbridge Recovery Watchdog as a Windows service on port 9002.
    Run this once after deploying the application.

.DESCRIPTION
    Registers watchdog_server.py as "WeighbridgeWatchdog" using NSSM.
    The watchdog starts automatically with Windows and survives crashes.
    Non-IT staff can open http://localhost:9002 to diagnose and restart components.

.EXAMPLE
    .\install-watchdog.ps1
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Paths ─────────────────────────────────────────────────────────────────────
$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Definition
$WorkspaceDir = Split-Path -Parent $ScriptDir
$BackendDir  = Join-Path $WorkspaceDir "backend"
$VenvPython  = Join-Path $BackendDir "venv\Scripts\python.exe"
$WatchdogPy  = Join-Path $BackendDir "watchdog_server.py"
$LogDir      = Join-Path $WorkspaceDir "logs"
$NssmExe     = "nssm"   # assumes nssm is in PATH; adjust if needed

$ServiceName = "WeighbridgeWatchdog"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Weighbridge Recovery Watchdog Installer" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ── Pre-flight checks ─────────────────────────────────────────────────────────
if (-not (Test-Path $WatchdogPy)) {
    Write-Error "watchdog_server.py not found at: $WatchdogPy"
    exit 1
}

if (-not (Test-Path $VenvPython)) {
    Write-Error "Python venv not found at: $VenvPython — run install.ps1 first"
    exit 1
}

try { Get-Command $NssmExe -ErrorAction Stop | Out-Null }
catch {
    Write-Error "NSSM not found in PATH. Install nssm from https://nssm.cc and add to PATH."
    exit 1
}

# ── Create log directory ──────────────────────────────────────────────────────
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir | Out-Null
    Write-Host "Created log directory: $LogDir"
}

# ── Remove existing service if present ───────────────────────────────────────
$existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Stopping and removing existing $ServiceName service…"
    & $NssmExe stop  $ServiceName confirm 2>$null | Out-Null
    & $NssmExe remove $ServiceName confirm 2>$null | Out-Null
    Start-Sleep 2
}

# ── Install service ───────────────────────────────────────────────────────────
Write-Host "Installing $ServiceName service…"
& $NssmExe install $ServiceName $VenvPython $WatchdogPy

# ── Configure service ─────────────────────────────────────────────────────────
Write-Host "Configuring service parameters…"

& $NssmExe set $ServiceName AppDirectory        $BackendDir
& $NssmExe set $ServiceName DisplayName         "Weighbridge Recovery Watchdog"
& $NssmExe set $ServiceName Description         "Serves the system status dashboard on http://localhost:9002 — non-IT recovery tool"

# Auto-restart on any exit
& $NssmExe set $ServiceName AppExit             Default Restart
& $NssmExe set $ServiceName AppRestartDelay     5000   # wait 5 s before restart

# Log output
$stdoutLog = Join-Path $LogDir "watchdog_stdout.log"
$stderrLog = Join-Path $LogDir "watchdog_stderr.log"
& $NssmExe set $ServiceName AppStdout          $stdoutLog
& $NssmExe set $ServiceName AppStderr          $stderrLog
& $NssmExe set $ServiceName AppRotateFiles     1
& $NssmExe set $ServiceName AppRotateBytes     5242880   # 5 MB rotation
& $NssmExe set $ServiceName AppRotateOnline    1

# Start type
& $NssmExe set $ServiceName Start              SERVICE_AUTO_START

# Depend on network being up
& $NssmExe set $ServiceName DependOnService    Tcpip

Write-Host "Service configured." -ForegroundColor Green

# ── Start service ─────────────────────────────────────────────────────────────
Write-Host "Starting $ServiceName…"
Start-Service $ServiceName
Start-Sleep 3

$svc = Get-Service -Name $ServiceName
if ($svc.Status -eq "Running") {
    Write-Host ""
    Write-Host "✅ WeighbridgeWatchdog is RUNNING" -ForegroundColor Green
    Write-Host ""
    Write-Host "   Recovery Dashboard → http://localhost:9002" -ForegroundColor Yellow
    Write-Host "   Share this URL with on-site staff for self-service troubleshooting."
    Write-Host ""
} else {
    Write-Warning "Service may not have started (status: $($svc.Status)). Check logs at $LogDir"
}

Write-Host "Done. The watchdog will start automatically whenever Windows boots." -ForegroundColor Cyan
Write-Host ""
