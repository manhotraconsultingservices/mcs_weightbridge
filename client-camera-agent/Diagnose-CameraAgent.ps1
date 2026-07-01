<#
.SYNOPSIS
    Diagnose the Weighbridge Camera Agent installation on this PC.

.DESCRIPTION
    Run this script whenever the camera agent isn't working as expected.
    It automatically finds the real install directory, checks the service,
    validates the config, and tails the logs — no parameters needed.

.EXAMPLE
    .\Diagnose-CameraAgent.ps1

.EXAMPLE
    # Write report to a file and share with support
    .\Diagnose-CameraAgent.ps1 | Tee-Object -FilePath C:\camera_agent_report.txt
#>

$ErrorActionPreference = "SilentlyContinue"
$SVC_NAME = "WeighbridgeCameraAgent"

function Write-Section($title) {
    Write-Host ""
    Write-Host "  [$title]" -ForegroundColor Cyan
    Write-Host "  $('=' * (54 - $title.Length))" -ForegroundColor DarkGray
}
function OK($msg)   { Write-Host "  [OK]   $msg" -ForegroundColor Green  }
function WARN($msg) { Write-Host "  [WARN] $msg" -ForegroundColor Yellow }
function ERR($msg)  { Write-Host "  [ERR]  $msg" -ForegroundColor Red    }
function INFO($msg) { Write-Host "         $msg" -ForegroundColor Gray   }

Write-Host ""
Write-Host "  Weighbridge Camera Agent -- Diagnostics" -ForegroundColor Cyan
Write-Host "  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor DarkGray
Write-Host ""

# ── 1. Locate the real install directory ──────────────────────────────────────
Write-Section "1. Service & Install Directory"

$svc       = Get-Service -Name $SVC_NAME -ErrorAction SilentlyContinue
$taskSvc   = Get-ScheduledTask -TaskName $SVC_NAME -ErrorAction SilentlyContinue

$installDir = $null
$nssmExe    = $null

if ($svc) {
    $qc       = sc.exe qc $SVC_NAME 2>&1
    $binLine  = $qc | Where-Object { $_ -match "BINARY_PATH_NAME" }
    $nssmPath = ($binLine -replace ".*BINARY_PATH_NAME\s*:\s*", "").Trim().Trim('"')
    $installDir = Split-Path -Parent $nssmPath

    if ($svc.Status -eq "Running") {
        OK "Service RUNNING   (dir: $installDir)"
    } else {
        WARN "Service exists but is $($svc.Status)   (dir: $installDir)"
    }
    $nssmExe = $nssmPath  # The NSSM binary is IN the install dir
} elseif ($taskSvc) {
    $installDir = (Split-Path -Parent $taskSvc.Actions[0].Execute)
    OK "Scheduled task found (dir: $installDir)"
} else {
    ERR "No WeighbridgeCameraAgent service or scheduled task found."
    INFO "Run Install-CameraAgent.ps1 to install the agent."
}

# Look for nssm in common places
$nssmSearch = @("nssm", "$installDir\nssm.exe", "C:\nssm\nssm.exe", "C:\scripts\nssm.exe")
foreach ($p in $nssmSearch) {
    $f = Get-Command $p -ErrorAction SilentlyContinue
    if ($f) { $nssmExe = $f.Source; break }
}
if ($nssmExe) { INFO "NSSM: $nssmExe" } else { WARN "NSSM not found on PATH (Stop-Service/Start-Service will be used)" }

# Check for any running python camera_agent.py processes
$procs = Get-WmiObject Win32_Process -ErrorAction SilentlyContinue |
         Where-Object { $_.CommandLine -like "*camera_agent*" }
if ($procs) {
    INFO "Running python processes:"
    $procs | ForEach-Object { INFO "  PID $($_.ProcessId): $($_.CommandLine)" }
} else {
    if ($svc -and $svc.Status -eq "Running") {
        WARN "Service says Running but no python camera_agent process found."
        INFO "Try: Restart-Service $SVC_NAME"
    }
}

# ── 2. Agent file check ────────────────────────────────────────────────────────
Write-Section "2. Agent File"

