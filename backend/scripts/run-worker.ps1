# Bot worker (the only MT5 process). Restarts automatically 10 s after it stops for any reason.
# Safe to restart: the worker reconciles every uncertain order with MT5 before trading again,
# and its OS lock prevents two workers from running at once.
$ErrorActionPreference = 'Continue'
Set-Location -LiteralPath (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
while ($true) {
    & '.venv\Scripts\python.exe' -m app.cli worker
    Start-Sleep -Seconds 10
}
