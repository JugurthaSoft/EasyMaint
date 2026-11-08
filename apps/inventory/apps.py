from django.apps import AppConfig


class InventoryConfig(AppConfig):
    name = "apps.inventory"
    label = "inventory"
    verbose_name = "Pièces de rechange et stocks"

    def ready(self):
        from apps.core.search import register_provider
        from apps.workorders import services as wo_services
        from apps.workorders.signals import work_order_closed

        from . import services
        from .selectors import search_items

        register_provider(search_items, capability="inventory.view")
        if services.work_order_parts_cost not in wo_services.PARTS_COST_PROVIDERS:
            wo_services.PARTS_COST_PROVIDERS.append(services.work_order_parts_cost)
        work_order_closed.connect(services.on_work_order_closed, dispatch_uid="inventory_release_reservations")
