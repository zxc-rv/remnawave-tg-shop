import logging
import asyncio
from aiogram import Router, F, types, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from typing import Optional

from config.settings import Settings

from db.database import get_all_users_for_broadcast, log_user_action
from bot.states.admin_states import AdminStates
from bot.keyboards.inline.admin_keyboards import get_broadcast_confirmation_keyboard, get_back_to_admin_panel_keyboard
from bot.middlewares.i18n import JsonI18n

router = Router(name="admin_broadcast_router")


async def broadcast_message_prompt_handler(callback: types.CallbackQuery,
                                           state: FSMContext, i18n_data: dict,
                                           settings: Settings):
    current_lang = i18n_data.get("current_language",
                                 getattr(settings, 'DEFAULT_LANGUAGE', 'en'))
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n:
        logging.error("i18n missing in broadcast_message_prompt_handler")
        await callback.answer("Language service error.", show_alert=True)
        return

    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)
    prompt_text = _("admin_broadcast_enter_message")

    if callback.message:
        try:
            await callback.message.edit_text(
                prompt_text,
                reply_markup=get_back_to_admin_panel_keyboard(
                    current_lang, i18n))
        except Exception as e:
            logging.warning(
                f"Could not edit message for broadcast prompt: {e}")
            await callback.message.answer(
                prompt_text,
                reply_markup=get_back_to_admin_panel_keyboard(
                    current_lang, i18n))
    await callback.answer()
    await state.set_state(AdminStates.waiting_for_broadcast_message)


@router.message(AdminStates.waiting_for_broadcast_message, F.text)
async def process_broadcast_message_handler(message: types.Message,
                                            state: FSMContext, i18n_data: dict,
                                            settings: Settings):
    current_lang = i18n_data.get("current_language",
                                 getattr(settings, 'DEFAULT_LANGUAGE', 'en'))
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n:
        logging.error("i18n missing in process_broadcast_message_handler")
        await message.reply("Language service error.")
        return

    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    broadcast_message_text = message.html_text
    await state.update_data(broadcast_message=broadcast_message_text)

    preview_snippet = broadcast_message_text[:200] + "..." if len(
        broadcast_message_text) > 200 else broadcast_message_text
    confirmation_prompt = _("admin_broadcast_confirm_prompt",
                            message_preview=preview_snippet)

    await message.answer(confirmation_prompt,
                         reply_markup=get_broadcast_confirmation_keyboard(
                             current_lang, i18n),
                         parse_mode="HTML")
    await state.set_state(AdminStates.confirming_broadcast)


@router.callback_query(F.data == "admin_action:main",
                       AdminStates.waiting_for_broadcast_message)
async def cancel_broadcast_at_prompt_stage(callback: types.CallbackQuery,
                                           state: FSMContext,
                                           settings: Settings,
                                           i18n_data: dict):
    from .common import admin_panel_actions_callback_handler
    current_lang = i18n_data.get("current_language",
                                 getattr(settings, 'DEFAULT_LANGUAGE', 'en'))
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n:
        logging.error("i18n missing")
        await callback.answer("Language error.", show_alert=True)
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    if callback.message:
        try:
            await callback.message.edit_text(_("admin_broadcast_cancelled"),
                                             reply_markup=None)
        except Exception:
            await callback.message.answer(_("admin_broadcast_cancelled"))
    await callback.answer(_("admin_broadcast_cancelled"))
    await state.clear()

    callback.data = "admin_action:main"

    from bot.keyboards.inline.admin_keyboards import get_admin_panel_keyboard
    if callback.message:
        await callback.message.answer(_("admin_panel_title"),
                                      reply_markup=get_admin_panel_keyboard(
                                          i18n, current_lang))


@router.callback_query(F.data.startswith("broadcast_final_action:"),
                       AdminStates.confirming_broadcast)
async def confirm_broadcast_callback_handler(callback: types.CallbackQuery,
                                             state: FSMContext,
                                             i18n_data: dict, bot: Bot,
                                             settings: Settings):
    current_lang = i18n_data.get("current_language",
                                 getattr(settings, 'DEFAULT_LANGUAGE', 'en'))
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n:
        logging.error("i18n missing")
        await callback.answer("Language error.", show_alert=True)
        return

    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    action = callback.data.split(":")[1]
    user_fsm_data = await state.get_data()
    broadcast_message = user_fsm_data.get("broadcast_message")

    if not callback.message:
        await callback.answer("Error: message context lost.", show_alert=True)
        await state.clear()
        return

    if action == "send":
        if not broadcast_message:
            await callback.message.edit_text(
                _("admin_broadcast_error_no_message"))
            await state.clear()
            await callback.answer(show_alert=True)
            return

        await callback.message.edit_text(_("admin_broadcast_sending_started"),
                                         reply_markup=None)
        await callback.answer()

        users_to_broadcast = await get_all_users_for_broadcast()
        sent_count = 0
        failed_count = 0
        logging.info(
            f"Starting broadcast: '{broadcast_message[:50]}...' to {len(users_to_broadcast)} users."
        )

        admin_user = callback.from_user

        for user_row in users_to_broadcast:
            user_id = user_row['user_id']
            try:
                await bot.send_message(user_id,
                                       broadcast_message,
                                       parse_mode="HTML")
                sent_count += 1

                await log_user_action(
                    user_id=admin_user.id,
                    telegram_username=admin_user.username,
                    telegram_first_name=admin_user.first_name,
                    event_type="admin_broadcast_sent",
                    content=f"To user {user_id}: {broadcast_message[:70]}...",
                    is_admin_event=True,
                    target_user_id=user_id)
            except Exception as e:
                failed_count += 1
                logging.warning(
                    f"Failed to send broadcast to user {user_id}: {type(e).__name__} - {e}"
                )

                await log_user_action(
                    user_id=admin_user.id,
                    telegram_username=admin_user.username,
                    telegram_first_name=admin_user.first_name,
                    event_type="admin_broadcast_failed",
                    content=
                    f"For user {user_id}: {type(e).__name__} - {str(e)[:70]}...",
                    is_admin_event=True,
                    target_user_id=user_id)
            await asyncio.sleep(0.05)

        result_message = _("admin_broadcast_finished_stats",
                           sent_count=sent_count,
                           failed_count=failed_count)
        await callback.message.answer(
            result_message,
            reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n))

    elif action == "cancel":
        await callback.message.edit_text(
            _("admin_broadcast_cancelled"),
            reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n))
        await callback.answer()

    await state.clear()
