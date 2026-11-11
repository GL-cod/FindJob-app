# Ouvre l'application « Mes candidatures » dans sa propre fenêtre.
# -Restart : redémarre seulement le serveur (bouton « Mettre à jour » de l'application) ;
# la fenêtre déjà ouverte se reconnecte toute seule.
param([switch]$Restart)
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Port = 8765
$Url = "http://127.0.0.1:$Port"
New-Item -ItemType Directory -Force -Path "logs" | Out-Null
$ServerLog = Join-Path $Root "logs\app_server.log"
$ServerErr = Join-Path $Root "logs\app_server_err.log"

function Test-Up {
    try { (Invoke-WebRequest -Uri "$Url/_stcore/health" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200 } catch { $false }
}

function Show-Error([string]$msg) {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show($msg, "Mes candidatures", "OK", "Error") | Out-Null
}

$python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Show-Error "Python de l'application introuvable ($python).`nRelance l'installation : windows\setup.ps1"
    exit 1
}

if ($Restart) {
    Start-Transcript -Path (Join-Path $Root "logs\restart.log") -Force | Out-Null
    Start-Sleep -Seconds 2   # laisse la page afficher son message
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
        Where-Object { $_.CommandLine -match "streamlit" -and $_.CommandLine -match "dashboard.py" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
    for ($i = 0; $i -lt 20 -and (Test-Up); $i++) { Start-Sleep -Milliseconds 500 }
}

if (-not (Test-Up)) {
    # Dépendances à jour (nouvelle fonction = parfois un nouveau paquet) ; rapide si rien ne manque
    & $python -m pip install --quiet --disable-pip-version-check -r requirements.txt -r requirements-app.txt 2>&1 | Out-Null
    # Serveur lancé sans fenêtre ; sa sortie va dans logs\app_server*.log
    $env:PYTHONUTF8 = "1"
    Start-Process -FilePath $python -WorkingDirectory $Root -WindowStyle Hidden `
        -RedirectStandardOutput $ServerLog -RedirectStandardError $ServerErr -ArgumentList @(
            "-m", "streamlit", "run", "app\dashboard.py",
            "--server.port", "$Port", "--server.headless", "true", "--server.address", "127.0.0.1",
            "--browser.gatherUsageStats", "false"
        )
    for ($i = 0; $i -lt 90 -and -not (Test-Up); $i++) { Start-Sleep -Milliseconds 500 }
    if (-not (Test-Up)) {
        $tail = @($ServerErr, $ServerLog) | Where-Object { Test-Path $_ } | ForEach-Object { Get-Content $_ -Tail 10 }
        $tail = if ($tail) { $tail -join "`n" } else { "(journal vide)" }
        Show-Error "Le serveur de l'application n'a pas démarré.`n`nFin du journal (logs\app_server*.log) :`n$tail"
        exit 1
    }
}

if ($Restart) { exit 0 }

# Edge en mode application : une fenêtre à part, sans barre d'adresse
$edge = @(
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($edge) {
    Start-Process -FilePath $edge -ArgumentList "--app=$Url", "--window-size=1300,900"
} else {
    Start-Process $Url
}
