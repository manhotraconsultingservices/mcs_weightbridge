#Requires -Version 5.0
<#
.SYNOPSIS
    Weighbridge ERP — Hardware Fingerprint Capture Tool

.DESCRIPTION
    Collects the 4 hardware identifiers (CPU, Motherboard, Disk, Windows Product ID)
    and saves fingerprint.json to your Desktop.

    Send the resulting fingerprint.json file to your vendor to receive your license key.

    This script does NOT require Python. Run it BEFORE calling the vendor.

.EXAMPLE
    Right-click this file → Run with PowerShell
#>

$ErrorActionPreference = "SilentlyContinue"

Clear-Host
Write-Host ""
Write-Host "  +----------------------------------------------------------+" -ForegroundColor Cyan
Write-Host "  |      Weighbridge ERP — Hardware Fingerprint Capture      |" -ForegroundColor Cyan
Write-Host "  |                  Vendor Licensing Tool                   |" -ForegroundColor Cyan
Write-Host "  +----------------------------------------------------------+" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Collecting hardware information. Please wait..." -ForegroundColor Gray
Write-Host ""

# ── Helper: SHA-256 hex of a string ──────────────────────────────────────────

function Get-Sha256 {
    param([string]$Value)
    if ([string]::IsNullOrEmpty($Value)) { return "" }
    $sha    = [System.Security.Cryptography.SHA256]::Create()
    $bytes  = [System.Text.Encoding]::UTF8.GetBytes($Value)
    $hash   = $sha.ComputeHash($bytes)
    $sha.Dispose()
    return ($hash | ForEach-Object { '{0:x2}' -f $_ }) -join ''
}

# ── Collect 4 hardware factors ────────────────────────────────────────────────

# 1. CPU ProcessorId
$cpuRaw = ""
try {
    $cpu    = Get-CimInstance -ClassName Win32_Processor -ErrorAction Stop | Select-Object -First 1
    $cpuRaw = $cpu.ProcessorId.Trim()
} catch { }

# Fallback to wmic if CIM fails
if ([string]::IsNullOrEmpty($cpuRaw)) {
    try {
        $wmicOut = (cmd /c "wmic cpu get ProcessorId /value" 2>$null) -join "`n"
        $cpuRaw  = ($wmicOut -split "`n" | Where-Object { $_ -match "=" } |
                    ForEach-Object { ($_ -split "=", 2)[1].Trim() } |
                    Where-Object { $_ -ne "" } | Select-Object -First 1)
    } catch { }
}

# 2. Motherboard SerialNumber
$mbRaw = ""
try {
    $mb    = Get-CimInstance -ClassName Win32_BaseBoard -ErrorAction Stop | Select-Object -First 1
    $mbRaw = $mb.SerialNumber.Trim()
} catch { }

if ([string]::IsNullOrEmpty($mbRaw)) {
    try {
        $wmicOut = (cmd /c "wmic baseboard get SerialNumber /value" 2>$null) -join "`n"
        $mbRaw   = ($wmicOut -split "`n" | Where-Object { $_ -match "=" } |
                    ForEach-Object { ($_ -split "=", 2)[1].Trim() } |
                    Where-Object { $_ -ne "" } | Select-Object -First 1)
    } catch { }
}

# 3. Disk SerialNumber
$diskRaw = ""
try {
    $disk    = Get-CimInstance -ClassName Win32_DiskDrive -ErrorAction Stop | Select-Object -First 1
    $diskRaw = $disk.SerialNumber.Trim()
} catch { }

if ([string]::IsNullOrEmpty($diskRaw)) {
    try {
        $wmicOut  = (cmd /c "wmic diskdrive get SerialNumber /value" 2>$null) -join "`n"
        $diskRaw  = ($wmicOut -split "`n" | Where-Object { $_ -match "=" } |
                     ForEach-Object { ($_ -split "=", 2)[1].Trim() } |
                     Where-Object { $_ -ne "" } | Select-Object -First 1)
    } catch { }
}

