$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Startup = [Environment]::GetFolderPath('Startup')
$ShortcutPath = Join-Path $Startup 'Trade Alert.lnk'
if (Test-Path -LiteralPath $ShortcutPath) {
    Remove-Item -LiteralPath $ShortcutPath -Force
}

try {
    $Processes = Get-CimInstance Win32_Process -ErrorAction Stop |
        Where-Object {
            $_.ProcessId -ne $PID -and (
                $_.CommandLine -match '[\\/]run-trade-alert\.ps1' -or
                $_.CommandLine -match '(?i)-m\s+trade_alert(?:\s|$)'
            )
        }
    foreach ($Process in $Processes) {
        Stop-Process -Id $Process.ProcessId -Force -ErrorAction SilentlyContinue
    }
}
catch {
    Write-Warning 'Could not inspect/stop Trade Alert processes automatically.'
}

Write-Host "Removed per-user startup shortcut: $ShortcutPath"
