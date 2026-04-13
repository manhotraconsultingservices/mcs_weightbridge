<#
.SYNOPSIS
    Weighbridge Multi-Tenant Management Script (Windows)

.DESCRIPTION
    Create, list, backup, and manage tenants for the Weighbridge SaaS platform.

.EXAMPLE
    .\Manage-Tenant.ps1 -Action Create -Slug acme -Name "Acme Corp" -Password Admin123 -Company "Acme Crushers"
    .\Manage-Tenant.ps1 -Action List
    .\Manage-Tenant.ps1 -Action Backup -Slug acme
    .\Manage-Tenant.ps1 -Action BackupAll
    .\Manage-Tenant.ps1 -Action Status
#>

param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("Create", "List", "Backup", "BackupAll", "Status")]
    [string]$Action,

    [string]$Slug,
    [string]$Name,
    [string]$Password,
    [string]$Company,
    [string]$AdminUser = "admin",

    [string]$ApiUrl = "http://localhost:9001",
    [string]$SuperAdminSecret = $env:SUPER_ADMIN_SECRET,
    [string]$PgContainer = "weighbridge_db",
    [string]$PgUser = "weighbridge",
    [string]$PgPassword = "weighbridge_dev_2024",
    [string]$BackupDir = ".\backups"
)

$ErrorActionPreference = "Stop"

# ── Helpers ──────────────────────────────────────────────────────────────────

function Write-Header {
    Write-Host ""
    Write-Host "  ╔══════════════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "  ║  Weighbridge Multi-Tenant Manager (Windows)  ║" -ForegroundColor Cyan
    Write-Host "  ╚══════════════════════════════════════════════╝" -ForegroundColor Cyan
    Write-Host ""
}

function Invoke-TenantApi {
    param(
        [string]$Method = "GET",
        [string]$Endpoint,
        [object]$Body = $null
    )

    if (-not $SuperAdminSecret) {
        throw "SUPER_ADMIN_SECRET is required. Set via -SuperAdminSecret or `$env:SUPER_ADMIN_SECRET"
    }

    $headers = @{
        "X-Super-Admin" = $SuperAdminSecret
        "Content-Type"  = "application/json"
    }

    $params = @{
        Uri     = "$ApiUrl$Endpoint"
        Method  = $Method
        Headers = $headers
    }

    if ($Body) {
        $params["Body"] = ($Body | ConvertTo-Json -Depth 10)
    }

    try {
        $response = Invoke-RestMethod @params
        return $response
    }
    catch {
        $statusCode = $_.Exception.Response.StatusCode.value__
        $errorBody = $_.ErrorDetails.Message
        Write-Host "  API Error (HTTP $statusCode): $errorBody" -ForegroundColor Red
        throw
    }
}

# ── Commands ─────────────────────────────────────────────────────────────────

function Invoke-Create {
    if (-not $Slug -or -not $Name -or -not $Password -or -not $Company) {
        Write-Host "  Error: -Slug, -Name, -Password, and -Company are required for Create" -ForegroundColor Red
        return
    }

    Write-Host "  Creating tenant: $Slug" -ForegroundColor Yellow

    $body = @{
        slug           = $Slug
        display_name   = $Name
        admin_username = $AdminUser
        admin_password = $Password
        company_name   = $Company
    }

    try {
        $result = Invoke-TenantApi -Method POST -Endpoint "/api/v1/admin/tenants" -Body $body
        Write-Host "  Tenant created successfully!" -ForegroundColor Green
        Write-Host ""
        Write-Host "  Tenant Details:" -ForegroundColor Cyan
        Write-Host "    Slug:          $($result.tenant.slug)"
        Write-Host "    Database:      $($result.tenant.db_name)"
        Write-Host "    Agent API Key: $($result.tenant.agent_api_key)"
        Write-Host ""
        Write-Host "  Login Credentials:" -ForegroundColor Cyan
        Write-Host "    Tenant Code:   $Slug"
        Write-Host "    Username:      $AdminUser"
        Write-Host "    Password:      (as provided)"
    }
    catch {
        Write-Host "  Failed to create tenant" -ForegroundColor Red
    }
}

function Invoke-List {
    Write-Host "  Listing all tenants..." -ForegroundColor Yellow

    try {
        $result = Invoke-TenantApi -Method GET -Endpoint "/api/v1/admin/tenants"
        Write-Host ""
        Write-Host "  Total: $($result.total) tenant(s)" -ForegroundColor Cyan
        Write-Host ""

        if ($result.tenants.Count -gt 0) {
            $format = "  {0,-15} {1,-25} {2,-20} {3,-8}"
            Write-Host ($format -f "SLUG", "DISPLAY NAME", "DATABASE", "ACTIVE") -ForegroundColor DarkGray
            Write-Host ("  " + "-" * 70) -ForegroundColor DarkGray
            foreach ($t in $result.tenants) {
                $activeColor = if ($t.is_active) { "Green" } else { "Red" }
                $activeTxt   = if ($t.is_active) { "Yes" } else { "No" }
                Write-Host ("  {0,-15} {1,-25} {2,-20} " -f $t.slug, $t.display_name, $t.db_name) -NoNewline
                Write-Host $activeTxt -ForegroundColor $activeColor
            }
        }
    }
    catch {
        Write-Host "  Failed to list tenants" -ForegroundColor Red
    }
}

