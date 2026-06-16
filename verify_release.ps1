$rel = "C:\releases\weighbridge-client-build"
$required = @(
    "backend\weighbridge.exe",
    "backend\setup_dpapi.py",
    "backend\show_fingerprint.py",
    "backend\run_server.py",
    "backend\hardening\secure_setup.ps1",
    "backend\.env.example",
    "backend\.env.template",
    "backend\app\templates\pdf\invoice.html",
    "frontend\dist\index.html",
    "docker-compose.yml",
    "scripts\Deploy-Full.ps1",
    "scripts\Setup-CloudflareTunnel.ps1",
    "scripts\Setup-CloudBackup.ps1",
    "scripts\Backup-ToCloud.ps1",
    "scripts\Verify-Deployment.ps1",
    "scripts\Generate-DeploymentConfig.ps1",
    "scripts\Install-Client.ps1",
    "scripts\install-services.ps1",
    "scripts\nssm.exe",
    "tools\license-generator\generate_license.py",
    "SECURE_DEPLOYMENT_PIPELINE.md",
    "NEW_TEAM_MEMBER_GUIDE.md"
)

Write-Host "`n=== Release Package Verification ===" -ForegroundColor Cyan
Write-Host ""
$pass = 0; $fail = 0
foreach ($f in $required) {
    $path = Join-Path $rel $f
    if (Test-Path $path) {
        $size = [math]::Round((Get-Item $path).Length / 1KB, 1)
        Write-Host "  [OK]   $f ($size KB)" -ForegroundColor Green
        $pass++
    } else {
        Write-Host "  [MISS] $f" -ForegroundColor Red
        $fail++
    }
}
Write-Host ""
$total = (Get-ChildItem $rel -Recurse | Measure-Object -Property Length -Sum).Sum
$totalMB = [math]::Round($total / 1MB, 1)
Write-Host "  Total: $pass/$($pass + $fail) files, $totalMB MB"
if ($fail -eq 0) {
    Write-Host "  RELEASE PACKAGE IS COMPLETE!" -ForegroundColor Green
} else {
    Write-Host "  $fail file(s) missing!" -ForegroundColor Red
}
Write-Host ""
