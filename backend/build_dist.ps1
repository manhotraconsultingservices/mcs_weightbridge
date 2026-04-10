##############################################################################
#  Weighbridge ERP — Production Binary Builder (Nuitka)
#
#  Compiles the Python backend to a native Windows executable.
#  The resulting .exe contains no .py or .pyc source files — reverse
#  engineering requires disassembly of compiled C code (Nuitka output).
#
#  Requirements (run once):
#    pip install nuitka ordered-set zstandard
#
#  Usage:
#    powershell -ExecutionPolicy Bypass -File build_dist.ps1
#
#  Output:
#    dist\weighbridge_server.exe   (standalone, ~60-100 MB)
##############################################################################

param(
    [string]$PythonExe = "venv\Scripts\python.exe",
    [string]$OutDir    = "dist",
    [switch]$Clean
)

Set-Location $PSScriptRoot
$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "  Weighbridge ERP - Nuitka Production Build" -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host ""

# ── Pre-flight checks ────────────────────────────────────────────────────────

if (-not (Test-Path $PythonExe)) {
    Write-Host "ERROR: Python not found at '$PythonExe'" -ForegroundColor Red
    Write-Host "       Create a venv first: python -m venv venv && venv\Scripts\pip install -r requirements.txt"
    exit 1
}

# Check Nuitka
$nuitkaCheck = & $PythonExe -c "import nuitka; print(nuitka.__version__)" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Nuitka not installed." -ForegroundColor Red
    Write-Host "       Run: $PythonExe -m pip install nuitka ordered-set zstandard"
    exit 1
}
Write-Host "  Nuitka version : $nuitkaCheck" -ForegroundColor Green

# ── Clean previous build ─────────────────────────────────────────────────────

if ($Clean -and (Test-Path $OutDir)) {
    Write-Host "  Cleaning previous build..."
    Remove-Item -Recurse -Force $OutDir
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

# ── Nuitka compile ────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "  Compiling backend to native binary (this takes 3-10 minutes)..." -ForegroundColor Yellow
Write-Host ""

$NuitkaArgs = @(
    "-m", "nuitka",
    "--standalone",                         # Bundle all dependencies
    "--onefile",                            # Single .exe output
    "--output-dir=$OutDir",
    "--output-filename=weighbridge_server", # Output name (no .exe — Nuitka adds it)

    # ── Security: strip debug info ────────────────────────────────────────────
    "--python-flag=no_docstrings",          # Remove all docstrings from bytecode
    "--python-flag=no_annotations",         # Remove type annotations
    "--python-flag=-OO",                    # Optimise bytecode (strips asserts + docstrings)

    # ── Silence warnings, optimise size ──────────────────────────────────────
    "--assume-yes-for-downloads",           # Auto-download Nuitka dependencies
    "--remove-output",                      # Remove build directory after packaging
    "--warn-unusual-code",

    # ── Include required packages ─────────────────────────────────────────────
    # FastAPI / Starlette
    "--include-package=fastapi",
    "--include-package=starlette",
    "--include-package=uvicorn",

    # Database
    "--include-package=sqlalchemy",
    "--include-package=asyncpg",
    "--include-package=psycopg",

    # Auth & crypto
    "--include-package=jose",
    "--include-package=passlib",
    "--include-package=cryptography",
    "--include-package=bcrypt",

    # Pydantic
    "--include-package=pydantic",
    "--include-package=pydantic_settings",

    # Other app deps
    "--include-package=httpx",
    "--include-package=PIL",
    "--include-package=jinja2",
    "--include-package=xhtml2pdf",
    "--include-package=openpyxl",

    # App itself
    "--include-package=app",

    # ── Data files to bundle ──────────────────────────────────────────────────
    "--include-data-dir=app/templates=app/templates",

    # Entry point
    "run.py"
)

Write-Host "  Running: python $($NuitkaArgs -join ' ')"
Write-Host ""

& $PythonExe @NuitkaArgs

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "ERROR: Nuitka compilation failed (exit code $LASTEXITCODE)" -ForegroundColor Red
    exit $LASTEXITCODE
}

# ── Post-build ────────────────────────────────────────────────────────────────

$exe = Get-Item "$OutDir\weighbridge_server.exe" -ErrorAction SilentlyContinue
if ($exe) {
    $sizeMB = [math]::Round($exe.Length / 1MB, 1)
    Write-Host ""
    Write-Host "========================================================" -ForegroundColor Green
    Write-Host "  BUILD SUCCESSFUL" -ForegroundColor Green
    Write-Host "  Output : $($exe.FullName)" -ForegroundColor Green
    Write-Host "  Size   : $sizeMB MB" -ForegroundColor Green
    Write-Host "========================================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Security notes:" -ForegroundColor Cyan
    Write-Host "    - No Python source or bytecode in the output binary" -ForegroundColor Cyan
    Write-Host "    - All docstrings and type annotations stripped" -ForegroundColor Cyan
    Write-Host "    - Reverse engineering requires native code disassembly" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Next steps:" -ForegroundColor Yellow
    Write-Host "    1. Copy weighbridge_server.exe to client machine" -ForegroundColor Yellow
    Write-Host "    2. Run setup_dpapi.py on client to encrypt secrets" -ForegroundColor Yellow
    Write-Host "    3. Run hardening\secure_setup.ps1 for OS hardening" -ForegroundColor Yellow
    Write-Host "    4. Register as Windows service using nssm-register.ps1" -ForegroundColor Yellow
} else {
    Write-Host "WARNING: Build appeared to succeed but .exe not found." -ForegroundColor Yellow
}
