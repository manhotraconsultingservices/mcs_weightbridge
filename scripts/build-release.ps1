<#
.SYNOPSIS
    Build a production release of Weighbridge Invoice Software.

.DESCRIPTION
    Compiles the Python backend into a native .exe using Nuitka, builds the
    React frontend, and packages everything into a release folder.

    Prerequisites:
    - Python 3.11+ with Nuitka installed (pip install nuitka)
    - MSVC C compiler (Visual Studio Build Tools)
    - Node.js 18+ with npm
    - All backend dependencies installed

.PARAMETER Version
    Release version string (e.g., "1.2.0")

.EXAMPLE
    .\build-release.ps1 -Version "1.2.0"
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$Version
)

$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$BackendDir = Join-Path $RootDir "backend"
$FrontendDir = Join-Path $RootDir "frontend"
$DistDir = Join-Path $RootDir "dist"
$ReleaseDir = Join-Path $DistDir "weighbridge-v$Version"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Weighbridge Release Builder v$Version" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# ── Clean ────────────────────────────────────────────────────────────────────
if (Test-Path $ReleaseDir) {
    Write-Host "`nCleaning previous build..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force $ReleaseDir
}
New-Item -ItemType Directory -Path $ReleaseDir -Force | Out-Null

# ── Build Frontend ──────────────────────────────────────────────────────────
Write-Host "`n[1/3] Building frontend..." -ForegroundColor Green
Push-Location $FrontendDir
npm ci --silent
npm run build
Pop-Location

$FrontendDist = Join-Path $FrontendDir "dist"
if (-not (Test-Path $FrontendDist)) {
    Write-Host "ERROR: Frontend build failed - dist/ not found" -ForegroundColor Red
    exit 1
}
Copy-Item -Recurse $FrontendDist (Join-Path $ReleaseDir "frontend\dist")
Write-Host "  Frontend built successfully." -ForegroundColor Gray

# ── Build Backend (Nuitka) ──────────────────────────────────────────────────
Write-Host "`n[2/3] Compiling backend with Nuitka..." -ForegroundColor Green
Write-Host "  This may take 10-20 minutes on first build." -ForegroundColor Yellow
Push-Location $BackendDir

python -m nuitka `
    --standalone `
    --onefile `
    --output-dir="$DistDir" `
    --output-filename="weighbridge-backend.exe" `
    --include-package=app `
    --include-package=uvicorn `
    --include-package=sqlalchemy `
    --include-package=asyncpg `
    --include-package=jose `
    --include-package=passlib `
    --include-package=cryptography `
    --include-package=pydantic `
    --include-package=jinja2 `
    --include-package=xhtml2pdf `
    --include-data-dir="app/templates=app/templates" `
    --windows-console-mode=attach `
    --company-name="Weighbridge Software" `
    --product-name="Weighbridge Invoice Software" `
    --file-version="$Version.0" `
    --product-version="$Version.0" `
    run_server.py

Pop-Location

$ExePath = Join-Path $DistDir "weighbridge-backend.exe"
if (-not (Test-Path $ExePath)) {
    Write-Host "ERROR: Nuitka compilation failed - .exe not found" -ForegroundColor Red
    exit 1
}
Move-Item $ExePath (Join-Path $ReleaseDir "weighbridge-backend.exe")
Write-Host "  Backend compiled successfully." -ForegroundColor Gray

# ── Package ─────────────────────────────────────────────────────────────────
Write-Host "`n[3/3] Packaging release..." -ForegroundColor Green

# Copy supporting files
$FilesToCopy = @(
    @{ Src = (Join-Path $RootDir "docker-compose.yml");                           Dst = "docker-compose.yml" },
    @{ Src = (Join-Path $RootDir "SETUP_GUIDE.md");                               Dst = "SETUP_GUIDE.md" },
    @{ Src = (Join-Path $RootDir "instructions\CLIENT_INSTALLATION_GUIDE.md");    Dst = "CLIENT_INSTALLATION_GUIDE.md" },
    @{ Src = (Join-Path $RootDir "backend\show_fingerprint.py");                  Dst = "show_fingerprint.py" },
)
foreach ($f in $FilesToCopy) {
    $src = $f.Src
    if (Test-Path $src) {
        Copy-Item $src (Join-Path $ReleaseDir $f.Dst)
    }
}

# Copy scripts
$ScriptsDir = Join-Path $ReleaseDir "scripts"
New-Item -ItemType Directory -Path $ScriptsDir -Force | Out-Null
$ScriptFiles = @(
    "Install-Client.ps1",
    "install-services.ps1",
    "manage-services.ps1",
    "Get-Fingerprint.ps1",
    "Get-Fingerprint.bat"
)
foreach ($s in $ScriptFiles) {
    $src = Join-Path $RootDir "scripts\$s"
    if (Test-Path $src) {
        Copy-Item $src (Join-Path $ScriptsDir $s)
    }
}

# Copy NSSM
$NssmSrc = Join-Path $RootDir "tools\nssm.exe"
$ToolsDir = Join-Path $ReleaseDir "tools"
New-Item -ItemType Directory -Path $ToolsDir -Force | Out-Null
if (Test-Path $NssmSrc) {
    Copy-Item $NssmSrc (Join-Path $ToolsDir "nssm.exe")
}

# Create template .env
$EnvTemplate = @"
# Weighbridge Configuration — Edit before first run
DATABASE_URL=postgresql+asyncpg://weighbridge:CHANGE_ME@localhost:5432/weighbridge
DATABASE_URL_SYNC=postgresql+psycopg://weighbridge:CHANGE_ME@localhost:5432/weighbridge
SECRET_KEY=CHANGE_ME_GENERATE_WITH_python_c_import_secrets_print_secrets_token_hex_32
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=480
PRIVATE_DATA_KEY=CHANGE_ME_GENERATE_WITH_python_c_import_secrets_print_secrets_token_hex_32
"@
$EnvTemplate | Out-File -Encoding utf8 (Join-Path $ReleaseDir ".env.template")

Write-Host "`n============================================================" -ForegroundColor Cyan
Write-Host "  BUILD COMPLETE" -ForegroundColor Green
Write-Host "  Release: $ReleaseDir" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1. Run Get-Fingerprint.bat/ps1 on the client machine to capture fingerprint"
Write-Host "  2. Run: python generate_license.py --fingerprint fingerprint.json --customer 'Name' --serial WB-XXXX --expires YYYY-MM-DD"
Write-Host "  3. Copy license.key to the root of the weighbridge-v$Version folder"
Write-Host "  4. Copy the entire weighbridge-v$Version folder to a USB drive"
Write-Host "  5. On the client machine: right-click scripts\Install-Client.ps1 → Run with PowerShell"
