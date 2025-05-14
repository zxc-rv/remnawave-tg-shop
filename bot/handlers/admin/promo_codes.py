import logging
from aiogram import Router, F, types, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from datetime import datetime, timedelta, timezone
from typing import Optional

from config.settings import Settings
from db.database import create_promo_code_db, get_promo_codes_db
from bot.states.admin_states import AdminStates
from bot.keyboards.inline.admin_keyboards import get_back_to_admin_panel_keyboard
from bot.middlewares.i18n import JsonI18n

router = Router(name="admin_promo_codes_router")


async def create_promo_prompt_handler(callback: types.CallbackQuery,
                                      state: FSMContext, i18n_data: dict,
                                      settings: Settings):
    current_lang = i18n_data.get("current_language",
                                 getattr(settings, 'DEFAULT_LANGUAGE', 'en'))
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n:
        logging.error("i18n missing in create_promo_prompt_handler")
        await callback.answer("Language service error.", show_alert=True)
        return

    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    prompt_text = _("admin_promo_create_prompt",
                    example_format="MYPROMO20 7 100 30")

    if callback.message:
        try:
            await callback.message.edit_text(
                prompt_text,
                reply_markup=get_back_to_admin_panel_keyboard(
                    current_lang, i18n))
        except Exception as e:
            logging.warning(f"Could not edit message for promo prompt: {e}")
            await callback.message.answer(
                prompt_text,
                reply_markup=get_back_to_admin_panel_keyboard(
                    current_lang, i18n))
    await callback.answer()
    await state.set_state(AdminStates.waiting_for_promo_details)


@router.message(AdminStates.waiting_for_promo_details, F.text)
async def process_promo_code_details_handler(message: types.Message,
                                             state: FSMContext,
                                             i18n_data: dict,
                                             settings: Settings):
    current_lang = i18n_data.get("current_language",
                                 getattr(settings, 'DEFAULT_LANGUAGE', 'en'))
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n:
        logging.error("i18n missing in process_promo_code_details_handler")
        await message.reply("Language service error.")
        return

    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    parts = message.text.strip().split()
    if not (3 <= len(parts) <= 4):
        await message.answer(_("admin_promo_invalid_format"))
        return

    try:
        code = parts[0].upper()
        if not (3 <= len(code) <= 30 and code.isalnum()):
            raise ValueError(
                "Promo code must be 3-30 alphanumeric characters.")
        bonus_days = int(parts[1])
        max_activations = int(parts[2])
        valid_until_date: Optional[datetime] = None
        valid_until_str_display = _("admin_promo_valid_indefinitely")

        if len(parts) == 4:
            valid_days_from_now = int(parts[3])
            if valid_days_from_now <= 0:
                raise ValueError(
                    "Validity days (if provided) must be positive.")

            valid_until_date = datetime.now(
                timezone.utc) + timedelta(days=valid_days_from_now)
            valid_until_str_display = _(
                "admin_promo_valid_until_display",
                date=valid_until_date.strftime('%Y-%m-%d'))
        if bonus_days <= 0 or max_activations <= 0:
            raise ValueError(
                "Bonus days and max activations must be positive.")
    except ValueError as e:
        await message.answer(_("admin_promo_invalid_values", error=str(e)))
        return

    admin_id = message.from_user.id

    promo_id = await create_promo_code_db(code, bonus_days, max_activations,
                                          admin_id, valid_until_date)

    if promo_id:
        success_text = _("admin_promo_created_success",
                         code=code,
                         bonus_days=bonus_days,
                         max_activations=max_activations,
                         valid_until_str=valid_until_str_display)
        await message.answer(success_text,
                             reply_markup=get_back_to_admin_panel_keyboard(
                                 current_lang, i18n))
    else:
        await message.answer(_("admin_promo_creation_failed"))
    await state.clear()


async def view_promo_codes_handler(callback: types.CallbackQuery,
                                   i18n_data: dict, settings: Settings):
    current_lang = i18n_data.get("current_language",
                                 getattr(settings, 'DEFAULT_LANGUAGE', 'en'))
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n:
        logging.error("i18n missing in view_promo_codes_handler")
        await callback.answer("Language error.", show_alert=True)
        return

    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)
    promos = await get_promo_codes_db(is_active_only=True, limit=20)

    if not callback.message:
        await callback.answer("Error: message context lost.", show_alert=True)
        return

    if not promos:
        await callback.message.edit_text(
            _("admin_no_active_promos"),
            reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n))
        await callback.answer()
        return

    response_text_parts = [f"<b>{_('admin_active_promos_list_header')}</b>\n"]
    for promo in promos:
        valid_until_display_text = _("admin_promo_valid_indefinitely")
        if promo['valid_until']:
            try:

                valid_until_dt: Optional[datetime] = None
                if 'T' in promo['valid_until']:
                    valid_until_dt = datetime.fromisoformat(
                        promo['valid_until'].replace("Z", "+00:00"))
                else:
                    valid_until_dt = datetime.strptime(promo['valid_until'],
                                                       '%Y-%m-%d %H:%M:%S')

                if valid_until_dt and valid_until_dt.tzinfo is None:
                    valid_until_dt = valid_until_dt.replace(
                        tzinfo=timezone.utc)

                valid_until_display_text = valid_until_dt.strftime('%Y-%m-%d')
            except ValueError as e:
                logging.warning(
                    f"Could not parse valid_until date string '{promo['valid_until']}' for promo code {promo['code']}: {e}"
                )
                valid_until_display_text = promo['valid_until']

        response_text_parts.append(
            _("admin_promo_list_item",
              code=promo['code'],
              bonus=promo['bonus_days'],
              current=promo['current_activations'],
              max=promo['max_activations'],
              valid_until=valid_until_display_text))

    final_text = "\n".join(response_text_parts)
    try:
        await callback.message.edit_text(
            final_text,
            reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n),
            parse_mode="HTML")
    except Exception as e:
        logging.warning(f"Failed to edit message for promo list: {e}")
        if callback.message:
            await callback.message.answer(
                final_text,
                reply_markup=get_back_to_admin_panel_keyboard(
                    current_lang, i18n),
                parse_mode="HTML")
    await callback.answer()
