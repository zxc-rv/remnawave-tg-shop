import logging
from aiogram import Router, F, types, Bot
from aiogram.filters import Command
from typing import Optional, Dict, Any, Union
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import Settings
from db.dal import payment_dal
from bot.keyboards.inline.user_keyboards import (
    get_subscription_options_keyboard, get_confirm_subscription_keyboard,
    get_payment_url_keyboard, get_back_to_main_menu_markup)
from bot.services.payment_service import YooKassaService
from bot.services.subscription_service import SubscriptionService
from bot.services.panel_api_service import PanelApiService
from bot.middlewares.i18n import JsonI18n

router = Router(name="user_subscription_router")


async def display_subscription_options(event: Union[types.Message,
                                                    types.CallbackQuery],
                                       i18n_data: dict, settings: Settings,
                                       session: AsyncSession):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")

    get_text = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs
                                                  ) if i18n else key

    if not i18n:
        err_msg = "Language service error."
        if isinstance(event, types.CallbackQuery):
            await event.answer(err_msg, show_alert=True)
        elif isinstance(event, types.Message):
            await event.answer(err_msg)
        return

    currency_symbol_val = settings.DEFAULT_CURRENCY_SYMBOL
    text_content = get_text("select_subscription_period"
                            ) if settings.subscription_options else get_text(
                                "no_subscription_options_available")

    reply_markup = get_subscription_options_keyboard(
        settings.subscription_options, currency_symbol_val, current_lang, i18n
    ) if settings.subscription_options else get_back_to_main_menu_markup(
        current_lang, i18n)

    target_message_obj = event.message if isinstance(
        event, types.CallbackQuery) else event
    if not target_message_obj:
        if isinstance(event, types.CallbackQuery):
            await event.answer(get_text("error_occurred_try_again"),
                               show_alert=True)
        return

    if isinstance(event, types.CallbackQuery):
        try:
            await target_message_obj.edit_text(text_content,
                                               reply_markup=reply_markup)
        except Exception:
            await target_message_obj.answer(text_content,
                                            reply_markup=reply_markup)
        await event.answer()
    else:
        await target_message_obj.answer(text_content,
                                        reply_markup=reply_markup)


