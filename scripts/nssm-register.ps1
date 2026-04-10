#Requires -RunAsAdministrator
<#
.SYNOPSIS
  Backwards-compatible redirect — use install-services.ps1 instead.
  This script is kept for compatibility and simply forwards to the new installer.
#>

param(
    [string]$InstallDir  = "",
    [string]$BackendPort = "9001",
    [switch]$Unregister
)

$newScript = Join-Path (Split-Path $MyInvocation.MyCommand.Path) "install-services.ps1"

if ($Unregister) {
    & $newScript -Unregister
} else {
    if ($InstallDir) {
        & $newScript -ProjectDir $InstallDir
    } else {
        & $newScript
    }
}
