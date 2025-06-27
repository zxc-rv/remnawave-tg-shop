import logging
import re
import math
from aiogram import Router, F, types, Bot
from aiogram.fsm.context import FSMContext
from typing import Optional, Tuple, List, Any

from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from config.settings import Settings

from db.dal import user_dal, subscription_dal
from db.models import User, Subscription

from bot.services.panel_api_service import PanelApiService

from bot.states.admin_states import AdminStates
from bot.keyboards.inline.admin_keyboards import (
    get_back_to_admin_panel_keyboard, get_user_card_keyboard,
    get_banned_users_keyboard, get_confirmation_keyboard,
    get_admin_panel_keyboard)
from bot.middlewares.i18n import JsonI18n

router = Router(name="admin_user_management_router")
USERNAME_REGEX = re.compile(r"^[a-zA-Z0-9_]{5,32}$")


async def _get_user_model_by_input(session: AsyncSession,
                                   input_text: str) -> Optional[User]:
    if input_text.isdigit():
        try:
            return await user_dal.get_user(session, user_id=int(input_text))
        except ValueError:
            return None
    if input_text.startswith("@") and USERNAME_REGEX.match(input_text[1:]):
        return await user_dal.get_user(session, username=input_text[1:])
    if USERNAME_REGEX.match(input_text):
        return await user_dal.get_user(session, username=input_text)
    return None


async def ban_user_prompt_handler(callback: types.CallbackQuery,
                                  state: FSMContext, i18n_data: dict,
                                  settings: Settings, session: AsyncSession):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n or not callback.message:
        await callback.answer("Error processing ban prompt.", show_alert=True)
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    prompt_text = _("admin_ban_user_prompt")
    try:
        await callback.message.edit_text(
            prompt_text,
            reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n))
    except Exception as e:
        logging.warning(
            f"Edit failed for ban_user_prompt: {e}. Sending new message.")
        await callback.message.answer(
            prompt_text,
            reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n))

    await callback.answer()
    await state.set_state(AdminStates.waiting_for_user_id_to_ban)


@router.message(AdminStates.waiting_for_user_id_to_ban, F.text)
async def process_user_input_to_ban_handler(message: types.Message,
                                            state: FSMContext, i18n_data: dict,
                                            settings: Settings,
                                            panel_service: PanelApiService,
                                            session: AsyncSession):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n:
        await message.reply("Language service error.")
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    input_text = message.text.strip() if message.text else ""
    user_to_ban_model = await _get_user_model_by_input(session, input_text)

    if not user_to_ban_model:
        await message.answer(
            _("admin_user_not_found_in_bot_db", user_id=input_text))
        await state.clear()
        return

    user_id_to_ban = user_to_ban_model.user_id
    user_display_for_msg = user_to_ban_model.username or str(user_id_to_ban)

    if message.from_user and (user_id_to_ban == message.from_user.id
                              or user_id_to_ban in settings.ADMIN_IDS):
        await message.answer(_("admin_cannot_ban_self_or_admin"))
        await state.clear()
        return

    if user_to_ban_model.is_banned:
        await message.answer(
            _("admin_user_already_banned",
              user_id_or_username=user_display_for_msg))
        await state.clear()
        return

    ban_success_local = await user_dal.set_user_ban_status(
        session, user_id_to_ban, True)

    if ban_success_local:

        panel_ban_message_part = ""
        if user_to_ban_model.panel_user_uuid:
            panel_ban_api_success = await panel_service.update_user_status_on_panel(
                user_to_ban_model.panel_user_uuid, enable=False)
            if panel_ban_api_success:
                panel_ban_message_part = _("admin_panel_ban_success_part")
            else:
                panel_ban_message_part = _("admin_panel_ban_fail_part")

        await session.commit()
        await message.answer(_("admin_user_banned_success_combined",
                               user_id_or_username=user_display_for_msg,
                               panel_status_part=panel_ban_message_part),
                             reply_markup=get_back_to_admin_panel_keyboard(
                                 current_lang, i18n))
    else:
        await session.rollback()
        await message.answer(_("admin_user_ban_failed_local_db_error"))

    await state.clear()


