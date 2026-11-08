# Sauvegarde EasyMaint sous Windows (PowerShell) : base PostgreSQL + fichiers joints.
# Usage, depuis C:\easymaint :   powershell -ExecutionPolicy Bypass -File scripts\backup.ps1 [-Destination D:\Sauvegardes]
# À planifier chaque nuit avec le Planificateur de tâches Windows.
param([string]$Destination = ".\sauvegardes")

$ErrorActionPreference = "Stop"
$stamp = Get-Date -Format "yyyyMMdd-HHmm"
New-Item -ItemType Directory -Force -Path $Destination | Out-Null

# Le fichier est produit dans le conteneur puis copié : une redirection PowerShell (>) abîmerait ce fichier binaire.
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom -f /tmp/easymaint.dump'
if ($LASTEXITCODE -ne 0) { throw "Échec de la sauvegarde de la base." }
docker compose cp db:/tmp/easymaint.dump "$Destination\easymaint-db-$stamp.dump"
docker compose exec -T db rm -f /tmp/easymaint.dump

docker compose cp web:/app/media "$Destination\easymaint-media-$stamp"
if ($LASTEXITCODE -ne 0) { throw "Échec de la copie des fichiers joints." }

Write-Host "Sauvegarde terminée : $Destination\easymaint-db-$stamp.dump et le dossier easymaint-media-$stamp"
