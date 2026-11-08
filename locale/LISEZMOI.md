# Traductions d'EasyMaint

Une installation fonctionne dans une seule langue (`EASYMAINT_LANGUAGE`). Le français est la langue de référence : tous les textes de l'interface sont écrits en français et
marqués pour la traduction (`{% translate %}`, `{% blocktranslate %}`, `gettext`, `gettext_lazy`).

| Langue | Fichier | État |
| --- | --- | --- |
| Anglais | `en/LC_MESSAGES/django.po` | complet (contrôlé par les tests) |
| Arabe | — | prévu (mise en page de droite à gauche déjà prête) |

## Après une modification de l'interface

Un test (`apps/core/tests/test_i18n.py`) échoue si un texte n'a pas de traduction anglaise. Pour compléter :

```bash
docker compose run --rm web python manage.py makemessages -l en --no-location
# traduire les nouvelles entrées (msgstr vides ou « fuzzy ») de locale/en/LC_MESSAGES/django.po
docker compose up -d --build        # le .po est contrôlé puis compilé à la construction de l'image
```

Les variables doivent être reprises à l'identique dans la traduction (`%(n)s`, `%(name)s`…).

## Ajouter une langue (exemple : arabe)

```bash
docker compose run --rm web python manage.py makemessages -l ar --no-location
# traduire locale/ar/LC_MESSAGES/django.po (Poedit, Weblate…)
```

Puis l'ajouter à `AVAILABLE_LANGUAGES` (`config/settings/base.py`) et l'installer avec `EASYMAINT_LANGUAGE=ar`.
L'arabe s'affiche automatiquement de droite à gauche (Bootstrap RTL). Les textes de la démonstration se traduisent dans `apps/core/demo_i18n.py`.
