# (Re)crée l'icône « Mes candidatures » sur le bureau.
$Root = Split-Path -Parent $PSScriptRoot
$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath("Desktop")) "Mes candidatures.lnk"))
$lnk.TargetPath = "$env:SystemRoot\System32\wscript.exe"
$lnk.Arguments = "`"$Root\windows\start_app.vbs`""
$lnk.WorkingDirectory = $Root
$lnk.IconLocation = "$env:SystemRoot\System32\imageres.dll,109"
$lnk.Description = "Suivi des offres VIE, HelloWork et LinkedIn"
$lnk.Save()
Write-Host "Icône « Mes candidatures » mise à jour sur le bureau." -ForegroundColor Green
