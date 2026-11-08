# Mise à jour d'EasyMaint sous Windows, en une commande, depuis le dossier d'EasyMaint :
#   1. copiez la nouvelle version par-dessus le dossier (votre .env et vos sauvegardes sont conservés),
#      ou laissez le script faire « git pull » si le dossier est un dépôt Git ;
#   2. powershell -ExecutionPolicy Bypass -File scripts\update.ps1
# Une sauvegarde est faite AVANT la mise à jour ; les migrations s'appliquent au redémarrage.
Set-Location (Split-Path $PSScriptRoot -Parent)

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }

if (Test-Path .git) {
  Step "Récupération de la nouvelle version (git pull)"
  git pull
  if ($LASTEXITCODE -ne 0) { Write-Host "git pull a échoué : mise à jour arrêtée." -ForegroundColor Red; exit 1 }
}

Step "Sauvegarde avant mise à jour"
docker compose exec -T backup sh /scripts/backup_daemon.sh --maintenant
if ($LASTEXITCODE -ne 0) {
  $answer = Read-Host "La sauvegarde a échoué. Continuer quand même ? (OUI pour continuer)"
  if ($answer -ne "OUI") { Write-Host "Mise à jour annulée."; exit 1 }
}

Step "Reconstruction et redémarrage"
docker compose up -d --build --remove-orphans
if ($LASTEXITCODE -ne 0) { Write-Host "Le redémarrage a échoué : voir les messages ci-dessus." -ForegroundColor Red; exit 1 }

docker compose ps
Write-Host "`nMise à jour terminée. La version installée s'affiche en bas du menu (lien « À propos »)." -ForegroundColor Green
