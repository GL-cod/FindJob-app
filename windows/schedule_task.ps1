# (Re)crée la tâche planifiée « CDI Watcher LinkedIn ».
# Horaires : lun-ven aux heures listées ci-dessous (modifiables), ou au démarrage du PC si l'heure est passée.
$RunTimes = @("12:05", "19:05")
$TaskName = "CDI Watcher LinkedIn"
$Root = Split-Path -Parent $PSScriptRoot

$runner = Join-Path $Root "windows\run_linkedin.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Normal -File `"$runner`"" -WorkingDirectory $Root
$days = "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"
$triggers = $RunTimes | ForEach-Object { New-ScheduledTaskTrigger -Weekly -DaysOfWeek $days -At $_ }
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers -Settings $settings `
    -Description "Recherche LinkedIn + APEC de l'application Mes candidatures" -Force | Out-Null
Write-Host "Tâche '$TaskName' : du lundi au vendredi à $($RunTimes -join ' et ')." -ForegroundColor Green
