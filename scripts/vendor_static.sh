#!/bin/sh
# Télécharge les bibliothèques front-end dans static/vendor pour un fonctionnement hors ligne.
# Lancé automatiquement à la construction de l'image Docker ; à lancer une fois en développement local.
set -e
DEST="$(dirname "$0")/../static/vendor"
mkdir -p "$DEST"

fetch() {
  if [ ! -s "$DEST/$2" ]; then
    echo "Téléchargement de $2"
    curl -fsSL "$1" -o "$DEST/$2"
  fi
  # Retire les références aux fichiers .map (non téléchargés) : sans cela, le stockage
  # des fichiers statiques de production refuse de démarrer en les cherchant.
  sed -i -e 's#/\*\# sourceMappingURL=[^*]*\*/##g' -e 's#//\# sourceMappingURL=[^ ]*$##' "$DEST/$2"
}

fetch https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css bootstrap.min.css
fetch https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.rtl.min.css bootstrap.rtl.min.css
fetch https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js bootstrap.bundle.min.js
fetch https://cdn.jsdelivr.net/npm/htmx.org@2.0.4/dist/htmx.min.js htmx.min.js
fetch https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js chart.umd.min.js
echo "Bibliothèques prêtes dans static/vendor"