if ($installDir -and (Test-Path $installDir)) {
    $agentFile = "$installDir\camera_agent.py"
    if (Test-Path $agentFile) {
        $agentBytes = (Get-Item $agentFile).Length
        $agentDate  = (Get-Item $agentFile).LastWriteTime.ToString("yyyy-MM-dd HH:mm")
        OK "camera_agent.py found ($agentBytes bytes, modified $agentDate)"

        # Check for GateLiveFeedPusher class (new code)
        $hasLiveFeed = Select-String -Path $agentFile -Pattern "GateLiveFeedPusher" -Quiet
        if ($hasLiveFeed) {
            OK "GateLiveFeedPusher class present (gate live feed supported)"
        } else {
            ERR "GateLiveFeedPusher class NOT found -- code is outdated."
            INFO "Fix: run Update-CameraAgent.ps1 to download the latest version."
        }

        # Check for GatePassListener
        $hasGateListener = Select-String -Path $agentFile -Pattern "GatePassListener" -Quiet
        if ($hasGateListener) {
            OK "GatePassListener class present (gate pass photos supported)"
        } else {
            WARN "GatePassListener class not found -- gate pass photos not supported."
        }
    } else {
        ERR "camera_agent.py not found in $installDir"
    }
} else {
    WARN "Cannot check agent file (install dir not found or inaccessible)"
}

# ── 3. Config check ───────────────────────────────────────────────────────────
Write-Section "3. Configuration (camera_config.json)"

$configPath = if ($installDir) { "$installDir\camera_config.json" } else { $null }
$cfg        = $null

if ($configPath -and (Test-Path $configPath)) {
    try {
        $raw = [System.IO.File]::ReadAllText($configPath, [System.Text.Encoding]::UTF8)
        $cfg = $raw | ConvertFrom-Json

        OK "Config found: $configPath"
        INFO "Cloud URL  : $($cfg.cloud_url)"
        INFO "Tenant     : $($cfg.tenant_slug)"
        INFO "Agent key  : $($cfg.agent_key.Substring(0,[Math]::Min(8,$cfg.agent_key.Length)))..."

        # Weighbridge cameras
        Write-Host ""
        INFO "Weighbridge cameras:"
        foreach ($cid in @("front", "top")) {
            $cam = $cfg.cameras.$cid
            if ($cam -and $cam.url) {
                INFO "  $cid : $($cam.url)"
            } else {
                WARN "  $cid : (no URL)"
            }
        }

        # Gate cameras
        Write-Host ""
        $hasGateCams = $false
        INFO "Gate cameras (for live feed + gate pass photos):"
        if ($cfg.PSObject.Properties["gate_cameras"]) {
            foreach ($gid in @("entry", "exit")) {
                $gcam = $cfg.gate_cameras.$gid
                if ($gcam -and $gcam.url) {
                    INFO "  $gid : $($gcam.url)"
                    $hasGateCams = $true
                } else {
                    WARN "  $gid : (no URL) -- live feed will reuse front camera"
                }
            }
        } else {
            ERR "gate_cameras section missing from config."
            INFO "Fix: run Update-CameraAgent.ps1 to add it."
        }

        # Snapshot mode
        Write-Host ""
        if ($cfg.snapshot_serve_url) {
            INFO "Snapshot mode : Local-first (Cloudflare Tunnel)"
            INFO "  Serve URL  : $($cfg.snapshot_serve_url)"
            INFO "  Save dir   : $($cfg.local_save_dir)"
        } else {
            INFO "Snapshot mode : Upload to VPS (legacy)"
        }

    } catch {
        ERR "Failed to parse camera_config.json: $_"
        INFO "The file may have invalid JSON or a BOM. Re-run Update-CameraAgent.ps1 to rewrite it."
    }
} else {
    ERR "camera_config.json not found$(if ($configPath) { " in $installDir" })"
    INFO "Run Install-CameraAgent.ps1 to create a fresh install."
}

# ── 4. Python check ───────────────────────────────────────────────────────────
Write-Section "4. Python Environment"

$pythonExe = $null
foreach ($py in @("python", "python3", "py")) {
    $f = Get-Command $py -ErrorAction SilentlyContinue
    if ($f) { $pythonExe = $f.Source; break }
}

