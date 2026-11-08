# Installation et exploitation d'EasyMaint (serveur de l'entreprise)

Pour un hébergement en ligne multi-entreprise (SaaS), voir [deploiement-cloud.md](deploiement-cloud.md).

## Installation sur un serveur Linux (recommandé)

Prérequis : un serveur Linux (Ubuntu 22.04/24.04 ou Debian 12), 4 Go de RAM, 20 Go de disque, [Docker Engine avec le plugin Compose](https://docs.docker.com/engine/install/). Une connexion Internet est nécessaire **uniquement pendant la construction** de l'image ; ensuite l'application fonctionne sur le réseau local seul.

```bash
# Copier le dossier easymaint sur le serveur, puis :
cd easymaint
sh scripts/install.sh          # ou : sh scripts/install.sh --demo  (ajoute les données de démonstration)
```

Le script vérifie Docker, crée le fichier `.env` (clé secrète et mot de passe de la base générés
automatiquement, jamais affichés), construit et démarre EasyMaint, puis demande le nom de l'entreprise,
son code et l'identifiant de l'administrateur (mot de passe saisi de façon masquée). Il peut être relancé
sans risque : un `.env` existant est conservé, une entreprise existante n'est pas recréée.

Installation manuelle (équivalente) :

```bash
cp .env.example .env
nano .env        # DJANGO_SECRET_KEY, POSTGRES_PASSWORD, adresse IP du serveur
docker compose up -d --build
docker compose exec web python manage.py create_tenant --name "Ma Société" --code ma-societe --admin admin
```

Ouvrir ensuite `http://<adresse-du-serveur>:8000` depuis n'importe quel poste du réseau.

Pour générer la clé secrète : `python3 -c "import secrets; print(secrets.token_urlsafe(50))"`.

### Données de démonstration

```bash
docker compose exec web python manage.py load_demo --password "Choisir-Un-Mot-De-Passe-2026"
```

Crée l'entreprise « demo » (usine de plasturgie, 11 localisations, 21 équipements, compteurs avec 12 semaines de relevés, techniciens, équipes et 16 ordres de travail) et un compte par rôle : `admin.demo`, `s.bensalah` (responsable maintenance), `a.mejri` (ingénieure), `r.jaziri` (chef d'équipe), `k.trabelsi`, `n.chaabane`, `h.ayari` (techniciens), `m.saidi` (magasinière), `m.gharbi` (production), `l.hammami` (direction). Tous ont le mot de passe choisi.

### Langue de l'installation

Le script d'installation demande la langue : **français** ou **anglais**. Ce choix vaut pour toute l'entreprise
(écrans, documents, exports, rapports) ; il est enregistré dans le `.env` (`EASYMAINT_LANGUAGE=fr` ou `en`).
Il est prévu pour être définitif : le changer plus tard traduit l'interface, mais pas les données déjà saisies
(noms d'équipements, comptes rendus…). La démonstration (`-Demo`, `--demo`) est chargée dans la langue choisie.

### Installation sous Windows

1. Installer [Docker Desktop](https://www.docker.com/products/docker-desktop/) (moteur WSL 2) et le régler pour **démarrer avec Windows** (Paramètres › General › Start Docker Desktop when you sign in). Pour un poste qui sert de serveur, désactiver la mise en veille.
2. Décompresser EasyMaint dans `C:\easymaint`.
3. Dans PowerShell :

```powershell
cd C:\easymaint
powershell -ExecutionPolicy Bypass -File scripts\install.ps1          # ou ... install.ps1 -Demo
```

4. Autoriser le port 8000 dans le pare-feu Windows si les autres postes n'accèdent pas à l'application :
   `New-NetFirewallRule -DisplayName "EasyMaint" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow` (PowerShell administrateur).

### Serveur sans aucun accès Internet

Construire l'image sur un poste connecté, puis la transférer :

```bash
docker compose build
docker save easymaint-web postgres:16-alpine -o easymaint-images.tar
# sur le serveur :
docker load -i easymaint-images.tar
docker compose up -d
```


## Sauvegarde et restauration

### Sauvegarde automatique (service `backup`)

Chaque nuit à partir de 1 h, le service `backup` sauvegarde la base PostgreSQL et les fichiers joints
dans le dossier **`sauvegardes`** à côté de `docker-compose.yml` (`C:\easymaint\sauvegardes` sous Windows),
puis efface les sauvegardes de plus de 14 jours. Heure et durée se règlent dans le `.env`
(`EASYMAINT_BACKUP_HOUR`, `EASYMAINT_BACKUP_KEEP_DAYS`). L'état est visible dans
**Paramètres › Sauvegardes** (alerte si la dernière sauvegarde a plus de 2 jours).

```bash
docker compose exec backup sh /scripts/backup_daemon.sh --maintenant   # sauvegarde immédiate
docker compose logs backup                                             # journal des sauvegardes
```

**Copiez régulièrement ce dossier hors du serveur** (disque externe, NAS) : une sauvegarde restée sur la
même machine ne protège ni d'une panne de disque ni d'un vol.

### Sauvegarde manuelle vers un autre dossier

Sous **Windows** (PowerShell, depuis `C:\easymaint`) :

```powershell
powershell -ExecutionPolicy Bypass -File scripts\backup.ps1 -Destination D:\Sauvegardes
```

Sous **Linux** : `sh scripts/backup.sh /chemin/vers/sauvegardes`

### Restauration (remplace toutes les données actuelles)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\restore.ps1 -Dump sauvegardes\easymaint-db-AAAAMMJJ-HHMM.dump -Media sauvegardes\easymaint-media-AAAAMMJJ-HHMM.tar.gz
```

```bash
sh scripts/restore.sh sauvegardes/easymaint-db-AAAAMMJJ-HHMM.dump sauvegardes/easymaint-media-AAAAMMJJ-HHMM.tar.gz
```

## Mise à jour (une commande)

Copier la nouvelle version par-dessus le dossier (le `.env` et les sauvegardes sont conservés), ou laisser
le script faire `git pull` si le dossier est un dépôt Git, puis :

```powershell
powershell -ExecutionPolicy Bypass -File scripts\update.ps1      # Windows
```

```bash
sh scripts/update.sh                                               # Linux
```

Le script sauvegarde la base et les fichiers, reconstruit l'image et redémarre ; les migrations
s'appliquent au démarrage. En cas de problème : restaurer la sauvegarde faite juste avant (voir plus haut).



## Dépannage

| Symptôme | Que faire |
| --- | --- |
| La page ne s'ouvre pas depuis un autre poste | Vérifier l'adresse IP dans `DJANGO_ALLOWED_HOSTS` et `DJANGO_CSRF_TRUSTED_ORIGINS` du `.env`, le pare-feu (port 8000), puis `docker compose up -d`. |
| « Bad Request (400) » | L'adresse utilisée n'est pas dans `DJANGO_ALLOWED_HOSTS`. |
| « Trop de tentatives de connexion » | Attendre 15 minutes (blocage automatique après 5 échecs). |
| Un service redémarre en boucle | `docker compose logs web` (ou `scheduler`, `backup`) et transmettre le message au support. |
| Sauvegarde ancienne (alerte dans Paramètres › Sauvegardes) | `docker compose ps` puis `docker compose logs backup`. |

Ne jamais envoyer le contenu du fichier `.env` (il contient les mots de passe) : décrire seulement le problème.
