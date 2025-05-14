import logging
import re
from aiogram import Router ,F ,types ,Bot
from aiogram .fsm .context import FSMContext
from typing import Optional ,Tuple ,List ,Any
import math
import aiosqlite
from datetime import datetime

from config .settings import Settings
from db .database import (
get_user ,set_user_ban_status_db ,get_user_by_telegram_username ,
get_banned_users_list_paginated ,get_user_active_subscription_end_date
)
from bot .services .panel_api_service import PanelApiService
from bot .states .admin_states import AdminStates
from bot .keyboards .inline .admin_keyboards import (
get_back_to_admin_panel_keyboard ,get_user_card_keyboard ,
get_banned_users_keyboard ,get_confirmation_keyboard ,get_admin_panel_keyboard
)
from bot .middlewares .i18n import JsonI18n

router =Router (name ="admin_user_management_router")

USERNAME_REGEX =re .compile (r"^[a-zA-Z0-9_]{5,32}$")


async def ban_user_prompt_handler (callback :types .CallbackQuery ,state :FSMContext ,i18n_data :dict ,settings :Settings ):

    current_lang =i18n_data .get ("current_language",getattr (settings ,'DEFAULT_LANGUAGE','en'));i18n :Optional [JsonI18n ]=i18n_data .get ("i18n_instance")
    if not i18n :logging .error ("i18n missing");await callback .answer ("Language error.",show_alert =True );return
    _ =lambda key ,**kwargs :i18n .gettext (current_lang ,key ,**kwargs );prompt_text =_ ("admin_ban_user_prompt")
    if callback .message :
        try :await callback .message .edit_text (prompt_text ,reply_markup =get_back_to_admin_panel_keyboard (current_lang ,i18n ))
        except Exception as e :logging .warning (f"Edit failed: {e}");await callback .message .answer (prompt_text ,reply_markup =get_back_to_admin_panel_keyboard (current_lang ,i18n ))
    await callback .answer ();await state .set_state (AdminStates .waiting_for_user_id_to_ban )


@router .message (AdminStates .waiting_for_user_id_to_ban ,F .text )
async def process_user_input_to_ban_handler (message :types .Message ,state :FSMContext ,i18n_data :dict ,settings :Settings ,panel_service :PanelApiService ):

    current_lang =i18n_data .get ("current_language",getattr (settings ,'DEFAULT_LANGUAGE','en'));i18n :Optional [JsonI18n ]=i18n_data .get ("i18n_instance")
    if not i18n :logging .error ("i18n missing");await message .reply ("Language error.");return
    _ =lambda key ,**kwargs :i18n .gettext (current_lang ,key ,**kwargs );input_text =message .text .strip ();user_to_ban_data :Optional [aiosqlite .Row ]=None ;user_id_or_username_for_msg =input_text
    if input_text .isdigit ():
        try :user_id_to_ban_val =int (input_text );user_to_ban_data =await get_user (user_id_to_ban_val )
        except ValueError :await message .answer (_ ("admin_invalid_user_id_format"));return
    elif input_text .startswith ("@")and USERNAME_REGEX .match (input_text [1 :]):user_to_ban_data =await get_user_by_telegram_username (input_text [1 :])
    elif USERNAME_REGEX .match (input_text ):user_to_ban_data =await get_user_by_telegram_username (input_text )
    else :await message .answer (_ ("admin_invalid_user_id_format")+" "+_ ("admin_invalid_username_format"));return
    if not user_to_ban_data :await message .answer (_ ("admin_user_not_found_in_bot_db",user_id =input_text ));await state .clear ();return
    user_id_to_ban =user_to_ban_data ['user_id'];user_id_or_username_for_msg =f"@{user_to_ban_data['username']}"if user_to_ban_data .get ('username')else str (user_id_to_ban )
    if user_id_to_ban ==message .from_user .id or user_id_to_ban in settings .ADMIN_IDS :await message .answer (_ ("admin_cannot_ban_self_or_admin"));await state .clear ();return
    if user_to_ban_data ['is_banned']:await message .answer (_ ("admin_user_already_banned",user_id_or_username =user_id_or_username_for_msg ));await state .clear ();return
    panel_user_uuid =user_to_ban_data ['panel_user_uuid']if user_to_ban_data and 'panel_user_uuid'in user_to_ban_data .keys ()and user_to_ban_data ['panel_user_uuid']else None
    await set_user_ban_status_db (user_id_to_ban ,is_banned =True )
    reply_markup_val =get_back_to_admin_panel_keyboard (current_lang ,i18n )
    if panel_user_uuid :
        panel_ban_success =await panel_service .update_user_status_on_panel (panel_user_uuid ,enable =False )
        if panel_ban_success :await message .answer (_ ("admin_user_banned_success_panel_too",user_id_or_username =user_id_or_username_for_msg ),reply_markup =reply_markup_val )
        else :await message .answer (_ ("admin_user_banned_local_panel_fail",user_id_or_username =user_id_or_username_for_msg ),reply_markup =reply_markup_val )
    else :await message .answer (_ ("admin_user_banned_local_no_panel_uuid",user_id_or_username =user_id_or_username_for_msg ),reply_markup =reply_markup_val )
    await state .clear ()


