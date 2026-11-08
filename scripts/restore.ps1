# Restauration EasyMaint sous Windows. ATTENTION : remplace toutes les données actuelles.
# Usage : powershell -ExecutionPolicy Bypass -File scripts\restore.ps1 -Dump sauvegardes\easymaint-db-AAAAMMJJ-HHMM.dump [-Media sauvegardes\easymaint-media-AAAAMMJJ-HHMM.tar.gz]
# -Media accepte l'archive .tar.gz de la sauvegarde automatique ou le dossier produit par backup.ps1.
param([Parameter(Mandatory = $true)][string]$Dump, [string]$Media = "")

$ErrorActionPreference = "Stop"
if (-not (Test-Path $Dump)) { throw "Fichier introuvable : $Dump" }
$answer = Read-Host "Toutes les données actuelles seront remplacées. Taper OUI pour continuer"
if ($answer -ne "OUI") { Write-Host "Restauration annulée."; exit 1 }

docker compose stop web scheduler backup
docker compose cp $Dump db:/tmp/restore.dump
docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists /tmp/restore.dump'
docker compose exec -T db rm -f /tmp/restore.dump
docker compose start web scheduler backup
if ($Media -ne "") {
  if ($Media.EndsWith(".tar.gz")) {
    docker compose cp $Media web:/tmp/restore-media.tar.gz
    docker compose exec -T -u root web sh -c "tar -xzf /tmp/restore-media.tar.gz -C /app && chown -R easymaint:easymaint /app/media && rm -f /tmp/restore-media.tar.gz"
  } else {
    docker compose cp "$Media\." web:/app/media
  }
}
Write-Host "Restauration terminée."
