from django.apps import AppConfig


class AssetsConfig(AppConfig):
    name = "apps.assets"
    label = "assets"
    verbose_name = "Patrimoine"

    def ready(self):
        from apps.core.search import register_provider

        from .selectors import search_equipment, search_locations

        register_provider(search_equipment, capability="assets.view")
        register_provider(search_locations, capability="assets.view")
