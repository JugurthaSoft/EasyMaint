#!/bin/sh
# Mise à jour d'EasyMaint (Linux), en une commande, depuis le dossier d'EasyMaint :
#   sh scripts/update.sh
# Récupère la nouvelle version (git pull si le dossier est un dépôt Git ; sinon copiez-la avant),
# sauvegarde, reconstruit et redémarre. Les migrations s'appliquent au redémarrage.
set -e
cd "$(dirname "$0")/.."
compose="docker compose"
[ -f docker-compose.saas.yml ] && grep -q "^EASYMAINT_DEPLOYMENT_MODE=saas" .env 2>/dev/null && compose="docker compose -f docker-compose.yml -f docker-compose.saas.yml"

if [ -d .git ]; then
  printf '\n== Récupération de la nouvelle version (git pull)\n'
  git pull
fi

printf '\n== Sauvegarde avant mise à jour\n'
if ! $compose exec -T backup sh /scripts/backup_daemon.sh --maintenant; then
  printf "La sauvegarde a échoué. Continuer quand même ? (OUI pour continuer) "
  read -r answer
  [ "$answer" = "OUI" ] || { echo "Mise à jour annulée."; exit 1; }
fi

printf '\n== Reconstruction et redémarrage\n'
$compose up -d --build --remove-orphans
$compose ps
printf '\nMise à jour terminée. La version installée s'"'"'affiche en bas du menu (lien « À propos »).\n'
