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

@router.callback_query(F.data.startswith("admin_extend:"))
async def admin_extend_subscription_handler(
        callback: types.CallbackQuery, settings: Settings,
        i18n_data: dict, bot: Bot, subscription_service: SubscriptionService,
        session: AsyncSession):
    
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs) if i18n else key
    
    try:
        from db.dal import user_dal
        
        parts = callback.data.split(":")
        target_user_id = int(parts[1])
        action = parts[2]
        
        db_user = await user_dal.get_user_by_id(session, target_user_id)
        user_name = f"{db_user.first_name or ''} {db_user.last_name or ''}".strip() if db_user else f"ID{target_user_id}"
        
        if action == "decline":
            await callback.message.edit_text(
                _("admin_payment_declined", user_name=user_name, user_id=target_user_id)
            )
            await callback.answer(_("admin_payment_declined", user_name=user_name, user_id=target_user_id))
            return
        
        days_to_extend = int(action)
        
        new_end_date = await subscription_service.extend_active_subscription_days(
            session, 
            target_user_id, 
            days_to_extend, 
            reason="admin_manual_extension"
        )
        
        if new_end_date:
            await callback.message.edit_text(
                _("admin_subscription_extended", user_name=user_name, user_id=target_user_id, days=days_to_extend) +
                f"\n📅 Новая дата окончания: {new_end_date.strftime('%d.%m.%Y')}"
            )
            
            try:
                user_lang = db_user.language_code if db_user and db_user.language_code else settings.DEFAULT_LANGUAGE
                user_msg = i18n.gettext(user_lang, "subscription_extended_by_admin", 
                                       days=days_to_extend,
                                       end_date=new_end_date.strftime('%d-%m-%Y'))
                await bot.send_message(target_user_id, user_msg)
            except Exception as e:
                logging.warning(f"Failed to notify user {target_user_id} about extension: {e}")
            
            await callback.answer(f"✅ Продлено на {days_to_extend} дней")
        else:
            await callback.answer("❌ Ошибка продления подписки", show_alert=True)
            await callback.message.edit_text(
                f"❌ Ошибка продления подписки для {user_name} (id{target_user_id})"
            )
            
    except (ValueError, IndexError) as e:
        logging.error(f"Invalid callback data in admin_extend_subscription_handler: {callback.data}")
        await callback.answer("Invalid request", show_alert=True)
    except Exception as e:
        logging.error(f"Error in admin extend handler: {e}")
        await callback.answer(f"❌ Ошибка: {str(e)}", show_alert=True)