async def unban_user_prompt_handler (callback :types .CallbackQuery ,state :FSMContext ,i18n_data :dict ,settings :Settings ):

    current_lang =i18n_data .get ("current_language",getattr (settings ,'DEFAULT_LANGUAGE','en'));i18n :Optional [JsonI18n ]=i18n_data .get ("i18n_instance")
    if not i18n :logging .error ("i18n missing");await callback .answer ("Language error.",show_alert =True );return
    _ =lambda key ,**kwargs :i18n .gettext (current_lang ,key ,**kwargs );prompt_text =_ ("admin_unban_user_prompt")
    if callback .message :
        try :await callback .message .edit_text (prompt_text ,reply_markup =get_back_to_admin_panel_keyboard (current_lang ,i18n ))
        except :await callback .message .answer (prompt_text ,reply_markup =get_back_to_admin_panel_keyboard (current_lang ,i18n ))
    await callback .answer ();await state .set_state (AdminStates .waiting_for_user_id_to_unban )

@router .message (AdminStates .waiting_for_user_id_to_unban ,F .text )
async def process_user_input_to_unban_handler (message :types .Message ,state :FSMContext ,i18n_data :dict ,settings :Settings ,panel_service :PanelApiService ):

    current_lang =i18n_data .get ("current_language",getattr (settings ,'DEFAULT_LANGUAGE','en'));i18n :Optional [JsonI18n ]=i18n_data .get ("i18n_instance")
    if not i18n :logging .error ("i18n missing");await message .reply ("Language error.");return
    _ =lambda key ,**kwargs :i18n .gettext (current_lang ,key ,**kwargs );input_text =message .text .strip ();user_to_unban_data :Optional [aiosqlite .Row ]=None ;user_id_or_username_for_msg =input_text
    if input_text .isdigit ():
        try :user_id_to_unban_val =int (input_text );user_to_unban_data =await get_user (user_id_to_unban_val )
        except ValueError :await message .answer (_ ("admin_invalid_user_id_format"));return
    elif input_text .startswith ("@")and USERNAME_REGEX .match (input_text [1 :]):user_to_unban_data =await get_user_by_telegram_username (input_text [1 :])
    elif USERNAME_REGEX .match (input_text ):user_to_unban_data =await get_user_by_telegram_username (input_text )
    else :await message .answer (_ ("admin_invalid_user_id_format")+" "+_ ("admin_invalid_username_format"));return
    if not user_to_unban_data :await message .answer (_ ("admin_user_not_found_in_bot_db",user_id =input_text ));await state .clear ();return
    user_id_to_unban =user_to_unban_data ['user_id'];user_id_or_username_for_msg =f"@{user_to_unban_data['username']}"if user_to_unban_data .get ('username')else str (user_id_to_unban )
    if not user_to_unban_data ['is_banned']:await message .answer (_ ("admin_user_not_banned",user_id_or_username =user_id_or_username_for_msg ));await state .clear ();return
    panel_user_uuid =user_to_unban_data ['panel_user_uuid']if user_to_unban_data and 'panel_user_uuid'in user_to_unban_data .keys ()and user_to_unban_data ['panel_user_uuid']else None
    await set_user_ban_status_db (user_id_to_unban ,is_banned =False )
    reply_markup_val =get_back_to_admin_panel_keyboard (current_lang ,i18n )
    if panel_user_uuid :
        panel_unban_success =await panel_service .update_user_status_on_panel (panel_user_uuid ,enable =True )
        if panel_unban_success :await message .answer (_ ("admin_user_unbanned_success_panel_too",user_id_or_username =user_id_or_username_for_msg ),reply_markup =reply_markup_val )
        else :await message .answer (_ ("admin_user_unbanned_local_panel_fail",user_id_or_username =user_id_or_username_for_msg ),reply_markup =reply_markup_val )
    else :await message .answer (_ ("admin_user_unbanned_local_no_panel_uuid",user_id_or_username =user_id_or_username_for_msg ),reply_markup =reply_markup_val )
    await state .clear ()


