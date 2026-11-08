# Prise en main d'EasyMaint

## Premier paramétrage (administrateur)

1. **Utilisateurs** (menu Paramètres) : créer les comptes et choisir un rôle pour chacun.
2. **Rôles et droits** : ajuster si besoin les droits des 8 rôles prédéfinis, ou créer un rôle.
3. **Familles et fabricants** : créer les familles d'équipements (deux niveaux possibles : Presses › Injection) et les fabricants.
4. **Localisations** : créer l'usine, puis « Ajouter dessous » pour les unités, puis éventuellement les lignes et zones. Un équipement peut être rattaché directement à une unité.
5. **Équipements** : depuis une localisation (« Équipement ») ou depuis la liste (« Nouvel équipement »).

## Au quotidien

- **Recherche globale** : touche `/` n'importe où, puis le code, la désignation ou le n° de série.
- **Liste des équipements** : filtres par état, localisation (sous-niveaux compris), famille et criticité ; export Excel de la liste filtrée.
- **Fiche équipement** : changer l'état en un clic, ajouter un sous-équipement, joindre manuels et plans, consulter l'historique des modifications.
- **Compteurs** : onglet Compteurs de la fiche, saisir la valeur et valider. Un compteur cumulatif refuse une valeur inférieure au relevé précédent. Le tableau de bord signale les compteurs non relevés depuis 30 jours.
- **Étiquettes QR** : bouton « Étiquettes QR » (liste filtrée ou fiche). Imprimer sur A4 ; le scan ouvre la fiche sur le téléphone après connexion.

## Interventions (phase 3A)

