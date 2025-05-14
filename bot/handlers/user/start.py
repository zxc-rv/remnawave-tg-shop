import logging
from aiogram import Router, F, types, Bot
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from typing import Optional, Dict, Any, Callable, Awaitable
from datetime import datetime, timezone, timedelta

from db.database import add_user_if_not_exists, update_user_language_code
from bot.keyboards.inline.user_keyboards import get_main_menu_inline_keyboard, get_language_selection_keyboard
from bot.services.subscription_service import SubscriptionService
from bot.services.panel_api_service import PanelApiService
from bot.services.referral_service import ReferralService
from bot.services.promo_code_service import PromoCodeService
from config.settings import Settings
from bot.middlewares.i18n import JsonI18n
from aiogram.types import InlineKeyboardMarkup

router = Router(name="user_start_router")


async def send_main_menu(message_or_callback: types.Message
                         | types.CallbackQuery,
                         settings: Settings,
                         i18n_data: dict,
                         show_trial_button_flag: bool,
                         is_edit: bool = False):
    current_lang = i18n_data.get("current_language",
                                 getattr(settings, 'DEFAULT_LANGUAGE', 'en'))
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    answered_callback_internally = False

    if not i18n:
        logging.error("i18n_instance missing in send_main_menu")
        target_mc_for_error = message_or_callback if isinstance(
            message_or_callback,
            types.Message) else message_or_callback.message
        error_text_fallback = "Error: Language service unavailable."
        if target_mc_for_error:
            try:
                await target_mc_for_error.answer(error_text_fallback)
            except Exception as e_ans:
                logging.error(
                    f"Failed to send error message in send_main_menu: {e_ans}")
        if isinstance(message_or_callback, types.CallbackQuery):
            await message_or_callback.answer()
            answered_callback_internally = True
        return

    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)
    user_full_name = message_or_callback.from_user.full_name
    text = _(key="main_menu_greeting", user_name=user_full_name)
    reply_markup: Optional[
        InlineKeyboardMarkup] = get_main_menu_inline_keyboard(
            current_lang, i18n, settings, show_trial_button_flag)
    target_message: Optional[types.Message] = None
    if isinstance(message_or_callback, types.Message):
        target_message = message_or_callback
    elif isinstance(message_or_callback, types.CallbackQuery):
        target_message = message_or_callback.message

    if not target_message:
        logging.error(
            f"send_main_menu: target_message is None for event from user {message_or_callback.from_user.id}."
        )
        if isinstance(
                message_or_callback,
                types.CallbackQuery) and not answered_callback_internally:
            await message_or_callback.answer("Error displaying menu.")
            answered_callback_internally = True
        return

    try:
        if is_edit:
            await target_message.edit_text(text, reply_markup=reply_markup)
        else:
            await target_message.answer(text, reply_markup=reply_markup)

        if isinstance(
                message_or_callback,
                types.CallbackQuery) and not answered_callback_internally:
            await message_or_callback.answer()
            answered_callback_internally = True
    except Exception as e_send_edit:
        logging.warning(
            f"Failed to send/edit main menu (user: {message_or_callback.from_user.id}): {e_send_edit}."
        )
        if is_edit:
            try:
                await target_message.answer(text, reply_markup=reply_markup)
            except Exception as e_send_new:
                logging.error(
                    f"Also failed to send new main menu message: {e_send_new}")
        if isinstance(
                message_or_callback,
                types.CallbackQuery) and not answered_callback_internally:
            await message_or_callback.answer()
            answered_callback_internally = True

    if isinstance(message_or_callback,
                  types.CallbackQuery) and not answered_callback_internally:
        logging.warning(
            f"Callback {message_or_callback.id} was not answered in send_main_menu main logic paths."
        )
        await message_or_callback.answer()


@router.message(CommandStart())
async def start_command_handler(message: types.Message, state: FSMContext,
                                settings: Settings, i18n_data: dict,
                                subscription_service: SubscriptionService,
                                bot: Bot):

    await state.clear()
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n:
        logging.error("i18n_instance not found")
        await message.answer("Language service error.")
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)
    user_id = message.from_user.id
    referred_by_user_id: Optional[int] = None
    args = message.text.split()
    if len(args) > 1 and args[0] == "/start":
        try:
            referral_param = args[1]
            if referral_param.startswith("ref_") and referral_param.split(
                    "_")[1].isdigit():
                potential_referrer_id = int(referral_param.split("_")[1])
                if potential_referrer_id != user_id:
                    referred_by_user_id = potential_referrer_id
        except (ValueError, IndexError) as e:
            logging.warning(f"Could not parse referral: '{args[1]}' - {e}")
    db_op_success, was_new_bot_user = await add_user_if_not_exists(
        user_id=user_id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
        lang_code=current_lang,
        referred_by_id=referred_by_user_id)
    if not db_op_success:
        await message.answer(_("error_occurred_processing_request"))
        return
    if referred_by_user_id:
        logging.info(
            f"User {user_id} started with referral from {referred_by_user_id}."
        )
    await message.answer(
        _(key="welcome", user_name=message.from_user.full_name))
    show_trial_button_in_menu = False
    if settings.TRIAL_ENABLED:
        if not await subscription_service.has_had_any_subscription(user_id):
            show_trial_button_in_menu = True
            logging.info(f"User {user_id} is eligible for a trial button.")

        else:
            logging.info(
                f"User {user_id} not eligible for trial button (already had a subscription)."
            )
    else:
        logging.info(f"Trial period is disabled in settings. No trial button.")
    await send_main_menu(message,
                         settings,
                         i18n_data,
                         show_trial_button_flag=show_trial_button_in_menu)


