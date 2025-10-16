import logging
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, Dict, Any
from aiogram import Bot
from datetime import datetime, timezone, timedelta

from config.settings import Settings
from db.dal import user_dal
from db.models import User
from db.dal import subscription_dal
from bot.middlewares.i18n import JsonI18n
from .subscription_service import SubscriptionService


class ReferralService:

    def __init__(self, settings: Settings,
                 subscription_service: SubscriptionService, bot: Bot,
                 i18n: JsonI18n):
        self.settings = settings
        self.subscription_service = subscription_service
        self.bot = bot
        self.i18n = i18n

    async def apply_referral_bonuses_for_payment(
            self, session: AsyncSession, referee_user_id: int,
            purchased_subscription_months: int) -> Dict[str, Any]:

        referee_final_end_date: Optional[datetime] = None
        referee_bonus_applied_days: Optional[int] = None
        inviter_bonus_successfully_applied = False

        try:
            referee_user_model = await user_dal.get_user_by_id(
                session, referee_user_id)
            if not referee_user_model or referee_user_model.referred_by_id is None:
                logging.debug(
                    f"User {referee_user_id} not referred or inviter ID missing. No referral bonuses."
                )
                return {
                    "referee_bonus_applied_days": None,
                    "referee_new_end_date": None
                }

            inviter_user_id = referee_user_model.referred_by_id
            inviter_user_model = await user_dal.get_user_by_id(
                session, inviter_user_id)

            referee_name_for_msg = referee_user_model.first_name or f"User {referee_user_id}"

            default_lang_for_placeholder = self.settings.DEFAULT_LANGUAGE
            inviter_name_for_referee_msg = (
                inviter_user_model.first_name if inviter_user_model
                and inviter_user_model.first_name else self.i18n.gettext(
                    default_lang_for_placeholder, "friend_placeholder"))

            inviter_bonus_days = self.settings.referral_bonus_inviter.get(
                purchased_subscription_months)
            referee_bonus_days = self.settings.referral_bonus_referee.get(
                purchased_subscription_months)

            if inviter_bonus_days and inviter_bonus_days > 0:
                if not inviter_user_model:

                    logging.warning(
                        f"Inviter user {inviter_user_id} not found in local DB. Cannot apply inviter bonus."
                    )
                else:

                    inviter_panel_uuid, inviter_panel_sub_link_id, _, _ = await self.subscription_service._get_or_create_panel_user_link_details(
                        session, inviter_user_id, inviter_user_model)

                    if not inviter_panel_uuid:
                        logging.warning(
                            f"Failed to get/create panel link for inviter {inviter_user_id}. Cannot apply inviter bonus directly to panel."
                        )

                    else:
                        new_end_date_inviter = await self.subscription_service.extend_active_subscription_days(
                            session=session,
                            user_id=inviter_user_id,
                            bonus_days=inviter_bonus_days,
                            reason=f"referral bonus from {referee_name_for_msg}"
                        )

                        if new_end_date_inviter:
                            inviter_bonus_successfully_applied = True
                            logging.info(
                                f"Bonus of {inviter_bonus_days} days successfully applied/extended for inviter {inviter_user_id}."
                            )

                            try:
                                inviter_lang = inviter_user_model.language_code or default_lang_for_placeholder
                                _i = lambda k, **kw: self.i18n.gettext(
                                    inviter_lang, k, **kw)
                                await self.bot.send_message(
                                    inviter_user_id,
                                    _i("referral_bonus_inviter_notification_extended",
                                       days=inviter_bonus_days,
                                       referee_name=referee_name_for_msg,
                                       new_end_date=new_end_date_inviter.
                                       strftime('%d.%m.%Y')))
                            except Exception as e_notify_inviter:
                                logging.error(
                                    f"Failed to send bonus notification to inviter {inviter_user_id}: {e_notify_inviter}"
                                )
                        else:

                            logging.info(
                                f"Inviter {inviter_user_id} has no active sub to extend. Creating new bonus subscription for {inviter_bonus_days} days."
                            )

                            bonus_start_date = datetime.now(timezone.utc)
                            bonus_end_date = bonus_start_date + timedelta(
                                days=inviter_bonus_days)

                            if not inviter_panel_sub_link_id:
                                logging.error(
                                    f"Cannot create bonus subscription for inviter {inviter_user_id}: panel_sub_link_id is missing even after link detail fetch."
                                )
                            else:
                                bonus_sub_payload = {
                                    "user_id":
                                    inviter_user_id,
                                    "panel_user_uuid":
                                    inviter_panel_uuid,
                                    "panel_subscription_uuid":
                                    inviter_panel_sub_link_id,
                                    "start_date":
                                    bonus_start_date,
                                    "end_date":
                                    bonus_end_date,
                                    "duration_months":
                                    0,
                                    "is_active":
                                    True,
                                    "status_from_panel":
                                    "ACTIVE_BONUS",
                                    "traffic_limit_bytes":
                                    self.settings.user_traffic_limit_bytes,
                                }
                                try:
                                    await subscription_dal.deactivate_other_active_subscriptions(
                                        session, inviter_panel_uuid,
                                        inviter_panel_sub_link_id)
                                    bonus_sub = await subscription_dal.upsert_subscription(
                                        session, bonus_sub_payload)

                                    panel_update_success = await self.subscription_service.panel_service.update_user_details_on_panel(
                                        inviter_panel_uuid, {
                                            "expireAt":
                                            bonus_end_date.isoformat(
                                                timespec='milliseconds').
                                            replace('+00:00', 'Z'),
                                            "status":
                                            "ACTIVE",
                                        })
                                    if panel_update_success:
                                        inviter_bonus_successfully_applied = True
                                        logging.info(
                                            f"New bonus subscription for {inviter_bonus_days} days created for inviter {inviter_user_id}."
                                        )

                                        inviter_lang = inviter_user_model.language_code or default_lang_for_placeholder
                                        _i = lambda k, **kw: self.i18n.gettext(
                                            inviter_lang, k, **kw)
                                        await self.bot.send_message(
                                            inviter_user_id,
                                            _i("referral_bonus_inviter_notification_new_sub",
                                               days=inviter_bonus_days,
                                               referee_name=
                                               referee_name_for_msg,
                                               new_end_date=bonus_end_date.
                                               strftime('%d.%m.%Y')))
                                    else:
                                        logging.warning(
                                            f"Failed to update panel for new bonus subscription for inviter {inviter_user_id}. Local bonus sub created (ID: {bonus_sub.subscription_id}) but may not be active on panel."
                                        )

                                except Exception as e_create_bonus_sub:
                                    logging.error(
                                        f"Failed to create new bonus subscription for inviter {inviter_user_id}: {e_create_bonus_sub}",
                                        exc_info=True)

            if referee_bonus_days and referee_bonus_days > 0:

                new_end_date_referee = await self.subscription_service.extend_active_subscription_days(
                    session=session,
                    user_id=referee_user_id,
                    bonus_days=referee_bonus_days,
                    reason=
                    f"referee bonus (invited by {inviter_name_for_referee_msg})"
                )
                if new_end_date_referee:
                    referee_final_end_date = new_end_date_referee
                    referee_bonus_applied_days = referee_bonus_days
                    logging.info(
                        f"Bonus of {referee_bonus_days} days successfully applied to referee {referee_user_id}."
                    )
                else:

                    logging.warning(
                        f"Failed to apply referee bonus for {referee_user_id} (could not extend their new subscription)."
                    )

            return {
                "referee_bonus_applied_days": referee_bonus_applied_days,
                "referee_new_end_date": referee_final_end_date,
                "inviter_bonus_applied_flag":
                inviter_bonus_successfully_applied
            }
        except Exception as e:
            logging.error(
                f"Error in apply_referral_bonuses_for_payment for referee {referee_user_id}: {e}",
                exc_info=True)

            raise

    def generate_referral_link(self, bot_username: str,
                               inviter_user_id: int) -> str:
        return f"https://t.me/{bot_username}?start=ref_{inviter_user_id}"
