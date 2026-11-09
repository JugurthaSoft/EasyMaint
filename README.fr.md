# EasyMaint — GMAO libre pour PME industrielles

[English](README.md) | **Français**

« La puissance fonctionnelle d'une GMAO professionnelle, avec la simplicité d'utilisation d'une application moderne. »

**Version 1.1.0** · logiciel libre sous licence **AGPL-3.0** · © 2026 Jamil KHALFALLAH et contributeurs · un logiciel [JugurthaSoft](https://jugurthasoft.com)

Code source : https://github.com/jugurthasoft/easymaint · Contact : contact@jugurthasoft.com

Application web en français ou en anglais, langue choisie à l'installation (Django, HTMX, Bootstrap 5, PostgreSQL), livrée en conteneurs Docker. Le même code
sert pour une installation sur un serveur de l'usine, sans Internet, et pour un hébergement en ligne
multi-entreprise (SaaS).

## Fonctions

- **Patrimoine** : localisations en arborescence, équipements et sous-ensembles, fiches techniques, documents, compteurs, QR codes, fiche PDF.
- **Interventions** : demandes, ordres de travail correctifs et amélioratifs, affectation, écran mobile du technicien (chronomètre, check-list, compte rendu), arrêts de production, validation, coûts figés, fiche d'intervention PDF, export Excel.
- **Préventif** : plans calendaires et sur compteur, génération automatique des OT, report, planning, taux de réalisation.
- **Conditionnel** : points de mesure, seuils versionnés (vibrations, huiles, températures…), courbes, alertes, règles de déclenchement, import CSV/Excel, API pour capteurs.
- **Magasin** : articles, magasins, fournisseurs, CMP, réservation et délivrance aux OT avec bons de sortie et de retour à signer, inventaires, nomenclatures, demandes d'achat imprimables, réapprovisionnement.
- **Coûts et budget** : analyse par équipement, unité, famille, type, mois ; budget annuel par unité ; rapports Excel et PDF.
- **Indicateurs** : MTBF, MTTR, disponibilités, taux de correctif, backlog… avec définitions ; rapport mensuel PDF automatique ; accueil personnalisable par utilisateur.
- **Mise en service** : imports Excel (équipements, articles avec stock initial, fournisseurs, historique).
- **Sécurité et exploitation** : 8 rôles et 29 droits modifiables, journal d'activité, données séparées par entreprise, blocage après échecs de connexion, notifications dans l'application, sauvegarde automatique chaque nuit.

## Installation rapide

Sous Windows (Docker Desktop installé), depuis le dossier d'EasyMaint :

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -Demo
```

Sous Linux (Docker installé) :

```bash
sh scripts/install.sh --demo
```

Ouvrir ensuite `http://<adresse-du-serveur>:8000`. Sans `-Demo` / `--demo`, seule votre entreprise est créée.
Le script demande la langue de l'installation (français ou anglais) ; la démonstration est chargée dans cette langue.

## Documentation

- [Installation et exploitation](docs/installation.md) : installation locale, sauvegarde et restauration, mise à jour, dépannage
- [Déploiement en ligne (SaaS)](docs/deploiement-cloud.md) : serveur loué, HTTPS automatique, une adresse par entreprise
- [Guide d'utilisation](docs/utilisation.md)
- [Architecture](docs/architecture.md) : règles multi-entreprise, droits, conventions de code
- [Historique des versions](docs/CHANGELOG.md)
- API : `/api/v1/` (navigable une fois connecté). Pour un capteur ou un logiciel : `docker compose exec web python manage.py create_api_token <identifiant>`, puis en-tête `Authorization: Token <jeton>` ; envoi de mesures sur `/api/v1/mesures/` (voir le guide d'utilisation).

## Développement

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements/dev.txt
sh scripts/vendor_static.sh          # Bootstrap, HTMX, Chart.js en local
python manage.py migrate             # SQLite par défaut en développement
python manage.py load_demo --password "Demo-EasyMaint-2026"
python manage.py runserver
```

### Tests

```bash
pytest                                          # en local
docker compose run --rm web pytest              # dans le conteneur (EASYMAINT_REQUIREMENTS=dev dans .env)
```

La suite couvre notamment : l'isolation des données entre entreprises (base, formulaires, API, fichiers, QR codes), les droits par rôle, la numérotation des documents, les règles des compteurs, le journal d'audit et la concordance entre modèles et migrations.

## Contribuer

Les contributions sont bienvenues (corrections, traductions, nouvelles fonctions) : voir [CONTRIBUTING.fr.md](CONTRIBUTING.fr.md).

## Licence et services

EasyMaint est un logiciel libre : vous pouvez l'utiliser, l'étudier, le modifier et le redistribuer selon les
termes de la [GNU Affero General Public License version 3](LICENSE) (voir aussi [COPYRIGHT](COPYRIGHT)).
Si vous proposez une version modifiée à des utilisateurs par un réseau (service en ligne), vous devez leur
donner accès à son code source (`EASYMAINT_SOURCE_URL`, affiché dans la page « À propos »).

L'auteur propose l'installation, la mise en service (reprise de l'existant, paramétrage), la formation des
équipes, l'hébergement et les développements sur mesure : contact@jugurthasoft.com.
