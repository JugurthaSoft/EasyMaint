#!/bin/sh
# Sauvegarde complète : base PostgreSQL + fichiers joints (photos, documents).
# Usage : sh scripts/backup.sh [dossier_de_destination]
# À planifier chaque nuit (cron sous Linux, Planificateur de tâches sous Windows).
set -e
DEST="${1:-./sauvegardes}"
STAMP="$(date +%Y%m%d-%H%M)"
mkdir -p "$DEST"

docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' > "$DEST/easymaint-db-$STAMP.dump"
docker compose exec -T web tar -czf - -C /app media > "$DEST/easymaint-media-$STAMP.tar.gz"

echo "Sauvegarde terminée : $DEST/easymaint-db-$STAMP.dump et easymaint-media-$STAMP.tar.gz"
