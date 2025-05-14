import logging
from typing import Callable ,Dict ,Any ,Awaitable ,Union ,Optional

from aiogram import BaseMiddleware ,Bot
from aiogram .types import Message ,CallbackQuery ,User ,InlineKeyboardMarkup ,Update
from aiogram .utils .keyboard import InlineKeyboardBuilder
from aiogram .exceptions import TelegramAPIError ,TelegramForbiddenError ,TelegramBadRequest ,AiogramError

from config .settings import Settings
from db .database import get_user
from bot .middlewares .i18n import JsonI18n
from bot .keyboards .inline .user_keyboards import get_user_banned_keyboard

class BanCheckMiddleware (BaseMiddleware ):
    def __init__ (self ,settings :Settings ,i18n_instance :JsonI18n ):
        super ().__init__ ()
        self .settings =settings
        self .i18n_main_instance =i18n_instance

    async def __call__ (
    self ,
    handler :Callable [[Update ,Dict [str ,Any ]],Awaitable [Any ]],
    event :Update ,
    data :Dict [str ,Any ]
    )->Any :
        event_user :Optional [User ]=data .get ("event_from_user")
        if not event_user :return await handler (event ,data )


        if event_user .id in self .settings .ADMIN_IDS :
            return await handler (event ,data )

        try :
            db_user_data =await get_user (user_id =event_user .id )
        except Exception as e_db :
            logging .error (f"BanCheckMiddleware: DB error fetching user {event_user.id}: {e_db}",exc_info =True )
            return await handler (event ,data )

        if db_user_data and db_user_data ['is_banned']==1 :
            logging .info (f"User {event_user.id} ({event_user.username or 'NoUsername'}) is banned. Blocking access and preparing notification.")

            ban_message_text ="You are blocked. Please contact support."
            keyboard :Optional [InlineKeyboardMarkup ]=None
            current_lang =self .settings .DEFAULT_LANGUAGE
            i18n_to_use :Optional [JsonI18n ]=None
            actual_event_object :Optional [Union [Message ,CallbackQuery ]]=None


            if event .message :
                actual_event_object =event .message
            elif event .callback_query :
                actual_event_object =event .callback_query


            if not actual_event_object :
                logging .warning (f"BanCheck: Could not determine specific event type (Message/CallbackQuery) for banned user {event_user.id} from Update object. Update type: {event.type}")

                try :
                    bot_instance :Bot =data ["bot"]
                    await bot_instance .send_message (event_user .id ,ban_message_text )
                except Exception as e_direct_send :
                    logging .error (f"BanCheck: Failed to send direct ban message to {event_user.id}: {e_direct_send}")
                return

            try :
                logging .debug ("BanCheck: [A] Inside main try block for banned user notification.")
                i18n_data_from_event =data .get ("i18n_data",{})
                current_lang =i18n_data_from_event .get ("current_language",self .settings .DEFAULT_LANGUAGE )
                i18n_to_use =i18n_data_from_event .get ("i18n_instance")
                logging .debug (f"BanCheck: [B] i18n_instance from event_data: {type(i18n_to_use)}. Current lang: {current_lang}")

                if not i18n_to_use :
                    i18n_to_use =self .i18n_main_instance
                    logging .warning (f"BanCheck: [B_fallback] Using fallback i18n instance for banned user {event_user.id}. Type: {type(i18n_to_use)}")

                if i18n_to_use :
                    _ =lambda k ,**kw :i18n_to_use .gettext (current_lang ,k ,**kw )
                    logging .debug ("BanCheck: [D] Attempting to get 'user_is_banned' text.")
                    ban_message_text =_ ("user_is_banned")
                    logging .debug (f"BanCheck: [E] Ban message text: '{ban_message_text}'")
                    if self .settings .SUPPORT_LINK :
                        logging .debug ("BanCheck: [F] Support link found. Attempting to get user_banned_keyboard.")
                        keyboard =get_user_banned_keyboard (self .settings .SUPPORT_LINK ,current_lang ,i18n_to_use )
                        logging .debug (f"BanCheck: [G] Keyboard created: {keyboard is not None}")
                    else :logging .debug ("BanCheck: [F_alt] No support link configured.")
                else :
                    logging .error (f"BanCheck: [CRITICAL] No i18n instance for user {event_user.id}. Using hardcoded text.")
                    if self .settings .SUPPORT_LINK :
                        kb_temp =InlineKeyboardBuilder ();kb_temp .button (text ="Support",url =self .settings .SUPPORT_LINK );keyboard =kb_temp .as_markup ()
                        logging .debug ("BanCheck: [G_alt] Fallback keyboard created due to no i18n.")

                logging .debug (f"BanCheck: [H] Final pre-send check. Message: '{ban_message_text}', Keyboard: {keyboard is not None}")


                if isinstance (actual_event_object ,Message ):
                    logging .debug (f"BanCheck: [I_Msg] Attempting actual_event_object.answer for Message to user {event_user.id}")
                    await actual_event_object .answer (ban_message_text ,reply_markup =keyboard )
                    logging .info (f"BanCheck: [J_Msg] Ban notification 'actual_event_object.answer' attempted for user {event_user.id} (Message).")
                elif isinstance (actual_event_object ,CallbackQuery ):
                    logging .debug (f"BanCheck: [I_CB] Attempting actual_event_object.answer (alert) for CallbackQuery to user {event_user.id}")
                    await actual_event_object .answer (ban_message_text ,show_alert =True )
                    logging .info (f"BanCheck: [J_CB] Ban alert 'actual_event_object.answer' attempted for user {event_user.id} (CallbackQuery).")

                    target_message_obj =actual_event_object .message
                    if target_message_obj :
                        target_chat_id =target_message_obj .chat .id
                        try :
                            logging .debug (f"BanCheck: [K_CB_Edit] Attempting target_message_obj.edit_text for user {event_user.id}")
                            await target_message_obj .edit_text (ban_message_text ,reply_markup =keyboard )
                            logging .info (f"BanCheck: [L_CB_Edit] Ban msg 'target_message_obj.edit_text' attempted for user {event_user.id} (Callback).")
                        except Exception as e_edit :
                            logging .warning (f"BanCheck: [M_CB_EditFail] Failed to edit message for banned user {event_user.id}: {type(e_edit).__name__} - {e_edit}. Sending new message.")
                            await actual_event_object .bot .send_message (target_chat_id ,ban_message_text ,reply_markup =keyboard )
                            logging .info (f"BanCheck: [N_CB_NewMsg] Ban msg 'actual_event_object.bot.send_message' (after edit fail) attempted for user {event_user.id} (Callback).")
                    else :
                        logging .warning (f"BanCheck: [K_CB_NoMsg] CallbackQuery from {event_user.id} has no .message attribute. Sending new message directly.")
                        await actual_event_object .bot .send_message (actual_event_object .from_user .id ,ban_message_text ,reply_markup =keyboard )
                        logging .info (f"BanCheck: [L_CB_NoMsg_NewMsg] Ban msg 'actual_event_object.bot.send_message' (no .message) attempted for user {event_user.id} (Callback).")
                else :
                    logging .error (f"BanCheck: [UNHANDLED_EVENT_TYPE_INTERNAL] actual_event_object type {type(actual_event_object)} was not Message or CallbackQuery.")

            except TelegramForbiddenError as e_forbidden :logging .warning (f"BanCheck: TelegramForbiddenError sending ban msg to {event_user.id}: {e_forbidden}")
            except TelegramBadRequest as e_bad_req :logging .error (f"BanCheck: TelegramBadRequest sending ban msg to {event_user.id}: {e_bad_req}",exc_info =True )
            except TelegramAPIError as e_api :logging .error (f"BanCheck: TelegramAPIError sending ban msg to {event_user.id}: {e_api}",exc_info =True )
            except AiogramError as e_aio :logging .error (f"BanCheck: AiogramError sending ban msg to {event_user.id}: {e_aio}",exc_info =True )
            except Exception as e_general :
                logging .error (f"BanCheck: Generic failure preparing or sending ban notification to user {event_user.id}: {e_general}",exc_info =True )

            logging .debug (f"BanCheck: [Z] End of ban processing for user {event_user.id}. Returning to stop further handlers.")
            return

        return await handler (event ,data )