<#
.SYNOPSIS
    Weighbridge Agent Deployment Script — one-click installer for client PCs.

.DESCRIPTION
    Deploys the Camera Agent and/or Scale Agent on a client PC.
    Handles: Python check, dependency install, config generation,
    Windows Scheduled Task registration, firewall rules, and verification.

.PARAMETER InstallDir
    Installation directory (default: C:\weighbridge-agent)

.PARAMETER AgentType
    Which agent(s) to deploy: "both", "camera", "scale" (default: both)

.PARAMETER CloudUrl
    Cloud server URL (default: https://weighbridgesetu.com)

.PARAMETER TenantSlug
    Tenant identifier (e.g., manhotra-consulting)

.PARAMETER AgentKey
    Agent API key from platform admin console

.PARAMETER FrontCameraUrl
    Front camera snapshot URL (e.g., http://192.168.0.101/cgi-bin/snapshot.cgi)

.PARAMETER TopCameraUrl
    Top camera snapshot URL (e.g., http://192.168.0.103/cgi-bin/snapshot.cgi)

.PARAMETER CameraUser
    Camera authentication username

.PARAMETER CameraPass
    Camera authentication password

.PARAMETER ComPort
    Serial port for scale (e.g., COM3)

.PARAMETER BaudRate
    Scale baud rate (default: 9600)

.PARAMETER Uninstall
    Remove agents, scheduled tasks, and firewall rules

.EXAMPLE
    # Interactive setup (prompts for all values)
    .\deploy-agents.ps1

.EXAMPLE
    # Full automated deployment
    .\deploy-agents.ps1 -TenantSlug "ziya-ore" -AgentKey "abc-123" `
        -FrontCameraUrl "http://192.168.0.101/cgi-bin/snapshot.cgi" `
        -TopCameraUrl "http://192.168.0.103/cgi-bin/snapshot.cgi" `
        -CameraUser "admin" -CameraPass "admin123" `
        -ComPort "COM3"

.EXAMPLE
    # Camera only
    .\deploy-agents.ps1 -AgentType camera -TenantSlug "demo" -AgentKey "key123"

.EXAMPLE
    # Uninstall everything
    .\deploy-agents.ps1 -Uninstall
#>

param(
    [string]$InstallDir   = "C:\weighbridge-agent",
    [ValidateSet("both","camera","scale")]
    [string]$AgentType    = "both",
    [string]$CloudUrl     = "https://weighbridgesetu.com",
    [string]$TenantSlug   = "",
    [string]$AgentKey     = "",
    [string]$FrontCameraUrl = "",
    [string]$TopCameraUrl   = "",
    [string]$CameraUser     = "",
    [string]$CameraPass     = "",
    [string]$ComPort        = "",
    [int]$BaudRate          = 9600,
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"

# ── Helpers ─────────────────────────────────────────────────────────────────

function Write-Step($num, $msg) {
    Write-Host ""
    Write-Host "  [$num] $msg" -ForegroundColor Cyan
    Write-Host "  $('─' * 50)" -ForegroundColor DarkGray
}

function Write-OK($msg)   { Write-Host "    ✓ $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "    ⚠ $msg" -ForegroundColor Yellow }
function Write-Err($msg)  { Write-Host "    ✗ $msg" -ForegroundColor Red }
function Write-Info($msg) { Write-Host "    $msg" -ForegroundColor Gray }

function Prompt-Value($prompt, $default) {
    $val = Read-Host "    $prompt [$default]"
    if ([string]::IsNullOrWhiteSpace($val)) { return $default }
    return $val.Trim()
}

function Prompt-Required($prompt) {
    do {
        $val = Read-Host "    $prompt"
        if ([string]::IsNullOrWhiteSpace($val)) {
            Write-Warn "This field is required."
        }
    } while ([string]::IsNullOrWhiteSpace($val))
    return $val.Trim()
}

# ── Banner ──────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "  ╔══════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "  ║   Weighbridge Agent Deployment                  ║" -ForegroundColor Cyan
Write-Host "  ║   Camera + Scale Agent Installer                ║" -ForegroundColor Cyan
Write-Host "  ╚══════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ── Uninstall ───────────────────────────────────────────────────────────────

if ($Uninstall) {
    Write-Step 1 "Removing Scheduled Tasks"

    foreach ($taskName in @("WeighbridgeCameraAgent", "WeighbridgeScaleAgent")) {
        $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        if ($task) {
            Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
            Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
            Write-OK "Removed task: $taskName"
        } else {
            Write-Info "Task not found: $taskName (skipped)"
        }
    }

    # Also try NSSM services
    $nssm = Get-Command nssm -ErrorAction SilentlyContinue
    if (-not $nssm) { $nssm = Get-Command "C:\scripts\nssm.exe" -ErrorAction SilentlyContinue }
    if ($nssm) {
        foreach ($svcName in @("WeighbridgeCameraAgent", "WeighbridgeScaleAgent")) {
            $svc = Get-Service -Name $svcName -ErrorAction SilentlyContinue
            if ($svc) {
                & $nssm.Source stop $svcName 2>$null
                & $nssm.Source remove $svcName confirm 2>$null
                Write-OK "Removed NSSM service: $svcName"
            }
        }
    }

    Write-Step 2 "Removing Firewall Rules"
    Remove-NetFirewallRule -DisplayName "Weighbridge Camera Agent*" -ErrorAction SilentlyContinue
    Remove-NetFirewallRule -DisplayName "Weighbridge Scale Agent*" -ErrorAction SilentlyContinue
    Write-OK "Firewall rules removed"

    Write-Step 3 "Stopping Processes"
    Get-Process python* -ErrorAction SilentlyContinue | Where-Object {
        $_.Path -and $_.Path -like "*weighbridge*"
    } | Stop-Process -Force -ErrorAction SilentlyContinue
    Write-OK "Agent processes stopped"

    Write-Host ""
    Write-Host "  ✓ Agents uninstalled." -ForegroundColor Green
    Write-Host "  Note: $InstallDir was NOT deleted (contains logs/configs)." -ForegroundColor Yellow
    Write-Host "  To fully remove: Remove-Item '$InstallDir' -Recurse -Force" -ForegroundColor Yellow
    Write-Host ""
    exit 0
}

# ══════════════════════════════════════════════════════════════════════════════
# INSTALLATION
# ══════════════════════════════════════════════════════════════════════════════

$deployCamera = $AgentType -in @("both", "camera")
$deployScale  = $AgentType -in @("both", "scale")

# ── Step 1: Check Python ────────────────────────────────────────────────────

Write-Step 1 "Checking Python"

$pythonExe = $null
foreach ($candidate in @(
    "python",
    "python3",
    "C:\Program Files\Python311\python.exe",
    "C:\Program Files\Python312\python.exe",
    "C:\Python311\python.exe",
    "C:\Python312\python.exe"
)) {
    try {
        $ver = & $candidate --version 2>&1
        if ($ver -match "Python 3\.\d+") {
            $pythonExe = $candidate
            break
        }
    } catch {}
}

if (-not $pythonExe) {
    Write-Err "Python 3.x not found. Install from https://python.org/downloads"
    exit 1
}

$pyVersion = & $pythonExe --version 2>&1
$pyPath    = & $pythonExe -c "import sys; print(sys.executable)" 2>&1
Write-OK "$pyVersion at $pyPath"

# ── Step 2: Create Install Directory ────────────────────────────────────────

Write-Step 2 "Setting up $InstallDir"

if (-not (Test-Path $InstallDir)) {
    New-Item -Path $InstallDir -ItemType Directory -Force | Out-Null
    Write-OK "Created $InstallDir"
} else {
    Write-Info "Directory exists (updating files)"
}

New-Item -Path "$InstallDir\logs" -ItemType Directory -Force -ErrorAction SilentlyContinue | Out-Null

# ── Step 3: Copy Agent Files ────────────────────────────────────────────────

Write-Step 3 "Copying agent files"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

$filesToCopy = @("requirements.txt")
if ($deployCamera) { $filesToCopy += "camera_agent.py" }
if ($deployScale)  { $filesToCopy += "scale_agent.py" }

foreach ($file in $filesToCopy) {
    $src = Join-Path $scriptDir $file
    if (Test-Path $src) {
        Copy-Item $src -Destination "$InstallDir\$file" -Force
        Write-OK "Copied $file"
    } else {
        Write-Warn "$file not found in $scriptDir"
    }
}

# ── Step 4: Install Python Dependencies ─────────────────────────────────────

Write-Step 4 "Installing Python dependencies"

$reqFile = Join-Path $InstallDir "requirements.txt"
if (Test-Path $reqFile) {
    # Install to global site-packages (for scheduled task/SYSTEM user)
    $sitePackages = & $pythonExe -c "import site; print(site.getsitepackages()[0])" 2>&1
    Write-Info "Target: $sitePackages"

    & $pythonExe -m pip install -r $reqFile --target $sitePackages --quiet --disable-pip-version-check 2>&1 | Out-Null

    # Verify key packages
    $missing = @()
    foreach ($pkg in @("requests", "pyserial", "websockets")) {
        $check = & $pythonExe -c "import $($pkg -replace '-','_')" 2>&1
        if ($LASTEXITCODE -ne 0) { $missing += $pkg }
    }

    if ($missing.Count -eq 0) {
        Write-OK "All dependencies installed (requests, pyserial, websockets)"
    } else {
        Write-Warn "Some packages may need manual install: $($missing -join ', ')"
        # Retry with user install
        & $pythonExe -m pip install -r $reqFile --quiet --disable-pip-version-check 2>&1 | Out-Null
    }
} else {
    Write-Warn "requirements.txt not found — skipping"
}

# ── Step 5: Gather Configuration ────────────────────────────────────────────

Write-Step 5 "Configuration"

# Prompt for shared values if not provided
if ([string]::IsNullOrWhiteSpace($TenantSlug)) {
    $TenantSlug = Prompt-Required "Tenant slug (e.g., ziya-ore-minerals)"
}
if ([string]::IsNullOrWhiteSpace($AgentKey)) {
    $AgentKey = Prompt-Required "Agent API key (from platform admin)"
}
$CloudUrl = Prompt-Value "Cloud URL" $CloudUrl

Write-OK "Tenant: $TenantSlug"
Write-OK "Cloud:  $CloudUrl"

# ── Step 6: Configure Camera Agent ──────────────────────────────────────────

if ($deployCamera) {
    Write-Step 6 "Configuring Camera Agent"

    if ([string]::IsNullOrWhiteSpace($FrontCameraUrl)) {
        Write-Host ""
        Write-Info "Common camera snapshot URL formats:"
        Write-Info "  CP Plus / Dahua:  http://IP/cgi-bin/snapshot.cgi"
        Write-Info "  Hikvision:        http://IP/Streaming/channels/1/picture"
        Write-Info "  Generic:          http://IP/snap.jpg"
        Write-Host ""
        $FrontCameraUrl = Prompt-Value "Front camera URL" "http://192.168.0.101/cgi-bin/snapshot.cgi"
    }
    if ([string]::IsNullOrWhiteSpace($TopCameraUrl)) {
        $TopCameraUrl = Prompt-Value "Top camera URL" "http://192.168.0.103/cgi-bin/snapshot.cgi"
    }
    if ([string]::IsNullOrWhiteSpace($CameraUser)) {
        $CameraUser = Prompt-Value "Camera username (enter for none)" ""
    }
    if ([string]::IsNullOrWhiteSpace($CameraPass) -and -not [string]::IsNullOrWhiteSpace($CameraUser)) {
        $CameraPass = Prompt-Value "Camera password" ""
    }

    $cameraConfig = @{
        cloud_url         = $CloudUrl
        tenant_slug       = $TenantSlug
        agent_key         = $AgentKey
        poll_interval_sec = 5
        status_port       = 9003
        ws_port           = 9004
        cameras           = @{
            front = @{
                label    = "Front View"
                url      = $FrontCameraUrl
                username = $CameraUser
                password = $CameraPass
            }
            top = @{
                label    = "Top View"
                url      = $TopCameraUrl
                username = $CameraUser
                password = $CameraPass
            }
        }
    }

    $cameraConfigPath = Join-Path $InstallDir "camera_config.json"
    $cameraConfig | ConvertTo-Json -Depth 4 | Set-Content $cameraConfigPath -Encoding UTF8
    Write-OK "camera_config.json saved"
    Write-Info "Front: $FrontCameraUrl"
    Write-Info "Top:   $TopCameraUrl"
}

# ── Step 7: Configure Scale Agent ───────────────────────────────────────────

if ($deployScale) {
    $stepNum = if ($deployCamera) { 7 } else { 6 }
    Write-Step $stepNum "Configuring Scale Agent"

    if ([string]::IsNullOrWhiteSpace($ComPort)) {
        # List available COM ports
        Write-Info "Available COM ports:"
        $ports = [System.IO.Ports.SerialPort]::GetPortNames()
        if ($ports.Count -eq 0) {
            Write-Warn "No COM ports detected. Connect the scale and retry."
            $ComPort = Prompt-Value "COM port" "COM3"
        } else {
            foreach ($p in $ports) { Write-Info "  → $p" }
            $ComPort = Prompt-Value "COM port" $ports[0]
        }
    }
    $BaudRate = [int](Prompt-Value "Baud rate" $BaudRate)

    $scaleConfig = @{
        cloud_url        = $CloudUrl
        tenant_slug      = $TenantSlug
        agent_key        = $AgentKey
        port             = $ComPort
        baud_rate        = $BaudRate
        data_bits        = 8
        stop_bits        = 1
        parity           = "N"
        push_interval_ms = 500
        status_port      = 9002
    }

    $scaleConfigPath = Join-Path $InstallDir "scale_config.json"
    $scaleConfig | ConvertTo-Json -Depth 4 | Set-Content $scaleConfigPath -Encoding UTF8
    Write-OK "scale_config.json saved"
    Write-Info "Port: $ComPort @ $BaudRate baud"
}

# ── Step 8: Test Cameras ────────────────────────────────────────────────────

if ($deployCamera) {
    $stepNum = if ($deployScale) { 8 } else { 7 }
    Write-Step $stepNum "Testing cameras"

    Push-Location $InstallDir
    $testResult = & $pythonExe camera_agent.py --test 2>&1
    Pop-Location

    foreach ($line in $testResult) {
        if ($line -match "OK") { Write-OK $line.Trim() }
        elseif ($line -match "FAILED|ERROR") { Write-Warn $line.Trim() }
        else { Write-Info $line.Trim() }
    }
}

# ── Step 9: Register Scheduled Tasks ────────────────────────────────────────

$stepNum = if ($deployScale -and $deployCamera) { 9 } elseif ($deployCamera -or $deployScale) { 8 } else { 7 }
Write-Step $stepNum "Registering Windows Scheduled Tasks"

function Register-AgentTask($taskName, $scriptFile, $description) {
    # Remove existing task if present
    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($existing) {
        Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Info "Removed existing task: $taskName"
    }

    # Also remove any NSSM service with same name
    $svc = Get-Service -Name $taskName -ErrorAction SilentlyContinue
    if ($svc) {
        $nssm = Get-Command nssm -ErrorAction SilentlyContinue
        if (-not $nssm) { $nssm = Get-Command "C:\scripts\nssm.exe" -ErrorAction SilentlyContinue }
        if ($nssm) {
            & $nssm.Source stop $taskName 2>$null
            & $nssm.Source remove $taskName confirm 2>$null
            Write-Info "Removed NSSM service: $taskName"
        }
    }

    $scriptPath = Join-Path $InstallDir $scriptFile
    $pyExePath  = (& $pythonExe -c "import sys; print(sys.executable)" 2>&1).Trim()

    # Create scheduled task that runs at startup and restarts on failure
    $action  = New-ScheduledTaskAction -Execute $pyExePath -Argument $scriptPath -WorkingDirectory $InstallDir
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit (New-TimeSpan -Days 365)

    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Trigger $trigger `
        -Principal $principal `
        -Settings $settings `
        -Description $description `
        -Force | Out-Null

    # Start the task immediately
    Start-ScheduledTask -TaskName $taskName
    Write-OK "$taskName registered and started"
}

if ($deployCamera) {
    Register-AgentTask "WeighbridgeCameraAgent" "camera_agent.py" `
        "Weighbridge Camera Agent — captures snapshots from IP cameras, serves WebSocket live feed on port 9004"
}

if ($deployScale) {
    Register-AgentTask "WeighbridgeScaleAgent" "scale_agent.py" `
        "Weighbridge Scale Agent — reads weight from COM port, pushes to cloud"
}

# ── Step 10: Firewall Rules ─────────────────────────────────────────────────

$stepNum++
Write-Step $stepNum "Configuring Firewall"

if ($deployCamera) {
    # Remove old rules first
    Remove-NetFirewallRule -DisplayName "Weighbridge Camera Agent HTTP" -ErrorAction SilentlyContinue
    Remove-NetFirewallRule -DisplayName "Weighbridge Camera Agent WebSocket" -ErrorAction SilentlyContinue

    New-NetFirewallRule -DisplayName "Weighbridge Camera Agent HTTP" `
        -Direction Inbound -Protocol TCP -LocalPort 9003 `
        -Action Allow -Profile Private,Domain -Description "Camera agent status API" | Out-Null
    New-NetFirewallRule -DisplayName "Weighbridge Camera Agent WebSocket" `
        -Direction Inbound -Protocol TCP -LocalPort 9004 `
        -Action Allow -Profile Private,Domain -Description "Camera agent WebSocket live feed" | Out-Null
    Write-OK "Firewall: ports 9003 (HTTP) + 9004 (WebSocket) opened"
}

if ($deployScale) {
    Remove-NetFirewallRule -DisplayName "Weighbridge Scale Agent HTTP" -ErrorAction SilentlyContinue

    New-NetFirewallRule -DisplayName "Weighbridge Scale Agent HTTP" `
        -Direction Inbound -Protocol TCP -LocalPort 9002 `
        -Action Allow -Profile Private,Domain -Description "Scale agent status API" | Out-Null
    Write-OK "Firewall: port 9002 (HTTP) opened"
}

# ── Step 11: Verify ─────────────────────────────────────────────────────────

$stepNum++
Write-Step $stepNum "Verifying deployment"

Start-Sleep -Seconds 5

if ($deployCamera) {
    $logFile = Join-Path $InstallDir "logs\camera_agent.log"
    if (Test-Path $logFile) {
        $logTail = Get-Content $logFile -Tail 10 -ErrorAction SilentlyContinue
        $wsReady = $logTail | Where-Object { $_ -match "WebSocket live server" }
        $running = $logTail | Where-Object { $_ -match "Running" }

        if ($wsReady) { Write-OK "Camera Agent: WebSocket live server ready (port 9004)" }
        elseif ($running) { Write-OK "Camera Agent: running" }
        else { Write-Warn "Camera Agent: check logs at $logFile" }
    } else {
        Write-Warn "Camera Agent: log file not found yet (may still be starting)"
    }

    # Test HTTP endpoint
    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:9003" -TimeoutSec 3 -ErrorAction Stop
        if ($resp.StatusCode -eq 200) { Write-OK "Camera Agent: HTTP status OK (port 9003)" }
    } catch {
        Write-Info "Camera Agent: HTTP endpoint not ready yet (may take a few seconds)"
    }
}

if ($deployScale) {
    $logFile = Join-Path $InstallDir "logs\scale_agent.log"
    if (Test-Path $logFile) {
        $logTail = Get-Content $logFile -Tail 5 -ErrorAction SilentlyContinue
        $running = $logTail | Where-Object { $_ -match "Running|listening" }

        if ($running) { Write-OK "Scale Agent: running" }
        else { Write-Warn "Scale Agent: check logs at $logFile" }
    } else {
        Write-Warn "Scale Agent: log file not found yet"
    }
}

# ── Summary ─────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "  ╔══════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "  ║   Deployment Complete!                          ║" -ForegroundColor Green
Write-Host "  ╚══════════════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""
Write-Host "  Install Dir:  $InstallDir" -ForegroundColor White
Write-Host "  Tenant:       $TenantSlug" -ForegroundColor White
Write-Host "  Cloud:        $CloudUrl" -ForegroundColor White
Write-Host ""

if ($deployCamera) {
    Write-Host "  Camera Agent:" -ForegroundColor Cyan
    Write-Host "    Task:       WeighbridgeCameraAgent" -ForegroundColor Gray
    Write-Host "    Status API: http://localhost:9003" -ForegroundColor Gray
    Write-Host "    Live Feed:  ws://localhost:9004/live/front" -ForegroundColor Gray
    Write-Host "                ws://localhost:9004/live/top" -ForegroundColor Gray
    Write-Host "    Config:     $InstallDir\camera_config.json" -ForegroundColor Gray
    Write-Host ""
}

if ($deployScale) {
    Write-Host "  Scale Agent:" -ForegroundColor Cyan
    Write-Host "    Task:       WeighbridgeScaleAgent" -ForegroundColor Gray
    Write-Host "    Status API: http://localhost:9002" -ForegroundColor Gray
    Write-Host "    COM Port:   $ComPort @ $BaudRate baud" -ForegroundColor Gray
    Write-Host "    Config:     $InstallDir\scale_config.json" -ForegroundColor Gray
    Write-Host ""
}

Write-Host "  Logs:         $InstallDir\logs\" -ForegroundColor Gray
Write-Host ""
Write-Host "  Quick Commands:" -ForegroundColor Yellow
Write-Host "    Check status:   Get-ScheduledTask 'Weighbridge*Agent'" -ForegroundColor Gray
Write-Host "    View logs:      Get-Content $InstallDir\logs\camera_agent.log -Tail 20" -ForegroundColor Gray
Write-Host "    Restart camera: Stop-ScheduledTask WeighbridgeCameraAgent; Start-ScheduledTask WeighbridgeCameraAgent" -ForegroundColor Gray
Write-Host "    Restart scale:  Stop-ScheduledTask WeighbridgeScaleAgent; Start-ScheduledTask WeighbridgeScaleAgent" -ForegroundColor Gray
Write-Host "    Uninstall:      .\deploy-agents.ps1 -Uninstall" -ForegroundColor Gray
Write-Host ""
