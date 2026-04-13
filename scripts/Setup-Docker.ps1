<#
.SYNOPSIS
    Weighbridge Docker + Multi-Tenant Setup Script (Windows)

.DESCRIPTION
    Sets up PostgreSQL in Docker, initializes master DB, and prepares backend .env.

.EXAMPLE
    .\Setup-Docker.ps1
#>

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir
$BackendDir = Join-Path $ProjectDir "backend"

Write-Host ""
Write-Host "  ╔══════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "  ║   Weighbridge Docker Setup (Windows)          ║" -ForegroundColor Cyan
Write-Host "  ╚══════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ── Step 1: Check Docker ─────────────────────────────────────────────────
Write-Host "[1/6] Checking Docker..." -ForegroundColor Yellow

try {
    $dockerVer = docker --version 2>$null
    if (-not $dockerVer) { throw "not found" }
    Write-Host "  Docker OK: $dockerVer" -ForegroundColor Green
} catch {
    Write-Host "  Docker not found. Install Docker Desktop from:" -ForegroundColor Red
    Write-Host "  https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe"
    exit 1
}

try {
    docker info 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "not running" }
} catch {
    Write-Host "  Docker daemon not running. Start Docker Desktop first." -ForegroundColor Red
    exit 1
}

# ── Step 2: Create data directory ────────────────────────────────────────
Write-Host "[2/6] Setting up data directory..." -ForegroundColor Yellow
$DataDir = "C:\data\pgdata"
if (-not (Test-Path $DataDir)) {
    New-Item -Path $DataDir -ItemType Directory -Force | Out-Null
    Write-Host "  Created $DataDir" -ForegroundColor Green
} else {
    Write-Host "  $DataDir already exists" -ForegroundColor Green
}

# ── Step 3: Prepare init scripts ─────────────────────────────────────────
Write-Host "[3/6] Preparing init scripts..." -ForegroundColor Yellow
$initScript = Join-Path $ProjectDir "docker\init-multi-db.sh"
if (Test-Path $initScript) {
    Write-Host "  Init scripts ready" -ForegroundColor Green
} else {
    Write-Host "  Warning: $initScript not found" -ForegroundColor Yellow
}

# ── Step 4: Start PostgreSQL ─────────────────────────────────────────────
Write-Host "[4/6] Starting PostgreSQL container..." -ForegroundColor Yellow

$pgStatus = docker ps --filter "name=weighbridge_db" --format '{{.Status}}' 2>$null
if ($pgStatus -match "Up") {
    Write-Host "  PostgreSQL already running" -ForegroundColor Green
} else {
    Push-Location $ProjectDir
    docker compose up -d db
    Pop-Location

    Write-Host "  Waiting for PostgreSQL to be ready" -NoNewline
    $ready = $false
    for ($i = 1; $i -le 30; $i++) {
        try {
            docker exec weighbridge_db pg_isready -U weighbridge 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) {
                $ready = $true
                break
            }
        } catch {}
        Write-Host "." -NoNewline
        Start-Sleep -Seconds 1
    }
    Write-Host ""
    if ($ready) {
        Write-Host "  PostgreSQL is ready!" -ForegroundColor Green
    } else {
        Write-Host "  PostgreSQL did not become ready in 30 seconds" -ForegroundColor Red
        exit 1
    }
}

# ── Step 5: Verify master database ───────────────────────────────────────
Write-Host "[5/6] Verifying master database..." -ForegroundColor Yellow

$masterExists = docker exec -e PGPASSWORD=weighbridge_dev_2024 weighbridge_db `
    psql -U weighbridge -d postgres -tAc `
    "SELECT 1 FROM pg_database WHERE datname = 'weighbridge_master'" 2>$null

if ($masterExists -and $masterExists.Trim() -eq "1") {
    Write-Host "  weighbridge_master database exists" -ForegroundColor Green
} else {
    Write-Host "  Creating weighbridge_master database..."
    docker exec -e PGPASSWORD=weighbridge_dev_2024 weighbridge_db `
        psql -U weighbridge -d postgres -c `
        "CREATE DATABASE weighbridge_master OWNER weighbridge"
    Write-Host "  weighbridge_master created" -ForegroundColor Green
}

# ── Step 6: Create .env if needed ────────────────────────────────────────
Write-Host "[6/6] Checking backend configuration..." -ForegroundColor Yellow
$envFile = Join-Path $BackendDir ".env"
if (-not (Test-Path $envFile)) {
    @"
DATABASE_URL=postgresql+asyncpg://weighbridge:weighbridge_dev_2024@localhost:5432/weighbridge
DATABASE_URL_SYNC=postgresql+psycopg://weighbridge:weighbridge_dev_2024@localhost:5432/weighbridge
SECRET_KEY=change-this-to-a-random-secret
MULTI_TENANT=true
MASTER_DATABASE_URL=postgresql+asyncpg://weighbridge:weighbridge_dev_2024@localhost:5432/weighbridge_master
MASTER_DATABASE_URL_SYNC=postgresql+psycopg://weighbridge:weighbridge_dev_2024@localhost:5432/weighbridge_master
SUPER_ADMIN_SECRET=change-this-to-a-strong-secret
"@ | Set-Content -Path $envFile -Encoding UTF8
    Write-Host "  Created $envFile (edit SUPER_ADMIN_SECRET!)" -ForegroundColor Green
} else {
    Write-Host "  $envFile already exists" -ForegroundColor Green
}

Write-Host ""
Write-Host "  ╔══════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "  ║   Setup Complete!                             ║" -ForegroundColor Green
Write-Host "  ╚══════════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Edit $envFile and set SUPER_ADMIN_SECRET"
Write-Host "  2. Start backend:"
Write-Host "     cd $BackendDir; uvicorn app.main:app --host 0.0.0.0 --port 9001"
Write-Host "  3. Create your first tenant:"
Write-Host "     `$env:SUPER_ADMIN_SECRET='your-secret'"
Write-Host "     .\Manage-Tenant.ps1 -Action Create -Slug demo -Name 'Demo Corp' -Password Admin123 -Company 'Demo Crushers'"
Write-Host ""
