# Historique des versions

## 1.1.0 — Version anglaise (08/11/2026)

### Langue choisie à l'installation
- Français ou anglais, choisi une fois pour toutes à l'installation (question posée par `install.ps1` / `install.sh`, réglage `EASYMAINT_LANGUAGE` du `.env`). Toute l'entreprise travaille ensuite dans cette langue. Une installation existante reste en français.

### Tout le logiciel en anglais
- Écrans, messages, menus, droits, statuts, définitions des indicateurs, notifications, graphiques (environ 2 200 textes).
- Documents et rapports dans la langue de l'installation : fiches d'intervention et d'équipement, bons de sortie et de retour, demandes d'achat, rapports de coûts, de budget, d'indicateurs et rapport mensuel, exports Excel, modèles d'import.
- Imports : un fichier dont les titres de colonnes sont en français ou en anglais est reconnu dans les deux cas (oui/yes, unités, types de maintenance).
- Formats : dates JJ/MM/AAAA dans les deux langues ; nombres 1 234,5 en français, 1,234.5 en anglais ; noms des mois et des jours traduits.
- Rôles prédéfinis affichés dans la langue de l'installation (tant que leur nom n'a pas été modifié).

### Démonstration en anglais
- Sur une installation en anglais, `load_demo` charge une démonstration entièrement en anglais. `--lang en --code demo-en` permet aussi de la charger à côté de la démonstration française (comptes `s.bensalah.en`…).

### Contrôle automatique
- Un test extrait tous les textes du logiciel (comme `makemessages`) et échoue s'il en reste un seul sans traduction anglaise ; il vérifie aussi les variables (%(n)s…) de chaque traduction. Le fichier `locale/en/LC_MESSAGES/django.po` est contrôlé et compilé à la construction de l'image.

## 1.0.0 — Version 1.0 : installation, déploiement en ligne, licence libre (08/11/2026)

### Installation et mise à jour
- Installation en une commande : `scripts/install.ps1` (Windows) et `scripts/install.sh` (Linux) vérifient Docker, créent le `.env` avec une clé secrète et un mot de passe de base générés (jamais affichés), démarrent EasyMaint et créent l'entreprise et son administrateur (option démonstration).
- Mise à jour en une commande : `scripts/update.ps1` et `scripts/update.sh` (récupération par Git si disponible, sauvegarde préalable, reconstruction, redémarrage).

