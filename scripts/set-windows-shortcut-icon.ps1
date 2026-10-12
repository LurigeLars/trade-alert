$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path (Split-Path -Parent $PSScriptRoot)).Path
$Python = Join-Path $RepoRoot '.venv\Scripts\python.exe'
$Pythonw = Join-Path $RepoRoot '.venv\Scripts\pythonw.exe'

if (-not (Test-Path -LiteralPath $Python -PathType Leaf) -or
    -not (Test-Path -LiteralPath $Pythonw -PathType Leaf)) {
    throw 'Trade Alert virtual environment missing. Install Trade Alert first.'
}

# Generated icon is stable, local and independent of the transient unread badge.
$IconPath = Join-Path $env:LOCALAPPDATA 'TradeAlert\trade-alert.ico'
$PythonCode = 'import sys; from trade_alert.tray import save_static_shortcut_icon; save_static_shortcut_icon(sys.argv[1])'
& $Python -c $PythonCode $IconPath
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $IconPath -PathType Leaf)) {
    throw 'Unable to generate Trade Alert shortcut icon.'
}

$Startup = [Environment]::GetFolderPath('Startup')
if ([string]::IsNullOrWhiteSpace($Startup)) {
    throw 'Could not resolve Windows Startup folder.'
}
$StartupLink = Join-Path $Startup 'Trade Alert.lnk'
if (-not (Test-Path -LiteralPath $StartupLink -PathType Leaf)) {
    throw 'Startup shortcut missing. Run install-windows-startup.ps1 first.'
}

$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($StartupLink)
if ($Shortcut.TargetPath -ine $Pythonw -or
    $Shortcut.Arguments.Trim() -ne '-m trade_alert') {
    throw 'Startup shortcut does not point to the expected Trade Alert executable.'
}
$Shortcut.IconLocation = "$IconPath,0"
$Shortcut.Save()
Write-Host "Startup shortcut icon updated: $StartupLink"

# Windows can keep a separate copy when a shortcut is pinned to the taskbar.
# Only change links with exactly the same Python target and Trade Alert args.
$PinnedFolder = Join-Path $env:APPDATA 'Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar'
if (Test-Path -LiteralPath $PinnedFolder -PathType Container) {
    Get-ChildItem -LiteralPath $PinnedFolder -Filter '*.lnk' -File | ForEach-Object {
        $Pinned = $Shell.CreateShortcut($_.FullName)
        if ($Pinned.TargetPath -ieq $Pythonw -and
            $Pinned.Arguments.Trim() -eq '-m trade_alert') {
            $Pinned.IconLocation = "$IconPath,0"
            $Pinned.Save()
            Write-Host "Pinned taskbar shortcut icon updated: $($_.Name)"
        }
    }
}

Write-Host "Static Trade Alert icon: $IconPath"
Write-Host 'If the old taskbar icon stays cached, unpin it and pin the updated shortcut again.'
