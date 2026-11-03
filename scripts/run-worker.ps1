$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
& '.venv\Scripts\python.exe' -m app.cli worker
exit $LASTEXITCODE