function Invoke-Backup {
    if (-not $Slug) {
        Write-Host "  Error: -Slug is required for Backup" -ForegroundColor Red
        return
    }

    Write-Host "  Backing up tenant: $Slug" -ForegroundColor Yellow

    if (-not (Test-Path $BackupDir)) {
        New-Item -Path $BackupDir -ItemType Directory -Force | Out-Null
    }

    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $filename  = "tenant_${Slug}_${timestamp}.sql"
    $filepath  = Join-Path $BackupDir $filename
    $dbName    = "wb_$Slug"

    $env:PGPASSWORD = $PgPassword
    docker exec -e PGPASSWORD=$PgPassword $PgContainer `
        pg_dump -U $PgUser -d $dbName --no-owner --no-acl `
        > $filepath

    $size = (Get-Item $filepath).Length / 1KB
    Write-Host "  Backup created: $filepath ($([math]::Round($size, 1)) KB)" -ForegroundColor Green
}

function Invoke-BackupAll {
    Write-Host "  Backing up all tenants..." -ForegroundColor Yellow

    if (-not (Test-Path $BackupDir)) {
        New-Item -Path $BackupDir -ItemType Directory -Force | Out-Null
    }

    $env:PGPASSWORD = $PgPassword
    $dbs = docker exec -e PGPASSWORD=$PgPassword $PgContainer `
        psql -U $PgUser -d postgres -tAc `
        "SELECT datname FROM pg_database WHERE datname LIKE 'wb_%' ORDER BY datname"

    if (-not $dbs) {
        Write-Host "  No tenant databases found." -ForegroundColor Yellow
        return
    }

    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $count = 0

    foreach ($db in ($dbs -split "`n" | Where-Object { $_.Trim() })) {
        $db = $db.Trim()
        $slug = $db -replace "^wb_", ""
        $filename = "tenant_${slug}_${timestamp}.sql"
        $filepath = Join-Path $BackupDir $filename

        Write-Host "  Backing up $slug... " -NoNewline
        docker exec -e PGPASSWORD=$PgPassword $PgContainer `
            pg_dump -U $PgUser -d $db --no-owner --no-acl `
            > $filepath
        $size = (Get-Item $filepath).Length / 1KB
        Write-Host "OK ($([math]::Round($size, 1)) KB)" -ForegroundColor Green
        $count++
    }

    Write-Host ""
    Write-Host "  Backed up $count tenant(s) to $BackupDir" -ForegroundColor Green
}

function Invoke-Status {
    Write-Host "  System Status" -ForegroundColor Yellow
    Write-Host "  ─────────────────────────────────────" -ForegroundColor DarkGray

    # Docker
    try {
        $pgStatus = docker ps --filter "name=$PgContainer" --format '{{.Status}}' 2>$null
        if ($pgStatus -match "Up") {
            Write-Host "  PostgreSQL:   " -NoNewline; Write-Host "Running" -ForegroundColor Green
        } else {
            Write-Host "  PostgreSQL:   " -NoNewline; Write-Host "Stopped" -ForegroundColor Red
        }
    } catch {
        Write-Host "  PostgreSQL:   " -NoNewline; Write-Host "Docker not available" -ForegroundColor Red
    }

    # Backend health
    try {
        $health = Invoke-RestMethod -Uri "$ApiUrl/api/v1/health" -TimeoutSec 5
        Write-Host "  Backend:      " -NoNewline; Write-Host $health.status -ForegroundColor Green
        $mt = if ($health.multi_tenant) { "Enabled" } else { "Disabled" }
        Write-Host "  Multi-tenant: " -NoNewline; Write-Host $mt -ForegroundColor Cyan
    } catch {
        Write-Host "  Backend:      " -NoNewline; Write-Host "Unreachable" -ForegroundColor Red
    }

    # Count tenant databases
    try {
        $env:PGPASSWORD = $PgPassword
        $count = docker exec -e PGPASSWORD=$PgPassword $PgContainer `
            psql -U $PgUser -d postgres -tAc `
            "SELECT COUNT(*) FROM pg_database WHERE datname LIKE 'wb_%'" 2>$null
        Write-Host "  Tenant DBs:   " -NoNewline; Write-Host $count.Trim() -ForegroundColor Cyan
    } catch {
        Write-Host "  Tenant DBs:   " -NoNewline; Write-Host "?" -ForegroundColor Yellow
    }

    Write-Host ""
}

# ── Main ─────────────────────────────────────────────────────────────────────
Write-Header

switch ($Action) {
    "Create"    { Invoke-Create }
    "List"      { Invoke-List }
    "Backup"    { Invoke-Backup }
    "BackupAll" { Invoke-BackupAll }
    "Status"    { Invoke-Status }
}
