import logging
import math
import re
from aiogram import Router, F, types, Bot
from aiogram.fsm.context import FSMContext
from typing import Optional, List, Dict, Any
import aiosqlite

from config.settings import Settings
from db.database import (get_all_message_logs_paginated,
                         count_all_message_logs,
                         get_user_message_logs_paginated,
                         count_user_message_logs, get_user,
                         get_user_by_telegram_username)
from bot.states.admin_states import AdminStates
from bot.keyboards.inline.admin_keyboards import (
    get_logs_menu_keyboard, get_logs_pagination_keyboard,
    get_back_to_admin_panel_keyboard, get_admin_panel_keyboard)
from bot.middlewares.i18n import JsonI18n

router = Router(name="admin_logs_router")
USERNAME_REGEX = re.compile(r"^[a-zA-Z0-9_]{5,32}$")


async def display_logs_menu(callback: types.CallbackQuery, i18n_data: dict,
                            settings: Settings):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")

    if not i18n:
        logging.error("i18n_instance missing in display_logs_menu")
        await callback.answer("Language service error.", show_alert=True)
        return
    if not callback.message:
        logging.error("CallbackQuery has no message in display_logs_menu")
        await callback.answer("Error processing request.", show_alert=True)
        return

    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    try:
        await callback.message.edit_text(text=_(key="admin_logs_menu_title"),
                                         reply_markup=get_logs_menu_keyboard(
                                             i18n, current_lang))
    except Exception as e:
        logging.warning(f"Failed to edit message for logs menu: {e}")
        await callback.message.answer(text=_(key="admin_logs_menu_title"),
                                      reply_markup=get_logs_menu_keyboard(
                                          i18n, current_lang))
    await callback.answer()


async def _display_formatted_logs(target_message: types.Message,
                                  logs: List[aiosqlite.Row],
                                  total_logs: int,
                                  current_page: int,
                                  settings: Settings,
                                  title_key: str,
                                  base_pagination_callback_data: str,
                                  i18n: JsonI18n,
                                  current_lang: str,
                                  title_kwargs: Optional[Dict[str,
                                                              Any]] = None):
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)
    page_size = settings.LOGS_PAGE_SIZE

    actual_title_kwargs = title_kwargs or {}

    if not logs and total_logs == 0:
        text = _(
            title_key, current_page=1, total_pages=1, **
            actual_title_kwargs) + "\n\n" + _("admin_no_logs_found")
        reply_markup = get_logs_pagination_keyboard(
            current_page,
            1,
            base_pagination_callback_data,
            i18n,
            current_lang,
            back_to_logs_menu=True)
    else:
        total_pages = math.ceil(total_logs / page_size) if page_size > 0 else 1
        text = _(title_key,
                 current_page=current_page + 1,
                 total_pages=max(1, total_pages),
                 **actual_title_kwargs) + "\n"

        log_entries_text = []
        for log_entry in logs:
            user_display_parts = []

            telegram_first_name = log_entry[
                'telegram_first_name'] if 'telegram_first_name' in log_entry.keys(
                ) and log_entry['telegram_first_name'] else None
            telegram_username = log_entry[
                'telegram_username'] if 'telegram_username' in log_entry.keys(
                ) and log_entry['telegram_username'] else None
            user_id_from_log = log_entry[
                'user_id'] if 'user_id' in log_entry.keys(
                ) and log_entry['user_id'] else None

            if telegram_first_name:
                user_display_parts.append(telegram_first_name)
            if telegram_username:
                user_display_parts.append(f"(@{telegram_username})")

            user_display = " ".join(user_display_parts).strip()
            if not user_display:
                user_display = _(
                    "system_or_unknown_user"
                ) if not user_id_from_log else f"ID: {user_id_from_log}"

            user_id_display = str(
                user_id_from_log) if user_id_from_log is not None else "N/A"
            content_raw = log_entry['content'] if 'content' in log_entry.keys(
            ) and log_entry['content'] else ""
            content_preview = (content_raw[:100] +
                               "...") if len(content_raw) > 100 else (
                                   content_raw or "N/A")

            log_entries_text.append(
                _("admin_log_entry_format",
                  timestamp_str=log_entry['timestamp_str']
                  if 'timestamp_str' in log_entry.keys() else 'N/A',
                  user_display=user_display,
                  user_id=user_id_display,
                  event_type=log_entry['event_type']
                  if 'event_type' in log_entry.keys() else 'N/A',
                  content_preview=content_preview).replace("\n", "\n  "))
        text += "\n\n".join(log_entries_text)
        reply_markup = get_logs_pagination_keyboard(
            current_page,
            total_pages,
            base_pagination_callback_data,
            i18n,
            current_lang,
            back_to_logs_menu=True)

    try:
        await target_message.edit_text(text,
                                       reply_markup=reply_markup,
                                       parse_mode="HTML",
                                       disable_web_page_preview=True)
    except Exception as e:
        logging.warning(
            f"Failed to edit message for logs display: {e}. Content length: {len(text)}"
        )
        chunk_size = 4000
        for i in range(0, len(text), chunk_size):
            chunk = text[i:i + chunk_size]
            is_last_chunk = (i + chunk_size) >= len(text)
            await target_message.answer(
                chunk,
                reply_markup=reply_markup if is_last_chunk else None,
                parse_mode="HTML",
                disable_web_page_preview=True)


