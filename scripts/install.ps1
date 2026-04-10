#Requires -RunAsAdministrator
<#
.SYNOPSIS
  Weighbridge Invoice Software — Windows Installation Script
  Run as Administrator: powershell -ExecutionPolicy Bypass -File install.ps1

.DESCRIPTION
  Installs and configures:
    - Python 3.11+ (if not present)
    - Node.js 20 LTS (if not present)
    - PostgreSQL 15 (if not present)
    - Python virtualenv + backend dependencies
    - Frontend npm dependencies + production build
    - Creates weighbridge PostgreSQL database and user
    - Generates .env file
    - (Optional) Registers Windows services via NSSM
#>

param(
  [string]$InstallDir   = "C:\weighbridge",
  [string]$DbPassword   = "weighbridge_prod_$(Get-Random -Maximum 9999)",
  [string]$SecretKey    = [System.Convert]::ToBase64String([System.Security.Cryptography.RandomNumberGenerator]::GetBytes(32)),
  [switch]$RegisterServices = $false
)

$ErrorActionPreference = "Stop"
$ProgressPreference    = "SilentlyContinue"

Write-Host "`n===== Weighbridge Invoice Software Installer =====" -ForegroundColor Cyan
Write-Host "Install directory : $InstallDir"
Write-Host "Register services : $RegisterServices`n"

# ── Helper functions ──────────────────────────────────────────────────────────

function Test-Command($cmd) {
  $null = Get-Command $cmd -ErrorAction SilentlyContinue
  $?
}

function Download-File($url, $dest) {
  Write-Host "  Downloading $(Split-Path $dest -Leaf)..."
  Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
}

# ── 1. Python ─────────────────────────────────────────────────────────────────
Write-Host "[1/7] Checking Python..." -ForegroundColor Yellow
if (-not (Test-Command "python")) {
  Write-Host "  Python not found. Downloading Python 3.11..."
  $pyInstaller = "$env:TEMP\python-3.11.9-amd64.exe"
  Download-File "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe" $pyInstaller
  Start-Process -FilePath $pyInstaller -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_pip=1" -Wait
  $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
  Write-Host "  Python installed." -ForegroundColor Green
} else {
  Write-Host "  Python found: $(python --version)" -ForegroundColor Green
}

# ── 2. Node.js ────────────────────────────────────────────────────────────────
Write-Host "[2/7] Checking Node.js..." -ForegroundColor Yellow
if (-not (Test-Command "node")) {
  Write-Host "  Node.js not found. Downloading Node.js 20 LTS..."
  $nodeInstaller = "$env:TEMP\node-v20.11.0-x64.msi"
  Download-File "https://nodejs.org/dist/v20.11.0/node-v20.11.0-x64.msi" $nodeInstaller
  Start-Process "msiexec.exe" -ArgumentList "/i `"$nodeInstaller`" /quiet /norestart" -Wait
  $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
  Write-Host "  Node.js installed." -ForegroundColor Green
} else {
  Write-Host "  Node.js found: $(node --version)" -ForegroundColor Green
}

# ── 3. PostgreSQL ─────────────────────────────────────────────────────────────
Write-Host "[3/7] Checking PostgreSQL..." -ForegroundColor Yellow
$pgServiceExists = Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue
if (-not $pgServiceExists) {
  Write-Host "  PostgreSQL not found. Downloading PostgreSQL 15..."
  $pgInstaller = "$env:TEMP\postgresql-15.5-1-windows-x64.exe"
  Download-File "https://get.enterprisedb.com/postgresql/postgresql-15.5-1-windows-x64.exe" $pgInstaller
  $pgPassword = "postgres_admin_$(Get-Random -Maximum 9999)"
  Write-Host "  PostgreSQL superuser password: $pgPassword" -ForegroundColor Magenta
  Write-Host "  (Save this — needed for DB admin)" -ForegroundColor Magenta
  Start-Process -FilePath $pgInstaller `
    -ArgumentList "--mode unattended --superpassword `"$pgPassword`" --servicename postgresql-15 --servicepassword `"$pgPassword`" --enable-components server,commandlinetools" `
    -Wait
  $env:Path += ";C:\Program Files\PostgreSQL\15\bin"
  Write-Host "  PostgreSQL installed." -ForegroundColor Green
} else {
  $env:Path += ";C:\Program Files\PostgreSQL\15\bin"
  Write-Host "  PostgreSQL found." -ForegroundColor Green
}

