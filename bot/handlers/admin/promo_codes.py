import logging
from aiogram import Router, F, types, Bot
from aiogram.fsm.context import FSMContext
from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import Settings

from db.dal import promo_code_dal

from bot.states.admin_states import AdminStates
from bot.keyboards.inline.admin_keyboards import get_back_to_admin_panel_keyboard, get_admin_panel_keyboard
from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardButton
from bot.middlewares.i18n import JsonI18n

router = Router(name="admin_promo_codes_router")


async def create_promo_prompt_handler(callback: types.CallbackQuery,
                                      state: FSMContext, i18n_data: dict,
                                      settings: Settings,
                                      session: AsyncSession):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n or not callback.message:
        await callback.answer("Error preparing promo creation.",
                              show_alert=True)
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    prompt_text = _("admin_promo_create_prompt",
                    example_format="MYPROMO20 7 100 30")

    try:
        await callback.message.edit_text(
            prompt_text,
            reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n))
    except Exception as e:
        logging.warning(
            f"Could not edit message for promo prompt: {e}. Sending new.")
        await callback.message.answer(
            prompt_text,
            reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n))
    await callback.answer()
    await state.set_state(AdminStates.waiting_for_promo_details)


@router.message(AdminStates.waiting_for_promo_details, F.text)
async def process_promo_code_details_handler(message: types.Message,
                                             state: FSMContext,
                                             i18n_data: dict,
                                             settings: Settings,
                                             session: AsyncSession):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n:
        await message.reply("Language service error.")
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    if not message.text:
        await message.answer(_("admin_promo_invalid_format"))
        return

    parts = message.text.strip().split()
    if not (3 <= len(parts) <= 4):
        await message.answer(_("admin_promo_invalid_format"))
        return

    try:
        code_str = parts[0].upper()
        if not (3 <= len(code_str) <= 30 and code_str.isalnum()):
            raise ValueError(_("admin_promo_invalid_code_format"))

        bonus_days = int(parts[1])
        max_activations = int(parts[2])

        valid_until_date: Optional[datetime] = None
        valid_until_str_display = _("admin_promo_valid_indefinitely")

        if len(parts) == 4:
            valid_days_from_now = int(parts[3])
            if valid_days_from_now <= 0:
                raise ValueError(_("admin_promo_invalid_validity_days"))
            valid_until_date = datetime.now(
                timezone.utc) + timedelta(days=valid_days_from_now)
            valid_until_str_display = _(
                "admin_promo_valid_until_display",
                date=valid_until_date.strftime('%Y-%m-%d'))

        if bonus_days <= 0 or max_activations <= 0:
            raise ValueError(_("admin_promo_invalid_bonus_or_activations"))

    except ValueError as e:
        await message.answer(_("admin_promo_invalid_values", error=str(e)))
        return
    except Exception as e_parse:
        logging.error(
            f"Error parsing promo details '{message.text}': {e_parse}")
        await message.answer(_("admin_promo_invalid_format_general"))
        return

    admin_id = message.from_user.id if message.from_user else 0

    promo_data_to_create = {
        "code": code_str,
        "bonus_days": bonus_days,
        "max_activations": max_activations,
        "created_by_admin_id": admin_id,
        "valid_until": valid_until_date,
        "is_active": True,
        "current_activations": 0
    }

    try:
        created_promo = await promo_code_dal.create_promo_code(
            session, promo_data_to_create)
        await session.commit()

        if created_promo:
            success_text = _("admin_promo_created_success",
                             code=created_promo.code,
                             bonus_days=created_promo.bonus_days,
                             max_activations=created_promo.max_activations,
                             valid_until_str=valid_until_str_display)
            await message.answer(success_text,
                                 reply_markup=get_back_to_admin_panel_keyboard(
                                     current_lang, i18n))
        else:
            await message.answer(
                _("admin_promo_creation_failed_duplicate", code=code_str))

    except Exception as e_db_create:
        await session.rollback()
        logging.error(
            f"Failed to create promo code '{code_str}' in DB: {e_db_create}",
            exc_info=True)
        await message.answer(_("admin_promo_creation_failed"))

    await state.clear()