@router.callback_query(F.data.startswith("admin_logs:view_all"))
async def view_all_logs_handler(callback: types.CallbackQuery,
                                settings: Settings, i18n_data: dict):
    page = 0
    parts = callback.data.split(":")

    if len(parts) == 3:
        try:
            page = int(parts[2])
        except ValueError:
            page = 0

    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    if not i18n or not callback.message:
        await callback.answer("Error processing request.", show_alert=True)
        return

    logs, total_logs = await get_all_message_logs_paginated(
        settings.LOGS_PAGE_SIZE,
        page * settings.LOGS_PAGE_SIZE), await count_all_message_logs()

    await _display_formatted_logs(
        target_message=callback.message,
        logs=logs,
        total_logs=total_logs,
        current_page=page,
        settings=settings,
        title_key="admin_all_logs_title",
        base_pagination_callback_data="admin_logs:view_all",
        i18n=i18n,
        current_lang=current_lang)
    await callback.answer()


@router.callback_query(F.data == "admin_logs:prompt_user")
async def prompt_user_for_logs_handler(callback: types.CallbackQuery,
                                       state: FSMContext, i18n_data: dict,
                                       settings: Settings):
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    if not i18n or not callback.message:
        await callback.answer("Error")
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    await callback.message.edit_text(
        text=_("admin_prompt_for_user_id_or_username_logs"),
        reply_markup=get_logs_menu_keyboard(i18n, current_lang))
    await state.set_state(AdminStates.waiting_for_user_id_for_logs)
    await callback.answer()


@router.message(AdminStates.waiting_for_user_id_for_logs, F.text)
async def process_user_id_for_logs_handler(message: types.Message,
                                           state: FSMContext,
                                           settings: Settings,
                                           i18n_data: dict):
    current_state_fsm = await state.get_state()
    logging.info(
        f"Processing user input for logs in state {current_state_fsm}: '{message.text}'"
    )
    await state.clear()

    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    if not i18n:
        await message.reply("Language error.")
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    input_text = message.text.strip()
    user_data_for_logs: Optional[aiosqlite.Row] = None

    if input_text.isdigit():
        try:
            user_data_for_logs = await get_user(int(input_text))
        except ValueError:
            pass
    elif input_text.startswith("@") and USERNAME_REGEX.match(input_text[1:]):
        user_data_for_logs = await get_user_by_telegram_username(input_text[1:]
                                                                 )
    elif USERNAME_REGEX.match(input_text):
        user_data_for_logs = await get_user_by_telegram_username(input_text)

    if not user_data_for_logs:
        await message.answer(_("admin_log_user_not_found", input=input_text))
        return

    target_user_id = user_data_for_logs['user_id']
    user_display = user_data_for_logs['first_name'] or (
        f"@{user_data_for_logs['username']}"
        if user_data_for_logs.get('username') else f"ID {target_user_id}")

    logs, total_logs = await get_user_message_logs_paginated(
        target_user_id, settings.LOGS_PAGE_SIZE,
        0), await count_user_message_logs(target_user_id)

    await _display_formatted_logs(
        target_message=message,
        logs=logs,
        total_logs=total_logs,
        current_page=0,
        settings=settings,
        title_key="admin_user_logs_title",
        base_pagination_callback_data=f"admin_logs:view_user:{target_user_id}",
        i18n=i18n,
        current_lang=current_lang,
        title_kwargs={"user_display": user_display})


@router.callback_query(F.data.startswith("admin_logs:view_user:"))
async def view_user_logs_paginated_handler(callback: types.CallbackQuery,
                                           settings: Settings,
                                           i18n_data: dict):
    try:
        parts = callback.data.split(":")
        target_user_id = int(parts[2])
        page = int(parts[3])
    except (IndexError, ValueError):
        await callback.answer("Invalid log request.", show_alert=True)
        return

    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    if not i18n or not callback.message:
        await callback.answer("Error")
        return

    user_data_for_logs = await get_user(target_user_id)
    if not user_data_for_logs:
        await callback.message.edit_text("User not found for logs.")
        await callback.answer()
        return
    user_display = user_data_for_logs['first_name'] or (
        f"@{user_data_for_logs['username']}"
        if user_data_for_logs.get('username') else f"ID {target_user_id}")

    logs, total_logs = await get_user_message_logs_paginated(
        target_user_id, settings.LOGS_PAGE_SIZE, page *
        settings.LOGS_PAGE_SIZE), await count_user_message_logs(target_user_id)

    await _display_formatted_logs(
        target_message=callback.message,
        logs=logs,
        total_logs=total_logs,
        current_page=page,
        settings=settings,
        title_key="admin_user_logs_title",
        base_pagination_callback_data=f"admin_logs:view_user:{target_user_id}",
        i18n=i18n,
        current_lang=current_lang,
        title_kwargs={"user_display": user_display})
    await callback.answer()


@router.callback_query(F.data == "admin_action:view_logs_menu",
                       AdminStates.waiting_for_user_id_for_logs)
async def cancel_log_user_input_state_to_menu(callback: types.CallbackQuery,
                                              state: FSMContext,
                                              settings: Settings,
                                              i18n_data: dict):
    await state.clear()
    await display_logs_menu(callback, i18n_data, settings)