async def view_banned_users_handler (callback :types .CallbackQuery ,i18n_data :dict ,settings :Settings ,state :FSMContext ):
    await state .clear ();current_page =0 ;
    if ":"in callback .data and callback .data .count (":")==2 :
        try :current_page =int (callback .data .split (":")[-1 ])
        except ValueError :current_page =0
    current_lang =i18n_data .get ("current_language",getattr (settings ,'DEFAULT_LANGUAGE','en'));i18n :Optional [JsonI18n ]=i18n_data .get ("i18n_instance")
    if not i18n :await callback .answer ("Language error.",show_alert =True );return
    _ =lambda key ,**kwargs :i18n .gettext (current_lang ,key ,**kwargs )


    banned_users ,total_banned =await get_banned_users_list_paginated (limit =settings .LOGS_PAGE_SIZE ,offset =current_page *settings .LOGS_PAGE_SIZE )

    if not callback .message :await callback .answer ("Error.");return
    if total_banned ==0 :
        await callback .message .edit_text (_ ("admin_no_banned_users"),reply_markup =get_back_to_admin_panel_keyboard (current_lang ,i18n ))
    else :
        total_pages =math .ceil (total_banned /settings .LOGS_PAGE_SIZE )if settings .LOGS_PAGE_SIZE >0 else 1
        await callback .message .edit_text (text =_ ("admin_banned_list_title",current_page =current_page +1 ,total_pages =max (1 ,total_pages )),reply_markup =get_banned_users_keyboard (banned_users ,current_page ,total_banned ,i18n ,current_lang ,settings ))
    await callback .answer ()

@router .callback_query (F .data .startswith ("admin_user_card:"))
async def show_user_card_handler (callback :types .CallbackQuery ,i18n_data :dict ,settings :Settings ,panel_service :PanelApiService ,state :FSMContext ,force_user_id :Optional [int ]=None ,force_page :Optional [int ]=None ):

    await state .clear ();user_id_to_show =0 ;banned_list_page_to_return =0
    if force_user_id is not None and force_page is not None :user_id_to_show =force_user_id ;banned_list_page_to_return =force_page
    else :
        try :parts =callback .data .split (":");user_id_to_show =int (parts [1 ]);banned_list_page_to_return =int (parts [2 ])if len (parts )>2 else 0
        except (IndexError ,ValueError ):await callback .answer ("Invalid user card data.",show_alert =True );return
    current_lang =i18n_data .get ("current_language",getattr (settings ,'DEFAULT_LANGUAGE','en'));i18n :Optional [JsonI18n ]=i18n_data .get ("i18n_instance")
    if not i18n :await callback .answer ("Language error.",show_alert =True );return
    _ =lambda key ,**kwargs :i18n .gettext (current_lang ,key ,**kwargs )
    user_data =await get_user (user_id_to_show )
    if not callback .message :await callback .answer ("Error.");return
    if not user_data :await callback .message .edit_text (_ ("admin_user_not_found_in_bot_db",user_id =user_id_to_show ),reply_markup =get_back_to_admin_panel_keyboard (current_lang ,i18n ));await callback .answer ();return
    user_display_name =user_data ['first_name']or (f"@{user_data['username']}"if user_data .get ('username')else f"ID: {user_id_to_show}")
    sub_end_date_str =await get_user_active_subscription_end_date (user_id_to_show )or _ ("user_card_sub_na")
    reg_date_from_db =user_data ['registration_date_str']if 'registration_date_str'in user_data .keys ()else "N/A"
    reg_date_display =reg_date_from_db [:10 ]if reg_date_from_db and reg_date_from_db !="N/A"else "N/A"
    card_text =_ ("user_card_info",user_id =user_data ['user_id'],username =user_data .get ('username',"N/A"),first_name =user_data .get ('first_name',""),last_name =user_data .get ('last_name',""),language_code =user_data .get ('language_code',"N/A"),panel_user_uuid =user_data .get ('panel_user_uuid',"N/A"),ban_status =_ (key ="user_card_banned")if user_data ['is_banned']else _ (key ="user_card_active"),reg_date =reg_date_display ,sub_end_date =sub_end_date_str )
    await callback .message .edit_text (text =f"{_('admin_user_card_title', user_display=user_display_name)}\n\n{card_text}",reply_markup =get_user_card_keyboard (user_id_to_show ,bool (user_data ['is_banned']),i18n ,current_lang ,banned_list_page_to_return ),parse_mode ="HTML")
    if force_user_id is None :await callback .answer ()

