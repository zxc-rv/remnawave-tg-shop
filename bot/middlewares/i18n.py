import logging
import json
import os
import aiosqlite
from typing import Any ,Awaitable ,Callable ,Dict ,Optional

from aiogram import BaseMiddleware
from aiogram .types import TelegramObject ,User ,Update


from db .database import get_user ,get_db_connection_manager ,_setup_db_connection
from config .settings import Settings




class JsonI18n :
    def __init__ (self ,path :str ,default :str ="en",domain :str ="bot"):
        self .domain =domain
        self .path =path
        self .default_lang =default
        self .locales_data :Dict [str ,Dict [str ,str ]]={}
        self ._load_locales ()
        logging .info (f"JsonI18n initialized. Loaded languages: {list(self.locales_data.keys())}. Default: {self.default_lang}")

    def _load_locales (self ):
        if not os .path .isdir (self .path ):logging .error (f"Locales path not found: {self.path}");return
        for item in os .listdir (self .path ):
            if item .endswith (".json"):
                lang_code =item .split (".")[0 ];file_path =os .path .join (self .path ,item )
                try :
                    with open (file_path ,"r",encoding ="utf-8")as f :self .locales_data [lang_code ]=json .load (f )
                except Exception as e :logging .error (f"Error loading locale {lang_code} from {file_path}: {e}")

    def gettext (self ,lang_code :Optional [str ],key :str ,**kwargs )->str :
        effective_lang_code =lang_code
        if not effective_lang_code or effective_lang_code not in self .locales_data :
            effective_lang_code =self .default_lang
        lang_data =self .locales_data .get (effective_lang_code )
        if lang_data is None :
            logging .warning (f"No language data for '{effective_lang_code}' (default: '{self.default_lang}'). Key '{key}'.");return key .format (**kwargs )if kwargs else key
        text =lang_data .get (key )
        if text is None :
            if effective_lang_code !=self .default_lang :
                default_lang_data =self .locales_data .get (self .default_lang ,{});text =default_lang_data .get (key )
            if text is None :return key .format (**kwargs )if kwargs else key
        try :return text .format (**kwargs )if kwargs else text
        except KeyError as e :logging .warning (f"Missing format key {e} for key '{key}' (lang: {effective_lang_code}). Text: '{text}'");return text
        except Exception as e :logging .error (f"Error formatting key '{key}' (lang: {effective_lang_code}): {e}. Text: '{text}'");return text

_i18n_instance :Optional [JsonI18n ]=None
def get_i18n_instance (path :str ="locales",default :str ="en",domain :str ="bot")->JsonI18n :
    global _i18n_instance
    if _i18n_instance is None :_i18n_instance =JsonI18n (path =path ,default =default ,domain =domain )
    return _i18n_instance


class I18nMiddleware (BaseMiddleware ):
    def __init__ (self ,i18n :JsonI18n ,settings :Settings ):
        super ().__init__ ()
        self .i18n =i18n
        self .settings =settings

    async def __call__ (
    self ,
    handler :Callable [[Update ,Dict [str ,Any ]],Awaitable [Any ]],
    event :Update ,
    data :Dict [str ,Any ]
    )->Any :
        event_user :Optional [User ]=data .get ("event_from_user")

        current_language =self .i18n .default_lang


        if event_user :
            logging .debug (f"I18nMiddleware: Processing for user {event_user.id}")

            try :

                user_db_data =await get_user (event_user .id )
                if user_db_data and user_db_data ['language_code']and user_db_data ['language_code']in self .i18n .locales_data :
                    current_language =user_db_data ['language_code']
                    logging .debug (f"I18nMiddleware: User {event_user.id} language loaded from DB: {current_language}")
                else :

                    if event_user .language_code :
                        lang_prefix =event_user .language_code .split ('-')[0 ]
                        if lang_prefix in self .i18n .locales_data :
                            current_language =lang_prefix
                            logging .debug (f"I18nMiddleware: User {event_user.id} language set from Telegram client (prefix): {current_language}")
                        elif event_user .language_code in self .i18n .locales_data :
                            current_language =event_user .language_code
                            logging .debug (f"I18nMiddleware: User {event_user.id} language set from Telegram client (full): {current_language}")
                        else :

                            logging .debug (f"I18nMiddleware: User {event_user.id} Telegram client language '{event_user.language_code}' not supported. Using default: {current_language}")
                    else :
                        logging .debug (f"I18nMiddleware: User {event_user.id} has no language_code from Telegram. Using default: {current_language}")
            except Exception as e_db_lang :

                logging .error (f"I18nMiddleware: Error fetching user language from DB for user {event_user.id}: {e_db_lang}. Falling back.")
                if event_user .language_code :
                    lang_prefix =event_user .language_code .split ('-')[0 ]
                    if lang_prefix in self .i18n .locales_data :current_language =lang_prefix
                    elif event_user .language_code in self .i18n .locales_data :current_language =event_user .language_code

        data ["i18n_data"]={
        "i18n_instance":self .i18n ,
        "current_language":current_language
        }
        logging .debug (f"I18nMiddleware: Final current_language for event: {current_language}")

        return await handler (event ,data )