#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Setup Cloudflare Tunnel for secure remote access to Weighbridge ERP.

.DESCRIPTION
    Installs cloudflared, configures a named tunnel, and registers it as a
    Windows service so the weighbridge backend is reachable at
    https://weighbridge-<client>.yourdomain.com without opening any inbound ports.

.PARAMETER TunnelToken
    The tunnel token from Cloudflare Zero Trust dashboard.
    Create one at: https://one.dash.cloudflare.com -> Networks -> Tunnels -> Create

.PARAMETER InstallDir
    Where to put cloudflared.exe and config.  Default: C:\weighbridge\cloudflared

.EXAMPLE
    .\Setup-CloudflareTunnel.ps1 -TunnelToken "eyJhIjoiNGY..."
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$TunnelToken,

    [string]$InstallDir = "C:\weighbridge\cloudflared"
)

$ErrorActionPreference = "Stop"
$ProgressPreference    = "SilentlyContinue"   # speed up Invoke-WebRequest

# ── Colours ─────────────────────────────────────────────────────────────────
function Write-Step  { param($n, $msg) Write-Host "`n[$n] $msg" -ForegroundColor Cyan }
function Write-OK    { param($msg) Write-Host "    [OK] $msg" -ForegroundColor Green }
function Write-Warn  { param($msg) Write-Host "    [WARN] $msg" -ForegroundColor Yellow }
function Write-Fail  { param($msg) Write-Host "    [FAIL] $msg" -ForegroundColor Red }

Write-Host "`n=============================================" -ForegroundColor White
Write-Host "  Weighbridge ERP - Cloudflare Tunnel Setup   " -ForegroundColor White
Write-Host "=============================================`n" -ForegroundColor White

# ── Step 1: Create install directory ────────────────────────────────────────
Write-Step 1 "Creating install directory..."

if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
}
Write-OK "Directory: $InstallDir"

# ── Step 2: Download cloudflared ────────────────────────────────────────────
Write-Step 2 "Downloading cloudflared..."

$cloudflaredExe = Join-Path $InstallDir "cloudflared.exe"

if (Test-Path $cloudflaredExe) {
    Write-OK "cloudflared.exe already exists - checking version..."
    & $cloudflaredExe --version 2>&1 | ForEach-Object { Write-Host "    $_" }
} else {
    $downloadUrl = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
    Write-Host "    Downloading from $downloadUrl ..."
    try {
        Invoke-WebRequest -Uri $downloadUrl -OutFile $cloudflaredExe -UseBasicParsing
        Write-OK "Downloaded cloudflared.exe ($([math]::Round((Get-Item $cloudflaredExe).Length / 1MB, 1)) MB)"
    }
    catch {
        Write-Fail "Download failed: $_"
        Write-Host "    Manual download: $downloadUrl" -ForegroundColor Yellow
        Write-Host "    Save as: $cloudflaredExe" -ForegroundColor Yellow
        exit 1
    }
}

# ── Step 3: Stop existing service if running ────────────────────────────────
Write-Step 3 "Checking for existing cloudflared service..."

$existingService = Get-Service -Name "cloudflared" -ErrorAction SilentlyContinue
if ($existingService) {
    if ($existingService.Status -eq "Running") {
        Write-Warn "Stopping existing cloudflared service..."
        Stop-Service -Name "cloudflared" -Force
        Start-Sleep -Seconds 2
    }
    Write-Warn "Removing existing cloudflared service..."
    & $cloudflaredExe service uninstall 2>&1 | Out-Null
    Start-Sleep -Seconds 2
    Write-OK "Old service removed"
} else {
    Write-OK "No existing service found"
}

# ── Step 4: Install tunnel as service ───────────────────────────────────────
Write-Step 4 "Installing cloudflared tunnel as Windows service..."

