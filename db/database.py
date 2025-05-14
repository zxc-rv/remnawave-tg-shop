import aiosqlite
import logging
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timezone

from config.settings import get_settings

try:
    settings = get_settings()
    DB_NAME = settings.DB_NAME
except Exception as e:
    logging.critical(f"Could not load settings for database.py: {e}",
                     exc_info=True)
    DB_NAME = "bot_database.sqlite3"

DB_BUSY_TIMEOUT_SECONDS = 15.0


def get_db_connection_manager():
    """
    Возвращает awaitable/async context manager для соединения с SQLite.
    """
    return aiosqlite.connect(DB_NAME, timeout=DB_BUSY_TIMEOUT_SECONDS)


async def _setup_db_connection(db: aiosqlite.Connection):
    """Применяет необходимые PRAGMA и row_factory к установленному соединению."""
    try:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute(
            f"PRAGMA busy_timeout = {int(DB_BUSY_TIMEOUT_SECONDS * 1000)};")
        db.row_factory = aiosqlite.Row
    except Exception as e:
        logging.error(
            f"Failed to set PRAGMAs or row_factory on connection: {e}",
            exc_info=True)


async def init_db():
    """Инициализирует схему БД."""
    try:
        async with get_db_connection_manager() as db:
            await _setup_db_connection(db)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    language_code TEXT DEFAULT 'en',
                    registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP, /* TEXT as ISO8601 string, e.g. YYYY-MM-DD HH:MM:SS */
                    is_banned INTEGER DEFAULT 0,
                    panel_user_uuid TEXT UNIQUE,
                    referred_by_id INTEGER,
                    FOREIGN KEY (referred_by_id) REFERENCES users(user_id)
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_users_panel_user_uuid ON users (panel_user_uuid);"
            )

            await db.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions (
                    subscription_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    panel_user_uuid TEXT NOT NULL,
                    panel_subscription_uuid TEXT UNIQUE,
                    start_date TEXT, /* Storing as ISO TEXT */
                    end_date TEXT NOT NULL, /* Storing as ISO TEXT */
                    duration_months INTEGER,
                    is_active INTEGER DEFAULT 1,
                    status_from_panel TEXT,
                    traffic_limit_bytes INTEGER,
                    traffic_used_bytes INTEGER,
                    last_notification_sent TEXT /* Storing as TEXT YYYY-MM-DD */
                )""")
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_subscriptions_user_id ON subscriptions (user_id);"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_subscriptions_panel_user_uuid ON subscriptions (panel_user_uuid);"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_subscriptions_end_date ON subscriptions (end_date);"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_subscriptions_is_active ON subscriptions (is_active);"
            )

            await db.execute("""
                CREATE TABLE IF NOT EXISTS payments (
                    payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    yookassa_payment_id TEXT UNIQUE,
                    idempotence_key TEXT UNIQUE,
                    amount REAL NOT NULL,
                    currency TEXT NOT NULL,
                    status TEXT NOT NULL,
                    description TEXT,
                    subscription_duration_months INTEGER,
                    promo_code_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  /* TEXT as ISO8601 string */
                    updated_at TIMESTAMP, /* TEXT as ISO8601 string */
                    FOREIGN KEY (user_id) REFERENCES users(user_id),
                    FOREIGN KEY (promo_code_id) REFERENCES promo_codes(promo_code_id)
                )""")
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_payments_user_id ON payments (user_id);"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_payments_yookassa_payment_id ON payments (yookassa_payment_id);"
            )

            await db.execute("""
                CREATE TABLE IF NOT EXISTS promo_codes (
                    promo_code_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT UNIQUE NOT NULL,
                    bonus_days INTEGER NOT NULL,
                    max_activations INTEGER NOT NULL,
                    current_activations INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    created_by_admin_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, /* TEXT as ISO8601 string */
                    valid_until TEXT NULL /* Storing as ISO TEXT YYYY-MM-DD HH:MM:SS */
                )""")
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_promo_codes_code ON promo_codes (code);"
            )

            await db.execute("""
                CREATE TABLE IF NOT EXISTS promo_code_activations (
                    activation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    promo_code_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    activated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, /* TEXT as ISO8601 string */
                    payment_id INTEGER,
                    FOREIGN KEY (promo_code_id) REFERENCES promo_codes(promo_code_id),
                    FOREIGN KEY (user_id) REFERENCES users(user_id),
                    FOREIGN KEY (payment_id) REFERENCES payments(payment_id),
                    UNIQUE (promo_code_id, user_id)
                )""")

            await db.execute("""
                CREATE TABLE IF NOT EXISTS message_logs (
                    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    telegram_username TEXT,
                    telegram_first_name TEXT,
                    event_type TEXT NOT NULL,
                    content TEXT,
                    raw_update_preview TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP, /* TEXT as ISO8601 string */
                    is_admin_event INTEGER DEFAULT 0,
                    target_user_id INTEGER,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_message_logs_user_id ON message_logs (user_id);"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_message_logs_event_type ON message_logs (event_type);"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_message_logs_timestamp ON message_logs (timestamp);"
            )

            await db.execute("""
                CREATE TABLE IF NOT EXISTS panel_sync_status (
                    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
                    last_sync_time TIMESTAMP, /* TEXT as ISO8601 string */
                    status TEXT,
                    details TEXT,
                    users_processed_from_panel INTEGER DEFAULT 0,
                    subscriptions_synced INTEGER DEFAULT 0
                )""")
            await db.execute(
                "INSERT OR IGNORE INTO panel_sync_status (id, status, details) VALUES (1, 'never_run', 'System initialized')"
            )

            await db.commit()
        logging.info("Database initialized/checked successfully.")
    except Exception as e:
        logging.error(f"Failed to initialize database: {e}", exc_info=True)
        raise


