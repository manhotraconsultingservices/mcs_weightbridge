<#
.SYNOPSIS
    Automated encrypted database backup to Cloudflare R2.

.DESCRIPTION
    Runs as a scheduled task (daily at 2 AM). Performs:
    1. pg_dump → compressed .sql.gz
    2. AES-256 encryption using OpenSSL
    3. Upload to Cloudflare R2 via rclone
    4. Prune local backups > 7 days
    5. Prune R2 backups > 90 days
    6. Send Telegram notification on success/failure
    7. Write status to backup-status.json for API endpoint

.PARAMETER ConfigFile
    Path to cloud backup config file. Default: C:\weighbridge\cloud-backup-config.json
#>

param(
    [string]$ConfigFile = "C:\weighbridge\cloud-backup-config.json"
)

$ErrorActionPreference = "Stop"

# ── Load configuration ──────────────────────────────────────────────────────
$WeighbridgeDir = "C:\weighbridge"
$BackupDir      = Join-Path $WeighbridgeDir "backups"
$LogFile        = Join-Path $WeighbridgeDir "logs\cloud-backup.log"
$StatusFile     = Join-Path $WeighbridgeDir "backup-status.json"
$RcloneExe      = Join-Path $WeighbridgeDir "tools\rclone.exe"
$Timestamp      = Get-Date -Format "yyyyMMdd_HHmmss"

function Write-Log {
    param($Message, [switch]$Error)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] $Message"
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
    if ($Error) { Write-Host $line -ForegroundColor Red }
    else        { Write-Host $line }
}

# Ensure directories exist
@($BackupDir, (Split-Path $LogFile)) | ForEach-Object {
    if (-not (Test-Path $_)) { New-Item -ItemType Directory -Path $_ -Force | Out-Null }
}

Write-Log "=== Cloud Backup Started ==="

# Load config
if (-not (Test-Path $ConfigFile)) {
    Write-Log "Config file not found: $ConfigFile" -Error
    exit 1
}

$config = Get-Content $ConfigFile -Raw | ConvertFrom-Json
$ClientId       = $config.client_id
$R2Remote       = $config.r2_remote         # rclone remote name (e.g., "weighbridge-r2")
$R2Bucket       = $config.r2_bucket         # bucket name
$EncryptionKey  = $config.encryption_key    # AES-256 passphrase
$DbHost         = if ($config.db_host) { $config.db_host } else { "localhost" }
$DbPort         = if ($config.db_port) { $config.db_port } else { "5432" }
$DbName         = if ($config.db_name) { $config.db_name } else { "weighbridge" }
$DbUser         = if ($config.db_user) { $config.db_user } else { "weighbridge" }
$DbPassword     = $config.db_password
$TgBotToken     = $config.telegram_bot_token
$TgChatId       = $config.telegram_chat_id
$LocalRetainDays  = if ($config.local_retain_days)  { $config.local_retain_days }  else { 7 }
$RemoteRetainDays = if ($config.remote_retain_days) { $config.remote_retain_days } else { 90 }

$backupResult = @{
    timestamp      = $null
    filename       = $null
    size_bytes     = 0
    size_human     = ""
    upload_success = $false
    error          = $null
    duration_sec   = 0
}

$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()

