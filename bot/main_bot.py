import logging
import asyncio

from aiogram import Bot ,Dispatcher ,Router ,F
from aiogram .enums import ParseMode
from aiogram .filters import CommandStart ,Command
from aiogram .client .default import DefaultBotProperties
from aiogram .webhook .aiohttp_server import SimpleRequestHandler ,setup_application
from aiogram .fsm .storage .memory import MemoryStorage
from aiohttp import web
from apscheduler .schedulers .asyncio import AsyncIOScheduler


from config .settings import Settings ,get_settings
from .middlewares .i18n import I18nMiddleware ,get_i18n_instance ,JsonI18n
from .middlewares .ban_check_middleware import BanCheckMiddleware
from .middlewares .action_logger_middleware import ActionLoggerMiddleware

from .handlers .user import user_router_aggregate
from .handlers .user import payment as user_payment_webhook_module

from .handlers .admin import admin_router_aggregate
from .filters .admin_filter import AdminFilter

from db .database import get_db_connection_manager

from .services .notification_service import schedule_subscription_notifications
from .services .payment_service import YooKassaService
from .services .panel_api_service import PanelApiService
from .services .subscription_service import SubscriptionService
from .services .referral_service import ReferralService
from .services .promo_code_service import PromoCodeService


async def register_all_routers (dp :Dispatcher ,settings :Settings ):
    dp .include_router (user_router_aggregate )
    admin_filtered_router_wrapper =Router (name ="admin_filtered_router_wrapper")
    admin_filter_instance =AdminFilter (admin_ids =settings .ADMIN_IDS )
    admin_filtered_router_wrapper .message .filter (admin_filter_instance )
    admin_filtered_router_wrapper .callback_query .filter (admin_filter_instance )
    admin_filtered_router_wrapper .include_router (admin_router_aggregate )
    dp .include_router (admin_filtered_router_wrapper )
    logging .info ("All application routers registered.")

async def on_startup_configured (dispatcher :Dispatcher ):

    bot :Bot =dispatcher ["bot_instance"];settings :Settings =dispatcher ["settings"];i18n_instance :JsonI18n =dispatcher ["i18n_instance"]
    logging .info ("STARTUP: on_startup_configured executing...")
    scheduler =AsyncIOScheduler (timezone ="UTC")
    try :await schedule_subscription_notifications (bot ,settings ,i18n_instance ,scheduler );scheduler .start ();dispatcher ["scheduler"]=scheduler ;logging .info ("STARTUP: APScheduler started.")
    except Exception as e :logging .error (f"STARTUP: Failed to start APScheduler: {e}",exc_info =True )
    telegram_webhook_url_to_set =getattr (settings ,'TELEGRAM_WEBHOOK_BASE_URL',None )
    if telegram_webhook_url_to_set :
        if settings .BOT_TOKEN in telegram_webhook_url_to_set :logging .error (f"CRITICAL: Bot token in TELEGRAM_WEBHOOK_BASE_URL ('{telegram_webhook_url_to_set}').");full_telegram_webhook_url ="ERROR_URL"
        else :full_telegram_webhook_url =f"{str(telegram_webhook_url_to_set).rstrip('/')}/{settings.BOT_TOKEN}"
        logging .info (f"STARTUP: Attempting to set Telegram webhook to: {full_telegram_webhook_url}")
        try :
            current_webhook_info_before =await bot .get_webhook_info ();logging .info (f"STARTUP: Current webhook info BEFORE: {current_webhook_info_before.model_dump_json(exclude_none=True, indent=2)}")
            if full_telegram_webhook_url !="ERROR_URL":
                set_success =await bot .set_webhook (url =full_telegram_webhook_url ,drop_pending_updates =True ,allowed_updates =dispatcher .resolve_used_update_types ())
                if set_success :logging .info (f"STARTUP: bot.set_webhook to {full_telegram_webhook_url} returned SUCCESS (True).")
                else :logging .error (f"STARTUP: bot.set_webhook to {full_telegram_webhook_url} returned FAILURE (False).")
                new_webhook_info =await bot .get_webhook_info ();logging .info (f"STARTUP: Webhook info AFTER: {new_webhook_info.model_dump_json(exclude_none=True, indent=2)}")
                if not new_webhook_info .url :logging .error ("STARTUP: CRITICAL - Webhook URL EMPTY after set attempt.")
            else :logging .error ("STARTUP: Skipped setting webhook due to URL config error.")
        except Exception as e_setwebhook :logging .error (f"STARTUP: EXCEPTION during set/get Telegram webhook: {e_setwebhook}",exc_info =True )
    else :
        logging .info ("STARTUP: TELEGRAM_WEBHOOK_BASE_URL not set. Attempting to delete webhook.");await bot .delete_webhook (drop_pending_updates =True )
    logging .info ("STARTUP: Bot on_startup_configured completed.")


