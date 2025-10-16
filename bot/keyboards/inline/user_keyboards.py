from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardButton
from aiogram.types import InlineKeyboardMarkup, WebAppInfo
from typing import Dict, Optional, List

from config.settings import Settings

# test


def get_main_menu_inline_keyboard(
    lang: str, i18n_instance, settings: Settings, show_trial_button: bool = False
) -> InlineKeyboardMarkup:
    _ = lambda key, **kwargs: i18n_instance.gettext(lang, key, **kwargs)
    builder = InlineKeyboardBuilder()

    if show_trial_button and settings.TRIAL_ENABLED:
        builder.row(
            InlineKeyboardButton(
                text=_(key="menu_activate_trial_button"),
                callback_data="main_action:request_trial",
            )
        )

    if settings.SUBSCRIPTION_MINI_APP_URL:
        builder.row(
            InlineKeyboardButton(
                text=_(key="menu_connect_button"),
                web_app=WebAppInfo(url=settings.SUBSCRIPTION_MINI_APP_URL),
            )
        )
    else:
        builder.row(
            InlineKeyboardButton(
                text=_(key="menu_subscribe_inline"),
                callback_data="main_action:subscribe",
            )
        )

    builder.row(
        InlineKeyboardButton(
            text=_(key="menu_my_subscription_inline"),
            callback_data="main_action:my_subscription",
        )
    )

    promo_button = InlineKeyboardButton(
        text=_(key="menu_apply_promo_button"), callback_data="main_action:apply_promo"
    )
    builder.row(promo_button)

    language_button = InlineKeyboardButton(
        text=_(key="menu_language_settings_inline"),
        callback_data="main_action:language",
    )
    status_button_list = []
    if settings.SERVER_STATUS_URL:
        status_button_list.append(
            InlineKeyboardButton(
                text=_(key="menu_server_status_button"), url=settings.SERVER_STATUS_URL
            )
        )

    if status_button_list:
        builder.row(language_button, *status_button_list)
    else:
        builder.row(language_button)

    if settings.SUPPORT_LINK:
        builder.row(
            InlineKeyboardButton(
                text=_(key="menu_support_button"), url=settings.SUPPORT_LINK
            )
        )

    if settings.TERMS_OF_SERVICE_URL:
        builder.row(
            InlineKeyboardButton(
                text=_(key="menu_terms_button"), url=settings.TERMS_OF_SERVICE_URL
            )
        )

    return builder.as_markup()


def get_language_selection_keyboard(
    i18n_instance, current_lang: str
) -> InlineKeyboardMarkup:
    _ = lambda key, **kwargs: i18n_instance.gettext(current_lang, key, **kwargs)
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"🇬🇧 English {'✅' if current_lang == 'en' else ''}",
        callback_data="set_lang_en",
    )
    builder.button(
        text=f"🇷🇺 Русский {'✅' if current_lang == 'ru' else ''}",
        callback_data="set_lang_ru",
    )
    builder.button(
        text=_(key="back_to_main_menu_button"), callback_data="main_action:back_to_main"
    )
    builder.adjust(1)
    return builder.as_markup()


def get_trial_confirmation_keyboard(lang: str, i18n_instance) -> InlineKeyboardMarkup:
    _ = lambda key, **kwargs: i18n_instance.gettext(lang, key, **kwargs)
    builder = InlineKeyboardBuilder()
    builder.button(
        text=_(key="trial_confirm_activate_button"),
        callback_data="trial_action:confirm_activate",
    )
    builder.button(
        text=_(key="cancel_button"), callback_data="main_action:back_to_main"
    )
    builder.adjust(1)
    return builder.as_markup()


def get_subscription_options_keyboard(
    subscription_options: Dict[int, Optional[int]],
    currency_symbol_val: str,
    lang: str,
    i18n_instance,
) -> InlineKeyboardMarkup:
    _ = lambda key, **kwargs: i18n_instance.gettext(lang, key, **kwargs)
    builder = InlineKeyboardBuilder()
    if subscription_options:
        for months, price in subscription_options.items():
            if price is not None:
                button_text = _(
                    "subscribe_for_months_button",
                    months=months,
                    price=price,
                    currency_symbol=currency_symbol_val,
                )
                builder.button(
                    text=button_text, callback_data=f"subscribe_period:{months}"
                )
        builder.adjust(1)
    builder.row(
        InlineKeyboardButton(
            text=_(key="back_to_main_menu_button"),
            callback_data="main_action:back_to_main",
        )
    )
    return builder.as_markup()