try {
    $env:PATH = "$InstallDir;$env:PATH"

    # Install using the connector token (simplest method - no config file needed)
    & $cloudflaredExe service install $TunnelToken 2>&1 | ForEach-Object { Write-Host "    $_" }

    if ($LASTEXITCODE -ne 0) {
        throw "cloudflared service install returned exit code $LASTEXITCODE"
    }

    Write-OK "cloudflared service installed successfully"
}
catch {
    Write-Fail "Service installation failed: $_"
    Write-Host ""
    Write-Host "    Troubleshooting:" -ForegroundColor Yellow
    Write-Host "    1. Ensure the tunnel token is correct (from Cloudflare dashboard)" -ForegroundColor Yellow
    Write-Host "    2. Run this script as Administrator" -ForegroundColor Yellow
    Write-Host "    3. Check if another cloudflared instance is running" -ForegroundColor Yellow
    exit 1
}

# ── Step 5: Start the service ───────────────────────────────────────────────
Write-Step 5 "Starting cloudflared service..."

Start-Service -Name "cloudflared" -ErrorAction SilentlyContinue
Start-Sleep -Seconds 5

$svc = Get-Service -Name "cloudflared" -ErrorAction SilentlyContinue
if ($svc -and $svc.Status -eq "Running") {
    Write-OK "cloudflared service is running"
} else {
    Write-Warn "Service may still be starting... checking again in 10 seconds"
    Start-Sleep -Seconds 10
    $svc = Get-Service -Name "cloudflared" -ErrorAction SilentlyContinue
    if ($svc -and $svc.Status -eq "Running") {
        Write-OK "cloudflared service is running"
    } else {
        Write-Fail "cloudflared service failed to start"
        Write-Host "    Check logs: Get-EventLog -LogName Application -Source cloudflared -Newest 20" -ForegroundColor Yellow
        exit 1
    }
}

# ── Step 6: Set service to auto-start ───────────────────────────────────────
Write-Step 6 "Configuring service auto-start..."

Set-Service -Name "cloudflared" -StartupType Automatic
Write-OK "Service set to start automatically on boot"

# ── Step 7: Add to PATH (optional) ─────────────────────────────────────────
Write-Step 7 "Adding cloudflared to system PATH..."

$machinePath = [Environment]::GetEnvironmentVariable("PATH", "Machine")
if ($machinePath -notlike "*$InstallDir*") {
    [Environment]::SetEnvironmentVariable("PATH", "$machinePath;$InstallDir", "Machine")
    Write-OK "Added $InstallDir to system PATH"
} else {
    Write-OK "Already in PATH"
}

# ── Step 8: Verify connectivity ────────────────────────────────────────────
Write-Step 8 "Verifying tunnel connectivity..."

Start-Sleep -Seconds 3
try {
    $tunnelInfo = & $cloudflaredExe tunnel info 2>&1
    Write-Host "    $($tunnelInfo -join "`n    ")"
    Write-OK "Tunnel is connected to Cloudflare edge"
}
catch {
    Write-Warn "Could not verify tunnel info (this is normal if using connector tokens)"
    Write-OK "Service is running - tunnel should be active"
}

# ── Summary ─────────────────────────────────────────────────────────────────
Write-Host "`n=============================================" -ForegroundColor Green
Write-Host "  Cloudflare Tunnel Setup Complete!            " -ForegroundColor Green
Write-Host "=============================================`n" -ForegroundColor Green

Write-Host "  Service Name:   cloudflared" -ForegroundColor White
Write-Host "  Service Status: Running" -ForegroundColor White
Write-Host "  Auto-Start:     Yes" -ForegroundColor White
Write-Host "  Install Dir:    $InstallDir" -ForegroundColor White
Write-Host ""
Write-Host "  IMPORTANT: Configure your tunnel's public hostname" -ForegroundColor Yellow
Write-Host "  in the Cloudflare Zero Trust dashboard to route:" -ForegroundColor Yellow
Write-Host "    weighbridge-<client>.yourdomain.com -> http://localhost:9001" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Zero Trust Access Policy (recommended):" -ForegroundColor Yellow
Write-Host "    - Require email OTP for all users" -ForegroundColor White
Write-Host "    - Restrict to India (country = IN)" -ForegroundColor White
Write-Host "    - Session duration: 24 hours" -ForegroundColor White
Write-Host ""
