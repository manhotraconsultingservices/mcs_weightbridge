<#
.SYNOPSIS
    Post-deployment verification checklist for Weighbridge ERP.

.DESCRIPTION
    Checks all services, security layers, connectivity, and backup status.
    Outputs a color-coded report and optionally saves to a JSON file.

.PARAMETER PublicUrl
    The public Cloudflare Tunnel URL (e.g., https://weighbridge-shreeram.yourdomain.com)

.PARAMETER OutputFile
    Save verification report to JSON file. Default: C:\weighbridge\deployment-report.json
#>

param(
    [string]$PublicUrl  = "",
    [string]$OutputFile = "C:\weighbridge\deployment-report.json"
)

$ErrorActionPreference = "Continue"
$WeighbridgeDir = "C:\weighbridge"

$checks  = @()
$passed  = 0
$failed  = 0
$warned  = 0

function Add-Check {
    param($Category, $Name, $Status, $Detail)
    $script:checks += @{ category = $Category; name = $Name; status = $Status; detail = $Detail }
    $icon = switch ($Status) { "PASS" { "[OK]" } "FAIL" { "[FAIL]" } "WARN" { "[WARN]" } }
    $color = switch ($Status) { "PASS" { "Green" } "FAIL" { "Red" } "WARN" { "Yellow" } }
    Write-Host "  $icon $Name" -ForegroundColor $color -NoNewline
    if ($Detail) { Write-Host " — $Detail" -ForegroundColor Gray } else { Write-Host "" }
    switch ($Status) { "PASS" { $script:passed++ } "FAIL" { $script:failed++ } "WARN" { $script:warned++ } }
}

Write-Host "`n================================================" -ForegroundColor White
Write-Host "  Weighbridge ERP — Deployment Verification      " -ForegroundColor White
Write-Host "================================================`n" -ForegroundColor White

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 1: Windows Services
# ═══════════════════════════════════════════════════════════════════════════
Write-Host "Services" -ForegroundColor Cyan

$services = @(
    @{ Name = "WeighbridgeBackend";  Label = "Backend API" },
    @{ Name = "WeighbridgeFrontend"; Label = "Frontend Server" },
    @{ Name = "cloudflared";         Label = "Cloudflare Tunnel" }
)

foreach ($svc in $services) {
    $s = Get-Service -Name $svc.Name -ErrorAction SilentlyContinue
    if ($s -and $s.Status -eq "Running") {
        Add-Check "Services" $svc.Label "PASS" "Running (auto-start: $($s.StartType))"
    } elseif ($s) {
        Add-Check "Services" $svc.Label "FAIL" "Status: $($s.Status)"
    } else {
        Add-Check "Services" $svc.Label "FAIL" "Service not found"
    }
}

# PostgreSQL Docker
$pgDocker = docker ps --filter "name=weighbridge_db" --format "{{.Status}}" 2>$null
if ($pgDocker -match "Up") {
    Add-Check "Services" "PostgreSQL (Docker)" "PASS" $pgDocker
} else {
    # Try native PostgreSQL service
    $pgSvc = Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue | Where-Object Status -eq "Running"
    if ($pgSvc) {
        Add-Check "Services" "PostgreSQL (Native)" "PASS" "Running"
    } else {
        Add-Check "Services" "PostgreSQL" "FAIL" "Not running"
    }
}

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 2: Security
# ═══════════════════════════════════════════════════════════════════════════
Write-Host "`nSecurity" -ForegroundColor Cyan

# DPAPI secrets
$dpapiFile = Join-Path $WeighbridgeDir "backend\secrets.dpapi"
if (Test-Path $dpapiFile) {
    Add-Check "Security" "DPAPI Secrets" "PASS" "secrets.dpapi exists"
} else {
    Add-Check "Security" "DPAPI Secrets" "WARN" "Not configured (using .env file)"
}

# No plaintext .env
$envFile = Join-Path $WeighbridgeDir "backend\.env"
$envBak  = Join-Path $WeighbridgeDir "backend\.env.bak"
if (Test-Path $envBak) {
    Add-Check "Security" "No .env.bak on disk" "FAIL" ".env.bak still exists! Remove and store offline."
} else {
    Add-Check "Security" "No .env.bak on disk" "PASS" "Cleaned"
}

# License
$licFile = Get-ChildItem -Path $WeighbridgeDir -Filter "license.key" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
if ($licFile) {
    Add-Check "Security" "License Key" "PASS" $licFile.FullName
} else {
    Add-Check "Security" "License Key" "WARN" "license.key not found (may be dev mode)"
}

# BitLocker
try {
    $bl = Get-BitLockerVolume -MountPoint "C:" -ErrorAction SilentlyContinue
    if ($bl -and $bl.ProtectionStatus -eq "On") {
        Add-Check "Security" "BitLocker (C: drive)" "PASS" "Encrypted with $($bl.EncryptionMethod)"
    } else {
        Add-Check "Security" "BitLocker (C: drive)" "WARN" "Not enabled — data at risk if machine is stolen"
    }
} catch {
    Add-Check "Security" "BitLocker (C: drive)" "WARN" "Could not check (requires admin)"
}

# Firewall — PostgreSQL blocked externally
$pgRule = Get-NetFirewallRule -DisplayName "*PostgreSQL*" -ErrorAction SilentlyContinue |
          Where-Object { $_.Direction -eq "Inbound" -and $_.Action -eq "Block" }
if ($pgRule) {
    Add-Check "Security" "Firewall: PostgreSQL blocked" "PASS" "Port 5432 blocked externally"
} else {
    # Check if any rule exists for 5432
    $portRule = Get-NetFirewallPortFilter -Protocol TCP | Where-Object LocalPort -eq 5432
    if (-not $portRule) {
        Add-Check "Security" "Firewall: PostgreSQL" "WARN" "No explicit rule (Windows may block by default)"
    } else {
        Add-Check "Security" "Firewall: PostgreSQL" "WARN" "Port 5432 rule exists — verify it blocks external access"
    }
}

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 3: Connectivity
# ═══════════════════════════════════════════════════════════════════════════
Write-Host "`nConnectivity" -ForegroundColor Cyan

# Local backend
try {
    $r = Invoke-WebRequest -Uri "http://localhost:9001/api/v1/auth/me" -TimeoutSec 5 -UseBasicParsing -ErrorAction SilentlyContinue
    Add-Check "Connectivity" "Backend (localhost:9001)" "PASS" "HTTP $($r.StatusCode)"
} catch {
    if ($_.Exception.Response.StatusCode -eq 401 -or $_.Exception.Response.StatusCode -eq 403) {
        Add-Check "Connectivity" "Backend (localhost:9001)" "PASS" "HTTP 401/403 (auth required — expected)"
    } else {
        Add-Check "Connectivity" "Backend (localhost:9001)" "FAIL" "$($_.Exception.Message)"
    }
}

# Local frontend
try {
    $r = Invoke-WebRequest -Uri "http://localhost:9000" -TimeoutSec 5 -UseBasicParsing -ErrorAction SilentlyContinue
    Add-Check "Connectivity" "Frontend (localhost:9000)" "PASS" "HTTP $($r.StatusCode)"
} catch {
    if ($_.Exception.Response.StatusCode) {
        Add-Check "Connectivity" "Frontend (localhost:9000)" "PASS" "HTTP $($_.Exception.Response.StatusCode)"
    } else {
        Add-Check "Connectivity" "Frontend (localhost:9000)" "FAIL" "$($_.Exception.Message)"
    }
}

# Public URL (Cloudflare Tunnel)
if ($PublicUrl) {
    try {
        $r = Invoke-WebRequest -Uri $PublicUrl -TimeoutSec 10 -UseBasicParsing -MaximumRedirection 0 -ErrorAction SilentlyContinue
        Add-Check "Connectivity" "Public URL" "PASS" "HTTP $($r.StatusCode) — $PublicUrl"
    } catch {
        $code = $_.Exception.Response.StatusCode.value__
        if ($code -eq 302 -or $code -eq 303) {
            Add-Check "Connectivity" "Public URL" "PASS" "HTTP $code (Zero Trust redirect — expected)"
        } elseif ($code) {
            Add-Check "Connectivity" "Public URL" "PASS" "HTTP $code — $PublicUrl"
        } else {
            Add-Check "Connectivity" "Public URL" "FAIL" "Cannot reach $PublicUrl"
        }
    }
} else {
    Add-Check "Connectivity" "Public URL" "WARN" "Not provided (use -PublicUrl to test)"
}

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 4: Cloud Backup
# ═══════════════════════════════════════════════════════════════════════════
Write-Host "`nCloud Backup" -ForegroundColor Cyan

# Scheduled task
$task = Get-ScheduledTask -TaskName "WeighbridgeCloudBackup" -ErrorAction SilentlyContinue
if ($task) {
    $taskInfo = $task | Get-ScheduledTaskInfo -ErrorAction SilentlyContinue
    $lastRun  = if ($taskInfo.LastRunTime -and $taskInfo.LastRunTime -gt (Get-Date "2000-01-01")) {
        $taskInfo.LastRunTime.ToString("dd-MMM-yyyy HH:mm")
    } else { "Never" }
    Add-Check "Backup" "Scheduled Task" "PASS" "Exists (last run: $lastRun)"
} else {
    Add-Check "Backup" "Scheduled Task" "FAIL" "WeighbridgeCloudBackup task not found"
}

# rclone installed
$rcloneExe = Join-Path $WeighbridgeDir "tools\rclone.exe"
if (Test-Path $rcloneExe) {
    Add-Check "Backup" "rclone" "PASS" "Installed"
} else {
    Add-Check "Backup" "rclone" "FAIL" "Not found at $rcloneExe"
}

# Backup config
$backupConfig = Join-Path $WeighbridgeDir "cloud-backup-config.json"
if (Test-Path $backupConfig) {
    Add-Check "Backup" "Config File" "PASS" $backupConfig
} else {
    Add-Check "Backup" "Config File" "FAIL" "cloud-backup-config.json not found"
}

# Last backup status
$statusFile = Join-Path $WeighbridgeDir "backup-status.json"
if (Test-Path $statusFile) {
    $status = Get-Content $statusFile -Raw | ConvertFrom-Json
    if ($status.upload_success) {
        Add-Check "Backup" "Last Backup" "PASS" "$($status.last_backup_size) on $($status.last_backup)"
    } else {
        Add-Check "Backup" "Last Backup" "FAIL" "Error: $($status.error)"
    }
} else {
    Add-Check "Backup" "Last Backup" "WARN" "No backup has run yet"
}

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 5: Hardware
# ═══════════════════════════════════════════════════════════════════════════
Write-Host "`nHardware" -ForegroundColor Cyan

# Check COM ports
$ports = [System.IO.Ports.SerialPort]::GetPortNames()
if ($ports.Count -gt 0) {
    Add-Check "Hardware" "Serial Ports" "PASS" "Found: $($ports -join ', ')"
} else {
    Add-Check "Hardware" "Serial Ports" "WARN" "No COM ports detected (weight scale not connected?)"
}

# System info
$os  = Get-CimInstance Win32_OperatingSystem
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$ram = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
Add-Check "Hardware" "System" "PASS" "$($os.Caption), $($cpu.Name), $ram GB RAM"

# ═══════════════════════════════════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════════════════════════════════

$total = $passed + $failed + $warned

Write-Host "`n================================================" -ForegroundColor White
Write-Host "  RESULTS: $passed/$total passed" -NoNewline -ForegroundColor $(if ($failed -eq 0) { "Green" } else { "Red" })
if ($failed -gt 0) { Write-Host ", $failed failed" -NoNewline -ForegroundColor Red }
if ($warned -gt 0) { Write-Host ", $warned warnings" -NoNewline -ForegroundColor Yellow }
Write-Host ""
Write-Host "================================================`n" -ForegroundColor White

if ($failed -gt 0) {
    Write-Host "  ACTION REQUIRED: Fix the failed checks above before handover." -ForegroundColor Red
} elseif ($warned -gt 0) {
    Write-Host "  MOSTLY READY: Review warnings above." -ForegroundColor Yellow
} else {
    Write-Host "  ALL CLEAR: Deployment is fully verified!" -ForegroundColor Green
}

# Save report
$report = @{
    timestamp    = (Get-Date -Format "o")
    hostname     = $env:COMPUTERNAME
    public_url   = $PublicUrl
    total_checks = $total
    passed       = $passed
    failed       = $failed
    warnings     = $warned
    checks       = $checks
}

$report | ConvertTo-Json -Depth 5 | Set-Content -Path $OutputFile -Encoding UTF8
Write-Host "`n  Report saved: $OutputFile`n" -ForegroundColor Cyan