try {
    # ── Step 1: pg_dump ─────────────────────────────────────────────────────
    Write-Log "Step 1: Running pg_dump..."

    $dumpFile = Join-Path $BackupDir "weighbridge_${Timestamp}.sql"
    $gzFile   = "${dumpFile}.gz"
    $encFile  = "${gzFile}.enc"

    $env:PGPASSWORD = $DbPassword

    # Find pg_dump
    $pgDump = $null
    @(
        "C:\Program Files\PostgreSQL\16\bin\pg_dump.exe",
        "C:\Program Files\PostgreSQL\15\bin\pg_dump.exe",
        "C:\Program Files\PostgreSQL\14\bin\pg_dump.exe"
    ) | ForEach-Object {
        if ((Test-Path $_) -and -not $pgDump) { $pgDump = $_ }
    }

    # Try docker pg_dump if local not found
    if (-not $pgDump) {
        Write-Log "  Using Docker pg_dump..."
        $dockerDumpFile = "/tmp/weighbridge_${Timestamp}.sql"
        & docker exec weighbridge_db pg_dump -h localhost -U $DbUser -d $DbName -F p --no-owner --no-acl > $dumpFile 2>&1
        if ($LASTEXITCODE -ne 0) { throw "Docker pg_dump failed (exit code $LASTEXITCODE)" }
    } else {
        Write-Log "  Using: $pgDump"
        & $pgDump -h $DbHost -p $DbPort -U $DbUser -d $DbName -F p --no-owner --no-acl -f $dumpFile 2>&1
        if ($LASTEXITCODE -ne 0) { throw "pg_dump failed (exit code $LASTEXITCODE)" }
    }

    $dumpSize = (Get-Item $dumpFile).Length
    Write-Log "  Dump complete: $([math]::Round($dumpSize / 1MB, 2)) MB"

    # ── Step 2: Compress ────────────────────────────────────────────────────
    Write-Log "Step 2: Compressing..."

    # Use PowerShell compression (no external gzip needed)
    $dumpBytes  = [System.IO.File]::ReadAllBytes($dumpFile)
    $outStream  = [System.IO.File]::Create($gzFile)
    $gzipStream = New-Object System.IO.Compression.GZipStream($outStream, [System.IO.Compression.CompressionLevel]::Optimal)
    $gzipStream.Write($dumpBytes, 0, $dumpBytes.Length)
    $gzipStream.Close()
    $outStream.Close()

    Remove-Item $dumpFile -Force
    $gzSize = (Get-Item $gzFile).Length
    Write-Log "  Compressed: $([math]::Round($gzSize / 1MB, 2)) MB (ratio: $([math]::Round($gzSize / $dumpSize * 100, 1))%)"

    # ── Step 3: Encrypt ─────────────────────────────────────────────────────
    Write-Log "Step 3: Encrypting with AES-256..."

    # Use .NET AES encryption (no OpenSSL dependency)
    $keyBytes   = [System.Text.Encoding]::UTF8.GetBytes($EncryptionKey.PadRight(32).Substring(0, 32))
    $aes        = [System.Security.Cryptography.Aes]::Create()
    $aes.Key    = $keyBytes
    $aes.GenerateIV()
    $iv         = $aes.IV

    $plainBytes = [System.IO.File]::ReadAllBytes($gzFile)
    $encryptor  = $aes.CreateEncryptor()
    $encBytes   = $encryptor.TransformFinalBlock($plainBytes, 0, $plainBytes.Length)

    # Write IV (16 bytes) + encrypted data
    $outBytes = New-Object byte[] ($iv.Length + $encBytes.Length)
    [Array]::Copy($iv, 0, $outBytes, 0, $iv.Length)
    [Array]::Copy($encBytes, 0, $outBytes, $iv.Length, $encBytes.Length)
    [System.IO.File]::WriteAllBytes($encFile, $outBytes)

    $aes.Dispose()
    Remove-Item $gzFile -Force

    $encSize = (Get-Item $encFile).Length
    Write-Log "  Encrypted: $([math]::Round($encSize / 1MB, 2)) MB"

    # ── Step 4: Upload to R2 ────────────────────────────────────────────────
    Write-Log "Step 4: Uploading to Cloudflare R2..."

    $r2Path = "${R2Remote}:${R2Bucket}/${ClientId}/weighbridge_${Timestamp}.sql.gz.enc"

    if (-not (Test-Path $RcloneExe)) {
        throw "rclone not found at $RcloneExe. Run Setup-CloudBackup.ps1 first."
    }

    & $RcloneExe copyto $encFile $r2Path --progress --transfers 1 --checkers 1 2>&1 | ForEach-Object { Write-Log "  $_" }

    if ($LASTEXITCODE -ne 0) { throw "rclone upload failed (exit code $LASTEXITCODE)" }

    Write-Log "  Uploaded to $r2Path"

    $backupResult.upload_success = $true
    $backupResult.filename       = "weighbridge_${Timestamp}.sql.gz.enc"
    $backupResult.size_bytes     = $encSize
    $backupResult.size_human     = "$([math]::Round($encSize / 1MB, 2)) MB"

    # ── Step 5: Prune local backups ─────────────────────────────────────────
    Write-Log "Step 5: Pruning local backups older than $LocalRetainDays days..."

    $cutoff = (Get-Date).AddDays(-$LocalRetainDays)
    $pruned = 0
    Get-ChildItem -Path $BackupDir -Filter "*.enc" | Where-Object { $_.LastWriteTime -lt $cutoff } | ForEach-Object {
        Remove-Item $_.FullName -Force
        $pruned++
    }
    Write-Log "  Pruned $pruned local backup(s)"

    # ── Step 6: Prune remote backups ────────────────────────────────────────
    Write-Log "Step 6: Pruning R2 backups older than $RemoteRetainDays days..."

    & $RcloneExe delete "${R2Remote}:${R2Bucket}/${ClientId}/" --min-age "${RemoteRetainDays}d" 2>&1 | ForEach-Object { Write-Log "  $_" }
    Write-Log "  Remote prune complete"

}
catch {
    $backupResult.error = $_.Exception.Message
    Write-Log "BACKUP FAILED: $($_.Exception.Message)" -Error
}
finally {
    # Clean up env
    Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue

    # Clean up temp files
    @($dumpFile, $gzFile) | ForEach-Object {
        if ($_ -and (Test-Path $_)) { Remove-Item $_ -Force }
    }
}

