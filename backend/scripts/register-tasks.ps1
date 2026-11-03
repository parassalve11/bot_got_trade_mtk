param([switch]$IncludeCaddy)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$taskUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $taskUser -LogonType Interactive -RunLevel Limited
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $taskUser
$settings = New-ScheduledTaskSettingsSet -Hidden -StartWhenAvailable -RestartCount 99 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$roles = @('api', 'worker')
if ($IncludeCaddy) { $roles += 'caddy' }
foreach ($role in $roles) {
    $scriptPath = Join-Path $projectRoot "scripts\run-$role.ps1"
    $arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -File "' + $scriptPath + '"'
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments -WorkingDirectory $projectRoot
    Register-ScheduledTask -TaskName "BYTEFX-$role" -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'BYTEFX: runs in the same logged-in Windows user session as MT5' -ErrorAction Stop | Out-Null
}
Write-Host 'Tasks registered for the next user logon. Start them in Task Scheduler when configuration is ready.'
Write-Host 'A logged-in MT5 user session is required; a reboot alone is not sufficient. Disconnect RDP instead of signing out.'
