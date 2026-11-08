from django.apps import AppConfig


class PreventiveConfig(AppConfig):
    name = "apps.preventive"
    label = "preventive"
    verbose_name = "Maintenance préventive"

    def ready(self):
        from apps.core.search import register_provider

        from . import (
            signals,  # noqa: F401  (branche les recalculs d'échéance et la génération sur relevé)
        )
        from .selectors import search_plans

        register_provider(search_plans, capability="preventive.view")
