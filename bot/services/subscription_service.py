import logging
import aiosqlite
from datetime import datetime ,timedelta ,timezone
from typing import Optional ,Dict ,Any ,List ,Callable ,Awaitable

from config .settings import Settings
from db .database import get_db_connection_manager ,_setup_db_connection ,get_user ,has_had_any_subscription as db_has_had_any_subscription
from .panel_api_service import PanelApiService


if False :
    from .referral_service import ReferralService

class SubscriptionService :
    def __init__ (self ,db_conn_provider :Callable [[],Any ],settings :Settings ,panel_service :PanelApiService ):
        self .db_conn_provider =db_conn_provider
        self .settings =settings
        self .panel_service =panel_service

    async def _get_db (self ,existing_conn :Optional [aiosqlite .Connection ]=None )->tuple [aiosqlite .Connection ,bool ]:
        """Helper to get a DB connection. Returns (connection, should_manage_flag)."""
        if existing_conn :
            return existing_conn ,False

        conn_manager =self .db_conn_provider ()
        conn =await conn_manager .__aenter__ ()
        try :
            await _setup_db_connection (conn )
        except Exception as e :
            await conn_manager .__aexit__ (type (e ),e ,e .__traceback__ )
            raise
        return conn ,True

    async def _release_db (self ,db :aiosqlite .Connection ,should_manage :bool ,exc_type =None ,exc_val =None ,exc_tb =None ):
        """Helper to release/close a DB connection if this service instance opened it."""
        if should_manage :
            await db .__aexit__ (exc_type ,exc_val ,exc_tb )

    async def get_user_language (self ,user_id :int )->str :
        """Fetches the user's language preference from the local database."""
        db ,should_manage =await self ._get_db ()
        try :
            user_record =await get_user (user_id ,db_conn =db )
            default_lang =self .settings .DEFAULT_LANGUAGE
            return user_record ['language_code']if user_record and 'language_code'in user_record .keys ()and user_record ['language_code']else default_lang
        finally :
            await self ._release_db (db ,should_manage )

    async def get_panel_user_uuid (self ,user_id :int ,db_conn :Optional [aiosqlite .Connection ]=None )->Optional [str ]:
        """Fetches panel_user_uuid for a given Telegram user_id from local DB."""
        db_to_use ,should_manage_this_conn =await self ._get_db (db_conn )
        try :
            user_record =await get_user (user_id ,db_conn =db_to_use )
            return user_record ['panel_user_uuid']if user_record and 'panel_user_uuid'in user_record .keys ()and user_record ['panel_user_uuid']else None
        finally :
            await self ._release_db (db_to_use ,should_manage_this_conn )

    async def has_had_any_subscription (self ,user_id :int ,db_conn :Optional [aiosqlite .Connection ]=None )->bool :
        """Checks if the user has any record in the subscriptions table."""
        db_to_use ,should_manage_this_conn =await self ._get_db (db_conn )
        try :
            return await db_has_had_any_subscription (user_id ,db_conn =db_to_use )
        finally :
            await self ._release_db (db_to_use ,should_manage_this_conn )

    async def activate_trial_subscription (self ,user_id :int )->Optional [Dict [str ,Any ]]:
        """
        Activates a trial subscription for an eligible user.
        Manages its own database connection and transaction.
        Returns dict with trial details or specific error dict on failure/ineligibility.
        """
        if not self .settings .TRIAL_ENABLED or self .settings .TRIAL_DURATION_DAYS <=0 :
            logging .info (f"Trial subscription feature is disabled or duration invalid for user {user_id}.")
            return {"eligible":False ,"activated":False ,"message_key":"trial_feature_disabled"}

        async with self .db_conn_provider ()as db :
            await _setup_db_connection (db )
            try :
                if await db_has_had_any_subscription (user_id ,db_conn =db ):
                    logging .info (f"User {user_id} has prior subscriptions. Trial not applicable.")
                    return {"eligible":False ,"activated":False ,"message_key":"trial_not_eligible_already_subscribed"}

                panel_user_uuid =await self .get_panel_user_uuid (user_id ,db_conn =db )
                panel_subscription_uuid_for_link =None ;panel_short_uuid_for_link =None
                panel_user_interacted_now =False ;specific_inbounds =self .settings .parsed_default_panel_user_inbound_uuids
                panel_actual_subscription_url :Optional [str ]=None

                if not panel_user_uuid :
                    logging .info (f"No panel_user_uuid for TG user_id {user_id} for trial. Creating panel user.")
                    panel_username_to_create =f"tg_{user_id}"
                    creation_response =await self .panel_service .create_panel_user (
                    username =panel_username_to_create ,telegram_id =user_id ,
                    default_expire_days =self .settings .TRIAL_DURATION_DAYS ,
                    default_traffic_limit_bytes =self .settings .trial_traffic_limit_bytes ,
                    default_traffic_limit_strategy =self .settings .PANEL_USER_DEFAULT_TRAFFIC_STRATEGY ,
                    specific_inbound_uuids =specific_inbounds ,
                    activate_all_inbounds_default_flag =False if specific_inbounds else True
                    )
                    panel_user_obj_from_api =None
                    if creation_response and not creation_response .get ("error"):panel_user_obj_from_api =creation_response .get ("response")
                    elif creation_response and creation_response .get ("errorCode")=="A019":
                        existing_users_list =await self .panel_service .get_users_by_filter (username =panel_username_to_create )
                        if existing_users_list and len (existing_users_list )==1 :panel_user_obj_from_api =existing_users_list [0 ]

                    if panel_user_obj_from_api and panel_user_obj_from_api .get ('uuid'):
                        panel_user_uuid =panel_user_obj_from_api ['uuid']
                        panel_subscription_uuid_for_link =panel_user_obj_from_api .get ('subscriptionUuid')
                        panel_short_uuid_for_link =panel_user_obj_from_api .get ('shortUuid')
                        panel_actual_subscription_url =panel_user_obj_from_api .get ('subscriptionUrl')
                        await db .execute ("UPDATE users SET panel_user_uuid = ? WHERE user_id = ?",(panel_user_uuid ,user_id ))
                        panel_user_interacted_now =True
                        if panel_user_obj_from_api .get ('telegramId')!=user_id :
                            await self .panel_service .update_user_details_on_panel (panel_user_uuid ,{"telegramId":user_id })
                    else :
                        logging .error (f"Failed to create/link panel user for trial (TG_ID {user_id}). Resp: {creation_response if 'creation_response' in locals() else 'N/A'}")
                        await db .rollback ()
                        return {"eligible":True ,"activated":False ,"message_key":"trial_activation_failed"}
                else :
                    panel_user_data =await self .panel_service .get_user_by_uuid (panel_user_uuid )
                    if panel_user_data :
                        panel_subscription_uuid_for_link =panel_user_data .get ('subscriptionUuid')
                        panel_short_uuid_for_link =panel_user_data .get ('shortUuid')
                        panel_actual_subscription_url =panel_user_data .get ('subscriptionUrl')

                if not panel_subscription_uuid_for_link and panel_short_uuid_for_link :
                    panel_subscription_uuid_for_link =panel_short_uuid_for_link
                if not panel_subscription_uuid_for_link :
                    logging .error (f"Critical: panel_subscription_uuid for link is None for trial (panel_uuid {panel_user_uuid}).")
                    await db .rollback ()
                    return {"eligible":True ,"activated":False ,"message_key":"trial_activation_failed"}

                start_date =datetime .now (timezone .utc )
                end_date =start_date +timedelta (days =self .settings .TRIAL_DURATION_DAYS )
                await db .execute ("UPDATE subscriptions SET is_active = 0 WHERE panel_user_uuid = ? AND is_active = 1",(panel_user_uuid ,))
                upsert_sql =""" INSERT INTO subscriptions (user_id, panel_user_uuid, panel_subscription_uuid, start_date, end_date, duration_months, is_active, status_from_panel, traffic_limit_bytes) VALUES (?, ?, ?, ?, ?, 0, 1, 'TRIAL', ?) ON CONFLICT(panel_subscription_uuid) DO UPDATE SET user_id = excluded.user_id, panel_user_uuid = excluded.panel_user_uuid, start_date = excluded.start_date, end_date = excluded.end_date, duration_months = 0, is_active = 1, status_from_panel = 'TRIAL', traffic_limit_bytes = excluded.traffic_limit_bytes, last_notification_sent = NULL; """
                trial_traffic_val =self .settings .trial_traffic_limit_bytes
                params =(user_id ,panel_user_uuid ,panel_subscription_uuid_for_link ,start_date .isoformat (),end_date .isoformat (),trial_traffic_val )

                upsert_cursor =await db .execute (upsert_sql ,params )
                trial_subscription_id =upsert_cursor .lastrowid
                if not trial_subscription_id or trial_subscription_id ==0 :
                    id_fetch_cursor =await db .execute ("SELECT subscription_id FROM subscriptions WHERE panel_subscription_uuid = ?",(panel_subscription_uuid_for_link ,))
                    id_fetch_row =await id_fetch_cursor .fetchone ()
                    if id_fetch_cursor :await id_fetch_cursor .close ()
                    if id_fetch_row :trial_subscription_id =id_fetch_row ['subscription_id']
                logging .info (f"Local trial subscription (ID: {trial_subscription_id}) for user {user_id} prepared. Ends: {end_date.isoformat()}.")

                panel_update_payload :Dict [str ,Any ]={"uuid":panel_user_uuid ,"expireAt":end_date .isoformat (timespec ='milliseconds').replace ('+00:00','Z'),"status":"ACTIVE","trafficLimitBytes":trial_traffic_val ,"trafficLimitStrategy":self .settings .PANEL_USER_DEFAULT_TRAFFIC_STRATEGY ,}
                if specific_inbounds :panel_update_payload ["activeUserInbounds"]=specific_inbounds
                elif panel_user_interacted_now :panel_update_payload ["activateAllInbounds"]=True

                updated_panel_user =await self .panel_service .update_user_details_on_panel (panel_user_uuid ,panel_update_payload )
                if not updated_panel_user :logging .warning (f"Panel user details update FAILED for trial user {panel_user_uuid}.")
                else :
                    logging .info (f"Panel user {panel_user_uuid} details updated for trial. Panel ExpireAt: {updated_panel_user.get('expireAt')}")
                    if updated_panel_user .get ('subscriptionUrl'):panel_actual_subscription_url =updated_panel_user .get ('subscriptionUrl')
                    if updated_panel_user .get ('shortUuid'):panel_short_uuid_for_link =updated_panel_user .get ('shortUuid')

                await db .commit ()
                return {"eligible":True ,"activated":True ,"end_date":end_date ,"days":self .settings .TRIAL_DURATION_DAYS ,"traffic_gb":self .settings .TRIAL_TRAFFIC_LIMIT_GB ,"panel_user_uuid":panel_user_uuid ,"panel_short_uuid":panel_short_uuid_for_link ,"subscription_url":panel_actual_subscription_url }
            except Exception as e :
                logging .error (f"Error activating trial for user {user_id}: {e}",exc_info =True )
                await db .rollback ()
                return {"eligible":True ,"activated":False ,"message_key":"trial_activation_failed"}

    async def activate_subscription (
    self ,user_id :int ,months :int ,payment_amount :float ,
    payment_id_internal :int ,db_conn :aiosqlite .Connection ,
    promo_code_id :Optional [int ]=None
    )->Optional [Dict [str ,Any ]]:
        db =db_conn
        try :
            panel_user_uuid =await self .get_panel_user_uuid (user_id ,db_conn =db )
            panel_subscription_uuid_for_link =None ;panel_short_uuid_for_link =None ;panel_user_interacted_now =False
            panel_actual_subscription_url :Optional [str ]=None
            specific_inbounds_from_settings =self .settings .parsed_default_panel_user_inbound_uuids
            if not panel_user_uuid :
                panel_username_to_create =f"tg_{user_id}"
                creation_response =await self .panel_service .create_panel_user (username =panel_username_to_create ,telegram_id =user_id ,default_expire_days =self .settings .PANEL_USER_DEFAULT_EXPIRE_DAYS ,default_traffic_limit_bytes =self .settings .PANEL_USER_DEFAULT_TRAFFIC_BYTES ,default_traffic_limit_strategy =self .settings .PANEL_USER_DEFAULT_TRAFFIC_STRATEGY ,specific_inbound_uuids =specific_inbounds_from_settings ,activate_all_inbounds_default_flag =False if specific_inbounds_from_settings else True )
                panel_user_object_from_api =None
                if creation_response and not creation_response .get ("error"):panel_user_object_from_api =creation_response .get ("response")
                elif creation_response and creation_response .get ("errorCode")=="A019":
                    existing_users_list =await self .panel_service .get_users_by_filter (username =panel_username_to_create )
                    if existing_users_list and len (existing_users_list )==1 :panel_user_object_from_api =existing_users_list [0 ]
                if panel_user_object_from_api and panel_user_object_from_api .get ('uuid'):
                    panel_user_uuid =panel_user_object_from_api ['uuid'];panel_subscription_uuid_for_link =panel_user_object_from_api .get ('subscriptionUuid');panel_short_uuid_for_link =panel_user_object_from_api .get ('shortUuid');panel_actual_subscription_url =panel_user_object_from_api .get ('subscriptionUrl')
                    cursor_conflict =await db .execute ("SELECT user_id FROM users WHERE panel_user_uuid = ? AND user_id != ?",(panel_user_uuid ,user_id ));conflicting_tg_user =await cursor_conflict .fetchone ();await cursor_conflict .close ()
                    if conflicting_tg_user :logging .error (f"CRITICAL CONFLICT: Panel UUID {panel_user_uuid} already linked to TG user {conflicting_tg_user['user_id']}.");return None
                    await db .execute ("UPDATE users SET panel_user_uuid = ? WHERE user_id = ?",(panel_user_uuid ,user_id ));panel_user_interacted_now =True
                    if panel_user_object_from_api .get ('telegramId')!=user_id :await self .panel_service .update_user_details_on_panel (panel_user_uuid ,{"telegramId":user_id })
                else :logging .error (f"Failed to create/link panel user for TG_ID {user_id}. Resp: {creation_response if 'creation_response' in locals() else 'N/A'}");return None
            else :
                panel_user_data =await self .panel_service .get_user_by_uuid (panel_user_uuid )
                if panel_user_data :panel_subscription_uuid_for_link =panel_user_data .get ('subscriptionUuid');panel_short_uuid_for_link =panel_user_data .get ('shortUuid');panel_actual_subscription_url =panel_user_data .get ('subscriptionUrl')
            if not panel_subscription_uuid_for_link and panel_short_uuid_for_link :panel_subscription_uuid_for_link =panel_short_uuid_for_link
            if not panel_subscription_uuid_for_link :logging .error (f"Critical: panel_subscription_uuid for link is None for panel_user_uuid {panel_user_uuid}.");return None

            cursor =await db .execute ("SELECT subscription_id, end_date FROM subscriptions WHERE panel_user_uuid = ? AND is_active = 1 ORDER BY end_date DESC LIMIT 1",(panel_user_uuid ,));current_sub_row =await cursor .fetchone ();await cursor .close ()
            current_sub_end_date_str =current_sub_row ['end_date']if current_sub_row else None ;start_date =datetime .now (timezone .utc )
            if current_sub_end_date_str :
                try :
                    parsed_current_end_date =datetime .fromisoformat (current_sub_end_date_str .replace ("Z","+00:00"))
                    if parsed_current_end_date .tzinfo is None :parsed_current_end_date =parsed_current_end_date .replace (tzinfo =timezone .utc )
                    if parsed_current_end_date >start_date :start_date =parsed_current_end_date
                except ValueError :logging .warning (f"Bad current_sub_end_date string: {current_sub_end_date_str} for panel_user {panel_user_uuid}.")
            final_end_date =start_date +timedelta (days =months *30 )
            if promo_code_id :
                promo_cursor =await db .execute ("SELECT bonus_days FROM promo_codes WHERE promo_code_id = ?",(promo_code_id ,));promo_row =await promo_cursor .fetchone ();await promo_cursor .close ()
                if promo_row :final_end_date +=timedelta (days =promo_row ['bonus_days']);await db .execute ("INSERT OR IGNORE INTO promo_code_activations (promo_code_id, user_id, payment_id) VALUES (?, ?, ?)",(promo_code_id ,user_id ,payment_id_internal ));await db .execute ("UPDATE promo_codes SET current_activations = current_activations + 1 WHERE promo_code_id = ?",(promo_code_id ,))

            await db .execute ("UPDATE subscriptions SET is_active = 0 WHERE panel_user_uuid = ? AND is_active = 1",(panel_user_uuid ,))
            upsert_sql =""" INSERT INTO subscriptions (user_id, panel_user_uuid, panel_subscription_uuid, start_date, end_date, duration_months, is_active, status_from_panel) VALUES (?, ?, ?, ?, ?, ?, 1, 'ACTIVE') ON CONFLICT(panel_subscription_uuid) DO UPDATE SET user_id = excluded.user_id, panel_user_uuid = excluded.panel_user_uuid, start_date = excluded.start_date, end_date = excluded.end_date, duration_months = excluded.duration_months, is_active = 1, status_from_panel = 'ACTIVE', last_notification_sent = NULL; """
            params =(user_id ,panel_user_uuid ,panel_subscription_uuid_for_link ,start_date .isoformat (),final_end_date .isoformat (),months )
            upsert_cursor =await db .execute (upsert_sql ,params );subscription_id_to_return =upsert_cursor .lastrowid
            if not subscription_id_to_return or subscription_id_to_return ==0 :
                id_cursor =await db .execute ("SELECT subscription_id FROM subscriptions WHERE panel_subscription_uuid = ?",(panel_subscription_uuid_for_link ,));id_row =await id_cursor .fetchone ();await id_cursor .close ()
                if id_row :subscription_id_to_return =id_row ['subscription_id']
            logging .info (f"Local subscription UPSERTED (ID: {subscription_id_to_return}) for user {user_id}. Ends: {final_end_date.isoformat()}.")

            panel_update_payload :Dict [str ,Any ]={"uuid":panel_user_uuid ,"expireAt":final_end_date .isoformat (timespec ='milliseconds').replace ('+00:00','Z'),"status":"ACTIVE","trafficLimitBytes":self .settings .PANEL_USER_DEFAULT_TRAFFIC_BYTES ,"trafficLimitStrategy":self .settings .PANEL_USER_DEFAULT_TRAFFIC_STRATEGY }
            if specific_inbounds_from_settings :panel_update_payload ["activeUserInbounds"]=specific_inbounds_from_settings
            elif panel_user_interacted_now :panel_update_payload ["activateAllInbounds"]=True
            if "activateAllInbounds"in panel_update_payload and not specific_inbounds_from_settings and not panel_user_interacted_now :del panel_update_payload ["activateAllInbounds"]
            logging .info (f"Attempting to update panel user {panel_user_uuid} for paid sub: {panel_update_payload}")
            updated_panel_user =await self .panel_service .update_user_details_on_panel (panel_user_uuid ,panel_update_payload )
            if not updated_panel_user :logging .warning (f"Panel user details update FAILED for {panel_user_uuid}.")
            else :
                logging .info (f"Panel user {panel_user_uuid} details updated. Panel ExpireAt: {updated_panel_user.get('expireAt')}")
                if updated_panel_user .get ('subscriptionUrl'):panel_actual_subscription_url =updated_panel_user .get ('subscriptionUrl')
                if updated_panel_user .get ('shortUuid'):panel_short_uuid_for_link =updated_panel_user .get ('shortUuid')
            return {"subscription_id":subscription_id_to_return ,"end_date":final_end_date ,"is_active":True ,"panel_user_uuid":panel_user_uuid ,"panel_short_uuid":panel_short_uuid_for_link ,"subscription_url":panel_actual_subscription_url }
        except Exception as e :logging .error (f"Error in activate_subscription (paid) for user {user_id}: {e}",exc_info =True );return None

    async def extend_active_subscription_days (self ,user_id :int ,bonus_days :int ,db_conn :aiosqlite .Connection ,reason :str ="bonus")->Optional [datetime ]:
        db =db_conn
        try :
            user_cursor =await db .execute ("SELECT panel_user_uuid FROM users WHERE user_id = ?",(user_id ,))
            user_panel_data =await user_cursor .fetchone ()
            if user_cursor :await user_cursor .close ()
            panel_user_uuid_for_update =user_panel_data ['panel_user_uuid']if user_panel_data and 'panel_user_uuid'in user_panel_data .keys ()and user_panel_data ['panel_user_uuid']else None

            sql_select_active_sub ="SELECT subscription_id, end_date FROM subscriptions WHERE user_id = ? AND is_active = 1 "
            params_select_active_sub :tuple =(user_id ,)
            if panel_user_uuid_for_update :
                sql_select_active_sub +="AND panel_user_uuid = ? "
                params_select_active_sub +=(panel_user_uuid_for_update ,)
            else :
                logging .warning (f"Extending subscription for user {user_id} without panel_user_uuid. This might be ambiguous if user has multiple panel accounts linked to one TG ID (not typical).")
            sql_select_active_sub +="ORDER BY end_date DESC LIMIT 1"

            cursor =await db .execute (sql_select_active_sub ,params_select_active_sub )
            active_sub_row =await cursor .fetchone ()
            if cursor :await cursor .close ()

            if not active_sub_row or not active_sub_row ['end_date']:
                logging .info (f"No active subscription found for user {user_id} (panel UUID: {panel_user_uuid_for_update}) to extend with {reason} bonus.")
                return None

            current_end_date_str =active_sub_row ['end_date']
            try :
                current_end_date =datetime .fromisoformat (current_end_date_str .replace ("Z","+00:00"))if isinstance (current_end_date_str ,str )else current_end_date_str
                if not isinstance (current_end_date ,datetime ):
                    raise ValueError ("current_end_date is not a datetime object after parsing")
            except ValueError as ve :
                logging .error (f"Error parsing current_end_date '{current_end_date_str}' for user {user_id}: {ve}")
                return None

            if current_end_date .tzinfo is None :
                current_end_date =current_end_date .replace (tzinfo =timezone .utc )

            now_utc =datetime .now (timezone .utc )
            start_point_for_bonus =current_end_date if current_end_date >now_utc else now_utc
            new_end_date =start_point_for_bonus +timedelta (days =bonus_days )

            await db .execute ("UPDATE subscriptions SET end_date = ?, last_notification_sent = NULL WHERE subscription_id = ?",(new_end_date .isoformat (),active_sub_row ['subscription_id']))
            logging .info (f"Subscription for user {user_id} extended by {bonus_days} days ({reason}). New end date: {new_end_date.isoformat()}")

            if panel_user_uuid_for_update :
                panel_update_payload ={"uuid":panel_user_uuid_for_update ,"expireAt":new_end_date .isoformat (timespec ='milliseconds').replace ('+00:00','Z')}
                if not await self .panel_service .update_user_details_on_panel (panel_user_uuid_for_update ,panel_update_payload ):
                    logging .warning (f"Failed to update panel expiry for {panel_user_uuid_for_update} after {reason} bonus.")
            return new_end_date
        except Exception as e :
            logging .error (f"Error extending subscription with {reason} bonus for user {user_id} (using provided db_conn): {e}",exc_info =True )
            return None

    async def extend_subscription_for_referral (self ,user_id :int ,bonus_days :int ,db_conn :aiosqlite .Connection ,is_referee_bonus :bool =False )->Optional [datetime ]:
        reason ="referee bonus"if is_referee_bonus else "inviter referral bonus"
        return await self .extend_active_subscription_days (user_id ,bonus_days ,db_conn ,reason =reason )

    async def get_active_subscription (self ,user_id :int )->Optional [Dict [str ,Any ]]:
        db ,should_manage =await self ._get_db ()
        try :
            now_iso_utc =datetime .now (timezone .utc ).isoformat ()
            cursor =await db .execute ("""SELECT s.subscription_id, s.panel_subscription_uuid, s.panel_user_uuid, s.start_date, s.end_date, s.duration_months, s.is_active, s.status_from_panel, s.traffic_limit_bytes, s.traffic_used_bytes, u.username as bot_username FROM subscriptions s LEFT JOIN users u ON s.user_id = u.user_id WHERE s.user_id = ? AND s.is_active = 1 AND s.end_date > ? ORDER BY s.end_date DESC LIMIT 1""",(user_id ,now_iso_utc ))
            sub_row =await cursor .fetchone ();await cursor .close ()
            if sub_row :
                sub_dict =dict (sub_row )
                for date_key in ['start_date','end_date']:
                    if sub_dict .get (date_key )and isinstance (sub_dict [date_key ],str ):
                        try :sub_dict [date_key ]=datetime .fromisoformat (sub_dict [date_key ].replace ("Z","+00:00"))
                        except ValueError :logging .warning (f"Could not parse date string {sub_dict[date_key]} for key {date_key} in get_active_subscription")
                return sub_dict
            return None
        finally :await self ._release_db (db ,should_manage )

    async def get_subscriptions_ending_soon (self ,days_threshold :int )->List [Dict [str ,Any ]]:
        db ,should_manage =await self ._get_db ()
        try :
            now_utc =datetime .now (timezone .utc )
            threshold_date =now_utc +timedelta (days =days_threshold )
            today_date_str =now_utc .strftime ('%Y-%m-%d')
            query =""" SELECT s.user_id, u.first_name, u.language_code, s.end_date as end_date_raw, strftime('%Y-%m-%d', s.end_date) as end_date_str FROM subscriptions s JOIN users u ON s.user_id = u.user_id WHERE s.is_active = 1 AND s.end_date BETWEEN ? AND ? AND (s.last_notification_sent IS NULL OR s.last_notification_sent < ?) ORDER BY s.end_date ASC """
            cursor =await db .execute (query ,(now_utc .isoformat (),threshold_date .isoformat (),today_date_str ));rows =await cursor .fetchall ();await cursor .close ()
            processed_rows =[]
            for row_data in rows :
                row_dict =dict (row_data );end_date_obj_for_calc =None
                if isinstance (row_dict ['end_date_raw'],str ):
                    try :
                        end_date_obj_for_calc =datetime .fromisoformat (row_dict ['end_date_raw'].replace ("Z","+00:00"))
                        if end_date_obj_for_calc .tzinfo is None :end_date_obj_for_calc =end_date_obj_for_calc .replace (tzinfo =timezone .utc )
                        row_dict ['days_left']=(end_date_obj_for_calc -now_utc ).total_seconds ()/(24 *3600 )
                    except ValueError :row_dict ['days_left']=None
                else :row_dict ['days_left']=None
                processed_rows .append (row_dict )
            return processed_rows
        finally :await self ._release_db (db ,should_manage )

    async def update_last_notification_sent (self ,user_id :int ,subscription_end_date_iso :str ):
        db ,should_manage =await self ._get_db ()
        try :
            today_iso_date_str =datetime .now (timezone .utc ).strftime ('%Y-%m-%d')
            await db .execute ("UPDATE subscriptions SET last_notification_sent = ? WHERE user_id = ? AND is_active = 1 AND end_date = ?",(today_iso_date_str ,user_id ,subscription_end_date_iso ))
            await db .commit ()
        except Exception as e :logging .error (f"Error updating last_notification_sent for {user_id} and end_date {subscription_end_date_iso}: {e}");await db .rollback ()
        finally :await self ._release_db (db ,should_manage )