async def unban_user_prompt_handler(callback: types.CallbackQuery,
                                    state: FSMContext, i18n_data: dict,
                                    settings: Settings, session: AsyncSession):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n or not callback.message:
        await callback.answer("Error processing unban prompt.",
                              show_alert=True)
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    prompt_text = _("admin_unban_user_prompt")
    try:
        await callback.message.edit_text(
            prompt_text,
            reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n))
    except Exception as e:
        logging.warning(
            f"Edit failed for unban_user_prompt: {e}. Sending new message.")
        await callback.message.answer(
            prompt_text,
            reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n))

    await callback.answer()
    await state.set_state(AdminStates.waiting_for_user_id_to_unban)


@router.message(AdminStates.waiting_for_user_id_to_unban, F.text)
async def process_user_input_to_unban_handler(message: types.Message,
                                              state: FSMContext,
                                              i18n_data: dict,
                                              settings: Settings,
                                              panel_service: PanelApiService,
                                              session: AsyncSession):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n:
        await message.reply("Language service error.")
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    input_text = message.text.strip() if message.text else ""
    user_to_unban_model = await _get_user_model_by_input(session, input_text)

    if not user_to_unban_model:
        await message.answer(
            _("admin_user_not_found_in_bot_db", user_id=input_text))
        await state.clear()
        return

    user_id_to_unban = user_to_unban_model.user_id
    user_display_for_msg = user_to_unban_model.username or str(
        user_id_to_unban)

    if not user_to_unban_model.is_banned:
        await message.answer(
            _("admin_user_not_banned",
              user_id_or_username=user_display_for_msg))
        await state.clear()
        return

    unban_success_local = await user_dal.set_user_ban_status(
        session, user_id_to_unban, False)

    if unban_success_local:
        panel_unban_message_part = ""
        if user_to_unban_model.panel_user_uuid:
            panel_unban_api_success = await panel_service.update_user_status_on_panel(
                user_to_unban_model.panel_user_uuid, enable=True)
            if panel_unban_api_success:
                panel_unban_message_part = _("admin_panel_unban_success_part")
            else:
                panel_unban_message_part = _("admin_panel_unban_fail_part")

        await session.commit()
        await message.answer(_("admin_user_unbanned_success_combined",
                               user_id_or_username=user_display_for_msg,
                               panel_status_part=panel_unban_message_part),
                             reply_markup=get_back_to_admin_panel_keyboard(
                                 current_lang, i18n))
    else:
        await session.rollback()
        await message.answer(_("admin_user_unban_failed_local_db_error"))

    await state.clear()


async def view_banned_users_handler(callback: types.CallbackQuery,
                                    state: FSMContext, i18n_data: dict,
                                    settings: Settings, session: AsyncSession):
    await state.clear()
    current_page_idx = 0
    if ":" in callback.data and callback.data.count(":") == 2:
        try:
            current_page_idx = int(callback.data.split(":")[-1])
        except ValueError:
            current_page_idx = 0

    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n or not callback.message:
        await callback.answer("Error displaying banned users.",
                              show_alert=True)
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    page_size = settings.LOGS_PAGE_SIZE
    offset = current_page_idx * page_size

    banned_user_models, total_banned_count = await user_dal.get_banned_users_paginated(
        session, limit=page_size, offset=offset)

    if total_banned_count == 0:
        await callback.message.edit_text(
            _("admin_no_banned_users"),
            reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n))
    else:
        total_pages = math.ceil(total_banned_count /
                                page_size) if page_size > 0 else 1
        await callback.message.edit_text(
            text=_("admin_banned_list_title",
                   current_page=current_page_idx + 1,
                   total_pages=max(1, total_pages)),
            reply_markup=get_banned_users_keyboard(banned_user_models,
                                                   current_page_idx,
                                                   total_banned_count, i18n,
                                                   current_lang, settings))
    await callback.answer()


