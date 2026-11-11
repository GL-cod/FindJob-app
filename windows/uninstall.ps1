# Supprime la tâche planifiée LinkedIn du CDI Watcher (les fichiers restent).
Unregister-ScheduledTask -TaskName "CDI Watcher LinkedIn" -Confirm:$false -ErrorAction SilentlyContinue
& (Join-Path $PSScriptRoot "stop_app.ps1")
Remove-Item (Join-Path ([Environment]::GetFolderPath("Desktop")) "Mes candidatures.lnk") -ErrorAction SilentlyContinue
Write-Host "Tâche 'CDI Watcher LinkedIn' supprimée. Tu peux ensuite supprimer le dossier du dépôt." -ForegroundColor Green