### Déploiement en ligne (SaaS)
- `docker-compose.saas.yml` et `docker/Caddyfile` : Caddy en frontal, HTTPS automatique (Let's Encrypt) pour le domaine et le sous-domaine de chaque entreprise ; certificats accordés seulement aux entreprises actives ; application non exposée directement.
- Guide pas à pas `docs/deploiement-cloud.md` (serveur loué, DNS, sécurité, ajout et suspension d'un client, sauvegardes hors serveur, surveillance).

### Licence libre
- EasyMaint est publié sous licence GNU AGPL-3.0 (fichiers `LICENSE`, `COPYRIGHT`, `CONTRIBUTING.md`).
- Page « À propos » (lien en bas du menu et sur la page de connexion) : version, licence, adresse du code source (`EASYMAINT_SOURCE_URL`), composants libres utilisés.

### Documentation
- README refondu (fonctions, installation rapide, licence et services), guide d'installation et d'exploitation `docs/installation.md` avec dépannage.

### Technique
- Adresses simplifiées : recherche `/recherche/`, sauvegardes `/parametres/sauvegardes/`, à propos `/a-propos/`.
- Production derrière HTTPS : sous-domaines inclus dans HSTS, appel interne de Caddy exempté de la redirection HTTPS.

## 0.7.0-b — Phase 7, partie B : sécurité, notifications, sauvegardes, performances (08/11/2026)

### Notifications (dans l'application uniquement)
- Cloche dans la barre supérieure (nombre de notifications non lues, les 6 dernières) et page « Mes notifications » (toutes / non lues, tout marquer comme lu).
- Déclencheurs : OT affecté à un technicien (le technicien) ; nouvelle demande d'intervention (les personnes qui analysent les demandes) ; nouvelle alerte conditionnelle (les personnes qui gèrent le conditionnel) ; pièce demandée au magasin pour un OT (les magasiniers) ; OT terminé (les personnes qui valident).
- L'auteur d'une action n'est pas notifié de sa propre action. Ouvrir une notification la marque comme lue et mène à l'élément concerné.
- Nettoyage automatique chaque nuit : notifications lues de plus de 90 jours, toutes celles de plus d'un an.

### Sécurité
- Blocage de la connexion après 5 échecs en 15 minutes pour un même identifiant (20 pour une même adresse IP), pendant 15 minutes ; le mot de passe n'est pas testé pendant le blocage. Réglable dans le `.env`. S'applique aussi à l'administration de la plateforme.
- Politique de sécurité du contenu (CSP) : seuls les scripts d'EasyMaint s'exécutent (plus aucun script dans les pages) ; en-têtes Permissions-Policy, Referrer-Policy, X-Frame-Options, nosniff, Cross-Origin-Opener-Policy.
- L'adresse IP n'est plus lue dans l'en-tête X-Forwarded-For (falsifiable) sauf derrière un proxy de confiance (`EASYMAINT_BEHIND_PROXY=true`).
- Test automatique qui parcourt toutes les adresses de l'application : aucune page n'est accessible sans connexion, ni sans le droit requis.

### Sauvegardes
- Nouveau service Docker `backup` : sauvegarde automatique chaque nuit (base + fichiers joints) dans le dossier `sauvegardes`, rotation sur 14 jours, écriture sans fichier incomplet ; sauvegarde immédiate en une commande.
- Page Paramètres › Sauvegardes (installation locale) : liste des sauvegardes, alerte si la dernière a plus de 2 jours.
- Les scripts de restauration acceptent l'archive des fichiers de la sauvegarde automatique.

### Performances
- Index sur les OT (liste, type et statut, échéance, fin des travaux) et sur les demandes.
- Indicateurs de l'accueil communs à l'entreprise (fiabilité, tendance, top 10, coûts) gardés en cache 10 minutes.

### Préparation multilingue
- Langue et sens de lecture de la page suivant la langue active (arabe de droite à gauche, Bootstrap RTL) ; langues activées par `EASYMAINT_LANGUAGES` (français seul tant que les traductions ne sont pas livrées). Procédure de traduction dans `locale/LISEZMOI.md`.

## 0.7.0-a — Phase 7, partie A : imports, exports et documents (08/11/2026)

### Imports de données (Paramètres › Imports de données)
- Équipements, fournisseurs, articles (avec stock initial, emplacement et fournisseur), historique de maintenance.
- Pour chacun : modèle Excel avec ligne d'exemple et notice, colonnes reconnues d'après leur titre, aperçu (création, mise à jour, ignorée, refusée avec motif), confirmation tout ou rien, fichier d'origine et bilan conservés.
- Option « mettre à jour les fiches existantes » (même code ou référence) ; familles et fabricants créés s'ils manquent.
- Historique : chaque ligne devient un OT validé à ses dates réelles (numéro de l'année de l'intervention), avec un arrêt machine si demandé ; MTBF, MTTR, disponibilité et coûts en tiennent compte ; une ligne déjà importée est ignorée.

### Documents
- Fiche d'intervention PDF (bouton « Fiche PDF » de l'OT) : vierge à remplir avant les travaux (lignes, cases, signatures), compte rendu complet après (check-list, pièces du magasin et hors magasin, temps, dépenses, coûts validés si le droit le permet).
- Fiche équipement PDF : identification, compteurs, plans préventifs, points de mesure, nomenclature, dernières interventions, coûts par année (selon les droits).
- Export Excel de la liste des OT, avec les filtres de l'écran.

### Rapport mensuel
- Rapport PDF du mois écoulé produit automatiquement par le planificateur (dès le 1er du mois) et conservé dans Indicateurs › Rapports mensuels ; production ou mise à jour à la demande ; commande `generate_monthly_report`.

### Technique
- Mise en page PDF commune (`apps/core/pdf.py`) pour tous les documents.

## 0.6.0 — Phase 6, partie B : indicateurs et tableau de bord (08/11/2026)

### Indicateurs
- Nouveau menu « Indicateurs » : MTBF, MTTR, durée moyenne d'arrêt par panne, disponibilité opérationnelle et intrinsèque, nombre de pannes (dont avec arrêt), durée des arrêts, taux de réalisation du préventif, respect du planning, taux de correctif (en nombre et en heures), backlog (heures et jours-homme), OT en retard, consommation de pièces, coût de maintenance, valeur du stock.
- Période et filtres (unité, famille, équipement) ; tableau par équipement ; top 10 des équipements les plus défaillants et les plus coûteux ; graphiques sur 12 mois (pannes et disponibilité, MTBF et MTTR, coût mensuel), répartition des OT par type, interventions par unité.
- Page « Définitions des indicateurs » : chaque formule et sa période, reprises dans l'export Excel et le rapport PDF.
- Fiche équipement : « jours de fonctionnement par semaine » (6 par défaut), utilisé avec les heures requises par jour pour le temps requis. Un arrêt n'est compté que les jours de fonctionnement, dans la limite des heures requises du jour.

### Accueil personnalisable
- L'accueil est composé de blocs (interventions, mes interventions, fiabilité sur 30 jours, tendance sur 12 mois, alertes conditionnelles, coûts, stock, préventif, équipements les plus défaillants et les plus coûteux, OT en retard, parc, équipements en panne, compteurs, dernières modifications).
- Chaque utilisateur choisit ses blocs et leur ordre (« Personnaliser l'accueil ») ; à défaut, une présentation adaptée à son rôle s'applique. Seuls les blocs autorisés par le rôle sont proposés, et un bloc retiré des droits disparaît même s'il avait été choisi.

## 0.6.0-a — Phase 6, partie A : coûts et budget (08/11/2026)

### Coûts réels
- Nouveau menu « Coûts et budget ». Sources : OT validés (main-d'œuvre, pièces du magasin et hors magasin, prestations externes, autres dépenses, figés à la validation), datés de la fin des travaux, et sorties de stock hors OT imputées à un équipement.
- Analyse sur une période, regroupée par équipement, unité, famille (premier niveau), type de maintenance ou mois ; filtres par unité, famille, type et équipement ; totaux par catégorie, part de chaque ligne, graphique de répartition et évolution mensuelle comparée à l'année précédente.
- Export Excel et rapport PDF (en-tête de l'entreprise, période, filtres, pied de page numéroté).

### Budget
- Budget annuel par unité, réparti à parts égales ou mois par mois ; comparaison budget / réel par mois et par unité (dépassements en rouge), taux de consommation, reste ; courbes cumulées ; rapport PDF. Saisie réservée au droit « Gérer les budgets ».

### Intégration
- Fiche équipement : onglet « Coûts » (historique financier par année et par catégorie, répartition par type, OT les plus coûteux).
- Accueil : coût du mois et dépense de l'année rapportée au budget annuel.
- Démonstration : un budget par unité pour l'année en cours.
- Nouvelle dépendance : ReportLab (génération des PDF, sans bibliothèque système).

## 0.5.0 — Phase 5, partie B : demandes d'achat et prix (08/11/2026)

Les achats (commande, réception fournisseur, facture, paiement) restent gérés par le service achats dans son propre logiciel. EasyMaint prépare la demande et enregistre l'entrée en stock.

### Demandes d'achat
- Demande d'achat `DA-AAAA-…` : fournisseur suggéré, motif, OT et équipement concernés, date souhaitée, urgence, observations ; lignes avec un article du magasin (désignation, unité et dernier prix repris automatiquement) ou une pièce non stockée décrite librement.
- Impression A4 avec les cases « Demandé par », « Visa du responsable maintenance » et « Reçu par le service achats » : la validation se fait par signature, sans circuit dans le logiciel.
- Réapprovisionnement : depuis les articles sous le minimum, quantités proposées pour revenir au stock maximum (à défaut au minimum), compte tenu des réservations ; une demande par fournisseur principal, modifiable avant impression.

### Entrée sur bon de commande
- Écran « Entrée sur bon de commande » : fournisseur, n° de BC du service achats, n° de bon de livraison, magasin, puis toutes les lignes du BC (article, quantité reçue, prix unitaire HT). Tout ou rien, un seul n° de mouvement.
- Chaque entrée met à jour le coût moyen pondéré et le prix de l'article chez ce fournisseur (fournisseur ajouté à l'article s'il n'y figurait pas).
- Le n° de BC est aussi saisissable sur une entrée simple et apparaît dans l'historique des mouvements.

### Historique des prix
- Fiche article : prix d'achat constatés à chaque entrée (date, fournisseur, BC), avec courbe d'évolution.

### Autres
- Démonstration : n° de BC sur les entrées, demandes de réapprovisionnement préparées, demande urgente d'un capteur non stocké pour la presse.

## 0.5.0-a — Phase 5, partie A : pièces de rechange et stock (07/11/2026)

### Articles et référentiels
- Nouveau module **Magasin** : articles (référence unique, désignation, famille, marque, fabricant, référence constructeur, unité, photo, fiche technique, prix de référence, stock mini et maxi, délai d'approvisionnement, pièce critique), familles, magasins, fournisseurs (contact, matricule fiscal) et fournisseurs de chaque article avec leur référence, leur prix et leur délai.
- Emplacement de l'article dans chaque magasin.
- Liste des articles : stock physique, réservé, disponible, CMP, valeur ; filtres (sous le minimum, en rupture, pièces critiques, désactivés), recherche (référence, désignation, marque, référence constructeur ou fournisseur), export Excel. Recherche globale étendue aux articles.

### Stock
- Stock tenu par magasin, uniquement par des mouvements : entrée, sortie hors OT, transfert, ajustement, inventaire, délivrance et retour pour un OT. Chaque mouvement est numéroté (`MVT-AAAA-…`), horodaté, valorisé, rattaché à son auteur, son motif et son document ; il ne se modifie ni ne se supprime.
- Valorisation au coût moyen pondéré, recalculé à chaque entrée.
- Stock négatif interdit ; les quantités réservées pour des OT ne peuvent être ni sorties ni transférées.
- Historique des mouvements filtrable (article, type, magasin, dates, OT, document) et exportable.
- Inventaires : ouverture par magasin (et famille), feuille de comptage Excel, saisie, validation qui enregistre les écarts ; un seul inventaire ouvert par magasin.

### Lien avec la maintenance
- Sur l'OT, bloc « Pièces du magasin » : le technicien affecté ou le responsable demande une pièce, qui lui est réservée ; le magasinier la délivre depuis l'écran « Pièces à délivrer », où il enregistre aussi les retours de pièces non utilisées (sans avoir besoin d'accéder aux OT). La valeur des pièces délivrées entre dans le coût de l'OT, figé à la validation ; ce qui n'est pas délivré est libéré à la validation ou à l'annulation.
- Les pièces hors magasin (achat direct, dépannage) restent saisissables librement.
- Plans préventifs : une pièce prévue peut être un article du magasin ; elle est réservée automatiquement à chaque OT généré.
- Fiche équipement : onglet « Pièces » (nomenclature avec repères, disponibilité, pièces en attente, consommations).
- Accueil : carte « Stock sous le minimum », valeur du stock, pièces à délivrer.

### Bons signés
- Bon de sortie et bon de retour imprimables (A4), avec les cases « Remis par (magasin) » et « Reçu par (technicien) », ou « Réceptionné par » et « Rapporté par » pour un retour. Les délivrances du même jour pour un même OT, par le même magasinier et le même magasin, figurent sur un seul bon. Lien proposé juste après chaque délivrance ou retour, et accessible depuis l'OT, l'écran « Pièces à délivrer » et l'historique des mouvements.

### Autres
- Numérotation `INV-AAAA-…` pour les inventaires.
- Démonstration : 2 magasins, 5 fournisseurs, 27 articles, six mois de mouvements, un transfert, un inventaire avec écart, la nomenclature de cinq équipements, des pièces demandées et délivrées sur les OT ouverts, les pièces des plans préventifs reliées au magasin.

## 0.4.1 — Correctif de la phase 4B (07/11/2026)

- Le téléchargement du modèle Excel d'import des mesures échouait (libellé du type de mesure mal converti).

## 0.4.0 — Phase 4, partie B : import des mesures et API capteurs (07/11/2026)

### Import de fichiers
- Conditionnel › Imports : envoi d'un fichier CSV (séparateur `;` `,` ou tabulation, UTF-8 ou Windows) ou Excel `.xlsx`.
- Modèle Excel à télécharger, pré-rempli avec les codes de l'entreprise, avec les feuilles Référentiel (points et paramètres) et Techniciens.
- Correspondance des colonnes détectée automatiquement d'après les titres, modifiable à l'écran ; deux dispositions acceptées (une mesure par ligne, ou une colonne par paramètre), combinables.
- Formats mémorisés : la correspondance d'un appareil ou d'un laboratoire s'enregistre sous un nom et se réapplique aux fichiers suivants.
- Aperçu avant enregistrement : mesures à importer, tournées créées, doublons, lignes refusées avec leur motif.
- Enregistrement identique à la saisie manuelle : niveaux selon les seuils en vigueur à la date de la mesure, alertes, règles de déclenchement ; traitement dans l'ordre chronologique.
- Doublons (même point, même paramètre, même date) ignorés : un fichier corrigé peut être réimporté sans risque.
- Historique des imports : fichier d'origine conservé et téléchargeable, correspondance utilisée, bilan ligne à ligne, tournées créées. Les tournées importées indiquent leur origine.

### API capteurs
- `POST /api/v1/mesures/` : une tournée envoyée par un capteur, une passerelle ou un logiciel ; mêmes contrôles et mêmes effets que la saisie ; renvoi sans effet en cas de répétition. `GET` : dernières mesures filtrables.
- Authentification par jeton (`Authorization: Token …`), commande `create_api_token`. Le jeton fonctionne aussi pour l'API des équipements.

### Autres
- Démonstration : un format d'import « Collecteur vibratoire (export CSV) ».

## 0.4.0-a1 — Ajustement de la phase 4A (07/11/2026)

- Création et modification d'un point de mesure : les paramètres sont regroupés par catégorie, avec un titre par famille (analyse vibratoire, analyse d'huile, température, pression…), dans l'ordre métier.

## 0.4.0-a — Phase 4, partie A : maintenance conditionnelle (07/11/2026)

### Référentiel
- Paramètres de mesure libres (code, nom, unité, catégorie, sens d'alerte : hausse, baisse ou plage) : vibratoire (vitesse mm/s RMS, accélération m/s², déplacement µm, fréquence dominante Hz), huile (viscosité, TAN, eau, Fe, Cu, Al, Cr, Si, code ISO 4406), température, pression, débit, intensité, énergie, épaisseur, autres.
- Points de mesure par équipement (emplacement, direction H/V/A, photo, paramètres mesurés).
- Seuils à 4 niveaux (normal, attention, alarme, critique), hauts et/ou bas, par point et par paramètre, avec leur source (norme, constructeur, laboratoire, retour d'expérience) et leur date d'application. Chaque modification crée une version : les mesures anciennes restent jugées avec les seuils de leur époque. Aucun seuil n'est fourni par le logiciel.

### Mesures
- Saisie en grille par équipement : relevé / contrôle, analyse vibratoire (vitesse de rotation, régime) ou analyse d'huile (type d'huile, heures de fonctionnement et de l'huile, laboratoire, n° et conclusion du rapport), avec fichier joint (rapport, export d'appareil).
- Niveau calculé pour chaque valeur ; virgule ou point décimal acceptés.
- Courbes d'évolution par point et paramètre, seuils tracés, points colorés selon le niveau.

### Alertes et règles
- Toute mesure au moins « attention » ouvre une alerte, ou met à jour celle déjà ouverte sur le même point et le même paramètre (niveau actuel, niveau le plus grave, retour à la normale).
- Acquittement (techniciens), clôture motivée (responsables), création d'un OT conditionnel ou d'une demande d'intervention depuis l'alerte.
- Règles de déclenchement : paramètre, équipement (ou tous), niveau minimal, nombre de mesures consécutives, action (demande ou OT conditionnel), priorité. Une seule demande ou un seul OT par alerte.

### Intégration
- Fiche équipement : onglet « Mesures » (état de chaque point, alertes, dernières tournées, boutons de saisie).
- Accueil : carte des alertes conditionnelles. Recherche globale étendue aux points de mesure.
- Démonstration : 18 paramètres, 7 points, seuils documentés, 35 tournées, 4 alertes dont une vibration en alarme qui a déclenché une demande.

## 0.3.1 — Correctif (07/11/2026)

- PostgreSQL : la génération des OT préventifs et le recalcul d'échéance à la validation échouaient (« FOR UPDATE cannot be applied to the nullable side of an outer join »). Le verrou ne porte plus que sur la ligne du plan.
- Les tests tournent désormais sur PostgreSQL dans Docker, comme en production, pour détecter ce type d'écart que SQLite masque.

## 0.3.0 — Phase 3, partie B : maintenance préventive et planning (07/11/2026)

### Plans préventifs
- Plan : équipement, opération, instructions techniques, temps estimé, priorité, équipe, techniciens, compétences nécessaires, check-list, pièces prévues, documents associés.
- Déclenchement par calendrier (tous les N jours, semaines, mois ou ans : quotidien, hebdomadaire, mensuel, trimestriel, semestriel, annuel, personnalisé), par compteur (heures, cycles, km, compteurs personnalisés) ou les deux (« le premier atteint »).
- Anticipation réglable : en jours pour le calendrier, en unités pour le compteur.
- Périodicité fixe (à partir de l'échéance prévue) ou glissante (à partir de la date de réalisation).
- Un plan compteur démarre de la valeur actuelle du compteur si l'on ne précise pas la valeur au dernier entretien.

### Génération automatique des OT
- Nouveau service Docker `scheduler` : vérification au démarrage puis chaque nuit (heure réglable par `EASYMAINT_SCHEDULER_HOUR`, 2 h par défaut).
- Vérification immédiate après chaque relevé de compteur.
- Jamais deux OT en attente pour un même plan ; la check-list du plan est copiée dans l'OT.
- Bouton « Générer l'OT maintenant » sur la fiche plan ; commande `python manage.py generate_preventive`.
- À la validation de l'OT, l'échéance suivante se recalcule ; à l'annulation, l'échéance est sautée.

### Report et planning
- Report d'un OT (nouvelle date + motif) : l'échéance d'origine est conservée et affichée.
- Planning jour, semaine et mois : OT par date prévue, couleur par type, retards en rouge, réalisés en vert, prévisions des plans en pointillé ; filtres par équipe et par technicien ; heures estimées par jour.

### Indicateurs
- Taux de réalisation du préventif et respect du planning sur 30 jours glissants (accueil et liste des plans), préventifs à réaliser sous 7 jours.

### Autres
- Fiche équipement : bloc « Plans préventifs ». OT : lien vers le plan, pièces prévues, échéance d'origine.
- Recherche globale étendue aux plans préventifs.
- Démonstration : 9 plans (calendrier, compteur, combinés) reliés aux OT existants et un mois d'historique.
- Correctif 0.3.0-a1 intégré (test de l'écran technicien, avertissement Django 6).

## 0.3.0-a — Phase 3, partie A : interventions correctives (06/11/2026)

### Techniciens et équipes
- Fiches techniciens (matricule, spécialité, compétences, équipe, coût horaire et heures supplémentaires), reliables à un compte utilisateur.
- Équipes avec chef d'équipe, compétences, sous-traitants.

### Demandes d'intervention
- Déclaration en un écran (équipement, description, priorité, arrêt de production), y compris depuis la fiche équipement.
- Une déclaration avec arrêt de production passe l'équipement « En panne » et ouvre un arrêt machine horodaté.
- Analyse par le responsable : acceptation (création de l'OT, puis planification) ou refus motivé (l'arrêt est clos).
- Chaque demandeur ne voit que ses propres demandes ; la maintenance les voit toutes.

### Ordres de travail
- Numérotation `OT-AAAA-000001`, création depuis une demande ou directe (les techniciens peuvent créer un OT urgent, qui leur est affecté).
- Cycle de statuts contrôlé : À planifier → Affecté → En cours → En attente de pièces / d'intervention externe → Terminé → Validé, ou Annulé (motif obligatoire). Historique de chaque changement.
- Planification : dates, temps estimé, équipe, techniciens (plusieurs), sous-traitant.
- Pointage par chronomètre (un seul actif par technicien) ou saisie manuelle, heures supplémentaires, taux figé à la saisie.
- Compte rendu : diagnostic, mode et cause de défaillance (référentiel), travaux réalisés ; check-list ; pièces utilisées (saisie libre en attendant le magasin de la phase 5) ; prestations et dépenses ; photos avant / après.
- Contrôles avant « Terminé » : compte rendu, cause (correctif), check-list complète, temps pointé.
- À la fin, l'arrêt machine est clos et l'équipement repasse « En service » s'il n'a plus d'autre arrêt ouvert.
- Validation par le responsable : coûts main-d'œuvre, pièces, externes, autres et total figés ; renvoi possible au technicien avec commentaire.
- Écran technicien sur téléphone, conforme à la maquette validée, et page « Mes interventions ».
- Liste filtrable (statut, texte, type, retard) ; recherche globale étendue aux OT et demandes.

### Autres
- Fiche équipement : onglet Interventions, nombre de pannes, coût cumulé des OT validés, boutons « Déclarer une panne » et « OT ».
- Accueil : demandes à traiter, OT en cours, en retard, à planifier (avec backlog en heures), à valider ; liste des OT en retard.
- Données de démonstration : 5 techniciens, 2 équipes, 11 OT historiques validés sur 5 mois, OT ouverts dans tous les états.
- Sauvegarde et restauration sous Windows : `scripts/backup.ps1`, `scripts/restore.ps1`.

## 0.2.1 — Ajustements de la phase 2 (06/11/2026)

- Le niveau de localisation « Atelier » s'appelle désormais **« Unité »** (Entreprise › Usine › Unité › Ligne). Les niveaux Ligne et Zone restent facultatifs : un équipement peut être rattaché directement à une unité.
- Démarrage en production : les bibliothèques front ne référencent plus de fichiers `.map` absents (corrigeait un échec de `collectstatic`).
- Suppression de deux avertissements de test (adresses web en https par défaut, bornes décimales de l'API).

## 0.2.0 — Phase 2 : noyau (06/11/2026)

### Socle
- Multi-entreprise strict : filtrage automatique par entreprise, refus des liens entre entreprises, fichiers servis uniquement après contrôle d'accès, contrôle du sous-domaine en mode SaaS.
- Numérotation des documents par entreprise et par année (`OT-2026-000001`), sûre en accès concurrent.
- Journal d'audit inaltérable : connexions, échecs, modifications avec valeurs avant / après, exports.
- Pièces jointes génériques (types autorisés, taille maximale paramétrable).
- Recherche globale extensible (équipements et localisations ; OT et pièces s'y ajouteront).
- Formats français : dates JJ/MM/AAAA, montants TND à 3 décimales, devise paramétrable par entreprise.

### Comptes et droits
- Connexion, déconnexion, changement de mot de passe, réinitialisation par l'administrateur.
- 8 rôles prédéfinis issus de la matrice validée, modifiables ; 29 capacités.
- Gestion des utilisateurs de l'entreprise ; garde-fous (pas d'auto-désactivation, l'Administrateur garde la gestion des utilisateurs).
- Commande `create_tenant` pour la première installation.

### Patrimoine
- Localisations en arborescence libre (usine › unité › ligne › zone), sans boucle possible.
- Familles (2 niveaux) et fabricants.
- Fiche équipement complète : identification, constructeur, localisation, sous-équipements, responsable, état, criticité A/B/C, photo, heures requises par jour (préparation de la disponibilité).
- Compteurs (heures, cycles, kilométrage, personnalisés) et relevés avec règles de cohérence.
- Documents techniques joints à l'équipement.
- Historique des modifications de chaque fiche.
- QR codes et planche d'étiquettes A4 imprimable.
- Liste filtrable (HTMX) et export Excel.
- API REST `/api/v1/` : équipements, localisations, familles, fabricants.

### Interface
- Menu latéral selon les droits, recherche globale (`/`), mise en page adaptée au téléphone.
- Tableau de bord initial sur données réelles : état du parc, équipements par unité et par état, équipements en panne, compteurs à relever, dernières modifications.

### Installation
- Docker Compose (PostgreSQL 16 + application), fonctionnement hors ligne, Linux ou Windows (Docker Desktop).
- Scripts de sauvegarde et de restauration.
- Données de démonstration (`load_demo`).
