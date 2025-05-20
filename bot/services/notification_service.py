import logging
import asyncio
from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, timezone

from config.settings import Settings

from sqlalchemy.orm import sessionmaker
from bot.middlewares.i18n import JsonI18n
from bot.services.panel_api_service import PanelApiService
from bot.services.subscription_service import SubscriptionService


async def send_expiration_warnings(bot: Bot, settings: Settings,
                                   i18n: JsonI18n,
                                   panel_service: PanelApiService,
                                   async_session_factory: sessionmaker):

    logging.info(
        f"Scheduler job 'send_expiration_warnings' started at {datetime.now(timezone.utc)} UTC."
    )

    if async_session_factory is None:
        logging.error(
            "NotificationService: AsyncSessionFactory not provided to send_expiration_warnings!"
        )
        return

    async with async_session_factory() as session:
        try:

            sub_service = SubscriptionService(settings, panel_service)

            expiring_subs_details_list = await sub_service.get_subscriptions_ending_soon(
                session, settings.SUBSCRIPTION_EXPIRATION_NOTIFICATION_DAYS)

            if not expiring_subs_details_list:
                logging.info(
                    "No subscriptions found ending soon for notification.")
                return

            logging.info(
                f"Found {len(expiring_subs_details_list)} subscriptions for expiration warning."
            )

            for sub_details in expiring_subs_details_list:
                user_id = sub_details['user_id']
                user_lang = sub_details.get('language_code',
                                            settings.DEFAULT_LANGUAGE)
                first_name = sub_details.get('first_name', f"User {user_id}")
                end_date_str_for_msg = sub_details.get('end_date_str', "N/A")
                days_left_display = sub_details.get('days_left', "N/A")

                subscription_actual_end_date_obj: Optional[
                    datetime] = sub_details.get(
                        'subscription_end_date_iso_for_update')

                _ = lambda key, **kwargs: i18n.gettext(user_lang, key, **kwargs
                                                       )
                message_text = _("subscription_ending_soon_notification",
                                 user_name=first_name,
                                 end_date=end_date_str_for_msg,
                                 days_left=days_left_display)
                try:
                    await bot.send_message(user_id, message_text)
                    logging.info(
                        f"Sent expiration warning to user {user_id} for subscription ending {end_date_str_for_msg}."
                    )

                    if subscription_actual_end_date_obj:
                        await sub_service.update_last_notification_sent(
                            session, user_id, subscription_actual_end_date_obj)
                    else:
                        logging.warning(
                            f"Could not find exact subscription end_date_obj for user {user_id} to update notification time."
                        )

                except Exception as e:
                    logging.error(
                        f"Failed to send expiration warning or update notification status for user {user_id}: {e}",
                        exc_info=True)

                await asyncio.sleep(0.1)

            await session.commit()
            logging.info(
                "Finished processing expiration warnings. Session committed.")

        except Exception as e_session:
            logging.error(
                f"Error during send_expiration_warnings session: {e_session}",
                exc_info=True)
            await session.rollback()
            logging.info(
                "Session rolled back due to error in send_expiration_warnings."
            )


async def schedule_subscription_notifications(
        bot: Bot, settings: Settings, i18n: JsonI18n,
        scheduler: AsyncIOScheduler, panel_service: PanelApiService,
        async_session_factory: sessionmaker):

    async def job_wrapper():

        try:
            await send_expiration_warnings(bot, settings, i18n, panel_service,
                                           async_session_factory)
        except Exception as e:
            logging.error(
                f"Unhandled error in scheduled job 'send_expiration_warnings' (job_wrapper): {e}",
                exc_info=True)

    try:
        notification_hour = int(settings.SUBSCRIPTION_NOTIFICATION_HOUR_UTC)
        notification_minute = int(
            settings.SUBSCRIPTION_NOTIFICATION_MINUTE_UTC)
    except (ValueError, TypeError):
        logging.warning(
            "SUBSCRIPTION_NOTIFICATION_HOUR_UTC or MINUTE_UTC is invalid in settings. Defaulting to 9:00 UTC."
        )
        notification_hour = 9
        notification_minute = 0

    scheduler.add_job(job_wrapper,
                      'cron',
                      hour=notification_hour,
                      minute=notification_minute,
                      name="daily_subscription_expiration_warnings_v2",
                      misfire_grace_time=60 * 15,
                      replace_existing=True)
    logging.info(
        f"Subscription expiration warning job scheduled daily at {notification_hour:02d}:{notification_minute:02d} UTC."
    )
