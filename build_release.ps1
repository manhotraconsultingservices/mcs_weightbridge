$ErrorActionPreference = "Continue"
Set-Location "C:\Users\Admin\Documents\workspace_Weighbridge"
$rel = "C:\releases\weighbridge-client-build"

# Create dirs
New-Item -ItemType Directory -Path "$rel\backend\hardening" -Force | Out-Null
New-Item -ItemType Directory -Path "$rel\backend\app\templates" -Force | Out-Null
New-Item -ItemType Directory -Path "$rel\frontend" -Force | Out-Null
New-Item -ItemType Directory -Path "$rel\scripts" -Force | Out-Null
New-Item -ItemType Directory -Path "$rel\tools\license-generator" -Force | Out-Null

# Backend utilities
Copy-Item "backend\setup_dpapi.py"             "$rel\backend\" -Force
Copy-Item "backend\show_fingerprint.py"        "$rel\backend\" -Force
Copy-Item "backend\requirements.txt"           "$rel\backend\" -Force
Copy-Item "backend\run_server.py"              "$rel\backend\" -Force
Copy-Item "backend\hardening\secure_setup.ps1" "$rel\backend\hardening\" -Force
Copy-Item "backend\.env.example"               "$rel\backend\" -Force

# Templates
xcopy "backend\app\templates" "$rel\backend\app\templates\" /E /I /Y /Q

# Frontend dist
xcopy "frontend\dist" "$rel\frontend\dist\" /E /I /Y /Q

# Scripts
xcopy "scripts" "$rel\scripts\" /E /I /Y /Q

# Docker compose
Copy-Item "docker-compose.yml" "$rel\" -Force

# License generator
Copy-Item "tools\license-generator\generate_license.py" "$rel\tools\license-generator\" -Force

# NSSM
if (Test-Path "tools\nssm.exe") {
    Copy-Item "tools\nssm.exe" "$rel\scripts\" -Force
}

# Docs
Copy-Item "SECURE_DEPLOYMENT_PIPELINE.md" "$rel\" -Force
Copy-Item "NEW_TEAM_MEMBER_GUIDE.md" "$rel\" -Force

# .env template
@"
DATABASE_URL=postgresql+asyncpg://weighbridge:REPLACE_ME@localhost:5432/weighbridge
DATABASE_URL_SYNC=postgresql+psycopg://weighbridge:REPLACE_ME@localhost:5432/weighbridge
SECRET_KEY=REPLACE_ME
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=480
PRIVATE_DATA_KEY=REPLACE_ME
"@ | Set-Content "$rel\backend\.env.template" -Encoding UTF8

Write-Host "`nRelease files copied to: $rel" -ForegroundColor Green