@router.callback_query(F.data.startswith("subscribe_period:"))
async def select_subscription_period_callback_handler(
        callback: types.CallbackQuery, settings: Settings, i18n_data: dict,
        session: AsyncSession):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    get_text = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs
                                                  ) if i18n else key

    if not i18n or not callback.message:
        await callback.answer(get_text("error_occurred_try_again"),
                              show_alert=True)
        return

    try:
        months = int(callback.data.split(":")[-1])
    except (ValueError, IndexError):
        logging.error(
            f"Invalid subscription period in callback_data: {callback.data}")
        await callback.answer(get_text("error_try_again"), show_alert=True)
        return

    price_rub = settings.subscription_options.get(months)
    if price_rub is None:
        logging.error(
            f"Price not found for {months} months subscription period in settings.subscription_options."
        )
        await callback.answer(get_text("error_try_again"), show_alert=True)
        return

    currency_symbol_val = settings.DEFAULT_CURRENCY_SYMBOL
    confirmation_text_content = get_text("confirm_subscription_prompt",
                                         months=months,
                                         price=f"{price_rub:.2f}",
                                         currency_symbol=currency_symbol_val)
    reply_markup = get_confirm_subscription_keyboard(months, price_rub,
                                                     currency_symbol_val,
                                                     current_lang, i18n)

    try:
        await callback.message.edit_text(confirmation_text_content,
                                         reply_markup=reply_markup)
    except Exception as e_edit:
        logging.warning(
            f"Edit message for subscription confirmation failed: {e_edit}. Sending new one."
        )
        await callback.message.answer(confirmation_text_content,
                                      reply_markup=reply_markup)
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_sub:"))
async def confirm_subscription_callback_handler(
        callback: types.CallbackQuery, settings: Settings, i18n_data: dict,
        yookassa_service: YooKassaService, session: AsyncSession):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")

    get_text = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs
                                                  ) if i18n else key

    if not i18n or not callback.message:

        await callback.answer(get_text("error_occurred_try_again"),
                              show_alert=True)
        return

    if not yookassa_service or not yookassa_service.configured:
        logging.error("YooKassa service is not configured or unavailable.")
        target_msg_edit = callback.message
        await target_msg_edit.edit_text(get_text("payment_service_unavailable")
                                        )
        await callback.answer(get_text("payment_service_unavailable_alert"),
                              show_alert=True)
        return

    try:
        _, data_payload = callback.data.split(":", 1)
        months_str, price_str = data_payload.split(":")
        months = int(months_str)
        price_rub = float(price_str)
    except (ValueError, IndexError):
        logging.error(
            f"Invalid confirmation data in callback: {callback.data}")
        await callback.answer(get_text("error_try_again"), show_alert=True)
        return

    user_id = callback.from_user.id

    payment_description = get_text("payment_description_subscription",
                                   months=months)
    currency_code_for_yk = "RUB"

    payment_record_data = {
        "user_id": user_id,
        "amount": price_rub,
        "currency": currency_code_for_yk,
        "status": "pending_yookassa",
        "description": payment_description,
        "subscription_duration_months": months,
    }
    db_payment_record = None
    try:
        db_payment_record = await payment_dal.create_payment_record(
            session, payment_record_data)
        await session.commit()
        logging.info(
            f"Payment record {db_payment_record.payment_id} created for user {user_id} with status 'pending_yookassa'."
        )
    except Exception as e_db_payment:
        await session.rollback()
        logging.error(
            f"Failed to create payment record in DB for user {user_id}: {e_db_payment}",
            exc_info=True)
        await callback.message.edit_text(
            get_text("error_creating_payment_record"))
        await callback.answer(get_text("error_try_again"), show_alert=True)
        return

    if not db_payment_record:
        await callback.message.edit_text(
            get_text("error_creating_payment_record"))
        await callback.answer(get_text("error_try_again"), show_alert=True)
        return

    yookassa_metadata = {
        "user_id": str(user_id),
        "subscription_months": str(months),
        "payment_db_id": str(db_payment_record.payment_id),
    }
    receipt_email_for_yk = settings.YOOKASSA_DEFAULT_RECEIPT_EMAIL

    payment_response_yk = await yookassa_service.create_payment(
        amount=price_rub,
        currency=currency_code_for_yk,
        description=payment_description,
        metadata=yookassa_metadata,
        receipt_email=receipt_email_for_yk)

    if payment_response_yk and payment_response_yk.get("confirmation_url"):
        try:
            await payment_dal.update_payment_status_by_db_id(
                session,
                payment_db_id=db_payment_record.payment_id,
                new_status=payment_response_yk.get("status", "pending"),
                yk_payment_id=payment_response_yk.get("id"))
            await session.commit()
        except Exception as e_db_update_ykid:
            await session.rollback()
            logging.error(
                f"Failed to update payment record {db_payment_record.payment_id} with YK ID: {e_db_update_ykid}",
                exc_info=True)
            await callback.message.edit_text(
                get_text("error_payment_gateway_link_failed"))
            await callback.answer(get_text("error_try_again"), show_alert=True)
            return

        await callback.message.edit_text(
            get_text(key="payment_link_message", months=months),
            reply_markup=get_payment_url_keyboard(
                payment_response_yk["confirmation_url"], current_lang, i18n),
            disable_web_page_preview=False)
    else:
        try:
            await payment_dal.update_payment_status_by_db_id(
                session, db_payment_record.payment_id, "failed_creation")
            await session.commit()
        except Exception as e_db_fail_create:
            await session.rollback()
            logging.error(
                f"Additionally failed to update payment record to 'failed_creation': {e_db_fail_create}",
                exc_info=True)

        logging.error(
            f"Failed to create payment in YooKassa for user {user_id}, payment_db_id {db_payment_record.payment_id}. Response: {payment_response_yk}"
        )
        await callback.message.edit_text(get_text("error_payment_gateway"))

    await callback.answer()


