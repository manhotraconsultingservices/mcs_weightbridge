<#
.SYNOPSIS
    Manage Weighbridge agents — start, stop, restart, status, logs, update.

.PARAMETER Action
    Action to perform: status, start, stop, restart, logs, update, test

.PARAMETER Agent
    Target agent: all, camera, scale (default: all)

.EXAMPLE
    .\manage-agents.ps1 status
    .\manage-agents.ps1 restart camera
    .\manage-agents.ps1 logs scale
    .\manage-agents.ps1 update          # pull latest agent files + restart
    .\manage-agents.ps1 test camera     # test camera connectivity
#>

param(
    [Parameter(Position=0)]
    [ValidateSet("status","start","stop","restart","logs","update","test")]
    [string]$Action = "status",

    [Parameter(Position=1)]
    [ValidateSet("all","camera","scale")]
    [string]$Agent = "all"
)

$InstallDir = "C:\weighbridge-agent"

$agents = @{
    camera = @{
        TaskName = "WeighbridgeCameraAgent"
        Script   = "camera_agent.py"
        LogFile  = "camera_agent.log"
        Ports    = @(9003, 9004)
        Label    = "Camera Agent"
    }
    scale = @{
        TaskName = "WeighbridgeScaleAgent"
        Script   = "scale_agent.py"
        LogFile  = "scale_agent.log"
        Ports    = @(9002)
        Label    = "Scale Agent"
    }
}

$targets = if ($Agent -eq "all") { @("camera", "scale") } else { @($Agent) }

function Get-AgentProcess($scriptName) {
    Get-Process python* -ErrorAction SilentlyContinue | Where-Object {
        try {
            $cmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)" -ErrorAction SilentlyContinue).CommandLine
            $cmdLine -and $cmdLine -like "*$scriptName*"
        } catch { $false }
    }
}

