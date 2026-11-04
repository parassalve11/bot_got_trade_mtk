# Starts the dashboard (frontend) on http://localhost:72 for this PC (change with -Port).
# Rebuilds, then serves; uses frontend\.env.local (BACKEND_URL=http://127.0.0.1:8000).
param([int]$Port = 72)
$ErrorActionPreference = 'Stop'
$frontend = (Resolve-Path (Join-Path $PSScriptRoot '..\..\frontend')).Path
Set-Location -LiteralPath $frontend
if (-not (Test-Path -LiteralPath 'node_modules')) {
    & npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw 'npm ci failed' }
}
# Rebuild at every start so the dashboard always matches the latest code (about 20 s).
& npm.cmd run build
if ($LASTEXITCODE -ne 0) { throw 'Dashboard build failed' }
# Serve; restart automatically 10 s after the server stops for any reason.
while ($true) {
    & npx.cmd next start -H 127.0.0.1 -p $Port
    Start-Sleep -Seconds 10
}
