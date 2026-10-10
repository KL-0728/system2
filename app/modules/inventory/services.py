from app.providers import register_provider
from app.services.inventory import InventoryService


def install():
    service = InventoryService()
    register_provider('inventory_writer', service)
    register_provider('integrity', service)

    from app.services.replenishment import ReplenishmentService
    register_provider('runs', ReplenishmentService())
