import uuid
import logging
from yookassa import Configuration, Payment
from yookassa.domain.request.payment_request_builder import PaymentRequestBuilder

from typing import Optional, Dict, Any, List

from config.settings import Settings


class YooKassaService:

    def __init__(self,
                 shop_id: Optional[str],
                 secret_key: Optional[str],
                 configured_return_url: Optional[str],
                 bot_username_for_default: Optional[str] = None,
                 settings_obj: Optional[Settings] = None):
        self.settings = settings_obj

        if not shop_id or not secret_key:
            logging.warning(
                "YooKassa SHOP_ID or SECRET_KEY not configured. Payment functionality will be disabled."
            )
            self.configured = False
        else:
            Configuration.account_id = shop_id
            Configuration.secret_key = secret_key
            self.configured = True
            logging.info(f"YooKassa configured for shop_id: {shop_id}")

        if configured_return_url:
            self.return_url = configured_return_url
        elif bot_username_for_default:
            self.return_url = f"https://t.me/{bot_username_for_default}"
            logging.info(
                f"YOOKASSA_RETURN_URL not set, using dynamic default: {self.return_url}"
            )
        else:
            self.return_url = "https://example.com/payment_error_no_return_url"
            logging.warning(
                f"YOOKASSA_RETURN_URL not set AND bot username not provided. Using placeholder: {self.return_url}"
            )
        logging.info(
            f"YooKassa Service effective return_url: {self.return_url}")

    async def create_payment(
            self, amount: float, currency: str, description: str,
            metadata: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self.configured:
            logging.error("YooKassa is not configured. Cannot create payment.")
            return None

        if not self.settings:
            logging.error(
                "YooKassaService: Settings object not available for receipt creation."
            )
            return {
                "error": True,
                "internal_message": "Service settings not initialized."
            }

        if not self.settings.YOOKASSA_DEFAULT_RECEIPT_EMAIL:
            logging.error(
                "CRITICAL: YOOKASSA_DEFAULT_RECEIPT_EMAIL is not configured. YooKassa payment will fail due to missing receipt customer contact."
            )
            return {
                "error":
                True,
                "internal_message":
                "YooKassa receipt email not configured by admin."
            }

        try:
            builder = PaymentRequestBuilder()
            builder.set_amount({
                "value": str(round(amount, 2)),
                "currency": currency.upper()
            })
            builder.set_capture(True)
            builder.set_confirmation({
                "type": "redirect",
                "return_url": self.return_url
            })
            builder.set_description(description)
            builder.set_metadata(metadata)

            receipt_items: List[Dict[str, Any]] = [{
                "description":
                description,
                "quantity":
                "1.00",
                "amount": {
                    "value": str(round(amount, 2)),
                    "currency": currency.upper()
                },
                "vat_code":
                str(self.settings.YOOKASSA_VAT_CODE),
                "payment_mode":
                self.settings.YOOKASSA_PAYMENT_MODE,
                "payment_subject":
                self.settings.YOOKASSA_PAYMENT_SUBJECT
            }]

            receipt_customer: Dict[str, str] = {}
            if self.settings.YOOKASSA_DEFAULT_RECEIPT_EMAIL:
                receipt_customer[
                    "email"] = self.settings.YOOKASSA_DEFAULT_RECEIPT_EMAIL

            if not receipt_customer:
                logging.error(
                    "YooKassa: No customer contact (email/phone) for receipt.")
                return {
                    "error": True,
                    "internal_message": "Receipt customer contact missing."
                }

            receipt_payload: Dict[str, Any] = {
                "customer": receipt_customer,
                "items": receipt_items
            }

            builder.set_receipt(receipt_payload)

            idempotence_key = str(uuid.uuid4())
            payment_request = builder.build()

            logging.info(
                f"Creating YooKassa payment (IDK: {idempotence_key}) with receipt. Email: {self.settings.YOOKASSA_DEFAULT_RECEIPT_EMAIL}"
            )

            res = Payment.create(payment_request, idempotence_key)
            logging.info(
                f"YooKassa Payment.create response: ID={res.id}, Status={res.status}"
            )

            return {
                "id":
                res.id,
                "confirmation_url":
                res.confirmation.confirmation_url
                if res.confirmation else None,
                "status":
                res.status,
                "metadata":
                res.metadata,
                "amount_value":
                float(res.amount.value),
                "amount_currency":
                res.amount.currency,
                "idempotence_key":
                idempotence_key,
                "paid":
                res.paid,
                "refundable":
                res.refundable,
                "created_at":
                res.created_at.isoformat() if hasattr(
                    res.created_at, 'isoformat') else str(res.created_at)
            }
        except Exception as e:
            logging.error(f"YooKassa payment creation failed: {e}",
                          exc_info=True)
            return None

    async def get_payment_info(self,
                               payment_id: str) -> Optional[Dict[str, Any]]:
        if not self.configured:
            logging.error(
                "YooKassa is not configured. Cannot get payment info.")
            return None
        try:
            payment_info = Payment.find_one(payment_id)
            if payment_info:
                return {
                    "id": payment_info.id,
                    "status": payment_info.status,
                    "paid": payment_info.paid,
                    "amount_value": float(payment_info.amount.value),
                    "amount_currency": payment_info.amount.currency,
                    "metadata": payment_info.metadata,
                    "description": payment_info.description,
                }
            return None
        except Exception as e:
            logging.error(
                f"YooKassa get payment info for {payment_id} failed: {e}")
            return None
