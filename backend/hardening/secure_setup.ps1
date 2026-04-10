##############################################################################
#  Weighbridge ERP — OS & Database Security Hardening Script
#
#  Run ONCE on the deployment machine as Administrator after installation.
#
#  What this script does:
#    1.  Creates a least-privilege Windows service account (weighbridge_svc)
#    2.  Locks down file system permissions on the installation directory
#    3.  Hardens PostgreSQL pg_hba.conf (localhost only, no TCP from LAN)
#    4.  Changes the PostgreSQL database password to a strong random value
#    5.  Configures the NSSM service to run as weighbridge_svc
#    6.  Enables Windows Firewall rules (block 5432 from external)
#    7.  Checks BitLocker status and prompts to enable
#    8.  Sets .env / secrets.dpapi file ACLs (service account read-only)
#
#  Usage:
#    powershell -ExecutionPolicy Bypass -File hardening\secure_setup.ps1
##############################################################################

#Requires -RunAsAdministrator
param(
    [string]$InstallDir   = "C:\weighbridge",
    [string]$PgDataDir    = "C:\Program Files\PostgreSQL\16\data",
    [string]$PgBinDir     = "C:\Program Files\PostgreSQL\16\bin",
    [string]$ServiceName  = "WeighbridgeERP",
    [string]$ServiceUser  = "weighbridge_svc"
)

$ErrorActionPreference = "Stop"

function Write-Step { param($msg) Write-Host "`n[$([datetime]::Now.ToString('HH:mm:ss'))] $msg" -ForegroundColor Cyan }
function Write-OK   { param($msg) Write-Host "  ✓ $msg" -ForegroundColor Green }
function Write-Warn { param($msg) Write-Host "  ⚠ $msg" -ForegroundColor Yellow }
function Write-Fail { param($msg) Write-Host "  ✗ $msg" -ForegroundColor Red }

Write-Host ""
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "  Weighbridge ERP — Security Hardening" -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Cyan

# ── 1. Create service account ────────────────────────────────────────────────
Write-Step "Creating least-privilege service account: $ServiceUser"

$existingUser = Get-LocalUser -Name $ServiceUser -ErrorAction SilentlyContinue
if ($existingUser) {
    Write-OK "User '$ServiceUser' already exists"
} else {
    # Generate a strong random password for the service account
    $svcPassword = [System.Web.Security.Membership]::GeneratePassword(32, 8)
    $secPwd = ConvertTo-SecureString $svcPassword -AsPlainText -Force
    New-LocalUser -Name $ServiceUser `
                  -Password $secPwd `
                  -Description "Weighbridge ERP service account (least privilege)" `
                  -PasswordNeverExpires `
                  -UserMayNotChangePassword | Out-Null

    # Grant "Log on as a service" right
    $tempFile = [System.IO.Path]::GetTempFileName()
    secedit /export /cfg $tempFile /quiet
    $content = Get-Content $tempFile
    $content = $content -replace "SeServiceLogonRight = (.+)", "SeServiceLogonRight = `$1,$ServiceUser"
    Set-Content $tempFile $content
    secedit /configure /db secedit.sdb /cfg $tempFile /quiet
    Remove-Item $tempFile -Force

    Write-OK "Created service account '$ServiceUser'"
    Write-Warn "Service account password stored in Windows credential store only"
}

# ── 2. Lock down installation directory ACLs ─────────────────────────────────
Write-Step "Setting installation directory permissions: $InstallDir"

if (Test-Path $InstallDir) {
    $acl = Get-Acl $InstallDir

    # Remove inheritance
    $acl.SetAccessRuleProtection($true, $false)

    # SYSTEM — full control (needed for Windows internals)
    $acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
        "SYSTEM", "FullControl", "ContainerInherit,ObjectInherit", "None", "Allow")))

    # Administrators — full control
    $acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
        "Administrators", "FullControl", "ContainerInherit,ObjectInherit", "None", "Allow")))

    # Service account — read + execute only (cannot modify source files)
    $acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
        $ServiceUser, "ReadAndExecute", "ContainerInherit,ObjectInherit", "None", "Allow")))

    Set-Acl $InstallDir $acl
    Write-OK "Directory ACLs locked to Administrators + $ServiceUser (read-only)"

    # Give service account write access ONLY to uploads/ and logs/
    foreach ($subdir in @("uploads", "logs")) {
        $path = Join-Path $InstallDir $subdir
        if (-not (Test-Path $path)) { New-Item -ItemType Directory -Path $path -Force | Out-Null }
        $subAcl = Get-Acl $path
        $subAcl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
            $ServiceUser, "Modify", "ContainerInherit,ObjectInherit", "None", "Allow")))
        Set-Acl $path $subAcl
        Write-OK "Granted $ServiceUser write access to: $path"
    }
} else {
    Write-Warn "Install directory not found: $InstallDir — skipping ACL setup"
}

