param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $projectRoot
& $Python -c 'import sys; assert (3,11) <= sys.version_info[:2] < (3,14), "Use 64-bit Python 3.11-3.13"; assert sys.maxsize > 2**32, "Use 64-bit Python"'
if ($LASTEXITCODE -ne 0) { throw 'Python prerequisite failed.' }
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    & $Python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
}
& '.venv\Scripts\python.exe' -m ensurepip --upgrade
if ($LASTEXITCODE -ne 0) { throw 'pip initialization failed.' }
& '.venv\Scripts\python.exe' -m pip install -r requirements.lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& '.venv\Scripts\python.exe' -m pip install --no-deps -e .
if ($LASTEXITCODE -ne 0) { throw 'Project installation failed.' }
if (-not (Test-Path -LiteralPath '.env')) {
    & '.venv\Scripts\python.exe' -m app.cli init-config
    if ($LASTEXITCODE -ne 0) { throw 'Configuration initialization failed.' }
}
Write-Host 'Setup complete. Edit .env and config\symbols.json, then follow docs\MT5_SETUP.md.'