def get_payment_method_keyboard(
    months: int,
    price: float,
    tribute_url: Optional[str],
    stars_price: Optional[int],
    currency_symbol_val: str,
    lang: str,
    i18n_instance,
    settings: Settings,
) -> InlineKeyboardMarkup:
    _ = lambda key, **kwargs: i18n_instance.gettext(lang, key, **kwargs)
    builder = InlineKeyboardBuilder()
    if settings.STARS_ENABLED and stars_price is not None:
        builder.button(
            text=_("pay_with_stars_button"),
            callback_data=f"pay_stars:{months}:{stars_price}",
        )
    if settings.TRIBUTE_ENABLED and tribute_url:
        builder.button(text=_("pay_with_tribute_button"), url=tribute_url)
    if settings.YOOKASSA_ENABLED:
        builder.button(
            text=_("pay_with_yookassa_button"), callback_data=f"pay_yk:{months}:{price}"
        )
    if settings.CRYPTOPAY_ENABLED:
        builder.button(
            text=_("pay_with_cryptopay_button"),
            callback_data=f"pay_crypto:{months}:{price}",
        )
    builder.button(text=_(key="cancel_button"), callback_data="main_action:subscribe")
    builder.adjust(1)
    return builder.as_markup()


def get_payment_url_keyboard(
    payment_url: str, lang: str, i18n_instance
) -> InlineKeyboardMarkup:
    _ = lambda key, **kwargs: i18n_instance.gettext(lang, key, **kwargs)
    builder = InlineKeyboardBuilder()
    builder.button(text=_(key="pay_button"), url=payment_url)
    builder.button(
        text=_(key="back_to_main_menu_button"), callback_data="main_action:back_to_main"
    )
    builder.adjust(1)
    return builder.as_markup()


def get_referral_link_keyboard(lang: str, i18n_instance) -> InlineKeyboardMarkup:
    _ = lambda key, **kwargs: i18n_instance.gettext(lang, key, **kwargs)
    builder = InlineKeyboardBuilder()
    builder.button(
        text=_(key="back_to_main_menu_button"), callback_data="main_action:back_to_main"
    )
    return builder.as_markup()


def get_back_to_main_menu_markup(lang: str, i18n_instance) -> InlineKeyboardMarkup:
    _ = lambda key, **kwargs: i18n_instance.gettext(lang, key, **kwargs)
    builder = InlineKeyboardBuilder()
    builder.button(
        text=_(key="back_to_main_menu_button"), callback_data="main_action:back_to_main"
    )
    return builder.as_markup()


def get_subscribe_only_markup(lang: str, i18n_instance) -> InlineKeyboardMarkup:
    _ = lambda key, **kwargs: i18n_instance.gettext(lang, key, **kwargs)
    builder = InlineKeyboardBuilder()
    builder.button(
        text=_(key="menu_subscribe_inline"), callback_data="main_action:subscribe"
    )
    return builder.as_markup()


def get_user_banned_keyboard(
    support_link: Optional[str], lang: str, i18n_instance
) -> Optional[InlineKeyboardMarkup]:
    if not support_link:
        return None
    _ = lambda key, **kwargs: i18n_instance.gettext(lang, key, **kwargs)
    builder = InlineKeyboardBuilder()
    builder.button(text=_(key="menu_support_button"), url=support_link)
    return builder.as_markup()


def get_connect_and_main_keyboard(
    lang: str, i18n_instance, settings: Settings, config_link: Optional[str]
) -> InlineKeyboardMarkup:
    _ = lambda key, **kwargs: i18n_instance.gettext(lang, key, **kwargs)
    builder = InlineKeyboardBuilder()

    if settings.SUBSCRIPTION_MINI_APP_URL:
        builder.row(
            InlineKeyboardButton(
                text=_(key="menu_connect_button"),
                web_app=WebAppInfo(url=settings.SUBSCRIPTION_MINI_APP_URL),
            )
        )
    else:
        builder.row(
            InlineKeyboardButton(
                text=_("connect_button"),
                callback_data="main_action:my_subscription",
            )
        )

    builder.row(
        InlineKeyboardButton(
            text=_("back_to_main_menu_button"),
            callback_data="main_action:back_to_main",
        )
    )

    return builder.as_markup()


def get_payment_confirmation_markup(lang: str, i18n_instance) -> InlineKeyboardMarkup:
    _ = lambda key, **kwargs: i18n_instance.gettext(lang, key, **kwargs)
    builder = InlineKeyboardBuilder()
    builder.button(
        text=_(key="payment_confirmation_button"),
        callback_data="payment_action:confirm_paid",
    )
    return builder.as_markup()