$stopwatch.Stop()
$backupResult.timestamp    = (Get-Date -Format "o")
$backupResult.duration_sec = [math]::Round($stopwatch.Elapsed.TotalSeconds, 1)

# ── Step 7: Write status file (for API endpoint) ───────────────────────────
Write-Log "Step 7: Writing status file..."

$statusData = @{
    last_backup      = $backupResult.timestamp
    last_backup_file = $backupResult.filename
    last_backup_size = $backupResult.size_human
    size_bytes       = $backupResult.size_bytes
    upload_success   = $backupResult.upload_success
    error            = $backupResult.error
    duration_sec     = $backupResult.duration_sec
    backup_location  = "R2:${R2Bucket}/${ClientId}/"
    next_scheduled   = (Get-Date).Date.AddDays(1).AddHours(2).ToString("o")
    client_id        = $ClientId
}

$statusData | ConvertTo-Json -Depth 5 | Set-Content -Path $StatusFile -Encoding UTF8
Write-Log "  Status written to $StatusFile"

# ── Step 8: Telegram notification ───────────────────────────────────────────
if ($TgBotToken -and $TgChatId) {
    Write-Log "Step 8: Sending Telegram notification..."

    if ($backupResult.upload_success) {
        $emoji = [char]0x2705  # green check
        $msg = @"
$emoji <b>Cloud Backup Successful</b>

Client: <b>$ClientId</b>
File: <code>$($backupResult.filename)</code>
Size: <b>$($backupResult.size_human)</b>
Duration: $($backupResult.duration_sec)s
Time: $(Get-Date -Format 'dd-MMM-yyyy HH:mm')
"@
    } else {
        $emoji = [char]0x274C  # red X
        $msg = @"
$emoji <b>Cloud Backup FAILED</b>

Client: <b>$ClientId</b>
Error: <code>$($backupResult.error)</code>
Time: $(Get-Date -Format 'dd-MMM-yyyy HH:mm')

Please check C:\weighbridge\logs\cloud-backup.log
"@
    }

    try {
        $tgUrl  = "https://api.telegram.org/bot${TgBotToken}/sendMessage"
        $tgBody = @{
            chat_id    = $TgChatId
            text       = $msg
            parse_mode = "HTML"
            disable_web_page_preview = $true
        } | ConvertTo-Json -Depth 3

        Invoke-RestMethod -Uri $tgUrl -Method Post -Body $tgBody -ContentType "application/json" | Out-Null
        Write-Log "  Telegram notification sent"
    }
    catch {
        Write-Log "  Telegram notification failed: $_" -Error
    }
} else {
    Write-Log "Step 8: Telegram not configured - skipping notification"
}

# ── Done ────────────────────────────────────────────────────────────────────
if ($backupResult.upload_success) {
    Write-Log "=== Cloud Backup Completed Successfully ($($backupResult.duration_sec)s) ==="
} else {
    Write-Log "=== Cloud Backup FAILED ===" -Error
    exit 1
}
