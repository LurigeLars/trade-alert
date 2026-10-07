$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path (Split-Path -Parent $PSScriptRoot)).Path
Set-Location $RepoRoot

$Uv = (Get-Command uv.exe -ErrorAction Stop).Source
$Python = Join-Path $RepoRoot '.venv\Scripts\python.exe'
$Pythonw = Join-Path $RepoRoot '.venv\Scripts\pythonw.exe'

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    & $Uv venv --python 3.12 .venv
    if ($LASTEXITCODE -ne 0) {
        throw "uv venv failed with exit code $LASTEXITCODE"
    }
}

& $Uv pip install --python $Python --editable .
if ($LASTEXITCODE -ne 0) {
    throw "uv pip install failed with exit code $LASTEXITCODE"
}

if (-not (Test-Path -LiteralPath $Pythonw -PathType Leaf)) {
    throw "pythonw.exe was not created at $Pythonw"
}

$Startup = [Environment]::GetFolderPath('Startup')
if ([string]::IsNullOrWhiteSpace($Startup)) {
    throw 'Could not resolve the current user Startup folder.'
}

$ShortcutPath = Join-Path $Startup 'Trade Alert.lnk'
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $Pythonw
$Shortcut.Arguments = '-m trade_alert'
$Shortcut.WorkingDirectory = $RepoRoot
$Shortcut.WindowStyle = 7
$Shortcut.Description = 'Trade Alert tray app'
$Shortcut.Save()

# Stop the legacy PowerShell runner and any old Trade Alert worker before replacing it.
try {
    $Legacy = Get-CimInstance Win32_Process -ErrorAction Stop |
        Where-Object {
            $_.ProcessId -ne $PID -and (
                $_.CommandLine -match '[\\/]run-trade-alert\.ps1' -or
                $_.CommandLine -match '(?i)-m\s+trade_alert(?:\s|$)'
            )
        }
    foreach ($Process in $Legacy) {
        Stop-Process -Id $Process.ProcessId -Force -ErrorAction SilentlyContinue
    }
}
catch {
    Write-Warning 'Could not inspect old Trade Alert processes; the new startup shortcut was still installed.'
}

Start-Process -FilePath $Pythonw -ArgumentList @('-m', 'trade_alert') -WorkingDirectory $RepoRoot

Write-Host "Installed per-user tray startup: $ShortcutPath"
Write-Host "Trade Alert started with pythonw.exe; no console window should remain open."
Write-Host "Look for the Trade Alert icon in the notification area beside the clock."
