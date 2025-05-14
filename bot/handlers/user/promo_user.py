import logging
import re
from aiogram import Router ,F ,types ,Bot
from aiogram .fsm .context import FSMContext
from typing import Optional

from config .settings import Settings
from bot .states .user_states import UserPromoStates
from bot .services .promo_code_service import PromoCodeService
from bot .services .subscription_service import SubscriptionService
from bot .keyboards .inline .user_keyboards import get_back_to_main_menu_markup
from bot .middlewares .i18n import JsonI18n
from aiogram .utils .markdown import hcode

from .start import send_main_menu

router =Router (name ="user_promo_router")

SUSPICIOUS_SQL_KEYWORDS_REGEX =re .compile (
r"\b(DROP\s*TABLE|DELETE\s*FROM|ALTER\s*TABLE|TRUNCATE\s*TABLE|UNION\s*SELECT|;\s*SELECT|;\s*INSERT|;\s*UPDATE|;\s*DELETE|xp_cmdshell|sysdatabases|sysobjects|INFORMATION_SCHEMA)\b",
re .IGNORECASE
)
SUSPICIOUS_CHARS_REGEX =re .compile (r"(--|#\s|;|\*\/|\/\*)")

async def prompt_promo_code_input (
callback :types .CallbackQuery ,
state :FSMContext ,
i18n_data :dict ,
settings :Settings
):
    current_lang =i18n_data .get ("current_language",getattr (settings ,'DEFAULT_LANGUAGE','en'))
    i18n :Optional [JsonI18n ]=i18n_data .get ("i18n_instance")
    if not i18n :await callback .answer ("Language error.",show_alert =True );return
    _ =lambda key ,**kwargs :i18n .gettext (current_lang ,key ,**kwargs )

    if not callback .message :
        logging .error ("CallbackQuery has no message in prompt_promo_code_input")
        await callback .answer (_ ("error_occurred_processing_request"),show_alert =True )
        return

    try :
        await callback .message .edit_text (
        text =_ (key ="promo_code_prompt"),
        reply_markup =get_back_to_main_menu_markup (current_lang ,i18n )
        )
    except Exception as e :
        logging .warning (f"Failed to edit message for promo prompt: {e}")
        await callback .message .answer (text =_ (key ="promo_code_prompt"),reply_markup =get_back_to_main_menu_markup (current_lang ,i18n ))

    await callback .answer ()
    await state .set_state (UserPromoStates .waiting_for_promo_code )
    logging .info (f"User {callback.from_user.id} entered state UserPromoStates.waiting_for_promo_code. FSM state: {await state.get_state()}")


@router .message (UserPromoStates .waiting_for_promo_code ,F .text )
async def process_promo_code_input (
message :types .Message ,
state :FSMContext ,
settings :Settings ,
i18n_data :dict ,
promo_code_service :PromoCodeService ,
bot :Bot
):
    logging .info (f"Processing promo code input from user {message.from_user.id} in state {await state.get_state()}: '{message.text}'")

    current_lang =i18n_data .get ("current_language",getattr (settings ,'DEFAULT_LANGUAGE','en'))
    i18n :Optional [JsonI18n ]=i18n_data .get ("i18n_instance")

    if not i18n or not promo_code_service :
        logging .error ("Deps missing in process_promo_code_input")
        await message .reply ("Service error. Please try again.")
        await state .clear ();return

    _ =lambda key ,**kwargs :i18n .gettext (current_lang ,key ,**kwargs )
    code_input =message .text .strip ();user =message .from_user
    is_suspicious =False
    if SUSPICIOUS_SQL_KEYWORDS_REGEX .search (code_input )or SUSPICIOUS_CHARS_REGEX .search (code_input )or len (code_input )>100 :
        is_suspicious =True
        logging .warning (f"Suspicious input for promo by user {user.id} (len: {len(code_input)}): '{code_input}'")

    response_to_user_text =""
    if is_suspicious :
        admin_notify_key ="admin_suspicious_promo_attempt_notification_no_username"if not user .username else "admin_suspicious_promo_attempt_notification"
        admin_lang =settings .DEFAULT_LANGUAGE
        _admin =lambda k ,**kw :i18n .gettext (admin_lang ,k ,**kw )
        admin_notification_text =_admin (admin_notify_key ,user_id =user .id ,user_username =user .username or "N/A",user_first_name =user .first_name or "N/A",promo_code_input =hcode (code_input ))
        try :await bot .send_message (settings .ADMIN_ID ,admin_notification_text ,parse_mode ="HTML")
        except Exception as e_admin_notify :logging .error (f"Failed to send suspicious promo notification to admin: {e_admin_notify}")
        response_to_user_text =_ ("promo_code_not_found",code =code_input .upper ())
    else :
        success ,response_text_from_service =await promo_code_service .apply_promo_code (user .id ,code_input ,current_lang )
        response_to_user_text =response_text_from_service

    await message .answer (response_to_user_text ,reply_markup =get_back_to_main_menu_markup (current_lang ,i18n ))
    await state .clear ()
    logging .info (f"Promo code '{code_input}' processing finished for user {message.from_user.id}. State cleared.")



@router .callback_query (F .data =="main_action:back_to_main",UserPromoStates .waiting_for_promo_code )
async def cancel_promo_input_via_button (
callback :types .CallbackQuery ,
state :FSMContext ,
settings :Settings ,
i18n_data :dict ,
subscription_service :SubscriptionService
):
    current_lang =i18n_data .get ("current_language",getattr (settings ,'DEFAULT_LANGUAGE','en'))
    i18n :Optional [JsonI18n ]=i18n_data .get ("i18n_instance")
    if not i18n :
        logging .error ("i18n missing in cancel_promo_input_via_button")
        await callback .answer ("Language error",show_alert =True )
        return

    logging .info (f"User {callback.from_user.id} cancelled promo code input via button from state {await state.get_state()}. Clearing state.")
    await state .clear ()
    logging .info (f"State after clear for user {callback.from_user.id}: {await state.get_state()}")

    if callback .message :
        show_trial_button_on_back =False
        if settings .TRIAL_ENABLED and not await subscription_service .has_had_any_subscription (callback .from_user .id ):
            show_trial_button_on_back =True

        await send_main_menu (callback ,settings ,i18n_data ,show_trial_button_flag =show_trial_button_on_back ,is_edit =True )
    else :

        await callback .answer ("Promo code input cancelled.",show_alert =False )