async def _show_user_card_actual(target_message: types.Message,
                                 user_id_to_show: int,
                                 banned_list_page_to_return: int,
                                 i18n_data: dict, settings: Settings,
                                 panel_service: PanelApiService,
                                 session: AsyncSession):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n: return

    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    user_model = await user_dal.get_user_by_id(session, user_id_to_show)
    if not user_model:
        await target_message.edit_text(
            _("admin_user_not_found_in_bot_db", user_id=user_id_to_show),
            reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n))
        return

    user_display_name = user_model.first_name or (f"@{user_model.username}"
                                                  if user_model.username else
                                                  f"ID: {user_id_to_show}")

    sub_end_date_str = await subscription_dal.get_user_active_subscription_end_date_str(
        session, user_id_to_show) or _("user_card_sub_na")

    reg_date_display = user_model.registration_date.strftime(
        '%Y-%m-%d %H:%M') if user_model.registration_date else "N/A"

    card_text = _("user_card_info",
                  user_id=user_model.user_id,
                  username=user_model.username or "N/A",
                  first_name=user_model.first_name or "",
                  last_name=user_model.last_name or "",
                  language_code=user_model.language_code or "N/A",
                  panel_user_uuid=user_model.panel_user_uuid or "N/A",
                  ban_status=_("user_card_banned")
                  if user_model.is_banned else _("user_card_active"),
                  reg_date=reg_date_display,
                  sub_end_date=sub_end_date_str)
    await target_message.edit_text(
        text=
        f"{_('admin_user_card_title', user_display=user_display_name)}\n\n{card_text}",
        reply_markup=get_user_card_keyboard(user_id_to_show,
                                            bool(user_model.is_banned), i18n,
                                            current_lang,
                                            banned_list_page_to_return),
        parse_mode="HTML")


@router.callback_query(F.data.startswith("admin_user_card:"))
async def show_user_card_handler(callback: types.CallbackQuery,
                                 state: FSMContext,
                                 i18n_data: dict,
                                 settings: Settings,
                                 panel_service: PanelApiService,
                                 session: AsyncSession,
                                 force_user_id: Optional[int] = None,
                                 force_page: Optional[int] = None):
    await state.clear()

    user_id_to_show = 0
    banned_list_page_to_return = 0

    if force_user_id is not None and force_page is not None:
        user_id_to_show = force_user_id
        banned_list_page_to_return = force_page
    else:
        try:
            parts = callback.data.split(":")
            user_id_to_show = int(parts[1])
            banned_list_page_to_return = int(parts[2]) if len(parts) > 2 else 0
        except (IndexError, ValueError):
            await callback.answer("Invalid user card data.", show_alert=True)
            return

    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n or not callback.message:
        await callback.answer("Error displaying user card.", show_alert=True)
        return

    await _show_user_card_actual(
        target_message=callback.message,
        user_id_to_show=user_id_to_show,
        banned_list_page_to_return=banned_list_page_to_return,
        i18n_data=i18n_data,
        settings=settings,
        panel_service=panel_service,
        session=session)
    if force_user_id is None:
        await callback.answer()


async def _confirm_action_handler(callback: types.CallbackQuery,
                                  i18n_data: dict, settings: Settings,
                                  session: AsyncSession, action_type: str):
    try:

        _, user_id_str, page_str = callback.data.split(":")
        user_id = int(user_id_str)
        banned_list_page = int(page_str)
    except (ValueError, IndexError):
        await callback.answer("Invalid confirmation data.", show_alert=True)
        return

    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n or not callback.message:
        await callback.answer("Error processing confirmation.",
                              show_alert=True)
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    user_model = await user_dal.get_user_by_id(session, user_id)
    user_display = (user_model.first_name or
                    (f"@{user_model.username}" if user_model.username else
                     f"ID {user_id}")) if user_model else f"ID {user_id}"

    prompt_key = f"admin_confirm_{action_type}_prompt"
    yes_callback = f"admin_{action_type}_do:{user_id}:{banned_list_page}"
    no_callback = f"admin_user_card:{user_id}:{banned_list_page}"

    await callback.message.edit_text(
        text=_("admin_confirm_action_title",
               action_text=_(f"{action_type}_verb_l")) + "\n\n" +
        _(prompt_key, user_display=user_display, user_id=user_id),
        reply_markup=get_confirmation_keyboard(yes_callback_data=yes_callback,
                                               no_callback_data=no_callback,
                                               i18n_instance=i18n,
                                               lang=current_lang),
        parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("admin_ban_confirm:"))
async def confirm_ban_handler(callback: types.CallbackQuery, i18n_data: dict,
                              settings: Settings, session: AsyncSession):
    await _confirm_action_handler(callback, i18n_data, settings, session,
                                  "ban")


@router.callback_query(F.data.startswith("admin_unban_confirm:"))
async def confirm_unban_handler(callback: types.CallbackQuery, i18n_data: dict,
                                settings: Settings, session: AsyncSession):
    await _confirm_action_handler(callback, i18n_data, settings, session,
                                  "unban")


