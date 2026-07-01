<#
.SYNOPSIS
    Update the Weighbridge Camera Agent on an existing client PC.

.DESCRIPTION
    Stops the running WeighbridgeCameraAgent service, replaces camera_agent.py
    with the latest version, optionally adds gate_cameras to camera_config.json
    (entry + exit cameras for the Gate Camera Live Feed page), then restarts.

    Run this script from the agents\ folder of the latest source:
        cd C:\path\to\weighbridge-source\backend\agents
        .\Update-CameraAgent.ps1

.PARAMETER InstallDir
    Directory where the agent is currently installed (default: C:\weighbridge-agent).

.PARAMETER EntryCameraUrl
    Gate ENTRY camera snapshot URL. Leave blank to keep existing value.

.PARAMETER ExitCameraUrl
    Gate EXIT camera snapshot URL. Leave blank to keep existing value.

.PARAMETER CameraUser
    Gate camera username. Defaults to the weighbridge camera username already in config.

.PARAMETER CameraPass
    Gate camera password. Defaults to the weighbridge camera password already in config.

.EXAMPLE
    # Interactive -- prompts for gate camera URLs
    .\Update-CameraAgent.ps1

.EXAMPLE
    # Fully automated
    .\Update-CameraAgent.ps1 `
        -EntryCameraUrl "http://192.168.0.223/cgi-bin/snapshot.cgi" `
        -ExitCameraUrl  "http://192.168.0.224/cgi-bin/snapshot.cgi"
#>

param(
    [string]$InstallDir     = "C:\weighbridge-agent",
    [string]$EntryCameraUrl = "",
    [string]$ExitCameraUrl  = "",
    [string]$CameraUser     = "",
    [string]$CameraPass     = ""
)

$ErrorActionPreference = "Stop"

function Write-Step($num, $msg) {
    Write-Host ""
    Write-Host "  [$num] $msg" -ForegroundColor Cyan
    Write-Host "  $('-' * 52)" -ForegroundColor DarkGray
}
function Write-OK($msg)   { Write-Host "  [OK]   $msg" -ForegroundColor Green  }
function Write-Warn($msg) { Write-Host "  [WARN] $msg" -ForegroundColor Yellow }
function Write-Info($msg) { Write-Host "         $msg" -ForegroundColor Gray   }
function Prompt-Value($prompt, $default) {
    $val = Read-Host "    $prompt [$default]"
    if ([string]::IsNullOrWhiteSpace($val)) { return $default }
    return $val.Trim()
}

Write-Host ""
Write-Host "  +====================================================+" -ForegroundColor Cyan
Write-Host "  |   Weighbridge Camera Agent -- Updater              |" -ForegroundColor Cyan
Write-Host "  |   Adds Gate Camera Live Feed support               |" -ForegroundColor Cyan
Write-Host "  +====================================================+" -ForegroundColor Cyan
Write-Host ""

# ── Step 1: Validate install directory ──────────────────────────────────────

Write-Step 1 "Checking install directory"

$agentScript = Join-Path $InstallDir "camera_agent.py"
$configFile  = Join-Path $InstallDir "camera_config.json"

if (-not (Test-Path $InstallDir)) {
    Write-Host "  [ERR] Install directory not found: $InstallDir" -ForegroundColor Red
    Write-Host "        Re-run with -InstallDir pointing to your agent folder." -ForegroundColor Yellow
    exit 1
}
if (-not (Test-Path $configFile)) {
    Write-Host "  [ERR] camera_config.json not found in $InstallDir" -ForegroundColor Red
    Write-Host "        This script updates an existing install. Run deploy-agents.ps1 for a fresh install." -ForegroundColor Yellow
    exit 1
}
Write-OK "Install dir: $InstallDir"

# ── Step 2: Stop the service ─────────────────────────────────────────────────

Write-Step 2 "Stopping WeighbridgeCameraAgent"

$taskExists  = Get-ScheduledTask  -TaskName "WeighbridgeCameraAgent" -ErrorAction SilentlyContinue
$nssmService = Get-Service        -Name     "WeighbridgeCameraAgent" -ErrorAction SilentlyContinue

if ($taskExists) {
    Stop-ScheduledTask -TaskName "WeighbridgeCameraAgent" -ErrorAction SilentlyContinue
    Write-OK "Scheduled task stopped"
} elseif ($nssmService) {
    $nssm = Get-Command nssm -ErrorAction SilentlyContinue
    if (-not $nssm) { $nssm = Get-Command "C:\scripts\nssm.exe" -ErrorAction SilentlyContinue }
    if ($nssm) {
        & $nssm.Source stop WeighbridgeCameraAgent 2>$null
        Write-OK "NSSM service stopped"
    } else {
        # NSSM not in PATH -- use built-in Stop-Service (works for NSSM-registered services too)
        Stop-Service -Name "WeighbridgeCameraAgent" -Force -ErrorAction SilentlyContinue
        Write-OK "Service stopped (via Stop-Service)"
    }
} else {
    Write-Warn "No running WeighbridgeCameraAgent found -- continuing"
}

