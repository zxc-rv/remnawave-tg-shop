import logging
import aiosqlite
from typing import Optional, Dict, Callable, Any, TYPE_CHECKING, Tuple
from aiogram import Bot
from datetime import datetime

from config.settings import Settings
from db.database import get_user
from bot.middlewares.i18n import JsonI18n

if TYPE_CHECKING:
    from .subscription_service import SubscriptionService


class ReferralService:

    def __init__(self, db_conn_provider: Callable[[], Any], settings: Settings,
                 subscription_service_instance: 'SubscriptionService',
                 bot: Bot, i18n: JsonI18n):
        self.db_conn_provider = db_conn_provider
        self.settings = settings
        self.subscription_service = subscription_service_instance
        self.bot = bot
        self.i18n = i18n

    async def process_new_user_referral(self, referee_user_id: int,
                                        inviter_user_id: Optional[int]):
        if inviter_user_id and referee_user_id != inviter_user_id:

            logging.info(
                f"Referral link used: User {referee_user_id} was invited by {inviter_user_id}."
            )

        pass

    async def apply_referral_bonuses_for_payment(
            self, referee_user_id: int, purchased_subscription_months: int,
            db_conn: aiosqlite.Connection) -> Dict[str, Any]:
        """Applies bonuses. Notifies inviter. Returns referee bonus details."""
        referee_final_end_date: Optional[datetime] = None
        referee_bonus_applied_days: Optional[int] = None
        try:
            referee_user_row = await get_user(referee_user_id, db_conn=db_conn)
            if not referee_user_row or referee_user_row[
                    'referred_by_id'] is None:
                logging.debug(
                    f"User {referee_user_id} not referred or inviter ID missing. No referral bonuses."
                )
                return {
                    "referee_bonus_applied_days": None,
                    "referee_new_end_date": None
                }

            inviter_user_id = referee_user_row['referred_by_id']
            inviter_user_row = await get_user(inviter_user_id, db_conn=db_conn)

            referee_name = referee_user_row[
                'first_name'] or f"User {referee_user_id}"

            default_lang_for_placeholder = getattr(self.settings,
                                                   'DEFAULT_LANGUAGE', 'en')
            inviter_name = inviter_user_row[
                'first_name'] if inviter_user_row else self.i18n.gettext(
                    default_lang_for_placeholder, "friend_placeholder")

            inviter_bonus = self.settings.referral_bonus_inviter.get(
                purchased_subscription_months)
            referee_bonus = self.settings.referral_bonus_referee.get(
                purchased_subscription_months)

            if inviter_bonus and inviter_bonus > 0 and inviter_user_row:
                new_end_date_inviter = await self.subscription_service.extend_subscription_for_referral(
                    user_id=inviter_user_id,
                    bonus_days=inviter_bonus,
                    db_conn=db_conn)
                if new_end_date_inviter:
                    logging.info(
                        f"Bonus applied for inviter {inviter_user_id}.")
                    try:
                        inviter_lang = inviter_user_row.get(
                            'language_code', default_lang_for_placeholder)
                        _i = lambda k, **kw: self.i18n.gettext(
                            inviter_lang, k, **kw)
                        await self.bot.send_message(
                            inviter_user_id,
                            _i("referral_bonus_inviter_notification_extended",
                               days=inviter_bonus,
                               referee_name=referee_name,
                               new_end_date=new_end_date_inviter.strftime(
                                   '%Y-%m-%d')))
                    except Exception as e:
                        logging.error(
                            f"Failed to send bonus notification to inviter {inviter_user_id}: {e}"
                        )
                else:
                    logging.warning(
                        f"Failed to apply bonus subscription extension for inviter {inviter_user_id}."
                    )

            if referee_bonus and referee_bonus > 0:
                new_end_date_referee = await self.subscription_service.extend_subscription_for_referral(
                    user_id=referee_user_id,
                    bonus_days=referee_bonus,
                    db_conn=db_conn,
                    is_referee_bonus=True)
                if new_end_date_referee:
                    logging.info(
                        f"Bonus applied for referee {referee_user_id}.")
                    referee_final_end_date = new_end_date_referee
                    referee_bonus_applied_days = referee_bonus
                else:
                    logging.warning(
                        f"Failed to apply bonus subscription extension for referee {referee_user_id}."
                    )

            return {
                "referee_bonus_applied_days": referee_bonus_applied_days,
                "referee_new_end_date": referee_final_end_date
            }
        except Exception as e:
            logging.error(
                f"Error in apply_referral_bonuses_for_payment (db_conn: {db_conn is not None}): {e}",
                exc_info=True)

            raise

    def generate_referral_link(self, bot_username: str,
                               inviter_user_id: int) -> str:
        return f"https://t.me/{bot_username}?start=ref_{inviter_user_id}"
