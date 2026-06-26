#Requires -RunAsAdministrator
<#
.SYNOPSIS
  Install the Weighbridge Scale Agent as a Windows service via NSSM.

.DESCRIPTION
  Wraps everything that previously had to be done by hand after a
  client-site visit: locates an already-installed NSSM, removes any
  leftover Scheduled Tasks from the older deploy-agents.ps1 flow,
  registers the agent as a Windows service with auto-start +
  auto-restart on crash, captures stdout/stderr to rotating log files,
  and verifies the agent is responding on its status port.

  Assumes nssm.exe is already installed (on PATH or a common location /
  -NssmDir). It does NOT download NSSM.

  Idempotent - safe to re-run. Each invocation tears down and recreates
  the service cleanly.

  NOTE: ASCII-only on purpose. Windows PowerShell 5.1 reads .ps1 files in
  the system ANSI codepage; non-ASCII glyphs in a UTF-8-no-BOM file derail
  the parser ("string is missing the terminator"). Keep this file ASCII.

.PARAMETER InstallDir
  Folder where scale_agent.py + scale_config.json already live.
  Default: C:\weighbridge-agent

.PARAMETER ServiceName
  Windows service name. Default: WeighbridgeScaleAgent

.PARAMETER PythonExe
  Full path to python.exe. Default: auto-detect from PATH or
  C:\Program Files\Python311\python.exe

.PARAMETER NssmDir
  Extra folder to look for nssm.exe (PATH is checked first). Default: C:\nssm

.PARAMETER Uninstall
  Remove the service (and the leftover Scheduled Tasks too). Does NOT
  delete the agent files in $InstallDir - that's a separate cleanup.

.EXAMPLE
  # First-time install (after you've already created scale_config.json)
  .\install-scale-service.ps1

  # Reinstall with a custom location
  .\install-scale-service.ps1 -InstallDir D:\weighbridge-agent

  # Tear it down
  .\install-scale-service.ps1 -Uninstall
#>

param(
    [string]$InstallDir   = "C:\weighbridge-agent",
    [string]$ServiceName  = "WeighbridgeScaleAgent",
    [string]$PythonExe    = "",
    [string]$NssmDir      = "C:\nssm",
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"

function Write-Section($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Write-OK($msg)      { Write-Host "  [OK]  $msg" -ForegroundColor Green }
function Write-Err($msg)     { Write-Host "  [ERR] $msg" -ForegroundColor Red }
function Write-Info($msg)    { Write-Host "  $msg" -ForegroundColor Gray }

# --------------------------------------------------------------------------
# Resolve helpers
# --------------------------------------------------------------------------

function Resolve-PythonExe {
    if ($PythonExe -and (Test-Path $PythonExe)) { return $PythonExe }
    # Prefer PATH if it has a Python 3.11+
    $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Path }
    # Common install locations
    foreach ($p in @(
        "C:\Program Files\Python311\python.exe",
        "C:\Program Files\Python312\python.exe",
        "C:\Program Files\Python313\python.exe"
    )) {
        if (Test-Path $p) { return $p }
    }
    throw "Could not find python.exe - pass -PythonExe explicitly"
}

function Ensure-Nssm {
    # Assumes NSSM is already installed. Looks on PATH first, then common
    # locations. Does NOT download (offline / locked-down client machines).
    $cmd = Get-Command nssm.exe -ErrorAction SilentlyContinue
    if ($cmd) { Write-OK "NSSM on PATH: $($cmd.Source)"; return $cmd.Source }
    foreach ($p in @(
        (Join-Path $NssmDir "nssm.exe"),
        "C:\nssm\nssm.exe",
        "C:\nssm\win64\nssm.exe",
        "C:\tools\nssm\nssm.exe",
        "C:\Program Files\nssm\nssm.exe",
        "C:\ProgramData\chocolatey\bin\nssm.exe",
        (Join-Path $InstallDir "nssm.exe")
    )) {
        if (Test-Path $p) { Write-OK "NSSM at $p"; return $p }
    }
    Write-Err "nssm.exe not found on PATH or in common locations."
    Write-Info "Install NSSM (https://nssm.cc/download) and put nssm.exe on PATH,"
    Write-Info "or pass its folder with -NssmDir C:\path\to\nssm-folder."
    throw "NSSM not found"
}

# --------------------------------------------------------------------------
# Uninstall path
# --------------------------------------------------------------------------

if ($Uninstall) {
    Write-Section "Uninstall"
    $nssm = Join-Path $NssmDir "nssm.exe"
    if (Test-Path $nssm) {
        & $nssm stop   $ServiceName confirm 2>$null | Out-Null
        & $nssm remove $ServiceName confirm 2>$null | Out-Null
        Write-OK "Service '$ServiceName' removed"
    } else {
        Write-Info "NSSM not installed - service likely already gone"
    }
    Get-ScheduledTask -TaskName "Weighbridge*" -ErrorAction SilentlyContinue |
        Unregister-ScheduledTask -Confirm:$false
    Write-OK "Any leftover Scheduled Tasks removed"
    Write-Info "Note: agent files in $InstallDir were NOT deleted. Remove manually if desired."
    return
}

# --------------------------------------------------------------------------
# Pre-flight
# --------------------------------------------------------------------------

Write-Section "Pre-flight checks"

$script = Join-Path $InstallDir "scale_agent.py"
$config = Join-Path $InstallDir "scale_config.json"

if (-not (Test-Path $script)) {
    Write-Err "scale_agent.py not found at $script"
    Write-Info "Copy the agent files into $InstallDir first."
    exit 1
}
Write-OK "scale_agent.py at $script"

if (-not (Test-Path $config)) {
    Write-Err "scale_config.json not found at $config"
    Write-Info "Create it before installing the service (see scale_config.example.json)"
    exit 1
}
Write-OK "scale_config.json at $config"

# Read the status port from the config (default 9002) so the health check below
# targets the right port.
$statusPort = 9002
try {
    $cfg = Get-Content $config -Raw | ConvertFrom-Json
    if ($cfg.status_port) { $statusPort = [int]$cfg.status_port }
} catch {
    Write-Info "Could not parse status_port from config - assuming $statusPort"
}

$PythonExe = Resolve-PythonExe
Write-OK "Python at $PythonExe ($(& $PythonExe --version 2>&1))"

# --------------------------------------------------------------------------
# Kill any foreground instance + remove old Scheduled Task
# --------------------------------------------------------------------------

Write-Section "Cleanup of older flows"

Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*scale_agent.py*' } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        Write-OK "Killed foreground PID $($_.ProcessId)"
    }