Start-Sleep -Seconds 2

# ── Step 3: Replace camera_agent.py ──────────────────────────────────────────

Write-Step 3 "Replacing camera_agent.py"

$srcAgent = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "camera_agent.py"
if (-not (Test-Path $srcAgent)) {
    Write-Host "  [ERR] camera_agent.py not found next to this script ($srcAgent)" -ForegroundColor Red
    Write-Host "        Run this script from the weighbridge-source\backend\agents\ folder." -ForegroundColor Yellow
    exit 1
}

$srcResolved = if (Test-Path $srcAgent) { (Resolve-Path $srcAgent).Path } else { $srcAgent }
$dstResolved = if (Test-Path $agentScript) { (Resolve-Path $agentScript).Path } else { $agentScript }

if ($srcResolved -eq $dstResolved) {
    Write-Warn "Script is inside the install directory -- cannot self-copy."
    Write-Info "Downloading latest camera_agent.py from GitHub..."
    $rawUrl = "https://raw.githubusercontent.com/manhotraconsultingservices/mcs_weightbridge/main/backend/agents/camera_agent.py"
    try {
        $backupPath = "$agentScript.bak"
        if (Test-Path $agentScript) { Copy-Item $agentScript $backupPath -Force; Write-Info "Backup: $backupPath" }
        Invoke-WebRequest -Uri $rawUrl -OutFile $agentScript -UseBasicParsing
        Write-OK "camera_agent.py downloaded from GitHub"
    } catch {
        Write-Host "  [ERR] Download failed: $_" -ForegroundColor Red
        Write-Host "        Download manually from: $rawUrl" -ForegroundColor Yellow
        exit 1
    }
} else {
    $backupPath = "$agentScript.bak"
    if (Test-Path $agentScript) {
        Copy-Item $agentScript $backupPath -Force
        Write-Info "Backup: $backupPath"
    }
    Copy-Item $srcAgent $agentScript -Force
    Write-OK "camera_agent.py updated"
}

# ── Step 4: Add gate_cameras to config if missing ────────────────────────────

Write-Step 4 "Updating camera_config.json (gate_cameras section)"

$rawJson = [System.IO.File]::ReadAllText($configFile, [System.Text.Encoding]::UTF8)
$cfg     = $rawJson | ConvertFrom-Json

# Read existing gate_cameras if already present
$existingEntry = ""
$existingExit  = ""
if ($cfg.PSObject.Properties["gate_cameras"]) {
    $gc = $cfg.gate_cameras
    if ($gc.PSObject.Properties["entry"]) { $existingEntry = $gc.entry.url }
    if ($gc.PSObject.Properties["exit"])  { $existingExit  = $gc.exit.url  }
}

if ($existingEntry -or $existingExit) {
    Write-Info "gate_cameras already present in config:"
    Write-Info "  Entry: $existingEntry"
    Write-Info "  Exit:  $existingExit"
    $overwrite = Read-Host "    Update gate camera URLs? (y/N)"
    if ($overwrite -notmatch "^[Yy]") {
        Write-Info "Keeping existing gate camera config."
    } else {
        $existingEntry = ""
        $existingExit  = ""
    }
}

