import logging
import json
import aiosqlite
import asyncio
from datetime import datetime ,timezone
from typing import Optional ,Dict ,Any

from aiohttp import web
from aiogram import Bot
from yookassa .domain .notification import WebhookNotification
from yookassa .domain .models import Amount

from db .database import get_db_connection_manager ,_setup_db_connection ,get_user
from bot .services .subscription_service import SubscriptionService
from bot .services .referral_service import ReferralService
from bot .services .panel_api_service import PanelApiService
from bot .middlewares .i18n import JsonI18n
from config .settings import Settings
from bot .services .payment_service import YooKassaService

payment_processing_lock =asyncio .Lock ()

YOOKASSA_EVENT_PAYMENT_SUCCEEDED ='payment.succeeded'
YOOKASSA_EVENT_PAYMENT_CANCELED ='payment.canceled'
YOOKASSA_EVENT_PAYMENT_WAITING_FOR_CAPTURE ='payment.waiting_for_capture'
YOOKASSA_EVENT_REFUND_SUCCEEDED ='refund.succeeded'

async def process_successful_payment (
bot :Bot ,payment_info_from_webhook :dict ,i18n :JsonI18n ,
settings :Settings ,panel_service :PanelApiService ,yk_service :YooKassaService ,
subscription_service :SubscriptionService ,
referral_service :ReferralService
):
    metadata =payment_info_from_webhook .get ("metadata",{})
    user_id_str =metadata .get ("user_id")
    subscription_months_str =metadata .get ("subscription_months")
    promo_code_id_str =metadata .get ("promo_code_id")
    payment_db_id_str =metadata .get ("payment_db_id")

    if not user_id_str or not subscription_months_str or not payment_db_id_str :
        logging .error (f"Missing crucial metadata for payment: {payment_info_from_webhook.get('id')}, metadata: {metadata}")
        return
    try :
        user_id =int (user_id_str );subscription_months =int (subscription_months_str )
        payment_db_id =int (payment_db_id_str )
        promo_code_id =int (promo_code_id_str )if promo_code_id_str and promo_code_id_str .isdigit ()else None
        amount_data =payment_info_from_webhook .get ("amount",{});
        payment_value =float (amount_data .get ("value",0.0 ))
    except (TypeError ,ValueError )as e :
        logging .error (f"Invalid metadata format for payment processing: {metadata} - {e}")
        return

    final_end_date_for_user :Optional [datetime ]=None
    applied_referee_bonus_days :Optional [int ]=None
    base_subscription_end_date :Optional [datetime ]=None

    async with get_db_connection_manager ()as db :
        await _setup_db_connection (db )
        try :
            await db .execute ("UPDATE payments SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE payment_id = ? AND (yookassa_payment_id = ? OR yookassa_payment_id IS NULL)",(payment_info_from_webhook .get ("status","succeeded"),payment_db_id ,payment_info_from_webhook .get ("id")))

            new_sub_details =await subscription_service .activate_subscription (user_id ,subscription_months ,payment_value ,payment_db_id ,db_conn =db ,promo_code_id =promo_code_id )

            if new_sub_details and new_sub_details .get ('end_date'):
                base_subscription_end_date =new_sub_details ['end_date']
                final_end_date_for_user =base_subscription_end_date

                referral_bonus_info =await referral_service .apply_referral_bonuses_for_payment (user_id ,subscription_months ,db_conn =db )

                if referral_bonus_info and referral_bonus_info .get ("referee_new_end_date"):
                    final_end_date_for_user =referral_bonus_info ["referee_new_end_date"]
                    applied_referee_bonus_days =referral_bonus_info .get ("referee_bonus_applied_days")

                await db .commit ()

                user_lang =await subscription_service .get_user_language (user_id )
                _ =lambda key ,**kwargs :i18n .gettext (user_lang ,key ,**kwargs )

                success_message =""
                if applied_referee_bonus_days and final_end_date_for_user :
                    referee_user_data =await get_user (user_id )
                    inviter_name_for_msg =_ ("friend_placeholder")

                    if referee_user_data and referee_user_data ['referred_by_id']is not None :
                        inviter_user_data_for_msg =await get_user (referee_user_data ['referred_by_id'])
                        if inviter_user_data_for_msg and inviter_user_data_for_msg ['first_name']:
                            inviter_name_for_msg =inviter_user_data_for_msg ['first_name']

                    success_message =_ ("payment_successful_with_referral_bonus",
                    months =subscription_months ,
                    base_end_date =base_subscription_end_date .strftime ('%Y-%m-%d')if base_subscription_end_date else "N/A",
                    bonus_days =applied_referee_bonus_days ,
                    final_end_date =final_end_date_for_user .strftime ('%Y-%m-%d'),
                    inviter_name =inviter_name_for_msg
                    )
                elif final_end_date_for_user :
                    success_message =_ ("payment_successful",
                    months =subscription_months ,
                    end_date =final_end_date_for_user .strftime ('%Y-%m-%d')
                    )
                else :
                    logging .error (f"Critical error: final_end_date_for_user is None for user {user_id}")
                    success_message =_ ("payment_successful_error_details")

                try :await bot .send_message (user_id ,success_message )
                except Exception as e :logging .error (f"Failed to send final payment success message to user {user_id}: {e}")
            else :
                logging .error (f"Failed to activate subscription for user {user_id} after payment {payment_info_from_webhook.get('id')}")
                await db .rollback ()
        except Exception as e :
            logging .error (f"Error during process_successful_payment transaction for user {user_id}: {e}",exc_info =True )
            await db .rollback ()
            try :
                user_lang_for_error =await subscription_service .get_user_language (user_id )
                _err =lambda key ,**kwargs :i18n .gettext (user_lang_for_error ,key ,**kwargs )
                await bot .send_message (user_id ,_err ("error_processing_your_payment"))
            except Exception as notify_err :logging .error (f"Failed to send error notification to user {user_id}: {notify_err}")