@router .callback_query (F .data .startswith ("admin_unban_confirm:"))
async def confirm_unban_handler (callback :types .CallbackQuery ,i18n_data :dict ,settings :Settings ):

    try :_ ,user_id_str ,page_str =callback .data .split (":");user_id =int (user_id_str );banned_list_page =int (page_str )
    except :await callback .answer ("Invalid data",show_alert =True );return
    current_lang =i18n_data .get ("current_language",getattr (settings ,'DEFAULT_LANGUAGE','en'));i18n :Optional [JsonI18n ]=i18n_data .get ("i18n_instance")
    if not i18n :await callback .answer ("Language error.",show_alert =True );return
    _ =lambda key ,**kwargs :i18n .gettext (current_lang ,key ,**kwargs )
    user_data =await get_user (user_id );user_display =(user_data ['first_name']or (f"@{user_data['username']}"if user_data .get ('username')else f"ID {user_id}"))if user_data else f"ID {user_id}"
    if callback .message :await callback .message .edit_text (text =_ ("admin_confirm_unban_prompt",user_display =user_display ,user_id =user_id ),reply_markup =get_confirmation_keyboard (yes_callback_data =f"admin_unban_do:{user_id}:{banned_list_page}",no_callback_data =f"admin_user_card:{user_id}:{banned_list_page}",i18n_instance =i18n ,lang =current_lang ),parse_mode ="HTML")
    await callback .answer ()


@router .callback_query (F .data .startswith ("admin_ban_confirm:"))
async def confirm_ban_handler (callback :types .CallbackQuery ,i18n_data :dict ,settings :Settings ):
    try :_ ,user_id_str ,page_str =callback .data .split (":");user_id =int (user_id_str );banned_list_page =int (page_str )
    except :await callback .answer ("Invalid data",show_alert =True );return
    current_lang =i18n_data .get ("current_language",getattr (settings ,'DEFAULT_LANGUAGE','en'));i18n :Optional [JsonI18n ]=i18n_data .get ("i18n_instance")
    if not i18n :await callback .answer ("Language error.",show_alert =True );return
    _ =lambda key ,**kwargs :i18n .gettext (current_lang ,key ,**kwargs )
    user_data =await get_user (user_id );user_display =(user_data ['first_name']or (f"@{user_data['username']}"if user_data .get ('username')else f"ID {user_id}"))if user_data else f"ID {user_id}"
    if callback .message :
        await callback .message .edit_text (text =_ ("admin_confirm_ban_prompt",user_display =user_display ,user_id =user_id ),reply_markup =get_confirmation_keyboard (yes_callback_data =f"admin_ban_do:{user_id}:{banned_list_page}",no_callback_data =f"admin_user_card:{user_id}:{banned_list_page}",i18n_instance =i18n ,lang =current_lang ),parse_mode ="HTML")
    await callback .answer ()


@router .callback_query (F .data .startswith ("admin_unban_do:"))
async def do_unban_user_handler (callback :types .CallbackQuery ,i18n_data :dict ,settings :Settings ,panel_service :PanelApiService ,state :FSMContext ):

    try :_ ,user_id_str ,page_str =callback .data .split (":");user_id_to_unban =int (user_id_str );banned_list_page =int (page_str )
    except :await callback .answer ("Invalid data",show_alert =True );return
    current_lang =i18n_data .get ("current_language",getattr (settings ,'DEFAULT_LANGUAGE','en'));i18n :Optional [JsonI18n ]=i18n_data .get ("i18n_instance")
    if not i18n :await callback .answer ("Language error.",show_alert =True );return
    _ =lambda key ,**kwargs :i18n .gettext (current_lang ,key ,**kwargs )
    user_to_unban_data =await get_user (user_id_to_unban );user_display_name =(user_to_unban_data ['first_name']or (f"@{user_to_unban_data['username']}"if user_to_unban_data .get ('username')else f"ID {user_id_to_unban}"))if user_to_unban_data else f"ID {user_id_to_unban}"
    if not user_to_unban_data or not user_to_unban_data ['is_banned']:
        await callback .answer (_ ("admin_user_not_banned",user_id_or_username =user_display_name ),show_alert =True )
        if callback .message :await show_user_card_handler (callback ,i18n_data ,settings ,panel_service ,state ,force_user_id =user_id_to_unban ,force_page =banned_list_page )
        return
    await set_user_ban_status_db (user_id_to_unban ,is_banned =False )
    panel_user_uuid =user_to_unban_data ['panel_user_uuid']if user_to_unban_data and 'panel_user_uuid'in user_to_unban_data .keys ()and user_to_unban_data ['panel_user_uuid']else None
    if panel_user_uuid :
        if not await panel_service .update_user_status_on_panel (panel_user_uuid ,enable =True ):logging .warning (f"Panel status update fail for unban {user_id_to_unban}")
    await callback .answer (_ ("admin_user_unbanned_from_card",user_display =user_display_name ,user_id =user_id_to_unban ),show_alert =False )
    if callback .message :await show_user_card_handler (callback ,i18n_data ,settings ,panel_service ,state ,force_user_id =user_id_to_unban ,force_page =banned_list_page )

