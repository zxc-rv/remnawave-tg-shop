import logging
from aiogram import Router, F, types
from typing import Optional, Dict, List
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import Settings

from db.dal import user_dal, payment_dal, panel_sync_dal
from db.models import Payment, PanelSyncStatus

from bot.keyboards.inline.admin_keyboards import get_back_to_admin_panel_keyboard
from bot.middlewares.i18n import JsonI18n

router = Router(name="admin_statistics_router")


async def show_statistics_handler(callback: types.CallbackQuery,
                                  i18n_data: dict, settings: Settings,
                                  session: AsyncSession):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    if not i18n or not callback.message:
        await callback.answer("Error displaying statistics.", show_alert=True)
        return
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    await callback.answer()

    stats_text_parts = [f"<b>{_('admin_stats_header')}</b>"]

    user_stats_dict = await user_dal.get_user_count_stats_dal(session)
    stats_text_parts.append(
        _("admin_stats_users",
          total_users=user_stats_dict.get("total_users", 0),
          banned_users=user_stats_dict.get("banned_users", 0),
          active_subs=user_stats_dict.get("users_with_active_subscriptions",
                                          0)))

    last_payments_models: List[
        Payment] = await payment_dal.get_recent_payment_logs_with_user(session,
                                                                       limit=5)
    if last_payments_models:
        stats_text_parts.append(
            f"\n<b>{_('admin_stats_recent_payments_header')}</b>")
        for payment in last_payments_models:
            status_emoji = "✅" if payment.status == 'succeeded' else (
                "⏳" if payment.status == 'pending'
                or payment.status == 'pending_yookassa' else "❌")

            user_info = f"User {payment.user_id}"
            if payment.user and payment.user.username:
                user_info += f" (@{payment.user.username})"
            elif payment.user and payment.user.first_name:
                user_info += f" ({payment.user.first_name})"

            payment_date_str = payment.created_at.strftime(
                '%Y-%m-%d') if payment.created_at else "N/A"

            stats_text_parts.append(
                _("admin_stats_payment_item",
                  status_emoji=status_emoji,
                  amount=payment.amount,
                  currency=payment.currency,
                  user_info=user_info,
                  p_status=payment.status,
                  p_date=payment_date_str))
    else:
        stats_text_parts.append(f"\n{_('admin_stats_no_payments_found')}")

    sync_status_model: Optional[
        PanelSyncStatus] = await panel_sync_dal.get_panel_sync_status(session)
    if sync_status_model and sync_status_model.status != "never_run":
        stats_text_parts.append(
            f"\n<b>{_('admin_stats_last_sync_header')}</b>")

        sync_time_val = sync_status_model.last_sync_time
        sync_time_str = sync_time_val.strftime(
            '%Y-%m-%d %H:%M:%S UTC') if sync_time_val else "N/A"

        details_val = sync_status_model.details
        details_str = (details_val[:100] +
                       "...") if details_val and len(details_val) > 100 else (
                           details_val or "N/A")

        stats_text_parts.append(
            f"  {_('admin_stats_sync_time')}: {sync_time_str}")
        stats_text_parts.append(
            f"  {_('admin_stats_sync_status')}: {sync_status_model.status}")
        stats_text_parts.append(
            f"  {_('admin_stats_sync_users_processed')}: {sync_status_model.users_processed_from_panel}"
        )
        stats_text_parts.append(
            f"  {_('admin_stats_sync_subs_synced')}: {sync_status_model.subscriptions_synced}"
        )
        stats_text_parts.append(
            f"  {_('admin_stats_sync_details_label')}: {details_str}")
    else:
        stats_text_parts.append(f"\n{_('admin_sync_status_never_run')}")

    final_text = "\n".join(stats_text_parts)

    try:
        await callback.message.edit_text(
            final_text,
            reply_markup=get_back_to_admin_panel_keyboard(current_lang, i18n),
            parse_mode="HTML")
    except Exception as e_edit:
        logging.error(f"Error editing message for statistics: {e_edit}",
                      exc_info=True)

        max_chunk_size = 4000
        for i in range(0, len(final_text), max_chunk_size):
            chunk = final_text[i:i + max_chunk_size]
            is_last_chunk = (i + max_chunk_size) >= len(final_text)
            try:
                await callback.message.answer(
                    chunk,
                    reply_markup=get_back_to_admin_panel_keyboard(
                        current_lang, i18n) if is_last_chunk else None,
                    parse_mode="HTML")
            except Exception as e_chunk:
                logging.error(f"Failed to send statistics chunk: {e_chunk}")
                if i == 0:
                    await callback.message.answer(
                        _("error_displaying_statistics"),
                        reply_markup=get_back_to_admin_panel_keyboard(
                            current_lang, i18n))
                break
