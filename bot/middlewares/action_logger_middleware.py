import logging
import json
from typing import Callable ,Dict ,Any ,Awaitable ,Union ,Optional

from aiogram import BaseMiddleware
from aiogram .types import Update ,Message ,CallbackQuery ,User

from db .database import log_user_action
from config .settings import Settings

class ActionLoggerMiddleware (BaseMiddleware ):
    def __init__ (self ,settings :Settings ):
        super ().__init__ ()
        self .settings =settings

    async def __call__ (
    self ,
    handler :Callable [[Update ,Dict [str ,Any ]],Awaitable [Any ]],
    event :Update ,
    data :Dict [str ,Any ]
    )->Any :

        event_user :Optional [User ]=data .get ("event_from_user")
        bot :Optional [Bot ]=data .get ("bot")

        user_id :Optional [int ]=None
        telegram_username :Optional [str ]=None
        telegram_first_name :Optional [str ]=None
        event_type :str =event .event_type
        content :Optional [str ]=None
        is_admin_event_flag :bool =False

        if event_user :
            user_id =event_user .id
            telegram_username =event_user .username
            telegram_first_name =event_user .first_name
            if user_id ==self .settings .ADMIN_IDS :
                is_admin_event_flag =True

        raw_update_snippet =None
        try :

            raw_update_snippet =event .model_dump_json (exclude_none =True ,indent =None )[:1000 ]
        except Exception :
            raw_update_snippet =str (event )[:1000 ]


        if event .message :
            msg =event .message
            if msg .text :
                content =msg .text
                if msg .text .startswith ('/'):
                    event_type ="command"
            elif msg .caption :
                content =f"[{msg.content_type}] {msg.caption}"
            else :
                content =f"[{msg.content_type}]"

        elif event .callback_query :
            cb =event .callback_query
            event_type ="callback_query"
            content =cb .data










        if user_id and event_type and content :
            try :
                await log_user_action (
                user_id =user_id ,
                telegram_username =telegram_username ,
                telegram_first_name =telegram_first_name ,
                event_type =event_type ,
                content =content [:1000 ],
                raw_update_preview =raw_update_snippet ,
                is_admin_event =is_admin_event_flag
                )
            except Exception as e_log :
                logging .error (f"ActionLoggerMiddleware: Failed to log event for user {user_id}: {e_log}",exc_info =True )
        elif user_id and event_type :
             try :
                await log_user_action (user_id =user_id ,telegram_username =telegram_username ,telegram_first_name =telegram_first_name ,event_type =event_type ,content ="N/A",raw_update_preview =raw_update_snippet ,is_admin_event =is_admin_event_flag )
             except Exception as e_log :
                logging .error (f"ActionLoggerMiddleware: Failed to log event (no content) for user {user_id}: {e_log}",exc_info =True )



        return await handler (event ,data )