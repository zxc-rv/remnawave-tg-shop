from aiogram import Router

from . import common
from . import broadcast
from . import promo_codes
from . import user_management
from . import statistics
from . import sync_admin
from . import logs_admin

admin_router_aggregate = Router(name="admin_features_router")

admin_router_aggregate.include_router(common.router)
admin_router_aggregate.include_router(broadcast.router)
admin_router_aggregate.include_router(promo_codes.router)
admin_router_aggregate.include_router(user_management.router)
admin_router_aggregate.include_router(statistics.router)
admin_router_aggregate.include_router(sync_admin.router)
admin_router_aggregate.include_router(logs_admin.router)

__all__ = ("admin_router_aggregate", )