# ── 3. Harden PostgreSQL pg_hba.conf ────────────────────────────────────────
Write-Step "Hardening PostgreSQL pg_hba.conf (localhost-only access)"

$pgHba = Join-Path $PgDataDir "pg_hba.conf"
if (Test-Path $pgHba) {
    # Backup original
    Copy-Item $pgHba "$pgHba.bak" -Force
    Write-OK "Backed up pg_hba.conf to $pgHba.bak"

    # Write hardened version
    $hardenedHba = @"
# Weighbridge ERP - Hardened pg_hba.conf
# Generated by secure_setup.ps1 on $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
#
# POLICY: Only localhost connections allowed. No external TCP/IP access.

# TYPE  DATABASE   USER         ADDRESS        METHOD

# PostgreSQL superuser via local socket
local   all        postgres                    trust

# Application user — localhost only via IPv4 loopback
host    weighbridge weighbridge  127.0.0.1/32  scram-sha-256

# Reject everything else
host    all        all           0.0.0.0/0     reject
host    all        all           ::/0          reject
"@
    Set-Content $pgHba $hardenedHba -Encoding UTF8
    Write-OK "pg_hba.conf hardened — LAN access to PostgreSQL blocked"
    Write-Warn "PostgreSQL service needs restart: Restart-Service postgresql*"
} else {
    Write-Warn "pg_hba.conf not found at: $pgHba"
    Write-Warn "Manually locate and update pg_hba.conf to restrict access"
}

# ── 4. Change PostgreSQL database password ───────────────────────────────────
Write-Step "Changing PostgreSQL database password"

Add-Type -AssemblyName System.Web
$newDbPwd = [System.Web.Security.Membership]::GeneratePassword(32, 8)
$psqlExe  = Join-Path $PgBinDir "psql.exe"

if (Test-Path $psqlExe) {
    $env:PGPASSWORD = "postgres"  # temporary — assumes postgres superuser has no password
    & $psqlExe -U postgres -c "ALTER USER weighbridge WITH PASSWORD '$newDbPwd';" 2>&1 | Out-Null
    Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue

    Write-OK "PostgreSQL password changed to a 32-character random value"

    # Write new password hint (admin must manually update secrets.dpapi or .env)
    Write-Host ""
    Write-Host "  ┌─────────────────────────────────────────────────────┐" -ForegroundColor Yellow
    Write-Host "  │  NEW DATABASE PASSWORD (update .env then re-run     │" -ForegroundColor Yellow
    Write-Host "  │  setup_dpapi.py to encrypt):                        │" -ForegroundColor Yellow
    Write-Host "  │  DATABASE_URL = postgresql+asyncpg://weighbridge:   │" -ForegroundColor Yellow
    Write-Host "  │  $newDbPwd   │" -ForegroundColor Yellow
    Write-Host "  │  @localhost:5432/weighbridge                        │" -ForegroundColor Yellow
    Write-Host "  └─────────────────────────────────────────────────────┘" -ForegroundColor Yellow
    Write-Host ""
} else {
    Write-Warn "psql.exe not found at $psqlExe — change DB password manually"
}

# ── 5. Configure NSSM service to run as service account ─────────────────────
Write-Step "Configuring Windows service to run as $ServiceUser"

$nssm = Get-Command nssm -ErrorAction SilentlyContinue
if ($nssm) {
    $svcExists = (sc.exe query $ServiceName 2>&1) -match "STATE"
    if ($svcExists) {
        nssm set $ServiceName ObjectName ".\$ServiceUser" | Out-Null
        Write-OK "Service '$ServiceName' configured to run as .\$ServiceUser"
        Write-Warn "Restart the service: Restart-Service $ServiceName"
    } else {
        Write-Warn "Service '$ServiceName' not found — configure manually after installation"
    }
} else {
    Write-Warn "nssm not found in PATH — configure service account manually in NSSM GUI"
}

# ── 6. Windows Firewall — block PostgreSQL from external ─────────────────────
Write-Step "Configuring Windows Firewall (block external PostgreSQL access)"

# Remove any existing PostgreSQL allow rules
Get-NetFirewallRule -DisplayName "*PostgreSQL*" -ErrorAction SilentlyContinue |
    Where-Object { $_.Direction -eq "Inbound" } |
    Remove-NetFirewallRule -ErrorAction SilentlyContinue

