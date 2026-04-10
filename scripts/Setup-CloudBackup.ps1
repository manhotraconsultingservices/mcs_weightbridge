#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Setup automated encrypted cloud backup to Cloudflare R2.

.DESCRIPTION
    Installs rclone, configures R2 credentials, creates config file,
    and registers a Windows scheduled task for daily backups at 2 AM.

.PARAMETER R2AccessKey
    Cloudflare R2 Access Key ID (from API Tokens in Cloudflare dashboard)

.PARAMETER R2SecretKey
    Cloudflare R2 Secret Access Key

.PARAMETER R2AccountId
    Cloudflare Account ID (from Overview page)

.PARAMETER R2Bucket
    R2 bucket name. Default: weighbridge-backups

.PARAMETER ClientId
    Client identifier (e.g., shreeram-crusher). Used as folder prefix in R2.

.PARAMETER EncryptionKey
    Passphrase for AES-256 encryption of backup files.
    If not provided, reads PRIVATE_DATA_KEY from secrets.

.PARAMETER TelegramBotToken
    Optional. Telegram bot token for backup notifications.

.PARAMETER TelegramChatId
    Optional. Telegram chat ID for backup notifications.

.EXAMPLE
    .\Setup-CloudBackup.ps1 -R2AccessKey "abc123" -R2SecretKey "xyz789" `
        -R2AccountId "1234abcd" -ClientId "shreeram-crusher"
#>

param(
    [Parameter(Mandatory = $true)]  [string]$R2AccessKey,
    [Parameter(Mandatory = $true)]  [string]$R2SecretKey,
    [Parameter(Mandatory = $true)]  [string]$R2AccountId,
    [Parameter(Mandatory = $true)]  [string]$ClientId,
    [string]$R2Bucket          = "weighbridge-backups",
    [string]$EncryptionKey     = "",
    [string]$DbPassword        = "",
    [string]$TelegramBotToken  = "",
    [string]$TelegramChatId    = ""
)

$ErrorActionPreference = "Stop"
$ProgressPreference    = "SilentlyContinue"

$WeighbridgeDir = "C:\weighbridge"
$ToolsDir       = Join-Path $WeighbridgeDir "tools"
$RcloneExe      = Join-Path $ToolsDir "rclone.exe"
$ConfigFile     = Join-Path $WeighbridgeDir "cloud-backup-config.json"
$RcloneConf     = Join-Path $ToolsDir "rclone.conf"

function Write-Step  { param($n, $msg) Write-Host "`n[$n] $msg" -ForegroundColor Cyan }
function Write-OK    { param($msg) Write-Host "    [OK] $msg" -ForegroundColor Green }
function Write-Fail  { param($msg) Write-Host "    [FAIL] $msg" -ForegroundColor Red }

Write-Host "`n=============================================" -ForegroundColor White
Write-Host "  Weighbridge ERP - Cloud Backup Setup        " -ForegroundColor White
Write-Host "=============================================`n" -ForegroundColor White

# ── Step 1: Create directories ──────────────────────────────────────────────
Write-Step 1 "Creating directories..."
@($ToolsDir, (Join-Path $WeighbridgeDir "backups"), (Join-Path $WeighbridgeDir "logs")) | ForEach-Object {
    if (-not (Test-Path $_)) { New-Item -ItemType Directory -Path $_ -Force | Out-Null }
}
Write-OK "Directories ready"

# ── Step 2: Download rclone ─────────────────────────────────────────────────
Write-Step 2 "Installing rclone..."

if (Test-Path $RcloneExe) {
    Write-OK "rclone already installed"
    & $RcloneExe --version 2>&1 | Select-Object -First 1 | ForEach-Object { Write-Host "    $_" }
} else {
    $rcloneUrl = "https://downloads.rclone.org/rclone-current-windows-amd64.zip"
    $zipFile   = Join-Path $env:TEMP "rclone.zip"
    $extractDir = Join-Path $env:TEMP "rclone-extract"

    Write-Host "    Downloading rclone..."
    Invoke-WebRequest -Uri $rcloneUrl -OutFile $zipFile -UseBasicParsing
    Expand-Archive -Path $zipFile -DestinationPath $extractDir -Force

    $rcloneBin = Get-ChildItem -Path $extractDir -Filter "rclone.exe" -Recurse | Select-Object -First 1
    if (-not $rcloneBin) { throw "Could not find rclone.exe in downloaded archive" }

    Copy-Item $rcloneBin.FullName $RcloneExe -Force
    Remove-Item $zipFile -Force -ErrorAction SilentlyContinue
    Remove-Item $extractDir -Recurse -Force -ErrorAction SilentlyContinue

    Write-OK "rclone installed at $RcloneExe"
}

# ── Step 3: Configure rclone for R2 ────────────────────────────────────────
Write-Step 3 "Configuring rclone for Cloudflare R2..."

$rcloneConfig = @"
[weighbridge-r2]
type = s3
provider = Cloudflare
access_key_id = $R2AccessKey
secret_access_key = $R2SecretKey
endpoint = https://${R2AccountId}.r2.cloudflarestorage.com
acl = private
no_check_bucket = true
"@

Set-Content -Path $RcloneConf -Value $rcloneConfig -Encoding UTF8
Write-OK "rclone config written to $RcloneConf"

# ── Step 4: Test R2 connectivity ────────────────────────────────────────────
Write-Step 4 "Testing R2 connectivity..."

$env:RCLONE_CONFIG = $RcloneConf
& $RcloneExe lsd "weighbridge-r2:${R2Bucket}" 2>&1 | ForEach-Object { Write-Host "    $_" }

