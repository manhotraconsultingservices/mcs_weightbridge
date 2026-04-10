<#
.SYNOPSIS
    Vendor-side tool: generates client-specific deployment package.

.DESCRIPTION
    Run BEFORE visiting the client site. Creates a folder with all
    client-specific configs needed by Deploy-Full.ps1.

.PARAMETER ClientName
    Company name (e.g., "Shree Ram Stone Crusher Pvt Ltd")

.PARAMETER ClientId
    Short kebab-case identifier (e.g., "shreeram-crusher"). Used in URLs and R2 paths.

.PARAMETER TunnelToken
    Cloudflare Tunnel connector token (from Zero Trust dashboard)

.PARAMETER R2AccessKey
    Cloudflare R2 API Access Key ID

.PARAMETER R2SecretKey
    Cloudflare R2 Secret Access Key

.PARAMETER R2AccountId
    Cloudflare Account ID

.PARAMETER LicenseKeyPath
    Path to the generated license.key file for this client

.PARAMETER Domain
    Your domain (e.g., "weighbridge.yourdomain.com")

.PARAMETER OutputDir
    Where to create the deployment package. Default: .\deployment-packages\<ClientId>

.EXAMPLE
    .\Generate-DeploymentConfig.ps1 `
        -ClientName "Shree Ram Stone Crusher Pvt Ltd" `
        -ClientId "shreeram" `
        -TunnelToken "eyJhIjoiNGY..." `
        -R2AccessKey "abc123" -R2SecretKey "xyz789" -R2AccountId "1234abcd" `
        -LicenseKeyPath ".\licenses\shreeram.key" `
        -Domain "weighbridge.example.com"
#>

param(
    [Parameter(Mandatory)] [string]$ClientName,
    [Parameter(Mandatory)] [string]$ClientId,
    [Parameter(Mandatory)] [string]$TunnelToken,
    [Parameter(Mandatory)] [string]$R2AccessKey,
    [Parameter(Mandatory)] [string]$R2SecretKey,
    [Parameter(Mandatory)] [string]$R2AccountId,
    [string]$LicenseKeyPath = "",
    [string]$Domain         = "weighbridge.example.com",
    [string]$R2Bucket       = "weighbridge-backups",
    [string]$TelegramBotToken = "",
    [string]$TelegramChatId   = "",
    [string]$OutputDir      = ""
)

$ErrorActionPreference = "Stop"

if (-not $OutputDir) {
    $OutputDir = Join-Path ".\deployment-packages" $ClientId
}

Write-Host "`n=============================================" -ForegroundColor White
Write-Host "  Weighbridge — Deployment Package Generator   " -ForegroundColor White
Write-Host "=============================================`n" -ForegroundColor White

# Create output directory
if (Test-Path $OutputDir) {
    Write-Host "  WARNING: Output directory exists. Overwriting..." -ForegroundColor Yellow
}
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

# ── 1. Deploy config (master JSON consumed by Deploy-Full.ps1) ──────────────
$deployConfig = @{
    client_name      = $ClientName
    client_id        = $ClientId
    domain           = $Domain
    public_url       = "https://weighbridge-${ClientId}.${Domain}"
    tunnel_token     = $TunnelToken
    r2_access_key    = $R2AccessKey
    r2_secret_key    = $R2SecretKey
    r2_account_id    = $R2AccountId
    r2_bucket        = $R2Bucket
    telegram_bot_token = $TelegramBotToken
    telegram_chat_id   = $TelegramChatId
    created_at       = (Get-Date -Format "o")
    created_by       = $env:USERNAME
    created_on       = $env:COMPUTERNAME
}

$configPath = Join-Path $OutputDir "deploy-config.json"
$deployConfig | ConvertTo-Json -Depth 5 | Set-Content -Path $configPath -Encoding UTF8
Write-Host "  [1/4] deploy-config.json" -ForegroundColor Green

# ── 2. Copy license key ─────────────────────────────────────────────────────
if ($LicenseKeyPath -and (Test-Path $LicenseKeyPath)) {
    Copy-Item $LicenseKeyPath (Join-Path $OutputDir "license.key") -Force
    Write-Host "  [2/4] license.key copied" -ForegroundColor Green
} else {
    Write-Host "  [2/4] license.key NOT PROVIDED — add manually before deployment" -ForegroundColor Yellow
}

