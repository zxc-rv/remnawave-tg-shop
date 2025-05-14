import logging
import aiosqlite
from aiogram import Router ,F ,types ,Bot
from aiogram .filters import Command
from aiogram .fsm .context import FSMContext
from typing import Optional ,Dict ,Any
from datetime import datetime ,timezone
from aiogram .utils .keyboard import InlineKeyboardBuilder
from aiogram .types import InlineKeyboardMarkup

from config .settings import Settings
from db .database import add_payment_record ,get_db_connection_manager ,_setup_db_connection
from bot .keyboards .inline .user_keyboards import (
get_subscription_options_keyboard ,
get_confirm_subscription_keyboard ,
get_payment_url_keyboard ,
get_back_to_main_menu_markup
)
from bot .services .payment_service import YooKassaService
from bot .services .subscription_service import SubscriptionService
from bot .services .panel_api_service import PanelApiService
from bot .middlewares .i18n import JsonI18n

router =Router (name ="user_subscription_router")

async def display_subscription_options (message_or_callback :types .Message |types .CallbackQuery ,i18n_data :dict ,settings :Settings ):
    current_lang =i18n_data .get ("current_language",getattr (settings ,'DEFAULT_LANGUAGE','en'))
    i18n :Optional [JsonI18n ]=i18n_data .get ("i18n_instance")
    if not i18n :
        logging .error ("i18n missing in display_subscription_options")

        target_msg =message_or_callback .message if isinstance (message_or_callback ,types .CallbackQuery )else message_or_callback
        if target_msg :await target_msg .answer ("Language service error.")
        if isinstance (message_or_callback ,types .CallbackQuery ):await message_or_callback .answer ()
        return

    get_translation =lambda key ,**kwargs :i18n .gettext (current_lang ,key ,**kwargs )
    currency_symbol_val =settings .DEFAULT_CURRENCY_SYMBOL

    text =get_translation ("select_subscription_period")if settings .subscription_options else get_translation ("no_subscription_options_available")
    reply_markup =get_subscription_options_keyboard (settings .subscription_options ,currency_symbol_val ,current_lang ,i18n )if settings .subscription_options else None

    target_message =message_or_callback .message if isinstance (message_or_callback ,types .CallbackQuery )else message_or_callback
    answered_callback =False

    if isinstance (message_or_callback ,types .CallbackQuery ):

        await message_or_callback .answer ()
        answered_callback =True

    if target_message :
        if isinstance (message_or_callback ,types .CallbackQuery ):
            try :
                await target_message .edit_text (text ,reply_markup =reply_markup )
            except Exception :
                await target_message .answer (text ,reply_markup =reply_markup )
        else :
            await target_message .answer (text ,reply_markup =reply_markup )
    elif isinstance (message_or_callback ,types .Message ):
         await message_or_callback .answer (text ,reply_markup =reply_markup )


    if isinstance (message_or_callback ,types .CallbackQuery )and not answered_callback :
        await message_or_callback .answer ()


@router .callback_query (F .data .startswith ("subscribe_period:"))
async def select_subscription_period_callback_handler (callback :types .CallbackQuery ,state :FSMContext ,settings :Settings ,i18n_data :dict ):
    current_lang =i18n_data .get ("current_language",getattr (settings ,'DEFAULT_LANGUAGE','en'))
    i18n :Optional [JsonI18n ]=i18n_data .get ("i18n_instance")
    if not i18n :
        logging .error ("i18n missing in select_subscription_period_callback_handler")
        await callback .answer ("Service error. Please try again.",show_alert =True )
        return
    get_translation =lambda key ,**kwargs :i18n .gettext (current_lang ,key ,**kwargs )

    try :months =int (callback .data .split (":")[-1 ])
    except ValueError :
        logging .error (f"Invalid sub period: {callback.data}")
        await callback .answer (get_translation ("error_try_again"),show_alert =True );return

    price =settings .subscription_options .get (months )
    if price is None :
        logging .error (f"Price not found for {months} months subscription.")
        await callback .answer (get_translation ("error_try_again"),show_alert =True );return

    currency_symbol_val =settings .DEFAULT_CURRENCY_SYMBOL
    confirmation_text =get_translation ("confirm_subscription_prompt",months =months ,price =price ,currency_symbol =currency_symbol_val )
    reply_markup =get_confirm_subscription_keyboard (months ,price ,currency_symbol_val ,current_lang ,i18n )

    if callback .message :
        try :await callback .message .edit_text (confirmation_text ,reply_markup =reply_markup )
        except Exception as e :logging .warning (f"Edit failed: {e}");await callback .message .answer (confirmation_text ,reply_markup =reply_markup )
    await callback .answer ()