@router.callback_query(F.data == "main_action:subscribe")
async def reshow_subscription_options_callback(callback: types.CallbackQuery,
                                               i18n_data: dict,
                                               settings: Settings,
                                               session: AsyncSession):
    await display_subscription_options(callback, i18n_data, settings, session)


async def my_subscription_command_handler(
        event: Union[types.Message, types.CallbackQuery], i18n_data: dict,
        settings: Settings, panel_service: PanelApiService,
        subscription_service: SubscriptionService, session: AsyncSession,
        bot: Bot):
    target_message_obj = event.message if isinstance(
        event, types.CallbackQuery) else event
    user = event.from_user

    if isinstance(event, types.CallbackQuery):
        await event.answer()

    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    get_text = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs
                                                  ) if i18n else key

    if not i18n or not target_message_obj:
        if isinstance(event, types.Message):
            await event.answer(get_text("error_occurred_try_again"))
        return

    if not panel_service or not subscription_service:
        logging.error(
            "PanelService or SubscriptionService is missing in my_subscription_command_handler."
        )
        await target_message_obj.answer(get_text("error_service_unavailable"))
        return

    active_sub_details = await subscription_service.get_active_subscription_details(
        session, user.id)

    sub_info_text_content = ""
    if active_sub_details:
        end_date_obj = active_sub_details.get('end_date')
        days_left = 0
        if end_date_obj:
            if end_date_obj.tzinfo is None:
                end_date_obj = end_date_obj.replace(tzinfo=timezone.utc)
            days_left = (end_date_obj.date() - datetime.now().date()).days

        actual_config_link = active_sub_details.get('config_link') or get_text(
            "config_link_not_available")

        traffic_limit_bytes = active_sub_details.get('traffic_limit_bytes')
        traffic_used_bytes = active_sub_details.get('traffic_used_bytes')

        traffic_limit_gb_str = get_text("traffic_unlimited")
        if traffic_limit_bytes and traffic_limit_bytes > 0:
            traffic_limit_gb_str = f"{traffic_limit_bytes / (1024**3):.2f} GB"

        traffic_used_gb_str = get_text("traffic_na")
        if traffic_used_bytes is not None:
            traffic_used_gb_str = f"{traffic_used_bytes / (1024**3):.2f} GB"

        sub_info_text_content = get_text(
            "my_subscription_details",
            end_date=end_date_obj.strftime("%Y-%m-%d")
            if end_date_obj else "N/A",
            days_left=max(0, days_left),
            status=active_sub_details.get(
                'status_from_panel', get_text('status_active')).capitalize(),
            config_link=actual_config_link,
            traffic_limit=traffic_limit_gb_str,
            traffic_used=traffic_used_gb_str)
    else:
        sub_info_text_content = get_text("subscription_not_active")
        logging.info(
            f"User {user.id} no active sub details for 'my_subscription'.")

    reply_markup_val = get_back_to_main_menu_markup(current_lang, i18n)

    if isinstance(event, types.CallbackQuery) and event.message:
        try:
            await event.message.edit_text(sub_info_text_content,
                                          reply_markup=reply_markup_val,
                                          parse_mode="HTML",
                                          disable_web_page_preview=True)
        except Exception as e_edit:
            logging.warning(
                f"Edit 'my_subscription' failed: {e_edit}. Sending new message to chat {target_message_obj.chat.id}."
            )
            await bot.send_message(chat_id=target_message_obj.chat.id,
                                   text=sub_info_text_content,
                                   reply_markup=reply_markup_val,
                                   parse_mode="HTML",
                                   disable_web_page_preview=True)
    else:
        await target_message_obj.answer(sub_info_text_content,
                                        reply_markup=reply_markup_val,
                                        parse_mode="HTML",
                                        disable_web_page_preview=True)


@router.message(Command("connect"))
async def connect_command_handler(message: types.Message, i18n_data: dict,
                                  settings: Settings,
                                  panel_service: PanelApiService,
                                  subscription_service: SubscriptionService,
                                  session: AsyncSession, bot: Bot):
    logging.info(f"User {message.from_user.id} used /connect command.")
    await my_subscription_command_handler(message, i18n_data, settings,
                                          panel_service, subscription_service,
                                          session, bot)
