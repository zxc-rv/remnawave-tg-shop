import logging
import asyncio
from aiogram import Bot
from apscheduler .schedulers .asyncio import AsyncIOScheduler
from datetime import datetime

from config .settings import Settings
from .subscription_service import SubscriptionService

from db .database import get_db_connection_manager
from bot .middlewares .i18n import JsonI18n
from .panel_api_service import PanelApiService


async def send_expiration_warnings (bot :Bot ,settings :Settings ,i18n :JsonI18n ,panel_service :PanelApiService ):
    """
    Sends expiration warnings to users whose subscriptions are ending soon.
    This function is called by the scheduler.
    """
    logging .info (f"Scheduler job: Checking for expiring subscriptions at {datetime.now()}...")


    sub_service =SubscriptionService (get_db_connection_manager ,settings ,panel_service )

    expiring_subs =await sub_service .get_subscriptions_ending_soon (settings .SUBSCRIPTION_EXPIRATION_NOTIFICATION_DAYS )

    if not expiring_subs :
        logging .info ("No subscriptions found ending soon for notification.")
        return

    logging .info (f"Found {len(expiring_subs)} subscriptions ending soon for notification.")
    for sub_info in expiring_subs :
        user_id =sub_info ['user_id']
        if not user_id :
            logging .warning (f"Skipping notification for subscription without user_id: {sub_info}")
            continue

        user_lang =sub_info .get ('language_code')if sub_info .get ('language_code')else getattr (settings ,'DEFAULT_LANGUAGE','en')
        first_name =sub_info .get ('first_name','User')
        end_date_str =sub_info ['end_date_str']

        days_left_float =sub_info .get ('days_left')
        days_left_display ='N/A'
        if days_left_float is not None :

            days_left_display =max (0 ,int (round (days_left_float )))

        _ =lambda key ,**kwargs :i18n .gettext (user_lang ,key ,**kwargs )
        message_text =_ (
        "subscription_ending_soon_notification",
        user_name =first_name ,
        end_date =end_date_str ,
        days_left =days_left_display
        )
        try :
            await bot .send_message (user_id ,message_text )

            await sub_service .update_last_notification_sent (user_id ,end_date_str )
            logging .info (f"Sent expiration warning to user {user_id} for subscription ending {end_date_str}")
        except Exception as e :

            logging .error (f"Failed to send expiration warning to user {user_id}: {e}")
        await asyncio .sleep (0.1 )


async def schedule_subscription_notifications (bot :Bot ,settings :Settings ,i18n :JsonI18n ,scheduler :AsyncIOScheduler ):
    """Schedules the daily job to send expiration warnings."""


    async def job_wrapper ():
        panel_service =PanelApiService (settings )
        try :

            await send_expiration_warnings (bot ,settings ,i18n ,panel_service )
        except Exception as e :
            logging .error (f"Error in scheduled job 'send_expiration_warnings': {e}",exc_info =True )
        finally :
            await panel_service .close_session ()


    try :
        notification_hour =int (settings .SUBSCRIPTION_NOTIFICATION_HOUR_UTC )
        notification_minute =int (settings .SUBSCRIPTION_NOTIFICATION_MINUTE_UTC )
    except (ValueError ,TypeError ):
        logging .warning ("SUBSCRIPTION_NOTIFICATION_HOUR_UTC or MINUTE_UTC is invalid. Defaulting to 9:00 UTC.")
        notification_hour =9
        notification_minute =0

    scheduler .add_job (
    job_wrapper ,
    'cron',
    hour =notification_hour ,
    minute =notification_minute ,
    name ="daily_subscription_expiration_warnings",
    misfire_grace_time =60 *15
    )
    logging .info (f"Subscription expiration warning job scheduled daily at {notification_hour:02d}:{notification_minute:02d} UTC.")