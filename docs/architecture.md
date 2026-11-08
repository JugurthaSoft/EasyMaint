# Architecture technique

## Vue d'ensemble

Monolithe modulaire Django : un seul déploiement, une application Django par domaine métier.

| Application | Rôle | Phase |
| --- | --- | --- |
| `core` | Entreprise (tenant), base multi-entreprise, numérotation, journal d'audit, pièces jointes, recherche globale, menu, formats | 2 |
| `accounts` | Utilisateurs, rôles, capacités, connexion, journal d'activité | 2 |
| `assets` | Localisations, familles, fabricants, équipements, compteurs, relevés, QR codes, API | 2 |
| `workforce` | Compétences, équipes, techniciens, sous-traitants | 3 |
| `workorders` | Demandes d'intervention, ordres de travail, pointages, pièces, dépenses, check-lists, arrêts machine, codes de défaillance | 3 |
| `preventive` | Plans préventifs, génération des OT, planning, indicateurs du préventif, tâches planifiées | 3 |
| `inventory` | Articles, familles, magasins, fournisseurs, stock par magasin, mouvements, CMP, réservations et délivrance aux OT, inventaires, nomenclature des équipements | 5 |
| `finance` | Coûts réels (OT validés, sorties hors OT), regroupements, budget annuel par unité, rapports Excel et PDF | 6 |
| `kpi` | Indicateurs (fiabilité, disponibilité, taux, backlog), définitions, tendances, exports | 6 |
| `imports` | Imports de mise en service (équipements, fournisseurs, articles, historique) : modèles, analyse, exécution | 7 |
| `condition` | Paramètres, points de mesure, seuils versionnés, tournées, mesures, alertes, règles de déclenchement | 4 |
| `dashboard` | Accueil et tableau de bord | 2 (enrichi en 3 et 6) |

Dépendances autorisées : `core` ← `accounts` ← `assets` ← `workforce` ← `workorders` ← `inventory` ← `preventive` ← `condition` ← `finance` ← `kpi` ← `dashboard`. Seule exception : `WorkOrder.preventive_plan` référence le plan par son nom (« preventive.PreventivePlan ») ; le code de `workorders` n'importe jamais `preventive` et le prévient par le signal `work_order_closed`. Quand un module amont affiche des données aval (onglet Interventions de la fiche équipement), il le fait par import conditionnel (`apps.is_installed`). Un module ne lit jamais les tables d'un module qui n'est pas en amont.

Dans chaque application :

- `models.py` — tables et règles de cohérence (`clean()`) ;
- `services.py` — **toutes les écritures métier** (une fonction = une action, en transaction) ;
- `selectors.py` — lectures complexes (filtres, arbres, agrégats) ;
- `forms.py`, `views.py`, `urls.py`, `api/` — interface web et API, qui appellent services et sélecteurs ;
- `tests/`.

## Séparation des données entre entreprises

Règle unique : **toute table métier hérite de `TenantScopedModel`**.

1. Le manager par défaut `objects` filtre sur l'entreprise courante. Sans entreprise courante, il renvoie un résultat **vide** : un oubli n'expose jamais les données d'une autre entreprise.
2. L'entreprise courante est posée par `TenantMiddleware` (celle de l'utilisateur connecté) ; en mode SaaS, le sous-domaine doit en plus correspondre. Dans les commandes et les tests : `with tenant_context(tenant):`.
3. `save()` renseigne automatiquement l'entreprise ; un enregistrement sans entreprise est refusé.
4. `clean()` refuse tout lien vers un objet d'une autre entreprise (`check_same_tenant`).
5. Les listes de choix des formulaires et les champs liés de l'API sont recalculés **à chaque requête** (un queryset construit au chargement du module serait vide).
6. Les fichiers envoyés ne sont jamais servis en accès direct : photos et documents passent par des vues qui contrôlent entreprise et droits.
7. `all_tenants` (non filtré) est réservé aux usages explicitement transverses : administration de la plateforme, commandes.

`User` n'hérite pas de `TenantScopedModel` (l'authentification doit pouvoir le trouver avant de connaître l'entreprise) : les vues de gestion des utilisateurs filtrent explicitement sur `request.tenant`.

## Droits

