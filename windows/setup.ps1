# Installe la partie LinkedIn du CDI Watcher sur ce PC Windows.
# Usage (PowerShell, dans le dossier du dépôt) :
#   powershell -ExecutionPolicy Bypass -File windows\setup.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$TaskName = "CDI Watcher LinkedIn"
$RunTimes = @("12:05", "19:05")   # pour l'affichage ; les horaires réels sont dans schedule_task.ps1

function Say($msg, $color = "Cyan") { Write-Host $msg -ForegroundColor $color }

# ---------------------------------------------------------------- 1. Python
Say "`n[1/7] Recherche de Python 3.10+..."
$Py = $null
foreach ($cand in @(@("py", "-3"), @("python"))) {
    try {
        $pyArgs = @($cand | Select-Object -Skip 1) + @("--version")
        $v = & $cand[0] @pyArgs 2>&1
        if ($LASTEXITCODE -eq 0 -and "$v" -match "Python 3\.(\d+)" -and [int]$Matches[1] -ge 10) { $Py = $cand; break }
    } catch {}
}
if (-not $Py) {
    Say "Python 3.10+ introuvable. Installe-le avec :" "Yellow"
    Say "  winget install -e --id Python.Python.3.13" "Yellow"
    Say "puis ferme et rouvre PowerShell et relance ce script." "Yellow"
    exit 1
}
Say "  OK : $(& $Py[0] @(@($Py | Select-Object -Skip 1) + '--version'))" "Green"

# ---------------------------------------------------------------- 2. venv + packages
Say "`n[2/7] Environnement Python et dépendances..."
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    & $Py[0] @(@($Py | Select-Object -Skip 1) + @("-m", "venv", ".venv"))
}
& ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
& ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt -r requirements-app.txt
if ($LASTEXITCODE -ne 0) { throw "pip install a échoué." }
Say "  OK" "Green"

# ---------------------------------------------------------------- 3. .env (clés)
Say "`n[3/7] Clés (fichier .env, jamais envoyé sur GitHub)..."
if (Test-Path ".env") {
    Say "  .env existe déjà, je le garde. Supprime-le pour ressaisir les clés." "Green"
} else {
    Say "  Ta clé Gemini : la même que le secret GEMINI_API_KEY de ton dépôt GitHub."
    $gemini = (Read-Host "  GEMINI_API_KEY").Trim()
    $lines = @("GEMINI_API_KEY=$gemini")
    [System.IO.File]::WriteAllLines((Join-Path $Root ".env"), $lines)
    Say "  OK" "Green"
}

# Nom pour les lettres de motivation (gardé sur ce PC, dans data\coordonnees.json)
$ContactFile = Join-Path $Root "data\coordonnees.json"
$contact = @{}
if (Test-Path $ContactFile) {
    try { (Get-Content $ContactFile -Raw -Encoding UTF8 | ConvertFrom-Json).PSObject.Properties | ForEach-Object { $contact[$_.Name] = $_.Value } } catch {}
}
if (-not $contact["nom"]) {
    $nom = (Read-Host "  Ton prénom et ton nom (signature des lettres)").Trim()
    if ($nom) {
        $contact["nom"] = $nom
        New-Item -ItemType Directory -Force -Path (Join-Path $Root "data") | Out-Null
        [System.IO.File]::WriteAllText($ContactFile, ($contact | ConvertTo-Json), (New-Object System.Text.UTF8Encoding $false))
        Say "  OK (modifiable plus tard dans l'onglet Réglages de l'application)" "Green"
    }
}

