# Examples:  .\register-tasks.ps1                          (bot: api + worker)
#            .\register-tasks.ps1 -Roles web               (dashboard on http://localhost:72)
#            .\register-tasks.ps1 -Roles api,worker,web    (everything; safe to re-run)
#
# Tasks run headless (conhost --headless): no window or Windows Terminal tab that could be closed.
# Triggers: at logon, plus a watchdog every 5 minutes that starts any task that is not running.
param([string[]]$Roles = @('api', 'worker'), [switch]$IncludeCaddy)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$taskUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $taskUser -LogonType Interactive -RunLevel Limited
$atLogon = New-ScheduledTaskTrigger -AtLogOn -User $taskUser
$watchdog = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
$settings = New-ScheduledTaskSettingsSet -Hidden -StartWhenAvailable -RestartCount 99 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$roles = @($Roles)
if ($IncludeCaddy) { $roles += 'caddy' }
foreach ($role in $roles) {
    if ($role -notin @('api', 'worker', 'web', 'caddy')) { throw "Unknown role: $role" }
}
foreach ($role in $roles) {
    $scriptPath = Join-Path $projectRoot "scripts\run-$role.ps1"
    $arguments = '--headless powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $scriptPath + '"'
    $action = New-ScheduledTaskAction -Execute 'conhost.exe' -Argument $arguments -WorkingDirectory $projectRoot
    Register-ScheduledTask -TaskName "BYTEFX-$role" -Action $action -Trigger @($atLogon, $watchdog) -Principal $principal -Settings $settings -Description 'BYTEFX: headless, starts at logon, watchdog every 5 minutes' -Force -ErrorAction Stop | Out-Null
}
Write-Host ('Registered: ' + (($roles | ForEach-Object { "BYTEFX-$_" }) -join ', ') + '. Headless; start at logon; watchdog every 5 minutes.')
Write-Host 'A logged-in Windows session is required (lock the PC instead of signing out).'