- Une **capacité** (`assets.manage`, `workorders.validate`…) autorise une action. La liste complète est dans `apps/accounts/capabilities.py`, y compris celle des modules à venir, pour que la matrice reste stable.
- Un **rôle** est une liste de capacités propre à chaque entreprise. Les 8 rôles prédéfinis sont créés avec l'entreprise et restent modifiables (le rôle Administrateur conserve toujours la gestion des utilisateurs).
- Contrôle côté serveur : `CapabilityRequiredMixin` (vues), `require_capability()` (fonctions), `HasCapability` (API). Dans les gabarits, `{% if user|can:"assets.manage" %}` masque les actions non autorisées, sans remplacer le contrôle serveur.

## Journal d'audit

`AuditLog` enregistre connexions, échecs de connexion, déconnexions, créations, modifications (avec valeurs avant → après), exports. Une entrée ne peut être ni modifiée ni supprimée par l'application. L'onglet « Historique des modifications » d'une fiche équipement lit ce journal.

## Cycle de vie des ordres de travail

Toutes les transitions passent par `apps/workorders/services.py` :

| Action | Depuis | Vers | Droit |
| --- | --- | --- | --- |
| Démarrer (1er chronomètre) | À planifier, Affecté | En cours | exécuter (OT affecté) ou gérer |
| Mettre en attente (motif) | En cours | Attente pièces / externe | exécuter |
| Reprendre | En attente | En cours | exécuter |
| Terminer (contrôles) | En cours, En attente | Terminé | exécuter |
| Valider (coûts figés) | Terminé | Validé | valider |
| Renvoyer (commentaire) | Terminé | En cours | valider |
| Annuler (motif) | tout statut ouvert | Annulé | gérer |

Arrêts machine : ouverts à la déclaration d'une panne avec arrêt de production (ou au démarrage d'un OT marqué « arrêt »), clos à la fin, au refus de la demande ou à l'annulation. Ils serviront au calcul du MTBF, du MTTR et de la disponibilité (phase 6).

## Maintenance préventive

