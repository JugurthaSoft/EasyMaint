# Déploiement en ligne (SaaS)

Ce guide met EasyMaint en ligne pour plusieurs entreprises clientes, chacune à sa propre adresse
(`acme.mondomaine.tn`), en HTTPS. Les données restent séparées par entreprise (voir architecture.md).

## 1. Ce qu'il faut

- Un **serveur loué (VPS)** sous Ubuntu 24.04 : 2 processeurs, 4 Go de RAM et 40 Go de disque suffisent pour
  une dizaine de PME. Choisir un hébergeur proche des clients.
- Un **nom de domaine** (par exemple `mondomaine.tn`) dont vous gérez la zone DNS.
- Une adresse e-mail pour les avis de Let's Encrypt (certificats HTTPS gratuits).

## 2. DNS

Chez le gestionnaire du domaine, créer deux enregistrements pointant vers l'adresse IP du serveur :

| Type | Nom | Valeur |
| --- | --- | --- |
| A | `mondomaine.tn` (ou `@`) | IP du serveur |
| A | `*.mondomaine.tn` | IP du serveur |

L'enregistrement `*` (générique) évite de toucher au DNS à chaque nouveau client.

## 3. Préparer le serveur

```bash
ssh root@IP-DU-SERVEUR
apt update && apt upgrade -y
curl -fsSL https://get.docker.com | sh          # Docker et docker compose
ufw allow OpenSSH && ufw allow 80/tcp && ufw allow 443/tcp && ufw enable
adduser easymaint && usermod -aG docker easymaint
```

Conseillé : connexion SSH par clé uniquement, mises à jour de sécurité automatiques (`unattended-upgrades`).

## 4. Installer EasyMaint

```bash
su - easymaint
git clone <adresse-de-votre-dépôt> easymaint     # ou copier le dossier
cd easymaint
cp .env.example .env
chmod 600 .env
nano .env
```

Dans `.env` :

```
DJANGO_SECRET_KEY=<60 caractères aléatoires : python3 -c "import secrets; print(secrets.token_urlsafe(50))">
POSTGRES_PASSWORD=<mot de passe long et aléatoire>
EASYMAINT_DEPLOYMENT_MODE=saas
EASYMAINT_SAAS_BASE_DOMAIN=mondomaine.tn
DJANGO_ALLOWED_HOSTS=.mondomaine.tn
DJANGO_CSRF_TRUSTED_ORIGINS=https://*.mondomaine.tn,https://mondomaine.tn
EASYMAINT_USE_HTTPS=true
EASYMAINT_BEHIND_PROXY=true
EASYMAINT_ACME_EMAIL=contact@mondomaine.tn
EASYMAINT_REQUIREMENTS=base
EASYMAINT_SOURCE_URL=<adresse publique du code source, obligatoire si vous l'avez modifié>
```

Démarrer avec le complément SaaS (Caddy en frontal, HTTPS automatique) :

```bash
docker compose -f docker-compose.yml -f docker-compose.saas.yml up -d --build
```

## 5. Ajouter une entreprise cliente

```bash
docker compose exec web python manage.py create_tenant --name "ACME Plastiques" --code acme --admin admin.acme
```

Le client se connecte sur `https://acme.mondomaine.tn`. Le premier accès prend quelques secondes : Caddy
obtient alors le certificat HTTPS. Caddy ne demande un certificat que pour une entreprise existante et
active (contrôle `/interne/tls/`). Un utilisateur ne peut se connecter que sur l'adresse de son entreprise.

Suspendre un client (impayé, fin de contrat) : dans l'administration de la plateforme
(`https://mondomaine.tn/admin-plateforme/`, compte créé avec `docker compose exec web python manage.py createsuperuser`),
décocher « active » sur l'entreprise. Ses utilisateurs ne peuvent plus se connecter ; les données sont conservées.

## 6. Sauvegardes hors du serveur

Le service `backup` sauvegarde chaque nuit dans `~/easymaint/sauvegardes`. **Copier ce dossier ailleurs**
chaque jour, par exemple vers un stockage objet (rclone) ou un second serveur :

```bash
crontab -e
# 30 3 * * * rsync -a --delete ~/easymaint/sauvegardes/ sauvegarde@autre-serveur:easymaint/
```

Tester une restauration sur un serveur de test au moins une fois par trimestre.

## 7. Mise à jour

```bash
cd ~/easymaint && sh scripts/update.sh
```

Le script détecte le mode SaaS, fait `git pull`, sauvegarde, reconstruit et redémarre.

## 8. Surveillance

- `docker compose -f docker-compose.yml -f docker-compose.saas.yml ps` : tous les services doivent être `Up`.
- `docker compose logs caddy` : certificats ; `docker compose logs web` : erreurs de l'application.
- Un service de surveillance externe gratuit (UptimeRobot ou équivalent) sur `https://mondomaine.tn/compte/connexion/`
  prévient en cas d'indisponibilité.

## Rappel licence (AGPL-3.0)

Proposer EasyMaint en ligne est autorisé, y compris contre paiement. Si vous avez **modifié** le code, vous
devez proposer à vos utilisateurs le code source de votre version : renseigner `EASYMAINT_SOURCE_URL`
(dépôt public), affiché dans la page « À propos ».
