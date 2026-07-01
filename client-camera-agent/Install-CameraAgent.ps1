<#
.SYNOPSIS
    Fresh install or re-install of the Weighbridge Camera Agent on a client PC.

.DESCRIPTION
    Installs the Weighbridge Camera Agent as a Windows service (WeighbridgeCameraAgent).
    The agent runs continuously in the background and:
      1. Captures JPEG snapshots from weighbridge cameras when a weight is recorded.
      2. Pushes live frames from gate cameras every 3 s for the Gate Camera Live Feed page.
      3. Captures entry/exit photos when a Gate Pass is created or closed.

    Prerequisites (checked automatically):
      - Python 3.11+ installed and on PATH
      - NSSM installed (downloads automatically if missing)
      - Network access to the cloud and to the camera IPs

.PARAMETER InstallDir
    Directory where agent files will be copied.
    Default: C:\weighbridge-agent  (override with -InstallDir C:\mydir)

.PARAMETER CloudUrl
    Cloud URL for this client, e.g. https://acme.weighbridgesetu.com
    If omitted the wizard prompts for it.

.PARAMETER TenantSlug
    Tenant identifier, e.g. acme-minerals
    If omitted the wizard prompts for it.

.PARAMETER AgentKey
    Agent API key from Platform Admin.
    If omitted the wizard prompts for it.

.PARAMETER FrontCameraUrl
    Weighbridge FRONT camera snapshot URL.  Prompted if omitted.

.PARAMETER TopCameraUrl
    Weighbridge TOP camera snapshot URL.  Leave blank if only one camera.

.PARAMETER EntryCameraUrl
    Gate ENTRY camera URL for the Gate Camera Live Feed page.
    Leave blank to reuse the front camera.

.PARAMETER ExitCameraUrl
    Gate EXIT camera URL. Leave blank to reuse the front camera.

.PARAMETER CameraUser
    Camera username (same for all cameras).  Prompted if omitted.

.PARAMETER CameraPass
    Camera password.  Prompted if omitted.

.EXAMPLE
    # Fully interactive
    .\Install-CameraAgent.ps1

.EXAMPLE
    # Silent / automated (all params supplied)
    .\Install-CameraAgent.ps1 `
        -InstallDir    "C:\weighbridge-agent" `
        -CloudUrl      "https://acme.weighbridgesetu.com" `
        -TenantSlug    "acme-minerals" `
        -AgentKey      "your-agent-api-key" `
        -FrontCameraUrl "http://192.168.0.101/cgi-bin/snapshot.cgi" `
        -TopCameraUrl   "http://192.168.0.103/cgi-bin/snapshot.cgi" `
        -EntryCameraUrl "http://192.168.0.200/cgi-bin/snapshot.cgi" `
        -ExitCameraUrl  "http://192.168.0.201/cgi-bin/snapshot.cgi" `
        -CameraUser     "admin" `
        -CameraPass     "camera123"
#>

param(
    [string]$InstallDir     = "C:\weighbridge-agent",
    [string]$CloudUrl       = "",
    [string]$TenantSlug     = "",
    [string]$AgentKey       = "",
    [string]$FrontCameraUrl = "",
    [string]$TopCameraUrl   = "",
    [string]$EntryCameraUrl = "",
    [string]$ExitCameraUrl  = "",
    [string]$CameraUser     = "",
    [string]$CameraPass     = ""
)

$ErrorActionPreference = "Stop"
$SVC_NAME = "WeighbridgeCameraAgent"

# ── Helpers ───────────────────────────────────────────────────────────────────
function Write-Banner($msg) {
    Write-Host ""
    Write-Host "  +====================================================+" -ForegroundColor Cyan
    Write-Host "  |  $($msg.PadRight(50))|" -ForegroundColor Cyan
    Write-Host "  +====================================================+" -ForegroundColor Cyan
    Write-Host ""
}
function Write-Step($n, $msg) {
    Write-Host ""
    Write-Host "  [$n] $msg" -ForegroundColor Cyan
    Write-Host "  $('-' * 52)" -ForegroundColor DarkGray
}
function Write-OK($msg)   { Write-Host "  [OK]   $msg" -ForegroundColor Green  }
function Write-Warn($msg) { Write-Host "  [WARN] $msg" -ForegroundColor Yellow }
function Write-Info($msg) { Write-Host "         $msg" -ForegroundColor Gray   }
function Write-Err($msg)  { Write-Host "  [ERR]  $msg" -ForegroundColor Red    }
function Ask($prompt, $default) {
    $v = Read-Host "    $prompt$(if ($default) { " [$default]" })"
    if ([string]::IsNullOrWhiteSpace($v)) { return $default }
    return $v.Trim()
}

Write-Banner "Weighbridge Camera Agent -- Installer"

# ── Step 1: Check existing service ───────────────────────────────────────────

