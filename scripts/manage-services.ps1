#Requires -RunAsAdministrator
<#
.SYNOPSIS
  Weighbridge Service Manager — start, stop, restart, status, logs.

.EXAMPLE
  # Show status of both services
  .\manage-services.ps1 status

  # Start both services
  .\manage-services.ps1 start

  # Stop both services
  .\manage-services.ps1 stop

  # Restart backend only (after code update)
  .\manage-services.ps1 restart backend

  # Tail backend log in real time
  .\manage-services.ps1 logs backend

  # Tail frontend log
  .\manage-services.ps1 logs frontend
#>

param(
    [Parameter(Position=0)]
    [ValidateSet("start","stop","restart","status","logs")]
    [string]$Action = "status",

    [Parameter(Position=1)]
    [ValidateSet("all","backend","frontend","")]
    [string]$Target = "all"
)

$SvcBackend  = "WeighbridgeBackend"
$SvcFrontend = "WeighbridgeFrontend"
$ProjectDir  = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$LogDir      = Join-Path $ProjectDir "logs"

function Get-Nssm {
    $candidates = @(
        "nssm",
        "C:\nssm\nssm.exe",
        (Join-Path $ProjectDir "tools\nssm.exe")
    )
    foreach ($c in $candidates) {
        $cmd = Get-Command $c -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    return $null
}

function Show-Status {
    Write-Host ""
    Write-Host "  Weighbridge Service Status" -ForegroundColor Cyan
    Write-Host "  --------------------------"
    foreach ($name in @($SvcBackend, $SvcFrontend)) {
        $svc = Get-Service -Name $name -ErrorAction SilentlyContinue
        if ($svc) {
            $color = if ($svc.Status -eq "Running") { "Green" } else { "Red" }
            Write-Host ("  {0,-28} {1}" -f $name, $svc.Status) -ForegroundColor $color
        } else {
            Write-Host ("  {0,-28} NOT INSTALLED" -f $name) -ForegroundColor DarkGray
        }
    }
    Write-Host ""
    Write-Host "  Backend  : http://localhost:9001"
    Write-Host "  Frontend : http://localhost:9000"
    Write-Host ""
}

function Start-Svc([string]$Name) {
    $svc = Get-Service -Name $Name -ErrorAction SilentlyContinue
    if (-not $svc) { Write-Host "  Service not found: $Name" -ForegroundColor Red; return }
    if ($svc.Status -eq "Running") {
        Write-Host "  $Name already running." -ForegroundColor Green
        return
    }
    Write-Host "  Starting $Name..." -NoNewline
    $nssm = Get-Nssm
    if ($nssm) { & $nssm start $Name | Out-Null } else { Start-Service $Name }
    Start-Sleep 3
    $svc = Get-Service -Name $Name
    $c = if ($svc.Status -eq "Running") { "Green" } else { "Red" }
    Write-Host " $($svc.Status)" -ForegroundColor $c
}

function Stop-Svc([string]$Name) {
    $svc = Get-Service -Name $Name -ErrorAction SilentlyContinue
    if (-not $svc) { Write-Host "  Service not found: $Name" -ForegroundColor Red; return }
    Write-Host "  Stopping $Name..." -NoNewline
    $nssm = Get-Nssm
    if ($nssm) { & $nssm stop $Name | Out-Null } else { Stop-Service $Name -Force }
    Start-Sleep 2
    $svc = Get-Service -Name $Name
    $c = if ($svc.Status -eq "Stopped") { "Green" } else { "Yellow" }
    Write-Host " $($svc.Status)" -ForegroundColor $c
}

function Show-Logs([string]$Which) {
    $logFile = switch ($Which) {
        "backend"  { Join-Path $LogDir "backend_stderr.log" }
        "frontend" { Join-Path $LogDir "frontend_stderr.log" }
        default    { Join-Path $LogDir "backend_stderr.log" }
    }
    if (-not (Test-Path $logFile)) {
        Write-Host "  Log not found: $logFile" -ForegroundColor Yellow
        Write-Host "  (Service may not have written any output yet)"
        return
    }
    Write-Host "  Tailing: $logFile  (Ctrl+C to stop)" -ForegroundColor Cyan
    Write-Host ""
    Get-Content $logFile -Wait -Tail 40
}

# ── Determine target services ─────────────────────────────────────────────────
$services = switch ($Target) {
    "backend"  { @($SvcBackend) }
    "frontend" { @($SvcFrontend) }
    default    { @($SvcBackend, $SvcFrontend) }
}

# ── Execute action ────────────────────────────────────────────────────────────
switch ($Action) {
    "status" {
        Show-Status
    }
    "start" {
        Write-Host ""
        foreach ($s in $services) { Start-Svc $s }
        Write-Host ""
    }
    "stop" {
        Write-Host ""
        foreach ($s in ($services | Sort-Object -Descending)) { Stop-Svc $s }
        Write-Host ""
    }
    "restart" {
        Write-Host ""
        foreach ($s in ($services | Sort-Object -Descending)) { Stop-Svc $s }
        Start-Sleep 2
        foreach ($s in $services) { Start-Svc $s }
        Write-Host ""
    }
    "logs" {
        $logTarget = if ($Target -eq "all") { "backend" } else { $Target }
        Show-Logs $logTarget
    }
}
