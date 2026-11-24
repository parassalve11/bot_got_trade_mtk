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
# Build only when there is no finished build yet (after frontend changes run `npm run build`
# yourself). Rebuilding at every start hung at logon: Next.js 16.4.4 ends the build with a
# "security advisory" error after compiling. A build that hangs is stopped after 5 minutes.
if (-not (Test-Path -LiteralPath '.next\BUILD_ID')) {
    $build = Start-Process -FilePath 'npm.cmd' -ArgumentList 'run', 'build' -NoNewWindow -PassThru
    if (-not $build.WaitForExit(300000)) { & taskkill.exe /T /F /PID $build.Id | Out-Null }
}
if (-not (Test-Path -LiteralPath '.next\BUILD_ID')) { throw 'No dashboard build to serve' }
# Serve; restart automatically 10 s after the server stops for any reason.
while ($true) {
    & npx.cmd next start -H 127.0.0.1 -p $Port
    Start-Sleep -Seconds 10
}