# ---------------------------------------------------------------- 4. profil
Say "`n[4/7] Profil (profile_cdi.txt)..."
$ProfileFile = Join-Path $Root "profile_cdi.txt"
$Placeholder = "COLLE ICI LE MEME TEXTE QUE TON SECRET CDI_USER_DESCRIPTION, puis enregistre et ferme le Bloc-notes."
if (-not (Test-Path $ProfileFile) -or (Get-Content $ProfileFile -Raw) -match "COLLE ICI") {
    [System.IO.File]::WriteAllText($ProfileFile, $Placeholder)
    Say "  Le Bloc-notes s'ouvre : colle ton profil, enregistre (Ctrl+S) et ferme-le."
    Start-Process notepad.exe -ArgumentList "`"$ProfileFile`"" -Wait
}
if ((Get-Content $ProfileFile -Raw) -match "COLLE ICI") { throw "Le profil n'a pas été rempli (profile_cdi.txt)." }
Say "  OK" "Green"

# ---------------------------------------------------------------- 5. Google Sheets
Say "`n[5/7] Lien avec un Google Sheets de suivi de tes candidatures (facultatif)..."
$envText = Get-Content ".env" -Raw
if ($envText -match "SHEETS_WEBAPP_URL=\S+") {
    Say "  Déjà relié (SHEETS_WEBAPP_URL présent dans .env)." "Green"
} elseif ((Read-Host "  Relier ton Google Sheets maintenant ? (O/N)") -match "^[oOyY]") {
    $token = -join ((48..57) + (97..122) | Get-Random -Count 24 | ForEach-Object { [char]$_ })
    Set-Clipboard -Value (Get-Content "google_sheets\apps_script.gs" -Raw)
    Say "  Un Google Sheets vierge s'ouvre dans ton navigateur (renomme-le « Suivi candidatures »)."
    Say "  Si tu as déjà ton propre Sheets de suivi, ouvre-le à la place : colonnes A à G ="
    Say "  N, Poste, Entreprise, Lien, Date, Retour, Commentaire (ligne 1 = en-têtes)."
    Say "  1. Dans ce Sheets : Extensions > Apps Script."
    Say "  2. Efface le code existant et colle (Ctrl+V) : le script est déjà dans ton presse-papiers."
    Say "  3. Remplace COLLE_ICI_TON_CODE_SECRET par ce code : $token" "Yellow"
    Say "  4. Enregistre, puis Déployer > Nouveau déploiement > type « Application Web »,"
    Say "     Exécuter en tant que : Moi, Qui a accès : Tout le monde > Déployer > autorise l'accès."
    Say "  5. Copie l'URL de l'application Web (elle finit par /exec)."
    Start-Process "https://sheets.new"
    $url = Read-Host "  Colle l'URL ici"
    Add-Content -Path ".env" -Value "SHEETS_WEBAPP_URL=$url" -Encoding UTF8
    Add-Content -Path ".env" -Value "SHEETS_TOKEN=$token" -Encoding UTF8
    try {
        $r = Invoke-RestMethod -Uri "$url`?token=$token" -TimeoutSec 30
        if ($r.ok) { Say "  OK : $($r.rows.Count) candidature(s) lues dans ton Sheets." "Green" }
        elseif ($r.error -eq "token") { Say "  Le script refuse le code secret : vérifie l'étape 3, puis Gérer les déploiements > Nouvelle version." "Yellow" }
        else { Say "  Google demande une connexion : l'accès doit être « Tout le monde » (pas « Tout utilisateur disposant d'un compte Google »). Gérer les déploiements > crayon > Nouvelle version." "Yellow" }
    } catch { Say "  Impossible de joindre le script ($($_.Exception.Message)). Tu pourras corriger SHEETS_WEBAPP_URL dans .env." "Yellow" }
} else {
    Say "  Ignoré. Relance ce script plus tard pour le faire."
}

# ---------------------------------------------------------------- 6. tâche planifiée
Say "`n[6/7] Tâche planifiée '$TaskName' (lun-ven $($RunTimes -join ', '))..."
& (Join-Path $PSScriptRoot "schedule_task.ps1")
Say "  OK. Une fenêtre s'ouvrira à chaque recherche. Si le PC est éteint à l'heure prévue, la recherche se lance à son prochain démarrage." "Green"

# ---------------------------------------------------------------- 7. raccourci bureau
Say "`n[7/7] Raccourci « Mes candidatures » sur le bureau..."
& (Join-Path $PSScriptRoot "create_shortcut.ps1")
Say "  OK" "Green"

# ---------------------------------------------------------------- test
$go = Read-Host "`nLancer une première recherche LinkedIn maintenant ? (O/N)"
if ($go -match "^[oOyY]") {
    Say "Recherche en cours (quelques minutes)..."
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$Root\windows\run_linkedin.ps1"
}
Say "`nOuverture de l'application Mes candidatures..."
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$Root\windows\start_app.ps1"
Say "`nTerminé. Ouvre l'application avec l'icône « Mes candidatures » du bureau. Journal : $Root\logs\linkedin.log" "Green"
Say "Pour tout désinstaller : powershell -ExecutionPolicy Bypass -File windows\uninstall.ps1" "Green"