if ($pythonExe) {
    $ver = & $pythonExe --version 2>&1
    OK "$ver at $pythonExe"

    # Check required packages
    $pkgs = @("requests", "urllib3", "PIL")
    foreach ($pkg in $pkgs) {
        $chk = & $pythonExe -c "import $pkg; print('ok')" 2>&1
        if ($chk -match "ok") {
            OK "Package: $pkg"
        } else {
            ERR "Package missing: $pkg"
            INFO "Fix: & '$pythonExe' -m pip install $(if ($pkg -eq 'PIL') { 'Pillow' } else { $pkg })"
        }
    }
    $ws = & $pythonExe -c "import websockets; print('ok')" 2>&1
    if ($ws -match "ok") { OK "Package: websockets (live stream)" }
    else { WARN "Package missing: websockets (live stream disabled but not required)" }
} else {
    ERR "Python not found on PATH"
    INFO "Download from https://python.org (3.11+)"
}

# ── 5. Network connectivity ────────────────────────────────────────────────────
Write-Section "5. Network Connectivity"

if ($cfg -and $cfg.cloud_url) {
    try {
        $healthUrl = "$($cfg.cloud_url.TrimEnd('/'))/api/v1/health"
        $resp = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 10 -ErrorAction Stop
        if ($resp.StatusCode -eq 200) {
            OK "Cloud reachable: $($cfg.cloud_url)"
        } else {
            WARN "Cloud returned HTTP $($resp.StatusCode)"
        }
    } catch {
        ERR "Cannot reach cloud: $($cfg.cloud_url)"
        INFO "Error: $_"
        INFO "Check internet connection or VPN."
    }

    # Test each camera
    if ($pythonExe -and (Test-Path "$installDir\camera_agent.py")) {
        Write-Host ""
        INFO "Testing camera connections (may take up to 30 s)..."
        $testOut = & $pythonExe "$installDir\camera_agent.py" --test 2>&1
        $testOut | ForEach-Object {
            if ($_ -match "OK") { OK $_ }
            elseif ($_ -match "FAILED|ERROR") { WARN $_ }
            else { INFO $_ }
        }
    }
}

# ── 6. Log file ───────────────────────────────────────────────────────────────
Write-Section "6. Recent Log (last 25 lines)"

$logFile = if ($installDir) { "$installDir\logs\camera_agent.log" } else { $null }
if ($logFile -and (Test-Path $logFile)) {
    $age = (Get-Date) - (Get-Item $logFile).LastWriteTime
    OK "Log file: $logFile (last updated $([int]$age.TotalMinutes) min ago)"
    Write-Host ""
    Get-Content $logFile -Tail 25 | ForEach-Object {
        if ($_ -match "\[ERROR\]")   { Write-Host "  $_" -ForegroundColor Red    }
        elseif ($_ -match "\[WARNING\]") { Write-Host "  $_" -ForegroundColor Yellow }
        elseif ($_ -match "\[INFO\].*Gate live feed") { Write-Host "  $_" -ForegroundColor Green }
        elseif ($_ -match "\[INFO\].*Gate") { Write-Host "  $_" -ForegroundColor Cyan }
        else { Write-Host "  $_" -ForegroundColor DarkGray }
    }
} else {
    WARN "Log file not found. Service may not have started yet."
    INFO "Expected: $($installDir)\logs\camera_agent.log"
}

# ── 7. Quick action menu ───────────────────────────────────────────────────────
Write-Host ""
Write-Host "  +====================================================+" -ForegroundColor DarkGray
Write-Host "  |  Quick Actions                                     |" -ForegroundColor DarkGray
Write-Host "  +====================================================+" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  Restart service:" -ForegroundColor Yellow
if ($nssmExe) {
    Write-Host "    & '$nssmExe' restart $SVC_NAME" -ForegroundColor Gray
} else {
    Write-Host "    Stop-Service $SVC_NAME -Force; Start-Service $SVC_NAME" -ForegroundColor Gray
}
Write-Host ""
Write-Host "  Update agent code + config:" -ForegroundColor Yellow
Write-Host "    .\Update-CameraAgent.ps1 -InstallDir '$installDir'" -ForegroundColor Gray
Write-Host ""
Write-Host "  Watch live log:" -ForegroundColor Yellow
Write-Host "    Get-Content '$logFile' -Wait -Tail 20" -ForegroundColor Gray
Write-Host ""
Write-Host "  Set gate camera URLs in config:" -ForegroundColor Yellow
Write-Host "    Notepad '$configPath'" -ForegroundColor Gray
Write-Host "    (then restart the service)" -ForegroundColor Gray
Write-Host ""