- Le déclencheur est porté par le plan (un plan = un déclencheur ; la table `PlanTrigger` du dossier de conception a été fusionnée dans le plan, plus simple à saisir).
- `apps/preventive/services.py` : `due_status` (dû ou non, échéance de l'OT), `generate_due_work_orders` (création), `on_work_order_closed` (recalcul).
- Unicité : tant qu'un OT du plan n'est ni validé ni annulé, aucun nouvel OT n'est créé (un OT « Terminé » non validé bloque donc le suivant).
- Calendrier : dû quand aujourd'hui ≥ échéance − anticipation. Compteur : dû quand valeur ≥ dernier entretien + intervalle − anticipation ; la date estimée vient de l'usage moyen des 30 derniers jours de relevés.
- Validation : périodicité fixe → échéance d'origine + N périodes (première date postérieure à la réalisation) ; glissante → date de réalisation + 1 période ; le compteur repart de sa valeur actuelle. Annulation : l'échéance est sautée.
- Déclencheurs de la génération : service Docker `scheduler` (`run_scheduler`, au démarrage puis chaque jour à `EASYMAINT_SCHEDULER_HOUR`), signal `post_save` des relevés de compteur (après validation de la transaction), bouton manuel. Le planificateur attend que les migrations soient appliquées avant de travailler.

## Maintenance conditionnelle

- Modèle unique « point × paramètre × seuil » pour le vibratoire, l'huile et les contrôles personnalisés : un nouveau type de mesure est un paramètre, pas une table.
- Niveau d'une mesure : seuil en vigueur à sa date (version la plus récente déjà applicable, à défaut la plus ancienne) ; côtés haut et bas évalués, le plus grave l'emporte ; sans seuil : « sans seuil », aucune alerte.
- Alertes : une seule alerte non close par point et paramètre ; une mesure saisie après coup, plus ancienne que la dernière connue, ne modifie pas l'alerte.
- Règles : évaluées à chaque mesure au moins au niveau de la règle ; « N consécutives » = les N dernières mesures du point et du paramètre ; une seule demande ou un seul OT par alerte. Les demandes et OT automatiques sont créés par le système (`automatic=True`, sans utilisateur).
- Les services du conditionnel ne contrôlent pas les droits (ils servent aussi à la démonstration et aux imports) : les vues le font (`condition.view`, `condition.record`, `condition.manage`).
- Écart au dossier de conception : le prélèvement d'huile (`OilSample`) est une tournée de type « analyse d'huile » portant les champs propres au laboratoire, ses résultats étant des mesures ordinaires.

## Import de mesures et API

- `apps/condition/importer.py` : lecture (CSV avec détection de l'encodage et du séparateur ; Excel `.xlsx` en lecture seule, feuille « Mesures » ou première feuille), correspondance `{"columns": {champ: colonne}, "values": {colonne: code paramètre}}` (formats long et large combinables), analyse ligne à ligne (`Resolver` partagé avec l'API), puis `execute()`.
- `execute()` relit le fichier conservé, regroupe les mesures en tournées (équipement, type, date, technicien), les enregistre par `services.record_session` dans l'ordre chronologique — mêmes niveaux, alertes et règles que la saisie — dans une seule transaction, avec verrou sur l'import (pas de double exécution).
- Doublon = même point, même paramètre, même date, en base ou dans le fichier : ignoré, jamais en erreur. Les tournées gardent leur origine (`source_import`, `source_api`).
- API : `TokenAuthentication` de DRF (jeton par compte). Le middleware ne voit pas l'utilisateur d'un jeton ; `apps.core.api.TenantAPIMixin` pose l'entreprise après l'authentification DRF, avec les mêmes contrôles (entreprise active, sous-domaine en SaaS), et la retire en fin de requête. Toutes les vues API en héritent.
- Droits : `imports.run` pour les écrans d'import ; `condition.view` / `condition.record` pour l'API des mesures.

## Stock

- Le stock d'un article est tenu **par magasin** (`StockLevel`) et ne se saisit jamais : il ne change que par un mouvement (`StockMovement`), via `apps/inventory/services.py`. Chaque mouvement porte un numéro `MVT-AAAA-…`, sa quantité signée, son coût unitaire, sa valeur, le stock du magasin et le CMP après mouvement, l'auteur, le motif et le document associé (OT, bon de livraison, inventaire).
- Les mouvements sont définitifs : `save()` sur un mouvement existant et `delete()` lèvent une erreur. Une erreur se corrige par un ajustement ou un retour.
- `_record()` verrouille l'article puis la ligne de stock (`select_for_update`), refuse le stock négatif et recalcule le CMP aux entrées valorisées : `CMP = (stock total × CMP + quantité × coût) / (stock total + quantité)`, tous magasins confondus. Sorties, transferts et inventaires négatifs sont valorisés au CMP sans le modifier ; tant qu'aucune entrée n'a fixé le CMP, le prix de référence de l'article sert de coût.
- Réservation : une pièce demandée sur un OT (`WorkOrderPart`, statuts demandée → partiellement délivrée → délivrée, ou soldée / annulée) réserve `quantité − délivré` dans son magasin. **Disponible = physique − réservé.** Sorties hors OT et transferts ne peuvent pas entamer le réservé ; la délivrance consomme sa propre réservation.
- Délivrance (magasinier, `stock.move`) : sortie au CMP du moment imputée à l'OT ; le retour d'une pièce non utilisée rentre au coût de sa sortie (le CMP en tient compte). La valeur nette (`issued_value`) est ajoutée au coût « pièces » de l'OT par `workorders.services.PARTS_COST_PROVIDERS`, sans que `workorders` importe `inventory`. Après validation de l'OT, plus de retour (coûts figés).
- À la validation ou à l'annulation d'un OT (signal `work_order_closed`), les quantités non délivrées sont libérées.
- Plans préventifs : une pièce de plan reliée à un article (`PlanPart.item`) est demandée automatiquement, dans le magasin le mieux approvisionné, à chaque création d'OT.
- Preuve de remise : bons de sortie et de retour imprimables à signer (`movement_slip`) ; un bon regroupe les mouvements de même OT, même type, même jour, même magasinier et même magasin. Une confirmation numérique (accusé de réception, code personnel) pourra s'y ajouter.
- Achats : EasyMaint s'arrête à la demande d'achat imprimée (`PurchaseRequest`, `DA-AAAA-…`, sans statut) et à l'entrée en stock. `receive_order()` enregistre les lignes d'un bon de commande papier sous un seul n° de mouvement (n° de BC dans `StockMovement.purchase_order`) ; chaque entrée avec fournisseur met à jour `ItemSupplier.price`. L'historique des prix est lu dans les entrées (`price_history`). Quantité de réapprovisionnement : maximum (à défaut minimum) − disponible, arrondie à l'unité pour les articles comptés.
- Inventaire (`StockCount`, `INV-AAAA-…`) : lignes créées à l'ouverture avec le stock théorique ; à la validation, chaque article compté est porté à la quantité comptée par un mouvement « Inventaire » de l'écart ; les articles non comptés ne bougent pas. Un seul inventaire ouvert par magasin.
- Droits : `inventory.view` (consulter), `inventory.manage` (articles, fournisseurs, magasins, nomenclatures), `stock.move` (mouvements, délivrance, retours), `stock.count` (inventaires). Une pièce se demande depuis l'OT par qui peut l'exécuter (technicien affecté ou responsable).

## Coûts et budget

- Coût réel = OT **validés** (coûts figés à la validation : main-d'œuvre au taux figé du pointage, pièces du magasin au CMP de sortie nettes des retours, pièces hors magasin, prestations, autres dépenses), datés de la **fin réelle** des travaux (à défaut de la validation), + **sorties de stock hors OT** imputées à un équipement (catégorie « pièces », type « Pièces hors OT »). Un OT non validé n'est jamais compté.
- Unité d'un coût : premier ancêtre de type « Unité » de la localisation de l'équipement (sinon « Hors unité »). Famille : famille de premier niveau.
- Budget : un enregistrement par année et par unité, douze montants mensuels ; « Répartir à parts égales » divise le montant annuel et reporte l'arrondi sur décembre. Taux de consommation = réel / budget de l'année.
- Calculs dans `apps/finance/selectors.py` (lecture seule) ; PDF par ReportLab (`apps/finance/pdf.py`).

## Indicateurs (phase 6B)

Les définitions faisant foi sont dans `apps/kpi/selectors.py` (`DEFINITIONS`), affichées telles quelles sur la page « Définitions des indicateurs ». En résumé :
- Temps requis = jours de fonctionnement de la période (jours par semaine de l'équipement, à partir du lundi) × heures requises par jour, sans compter les jours à venir.
- Arrêts : `DowntimeEvent` avec arrêt de production, comptés jour par jour sur les seuls jours de fonctionnement et plafonnés aux heures requises du jour ; un arrêt en cours compte jusqu'à maintenant.
- Panne : OT correctif terminé ou validé, daté de son début réel. MTBF = (TR − arrêts pour panne) ÷ pannes ; MTTR = moyenne (fin réelle − début réel) ; disponibilité opérationnelle = (TR − tous arrêts) ÷ TR ; intrinsèque = (TR − arrêts pour panne) ÷ TR.
- Accueil : `apps/dashboard/blocks.py` déclare les blocs (capacité, gabarit, largeur, fonction de calcul appelée seulement si le bloc est affiché) et la présentation par défaut de chaque rôle ; `DashboardLayout` mémorise le choix de l'utilisateur.

## Imports et documents (phase 7A)

- `apps/imports/importers.py` : un `Importer` par type déclare ses colonnes (`Field` : clé, libellé du modèle, synonymes), analyse chaque ligne (`Row` : création, mise à jour, ignorée, messages) et enregistre dans une transaction unique. La lecture des fichiers est celle des mesures (`apps.condition.importer.read_table`).
- PDF : `apps/core/pdf.py` (`table_report` pour les tableaux, `document` pour les fiches à sections et signatures), ReportLab, police Helvetica (les espaces fines insécables sont remplacées).
- Rapport mensuel : `apps/kpi/reports.py` ; le planificateur appelle `generate_missing_for_all_tenants()` chaque jour (sans effet si le rapport du mois écoulé existe).

## Notifications, sécurité et sauvegardes (phase 7B)

- `apps/notifications` : modèle `Notification` (destinataire, type, titre, lien, lue le). Les déclencheurs (`receivers.py`) écoutent les enregistrements des autres modules par signaux Django : les modules métier ne connaissent pas les notifications. Destinataires choisis par capacité (`users_with`) ; l'auteur de l'action (utilisateur courant posé par `TenantMiddleware`, `get_current_user()`) est exclu. Une erreur de notification ne fait jamais échouer l'action métier (point de sauvegarde).
- Blocage des connexions : `apps/accounts/lockout.py`, calculé sur les échecs du journal d'audit (index `action, at`), appliqué par `LockoutMixin` au formulaire de connexion et à celui de l'administration.
- En-têtes : `SecurityHeadersMiddleware` (CSP sans script en ligne, Permissions-Policy). Les comportements de page passent par des attributs `data-print`, `data-autosubmit` et le fichier `static/js/easymaint.js`.
- `apps/core/tests/test_security.py` parcourt toutes les adresses déclarées : un nouvel écran sans contrôle de droit fait échouer les tests.
- Sauvegardes : service `backup` (image `postgres:16-alpine`, script `scripts/backup_daemon.sh`), dossier `sauvegardes` monté en lecture seule dans `web` pour la page d'état.
- Cache : `CACHES` en mémoire du processus ; les blocs `cached=True` de l'accueil sont mis en cache par entreprise et par jour.

## Indicateurs du préventif

Sur les OT préventifs dont l'échéance d'origine tombe dans les 30 derniers jours :

- taux de réalisation = OT terminés ou validés / OT échus ;
- respect du planning = OT terminés au plus tard à leur échéance d'origine / OT échus ;
- un OT annulé compte comme non réalisé ; un report ne change pas l'échéance d'origine.

## Numérotation

`next_document_number("OT")` → `OT-2026-000001`, par entreprise et par année, avec verrouillage de ligne : pas de doublon en accès simultané. Utilisé à partir de la phase 3 (OT, DI, DA, BC, mouvements MVT, inventaires INV).

## Formats

Français (référence) et anglais. Une langue par installation : `EASYMAINT_LANGUAGE` → `LANGUAGE_CODE` (pas de choix par utilisateur, pas de `LocaleMiddleware`). Dates `JJ/MM/AAAA` dans les deux langues (`config/formats/fr`, `config/formats/en`) ; nombres et montants mis en forme par `apps/core/formatting.py` selon la langue active (filtres `|money`, `|number`), mois et jours par `month_name`, `month_abbr`, `weekday_abbreviations`. Catalogue anglais : `locale/en/LC_MESSAGES/django.po`, complet (test d'extraction). Les modèles d'import reconnaissent les titres de colonnes dans toutes les langues disponibles (`label_variants`, `AVAILABLE_LANGUAGES`). Démonstration anglaise : `apps/core/demo_i18n.py`.

## Interface

Gabarits Django + HTMX (filtres et recherche sans rechargement) + Bootstrap 5. Bibliothèques front copiées localement (`scripts/vendor_static.sh`) : aucun appel Internet en fonctionnement. Le menu latéral (`apps/core/navigation.py`) n'affiche que les modules livrés et autorisés.

## Déploiement

Image Docker unique (`docker/Dockerfile`), Gunicorn, fichiers statiques servis par WhiteNoise, PostgreSQL 16. Configuration par variables d'environnement (`.env`) ; `EASYMAINT_DEPLOYMENT_MODE=onprem|saas`. Les tâches planifiées tournent dans un second conteneur (`scheduler`) issu de la même image : pas de Celery ni de Redis, suffisant pour une génération quotidienne et plus léger à installer. Un troisième conteneur (`backup`) réalise les sauvegardes nocturnes. En SaaS, `docker-compose.saas.yml` ajoute Caddy (HTTPS à la demande, contrôlé par `/interne/tls/`, qui n'accepte que les sous-domaines des entreprises actives) ; voir docs/deploiement-cloud.md.

## Écarts assumés par rapport au dossier de conception (phase 1)

- Historique des modifications : journal d'audit maison (valeurs avant/après lisibles) au lieu de django-simple-history, pour une seule source d'historique et moins de dépendances.
- Journal des connexions fusionné dans `AuditLog` (actions `login`, `login_failed`, `logout`).
- Tâches planifiées : service `scheduler` au lieu de Celery + Redis.
- Déclencheur préventif porté par le plan (pas de table `PlanTrigger` séparée).
