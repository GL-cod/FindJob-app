# Recherche LinkedIn + APEC du CDI Watcher, lancée par la tâche planifiée « CDI Watcher LinkedIn ».
# S'affiche dans une fenêtre pour que tu voies ce qui se passe, et écrit tout dans logs\linkedin.log.
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Host.UI.RawUI.WindowTitle = "CDI Watcher - recherche LinkedIn + APEC"
New-Item -ItemType Directory -Force -Path "logs" | Out-Null
$Log = Join-Path $Root "logs\linkedin.log"

function Out-Both([string]$line) {
    Write-Host $line
    Add-Content -Path $Log -Value $line -Encoding UTF8
}

Out-Both ""
Out-Both "===== $(Get-Date -Format 'yyyy-MM-dd HH:mm') (tâche planifiée) ====="

# Code et réglages à jour (cdi_search.yaml modifié sur GitHub)
if (Get-Command git -ErrorAction SilentlyContinue) {
    & "$Root\.venv\Scripts\python.exe" -m src.gitsync 2>&1 | ForEach-Object { Out-Both "$_" }
}

$env:CDI_SOURCES      = "linkedin,apec"
$env:CDI_STORE_PATH   = "data\cdi_offers_linkedin.json"
$env:CDI_STATE_PATH   = "data\cdi_state_linkedin.json"
$env:CDI_METRICS_PATH = "logs\cdi_metrics_linkedin.jsonl"
$env:FORCE_RUN        = "1"
$env:PYTHONUTF8       = "1"
$env:PYTHONUNBUFFERED = "1"

& "$Root\.venv\Scripts\python.exe" -m src.cdi_main 2>&1 | ForEach-Object { Out-Both "$_" }
$code = $LASTEXITCODE

Write-Host ""
if ($code -eq 0) {
    Write-Host "Recherche terminée. Les offres retenues sont dans l'application Mes candidatures." -ForegroundColor Green
} else {
    Write-Host "La recherche s'est terminée avec une erreur (voir ci-dessus ou logs\linkedin.log)." -ForegroundColor Red
}
Write-Host "Cette fenêtre se ferme dans 30 secondes."
Start-Sleep -Seconds 30
exit $code
