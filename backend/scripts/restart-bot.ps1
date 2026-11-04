# Restarts the bot (API + worker) and, with -Web, the local dashboard.
# Stops the scheduled tasks, their self-restarting wrapper loops (conhost/powershell running
# run-*.ps1) and the Python/Node programs, then starts the tasks again.
param([switch]$Web)
$ErrorActionPreference = 'Stop'
$roles = @('worker', 'api')
if ($Web) { $roles += 'web' }
$pattern = 'run-(' + ($roles -join '|') + ')\.ps1'
foreach ($r in $roles) { Stop-ScheduledTask -TaskName "BYTEFX-$r" -ErrorAction SilentlyContinue }

function Stop-Matching([scriptblock]$filter) {
    Get-CimInstance Win32_Process | Where-Object $filter |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}
# 1) wrapper loops first, so nothing respawns
Stop-Matching { $_.Name -in @('conhost.exe', 'powershell.exe') -and $_.CommandLine -match $pattern }
# 2) the programs themselves
Stop-Matching { $_.Name -eq 'python.exe' -and $_.CommandLine -match 'app\.cli (api|worker)' }
if ($Web) { Stop-Matching { $_.Name -eq 'node.exe' -and $_.CommandLine -match 'next.*start' } }
Start-Sleep -Seconds 3

$start = @('api', 'worker')
if ($Web) { $start += 'web' }
foreach ($r in $start) { Start-ScheduledTask -TaskName "BYTEFX-$r" }
Start-Sleep -Seconds 8
try { Write-Host ('Bot health: ' + (Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/health -TimeoutSec 10).Content) }
catch { Write-Host 'Bot is still starting; check http://127.0.0.1:8000/health in a few seconds.' }
