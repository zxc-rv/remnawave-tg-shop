from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardButton
from aiogram.types import InlineKeyboardMarkup, WebAppInfo
from typing import Optional, List, Any
import math

from config.settings import Settings
from bot.middlewares.i18n import JsonI18n
from db.models import User


def get_admin_panel_keyboard(i18n_instance, lang: str,
                             settings: Settings) -> InlineKeyboardMarkup:
    _ = lambda key, **kwargs: i18n_instance.gettext(lang, key, **kwargs)
    builder = InlineKeyboardBuilder()
    builder.button(text=_(key="admin_stats_button"),
                   callback_data="admin_action:stats")
    builder.button(text=_(key="admin_broadcast_button"),
                   callback_data="admin_action:broadcast")
    builder.button(text=_(key="admin_create_promo_button"),
                   callback_data="admin_action:create_promo")
    builder.button(text=_(key="admin_manage_promos_button"),
                   callback_data="admin_action:manage_promos")
    builder.button(text=_(key="admin_view_promos_button"),
                   callback_data="admin_action:view_promos")
    builder.button(text=_(key="admin_ban_user_button"),
                   callback_data="admin_action:ban_user_prompt")
    builder.button(text=_(key="admin_unban_user_button"),
                   callback_data="admin_action:unban_user_prompt")
    builder.button(text=_(key="admin_view_banned_users_button"),
                   callback_data="admin_action:view_banned:0")
    builder.button(text=_(key="admin_view_logs_menu_button"),
                   callback_data="admin_action:view_logs_menu")
    builder.button(text=_(key="admin_sync_panel_button"),
                   callback_data="admin_action:sync_panel")
    builder.adjust(2, 2, 2, 2, 1)
    return builder.as_markup()


def get_logs_menu_keyboard(i18n_instance, lang: str) -> InlineKeyboardMarkup:
    _ = lambda key, **kwargs: i18n_instance.gettext(lang, key, **kwargs)
    builder = InlineKeyboardBuilder()
    builder.button(text=_(key="admin_view_all_logs_button"),
                   callback_data="admin_logs:view_all:0")
    builder.button(text=_(key="admin_view_user_logs_prompt_button"),
                   callback_data="admin_logs:prompt_user")
    builder.row(
        InlineKeyboardButton(text=_(key="back_to_admin_panel_button"),
                             callback_data="admin_action:main"))
    return builder.as_markup()


def get_logs_pagination_keyboard(
        current_page: int,
        total_pages: int,
        base_callback_data: str,
        i18n_instance,
        lang: str,
        back_to_logs_menu: bool = False) -> InlineKeyboardMarkup:
    _ = lambda key, **kwargs: i18n_instance.gettext(lang, key, **kwargs)
    builder = InlineKeyboardBuilder()
    row_buttons = []
    if current_page > 0:
        row_buttons.append(
            InlineKeyboardButton(
                text="⬅️ " + _("prev_page_button", default="Prev"),
                callback_data=f"{base_callback_data}:{current_page - 1}"))
    if current_page < total_pages - 1:
        row_buttons.append(
            InlineKeyboardButton(
                text=_("next_page_button", default="Next") + " ➡️",
                callback_data=f"{base_callback_data}:{current_page + 1}"))

    if row_buttons: builder.row(*row_buttons)

    if back_to_logs_menu:
        builder.row(
            InlineKeyboardButton(text=_(key="admin_logs_menu_title"),
                                 callback_data="admin_action:view_logs_menu"))
    else:
        builder.row(
            InlineKeyboardButton(text=_(key="back_to_admin_panel_button"),
                                 callback_data="admin_action:main"))
    return builder.as_markup()


