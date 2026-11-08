#!/bin/sh
# Service « backup » de docker-compose : sauvegarde automatique chaque nuit, avec rotation.
#   - base PostgreSQL (pg_dump, format compressé) + fichiers joints (photos, documents, rapports) ;
#   - dans le dossier « sauvegardes » à côté de docker-compose.yml (C:\easymaint\sauvegardes sous Windows) ;
#   - une fois par jour à partir de EASYMAINT_BACKUP_HOUR, puis suppression des sauvegardes de plus de
#     EASYMAINT_BACKUP_KEEP_DAYS jours.
# Sauvegarde immédiate :  docker compose exec backup sh /scripts/backup_daemon.sh --maintenant
# Copiez régulièrement ce dossier hors du serveur (disque externe, NAS) : une sauvegarde restée
# sur la même machine ne protège pas d'une panne de disque ni d'un vol.
set -u
DEST=/sauvegardes
HOUR="${BACKUP_HOUR:-1}"
KEEP="${BACKUP_KEEP_DAYS:-14}"
MARK="$DEST/.derniere-sauvegarde"
mkdir -p "$DEST"

log() { echo "$(date '+%d/%m/%Y %H:%M') · $*"; }

backup() {
  stamp="$(date +%Y%m%d-%H%M)"
  db="$DEST/easymaint-db-$stamp.dump"
  media="$DEST/easymaint-media-$stamp.tar.gz"
  # Écriture dans un fichier temporaire puis renommage : une sauvegarde interrompue ne laisse
  # jamais un fichier incomplet qui ressemblerait à une sauvegarde valide.
  if ! pg_dump --format=custom --file="$db.part"; then
    rm -f "$db.part"; log "ÉCHEC de la sauvegarde de la base"; return 1
  fi
  mv "$db.part" "$db"
  if [ -d /media ]; then
    if tar -czf "$media.part" -C / media; then mv "$media.part" "$media"; else rm -f "$media.part"; log "ÉCHEC de la sauvegarde des fichiers"; return 1; fi
  fi
  find "$DEST" -maxdepth 1 -type f -name 'easymaint-*' -mtime +"$KEEP" -exec rm -f {} \;
  date +%Y%m%d > "$MARK"
  log "sauvegarde terminée : $(basename "$db")$( [ -f "$media" ] && echo " et $(basename "$media")" )"
}

until pg_isready -q; do log "base de données pas encore prête, nouvel essai dans 10 s"; sleep 10; done

if [ "${1:-}" = "--maintenant" ]; then
  backup
  exit $?
fi

log "sauvegarde automatique chaque jour à partir de ${HOUR} h, conservation ${KEEP} jours, dans le dossier « sauvegardes »"
while true; do
  today="$(date +%Y%m%d)"
  hour="$(date +%H)"; hour="${hour#0}"
  last="$(cat "$MARK" 2>/dev/null || true)"
  if [ "$today" != "$last" ] && [ "${hour:-0}" -ge "$HOUR" ]; then
    backup || log "nouvel essai dans une heure"
    [ "$(cat "$MARK" 2>/dev/null || true)" = "$today" ] || sleep 3540
  fi
  sleep 60
done
