$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
& '.\tools\caddy.exe' run --config '.\deploy\Caddyfile' --adapter caddyfile
exit $LASTEXITCODE
