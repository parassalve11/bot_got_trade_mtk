# Examples:  .egister-tasks.ps1                (bot: api + worker)
#            .egister-tasks.ps1 -Roles web     (dashboard on http://localhost:3000)
#            .egister-tasks.ps1 -Roles api,worker,web
param([string[]]$Roles = @('api', 'worker'), [switch]$IncludeCaddy)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$taskUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $taskUser -LogonType Interactive -RunLevel Limited
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $taskUser
$settings = New-ScheduledTaskSettingsSet -Hidden -StartWhenAvailable -RestartCount 99 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$roles = @($Roles)
if ($IncludeCaddy) { $roles += 'caddy' }
foreach ($role in $roles) {
    if ($role -notin @('api', 'worker', 'web', 'caddy')) { throw "Unknown role: $role" }
}
foreach ($role in $roles) {
    $scriptPath = Join-Path $projectRoot "scripts\run-$role.ps1"
    $arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -File "' + $scriptPath + '"'
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments -WorkingDirectory $projectRoot
    Register-ScheduledTask -TaskName "BYTEFX-$role" -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'BYTEFX: runs in the same logged-in Windows user session as MT5' -Force -ErrorAction Stop | Out-Null
}
Write-Host ('Registered: ' + (($roles | ForEach-Object { "BYTEFX-$_" }) -join ', ') + '. They start at every Windows logon.')
Write-Host 'A logged-in MT5 user session is required; a reboot alone is not sufficient. Disconnect RDP instead of signing out.'
