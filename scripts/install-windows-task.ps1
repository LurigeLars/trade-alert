$ErrorActionPreference = 'Stop'
$Installer = Join-Path $PSScriptRoot 'install-windows-startup.ps1'
& $Installer