if (-not $existingEntry -and -not $existingExit) {
    # Resolve defaults from existing weighbridge camera credentials
    $defaultUser = ""
    $defaultPass = ""
    if ($cfg.PSObject.Properties["cameras"] -and $cfg.cameras.PSObject.Properties["front"]) {
        $defaultUser = $cfg.cameras.front.username
        $defaultPass = $cfg.cameras.front.password
    }

    Write-Host ""
    Write-Info "Enter the gate camera snapshot URLs for the live feed page."
    Write-Info "Tip: Leave blank if you want to skip that camera position."
    Write-Host ""

    if ([string]::IsNullOrWhiteSpace($EntryCameraUrl)) {
        $EntryCameraUrl = Prompt-Value "Entry camera URL (blank to skip)" ""
    }
    if ([string]::IsNullOrWhiteSpace($ExitCameraUrl)) {
        $ExitCameraUrl = Prompt-Value "Exit  camera URL (blank to skip)" ""
    }
    if ([string]::IsNullOrWhiteSpace($CameraUser)) {
        $CameraUser = Prompt-Value "Camera username (enter for same as weighbridge: $defaultUser)" $defaultUser
    }
    if ([string]::IsNullOrWhiteSpace($CameraPass) -and -not [string]::IsNullOrWhiteSpace($CameraUser)) {
        $CameraPass = Prompt-Value "Camera password" $defaultPass
    }

    # Build gate_cameras as a hashtable, merge into the parsed JSON.
    # ConvertFrom-Json returns PSCustomObject; rebuild as hashtable for clean serialization.

    function ConvertPSObjectToHashtable($obj) {
        if ($null -eq $obj) { return $null }
        if ($obj -is [System.Management.Automation.PSCustomObject]) {
            $ht = @{}
            foreach ($prop in $obj.PSObject.Properties) {
                $ht[$prop.Name] = ConvertPSObjectToHashtable $prop.Value
            }
            return $ht
        }
        if ($obj -is [System.Object[]]) {
            return @($obj | ForEach-Object { ConvertPSObjectToHashtable $_ })
        }
        return $obj
    }

    $cfgHt = ConvertPSObjectToHashtable $cfg
    $cfgHt["gate_cameras"] = @{
        entry = @{ url = $EntryCameraUrl; username = $CameraUser; password = $CameraPass }
        exit  = @{ url = $ExitCameraUrl;  username = $CameraUser; password = $CameraPass }
    }

    $newJson = $cfgHt | ConvertTo-Json -Depth 6
    # Write BOM-free UTF-8 so Python's json.load() can read it without errors
    [System.IO.File]::WriteAllText($configFile, $newJson, [System.Text.UTF8Encoding]::new($false))

    Write-OK "camera_config.json updated"
    if ($EntryCameraUrl) { Write-Info "Entry: $EntryCameraUrl" } else { Write-Info "Entry: (skipped)" }
    if ($ExitCameraUrl)  { Write-Info "Exit:  $ExitCameraUrl"  } else { Write-Info "Exit:  (skipped)" }
} else {
    Write-OK "gate_cameras unchanged"
}

# ── Step 5: Restart the service ───────────────────────────────────────────────

Write-Step 5 "Restarting WeighbridgeCameraAgent"

if ($taskExists) {
    Start-ScheduledTask -TaskName "WeighbridgeCameraAgent"
    Write-OK "Scheduled task started"
} elseif ($nssmService) {
    $nssm = Get-Command nssm -ErrorAction SilentlyContinue
    if (-not $nssm) { $nssm = Get-Command "C:\scripts\nssm.exe" -ErrorAction SilentlyContinue }
    if ($nssm) {
        & $nssm.Source start WeighbridgeCameraAgent 2>$null
        Write-OK "NSSM service started"
    } else {
        # NSSM not in PATH -- use built-in Start-Service
        Start-Service -Name "WeighbridgeCameraAgent" -ErrorAction SilentlyContinue
        Write-OK "Service started (via Start-Service)"
    }
} else {
    Write-Warn "Service not found -- start it manually:"
    Write-Info "  python $agentScript"
}

# ── Step 6: Verify ────────────────────────────────────────────────────────────

Write-Step 6 "Verifying"

Start-Sleep -Seconds 5

$logFile = Join-Path $InstallDir "logs\camera_agent.log"
if (Test-Path $logFile) {
    $tail = Get-Content $logFile -Tail 15 -ErrorAction SilentlyContinue
    $gateReady = $tail | Where-Object { $_ -match "Gate live feed" }
    $running   = $tail | Where-Object { $_ -match "Running|started" }

    if ($gateReady) {
        Write-OK "Gate live feed pusher confirmed in logs:"
        $gateReady | ForEach-Object { Write-Info "  $_" }
    } elseif ($running) {
        Write-OK "Agent running (gate live log line may appear in a few seconds)"
    } else {
        Write-Warn "No log lines yet -- check manually:"
        Write-Info "  Get-Content '$logFile' -Tail 20"
    }
} else {
    Write-Warn "Log file not found yet (agent may still be starting)"
}

# ── Summary ───────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "  +====================================================+" -ForegroundColor Green
Write-Host "  |   Update Complete!                                  |" -ForegroundColor Green
Write-Host "  +====================================================+" -ForegroundColor Green
Write-Host ""
Write-Host "  Agent dir : $InstallDir" -ForegroundColor White
Write-Host "  Config    : $configFile" -ForegroundColor White
Write-Host ""
Write-Host "  What is new in this update:" -ForegroundColor Yellow
Write-Host "    - Gate Camera Live Feed: the agent now pushes frames from" -ForegroundColor Gray
Write-Host "      gate_cameras.entry + .exit to the cloud every 3 s." -ForegroundColor Gray
Write-Host "    - Open app -> Operations -> Gate Cameras -> Live to see frames." -ForegroundColor Gray
Write-Host ""
Write-Host "  Useful commands:" -ForegroundColor Yellow
Write-Host "    View logs : Get-Content '$logFile' -Tail 30" -ForegroundColor Gray
Write-Host "    Restart   : Stop-ScheduledTask WeighbridgeCameraAgent; Start-ScheduledTask WeighbridgeCameraAgent" -ForegroundColor Gray
Write-Host ""