@router.message(Command("language"))
@router.callback_query(F.data == "main_action:language")
async def language_command_handler(event: types.Message | types.CallbackQuery,
                                   i18n_data: dict, settings: Settings):

    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    target_message_for_reply: Optional[types.Message] = None
    is_callback = isinstance(event, types.CallbackQuery)
    answered_callback = False
    if is_callback:
        await event.answer()
        answered_callback = True
        target_message_for_reply = event.message
    else:
        target_message_for_reply = event
    if not i18n:
        logging.error("i18n instance is missing in language_command_handler.")
        error_message_text = "Language service error."
        if target_message_for_reply:
            await target_message_for_reply.answer(error_message_text)
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)
    text_to_send = _(key="choose_language")
    reply_markup_to_send = get_language_selection_keyboard(i18n, current_lang)
    if not target_message_for_reply:
        logging.warning("language_command_handler: No target message.")
        return
    if is_callback:
        try:
            await target_message_for_reply.edit_text(
                text_to_send, reply_markup=reply_markup_to_send)
        except Exception as e:
            logging.info(
                f"Could not edit for lang selection: {e}. Sending new.")
            await target_message_for_reply.answer(
                text_to_send, reply_markup=reply_markup_to_send)
    else:
        await target_message_for_reply.answer(
            text_to_send, reply_markup=reply_markup_to_send)


@router.callback_query(F.data.startswith("set_lang_"))
async def select_language_callback_handler(
        callback: types.CallbackQuery, i18n_data: dict, settings: Settings,
        subscription_service: SubscriptionService):
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n or not callback.message:
        await callback.answer("Language service error.", show_alert=True)
        return

    lang_code = callback.data.split("_")[2]
    user_id = callback.from_user.id
    await update_user_language_code(user_id, lang_code)
    i18n_data["current_language"] = lang_code
    _ = lambda key, **kwargs: i18n.gettext(lang_code, key, **kwargs)

    await callback.answer(_(key="language_set_alert"))

    show_trial_button_after_lang_change = False
    if settings.TRIAL_ENABLED and not await subscription_service.has_had_any_subscription(
            user_id):
        show_trial_button_after_lang_change = True

    await send_main_menu(
        callback,
        settings,
        i18n_data,
        show_trial_button_flag=show_trial_button_after_lang_change,
        is_edit=True)


@router.callback_query(F.data.startswith("main_action:"))
async def main_action_callback_handler(
        callback: types.CallbackQuery, state: FSMContext, settings: Settings,
        i18n_data: dict, bot: Bot, subscription_service: SubscriptionService,
        referral_service: ReferralService, panel_service: PanelApiService,
        promo_code_service: PromoCodeService):

    action = callback.data.split(":")[1]
    from . import subscription as user_subscription_handlers
    from . import referral as user_referral_handlers
    from . import promo_user as user_promo_handlers
    from . import trial_handler as user_trial_handlers
    if not callback.message:
        logging.error(f"Callback {callback.id} no message for {action}")
        await callback.answer("Error.")
        return

    if action == "subscribe":
        await user_subscription_handlers.display_subscription_options(
            callback, i18n_data, settings)
    elif action == "my_subscription":
        await user_subscription_handlers.my_subscription_command_handler(
            callback, i18n_data, settings, panel_service, subscription_service)
    elif action == "referral":
        await user_referral_handlers.referral_command_handler(
            callback, settings, i18n_data, referral_service, bot)
    elif action == "apply_promo":
        await user_promo_handlers.prompt_promo_code_input(
            callback, state, i18n_data, settings)
    elif action == "request_trial":
        await user_trial_handlers.request_trial_confirmation_handler(
            callback, settings, i18n_data, subscription_service)
    elif action == "language":
        await language_command_handler(callback, i18n_data, settings)
    elif action == "back_to_main":
        show_trial_button_on_back = False
        if settings.TRIAL_ENABLED and not await subscription_service.has_had_any_subscription(
                callback.from_user.id):
            show_trial_button_on_back = True
        await send_main_menu(callback,
                             settings,
                             i18n_data,
                             show_trial_button_flag=show_trial_button_on_back,
                             is_edit=True)
    else:
        await callback.answer("Unknown action.", show_alert=True)