# 4. Windows Product ID (unique per Windows installation)
$winprodRaw = ""
try {
    $regPath    = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion"
    $winprodRaw = (Get-ItemProperty -Path $regPath -Name "ProductId" -ErrorAction Stop).ProductId.Trim()
} catch { }

# ── Hostname ──────────────────────────────────────────────────────────────────

$hostname = $env:COMPUTERNAME.ToUpper()

# ── Compute SHA-256 hashes ────────────────────────────────────────────────────

$factorHashes = @{
    cpu     = Get-Sha256 $cpuRaw
    mb      = Get-Sha256 $mbRaw
    disk    = Get-Sha256 $diskRaw
    winprod = Get-Sha256 $winprodRaw
}

# Full fingerprint: SHA-256 of the canonical factor string
$anyValue = $cpuRaw -or $mbRaw -or $diskRaw -or $winprodRaw

if ($anyValue) {
    $canonical  = "CPU:${cpuRaw}|MB:${mbRaw}|DISK:${diskRaw}|WIN:${winprodRaw}"
    $hwFingerprint = Get-Sha256 $canonical
} else {
    $hwFingerprint = "NO_HW_INFO"
    Write-Host "  WARNING: Could not read hardware identifiers." -ForegroundColor Yellow
    Write-Host "  The license will be bound by hostname only.  " -ForegroundColor Yellow
    Write-Host ""
}

# ── Build output payload ──────────────────────────────────────────────────────

$payload = [ordered]@{
    hostname             = $hostname
    hardware_fingerprint = $hwFingerprint
    factor_hashes        = [ordered]@{
        cpu     = $factorHashes.cpu
        mb      = $factorHashes.mb
        disk    = $factorHashes.disk
        winprod = $factorHashes.winprod
    }
}

# ── Save to Desktop ──────────────────────────────────────────────────────────

$desktopPath   = [System.Environment]::GetFolderPath("Desktop")
$outputFile    = Join-Path $desktopPath "fingerprint.json"

$jsonText = $payload | ConvertTo-Json -Depth 5
$jsonText | Out-File -FilePath $outputFile -Encoding UTF8 -NoNewline

# ── Display results ──────────────────────────────────────────────────────────

Write-Host "  Hardware Factors Collected:" -ForegroundColor White
Write-Host "  ----------------------------" -ForegroundColor Gray
Write-Host ("  Hostname     : " + $hostname) -ForegroundColor Gray
Write-Host ("  CPU ID       : " + $(if ($cpuRaw) { $cpuRaw } else { "(not found)" })) -ForegroundColor Gray
Write-Host ("  Motherboard  : " + $(if ($mbRaw) { $mbRaw } else { "(not found)" })) -ForegroundColor Gray
Write-Host ("  Disk Serial  : " + $(if ($diskRaw) { $diskRaw } else { "(not found)" })) -ForegroundColor Gray
Write-Host ("  Windows ID   : " + $(if ($winprodRaw) { $winprodRaw } else { "(not found)" })) -ForegroundColor Gray
Write-Host ""
Write-Host ("  Fingerprint  : " + $hwFingerprint.Substring(0, [Math]::Min(32, $hwFingerprint.Length)) + "...") -ForegroundColor Green
Write-Host ""

Write-Host "  +---------------------------------------------------------+" -ForegroundColor Green
Write-Host "  |                   FILE SAVED                            |" -ForegroundColor Green
Write-Host ("  |  " + $outputFile.PadRight(55) + "  |") -ForegroundColor Green
Write-Host "  +---------------------------------------------------------+" -ForegroundColor Green
Write-Host ""
Write-Host "  NEXT STEP:" -ForegroundColor Yellow
Write-Host "  Send 'fingerprint.json' from your Desktop to your vendor" -ForegroundColor Yellow
Write-Host "  via WhatsApp or email. The vendor will generate your" -ForegroundColor Yellow
Write-Host "  license.key and send it back." -ForegroundColor Yellow
Write-Host ""

# Open the Desktop folder so the user can easily find the file
try {
    Start-Process "explorer.exe" $desktopPath
} catch { }

Write-Host "  (The Desktop folder has been opened for you.)" -ForegroundColor Gray
Write-Host ""
Read-Host "  Press ENTER to close this window"
