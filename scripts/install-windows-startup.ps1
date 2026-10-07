$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path (Split-Path -Parent $PSScriptRoot)).Path
$Runner = (Resolve-Path (Join-Path $PSScriptRoot 'run-trade-alert.ps1')).Path
$PowerShell = (Get-Command powershell.exe -ErrorAction Stop).Source
$Startup = [Environment]::GetFolderPath('Startup')
if ([string]::IsNullOrWhiteSpace($Startup)) {
    throw 'Could not resolve the current user Startup folder.'
}

$ShortcutPath = Join-Path $Startup 'Trade Alert.lnk'
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $PowerShell
$Shortcut.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Runner`""
$Shortcut.WorkingDirectory = $RepoRoot
$Shortcut.WindowStyle = 7
$Shortcut.Description = 'Trade Alert local news notifier'
$Shortcut.Save()

$AlreadyRunning = $false
try {
    $AlreadyRunning = $null -ne (
        Get-CimInstance Win32_Process -ErrorAction Stop |
            Where-Object { $_.CommandLine -match '[\\/]run-trade-alert\.ps1' } |
            Select-Object -First 1
    )
}
catch {
    Write-Warning "Could not inspect running processes; the startup shortcut was still installed."
}

if (-not $AlreadyRunning) {
    Start-Process -FilePath $PowerShell -ArgumentList @(
        '-NoProfile',
        '-WindowStyle', 'Hidden',
        '-ExecutionPolicy', 'Bypass',
        '-File', $Runner
    ) -WorkingDirectory $RepoRoot
}

Write-Host "Installed per-user startup shortcut: $ShortcutPath"
Write-Host "Trade Alert starts at Windows logon without administrator rights."
if ($AlreadyRunning) {
    Write-Host 'Trade Alert was already running; no duplicate process was started.'
}
else {
    Write-Host 'Trade Alert started now.'
}