@router .callback_query (F .data .startswith ("admin_ban_do:"))
async def do_ban_user_handler (callback :types .CallbackQuery ,i18n_data :dict ,settings :Settings ,panel_service :PanelApiService ,state :FSMContext ):
    try :_ ,user_id_str ,page_str =callback .data .split (":");user_id_to_ban =int (user_id_str );banned_list_page =int (page_str )
    except :await callback .answer ("Invalid data",show_alert =True );return
    current_lang =i18n_data .get ("current_language",getattr (settings ,'DEFAULT_LANGUAGE','en'));i18n :Optional [JsonI18n ]=i18n_data .get ("i18n_instance")
    if not i18n :await callback .answer ("Language error.",show_alert =True );return
    _ =lambda key ,**kwargs :i18n .gettext (current_lang ,key ,**kwargs )
    user_to_ban_data =await get_user (user_id_to_ban );user_display_name =(user_to_ban_data ['first_name']or (f"@{user_to_ban_data['username']}"if user_to_ban_data .get ('username')else f"ID {user_id_to_ban}"))if user_to_ban_data else f"ID {user_id_to_ban}"
    if not user_to_ban_data :await callback .answer (_ ("admin_user_not_found_in_bot_db",user_id =user_id_to_ban ),show_alert =True );return
    if user_to_ban_data ['is_banned']:await callback .answer (_ ("admin_user_already_banned",user_id_or_username =user_display_name ),show_alert =True );return
    if user_id_to_ban ==callback .from_user .id or user_id_to_ban in settings .ADMIN_IDS :await callback .answer (_ ("admin_cannot_ban_self_or_admin"),show_alert =True );return

    await set_user_ban_status_db (user_id_to_ban ,is_banned =True )
    panel_user_uuid =user_to_ban_data ['panel_user_uuid']if user_to_ban_data and 'panel_user_uuid'in user_to_ban_data .keys ()and user_to_ban_data ['panel_user_uuid']else None
    if panel_user_uuid :
        if not await panel_service .update_user_status_on_panel (panel_user_uuid ,enable =False ):logging .warning (f"Panel status update fail for ban {user_id_to_ban}")
    await callback .answer (_ ("admin_user_banned_from_card",user_display =user_display_name ,user_id =user_id_to_ban ),show_alert =False )
    if callback .message :await show_user_card_handler (callback ,i18n_data ,settings ,panel_service ,state ,force_user_id =user_id_to_ban ,force_page =banned_list_page )


@router .callback_query (F .data =="admin_action:main",AdminStates .waiting_for_user_id_to_ban )
@router .callback_query (F .data =="admin_action:main",AdminStates .waiting_for_user_id_to_unban )
async def cancel_user_management_input_state (callback :types .CallbackQuery ,state :FSMContext ,settings :Settings ,i18n_data :dict ,bot :Bot ):

    current_lang =i18n_data .get ("current_language",getattr (settings ,'DEFAULT_LANGUAGE','en'));i18n :Optional [JsonI18n ]=i18n_data .get ("i18n_instance")
    if not i18n :await callback .answer ("Language error.",show_alert =True );return
    _ =lambda key ,**kwargs :i18n .gettext (current_lang ,key ,**kwargs )
    if callback .message :
        try :await callback .message .edit_text (_ ("admin_action_cancelled_default"),reply_markup =get_admin_panel_keyboard (i18n ,current_lang ,settings ))
        except :await callback .message .answer (_ ("admin_action_cancelled_default"),reply_markup =get_admin_panel_keyboard (i18n ,current_lang ,settings ))
    await callback .answer (_ ("admin_action_cancelled_default"));await state .clear ()