def get_banned_users_keyboard(banned_users: List[User], current_page: int,
                              total_banned: int, i18n_instance: JsonI18n,
                              lang: str,
                              settings: Settings) -> InlineKeyboardMarkup:
    _ = lambda key, **kwargs: i18n_instance.gettext(lang, key, **kwargs)
    builder = InlineKeyboardBuilder()
    page_size = settings.LOGS_PAGE_SIZE

    if not banned_users and total_banned == 0:
        pass

    for user_row in banned_users:

        user_display_parts = []
        if user_row.first_name:
            user_display_parts.append(user_row.first_name)
        if user_row.username:
            user_display_parts.append(f"(@{user_row.username})")
        if not user_display_parts:
            user_display_parts.append(f"ID: {user_row.user_id}")

        user_display = " ".join(user_display_parts).strip()

        button_text = _("admin_banned_user_button_text",
                        user_display=user_display,
                        user_id=user_row.user_id)
        builder.row(
            InlineKeyboardButton(
                text=button_text,
                callback_data=
                f"admin_user_card:{user_row.user_id}:{current_page}"))

    if total_banned > page_size:
        total_pages = math.ceil(total_banned / page_size)
        pagination_buttons = []
        if current_page > 0:
            pagination_buttons.append(
                InlineKeyboardButton(
                    text=_("prev_page_button"),
                    callback_data=f"admin_action:view_banned:{current_page - 1}"
                ))
        pagination_buttons.append(
            InlineKeyboardButton(text=f"{current_page + 1}/{total_pages}",
                                 callback_data="stub_page_display"))
        if current_page < total_pages - 1:
            pagination_buttons.append(
                InlineKeyboardButton(
                    text=_("next_page_button"),
                    callback_data=f"admin_action:view_banned:{current_page + 1}"
                ))
        if pagination_buttons:
            builder.row(*pagination_buttons)

    builder.row(
        InlineKeyboardButton(text=_("back_to_admin_panel_button"),
                             callback_data="admin_action:main"))
    return builder.as_markup()


def get_user_card_keyboard(user_id: int,
                           is_banned: bool,
                           i18n_instance,
                           lang: str,
                           banned_list_page: int = 0) -> InlineKeyboardMarkup:
    _ = lambda key, **kwargs: i18n_instance.gettext(lang, key, **kwargs)
    builder = InlineKeyboardBuilder()
    if is_banned:
        builder.button(
            text=_(key="user_card_unban_button"),
            callback_data=f"admin_unban_confirm:{user_id}:{banned_list_page}")
    else:
        builder.button(
            text=_(key="user_card_ban_button"),
            callback_data=f"admin_ban_confirm:{user_id}:{banned_list_page}")
    builder.button(
        text=_(key="user_card_back_to_banned_list_button"),
        callback_data=f"admin_action:view_banned:{banned_list_page}")
    builder.button(text=_(key="back_to_admin_panel_button"),
                   callback_data="admin_action:main")
    builder.adjust(1)
    return builder.as_markup()


def get_confirmation_keyboard(yes_callback_data: str, no_callback_data: str,
                              i18n_instance,
                              lang: str) -> InlineKeyboardMarkup:
    _ = lambda key, **kwargs: i18n_instance.gettext(lang, key, **kwargs)
    builder = InlineKeyboardBuilder()
    builder.button(text=_(key="yes_button"), callback_data=yes_callback_data)
    builder.button(text=_(key="no_button"), callback_data=no_callback_data)
    return builder.as_markup()


def get_broadcast_confirmation_keyboard(lang: str,
                                        i18n_instance) -> InlineKeyboardMarkup:
    _ = lambda key, **kwargs: i18n_instance.gettext(lang, key, **kwargs)
    builder = InlineKeyboardBuilder()
    builder.button(text=_(key="confirm_broadcast_send_button"),
                   callback_data="broadcast_final_action:send")
    builder.button(text=_(key="cancel_broadcast_button"),
                   callback_data="broadcast_final_action:cancel")
    builder.adjust(2)
    return builder.as_markup()


def get_back_to_admin_panel_keyboard(lang: str,
                                     i18n_instance) -> InlineKeyboardMarkup:
    _ = lambda key, **kwargs: i18n_instance.gettext(lang, key, **kwargs)
    builder = InlineKeyboardBuilder()
    builder.button(text=_(key="back_to_admin_panel_button"),
                   callback_data="admin_action:main")
    return builder.as_markup()
