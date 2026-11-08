"""
Capacités (droits fins) et rôles prédéfinis.

Une capacité autorise une action précise. Un rôle est une liste de capacités,
modifiable par l'administrateur de l'entreprise. Les capacités des modules à
venir sont déjà déclarées pour que la matrice des rôles soit stable.
"""
from django.utils.translation import gettext_lazy as _

CAPABILITY_GROUPS = [
    (_("Administration"), [
        ("settings.manage", _("Gérer les utilisateurs, les rôles et les paramètres")),
        ("audit.view", _("Consulter le journal d'activité")),
    ]),
    (_("Patrimoine"), [
        ("assets.view", _("Consulter les équipements et localisations")),
        ("assets.manage", _("Créer et modifier les équipements, localisations, familles")),
        ("meters.record", _("Saisir des relevés de compteurs")),
    ]),
    (_("Interventions"), [
        ("requests.create", _("Déclarer une demande d'intervention")),
        ("requests.manage", _("Analyser et valider les demandes")),
        ("workorders.view", _("Consulter les ordres de travail")),
        ("workorders.manage", _("Créer, planifier et affecter les OT")),
        ("workorders.create_direct", _("Créer directement un OT sans demande")),
        ("workorders.execute", _("Exécuter et clôturer ses OT")),
        ("workorders.validate", _("Valider les OT terminés")),
    ]),
    (_("Préventif et conditionnel"), [
        ("preventive.view", _("Consulter les plans préventifs")),
        ("preventive.manage", _("Gérer les plans préventifs")),
        ("condition.view", _("Consulter les mesures conditionnelles")),
        ("condition.record", _("Saisir des mesures")),
        ("condition.manage", _("Gérer seuils et règles d'alerte")),
    ]),
    (_("Stock et achats"), [
        ("inventory.view", _("Consulter les articles et le stock")),
        ("inventory.manage", _("Gérer les articles et fournisseurs")),
        ("stock.move", _("Saisir des mouvements de stock")),
        ("stock.count", _("Réaliser les inventaires")),
        ("purchasing.request", _("Créer des demandes d'achat")),
        ("purchasing.approve", _("Approuver les achats")),
    ]),
    (_("Ressources et pilotage"), [
        ("workforce.view", _("Consulter techniciens et équipes")),
        ("workforce.manage", _("Gérer techniciens et équipes")),
        ("costs.view", _("Consulter les coûts")),
        ("costs.manage", _("Gérer les budgets")),
        ("kpi.view", _("Consulter les indicateurs")),
        ("imports.run", _("Importer des données Excel")),
    ]),
]

ALL_CAPABILITIES = [code for _group, items in CAPABILITY_GROUPS for code, _label in items]
CAPABILITY_LABELS = {code: label for _group, items in CAPABILITY_GROUPS for code, label in items}

_READ_ALL = {
    "assets.view", "workorders.view", "preventive.view", "condition.view",
    "inventory.view", "workforce.view", "costs.view", "kpi.view",
}

# Rôles prédéfinis (matrice validée en phase 1). Code -> (libellé, capacités)
DEFAULT_ROLES = {
    "admin": (_("Administrateur"), set(ALL_CAPABILITIES)),
    "maintenance_manager": (_("Responsable maintenance"), set(ALL_CAPABILITIES) - {"settings.manage"}),
    "maintenance_engineer": (_("Ingénieur maintenance"), _READ_ALL | {
        "assets.manage", "meters.record", "requests.create", "requests.manage",
        "workorders.manage", "workorders.create_direct", "workorders.execute", "workorders.validate",
        "preventive.manage", "condition.record", "condition.manage", "inventory.manage",
        "purchasing.request", "imports.run",
    }),
    "team_leader": (_("Chef d'équipe"), {
        "assets.view", "meters.record", "requests.create", "requests.manage",
        "workorders.view", "workorders.manage", "workorders.create_direct", "workorders.execute",
        "workorders.validate", "preventive.view", "condition.view", "condition.record",
        "inventory.view", "purchasing.request", "workforce.view", "kpi.view",
    }),
    "technician": (_("Technicien"), {
        "assets.view", "meters.record", "requests.create", "workorders.view",
        "workorders.create_direct", "workorders.execute", "preventive.view",
        "condition.view", "condition.record", "inventory.view",
    }),
    "storekeeper": (_("Magasinier"), {
        "assets.view", "requests.create", "inventory.view", "inventory.manage",
        "stock.move", "stock.count", "purchasing.request", "kpi.view",
    }),
    "production_manager": (_("Responsable de production"), {
        "assets.view", "meters.record", "requests.create", "workorders.view",
        "preventive.view", "condition.view", "costs.view", "kpi.view",
    }),
    "management": (_("Direction"), _READ_ALL | {"audit.view", "costs.manage", "purchasing.approve"}),
}
