# Arrête le serveur de l'application « Mes candidatures » (il tourne en arrière-plan).
Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -match "streamlit" -and $_.CommandLine -match "dashboard.py" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Write-Host "Application arrêtée." -ForegroundColor Green