Write-Step 1 "Checking for existing installation"

$existingSvc = Get-Service -Name $SVC_NAME -ErrorAction SilentlyContinue

if ($existingSvc) {
    # Find the real install dir from the NSSM binary path
    $qc = sc.exe qc $SVC_NAME 2>$null
    $nssmPath = ($qc | Select-String "BINARY_PATH_NAME").ToString() -replace ".*BINARY_PATH_NAME\s*:\s*",""
    $nssmPath = $nssmPath.Trim()
    $detectedDir = Split-Path -Parent $nssmPath

    Write-Warn "Service '$SVC_NAME' already installed."
    Write-Info "Detected install dir: $detectedDir"
    Write-Host ""
    Write-Host "    Options:" -ForegroundColor Yellow
    Write-Host "      1 = Update existing install (keep dir: $detectedDir)" -ForegroundColor Gray
    Write-Host "      2 = Reinstall to new directory ($InstallDir)" -ForegroundColor Gray
    Write-Host "      3 = Exit" -ForegroundColor Gray
    Write-Host ""
    $choice = Read-Host "    Choose [1]"
    if ($choice -eq "3") { exit 0 }
    if ($choice -ne "2") { $InstallDir = $detectedDir }

    Write-Info "Stopping existing service..."
    Stop-Service $SVC_NAME -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    Write-OK "Existing service stopped"
} else {
    Write-OK "No existing service found -- fresh install"
}

# ── Step 2: Locate NSSM ──────────────────────────────────────────────────────

Write-Step 2 "Locating NSSM (service manager)"

# Common NSSM locations to check
$nssmPaths = @(
    "nssm",
    "C:\nssm\nssm.exe",
    "C:\scripts\nssm.exe",
    "C:\tools\nssm.exe",
    "$InstallDir\nssm.exe"
)
$nssmExe = $null
foreach ($p in $nssmPaths) {
    $found = Get-Command $p -ErrorAction SilentlyContinue
    if ($found) { $nssmExe = $found.Source; break }
}

if (-not $nssmExe) {
    Write-Warn "NSSM not found -- downloading..."
    $nssmDir = "$InstallDir"
    New-Item -ItemType Directory -Force -Path $nssmDir | Out-Null
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    try {
        Invoke-WebRequest -Uri "https://nssm.cc/release/nssm-2.24.zip" -OutFile "$env:TEMP\nssm.zip" -UseBasicParsing
        Expand-Archive "$env:TEMP\nssm.zip" -DestinationPath "$env:TEMP\nssm_extract" -Force
        $nssm64 = Get-ChildItem "$env:TEMP\nssm_extract" -Recurse -Filter "nssm.exe" |
                  Where-Object { $_.FullName -like "*win64*" } |
                  Select-Object -First 1
        if (-not $nssm64) {
            $nssm64 = Get-ChildItem "$env:TEMP\nssm_extract" -Recurse -Filter "nssm.exe" | Select-Object -First 1
        }
        Copy-Item $nssm64.FullName "$nssmDir\nssm.exe" -Force
        $nssmExe = "$nssmDir\nssm.exe"
        Write-OK "NSSM downloaded to $nssmExe"
    } catch {
        Write-Err "Could not download NSSM: $_"
        Write-Info "Download manually from https://nssm.cc and place nssm.exe in $nssmDir"
        exit 1
    }
} else {
    Write-OK "NSSM found: $nssmExe"
}

# ── Step 3: Check Python ──────────────────────────────────────────────────────

Write-Step 3 "Checking Python"

$pythonExe = $null
foreach ($py in @("python", "python3", "py")) {
    $found = Get-Command $py -ErrorAction SilentlyContinue
    if ($found) {
        $ver = & $found.Source --version 2>&1
        if ($ver -match "3\.(1[1-9]|[2-9][0-9])") {
            $pythonExe = $found.Source
            Write-OK "Python: $ver at $pythonExe"
            break
        }
    }
}

if (-not $pythonExe) {
    Write-Err "Python 3.11+ not found on PATH."
    Write-Info "Download from https://python.org and re-run this script."
    exit 1
}

# ── Step 4: Create install directory and copy agent files ─────────────────────

Write-Step 4 "Setting up install directory"

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
New-Item -ItemType Directory -Force -Path "$InstallDir\logs" | Out-Null
Write-OK "Directory: $InstallDir"

# Copy agent files from next to this script
$srcDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$srcAgent = Join-Path $srcDir "camera_agent.py"

