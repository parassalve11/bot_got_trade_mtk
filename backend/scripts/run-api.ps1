# Bot API (FastAPI on 127.0.0.1:8000). Restarts automatically 10 s after it stops for any reason.
$ErrorActionPreference = 'Continue'
Set-Location -LiteralPath (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
while ($true) {
    & '.venv\Scripts\python.exe' -m app.cli api
    Start-Sleep -Seconds 10
}
