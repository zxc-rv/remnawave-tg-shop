import logging
from aiogram import Router ,types ,Bot
from aiogram .filters import Command
from typing import Optional

from config .settings import Settings
from bot .services .panel_api_service import PanelApiService

from db .database import update_sync_status ,get_last_sync_status ,sync_panel_user_data
from bot .middlewares .i18n import JsonI18n
from bot .keyboards .inline .admin_keyboards import get_back_to_admin_panel_keyboard

router =Router (name ="admin_sync_router")

@router .message (Command ("sync"))
async def sync_command_handler (
message :types .Message ,
bot :Bot ,
settings :Settings ,
i18n_data :dict ,
panel_service :PanelApiService
):
    current_lang =i18n_data .get ("current_language",getattr (settings ,'DEFAULT_LANGUAGE','en'))
    i18n :Optional [JsonI18n ]=i18n_data .get ("i18n_instance")
    if not i18n :logging .error ("i18n missing");await message .answer ("Language error.");return
    _ =lambda key ,**kwargs :i18n .gettext (current_lang ,key ,**kwargs )

    await message .answer (_ ("sync_started"))
    logging .info ("Admin triggered panel sync.")

    users_processed_count =0
    users_synced_successfully =0
    sync_errors =[]

    try :
        panel_users_data =await panel_service .get_all_panel_users ()

        if panel_users_data is None :
            error_msg ="Failed to fetch users from panel or panel API issue."
            sync_errors .append (error_msg )
            await update_sync_status ("failed",error_msg )
            await message .answer (_ ("sync_failed",details =error_msg ))
            return

        if not panel_users_data :
            status_msg ="No users found in the panel to sync."
            await update_sync_status ("success",status_msg ,0 ,0 )
            await message .answer (_ ("sync_completed",status ="Success",details =status_msg ))
            return

        total_panel_users =len (panel_users_data )
        logging .info (f"Starting sync for {total_panel_users} panel users.")














        for panel_user_dict in panel_users_data :
            users_processed_count +=1
            telegram_id_from_panel =panel_user_dict .get ('telegramId')
            panel_uuid =panel_user_dict .get ('uuid')

            if not telegram_id_from_panel :
                logging .info (f"Panel user {panel_uuid} (username: {panel_user_dict.get('username')}) has no 'telegramId'. Skipping TG ID based sync.")



                continue

            if not panel_uuid :
                logging .warning (f"Panel user (TG ID: {telegram_id_from_panel}) missing 'uuid'. Skipping.")
                sync_errors .append (f"Panel user data for TG ID {telegram_id_from_panel} missing UUID.")
                continue


            if await sync_panel_user_data (panel_user_dict ):
                users_synced_successfully +=1
            else :
                sync_errors .append (f"Sync issue for panel user: {panel_uuid} (TG ID: {telegram_id_from_panel})")

            if users_processed_count %20 ==0 :
                logging .info (f"Sync progress: {users_processed_count}/{total_panel_users} users processed.")

        status_msg =f"Panel users checked: {total_panel_users}. Users/Subscriptions synced via TG ID: {users_synced_successfully}."
        if sync_errors :
            status_msg +=f" Errors encountered: {len(sync_errors)}. See logs for details."
            error_preview ="\n".join (sync_errors [:3 ])
            await update_sync_status ("partial_success",status_msg +" "+error_preview ,total_panel_users ,users_synced_successfully )
            await message .answer (_ ("sync_completed",status ="Partial Success",details =status_msg ))
        else :
            await update_sync_status ("success",status_msg ,total_panel_users ,users_synced_successfully )
            await message .answer (_ ("sync_completed",status ="Success",details =status_msg ))

    except Exception as e :
        logging .error (f"Error during /sync command: {e}",exc_info =True )
        error_detail =f"An unexpected error occurred during sync: {str(e)}"
        await update_sync_status ("failed",error_detail ,users_processed_count ,users_synced_successfully )
        await message .answer (_ ("sync_failed",details =error_detail ))

@router .message (Command ("syncstatus"))
async def sync_status_command_handler (message :types .Message ,i18n_data :dict ,settings :Settings ):

    current_lang =i18n_data .get ("current_language",getattr (settings ,'DEFAULT_LANGUAGE','en'));i18n :Optional [JsonI18n ]=i18n_data .get ("i18n_instance")
    if not i18n :await message .answer ("Language error.");return
    _ =lambda key ,**kwargs :i18n .gettext (current_lang ,key ,**kwargs );status_record =await get_last_sync_status ();response_text =""
    if status_record :
        last_time_val =status_record ['last_sync_time'];last_time_str =last_time_val .strftime ('%Y-%m-%d %H:%M:%S UTC')if isinstance (last_time_val ,datetime )else str (last_time_val )
        if isinstance (last_time_str ,str )and len (last_time_str )>19 :last_time_str =last_time_str [:19 ]
        details_val =status_record ['details'];details_str =(details_val [:200 ]+"...")if details_val and len (details_val )>200 else (details_val or "N/A")
        response_text =(f"<b>{_('admin_stats_last_sync_header')}</b>\n"
        f"  {_('admin_stats_sync_time')}: {last_time_str}\n"
        f"  {_('admin_stats_sync_status')}: {status_record['status']}\n"
        f"  {_('admin_stats_sync_users_processed')}: {status_record['users_processed_from_panel']}\n"
        f"  {_('admin_stats_sync_subs_synced')}: {status_record['subscriptions_synced']}\n"
        f"  {_('admin_stats_sync_details_label')}: {details_str}")
    else :response_text =_ ("admin_sync_status_never_run")
    await message .answer (response_text ,parse_mode ="HTML")