from django.apps import AppConfig


class ConditionConfig(AppConfig):
    name = "apps.condition"
    label = "condition"
    verbose_name = "Maintenance conditionnelle"

    def ready(self):
        from apps.core.search import register_provider

        from .selectors import search_points

        register_provider(search_points, capability="condition.view")
