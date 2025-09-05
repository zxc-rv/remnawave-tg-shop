import logging
import math
import re
from aiogram import Router, F, types, Bot
from aiogram.fsm.context import FSMContext
from typing import Optional, List, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import Settings

from db.dal import message_log_dal, user_dal
from db.models import MessageLog, User

from bot.states.admin_states import AdminStates
from bot.keyboards.inline.admin_keyboards import (
    get_logs_menu_keyboard, get_logs_pagination_keyboard,
    get_back_to_admin_panel_keyboard)
from bot.middlewares.i18n import JsonI18n

router = Router(name="admin_logs_router")
USERNAME_REGEX = re.compile(r"^[a-zA-Z0-9_]{5,32}$")


async def display_logs_menu(callback: types.CallbackQuery, i18n_data: dict,
                            settings: Settings, session: AsyncSession):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")

    if not i18n or not callback.message:
        await callback.answer("Error displaying logs menu.", show_alert=True)
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    try:
        await callback.message.edit_text(text=_(key="admin_logs_menu_title"),
                                         reply_markup=get_logs_menu_keyboard(
                                             i18n, current_lang))
    except Exception as e:
        logging.warning(
            f"Failed to edit message for logs menu: {e}. Sending new.")
        await callback.message.answer(text=_(key="admin_logs_menu_title"),
                                      reply_markup=get_logs_menu_keyboard(
                                          i18n, current_lang))
    await callback.answer()


async def _display_formatted_logs(target_message: types.Message,
                                  logs: List[MessageLog],
                                  total_logs: int,
                                  current_page_idx: int,
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
            current_page_idx,
            1,
            base_pagination_callback_data,
            i18n,
            current_lang,
            back_to_logs_menu=True)
    else:
        total_pages = math.ceil(total_logs / page_size) if page_size > 0 else 1
        text = _(title_key,
                 current_page=current_page_idx + 1,
                 total_pages=max(1, total_pages),
                 **actual_title_kwargs) + "\n"

        log_entries_text = []
        for log_entry_model in logs:
            user_display_parts = []
            if log_entry_model.telegram_first_name:
                user_display_parts.append(log_entry_model.telegram_first_name)
            if log_entry_model.telegram_username:
                user_display_parts.append(
                    f"(@{log_entry_model.telegram_username})")

            user_display = " ".join(user_display_parts).strip()
            if not user_display:
                user_display = _(
                    "system_or_unknown_user"
                ) if not log_entry_model.user_id else f"ID: {log_entry_model.user_id}"

            user_id_display = str(
                log_entry_model.user_id
            ) if log_entry_model.user_id is not None else "N/A"
            content_raw = log_entry_model.content or ""
            content_preview = (content_raw[:100] +
                               "...") if len(content_raw) > 100 else (
                                   content_raw or "N/A")

            timestamp_str_display = log_entry_model.timestamp.strftime(
                '%d.%m.%Y %H:%M:%S') if log_entry_model.timestamp else 'N/A'

            log_entries_text.append(
                _("admin_log_entry_format",
                  timestamp_str=timestamp_str_display,
                  user_display=user_display,
                  user_id=user_id_display,
                  event_type=log_entry_model.event_type or 'N/A',
                  content_preview=content_preview).replace("\n", "\n  "))
        text += "\n\n".join(log_entries_text)
        reply_markup = get_logs_pagination_keyboard(
            current_page_idx,
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
            f"Failed to edit message for logs display (len: {len(text)}): {e}. Sending new message(s)."
        )

        max_chunk_size = 4000
        for i in range(0, len(text), max_chunk_size):
            chunk = text[i:i + max_chunk_size]
            is_last_chunk = (i + max_chunk_size) >= len(text)
            try:
                await target_message.answer(
                    chunk,
                    reply_markup=reply_markup if is_last_chunk else None,
                    parse_mode="HTML",
                    disable_web_page_preview=True)
            except Exception as e_chunk:
                logging.error(f"Failed to send log chunk: {e_chunk}")

                if i == 0:
                    await target_message.answer(
                        _("error_displaying_logs_too_long"),
                        reply_markup=reply_markup if is_last_chunk else None)
                break


