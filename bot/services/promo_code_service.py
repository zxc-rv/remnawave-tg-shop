import logging
import aiosqlite
from datetime import datetime ,timezone
from typing import Optional ,Dict ,Callable ,Any ,Tuple

from aiogram import Bot
from config .settings import Settings
from db .database import get_promo_code_by_code ,increment_promo_activation ,get_db_connection_manager ,_setup_db_connection
from .subscription_service import SubscriptionService
from bot .middlewares .i18n import JsonI18n

class PromoCodeService :
    def __init__ (
    self ,
    db_conn_provider :Callable [[],Any ],
    settings :Settings ,
    subscription_service :SubscriptionService ,
    bot :Bot ,
    i18n :JsonI18n
    ):
        self .db_conn_provider =db_conn_provider
        self .settings =settings
        self .subscription_service =subscription_service
        self .bot =bot
        self .i18n =i18n

    async def apply_promo_code (self ,user_id :int ,code_input :str ,user_lang :str )->Tuple [bool ,str ]:
        """
        Applies a promo code for a user.
        Returns: (success_status: bool, message_text_for_user: str)
        """
        _ =lambda k ,**kw :self .i18n .gettext (user_lang ,k ,**kw )
        code_input_upper =code_input .strip ().upper ()

        async with self .db_conn_provider ()as db :
            await _setup_db_connection (db )
            try :
                promo_data =await get_promo_code_by_code (code_input_upper ,db_conn =db )

                if not promo_data :
                    return False ,_ ("promo_code_not_found",code =code_input_upper )

                if promo_data ['current_activations']>=promo_data ['max_activations']:
                    return False ,_ ("promo_code_max_activations_reached",code =code_input_upper )






                active_sub =await self .subscription_service .get_active_subscription (user_id )
                if not active_sub :
                    return False ,_ ("promo_code_no_active_subscription")

                bonus_days =promo_data ['bonus_days']


                new_end_date =await self .subscription_service .extend_active_subscription_days (
                user_id =user_id ,
                bonus_days =bonus_days ,
                db_conn =db ,
                reason =f"promo code {code_input_upper}"
                )

                if new_end_date :


                    activation_success =await increment_promo_activation (promo_data ['promo_code_id'],user_id ,db_conn =db ,payment_id =None )
                    if activation_success :
                        await db .commit ()
                        return True ,_ ("promo_code_applied_success",
                        code =code_input_upper ,
                        bonus_days =bonus_days ,
                        new_end_date =new_end_date .strftime ('%Y-%m-%d'))
                    else :



                        await db .rollback ()
                        return False ,_ ("promo_code_invalid_or_expired")
                else :
                    await db .rollback ()
                    return False ,_ ("error_applying_promo_bonus")

            except Exception as e :
                logging .error (f"Error applying promo code {code_input_upper} for user {user_id}: {e}",exc_info =True )
                await db .rollback ()
                return False ,_ ("error_try_again")