if (-not (Test-Path $srcAgent)) {
    # Not next to this script -- try GitHub download
    Write-Warn "camera_agent.py not found next to this script. Downloading from GitHub..."
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    try {
        Invoke-WebRequest `
            -Uri "https://raw.githubusercontent.com/manhotraconsultingservices/mcs_weightbridge/main/backend/agents/camera_agent.py" `
            -OutFile "$InstallDir\camera_agent.py" `
            -UseBasicParsing
        Write-OK "camera_agent.py downloaded from GitHub"
    } catch {
        Write-Err "Could not find or download camera_agent.py: $_"
        exit 1
    }
} else {
    $agentDst = "$InstallDir\camera_agent.py"
    $srcResolved = (Resolve-Path $srcAgent).Path
    $dstResolved = if (Test-Path $agentDst) { (Resolve-Path $agentDst).Path } else { $agentDst }
    if ($srcResolved -ne $dstResolved) {
        Copy-Item $srcAgent $agentDst -Force
        Write-OK "camera_agent.py installed"
    } else {
        Write-OK "camera_agent.py already in place"
    }
}

# Copy nssm.exe into install dir if it's not already there
$nssmDst = "$InstallDir\nssm.exe"
if ($nssmExe -ne $nssmDst -and (Test-Path $nssmExe)) {
    Copy-Item $nssmExe $nssmDst -Force -ErrorAction SilentlyContinue
}

# ── Step 5: Install Python packages ──────────────────────────────────────────

Write-Step 5 "Installing Python packages"

$packages = @("requests", "urllib3", "Pillow")
foreach ($pkg in $packages) {
    Write-Info "Installing $pkg..."
    & $pythonExe -m pip install $pkg --quiet 2>&1 | Out-Null
}
Write-OK "Core packages installed"

# Optional (websockets for live stream)
Write-Info "Installing websockets (optional)..."
& $pythonExe -m pip install "websockets>=13" --quiet 2>&1 | Out-Null
Write-OK "websockets installed"

# ── Step 6: Collect configuration ─────────────────────────────────────────────

Write-Step 6 "Configuration"

Write-Info "Common camera snapshot URL formats:"
Write-Info "  CP Plus / Dahua:  http://IP/cgi-bin/snapshot.cgi"
Write-Info "  Hikvision:        http://IP/Streaming/channels/1/picture"
Write-Info "  Generic:          http://IP/snap.jpg"
Write-Host ""

if ([string]::IsNullOrWhiteSpace($CloudUrl)) {
    $CloudUrl = Ask "Cloud URL" "https://weighbridgesetu.com"
}
if ([string]::IsNullOrWhiteSpace($TenantSlug)) {
    $TenantSlug = Ask "Tenant slug (e.g. acme-minerals)" ""
}
if ([string]::IsNullOrWhiteSpace($AgentKey)) {
    $AgentKey = Ask "Agent API key (from Platform Admin)" ""
}

Write-Host ""
Write-Info "-- Weighbridge cameras (for snapshot on each weight) --"
if ([string]::IsNullOrWhiteSpace($FrontCameraUrl)) {
    $FrontCameraUrl = Ask "Front camera URL" "http://192.168.0.101/cgi-bin/snapshot.cgi"
}
if ([string]::IsNullOrWhiteSpace($TopCameraUrl)) {
    $TopCameraUrl = Ask "Top camera URL (blank to skip)" ""
}
if ([string]::IsNullOrWhiteSpace($CameraUser)) {
    $CameraUser = Ask "Camera username" "admin"
}
if ([string]::IsNullOrWhiteSpace($CameraPass)) {
    $CameraPass = Ask "Camera password" ""
}

Write-Host ""
Write-Info "-- Gate cameras (for live feed + gate pass photos) --"
Write-Info "   Leave blank to reuse the front camera above."
if ([string]::IsNullOrWhiteSpace($EntryCameraUrl)) {
    $EntryCameraUrl = Ask "Gate ENTRY camera URL (blank = use front camera)" ""
}
if ([string]::IsNullOrWhiteSpace($ExitCameraUrl)) {
    $ExitCameraUrl = Ask "Gate EXIT camera URL (blank = use front camera)" ""
}

# ── Step 7: Write camera_config.json ─────────────────────────────────────────

Write-Step 7 "Writing camera_config.json"

$configPath = "$InstallDir\camera_config.json"
$config = @{
    cloud_url        = $CloudUrl
    tenant_slug      = $TenantSlug
    agent_key        = $AgentKey
    poll_interval_sec = 5
    status_port      = 9003
    ws_port          = 9004
    snapshot_serve_url = ""
    local_save_dir   = "D:\weighbridge\snapshots"
    file_serve_port  = 9005
    cameras = @{
        front = @{ label = "Front View"; url = $FrontCameraUrl; username = $CameraUser; password = $CameraPass }
        top   = @{ label = "Top View";   url = $TopCameraUrl;   username = $CameraUser; password = $CameraPass }
    }
    gate_cameras = @{
        entry = @{ label = "Gate Entry"; url = $EntryCameraUrl; username = $CameraUser; password = $CameraPass }
        exit  = @{ label = "Gate Exit";  url = $ExitCameraUrl;  username = $CameraUser; password = $CameraPass }
    }
}

[System.IO.File]::WriteAllText(
    $configPath,
    ($config | ConvertTo-Json -Depth 6),
    [System.Text.UTF8Encoding]::new($false)
)
Write-OK "Config saved: $configPath"

# ── Step 8: Test cameras ──────────────────────────────────────────────────────

Write-Step 8 "Testing camera connections"

Write-Info "Testing front camera..."
$testResult = & $pythonExe "$InstallDir\camera_agent.py" --test 2>&1
$testResult | ForEach-Object { Write-Info $_ }

if ($testResult -match "ERROR|FAILED") {
    Write-Warn "Some cameras could not be reached."
    Write-Info "Check the camera IPs and credentials in $configPath"
    Write-Info "You can proceed -- the service will retry automatically."
} else {
    Write-OK "Cameras tested successfully"
}

# ── Step 9: Install Windows service ──────────────────────────────────────────

Write-Step 9 "Installing Windows service"

$logDir     = "$InstallDir\logs"
$agentFile  = "$InstallDir\camera_agent.py"

# Remove stale service if present
$stale = & $nssmExe status $SVC_NAME 2>&1
if ($stale -notmatch "does not exist") {
    & $nssmExe stop $SVC_NAME 2>&1 | Out-Null
    & $nssmExe remove $SVC_NAME confirm 2>&1 | Out-Null
    Start-Sleep -Seconds 2
}

& $nssmExe install    $SVC_NAME $pythonExe "$agentFile"
& $nssmExe set        $SVC_NAME AppDirectory   $InstallDir
& $nssmExe set        $SVC_NAME AppStdout      "$logDir\camera_service_stdout.log"
& $nssmExe set        $SVC_NAME AppStderr      "$logDir\camera_service_stderr.log"
& $nssmExe set        $SVC_NAME AppRotateFiles 1
& $nssmExe set        $SVC_NAME AppRotateBytes 10485760
& $nssmExe set        $SVC_NAME Description    "Weighbridge Camera Agent"
& $nssmExe set        $SVC_NAME Start          SERVICE_AUTO_START
& $nssmExe set        $SVC_NAME ObjectName     LocalSystem

Write-OK "Service registered: $SVC_NAME"

# ── Step 10: Start service and verify ────────────────────────────────────────

Write-Step 10 "Starting service"

& $nssmExe start $SVC_NAME 2>&1 | Out-Null
Start-Sleep -Seconds 6

$svc = Get-Service -Name $SVC_NAME -ErrorAction SilentlyContinue
if ($svc -and $svc.Status -eq "Running") {
    Write-OK "Service is RUNNING"
} else {
    Write-Warn "Service may not have started -- check logs below:"
}

$logFile = "$logDir\camera_agent.log"
if (Test-Path $logFile) {
    Write-Host ""
    Get-Content $logFile -Tail 12 | ForEach-Object { Write-Info $_ }
}

# ── Summary ───────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "  +====================================================+" -ForegroundColor Green
Write-Host "  |  Installation Complete!                            |" -ForegroundColor Green
Write-Host "  +====================================================+" -ForegroundColor Green
Write-Host ""
Write-Host "  Install dir : $InstallDir"           -ForegroundColor White
Write-Host "  Config      : $configPath"           -ForegroundColor White
Write-Host "  Logs        : $logDir"               -ForegroundColor White
Write-Host "  Service     : $SVC_NAME"             -ForegroundColor White
Write-Host ""
Write-Host "  Useful commands:" -ForegroundColor Yellow
Write-Host "    View logs     : Get-Content '$logFile' -Tail 30" -ForegroundColor Gray
Write-Host "    Service status: nssm status $SVC_NAME"           -ForegroundColor Gray
Write-Host "    Restart       : nssm restart $SVC_NAME"          -ForegroundColor Gray
Write-Host "    Diagnose      : .\Diagnose-CameraAgent.ps1"       -ForegroundColor Gray
Write-Host "    Update        : .\Update-CameraAgent.ps1 -InstallDir '$InstallDir'" -ForegroundColor Gray
Write-Host ""
Write-Host "  Gate Camera Live Feed:" -ForegroundColor Yellow
Write-Host "    Open the app -> Operations -> Gate Cameras -> Live" -ForegroundColor Gray
if (-not $EntryCameraUrl) {
    Write-Host "    NOTE: No gate camera URL was set -- reusing front camera." -ForegroundColor Yellow
    Write-Host "          Add gate_cameras.entry/exit URLs to $configPath" -ForegroundColor Yellow
    Write-Host "          and run .\Update-CameraAgent.ps1 to activate the live feed." -ForegroundColor Yellow
}
Write-Host ""