async def process_cancelled_payment (bot :Bot ,payment_info_from_webhook :dict ,i18n :JsonI18n ,settings :Settings ):
    metadata =payment_info_from_webhook .get ("metadata",{})
    user_id_str =metadata .get ("user_id");payment_db_id_str =metadata .get ("payment_db_id")
    if not user_id_str or not payment_db_id_str :logging .warning (f"Missing metadata in cancelled payment: {payment_info_from_webhook.get('id')}");return
    try :user_id =int (user_id_str );payment_db_id =int (payment_db_id_str )
    except ValueError :logging .error (f"Invalid metadata in cancelled payment: {metadata}");return
    async with get_db_connection_manager ()as db :
        await _setup_db_connection (db )
        await db .execute ("UPDATE payments SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE payment_id = ? AND (yookassa_payment_id = ? OR yookassa_payment_id IS NULL)",(payment_info_from_webhook .get ("status","canceled"),payment_db_id ,payment_info_from_webhook .get ("id")))
        await db .commit ()
    user_lang =getattr (settings ,'DEFAULT_LANGUAGE','en')
    _ =lambda key ,**kwargs :i18n .gettext (user_lang ,key ,**kwargs )
    try :await bot .send_message (user_id ,_ ("payment_failed"))
    except Exception as e :logging .error (f"Failed to send payment cancellation message to user {user_id}: {e}")