@router .callback_query (F .data .startswith ("confirm_sub:"))
async def confirm_subscription_callback_handler (
callback :types .CallbackQuery ,state :FSMContext ,
settings :Settings ,i18n_data :dict ,yookassa_service :YooKassaService
):
    i18n :Optional [JsonI18n ]=i18n_data .get ("i18n_instance")
    current_lang =i18n_data .get ("current_language",getattr (settings ,'DEFAULT_LANGUAGE','en'))
    if not i18n :logging .error ("i18n missing");await callback .answer ("Language error.",show_alert =True );return
    get_translation =lambda key ,**kwargs :i18n .gettext (current_lang ,key ,**kwargs )
    if not yookassa_service or not yookassa_service .configured :
        logging .error ("YooKassa service missing or not configured")
        await callback .message .edit_text (get_translation ("payment_service_unavailable"))if callback .message else None
        await callback .answer (get_translation ("payment_service_unavailable"),show_alert =True );return
    try :_ ,data_payload =callback .data .split (":",1 );months_str ,price_str =data_payload .split (":");months =int (months_str );price =float (price_str )
    except ValueError :logging .error (f"Invalid confirm data: {callback.data}");await callback .answer (get_translation ("error_try_again"),show_alert =True );return

    user_id =callback .from_user .id
    description =get_translation ("payment_description_subscription",months =months )
    currency =settings .DEFAULT_CURRENCY_SYMBOL
    payment_metadata ={"user_id":str (user_id ),"subscription_months":str (months ),"description":description }
    payment_db_id =await add_payment_record (user_id ,None ,None ,price ,currency ,"pending_creation",description ,months ,None )
    if not payment_db_id :
        if callback .message :await callback .message .edit_text (get_translation ("error_creating_payment_record"))
        await callback .answer (show_alert =True );return
    payment_metadata ["payment_db_id"]=str (payment_db_id )
    payment_response =await yookassa_service .create_payment (price ,currency ,description ,payment_metadata )

    if callback .message :
        if payment_response and payment_response .get ("confirmation_url"):
            async with get_db_connection_manager ()as db :await _setup_db_connection (db );await db .execute ("UPDATE payments SET yookassa_payment_id = ?, idempotence_key = ?, status = ? WHERE payment_id = ?",(payment_response ["id"],payment_response .get ("idempotence_key"),payment_response ["status"],payment_db_id ));await db .commit ()
            await callback .message .edit_text (get_translation (key ="payment_link_message",months =months ),reply_markup =get_payment_url_keyboard (payment_response ["confirmation_url"],current_lang ,i18n ),disable_web_page_preview =False )
        else :
            async with get_db_connection_manager ()as db :await _setup_db_connection (db );await db .execute ("UPDATE payments SET status = ? WHERE payment_id = ?",("failed_creation",payment_db_id ));await db .commit ()
            await callback .message .edit_text (get_translation ("error_payment_gateway"))
    await callback .answer ()


@router .callback_query (F .data =="main_action:subscribe")
async def reshow_subscription_options_callback (callback :types .CallbackQuery ,i18n_data :dict ,settings :Settings ):
    await display_subscription_options (callback ,i18n_data ,settings )