if ($LASTEXITCODE -ne 0) {
    Write-Host "    Bucket may not exist yet - creating..." -ForegroundColor Yellow
    & $RcloneExe mkdir "weighbridge-r2:${R2Bucket}" 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-OK "Bucket created: $R2Bucket"
    } else {
        Write-Fail "Could not create bucket. Check credentials and account ID."
        exit 1
    }
} else {
    Write-OK "R2 connectivity confirmed"
}

# ── Step 5: Generate backup config ──────────────────────────────────────────
Write-Step 5 "Generating backup configuration..."

# Auto-detect encryption key from .env or secrets
if (-not $EncryptionKey) {
    $envFile = Join-Path $WeighbridgeDir "backend\.env"
    if (Test-Path $envFile) {
        $envContent = Get-Content $envFile
        $match = $envContent | Where-Object { $_ -match "^PRIVATE_DATA_KEY=(.+)$" }
        if ($match) { $EncryptionKey = $Matches[1] }
    }
}
if (-not $EncryptionKey) {
    $EncryptionKey = -join ((65..90) + (97..122) + (48..57) | Get-Random -Count 32 | ForEach-Object { [char]$_ })
    Write-Host "    Generated random encryption key" -ForegroundColor Yellow
}

# Auto-detect DB password
if (-not $DbPassword) {
    $envFile = Join-Path $WeighbridgeDir "backend\.env"
    if (Test-Path $envFile) {
        $envContent = Get-Content $envFile
        $match = $envContent | Where-Object { $_ -match "^DATABASE_URL=.*:(.+)@" }
        if ($match) { $DbPassword = $Matches[1] }
    }
}
if (-not $DbPassword) { $DbPassword = "weighbridge_dev_2024" }

$configData = @{
    client_id           = $ClientId
    r2_remote           = "weighbridge-r2"
    r2_bucket           = $R2Bucket
    encryption_key      = $EncryptionKey
    db_host             = "localhost"
    db_port             = "5432"
    db_name             = "weighbridge"
    db_user             = "weighbridge"
    db_password         = $DbPassword
    telegram_bot_token  = $TelegramBotToken
    telegram_chat_id    = $TelegramChatId
    local_retain_days   = 7
    remote_retain_days  = 90
}

$configData | ConvertTo-Json -Depth 5 | Set-Content -Path $ConfigFile -Encoding UTF8

# Lock config file permissions (only Administrators + SYSTEM)
$acl = Get-Acl $ConfigFile
$acl.SetAccessRuleProtection($true, $false)
$adminRule  = New-Object System.Security.AccessControl.FileSystemAccessRule("BUILTIN\Administrators", "FullControl", "Allow")
$systemRule = New-Object System.Security.AccessControl.FileSystemAccessRule("NT AUTHORITY\SYSTEM", "FullControl", "Allow")
$acl.AddAccessRule($adminRule)
$acl.AddAccessRule($systemRule)
Set-Acl $ConfigFile $acl

Write-OK "Config written to $ConfigFile (ACL locked)"

# ── Step 6: Register scheduled task ─────────────────────────────────────────
Write-Step 6 "Creating scheduled task for daily backup at 2:00 AM..."

$taskName   = "WeighbridgeCloudBackup"
$scriptPath = Join-Path (Split-Path $PSScriptRoot) "scripts\Backup-ToCloud.ps1"
if (-not (Test-Path $scriptPath)) {
    # Try current directory
    $scriptPath = Join-Path $PSScriptRoot "Backup-ToCloud.ps1"
}

# Remove existing task
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

$action  = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`" -ConfigFile `"$ConfigFile`""

$trigger = New-ScheduledTaskTrigger -Daily -At "02:00AM"

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Weighbridge ERP - Daily encrypted database backup to Cloudflare R2" | Out-Null

Write-OK "Scheduled task '$taskName' created (daily at 2:00 AM)"

# ── Step 7: Run initial test backup ─────────────────────────────────────────
Write-Step 7 "Running initial test backup..."

try {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $scriptPath -ConfigFile $ConfigFile
    if ($LASTEXITCODE -eq 0) {
        Write-OK "Initial backup completed successfully!"
    } else {
        Write-Fail "Initial backup failed (exit code $LASTEXITCODE)"
        Write-Host "    Check log: C:\weighbridge\logs\cloud-backup.log" -ForegroundColor Yellow
    }
}
catch {
    Write-Fail "Initial backup error: $_"
    Write-Host "    This may be expected if the database is not running yet." -ForegroundColor Yellow
    Write-Host "    The scheduled task will retry tomorrow at 2 AM." -ForegroundColor Yellow
}

# ── Summary ─────────────────────────────────────────────────────────────────
Write-Host "`n=============================================" -ForegroundColor Green
Write-Host "  Cloud Backup Setup Complete!                 " -ForegroundColor Green
Write-Host "=============================================`n" -ForegroundColor Green

Write-Host "  Backup Schedule:   Daily at 2:00 AM" -ForegroundColor White
Write-Host "  Storage:           Cloudflare R2 ($R2Bucket)" -ForegroundColor White
Write-Host "  Client Folder:     $ClientId/" -ForegroundColor White
Write-Host "  Encryption:        AES-256" -ForegroundColor White
Write-Host "  Local Retention:   $($configData.local_retain_days) days" -ForegroundColor White
Write-Host "  Remote Retention:  $($configData.remote_retain_days) days" -ForegroundColor White
Write-Host "  Telegram Alerts:   $(if($TelegramBotToken){'Enabled'}else{'Disabled'})" -ForegroundColor White
Write-Host ""
Write-Host "  Config:  $ConfigFile" -ForegroundColor Cyan
Write-Host "  Log:     C:\weighbridge\logs\cloud-backup.log" -ForegroundColor Cyan
Write-Host "  Status:  C:\weighbridge\backup-status.json" -ForegroundColor Cyan
Write-Host ""
