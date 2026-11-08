#!/bin/sh
# Installation d'EasyMaint sur un serveur Linux (Docker et le plugin « docker compose » installés).
#   sh scripts/install.sh            installation
#   sh scripts/install.sh --demo     + données de démonstration
# Relançable sans risque : un .env existant est conservé, une entreprise existante n'est pas recréée.
# Les mots de passe générés ne sont jamais affichés.
set -e
cd "$(dirname "$0")/.."

step() { printf '\n== %s\n' "$1"; }
fail() { echo "$1" >&2; exit 1; }
secret() { LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c "$1"; }
env_value() { v=$(grep -E "^$1=" .env | head -n1 | cut -d= -f2-); [ -n "$v" ] && echo "$v" || echo "$2"; }

step "1/5 Vérification de Docker"
docker compose version > /dev/null 2>&1 || fail "Docker (avec docker compose) est introuvable : installez-le puis relancez ce script."
echo "Docker est prêt."

step "2/5 Configuration (fichier .env)"
if [ -f .env ]; then
  echo "Fichier .env existant : conservé tel quel."
else
  ip=$(hostname -I 2>/dev/null | awk '{print $1}')
  [ -n "$ip" ] || ip=127.0.0.1
  printf "Adresse IP de ce serveur sur le réseau de l'usine [%s] : " "$ip"
  read -r answer
  [ -n "$answer" ] && ip="$answer"
  echo "Langue d'EasyMaint pour toute l'entreprise (choix définitif) / EasyMaint language for the whole company:"
  echo "  1 = Français    2 = English"
  printf "Choix / Choice [1] : "
  read -r choice
  language=fr
  [ "$choice" = "2" ] && language=en
  umask 077
  sed -e "s|^DJANGO_SECRET_KEY=.*|DJANGO_SECRET_KEY=$(secret 60)|" \
      -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(secret 32)|" \
      -e "s|^DJANGO_ALLOWED_HOSTS=.*|DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,$ip|" \
      -e "s|^DJANGO_CSRF_TRUSTED_ORIGINS=.*|DJANGO_CSRF_TRUSTED_ORIGINS=http://$ip:8000|" \
      -e "s|^EASYMAINT_REQUIREMENTS=.*|EASYMAINT_REQUIREMENTS=base|" \
      -e "s|^EASYMAINT_LANGUAGE=.*|EASYMAINT_LANGUAGE=$language|" .env.example > .env
  grep -q "^EASYMAINT_LANGUAGE=" .env || echo "EASYMAINT_LANGUAGE=$language" >> .env
  echo "Langue / language : $language"
  umask 022
  echo "Fichier .env créé : clé secrète et mot de passe de la base générés automatiquement. Ne le partagez jamais."
fi
port=$(env_value EASYMAINT_PORT 8000)

step "3/5 Construction et démarrage (plusieurs minutes la première fois)"
docker compose up -d --build

step "4/5 Attente de l'application"
i=0
until docker compose exec -T web python -c "import urllib.request,sys; sys.exit(urllib.request.urlopen('http://localhost:8000/compte/connexion/').status != 200)" > /dev/null 2>&1; do
  i=$((i + 1)); [ $i -lt 60 ] || fail "L'application ne répond pas. Consultez : docker compose logs web"
  sleep 3
done
echo "L'application répond."

step "5/5 Entreprise et administrateur"
counts=$(docker compose exec -T web python manage.py shell -c "from apps.core.models import Tenant; print('EM', Tenant.objects.count(), Tenant.objects.exclude(code='demo').count())" | grep -E '^EM [0-9]+ [0-9]+' | tail -n1)
total=$(echo "$counts" | awk '{print $2}'); own=$(echo "$counts" | awk '{print $3}')
create=yes
if [ "${own:-0}" -gt 0 ]; then
  echo "Une entreprise existe déjà : rien à créer."; create=no
elif [ "${total:-0}" -gt 0 ]; then
  printf "Seule l'entreprise de démonstration existe. Créer votre propre entreprise maintenant ? (O/N) "; read -r answer
  case "$answer" in [oOyY]*) ;; *) create=no ;; esac
fi
if [ "$create" = yes ]; then
  printf "Raison sociale de l'entreprise : "; read -r name
  printf "Code court (minuscules, chiffres et tirets, par exemple usine-sfax) : "; read -r code
  printf "Identifiant de l'administrateur [admin] : "; read -r admin
  [ -n "$admin" ] || admin=admin
  echo "Choisissez le mot de passe de l'administrateur (10 caractères minimum, saisie masquée) :"
  docker compose exec web python manage.py create_tenant --name "$name" --code "$code" --admin "$admin" \
    || fail "Création refusée (voir le message). Relancez le script pour réessayer."
fi
if [ "${1:-}" = "--demo" ]; then
  printf "Mot de passe des comptes de démonstration : "; stty -echo 2>/dev/null; read -r demo; stty echo 2>/dev/null; echo
  docker compose exec -T web python manage.py load_demo --password "$demo"
fi

host_ip=$(env_value DJANGO_ALLOWED_HOSTS localhost | tr ',' '\n' | grep -vE '^(localhost|127\.0\.0\.1|web|)$' | tail -n1)
if [ -n "$host_ip" ]; then
  printf '\nEasyMaint est installé : http://%s:%s\n' "$host_ip" "$port"
else
  printf '\nEasyMaint est installé : http://localhost:%s\n' "$port"
  echo "Accès depuis les autres postes : ajoutez l'adresse IP du serveur dans DJANGO_ALLOWED_HOSTS et DJANGO_CSRF_TRUSTED_ORIGINS du .env."
fi
echo "Sauvegarde automatique chaque nuit dans le dossier « sauvegardes » : copiez-le régulièrement hors du serveur."