async def on_shutdown_configured (dispatcher :Dispatcher ):

    logging .warning ("SHUTDOWN: on_shutdown_configured executing...");scheduler :AsyncIOScheduler =dispatcher .get ("scheduler")
    if scheduler and scheduler .running :
        try :scheduler .shutdown (wait =False );logging .info ("SHUTDOWN: APScheduler shut down.")
        except Exception as e :logging .error (f"SHUTDOWN: Error APScheduler: {e}",exc_info =True )
    panel_service :PanelApiService =dispatcher .get ("panel_service")
    if panel_service and panel_service ._session and not panel_service ._session .closed :await panel_service .close_session ()
    bot :Bot =dispatcher .get ("bot_instance")
    if bot and bot .session and not bot .session .closed :await bot .session .close ()
    logging .info ("SHUTDOWN: Bot on_shutdown_configured completed.")


async def run_bot (settings_param :Settings ):
    storage =MemoryStorage ()
    default_props =DefaultBotProperties (parse_mode =ParseMode .HTML )
    bot =Bot (token =settings_param .BOT_TOKEN ,default =default_props )

    dp =Dispatcher (storage =storage ,settings =settings_param ,bot_instance =bot )

    actual_bot_username ="your_bot_username"
    try :
        bot_info =await bot .get_me ()
        actual_bot_username =bot_info .username
        logging .info (f"Bot username: @{actual_bot_username}")
    except Exception as e :
        logging .error (f"Failed to get bot info: {e}. Using fallback username: {actual_bot_username}")

    default_lang =settings_param .DEFAULT_LANGUAGE
    i18n_instance =get_i18n_instance (path ="locales",default =default_lang )


    yookassa_service =YooKassaService (
    shop_id =settings_param .YOOKASSA_SHOP_ID ,
    secret_key =settings_param .YOOKASSA_SECRET_KEY ,
    configured_return_url =settings_param .YOOKASSA_RETURN_URL ,
    bot_username_for_default =actual_bot_username ,
    settings_obj =settings_param
    )

    panel_service =PanelApiService (settings_param )
    subscription_service =SubscriptionService (get_db_connection_manager ,settings_param ,panel_service )
    referral_service =ReferralService (get_db_connection_manager ,settings_param ,subscription_service ,bot ,i18n_instance )
    promo_code_service =PromoCodeService (get_db_connection_manager ,settings_param ,subscription_service ,bot ,i18n_instance )


    dp ["i18n_instance"]=i18n_instance
    dp ["i18n_data"]={"i18n_instance":i18n_instance ,"current_language":default_lang }
    dp ["yookassa_service"]=yookassa_service
    dp ["panel_service"]=panel_service
    dp ["subscription_service"]=subscription_service
    dp ["referral_service"]=referral_service
    dp ["promo_code_service"]=promo_code_service



    dp .update .outer_middleware (I18nMiddleware (i18n =i18n_instance ,settings =settings_param ))
    dp .update .outer_middleware (BanCheckMiddleware (settings =settings_param ,i18n_instance =i18n_instance ))
    dp .update .outer_middleware (ActionLoggerMiddleware (settings =settings_param ))

    dp .startup .register (on_startup_configured )
    dp .shutdown .register (on_shutdown_configured )
    await register_all_routers (dp ,settings_param )


    tg_webhook_base =getattr (settings_param ,'TELEGRAM_WEBHOOK_BASE_URL',None );yk_webhook_base =getattr (settings_param ,'YOOKASSA_WEBHOOK_BASE_URL',None )
    logging .info (f"--- Determining Run Mode ---");logging .info (f"Configured TELEGRAM_WEBHOOK_BASE_URL: '{tg_webhook_base}'");logging .info (f"Configured YOOKASSA_WEBHOOK_BASE_URL: '{yk_webhook_base}'")
    should_run_aiohttp =bool (yk_webhook_base and settings_param .yookassa_webhook_path )or bool (tg_webhook_base )
    telegram_uses_webhook =bool (tg_webhook_base );telegram_should_poll =not telegram_uses_webhook
    logging .info (f"Decision: Run AIOHTTP server: {should_run_aiohttp}");logging .info (f"Decision: Telegram uses webhook: {telegram_uses_webhook}");logging .info (f"Decision: Telegram should poll: {telegram_should_poll}");logging .info (f"--- End Run Mode Decision ---")
    web_app_runner =None ;main_tasks_to_await =[]
    if should_run_aiohttp :
        app =web .Application ();app ['bot']=bot ;app ['dp']=dp ;app ['settings']=settings_param ;app ['i18n']=i18n_instance
        app ['yookassa_service']=yookassa_service ;app ['panel_service']=panel_service ;app ['subscription_service']=subscription_service
        app ['referral_service']=referral_service ;app ['promo_code_service']=promo_code_service
        setup_application (app ,dp ,bot =bot );logging .info ("AIOHTTP app context populated and dispatcher lifecycle linked.")
        if telegram_uses_webhook :telegram_webhook_path =f"/{settings_param.BOT_TOKEN}";app .router .add_post (telegram_webhook_path ,SimpleRequestHandler (dispatcher =dp ,bot =bot ));logging .info (f"Telegram webhook route: {telegram_webhook_path}.")
        if yk_webhook_base and settings_param .yookassa_webhook_path :app .router .add_post (settings_param .yookassa_webhook_path ,user_payment_webhook_module .yookassa_webhook_route );logging .info (f"YK webhook route: {settings_param.yookassa_webhook_path}")
        web_app_runner =web .AppRunner (app );await web_app_runner .setup ();site =web .TCPSite (web_app_runner ,host =settings_param .WEB_SERVER_HOST ,port =settings_param .WEB_SERVER_PORT )
        async def web_server_task_wrapper ():await site .start ();logging .info (f"AIOHTTP server started on {settings_param.WEB_SERVER_HOST}:{settings_param.WEB_SERVER_PORT}.");await asyncio .Event ().wait ()if not telegram_should_poll else await asyncio .sleep (31536000 )
        main_tasks_to_await .append (asyncio .create_task (web_server_task_wrapper (),name ="AIOHTTPServerWrapperTask"))
    if telegram_should_poll :logging .info ("TG polling task created.");main_tasks_to_await .append (asyncio .create_task (dp .start_polling (bot ,allowed_updates =dp .resolve_used_update_types ()),name ="TelegramPollingTask"))
    if not main_tasks_to_await :logging .error ("Bot not configured for any mode.");await dp .emit_shutdown ();return
    logging .info (f"Starting bot with main tasks: {[task.get_name() for task in main_tasks_to_await]}")
    try :
        if main_tasks_to_await :await asyncio .gather (*main_tasks_to_await )
    except (KeyboardInterrupt ,SystemExit ,asyncio .CancelledError )as e :logging .info (f"Main loop interrupted: {type(e).__name__}")
    finally :
        logging .info ("Initiating final shutdown sequence...");
        for task in main_tasks_to_await :
            if task and not task .done ():task .cancel ();
            try :await task
            except asyncio .CancelledError :logging .info (f"Task '{task.get_name()}' cancelled.")
            except Exception as e_cancel :logging .error (f"Error cancelling task '{task.get_name()}': {e_cancel}",exc_info =True )
        if web_app_runner :await web_app_runner .cleanup ();logging .info ("AIOHTTP AppRunner cleaned up.")
        if not (telegram_should_poll and len (main_tasks_to_await )==1 and any (t .get_name ()=="TelegramPollingTask"for t in main_tasks_to_await if t and not t .done ())):
            logging .info ("Explicitly calling dp.emit_shutdown() in run_bot finally.")
            await dp .emit_shutdown ()
        if bot .session and not bot .session .closed :await bot .session .close ()
        logging .info ("Bot run_bot function finished.")