async def my_subscription_command_handler (
message_event :types .Message |types .CallbackQuery ,
i18n_data :dict ,
settings :Settings ,
panel_service :PanelApiService ,
subscription_service :SubscriptionService
):
    target_message =message_event .message if isinstance (message_event ,types .CallbackQuery )else message_event
    user =message_event .from_user
    if isinstance (message_event ,types .CallbackQuery ):await message_event .answer ()

    current_lang =i18n_data .get ("current_language",getattr (settings ,'DEFAULT_LANGUAGE','en'))
    i18n :Optional [JsonI18n ]=i18n_data .get ("i18n_instance")
    if not i18n :logging .error ("i18n missing");await target_message .answer ("Lang error");return
    get_translation =lambda key ,**kwargs :i18n .gettext (current_lang ,key ,**kwargs )
    if not panel_service or not subscription_service :logging .error ("Services missing");await target_message .answer (get_translation ("error_service_unavailable"));return

    active_sub =await subscription_service .get_active_subscription (user .id )
    sub_info_text =""
    if active_sub :
        end_date_obj =active_sub .get ('end_date')
        if isinstance (end_date_obj ,str ):
            try :end_date_obj =datetime .fromisoformat (end_date_obj .replace ("Z","+00:00"))
            except ValueError :logging .warning (f"Could not parse date string '{end_date_obj}'.");end_date_obj =datetime .now (timezone .utc )

        if not isinstance (end_date_obj ,datetime ):end_date_obj =datetime .now (timezone .utc )
        if end_date_obj .tzinfo is None :end_date_obj =end_date_obj .replace (tzinfo =timezone .utc )


        today_date_utc =datetime .now (timezone .utc ).date ()
        end_date_only =end_date_obj .date ()
        days_left =(end_date_only -today_date_utc ).days

        actual_config_link =get_translation ("config_link_not_available");panel_user_uuid =active_sub .get ('panel_user_uuid')
        if panel_user_uuid :
            panel_user_data =await panel_service .get_user_by_uuid (panel_user_uuid )
            if panel_user_data :
                if panel_user_data .get ('subscriptionUrl'):actual_config_link =panel_user_data ['subscriptionUrl']
                elif panel_user_data .get ('shortUuid'):
                    link =await panel_service .get_subscription_link (panel_user_data ['shortUuid'])
                    if link :actual_config_link =link

        traffic_limit_gb =get_translation ("traffic_unlimited");traffic_used_gb =get_translation ("traffic_na")
        if active_sub .get ('traffic_limit_bytes')and active_sub ['traffic_limit_bytes']>0 :traffic_limit_gb =f"{active_sub['traffic_limit_bytes'] / (1024**3):.2f} GB"
        if active_sub .get ('traffic_used_bytes')is not None :traffic_used_gb =f"{active_sub['traffic_used_bytes'] / (1024**3):.2f} GB"

        sub_info_text =get_translation ("my_subscription_details",end_date =end_date_obj .strftime ("%Y-%m-%d"),days_left =max (0 ,days_left ),status =active_sub .get ('status_from_panel',get_translation ('status_active')).capitalize (),config_link =actual_config_link ,traffic_limit =traffic_limit_gb ,traffic_used =traffic_used_gb )
    else :
        sub_info_text =get_translation ("subscription_not_active")

    reply_markup_val =get_back_to_main_menu_markup (current_lang ,i18n )
    if isinstance (message_event ,types .CallbackQuery )and message_event .message :
        try :await message_event .message .edit_text (sub_info_text ,reply_markup =reply_markup_val ,parse_mode ="HTML",disable_web_page_preview =True )
        except Exception as e :logging .warning (f"Edit 'my_sub' failed: {e}");await target_message .answer (sub_info_text ,reply_markup =reply_markup_val ,parse_mode ="HTML",disable_web_page_preview =True )
    else :await target_message .answer (sub_info_text ,reply_markup =reply_markup_val ,parse_mode ="HTML",disable_web_page_preview =True )


@router .message (Command ("connect"))
async def connect_command_handler (
message :types .Message ,
i18n_data :dict ,
settings :Settings ,
panel_service :PanelApiService ,
subscription_service :SubscriptionService
):
    """Handles the /connect command, showing subscription info."""
    logging .info (f"User {message.from_user.id} used /connect command.")
    await my_subscription_command_handler (message ,i18n_data ,settings ,panel_service ,subscription_service )