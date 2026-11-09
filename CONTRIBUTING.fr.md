# Contribuer à EasyMaint

[English](CONTRIBUTING.md) | **Français**

Merci de votre intérêt ! Les corrections, traductions (arabe, anglais), améliorations et nouvelles
fonctions sont bienvenues.

## Principes du projet

- **Pas de fausse fonctionnalité** : une fonction livrée est complète, testée et documentée.
- **Ne jamais retirer une fonction existante** sans discussion préalable.
- Toute donnée métier hérite de `TenantScopedModel` et passe par `objects` (filtré sur l'entreprise) :
  voir [docs/architecture.md](docs/architecture.md).
- Chaque écran vérifie un droit (`CapabilityRequiredMixin` ou `require_capability`) : le test
  `apps/core/tests/test_security.py` parcourt toutes les adresses et échoue sinon.
- Aucun script dans les gabarits (politique de sécurité du contenu) : les comportements vont dans `static/js`.
- Textes de l'interface en français, marqués pour la traduction (`{% translate %}`, `gettext`).

## Proposer une modification

1. Créer une branche, développer avec ses tests.
2. Vérifier : `ruff check --select F,E9,I .` puis `docker compose run --rm web pytest` (tous les tests passent,
   migrations comprises).
3. Mettre à jour la documentation (`docs/`) et `docs/CHANGELOG.md`.
4. Ouvrir une demande de fusion en expliquant le besoin métier.

En contribuant, vous acceptez que votre code soit diffusé sous la licence du projet (AGPL-3.0).

## Signaler une faille de sécurité

Ne pas ouvrir de ticket public : écrire à contact@jugurthasoft.com.