@router.callback_query(F.data.startswith("admin_logs:view_all"))
async def view_all_logs_handler(callback: types.CallbackQuery,
                                settings: Settings, i18n_data: dict,
                                session: AsyncSession):
    page_idx = 0
    parts = callback.data.split(":")
    if len(parts) == 3:
        try:
            page_idx = int(parts[2])
        except ValueError:
            page_idx = 0

    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    if not i18n or not callback.message:
        await callback.answer("Error processing request.", show_alert=True)
        return

    logs_models = await message_log_dal.get_all_message_logs(
        session, settings.LOGS_PAGE_SIZE, page_idx * settings.LOGS_PAGE_SIZE)
    total_logs_count = await message_log_dal.count_all_message_logs(session)

    await _display_formatted_logs(
        target_message=callback.message,
        logs=logs_models,
        total_logs=total_logs_count,
        current_page_idx=page_idx,
        settings=settings,
        title_key="admin_all_logs_title",
        base_pagination_callback_data="admin_logs:view_all",
        i18n=i18n,
        current_lang=current_lang)
    await callback.answer()


@router.callback_query(F.data == "admin_logs:prompt_user")
async def prompt_user_for_logs_handler(callback: types.CallbackQuery,
                                       state: FSMContext, i18n_data: dict,
                                       settings: Settings,
                                       session: AsyncSession):
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    if not i18n or not callback.message:
        await callback.answer("Error preparing user log prompt.",
                              show_alert=True)
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
                                           settings: Settings, i18n_data: dict,
                                           session: AsyncSession):
    await state.clear()

    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    if not i18n:
        await message.reply("Language service error.")
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    input_text = message.text.strip() if message.text else ""
    user_model_for_logs: Optional[User] = None

    if input_text.isdigit():
        try:
            user_model_for_logs = await user_dal.get_user_by_id(
                session, int(input_text))
        except ValueError:
            pass
    elif input_text.startswith("@") and USERNAME_REGEX.match(input_text[1:]):
        user_model_for_logs = await user_dal.get_user_by_username(
            session, input_text[1:])
    elif USERNAME_REGEX.match(input_text):
        user_model_for_logs = await user_dal.get_user_by_username(
            session, input_text)

    if not user_model_for_logs:
        await message.answer(_("admin_log_user_not_found", input=input_text))
        return

    target_user_id = user_model_for_logs.user_id
    user_display_name = user_model_for_logs.first_name or (
        f"@{user_model_for_logs.username}"
        if user_model_for_logs.username else f"ID {target_user_id}")

    logs_models = await message_log_dal.get_user_message_logs(
        session, target_user_id, settings.LOGS_PAGE_SIZE, 0)
    total_user_logs_count = await message_log_dal.count_user_message_logs(
        session, target_user_id)

    await _display_formatted_logs(
        target_message=message,
        logs=logs_models,
        total_logs=total_user_logs_count,
        current_page_idx=0,
        settings=settings,
        title_key="admin_user_logs_title",
        base_pagination_callback_data=f"admin_logs:view_user:{target_user_id}",
        i18n=i18n,
        current_lang=current_lang,
        title_kwargs={"user_display": user_display_name})


@router.callback_query(F.data.startswith("admin_logs:view_user:"))
async def view_user_logs_paginated_handler(callback: types.CallbackQuery,
                                           settings: Settings, i18n_data: dict,
                                           session: AsyncSession):
    try:
        parts = callback.data.split(":")
        target_user_id = int(parts[2])
        page_idx = int(parts[3])
    except (IndexError, ValueError):
        await callback.answer("Invalid log request format.", show_alert=True)
        return

    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    if not i18n or not callback.message:
        await callback.answer("Error processing request.", show_alert=True)
        return

    user_model_for_logs = await user_dal.get_user_by_id(
        session, target_user_id)
    if not user_model_for_logs:
        await callback.message.edit_text("User not found for logs.")
        await callback.answer()
        return

    user_display_name = user_model_for_logs.first_name or (
        f"@{user_model_for_logs.username}"
        if user_model_for_logs.username else f"ID {target_user_id}")

    logs_models = await message_log_dal.get_user_message_logs(
        session, target_user_id, settings.LOGS_PAGE_SIZE,
        page_idx * settings.LOGS_PAGE_SIZE)
    total_user_logs_count = await message_log_dal.count_user_message_logs(
        session, target_user_id)

    await _display_formatted_logs(
        target_message=callback.message,
        logs=logs_models,
        total_logs=total_user_logs_count,
        current_page_idx=page_idx,
        settings=settings,
        title_key="admin_user_logs_title",
        base_pagination_callback_data=f"admin_logs:view_user:{target_user_id}",
        i18n=i18n,
        current_lang=current_lang,
        title_kwargs={"user_display": user_display_name})
    await callback.answer()


@router.callback_query(F.data == "admin_action:view_logs_menu",
                       AdminStates.waiting_for_user_id_for_logs)
async def cancel_log_user_input_state_to_menu(callback: types.CallbackQuery,
                                              state: FSMContext,
                                              settings: Settings,
                                              i18n_data: dict,
                                              session: AsyncSession):
    await state.clear()

    await display_logs_menu(callback, i18n_data, settings, session)