async def _do_ban_unban_action_handler(callback: types.CallbackQuery,
                                       i18n_data: dict, settings: Settings,
                                       panel_service: PanelApiService,
                                       session: AsyncSession,
                                       state: FSMContext, action_type: str):
    try:

        _, user_id_str, page_str = callback.data.split(":")
        user_id_target = int(user_id_str)
        banned_list_page = int(page_str)
    except (ValueError, IndexError):
        await callback.answer("Invalid action data.", show_alert=True)
        return

    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n or not callback.message:
        await callback.answer("Error processing action.", show_alert=True)
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    user_model = await user_dal.get_user_by_id(session, user_id_target)
    if not user_model:
        await callback.answer(_("admin_user_not_found_in_bot_db",
                                user_id=user_id_target),
                              show_alert=True)
        return

    user_display_name = user_model.first_name or (f"@{user_model.username}"
                                                  if user_model.username else
                                                  f"ID {user_id_target}")

    is_banning = action_type == "ban"

    if is_banning:
        if user_model.is_banned:
            await callback.answer(_("admin_user_already_banned",
                                    user_id_or_username=user_display_name),
                                  show_alert=True)
            return
        if user_id_target == callback.from_user.id or user_id_target in settings.ADMIN_IDS:
            await callback.answer(_("admin_cannot_ban_self_or_admin"),
                                  show_alert=True)
            return
    else:
        if not user_model.is_banned:
            await callback.answer(_("admin_user_not_banned",
                                    user_id_or_username=user_display_name),
                                  show_alert=True)
            return

    action_success_local = await user_dal.set_user_ban_status(
        session, user_id_target, is_banning)

    if action_success_local:
        panel_action_message = ""
        if user_model.panel_user_uuid:
            panel_api_success = await panel_service.update_user_status_on_panel(
                user_model.panel_user_uuid, enable=not is_banning)
            if not panel_api_success:
                panel_action_message = _("admin_panel_status_update_fail_part")
                logging.warning(
                    f"Panel status update failed for {action_type} of user {user_id_target} (panel: {user_model.panel_user_uuid})"
                )

        await session.commit()
        alert_message_key = f"admin_user_{action_type}ned_from_card_alert"
        await callback.answer(_(alert_message_key,
                                user_display=user_display_name,
                                user_id=user_id_target) + " " +
                              panel_action_message,
                              show_alert=False)
    else:
        await session.rollback()
        await callback.answer(_(f"admin_user_{action_type}_failed_db_error"),
                              show_alert=True)
        return

    await show_user_card_handler(callback,
                                 state,
                                 i18n_data,
                                 settings,
                                 panel_service,
                                 session,
                                 force_user_id=user_id_target,
                                 force_page=banned_list_page)


@router.callback_query(F.data.startswith("admin_ban_do:"))
async def do_ban_user_handler(callback: types.CallbackQuery, i18n_data: dict,
                              settings: Settings,
                              panel_service: PanelApiService,
                              session: AsyncSession, state: FSMContext):
    await _do_ban_unban_action_handler(callback, i18n_data, settings,
                                       panel_service, session, state, "ban")


@router.callback_query(F.data.startswith("admin_unban_do:"))
async def do_unban_user_handler(callback: types.CallbackQuery, i18n_data: dict,
                                settings: Settings,
                                panel_service: PanelApiService,
                                session: AsyncSession, state: FSMContext):
    await _do_ban_unban_action_handler(callback, i18n_data, settings,
                                       panel_service, session, state, "unban")


@router.callback_query(F.data == "admin_action:main",
                       AdminStates.waiting_for_user_id_to_ban)
@router.callback_query(F.data == "admin_action:main",
                       AdminStates.waiting_for_user_id_to_unban)
async def cancel_user_management_input_state(
    callback: types.CallbackQuery,
    state: FSMContext,
    settings: Settings,
    i18n_data: dict,
    bot: Bot,
):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n or not callback.message:
        await callback.answer("Error cancelling.", show_alert=True)
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    try:
        await callback.message.edit_text(_("admin_action_cancelled_default"),
                                         reply_markup=get_admin_panel_keyboard(
                                             i18n, current_lang, settings))
    except Exception:
        await callback.message.answer(_("admin_action_cancelled_default"),
                                      reply_markup=get_admin_panel_keyboard(
                                          i18n, current_lang, settings))
    await callback.answer(_("admin_action_cancelled_default_alert"))
    await state.clear()
