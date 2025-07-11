import logging
from typing import Optional

from aiogram import Bot, types
from aiogram.types import LabeledPrice
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import Settings
from db.dal import payment_dal, user_dal
from .subscription_service import SubscriptionService
from .referral_service import ReferralService
from bot.middlewares.i18n import JsonI18n
from .notification_service import notify_admin_new_payment


class StarsService:
    def __init__(self, bot: Bot, settings: Settings, i18n: JsonI18n,
                 subscription_service: SubscriptionService,
                 referral_service: ReferralService):
        self.bot = bot
        self.settings = settings
        self.i18n = i18n
        self.subscription_service = subscription_service
        self.referral_service = referral_service

    async def create_invoice(self, session: AsyncSession, user_id: int, months: int,
                             stars_price: int, description: str) -> Optional[int]:
        payment_record_data = {
            "user_id": user_id,
            "amount": float(stars_price),
            "currency": "XTR",
            "status": "pending_stars",
            "description": description,
            "subscription_duration_months": months,
            "provider": "telegram_stars",
        }
        try:
            db_payment_record = await payment_dal.create_payment_record(
                session, payment_record_data)
            await session.commit()
        except Exception as e_db:
            await session.rollback()
            logging.error(f"Failed to create stars payment record: {e_db}",
                          exc_info=True)
            return None

        payload = f"{db_payment_record.payment_id}:{months}"
        prices = [LabeledPrice(label=description, amount=stars_price)]
        try:
            await self.bot.send_invoice(
                chat_id=user_id,
                title=description,
                description=description,
                payload=payload,
                provider_token="",
                currency="XTR",
                prices=prices,
            )
            return db_payment_record.payment_id
        except Exception as e_inv:
            logging.error(f"Failed to send Telegram Stars invoice: {e_inv}",
                          exc_info=True)
            return None

    async def process_successful_payment(self, session: AsyncSession,
                                         message: types.Message,
                                         payment_db_id: int,
                                         months: int,
                                         stars_amount: int,
                                         i18n_data: dict) -> None:
        try:
            await payment_dal.update_provider_payment_and_status(
                session, payment_db_id,
                message.successful_payment.provider_payment_charge_id,
                "succeeded")
            await session.commit()
        except Exception as e_upd:
            await session.rollback()
            logging.error(
                f"Failed to update stars payment record {payment_db_id}: {e_upd}",
                exc_info=True)
            return

        activation_details = await self.subscription_service.activate_subscription(
            session,
            message.from_user.id,
            months,
            float(stars_amount),
            payment_db_id,
            provider="telegram_stars",
        )
        if not activation_details or not activation_details.get("end_date"):
            logging.error(
                f"Failed to activate subscription after stars payment for user {message.from_user.id}")
            return

        referral_bonus = await self.referral_service.apply_referral_bonuses_for_payment(
            session, message.from_user.id, months)
        await session.commit()

        applied_days = referral_bonus.get("referee_bonus_applied_days") if referral_bonus else None
        final_end = referral_bonus.get("referee_new_end_date") if referral_bonus else None
        if not final_end:
            final_end = activation_details["end_date"]

        current_lang = i18n_data.get("current_language",
                                     self.settings.DEFAULT_LANGUAGE)
        i18n: JsonI18n = i18n_data.get("i18n_instance")
        _ = lambda k, **kw: i18n.gettext(current_lang, k, **kw) if i18n else k

        if applied_days:
            inviter_name_display = _("friend_placeholder")
            db_user = await user_dal.get_user_by_id(session, message.from_user.id)
            if db_user and db_user.referred_by_id:
                inviter = await user_dal.get_user_by_id(session, db_user.referred_by_id)
                if inviter and inviter.first_name:
                    inviter_name_display = inviter.first_name
                elif inviter and inviter.username:
                    inviter_name_display = f"@{inviter.username}"
            success_msg = _(
                "payment_successful_with_referral_bonus",
                months=months,
                base_end_date=activation_details["end_date"].strftime('%Y-%m-%d'),
                bonus_days=applied_days,
                final_end_date=final_end.strftime('%Y-%m-%d'),
                inviter_name=inviter_name_display,
            )
        else:
            success_msg = _("payment_successful", months=months,
                            end_date=final_end.strftime('%Y-%m-%d'))
        try:
            await self.bot.send_message(message.from_user.id, success_msg)
        except Exception as e_send:
            logging.error(
                f"Failed to send stars payment success message: {e_send}")

        await notify_admin_new_payment(
            self.bot,
            self.settings,
            self.i18n,
            message.from_user.id,
            months,
            float(stars_amount),
            currency="XTR",
        )