async def yookassa_webhook_route (request :web .Request ):
    logging .info (f"YooKassa Webhook Route: Available keys in request.app: {list(request.app.keys())}")
    try :
        bot :Bot =request .app ['bot'];i18n_instance :JsonI18n =request .app ['i18n'];settings :Settings =request .app ['settings']
        yk_service :YooKassaService =request .app ['yookassa_service'];panel_service :PanelApiService =request .app ['panel_service']
        subscription_service :SubscriptionService =request .app ['subscription_service']
        referral_service :ReferralService =request .app ['referral_service']
    except KeyError as e :logging .error (f"KeyError accessing app context in yookassa_webhook_route: {e}.",exc_info =True );return web .Response (status =500 ,text ="Internal Server Error: Missing app context")
    try :
        event_json =await request .json ();notification_object =WebhookNotification (event_json )
        payment_data_from_notification =notification_object .object
        logging .info (f"YooKassa Webhook Parsed: Event='{notification_object.event}', PaymentId='{payment_data_from_notification.id}', Status='{payment_data_from_notification.status}'")
        if not payment_data_from_notification or not hasattr (payment_data_from_notification ,'metadata')or payment_data_from_notification .metadata is None :
            logging .error (f"YooKassa webhook payment {payment_data_from_notification.id} lacks metadata.");return web .Response (status =200 ,text ="ok_error_no_metadata")
        payment_dict_for_processing ={}
        if hasattr (payment_data_from_notification ,'model_dump'):
            payment_dict_for_processing =payment_data_from_notification .model_dump (exclude_none =True )
            if 'amount'in payment_dict_for_processing and isinstance (payment_dict_for_processing ['amount'],Amount ):amount_obj =payment_dict_for_processing ['amount'];payment_dict_for_processing ['amount']={"value":str (amount_obj .value ),"currency":str (amount_obj .currency )}
            elif 'amount'in payment_dict_for_processing and not isinstance (payment_dict_for_processing ['amount'],dict ):amount_obj_original =payment_data_from_notification .amount ;payment_dict_for_processing ['amount']={"value":str (amount_obj_original .value ),"currency":str (amount_obj_original .currency )}if hasattr (amount_obj_original ,'value')and hasattr (amount_obj_original ,'currency')else {"value":"0.0","currency":"RUB"}
        elif hasattr (payment_data_from_notification ,'amount')and hasattr (payment_data_from_notification .amount ,'value')and hasattr (payment_data_from_notification .amount ,'currency'):amount_obj =payment_data_from_notification .amount ;payment_dict_for_processing ={"id":str (payment_data_from_notification .id ),"status":str (payment_data_from_notification .status ),"paid":bool (payment_data_from_notification .paid ),"amount":{"value":str (amount_obj .value ),"currency":str (amount_obj .currency )},"metadata":dict (payment_data_from_notification .metadata )if payment_data_from_notification .metadata else {},"description":str (payment_data_from_notification .description )if payment_data_from_notification .description else None }
        else :logging .error (f"Could not serialize payment_data for payment {payment_data_from_notification.id}");return web .Response (status =200 ,text ="ok_error_serialization")
        async with payment_processing_lock :
            if notification_object .event ==YOOKASSA_EVENT_PAYMENT_SUCCEEDED :
                if payment_dict_for_processing .get ("paid")and payment_dict_for_processing .get ("status")=="succeeded":
                    await process_successful_payment (bot ,payment_dict_for_processing ,i18n_instance ,settings ,panel_service ,yk_service ,subscription_service ,referral_service )
                else :logging .warning (f"Payment Succeeded event for {payment_dict_for_processing.get('id')} but data not ok: status='{payment_dict_for_processing.get('status')}', paid='{payment_dict_for_processing.get('paid')}'")
            elif notification_object .event ==YOOKASSA_EVENT_PAYMENT_CANCELED :
                await process_cancelled_payment (bot ,payment_dict_for_processing ,i18n_instance ,settings )
        return web .Response (status =200 ,text ="ok")
    except json .JSONDecodeError :logging .error ("YooKassa Webhook: Invalid JSON.");return web .Response (status =200 ,text ="ok_invalid_json")
    except KeyError as e :logging .error (f"KeyError in yookassa_webhook_route after initial context access: {e}.",exc_info =True );return web .Response (status =500 ,text ="Internal Server Error: Context error post-access")
    except Exception as e :logging .error (f"YooKassa Webhook processing error: {e}",exc_info =True );return web .Response (status =200 ,text ="ok_internal_error")