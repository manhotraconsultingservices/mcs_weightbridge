#Requires -RunAsAdministrator
param()
Set-StrictMode -Off
$ErrorActionPreference = "Stop"

$AppDir       = "C:\Users\Admin\Documents\workspace_Weighbridge"
$Nssm         = "$AppDir\tools\nssm.exe"
$BackendDir   = "$AppDir\backend"
$FrontendDist = "$AppDir\frontend\dist"
$VenvDir      = "$BackendDir\venv"
$LogsDir      = "$AppDir\logs"
$Python311    = "C:\Program Files\Python311\python.exe"

function Write-Step($msg) { Write-Host "" ; Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-OK($msg)   { Write-Host "    [OK] $msg" -ForegroundColor Green }
function Write-Fail($msg) { Write-Host "    [!!] $msg" -ForegroundColor Red ; exit 1 }

Write-Host ""
Write-Host "============================================" -ForegroundColor Yellow
Write-Host "  Weighbridge Service Fix" -ForegroundColor Yellow
Write-Host "============================================" -ForegroundColor Yellow

# --- Step 1: Install Python 3.11 system-wide ---
Write-Step "Step 1: Checking for system-wide Python 3.11..."

if (Test-Path $Python311) {
    $ver = & $Python311 --version 2>&1
    Write-OK "Found: $ver"
} else {
    Write-Host "    Not found. Downloading Python 3.11.9 installer..." -ForegroundColor Yellow
    $Installer = "$env:TEMP\python-3.11.9-amd64.exe"
    $Url = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $ProgressPreference = "SilentlyContinue"
    Invoke-WebRequest -Uri $Url -OutFile $Installer -UseBasicParsing
    Write-Host "    Installing (takes ~2 min)..." -ForegroundColor Yellow
    $proc = Start-Process -FilePath $Installer `
        -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_pip=1 Include_launcher=0" `
        -Wait -PassThru
    if ($proc.ExitCode -ne 0) { Write-Fail "Python installer failed (exit $($proc.ExitCode))" }
    if (-not (Test-Path $Python311)) { Write-Fail "Installed but not found at $Python311" }
    Write-OK "Python 3.11 installed."
}

# --- Step 2: Create virtualenv ---
Write-Step "Step 2: Creating virtualenv..."

$VenvPython = "$VenvDir\Scripts\python.exe"
$VenvPip    = "$VenvDir\Scripts\pip.exe"

if (Test-Path $VenvPython) {
    Write-OK "Virtualenv already exists."
} else {
    & $Python311 -m venv $VenvDir
    if (-not (Test-Path $VenvPython)) { Write-Fail "venv creation failed." }
    Write-OK "Virtualenv created."
}

# --- Step 3: Install packages ---
Write-Step "Step 3: Installing Python packages (3-5 min first run)..."

& $VenvPython -m pip install --quiet --upgrade pip 2>$null
& $VenvPython -m pip install -r "$BackendDir\requirements.txt"
if ($LASTEXITCODE -ne 0) { Write-Fail "pip install failed." }

$test = & $VenvPython -c "import fastapi, uvicorn, sqlalchemy, xhtml2pdf; print('OK')" 2>&1
if ($test -ne "OK") { Write-Fail "Import test failed: $test" }
Write-OK "Packages installed and verified."

# --- Step 4: Stop services ---
Write-Step "Step 4: Stopping services..."
Stop-Service WeighbridgeBackend  -ErrorAction SilentlyContinue -Force 2>$null
Stop-Service WeighbridgeFrontend -ErrorAction SilentlyContinue -Force 2>$null
Start-Sleep 2
Write-OK "Services stopped."

# --- Step 5: Reconfigure WeighbridgeBackend ---
Write-Step "Step 5: Reconfiguring WeighbridgeBackend..."

& $Nssm set WeighbridgeBackend Application    $VenvPython
& $Nssm set WeighbridgeBackend AppParameters  "-m uvicorn app.main:app --host 0.0.0.0 --port 9001 --workers 2"
& $Nssm set WeighbridgeBackend AppDirectory   $BackendDir
& $Nssm set WeighbridgeBackend AppRestartDelay        3000
& $Nssm set WeighbridgeBackend Start                 SERVICE_AUTO_START
# Graceful shutdown: send Ctrl+C and wait 10s so serial port closes cleanly
# This prevents the CH340 USB-serial driver from getting stuck after service stop
& $Nssm set WeighbridgeBackend AppStopMethodConsole  10000
& $Nssm set WeighbridgeBackend AppStopMethodWindow   5000
& $Nssm set WeighbridgeBackend AppStopMethodThreads  5000

# Load .env into service environment
$envVars = Get-Content "$BackendDir\.env" -ErrorAction SilentlyContinue |
    Where-Object { $_ -match "^\w" -and $_ -notmatch "^#" } |
    ForEach-Object { $_.Trim() }
if ($envVars) {
    $envBlock = $envVars -join [char]10
    & $Nssm set WeighbridgeBackend AppEnvironmentExtra $envBlock
}
Write-OK "WeighbridgeBackend reconfigured."

# --- Step 6: Reconfigure WeighbridgeFrontend ---
Write-Step "Step 6: Reconfiguring WeighbridgeFrontend..."

$frontParams = "-m http.server 9000 --directory " + $FrontendDist
& $Nssm set WeighbridgeFrontend Application   $VenvPython
& $Nssm set WeighbridgeFrontend AppParameters $frontParams
& $Nssm set WeighbridgeFrontend AppDirectory  $FrontendDist
& $Nssm set WeighbridgeFrontend Start         SERVICE_AUTO_START
Write-OK "WeighbridgeFrontend reconfigured."

# --- Step 7: Ensure logs dir ---
New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null

# --- Step 8: Start services ---
Write-Step "Step 8: Starting services..."

Start-Service WeighbridgeBackend
Start-Sleep 10
$bs = (Get-Service WeighbridgeBackend).Status
if ($bs -ne "Running") {
    Get-Content "$LogsDir\backend_stderr.log" -Tail 20 -ErrorAction SilentlyContinue
    Write-Fail "WeighbridgeBackend failed to start (status: $bs). Check $LogsDir\backend_stderr.log"
}
Write-OK "WeighbridgeBackend is Running."

Start-Service WeighbridgeFrontend
Start-Sleep 3
$fs = (Get-Service WeighbridgeFrontend).Status
Write-OK "WeighbridgeFrontend status: $fs"

# --- Step 9: Health check ---
Write-Step "Step 9: Health check..."
Start-Sleep 5

try {
    $resp = Invoke-RestMethod "http://127.0.0.1:9001/api/v1/auth/login" `
        -Method Post `
        -Body "username=admin&password=admin123" `
        -ContentType "application/x-www-form-urlencoded" `
        -ErrorAction Stop
    if ($resp.access_token) { Write-OK "Backend API OK - login successful." }
} catch {
    Write-Host "    Health check failed: $_" -ForegroundColor Yellow
    Write-Host "    Service may still be starting. Try http://127.0.0.1:9001 in 30 seconds." -ForegroundColor Yellow
}

# --- Done ---
Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  Fix complete!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Backend  : http://127.0.0.1:9001"
Write-Host "  Frontend : http://127.0.0.1:9000"
Write-Host ""
Write-Host "  Both services AUTO-START on every reboot."
Write-Host "  No manual action required after restart."
Write-Host ""
