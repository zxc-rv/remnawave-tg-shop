import logging
from aiogram import Router, F, types, Bot
from aiogram.filters import Command
from typing import Optional, Dict

from config.settings import Settings
from bot.services.referral_service import ReferralService
from db.database import get_db_connection_manager
from bot.keyboards.inline.user_keyboards import get_referral_link_keyboard, get_back_to_main_menu_markup
from bot.middlewares.i18n import JsonI18n

router = Router(name="user_referral_router")


async def referral_command_handler(event: types.Message | types.CallbackQuery,
                                   settings: Settings, i18n_data: dict,
                                   referral_service: ReferralService,
                                   bot: Bot):
    current_lang = i18n_data.get("current_language",
                                 getattr(settings, 'DEFAULT_LANGUAGE', 'en'))
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")

    target_message = event.message if isinstance(
        event, types.CallbackQuery) else event
    if not target_message:
        logging.error(
            "Target message is None in referral_command_handler from callback."
        )
        if isinstance(event, types.CallbackQuery):
            await event.answer("Error displaying referral info.")
        return

    if not i18n or not referral_service:
        logging.error("Deps missing in referral_command_handler")
        await target_message.answer("Service error." if isinstance(
            event, types.Message) else "Service error.",
                                    parse_mode=None)
        if isinstance(event, types.CallbackQuery): await event.answer()
        return

    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    bot_info = await bot.get_me()
    bot_username = bot_info.username
    inviter_user_id = event.from_user.id
    referral_link = referral_service.generate_referral_link(
        bot_username, inviter_user_id)
    bonus_info_parts = []

    if hasattr(settings,
               'subscription_options') and settings.subscription_options:
        for months_period in sorted(settings.subscription_options.keys()):
            inv_bonus = settings.referral_bonus_inviter.get(months_period)
            ref_bonus = settings.referral_bonus_referee.get(months_period)
            if inv_bonus is not None or ref_bonus is not None:
                bonus_info_parts.append(
                    _("referral_bonus_per_period",
                      months=months_period,
                      inviter_bonus_days=inv_bonus
                      if inv_bonus is not None else _("no_bonus_days"),
                      referee_bonus_days=ref_bonus
                      if ref_bonus is not None else _("no_bonus_days")))
    bonus_details_str = "\n".join(bonus_info_parts) if bonus_info_parts else _(
        "referral_no_bonuses_configured")
    text = _("referral_program_info_new",
             referral_link=referral_link,
             bonus_details=bonus_details_str)

    reply_markup_val = get_back_to_main_menu_markup(current_lang, i18n)

    if isinstance(event, types.Message):
        await event.answer(text,
                           reply_markup=reply_markup_val,
                           disable_web_page_preview=True)
    elif isinstance(event, types.CallbackQuery):
        try:
            await event.message.edit_text(text,
                                          reply_markup=reply_markup_val,
                                          disable_web_page_preview=True)
        except Exception as e:
            logging.warning(f"Failed to edit message for referral info: {e}")

            await event.message.answer(text,
                                       reply_markup=reply_markup_val,
                                       disable_web_page_preview=True)
        await event.answer()


@router.callback_query(F.data == "copy_referral_link_ack")
async def copy_referral_link_ack_callback_handler(
        callback: types.CallbackQuery, i18n_data: dict, settings: Settings):
    current_lang = i18n_data.get("current_language",
                                 getattr(settings, 'DEFAULT_LANGUAGE', 'en'))
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n:
        return await callback.answer("Language service error.",
                                     show_alert=True)
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)
    await callback.answer(text=_(key="referral_link_for_copying_reminder"),
                          show_alert=False)
