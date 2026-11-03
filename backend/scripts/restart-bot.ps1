# Restarts the bot (API + worker) and, with -Web, the local dashboard.
# Stop-ScheduledTask only ends the PowerShell wrapper; this also ends the Python/Node processes.
param([switch]$Web)
$ErrorActionPreference = 'Stop'
$tasks = @('BYTEFX-worker', 'BYTEFX-api')
if ($Web) { $tasks += 'BYTEFX-web' }
foreach ($t in $tasks) { Stop-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue }
$procs = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -eq 'python.exe' -and $_.CommandLine -match 'app\.cli (api|worker)') -or
    ($Web -and $_.Name -eq 'node.exe' -and $_.CommandLine -match 'next.*start')
}
$all = Get-CimInstance Win32_Process
$ids = @($procs.ProcessId) + @(($all | Where-Object { $procs.ProcessId -contains $_.ParentProcessId }).ProcessId)
foreach ($id in ($ids | Where-Object { $_ } | Select-Object -Unique)) { Stop-Process -Id $id -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 3
[array]::Reverse($tasks)
foreach ($t in $tasks) { Start-ScheduledTask -TaskName $t }
Start-Sleep -Seconds 8
try { Write-Host ('Bot health: ' + (Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/health -TimeoutSec 10).Content) }
catch { Write-Host 'Bot is still starting; check http://127.0.0.1:8000/health in a few seconds.' }
