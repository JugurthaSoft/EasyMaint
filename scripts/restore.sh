#!/bin/sh
# Restauration d'une sauvegarde (automatique, ou produite par backup.sh).
# Usage : sh scripts/restore.sh sauvegardes/easymaint-db-AAAAMMJJ-HHMM.dump [sauvegardes/easymaint-media-....tar.gz]
# ATTENTION : remplace toutes les données actuelles.
set -e
DB_DUMP="$1"
MEDIA_ARCHIVE="$2"
[ -f "$DB_DUMP" ] || { echo "Fichier de sauvegarde introuvable : $DB_DUMP"; exit 1; }

printf "Toutes les données actuelles seront remplacées. Taper OUI pour continuer : "
read -r answer
[ "$answer" = "OUI" ] || { echo "Restauration annulée."; exit 1; }

docker compose stop web scheduler backup
docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists' < "$DB_DUMP"
docker compose start web scheduler backup
if [ -n "$MEDIA_ARCHIVE" ]; then
  docker compose exec -T web tar -xzf - -C /app < "$MEDIA_ARCHIVE"
fi
echo "Restauration terminée."