# ── 4. Copy application files ─────────────────────────────────────────────────
Write-Host "[4/7] Setting up application directory..." -ForegroundColor Yellow
if (-not (Test-Path $InstallDir)) { New-Item -ItemType Directory -Path $InstallDir | Out-Null }

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir

Write-Host "  Copying from $projectRoot to $InstallDir..."
Copy-Item -Path "$projectRoot\backend" -Destination "$InstallDir\backend" -Recurse -Force
Copy-Item -Path "$projectRoot\frontend" -Destination "$InstallDir\frontend" -Recurse -Force
Copy-Item -Path "$projectRoot\scripts" -Destination "$InstallDir\scripts" -Recurse -Force

# ── 5. Python virtualenv + dependencies ───────────────────────────────────────
Write-Host "[5/7] Installing Python dependencies..." -ForegroundColor Yellow
Set-Location "$InstallDir\backend"
python -m venv venv
& ".\venv\Scripts\pip.exe" install --upgrade pip -q
& ".\venv\Scripts\pip.exe" install -r requirements.txt -q
Write-Host "  Python dependencies installed." -ForegroundColor Green

# ── 6. Frontend build ─────────────────────────────────────────────────────────
Write-Host "[6/7] Building frontend..." -ForegroundColor Yellow
Set-Location "$InstallDir\frontend"
npm install --silent
npm run build --silent
Write-Host "  Frontend built." -ForegroundColor Green

# ── 7. Database + .env ────────────────────────────────────────────────────────
Write-Host "[7/7] Configuring database and environment..." -ForegroundColor Yellow

# Create DB and user (requires psql in PATH)
$createDbSql = @"
DO `$`$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_user WHERE usename = 'weighbridge') THEN
    CREATE USER weighbridge WITH PASSWORD '$DbPassword';
  END IF;
END
`$`$;
CREATE DATABASE weighbridge OWNER weighbridge;
GRANT ALL PRIVILEGES ON DATABASE weighbridge TO weighbridge;
"@

try {
  $env:PGPASSWORD = "postgres"
  $createDbSql | & psql -U postgres -q
  Write-Host "  Database created." -ForegroundColor Green
} catch {
  Write-Host "  Could not auto-create database. Please run manually:" -ForegroundColor Yellow
  Write-Host "  psql -U postgres -c `"CREATE USER weighbridge WITH PASSWORD '$DbPassword';`""
  Write-Host "  psql -U postgres -c `"CREATE DATABASE weighbridge OWNER weighbridge;`""
}

# Write .env
$envContent = @"
DATABASE_URL=postgresql+asyncpg://weighbridge:$DbPassword@localhost:5432/weighbridge
DATABASE_URL_SYNC=postgresql+psycopg://weighbridge:$DbPassword@localhost:5432/weighbridge
SECRET_KEY=$SecretKey
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=480
"@

$envContent | Out-File -FilePath "$InstallDir\backend\.env" -Encoding UTF8 -NoNewline
Write-Host "  .env written." -ForegroundColor Green

# Run Alembic migrations
Write-Host "  Running database migrations..."
Set-Location "$InstallDir\backend"
try {
  & ".\venv\Scripts\python.exe" -m alembic upgrade head
  Write-Host "  Migrations complete." -ForegroundColor Green
} catch {
  Write-Host "  Migration warning: $_" -ForegroundColor Yellow
}

# ── Optional: Windows Services ────────────────────────────────────────────────
if ($RegisterServices) {
  & "$InstallDir\scripts\nssm-register.ps1" -InstallDir $InstallDir
}

# ── Summary ───────────────────────────────────────────────────────────────────
Write-Host "`n===== Installation Complete! =====" -ForegroundColor Green
Write-Host ""
Write-Host "Installation directory : $InstallDir"
Write-Host "Database password      : $DbPassword" -ForegroundColor Magenta
Write-Host "Secret key             : $SecretKey" -ForegroundColor Magenta
Write-Host ""
Write-Host "To start manually:"
Write-Host "  Backend  : cd $InstallDir\backend && .\venv\Scripts\uvicorn.exe app.main:app --host 0.0.0.0 --port 9001"
Write-Host "  Frontend : Serve $InstallDir\frontend\dist\ with any static file server or Nginx"
Write-Host ""
Write-Host "To register as Windows services:"
Write-Host "  powershell -File $InstallDir\scripts\nssm-register.ps1 -InstallDir $InstallDir"
Write-Host ""
Write-Host "Access the application at http://localhost:9001 (backend) or the configured frontend port."
Write-Host "(First login: admin / admin — change password immediately!)"