async def add_user_if_not_exists(
        user_id: int,
        username: Optional[str],
        first_name: Optional[str],
        last_name: Optional[str],
        lang_code: str = 'en',
        referred_by_id: Optional[int] = None,
        panel_user_uuid: Optional[str] = None) -> Tuple[bool, bool]:
    """Adds user if not exists. Sets referred_by_id for new users. Returns (success, was_new_user_flag)."""
    was_new_user = False
    async with get_db_connection_manager() as db:
        await _setup_db_connection(db)
        try:
            cursor = await db.execute(
                "SELECT user_id, username, first_name, last_name, language_code, referred_by_id, panel_user_uuid, is_banned FROM users WHERE user_id = ?",
                (user_id, ))
            existing_user = await cursor.fetchone()
            await cursor.close()
            if existing_user:
                update_fields = {}
                if username is not None and username != existing_user[
                        'username']:
                    update_fields['username'] = username
                if first_name is not None and first_name != existing_user[
                        'first_name']:
                    update_fields['first_name'] = first_name
                if last_name is not None and last_name != existing_user[
                        'last_name']:
                    update_fields['last_name'] = last_name

                if panel_user_uuid and existing_user['panel_user_uuid'] is None:
                    update_fields['panel_user_uuid'] = panel_user_uuid

                if lang_code != existing_user['language_code']:
                    update_fields['language_code'] = lang_code
                if update_fields:
                    set_clause = ", ".join(
                        [f"{field} = ?" for field in update_fields.keys()])
                    params = list(update_fields.values()) + [user_id]
                    await db.execute(
                        f"UPDATE users SET {set_clause} WHERE user_id = ?",
                        tuple(params))
            else:
                await db.execute(
                    """INSERT INTO users (user_id, username, first_name, last_name, language_code, referred_by_id, panel_user_uuid, is_banned) VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
                    (user_id, username, first_name, last_name, lang_code,
                     referred_by_id, panel_user_uuid))
                logging.info(
                    f"New user {user_id} added. Referred by: {referred_by_id or 'N/A'}."
                )
                was_new_user = True
            await db.commit()
            return True, was_new_user
        except aiosqlite.IntegrityError as e:
            if "UNIQUE constraint failed: users.panel_user_uuid" in str(
                    e) and panel_user_uuid:
                res = await db.execute(
                    "UPDATE users SET user_id = ?, username = ?, first_name = ?, last_name = ?, language_code = COALESCE(?, language_code) WHERE panel_user_uuid = ? AND user_id IS NULL",
                    (user_id, username, first_name, last_name, lang_code,
                     panel_user_uuid))
                if res.rowcount > 0:
                    await db.commit()
                    logging.info(
                        f"Linked panel user {panel_user_uuid} to TG {user_id}."
                    )
                    return True, False
                else:
                    logging.error(
                        f"Conflict: Panel UUID {panel_user_uuid} exists.")
                    await db.rollback()
                    return False, False
            else:
                logging.error(f"DB integrity error for user {user_id}: {e}")
                await db.rollback()
                return False, False
        except Exception as e:
            logging.error(
                f"DB error in add_user_if_not_exists for user {user_id}: {e}",
                exc_info=True)
            await db.rollback()
            return False, False


async def get_user(
        user_id: int,
        db_conn: Optional[aiosqlite.Connection] = None
) -> Optional[aiosqlite.Row]:
    sql = "SELECT user_id, username, first_name, last_name, language_code, referred_by_id, panel_user_uuid, is_banned, strftime('%Y-%m-%d %H:%M:%S', registration_date) as registration_date_str FROM users WHERE user_id = ?"
    if db_conn:
        cursor = await db_conn.execute(sql, (user_id, ))
        row = await cursor.fetchone()
        if cursor:
            await cursor.close()
            return row
    else:
        async with get_db_connection_manager() as db:
            await _setup_db_connection(db)
            cursor = await db.execute(sql, (user_id, ))
            row = await cursor.fetchone()
            if cursor:
                await cursor.close()
                return row


async def get_user_by_telegram_username(
        username: str,
        db_conn: Optional[aiosqlite.Connection] = None
) -> Optional[aiosqlite.Row]:
    sql = "SELECT user_id, username, first_name, last_name, language_code, referred_by_id, panel_user_uuid, is_banned, strftime('%Y-%m-%d %H:%M:%S', registration_date) as registration_date_str FROM users WHERE LOWER(username) = LOWER(?)"
    clean_username = username.lstrip('@')
    if db_conn:
        cursor = await db_conn.execute(sql, (clean_username, ))
        row = await cursor.fetchone()
        if cursor:
            await cursor.close()
            return row
    else:
        async with get_db_connection_manager() as db:
            await _setup_db_connection(db)
            cursor = await db.execute(sql, (clean_username, ))
            row = await cursor.fetchone()
            if cursor:
                await cursor.close()
                return row


async def get_user_by_panel_uuid(
        panel_user_uuid: str,
        db_conn: Optional[aiosqlite.Connection] = None
) -> Optional[aiosqlite.Row]:
    sql = "SELECT user_id, username, first_name, last_name, language_code, referred_by_id, panel_user_uuid, is_banned, strftime('%Y-%m-%d %H:%M:%S', registration_date) as registration_date_str FROM users WHERE panel_user_uuid = ?"
    if db_conn:
        cursor = await db_conn.execute(sql, (panel_user_uuid, ))
        row = await cursor.fetchone()
        if cursor:
            await cursor.close()
            return row
    else:
        async with get_db_connection_manager() as db:
            await _setup_db_connection(db)
            cursor = await db.execute(sql, (panel_user_uuid, ))
            row = await cursor.fetchone()
            if cursor:
                await cursor.close()
                return row


async def get_banned_users_list_paginated(
        limit: int, offset: int) -> Tuple[List[aiosqlite.Row], int]:
    sql_users = "SELECT user_id, username, first_name, last_name FROM users WHERE is_banned = 1 ORDER BY registration_date DESC LIMIT ? OFFSET ?"
    sql_count = "SELECT COUNT(*) as total_banned FROM users WHERE is_banned = 1"
    users_list: List[aiosqlite.Row] = []
    total_banned = 0
    async with get_db_connection_manager() as db:
        await _setup_db_connection(db)
        cursor_users = await db.execute(sql_users, (limit, offset))
        users_list = await cursor_users.fetchall()
        await cursor_users.close()
        cursor_count = await db.execute(sql_count)
        count_row = await cursor_count.fetchone()
        await cursor_count.close()
        if count_row: total_banned = count_row['total_banned']
    return users_list, total_banned


async def get_user_active_subscription_end_date(
        user_id: int,
        db_conn: Optional[aiosqlite.Connection] = None) -> Optional[str]:
    sql = "SELECT strftime('%Y-%m-%d', end_date) as end_date_str FROM subscriptions WHERE user_id = ? AND is_active = 1 AND DATETIME(end_date) > DATETIME('now', 'localtime') ORDER BY end_date DESC LIMIT 1"
    if db_conn:
        cursor = await db_conn.execute(sql, (user_id, ))
        row = await cursor.fetchone()
        if cursor:
            await cursor.close()
            return row['end_date_str'] if row else None
    else:
        async with get_db_connection_manager() as db:
            await _setup_db_connection(db)
            cursor = await db.execute(sql, (user_id, ))
            row = await cursor.fetchone()
            if cursor:
                await cursor.close()
                return row['end_date_str'] if row else None


async def update_user_language_code(user_id: int, lang_code: str):
    async with get_db_connection_manager() as db:
        await _setup_db_connection(db)
        await db.execute(
            "UPDATE users SET language_code = ? WHERE user_id = ?",
            (lang_code, user_id))
        await db.commit()


async def set_user_ban_status_db(user_id: int, is_banned: bool) -> bool:
    async with get_db_connection_manager() as db:
        await _setup_db_connection(db)
        try:
            await db.execute(
                "UPDATE users SET is_banned = ? WHERE user_id = ?",
                (1 if is_banned else 0, user_id))
            await db.commit()
            return True
        except Exception as e:
            logging.error(f"Error setting ban status for {user_id}: {e}")
            await db.rollback()
            return False


async def update_user_panel_uuid(
        user_id: int,
        panel_user_uuid: str,
        db_conn: Optional[aiosqlite.Connection] = None):

    async def _operation(db_op: aiosqlite.Connection):
        try:
            await db_op.execute(
                "UPDATE users SET panel_user_uuid = ? WHERE user_id = ?",
                (panel_user_uuid, user_id))
            await db_op.commit()
        except aiosqlite.IntegrityError:
            logging.error(
                f"Failed to update panel_uuid for user {user_id} (UNIQUE constraint)."
            )
            await db_op.rollback()
        except Exception as e:
            logging.error(
                f"Error in update_user_panel_uuid for {user_id}: {e}")
            await db_op.rollback()

    if db_conn:
        await _setup_db_connection(db_conn
                                   ) if not db_conn.row_factory else None
        await _operation(db_conn)
    else:
        async with get_db_connection_manager() as db:
            await _setup_db_connection(db)
            await _operation(db)


async def update_or_create_user_from_panel(
        panel_data: Dict[str, Any],
        db_conn: Optional[aiosqlite.Connection] = None) -> bool:
    panel_uuid = panel_data.get('uuid')
    username = panel_data.get('username')
    if not panel_uuid:
        logging.warning(
            "update_or_create_user_from_panel: panel_uuid missing.")
        return False

    async def _operation(db_op: aiosqlite.Connection):
        existing_user = await get_user_by_panel_uuid(panel_uuid, db_conn=db_op)
        if not existing_user:
            reg_date_str = panel_data.get('createdAt',
                                          datetime.utcnow().isoformat())
            if isinstance(reg_date_str, datetime):
                reg_date_str = reg_date_str.isoformat()
            await db_op.execute(
                "INSERT INTO users (panel_user_uuid, username, registration_date, is_banned) VALUES (?, ?, ?, 0)",
                (panel_uuid, username, reg_date_str))
        await db_op.commit()
        return True

    try:
        if db_conn:
            await _setup_db_connection(db_conn
                                       ) if not db_conn.row_factory else None
            return await _operation(db_conn)
        else:
            async with get_db_connection_manager() as db:
                await _setup_db_connection(db)
                return await _operation(db)
    except Exception as e:
        logging.error(
            f"Error in update_or_create_user_from_panel panel_uuid {panel_uuid}: {e}",
            exc_info=True)
        return False


async def update_or_create_subscription_from_panel(
        panel_user_uuid: str,
        sub_data: Dict[str, Any],
        db_conn: Optional[aiosqlite.Connection] = None) -> bool:

    async def _operation(db_op: aiosqlite.Connection):
        cursor = await db_op.execute(
            "SELECT user_id FROM users WHERE panel_user_uuid = ?",
            (panel_user_uuid, ))
        user_row = await cursor.fetchone()
        await cursor.close()
        bot_user_id = user_row['user_id'] if user_row else None
        panel_sub_link_uuid = sub_data.get('subscriptionUuid') or sub_data.get(
            'shortUuid')
        if not panel_sub_link_uuid:
            logging.warning(
                f"No panel_subscription_uuid or shortUuid for panel user {panel_user_uuid}"
            )
            return False
        end_date_str = sub_data.get('expireAt')
        end_date = None
        if end_date_str:
            try:
                end_date = datetime.fromisoformat(
                    end_date_str.replace("Z", "+00:00"))
            except ValueError:
                logging.warning(
                    f"Bad expireAt: {end_date_str} for {panel_user_uuid}")
                return False
        if not end_date:
            logging.warning(f"No end_date for {panel_user_uuid}")
            return False
        status_panel = sub_data.get('status', 'UNKNOWN').upper()
        is_active_panel = 1 if status_panel == 'ACTIVE' else 0
        traffic_limit = sub_data.get('trafficLimitBytes')
        traffic_used = sub_data.get('usedTrafficBytes',
                                    sub_data.get('lifetimeUsedTrafficBytes'))
        start_date_iso = sub_data.get('createdAt',
                                      datetime.utcnow().isoformat())
        if isinstance(start_date_iso, datetime):
            start_date_iso = start_date_iso.isoformat()
        duration_months_val = sub_data.get('duration_months')
        upsert_sql = """ INSERT INTO subscriptions (user_id, panel_user_uuid, panel_subscription_uuid, start_date, end_date, duration_months, is_active, status_from_panel, traffic_limit_bytes, traffic_used_bytes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(panel_subscription_uuid) DO UPDATE SET user_id = excluded.user_id, panel_user_uuid = excluded.panel_user_uuid, start_date = excluded.start_date, end_date = excluded.end_date, duration_months = excluded.duration_months, is_active = excluded.is_active, status_from_panel = excluded.status_from_panel, traffic_limit_bytes = excluded.traffic_limit_bytes, traffic_used_bytes = excluded.traffic_used_bytes, last_notification_sent = NULL; """
        params = (bot_user_id, panel_user_uuid, panel_sub_link_uuid,
                  start_date_iso, end_date.isoformat(), duration_months_val,
                  is_active_panel, status_panel, traffic_limit, traffic_used)
        await db_op.execute(upsert_sql, params)
        await db_op.commit()
        return True

    try:
        if db_conn:
            await _setup_db_connection(db_conn
                                       ) if not db_conn.row_factory else None
            return await _operation(db_conn)
        else:
            async with get_db_connection_manager() as db:
                await _setup_db_connection(db)
                return await _operation(db)
    except Exception as e:
        logging.error(
            f"Error in update_or_create_subscription_from_panel for {panel_user_uuid}: {e}",
            exc_info=True)
        return False


async def update_sync_status(status: str,
                             details: str,
                             users_processed: int = 0,
                             subs_synced: int = 0):
    async with get_db_connection_manager() as db:
        await _setup_db_connection(db)
        await db.execute(
            "UPDATE panel_sync_status SET last_sync_time=CURRENT_TIMESTAMP, status=?, details=?, users_processed_from_panel=?, subscriptions_synced=? WHERE id=1",
            (status, details, users_processed, subs_synced))
        await db.commit()


async def get_last_sync_status() -> Optional[aiosqlite.Row]:
    async with get_db_connection_manager() as db:
        await _setup_db_connection(db)
        cursor = await db.execute(
            "SELECT * FROM panel_sync_status WHERE id = 1")
        row = await cursor.fetchone()
        await cursor.close()
        return row


async def get_all_users_for_broadcast() -> List[aiosqlite.Row]:
    async with get_db_connection_manager() as db:
        await _setup_db_connection(db)
        cursor = await db.execute(
            "SELECT user_id FROM users WHERE user_id IS NOT NULL AND is_banned = 0"
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return rows


async def get_user_count_stats() -> Dict[str, int]:
    async with get_db_connection_manager() as db:
        await _setup_db_connection(db)
        cursor = await db.execute(
            "SELECT COUNT(DISTINCT user_id) as count FROM users WHERE user_id IS NOT NULL"
        )
        total_users_c_row = await cursor.fetchone()
        await cursor.close()
        cursor = await db.execute(
            "SELECT COUNT(DISTINCT user_id) as count FROM users WHERE user_id IS NOT NULL AND is_banned = 1"
        )
        banned_users_c_row = await cursor.fetchone()
        await cursor.close()
        cursor = await db.execute(
            "SELECT COUNT(DISTINCT user_id) as count FROM subscriptions WHERE user_id IS NOT NULL AND is_active = 1 AND DATETIME(end_date) > DATETIME('now', 'localtime')"
        )
        active_subs_c_row = await cursor.fetchone()
        await cursor.close()
        return {
            "total_users":
            total_users_c_row['count'] if total_users_c_row else 0,
            "banned_users":
            banned_users_c_row['count'] if banned_users_c_row else 0,
            "users_with_active_subscriptions":
            active_subs_c_row['count'] if active_subs_c_row else 0
        }


async def get_payment_logs(limit: int = 20,
                           offset: int = 0) -> List[aiosqlite.Row]:
    async with get_db_connection_manager() as db:
        await _setup_db_connection(db)
        cursor = await db.execute(
            """SELECT p.payment_id, p.user_id, u.username, p.amount, p.currency, p.status, p.description, strftime('%Y-%m-%d %H:%M:%S', p.created_at) as created_at FROM payments p LEFT JOIN users u ON p.user_id = u.user_id ORDER BY p.created_at DESC LIMIT ? OFFSET ?""",
            (limit, offset))
        rows = await cursor.fetchall()
        await cursor.close()
        return rows


async def log_user_action(user_id: Optional[int],
                          event_type: str,
                          content: Optional[str] = None,
                          telegram_username: Optional[str] = None,
                          telegram_first_name: Optional[str] = None,
                          is_admin_event: bool = False,
                          target_user_id: Optional[int] = None,
                          raw_update_preview: Optional[str] = None):
    async with get_db_connection_manager() as db:
        await _setup_db_connection(db)
        try:
            await db.execute(
                """INSERT INTO message_logs (user_id, telegram_username, telegram_first_name, event_type, content, raw_update_preview, is_admin_event, target_user_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, telegram_username, telegram_first_name, event_type,
                 content, raw_update_preview, 1 if is_admin_event else 0,
                 target_user_id))
            await db.commit()
        except Exception as e:
            logging.error(
                f"Failed to log action for user {user_id}, type {event_type}: {e}",
                exc_info=True)


async def get_message_logs_db(limit: int = 20,
                              offset: int = 0) -> List[aiosqlite.Row]:
    async with get_db_connection_manager() as db:
        await _setup_db_connection(db)
        cursor = await db.execute(
            """SELECT log_id, user_id, telegram_username, telegram_first_name, event_type, content, strftime('%Y-%m-%d %H:%M:%S', timestamp) as timestamp_str, is_admin_event FROM message_logs ORDER BY timestamp DESC LIMIT ? OFFSET ?""",
            (limit, offset))
        rows = await cursor.fetchall()
        await cursor.close()
        return rows


async def count_all_message_logs() -> int:
    async with get_db_connection_manager() as db:
        await _setup_db_connection(db)
        cursor = await db.execute("SELECT COUNT(*) as count FROM message_logs")
        row = await cursor.fetchone()
        await cursor.close()
        return row['count'] if row else 0


async def get_user_message_logs_paginated(user_id_to_search: int, limit: int,
                                          offset: int) -> List[aiosqlite.Row]:
    async with get_db_connection_manager() as db:
        await _setup_db_connection(db)
        cursor = await db.execute(
            """SELECT log_id, user_id, telegram_username, telegram_first_name, event_type, content, strftime('%Y-%m-%d %H:%M:%S', timestamp) as timestamp_str FROM message_logs WHERE user_id = ? OR target_user_id = ? ORDER BY timestamp DESC LIMIT ? OFFSET ?""",
            (user_id_to_search, user_id_to_search, limit, offset))
        rows = await cursor.fetchall()
        await cursor.close()
        return rows


async def count_user_message_logs(user_id_to_search: int) -> int:
    async with get_db_connection_manager() as db:
        await _setup_db_connection(db)
        cursor = await db.execute(
            "SELECT COUNT(*) as count FROM message_logs WHERE user_id = ? OR target_user_id = ?",
            (user_id_to_search, user_id_to_search))
        row = await cursor.fetchone()
        await cursor.close()
        return row['count'] if row else 0


async def add_payment_record(user_id: int,
                             yookassa_payment_id: Optional[str],
                             idempotence_key: Optional[str],
                             amount: float,
                             currency: str,
                             status: str,
                             description: str,
                             sub_months: int,
                             promo_id: Optional[int] = None) -> Optional[int]:
    async with get_db_connection_manager() as db:
        await _setup_db_connection(db)
        try:
            cursor = await db.execute(
                """INSERT INTO payments (user_id, yookassa_payment_id, idempotence_key, amount, currency, status, description, subscription_duration_months, promo_code_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, yookassa_payment_id, idempotence_key, amount,
                 currency, status, description, sub_months, promo_id))
            await db.commit()
            return cursor.lastrowid
        except Exception as e:
            logging.error(
                f"Failed to add payment record user {user_id}, yk_id {yookassa_payment_id}: {e}"
            )
            await db.rollback()
            return None


async def update_payment_status(
        payment_db_id: Optional[int] = None,
        yookassa_payment_id: Optional[str] = None,
        new_status: Optional[str] = None,
        db_conn: Optional[aiosqlite.Connection] = None):

    async def _operation(db_op: aiosqlite.Connection):
        if new_status is None: return
        if payment_db_id:
            await db_op.execute(
                "UPDATE payments SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE payment_id = ?",
                (new_status, payment_db_id))
        elif yookassa_payment_id:
            await db_op.execute(
                "UPDATE payments SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE yookassa_payment_id = ?",
                (new_status, yookassa_payment_id))
        else:
            logging.warning(
                "update_payment_status called without payment_id or yookassa_payment_id"
            )
            return
        await db_op.commit()

    if db_conn:
        await _setup_db_connection(db_conn
                                   ) if not db_conn.row_factory else None
        await _operation(db_conn)
    else:
        async with get_db_connection_manager() as db:
            await _setup_db_connection(db)
            await _operation(db)


async def get_payment_by_yookassa_id(
        yookassa_payment_id: str) -> Optional[aiosqlite.Row]:
    async with get_db_connection_manager() as db:
        await _setup_db_connection(db)
        cursor = await db.execute(
            "SELECT * FROM payments WHERE yookassa_payment_id = ?",
            (yookassa_payment_id, ))
        row = await cursor.fetchone()
        await cursor.close()
        return row


async def create_promo_code_db(
        code: str,
        bonus_days: int,
        max_activations: int,
        admin_id: int,
        valid_until_dt: Optional[datetime] = None) -> Optional[int]:
    valid_until_iso: Optional[str] = valid_until_dt.isoformat(
    ) if valid_until_dt else None
    async with get_db_connection_manager() as db:
        await _setup_db_connection(db)
        try:
            cursor = await db.execute(
                "INSERT INTO promo_codes (code, bonus_days, max_activations, created_by_admin_id, valid_until) VALUES (?, ?, ?, ?, ?)",
                (code.upper(), bonus_days, max_activations, admin_id,
                 valid_until_iso))
            await db.commit()
            return cursor.lastrowid
        except aiosqlite.IntegrityError:
            logging.warning(f"Promo code {code.upper()} exists.")
            await db.rollback()
            return None
        except Exception as e:
            logging.error(f"Error creating promo {code.upper()}: {e}")
            await db.rollback()
            return None


async def get_promo_codes_db(is_active_only: bool = True,
                             limit: int = 20,
                             offset: int = 0) -> List[aiosqlite.Row]:
    async with get_db_connection_manager() as db:
        await _setup_db_connection(db)
        query = "SELECT promo_code_id, code, bonus_days, max_activations, current_activations, is_active, created_by_admin_id, created_at, valid_until FROM promo_codes"
        params = []
        conditions = []
        if is_active_only: conditions.append("is_active = 1")
        conditions.append(
            "(valid_until IS NULL OR DATETIME(valid_until) > DATETIME('now', 'localtime'))"
        )
        if conditions: query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        cursor = await db.execute(query, tuple(params))
        rows = await cursor.fetchall()
        await cursor.close()
        return rows


async def get_promo_code_by_code(
        code: str,
        db_conn: Optional[aiosqlite.Connection] = None
) -> Optional[aiosqlite.Row]:
    sql = "SELECT * FROM promo_codes WHERE code = ? AND is_active = 1 AND (DATETIME(valid_until) IS NULL OR DATETIME(valid_until) > DATETIME('now', 'localtime'))"
    if db_conn:
        cursor = await db_conn.execute(sql, (code.upper(), ))
        row = await cursor.fetchone()
        if cursor:
            await cursor.close()
            return row
    else:
        async with get_db_connection_manager() as db:
            await _setup_db_connection(db)
            cursor = await db.execute(sql, (code.upper(), ))
            row = await cursor.fetchone()
            if cursor:
                await cursor.close()
                return row


async def increment_promo_activation(promo_code_id: int,
                                     user_id: int,
                                     db_conn: aiosqlite.Connection,
                                     payment_id: Optional[int] = None) -> bool:

    db = db_conn
    try:
        cursor = await db.execute(
            "SELECT 1 FROM promo_code_activations WHERE promo_code_id = ? AND user_id = ?",
            (promo_code_id, user_id))
        existing = await cursor.fetchone()
        await cursor.close()
        if existing:
            logging.info(f"User {user_id} already used promo {promo_code_id}.")
            return False
        await db.execute(
            "INSERT INTO promo_code_activations (promo_code_id, user_id, payment_id) VALUES (?, ?, ?)",
            (promo_code_id, user_id, payment_id))
        await db.execute(
            "UPDATE promo_codes SET current_activations = current_activations + 1 WHERE promo_code_id = ?",
            (promo_code_id, ))
        return True
    except aiosqlite.IntegrityError:
        logging.warning(
            f"IntegrityError on promo activation p:{promo_code_id} u:{user_id}."
        )
        return False
    except Exception as e:
        logging.error(
            f"Error promo activation p:{promo_code_id} u:{user_id}: {e}",
            exc_info=True)
        return False


async def get_all_message_logs_paginated(limit: int,
                                         offset: int) -> List[aiosqlite.Row]:
    """
    Fetches a paginated list of all message logs, ordered by the newest first.
    """
    async with get_db_connection_manager() as db:
        await _setup_db_connection(db)

        sql = """
            SELECT
                log_id,
                user_id,
                telegram_username,
                telegram_first_name,
                event_type,
                content,
                strftime('%Y-%m-%d %H:%M:%S', timestamp) as timestamp_str,
                is_admin_event,
                target_user_id
            FROM message_logs
            ORDER BY timestamp DESC
            LIMIT ? OFFSET ?
        """
        try:
            cursor = await db.execute(sql, (limit, offset))
            rows = await cursor.fetchall()
            await cursor.close()
            return rows
        except Exception as e:
            logging.error(f"Error fetching all message logs: {e}",
                          exc_info=True)
            return []


async def has_had_any_subscription(
        user_id: int, db_conn: Optional[aiosqlite.Connection] = None) -> bool:
    """Checks if a user has ever had any subscription (trial or paid)."""
    sql = "SELECT 1 FROM subscriptions WHERE user_id = ? LIMIT 1"
    if db_conn:
        cursor = await db_conn.execute(sql, (user_id, ))
        row = await cursor.fetchone()
        await cursor.close()
        return row is not None
    else:
        async with get_db_connection_manager() as db:
            await _setup_db_connection(db)
            cursor = await db.execute(sql, (user_id, ))
            row = await cursor.fetchone()
            await cursor.close()
            return row is not None


async def sync_panel_user_data(
        panel_user_dict: Dict[str, Any],
        db_conn_passed: Optional[aiosqlite.Connection] = None) -> bool:
    """
    Synchronizes a single panel user's data (user info and subscription) with the local bot database.
    Prioritizes matching/creating bot user by panel_user_dict['telegramId'].
    Manages its own transaction if db_conn_passed is None.
    """
    panel_uuid = panel_user_dict.get('uuid')
    telegram_id_from_panel = panel_user_dict.get('telegramId')
    panel_username = panel_user_dict.get('username')

    if not panel_uuid:
        logging.warning(
            f"Sync: Panel user data missing 'uuid'. Data: {panel_user_dict}")
        return False
    if not telegram_id_from_panel:
        logging.info(
            f"Sync: Panel user {panel_uuid} (username: {panel_username}) has no 'telegramId'. Skipping TG ID based sync for this user."
        )

        return False

    async def _operation(db: aiosqlite.Connection):

        bot_user_id = int(telegram_id_from_panel)

        existing_bot_user = await get_user(bot_user_id, db_conn=db)

        if existing_bot_user:

            if existing_bot_user['panel_user_uuid'] != panel_uuid:
                if existing_bot_user['panel_user_uuid'] is not None:
                    logging.warning(
                        f"Sync: TG User {bot_user_id} already linked to panel_uuid {existing_bot_user['panel_user_uuid']}, but panel now provides {panel_uuid} for this TG ID. Updating to new panel_uuid."
                    )

                cursor_conflict = await db.execute(
                    "SELECT user_id FROM users WHERE panel_user_uuid = ? AND user_id != ?",
                    (panel_uuid, bot_user_id))
                conflicting_user = await cursor_conflict.fetchone()
                await cursor_conflict.close()
                if conflicting_user:
                    logging.error(
                        f"Sync: CRITICAL CONFLICT! New panel_uuid {panel_uuid} (for TG ID {bot_user_id}) is already linked to different TG User {conflicting_user['user_id']}. Skipping user update for panel_uuid."
                    )
                else:
                    await db.execute(
                        "UPDATE users SET panel_user_uuid = ?, username = ? WHERE user_id = ?",
                        (panel_uuid, panel_username, bot_user_id))
                    logging.info(
                        f"Sync: Updated panel_uuid for existing TG user {bot_user_id} to {panel_uuid}."
                    )
            else:

                if panel_username and existing_bot_user[
                        'username'] != panel_username:
                    await db.execute(
                        "UPDATE users SET username = ? WHERE user_id = ?",
                        (panel_username, bot_user_id))
                    logging.info(
                        f"Sync: Updated username for TG user {bot_user_id} from panel username {panel_username}."
                    )
        else:

            cursor_conflict = await db.execute(
                "SELECT user_id FROM users WHERE panel_user_uuid = ?",
                (panel_uuid, ))
            conflicting_user = await cursor_conflict.fetchone()
            await cursor_conflict.close()
            if conflicting_user:
                logging.error(
                    f"Sync: CRITICAL CONFLICT! Panel UUID {panel_uuid} (for new TG ID {bot_user_id}) is already linked to existing TG User {conflicting_user['user_id']}. Skipping new user creation."
                )
                return False

            reg_date_str = panel_user_dict.get(
                'createdAt',
                datetime.now(timezone.utc).isoformat())
            if isinstance(reg_date_str, datetime):
                reg_date_str = reg_date_str.isoformat()
            await db.execute(
                """INSERT INTO users (user_id, username, panel_user_uuid, registration_date, is_banned, language_code)
                   VALUES (?, ?, ?, ?, 0, ?)""",
                (bot_user_id, panel_username, panel_uuid, reg_date_str,
                 settings.DEFAULT_LANGUAGE))
            logging.info(
                f"Sync: New user created in bot DB from panel data: TG ID {bot_user_id}, Panel UUID {panel_uuid}, Panel Username {panel_username}"
            )

        panel_sub_link_uuid = panel_user_dict.get(
            'subscriptionUuid') or panel_user_dict.get('shortUuid')
        if not panel_sub_link_uuid:
            logging.warning(
                f"Sync: Panel user {panel_uuid} (TG ID: {bot_user_id}) has no 'subscriptionUuid' or 'shortUuid'. Cannot sync subscription link."
            )

            await db.commit()
            return True

        end_date_str = panel_user_dict.get('expireAt')
        end_date_obj = None
        if end_date_str:
            try:
                end_date_obj = datetime.fromisoformat(
                    end_date_str.replace("Z", "+00:00"))
            except ValueError:
                logging.warning(
                    f"Sync: Bad expireAt '{end_date_str}' for panel user {panel_uuid}. Skipping subscription update."
                )
                return True

        if not end_date_obj:
            logging.warning(
                f"Sync: No valid end_date for panel user {panel_uuid}. Skipping subscription update."
            )
            return True

        status_panel = panel_user_dict.get('status', 'UNKNOWN').upper()
        is_active_panel = 1 if status_panel == 'ACTIVE' else 0
        traffic_limit = panel_user_dict.get('trafficLimitBytes')
        traffic_used = panel_user_dict.get(
            'usedTrafficBytes',
            panel_user_dict.get('lifetimeUsedTrafficBytes'))

        start_date_iso = panel_user_dict.get(
            'createdAt',
            datetime.now(timezone.utc).isoformat())
        if isinstance(start_date_iso, datetime):
            start_date_iso = start_date_iso.isoformat()

        duration_months_val = None

        await db.execute(
            "UPDATE subscriptions SET is_active = 0 WHERE user_id = ? AND panel_user_uuid = ? AND is_active = 1 AND panel_subscription_uuid != ?",
            (bot_user_id, panel_uuid, panel_sub_link_uuid))

        upsert_sub_sql = """
            INSERT INTO subscriptions (
                user_id, panel_user_uuid, panel_subscription_uuid,
                start_date, end_date, duration_months,
                is_active, status_from_panel, traffic_limit_bytes, traffic_used_bytes,
                last_notification_sent
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            ON CONFLICT(panel_subscription_uuid) DO UPDATE SET
                user_id = excluded.user_id,
                panel_user_uuid = excluded.panel_user_uuid,
                start_date = excluded.start_date,
                end_date = excluded.end_date,
                duration_months = excluded.duration_months,
                is_active = excluded.is_active,
                status_from_panel = excluded.status_from_panel,
                traffic_limit_bytes = excluded.traffic_limit_bytes,
                traffic_used_bytes = excluded.traffic_used_bytes,
                last_notification_sent = NULL;
        """
        sub_params = (bot_user_id, panel_uuid, panel_sub_link_uuid,
                      start_date_iso, end_date_obj.isoformat(),
                      duration_months_val, is_active_panel, status_panel,
                      traffic_limit, traffic_used)
        await db.execute(upsert_sub_sql, sub_params)
        logging.info(
            f"Sync: Subscription upserted for TG ID {bot_user_id}, Panel UUID {panel_uuid}, Link ID {panel_sub_link_uuid}"
        )

        await db.commit()
        return True

    if db_conn_passed:
        return await _operation(db_conn_passed)
    else:
        async with get_db_connection_manager() as db:
            await _setup_db_connection(db)
            try:
                return await _operation(db)

            except Exception as e:
                logging.error(
                    f"Sync: General DB error during sync_panel_user_data for panel UUID {panel_uuid}: {e}",
                    exc_info=True)
                await db.rollback()
                return False