switch ($Action) {

    "status" {
        Write-Host ""
        Write-Host "  Weighbridge Agent Status" -ForegroundColor Cyan
        Write-Host "  $('─' * 40)" -ForegroundColor DarkGray

        foreach ($name in $targets) {
            $a = $agents[$name]
            Write-Host ""
            Write-Host "  $($a.Label):" -ForegroundColor White

            # Scheduled task
            $task = Get-ScheduledTask -TaskName $a.TaskName -ErrorAction SilentlyContinue
            if ($task) {
                $state = $task.State
                $color = if ($state -eq "Running") { "Green" } elseif ($state -eq "Ready") { "Yellow" } else { "Red" }
                Write-Host "    Task:    $($a.TaskName) [$state]" -ForegroundColor $color
            } else {
                Write-Host "    Task:    Not registered" -ForegroundColor DarkGray
            }

            # Process
            $proc = Get-AgentProcess $a.Script
            if ($proc) {
                Write-Host "    Process: PID $($proc.Id) (running)" -ForegroundColor Green
            } else {
                Write-Host "    Process: Not running" -ForegroundColor Red
            }

            # Port check
            foreach ($port in $a.Ports) {
                try {
                    $resp = Invoke-WebRequest -Uri "http://localhost:$port" -TimeoutSec 2 -ErrorAction Stop
                    Write-Host "    Port $port : responding" -ForegroundColor Green
                } catch {
                    Write-Host "    Port $port : not responding" -ForegroundColor Red
                }
            }

            # Last log entry
            $logPath = Join-Path $InstallDir "logs\$($a.LogFile)"
            if (Test-Path $logPath) {
                $lastLine = Get-Content $logPath -Tail 1 -ErrorAction SilentlyContinue
                if ($lastLine) {
                    $truncated = if ($lastLine.Length -gt 70) { $lastLine.Substring(0, 70) + "..." } else { $lastLine }
                    Write-Host "    Last log: $truncated" -ForegroundColor DarkGray
                }
            }
        }
        Write-Host ""
    }

    "start" {
        foreach ($name in $targets) {
            $a = $agents[$name]
            $task = Get-ScheduledTask -TaskName $a.TaskName -ErrorAction SilentlyContinue
            if ($task) {
                Start-ScheduledTask -TaskName $a.TaskName
                Write-Host "  Started $($a.Label)" -ForegroundColor Green
            } else {
                Write-Host "  $($a.Label): task not registered. Run deploy-agents.ps1 first." -ForegroundColor Yellow
            }
        }
    }

    "stop" {
        foreach ($name in $targets) {
            $a = $agents[$name]
            # Stop scheduled task
            Stop-ScheduledTask -TaskName $a.TaskName -ErrorAction SilentlyContinue

            # Kill process
            $proc = Get-AgentProcess $a.Script
            if ($proc) {
                $proc | Stop-Process -Force
                Write-Host "  Stopped $($a.Label) (PID $($proc.Id))" -ForegroundColor Yellow
            } else {
                Write-Host "  $($a.Label) was not running" -ForegroundColor DarkGray
            }
        }
    }

    "restart" {
        foreach ($name in $targets) {
            $a = $agents[$name]

            # Kill existing process
            $proc = Get-AgentProcess $a.Script
            if ($proc) { $proc | Stop-Process -Force }
            Stop-ScheduledTask -TaskName $a.TaskName -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 2

            # Start fresh
            $task = Get-ScheduledTask -TaskName $a.TaskName -ErrorAction SilentlyContinue
            if ($task) {
                Start-ScheduledTask -TaskName $a.TaskName
                Write-Host "  Restarted $($a.Label)" -ForegroundColor Green
            } else {
                Write-Host "  $($a.Label): task not registered" -ForegroundColor Yellow
            }
        }

        # Wait and show status
        Start-Sleep -Seconds 3
        & $MyInvocation.MyCommand.Path status $Agent
    }

    "logs" {
        foreach ($name in $targets) {
            $a = $agents[$name]
            $logPath = Join-Path $InstallDir "logs\$($a.LogFile)"
            if (Test-Path $logPath) {
                Write-Host ""
                Write-Host "  ═══ $($a.Label) — last 20 lines ═══" -ForegroundColor Cyan
                Get-Content $logPath -Tail 20
            } else {
                Write-Host "  $($a.Label): no log file found" -ForegroundColor Yellow
            }
        }
        Write-Host ""
    }

    "update" {
        Write-Host ""
        Write-Host "  Updating agent files..." -ForegroundColor Cyan

        $sourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path
        $updated = @()

        foreach ($name in $targets) {
            $a = $agents[$name]
            $src = Join-Path $sourceDir $a.Script
            $dst = Join-Path $InstallDir $a.Script

            if (Test-Path $src) {
                $srcHash = (Get-FileHash $src).Hash
                $dstHash = if (Test-Path $dst) { (Get-FileHash $dst).Hash } else { "" }

                if ($srcHash -ne $dstHash) {
                    Copy-Item $src $dst -Force
                    Write-Host "    Updated $($a.Script)" -ForegroundColor Green
                    $updated += $name
                } else {
                    Write-Host "    $($a.Script) already up to date" -ForegroundColor DarkGray
                }
            } else {
                Write-Host "    $($a.Script) not found in source" -ForegroundColor Yellow
            }
        }

        # Also update requirements.txt
        $reqSrc = Join-Path $sourceDir "requirements.txt"
        $reqDst = Join-Path $InstallDir "requirements.txt"
        if (Test-Path $reqSrc) {
            Copy-Item $reqSrc $reqDst -Force
            $pythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
            if ($pythonExe) {
                & $pythonExe -m pip install -r $reqDst --quiet --disable-pip-version-check 2>&1 | Out-Null
                Write-Host "    Dependencies updated" -ForegroundColor Green
            }
        }

        # Restart updated agents
        if ($updated.Count -gt 0) {
            Write-Host ""
            Write-Host "  Restarting updated agents..." -ForegroundColor Cyan
            foreach ($name in $updated) {
                $a = $agents[$name]
                $proc = Get-AgentProcess $a.Script
                if ($proc) { $proc | Stop-Process -Force }
                Stop-ScheduledTask -TaskName $a.TaskName -ErrorAction SilentlyContinue
                Start-Sleep 2
                Start-ScheduledTask -TaskName $a.TaskName -ErrorAction SilentlyContinue
                Write-Host "    Restarted $($a.Label)" -ForegroundColor Green
            }
        }
        Write-Host ""
    }

    "test" {
        foreach ($name in $targets) {
            if ($name -eq "camera") {
                Write-Host ""
                Write-Host "  Testing cameras..." -ForegroundColor Cyan
                Push-Location $InstallDir
                $pythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
                & $pythonExe camera_agent.py --test
                Pop-Location
            }
            if ($name -eq "scale") {
                Write-Host ""
                Write-Host "  Scale test: checking COM port..." -ForegroundColor Cyan
                $ports = [System.IO.Ports.SerialPort]::GetPortNames()
                Write-Host "  Available ports: $($ports -join ', ')" -ForegroundColor White
                try {
                    $resp = Invoke-WebRequest -Uri "http://localhost:9002" -TimeoutSec 3 -ErrorAction Stop
                    $data = $resp.Content | ConvertFrom-Json
                    Write-Host "  Scale status: $($data.status)" -ForegroundColor Green
                    Write-Host "  Last weight:  $($data.last_weight_kg) kg" -ForegroundColor Green
                } catch {
                    Write-Host "  Scale agent not responding on port 9002" -ForegroundColor Red
                }
            }
        }
        Write-Host ""
    }
}