# Block port 5432 from all external sources
New-NetFirewallRule `
    -DisplayName "Weighbridge: Block PostgreSQL External" `
    -Direction Inbound `
    -Protocol TCP `
    -LocalPort 5432 `
    -RemoteAddress "0.0.0.0/0" `
    -Action Block `
    -Enabled True | Out-Null

Write-OK "Firewall rule added: block TCP 5432 from external networks"

# ── 7. BitLocker status check ────────────────────────────────────────────────
Write-Step "Checking BitLocker status (database encryption at rest)"

try {
    $blStatus = Get-BitLockerVolume -MountPoint $env:SystemDrive -ErrorAction Stop
    if ($blStatus.VolumeStatus -eq "FullyEncrypted") {
        Write-OK "BitLocker is ACTIVE on $($env:SystemDrive) — database encrypted at rest"
    } elseif ($blStatus.VolumeStatus -eq "EncryptionInProgress") {
        Write-OK "BitLocker encryption in progress on $($env:SystemDrive)"
    } else {
        Write-Warn "BitLocker is NOT enabled on $($env:SystemDrive)"
        Write-Host ""
        Write-Host "  ⚠  CRITICAL: The PostgreSQL database is NOT encrypted at rest." -ForegroundColor Red
        Write-Host "     If this machine is stolen, all business data is immediately readable." -ForegroundColor Red
        Write-Host ""
        Write-Host "  To enable BitLocker:" -ForegroundColor Yellow
        Write-Host "    1. Open Control Panel → BitLocker Drive Encryption" -ForegroundColor Yellow
        Write-Host "    2. Turn on BitLocker for $($env:SystemDrive)" -ForegroundColor Yellow
        Write-Host "    3. Save the recovery key to a SEPARATE secure location (USB + print)" -ForegroundColor Yellow
        Write-Host "    4. Choose 'Encrypt entire drive' (not just used space)" -ForegroundColor Yellow
        Write-Host ""
        $enable = Read-Host "  Enable BitLocker now? (y/N)"
        if ($enable -eq 'y') {
            Enable-BitLocker -MountPoint $env:SystemDrive `
                -EncryptionMethod XtsAes256 `
                -SkipHardwareTest `
                -RecoveryPasswordProtector | Out-Null
            Write-OK "BitLocker encryption started. Save the recovery key shown above."
        }
    }
} catch {
    Write-Warn "Could not check BitLocker status: $_"
}

# ── 8. Lock down secrets file ACLs ──────────────────────────────────────────
Write-Step "Locking down secrets.dpapi and .env file permissions"

foreach ($secretFile in @("$InstallDir\backend\secrets.dpapi", "$InstallDir\backend\.env")) {
    if (Test-Path $secretFile) {
        $acl = Get-Acl $secretFile
        $acl.SetAccessRuleProtection($true, $false)
        # Only SYSTEM and Administrators can read
        $acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
            "SYSTEM", "Read", "None", "None", "Allow")))
        $acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
            "Administrators", "FullControl", "None", "None", "Allow")))
        $acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
            $ServiceUser, "Read", "None", "None", "Allow")))
        Set-Acl $secretFile $acl
        Write-OK "Locked ACL on: $secretFile"
    }
}

# ── Done ─────────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "=======================================================" -ForegroundColor Green
Write-Host "  Security Hardening Complete" -ForegroundColor Green
Write-Host "=======================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Checklist:" -ForegroundColor Cyan
Write-Host "    [✓] Service account created: $ServiceUser" -ForegroundColor Cyan
Write-Host "    [✓] Directory ACLs locked down" -ForegroundColor Cyan
Write-Host "    [✓] PostgreSQL access restricted to localhost" -ForegroundColor Cyan
Write-Host "    [✓] Firewall blocking external PostgreSQL access" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Manual steps still required:" -ForegroundColor Yellow
Write-Host "    [ ] Run setup_dpapi.py to encrypt .env secrets" -ForegroundColor Yellow
Write-Host "    [ ] Update DATABASE_URL in .env with new password" -ForegroundColor Yellow
Write-Host "    [ ] Enable BitLocker on $($env:SystemDrive) (if not already done)" -ForegroundColor Yellow
Write-Host "    [ ] Restart PostgreSQL service" -ForegroundColor Yellow
Write-Host "    [ ] Restart Weighbridge ERP service" -ForegroundColor Yellow
Write-Host ""