# ── 3. Deployment checklist ─────────────────────────────────────────────────
$checklist = @"
========================================
 DEPLOYMENT CHECKLIST — $ClientName
 Client ID: $ClientId
 Generated: $(Get-Date -Format 'dd-MMM-yyyy HH:mm')
========================================

BEFORE VISITING CLIENT:
[ ] Verify license.key is in this folder
[ ] Verify tunnel token is correct (test in Cloudflare dashboard)
[ ] Verify R2 bucket exists: $R2Bucket
[ ] Copy latest release package (weighbridge-full-x.x.x/)
[ ] Ensure Docker Desktop installer is available (if needed)

USB DRIVE CONTENTS:
  deployment-packages/$ClientId/
    deploy-config.json     — All client configs
    license.key            — Hardware-locked license
    CHECKLIST.txt          — This file
  weighbridge-full-x.x.x/ — Application release package
  scripts/                 — Deployment scripts
  Docker Desktop Installer.exe (if needed)

AT CLIENT SITE:
[ ] 1. Verify system: Windows 10/11, 8GB+ RAM, 5GB+ free
[ ] 2. Install Docker Desktop (if not present)
[ ] 3. Run: Deploy-Full.ps1 -ConfigFile deploy-config.json
[ ] 4. Wait for all 6 phases to complete
[ ] 5. Change admin password (default: admin / admin123)
[ ] 6. Enter company details (GSTIN, PAN, address, bank)
[ ] 7. Configure weighing scale COM port
[ ] 8. Connect IP cameras (if applicable)
[ ] 9. Create financial year
[ ] 10. Create operator user accounts
[ ] 11. Test: Create sample token → weigh → invoice → print
[ ] 12. Verify public URL: $($deployConfig.public_url)
[ ] 13. Store USB with .env.bak safely (offline backup)

POST-DEPLOYMENT:
[ ] Run Verify-Deployment.ps1 -PublicUrl "$($deployConfig.public_url)"
[ ] All checks PASS → hand over to client
"@

$checklistPath = Join-Path $OutputDir "CHECKLIST.txt"
Set-Content -Path $checklistPath -Value $checklist -Encoding UTF8
Write-Host "  [3/4] CHECKLIST.txt" -ForegroundColor Green

# ── 4. Quick-deploy batch file ──────────────────────────────────────────────
$batchContent = @"
@echo off
echo ========================================
echo  Weighbridge ERP — One-Click Deploy
echo  Client: $ClientName
echo ========================================
echo.
echo This will install the Weighbridge application.
echo Press Ctrl+C to cancel, or...
pause

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\scripts\Deploy-Full.ps1" -ConfigFile "%~dp0deploy-config.json"

echo.
echo Done! Check the output above for any errors.
pause
"@

$batchPath = Join-Path $OutputDir "DEPLOY.bat"
Set-Content -Path $batchPath -Value $batchContent -Encoding ASCII
Write-Host "  [4/4] DEPLOY.bat (double-click installer)" -ForegroundColor Green

# ── Summary ─────────────────────────────────────────────────────────────────
Write-Host "`n=============================================" -ForegroundColor Green
Write-Host "  Deployment Package Ready!                    " -ForegroundColor Green
Write-Host "=============================================`n" -ForegroundColor Green

Write-Host "  Client:     $ClientName" -ForegroundColor White
Write-Host "  Client ID:  $ClientId" -ForegroundColor White
Write-Host "  Public URL: $($deployConfig.public_url)" -ForegroundColor Cyan
Write-Host "  Package:    $OutputDir" -ForegroundColor White
Write-Host ""
Write-Host "  Contents:" -ForegroundColor White

Get-ChildItem $OutputDir | ForEach-Object {
    Write-Host "    $($_.Name) ($([math]::Round($_.Length / 1KB, 1)) KB)" -ForegroundColor Gray
}

Write-Host "`n  Next: Copy this folder + release package to USB drive.`n" -ForegroundColor Yellow
