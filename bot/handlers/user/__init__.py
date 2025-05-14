from aiogram import Router


from .import start
from .import subscription
from .import referral
from .import promo_user
from .import trial_handler


user_router_aggregate =Router (name ="user_router_aggregate")




user_router_aggregate .include_router (promo_user .router )
user_router_aggregate .include_router (trial_handler .router )
user_router_aggregate .include_router (start .router )
user_router_aggregate .include_router (subscription .router )
user_router_aggregate .include_router (referral .router )

