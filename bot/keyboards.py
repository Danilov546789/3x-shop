from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from core.config import settings


def main_menu_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🛒 Открыть магазин", web_app=WebAppInfo(url=settings.miniapp_url))],
        [InlineKeyboardButton(text="📊 Моя подписка", callback_data="status")],
    ]
    if settings.TRIAL_ENABLED:
        rows.append([InlineKeyboardButton(text="🎁 Пробный период", callback_data="trial")])
    rows.append([InlineKeyboardButton(text="📱 Какое приложение скачать", callback_data="apps")])
    rows.append([InlineKeyboardButton(text="🆘 Поддержка", callback_data="support")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def join_channel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📢 Подписаться на канал", url=settings.REQUIRED_CHANNEL_URL)],
            [InlineKeyboardButton(text="✅ Я подписался", callback_data="check_sub")],
        ]
    )


def apps_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📱 Happ (iOS / Android / macOS)", url=settings.APP_LINK_IOS)],
            [InlineKeyboardButton(text="🪟 v2rayN (Windows)", url=settings.APP_LINK_WINDOWS)],
            [InlineKeyboardButton(text="🐧 v2rayN (Linux, релизы)", url=settings.APP_LINK_LINUX)],
        ]
    )
