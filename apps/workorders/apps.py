from django.apps import AppConfig


class WorkordersConfig(AppConfig):
    name = "apps.workorders"
    label = "workorders"
    verbose_name = "Interventions"

    def ready(self):
        from apps.core.search import register_provider

        from .selectors import search_requests, search_work_orders

        register_provider(search_work_orders, capability="workorders.view")
        register_provider(search_requests, capability="requests.create")
