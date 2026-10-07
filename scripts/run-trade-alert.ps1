$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path (Split-Path -Parent $PSScriptRoot)).Path
Set-Location $RepoRoot
$Uv = (Get-Command uv.exe -ErrorAction Stop).Source
$RuntimeLog = Join-Path $env:LOCALAPPDATA 'TradeAlert\runner.log'
$RuntimeDir = Split-Path -Parent $RuntimeLog
New-Item -ItemType Directory -Path $RuntimeDir -Force | Out-Null

while ($true) {
    & $Uv run --python 3.12 python -m trade_alert
    $ExitCode = $LASTEXITCODE

    if ($ExitCode -eq 0) {
        break
    }

    $Stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Add-Content -LiteralPath $RuntimeLog -Value "$Stamp worker exited with code $ExitCode; restarting in 5 seconds."
    Start-Sleep -Seconds 5
}