async def view_promo_codes_handler(callback: types.CallbackQuery,
                                   i18n_data: dict, settings: Settings,
                                   session: AsyncSession):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n or not callback.message:
        await callback.answer("Error displaying promo codes.", show_alert=True)
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    promo_models = await promo_code_dal.get_all_active_promo_codes(session,
                                                                   limit=20,
                                                                   offset=0)

    if not promo_models:
        await callback.message.edit_text(
            _("admin_no_active_promos"),
            reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n))
        await callback.answer()
        return

    response_text_parts = [f"<b>{_('admin_active_promos_list_header')}</b>\n"]
    for promo in promo_models:
        valid_until_display_text = _("admin_promo_valid_indefinitely")
        if promo.valid_until:

            valid_until_display_text = promo.valid_until.strftime('%Y-%m-%d')

        response_text_parts.append(
            _("admin_promo_list_item",
              code=promo.code,
              bonus=promo.bonus_days,
              current=promo.current_activations,
              max=promo.max_activations,
              valid_until=valid_until_display_text))

    final_text = "\n".join(response_text_parts)
    try:
        await callback.message.edit_text(
            final_text,
            reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n),
            parse_mode="HTML")
    except Exception as e:
        logging.warning(
            f"Failed to edit message for promo list: {e}. Sending new.")
        if callback.message:
            await callback.message.answer(
                final_text,
                reply_markup=get_back_to_admin_panel_keyboard(
                    current_lang, i18n),
                parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin_action:manage_promos")
async def manage_promo_codes_handler(callback: types.CallbackQuery,
                                     i18n_data: dict, settings: Settings,
                                     session: AsyncSession):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n or not callback.message:
        await callback.answer("Error displaying promo codes.", show_alert=True)
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    promo_models = await promo_code_dal.get_all_active_promo_codes(session,
                                                                   limit=20,
                                                                   offset=0)
    if not promo_models:
        await callback.message.edit_text(
            _("admin_no_active_promos"),
            reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n))
        await callback.answer()
        return

    kb = InlineKeyboardBuilder()
    for promo in promo_models:
        kb.row(
            InlineKeyboardButton(
                text=promo.code,
                callback_data=f"promo_edit:{promo.promo_code_id}"),
            InlineKeyboardButton(
                text=_("admin_promo_delete_button"),
                callback_data=f"promo_delete:{promo.promo_code_id}"),
        )
    kb.row(
        InlineKeyboardButton(text=_("back_to_admin_panel_button"),
                             callback_data="admin_action:main"))

    await callback.message.edit_text(
        _("admin_manage_promos_title"),
        reply_markup=kb.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("promo_edit:"))
async def promo_edit_select_handler(callback: types.CallbackQuery, state: FSMContext,
                                    i18n_data: dict, settings: Settings,
                                    session: AsyncSession):
    promo_id = int(callback.data.split(":")[1])
    promo = await promo_code_dal.get_promo_code_by_id(session, promo_id)
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n or not promo or not callback.message:
        await callback.answer("Error", show_alert=True)
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    await state.update_data(edit_promo_id=promo_id)
    await state.set_state(AdminStates.waiting_for_promo_edit_details)
    await callback.message.edit_text(
        _("admin_promo_edit_prompt", code=promo.code),
        reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n),
        parse_mode="HTML")
    await callback.answer()


@router.message(AdminStates.waiting_for_promo_edit_details, F.text)
async def process_promo_edit_details(message: types.Message, state: FSMContext,
                                     i18n_data: dict, settings: Settings,
                                     session: AsyncSession):
    data = await state.get_data()
    promo_id = data.get("edit_promo_id")
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n or not promo_id:
        await message.answer("Error")
        await state.clear()
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    parts = message.text.strip().split()
    if not (3 <= len(parts) <= 4):
        await message.answer(_("admin_promo_invalid_format"))
        return
    try:
        code_str = parts[0].upper()
        bonus = int(parts[1])
        max_act = int(parts[2])
        valid_until = None
        if len(parts) == 4:
            days = int(parts[3])
            valid_until = datetime.now(timezone.utc) + timedelta(days=days)
    except Exception:
        await message.answer(_("admin_promo_invalid_format_general"))
        return

    update_data = {
        "code": code_str,
        "bonus_days": bonus,
        "max_activations": max_act,
        "valid_until": valid_until,
    }
    updated = await promo_code_dal.update_promo_code(session, promo_id, update_data)
    if updated:
        await session.commit()
        await message.answer(
            _("admin_promo_updated_success", code=code_str),
            reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n),
            parse_mode="HTML",
        )
    else:
        await session.rollback()
        await message.answer(_("admin_promo_not_found"))
    await state.clear()


@router.callback_query(F.data.startswith("promo_delete:"))
async def promo_delete_handler(callback: types.CallbackQuery, i18n_data: dict,
                               settings: Settings, session: AsyncSession):
    promo_id = int(callback.data.split(":")[1])
    promo = await promo_code_dal.delete_promo_code(session, promo_id)
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n or not callback.message:
        await callback.answer("Error", show_alert=True)
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    if promo:
        await session.commit()
        await callback.message.edit_text(
            _("admin_promo_deleted_success", code=promo.code),
            reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n),
            parse_mode="HTML")
    else:
        await session.rollback()
        await callback.message.edit_text(
            _("admin_promo_not_found"),
            reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n))
    await callback.answer()


@router.callback_query(
    F.data == "admin_action:main",
    AdminStates.waiting_for_promo_details | AdminStates.waiting_for_promo_edit_details,
)
async def cancel_promo_creation_state_to_menu(callback: types.CallbackQuery,
                                              state: FSMContext,
                                              settings: Settings,
                                              i18n_data: dict,
                                              session: AsyncSession):
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
