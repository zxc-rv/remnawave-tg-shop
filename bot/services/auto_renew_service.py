import logging
from datetime import datetime, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.orm import sessionmaker

from config.settings import Settings
from bot.services.subscription_service import SubscriptionService
from bot.services.panel_api_service import PanelApiService
from db.dal import subscription_dal


async def auto_extend_tribute_subscriptions(
        settings: Settings, panel_service: PanelApiService,
        async_session_factory: sessionmaker) -> None:
    logging.info(
        f"Scheduler job 'auto_extend_tribute_subscriptions' started at {datetime.now(timezone.utc)} UTC."
    )
    async with async_session_factory() as session:
        try:
            sub_service = SubscriptionService(settings, panel_service)
            subs = await subscription_dal.get_active_subscriptions_for_autorenew(
                session, 'tribute', require_skip_flag=False)
            if not subs:
                logging.info("No Tribute subscriptions to auto-extend.")
                return
            for sub in subs:
                if not sub.skip_notifications:
                    from db.dal import payment_dal
                    has_pay = await payment_dal.user_has_successful_payment_for_provider(
                        session, sub.user_id, 'tribute')
                    if not has_pay:
                        continue
                    await subscription_dal.set_skip_notifications_for_provider(
                        session, sub.user_id, 'tribute', True)

                months = sub.duration_months or 1
                bonus_days = months * 30
                await sub_service.extend_active_subscription_days(
                    session, sub.user_id, bonus_days,
                    reason='tribute_autorenew')
            await session.commit()
            logging.info(
                f"Auto-extended {len(subs)} Tribute subscriptions and committed session.")
        except Exception as e:
            logging.error(
                f"Error during auto_extend_tribute_subscriptions: {e}",
                exc_info=True)
            await session.rollback()
            logging.info("Session rolled back due to error in auto_extend_tribute_subscriptions.")


def schedule_tribute_autorenew(
        settings: Settings, scheduler: AsyncIOScheduler,
        panel_service: PanelApiService,
        async_session_factory: sessionmaker) -> None:

    async def job_wrapper():
        try:
            await auto_extend_tribute_subscriptions(
                settings, panel_service, async_session_factory)
        except Exception as e:
            logging.error(
                f"Unhandled error in scheduled job 'auto_extend_tribute_subscriptions': {e}",
                exc_info=True)

    scheduler.add_job(
        job_wrapper,
        'cron',
        hour=0,
        minute=5,
        name='daily_tribute_autorenew',
        misfire_grace_time=60 * 15,
        replace_existing=True)
    logging.info(
        "Tribute subscription auto-renew job scheduled daily at 00:05 UTC.")
