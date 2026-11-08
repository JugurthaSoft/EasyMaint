#!/bin/sh
# Démarrage du conteneur : attend la base, applique les migrations, prépare les fichiers statiques.
set -e

if [ -n "$POSTGRES_DB" ]; then
  echo "Attente de PostgreSQL..."
  python - <<'EOF'
import os, sys, time
import psycopg
for attempt in range(60):
    try:
        psycopg.connect(
            dbname=os.environ["POSTGRES_DB"],
            user=os.environ.get("POSTGRES_USER", "easymaint"),
            password=os.environ.get("POSTGRES_PASSWORD", ""),
            host=os.environ.get("POSTGRES_HOST", "db"),
            port=os.environ.get("POSTGRES_PORT", "5432"),
        ).close()
        sys.exit(0)
    except psycopg.OperationalError:
        time.sleep(1)
print("PostgreSQL injoignable après 60 s", file=sys.stderr)
sys.exit(1)
EOF
fi

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec "$@"