1. **Paramétrage** : Équipes › créer les techniciens (relier chacun à son compte pour qu'il pointe depuis son téléphone), les équipes ; Paramètres › Codes de défaillance.
2. **Déclarer une panne** : menu Demandes, ou bouton « Déclarer une panne » sur la fiche équipement. Cocher « La production est arrêtée » si c'est le cas.
3. **Traiter la demande** (responsable) : l'ouvrir, choisir type et priorité, « Accepter » ; l'écran de planification s'ouvre pour désigner les intervenants.
4. **Intervenir** (technicien) : Mes interventions › l'OT › « Démarrer l'intervention ». Cocher la check-list, ajouter les pièces et les photos, renseigner la cause et les travaux, puis « Terminer ».
5. **Valider** (responsable) : Ordres de travail › filtre « Terminés à valider » › « Valider ». Les coûts sont alors figés.

## Maintenance préventive (phase 3B)

1. **Créer un plan** : Préventif › Nouveau plan (ou « + Plan » sur la fiche équipement). Choisir le déclenchement :
   - *Calendrier* : « tous les 3 mois », première échéance, nombre de jours d'anticipation ;
   - *Compteur* : compteur de l'équipement, intervalle (par exemple 2 000 h), anticipation (par exemple 100 h) ;
   - *Les deux* : l'OT est créé dès que le premier seuil est atteint.
   La check-list se saisit un point par ligne ; les pièces prévues et les documents s'ajoutent sur la fiche du plan.
2. **Génération** : automatique chaque nuit et après chaque relevé de compteur. Le bouton « Générer l'OT maintenant » force la création.
3. **Réalisation** : l'OT préventif se traite comme un correctif (démarrer, check-list, terminer, valider). À la validation, la prochaine échéance du plan est recalculée.
4. **Reporter** : sur l'OT, « Reporter » (nouvelle date et motif). L'échéance d'origine reste visible et sert au calcul du respect du planning.
5. **Planning** : vues jour, semaine, mois ; filtres par équipe et technicien ; les prévisions des plans apparaissent en pointillé.

## Maintenance conditionnelle (phase 4A)

1. **Paramètres** (Conditionnel › Paramètres) : créer ce que vous mesurez, avec son unité et son sens d'alerte (« monte » pour une vibration, « plage » pour une viscosité).
2. **Points de mesure** : fiche équipement › onglet Mesures › « Point de mesure ». Cocher les paramètres mesurés à cet endroit.
3. **Seuils** : ouvrir le point, « Définir les seuils » pour chaque paramètre, en indiquant la source (norme, constructeur, laboratoire, retour d'expérience). Pour les changer plus tard, « Modifier les seuils » crée une nouvelle version à partir d'une date.
4. **Saisir** : onglet Mesures › « Relevé / contrôle », « Analyse vibratoire » ou « Analyse d'huile ». Remplir la grille (cases vides = non mesuré), le contexte, joindre le rapport.
5. **Alertes** : Conditionnel › Alertes, ou la carte de l'accueil. Acquitter, créer un OT ou une demande, puis clore en indiquant le traitement.
6. **Règles** : Conditionnel › Règles, pour qu'une demande ou un OT soit créé automatiquement (par exemple : vitesse vibratoire en alarme → demande d'intervention ; fer en alarme deux fois de suite → OT).

## Import de mesures et API (phase 4B)

**Import d'un fichier** (Conditionnel › Imports, droit « Importer des données ») :

1. « Télécharger le modèle Excel » : feuille *Mesures* pré-remplie avec vos codes, feuilles *Référentiel* (points et paramètres) et *Techniciens*. Ou utilisez directement l'export CSV / Excel de votre appareil.
2. Choisir le fichier (et, s'il existe, son **format** mémorisé), puis « Lire le fichier ». Rien n'est encore enregistré.
3. **Correspondance des colonnes** : indiquer la colonne de la date, du point (et de l'équipement si un même code de point existe sur plusieurs machines). Deux dispositions : une mesure par ligne (colonnes Paramètre et Valeur) ou une colonne par paramètre. Donner un nom dans « Mémoriser comme format » pour ne plus refaire ce réglage.
4. **Aperçu** : mesures à importer, tournées qui seront créées, doublons ignorés et lignes refusées avec leur motif (point inconnu, date illisible ou future, valeur non numérique, matricule inconnu…).
5. « Importer » : les mesures sont enregistrées comme une saisie manuelle (niveaux, alertes, règles). Les lignes refusées ne sont pas importées ; corrigez-les et réimportez le fichier : les mesures déjà présentes (même point, même paramètre, même date) sont ignorées.

L'historique conserve chaque fichier, la correspondance utilisée et le bilan ligne à ligne. Limites : 10 Mo, 5 000 lignes et 20 000 mesures par fichier ; formats CSV (séparateur `;` `,` ou tabulation, UTF-8 ou Windows) et Excel `.xlsx` (pas l'ancien `.xls`).

**API pour les capteurs et passerelles** :

1. Créer un compte dédié (par exemple `capteurs`) avec le rôle *Technicien* (droit « Saisir des mesures »).
2. `docker compose exec web python manage.py create_api_token capteurs` affiche le jeton (`--renew` le remplace).
3. Envoyer une tournée :

```
POST /api/v1/mesures/
Authorization: Token <jeton>
Content-Type: application/json

{"equipment": "CMP-02", "measured_at": "2026-11-07T08:30:00+01:00",
 "kind": "vibration", "technician": "T-004",
 "values": [{"point": "MOT-CA-H", "parameter": "VIB-V", "value": 3.4}]}
```

Réponse `201` avec le niveau de chaque mesure ; `400` avec le détail des erreurs ; un envoi répété est sans effet (`200`, mesures comptées dans `skipped`). `GET /api/v1/mesures/?equipment=CMP-02&parameter=VIB-V&since=2026-10-01` liste les dernières mesures. `kind` et `technician` sont facultatifs.

## Magasin : pièces de rechange et stock (phase 5A)

**Mise en place** (Magasin) : créer les **magasins**, les **familles**, les **fournisseurs**, puis les **articles** (référence unique, désignation, marque, fabricant, référence constructeur, unité, prix de référence, stock mini et maxi, délai, pièce critique, photo, fiche technique). Sur la fiche article, ajouter ses fournisseurs (référence et prix chez chacun) et l'emplacement dans chaque magasin.

**Stock de départ** : une « Entrée » par article avec le coût d'achat (le coût moyen pondéré part de là), ou un inventaire.

**Mouvements** (droit « Saisir des mouvements de stock ») : depuis la fiche article ou Magasin › Mouvements :
- *Entrée* : réception avec le n° de bon de livraison et le fournisseur ; le CMP est recalculé ;
- *Sortie hors OT* : avec un motif ; pour une intervention, la pièce se demande depuis l'OT ;
- *Transfert* entre magasins ;
- *Ajustement* : stock du magasin corrigé, avec un motif.
Aucun mouvement ne se modifie ni ne se supprime ; le stock ne peut jamais devenir négatif.

**Pièces pour une intervention** :
1. Le technicien (ou le responsable) ouvre l'OT › « Pièces du magasin », saisit la référence et la quantité, « Demander au magasin ». La pièce lui est réservée.
2. Le magasinier voit la demande dans Magasin › **Pièces à délivrer** (les OT les plus urgents en premier) et clique « Délivrer » : la sortie de stock est imputée à l'OT au coût moyen. Il imprime aussitôt le **bon de sortie** (lien affiché après la délivrance) et le fait signer par le technicien qui reçoit la pièce : c'est la preuve de remise en cas de désaccord. Le bon regroupe les pièces délivrées le même jour pour le même OT.
3. Pièce non utilisée : le magasinier l'enregistre dans Magasin › Pièces à délivrer › « Pièces délivrées : retours possibles » (ou sur l'OT pour qui y a accès) ; elle revient en stock et le coût de l'OT baisse ; le **bon de retour** se fait signer de la même façon.
4. À la validation de l'OT, son coût « pièces » comprend les pièces délivrées ; ce qui n'a pas été délivré est libéré.
Les pièces non stockées (achat direct, dépannage chez un fournisseur) se saisissent toujours librement dans « Pièces hors magasin ».

**Plans préventifs** : dans « Pièces prévues », choisir un article du magasin : il sera réservé automatiquement sur chaque OT généré.

**Nomenclature** : fiche équipement › onglet **Pièces** : pièces montées (avec repère), leur disponibilité, les pièces en attente pour ses OT et l'historique des consommations.

**Inventaire** (droit « Réaliser les inventaires ») : Magasin › Inventaires › choisir le magasin (et éventuellement une famille), imprimer la feuille de comptage (Excel), saisir les quantités comptées, « Enregistrer et valider ». Les écarts deviennent des mouvements « Inventaire » ; un article laissé vide n'est pas modifié.

**Demandes d'achat** (droit « Créer des demandes d'achat ») : Magasin › Demandes d'achat › « Nouvelle demande d'achat » : fournisseur suggéré, motif, OT ou équipement, date souhaitée, puis les articles (référence du magasin, ou description libre d'une pièce non stockée). « Imprimer », faire signer (demandeur, responsable maintenance) et transmettre au service achats, qui commande dans son propre logiciel. Pour le stock courant : « Réapprovisionner les articles sous le minimum » prépare une demande par fournisseur principal avec les quantités utiles.

**Entrée sur bon de commande** (magasinier) : à réception de la copie papier du bon de commande, Magasin › Mouvements › « Entrée sur bon de commande » : fournisseur, n° de BC, n° de bon de livraison, magasin, puis chaque ligne (article, quantité reçue, prix unitaire HT du BC). Le stock, le coût moyen et le prix fournisseur sont mis à jour ; la fiche article garde l'historique des prix. Le document de réception du fournisseur (signé par le magasinier et un technicien) et la facture suivent leur circuit habituel hors d'EasyMaint.

**Suivi** : l'accueil et la liste des articles signalent les articles **sous le minimum** (disponible = physique − réservé, comparé au mini), les pièces critiques, la valeur du stock ; export Excel des articles et des mouvements.

## Coûts et budget (phase 6A)

**Analyse des coûts** (droit « Consulter les coûts ») : menu Coûts et budget. Choisir la période, le regroupement (équipement, unité, famille, type de maintenance, mois) et éventuellement des filtres, puis « Afficher ». Les montants viennent des OT **validés** (à la date de fin des travaux) et des sorties de stock hors OT imputées à un équipement. « Excel » et « Rapport PDF » reprennent exactement le tableau affiché.

**Budget** (droit « Gérer les budgets ») : onglet Budget / réel › « Définir » sur une unité : montant annuel + « Répartir à parts égales », ou montant de chaque mois (par exemple un mois d'arrêt technique plus chargé). Le tableau compare chaque mois le budget et le réel (dépassements en rouge), avec le taux de consommation ; « Rapport PDF » pour la direction.

**Historique d'un équipement** : fiche équipement › onglet **Coûts**.

## Indicateurs et accueil (phase 6B)

**Paramétrage** : sur chaque fiche équipement, « Heures requises par jour » et « Jours de fonctionnement par semaine » (5 = lundi-vendredi, 6 = lundi-samedi, 7 = tous les jours) définissent le temps requis.

**Indicateurs** (droit « Consulter les indicateurs ») : menu Indicateurs ; choisir la période et les filtres, puis « Calculer ». Cliquer sur un équipement du tableau pour n'afficher que ses indicateurs. « Définitions des indicateurs » explique chaque calcul ; « Excel » et « Rapport PDF » reprennent la page.

**Personnaliser l'accueil** : bouton en haut de l'accueil ; cocher les blocs voulus, les ordonner avec les flèches, « Enregistrer ». « Rétablir la présentation de mon rôle » revient au choix par défaut.

## Reprise de l'existant et documents (phase 7A)

**Imports de données** (droit « Importer des données ») : Paramètres › Imports de données. Ordre conseillé : créer les localisations à l'écran, puis importer équipements, fournisseurs, articles et, si vous en avez, l'historique. Pour chaque type : « Modèle Excel », le remplir (supprimer la ligne d'exemple), « Lire le fichier », vérifier l'aperçu et les lignes refusées, « Importer ». Renvoyer un fichier corrigé est sans risque : ce qui existe déjà est ignoré (ou mis à jour si l'option est cochée).

**Fiche d'intervention** : sur l'OT, « Fiche PDF ». Imprimée avant l'intervention, elle sert de bon de travail à remplir à la main ; après, c'est le compte rendu complet à signer.

**Fiche équipement** : sur la fiche équipement, « Fiche PDF ».

**Export des OT** : liste des OT › « Excel » (reprend les filtres affichés).

**Rapport mensuel** : Indicateurs › Rapports mensuels. Le rapport du mois écoulé est produit automatiquement la nuit du 1er ; « Produire » le refait pour n'importe quel mois (par exemple après la saisie tardive d'OT).

## Notifications, connexion et sauvegardes (phase 7B)

- **Cloche** (en haut à droite) : le chiffre rouge indique les notifications non lues. Cliquer sur une notification ouvre l'OT, la demande ou l'alerte concernée. « Mes notifications » garde l'historique (90 jours après lecture).
- Qui reçoit quoi : le technicien quand un OT lui est affecté ; le responsable (droit « analyser les demandes ») à chaque nouvelle demande ; le responsable du conditionnel à chaque nouvelle alerte ; le magasinier quand une pièce est demandée pour un OT ; le valideur quand un OT est terminé.
- **Connexion** : après 5 mots de passe erronés en 15 minutes, le compte est bloqué 15 minutes (même avec le bon mot de passe). Attendre, ou demander à l'administrateur de vérifier le journal d'activité (échecs de connexion).
- **Sauvegardes** (administrateur, Paramètres › Sauvegardes) : vérifier d'un coup d'œil que la sauvegarde de la nuit a bien eu lieu. Copier régulièrement le dossier `sauvegardes` du serveur sur un disque externe.

## Langue (français / English)

La langue est choisie une fois, à l'installation : toute l'entreprise travaille en français ou en anglais
(écrans, PDF, exports Excel, rapports). Les données saisies (noms d'équipements, comptes rendus…) restent
telles qu'elles ont été écrites. Les fichiers d'import sont reconnus avec des titres de colonnes en français
ou en anglais.

## À propos

Le lien « EasyMaint · version … » en bas du menu ouvre la page « À propos » : version installée, licence libre
(AGPL-3.0), adresse du code source et composants utilisés. À communiquer au support avec toute demande.

## Journal d'activité

Paramètres › Journal d'activité : connexions, échecs de connexion et toutes les modifications, avec l'auteur, la date et les valeurs avant / après.
