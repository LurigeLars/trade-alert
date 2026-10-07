$ErrorActionPreference = 'Stop'

$Uninstaller = Join-Path $PSScriptRoot 'uninstall-windows-startup.ps1'
& $Uninstaller

try {
    $Task = Get-ScheduledTask -TaskName 'Trade Alert' -ErrorAction SilentlyContinue
    if ($null -ne $Task) {
        Stop-ScheduledTask -TaskName 'Trade Alert' -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName 'Trade Alert' -Confirm:$false -ErrorAction SilentlyContinue
        Write-Host "Removed legacy Scheduled Task: Trade Alert"
    }
}
catch {
    Write-Warning 'Could not inspect/remove the legacy Scheduled Task; this does not affect the per-user startup installation.'
}
