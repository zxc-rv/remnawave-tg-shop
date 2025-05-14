import aiohttp
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, timezone

from config.settings import Settings


class PanelApiService:

    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = settings.PANEL_API_URL
        self.api_key = settings.PANEL_API_KEY
        self._session: Optional[aiohttp.ClientSession] = None
        self.default_client_ip = "127.0.0.1"

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close_session(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
            logging.info("Panel API service session closed.")

    async def _prepare_headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "X-Forwarded-Proto": "https",
            "X-Forwarded-For": self.default_client_ip,
            "X-Real-IP": self.default_client_ip,
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        return headers

    async def _request(self, method: str, endpoint: str,
                       **kwargs) -> Optional[Dict[str, Any]]:
        if not self.base_url:
            logging.error("Panel API URL not configured.")
            return {
                "error": True,
                "status_code": 0,
                "message": "Panel API URL not configured."
            }

        session = await self._get_session()
        headers = await self._prepare_headers()

        if "Authorization" not in headers and self.api_key:
            logging.warning(
                f"Authorization header missing for panel endpoint {endpoint} despite API key being set."
            )

        url = f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        json_payload_for_log = kwargs.get('json') if method in [
            "POST", "PATCH", "PUT"
        ] else None
        log_prefix = f"Panel API {method} {url}"
        if json_payload_for_log:
            log_prefix += f" Payload: {json_payload_for_log}"

        try:
            async with session.request(method, url, headers=headers,
                                       **kwargs) as response:
                if 200 <= response.status < 300:
                    try:
                        data = await response.json()
                        logging.debug(
                            f"{log_prefix} - Success ({response.status})")
                        return data
                    except aiohttp.ContentTypeError:
                        logging.debug(
                            f"{log_prefix} - Success ({response.status}) with non-JSON response."
                        )
                        return {
                            "status": "success",
                            "code": response.status,
                            "data_text": await response.text()
                        }
                else:
                    try:
                        error_json = await response.json()
                        logging.error(
                            f"{log_prefix} - Failed ({response.status}): {error_json}"
                        )
                        return {
                            "error": True,
                            "status_code": response.status,
                            "response": error_json,
                            "message": error_json.get("message"),
                            "errorCode": error_json.get("errorCode")
                        }
                    except aiohttp.ContentTypeError:
                        error_text = await response.text()
                        logging.error(
                            f"{log_prefix} - Failed ({response.status}): {error_text}"
                        )
                        return {
                            "error": True,
                            "status_code": response.status,
                            "message": error_text
                        }
        except aiohttp.ClientError as e:
            logging.error(f"Panel API client request error to {url}: {e}")
            return {"error": True, "status_code": -1, "message": str(e)}
        except Exception as e:
            logging.error(f"Unexpected Panel API request error to {url}: {e}",
                          exc_info=True)
            return {
                "error": True,
                "status_code": -2,
                "message": f"Unexpected error: {str(e)}"
            }

    async def get_users_by_filter(
            self,
            username: Optional[str] = None) -> Optional[List[Dict[str, Any]]]:
        """Fetches users from panel by username."""
        if not username:
            logging.warning("get_users_by_filter called without username.")
            return None

        params = {"username": username}
        response_data = await self._request("GET", "/users", params=params)

        if response_data and not response_data.get("error"):
            users_list = response_data.get("response", {}).get("users", [])
            logging.info(
                f"Found {len(users_list)} panel users matching filter: {params}"
            )
            return users_list
        logging.error(
            f"Failed to fetch panel users with filter {params}. Response: {response_data}"
        )
        return None

    async def create_panel_user(
        self,
        username: str,
        telegram_id: Optional[int] = None,
        email: Optional[str] = None,
        default_expire_days: int = 1,
        default_traffic_limit_bytes: int = 0,
        default_traffic_limit_strategy: str = "NO_RESET",
        specific_inbound_uuids: Optional[List[str]] = None,
        activate_all_inbounds_default_flag: bool = True
    ) -> Optional[Dict[str, Any]]:

        if not (6 <= len(username) <= 34
                and username.replace('_', '').replace('-', '').isalnum()):
            msg = f"Username '{username}' for panel does not meet requirements (6-34 chars, alphanumeric, _, -)."
            logging.error(msg)
            return {
                "error": True,
                "status_code": 400,
                "message": msg,
                "response": {
                    "message": msg,
                    "errorCode": "VALIDATION_ERROR"
                }
            }

        now = datetime.now(timezone.utc)
        expire_at_dt = now + timedelta(days=default_expire_days)
        expire_at_iso = expire_at_dt.isoformat(
            timespec='milliseconds').replace('+00:00', 'Z')

        payload: Dict[str, Any] = {
            "username": username,
            "expireAt": expire_at_iso,
            "trafficLimitStrategy": default_traffic_limit_strategy,
            "trafficLimitBytes": default_traffic_limit_bytes,
        }
        if specific_inbound_uuids:
            payload["activeUserInbounds"] = specific_inbound_uuids

            payload["activateAllInbounds"] = False
        else:
            payload["activateAllInbounds"] = activate_all_inbounds_default_flag

        if telegram_id is not None: payload["telegramId"] = telegram_id
        if email: payload["email"] = email

        return await self._request("POST", "/users", json=payload)

    async def update_user_details_on_panel(
            self, user_uuid: str,
            update_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if 'uuid' not in update_payload: update_payload['uuid'] = user_uuid

        update_payload.pop('activateAllInbounds', None)

        full_response = await self._request("PATCH",
                                            "/users",
                                            json=update_payload)
        if full_response and not full_response.get(
                "error") and full_response.get("response"):
            logging.info(f"User {user_uuid} details updated on panel.")
            return full_response.get("response")
        logging.error(
            f"Failed to update user {user_uuid} details on panel. Payload: {update_payload}, Resp: {full_response}"
        )
        return None

    async def get_all_panel_users(self,
                                  page_size: int = 100
                                  ) -> Optional[List[Dict[str, Any]]]:
        all_users = []
        start_offset = 0
        while True:
            params = {"size": page_size, "start": start_offset}
            response_data = await self._request("GET", "/users", params=params)
            if not response_data or response_data.get("error"):
                logging.error(
                    f"Failed to fetch panel users batch: {response_data}")
                return None
            users_batch = response_data.get("response", {}).get("users", [])
            if not users_batch: break
            all_users.extend(users_batch)
            if len(users_batch) < page_size: break
            start_offset += page_size
        logging.info(f"Fetched {len(all_users)} users from panel API.")
        return all_users

    async def get_user_by_uuid(self,
                               user_uuid: str) -> Optional[Dict[str, Any]]:
        full_response = await self._request("GET", f"/users/{user_uuid}")
        if full_response and not full_response.get(
                "error") and full_response.get("response"):
            return full_response.get("response")
        return None

    async def update_user_status_on_panel(self, user_uuid: str,
                                          enable: bool) -> bool:
        endpoint = f"/users/{user_uuid}/actions/{'enable' if enable else 'disable'}"
        response_data = await self._request("POST", endpoint)
        if response_data and not response_data.get("error") and (
                response_data.get("response")
                or response_data.get("status") == "success"):
            logging.info(
                f"User {user_uuid} status on panel -> {'enabled' if enable else 'disabled'}."
            )
            return True
        logging.error(
            f"Failed to update user {user_uuid} status on panel. Resp: {response_data}"
        )
        return False

    async def get_subscription_link(
            self,
            short_uuid_or_sub_uuid: str,
            client_type: Optional[str] = None) -> Optional[str]:
        if not self.settings.PANEL_API_URL: return None
        return f"{self.settings.PANEL_API_URL.rstrip('/')}/sub/{short_uuid_or_sub_uuid}"
