$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot
uv run --python 3.12 --with mcp==2.2.0 python -m trade_alert