Get-ScheduledTask -TaskName "Weighbridge*" -ErrorAction SilentlyContinue |
    Unregister-ScheduledTask -Confirm:$false
Write-OK "Older Scheduled Tasks (if any) removed"

# --------------------------------------------------------------------------
# NSSM
# --------------------------------------------------------------------------

Write-Section "NSSM"
$nssm = Ensure-Nssm

# --------------------------------------------------------------------------
# Register / Re-register the service
# --------------------------------------------------------------------------

Write-Section "Register service '$ServiceName'"

# Idempotent - tear down any prior instance first
& $nssm stop   $ServiceName confirm 2>$null | Out-Null
& $nssm remove $ServiceName confirm 2>$null | Out-Null

$logDir = Join-Path $InstallDir "logs"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

& $nssm install $ServiceName $PythonExe $script
& $nssm set     $ServiceName AppDirectory   $InstallDir
& $nssm set     $ServiceName DisplayName    "Weighbridge Scale Agent"
& $nssm set     $ServiceName Description    "Reads weight from the bridge indicator (RS-232/USB) and pushes to the cloud."
& $nssm set     $ServiceName Start          SERVICE_AUTO_START
& $nssm set     $ServiceName ObjectName     "LocalSystem"

# Auto-restart on crash. AppExit Default Restart = restart on ANY non-zero exit.
& $nssm set     $ServiceName AppExit         Default Restart
& $nssm set     $ServiceName AppRestartDelay 2000

# Capture stdout/stderr - invaluable when the service won't start. Rotate at 10 MB.
& $nssm set     $ServiceName AppStdout         (Join-Path $logDir "service_stdout.log")
& $nssm set     $ServiceName AppStderr         (Join-Path $logDir "service_stderr.log")
& $nssm set     $ServiceName AppRotateFiles    1
& $nssm set     $ServiceName AppRotateOnline   1
& $nssm set     $ServiceName AppRotateBytes    10485760
Write-OK "Service registered"

# --------------------------------------------------------------------------
# Start + verify
# --------------------------------------------------------------------------

Write-Section "Start + verify"

& $nssm start $ServiceName | Out-Null
Start-Sleep -Seconds 3

$svc = Get-Service $ServiceName -ErrorAction SilentlyContinue
if ($svc -and $svc.Status -eq "Running") {
    Write-OK "Service is Running (StartType: $($svc.StartType))"
} else {
    Write-Err "Service is not Running. Check $logDir\service_stderr.log"
    exit 1
}

$conn = Get-NetTCPConnection -LocalPort $statusPort -ErrorAction SilentlyContinue
if ($conn) {
    Write-OK "Status port $statusPort listening (PID $($conn.OwningProcess))"
} else {
    Write-Err "Status port $statusPort NOT listening. Most likely scale_agent.py crashed during init."
    Write-Info "Tail of service_stderr.log:"
    Get-Content (Join-Path $logDir "service_stderr.log") -Tail 30 -ErrorAction SilentlyContinue |
        ForEach-Object { Write-Host "      $_" -ForegroundColor DarkYellow }
    exit 1
}

Write-Section "Status snapshot"
try {
    $status = Invoke-RestMethod "http://localhost:$statusPort/status" -TimeoutSec 5
    $status | ConvertTo-Json -Depth 5 | Write-Host
    if ($status.cloud_push_success) {
        Write-OK "Cloud push working"
    } else {
        Write-Host "  [WARN] cloud_push_success is false - check tenant_slug + agent_key in $config" -ForegroundColor Yellow
    }
} catch {
    Write-Host "  [WARN] /status endpoint failed: $_" -ForegroundColor Yellow
}

Write-Host "`nInstalled. Day-to-day commands:" -ForegroundColor Green
Write-Host "  Get-Service $ServiceName"
Write-Host "  Restart-Service $ServiceName"
Write-Host "  Get-Content $logDir\scale_agent.log -Tail 30 -Wait"
Write-Host "  Invoke-RestMethod http://localhost:$statusPort/status | ConvertTo-Json -Depth 5"
Write-Host ""
Write-Host "Uninstall:" -ForegroundColor Gray
Write-Host "  .\install-scale-service.ps1 -Uninstall"
