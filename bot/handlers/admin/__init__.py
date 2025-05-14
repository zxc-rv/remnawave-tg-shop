from aiogram import Router


from .common import router as common_admin_router
from .promo_codes import router as promo_codes_admin_router
from .user_management import router as user_management_admin_router
from .broadcast import router as broadcast_admin_router
from .statistics import router as statistics_admin_router
from .sync_admin import router as sync_admin_router
from .logs_admin import router as logs_admin_router


admin_router_aggregate =Router (name ="admin_router_aggregate")


admin_router_aggregate .include_router (common_admin_router )
admin_router_aggregate .include_router (promo_codes_admin_router )
admin_router_aggregate .include_router (user_management_admin_router )
admin_router_aggregate .include_router (broadcast_admin_router )
admin_router_aggregate .include_router (statistics_admin_router )
admin_router_aggregate .include_router (sync_admin_router )
admin_router_aggregate .include_router (logs_admin_router )

