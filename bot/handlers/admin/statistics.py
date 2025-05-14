import logging
from aiogram import Router ,F ,types
from typing import Optional ,Dict
from datetime import datetime

from config .settings import Settings
from db .database import get_user_count_stats ,get_payment_logs ,get_message_logs_db ,get_last_sync_status
from bot .keyboards .inline .admin_keyboards import get_back_to_admin_panel_keyboard
from bot .middlewares .i18n import JsonI18n

router =Router (name ="admin_statistics_router")


async def show_statistics_handler (callback :types .CallbackQuery ,i18n_data :dict ,settings :Settings ):
    current_lang =i18n_data .get ("current_language",getattr (settings ,'DEFAULT_LANGUAGE','en'))
    i18n :Optional [JsonI18n ]=i18n_data .get ("i18n_instance")
    if not i18n :
        logging .error ("i18n missing in show_statistics_handler")
        await callback .answer ("Language service error.",show_alert =True )
        return

    _ =lambda key ,**kwargs :i18n .gettext (current_lang ,key ,**kwargs )

    await callback .answer ()

    stats_text_parts =[f"<b>{_('admin_stats_header')}</b>"]


    user_stats =await get_user_count_stats ()
    stats_text_parts .append (
    _ ("admin_stats_users",
    total_users =user_stats .get ("total_users",0 ),
    banned_users =user_stats .get ("banned_users",0 ),
    active_subs =user_stats .get ("users_with_active_subscriptions",0 )
    )
    )


    last_payments =await get_payment_logs (limit =5 )
    if last_payments :
        stats_text_parts .append (f"\n<b>{_('admin_stats_recent_payments_header')}</b>")
        for payment in last_payments :
            status_emoji ="✅"if payment ['status']=='succeeded'else ("⏳"if payment ['status']=='pending'else "❌")
            user_info =f"User {payment['user_id']}"+(f" (@{payment['username']})"if payment ['username']else "")
            payment_date_str =payment ['created_at']
            if isinstance (payment_date_str ,str )and len (payment_date_str )>10 :
                payment_date_str =payment_date_str [:10 ]

            stats_text_parts .append (
            _ ("admin_stats_payment_item",
            status_emoji =status_emoji ,amount =payment ['amount'],currency =payment ['currency'],
            user_info =user_info ,p_status =payment ['status'],p_date =payment_date_str
            )
            )
    else :
        stats_text_parts .append (f"\n{_('admin_stats_no_payments_found')}")


    sync_status =await get_last_sync_status ()
    if sync_status :
        stats_text_parts .append (f"\n<b>{_('admin_stats_last_sync_header')}</b>")

        sync_time_val =sync_status ['last_sync_time']
        sync_time_str ="N/A"
        if isinstance (sync_time_val ,datetime ):
            sync_time_str =sync_time_val .strftime ('%Y-%m-%d %H:%M:%S UTC')
        elif isinstance (sync_time_val ,str ):
            sync_time_str =sync_time_val [:19 ]if len (sync_time_val )>19 else sync_time_val

        details_val =sync_status ['details']
        details_str =(details_val [:100 ]+"...")if details_val and len (details_val )>100 else (details_val or "N/A")


        stats_text_parts .append (f"  {_('admin_stats_sync_time')}: {sync_time_str}")
        stats_text_parts .append (f"  {_('admin_stats_sync_status')}: {sync_status['status']}")
        stats_text_parts .append (f"  {_('admin_stats_sync_users_processed')}: {sync_status['users_processed_from_panel']}")
        stats_text_parts .append (f"  {_('admin_stats_sync_subs_synced')}: {sync_status['subscriptions_synced']}")
        stats_text_parts .append (f"  {_('admin_stats_sync_details_label')}: {details_str}")
    else :
        stats_text_parts .append (f"\n{_('admin_sync_status_never_run')}")

    final_text ="\n".join (stats_text_parts )

    if callback .message :
        try :
            await callback .message .edit_text (
            final_text ,
            reply_markup =get_back_to_admin_panel_keyboard (current_lang ,i18n ),
            parse_mode ="HTML"
            )
        except Exception as e :
            logging .error (f"Error editing message for statistics: {e}",exc_info =True )

            for chunk in [final_text [i :i +4000 ]for i in range (0 ,len (final_text ),4000 )]:
                 await callback .message .answer (
                 chunk ,
                 reply_markup =get_back_to_admin_panel_keyboard (current_lang ,i18n )if chunk ==final_text [-len (chunk ):]else None ,
                 parse_mode ="HTML"
                 )
    else :
        logging .error ("Cannot send statistics, callback.message is None.")