import logging
from aiogram import Router, F, types, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import Settings
from bot.keyboards.inline.admin_keyboards import get_admin_panel_keyboard
from bot.middlewares.i18n import JsonI18n
from bot.services.panel_api_service import PanelApiService
from bot.services.subscription_service import SubscriptionService

from . import broadcast as admin_broadcast_handlers
from . import promo_codes as admin_promo_handlers
from . import user_management as admin_user_mgmnt_handlers
from . import statistics as admin_stats_handlers
from . import sync_admin as admin_sync_handlers
from . import logs_admin as admin_logs_handlers

router = Router(name="admin_common_router")


@router.message(Command("admin"))
async def admin_panel_command_handler(
    message: types.Message,
    state: FSMContext,
    settings: Settings,
    i18n_data: dict,
):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n:
        logging.error("i18n missing in admin_panel_command_handler")
        await message.answer("Language service error.")
        return

    await state.clear()
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)
    await message.answer(_(key="admin_panel_title"),
                         reply_markup=get_admin_panel_keyboard(
                             i18n, current_lang, settings))


@router.callback_query(F.data.startswith("admin_action:"))
async def admin_panel_actions_callback_handler(
        callback: types.CallbackQuery, state: FSMContext, settings: Settings,
        i18n_data: dict, bot: Bot, panel_service: PanelApiService,
        subscription_service: SubscriptionService, session: AsyncSession):
    action_parts = callback.data.split(":")
    action = action_parts[1]

    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n:
        logging.error("i18n missing in admin_panel_actions_callback_handler")
        await callback.answer("Language error.", show_alert=True)
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    if not callback.message:
        logging.error(
            f"CallbackQuery {callback.id} from {callback.from_user.id} has no message for admin_action {action}"
        )
        await callback.answer("Error processing action: message context lost.",
                              show_alert=True)
        return

    if action == "stats":
        await admin_stats_handlers.show_statistics_handler(
            callback, i18n_data, settings, session)
    elif action == "broadcast":
        await admin_broadcast_handlers.broadcast_message_prompt_handler(
            callback, state, i18n_data, settings, session)
    elif action == "create_promo":
        await admin_promo_handlers.create_promo_prompt_handler(
            callback, state, i18n_data, settings, session)
    elif action == "manage_promos":
        await admin_promo_handlers.manage_promo_codes_handler(
            callback, i18n_data, settings, session)
    elif action == "view_promos":
        await admin_promo_handlers.view_promo_codes_handler(
            callback, i18n_data, settings, session)
    elif action == "ban_user_prompt":
        await admin_user_mgmnt_handlers.ban_user_prompt_handler(
            callback, state, i18n_data, settings, session)
    elif action == "unban_user_prompt":
        await admin_user_mgmnt_handlers.unban_user_prompt_handler(
            callback, state, i18n_data, settings, session)
    elif action == "view_banned":

        await admin_user_mgmnt_handlers.view_banned_users_handler(
            callback, state, i18n_data, settings, session)
    elif action == "view_logs_menu":
        await admin_logs_handlers.display_logs_menu(callback, i18n_data,
                                                    settings, session)
    elif action == "sync_panel":

        await admin_sync_handlers.sync_command_handler(
            message_event=callback,
            bot=bot,
            settings=settings,
            i18n_data=i18n_data,
            panel_service=panel_service,
            session=session)
        await callback.answer(_("admin_sync_initiated_from_panel"))
    elif action == "main":
        try:
            await callback.message.edit_text(
                _(key="admin_panel_title"),
                reply_markup=get_admin_panel_keyboard(i18n, current_lang,
                                                      settings))
        except Exception:
            await callback.message.answer(
                _(key="admin_panel_title"),
                reply_markup=get_admin_panel_keyboard(i18n, current_lang,
                                                      settings))
        await callback.answer()
    else:
        logging.warning(
            f"Unknown admin_action received: {action} from callback {callback.data}"
        )
        await callback.answer(_("admin_unknown_action"), show_alert=True)
